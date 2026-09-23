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
    ilaap_summary,
    list_models,
    lcr_summary,
    nsfr_summary,
)
import audit_log as al  # noqa: E402
from assets import ui  # noqa: E402
from assets.theme import ratio_status  # noqa: E402

ui.hero("Executive Summary",
        "Board-level liquidity commentary generated from your latest LCR and NSFR runs, via the OpenModel gateway.",
        "AI-Powered Analysis", "sparkles", "violet")

lcr_res = st.session_state.get("lcr_results")
nsfr_res = st.session_state.get("nsfr_results")
ilaap_res = st.session_state.get("ilaap_results")


@st.cache_data(ttl=3600, show_spinner=False)
def _models():
    return list_models()


# ── Sidebar: engine configuration ───────────────────────────────────────────
with st.sidebar:
    st.markdown("## AI Engine")
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
        st.success("API key loaded", icon=":material/key:")
    else:
        st.error("API key not configured", icon=":material/key_off:")
    st.markdown("---")
    st.caption("AI Executive Summary v2.0 · Powered by openmodel.ai")

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
ui.section("Analysis Context")

col1, col2, col3 = st.columns(3)
with col1:
    if lcr_res:
        st.success(f"LCR results available — as of {lcr_res['asof']}", icon=":material/check_circle:")
    else:
        st.warning("No LCR results. Run the LCR Calculator first.", icon=":material/warning:")
with col2:
    if nsfr_res:
        st.success(f"NSFR results available — as of {nsfr_res['asof']}", icon=":material/check_circle:")
    else:
        st.warning("No NSFR results. Run the NSFR Calculator first.", icon=":material/warning:")
with col3:
    if ilaap_res:
        st.success(f"ILAAP Survival Period available — {ilaap_res['scenario_label']}", icon=":material/check_circle:")
    else:
        st.warning("No ILAAP results. Run Stress Testing (ILAAP) first — optional.", icon=":material/warning:")

if not (lcr_res or nsfr_res):
    st.info("No analysis data found in the current session. Go to the LCR or NSFR page to run an analysis.")
    st.stop()

# Headline figures, so the analyst sees exactly what the model is being fed.
tiles = []
if lcr_res:
    lcr_val = lcr_res["lcr"].get("LCR", 0)
    tiles.append(ui.kpi_card("droplet", "LCR Ratio", f"{lcr_val:.2f}%", ratio_status(lcr_val)))
    tiles.append(ui.kpi_card("shield", "Total HQLA", f"{lcr_res['lcr']['Total HQLA']:,.0f}"))
if nsfr_res:
    nsfr_val = nsfr_res["nsfr"].get("NSFR", 0)
    tiles.append(ui.kpi_card("landmark", "NSFR Ratio", f"{nsfr_val:.2f}%", ratio_status(nsfr_val)))
    tiles.append(ui.kpi_card("trending-up", "Total ASF", f"{nsfr_res['nsfr']['Total ASF']:,.0f}"))

    rsf = nsfr_res["rsf"]
    performing = rsf.get("perf_A", 0) + rsf.get("perf_B", 0) + rsf.get("perf_C", 0)
    npf = rsf.get("npf", 0)
    npf_ratio = (npf / (performing + npf) * 100) if (performing + npf) else 0.0
    tiles.append(ui.kpi_card("triangle-alert", "NPF Ratio", f"{npf_ratio:.2f}%",
                             "warning" if npf_ratio < 5 else "critical"))

    ldr_row = nsfr_res["dfs"]["nrc_rangkuman"]
    ldr_match = ldr_row.loc[ldr_row["KETERANGAN"] == "LDR", "REALISASI"]
    if len(ldr_match):
        ldr_pct = float(ldr_match.iloc[0]) * 100
        tiles.append(ui.kpi_card("scale", "LDR", f"{ldr_pct:.1f}%"))
if ilaap_res:
    result = ilaap_res["result"]
    survival_disp = f'{result.get("survival_hari")}d' if result.get("survival_hari") is not None else ">5y"
    tiles.append(ui.kpi_card("hourglass", "Survival Horizon", survival_disp,
                             "healthy" if result["memenuhi_target"] else "critical"))
    tiles.append(ui.kpi_card("triangle-alert", "ILAAP Add-On",
                             "Required" if result["add_on_required"] else "Not required",
                             "critical" if result["add_on_required"] else "healthy"))
ui.kpi_grid(tiles)
st.caption("Scorecard ini adalah persis konteks numerik yang dikirim ke model AI — bukan ringkasan terpisah.")

# ── Report scope ────────────────────────────────────────────────────────────
ui.section("Report Scope")

options = ["Combined — Board / ALCO executive summary"]
if lcr_res:
    options.append("LCR only — compliance & outflow drivers")
if nsfr_res:
    options.append("NSFR only — structural funding adequacy")
if ilaap_res:
    options.append("ILAAP only — survival period & add-on status")

scope = st.radio("Scope", options, horizontal=True, label_visibility="collapsed")
if scope.startswith("Combined") and ilaap_res:
    st.caption("ILAAP Survival Period will be included in the combined summary automatically.")

if st.button("Generate Executive Summary", type="primary", icon=":material/auto_awesome:",
             use_container_width=True):
    with st.spinner(f"Analyzing liquidity position with `{model}`…"):
        if scope.startswith("LCR"):
            text, err = lcr_summary(
                lcr_res["lcr"], lcr_res["hqla"], lcr_res["outflow"], lcr_res["inflow"], model=model
            )
        elif scope.startswith("NSFR"):
            text, err = nsfr_summary(
                nsfr_res["nsfr"], nsfr_res["asf"], nsfr_res["rsf"], model=model
            )
        elif scope.startswith("ILAAP"):
            text, err = ilaap_summary(ilaap_res, model=model)
        else:
            text, err = combined_summary(lcr_res, nsfr_res, ilaap_res, model=model)

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
    ui.section("AI Generated Report")
    st.caption(
        f"Model `{meta.get('model', model)}` · {meta.get('scope', '')} · "
        f"generated {meta.get('generated', '')}"
    )
    with st.container(border=True):
        st.markdown(summary_text)

    st.download_button(
        "Download as Markdown", icon=":material/download:",
        data=(
            f"# Liquidity Executive Summary\n\n"
            f"_Model: {meta.get('model', model)} · {meta.get('scope', '')} · "
            f"{meta.get('generated', '')}_\n\n{summary_text}\n"
        ),
        file_name=f"Executive_Summary_{_dt.date.today()}.md",
        mime="text/markdown",
        use_container_width=True,
    )

ui.footer("© 2025 — Liquidity Risk Management &nbsp;·&nbsp; "
          "AI summaries must be reviewed by risk professionals before use.")
