# Agentic AI + RAG for Automobile Supply Chain (Pune auto cluster)
 
Portfolio project built phase by phase. **This is the Phase 2 snapshot** (data + cleaning + EDA).
The full README (architecture, demo, deployment) is written in Phase 8.

 
## Quick start (Python 3.11)
 
```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
 
python -m scm.data_gen.generate_all  # raw (dirty) CSVs + contracts/SOPs/emails
python -m scm.cleaning.clean         # clean CSVs + SQLite + data-quality report
python -m scm.eda.eda                # charts + summary in reports/
python -m pytest -q                  # 10 tests
```
 
## Layout
 
| Path | Purpose |
|---|---|
| `src/scm/config.py` | paths, dates, business rules shared by every phase |
| `src/scm/data_gen/` | master data, simulation, dirt injection, documents |
| `src/scm/cleaning/clean.py` | cleaning pipeline with per-rule counts |
| `src/scm/eda/eda.py` | exploratory analysis and charts |
| `data/raw/` | dirty ERP-style exports |
| `data/docs/` | contracts, amendments, SOPs, emails (.docx/.pdf/.txt) + `doc_manifest.csv` |
| `data/eval/` | seed questions with known answers for RAG evaluation |
| `scripts/check_accounts.py` | checks that the API keys in `.env` work (never prints a key) |
| `reports/` | data-quality report, EDA charts and summary |