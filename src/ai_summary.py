"""
AI Summary — OpenModel gateway (https://openmodel.ai) integration.

OpenModel is a multi-model gateway that speaks Anthropic's Messages protocol,
so the official `anthropic` SDK can be pointed straight at it:

    Base URL   : https://api.openmodel.ai        (SDK appends /v1/messages)
    Auth       : Authorization: Bearer om-...    (X-Api-Key also accepted)
    Version hdr: anthropic-version: 2023-06-01   (sent by the SDK)
    Models     : GET https://api.openmodel.ai/web/v1/models  (public, no key)

Configure via `.env` in the project root:

    OPENMODEL_API_KEY=om-xxxxxxxx
    OPENMODEL_MODEL=deepseek-v4.1-flash     # optional
    OPENMODEL_BASE_URL=https://api.openmodel.ai   # optional
"""
from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request

_THIS = pathlib.Path(__file__).resolve()
_ENV_CANDIDATES = [_THIS.parent.parent / ".env", _THIS.parent / ".env", pathlib.Path.cwd() / ".env"]

DEFAULT_MODEL = "deepseek-v4.1-flash"
DEFAULT_BASE_URL = "https://api.openmodel.ai"
MODELS_URL = "https://api.openmodel.ai/web/v1/models"
_PLACEHOLDERS = {"", "your_api_key_here", "your_key", "changeme", "xxx"}
_SYSTEM = (
    "You are a senior liquidity risk analyst advising the ALCO and Board of a bank "
    "supervised by OJK (Otoritas Jasa Keuangan), assessed against POJK No. 20/2025 (LCR/NSFR) "
    "and SEOJK No. 26/SEOJK.03/2025 (ILAAP). You write in precise, regulator-ready English and "
    "never invent figures that were not provided to you. If a figure needed to answer a question "
    "was not given in the data below, say explicitly that it is not available rather than "
    "estimating or guessing it.\n\n"
    "HOUSE STYLE — follow this in every response:\n"
    "• Write in a blended style. Each section opens with a NARRATIVE PARAGRAPH of 3-5 full "
    "sentences in flowing prose that explains what the numbers mean, why the position arose "
    "and what follows from it — then, beneath it, 3-5 bullet points carrying the specific "
    "figures, drivers or actions.\n"
    "• Never answer with bullet points alone. A section that is only a list is not acceptable: "
    "the reasoning must be written out as prose first, and the bullets only carry the evidence.\n"
    "• Bullets are short and factual. The analysis, causality and judgement belong in the "
    "paragraphs, not in the bullets.\n"
    "• Quantify wherever the data allows — state the ratio, the gap in IDR, and the percentage "
    "points of headroom or shortfall. Do not restate a figure without interpreting it.\n"
    "• Professional board-paper register. No filler, no hedging, no marketing tone."
)

_STYLE_REMINDER = (
    "Formatting: markdown headers for each numbered section. Under every header write the "
    "narrative paragraph FIRST (3-5 sentences of connected prose), then the supporting bullets. "
    "Do not produce a bullets-only report."
)

# Sensible fallbacks used only when the live model list cannot be reached.
FALLBACK_MODELS = [
    "deepseek-v4.1-flash",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "glm-5",
]


# ─────────────────────────────── environment ────────────────────────────────
def _load_env() -> None:
    """Load the first `.env` found. Tolerates CRLF files and quoted values."""
    try:
        from dotenv import load_dotenv

        for p in _ENV_CANDIDATES:
            if p.exists():
                load_dotenv(p, override=True)
                return
    except ImportError:
        pass

    for p in _ENV_CANDIDATES:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()
            return


def _env(name: str, default: str = "") -> str:
    """Read an env var, stripping stray whitespace, CR and surrounding quotes."""
    return os.getenv(name, default).strip().strip("'").strip('"').strip()


def get_api_key() -> str:
    _load_env()
    return _env("OPENMODEL_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN")


