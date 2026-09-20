"""AI Summary Page — Executive Summary of LCR and NSFR results via OpenModel."""
import datetime as _dt
import pathlib
import sys

import streamlit as st

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SRC_DIR))
from ai_summary import (  # noqa: E402
    DEFAULT_MODEL,
    check_config,
    combined_summary,
    get_base_url,
    get_model,
    list_models,
    lcr_summary,
    nsfr_summary,
)
import audit_log as al  # noqa: E402

st.markdown("""
<div class="lcr-hero hero-violet">
  <div class="badge">🤖 AI-POWERED ANALYSIS</div>
  <h1>Executive Summary</h1>
  <p>Board-level liquidity commentary generated from your latest LCR and NSFR runs, via the OpenModel gateway.</p>
</div>
""", unsafe_allow_html=True)

lcr_res = st.session_state.get("lcr_results")
nsfr_res = st.session_state.get("nsfr_results")


@st.cache_data(ttl=3600, show_spinner=False)
def _models():
    return list_models()


# ── Sidebar: engine configuration ───────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🤖 AI Engine")
    ready, msg = check_config()

    catalogue = _models()
    preferred = get_model()
    if preferred not in catalogue:
        catalogue = [preferred] + catalogue
    model = st.selectbox(
        "Model",
        catalogue,
        index=catalogue.index(preferred) if preferred in catalogue else 0,
        help="Live catalogue from OpenModel. Defaults to OPENMODEL_MODEL in .env "
             f"(currently `{preferred or DEFAULT_MODEL}`).",
    )
    st.caption(f"Endpoint: `{get_base_url()}/v1/messages`")
    if ready:
        st.success("API key loaded", icon="🔑")
    else:
        st.error("API key not configured", icon="🔑")
    st.markdown("---")
    st.markdown(
        "<p style='font-size:0.68rem;color:#94A3B8;text-align:center;font-weight:600;'>"
        "AI Executive Summary v2.0<br/>Powered by openmodel.ai</p>",
        unsafe_allow_html=True,
    )

# ── Configuration guard ─────────────────────────────────────────────────────
if not ready:
    st.error(msg)
    with st.expander("How to configure OpenModel", expanded=True):
        st.markdown(
            f"""
1. Create an API key at [openmodel.ai](https://openmodel.ai) — keys look like `om-a1f4-…`.
2. Add it to the `.env` file in the project root:

```dotenv
OPENMODEL_API_KEY=om-your-real-key
# optional overrides
OPENMODEL_MODEL={DEFAULT_MODEL}
OPENMODEL_BASE_URL=https://api.openmodel.ai
```

3. Restart the app (`streamlit run src/app.py`).

OpenModel speaks the **Anthropic Messages protocol**, so this page talks to
`{get_base_url()}/v1/messages` through the official `anthropic` SDK.
"""
        )
    st.stop()

# ── Analysis context ────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Analysis Context</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    if lcr_res:
        st.success(f"✅ LCR results available — as of {lcr_res['asof']}")
    else:
        st.warning("⚠️ No LCR results. Run the LCR Calculator first.")
with col2:
    if nsfr_res:
        st.success(f"✅ NSFR results available — as of {nsfr_res['asof']}")
    else:
        st.warning("⚠️ No NSFR results. Run the NSFR Calculator first.")

if not (lcr_res or nsfr_res):
    st.info("No analysis data found in the current session. Go to the LCR or NSFR page to run an analysis.")
    st.stop()

# Headline figures, so the analyst sees exactly what the model is being fed.
def _kpi(icon, label, value, tone):
    return (f'<div class="kpi-card {tone}"><div class="top-bar"></div>'
            f'<span class="icon">{icon}</span><div class="value">{value}</div>'
            f'<div class="kpi-label">{label}</div></div>')


tiles = []
if lcr_res:
    lcr_val = lcr_res["lcr"].get("LCR", 0)
    tiles.append(_kpi("💧", "LCR Ratio", f"{lcr_val:.2f}%", "green" if lcr_val >= 100 else "red"))
    tiles.append(_kpi("🏦", "Total HQLA", f"{lcr_res['lcr']['Total HQLA']:,.0f}", "blue"))
if nsfr_res:
    nsfr_val = nsfr_res["nsfr"].get("NSFR", 0)
    tiles.append(_kpi("🏛️", "NSFR Ratio", f"{nsfr_val:.2f}%", "green" if nsfr_val >= 100 else "red"))
    tiles.append(_kpi("📦", "Total ASF", f"{nsfr_res['nsfr']['Total ASF']:,.0f}", "teal"))
st.markdown(f'<div class="kpi-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)

# ── Report scope ────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Report Scope</div>', unsafe_allow_html=True)

options = ["Combined — Board / ALCO executive summary"]
if lcr_res:
    options.append("LCR only — compliance & outflow drivers")
if nsfr_res:
    options.append("NSFR only — structural funding adequacy")

scope = st.radio("Scope", options, horizontal=True, label_visibility="collapsed")

if st.button("✨ Generate Executive Summary", type="primary", use_container_width=True):
    with st.spinner(f"Analyzing liquidity position with `{model}`…"):
        if scope.startswith("LCR"):
            text, err = lcr_summary(
                lcr_res["lcr"], lcr_res["hqla"], lcr_res["outflow"], lcr_res["inflow"], model=model
            )
        elif scope.startswith("NSFR"):
            text, err = nsfr_summary(
                nsfr_res["nsfr"], nsfr_res["asf"], nsfr_res["rsf"], model=model
            )
        else:
            text, err = combined_summary(lcr_res, nsfr_res, model=model)

    if err:
        al.record_error("AI Summary", f"Generation failed ({model}): {err}")
        st.error(err)
    else:
        al.record_ai(model, scope, prompt_chars=0, response_chars=len(text))
        st.session_state["executive_summary_text"] = text
        st.session_state["executive_summary_meta"] = {
            "model": model,
            "scope": scope,
            "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

# ── Generated report ────────────────────────────────────────────────────────
summary_text = st.session_state.get("executive_summary_text")
if summary_text:
    meta = st.session_state.get("executive_summary_meta", {})
    st.markdown('<div class="section-label">AI Generated Report</div>', unsafe_allow_html=True)
    st.caption(
        f"Model `{meta.get('model', model)}` · {meta.get('scope', '')} · "
        f"generated {meta.get('generated', '')}"
    )
    with st.container(border=True):
        st.markdown(summary_text)

    st.download_button(
        "⬇️ Download as Markdown",
        data=(
            f"# Liquidity Executive Summary\n\n"
            f"_Model: {meta.get('model', model)} · {meta.get('scope', '')} · "
            f"{meta.get('generated', '')}_\n\n{summary_text}\n"
        ),
        file_name=f"Executive_Summary_{_dt.date.today()}.md",
        mime="text/markdown",
        use_container_width=True,
    )

st.markdown(
    '<div class="lcr-footer">© 2025 — Liquidity Risk Management &nbsp;·&nbsp; '
    'AI summaries must be reviewed by risk professionals before use.</div>',
    unsafe_allow_html=True,
)
