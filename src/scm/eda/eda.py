"""Exploratory data analysis on the CLEANED data. Writes charts + a markdown summary to reports/.
 
    python -m scm.eda.eda
"""
from __future__ import annotations
 
import json
from pathlib import Path
 
import matplotlib
 
matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
 
from scm import config as C
 
 
def abc_classify(value: pd.Series) -> pd.Series:
    """Class by cumulative share of value (A <= 80%, B <= 95%, C rest). Full tool version comes in Phase 4."""
    v = value.sort_values(ascending=False)
    share = v.cumsum() / v.sum()
    prev = share.shift(fill_value=0)                     # an item is A if it STARTS inside the first 80%
    cls = np.where(prev < C.ABC_CUTOFFS[0], "A", np.where(prev < C.ABC_CUTOFFS[1], "B", "C"))
    return pd.Series(cls, index=v.index)
 
 
def _load(d: Path) -> dict[str, pd.DataFrame]:
    t = {n: pd.read_csv(d / f"{n}.csv") for n in ["suppliers", "items", "sales", "purchase_orders", "inventory_snapshot", "reorder_policy"]}
    t["sales"]["dispatch_date"] = pd.to_datetime(t["sales"].dispatch_date)
    for c in ["po_date", "promised_date", "actual_receipt_date"]:
        t["purchase_orders"][c] = pd.to_datetime(t["purchase_orders"][c])
    t["inventory_snapshot"]["snapshot_date"] = pd.to_datetime(t["inventory_snapshot"].snapshot_date)
    return t
 
 
