"""
Audit Log — calculation traceability for internal audit.
========================================================

Records, for every session, *how* a reported LCR / NSFR figure was produced:

  · which source file was used, with its SHA-256 fingerprint and size
  · which parameters were applied (reporting date, stress assumptions)
  · every weighting step: base amount × regulatory factor = weighted amount,
    with the POJK rule that sets the factor
  · the final ratio arithmetic
  · every export and every AI summary generated from the results

The derivation tables below are declarative: they restate the factors the
engines apply, and `reconcile()` re-adds the traced lines and compares the
result against the engine's own total. A mismatch means the trace and the
engine have drifted apart, and is reported as a FAIL — so the audit log is a
control over the calculation, not merely a description of it.

The engines themselves are deliberately untouched: calculation rates and logic
must not change without regulatory review.
"""
from __future__ import annotations

import datetime as _dt
import getpass
import hashlib
import io
import json
import platform
import uuid

import pandas as pd
import streamlit as st

# The factors that are still placeholders (Entitas Sektor Publik run-off, RSF on
# encumbered securities) are referenced rather than copied, so the audit trail
# can never disagree with what the engines actually applied.
import lcr_engine
import nsfr_engine

_LOG_KEY = "audit_log_entries"
_RUN_KEY = "audit_run_id"
_START_KEY = "audit_run_started"

# BPD / bank umum konvensional. (Was POJK No. 20 Tahun 2025, which covers
# bank syariah — BUS/UUS — only.)
REG = "POJK 42/2015 jo. 19/2024 (LCR) · POJK 50/2017 jo. 20/2024 (NSFR)"


# ─────────────────────────────── session store ──────────────────────────────
def _store() -> list:
    if _LOG_KEY not in st.session_state:
        st.session_state[_LOG_KEY] = []
    return st.session_state[_LOG_KEY]


def run_id() -> str:
    if _RUN_KEY not in st.session_state:
        st.session_state[_RUN_KEY] = uuid.uuid4().hex[:12].upper()
    return st.session_state[_RUN_KEY]


def started_at() -> str:
    if _START_KEY not in st.session_state:
        st.session_state[_START_KEY] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return st.session_state[_START_KEY]


def operator() -> str:
    try:
        return f"{getpass.getuser()}@{platform.node()}"
    except Exception:
        return "unknown"


def clear() -> None:
    st.session_state[_LOG_KEY] = []
    st.session_state.pop(_RUN_KEY, None)
    st.session_state.pop(_START_KEY, None)


def entry_count() -> int:
    return len(_store())


# ──────────────────────────────── recording ─────────────────────────────────
def record(module: str, event: str, description: str, *, reference: str = "",
           input_value=None, factor=None, output_value=None, detail: dict | None = None) -> None:
    """Append one immutable entry to the session audit trail."""
    log = _store()
    log.append({
        "Seq": len(log) + 1,
        "Timestamp": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Module": module,
        "Event": event,
        "Description": description,
        "Input Value": input_value,
        "Factor": factor,
        "Output Value": output_value,
        "Reference": reference,
        "Detail": json.dumps(detail, default=str) if detail else "",
    })


def record_file(module: str, key: str, file) -> None:
    """Fingerprint an uploaded source file so the run can be reproduced."""
    name, size, digest = "-", None, "-"
    try:
        name = getattr(file, "name", str(file))
        data = file.getvalue() if hasattr(file, "getvalue") else None
        if data is not None:
            size = len(data)
            digest = hashlib.sha256(data).hexdigest()
    except Exception as e:  # never let logging break a calculation
        digest = f"unavailable ({type(e).__name__})"
    record(
        module, "INPUT FILE", f"{key.upper()} — {name}",
        reference="Source data",
        input_value=size,
        detail={"file_key": key, "filename": name, "bytes": size, "sha256": digest},
    )


def record_parameter(module: str, name: str, value) -> None:
    record(module, "PARAMETER", f"{name} = {value}", reference="User input",
           detail={"parameter": name, "value": value})


def record_result(module: str, name: str, value, reference: str = REG) -> None:
    record(module, "RESULT", name, reference=reference, output_value=value)