def get_base_url() -> str:
    _load_env()
    return (_env("OPENMODEL_BASE_URL") or _env("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def get_model() -> str:
    _load_env()
    return _env("OPENMODEL_MODEL") or DEFAULT_MODEL


def check_config() -> tuple[bool, str]:
    """(ready, message) — cheap pre-flight so the UI can explain what is missing."""
    key = get_api_key()
    if key.lower() in _PLACEHOLDERS:
        return False, (
            "`OPENMODEL_API_KEY` is still the placeholder value. Create a key at "
            "https://openmodel.ai (it looks like `om-…`) and put it in the project `.env`."
        )
    if not key.startswith("om-"):
        return True, (
            f"Key loaded but it does not look like an OpenModel key (expected an `om-…` prefix). "
            f"Endpoint: {get_base_url()}/v1/messages"
        )
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "The `anthropic` SDK is not installed. Run: `pip install anthropic`"
    return True, f"Connected to {get_base_url()}/v1/messages as `{get_model()}`."


def list_models() -> list[str]:
    """Live model catalogue from OpenModel's public endpoint; falls back to a static list."""
    try:
        req = urllib.request.Request(MODELS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return list(FALLBACK_MODELS)

    items = payload.get("data") or payload.get("models") or payload
    if isinstance(items, dict):
        items = items.get("items") or list(items.values())
    names = []
    for m in items or []:
        if isinstance(m, dict):
            name = m.get("key") or m.get("id") or m.get("name")
        else:
            name = m
        if isinstance(name, str) and name:
            names.append(name)
    return sorted(set(names)) or list(FALLBACK_MODELS)


# ─────────────────────────────── generation ─────────────────────────────────
def _ask(prompt: str, model: str | None = None, max_tokens: int = 8000):
    """Send one prompt to OpenModel. Returns (text, error_message).

    Some models on the OpenModel catalogue are reasoning models that emit
    `thinking` content blocks before the final `text` block. If max_tokens is
    too small, the model can spend its entire budget thinking and return no
    text at all — this looked to users like the app "returning no context".
    Mitigated two ways: a generous default max_tokens, and one automatic
    retry with double the budget if the first attempt comes back empty.
    """
    key = get_api_key()
    if key.lower() in _PLACEHOLDERS:
        return None, (
            "⚠️ API key not configured. Set `OPENMODEL_API_KEY=om-…` in the project `.env` "
            "(get one at https://openmodel.ai)."
        )

    try:
        import anthropic
    except ImportError:
        return None, "⚠️ The `anthropic` SDK is missing. Run: `pip install anthropic`"

    model = (model or get_model()).strip()
    try:
        client = anthropic.Anthropic(
            api_key=key,
            base_url=get_base_url(),
            # The SDK sends X-Api-Key; OpenModel documents Authorization: Bearer as
            # the primary scheme, so send both and let the gateway pick.
            default_headers={"Authorization": f"Bearer {key}"},
            timeout=180.0,
            max_retries=2,
        )

        def _generate(budget: int) -> str:
            resp = client.messages.create(
                model=model,
                max_tokens=budget,
                system=_SYSTEM,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            # Reasoning models return `thinking` blocks alongside `text` — keep the text.
            return "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            ).strip()

        text = _generate(max_tokens)
        if not text:
            # Likely a reasoning model that exhausted its budget thinking —
            # retry once with double the budget before giving up.
            text = _generate(max_tokens * 2)
        if not text:
            return None, (
                f"⚠️ `{model}` returned no text content even after retrying with a larger "
                f"token budget. This model may require a `thinking` parameter this gateway "
                f"doesn't expose, or may not be suited to long-form generation — try a "
                f"different model from the list (e.g. `{DEFAULT_MODEL}`)."
            )
        return text, None
    except anthropic.AuthenticationError:
        return None, "⚠️ Authentication rejected by OpenModel. Check `OPENMODEL_API_KEY` in `.env`."
    except anthropic.NotFoundError:
        return None, (
            f"⚠️ Model `{model}` was not found on OpenModel. Pick one from the model list "
            f"(see {MODELS_URL})."
        )
    except anthropic.RateLimitError:
        return None, "⚠️ Rate limited by OpenModel. Wait a moment and try again."
    except anthropic.APIConnectionError as e:
        return None, f"⚠️ Could not reach OpenModel at {get_base_url()}: {e}"
    except anthropic.APIStatusError as e:
        return None, f"⚠️ OpenModel error {e.status_code}: {e.message}"
    except Exception as e:  # noqa: BLE001 — surfaced to the user, never swallowed
        return None, f"⚠️ Generation error: {type(e).__name__}: {e}"


# ──────────────────────────────── prompts ───────────────────────────────────
def lcr_summary(lcr, hqla, outflow, inflow, model: str | None = None):
    return _ask(
        f"""Analyse these LCR results per POJK No. 20/2025 for the ALCO.

Structure the note under these headers, each written as a narrative paragraph followed by
supporting bullets:
1) Compliance Position — state the ratio against the 100% minimum, quantify the headroom or
   shortfall in both percentage points and IDR, and say what that means for the 30-day horizon.
2) Key Risk Drivers — explain which components move the ratio and why, not merely which are largest.
3) Largest Outflow Concentration — identify the dominant outflow bucket, explain the behavioural
   assumption behind its run-off factor, and assess how exposed the ratio is if that assumption fails.
4) Recommendations — concrete actions for ALCO, each with the expected direction of impact.

Target 450-600 words. {_STYLE_REMINDER}

- Total HQLA: IDR {lcr.get('Total HQLA', 0):,.0f}
- Total Outflow: IDR {lcr.get('Total Cash Outflow', 0):,.0f}
- Total Inflow: IDR {lcr.get('Total Cash Inflow', 0):,.0f}
- LCR: {lcr.get('LCR', 0):.2f}% (min 100%)
HQLA: {', '.join(f'{k}: {v:,.0f}' for k, v in hqla.items())}
Outflows: Retail={outflow.get('Total Outflow Pendanaan Perorangan', 0):,.0f}, SME={outflow.get('Total Outflow Pendanaan UMK', 0):,.0f}, Corp={outflow.get('Total Outflow Pendanaan Korporasi', 0):,.0f}, Add={outflow.get('Total Outflow Tambahan', 0):,.0f}""",
        model=model,
    )


def nsfr_summary(nsfr, asf, rsf, model: str | None = None):
    return _ask(
        f"""Analyse these NSFR results per POJK No. 20/2025 for the ALCO.

Structure the note under these headers, each written as a narrative paragraph followed by
supporting bullets:
1) Compliance Position — the ratio against the 100% minimum, with the gap quantified in both
   percentage points and IDR.
2) Funding Stability — assess the quality and behavioural stickiness of the funding base, not
   just its size.
3) ASF versus RSF Gap — explain which asset classes consume stable funding and which liabilities
   supply it, and where the structural mismatch actually sits.
4) Recommendations — concrete balance-sheet actions, each with the expected effect on the ratio.

Target 450-600 words. {_STYLE_REMINDER}

- Total ASF: IDR {nsfr.get('Total ASF', 0):,.0f}
- Total RSF: IDR {nsfr.get('Total RSF', 0):,.0f}
- NSFR: {nsfr.get('NSFR', 0):.2f}% (min 100%)
ASF: {', '.join(f'{k}: {v:,.0f}' for k, v in asf.items() if 'ASF' in k)}
RSF: {', '.join(f'{k}: {v:,.0f}' for k, v in rsf.items() if 'RSF' in k)}""",
        model=model,
    )


def ilaap_summary(ilaap_res, model: str | None = None):
    """Narrative on Survival Period Monitoring (ILAAP, SEOJK No. 26/2025)."""
    if not ilaap_res:
        return None, "No ILAAP Survival Period results available. Run it from the Stress Testing page first."

    result = ilaap_res["result"]
    available = ilaap_res["available"]
    add_on_note = (
        "Add-on required, but the shortfall-to-LCR-percentage conversion methodology has not "
        "yet been confirmed by the Bank's Risk Management & Compliance division (this is a "
        "known, deliberate gap in the current tooling, not missing data) — do not estimate or "
        "guess an add-on percentage."
        if result.get("add_on_required")
        else "No add-on required — the survival period target is met."
    )
    return _ask(
        f"""Analyse this Survival Period Monitoring (ILAAP) result per SEOJK No. 26/SEOJK.03/2025
for the ALCO. Scenario: {ilaap_res['scenario_label']}. Reporting date: {ilaap_res['asof']}.

Structure the note under these headers, each written as a narrative paragraph followed by
supporting bullets:
1) Survival Position — state the survival horizon against the {ilaap_res['target_survival_days']}-day
   target, and what it means operationally if the stress scenario materialised.
2) Available HQLA Composition — explain how GWM/PLM/BI-sourced-liquidity deductions shape the
   day-0 buffer actually available to absorb the stress, versus gross HQLA.
3) Add-On Status — state clearly: {add_on_note}
4) Recommendations — concrete actions for ALCO, each with the expected effect on the survival
   horizon.

Target 350-500 words. {_STYLE_REMINDER}

- Scenario: {ilaap_res['scenario_label']} (no LCR 75% inflow cap applied, per SEOJK §10.21)
- Total HQLA (gross): IDR {available['total_hqla']:,.0f}
- GWM obligation: IDR {available['gwm_obligation']:,.0f} (already netted inside Total HQLA)
- PLM obligation (assumption): IDR {available['plm_obligation']:,.0f}
- BI-sourced liquidity drawn: IDR {available['bi_sourced_liquidity']:,.0f}
- Available HQLA (Day 0): IDR {available['available_hqla']:,.0f}
- Target survival period: {ilaap_res['target_survival_days']} days
- Survival horizon reached: {result.get('survival_hari') if result.get('survival_hari') is not None else 'beyond the 19-bucket ladder horizon (>5 years)'}
- Target met: {result['memenuhi_target']}
- Add-on required: {result['add_on_required']}
{f"- Shortfall at target bucket: IDR {result.get('shortfall_pada_target', 0):,.0f}" if result.get('add_on_required') else ""}""",
        model=model,
    )


def combined_summary(lcr_res, nsfr_res, ilaap_res=None, model: str | None = None):
    if not lcr_res and not nsfr_res:
        return None, "No analysis results available. Run LCR and/or NSFR first."
    parts = []
    if lcr_res:
        parts.append(
            f"LCR: {lcr_res['lcr'].get('LCR', 0):.2f}%, "
            f"HQLA: {lcr_res['lcr']['Total HQLA']:,.0f}, "
            f"Outflow: {lcr_res['lcr']['Total Cash Outflow']:,.0f}, "
            f"Inflow: {lcr_res['lcr']['Total Cash Inflow']:,.0f}, "
            f"Retail outflow: {lcr_res['outflow'].get('Total Outflow Pendanaan Perorangan', 0):,.0f}, "
            f"SME outflow: {lcr_res['outflow'].get('Total Outflow Pendanaan UMK', 0):,.0f}, "
            f"Corporate outflow: {lcr_res['outflow'].get('Total Outflow Pendanaan Korporasi', 0):,.0f}"
        )
    if nsfr_res:
        rsf = nsfr_res["rsf"]
        performing = rsf.get("perf_A", 0) + rsf.get("perf_B", 0) + rsf.get("perf_C", 0)
        npf = rsf.get("npf", 0)
        npf_ratio = (npf / (performing + npf) * 100) if (performing + npf) else 0.0
        ldr_row = nsfr_res["dfs"]["nrc_rangkuman"]
        ldr_match = ldr_row.loc[ldr_row["KETERANGAN"] == "LDR", "REALISASI"]
        ldr_pct = float(ldr_match.iloc[0]) * 100 if len(ldr_match) else None
        parts.append(
            f"NSFR: {nsfr_res['nsfr'].get('NSFR', 0):.2f}%, "
            f"ASF: {nsfr_res['nsfr']['Total ASF']:,.0f}, "
            f"RSF: {nsfr_res['nsfr']['Total RSF']:,.0f}, "
            f"NPF ratio: {npf_ratio:.2f}%"
            + (f", LDR: {ldr_pct:.1f}%" if ldr_pct is not None else "")
        )
    ilaap_section = ""
    if ilaap_res:
        result, available = ilaap_res["result"], ilaap_res["available"]
        parts.append(
            f"ILAAP Survival Period ({ilaap_res['scenario_label']}): "
            f"Available HQLA Day 0: {available['available_hqla']:,.0f}, "
            f"target {ilaap_res['target_survival_days']} days, "
            f"survival horizon: {result.get('survival_hari', '>5 years')}, "
            f"target met: {result['memenuhi_target']}, "
            f"add-on required: {result['add_on_required']} "
            f"(add-on percentage not computed — methodology pending Bank policy confirmation)"
        )
        ilaap_section = (
            "\n4) ILAAP Survival Period — the stress-scenario survival horizon versus the Bank's "
            "target, and what it implies alongside the point-in-time LCR/NSFR figures above. If "
            "add-on is flagged as required, state plainly that the add-on percentage itself is "
            "not yet computable (policy pending) — do not invent one.\n"
        )
    return _ask(
        f"""Write an executive summary on the combined liquidity position for the Board of
Directors, assessed against POJK No. 20/2025 (LCR/NSFR){" and SEOJK No. 26/SEOJK.03/2025 (ILAAP)" if ilaap_res else ""}:
{chr(10).join(parts)}

Open with a short **Executive Overview** — two paragraphs of continuous prose, no bullets — that
states the overall verdict, the single most important issue facing the Board, and what is being
asked of them. Then work through these sections, each opening with its narrative paragraph and
closing with supporting bullets:

1) Overall Liquidity Health — reconcile the ratios above into one judgement. Where they point in
   different directions, explain why that divergence arises and which signal should govern.
2) LCR Compliance and Key Drivers — the 30-day position, its headroom, and what sustains it.
3) NSFR Structural Funding Adequacy — the one-year position, the durability of the funding base,
   and what the NPF/LDR figures say about underlying asset quality.
{ilaap_section}5) Cross-Ratio Interactions — how actions taken to defend one ratio affect the others. Be
   specific about the trade-off: lengthening liability tenor, shifting into HQLA, or repricing
   deposits all move these metrics, not always in the same direction.
6) Strategic Recommendations for ALCO — prioritised actions, each with the expected effect on the
   ratios above and an indicative timeframe.
7) Early Warning Indicators — the specific metrics and thresholds that should trigger escalation
   before any ratio is breached or the survival target is missed.

Target 800-1100 words. {_STYLE_REMINDER}
Close with one sentence noting that the figures derive from the bank's own reported source files
and that the calculation trace is available in the system's audit log.""",
        model=model,
        max_tokens=10000,
    )
