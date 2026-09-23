"""
ILAAP Stress Testing — Survival Period Monitoring
====================================================
Full regulatory implementation per SEOJK No. 26/SEOJK.03/2025 (ILAAP):
  - Modul 1: Available HQLA (Total HQLA − GWM − PLM − BI-sourced liquidity)
  - Modul 2: Survival Period Monitoring (19-bucket cash-flow ladder,
    official stress scenarios, NO 75% LCR inflow cap per §10.21)

This replaces the previous slider-based approximate simulation, which used a
generic front-loaded decay curve rather than the bank's actual transaction
data. All figures here are derived from the same source files already
uploaded on the LCR Calculator page (no new upload needed) — run LCR first.

See docs/SPEK_MODUL_ILAAP.md for the full specification this implements.
"""
import pathlib
import sys

import pandas as pd
import streamlit as st
import altair as alt

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from lcr_engine import fmt_currency  # noqa: E402
from ilaap import survival_period as sp  # noqa: E402
from ilaap import data_contract  # noqa: E402
from ilaap import audit as ilaap_audit  # noqa: E402
from ilaap.available_hqla import available_hqla_calc  # noqa: E402
import audit_log as al  # noqa: E402

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="lcr-hero hero-rose">
  <div class="badge">🌩️ ILAAP — SURVIVAL PERIOD MONITORING</div>
  <h1>Stress Testing (ILAAP)</h1>
  <p>Available HQLA &amp; 19-bucket cash-flow ladder per SEOJK No. 26/SEOJK.03/2025 —
  no LCR 75% inflow cap, official stress scenarios, independent reconciliation.</p>
