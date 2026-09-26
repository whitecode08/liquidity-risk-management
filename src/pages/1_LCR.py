"""
LCR Calculator Page
====================
Liquidity Coverage Ratio — 30-day stress horizon.
POJK 42/2015 jo. POJK 19/2024 — minimum 100%.

Run from project root:  streamlit run src/app.py
"""

import json
import math
import pathlib
import pandas as pd
import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────
_SRC_DIR  = pathlib.Path(__file__).resolve().parent.parent  # src/
_ROOT_DIR = _SRC_DIR.parent
_TPL_DIR  = _ROOT_DIR / "template"
_OUT_DIR  = _ROOT_DIR / "output"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

# CSS & branding handled by app.py router

# ── Import engine ─────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, str(_SRC_DIR))
from lcr_engine import fmt_currency
import audit_log as al
import pipeline as pl
from assets import ui
from assets import chart_theme as ct
from assets.theme import COLORS, HQLA_COLORS, LCR_OUTFLOW_COLORS, ratio_status

# ── Hero ──────────────────────────────────────────────────────────────────────
ui.hero("LCR Calculator",
        "30-day liquidity stress test &nbsp;·&nbsp; Upload source files → auto-calculation → OJK report export"
        " &nbsp;·&nbsp; POJK 42/2015 jo. POJK 19/2024 &nbsp;·&nbsp; Minimum 100%",
        "LCR — Liquidity Coverage Ratio", "droplet")

# ── Sidebar ───────────────────────────────────────────────────────────────────
# No manual "Reporting Date" input: the reporting date is not a free choice,
# it's a fact the uploaded files already state in their own `periodeData`
# column. A picker defaulting to "today" with no link to the files let the
# as-of date silently drift from the data's actual date — every tenor/maturity
# calculation still ran, just against the wrong horizon, producing a fully
# plausible but wrong LCR with no error to catch it. Reading it from the files
# removes the chance to get it wrong.
with st.sidebar:
    st.markdown("## Source Files")
    st.markdown(
        "<small>Required: "
        "<code>NeracaHarian</code>, <code>PenempatanBI</code>, <code>SBI</code>, "
        "<code>Tabungan</code>, <code>Giro</code>, <code>Deposito</code>, <code>Pinjaman</code></small>",
        unsafe_allow_html=True,
    )
    files = st.file_uploader(
        "Upload source .xlsx files (NeracaHarian, PenempatanBI, SBI, Tabungan, Giro, Deposito, Pinjaman)",
        type=["xlsx"], accept_multiple_files=True, label_visibility="collapsed", key="lcr_files",
    )

    st.markdown("## OJK Template")
    template_file = st.file_uploader(
        "Template LCR.xlsx (optional — for Excel export)",
        type=["xlsx"], accept_multiple_files=False, label_visibility="collapsed", key="lcr_tpl",
    )

    st.markdown("---")
    st.caption("LCR Calculator v2.1 · POJK 42/2015 jo. 19/2024")

# ── File Detection ────────────────────────────────────────────────────────────
get = lambda kw: next((f for f in (files or []) if kw.lower() in f.name.lower()), None)
file_nrc01 = get("neracaharian"); file_pbi01 = get("penempatanbi"); file_sym01 = get("sbi")
file_tab01 = get("tabungan"); file_gir01 = get("giro"); file_dep01 = get("deposito")
file_krp01 = get("pinjaman")

required_map = {
    "NeracaHarian": (file_nrc01, "NeracaHarian — Neraca Harian / RKA"),
    "PenempatanBI": (file_pbi01, "PenempatanBI — Penempatan di Bank Indonesia"),
    "SBI":          (file_sym01, "SBI — Sertifikat Bank Indonesia"),
    "Tabungan":     (file_tab01, "Tabungan"),
    "Giro":         (file_gir01, "Giro"),
    "Deposito":     (file_dep01, "Deposito"),
    "Pinjaman":     (file_krp01, "Pinjaman — Kredit"),
}
ok_all = all(f is not None for f, _ in required_map.values())

# ── File checklist ────────────────────────────────────────────────────────────
ui.section("Data Completeness Check")
cols_l, cols_r = st.columns(2)
for i, (key, (f, label)) in enumerate(required_map.items()):
    with (cols_l if i % 2 == 0 else cols_r):
        ui.md(ui.file_badge(key, f.name if f else None))

