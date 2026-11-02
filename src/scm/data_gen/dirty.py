"""Turn clean 'ground truth' tables into realistic dirty ERP exports.
 
Every defect we inject is counted in a dirt log (data/ground_truth/dirt_log.json) so that
the cleaning step can be *verified*, not just trusted.
"""
from __future__ import annotations
 
import numpy as np
import pandas as pd
 
from scm.config import OEM_CUSTOMERS
 
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%Y%m%d"]
DATE_WEIGHTS = [0.60, 0.20, 0.15, 0.05]
UOM_VARIANTS = {"NOS": ["Nos", "PCS", "pcs", "EA", "nos"], "KG": ["Kg", "kgs", "KGS", "kg"], "LTR": ["L", "Ltr", "ltr", "Litre"]}
CUSTOMER_VARIANTS = {
    "Deccan Motors Ltd": ["DECCAN MOTORS LTD", "Deccan Motors", "Deccan Motors Limited", "Deccan Motors Ltd."],
    "Konkan Two-Wheelers Ltd": ["Konkan Two Wheelers", "KONKAN 2W LTD", "Konkan Two-Wheelers Limited"],
    "Malwa Commercial Vehicles Ltd": ["Malwa CV Ltd", "MALWA COMMERCIAL VEHICLES", "Malwa Commercial Vehicles Limited"],
    "Satpura Tractors Pvt Ltd": ["Satpura Tractors", "SATPURA TRACTORS PVT. LTD.", "Satpura Tractors Private Limited"],
}
 
 
def _mask(rng: np.random.Generator, n: int, frac: float) -> np.ndarray:
    return rng.random(n) < frac
 
 
def messy_dates(s: pd.Series, rng: np.random.Generator) -> pd.Series:
    """Format a datetime Series as strings using a random mix of formats (NaT stays blank)."""
    out = pd.Series([None] * len(s), index=s.index, dtype=object)
    pick = rng.choice(len(DATE_FORMATS), size=len(s), p=DATE_WEIGHTS)
    valid = s.notna().to_numpy()
    for k, fmt in enumerate(DATE_FORMATS):
        m = (pick == k) & valid
        out[m] = s[m].dt.strftime(fmt)
    return out
 
 
def messy_item_id(s: pd.Series, rng: np.random.Generator, log: dict) -> pd.Series:
    out = s.astype(object).copy()
    n = len(out)
    for name, frac, fn in [("item_id_lowercase", 0.05, str.lower), ("item_id_trailing_space", 0.03, lambda v: v + " "),
                           ("item_id_missing_hyphen", 0.02, lambda v: v.replace("-", ""))]:
        m = _mask(rng, n, frac)
        out[m] = out[m].map(fn)
        log[name] = int(m.sum())
    return out
 
 
def add_duplicates(df: pd.DataFrame, rng: np.random.Generator, frac: float) -> tuple[pd.DataFrame, int]:
    """Re-insert copies of some rows right after the original (as a double export would)."""
    df = df.reset_index(drop=True)
    dup = df[_mask(rng, len(df), frac)]
    out = pd.concat([df, dup]).sort_index(kind="stable").reset_index(drop=True)
    return out, len(dup)
 
 
def _money_str(v: float, rng: np.random.Generator) -> str:
    style = rng.integers(0, 3)
    return [f"\u20b9{v:,.2f}", f"Rs. {v:,.2f}", f"{v:,.2f}"][style]
 
 
