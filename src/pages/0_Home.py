"""Home page — Overview & navigation."""
import streamlit as st

st.markdown("""
<div class="lcr-hero">
  <div class="badge">💧 LIQUIDITY RISK MANAGEMENT SYSTEM</div>
  <h1>Liquidity Risk Management</h1>
  <p>Regulatory compliance tools for LCR and NSFR &nbsp;·&nbsp; POJK No. 20 Tahun 2025 &nbsp;·&nbsp; Bank BUS &amp; UUS</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="nav-grid">
  <a class="nav-card" href="/lcr" target="_self">
    <div class="nav-icon">💧</div>
    <div class="nav-title">LCR Calculator</div>
    <div class="nav-desc">Liquidity Coverage Ratio — 30-day stress horizon. Upload source files, auto-calculate HQLA, Cash Outflows &amp; Inflows, export OJK report.</div>
    <div class="nav-badge">Min. 100% per POJK</div>
  </a>
  <a class="nav-card" href="/nsfr" target="_self">
    <div class="nav-icon">🏦</div>
    <div class="nav-title">NSFR Calculator</div>
    <div class="nav-desc">Net Stable Funding Ratio — 1-year structural liquidity. Calculate Available vs Required Stable Funding, export OJK report.</div>
    <div class="nav-badge">Min. 100% per POJK</div>
  </a>
  <a class="nav-card" href="/ai-summary" target="_self">
    <div class="nav-icon">🤖</div>
    <div class="nav-title">AI Executive Summary</div>
    <div class="nav-desc">AI-generated board-level summary of your latest LCR and NSFR results (DeepSeek V4.1 Flash).</div>
    <div class="nav-badge">Requires LCR / NSFR run</div>
  </a>
  <a class="nav-card" href="/stress-testing" target="_self">
    <div class="nav-icon">🌩️</div>
    <div class="nav-title">ILAAP Stress Testing</div>
    <div class="nav-desc">Simulate HQLA haircuts, deposit run-offs and inflow shocks to estimate the survival horizon.</div>
    <div class="nav-badge">Requires LCR run</div>
  </a>
  <a class="nav-card" href="/audit-log" target="_self">
    <div class="nav-icon">📒</div>
    <div class="nav-title">Audit Log</div>
    <div class="nav-desc">Traceability for internal audit — source-file fingerprints, every regulatory weighting applied, the ratio arithmetic, and a reconciliation control. Exports as an audit pack.</div>
    <div class="nav-badge">Governance &amp; assurance</div>
  </a>
</div>
""", unsafe_allow_html=True)

st.divider()

st.markdown("""
<div class="ref-box">
  <div class="ref-title">📋 Regulatory Framework — POJK No. 20 Tahun 2025</div>
  <table class="ref-table">
    <thead><tr><th>Ratio</th><th>Full Name</th><th>Horizon</th><th>Minimum</th><th>Applicable to</th></tr></thead>
    <tbody>
      <tr><td><strong>LCR</strong></td><td>Liquidity Coverage Ratio / Rasio Kecukupan Likuiditas</td><td>30 days</td><td>100%</td><td>BUS &amp; UUS</td></tr>
      <tr><td><strong>NSFR</strong></td><td>Net Stable Funding Ratio / Rasio Pendanaan Stabil Bersih</td><td>1 year</td><td>100%</td><td>BUS &amp; UUS</td></tr>
    </tbody>
  </table>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    st.markdown("""
<div class="lcr-card">
  <div class="section-label">LCR — Required Source Files</div>
  <table class="ref-table">
    <thead><tr><th>File</th><th>Description</th></tr></thead>
    <tbody>
      <tr><td><code>NeracaHarian</code></td><td>Daily Balance Sheet (ASET, RANGKUMAN, RKA)</td></tr>
      <tr><td><code>PenempatanBI</code></td><td>BI Placement (FASBIS, Giro BI)</td></tr>
      <tr><td><code>SBI</code></td><td>Sertifikat Bank Indonesia instrument data</td></tr>
      <tr><td><code>Tabungan</code></td><td>Savings accounts</td></tr>
      <tr><td><code>Giro</code></td><td>Current accounts</td></tr>
      <tr><td><code>Deposito</code></td><td>Time deposits</td></tr>
      <tr><td><code>Pinjaman</code></td><td>Loans / receivables</td></tr>
    </tbody>
  </table>
</div>
""", unsafe_allow_html=True)
with col2:
    st.markdown("""
<div class="lcr-card">
  <div class="section-label">NSFR — Required Source Files</div>
  <table class="ref-table">
    <thead><tr><th>File</th><th>Description</th></tr></thead>
    <tbody>
      <tr><td><code>NeracaHarian</code></td><td>Daily Balance Sheet (ASET, RANGKUMAN)</td></tr>
      <tr><td><code>PenempatanBI</code></td><td>BI Placement — for RSF HQLA</td></tr>
      <tr><td><code>SBI</code></td><td>Sertifikat Bank Indonesia — for RSF HQLA</td></tr>
      <tr><td><code>Tabungan</code></td><td>Savings — retail &amp; SME ASF</td></tr>
      <tr><td><code>Giro</code></td><td>Current accounts — retail, SME &amp; corp ASF</td></tr>
      <tr><td><code>Deposito</code></td><td>Time deposits — maturity-bucketed ASF</td></tr>
      <tr><td><code>Pinjaman</code></td><td>Loans — RSF by quality</td></tr>
    </tbody>
  </table>
</div>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="lcr-footer">'
    '© 2025 — Liquidity Risk Management System &nbsp;·&nbsp; Powered by Streamlit &nbsp;·&nbsp; '
    'POJK No. 20 Tahun 2025</div>',
    unsafe_allow_html=True,
)
