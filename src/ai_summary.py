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
    "You are a senior Islamic banking liquidity risk analyst advising the ALCO and Board "
    "of a Sharia bank supervised by OJK. You write in precise, regulator-ready English and "
    "never invent figures that were not provided to you.\n\n"
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
def _ask(prompt: str, model: str | None = None, max_tokens: int = 4096):
    """Send one prompt to OpenModel. Returns (text, error_message)."""
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
            timeout=120.0,
            max_retries=2,
        )
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_SYSTEM,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        # Reasoning models return `thinking` blocks alongside `text` — keep the text.
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
        if not text:
            return None, f"⚠️ `{model}` returned no text content. Try another model."
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


def combined_summary(lcr_res, nsfr_res, model: str | None = None):
    if not lcr_res and not nsfr_res:
        return None, "No analysis results available. Run LCR and/or NSFR first."
    parts = []
    if lcr_res:
        parts.append(
            f"LCR: {lcr_res['lcr'].get('LCR', 0):.2f}%, "
            f"HQLA: {lcr_res['lcr']['Total HQLA']:,.0f}, "
            f"Outflow: {lcr_res['lcr']['Total Cash Outflow']:,.0f}"
        )
    if nsfr_res:
        parts.append(
            f"NSFR: {nsfr_res['nsfr'].get('NSFR', 0):.2f}%, "
            f"ASF: {nsfr_res['nsfr']['Total ASF']:,.0f}, "
            f"RSF: {nsfr_res['nsfr']['Total RSF']:,.0f}"
        )
    return _ask(
        f"""Write an executive summary on the combined liquidity position for the Board of
Directors, assessed against POJK No. 20/2025:
{chr(10).join(parts)}

Open with a short **Executive Overview** — two paragraphs of continuous prose, no bullets — that
states the overall verdict, the single most important issue facing the Board, and what is being
asked of them. Then work through these sections, each opening with its narrative paragraph and
closing with supporting bullets:

1) Overall Liquidity Health — reconcile the two ratios into one judgement. Where they point in
   different directions, explain why that divergence arises and which signal should govern.
2) LCR Compliance and Key Drivers — the 30-day position, its headroom, and what sustains it.
3) NSFR Structural Funding Adequacy — the one-year position and the durability of the funding base.
4) Cross-Ratio Interactions — how actions taken to defend one ratio affect the other. Be specific
   about the trade-off: lengthening liability tenor, shifting into HQLA, or repricing deposits all
   move both ratios, not always in the same direction.
5) Strategic Recommendations for ALCO — prioritised actions, each with the expected effect on both
   ratios and an indicative timeframe.
6) Early Warning Indicators — the specific metrics and thresholds that should trigger escalation
   before either ratio is breached.

Target 800-1000 words. {_STYLE_REMINDER}
Close with one sentence noting that the figures derive from the bank's own reported source files
and that the calculation trace is available in the system's audit log.""",
        model=model,
        max_tokens=6000,
    )
