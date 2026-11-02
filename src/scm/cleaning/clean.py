"""Data cleaning pipeline: dirty ERP exports (data/raw) -> trusted tables (data/processed).
 
Principles
----------
1. Never silently fix: every rule counts the rows it touches (reports/data_quality_report.md).
2. Prefer *quarantine* (save the bad row aside) over guessing when a row cannot be repaired safely.
3. Where we do impute, we say how, and add a boolean flag column (e.g. ``dispatched_imputed``).
4. Order matters: masters first (they validate everything else), then transactions.
 
Assumptions (documented in the data-quality report)
---------------------------------------------------
* Slash dates are day/month/year (Indian convention), never month/day.
* A negative dispatched quantity with no return flag is a sign-entry error, so we take the absolute value.
* A missing dispatched quantity is imputed with the OEM schedule quantity (assume full shipment).
"""
from __future__ import annotations
 
import argparse
import difflib
import json
import re
from pathlib import Path
 
import numpy as np
import pandas as pd
 
from scm import config as C
 
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%Y%m%d"]
UOM_CANON = {"nos": "NOS", "pcs": "NOS", "ea": "NOS", "each": "NOS", "kg": "KG", "kgs": "KG", "g": "G", "gm": "G", "mt": "MT",
             "l": "LTR", "ltr": "LTR", "litre": "LTR", "ml": "ML"}
UOM_FACTOR = {("G", "KG"): 0.001, ("MT", "KG"): 1000.0, ("ML", "LTR"): 0.001}
CUSTOMER_KEYS = {"deccan": "Deccan Motors Ltd", "konkan": "Konkan Two-Wheelers Ltd", "malwa": "Malwa Commercial Vehicles Ltd", "satpura": "Satpura Tractors Pvt Ltd"}
CITY_CANON = {"pcmc": "Pimpri-Chinchwad", "pimpri chinchwad": "Pimpri-Chinchwad", "pimpri-chinchwad": "Pimpri-Chinchwad",
              "bhosari midc": "Bhosari (MIDC)", "bhosari": "Bhosari (MIDC)", "bhosari (midc)": "Bhosari (MIDC)"}
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\dZ\d$")
 
 
class DQReport:
    """Collects how many rows each cleaning rule touched."""
 
    def __init__(self) -> None:
        self.tables: dict[str, dict] = {}
 
    def start(self, table: str, rows_in: int) -> None:
        self.tables[table] = {"rows_in": int(rows_in), "rows_out": None, "rules": {}}
 
    def rule(self, table: str, name: str, n: int) -> None:
        self.tables[table]["rules"][name] = int(n)
 
    def finish(self, table: str, rows_out: int) -> None:
        self.tables[table]["rows_out"] = int(rows_out)
 
    def to_markdown(self) -> str:
        lines = ["# Data quality report", "", "Rows touched by each cleaning rule. Quarantined rows are saved under `data/processed/quarantine/`.", ""]
        for t, d in self.tables.items():
            lines += [f"## {t}", f"Rows in: **{d['rows_in']:,}** | rows out: **{d['rows_out']:,}**", "", "| Rule | Rows affected |", "|---|---:|"]
            lines += [f"| {k} | {v:,} |" for k, v in d["rules"].items()] + [""]
        return "\n".join(lines)
 
 
