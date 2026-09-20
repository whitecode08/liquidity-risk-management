"""Audit Log Page — calculation traceability for internal audit."""
import datetime as _dt
import pathlib
import sys

import pandas as pd
import streamlit as st

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SRC_DIR))
import audit_log as al  # noqa: E402

st.markdown("""
<div class="lcr-hero hero-amber">
  <div class="badge">📒 GOVERNANCE — AUDIT TRAIL</div>
  <h1>Audit Log</h1>
  <p>Evidence of how every reported figure was produced: source files and their fingerprints,
     each regulatory weighting applied, the ratio arithmetic, and a reconciliation control —
     exportable as an audit pack.</p>
</div>
""", unsafe_allow_html=True)

lcr_res = st.session_state.get("lcr_results")
nsfr_res = st.session_state.get("nsfr_results")

fmt_idr = lambda v: "-" if pd.isna(v) else f"{v:,.0f}"


def _kpi(icon, label, value, tone):
    return (f'<div class="kpi-card {tone}"><div class="top-bar"></div>'
            f'<span class="icon">{icon}</span><div class="value">{value}</div>'
            f'<div class="kpi-label">{label}</div></div>')


# ── Run identity ────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Run Identity</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="kpi-grid">'
    + _kpi("🆔", "Audit Run ID", al.run_id(), "blue")
    + _kpi("👤", "Operator", al.operator().split("@")[0], "navy")
    + _kpi("🕓", "Session Started", al.started_at()[11:], "teal")
    + _kpi("📑", "Entries Recorded", str(al.entry_count()), "green")
    + '</div>',
    unsafe_allow_html=True,
)

if not (lcr_res or nsfr_res) and al.entry_count() == 0:
    st.info(
        "Nothing recorded yet. Run the LCR or NSFR calculator and the audit trail will capture "
        "the source files, the weightings applied and the ratio arithmetic automatically."
    )
    st.stop()

# ── Reconciliation control ──────────────────────────────────────────────────
if lcr_res or nsfr_res:
    st.markdown('<div class="section-label">Reconciliation Control</div>', unsafe_allow_html=True)
    rec = al.reconcile(lcr_res, nsfr_res)
    failed = (rec["Status"] == "FAIL").sum() if not rec.empty else 0
    if failed:
        st.error(
            f"⚠️ {failed} reconciliation check(s) FAILED. The audit trace does not re-add to the "
            "engine's totals — investigate before relying on these figures."
        )
    else:
        st.success(
            "✅ All checks PASS — re-adding the traced line items reproduces the calculation "
            "engine's totals exactly."
        )
    st.caption(
        "Each traced line is re-added independently of the engine and compared with the engine's "
        "own total (tolerance: IDR 1). This makes the log a control over the calculation, not just "
        "a description of it."
    )
    st.dataframe(
        rec.style.format({"Audit Trace Total": fmt_idr, "Engine Total": fmt_idr,
                          "Difference": fmt_idr}),
        use_container_width=True, hide_index=True,
    )

# ── Ratio arithmetic ────────────────────────────────────────────────────────
if lcr_res or nsfr_res:
    st.markdown('<div class="section-label">Ratio Arithmetic — Step by Step</div>',
                unsafe_allow_html=True)
    steps = al.ratio_steps(lcr_res, nsfr_res)
    st.dataframe(
        steps.style.format({"Value": lambda v: f"{v:,.2f}"}),
        use_container_width=True, hide_index=True,
    )

# ── Derivation tables ───────────────────────────────────────────────────────
st.markdown('<div class="section-label">Calculation Derivation — Base × Factor = Weighted</div>',
            unsafe_allow_html=True)

tabs = st.tabs(["💧 LCR Derivation", "🏦 NSFR Derivation", "📋 Event Log"])

with tabs[0]:
    if lcr_res:
        t = al.lcr_trace(lcr_res)
        st.caption(f"LCR as of {lcr_res['asof']} · {len(t)} weighted line items · {al.REG}")
        for cat in t["Category"].unique():
            sub = t[t["Category"] == cat]
            st.markdown(f"**{cat}** — weighted total: `{sub['Weighted Amount (IDR)'].sum():,.0f}`")
            st.dataframe(
                sub.drop(columns=["Category", "Regulation"]).style.format({
                    "Base Amount (IDR)": fmt_idr,
                    "Weighted Amount (IDR)": fmt_idr,
                    "Factor": "{:.0%}",
                }),
                use_container_width=True, hide_index=True,
            )
    else:
        st.info("No LCR run in this session.")

with tabs[1]:
    if nsfr_res:
        t = al.nsfr_trace(nsfr_res)
        st.caption(f"NSFR as of {nsfr_res['asof']} · {len(t)} weighted line items · {al.REG}")
        for cat in t["Category"].unique():
            sub = t[t["Category"] == cat]
            st.markdown(f"**{cat}** — weighted total: `{sub['Weighted Amount (IDR)'].sum():,.0f}`")
            st.dataframe(
                sub.drop(columns=["Category", "Regulation"]).style.format({
                    "Base Amount (IDR)": fmt_idr,
                    "Weighted Amount (IDR)": fmt_idr,
                    "Factor": "{:.0%}",
                }),
                use_container_width=True, hide_index=True,
            )
    else:
        st.info("No NSFR run in this session.")

with tabs[2]:
    ev = al.events_df()
    if ev.empty:
        st.info("No events recorded yet.")
    else:
        modules = st.multiselect("Filter by module", sorted(ev["Module"].unique()),
                                 default=sorted(ev["Module"].unique()))
        events = st.multiselect("Filter by event type", sorted(ev["Event"].unique()),
                                default=sorted(ev["Event"].unique()))
        view = ev[ev["Module"].isin(modules) & ev["Event"].isin(events)]
        st.caption(f"{len(view)} of {len(ev)} entries. Source files are fingerprinted with SHA-256 "
                   "so the run can be reproduced from the same inputs.")
        st.dataframe(view, use_container_width=True, hide_index=True)

# ── Export ──────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Export Audit Pack</div>', unsafe_allow_html=True)

stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
col1, col2, col3 = st.columns(3)

with col1:
    st.download_button(
        "📊 Excel audit pack",
        data=al.build_workbook(lcr_res, nsfr_res),
        file_name=f"Audit_Log_{al.run_id()}_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        help="Multi-sheet workbook: run summary, event log, ratio arithmetic, "
             "reconciliation and both derivation tables.",
    )
with col2:
    st.download_button(
        "🧾 Event log (CSV)",
        data=al.events_df().to_csv(index=False).encode("utf-8"),
        file_name=f"Audit_Events_{al.run_id()}_{stamp}.csv",
        mime="text/csv",
        use_container_width=True,
    )
with col3:
    st.download_button(
        "🔗 Full trace (JSON)",
        data=al.build_json(lcr_res, nsfr_res),
        file_name=f"Audit_Trace_{al.run_id()}_{stamp}.json",
        mime="application/json",
        use_container_width=True,
        help="Machine-readable trace for audit tooling or long-term retention.",
    )

with st.expander("Reset the audit trail"):
    st.warning(
        "Clearing discards the trail for this session, including the run ID. Export the audit "
        "pack first if the run needs to be evidenced."
    )
    if st.button("🗑️ Clear audit log", use_container_width=True):
        al.clear()
        st.rerun()

st.markdown(
    '<div class="lcr-footer">© 2025 — Liquidity Risk Management &nbsp;·&nbsp; '
    'Audit trail is session-scoped: export before closing the app to retain evidence.</div>',
    unsafe_allow_html=True,
)