def record_export(module: str, filename: str, size_bytes: int, template: str = "") -> None:
    record(module, "EXPORT", f"Report generated — {filename}",
           reference=f"OJK template: {template}" if template else "",
           input_value=size_bytes,
           detail={"filename": filename, "bytes": size_bytes, "template": template})


def record_ai(model: str, scope: str, prompt_chars: int, response_chars: int) -> None:
    record("AI Summary", "AI GENERATION", f"{scope} — model `{model}`",
           reference="openmodel.ai gateway",
           detail={"model": model, "scope": scope,
                   "prompt_chars": prompt_chars, "response_chars": response_chars})


def record_error(module: str, message: str) -> None:
    record(module, "ERROR", message, reference="Exception")


# ───────────────────────── derivation specifications ────────────────────────
# (Category, Line item, base key, factor, weighted key or None, rule reference)
# `weighted key is None` means the weighted figure is recomputed as base × factor.

LCR_HQLA_SPEC = [
    ("HQLA", "Cash & cash equivalents", "Cash & Cash Equivalents", 1.00,
     "Level 1 asset — no haircut"),
    ("HQLA", "Placement at Bank Indonesia (SBI + Giro BI net of GWM + Deposit Facility)",
     "Placement at Central Bank", 1.00, "Level 1 asset — no haircut"),
]

LCR_OUTFLOW_SPEC = [
    ("Outflow — Retail", "Retail deposits, stable", "Retail Stable Funding", 0.05,
     "Outflow — Retail Stable (5%)", "Retail stable run-off 5%"),
    ("Outflow — Retail", "Retail deposits, less stable", "Retail Unstable Funding", 0.10,
     "Outflow — Retail Unstable (10%)", "Retail less-stable run-off 10%"),
    ("Outflow — SME", "SME (UMK) deposits, stable", "SME Stable Funding", 0.05,
     "Outflow — SME Stable (5%)", "SME stable run-off 5%"),
    ("Outflow — SME", "SME (UMK) deposits, less stable", "SME Unstable Funding", 0.10,
     "Outflow — SME Unstable (10%)", "SME less-stable run-off 10%"),
    ("Outflow — Corporate", "Operational, LPS covered", "Corp Operational — LPS Covered", 0.05,
     "Corp Operational — LPS Covered (5%)", "Operational deposit, insured 5%"),
    ("Outflow — Corporate", "Operational, not LPS covered", "Corp Operational — Not LPS Covered", 0.25,
     "Corp Operational — Not LPS Covered (25%)", "Operational deposit, uninsured 25%"),
    ("Outflow — Corporate", "Non-operational, LPS covered", "Corp Non-Op — LPS Covered", 0.20,
     "Corp Non-Op — LPS Covered (20%)", "Non-operational deposit, insured 20%"),
    ("Outflow — Corporate", "Non-operational, not LPS covered", "Corp Non-Op — Not LPS Covered", 0.40,
     "Corp Non-Op — Not LPS Covered (40%)", "Non-operational deposit, uninsured 40%"),
    ("Outflow — Retail", "Retail deposits, matured (payable now)", "Retail Matured Deposits", 1.00,
     "Outflow — Retail Matured (100%)", "Contractually matured — full run-off"),
    ("Outflow — SME", "SME (UMK) deposits, matured (payable now)", "SME Matured Deposits", 1.00,
     "Outflow — SME Matured (100%)", "Contractually matured — full run-off"),
    ("Outflow — Corporate", "Corporate deposits, matured (payable now)", "Corp Matured Deposits", 1.00,
     "Corp Matured Deposits (100%)", "Contractually matured — full run-off"),
    # Entitas Sektor Publik factors are PLACEHOLDERS pending confirmation —
    # see the RUNOFF_PSE_* constants in src/lcr_engine.py.
    ("Outflow — Public Sector", "Operational, LPS covered", "PSE Operational — LPS Covered",
     lcr_engine.RUNOFF_PSE_OP_LPS, None, "Entitas Sektor Publik — PERLU KONFIRMASI"),
    ("Outflow — Public Sector", "Operational, not LPS covered", "PSE Operational — Not LPS Covered",
     lcr_engine.RUNOFF_PSE_OP_NONLPS, None, "Entitas Sektor Publik — PERLU KONFIRMASI"),
    ("Outflow — Public Sector", "Non-operational, LPS covered", "PSE Non-Op — LPS Covered",
     lcr_engine.RUNOFF_PSE_NONOP_LPS, None, "Entitas Sektor Publik — PERLU KONFIRMASI"),
    ("Outflow — Public Sector", "Non-operational, not LPS covered", "PSE Non-Op — Not LPS Covered",
     lcr_engine.RUNOFF_PSE_NONOP_NONLPS, None, "Entitas Sektor Publik — PERLU KONFIRMASI"),
    ("Outflow — Public Sector", "Deposits matured (payable now)", "PSE Matured Deposits",
     1.00, None, "Contractually matured — full run-off"),
    ("Outflow — Bank/FI", "Funding from banks & financial institutions", "Bank/FI Funding",
     lcr_engine.RUNOFF_BANK, "Total Outflow Pendanaan Lembaga Keuangan",
     "Financial-institution funding — 100% run-off"),
    ("Outflow — Additional", "Undrawn credit commitments", "Undrawn Credit Commitment", 0.10,
     "Undrawn Credit Commitment (10%)", "Committed undrawn facility 10%"),
    ("Outflow — Additional", "Guarantees issued (contingent)", "Guarantee Contingency", 0.05,
     "Guarantee Contingency (5%)", "Contingent guarantee 5%"),
]

