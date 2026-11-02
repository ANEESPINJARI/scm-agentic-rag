"""One command to regenerate every dataset and document.
 
    python -m scm.data_gen.generate_all                # defaults (300 items, 24 months)
    python -m scm.data_gen.generate_all --items 60 --start 2025-11-01 --end 2026-10-31 --out ./tmp_data
"""
from __future__ import annotations
 
import argparse
import json
from pathlib import Path
 
import numpy as np
import pandas as pd
 
from scm import config as C
from scm.data_gen import dirty
from scm.data_gen.documents import generate_documents
from scm.data_gen.master_data import make_items, make_suppliers
from scm.data_gen.simulate import build_calendar, simulate
 
 
def _csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # BOM so Excel shows the rupee sign correctly
 
 
def generate(n_items: int = C.N_ITEMS, start: str = C.START_DATE, end: str = C.END_DATE, seed: int = C.SEED,
             data_dir: Path = C.DATA_DIR, make_docs: bool = True) -> dict:
    rng = np.random.default_rng(seed)
    raw, truth, docs, evald = data_dir / "raw", data_dir / "ground_truth", data_dir / "docs", data_dir / "eval"
 
    suppliers, sim = make_suppliers(rng)
    items = make_items(rng, suppliers, n_items)
    dates, work = build_calendar(start, end)
    out = simulate(items, suppliers, sim, dates, work, rng)
 
    # ---- ground truth (clean) -------------------------------------------------
    _csv(suppliers, truth / "suppliers.csv")
    _csv(sim, truth / "supplier_sim_params.csv")
    _csv(items, truth / "items.csv")
    for name, df in out.items():
        _csv(df, truth / f"{name}.csv")
 
    # ---- documents (also decide which suppliers got a contract amendment) -----
    doc_info = {"amended": [], "n_docs": 0, "n_qa": 0}
    if make_docs:
        doc_info = generate_documents(suppliers, items, out["purchase_orders"], rng, docs, evald)
 
    # ---- dirty raw exports --------------------------------------------------------
    log: dict = {}
    for name, (df, lg) in {
        "sales_raw": dirty.dirty_sales(out["sales"], rng),
        "purchase_orders_raw": dirty.dirty_pos(out["purchase_orders"], suppliers, rng),
        "inventory_snapshot_raw": dirty.dirty_inventory(out["inventory_snapshot"], rng),
        "suppliers_raw": dirty.dirty_suppliers(suppliers, rng, doc_info["amended"]),
        "items_raw": dirty.dirty_items(items, rng),
        "reorder_policy_raw": dirty.dirty_policy(out["reorder_policy"], rng),
    }.items():
        _csv(df, raw / f"{name}.csv")
        log[name] = lg
    (truth / "dirt_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
 
    summary = dict(suppliers=len(suppliers), items=len(items), sales_rows=len(out["sales"]), po_lines=len(out["purchase_orders"]),
                   inventory_rows=len(out["inventory_snapshot"]), documents=doc_info["n_docs"], golden_qa=doc_info["n_qa"], amended_suppliers=doc_info["amended"])
    return summary
 
 
def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic SCM data and documents")
    ap.add_argument("--items", type=int, default=C.N_ITEMS)
    ap.add_argument("--start", default=C.START_DATE)
    ap.add_argument("--end", default=C.END_DATE)
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--out", type=Path, default=C.DATA_DIR)
    ap.add_argument("--skip-docs", action="store_true")
    a = ap.parse_args()
    print(json.dumps(generate(a.items, a.start, a.end, a.seed, a.out, not a.skip_docs), indent=2))
 
 
if __name__ == "__main__":
    main()