def run(processed_dir: Path = C.PROCESSED_DIR, reports_dir: Path = C.REPORTS_DIR) -> dict:
    t = _load(processed_dir)
    out = reports_dir / "eda"
    out.mkdir(parents=True, exist_ok=True)
    sales, items, pos, inv, sup, pol = t["sales"], t["items"].set_index("item_id"), t["purchase_orders"], t["inventory_snapshot"], t["suppliers"], t["reorder_policy"].set_index("item_id")
    end = sales.dispatch_date.max()
    last12 = sales[sales.dispatch_date > end - pd.Timedelta(days=365)]
 
    # ---- ABC (last 12 months consumption value)
    value = (last12.groupby("item_id").schedule_qty.sum() * items.unit_cost_inr).dropna()
    abc = abc_classify(value)
    cum = value.sort_values(ascending=False).cumsum() / value.sum()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(range(len(cum)), value.sort_values(ascending=False).values / 1e6, color="#8FAADC")
    ax2 = ax.twinx()
    ax2.plot(range(len(cum)), cum.values * 100, color="#C00000")
    ax2.axhline(80, ls="--", color="grey"); ax2.axhline(95, ls="--", color="grey")
    ax.set_xlabel("Items ranked by annual value"); ax.set_ylabel("Annual value (INR million)"); ax2.set_ylabel("Cumulative %")
    ax.set_title("Pareto / ABC analysis (last 12 months)")
    fig.tight_layout(); fig.savefig(out / "01_abc_pareto.png", dpi=130); plt.close(fig)
    n_a, n_b, n_c = (abc == "A").sum(), (abc == "B").sum(), (abc == "C").sum()
 
    # ---- monthly demand value and weekday pattern
    sv = sales.assign(val=sales.schedule_qty * sales.item_id.map(items.unit_cost_inr))
    monthly = sv.groupby(sv.dispatch_date.dt.to_period("M")).val.sum() / 1e6
    fig, ax = plt.subplots(figsize=(8, 4)); monthly.plot(ax=ax, marker="o", color="#2F5496")
    ax.set_ylabel("OEM schedule value (INR million)"); ax.set_title("Monthly demand value (festive peak Sep-Oct, year-end push in March)")
    fig.tight_layout(); fig.savefig(out / "02_monthly_demand.png", dpi=130); plt.close(fig)
    dow = sv.groupby(sv.dispatch_date.dt.day_name()).val.sum().reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]).fillna(0)
    fig, ax = plt.subplots(figsize=(6, 3.5)); (dow / 1e6).plot.bar(ax=ax, color="#8FAADC")
    ax.set_ylabel("INR million"); ax.set_title("Demand by weekday (Sunday = no production)")
    fig.tight_layout(); fig.savefig(out / "03_weekday.png", dpi=130); plt.close(fig)
 
    # ---- top A items, weekly
    top = value.sort_values(ascending=False).index[:3]
    fig, ax = plt.subplots(figsize=(8, 4))
    for it in top:
        s = sales[sales.item_id == it].set_index("dispatch_date").schedule_qty.resample("W").sum()
        s.plot(ax=ax, label=f"{it}")
    ax.set_ylabel("Weekly schedule qty"); ax.set_title("Top 3 A-class items: weekly demand"); ax.legend()
    fig.tight_layout(); fig.savefig(out / "04_top_items_weekly.png", dpi=130); plt.close(fig)
 
    # ---- supplier delivery performance
    closed = pos[pos.status == "Closed"].copy()
    perf = closed.groupby("supplier_id").agg(po_lines=("po_number", "count"), on_time=("delay_days", lambda x: (x <= 0).mean()), avg_delay=("delay_days", "mean"),
                                             avg_lt=("lead_time_days", "mean"), rejected=("rejected_qty", "sum"), received=("received_qty", "sum"))
    perf["ppm"] = perf.rejected / perf.received * 1e6
    perf = perf.join(sup.set_index("supplier_id")[["supplier_name", "category", "lead_time_days"]])
    fig, ax = plt.subplots(figsize=(8, 4.5)); perf.on_time.sort_values().mul(100).plot.barh(ax=ax, color="#8FAADC")
    ax.set_xlabel("On-time delivery %"); ax.set_title("Supplier on-time delivery (receipt <= promised date)")
    fig.tight_layout(); fig.savefig(out / "05_supplier_on_time.png", dpi=130); plt.close(fig)
    fig, ax = plt.subplots(figsize=(5.5, 5)); ax.scatter(perf.lead_time_days, perf.avg_lt, color="#2F5496")
    lim = [0, max(perf.lead_time_days.max(), perf.avg_lt.max()) + 3]; ax.plot(lim, lim, "--", color="grey")
    ax.set_xlabel("Contract / ERP lead time (days)"); ax.set_ylabel("Actual average lead time (days)"); ax.set_title("Actual vs contractual lead time")
    fig.tight_layout(); fig.savefig(out / "06_lead_time_actual_vs_contract.png", dpi=130); plt.close(fig)
 
    # ---- service level by class
    s2 = sales.assign(cls=sales.item_id.map(abc))
    svc = s2.groupby("cls").agg(lines=("item_id", "size"), short_lines=("dispatched_qty", lambda x: 0), sched=("schedule_qty", "sum"), disp=("dispatched_qty", "sum"))
    svc["short_lines"] = s2.assign(sh=s2.dispatched_qty < s2.schedule_qty).groupby("cls").sh.sum()
    svc["fill_rate"] = svc.disp / svc.sched
    svc["line_stockout_rate"] = svc.short_lines / svc.lines
    fig, ax = plt.subplots(figsize=(5.5, 3.5)); (svc.fill_rate * 100).plot.bar(ax=ax, color=["#C00000", "#ED7D31", "#8FAADC"])
    ax.axhline(98, ls="--", color="grey"); ax.set_ylim(70, 101); ax.set_ylabel("Quantity fill rate %"); ax.set_title("Fill rate by ABC class (target A = 98%)")
    fig.tight_layout(); fig.savefig(out / "07_fill_rate_by_class.png", dpi=130); plt.close(fig)
 
    # ---- days of cover now, and stale-policy check
    recent = sales[sales.dispatch_date > end - pd.Timedelta(days=90)].groupby("item_id").schedule_qty.sum() / 90
    last_inv = inv[inv.snapshot_date == inv.snapshot_date.max()].set_index("item_id")
    cover = (last_inv.on_hand_qty / recent.reindex(last_inv.index)).replace([np.inf], np.nan).dropna()
    fig, ax = plt.subplots(figsize=(7, 3.8)); cover.clip(upper=60).plot.hist(bins=30, ax=ax, color="#8FAADC")
    ax.set_xlabel("Days of cover (clipped at 60)"); ax.set_title("Days of stock cover, latest snapshot")
    fig.tight_layout(); fig.savefig(out / "08_days_of_cover.png", dpi=130); plt.close(fig)
    sup_lt = perf.avg_lt
    need = pd.DataFrame({"demand": recent, "lead": items.supplier_id.map(sup_lt)}).dropna()
    need["needed_rop"] = need.demand * need["lead"]
    need["current_rop"] = pol.reorder_point
    a_items = abc[abc == "A"].index
    a_need = need.loc[need.index.intersection(a_items)]
    below = float((a_need.current_rop < a_need.needed_rop).mean())
 
    # ---- data quality chart
    dq_path = reports_dir / "data_quality_report.json"
    if dq_path.exists():
        dq = json.loads(dq_path.read_text())
        rows = [(f"{tb}: {r[:45]}", n) for tb, d in dq.items() for r, n in d["rules"].items() if n > 0 and "should be 0" not in r]
        rows = sorted(rows, key=lambda x: -x[1])[:12]
        fig, ax = plt.subplots(figsize=(9, 5)); ax.barh([r[0] for r in rows][::-1], [r[1] for r in rows][::-1], color="#8FAADC")
        ax.set_xscale("log"); ax.set_xlabel("Rows affected (log scale)"); ax.set_title("Top data-cleaning rules by rows affected")
        fig.tight_layout(); fig.savefig(out / "09_data_quality.png", dpi=130); plt.close(fig)
 
    s = dict(
        period=f"{sales.dispatch_date.min().date()} to {end.date()}", items=len(items), suppliers=len(sup), sales_rows=len(sales), po_lines=len(pos),
        abc_counts={"A": int(n_a), "B": int(n_b), "C": int(n_c)},
        a_value_share_pct=round(100 * value[abc[abc == "A"].index].sum() / value.sum(), 1),
        peak_month=str(monthly.idxmax()), peak_vs_avg=round(float(monthly.max() / monthly.mean()), 2),
        fill_rate_pct=(svc.fill_rate * 100).round(1).to_dict(), line_stockout_pct=(svc.line_stockout_rate * 100).round(1).to_dict(),
        on_time_overall_pct=round(float((closed.delay_days <= 0).mean() * 100), 1), avg_delay_days=round(float(closed.delay_days.mean()), 1),
        worst_supplier=str(perf.on_time.idxmin()), worst_supplier_on_time_pct=round(float(perf.on_time.min() * 100), 1),
        suppliers_over_ppm_limit_note="compare perf.ppm with contract PPM limit in Phase 4",
        median_days_cover=round(float(cover.median()), 1), a_items_with_rop_below_need_pct=round(below * 100, 1),
    )
    md = ["# EDA summary", "", "Computed from cleaned data. Charts are in `reports/eda/`.", ""]
    md += [f"- **{k}**: {v}" for k, v in s.items()]
    (reports_dir / "eda_summary.md").write_text("\n".join(md), encoding="utf-8")
    perf.round(2).to_csv(reports_dir / "supplier_performance_preview.csv")
    return s
 
 
if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