LCR_INFLOW_SPEC = [
    ("Inflow", "Performing counterparty receivables maturing ≤30 days",
     "Counterparty Receivables (<=30d, Performing)", 0.50,
     "Total Inflow Tagihan Counterparty (50%)", "Performing receivable inflow 50%"),
    ("Inflow", "Placement at other banks", "Placement at Other Banks", 0.00,
     "Total Penempatan Dana Bank Lain (0%)", "Interbank placement — 0% recognised"),
]

NSFR_ASF_SPEC = [
    ("ASF — Retail", "Stable, demand & <1yr deposits", "ret_stable_demand", 0.95),
    ("ASF — Retail", "Stable, time deposits <6m", "ret_stable_depo_A", 0.95),
    ("ASF — Retail", "Stable, time deposits 6m–1yr", "ret_stable_depo_B", 0.95),
    ("ASF — Retail", "Stable, time deposits ≥1yr", "ret_stable_depo_C", 1.00),
    ("ASF — Retail", "Less stable, demand & <1yr deposits", "ret_unstable_demand", 0.90),
    ("ASF — Retail", "Less stable, time deposits <6m", "ret_unstable_depo_A", 0.90),
    ("ASF — Retail", "Less stable, time deposits 6m–1yr", "ret_unstable_depo_B", 0.90),
    ("ASF — Retail", "Less stable, time deposits ≥1yr", "ret_unstable_depo_C", 1.00),
    ("ASF — SME", "Stable, demand & <1yr deposits", "umk_stable_demand", 0.95),
    ("ASF — SME", "Stable, time deposits <6m", "umk_stable_depo_A", 0.95),
    ("ASF — SME", "Stable, time deposits 6m–1yr", "umk_stable_depo_B", 0.95),
    ("ASF — SME", "Stable, time deposits ≥1yr", "umk_stable_depo_C", 1.00),
    ("ASF — SME", "Less stable, demand & <1yr deposits", "umk_unstable_demand", 0.90),
    ("ASF — SME", "Less stable, time deposits <6m", "umk_unstable_depo_A", 0.90),
    ("ASF — SME", "Less stable, time deposits 6m–1yr", "umk_unstable_depo_B", 0.90),
    ("ASF — SME", "Less stable, time deposits ≥1yr", "umk_unstable_depo_C", 1.00),
    ("ASF — Corporate", "Operational (demand & savings)", "corp_op", 0.50),
    ("ASF — Corporate", "Non-operational time deposits <6m", "corp_nop_A", 0.50),
    ("ASF — Corporate", "Non-operational time deposits 6m–1yr", "corp_nop_B", 0.50),
    ("ASF — Corporate", "Non-operational time deposits ≥1yr", "corp_nop_C", 1.00),
    # Entitas Sektor Publik (Pemda/BUMD/BLUD) shares the corporate ASF factors
    # and is already included in the corp_* figures above; this line is
    # informational, hence a 0% factor — counting it again would double it.
    ("ASF — Public Sector", "Pemda/BUMD/BLUD funding (included in Corporate above)",
     "Public Sector Funding (Pemda/BUMD/BLUD)", 0.00),
    ("ASF — Bank/FI", "Funding from banks & financial institutions (weighted)",
     "ASF Bank/FI", 1.00),
    ("ASF — Matured", "Deposits already matured (payable now)",
     "Matured Deposits (0% ASF)", 0.00),
    ("ASF — Capital", "Tier 1 capital", "tier1_capital", 1.00),
]

