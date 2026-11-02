"""Generate the unstructured documents used by RAG: contracts, amendments, SOPs and e-mails.
 
Facts inside the documents (lead times, penalties, approval limits...) come from the same
tables / config constants as the structured data, so RAG answers can be checked against truth.
"""
from __future__ import annotations
 
from pathlib import Path
from xml.sax.saxutils import escape
 
import numpy as np
import pandas as pd
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
 
from scm import config as C
from scm.config import inr
 
# ----------------------------------------------------------------------------- writers
Section = tuple[str, str]
 
 
def write_document(path: Path, title: str, subtitle: str, sections: list[Section]) -> None:
    """Write the same content as .docx, .pdf or .txt depending on the file extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower()
    if ext == ".txt":
        lines = [title.upper(), subtitle, "=" * 60, ""]
        for h, body in sections:
            lines += [h, body, ""]
        path.write_text("\n".join(lines), encoding="utf-8")
    elif ext == ".docx":
        doc = Document()
        doc.add_heading(title, level=1)
        doc.add_paragraph(subtitle)
        for h, body in sections:
            if h:
                doc.add_heading(h, level=2)
            for para in body.split("\n"):
                if para.strip():
                    doc.add_paragraph(para)
        doc.save(str(path))
    elif ext == ".pdf":
        styles = getSampleStyleSheet()
        story = [Paragraph(escape(title), styles["Title"]), Paragraph(escape(subtitle), styles["Italic"]), Spacer(1, 0.4 * cm)]
        for h, body in sections:
            if h:
                story.append(Paragraph(escape(h), styles["Heading3"]))
            for para in body.split("\n"):
                if para.strip():
                    story.append(Paragraph(escape(para), styles["BodyText"]))
            story.append(Spacer(1, 0.2 * cm))
        SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                          title=title, author=C.COMPANY).build(story)
    else:
        raise ValueError(f"unsupported extension {ext}")
 
 
# ----------------------------------------------------------------------------- contracts
def contract_sections(s: dict) -> list[Section]:
    return [
        ("1. Parties and Scope", f"This Supply Agreement is made between {C.COMPANY}, {C.PLANT_ADDRESS} (the Buyer) and {s['supplier_name']}, "
         f"located at {s['city']} (the Supplier), GSTIN {s['gstin']}. The Supplier shall supply {s['category']} items listed in the Buyer's item master "
         f"against written Purchase Orders (POs) issued by the Buyer."),
        ("2. Term", f"This Agreement is effective from {s['contract_start_date']} and remains valid until {s['contract_end_date']}, unless terminated earlier under Clause 11. "
         f"It may be renewed by mutual written consent."),
        ("3. Pricing and Price Revision", "Prices are in Indian Rupees (INR), exclusive of GST, and are fixed for twelve months from the effective date. "
         "The Supplier may request a revision with 30 days' written notice supported by published raw-material index evidence. A revision takes effect only after written acceptance by the Buyer's Purchase Manager."),
        ("4. Lead Time and Delivery", f"The Supplier shall deliver within {s['contract_lead_time_days']} calendar days from the date of the PO. Delivery terms: {s['incoterm']}. "
         "Deliveries are accepted Monday to Saturday between 9:00 and 17:00 at the Buyer's plant gate. A valid GST invoice, delivery challan and an e-way bill (for consignments above INR 50,000) must accompany every consignment."),
        ("5. Order Quantity and MOQ", "Each PO line is placed in multiples of the item's pack size and not below the item's minimum order quantity (MOQ) recorded in the item master. "
         "A delivered quantity within plus or minus 5 percent of the PO quantity is acceptable."),
        ("6. Payment Terms", f"Payment is due {s['payment_terms_days']} days from the date of receipt of a correct invoice and acceptance of the goods, by NEFT. "
         "Disputed quantities are excluded until resolved."),
        ("7. Quality", f"The Supplier's rejection level shall not exceed {s['ppm_limit']} parts per million (PPM) measured monthly at the Buyer's incoming inspection. "
         "On any rejection the Supplier shall submit an 8D report within 5 working days and replace rejected goods within 7 calendar days, failing which the Buyer may raise a debit note."),
        ("8. Delay Penalty", f"For each full week of delay beyond the delivery date, the Supplier shall pay a penalty of {s['delay_penalty_pct_per_week']} percent of the value of the delayed goods, "
         f"capped at {s['penalty_cap_pct']} percent of the PO value. Delay caused by Force Majeure under Clause 10 is excluded."),
        ("9. Expediting and Premium Freight", "If a delivery is more than 5 days late, the Buyer may request expediting. Where the delay is attributable to the Supplier, premium freight "
         "(air, dedicated vehicle or courier) is borne by the Supplier."),
        ("10. Force Majeure", "Neither party is liable for failure caused by events beyond reasonable control, including natural disasters, government orders or general strikes, provided written notice "
         "is given within 48 hours of the event. Heavy rain or ordinary transport disruption is not Force Majeure unless a government order closes the route."),
        ("11. Termination", "Either party may terminate with 60 days' written notice. The Buyer may terminate immediately if the Supplier exceeds the PPM limit for three consecutive months."),
        ("12. Confidentiality", "Drawings, schedules and prices are confidential and shall not be disclosed to third parties."),
        ("13. Governing Law and Jurisdiction", "This Agreement is governed by Indian law. The courts at Pune have exclusive jurisdiction."),
    ]
 
 
def amendment_sections(s: dict, new: dict, effective: str, base_doc: str) -> list[Section]:
    return [
        ("Amendment No. 1", f"This Amendment No. 1 to the Supply Agreement {base_doc} between {C.COMPANY} and {s['supplier_name']} is effective from {effective}. "
         "Where it conflicts with the Agreement, this Amendment prevails."),
        ("Clause 4 (Lead Time) replaced", f"The Supplier shall deliver within {new['lead_time']} calendar days from the date of the PO."),
        ("Clause 6 (Payment Terms) replaced", f"Payment is due {new['payment_terms']} days from the date of receipt of a correct invoice and acceptance of the goods."),
        ("Clause 8 (Delay Penalty) replaced", f"For each full week of delay beyond the delivery date, the Supplier shall pay a penalty of {new['penalty']} percent of the value of the delayed goods, "
         f"capped at {s['penalty_cap_pct']} percent of the PO value."),
        ("All other clauses", "All other clauses of the Agreement remain unchanged."),
    ]
 
 
# ----------------------------------------------------------------------------- SOPs
def sop_documents() -> list[dict]:
    pm = C.PO_APPROVAL_MATRIX
    return [
        dict(doc_id="SOP-INV-001", title="SOP: Reorder Point and Safety Stock Review", ext=".docx", sections=[
            ("Purpose", "Keep reorder points (ROP) and safety stock (SS) aligned with real demand and supplier lead time so lines are not stopped and cash is not locked in excess stock."),
            ("ABC classification", f"Items are classified by annual consumption value. Class A items make up the first {int(C.ABC_CUTOFFS[0] * 100)} percent of cumulative value, class B the next "
             f"{int((C.ABC_CUTOFFS[1] - C.ABC_CUTOFFS[0]) * 100)} percent, and class C the remainder."),
            ("Service level targets and review frequency", f"Target service levels: A = {int(C.SERVICE_LEVELS['A'] * 100)} percent, B = {int(C.SERVICE_LEVELS['B'] * 100)} percent, C = {int(C.SERVICE_LEVELS['C'] * 100)} percent. "
             f"Review frequency: A items {C.REVIEW_FREQUENCY['A']}, B items {C.REVIEW_FREQUENCY['B']}, C items {C.REVIEW_FREQUENCY['C']}."),
            ("Calculation", "ROP = average daily demand x lead time + safety stock. Safety stock = z x square root of (lead time x variance of daily demand + average daily demand squared x variance of lead time), "
             "where z comes from the target service level. Use supplier actual lead time, not only the contractual lead time."),
            ("Approval of changes", f"Any change to ROP or SS of an A item needs approval from the {C.REORDER_CHANGE_APPROVER['A']}. B and C item changes may be approved by the {C.REORDER_CHANGE_APPROVER['B']}. "
             f"A change of more than {int(C.REORDER_CHANGE_ESCALATION_PCT * 100)} percent versus the current value must also be approved by the Plant Head. Every approved change is recorded with date and approver."),
        ]),
        dict(doc_id="SOP-PO-002", title="SOP: Purchase Order Creation and Approval", ext=".pdf", sections=[
            ("Purpose", "Define who may raise and approve purchase orders, and the checks required before a PO is released to a supplier."),
            ("Approval matrix", f"PO value up to INR {inr(pm[0][0])}: {pm[0][1]}. Above INR {inr(pm[0][0])} and up to INR {inr(pm[1][0])}: {pm[1][1]}. Above INR {inr(pm[1][0])}: {pm[2][1]}. "
             "The value is the total of all lines on the PO excluding GST. Splitting a PO to stay under a limit is prohibited."),
            ("Pre-release checks", "Before release confirm that: the supplier is on the approved supplier list; a valid contract exists; the quantity respects MOQ and pack size; "
             "the price matches the contract or an approved revision; and the delivery date respects the supplier lead time."),
            ("Emergency POs", "In a line-stoppage risk the Purchase Manager may give verbal approval. The approval must be confirmed in writing within 4 hours."),
        ]),
        dict(doc_id="SOP-EXP-003", title="SOP: Expediting and Premium Freight", ext=".txt", sections=[
            ("Triggers", "For A items: if a PO is overdue by more than 2 days, the buyer sends an expedite e-mail. If overdue by more than 5 days, the buyer also calls the supplier and informs the Purchase Manager. "
             "For B and C items the thresholds are 5 and 10 days."),
            ("Stock cover rule", "Expedite immediately when remaining stock cover is less than the supplier's expected remaining lead time, regardless of overdue days."),
            ("Premium freight", f"Premium freight up to INR {inr(C.PREMIUM_FREIGHT_LIMIT_INR)} may be approved by the Purchase Manager. Above that amount the Plant Head must approve. "
             "Recover the cost from the supplier where the contract allows it."),
            ("Record keeping", "Log every expedite request with PO number, supplier, promised date, new committed date and reason."),
        ]),
        dict(doc_id="SOP-QUA-004", title="SOP: Supplier Quality Escalation", ext=".docx", sections=[
            ("Measurement", "Supplier quality is measured monthly in PPM = rejected quantity / received quantity x 1,000,000, measured at incoming inspection."),
            ("Escalation levels", "Level 1: PPM above the contract limit in one month - issue a quality alert and request an 8D report within 5 working days. "
             "Level 2: above the limit for two consecutive months - supplier visit and containment (100 percent sorting at supplier end). "
             "Level 3: above the limit for three consecutive months - supplier placed on probation, new business on hold, and termination rights under the contract may be exercised."),
            ("Rejected material", "Rejected goods are tagged and segregated, returned or scrapped within 15 days, and a debit note raised where the contract allows."),
        ]),
        dict(doc_id="SOP-STK-005", title="SOP: Stock-out and Line-Stoppage Escalation", ext=".pdf", sections=[
            ("Alert levels", "Red alert: A item with less than 2 days of stock cover or a confirmed stock-out. Amber alert: A item with less than 5 days of cover, or any item whose cover is below its lead time."),
            ("Actions on red alert", "Inform the Plant Head and the OEM customer's logistics contact the same day, place an emergency PO, arrange premium freight if needed, and review alternative approved sources."),
            ("Daily report", "The planner reviews the daily inventory report by 9:30 each working morning and records actions for every red and amber item."),
        ]),
        dict(doc_id="SOP-SHT-006", title="SOP: Festival and Plant Shutdown Planning", ext=".txt", sections=[
            ("Notice", "Supplier shutdown calendars are collected and the plant shutdown calendar is shared with suppliers at least 30 days before Diwali, Ganesh festival and year-end."),
            ("Pre-build", "For A items, build safety stock of at least 14 days of demand before a shutdown or festival week, subject to Purchase Manager approval of the extra inventory."),
            ("Deliveries", "No deliveries are scheduled during a plant shutdown. POs due in a shutdown window are rescheduled to the first working day afterwards."),
        ]),
    ]
 
 
# ----------------------------------------------------------------------------- e-mails
REASONS = ["heavy rain and road diversions near Pune-Mumbai expressway", "furnace breakdown at our foundry", "shortage of raw material from our steel supplier",
           "labour shortage during the festival week", "a transporter strike in the region", "a tooling repair taking longer than planned"]
DEFECTS = ["burrs on machined surface", "dimensional deviation beyond tolerance", "surface porosity", "thread damage", "rust on parts due to poor packing", "wrong marking on parts"]
BUYERS = [("Rohan Gokhale", "Senior Buyer"), ("Priya Nene", "Purchase Executive")]
 
 
def _fmt(d) -> str:
    return pd.Timestamp(d).strftime("%d-%b-%Y")
 
 
def make_emails(pos: pd.DataFrame, items: pd.DataFrame, sup: pd.DataFrame, rng: np.random.Generator, out_dir: Path) -> list[dict]:
    pos = pos.merge(items[["item_id", "description", "uom"]], on="item_id").merge(sup[["supplier_id", "supplier_name", "contact_person", "contact_email"]], on="supplier_id")
    closed = pos[pos.status == "Closed"].copy()
    closed["delay"] = (closed.actual_receipt_date - closed.promised_date).dt.days
    late, rejected = closed[closed.delay > 3], closed[closed.rejected_qty > 0]
    plan = [("delay", late, 14), ("expedite", late, 10), ("quality", rejected, 12), ("price", closed, 8), ("dispatch", closed, 8), ("payment", closed, 6), ("capacity", closed, 4)]
    manifest: list[dict] = []
    n = 0
    domain = "sahyadri-auto.example.com"
    for topic, pool, k in plan:
        pool = pool if len(pool) >= k else closed
        for r in pool.sample(k, random_state=int(rng.integers(0, 10**6))).itertuples():
            n += 1
            buyer, role = BUYERS[n % 2]
            ours = f"{buyer.split()[0].lower()}.{buyer.split()[1].lower()}@{domain}"
            po = f"{r.po_number} line {r.line_no}"
            item = f"{r.item_id} ({r.description})"
            qty = f"{int(r.order_qty)} {r.uom}"
            if topic == "delay":
                sent = pd.Timestamp(r.promised_date) - pd.Timedelta(days=int(rng.integers(1, 4)))
                new = pd.Timestamp(r.promised_date) + pd.Timedelta(days=int(rng.integers(4, 13)))
                frm, to, subj = r.contact_email, ours, f"Delay in dispatch - {r.po_number}"
                body = (f"Dear {buyer.split()[0]},\n\nWe regret to inform you that dispatch against {po}, item {item}, quantity {qty}, promised for {_fmt(r.promised_date)}, "
                        f"will be delayed. Reason: {rng.choice(REASONS)}. We now expect to dispatch by {_fmt(new)}.\nWe apologise for the inconvenience and will share the e-way bill once the vehicle is loaded.\n\nRegards,\n{r.contact_person}\n{r.supplier_name}")
            elif topic == "expedite":
                sent = pd.Timestamp(r.promised_date) + pd.Timedelta(days=int(rng.integers(3, 8)))
                frm, to, subj = ours, r.contact_email, f"URGENT: Expedite {r.po_number} - {r.item_id}"
                body = (f"Dear {r.contact_person.split()[0]},\n\n{po}, item {item}, quantity {qty}, was due on {_fmt(r.promised_date)} and is now overdue. "
                        f"Our stock cover is critical and a line stoppage at our OEM customer is possible. Please confirm a firm dispatch date by end of day. "
                        f"As per the premium freight clause of our agreement, additional freight due to supplier-side delay will be to your account.\n\nRegards,\n{buyer}\n{role}, {C.COMPANY}")
            elif topic == "quality":
                sent = pd.Timestamp(r.actual_receipt_date) + pd.Timedelta(days=int(rng.integers(1, 4)))
                rej = int(r.rejected_qty)
                frm, to, subj = f"quality@{domain}", r.contact_email, f"Rejection notice - {r.po_number} - {r.item_id}"
                body = (f"Dear {r.contact_person.split()[0]},\n\nIncoming inspection of the lot received on {_fmt(r.actual_receipt_date)} against {po}, item {item}, "
                        f"found {rej} pieces rejected out of {int(r.received_qty)} received. Defect observed: {rng.choice(DEFECTS)}.\n"
                        f"Please submit an 8D report within 5 working days and replace the rejected quantity within 7 days as per the quality clause. Rejected material is tagged and held for your disposition.\n\nRegards,\nQuality Assurance\n{C.COMPANY}")
            elif topic == "price":
                sent = pd.Timestamp(r.po_date)
                pct = int(rng.integers(3, 9))
                frm, to, subj = r.contact_email, ours, f"Request for price revision - {r.item_id}"
                body = (f"Dear {buyer.split()[0]},\n\nDue to a rise in raw material prices over the last quarter, we request a price increase of {pct} percent on item {item}, "
                        f"effective {_fmt(sent + pd.Timedelta(days=30))}. Supporting index data is attached. Please let us know your acceptance.\n\nRegards,\n{r.contact_person}\n{r.supplier_name}")
            elif topic == "dispatch":
                sent = pd.Timestamp(r.actual_receipt_date) - pd.Timedelta(days=1)
                frm, to, subj = r.contact_email, ours, f"Dispatch advice - {r.po_number}"
                body = (f"Dear {buyer.split()[0]},\n\nGoods against {po}, item {item}, quantity {qty}, have been dispatched today. "
                        f"Vehicle LR No. {rng.integers(100000, 999999)}, e-way bill {rng.integers(10**11, 10**12 - 1)}. Expected arrival at your plant: {_fmt(r.actual_receipt_date)}.\n\nRegards,\n{r.contact_person}\n{r.supplier_name}")
            elif topic == "payment":
                sent = pd.Timestamp(r.actual_receipt_date) + pd.Timedelta(days=int(r.payment_terms_days) + int(rng.integers(5, 20)))
                amt = float(str(r.unit_price).replace(",", "").replace("\u20b9", "").replace("Rs.", "")) * float(r.received_qty)
                frm, to, subj = r.contact_email, f"accounts@{domain}", f"Payment reminder - invoice for {r.po_number}"
                body = (f"Dear Accounts Team,\n\nThis is a reminder that payment of about INR {inr(amt)} against {po} (goods received {_fmt(r.actual_receipt_date)}) "
                        f"is overdue as per the agreed {int(r.payment_terms_days)} day payment terms. Please release payment or share the reason for hold.\n\nRegards,\n{r.contact_person}\n{r.supplier_name}")
            else:
                sent = pd.Timestamp(r.po_date)
                frm, to, subj = r.contact_email, ours, f"Capacity constraint for {r.item_id}"
                body = (f"Dear {buyer.split()[0]},\n\nWe can support your current schedule for item {item}, but cannot commit to more than 10 percent above the current monthly volume "
                        f"for the next two months because of limited machine capacity. Please plan accordingly.\n\nRegards,\n{r.contact_person}\n{r.supplier_name}")
            doc_id = f"EML-{n:04d}"
            path = out_dir / "emails" / f"{doc_id}_{topic}_{r.supplier_id}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"From: {frm}\nTo: {to}\nDate: {sent.strftime('%a, %d %b %Y')} 10:{int(rng.integers(10, 59))}\n"
                            f"Subject: {subj}\nMessage-ID: <{doc_id}@{domain}>\n\n{body}\n", encoding="utf-8")
            manifest.append(dict(doc_id=doc_id, doc_type="email", topic=topic, title=subj, supplier_id=r.supplier_id, related_po=r.po_number,
                                 effective_date=sent.date().isoformat(), version=1, supersedes="", file_path=str(path.relative_to(out_dir)), format="txt"))
    return manifest
 
 
# ----------------------------------------------------------------------------- orchestration
def generate_documents(sup: pd.DataFrame, items: pd.DataFrame, pos: pd.DataFrame, rng: np.random.Generator,
                       docs_dir: Path, eval_dir: Path) -> dict:
    manifest: list[dict] = []
    facts: dict[str, dict] = {}
    amended = sorted(rng.choice(sup.supplier_id.to_numpy(), size=min(6, len(sup)), replace=False).tolist())
    contract_exts = [".docx", ".pdf"]
    amend_exts = [".docx", ".pdf", ".txt"]
    for i, s in enumerate(sup.to_dict("records")):
        ext = contract_exts[i % 2]
        doc_id = f"CON-{s['supplier_id']}"
        rel = Path("contracts") / f"{doc_id}_{s['supplier_name'].replace(' ', '_')}{ext}"
        write_document(docs_dir / rel, f"Supply Agreement - {s['supplier_name']}", f"Agreement reference {doc_id}", contract_sections(s))
        manifest.append(dict(doc_id=doc_id, doc_type="contract", topic="supply_agreement", title=f"Supply Agreement - {s['supplier_name']}", supplier_id=s["supplier_id"],
                             related_po="", effective_date=s["contract_start_date"], version=1, supersedes="", file_path=str(rel), format=ext[1:]))
        facts[s["supplier_id"]] = dict(lead_time=s["contract_lead_time_days"], payment_terms=s["payment_terms_days"], penalty=s["delay_penalty_pct_per_week"],
                                       cap=s["penalty_cap_pct"], ppm=s["ppm_limit"], doc_id=doc_id)
        if s["supplier_id"] in amended:
            new = dict(lead_time=s["contract_lead_time_days"] + int(rng.choice([-2, 2, 3])),
                       payment_terms=int(rng.choice([p for p in [30, 45, 60, 90] if p != s["payment_terms_days"]])),
                       penalty=1.0 if s["delay_penalty_pct_per_week"] == 0.5 else 0.5)
            eff = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=int(rng.integers(0, 180)))).date().isoformat()
            aext = amend_exts[len(facts) % 3]
            adoc = f"AMD-{s['supplier_id']}-01"
            arel = Path("contracts") / f"{adoc}_{s['supplier_name'].replace(' ', '_')}{aext}"
            write_document(docs_dir / arel, f"Amendment No. 1 - {s['supplier_name']}", f"Amendment reference {adoc} to {doc_id}", amendment_sections(s, new, eff, doc_id))
            manifest.append(dict(doc_id=adoc, doc_type="amendment", topic="supply_agreement", title=f"Amendment No. 1 - {s['supplier_name']}", supplier_id=s["supplier_id"],
                                 related_po="", effective_date=eff, version=2, supersedes=doc_id, file_path=str(arel), format=aext[1:]))
            facts[s["supplier_id"]].update(lead_time=new["lead_time"], payment_terms=new["payment_terms"], penalty=new["penalty"], doc_id=adoc)
    for sop in sop_documents():
        rel = Path("sops") / f"{sop['doc_id']}{sop['ext']}"
        write_document(docs_dir / rel, sop["title"], f"Document {sop['doc_id']} | {C.COMPANY}", sop["sections"])
        manifest.append(dict(doc_id=sop["doc_id"], doc_type="sop", topic=sop["title"].split(": ")[1], title=sop["title"], supplier_id="", related_po="",
                             effective_date="2024-04-01", version=1, supersedes="", file_path=str(rel), format=sop["ext"][1:]))
    manifest += make_emails(pos, items, sup, rng, docs_dir)
    man = pd.DataFrame(manifest)
    man.to_csv(docs_dir / "doc_manifest.csv", index=False)
 
    # seed questions with known answers for RAG evaluation (Phase 3 extends these)
    qa = []
    names = sup.set_index("supplier_id").supplier_name
    for sid, f in facts.items():
        n = names[sid]
        qa += [
            dict(question=f"What is the contractual lead time for {n}?", expected_answer=f"{f['lead_time']} calendar days", supplier_id=sid, doc_id=f["doc_id"], fact_type="lead_time"),
            dict(question=f"What are the payment terms for {n}?", expected_answer=f"{f['payment_terms']} days from receipt of a correct invoice and acceptance of goods", supplier_id=sid, doc_id=f["doc_id"], fact_type="payment_terms"),
            dict(question=f"What delay penalty applies to {n}?", expected_answer=f"{f['penalty']} percent of delayed goods value per full week, capped at {f['cap']} percent of PO value", supplier_id=sid, doc_id=f["doc_id"], fact_type="delay_penalty"),
            dict(question=f"What is the PPM limit in the contract with {n}?", expected_answer=f"{f['ppm']} PPM", supplier_id=sid, doc_id=f["doc_id"], fact_type="ppm_limit"),
        ]
    pm = C.PO_APPROVAL_MATRIX
    qa += [
        dict(question="Who must approve a purchase order of INR 3,50,000?", expected_answer=pm[1][1], supplier_id="", doc_id="SOP-PO-002", fact_type="sop"),
        dict(question="Who must approve a purchase order of INR 8,00,000?", expected_answer=pm[2][1], supplier_id="", doc_id="SOP-PO-002", fact_type="sop"),
        dict(question="Who approves a reorder point change for an A-class item?", expected_answer=C.REORDER_CHANGE_APPROVER["A"], supplier_id="", doc_id="SOP-INV-001", fact_type="sop"),
        dict(question="What service level is targeted for A-class items?", expected_answer=f"{int(C.SERVICE_LEVELS['A'] * 100)} percent", supplier_id="", doc_id="SOP-INV-001", fact_type="sop"),
        dict(question="How many days of stock cover trigger a red alert for an A item?", expected_answer="Less than 2 days", supplier_id="", doc_id="SOP-STK-005", fact_type="sop"),
        dict(question="Up to what amount can the Purchase Manager approve premium freight?", expected_answer=f"INR {inr(C.PREMIUM_FREIGHT_LIMIT_INR)}", supplier_id="", doc_id="SOP-EXP-003", fact_type="sop"),
    ]
    eval_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(qa).to_csv(eval_dir / "golden_qa_seed.csv", index=False)
    return dict(amended=amended, n_docs=len(man), n_qa=len(qa))
