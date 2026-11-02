"""Simulate two years of demand, inventory and purchase orders (clean 'ground truth').
 
Design goals
------------
* Realistic enough that forecasting, safety stock and ABC analysis give meaningful results.
* A deliberately *stale* reorder policy, so the agents have real problems to find:
  demand drifts and shifts while reorder points are only reviewed occasionally.
* Weekly pattern, festive/year-end seasonality, plant shutdowns, monsoon delays,
  supplier disruptions, short shipments and quality rejections.
"""
from __future__ import annotations
 
import numpy as np
import pandas as pd
 
from scm.config import OEM_CUSTOMERS, SHUTDOWNS, fy_label
 
MONTH_FACTOR = {1: 1.00, 2: 1.02, 3: 1.10, 4: 0.92, 5: 0.95, 6: 0.97, 7: 0.96, 8: 1.02, 9: 1.12, 10: 1.18, 11: 1.08, 12: 0.90}
DOW_FACTOR = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.55, 0.0])  # Mon..Sun (Sat half day, Sun off)
 
 
def build_calendar(start: str, end: str) -> tuple[pd.DatetimeIndex, np.ndarray]:
    dates = pd.date_range(start, end, freq="D")
    work = np.asarray(dates.dayofweek != 6)
    for a, b in SHUTDOWNS:
        work &= ~np.asarray((dates >= a) & (dates <= b))
    return dates, work
 
 