NSFR_RSF_SPEC = [
    ("RSF — HQLA", "Cash (KAS)", "kas", 0.00),
    ("RSF — HQLA", "BI placement (Deposit Facility + Giro BI)", "penempatan_bi", 0.00),
    ("RSF — HQLA", "SBI (unencumbered)", "sbi", 0.00),
    ("RSF — Interbank", "Placement at other banks", "interbank", 0.15),
    ("RSF — Loans", "Performing loans <6m", "perf_A", 0.50),
    ("RSF — Loans", "Performing loans 6m–1yr", "perf_B", 0.50),
    ("RSF — Loans", "Performing loans ≥1yr", "perf_C", 0.65),
    ("RSF — Loans", "Non-performing loans (NPL)", "npl", 1.00),
    ("RSF — Securities", "Non-HQLA securities held", "non_hqla_sb", 0.50),
    # PERLU KONFIRMASI — see RSF_SURAT_BERHARGA_DIAGUNKAN in src/nsfr_engine.py.
    ("RSF — Securities", "SBI pledged as collateral (encumbered)", "sbi_encumbered",
     nsfr_engine.RSF_SURAT_BERHARGA_DIAGUNKAN),
    ("RSF — Other", "Fixed assets & inventory", "fixed", 1.00),
    ("RSF — Other", "Other assets", "other", 1.00),
]


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ───────────────────────────── derivation tables ────────────────────────────
def lcr_trace(lcr_res: dict) -> pd.DataFrame:
    """Full base → factor → weighted derivation for the LCR."""
    hqla, outflow, inflow = lcr_res["hqla"], lcr_res["outflow"], lcr_res["inflow"]
    rows = []

    for cat, line, key, factor, ref in LCR_HQLA_SPEC:
        base = _num(hqla.get(key))
        rows.append({"Category": cat, "Line Item": line, "Base Amount (IDR)": base,
                     "Factor": factor, "Weighted Amount (IDR)": base * factor,
                     "Basis": ref, "Regulation": REG})

    for cat, line, base_key, factor, weighted_key, ref in LCR_OUTFLOW_SPEC:
        base = _num(outflow.get(base_key))
        rows.append({"Category": cat, "Line Item": line, "Base Amount (IDR)": base,
                     "Factor": factor,
                     "Weighted Amount (IDR)": _num(outflow.get(weighted_key, base * factor)),
                     "Basis": ref, "Regulation": REG})

    for cat, line, base_key, factor, weighted_key, ref in LCR_INFLOW_SPEC:
        base = _num(inflow.get(base_key))
        rows.append({"Category": cat, "Line Item": line, "Base Amount (IDR)": base,
                     "Factor": factor,
                     "Weighted Amount (IDR)": _num(inflow.get(weighted_key, base * factor)),
                     "Basis": ref, "Regulation": REG})

    return pd.DataFrame(rows)


def nsfr_trace(nsfr_res: dict) -> pd.DataFrame:
    """Full base → factor → weighted derivation for the NSFR."""
    asf, rsf = nsfr_res["asf"], nsfr_res["rsf"]
    rows = []
    for cat, line, key, factor in NSFR_ASF_SPEC:
        base = _num(asf.get(key))
        rows.append({"Category": cat, "Line Item": line, "Base Amount (IDR)": base,
                     "Factor": factor, "Weighted Amount (IDR)": base * factor,
                     "Basis": f"ASF factor {factor:.0%}", "Regulation": REG})
    for cat, line, key, factor in NSFR_RSF_SPEC:
        base = _num(rsf.get(key))
        rows.append({"Category": cat, "Line Item": line, "Base Amount (IDR)": base,
                     "Factor": factor, "Weighted Amount (IDR)": base * factor,
                     "Basis": f"RSF factor {factor:.0%}", "Regulation": REG})
    return pd.DataFrame(rows)


