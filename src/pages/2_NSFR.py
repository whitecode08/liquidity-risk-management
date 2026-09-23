"""
NSFR Calculator Page
=====================
Net Stable Funding Ratio — 1-year structural liquidity horizon.
POJK No. 20 Tahun 2025 — minimum 100%.

Formula: NSFR = ASF / RSF × 100%
  ASF = Available Stable Funding (weighted liabilities + equity)
  RSF = Required Stable Funding  (weighted assets)

Run from project root:  streamlit run src/app.py
"""

import json
import math
import pathlib
import pandas as pd
import streamlit as st
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
_SRC_DIR  = pathlib.Path(__file__).resolve().parent.parent  # src/
_ROOT_DIR = _SRC_DIR.parent
_OUT_DIR  = _ROOT_DIR / "output"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

# CSS & branding handled by app.py router

import sys
sys.path.insert(0, str(_SRC_DIR))
from nsfr_engine import fmt_currency
import audit_log as al
import pipeline as pl
from assets import ui
from assets import chart_theme as ct
from assets.theme import ASF_COLORS, RSF_COLORS, COLORS, ratio_status

# ── Hero ──────────────────────────────────────────────────────────────────────
ui.hero("NSFR Calculator",
        "1-year structural liquidity assessment &nbsp;·&nbsp; Upload source files → ASF / RSF calculation → OJK report"
        " &nbsp;·&nbsp; POJK No. 20 Tahun 2025 &nbsp;·&nbsp; Minimum 100%",
        "NSFR — Net Stable Funding Ratio", "landmark", "green")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Parameters")
    asof_date     = st.date_input("Reporting Date (As-Of)", value=datetime.today(), key="nsfr_date")
    asof_date_str = asof_date.strftime("%Y-%m-%d")

    st.markdown("## Source Files")
    st.markdown(
        "<small>Required: "
        "<code>NeracaHarian</code>, <code>PenempatanBI</code>, <code>SBI</code>, "
        "<code>Tabungan</code>, <code>Giro</code>, <code>Deposito</code>, <code>Pinjaman</code></small>",
        unsafe_allow_html=True,
    )
    files = st.file_uploader(
        "Upload source .xlsx files (NeracaHarian, PenempatanBI, SBI, Tabungan, Giro, Deposito, Pinjaman)",
        type=["xlsx"], accept_multiple_files=True,
        label_visibility="collapsed", key="nsfr_files",
    )
    st.markdown("## OJK Template")
    template_file = st.file_uploader(
        "Template NSFR.xlsx (optional — for Excel export)",
        type=["xlsx"], accept_multiple_files=False,
        label_visibility="collapsed", key="nsfr_tpl",
    )
    st.markdown("---")
    st.caption("NSFR Calculator v1.0 · POJK No. 20 / 2025")

# ── File detection ────────────────────────────────────────────────────────────
get = lambda kw: next((f for f in (files or []) if kw.lower() in f.name.lower()), None)
file_nrc01 = get("neracaharian"); file_pbi01 = get("penempatanbi"); file_sym01 = get("sbi")
file_tab01 = get("tabungan"); file_gir01 = get("giro"); file_dep01 = get("deposito")
file_krp01 = get("pinjaman")

required_map = {
    "NeracaHarian": (file_nrc01, "NeracaHarian — Balance Sheet"),
    "PenempatanBI": (file_pbi01, "PenempatanBI — Penempatan di Bank Indonesia"),
    "SBI":          (file_sym01, "SBI — Sertifikat Bank Indonesia"),
    "Tabungan":     (file_tab01, "Tabungan"),
    "Giro":         (file_gir01, "Giro"),
    "Deposito":     (file_dep01, "Deposito"),
    "Pinjaman":     (file_krp01, "Pinjaman — Kredit"),
}
ok_all = all(f is not None for f, _ in required_map.values())

# ── Checklist ─────────────────────────────────────────────────────────────────
ui.section("Data Completeness Check")
cols_l, cols_r = st.columns(2)
for i, (key, (f, label)) in enumerate(required_map.items()):
    with (cols_l if i % 2 == 0 else cols_r):
        ui.md(ui.file_badge(key, f.name if f else None))

# ── Session management ────────────────────────────────────────────────────────
# file_id changes on every (re-)upload, so replacing a file with a same-named
# one still invalidates the previous result.
if files:
    sig = (asof_date_str, tuple(sorted((f.name, f.file_id) for f in files)))
    if st.session_state.get("nsfr_sig") != sig:
        st.session_state["nsfr_sig"]     = sig
        st.session_state["nsfr_started"] = False
        st.session_state["nsfr_results"] = None

st.divider()

# ── Run button ────────────────────────────────────────────────────────────────
col_btn, col_hint = st.columns([1, 3])
with col_btn:
    if st.button("Run NSFR Analysis", type="primary", icon=":material/play_arrow:",
                 disabled=not ok_all, use_container_width=True, key="nsfr_run"):
        st.session_state["nsfr_started"] = True
with col_hint:
    if not ok_all:
        st.warning("Upload all 7 required files to enable analysis.", icon=":material/warning:")

