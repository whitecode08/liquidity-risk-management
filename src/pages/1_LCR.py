"""
LCR Calculator Page
====================
Liquidity Coverage Ratio — 30-day stress horizon.
POJK No. 20 Tahun 2025 — minimum 100%.

Run from project root:  streamlit run src/app.py
"""

import io
import json
import math
import pathlib
import pandas as pd
import streamlit as st
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
_SRC_DIR  = pathlib.Path(__file__).resolve().parent.parent  # src/
_ROOT_DIR = _SRC_DIR.parent
_CSS_FILE = _SRC_DIR / "assets" / "style.css"
_TPL_DIR  = _ROOT_DIR / "template"
_OUT_DIR  = _ROOT_DIR / "output"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

# CSS & branding handled by app.py router

# ── Import engine ─────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, str(_SRC_DIR))
from lcr_engine import (
    hqla_calc, dpk_organize, outflow_retail, outflow_umk, outflow_corp,
    outflow_additional, inflow_counterparty, lcr_calculation,
    generate_report_excel, fmt_currency, safe_read_excel, parse_number_from_str,
)
import audit_log as al

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="lcr-hero">
  <div class="badge">💧 LCR — LIQUIDITY COVERAGE RATIO</div>
  <h1>LCR Calculator</h1>
  <p>30-day liquidity stress test &nbsp;·&nbsp; Upload source files → auto-calculation → OJK report export
  &nbsp;·&nbsp; POJK No. 20 Tahun 2025 &nbsp;·&nbsp; Minimum 100%</p>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Parameters")
    asof_date     = st.date_input("Reporting Date (As-Of)", value=datetime.today(), key="lcr_date")
    asof_date_str = asof_date.strftime("%Y-%m-%d")

    st.markdown("## 📂 Source Files")
    st.markdown(
        "<small style='color:#94A3B8;font-weight:500;'>Required: "
        "<code>NeracaHarian</code>, <code>PenempatanBI</code>, <code>SBI</code>, "
        "<code>Tabungan</code>, <code>Giro</code>, <code>Deposito</code>, <code>Pinjaman</code></small>",
        unsafe_allow_html=True,
    )
    files = st.file_uploader(
        "Upload source .xlsx files (NeracaHarian, PenempatanBI, SBI, Tabungan, Giro, Deposito, Pinjaman)",
        type=["xlsx"], accept_multiple_files=True, label_visibility="collapsed", key="lcr_files",
    )

    st.markdown("## 📋 OJK Template")
    template_file = st.file_uploader(
        "Template LCR.xlsx (optional — for Excel export)",
        type=["xlsx"], accept_multiple_files=False, label_visibility="collapsed", key="lcr_tpl",
    )

    st.markdown("---")
    st.markdown("<p style='font-size:0.68rem;color:#94A3B8;text-align:center;font-weight:600;'>LCR Calculator v2.1<br/>POJK No. 20 / 2025</p>", unsafe_allow_html=True)

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
st.markdown('<div class="section-label">Data Completeness Check</div>', unsafe_allow_html=True)
cols_l, cols_r = st.columns(2)
for i, (key, (f, label)) in enumerate(required_map.items()):
    col = cols_l if i % 2 == 0 else cols_r
    status = "ok" if f else "missing"
    icon   = "✅" if f else "⚠️"
    name   = f.name if f else "not uploaded"
    with col:
        st.markdown(
            f'<div class="file-badge {status}"><span class="icon">{icon}</span>'
            f'<span class="label">{key}</span><span class="name">{name}</span></div>',
            unsafe_allow_html=True,
        )

# ── Input change detection ────────────────────────────────────────────────────
if files:
    sig = (asof_date_str, tuple(sorted([f.name for f in files])))
    if st.session_state.get("lcr_sig") != sig:
        st.session_state["lcr_sig"]     = sig
        st.session_state["lcr_started"] = False
        st.session_state["lcr_results"] = None

st.divider()

# ── Run button ────────────────────────────────────────────────────────────────
col_btn, col_hint = st.columns([1, 3])
with col_btn:
    if st.button("🚀 Run LCR Analysis", type="primary", disabled=not ok_all, use_container_width=True, key="lcr_run"):
        st.session_state["lcr_started"] = True
with col_hint:
    if not ok_all:
        st.warning("⚠️ Upload all 7 required files to enable analysis.")

