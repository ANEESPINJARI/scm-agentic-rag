"""Generate the clean supplier master and item master.
 
"""
from __future__ import annotations
 
import string
 
import numpy as np
import pandas as pd
 
# demand = median units/day for the category; cost = INR per unit range;
# lt = (mean lead time days, std); moq = MOQ range; weight = share of SKUs
CATEGORIES: dict[str, dict] = {
    "Castings":           dict(parts=["Aluminium die-cast housing", "SG iron brake drum", "Gearbox casing", "Cylinder head casting", "Oil pan casting"], uom="NOS", cost=(450, 3500), demand=(10, 60), lt=(18, 3), moq=(50, 200), n_sup=3, weight=35),
    "Forgings":           dict(parts=["Crankshaft forging", "Connecting rod forging", "Steering knuckle", "Axle shaft blank"], uom="NOS", cost=(300, 2200), demand=(15, 80), lt=(22, 4), moq=(100, 400), n_sup=2, weight=25),
    "Fasteners":          dict(parts=["Hex bolt", "Flange nut", "Stud", "Spring washer", "Socket head screw", "Wheel bolt"], uom="NOS", cost=(1.5, 45), demand=(400, 6000), lt=(9, 2), moq=(2000, 10000), n_sup=3, weight=55),
    "Rubber & Plastics":  dict(parts=["Rubber grommet", "Engine mount bush", "Door seal strip", "Fuel hose clamp cover", "ABS clip", "Wiper blade rubber"], uom="NOS", cost=(8, 260), demand=(80, 1200), lt=(13, 3), moq=(500, 3000), n_sup=3, weight=40),
    "Wiring Harness":     dict(parts=["Main wiring harness", "Headlamp harness", "Ignition coil lead", "Battery cable assembly"], uom="NOS", cost=(220, 1800), demand=(20, 140), lt=(15, 3), moq=(100, 500), n_sup=2, weight=25),
    "Bearings":           dict(parts=["Deep groove ball bearing", "Tapered roller bearing", "Needle bearing", "Wheel hub bearing"], uom="NOS", cost=(60, 950), demand=(60, 500), lt=(21, 5), moq=(200, 1000), n_sup=2, weight=30),
    "Stampings":          dict(parts=["Bracket stamping", "Chassis cross-member", "Heat shield", "Mudguard panel", "Clutch cover pressing"], uom="NOS", cost=(25, 700), demand=(40, 400), lt=(10, 2), moq=(200, 1000), n_sup=3, weight=35),
    "Packaging":          dict(parts=["Corrugated carton", "Returnable plastic crate", "VCI bag", "Foam separator"], uom="NOS", cost=(6, 180), demand=(100, 900), lt=(5, 1), moq=(500, 2000), n_sup=2, weight=15),
    "Lubricants":         dict(parts=["Gear oil EP90", "Coolant concentrate", "Assembly grease", "Cutting fluid"], uom="LTR", cost=(120, 520), demand=(40, 350), lt=(6, 1), moq=(200, 1000), n_sup=2, weight=12),
    "Sensors & Electronics": dict(parts=["Wheel speed sensor", "Throttle position sensor", "ECU relay module", "Temperature sensor"], uom="NOS", cost=(150, 2600), demand=(10, 70), lt=(30, 6), moq=(100, 300), n_sup=1, weight=13),
    "Raw Steel":          dict(parts=["Alloy steel bar EN24", "CRCA steel coil", "Case hardening steel bar"], uom="KG", cost=(58, 140), demand=(300, 3000), lt=(11, 2), moq=(2000, 10000), n_sup=2, weight=15),
}
 
LOCAL_CITIES = ["Chakan", "Bhosari (MIDC)", "Pimpri-Chinchwad", "Talawade", "Ranjangaon", "Nigdi", "Akurdi", "Moshi"]
REGIONAL_CITIES = ["Kolhapur", "Nashik", "Chhatrapati Sambhajinagar", "Satara"]
FAR_CITIES = ["Chennai", "Gurugram", "Bengaluru"]
 
NAME_PREFIX = ["Bhima", "Indrayani", "Pavna", "Sahyadri", "Mulshi", "Chakan", "Talawade", "Moshi", "Akurdi", "Nigdi",
               "Ranjan", "Deccan", "Konkan", "Vitthal", "Shivneri", "Rajgad", "Sinhagad", "Purandar", "Malhar", "Gajanan",
               "Omkar", "Samarth", "Vighnaharta", "Kaveri", "Godavari"]
NAME_SUFFIX = ["Industries", "Enterprises", "Engineering Works", "Components Pvt Ltd", "Auto Products", "Precision Pvt Ltd", "Udyog"]
CAT_WORD = {
    "Castings": "Castings", "Forgings": "Forgings", "Fasteners": "Fasteners", "Rubber & Plastics": "Polymers",
    "Wiring Harness": "Cables", "Bearings": "Bearings", "Stampings": "Pressings", "Packaging": "Packaging",
    "Lubricants": "Lubricants", "Sensors & Electronics": "Electronics", "Raw Steel": "Steel",
}
 
 
def _gstin(rng: np.random.Generator) -> str:
    letters = string.ascii_uppercase
    pan = "".join(rng.choice(list(letters), 5)) + f"{rng.integers(0, 10000):04d}" + str(rng.choice(list(letters)))
    return f"27{pan}1Z{rng.integers(0, 10)}"  # synthetic; 27 = Maharashtra code
 
 