# ----------------------------------------------------------------------------- sales
def dirty_sales(truth: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    log: dict = {}
    df = truth.copy().reset_index(drop=True)
    n = len(df)
    df["schedule_qty"] = df.schedule_qty.astype(float)
    df["dispatched_qty"] = df.dispatched_qty.astype(float)
 
    # outliers: a keying error multiplies the schedule by 100 (only where it is large enough to matter)
    m = _mask(rng, n, 0.001) & (df.schedule_qty >= 3)
    df.loc[m, "schedule_qty"] *= 100
    log["schedule_qty_x100_outlier"] = int(m.sum())
 
    # unit-of-measure problems: genuine conversions needed for KG and LTR items
    uom_log = 0
    for base, alt, factor in [("KG", "G", 1000), ("KG", "MT", 0.001), ("LTR", "ML", 1000)]:
        m = (df.uom == base) & _mask(rng, n, 0.015)
        df.loc[m, ["schedule_qty", "dispatched_qty"]] *= factor
        df.loc[m, "uom"] = alt
        uom_log += int(m.sum())
    log["uom_needing_conversion"] = uom_log
    # cosmetic UoM spelling variants
    m = _mask(rng, n, 0.08)
    df.loc[m, "uom"] = [rng.choice(UOM_VARIANTS[u]) if u in UOM_VARIANTS else u for u in df.loc[m, "uom"]]
    log["uom_spelling_variant"] = int(m.sum())
 
    # customers: spelling variants and blanks
    m = _mask(rng, n, 0.20)
    df.loc[m, "customer"] = [rng.choice(CUSTOMER_VARIANTS[c]) for c in df.loc[m, "customer"]]
    log["customer_variant"] = int(m.sum())
    m = _mask(rng, n, 0.005)
    df.loc[m, "customer"] = None
    log["customer_missing"] = int(m.sum())
 
    # missing / negative dispatched quantity
    m = _mask(rng, n, 0.01)
    df.loc[m, "dispatched_qty"] = np.nan
    log["dispatched_qty_missing"] = int(m.sum())
    m = _mask(rng, n, 0.002) & (df.dispatched_qty > 0)
    df.loc[m, "dispatched_qty"] *= -1
    log["dispatched_qty_negative"] = int(m.sum())
    m = _mask(rng, n, 0.01)
    df.loc[m, "uom"] = None
    log["uom_missing"] = int(m.sum())
 
    df["item_id"] = messy_item_id(df.item_id, rng, log)
    df["dispatch_date"] = messy_dates(df.dispatch_date, rng)
    df, nd = add_duplicates(df, rng, 0.015)
    log["duplicate_rows"] = nd
    return df, log
 
 
# ----------------------------------------------------------------------------- purchase orders
def dirty_pos(truth: pd.DataFrame, suppliers: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    log: dict = {}
    df = truth.copy().reset_index(drop=True)
    n = len(df)
    names = suppliers.set_index("supplier_id").supplier_name
 
    # supplier referenced by (possibly misspelt) name instead of id
    m = _mask(rng, n, 0.10)
    df["supplier_ref"] = df.supplier_id
    df.loc[m, "supplier_ref"] = [rng.choice([names[s], names[s].upper(), names[s].replace("Pvt Ltd", "Private Limited")]) for s in df.loc[m, "supplier_id"]]
    df = df.drop(columns="supplier_id").rename(columns={"supplier_ref": "supplier"})
    log["supplier_by_name"] = int(m.sum())
 
    # receipt date earlier than PO date (year keyed wrongly)
    closed = (df.status == "Closed") & df.actual_receipt_date.notna()
    m = closed & _mask(rng, n, 0.003)
    df.loc[m, "actual_receipt_date"] = df.loc[m, "po_date"] - pd.to_timedelta(rng.integers(1, 20, int(m.sum())), unit="D")
    log["receipt_before_po_date"] = int(m.sum())
 
    # missing received quantity on closed POs
    m = closed & _mask(rng, n, 0.008) & ~df.index.isin(df.index[df.actual_receipt_date < df.po_date])
    df["received_qty"] = df.received_qty.astype(object)
    df.loc[m, "received_qty"] = np.nan
    log["received_qty_missing_on_closed"] = int(m.sum())
 
    # prices as text with currency symbols; quantities with thousands separators
    df["unit_price"] = [_money_str(v, rng) for v in df.unit_price]
    m = _mask(rng, n, 0.03) & (df.order_qty >= 1000)
    df["order_qty"] = df.order_qty.astype(object)
    df.loc[m, "order_qty"] = df.loc[m, "order_qty"].map(lambda v: f"{int(v):,}")
    log["order_qty_with_commas"] = int(m.sum())
 
    # status spelling
    variants = {"Closed": ["CLOSED", "closed", "Closed"], "Open": ["OPEN", "open", "Open"]}
    df["status"] = [rng.choice(variants[s]) for s in df.status]
 
    df["item_id"] = messy_item_id(df.item_id, rng, log)
    for c in ["po_date", "promised_date", "actual_receipt_date"]:
        df[c] = messy_dates(pd.to_datetime(df[c]), rng)
    df, nd = add_duplicates(df, rng, 0.01)
    log["duplicate_rows"] = nd
    return df, log
 
 
# ----------------------------------------------------------------------------- inventory
def dirty_inventory(truth: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    log: dict = {}
    df = truth.copy().reset_index(drop=True)
    n = len(df)
    df["on_hand_qty"] = df.on_hand_qty.astype(float)
    m = _mask(rng, n, 0.002) & (df.on_hand_qty > 0)
    df.loc[m, "on_hand_qty"] *= -1
    log["on_hand_negative"] = int(m.sum())
    m = _mask(rng, n, 0.005)
    df.loc[m, "on_hand_qty"] = np.nan
    log["on_hand_missing"] = int(m.sum())
    m = _mask(rng, n, 0.15)
    df.loc[m, "location"] = df.loc[m, "location"].str.replace("WH-", "WH ", regex=False).str.replace("/R", " - R", regex=False)
    log["location_format_variant"] = int(m.sum())
    df["item_id"] = messy_item_id(df.item_id, rng, log)
    df["snapshot_date"] = messy_dates(pd.to_datetime(df.snapshot_date), rng)
    df, nd = add_duplicates(df, rng, 0.01)
    log["duplicate_rows"] = nd
    return df, log
 
 
# ----------------------------------------------------------------------------- masters
def dirty_suppliers(truth: pd.DataFrame, rng: np.random.Generator, amended_ids: list[str]) -> tuple[pd.DataFrame, dict]:
    """The raw ERP supplier master only carries commercial basics. Penalty, PPM limit etc. exist
    ONLY in the contract documents (that is what RAG is for)."""
    log: dict = {}
    df = truth[["supplier_id", "supplier_name", "category", "city", "gstin", "contact_person", "contact_email", "phone",
                "payment_terms_days", "contract_lead_time_days", "incoterm"]].copy().reset_index(drop=True)
    n = len(df)
    df = df.rename(columns={"payment_terms_days": "payment_terms", "contract_lead_time_days": "lead_time"})
    df["lead_time"] = [rng.choice([f"{v} days", str(v), f"{v / 7:.0f} weeks" if v % 7 == 0 else f"{v} days"]) for v in df.lead_time]
    df["payment_terms"] = [rng.choice([f"{v} days", f"Net {v}", str(v)]) for v in df.payment_terms]
    city_var = {"Pimpri-Chinchwad": ["PCMC", "Pimpri Chinchwad", "Pimpri-Chinchwad"], "Bhosari (MIDC)": ["Bhosari MIDC", "Bhosari", "Bhosari (MIDC)"]}
    m = df.city.isin(city_var)
    df.loc[m, "city"] = [rng.choice(city_var[c]) for c in df.loc[m, "city"]]
    log["city_variant_rows"] = int(m.sum())
    m = _mask(rng, n, 0.08)
    df.loc[m, "contact_email"] = None
    log["contact_email_missing"] = int(m.sum())
    m = _mask(rng, n, 0.06)
    df.loc[m, "gstin"] = df.loc[m, "gstin"].str[:-2]          # truncated GSTIN -> invalid
    log["gstin_invalid"] = int(m.sum())
    # stale ERP values for suppliers whose contract was later amended (intentional master-vs-contract mismatch)
    log["amended_supplier_ids"] = amended_ids
    dup = df.sample(3, random_state=int(rng.integers(0, 10_000))).copy()
    dup["supplier_name"] = dup.supplier_name.str.upper()
    dup["contact_email"] = None
    df = pd.concat([df, dup], ignore_index=True)
    log["duplicate_rows"] = 3
    return df, log
 
 
def dirty_items(truth: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    log: dict = {}
    df = truth.drop(columns="base_daily_demand").copy().reset_index(drop=True)
    n = len(df)
    df["unit_cost_inr"] = [_money_str(v, rng) for v in df.unit_cost_inr]
    m = _mask(rng, n, 0.08)
    df.loc[m, "uom"] = [rng.choice(UOM_VARIANTS[u]) for u in df.loc[m, "uom"]]
    log["uom_spelling_variant"] = int(m.sum())
    m = _mask(rng, n, 0.04)
    df.loc[m, "category"] = None
    log["category_missing"] = int(m.sum())
    df, nd = add_duplicates(df, rng, 0.01)
    log["duplicate_rows"] = nd
    return df, log
 
 
def dirty_policy(truth: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    df = truth.copy().reset_index(drop=True)
    m = _mask(rng, len(df), 0.03)
    df["safety_stock"] = df.safety_stock.astype(float)
    df.loc[m, "safety_stock"] = np.nan
    df["last_reviewed_date"] = messy_dates(pd.to_datetime(df.last_reviewed_date), rng)
    return df, {"safety_stock_missing": int(m.sum())}
