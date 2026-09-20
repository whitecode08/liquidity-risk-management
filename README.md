# 💧 Liquidity Risk Management System

A Streamlit-based regulatory compliance tool for calculating the **Liquidity Coverage Ratio (LCR)** and **Net Stable Funding Ratio (NSFR)** in accordance with **POJK No. 20 Tahun 2025** — _Kewajiban Pemenuhan Rasio Kecukupan Likuiditas dan Rasio Pendanaan Stabil Bersih bagi Bank BUS & UUS_.

---

## Project Structure

```
liquidity-risk-management/
├── src/
│   ├── app.py                  # ← Main entry point (Home page)
│   ├── lcr_engine.py           # ← LCR business logic (pure Python, no UI)
│   ├── nsfr_engine.py          # ← NSFR business logic (pure Python, no UI)
│   ├── ai_summary.py           # ← AI Executive Summary (OpenModel / DeepSeek)
│   ├── audit_log.py            # ← Audit trail & calculation derivation tables
│   ├── pages/
│   │   ├── 0_Home.py           # ← Home page
│   │   ├── 1_LCR.py            # ← LCR Calculator page
│   │   ├── 2_NSFR.py           # ← NSFR Calculator page
│   │   ├── 3_AI_Summary.py     # ← AI Executive Summary page
│   │   ├── 4_Stress_Testing.py # ← ILAAP stress testing / survival horizon
│   │   └── 5_Audit_Log.py      # ← Calculation audit trail for internal audit
│   └── assets/
│       └── style.css           # ← Custom banking UI stylesheet
├── .env.example                # ← Template .env
├── README.md
└── .gitignore
```

---

## Data & Secrets — Not in This Repository

`database/`, `template/`, `docs/` and `.env` are **git-ignored**. This is a compliance tool that
handles real customer account balances and deposit records — none of that belongs in version
control, ever, even in a private repo.

| Folder / file     | Why it's ignored                             | What replaces it                                      |
| ----------------- | -------------------------------------------- | ----------------------------------------------------- |
| `database/*.xlsx` | Real customer account & financing data       | Upload via the sidebar file uploader each session     |
| `template/*.xlsx` | OJK reporting templates (large binaries)     | Upload via the sidebar; not read from disk by the app |
| `docs/*.pdf`      | Regulatory reference PDF (large binary)      | Re-download from OJK if needed for reference          |
| `output/*.xlsx`   | Generated reports — may contain real figures | Regenerated on demand; `.gitkeep` keeps the folder    |
| `.env`            | Real `OPENMODEL_API_KEY`                     | Copy `.env.example` → `.env` and fill in your own key |

Cloning this repo gives you working code with **no data and no secrets**. Nothing in `src/`
reads from `database/`, `template/` or `docs/` at import time — every one of them is optional
and only used if you choose to keep local copies for development.

---

## Requirements

- Python 3.10+
- `streamlit`, `pandas`, `numpy`, `openpyxl`, `altair`, `python-dotenv`, `anthropic`

```bash
pip install streamlit pandas numpy openpyxl altair python-dotenv anthropic
```

### AI Executive Summary configuration

