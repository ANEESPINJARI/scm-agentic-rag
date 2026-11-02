"""Load the cleaned CSVs into one SQLite file that the agent tools will query (Phase 4+)."""
from __future__ import annotations
 
import sqlite3
from pathlib import Path
 
import pandas as pd
 
from scm import config as C
 
TABLES = ["suppliers", "items", "sales", "purchase_orders", "inventory_snapshot", "reorder_policy"]
INDEXES = {
    "sales": ["item_id", "dispatch_date"], "purchase_orders": ["item_id", "supplier_id", "po_number"],
    "inventory_snapshot": ["item_id", "snapshot_date"], "items": ["supplier_id"], "reorder_policy": ["item_id"],
}
 
 
def build_database(processed_dir: Path = C.PROCESSED_DIR, db_path: Path | None = None) -> Path:
    db_path = db_path or processed_dir / "scm.db"
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as con:
        for t in TABLES:
            df = pd.read_csv(processed_dir / f"{t}.csv")
            df.to_sql(t, con, index=False)
            for col in INDEXES.get(t, []):
                con.execute(f"CREATE INDEX idx_{t}_{col} ON {t}({col})")
        con.execute("CREATE TABLE IF NOT EXISTS approvals_log (id INTEGER PRIMARY KEY, created_at TEXT, kind TEXT, payload TEXT, approver_role TEXT, status TEXT)")
    return db_path
