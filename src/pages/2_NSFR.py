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
_OUT_DIR  = _ROOT_DIR / "output"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

# CSS & branding handled by app.py router

import sys
sys.path.insert(0, str(_SRC_DIR))
from nsfr_engine import (
    asf_calc, rsf_calc, nsfr_calculation, generate_nsfr_report_excel, fmt_currency,
)
from lcr_engine import safe_read_excel, dpk_organize
import audit_log as al

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="nsfr-hero">
  <div class="badge">🏦 NSFR — NET STABLE FUNDING RATIO</div>
  <h1>NSFR Calculator</h1>
  <p>1-year structural liquidity assessment &nbsp;·&nbsp; Upload source files → ASF / RSF calculation → OJK report
  &nbsp;·&nbsp; POJK No. 20 Tahun 2025 &nbsp;·&nbsp; Minimum 100%</p>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Parameters")
    asof_date     = st.date_input("Reporting Date (As-Of)", value=datetime.today(), key="nsfr_date")
    asof_date_str = asof_date.strftime("%Y-%m-%d")

    st.markdown("## 📂 Source Files")
    st.markdown(
        "<small style='color:#94A3B8;font-weight:500;'>Required: "
        "<code>nrc01</code>, <code>pbi01</code>, <code>sym01</code>, "
        "<code>tab01</code>, <code>gir01</code>, <code>dep01</code>, <code>krp01</code></small>",
        unsafe_allow_html=True,
    )
    files = st.file_uploader(
        "Upload HasilGenerateAllCabang_*.xlsx files",
        type=["xlsx"], accept_multiple_files=True,
        label_visibility="collapsed", key="nsfr_files",
    )
    st.markdown("## 📋 OJK Template")
    template_file = st.file_uploader(
        "Template NSFR.xlsx (optional — for Excel export)",
        type=["xlsx"], accept_multiple_files=False,
        label_visibility="collapsed", key="nsfr_tpl",
    )
    st.markdown("---")
    st.markdown("<p style='font-size:0.68rem;color:#94A3B8;text-align:center;font-weight:600;'>NSFR Calculator v1.0<br/>POJK No. 20 / 2025</p>", unsafe_allow_html=True)

# ── File detection ────────────────────────────────────────────────────────────
get = lambda kw: next((f for f in (files or []) if kw.lower() in f.name.lower()), None)
file_nrc01 = get("nrc01"); file_pbi01 = get("pbi01"); file_sym01 = get("sym01")
file_tab01 = get("tab01"); file_gir01 = get("gir01"); file_dep01 = get("dep01")
file_krp01 = get("krp01")

required_map = {
    "nrc01": (file_nrc01, "nrc01 — Balance Sheet"),
    "pbi01": (file_pbi01, "pbi01 — BI Placement"),
    "sym01": (file_sym01, "sym01 — SUKBI"),
    "tab01": (file_tab01, "tab01 — Tabungan"),
    "gir01": (file_gir01, "gir01 — Giro"),
    "dep01": (file_dep01, "dep01 — Deposito"),
    "krp01": (file_krp01, "krp01 — Financing"),
}
ok_all = all(f is not None for f, _ in required_map.values())

# ── Checklist ─────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Data Completeness Check</div>', unsafe_allow_html=True)
cols_l, cols_r = st.columns(2)
for i, (key, (f, label)) in enumerate(required_map.items()):
    col = cols_l if i % 2 == 0 else cols_r
    status = "ok" if f else "missing"; icon = "✅" if f else "⚠️"; name = f.name if f else "not uploaded"
    with col:
        st.markdown(
            f'<div class="file-badge {status}"><span class="icon">{icon}</span>'
            f'<span class="label">{key}</span><span class="name">{name}</span></div>',
            unsafe_allow_html=True,
        )

# ── Session management ────────────────────────────────────────────────────────
if files:
    sig = (asof_date_str, tuple(sorted([f.name for f in files])))
    if st.session_state.get("nsfr_sig") != sig:
        st.session_state["nsfr_sig"]     = sig
        st.session_state["nsfr_started"] = False
        st.session_state["nsfr_results"] = None

st.divider()

# ── Run button ────────────────────────────────────────────────────────────────
col_btn, col_hint = st.columns([1, 3])
with col_btn:
    if st.button("🚀 Run NSFR Analysis", type="primary", disabled=not ok_all,
                 use_container_width=True, key="nsfr_run"):
        st.session_state["nsfr_started"] = True