</div>
""", unsafe_allow_html=True)

lcr_res = st.session_state.get("lcr_results")
if not lcr_res:
    st.warning("⚠️ LCR Results required. Please run the LCR Calculator first — "
               "this page reuses its uploaded data (NeracaHarian, Tabungan, Giro, "
               "Deposito, Pinjaman) to build the transaction ledger.")
    st.stop()

asof_date_str = lcr_res["asof"]
dfs = lcr_res["dfs"]
df_tab, df_giro, df_depo, df_fin, df_rka = dfs["tab"], dfs["giro"], dfs["depo"], dfs["fin"], dfs["rka"]
dpk_total = (df_tab["jumlahBulanLaporanActive"].sum()
             + df_giro["jumlahBulanLaporanActive"].sum()
             + df_depo["jumlahBulanLaporanActive"].sum())

buckets = sp.load_time_buckets()
scenarios = sp.load_stress_scenarios()

# ── Parameters ────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Modul 1 — Available HQLA Assumptions</div>', unsafe_allow_html=True)
st.caption(
    "GWM sudah dinetkan di dalam Total HQLA oleh `hqla_calc()` (lihat "
    "`estimate_gwm` di lcr_engine.py) — tidak dikurangi lagi di sini agar "
    "tidak double-count. PLM adalah **asumsi placeholder** (belum ada regulasi "
    "PLM harian aktual di data) — sesuaikan slider sesuai kebijakan Bank."
)
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Kewajiban GWM (sudah dinetkan)", fmt_currency(0))
with c2:
    plm_rate_pct = st.slider("Asumsi rate PLM (% × DPK)", 0.0, 10.0, 3.0, 0.5,
                              help="Penyangga Likuiditas Makroprudensial — PLACEHOLDER, konfirmasi ke Bank/BI.")
    plm_obligation = dpk_total * plm_rate_pct / 100
    st.caption(f"= {fmt_currency(plm_obligation)} (dari DPK {fmt_currency(dpk_total)})")
with c3:
    bi_sourced_liquidity = st.number_input(
        "Sumber likuiditas dari Bank Sentral (IDR)", min_value=0.0, value=0.0, step=1e9,
        help="Mis. fasilitas repo/FTK BI yang sedang ditarik. Default 0 jika tidak ada.",
    )

st.markdown('<div class="section-label">Modul 2 — Survival Period Scenario</div>', unsafe_allow_html=True)
c4, c5 = st.columns(2)
with c4:
    scenario_id = st.selectbox(
        "Skenario stres", options=list(scenarios.keys()),
        format_func=lambda k: scenarios[k]["label"],
    )
with c5:
    target_survival_days = st.number_input(
        "Target survival period (hari)", min_value=1, value=90, step=1,
        help="Risk appetite Bank — SEOJK 26/2025 tidak menetapkan angka baku (§12 item 4). Default 90 hari.",
    )

st.divider()

# ── Calculation (cached — only recompute when an actual input changes) ───────
# lcr_res is a fresh dict object every time the LCR Calculator page runs, so
# id(lcr_res) doubles as a cheap "which LCR baseline is this" fingerprint:
# it changes when the user reruns LCR, and stays stable across navigation
# to/from this page in between. Without this guard, Streamlit's top-to-bottom
# rerun-on-every-interaction model recomputed the ledger/ladder/reconciliation
# — and re-appended a full audit-log entry — on every single page visit.
sig = (id(lcr_res), scenario_id, target_survival_days,
       round(plm_rate_pct, 4), bi_sourced_liquidity)

if st.session_state.get("ilaap_sig") != sig:
    try:
        available = available_hqla_calc(
            lcr_res["hqla"], gwm_obligation=0,
            plm_obligation=plm_obligation, bi_sourced_liquidity=bi_sourced_liquidity,
        )
        ledger = data_contract.build_transactions_ledger(df_tab, df_giro, df_depo, df_fin, df_rka, asof_date_str)
        scenario = scenarios[scenario_id]
        ladder = sp.project_cashflow_ladder(ledger, buckets, scenario, asof_date_str)
        result = sp.determine_survival_period(ladder, available["available_hqla"], target_survival_days, buckets)
        recon = ilaap_audit.reconcile_ladder(ledger, ladder, buckets, scenario, asof_date_str)

        ilaap_audit.log_survival_period_run(
            ladder, scenario_id, result,
            manifest={"asof": asof_date_str, "target_survival_days": target_survival_days,
                      "plm_rate_pct": plm_rate_pct, "bi_sourced_liquidity": bi_sourced_liquidity},
        )

        st.session_state["ilaap_sig"] = sig
        st.session_state["ilaap_page_cache"] = {
            "scenario": scenario, "available": available, "ladder": ladder, "result": result, "recon": recon,
        }
        # Exposed for the AI Executive Summary page (src/pages/3_AI_Summary.py) so
        # its scorecard and prompts can include the ILAAP position, not just LCR/NSFR.
        st.session_state["ilaap_results"] = {
            "asof": asof_date_str,
            "scenario_id": scenario_id,
            "scenario_label": scenario["label"],
            "target_survival_days": target_survival_days,
            "available": available,
            "result": {k: v for k, v in result.items() if k != "ladder"},
        }
    except Exception as e:
        al.record_error("ILAAP — Survival Period", f"Calculation failed: {type(e).__name__}: {e}")
        st.error(f"❌ Calculation error: {e}")
        st.stop()

cache = st.session_state["ilaap_page_cache"]
scenario, available, ladder, result, recon = (
    cache["scenario"], cache["available"], cache["ladder"], cache["result"], cache["recon"],
)

# ── KPI cards ─────────────────────────────────────────────────────────────────
st.markdown(f'<div class="section-label">Hasil · {asof_date_str} · {scenario["label"]}</div>', unsafe_allow_html=True)

compliant = result["memenuhi_target"]
s_color = "#22C55E" if compliant else "#EF4444"
s_label = "TARGET TERPENUHI" if compliant else "ADD-ON DIPERLUKAN"
survival_disp = f'{result["survival_hari"]} hari' if result["survival_hari"] is not None else f'> {buckets[-2]["hari_mulai"]} hari'

st.markdown(f"""
<div class="lcr-gauge-wrap" style="border-color:{s_color}55;">
  <div class="gauge-title">Survival Period Status</div>
  <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.5rem;">
    <span style="font-size:1.8rem;font-weight:800;color:#fff;">{survival_disp}</span>
    <span style="background:{s_color}22;border:1px solid {s_color}66;color:{s_color};
                 border-radius:20px;padding:0.15rem 0.7rem;font-size:0.7rem;font-weight:700;
                 letter-spacing:0.1em;">{s_label}</span>
  </div>
  <div style="font-size:0.78rem;color:var(--text-muted);">Target: {target_survival_days} hari &nbsp;·&nbsp; Skenario: {scenario["label"]}</div>