if not st.session_state.get("nsfr_started"):
    ui.empty_state("landmark", "No Analysis Yet",
                   "Upload all required files and click <strong>Run NSFR Analysis</strong> to begin.")
    st.stop()

# ── Load & calculate ──────────────────────────────────────────────────────────
if st.session_state.get("nsfr_results") is None:
    with st.spinner("Reading & calculating NSFR…"):
        try:
            sources = {key: f.getvalue() for key, (f, _lbl) in required_map.items()}
            st.session_state["nsfr_results"] = pl.run_nsfr(sources, asof_date_str)
            hasil_nsfr = st.session_state["nsfr_results"]["nsfr"]

            # ── Audit trail ───────────────────────────────────────────────────
            al.record("NSFR", "RUN START", "NSFR calculation executed",
                      reference=al.REG, detail={"asof": asof_date_str})
            al.record_parameter("NSFR", "Reporting date (as-of)", asof_date_str)
            for _key, (_f, _lbl) in required_map.items():
                al.record_file("NSFR", _key, _f)
            for _name, _val in (("Total ASF", hasil_nsfr["Total ASF"]),
                                ("Total RSF", hasil_nsfr["Total RSF"]),
                                ("NSFR (%)", hasil_nsfr["NSFR"])):
                al.record_result("NSFR", _name, _val)
            for _r in al.nsfr_trace(st.session_state["nsfr_results"]).to_dict("records"):
                al.record("NSFR", "CALC STEP", f'{_r["Category"]} — {_r["Line Item"]}',
                          reference=f'{_r["Basis"]} ({al.REG})',
                          input_value=_r["Base Amount (IDR)"], factor=_r["Factor"],
                          output_value=_r["Weighted Amount (IDR)"])
        except Exception as e:
            al.record_error("NSFR", f"Calculation failed: {type(e).__name__}: {e}")
            st.error(f"Calculation error: {e}", icon=":material/error:")
            st.session_state["nsfr_started"] = False
            st.stop()

# ── Render ────────────────────────────────────────────────────────────────────
R             = st.session_state["nsfr_results"]
hasil_asf     = R["asf"]; hasil_rsf = R["rsf"]; hasil_nsfr = R["nsfr"]
asof_date_str = R["asof"]
nsfr_val      = hasil_nsfr["NSFR"]

ui.section(f"Analysis Results · {asof_date_str}")

# Status headline (same status language as the KPI bars)
status    = ratio_status(nsfr_val)
nsfr_disp = "∞ %" if math.isinf(nsfr_val) else f"{nsfr_val:.2f}%"
pct_fill  = 100 if math.isinf(nsfr_val) else min(nsfr_val, 200) / 200 * 100
ui.status_panel("NSFR Status", nsfr_disp, status, fill_pct=pct_fill,
                scale_labels=("0%", "100% (min)", "200%"))

ui.kpi_grid([
    ui.kpi_card("trending-up", "Total ASF", fmt_currency(hasil_nsfr["Total ASF"])),
    ui.kpi_card("trending-down", "Total RSF", fmt_currency(hasil_nsfr["Total RSF"])),
    ui.kpi_card("gauge", "NSFR Ratio", nsfr_disp, status),
])
st.caption("ASF factors: Retail/SME stable 95%, less stable 90%, Corporate 50% per POJK No. 20/2025. "
           "Values in IDR. Status: ≥110% compliant · 100–110% thin buffer · <100% breach.")

# ── Visualizations ────────────────────────────────────────────────────────────
ui.section("Visual Insights")
vc1, vc2 = st.columns(2)
with vc1:
    asf_df = pd.DataFrame({
        "Segment": list(ASF_COLORS),
        "Amount": [
            hasil_asf.get("ASF Retail Stable (95%)", 0),
            hasil_asf.get("ASF SME Stable (95%)", 0),
            hasil_asf.get("ASF Retail Unstable (90%)", 0),
            hasil_asf.get("ASF SME Unstable (90%)", 0),
            hasil_asf.get("ASF Corporate (50%)", 0),
        ],
    })
    ch, omitted = ct.hbar(asf_df, label="Segment", value="Amount", colors=ASF_COLORS,
                          title="ASF by Funding Segment", x_title="IDR (weighted)")
    if ch is not None:
        ct.render(ch)
    ct.omitted_note(omitted)

with vc2:
    rsf_df = pd.DataFrame({
        "Component": list(RSF_COLORS),
        "Amount": [
            hasil_rsf.get("RSF — HQLA (0%)", 0),
            hasil_rsf.get("RSF — Performing Financing <6m (50%)", 0),
            hasil_rsf.get("RSF — Performing Financing 6m-1yr (50%)", 0),
            hasil_rsf.get("RSF — Performing Financing ≥1yr (65%)", 0),
            hasil_rsf.get("RSF — NPF (100%)", 0),
            hasil_rsf.get("RSF — Fixed Assets (100%)", 0),
        ],
    })
    ch, omitted = ct.hbar(rsf_df, label="Component", value="Amount", colors=RSF_COLORS,
                          title="RSF by Asset Category", x_title="IDR (weighted)")
    if ch is not None:
        ct.render(ch)
    ct.omitted_note(omitted)

