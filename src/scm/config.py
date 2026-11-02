"""Central configuration: paths, dates and business rules shared by every phase.
 
Business rules live here (not inside agent prompts) so that the data generator,
the SOP documents, the tools and the tests all agree on the same numbers.
"""
from __future__ import annotations
 
import os
from pathlib import Path
 
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"                # dirty files, as an ERP export would look
DOCS_DIR = DATA_DIR / "docs"              # unstructured documents for RAG
TRUTH_DIR = DATA_DIR / "ground_truth"     # clean copies, used ONLY for tests/validation
PROCESSED_DIR = DATA_DIR / "processed"    # cleaned data used by the application
EVAL_DIR = DATA_DIR / "eval"              # seed questions for RAG evaluation
REPORTS_DIR = ROOT / "reports"
DB_PATH = PROCESSED_DIR / "scm.db"
 
SEED = int(os.getenv("SCM_SEED", "42"))
N_ITEMS = int(os.getenv("SCM_N_ITEMS", "300"))
START_DATE = "2024-11-01"
END_DATE = "2026-10-31"
 
COMPANY = "Sahyadri Auto Components Pvt Ltd"
PLANT_ADDRESS = "Plot 114, MIDC Phase II, Chakan, Pune 410501, Maharashtra"
 
# ---- Business rules (used by SOP documents, tools and agents) -------------
ABC_CUTOFFS = (0.80, 0.95)                      # cumulative value share: A<=80%, B<=95%, C rest
SERVICE_LEVELS = {"A": 0.98, "B": 0.95, "C": 0.90}
REVIEW_FREQUENCY = {"A": "monthly", "B": "quarterly", "C": "annually"}
 
# (upper limit of PO value in INR, approver role)
PO_APPROVAL_MATRIX = [(100_000, "Buyer"), (500_000, "Purchase Manager"), (float("inf"), "Plant Head")]
# Who approves a change to reorder point / safety stock, by ABC class
REORDER_CHANGE_APPROVER = {"A": "Purchase Manager", "B": "Buyer", "C": "Buyer"}
REORDER_CHANGE_ESCALATION_PCT = 0.30            # change above 30% -> Plant Head
PREMIUM_FREIGHT_LIMIT_INR = 25_000              # above this -> Plant Head
 
OEM_CUSTOMERS = [
    "Deccan Motors Ltd",
    "Konkan Two-Wheelers Ltd",
    "Malwa Commercial Vehicles Ltd",
    "Satpura Tractors Pvt Ltd",
]
 
# Approximate plant shutdown windows (festival / year-end). Realistic, not exact.
SHUTDOWNS = [
    ("2024-11-01", "2024-11-03"), ("2024-12-25", "2024-12-31"),
    ("2025-03-31", "2025-03-31"), ("2025-08-27", "2025-08-29"),
    ("2025-10-20", "2025-10-24"), ("2025-12-25", "2025-12-31"),
    ("2026-03-31", "2026-03-31"), ("2026-09-14", "2026-09-16"),
]
 
 
def inr(x: float) -> str:
    """Format a number with Indian digit grouping, e.g. 1234567 -> '12,34,567'."""
    s = str(int(round(x)))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])
 
 
def fy_label(ts) -> str:
    """Indian financial year label (April-March), e.g. 2025-06-01 -> '25-26'."""
    y = ts.year if ts.month >= 4 else ts.year - 1
    return f"{y % 100:02d}-{(y + 1) % 100:02d}"