# ── As-of date, derived from the data ─────────────────────────────────────────
asof_date_str, per_file_dates = pl.resolve_asof_date(
    {k: f.getvalue() for k, (f, _l) in required_map.items() if f}
)
date_blocked = False
if not files:
    ui.section("Reporting Date")
    st.caption("Detected automatically from the uploaded files' own `periodeData` — "
               "upload the source files below to see it.")
elif asof_date_str:
    ui.section("Reporting Date")
    st.info(f"**{asof_date_str}** — read from `periodeData` in the uploaded files.",
            icon=":material/event:")
elif per_file_dates:
    # Files uploaded, each reports a date, but they disagree — a genuine data
    # problem (mixed reporting periods), not something a date picker could
    # have caught either. Block rather than silently pick one.
    date_blocked = True
    ui.section("Reporting Date")
    mismatch_df = pd.DataFrame(
        [(k, v) for k, v in per_file_dates.items()], columns=["File", "periodeData"])
    st.error(
        "⚠️ **File yang diupload melaporkan tanggal berbeda-beda.** Semua file "
        "sumber harus untuk posisi laporan yang sama — periksa apakah salah satu "
        "file tertukar dari periode lain.",
        icon=":material/error:",
    )
    st.dataframe(mismatch_df, use_container_width=True, hide_index=True)
else:
    # Files uploaded (or being uploaded) but none of them carry periodeData yet
    # — e.g. still mid-upload, or NeracaHarian-only so far.
    date_blocked = True

# ── Input change detection ────────────────────────────────────────────────────
# file_id changes on every (re-)upload, so replacing a file with a same-named
# one still invalidates the previous result.
if files:
    sig = (asof_date_str, tuple(sorted((f.name, f.file_id) for f in files)))
    if st.session_state.get("lcr_sig") != sig:
        st.session_state["lcr_sig"]     = sig
        st.session_state["lcr_started"] = False
        st.session_state["lcr_results"] = None

st.divider()

# ── Run button ────────────────────────────────────────────────────────────────
col_btn, col_hint = st.columns([1, 3])
with col_btn:
    if st.button("Run LCR Analysis", type="primary", icon=":material/play_arrow:",
                 disabled=not ok_all or date_blocked, use_container_width=True, key="lcr_run"):
        st.session_state["lcr_started"] = True
with col_hint:
    if not ok_all:
        st.warning("Upload all 7 required files to enable analysis.", icon=":material/warning:")
    elif date_blocked:
        st.warning("Resolve the reporting date above to enable analysis.", icon=":material/warning:")

if not st.session_state.get("lcr_started"):
    ui.empty_state("droplet", "No Analysis Yet",
                   "Upload all required files and click <strong>Run LCR Analysis</strong> to begin.")
    st.stop()

# ── Load & process ────────────────────────────────────────────────────────────
if st.session_state.get("lcr_results") is None:
    with st.spinner("Reading & processing data files…"):
        try:
            sources = {key: f.getvalue() for key, (f, _lbl) in required_map.items()}
            st.session_state["lcr_results"] = pl.run_lcr(sources, asof_date_str)
            hasil_lcr = st.session_state["lcr_results"]["lcr"]

            # ── Audit trail ───────────────────────────────────────────────────
            al.record("LCR", "RUN START", "LCR calculation executed",
                      reference=al.REG, detail={"asof": asof_date_str})
            al.record_parameter("LCR", "Reporting date (as-of)", asof_date_str)
            for _key, (_f, _lbl) in required_map.items():
                al.record_file("LCR", _key, _f)
            for _name, _val in (("Total HQLA", hasil_lcr["Total HQLA"]),
                                ("Total Cash Outflow", hasil_lcr["Total Cash Outflow"]),
                                ("Total Cash Inflow", hasil_lcr["Total Cash Inflow"]),
                                ("LCR (%)", hasil_lcr["LCR"])):
                al.record_result("LCR", _name, _val)
            for _r in al.lcr_trace(st.session_state["lcr_results"]).to_dict("records"):
                al.record("LCR", "CALC STEP", f'{_r["Category"]} — {_r["Line Item"]}',
                          reference=f'{_r["Basis"]} ({al.REG})',
                          input_value=_r["Base Amount (IDR)"], factor=_r["Factor"],
                          output_value=_r["Weighted Amount (IDR)"])
        except Exception as e:
            al.record_error("LCR", f"Calculation failed: {type(e).__name__}: {e}")
            st.error(f"Calculation error: {e}", icon=":material/error:")
            st.session_state["lcr_started"] = False
            st.stop()

