"""
Design tokens — single source of truth for colour and type.
============================================================
Both the stylesheet and the Altair charts read from here: app.py renders
COLORS into CSS custom properties (see css_variables()), and
assets/chart_theme.py uses the same dict for chart marks. Change a colour
here and it changes everywhere; never hard-code a hex value in a page.
"""

COLORS = {
    "bg_primary":       "#0B0F19",
    "bg_surface":       "#111827",
    "bg_surface_hover": "#161F2E",
    "bg_sidebar":       "#080C15",
    "border":           "#1F2937",
    "border_strong":    "#2B3647",
    "text_primary":     "#F3F4F6",
    "text_secondary":   "#9CA3AF",
    "text_muted":       "#6B7280",
    "grid":             "#1F2937",   # chart gridlines — deliberately faint
    "accent_blue":      "#3B82F6",
    "accent_blue_soft": "#60A5FA",
    "accent_green":     "#22C55E",
    "accent_red":       "#EF4444",
    "accent_amber":     "#F59E0B",
    "accent_violet":    "#8B5CF6",
}

# Category colours encode the regulatory weighting tier, not the segment:
# segments that share a factor share a colour, so the eye reads stability /
# funding burden directly. Keys are the chart labels used by the pages.
ASF_COLORS = {                      # ASF factor → more stable = stronger green
    "Retail Stable (95%)":   "#22C55E",
    "SME Stable (95%)":      "#22C55E",
    "Retail Unstable (90%)": "#86EFAC",
    "SME Unstable (90%)":    "#86EFAC",
    "Corporate (50%)":       "#F59E0B",
}
RSF_COLORS = {                      # RSF factor → heavier requirement = hotter
    "HQLA (0%)":              "#22C55E",
    "Financing <6m (50%)":    "#FCD34D",
    "Financing 6m–1y (50%)":  "#FCD34D",
    "Financing ≥1y (65%)":    "#F59E0B",
    "NPF (100%)":             "#EF4444",
    "Fixed Assets (100%)":    "#EF4444",
}
LCR_OUTFLOW_COLORS = {              # one hue family: all are stressed outflows
    "Retail":     "#60A5FA",
    "SME (UMK)":  "#3B82F6",
    "Corporate":  "#2563EB",
    "Additional": "#93C5FD",
}
HQLA_COLORS = {
    "Cash":          "#22C55E",
    "BI Placement":  "#3B82F6",
    "HQLA Level 2":  "#8B5CF6",
}

FONT_FAMILY = "Inter, -apple-system, 'Segoe UI', sans-serif"

# Regulatory minimum is 100% for LCR and NSFR (POJK No. 20/2025). The 10pt
# band above it is a management early-warning buffer, not a regulatory limit.
RATIO_MINIMUM = 100.0
RATIO_BUFFER = 110.0

STATUS_LABEL = {"healthy": "COMPLIANT", "warning": "THIN BUFFER", "critical": "BREACH"}
STATUS_COLOR = {"healthy": COLORS["accent_green"], "warning": COLORS["accent_amber"],
                "critical": COLORS["accent_red"]}


def ratio_status(value: float) -> str:
    """'healthy' ≥110%, 'warning' 100–110%, 'critical' <100%. inf counts as healthy."""
    if value >= RATIO_BUFFER:
        return "healthy"
    if value >= RATIO_MINIMUM:
        return "warning"
    return "critical"


def css_variables() -> str:
    """COLORS as a :root block, e.g. bg_primary → --bg-primary."""
    decls = ";".join(f"--{k.replace('_', '-')}:{v}" for k, v in COLORS.items())
    return f":root{{{decls}}}"