def _slug(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())[:18]
 
 
def make_suppliers(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (supplier_master_truth, supplier_sim_params)."""
    rows, sim = [], []
    used: set[str] = set()
    sid = 0
    first = ["Rajesh", "Sunita", "Amit", "Prakash", "Neha", "Vikram", "Anita", "Sandeep", "Kavita", "Manoj", "Deepak", "Meera"]
    last = ["Patil", "Kulkarni", "Deshmukh", "Joshi", "Jadhav", "More", "Pawar", "Shinde", "Gaikwad", "Kale", "Bhosale", "Naik"]
    for cat, spec in CATEGORIES.items():
        for _ in range(spec["n_sup"]):
            sid += 1
            while True:
                name = f"{rng.choice(NAME_PREFIX)} {CAT_WORD[cat]} {rng.choice(NAME_SUFFIX)}"
                if name not in used:
                    used.add(name)
                    break
            r = rng.random()
            if cat == "Sensors & Electronics" or r > 0.90:
                city, add = rng.choice(FAR_CITIES), 8
            elif r > 0.70:
                city, add = rng.choice(REGIONAL_CITIES), 3
            else:
                city, add = rng.choice(LOCAL_CITIES), 0
            lt_mean, lt_std = spec["lt"]
            contract_lt = int(round(lt_mean + add + rng.integers(-1, 2)))
            ppm_limit = int(rng.choice([1000, 1500, 2000, 3000, 5000]))
            start = pd.Timestamp("2022-04-01") + pd.Timedelta(days=int(rng.integers(0, 900)))
            person = f"{rng.choice(first)} {rng.choice(last)}"
            rows.append(dict(
                supplier_id=f"S{sid:03d}", supplier_name=name, category=cat, city=city, state="Maharashtra" if add < 8 else "Other",
                gstin=_gstin(rng), contact_person=person,
                contact_email=f"{person.split()[0].lower()}.{person.split()[1].lower()}@{_slug(name)}.example.com",
                phone=f"+91 9{rng.integers(100000000, 999999999)}",
                payment_terms_days=int(rng.choice([30, 45, 60, 90], p=[0.25, 0.4, 0.25, 0.1])),
                contract_lead_time_days=contract_lt,
                incoterm=str(rng.choice(["DAP Chakan plant", "EXW supplier works"], p=[0.7, 0.3])),
                delay_penalty_pct_per_week=float(rng.choice([0.5, 1.0])),
                penalty_cap_pct=float(rng.choice([5.0, 10.0])),
                ppm_limit=ppm_limit,
                contract_start_date=start.date().isoformat(),
                contract_end_date=(start + pd.Timedelta(days=int(365 * rng.choice([3, 3, 4])))).date().isoformat(),
            ))
            sim.append(dict(
                supplier_id=f"S{sid:03d}",
                lt_mean_actual=contract_lt * float(rng.uniform(0.88, 1.10)),   # real lead time drifts above contract
                lt_std=float(lt_std * rng.uniform(0.6, 1.5)),
                delay_prob=float(rng.uniform(0.03, 0.12)),                      # chance of a disruption on any PO
                ppm_actual=float(ppm_limit * rng.uniform(0.3, 1.6)),            # some suppliers exceed their limit
            ))
    return pd.DataFrame(rows), pd.DataFrame(sim)
 
 
def make_items(rng: np.random.Generator, suppliers: pd.DataFrame, n_items: int) -> pd.DataFrame:
    """Create the item master. Demand and cost scales differ by category, and a
    lognormal multiplier creates the Pareto (ABC) pattern seen in real plants."""
    total_w = sum(c["weight"] for c in CATEGORIES.values())
    rows, n = [], 0
    for cat, spec in CATEGORIES.items():
        k = max(2, int(round(spec["weight"] / total_w * n_items)))
        sups = suppliers[suppliers.category == cat].supplier_id.tolist()
        for _ in range(k):
            n += 1
            cost = float(np.exp(rng.uniform(np.log(spec["cost"][0]), np.log(spec["cost"][1]))))
            base = float(np.exp(rng.uniform(np.log(spec["demand"][0]), np.log(spec["demand"][1]))) * np.exp(rng.normal(0, 0.8)))
            sid = str(rng.choice(sups))
            moq = int(round(rng.uniform(*spec["moq"]), -1)) or 10
            code = f"{rng.choice(list('ABCDEFGHJKLMNPRSTVWXZ'))}{rng.integers(100, 999)}"
            lt = int(suppliers.loc[suppliers.supplier_id == sid, "contract_lead_time_days"].iloc[0])
            rows.append(dict(
                item_id=f"PN-{10000 + n}", description=f"{rng.choice(spec['parts'])} - {code}", category=cat,
                uom=spec["uom"], unit_cost_inr=round(cost, 2), supplier_id=sid, moq=moq,
                pack_size=int(rng.choice([10, 20, 50, 100])) if spec["uom"] == "NOS" else 25,
                planned_lead_time_days=lt, criticality=str(rng.choice(["High", "Medium", "Low"], p=[0.25, 0.45, 0.30])),
                storage_location=f"WH-{rng.choice(list('ABC'))}/R{rng.integers(1, 40):02d}",
                base_daily_demand=round(base, 2),   # simulation parameter; dropped from the raw export
            ))
    return pd.DataFrame(rows)