# ----------------------------------------------------------------------------- helpers
def as_str(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip()
 
 
def normalize_item_id(s: pd.Series) -> pd.Series:
    """'pn-10023 ' / 'PN10023' / 'PN-10023' -> 'PN-10023'; anything else -> <NA>."""
    t = as_str(s).str.upper().str.replace(r"\s+", "", regex=True)
    return "PN-" + t.str.extract(r"^PN-?(\d{5})$")[0]
 
 
def parse_mixed_dates(s: pd.Series) -> pd.Series:
    """Try each known format in turn; unparseable values become NaT."""
    t = as_str(s)
    result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        result = result.fillna(pd.to_datetime(t, format=fmt, errors="coerce", exact=True).astype("datetime64[ns]"))
    return result
 
 
def to_number(s: pd.Series) -> pd.Series:
    t = as_str(s).str.replace(r"[\u20b9,]|Rs\.?|INR", "", regex=True).str.strip()
    return pd.to_numeric(t, errors="coerce")
 
 
def canon_uom(s: pd.Series) -> pd.Series:
    return as_str(s).str.lower().map(UOM_CANON).astype("string")
 
 
def _dedupe(df: pd.DataFrame, subset: list[str]) -> tuple[pd.DataFrame, int]:
    out = df.drop_duplicates(subset=subset, keep="first")
    return out, len(df) - len(out)
 
 
def _quarantine(qdir: Path, name: str, df: pd.DataFrame, reason: str) -> None:
    if len(df):
        qdir.mkdir(parents=True, exist_ok=True)
        df.assign(quarantine_reason=reason).to_csv(qdir / f"{name}.csv", index=False)
 
 
def _read(raw_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(raw_dir / f"{name}.csv", dtype=str, encoding="utf-8-sig", keep_default_na=True)
 
 
# ----------------------------------------------------------------------------- masters
def clean_suppliers(raw: pd.DataFrame, rep: DQReport) -> pd.DataFrame:
    rep.start("suppliers", len(raw))
    df = raw.copy()
    df["_filled"] = df.notna().sum(axis=1)
    df = df.sort_values(["supplier_id", "_filled"], ascending=[True, False])
    df, n = _dedupe(df, ["supplier_id"])
    rep.rule("suppliers", "duplicate supplier records removed (kept most complete)", n)
    df = df.drop(columns="_filled").sort_values("supplier_id").reset_index(drop=True)
 
    def days(v) -> float:
        if pd.isna(v):
            return np.nan
        m = re.search(r"(\d+(?:\.\d+)?)\s*(week|wk)?", str(v).lower())
        return float(m.group(1)) * (7 if m and m.group(2) else 1) if m else np.nan
 
    df["lead_time_days"] = df["lead_time"].map(days)
    df["payment_terms_days"] = df["payment_terms"].map(days)
    rep.rule("suppliers", "lead time text ('3 weeks', '21') -> days", int(df.lead_time.astype(str).str.contains("week|^\\d+$", regex=True).sum()))
    rep.rule("suppliers", "payment terms text ('Net 45') -> days", int(df.payment_terms.astype(str).str.contains("Net|days").sum()))
    df = df.drop(columns=["lead_time", "payment_terms"])
    before = df.city.copy()
    df["city"] = df.city.map(lambda c: CITY_CANON.get(str(c).strip().lower(), c))
    rep.rule("suppliers", "city spelling standardised", int((before != df.city).sum()))
    df["gstin_valid"] = df.gstin.fillna("").map(lambda g: bool(GSTIN_RE.match(g)))
    rep.rule("suppliers", "GSTIN failed format check (flagged, not deleted)", int((~df.gstin_valid).sum()))
    rep.rule("suppliers", "contact e-mail missing (left blank)", int(df.contact_email.isna().sum()))
    rep.finish("suppliers", len(df))
    return df
 
 
def clean_items(raw: pd.DataFrame, suppliers: pd.DataFrame, rep: DQReport, qdir: Path) -> pd.DataFrame:
    rep.start("items", len(raw))
    df = raw.copy()
    df["item_id"] = normalize_item_id(df.item_id)
    bad = df.item_id.isna()
    _quarantine(qdir, "items_bad_id", df[bad], "invalid item_id")
    df = df[~bad]
    df, n = _dedupe(df, ["item_id"])
    rep.rule("items", "duplicate item rows removed", n)
    df["unit_cost_inr"] = to_number(df.unit_cost_inr)
    rep.rule("items", "unit cost text ('Rs. 1,250.00') -> number", int(as_str(raw.unit_cost_inr).str.contains(r"[\u20b9,]|Rs", regex=True).sum()))
    before = df.uom.copy()
    df["uom"] = canon_uom(df.uom)
    rep.rule("items", "UoM spelling standardised", int((before.astype("string") != df.uom).sum()))
    cat = suppliers.set_index("supplier_id").category
    miss = df.category.isna()
    df.loc[miss, "category"] = df.loc[miss, "supplier_id"].map(cat)
    rep.rule("items", "missing category filled from supplier category", int(miss.sum()))
    for c in ["moq", "pack_size", "planned_lead_time_days"]:
        df[c] = to_number(df[c]).astype("Int64")
    orphan = ~df.supplier_id.isin(suppliers.supplier_id)
    rep.rule("items", "items with unknown supplier (should be 0)", int(orphan.sum()))
    df = df.sort_values("item_id").reset_index(drop=True)
    rep.finish("items", len(df))
    return df
 
 
# ----------------------------------------------------------------------------- transactions
def clean_sales(raw: pd.DataFrame, items: pd.DataFrame, rep: DQReport, qdir: Path) -> pd.DataFrame:
    rep.start("sales", len(raw))
    df = raw.copy()
    df["item_id"] = normalize_item_id(df.item_id)
    rep.rule("sales", "item_id re-formatted (case/space/hyphen)", int((as_str(raw.item_id) != df.item_id).sum()))
    bad = df.item_id.isna() | ~df.item_id.isin(items.item_id)
    _quarantine(qdir, "sales_unknown_item", df[bad], "item_id not in item master")
    rep.rule("sales", "quarantined: unknown item_id", int(bad.sum()))
    df = df[~bad].copy()
 
    df["dispatch_date"] = parse_mixed_dates(df.dispatch_date)
    bad = df.dispatch_date.isna()
    _quarantine(qdir, "sales_bad_date", df[bad], "unparseable date")
    rep.rule("sales", "quarantined: unparseable date", int(bad.sum()))
    df = df[~bad].copy()
 
    def canon_cust(v):
        if pd.isna(v):
            return pd.NA
        low = str(v).lower()
        return next((c for k, c in CUSTOMER_KEYS.items() if k in low), pd.NA)
 
    raw_c = df.customer.copy()
    df["customer"] = df.customer.map(canon_cust).astype("string")
    rep.rule("sales", "customer name standardised", int(((raw_c != df.customer) & raw_c.notna()).sum()))
    df["schedule_qty"] = to_number(df.schedule_qty)
    df["dispatched_qty"] = to_number(df.dispatched_qty)
 
    base = items.set_index("item_id").uom
    df["uom"] = canon_uom(df.uom)
    miss = df.uom.isna()
    df.loc[miss, "uom"] = df.loc[miss, "item_id"].map(base)
    rep.rule("sales", "missing UoM filled from item master", int(miss.sum()))
    df["_base"] = df.item_id.map(base)
    conv = 0
    for (frm, to), f in UOM_FACTOR.items():
        m = (df.uom == frm) & (df._base == to)
        df.loc[m, ["schedule_qty", "dispatched_qty"]] = df.loc[m, ["schedule_qty", "dispatched_qty"]] * f
        df.loc[m, "uom"] = to
        conv += int(m.sum())
    rep.rule("sales", "quantities converted to item base UoM (g/MT -> kg, ml -> litre)", conv)
    rep.rule("sales", "UoM still different from base after conversion (should be 0)", int((df.uom != df._base).sum()))
    df = df.drop(columns="_base")
 
    df, n = _dedupe(df, ["dispatch_date", "item_id", "customer", "invoice_no", "schedule_qty", "dispatched_qty"])
    rep.rule("sales", "duplicate rows removed", n)
 
    neg = df.dispatched_qty < 0
    df.loc[neg, "dispatched_qty"] = df.loc[neg, "dispatched_qty"].abs()
    rep.rule("sales", "negative dispatched qty -> absolute value (sign error)", int(neg.sum()))
 
    df = df.sort_values(["item_id", "dispatch_date", "customer"], na_position="last").reset_index(drop=True)
    g = df.groupby("item_id")["schedule_qty"]
    med = g.transform("median")
    mad = (df.schedule_qty - med).abs().groupby(df.item_id).transform("median")
    out = (df.schedule_qty > med + 12 * 1.4826 * np.maximum(mad, 1)) & (df.schedule_qty > 5 * med)
    smooth = df.schedule_qty.where(~out).groupby(df.item_id).transform(lambda x: x.rolling(7, center=True, min_periods=1).median())
    df["schedule_imputed"] = out
    df.loc[out, "schedule_qty"] = smooth[out].round()
    rep.rule("sales", "outlier schedule qty replaced by 7-row rolling median", int(out.sum()))
 
    miss = df.dispatched_qty.isna()
    df["dispatched_imputed"] = miss
    df.loc[miss, "dispatched_qty"] = df.loc[miss, "schedule_qty"]
    rep.rule("sales", "missing dispatched qty := schedule qty (assume full shipment)", int(miss.sum()))
 
    # Missing customer: pick the item's most frequent customer that is NOT already on the same date/item
    # (otherwise a two-customer item would get two identical keys).
    known = df.dropna(subset=["customer"])
    ranked = known.groupby("item_id").customer.agg(lambda x: x.value_counts().index.tolist()).to_dict()
    taken = known.groupby(["dispatch_date", "item_id"]).customer.agg(set).to_dict()
    miss = df.customer.isna()
    df["customer_imputed"] = miss
    for idx in df.index[miss]:
        key = (df.at[idx, "dispatch_date"], df.at[idx, "item_id"])
        cands = ranked.get(key[1], [])
        choice = next((c for c in cands if c not in taken.get(key, set())), cands[0] if cands else pd.NA)
        df.at[idx, "customer"] = choice
        taken.setdefault(key, set()).add(choice)
    rep.rule("sales", "missing customer := item's most frequent customer not already on that date", int(miss.sum()))
    df[["schedule_qty", "dispatched_qty"]] = df[["schedule_qty", "dispatched_qty"]].round(3)
    rep.finish("sales", len(df))
    return df
 
 
def _supplier_resolver(suppliers: pd.DataFrame):
    def norm(x: str) -> str:
        x = re.sub(r"[^a-z0-9 ]", "", str(x).lower().replace("private limited", "pvt ltd"))
        return re.sub(r"\s+", " ", x).strip()
    lookup = {norm(n): i for n, i in zip(suppliers.supplier_name, suppliers.supplier_id)}
    ids = set(suppliers.supplier_id)
 
    def resolve(v):
        if pd.isna(v):
            return pd.NA
        v = str(v).strip()
        if v in ids:
            return v
        k = norm(v)
        if k in lookup:
            return lookup[k]
        close = difflib.get_close_matches(k, list(lookup), n=1, cutoff=0.9)
        return lookup[close[0]] if close else pd.NA
    return resolve
 
 
def clean_pos(raw: pd.DataFrame, suppliers: pd.DataFrame, items: pd.DataFrame, rep: DQReport, qdir: Path) -> pd.DataFrame:
    rep.start("purchase_orders", len(raw))
    df = raw.copy()
    df["item_id"] = normalize_item_id(df.item_id)
    bad = df.item_id.isna() | ~df.item_id.isin(items.item_id)
    _quarantine(qdir, "po_unknown_item", df[bad], "item_id not in item master")
    rep.rule("purchase_orders", "quarantined: unknown item_id", int(bad.sum()))
    df = df[~bad].copy()
 
    resolve = _supplier_resolver(suppliers)
    by_name = ~df.supplier.fillna("").str.match(r"^S\d{3}$")
    df["supplier_id"] = df.supplier.map(resolve).astype("string")
    rep.rule("purchase_orders", "supplier name mapped to supplier_id", int(by_name.sum()))
    bad = df.supplier_id.isna()
    _quarantine(qdir, "po_unknown_supplier", df[bad], "supplier not found")
    rep.rule("purchase_orders", "quarantined: unknown supplier", int(bad.sum()))
    df = df[~bad].drop(columns="supplier")
 
    for c in ["po_date", "promised_date", "actual_receipt_date"]:
        df[c] = parse_mixed_dates(df[c])
    for c in ["order_qty", "unit_price", "received_qty", "rejected_qty", "line_no", "payment_terms_days"]:
        df[c] = to_number(df[c])
    rep.rule("purchase_orders", "price/quantity text ('Rs. 1,250.00', '1,200') -> number", int(as_str(raw.unit_price).str.contains(r"[\u20b9,]|Rs", regex=True).sum() + as_str(raw.order_qty).str.contains(",", regex=False).sum()))
    df["status"] = as_str(df.status).str.lower().map({"closed": "Closed", "open": "Open", "short closed": "Short Closed"}).astype("string")
    df, n = _dedupe(df, ["po_number", "line_no"])
    rep.rule("purchase_orders", "duplicate PO lines removed", n)
 
    badrec = (df.status == "Closed") & (df.actual_receipt_date < df.po_date)
    _quarantine(qdir, "po_receipt_before_po_date", df[badrec], "receipt date earlier than PO date")
    rep.rule("purchase_orders", "quarantined: receipt date before PO date", int(badrec.sum()))
    df = df[~badrec].copy()
 
    miss = (df.status == "Closed") & df.received_qty.isna()
    df["received_imputed"] = miss
    df.loc[miss, "received_qty"] = df.loc[miss, "order_qty"]
    rep.rule("purchase_orders", "missing received qty on closed PO := order qty", int(miss.sum()))
 
    df["po_value_inr"] = (df.order_qty * df.unit_price).round(2)
    df["lead_time_days"] = (df.actual_receipt_date - df.po_date).dt.days
    df["delay_days"] = (df.actual_receipt_date - df.promised_date).dt.days
    df = df.sort_values(["po_date", "po_number", "line_no"]).reset_index(drop=True)
    rep.finish("purchase_orders", len(df))
    return df
 
 
def clean_inventory(raw: pd.DataFrame, items: pd.DataFrame, rep: DQReport, qdir: Path) -> pd.DataFrame:
    rep.start("inventory_snapshot", len(raw))
    df = raw.copy()
    df["item_id"] = normalize_item_id(df.item_id)
    bad = df.item_id.isna() | ~df.item_id.isin(items.item_id)
    _quarantine(qdir, "inventory_unknown_item", df[bad], "item_id not in item master")
    df = df[~bad].copy()
    df["snapshot_date"] = parse_mixed_dates(df.snapshot_date)
    df["on_hand_qty"] = to_number(df.on_hand_qty)
    df["on_order_qty"] = to_number(df.on_order_qty)
    df, n = _dedupe(df, ["snapshot_date", "item_id"])
    rep.rule("inventory_snapshot", "duplicate snapshot rows removed", n)
    pat = r"WH\s*([A-Z])\s*[-/ ]*\s*R(\d+)"
    fixed = as_str(df.location).str.replace(pat, r"WH-\1/R\2", regex=True)
    rep.rule("inventory_snapshot", "location format standardised", int((fixed != as_str(df.location)).sum()))
    df["location"] = fixed
    df = df.sort_values(["item_id", "snapshot_date"]).reset_index(drop=True)
    neg = df.on_hand_qty < 0
    df.loc[neg, "on_hand_qty"] = np.nan
    rep.rule("inventory_snapshot", "negative on-hand treated as missing", int(neg.sum()))
    miss = df.on_hand_qty.isna()
    df["on_hand_imputed"] = miss
    df["on_hand_qty"] = df.groupby("item_id")["on_hand_qty"].transform(lambda x: x.ffill(limit=3).bfill(limit=3))
    rep.rule("inventory_snapshot", "missing on-hand filled with neighbouring day (max 3 days)", int(miss.sum()))
    rep.rule("inventory_snapshot", "still missing after fill (kept as blank)", int(df.on_hand_qty.isna().sum()))
    rep.finish("inventory_snapshot", len(df))
    return df
 
 
def clean_policy(raw: pd.DataFrame, items: pd.DataFrame, rep: DQReport) -> pd.DataFrame:
    rep.start("reorder_policy", len(raw))
    df = raw.copy()
    df["item_id"] = normalize_item_id(df.item_id)
    df["last_reviewed_date"] = parse_mixed_dates(df.last_reviewed_date)
    for c in ["reorder_point", "safety_stock", "order_qty"]:
        df[c] = to_number(df[c])
    rep.rule("reorder_policy", "safety stock missing (will be recomputed in Phase 4)", int(df.safety_stock.isna().sum()))
    rep.rule("reorder_policy", "policy last reviewed more than 180 days before 2026-10-31", int((df.last_reviewed_date < pd.Timestamp(C.END_DATE) - pd.Timedelta(days=180)).sum()))
    rep.finish("reorder_policy", len(df))
    return df
 
 
# ----------------------------------------------------------------------------- orchestration
def clean_all(raw_dir: Path = C.RAW_DIR, out_dir: Path = C.PROCESSED_DIR, reports_dir: Path = C.REPORTS_DIR) -> DQReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    qdir = out_dir / "quarantine"
    rep = DQReport()
    suppliers = clean_suppliers(_read(raw_dir, "suppliers_raw"), rep)
    items = clean_items(_read(raw_dir, "items_raw"), suppliers, rep, qdir)
    tables = {
        "suppliers": suppliers, "items": items,
        "sales": clean_sales(_read(raw_dir, "sales_raw"), items, rep, qdir),
        "purchase_orders": clean_pos(_read(raw_dir, "purchase_orders_raw"), suppliers, items, rep, qdir),
        "inventory_snapshot": clean_inventory(_read(raw_dir, "inventory_snapshot_raw"), items, rep, qdir),
        "reorder_policy": clean_policy(_read(raw_dir, "reorder_policy_raw"), items, rep),
    }
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    (reports_dir / "data_quality_report.md").write_text(rep.to_markdown(), encoding="utf-8")
    (reports_dir / "data_quality_report.json").write_text(json.dumps(rep.tables, indent=2), encoding="utf-8")
    return rep
 
 
def main() -> None:
    from scm.db import build_database
 
    ap = argparse.ArgumentParser(description="Clean raw SCM exports and build the SQLite database")
    ap.add_argument("--no-db", action="store_true")
    a = ap.parse_args()
    rep = clean_all()
    print(rep.to_markdown())
    if not a.no_db:
        print("SQLite database:", build_database())
 
 
if __name__ == "__main__":
    main()