if not st.session_state.get("lcr_started"):
    st.markdown(
        '<div class="lcr-card" style="text-align:center;padding:2.5rem;">'
        '<span style="font-size:2.5rem;">💧</span>'
        '<h3 style="color:#E2E8F0!important;font-weight:500;margin:0.5rem 0 0.3rem;">No Analysis Yet</h3>'
        '<p style="color:#94A3B8;font-size:0.85rem;">Upload all required files and click '
        '<strong style="color:#60A5FA">Run LCR Analysis</strong> to begin.</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# ── Load & process ────────────────────────────────────────────────────────────
if st.session_state.get("lcr_results") is None:
    with st.spinner("Reading & processing data files…"):
        try:
            df_nrc_aset      = safe_read_excel(file_nrc01, sheet_name="ASET")
            df_nrc_rangkuman = safe_read_excel(file_nrc01, sheet_name="RANGKUMAN")
            df_rka           = safe_read_excel(file_nrc01, sheet_name="RKA")
            df_pbi           = safe_read_excel(file_pbi01)
            df_sukbi         = safe_read_excel(file_sym01)
            df_tab           = safe_read_excel(file_tab01)
            df_giro          = safe_read_excel(file_gir01)
            df_depo          = safe_read_excel(file_dep01)
            df_fin           = safe_read_excel(file_krp01)

            df_tab, df_giro, df_depo = dpk_organize(df_tab, df_giro, df_depo)
            hasil_hqla  = hqla_calc(df_nrc_aset, df_nrc_rangkuman, df_pbi, df_sukbi)
            out_retail  = outflow_retail(df_tab, df_giro, df_depo, asof_date_str)
            out_umk     = outflow_umk(df_tab, df_giro, df_depo, asof_date_str)
            out_corp    = outflow_corp(df_tab, df_giro, df_depo, asof_date_str)
            out_add     = outflow_additional(df_rka)
            hasil_outflow = {
                **out_retail, **out_umk, **out_corp, **out_add,
                "Total Outflow": (
                    out_retail["Total Outflow Pendanaan Perorangan"]
                    + out_umk["Total Outflow Pendanaan UMK"]
                    + out_corp["Total Outflow Pendanaan Korporasi"]
                    + out_add["Total Outflow Tambahan"]
                ),
            }
            inflow = inflow_counterparty(df_fin, df_nrc_aset, asof_date_str)
            hasil_inflow = {**inflow, "Total Cash Inflow": inflow["Total Inflow Tagihan Counterparty (50%)"]}
            hasil_lcr = lcr_calculation(
                hasil_hqla,
                {k: hasil_outflow[k] for k in
                 ["Total Outflow Pendanaan Perorangan","Total Outflow Pendanaan UMK",
                  "Total Outflow Pendanaan Korporasi","Total Outflow Tambahan"]},
                hasil_inflow,
            )
            st.session_state["lcr_results"] = {
                "asof": asof_date_str,
                "dfs":  {"nrc_aset": df_nrc_aset, "nrc_rangkuman": df_nrc_rangkuman,
                         "rka": df_rka, "tab": df_tab, "giro": df_giro, "depo": df_depo, "fin": df_fin},
                "hqla": hasil_hqla, "outflow": hasil_outflow,
                "inflow": hasil_inflow, "lcr": hasil_lcr,
            }

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
            st.error(f"❌ Calculation error: {e}")
            st.session_state["lcr_started"] = False
            st.stop()

# ── Render results ────────────────────────────────────────────────────────────
R             = st.session_state["lcr_results"]
hasil_hqla    = R["hqla"]; hasil_outflow = R["outflow"]
hasil_inflow  = R["inflow"]; hasil_lcr = R["lcr"]
asof_date_str = R["asof"]
lcr_val       = hasil_lcr["LCR"]

st.markdown(f'<div class="section-label">Analysis Results · {asof_date_str}</div>', unsafe_allow_html=True)

# Gauge
if math.isinf(lcr_val):
    pct_fill = 100; disp = "∞ %"; color = "green"; s_label = "COMPLIANT"
else:
    pct_fill = min(lcr_val, 200) / 200 * 100
    disp     = f"{lcr_val:.2f}%"
    color    = "green" if lcr_val >= 100 else ("amber" if lcr_val >= 50 else "red")
    s_label  = {"green": "COMPLIANT", "amber": "WATCH", "red": "BREACH"}[color]
s_color = {"green": "#22C55E", "amber": "#F59E0B", "red": "#EF4444"}[color]

st.markdown(f"""
<div class="lcr-gauge-wrap">
  <div class="gauge-title">LCR Status</div>
  <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.5rem;">
    <span style="font-size:1.8rem;font-weight:800;color:#fff;">{disp}</span>
    <span style="background:{s_color}22;border:1px solid {s_color}66;color:{s_color};
                 border-radius:20px;padding:0.15rem 0.7rem;font-size:0.7rem;font-weight:700;
                 letter-spacing:0.1em;">{s_label}</span>
  </div>
  <div class="gauge-track"><div class="gauge-fill {color}" style="width:{pct_fill:.1f}%;"></div></div>
  <div class="gauge-labels"><span>0%</span><span>100% (min)</span><span>200%</span></div>
</div>""", unsafe_allow_html=True)

# KPI cards
lcr_disp = "∞ %" if math.isinf(lcr_val) else f"{lcr_val:.2f}%"
def _kpi(icon, label, value, c):
    return (f'<div class="kpi-card {c}"><div class="top-bar"></div>'
            f'<span class="icon">{icon}</span><div class="value">{value}</div>'
            f'<div class="kpi-label">{label}</div></div>')

st.markdown(
    f'<div class="kpi-grid">'
    f'{_kpi("🏦","Total HQLA", fmt_currency(hasil_lcr["Total HQLA"]), "blue")}'
    f'{_kpi("📤","Total Cash Outflow", fmt_currency(hasil_lcr["Total Cash Outflow"]), "navy")}'
    f'{_kpi("📥","Total Cash Inflow", fmt_currency(hasil_lcr["Total Cash Inflow"]), "teal")}'
    f'{_kpi("📊","LCR Ratio", lcr_disp, color)}'
    f'</div>', unsafe_allow_html=True,
)
st.markdown("<small style='color:#94A3B8;font-size:0.72rem;font-weight:500;'>* Inflow capped at 75% of Total Outflow per Basel/POJK rules. Values in IDR.</small>", unsafe_allow_html=True)

# ── Visualizations ────────────────────────────────────────────────────────────
import altair as alt
_section = lambda t: st.markdown(f'<div class="section-label">{t}</div>', unsafe_allow_html=True)
_section("Visual Insights")
vc1, vc2 = st.columns(2)
with vc1:
    out_data = pd.DataFrame({
        'Category': ['Retail', 'SME (UMK)', 'Corporate', 'Additional'],
        'Amount': [
            hasil_outflow['Total Outflow Pendanaan Perorangan'],
            hasil_outflow['Total Outflow Pendanaan UMK'],
            hasil_outflow['Total Outflow Pendanaan Korporasi'],
            hasil_outflow['Total Outflow Tambahan'],
        ]
    })
    ch1 = alt.Chart(out_data, title='Cash Outflow Composition').mark_bar(
        cornerRadiusTopLeft=8, cornerRadiusTopRight=8
    ).encode(
        x=alt.X('Amount:Q', title='IDR', axis=alt.Axis(format='~s')),
        y=alt.Y('Category:N', sort='-x', title=None),
        color=alt.Color('Category:N', scale=alt.Scale(scheme='blues'), legend=None),
        tooltip=['Category', alt.Tooltip('Amount:Q', format=',.0f')]
    ).properties(height=220)
    st.altair_chart(ch1, use_container_width=True)

with vc2:
    hqla_data = pd.DataFrame({
        'Component': ['Cash', 'BI Placement', 'HQLA Level 2'],
        'Amount': [
            hasil_hqla['Cash & Cash Equivalents'],
            hasil_hqla['Placement at Central Bank'],
            hasil_hqla['HQLA Level 2'],
        ]
    })
    ch2 = alt.Chart(hqla_data, title='HQLA Composition').mark_arc(innerRadius=50, cornerRadius=4).encode(
        theta=alt.Theta('Amount:Q'),
        color=alt.Color('Component:N', scale=alt.Scale(scheme='teals'), legend=alt.Legend(orient='bottom')),
        tooltip=['Component', alt.Tooltip('Amount:Q', format=',.0f')]
    ).properties(height=220)
    st.altair_chart(ch2, use_container_width=True)

# Inflow vs Outflow comparison
io_data = pd.DataFrame({
    'Type': ['Total Outflow', 'Total Inflow', 'Net Outflow'],
    'Amount': [
        hasil_lcr['Total Cash Outflow'],
        hasil_lcr['Total Cash Inflow'],
        hasil_lcr['Total Cash Outflow'] - hasil_lcr['Total Cash Inflow'],
    ],
    'Color': ['#EF4444', '#22C55E', '#F59E0B']
})
ch3 = alt.Chart(io_data, title='Inflow vs Outflow — 30 Day Stress Horizon').mark_bar(
    cornerRadiusTopLeft=8, cornerRadiusTopRight=8
).encode(
    x=alt.X('Type:N', sort=None, title=None),
    y=alt.Y('Amount:Q', title='IDR', axis=alt.Axis(format='~s')),
    color=alt.Color('Color:N', scale=None),
    tooltip=['Type', alt.Tooltip('Amount:Q', format=',.0f')]
).properties(height=250)
st.altair_chart(ch3, use_container_width=True)

st.divider()

# ── Detail tabs ───────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["🏦  HQLA", "📤  Cash Outflow", "📥  Cash Inflow", "🔍  Data Preview"])

import pandas as pd
with tab1:
    st.markdown('<div class="section-label">High-Quality Liquid Assets (HQLA)</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame({"Component": list(hasil_hqla.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in hasil_hqla.values()]}),
                 use_container_width=True, hide_index=True)

with tab2:
    st.markdown('<div class="section-label">Stressed Cash Outflows — ≤30d Horizon</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([(k, fmt_currency(v)) for k, v in hasil_outflow.items()],
                              columns=["Component","Amount (IDR)"]),
                 use_container_width=True, hide_index=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Outflow", fmt_currency(hasil_outflow["Total Outflow"]))
    c2.metric("Retail + SME",  fmt_currency(hasil_outflow["Total Outflow Pendanaan Perorangan"] + hasil_outflow["Total Outflow Pendanaan UMK"]))
    c3.metric("Corporate",     fmt_currency(hasil_outflow["Total Outflow Pendanaan Korporasi"]))

with tab3:
    st.markdown('<div class="section-label">Expected Cash Inflows — 30-Day Horizon</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([(k, fmt_currency(v)) for k, v in hasil_inflow.items()],
                              columns=["Component","Amount (IDR)"]),
                 use_container_width=True, hide_index=True)