def ratio_steps(lcr_res: dict | None, nsfr_res: dict | None) -> pd.DataFrame:
    """The final ratio arithmetic, written out step by step."""
    rows = []
    if lcr_res:
        lcr = lcr_res["lcr"]
        hqla_v = _num(lcr.get("Total HQLA"))
        out_v = _num(lcr.get("Total Cash Outflow"))
        in_v = _num(lcr.get("Total Cash Inflow"))
        cap = min(out_v * 0.75, in_v)
        denom = out_v - cap
        rows += [
            {"Ratio": "LCR", "Step": "1. Total HQLA (stock of liquid assets)",
             "Formula": "Σ weighted HQLA", "Value": hqla_v},
            {"Ratio": "LCR", "Step": "2. Total weighted cash outflow (30 days)",
             "Formula": "Σ weighted outflows", "Value": out_v},
            {"Ratio": "LCR", "Step": "3. Total weighted cash inflow (30 days)",
             "Formula": "Σ weighted inflows", "Value": in_v},
            {"Ratio": "LCR", "Step": "4. Inflow cap applied",
             "Formula": "min(inflow, 75% × outflow)", "Value": cap},
            {"Ratio": "LCR", "Step": "5. Net cash outflow (denominator)",
             "Formula": "outflow − capped inflow", "Value": denom},
            {"Ratio": "LCR", "Step": "6. LCR",
             "Formula": "HQLA ÷ net cash outflow × 100", "Value": _num(lcr.get("LCR"))},
            {"Ratio": "LCR", "Step": "7. Regulatory minimum", "Formula": REG, "Value": 100.0},
            {"Ratio": "LCR", "Step": "8. Headroom vs minimum",
             "Formula": "LCR − 100", "Value": _num(lcr.get("LCR")) - 100.0},
        ]
    if nsfr_res:
        nsfr = nsfr_res["nsfr"]
        asf_v = _num(nsfr.get("Total ASF"))
        rsf_v = _num(nsfr.get("Total RSF"))
        rows += [
            {"Ratio": "NSFR", "Step": "1. Total available stable funding (ASF)",
             "Formula": "Σ liabilities × ASF factor", "Value": asf_v},
            {"Ratio": "NSFR", "Step": "2. Total required stable funding (RSF)",
             "Formula": "Σ assets × RSF factor", "Value": rsf_v},
            {"Ratio": "NSFR", "Step": "3. Funding surplus / (gap)",
             "Formula": "ASF − RSF", "Value": asf_v - rsf_v},
            {"Ratio": "NSFR", "Step": "4. NSFR",
             "Formula": "ASF ÷ RSF × 100", "Value": _num(nsfr.get("NSFR"))},
            {"Ratio": "NSFR", "Step": "5. Regulatory minimum", "Formula": REG, "Value": 100.0},
            {"Ratio": "NSFR", "Step": "6. Headroom vs minimum",
             "Formula": "NSFR − 100", "Value": _num(nsfr.get("NSFR")) - 100.0},
        ]
    return pd.DataFrame(rows)


def reconcile(lcr_res: dict | None, nsfr_res: dict | None, tolerance: float = 1.0) -> pd.DataFrame:
    """
    Control check: re-add the traced lines and compare against the engine's own
    totals. Any difference beyond `tolerance` (IDR) is reported as a FAIL.
    """
    rows = []

    def _check(label, traced, engine):
        delta = traced - engine
        rows.append({
            "Check": label,
            "Audit Trace Total": traced,
            "Engine Total": engine,
            "Difference": delta,
            "Status": "PASS" if abs(delta) <= tolerance else "FAIL",
        })

    if lcr_res:
        t = lcr_trace(lcr_res)
        _check("LCR — Total HQLA",
               t[t["Category"] == "HQLA"]["Weighted Amount (IDR)"].sum(),
               _num(lcr_res["lcr"].get("Total HQLA")))
        _check("LCR — Total weighted outflow",
               t[t["Category"].str.startswith("Outflow")]["Weighted Amount (IDR)"].sum(),
               _num(lcr_res["lcr"].get("Total Cash Outflow")))
        _check("LCR — Total weighted inflow",
               t[t["Category"] == "Inflow"]["Weighted Amount (IDR)"].sum(),
               _num(lcr_res["lcr"].get("Total Cash Inflow")))
    if nsfr_res:
        t = nsfr_trace(nsfr_res)
        _check("NSFR — Total ASF",
               t[t["Category"].str.startswith("ASF")]["Weighted Amount (IDR)"].sum(),
               _num(nsfr_res["nsfr"].get("Total ASF")))
        _check("NSFR — Total RSF",
               t[t["Category"].str.startswith("RSF")]["Weighted Amount (IDR)"].sum(),
               _num(nsfr_res["nsfr"].get("Total RSF")))

    return pd.DataFrame(rows)


