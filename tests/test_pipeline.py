"""End-to-end checks: generate a small dataset, clean it, and compare against ground truth."""
from __future__ import annotations
 
import json
import re
import sqlite3
 
import pandas as pd
import pytest
 
from scm.cleaning.clean import clean_all, normalize_item_id, parse_mixed_dates, to_number
from scm.data_gen.generate_all import generate
from scm.db import build_database
 
 
@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("scm")
    summary = generate(n_items=40, start="2025-11-01", end="2026-04-30", seed=7, data_dir=root)
    rep = clean_all(root / "raw", root / "processed", root / "reports")
    return root, summary, rep
 
 
def _truth(root, name):
    return pd.read_csv(root / "ground_truth" / f"{name}.csv")
 
 
def _clean(root, name):
    return pd.read_csv(root / "processed" / f"{name}.csv")
 
 
# ------------------------------------------------------------------ unit tests
def test_normalize_item_id():
    s = pd.Series(["PN-10023", "pn-10023 ", "PN10023", "garbage", None])
    out = normalize_item_id(s)
    assert list(out[:3]) == ["PN-10023"] * 3
    assert pd.isna(out[3]) and pd.isna(out[4])
 
 
def test_parse_mixed_dates():
    s = pd.Series(["2025-03-14", "14/03/2025", "14-Mar-2025", "20250314", "not a date"])
    out = parse_mixed_dates(s)
    assert (out[:4] == pd.Timestamp("2025-03-14")).all()
    assert pd.isna(out[4])
 
 
def test_to_number():
    s = pd.Series(["\u20b91,250.50", "Rs. 99", "1,200", "7"])
    assert list(to_number(s)) == [1250.5, 99.0, 1200.0, 7.0]
 
 
# ------------------------------------------------------------------ pipeline vs ground truth
def test_dedupe_matches_injected_counts(built):
    root, _, rep = built
    log = json.loads((root / "ground_truth" / "dirt_log.json").read_text())
    assert rep.tables["sales"]["rules"]["duplicate rows removed"] == log["sales_raw"]["duplicate_rows"]
    assert rep.tables["purchase_orders"]["rules"]["duplicate PO lines removed"] == log["purchase_orders_raw"]["duplicate_rows"]
    assert rep.tables["suppliers"]["rows_out"] == len(_truth(root, "suppliers"))
    assert rep.tables["items"]["rows_out"] == len(_truth(root, "items"))
 
 
def test_sales_rows_and_quantities_recovered(built):
    root, _, _ = built
    t, c = _truth(root, "sales"), _clean(root, "sales")
    assert abs(len(c) - len(t)) <= max(2, 0.001 * len(t))
    assert abs(c.dispatched_qty.sum() - t.dispatched_qty.sum()) / t.dispatched_qty.sum() < 0.02
    assert abs(c.schedule_qty.sum() - t.schedule_qty.sum()) / t.schedule_qty.sum() < 0.02
 
 
def test_sales_quality_rules(built):
    root, _, _ = built
    c = _clean(root, "sales")
    items = _clean(root, "items").set_index("item_id")
    assert c.item_id.str.match(r"^PN-\d{5}$").all()
    assert (c.dispatched_qty >= 0).all() and (c.schedule_qty >= 0).all()
    assert c.customer.notna().all()
    assert (c.uom.values == c.item_id.map(items.uom).values).all()
    # imputing a customer must not create (almost) any duplicate date/item/customer keys
    assert c.duplicated(["dispatch_date", "item_id", "customer"], keep=False).mean() < 0.001
 
 
def test_po_cleaning(built):
    root, _, rep = built
    log = json.loads((root / "ground_truth" / "dirt_log.json").read_text())
    c = _clean(root, "purchase_orders")
    q = rep.tables["purchase_orders"]["rules"]["quarantined: receipt date before PO date"]
    assert q == log["purchase_orders_raw"]["receipt_before_po_date"]
    assert len(c) == len(_truth(root, "purchase_orders")) - q
    assert c.supplier_id.str.match(r"^S\d{3}$").all()
    assert not c.duplicated(["po_number", "line_no"]).any()
    closed = c[c.status == "Closed"]
    assert (closed.actual_receipt_date >= closed.po_date).all()
    assert closed.received_qty.notna().all()
    assert set(c.status.unique()) <= {"Open", "Closed", "Short Closed"}
 
 
def test_inventory_and_suppliers(built):
    root, _, _ = built
    inv, sup = _clean(root, "inventory_snapshot"), _clean(root, "suppliers")
    assert not inv.duplicated(["snapshot_date", "item_id"]).any()
    assert (inv.on_hand_qty.dropna() >= 0).all()
    assert inv.location.str.match(r"^WH-[A-Z]/R\d+$").all()
    assert sup.supplier_id.is_unique and sup.lead_time_days.notna().all() and sup.payment_terms_days.notna().all()
    t = _truth(root, "suppliers").set_index("supplier_id")
    assert (sup.set_index("supplier_id").lead_time_days == t.contract_lead_time_days).all()
 
 
# ------------------------------------------------------------------ documents and database
def test_documents_and_manifest(built):
    root, summary, _ = built
    man = pd.read_csv(root / "docs" / "doc_manifest.csv")
    assert {"contract", "amendment", "sop", "email"} <= set(man.doc_type)
    assert all((root / "docs" / p).exists() for p in man.file_path)
    assert set(man.format) == {"docx", "pdf", "txt"}
    amd = man[man.doc_type == "amendment"]
    assert len(amd) == len(summary["amended_suppliers"]) and (amd.supersedes.str.startswith("CON-")).all()
    qa = pd.read_csv(root / "eval" / "golden_qa_seed.csv")
    assert len(qa) >= 4 * len(_truth(root, "suppliers"))
    assert re.search(r"\d", qa.expected_answer.iloc[0])
 
 
def test_sqlite_build(built):
    root, _, _ = built
    db = build_database(root / "processed")
    with sqlite3.connect(db) as con:
        n = con.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert n > 0 and {"suppliers", "items", "sales", "purchase_orders", "inventory_snapshot", "reorder_policy", "approvals_log"} <= tables