with col_hint:
    if not ok_all:
        st.warning("⚠️ Upload all 7 required files to enable analysis.")

if not st.session_state.get("nsfr_started"):
    st.markdown(
        '<div class="lcr-card" style="text-align:center;padding:2.5rem;">'
        '<span style="font-size:2.5rem;">🏦</span>'
        '<h3 style="color:#E2E8F0!important;font-weight:500;margin:0.5rem 0 0.3rem;">No Analysis Yet</h3>'
        '<p style="color:#94A3B8;font-size:0.85rem;">Upload all required files and click '
        '<strong style="color:#6EE7B7">Run NSFR Analysis</strong> to begin.</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# ── Load & calculate ──────────────────────────────────────────────────────────
if st.session_state.get("nsfr_results") is None:
    with st.spinner("Reading & calculating NSFR…"):
        try:
            df_nrc_aset      = safe_read_excel(file_nrc01, sheet_name="ASET")
            df_nrc_rangkuman = safe_read_excel(file_nrc01, sheet_name="RANGKUMAN")
            df_pbi           = safe_read_excel(file_pbi01)
            df_sukbi         = safe_read_excel(file_sym01)
            df_tab           = safe_read_excel(file_tab01)
            df_giro          = safe_read_excel(file_gir01)
            df_depo          = safe_read_excel(file_dep01)
            df_fin           = safe_read_excel(file_krp01)

            # dpk_organize adds jumlahBulanLaporanActive & kategoriNasabah
            df_tab, df_giro, df_depo = dpk_organize(df_tab, df_giro, df_depo)

            hasil_asf  = asf_calc(df_tab, df_giro, df_depo, df_nrc_rangkuman, asof_date_str)
            hasil_rsf  = rsf_calc(df_nrc_aset, df_fin, df_pbi, df_sukbi, df_nrc_rangkuman, asof_date_str)
            hasil_nsfr = nsfr_calculation(hasil_asf, hasil_rsf)

            st.session_state["nsfr_results"] = {
                "asof": asof_date_str,
                "asf":  hasil_asf, "rsf": hasil_rsf, "nsfr": hasil_nsfr,
                "dfs":  {"nrc_aset": df_nrc_aset, "nrc_rangkuman": df_nrc_rangkuman,
                         "tab": df_tab, "giro": df_giro, "depo": df_depo, "fin": df_fin},
            }

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
            st.error(f"❌ Calculation error: {e}")
            st.session_state["nsfr_started"] = False
            st.stop()

# ── Render ────────────────────────────────────────────────────────────────────
R             = st.session_state["nsfr_results"]
hasil_asf     = R["asf"]; hasil_rsf = R["rsf"]; hasil_nsfr = R["nsfr"]
asof_date_str = R["asof"]
nsfr_val      = hasil_nsfr["NSFR"]

st.markdown(f'<div class="section-label">Analysis Results · {asof_date_str}</div>', unsafe_allow_html=True)

# Gauge
if math.isinf(nsfr_val):
    pct_fill = 100; disp = "∞ %"; color = "green"; s_label = "COMPLIANT"
else:
    pct_fill = min(nsfr_val, 200) / 200 * 100
    disp     = f"{nsfr_val:.2f}%"
    color    = "green" if nsfr_val >= 100 else ("amber" if nsfr_val >= 50 else "red")
    s_label  = {"green": "COMPLIANT", "amber": "WATCH", "red": "BREACH"}[color]
s_color = {"green": "#22C55E", "amber": "#F59E0B", "red": "#EF4444"}[color]

st.markdown(f"""
<div class="lcr-gauge-wrap nsfr-gauge" style="border-color:rgba(52,211,153,0.3);">
  <div class="gauge-title">NSFR Status</div>
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
def _kpi(icon, label, value, c):
    return (f'<div class="kpi-card {c}"><div class="top-bar"></div>'
            f'<span class="icon">{icon}</span><div class="value">{value}</div>'
            f'<div class="kpi-label">{label}</div></div>')

nsfr_disp = "∞ %" if math.isinf(nsfr_val) else f"{nsfr_val:.2f}%"
st.markdown(
    f'<div class="kpi-grid">'
    f'{_kpi("📈", "Total ASF", fmt_currency(hasil_nsfr["Total ASF"]), "teal")}'
    f'{_kpi("📉", "Total RSF", fmt_currency(hasil_nsfr["Total RSF"]), "navy")}'
    f'{_kpi("🏦", "NSFR Ratio", nsfr_disp, color)}'
    f'</div>', unsafe_allow_html=True,
)
st.markdown("<small style='color:#94A3B8;font-size:0.72rem;font-weight:500;'>* ASF factors: Retail/SME stable 95%, less stable 90%, Corporate 50% per POJK No. 20/2025. Values in IDR.</small>", unsafe_allow_html=True)

# ── Visualizations ────────────────────────────────────────────────────────────
import altair as alt
_section = lambda t: st.markdown(f'<div class="section-label">{t}</div>', unsafe_allow_html=True)
_section("Visual Insights")
vc1, vc2 = st.columns(2)
with vc1:
    asf_chart_data = pd.DataFrame({
        'Segment': ['Retail Stable', 'Retail Unstable', 'SME Stable', 'SME Unstable', 'Corporate'],
        'Amount': [
            hasil_asf.get('ASF Retail Stable (95%)', 0),
            hasil_asf.get('ASF Retail Unstable (90%)', 0),
            hasil_asf.get('ASF SME Stable (95%)', 0),
            hasil_asf.get('ASF SME Unstable (90%)', 0),
            hasil_asf.get('ASF Corporate (50%)', 0),
        ]
    })
    ch_asf = alt.Chart(asf_chart_data, title='ASF by Funding Segment').mark_bar(
        cornerRadiusTopLeft=8, cornerRadiusTopRight=8
    ).encode(
        x=alt.X('Amount:Q', title='IDR (weighted)', axis=alt.Axis(format='~s')),
        y=alt.Y('Segment:N', sort='-x', title=None),
        color=alt.Color('Segment:N', scale=alt.Scale(scheme='greens'), legend=None),
        tooltip=['Segment', alt.Tooltip('Amount:Q', format=',.0f')]
    ).properties(height=240)
    st.altair_chart(ch_asf, use_container_width=True)

with vc2:
    rsf_items = [
        ('HQLA (0%)', hasil_rsf.get('RSF — HQLA (0%)', 0)),
        ('Financing <6m', hasil_rsf.get('RSF — Performing Financing <6m (50%)', 0)),
        ('Financing 6m-1yr', hasil_rsf.get('RSF — Performing Financing 6m-1yr (50%)', 0)),
        ('Financing ≥1yr', hasil_rsf.get('RSF — Performing Financing ≥1yr (65%)', 0)),
        ('NPF (100%)', hasil_rsf.get('RSF — NPF (100%)', 0)),
        ('Fixed Assets', hasil_rsf.get('RSF — Fixed Assets (100%)', 0)),
    ]
    rsf_chart_data = pd.DataFrame(rsf_items, columns=['Component', 'Amount'])
    ch_rsf = alt.Chart(rsf_chart_data, title='RSF by Asset Category').mark_bar(
        cornerRadiusTopLeft=8, cornerRadiusTopRight=8
    ).encode(
        x=alt.X('Amount:Q', title='IDR (weighted)', axis=alt.Axis(format='~s')),
        y=alt.Y('Component:N', sort='-x', title=None),
        color=alt.Color('Component:N', scale=alt.Scale(scheme='reds'), legend=None),
        tooltip=['Component', alt.Tooltip('Amount:Q', format=',.0f')]
    ).properties(height=240)
    st.altair_chart(ch_rsf, use_container_width=True)

# ASF vs RSF comparison
comp_data = pd.DataFrame({
    'Metric': ['Available Stable Funding (ASF)', 'Required Stable Funding (RSF)'],
    'Amount': [hasil_nsfr['Total ASF'], hasil_nsfr['Total RSF']],
    'Color': ['#22C55E', '#EF4444']
})
ch_comp = alt.Chart(comp_data, title='ASF vs RSF \u2014 Structural Funding Gap').mark_bar(
    cornerRadiusTopLeft=8, cornerRadiusTopRight=8, size=50
).encode(
    x=alt.X('Metric:N', sort=None, title=None),
    y=alt.Y('Amount:Q', title='IDR', axis=alt.Axis(format='~s')),
    color=alt.Color('Color:N', scale=None),
    tooltip=['Metric', alt.Tooltip('Amount:Q', format=',.0f')]
).properties(height=280)
st.altair_chart(ch_comp, use_container_width=True)

st.divider()

# ── Detail tabs ───────────────────────────────────────────────────────────────
tab_asf, tab_rsf, tab_raw = st.tabs(["📈  Available Stable Funding (ASF)", "📉  Required Stable Funding (RSF)", "🔍  Data Preview"])

with tab_asf:
    st.markdown('<div class="section-label">Available Stable Funding — Liabilities & Equity (1-Year View)</div>', unsafe_allow_html=True)
    st.info("ℹ️ ASF represents the portion of liabilities and equity expected to be stable over a 1-year horizon. Higher ASF factors = more stable funding.", icon=None)

    # Retail section
    st.markdown("**🏠 Retail Funding (Perorangan)**")
    ret_items = {k: v for k, v in hasil_asf.items() if "Retail" in k or "retail" in k.lower()}
    st.dataframe(pd.DataFrame({"Component": list(ret_items.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in ret_items.values()]}),
                 use_container_width=True, hide_index=True)

    st.markdown("**🏢 SME Funding (UMK)**")
    umk_items = {k: v for k, v in hasil_asf.items() if "SME" in k or "umk" in k.lower()}
    st.dataframe(pd.DataFrame({"Component": list(umk_items.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in umk_items.values()]}),
                 use_container_width=True, hide_index=True)

    st.markdown("**🏛️ Corporate Funding (Korporasi)**")
    corp_items = {k: v for k, v in hasil_asf.items() if "Corporate" in k or "Corp" in k}
    st.dataframe(pd.DataFrame({"Component": list(corp_items.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in corp_items.values()]}),
                 use_container_width=True, hide_index=True)

    st.divider()
    st.metric("✅ Total ASF", fmt_currency(hasil_asf["Total ASF"]))

with tab_rsf:
    st.markdown('<div class="section-label">Required Stable Funding — Assets (1-Year View)</div>', unsafe_allow_html=True)
    st.info("ℹ️ RSF represents the portion of assets that must be supported by stable funding. Higher RSF factors = more stable funding required.", icon=None)
    st.dataframe(pd.DataFrame({"Component": list(hasil_rsf.keys()),
                               "Amount (IDR)": [fmt_currency(v) for v in hasil_rsf.values()]}),
                 use_container_width=True, hide_index=True)
    st.divider()
    st.metric("✅ Total RSF", fmt_currency(hasil_rsf["Total RSF"]))

with tab_raw:
    st.caption("Inspect raw data for debugging source-file issues.")
    dfs = R["dfs"]
    d1, d2 = st.tabs(["📄 Balance Sheet (nrc01)", "👥 DPK / Financing"])
    with d1:
        st.write("**ASET**");      st.dataframe(dfs["nrc_aset"].head(50),      use_container_width=True)
        st.write("**RANGKUMAN**"); st.dataframe(dfs["nrc_rangkuman"].head(50), use_container_width=True)
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
    st.download_button("⬇️  Download Summary (JSON)",
        data=json.dumps(export_payload, indent=2, ensure_ascii=False).encode("utf-8"),
        file_name=f"nsfr_summary_{asof_date_str}.json", mime="application/json",
        use_container_width=True, key="nsfr_dl_json",
    )
with dl2:
    if template_file is not None:
        try:
            rpt = generate_nsfr_report_excel(template_file, hasil_asf, hasil_rsf, asof_date_str)
            al.record_export("NSFR", f"NSFR_Report_{asof_date_str}.xlsx", len(rpt),
                             template=getattr(template_file, "name", "Template NSFR.xlsx"))
            st.download_button("📊  Generate & Download OJK Report (Excel)",
                data=rpt, file_name=f"NSFR_Report_{asof_date_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True, key="nsfr_dl_xlsx",
            )
        except Exception as e:
            st.error(f"Failed to generate Excel report: {e}")
    else:
        st.info("Upload **Template NSFR.xlsx** in the sidebar to enable Excel export.")


st.markdown(
    '<div class="lcr-footer">© 2025 — NSFR Calculator &nbsp;·&nbsp; Powered by Streamlit &nbsp;·&nbsp; '
    'POJK No. 20 Tahun 2025</div>',
    unsafe_allow_html=True,
)