# ASF vs RSF comparison — horizontal, short labels: nothing to truncate
gap = hasil_nsfr["Total ASF"] - hasil_nsfr["Total RSF"]
comp_df = pd.DataFrame({
    "Metric": ["Available (ASF)", "Required (RSF)"],
    "Amount": [hasil_nsfr["Total ASF"], hasil_nsfr["Total RSF"]],
})
ch, _ = ct.hbar(
    comp_df, label="Metric", value="Amount",
    colors={"Available (ASF)": COLORS["accent_green"], "Required (RSF)": COLORS["accent_blue"]},
    title={"text": "ASF vs RSF — Structural Funding Gap",
           "subtitle": f"{'Surplus' if gap >= 0 else 'Shortfall'}: IDR {fmt_currency(abs(gap))} (ASF − RSF)"},
    x_title="IDR", height=ct.STRIP_CHART_HEIGHT,
)
if ch is not None:
    ct.render(ch)

st.divider()

# ── Detail tabs ───────────────────────────────────────────────────────────────
tab_asf, tab_rsf = st.tabs(["Available Stable Funding (ASF)", "Required Stable Funding (RSF)"])

with tab_asf:
    ui.section("Available Stable Funding — Liabilities & Equity (1-Year View)")
    st.info("ASF represents the portion of liabilities and equity expected to be stable over a 1-year horizon. "
            "Higher ASF factors = more stable funding.", icon=":material/info:")

    # Retail section
    st.markdown("**Retail Funding (Perorangan)**")
    ret_items = {k: v for k, v in hasil_asf.items() if "Retail" in k or "retail" in k.lower()}
    st.dataframe(pd.DataFrame({"Component": list(ret_items.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in ret_items.values()]}),
                 use_container_width=True, hide_index=True)

    st.markdown("**SME Funding (UMK)**")
    umk_items = {k: v for k, v in hasil_asf.items() if "SME" in k or "umk" in k.lower()}
    st.dataframe(pd.DataFrame({"Component": list(umk_items.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in umk_items.values()]}),
                 use_container_width=True, hide_index=True)

    st.markdown("**Corporate Funding (Korporasi)**")
    corp_items = {k: v for k, v in hasil_asf.items() if "Corporate" in k or "Corp" in k}
    st.dataframe(pd.DataFrame({"Component": list(corp_items.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in corp_items.values()]}),
                 use_container_width=True, hide_index=True)

    st.divider()
    st.metric("Total ASF", fmt_currency(hasil_asf["Total ASF"]))

with tab_rsf:
    ui.section("Required Stable Funding — Assets (1-Year View)")
    st.info("RSF represents the portion of assets that must be supported by stable funding. "
            "Higher RSF factors = more stable funding required.", icon=":material/info:")
    st.dataframe(pd.DataFrame({"Component": list(hasil_rsf.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in hasil_rsf.values()]}),
                 use_container_width=True, hide_index=True)
    st.divider()
    st.metric("Total RSF", fmt_currency(hasil_rsf["Total RSF"]))

# ── Downloads ─────────────────────────────────────────────────────────────────
st.divider()
ui.section("Export & Download")


@st.fragment
def _downloads():
    # Fragment: a download click reruns only this block, not the whole page.
    export_payload = {
        "as_of": asof_date_str,
        "asf":   {k: float(v) for k, v in hasil_asf.items()},
        "rsf":   {k: float(v) for k, v in hasil_rsf.items()},
        "nsfr": {
            "Total ASF": float(hasil_nsfr["Total ASF"]),
            "Total RSF": float(hasil_nsfr["Total RSF"]),
            "NSFR":      None if math.isinf(nsfr_val) else float(nsfr_val),
        },
    }
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button("Download Summary (JSON)", icon=":material/download:",
            data=json.dumps(export_payload, indent=2, ensure_ascii=False).encode("utf-8"),
            file_name=f"nsfr_summary_{asof_date_str}.json", mime="application/json",
            use_container_width=True, key="nsfr_dl_json",
        )
    with dl2:
        if template_file is not None:
            try:
                rpt = pl.nsfr_report(template_file.getvalue(), hasil_asf, hasil_rsf, asof_date_str)
                fname = f"NSFR_Report_{asof_date_str}.xlsx"
                # Logged when the user actually downloads, not on every rerun.
                st.download_button("Generate & Download OJK Report (Excel)", icon=":material/table_view:",
                    data=rpt, file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True, key="nsfr_dl_xlsx",
                    on_click=al.record_export,
                    args=("NSFR", fname, len(rpt)),
                    kwargs={"template": getattr(template_file, "name", "Template NSFR.xlsx")},
                )
            except Exception as e:
                st.error(f"Failed to generate Excel report: {e}")
        else:
            st.info("Upload **Template NSFR.xlsx** in the sidebar to enable Excel export.")


_downloads()

ui.footer("© 2025 — NSFR Calculator &nbsp;·&nbsp; Powered by Streamlit &nbsp;·&nbsp; POJK No. 20 Tahun 2025")
