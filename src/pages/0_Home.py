"""Home page — Overview & navigation."""
import pathlib
import sys

import streamlit as st

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
from assets import ui  # noqa: E402
from assets.icons import icon  # noqa: E402

ui.hero("Liquidity Risk Management",
        "Regulatory compliance tools for LCR and NSFR &nbsp;·&nbsp; POJK No. 20 Tahun 2025 &nbsp;·&nbsp; Bank BUS &amp; UUS",
        "Liquidity Risk Management System", "droplet")

_CARDS = [
    ("/lcr", "droplet", "LCR Calculator",
     "Liquidity Coverage Ratio — 30-day stress horizon. Upload source files, auto-calculate HQLA, Cash Outflows &amp; Inflows, export OJK report.",
     "Min. 100% per POJK"),
    ("/nsfr", "landmark", "NSFR Calculator",
     "Net Stable Funding Ratio — 1-year structural liquidity. Calculate Available vs Required Stable Funding, export OJK report.",
     "Min. 100% per POJK"),
    ("/ai-summary", "sparkles", "AI Executive Summary",
     "AI-generated board-level summary of your latest LCR and NSFR results (DeepSeek V4.1 Flash).",
     "Requires LCR / NSFR run"),
    ("/stress-testing", "activity", "ILAAP Stress Testing",
     "Simulate HQLA haircuts, deposit run-offs and inflow shocks to estimate the survival horizon.",
     "Requires LCR run"),
    ("/audit-log", "shield-check", "Audit Log",
     "Traceability for internal audit — source-file fingerprints, every regulatory weighting applied, the ratio arithmetic, and a reconciliation control. Exports as an audit pack.",
     "Governance &amp; assurance"),
]
ui.md('<div class="nav-grid">' + "".join(
    f'<a class="nav-card" href="{href}" target="_self"><div class="nav-icon">{icon(ic, 20)}</div>'
    f'<div class="nav-title">{title}</div><div class="nav-desc">{desc}</div>'
    f'<div class="nav-foot"><span class="nav-badge">{badge}</span>{icon("arrow-right", 16)}</div></a>'
    for href, ic, title, desc, badge in _CARDS
) + '</div>')

st.divider()

ui.md(f"""
<div class="ref-box">
  <div class="ref-title">{icon("book-open", 18)} Regulatory Framework — POJK No. 20 Tahun 2025</div>
  <table class="ref-table">
    <thead><tr><th>Ratio</th><th>Full Name</th><th>Horizon</th><th>Minimum</th><th>Applicable to</th></tr></thead>
    <tbody>
      <tr><td><strong>LCR</strong></td><td>Liquidity Coverage Ratio / Rasio Kecukupan Likuiditas</td><td>30 days</td><td>100%</td><td>BUS &amp; UUS</td></tr>
      <tr><td><strong>NSFR</strong></td><td>Net Stable Funding Ratio / Rasio Pendanaan Stabil Bersih</td><td>1 year</td><td>100%</td><td>BUS &amp; UUS</td></tr>
    </tbody>
  </table>
</div>
""")

st.write("")
col1, col2 = st.columns(2)
with col1:
    ui.md("""
<div class="panel">
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
""")
with col2:
    ui.md("""
<div class="panel">
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
""")

ui.footer("© 2025 — Liquidity Risk Management System &nbsp;·&nbsp; Powered by Streamlit &nbsp;·&nbsp; POJK No. 20 Tahun 2025")