</div>""", unsafe_allow_html=True)


def _kpi(icon, label, value, c):
    return (f'<div class="kpi-card {c}"><div class="top-bar"></div>'
            f'<span class="icon">{icon}</span><div class="value">{value}</div>'
            f'<div class="kpi-label">{label}</div></div>')


st.markdown(
    f'<div class="kpi-grid">'
    f'{_kpi("🏦", "Total HQLA", fmt_currency(available["total_hqla"]), "blue")}'
    f'{_kpi("💧", "Available HQLA (Day 0)", fmt_currency(available["available_hqla"]), "teal")}'
    f'{_kpi("📉", "PLM Obligation", fmt_currency(available["plm_obligation"]), "amber")}'
    f'{_kpi("🌊", "Survival Horizon", survival_disp, "green" if compliant else "red")}'
    f'</div>', unsafe_allow_html=True,
)

if result["add_on_required"]:
    st.warning(
        f"⚠️ Survival period tidak memenuhi target {target_survival_days} hari. "
        f"Shortfall pada bucket target: **{fmt_currency(result['shortfall_pada_target'])}**. "
        f"Perhitungan Pillar 2 add-on (persentase LCR tambahan) **belum diimplementasikan** — "
        f"metodologi konversi shortfall→persentase belum dikonfirmasi ke Divisi Manajemen "
        f"Risiko & Kepatuhan (lihat `compute_add_on_percent()` di `ilaap/survival_period.py`)."
    )

st.divider()

# ── Ladder chart ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">19-Bucket Cash-Flow Ladder</div>', unsafe_allow_html=True)

label_map = {b["id"]: b.get("label", b["id"]) for b in buckets}
order = sp.bucket_order(buckets)
chart_df = result["ladder"].reset_index().rename(columns={"index": "bucket_id"})
chart_df["Bucket"] = chart_df["bucket_id"].map(label_map)
chart_df["order"] = chart_df["bucket_id"].apply(lambda b: order.index(b))
chart_df = chart_df.sort_values("order")

area = alt.Chart(chart_df).mark_area(
    line={"color": "#22D3EE"},
    color=alt.Gradient(gradient="linear",
                        stops=[alt.GradientStop(color="#22D3EE", offset=0),
                               alt.GradientStop(color="rgba(34,211,238,0)", offset=1)],
                        x1=1, x2=1, y1=1, y2=0),
).encode(
    x=alt.X("Bucket:N", sort=chart_df["Bucket"].tolist(), title=None,
            axis=alt.Axis(labelAngle=-45)),
    y=alt.Y("available_hqla_kumulatif:Q", title="Available HQLA (IDR)"),
    tooltip=["Bucket", alt.Tooltip("available_hqla_kumulatif:Q", format=",.0f", title="Available HQLA"),
             alt.Tooltip("arus_keluar_kumulatif:Q", format=",.0f", title="Kumulatif Keluar"),
             alt.Tooltip("arus_masuk_kumulatif:Q", format=",.0f", title="Kumulatif Masuk")],
).properties(height=320)
zero_line = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#EF4444", strokeDash=[5, 5]).encode(y="y:Q")
st.altair_chart(area + zero_line, use_container_width=True)

with st.expander("📋 Lihat tabel ladder lengkap (19 bucket)"):
    display_df = chart_df[["Bucket", "arus_keluar", "arus_masuk", "arus_keluar_kumulatif",
                            "arus_masuk_kumulatif", "net_outflow_kumulatif",
                            "available_hqla_kumulatif"]].copy()
    for col in display_df.columns[1:]:
        display_df[col] = display_df[col].apply(fmt_currency)
    st.dataframe(display_df, use_container_width=True, hide_index=True)

st.divider()

# ── Reconciliation ────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Rekonsiliasi Independen (Kontrol Audit)</div>', unsafe_allow_html=True)
all_pass = (recon["Status"] == "PASS").all()
st.markdown(
    f'<span style="background:{"#22C55E22" if all_pass else "#EF444422"};'
    f'border:1px solid {"#22C55E66" if all_pass else "#EF444466"};'
    f'color:{"#22C55E" if all_pass else "#EF4444"};border-radius:20px;'
    f'padding:0.2rem 0.9rem;font-size:0.75rem;font-weight:700;letter-spacing:0.08em;">'
    f'{"✅ ALL BUCKETS PASS" if all_pass else "❌ RECONCILIATION FAILED"}</span>',
    unsafe_allow_html=True,
)
st.caption(
    "net_outflow_kumulatif dihitung ulang secara independen dari transaksi mentah "
    "(bukan dari hasil project_cashflow_ladder()) dan dibandingkan per bucket — "
    "sama seperti prinsip reconcile() untuk LCR/NSFR."
)
recon_display = recon.copy()
recon_display["Bucket"] = recon_display["bucket_id"].map(label_map)
for col in ("net_outflow_kumulatif (independen)", "net_outflow_kumulatif (engine)", "Selisih"):
    recon_display[col] = recon_display[col].apply(fmt_currency)
st.dataframe(
    recon_display[["Bucket", "net_outflow_kumulatif (independen)",
                   "net_outflow_kumulatif (engine)", "Selisih", "Status"]],
    use_container_width=True, hide_index=True,
)

st.markdown(
    '<div class="lcr-footer">© 2025 — ILAAP Survival Period Monitoring &nbsp;·&nbsp; '
    'SEOJK No. 26/SEOJK.03/2025 &nbsp;·&nbsp; Internal management use only.</div>',
    unsafe_allow_html=True,
)