def make_demand(items: pd.DataFrame, dates: pd.DatetimeIndex, work: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Integer OEM schedule quantity per item per day, shape (n_items, n_days)."""
    n_i, n_d = len(items), len(dates)
    mu = items.base_daily_demand.to_numpy()[:, None]
    t = (np.arange(n_d) / 365.0)[None, :]
    trend = np.exp(rng.normal(0.05, 0.12, n_i)[:, None] * t)                       # yearly drift per item
    month_idx = np.asarray(dates.month)
    amp = rng.uniform(0.5, 1.5, n_i)[:, None]
    season = 1 + amp * (np.array([MONTH_FACTOR[m] for m in month_idx])[None, :] - 1)
    dow = DOW_FACTOR[np.asarray(dates.dayofweek)][None, :]
    shift = np.ones((n_i, n_d))                                                     # new-model ramp-ups
    for i in rng.choice(n_i, size=max(1, n_i // 20), replace=False):
        shift[i, int(rng.integers(n_d // 4, n_d * 3 // 4)):] *= rng.uniform(1.3, 1.6)
    mean = mu * trend * season * dow * shift * work[None, :]
    k = np.clip(mu[:, 0] / 2, 1.5, 20)[:, None]                                    # low volume -> lumpier demand
    lam = mean * rng.gamma(k, 1.0 / k, size=mean.shape)
    return rng.poisson(lam).astype(int)
 
 
def _policy(avg_daily: float, lt: int, moq: int, pack: int) -> tuple[int, int, int]:
    """The planner's *naive* rule: mean demand over lead time + 45%, no statistical safety stock."""
    rop = int(np.ceil(avg_daily * lt * 1.45))
    ss = int(np.ceil(avg_daily * lt * 0.45))
    oq = int(max(moq, np.ceil(avg_daily * 21 / pack) * pack))
    return rop, ss, oq
 
 
def simulate(items: pd.DataFrame, suppliers: pd.DataFrame, sim: pd.DataFrame, dates: pd.DatetimeIndex,
             work: np.ndarray, rng: np.random.Generator, snapshot_days: int = 120) -> dict[str, pd.DataFrame]:
    demand = make_demand(items, dates, work, rng)
    n_i, n_d = demand.shape
    sup = suppliers.set_index("supplier_id")
    simp = sim.set_index("supplier_id")
    monsoon = np.isin(np.asarray(dates.month), [6, 7, 8, 9])
 
    disp = np.zeros_like(demand)
    onhand_hist = np.zeros((n_i, n_d), dtype=int)
    onorder_hist = np.zeros((n_i, n_d), dtype=int)
    po_rows: list[dict] = []
    policy_rows: list[dict] = []
 
    for i, it in enumerate(items.itertuples()):
        d = demand[i]
        sp = simp.loc[it.supplier_id]
        lt_plan = int(it.planned_lead_time_days)
        reviewed = rng.random() < 0.60                      # only 60% of items ever get re-reviewed
        review_days = set(range(90 + int(rng.integers(0, 60)), n_d, 180)) if reviewed else set()
        rop, ss, oq = _policy(d[:60].sum() / 60, lt_plan, int(it.moq), int(it.pack_size))
        last_review = dates[0]
        on_hand = rop + oq // 2
        open_pos: list[dict] = []
 
        for t in range(n_d):
            if t in review_days:
                rop, ss, oq = _policy(d[t - 90:t].sum() / 90, lt_plan, int(it.moq), int(it.pack_size))
                last_review = dates[t]
            if work[t]:
                still = []
                for p in open_pos:
                    if p["arrival"] <= t:
                        on_hand += p["received_qty"] - p["rejected_qty"]
                        p["actual_receipt_date"] = dates[t]
                        p["status"] = "Closed"
                        po_rows.append(p)
                    else:
                        still.append(p)
                open_pos = still
                shipped = min(on_hand, int(d[t]))
                on_hand -= shipped
                disp[i, t] = shipped
                if on_hand + sum(p["order_qty"] for p in open_pos) <= rop:
                    lt = max(2, int(round(rng.normal(sp.lt_mean_actual, sp.lt_std))))
                    if monsoon[t]:
                        lt += int(rng.integers(0, 4))
                    if rng.random() < sp.delay_prob:
                        lt += int(rng.integers(3, 11))
                    recv = oq if rng.random() > 0.05 else int(oq * rng.uniform(0.80, 0.97))
                    rej = int(rng.binomial(recv, min(sp.ppm_actual / 1e6, 1.0)))
                    if rng.random() < 0.02:
                        rej += int(recv * rng.uniform(0.03, 0.10))
                    years_back = (n_d - t) / 365.0
                    open_pos.append(dict(
                        po_date=dates[t], supplier_id=it.supplier_id, item_id=it.item_id, order_qty=oq,
                        unit_price=round(it.unit_cost_inr * (1 - 0.045 * years_back) * rng.uniform(0.99, 1.01), 2),
                        promised_date=dates[t] + pd.Timedelta(days=lt_plan), arrival=t + lt,
                        received_qty=recv, rejected_qty=rej, actual_receipt_date=pd.NaT, status="Open"))
            onhand_hist[i, t] = on_hand
            onorder_hist[i, t] = sum(p["order_qty"] for p in open_pos)
 
        for p in open_pos:                                  # still open at the end of the window
            p["received_qty"], p["rejected_qty"] = np.nan, np.nan
            po_rows.append(p)
        policy_rows.append(dict(item_id=it.item_id, reorder_point=rop, safety_stock=ss, order_qty=oq,
                                last_reviewed_date=last_review.date().isoformat()))
 
    # ---- purchase orders: number them like an Indian ERP (PO/<FY>/<seq>), one PO per supplier per day
    pos = pd.DataFrame(po_rows).drop(columns="arrival").sort_values(["po_date", "supplier_id", "item_id"]).reset_index(drop=True)
    key = pos.po_date.dt.strftime("%Y%m%d") + pos.supplier_id
    pos["po_seq"] = pd.factorize(key)[0] + 1
    pos["po_number"] = [f"PO/{fy_label(d)}/{s:05d}" for d, s in zip(pos.po_date, pos.po_seq)]
    pos["line_no"] = pos.groupby("po_number").cumcount() + 1
    pos["payment_terms_days"] = pos.supplier_id.map(sup.payment_terms_days)
    pos = pos[["po_number", "line_no", "po_date", "supplier_id", "item_id", "order_qty", "unit_price", "promised_date",
               "actual_receipt_date", "received_qty", "rejected_qty", "status", "payment_terms_days"]]
 
    # ---- sales (OEM schedule vs what we actually dispatched)
    pieces = []
    n_c = len(OEM_CUSTOMERS)
    for i, it in enumerate(items.itertuples()):
        sched, shipped = demand[i], disp[i]
        prim = int(rng.integers(0, n_c))
        if rng.random() < 0.25:                              # a quarter of items go to two customers
            sec_c = (prim + 1 + int(rng.integers(0, n_c - 1))) % n_c
            s2 = rng.binomial(sched, 0.3)
            d2 = np.minimum(s2, np.round(shipped * s2 / np.maximum(sched, 1)).astype(int))
            parts = [(OEM_CUSTOMERS[prim], sched - s2, shipped - d2), (OEM_CUSTOMERS[sec_c], s2, d2)]
        else:
            parts = [(OEM_CUSTOMERS[prim], sched, shipped)]
        for cust, s, dsp in parts:
            m = s > 0
            pieces.append(pd.DataFrame(dict(dispatch_date=dates[m], item_id=it.item_id, customer=cust, uom=it.uom,
                                            schedule_qty=s[m], dispatched_qty=dsp[m])))
    sales = pd.concat(pieces, ignore_index=True).sort_values(["dispatch_date", "item_id", "customer"]).reset_index(drop=True)
    sales["invoice_no"] = None
    has = sales.dispatched_qty > 0
    fy = sales.dispatch_date.map(fy_label)
    sales.loc[has, "invoice_no"] = [f"INV/{f}/{n:06d}" for f, n in zip(fy[has], range(1, int(has.sum()) + 1))]
 
    # ---- daily inventory snapshots for the most recent window
    lo = max(0, n_d - snapshot_days)
    snap = pd.DataFrame(dict(
        snapshot_date=np.tile(dates[lo:], n_i), item_id=np.repeat(items.item_id.to_numpy(), n_d - lo),
        on_hand_qty=onhand_hist[:, lo:].ravel(), on_order_qty=onorder_hist[:, lo:].ravel()))
    snap["location"] = snap.item_id.map(items.set_index("item_id").storage_location)
 
    return dict(sales=sales, purchase_orders=pos, inventory_snapshot=snap, reorder_policy=pd.DataFrame(policy_rows))
