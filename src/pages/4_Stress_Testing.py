"""ILAAP Stress Testing & Survival Horizon Analysis."""
import pathlib
import pandas as pd
import streamlit as st
import altair as alt

st.markdown("""
<div class="lcr-hero hero-rose">
  <div class="badge">🌩️ ILAAP — STRESS TESTING</div>
  <h1>Survival Horizon Analysis</h1>
  <p>Simulate severe liquidity shocks, haircut adjustments, and run-off scenarios to determine the bank's survival horizon under stress (Internal Liquidity Adequacy Assessment Process).</p>
</div>
""", unsafe_allow_html=True)

lcr_res = st.session_state.get("lcr_results")
nsfr_res = st.session_state.get("nsfr_results")

if not lcr_res:
    st.warning("⚠️ LCR Results required. Please run the LCR Calculator first to establish a baseline for stress testing.")
    st.stop()

# ── Baseline Data ─────────────────────────────────────────────────────────────
hqla_base = lcr_res["lcr"]["Total HQLA"]
outflow_base = lcr_res["lcr"]["Total Cash Outflow"]
inflow_base = lcr_res["lcr"]["Total Cash Inflow"]

st.markdown('<div class="section-label">Stress Scenario Parameters</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**HQLA Haircuts**")
    hqla_haircut = st.slider("Additional HQLA Depreciation", 0, 50, 10, format="%d%%",
                             help="Simulates market value drop of liquid assets.")
with col2:
    st.markdown("**Deposit Run-offs**")
    retail_stress = st.slider("Retail/SME Extra Run-off", 0, 100, 20, format="%d%%",
                              help="Increase in withdrawal rate for retail and SME deposits.")
    corp_stress = st.slider("Corporate Extra Run-off", 0, 100, 40, format="%d%%",
                            help="Increase in withdrawal rate for corporate funding.")
with col3:
    st.markdown("**Inflow Shocks**")
    inflow_haircut = st.slider("Inflow Reduction", 0, 100, 25, format="%d%%",
                               help="Simulates counterparty default or delayed payments.")

# ── Apply Stress ──────────────────────────────────────────────────────────────
# Stressed HQLA
stressed_hqla = hqla_base * (1 - hqla_haircut/100)

# Stressed Outflow
# We'll approximate the extra outflow based on the base outflow composition
out_retail = lcr_res["outflow"].get("Total Outflow Pendanaan Perorangan", 0) + lcr_res["outflow"].get("Total Outflow Pendanaan UMK", 0)
out_corp = lcr_res["outflow"].get("Total Outflow Pendanaan Korporasi", 0)
out_other = outflow_base - out_retail - out_corp

stressed_out_retail = out_retail * (1 + retail_stress/100)
stressed_out_corp = out_corp * (1 + corp_stress/100)
stressed_outflow = stressed_out_retail + stressed_out_corp + out_other

# Stressed Inflow
stressed_inflow = inflow_base * (1 - inflow_haircut/100)

# Stressed LCR
net_stressed_outflow = max(0, stressed_outflow - min(stressed_inflow, 0.75 * stressed_outflow))
stressed_lcr = (stressed_hqla / net_stressed_outflow * 100) if net_stressed_outflow > 0 else float('inf')

st.divider()

# ── KPI Cards ─────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Stressed Liquidity Position</div>', unsafe_allow_html=True)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Stressed HQLA", f"IDR {stressed_hqla/1e9:,.0f} B", delta=f"-{hqla_haircut}% from base", delta_color="inverse")
k2.metric("Stressed Outflow", f"IDR {stressed_outflow/1e9:,.0f} B", delta=f"+{(stressed_outflow-outflow_base)/max(1, outflow_base)*100:.1f}% from base", delta_color="inverse")
k3.metric("Stressed Inflow", f"IDR {stressed_inflow/1e9:,.0f} B", delta=f"-{inflow_haircut}% from base", delta_color="inverse")
k4.metric("Stressed LCR", f"{stressed_lcr:.1f}%", delta=f"{stressed_lcr - lcr_res['lcr']['LCR']:.1f}%", delta_color="inverse")

# ── Survival Horizon Simulation ───────────────────────────────────────────────
st.markdown('<div class="section-label">Survival Horizon (30-Day Liquidity Depletion)</div>', unsafe_allow_html=True)

# Simulate daily depletion. Assume:
# Outflows are front-loaded (e.g. 40% in week 1, 30% week 2, etc.)
# Inflows are linear.
days = list(range(0, 31))
hqla_daily = []
current_hqla = stressed_hqla

daily_inflow = stressed_inflow / 30
for day in days:
    if day == 0:
        hqla_daily.append(current_hqla)
        continue
    
    # Front-loaded outflow curve: logarithmic decay of intensity
    # Roughly: day 1 is highest, day 30 is lowest
    daily_outflow_weight = (31 - day) / sum(range(1, 31))
    daily_outflow = stressed_outflow * daily_outflow_weight
    
    net_daily_drain = daily_outflow - daily_inflow
    current_hqla -= net_daily_drain
    hqla_daily.append(current_hqla)

df_survival = pd.DataFrame({
    "Day": days,
    "HQLA Balance": hqla_daily,
    "Zero Line": [0] * 31
})

survival_days = next((d for d, h in enumerate(hqla_daily) if h < 0), ">30")

col_chart, col_stats = st.columns([3, 1])

with col_chart:
    chart = alt.Chart(df_survival).mark_area(
        line={'color':'#3B82F6'}, color=alt.Gradient(
            gradient='linear', stops=[alt.GradientStop(color='#3B82F6', offset=0), alt.GradientStop(color='rgba(59,130,246,0)', offset=1)], x1=1, x2=1, y1=1, y2=0
        )
    ).encode(
        x=alt.X('Day:Q', scale=alt.Scale(domain=[0, 30])),
        y=alt.Y('HQLA Balance:Q', title="HQLA (IDR)"),
        tooltip=['Day', alt.Tooltip('HQLA Balance:Q', format=",.0f")]
    ).properties(height=300)
    
    zero_line = alt.Chart(df_survival).mark_line(color='red', strokeDash=[5,5]).encode(
        x='Day:Q', y='Zero Line:Q'
    )
    st.altair_chart(chart + zero_line, use_container_width=True)

with col_stats:
    surv_color = "#22C55E" if str(survival_days) == ">30" or survival_days >= 30 else ("#F59E0B" if survival_days >= 14 else "#EF4444")
    st.markdown(f"""
    <div class="kpi-card" style="border-color:{surv_color}; text-align:center; padding: 2rem 1rem;">
      <div style="font-size:0.8rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px; margin-bottom:0.5rem;">Survival Horizon</div>
      <div style="font-size:3rem; font-weight:800; color:{surv_color}; line-height:1;">{survival_days}</div>
      <div style="font-size:0.9rem; color:var(--text-muted); margin-top:0.5rem;">Days</div>
    </div>
    """, unsafe_allow_html=True)
    st.caption("Survival horizon indicates the number of days the bank can operate before completely exhausting its High-Quality Liquid Assets under the selected stress scenario.")

# NSFR Stress check
if nsfr_res:
    st.divider()
    st.markdown('<div class="section-label">NSFR Structural Stress (1-Year)</div>', unsafe_allow_html=True)
    asf_base = nsfr_res["nsfr"]["Total ASF"]
    rsf_base = nsfr_res["nsfr"]["Total RSF"]
    
    st.info("Applying Retail/Corporate run-off scenarios to 1-year stable funding base. Wholesale funding is assumed to have a higher withdrawal risk in severe structural stress.")
    
    # Simple proxy: extra run-off reduces ASF
    stressed_asf = asf_base * (1 - (retail_stress*0.2 + corp_stress*0.5)/100)
    stressed_nsfr = (stressed_asf / rsf_base * 100) if rsf_base > 0 else float('inf')
    
    nk1, nk2, nk3 = st.columns(3)
    nk1.metric("Stressed ASF", f"IDR {stressed_asf/1e9:,.0f} B", delta=f"{stressed_asf - asf_base:,.0f} IDR", delta_color="inverse")
    nk2.metric("Base RSF", f"IDR {rsf_base/1e9:,.0f} B")
    nk3.metric("Stressed NSFR", f"{stressed_nsfr:.1f}%", delta=f"{stressed_nsfr - nsfr_res['nsfr']['NSFR']:.1f}%", delta_color="inverse")

st.markdown(
    '<div class="lcr-footer">© 2025 — ILAAP Stress Testing Module &nbsp;·&nbsp; Internal management use only.</div>',
    unsafe_allow_html=True,
)