# ──────────────────────────────── exports ───────────────────────────────────
def events_df() -> pd.DataFrame:
    log = _store()
    if not log:
        return pd.DataFrame(columns=["Seq", "Timestamp", "Module", "Event", "Description",
                                     "Input Value", "Factor", "Output Value", "Reference", "Detail"])
    return pd.DataFrame(log)


def run_summary(lcr_res: dict | None, nsfr_res: dict | None) -> pd.DataFrame:
    rows = [
        ("Audit run ID", run_id()),
        ("Session started", started_at()),
        ("Report generated", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Operator", operator()),
        ("Regulation applied", REG),
        ("LCR as-of date", lcr_res["asof"] if lcr_res else "not run"),
        ("NSFR as-of date", nsfr_res["asof"] if nsfr_res else "not run"),
        ("LCR result", f"{lcr_res['lcr'].get('LCR', 0):.2f}%" if lcr_res else "not run"),
        ("NSFR result", f"{nsfr_res['nsfr'].get('NSFR', 0):.2f}%" if nsfr_res else "not run"),
        ("Audit entries recorded", str(entry_count())),
    ]
    return pd.DataFrame(rows, columns=["Field", "Value"])


def build_workbook(lcr_res: dict | None, nsfr_res: dict | None) -> bytes:
    """Multi-sheet audit pack for submission to internal audit."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        run_summary(lcr_res, nsfr_res).to_excel(xl, sheet_name="Run Summary", index=False)
        events_df().to_excel(xl, sheet_name="Event Log", index=False)
        if lcr_res is not None or nsfr_res is not None:
            ratio_steps(lcr_res, nsfr_res).to_excel(xl, sheet_name="Ratio Arithmetic", index=False)
            reconcile(lcr_res, nsfr_res).to_excel(xl, sheet_name="Reconciliation", index=False)
        if lcr_res:
            lcr_trace(lcr_res).to_excel(xl, sheet_name="LCR Derivation", index=False)
        if nsfr_res:
            nsfr_trace(nsfr_res).to_excel(xl, sheet_name="NSFR Derivation", index=False)

        widths = {"Run Summary": [28, 46], "Event Log": [6, 20, 14, 16, 52, 20, 10, 20, 30, 50],
                  "Ratio Arithmetic": [10, 42, 34, 22],
                  "Reconciliation": [34, 22, 22, 18, 10],
                  "LCR Derivation": [24, 52, 22, 10, 24, 38, 26],
                  "NSFR Derivation": [24, 52, 22, 10, 24, 38, 26]}
        for sheet, cols in widths.items():
            if sheet in xl.book.sheetnames:
                ws = xl.book[sheet]
                for i, w in enumerate(cols, start=1):
                    ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
                ws.freeze_panes = "A2"
    return buf.getvalue()


def build_json(lcr_res: dict | None, nsfr_res: dict | None) -> bytes:
    payload = {
        "run_id": run_id(),
        "session_started": started_at(),
        "exported_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "operator": operator(),
        "regulation": REG,
        "events": _store(),
        "ratio_steps": ratio_steps(lcr_res, nsfr_res).to_dict("records"),
        "reconciliation": reconcile(lcr_res, nsfr_res).to_dict("records"),
        "lcr_derivation": lcr_trace(lcr_res).to_dict("records") if lcr_res else [],
        "nsfr_derivation": nsfr_trace(nsfr_res).to_dict("records") if nsfr_res else [],
    }
    return json.dumps(payload, indent=2, default=str).encode("utf-8")