with tab4:
    st.caption("Inspect raw data columns to debug source-file mismatches.")
    dfs = R["dfs"]
    d1, d2 = st.tabs(["📄 NeracaHarian Sheets", "👥 DPK / Financing"])
    with d1:
        st.write("**ASET**");      st.dataframe(dfs["nrc_aset"].head(50),      use_container_width=True)
        st.write("**RANGKUMAN**"); st.dataframe(dfs["nrc_rangkuman"].head(50), use_container_width=True)
        st.write("**RKA**");       st.dataframe(dfs["rka"].head(50),           use_container_width=True)
    with d2:
        st.write("**TAB**");  st.dataframe(dfs["tab"].head(30),  use_container_width=True)
        st.write("**GIRO**"); st.dataframe(dfs["giro"].head(30), use_container_width=True)
        st.write("**DEPO**"); st.dataframe(dfs["depo"].head(30), use_container_width=True)
        st.write("**FIN**");  st.dataframe(dfs["fin"].head(30),  use_container_width=True)

# ── Downloads ─────────────────────────────────────────────────────────────────
st.divider()
st.markdown('<div class="section-label">Export & Download</div>', unsafe_allow_html=True)

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
    st.download_button("⬇️  Download Summary (JSON)",
        data=json.dumps(export_payload, indent=2, ensure_ascii=False).encode("utf-8"),
        file_name=f"lcr_summary_{asof_date_str}.json", mime="application/json",
        use_container_width=True, key="lcr_dl_json",
    )
with dl2:
    if template_file is not None:
        try:
            rpt = generate_report_excel(template_file, hasil_hqla, hasil_outflow, hasil_inflow, asof_date_str)
            al.record_export("LCR", f"LCR_Report_{asof_date_str}.xlsx", len(rpt),
                             template=getattr(template_file, "name", "Template LCR.xlsx"))
            st.download_button("📊  Generate & Download OJK Report (Excel)",
                data=rpt, file_name=f"LCR_Report_{asof_date_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True, key="lcr_dl_xlsx",
            )
        except Exception as e:
            st.error(f"Failed to generate Excel report: {e}")
    else:
        st.info("Upload **Template LCR.xlsx** in the sidebar to enable Excel export.")


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="lcr-footer">© 2025 — LCR Calculator &nbsp;·&nbsp; Powered by Streamlit &nbsp;·&nbsp; '
    'POJK No. 20 Tahun 2025</div>',
    unsafe_allow_html=True,
)