# ── Render results ────────────────────────────────────────────────────────────
R             = st.session_state["lcr_results"]
hasil_hqla    = R["hqla"]; hasil_outflow = R["outflow"]
hasil_inflow  = R["inflow"]; hasil_lcr = R["lcr"]
asof_date_str = R["asof"]
lcr_val       = hasil_lcr["LCR"]

ui.section(f"Analysis Results · {asof_date_str}")

# Status headline (same status language as the KPI bars)
status   = ratio_status(lcr_val)
lcr_disp = "∞ %" if math.isinf(lcr_val) else f"{lcr_val:.2f}%"
pct_fill = 100 if math.isinf(lcr_val) else min(lcr_val, 200) / 200 * 100
ui.status_panel("LCR Status", lcr_disp, status, fill_pct=pct_fill,
                scale_labels=("0%", "100% (min)", "200%"))

ui.kpi_grid([
    ui.kpi_card("shield", "Total HQLA", fmt_currency(hasil_lcr["Total HQLA"])),
    ui.kpi_card("arrow-up-from-line", "Total Cash Outflow", fmt_currency(hasil_lcr["Total Cash Outflow"])),
    ui.kpi_card("arrow-down-to-line", "Total Cash Inflow", fmt_currency(hasil_lcr["Total Cash Inflow"])),
    ui.kpi_card("gauge", "LCR Ratio", lcr_disp, status),
])
st.caption("Inflow capped at 75% of Total Outflow per Basel/POJK rules. Values in IDR. "
           "Status: ≥110% compliant · 100–110% thin buffer · <100% breach.")

# ── Visualizations ────────────────────────────────────────────────────────────
import altair as alt
ui.section("Visual Insights")
vc1, vc2 = st.columns(2)
with vc1:
    out_data = pd.DataFrame({
        "Category": list(LCR_OUTFLOW_COLORS),
        "Amount": [
            hasil_outflow["Total Outflow Pendanaan Perorangan"],
            hasil_outflow["Total Outflow Pendanaan UMK"],
            hasil_outflow["Total Outflow Pendanaan Korporasi"],
            hasil_outflow["Total Outflow Pendanaan Sektor Publik"],
            hasil_outflow["Total Outflow Pendanaan Lembaga Keuangan"],
            hasil_outflow["Total Outflow Tambahan"],
        ],
    })
    ch1, omitted = ct.hbar(out_data, label="Category", value="Amount", colors=LCR_OUTFLOW_COLORS,
                           title="Cash Outflow Composition")
    if ch1 is not None:
        ct.render(ch1)
    ct.omitted_note(omitted)

with vc2:
    hqla_data = pd.DataFrame({
        "Component": list(HQLA_COLORS),
        "Amount": [
            hasil_hqla["Cash & Cash Equivalents"],
            hasil_hqla["Placement at Central Bank"],
            hasil_hqla["HQLA Level 2"],
        ],
    })
    hqla_plot, omitted = ct.prepare_bar_data(hqla_data, "Amount")
    ch2 = alt.Chart(hqla_plot, title="HQLA Composition").mark_arc(
        innerRadius=62, cornerRadius=3, padAngle=0.01,
    ).encode(
        theta=alt.Theta("Amount:Q"),
        color=alt.Color("Component:N", title=None,
                        scale=alt.Scale(domain=hqla_plot["Component"].tolist(),
                                        range=[HQLA_COLORS[c] for c in hqla_plot["Component"]])),
        tooltip=["Component", alt.Tooltip("Amount:Q", format=",.0f", title="IDR")],
    )
    ct.render(ct.apply_theme(ch2, height=ct.PANEL_CHART_HEIGHT))
    ct.omitted_note(omitted)

# Inflow vs Outflow comparison
io_data = pd.DataFrame({
    "Type": ["Total Outflow", "Total Inflow", "Net Outflow"],
    "Amount": [
        hasil_lcr["Total Cash Outflow"],
        hasil_lcr["Total Cash Inflow"],
        hasil_lcr["Total Cash Outflow"] - hasil_lcr["Total Cash Inflow"],
    ],
})
ch3, _ = ct.hbar(
    io_data, label="Type", value="Amount",
    colors={"Total Outflow": COLORS["accent_red"], "Total Inflow": COLORS["accent_green"],
            "Net Outflow": COLORS["accent_amber"]},
    title="Inflow vs Outflow — 30 Day Stress Horizon", height=ct.STRIP_CHART_HEIGHT,
    hide_zero=False,  # always show all three bars — a zero Total Inflow must
                       # still appear, otherwise Outflow and Net Outflow look
                       # like two outflows with nothing to compare against.
)
if ch3 is not None:
    ct.render(ch3)