The AI page talks to [OpenModel](https://openmodel.ai), a multi-model gateway that speaks the
**Anthropic Messages protocol**, so the official `anthropic` SDK is pointed straight at it.

| Setting         | Value                                                                |
| --------------- | -------------------------------------------------------------------- |
| Base URL        | `https://api.openmodel.ai` (SDK appends `/v1/messages`)              |
| Auth            | `Authorization: Bearer om-…` (`X-Api-Key` also accepted)             |
| Version header  | `anthropic-version: 2023-06-01` (sent by the SDK)                    |
| Model catalogue | `GET https://api.openmodel.ai/web/v1/models` — public, no key needed |

Create an API key at [openmodel.ai](https://openmodel.ai) (keys look like `om-a1f4-…`), copy
`.env.example` to `.env`, and fill it in:

```dotenv
OPENMODEL_API_KEY=om-your-real-key
# optional
OPENMODEL_MODEL=deepseek-v4.1-flash
OPENMODEL_BASE_URL=https://api.openmodel.ai
```

The AI Summary page reads the live model catalogue into a sidebar picker, so the model can be
switched (DeepSeek, Claude, GLM, …) without editing `.env`. Without a valid key the page shows
setup instructions instead of failing silently.

---

## Running the Application

From the **project root** directory:

```bash
streamlit run src/app.py
```

The app opens at `http://localhost:8501`. Use the sidebar navigation to switch between:

- 🏠 **Home** — Overview & file reference
- 💧 **LCR** — Liquidity Coverage Ratio calculator
- 🏦 **NSFR** — Net Stable Funding Ratio calculator
- 🤖 **AI Executive Summary** — Board-level summary of LCR/NSFR results
- 🌩️ **ILAAP Stress Testing** — Survival horizon under stress scenarios
- 📒 **Audit Log** — Calculation trace and audit pack export

---

## Source Files

All source files follow the naming pattern:
`HasilGenerateAllCabang_<code>_<YYYY-MM-DD>.xlsx`

| File Code | Description                                                         | Used In   |
| --------- | ------------------------------------------------------------------- | --------- |
| `nrc01`   | Daily Balance Sheet — sheets: **ASET**, **RANGKUMAN**, **RKA**      | LCR, NSFR |
| `pbi01`   | BI Placement (FASBIS F08, Giro BI F09)                              | LCR, NSFR |
| `sym01`   | SUKBI instrument data (`SedangDiagunkan`, `nominal`)                | LCR, NSFR |
| `tab01`   | Tabungan (savings accounts)                                         | LCR, NSFR |
| `gir01`   | Giro (current accounts)                                             | LCR, NSFR |
| `dep01`   | Deposito (time deposits, with `tanggalJatuhTempo`)                  | LCR, NSFR |
| `krp01`   | Financing / receivables (`tanggalJatuhTempo`, `kualitas`, `jumlah`) | LCR, NSFR |

Upload via the sidebar file uploader. Optionally upload the OJK Excel template for regulatory report export.

---

## LCR Calculation Logic

**Formula:** `LCR = HQLA / (Total Outflow − min(Inflow, 75% × Total Outflow)) × 100%`  
**Minimum required:** 100% per POJK No. 20 Tahun 2025

| Component                | Method                                                                            |
| ------------------------ | --------------------------------------------------------------------------------- |
| **HQLA**                 | Cash + BI Placement (Giro BI net of GWM 3.5% × DPK + FASBIS + SUKBI unencumbered) |
| **Outflow — Retail**     | Stable ≤ IDR 2B → 5%; Unstable → 10%                                              |
| **Outflow — SME (UMK)**  | Stable ≤ IDR 2B → 5%; Unstable → 10%                                              |
| **Outflow — Corporate**  | Op + LPS → 5%; Op + non-LPS → 25%; Non-Op + LPS → 20%; Non-Op + non-LPS → 40%     |
| **Outflow — Additional** | Undrawn financing → 10%; Guarantees → 5%                                          |
| **Inflow**               | Performing counterparty receivables ≤30d → 50%; Other bank placement → 0%         |
| **Inflow cap**           | min(Total Inflow, 75% × Total Outflow)                                            |

---

## NSFR Calculation Logic

**Formula:** `NSFR = ASF / RSF × 100%`  
**Minimum required:** 100% per POJK No. 20 Tahun 2025

### ASF (Available Stable Funding)

| Component                                            | Factor |
| ---------------------------------------------------- | ------ |
| Retail & SME — stable demand deposits (tab, giro)    | 95%    |
| Retail & SME — stable deposits (deposito) all tenors | 95%    |
| Retail & SME — less stable (demand + deposits)       | 90%    |
| Corporate — operational (tab, giro)                  | 50%    |
| Corporate — non-operational deposits                 | 50%    |
| Tier 1 Capital                                       | 100%   |

### RSF (Required Stable Funding)

| Component                                        | Factor |
| ------------------------------------------------ | ------ |
| HQLA (Cash, FASBIS, Giro BI, SUKBI unencumbered) | 0%     |
| Interbank placement                              | 15%    |
| Performing financing < 6 months                  | 50%    |
| Performing financing 6m – 1yr                    | 50%    |
| Performing financing ≥ 1 year                    | 65%    |
| Non-performing financing (NPF, kualitas ≥ 3)     | 100%   |
| Non-HQLA securities (unencumbered)               | 50%    |
| Fixed assets                                     | 100%   |
| Other assets                                     | 100%   |

---

## Exports

| Format                  | Description                                                                      |
| ----------------------- | -------------------------------------------------------------------------------- |
| **JSON Summary**        | Full breakdown of all components + ratio value                                   |
| **Excel Report (LCR)**  | Values mapped into OJK `Template LCR.xlsx`                                       |
| **Excel Report (NSFR)** | Values mapped into OJK `Template NSFR.xlsx`                                      |
| **Audit Pack (Excel)**  | Run summary, event log, ratio arithmetic, reconciliation, LCR & NSFR derivations |
| **Audit Events (CSV)**  | Flat event log for GRC tooling                                                   |
| **Audit Trace (JSON)**  | Machine-readable full trace for retention                                        |

---

## Audit Log

The **Audit Log** page (`src/audit_log.py`) answers the question internal audit always asks:
_how was this number produced?_ It records, for the current session:

| Captured              | Detail                                                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Source files**      | Filename, byte size and **SHA-256 fingerprint** of every uploaded file, so a run can be proven to have used specific inputs |
| **Parameters**        | Reporting (as-of) date and any stress assumptions applied                                                                   |
| **Calculation steps** | Every weighting as `base amount × regulatory factor = weighted amount`, with the rule that sets the factor                  |
| **Ratio arithmetic**  | The final formula written out step by step, including the LCR inflow cap and the headroom against the 100% minimum          |
| **Exports**           | Every OJK report generated, with template name and output size                                                              |
| **AI generations**    | Model, scope and response size for each executive summary                                                                   |
| **Errors**            | Any failed calculation, with exception type                                                                                 |

### Reconciliation control

The derivation tables in `audit_log.py` are **declarative restatements** of the factors the
engines apply. `reconcile()` re-adds the traced line items independently and compares the result
against the engine's own totals (tolerance IDR 1). Every check must read **PASS**.

This makes the audit log a _control over_ the calculation rather than merely a description of it:
if someone edits a factor in an engine without updating the derivation spec, the reconciliation
fails loudly on the Audit Log page instead of silently reporting a wrong number.

The engines are deliberately left untouched by the logging — calculation rates and logic must not
change without regulatory review.

> **Retention:** the trail is session-scoped and held in Streamlit session state. Export the audit
> pack before closing the app; nothing is persisted to disk automatically.

---

## Architecture

```
app.py  (Streamlit entry point / Home)
  ├── pages/1_LCR.py    → imports lcr_engine.py
  └── pages/2_NSFR.py   → imports nsfr_engine.py
```

Business logic is fully separated from UI. To run calculations programmatically without the UI, import directly:

```python
from src.lcr_engine import hqla_calc, lcr_calculation
from src.nsfr_engine import asf_calc, rsf_calc, nsfr_calculation
```

---

## Notes

- The Streamlit app uses file uploads only — nothing needs to be present in `database/`,
  `template/` or `docs/` to run the app. Those folders are git-ignored; keep your own local
  copies for development, or upload files fresh each session.
- `GEMINI_API_KEY` in a pre-existing `.env` is a leftover from before the AI Summary page moved
  to the OpenModel gateway — it is unused by any code in `src/` and can be removed.
- Adjust run-off rates and ASF/RSF factors in the engine files if your bank's internal policy differs from the default POJK framework.
- NSFR Tier 1 capital component requires a capital adequacy report — populate `tier1_capital` in `nsfr_engine.py` accordingly.

---

\*© 2025 — Liquidity Risk Management System