st.divider()

# ── Detail tabs ───────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["HQLA", "Cash Outflow", "Cash Inflow"])
with tab1:
    ui.section("High-Quality Liquid Assets (HQLA)")
    st.dataframe(pd.DataFrame({"Component": list(hasil_hqla.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in hasil_hqla.values()]}),
                 use_container_width=True, hide_index=True)

with tab2:
    ui.section("Stressed Cash Outflows — ≤30d Horizon")
    st.dataframe(pd.DataFrame([(k, fmt_currency(v)) for k, v in hasil_outflow.items()],
                              columns=["Component","Amount (IDR)"]),
                 use_container_width=True, hide_index=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Outflow", fmt_currency(hasil_outflow["Total Outflow"]))
    c2.metric("Retail + SME",  fmt_currency(hasil_outflow["Total Outflow Pendanaan Perorangan"] + hasil_outflow["Total Outflow Pendanaan UMK"]))
    c3.metric("Corporate",     fmt_currency(hasil_outflow["Total Outflow Pendanaan Korporasi"]))
    c4.metric("Public Sector", fmt_currency(hasil_outflow["Total Outflow Pendanaan Sektor Publik"]),
              help="Pemda (RKUD) / BUMD / instansi-BLUD. Run-off rates are placeholders "
                   "pending confirmation against POJK 42/2015 jo. 19/2024 Pasal 25.")

with tab3:
    ui.section("Expected Cash Inflows — 30-Day Horizon")
    st.dataframe(pd.DataFrame([(k, fmt_currency(v)) for k, v in hasil_inflow.items()],
                              columns=["Component","Amount (IDR)"]),
                 use_container_width=True, hide_index=True)

# ── Downloads ─────────────────────────────────────────────────────────────────
st.divider()
ui.section("Export & Download")


@st.fragment
def _downloads():
    # Fragment: a download click reruns only this block, not the whole page.
    export_payload = {
        "as_of": asof_date_str,
        "hqla":    {k: float(v) for k, v in hasil_hqla.items()},
        "outflow": {k: float(v) for k, v in hasil_outflow.items()},
        "inflow":  {k: float(v) for k, v in hasil_inflow.items()},
        "lcr": {
            "Total HQLA":         float(hasil_lcr["Total HQLA"]),
            "Total Cash Outflow": float(hasil_lcr["Total Cash Outflow"]),
            "Total Cash Inflow":  float(hasil_lcr["Total Cash Inflow"]),
            "LCR":                None if math.isinf(hasil_lcr["LCR"]) else float(hasil_lcr["LCR"]),
        },
    }
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button("Download Summary (JSON)", icon=":material/download:",
            data=json.dumps(export_payload, indent=2, ensure_ascii=False).encode("utf-8"),
            file_name=f"lcr_summary_{asof_date_str}.json", mime="application/json",
            use_container_width=True, key="lcr_dl_json",
        )
    with dl2:
        if template_file is not None:
            try:
                rpt = pl.lcr_report(template_file.getvalue(), hasil_hqla, hasil_outflow, hasil_inflow, asof_date_str)
                fname = f"LCR_Report_{asof_date_str}.xlsx"
                # Logged when the user actually downloads, not on every rerun.
                st.download_button("Generate & Download OJK Report (Excel)", icon=":material/table_view:",
                    data=rpt, file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True, key="lcr_dl_xlsx",
                    on_click=al.record_export,
                    args=("LCR", fname, len(rpt)),
                    kwargs={"template": getattr(template_file, "name", "Template LCR.xlsx")},
                )
            except Exception as e:
                st.error(f"Failed to generate Excel report: {e}")
        else:
            st.info("Upload **Template LCR.xlsx** in the sidebar to enable Excel export.")


_downloads()

ui.footer("© 2025 — LCR Calculator &nbsp;·&nbsp; Powered by Streamlit &nbsp;·&nbsp; POJK 42/2015 jo. POJK 19/2024")
