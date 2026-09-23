"""
Central chart theme (Altair / Vega-Lite).
=========================================
Every chart on every page goes through apply_theme() and render() so that
gridlines, fonts, heights and colours are identical across panels. Build the
chart, then `render(apply_theme(chart, height=...))` — never style per chart.

The app renders charts with Altair (a declared dependency) rather than
Plotly; the knobs below are the Vega-Lite equivalents of the usual Plotly
fixes (tickCount ≈ nticks, labelLimit=0 ≈ automargin).
"""
import altair as alt
import pandas as pd
import streamlit as st

from assets.theme import COLORS, FONT_FAMILY

# One height per context: every chart in a st.columns() row uses the same one.
PANEL_CHART_HEIGHT = 280
WIDE_CHART_HEIGHT = 300    # full-width time series (ILAAP ladder)
STRIP_CHART_HEIGHT = 190   # full-width 2–3 bar comparisons

# Vega's SI prefix for 1e9 is "G"; finance readers expect "B" (billion).
IDR_SHORT = "replace(format({v}, '.3~s'), 'G', 'B')"


def apply_theme(chart: alt.TopLevelMixin, *, height: int) -> alt.TopLevelMixin:
    """Apply the house style. `height` is the TOTAL rendered height (axes and
    title included), so side-by-side charts line up exactly."""
    text2, muted = COLORS["text_secondary"], COLORS["text_muted"]
    return (
        chart.properties(
            height=height,
            background="transparent",
            padding={"left": 16, "right": 20, "top": 14, "bottom": 12},
            autosize=alt.AutoSizeParams(type="fit", contains="padding"),
        )
        .configure(font=FONT_FAMILY)
        .configure_view(stroke=None)
        .configure_title(
            color=COLORS["text_primary"], fontSize=15, fontWeight=600,
            anchor="start", offset=14, subtitleColor=muted, subtitleFontSize=12,
        )
        .configure_axis(
            labelColor=text2, labelFontSize=12, labelPadding=6,
            titleColor=muted, titleFontSize=12, titleFontWeight=500, titlePadding=10,
            domain=False, ticks=False, gridColor=COLORS["grid"], gridWidth=1,
        )
        # Value axis: few, faint gridlines — no "barcode" effect.
        .configure_axisQuantitative(tickCount=5, grid=True)
        # Category axis: no per-row gridline, never truncate a label.
        .configure_axisBand(grid=False, labelLimit=0, labelFontSize=13, labelColor=COLORS["text_primary"])
        .configure_legend(
            labelColor=text2, labelFontSize=12, titleColor=muted, titleFontSize=12,
            symbolType="circle", symbolSize=90, orient="bottom", direction="horizontal",
        )
    )


def render(chart: alt.TopLevelMixin) -> None:
    # theme=None: Streamlit's own chart theme would override ours.
    st.altair_chart(chart, theme=None, width="stretch")


def prepare_bar_data(df: pd.DataFrame, value_col: str, hide_zero: bool = True):
    """Drop zero rows (they still eat a full band otherwise) and return
    (plot_df, omitted_labels) so the page can list what was left out."""
    label_col = df.columns[0]
    mask = df[value_col] > 0 if hide_zero else pd.Series(True, index=df.index)
    omitted = df.loc[~mask, label_col].tolist()
    return df[mask].sort_values(value_col, ascending=False), omitted


def hbar(df: pd.DataFrame, *, label: str, value: str, colors: dict, title: str,
         x_title: str = "IDR", height: int = PANEL_CHART_HEIGHT, hide_zero: bool = True):
    """Themed horizontal bar chart with value labels. Returns (chart, omitted);
    chart is None when every category is zero.

    hide_zero=False for a fixed, small set of bars that are always meaningful
    together (e.g. Outflow/Inflow/Net) — hiding one because it happens to be
    zero this period would make the remaining bars look like they compare
    the wrong things."""
    data, omitted = prepare_bar_data(df[[label, value]], value, hide_zero=hide_zero)
    if data.empty:
        return None, omitted
    order = data[label].tolist()
    x_max = float(data[value].max()) * 1.18   # headroom for the end-of-bar labels
    y = alt.Y(f"{label}:N", sort=order, title=None, axis=alt.Axis(labelPadding=10))
    base = alt.Chart(data, title=title).encode(y=y)
    bars = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.62}).encode(
        x=alt.X(f"{value}:Q", title=x_title, scale=alt.Scale(domain=[0, x_max], nice=False),
                axis=alt.Axis(labelExpr=IDR_SHORT.format(v="datum.value"))),
        color=alt.Color(f"{label}:N", legend=None,
                        scale=alt.Scale(domain=list(colors), range=list(colors.values()))),
        tooltip=[alt.Tooltip(f"{label}:N", title="Category"),
                 alt.Tooltip(f"{value}:Q", format=",.0f", title="IDR")],
    )
    text = base.transform_calculate(
        _lbl=IDR_SHORT.format(v=f"datum['{value}']")
    ).mark_text(align="left", dx=6, fontSize=12, fontWeight=600, color=COLORS["text_primary"]).encode(
        x=alt.X(f"{value}:Q"), text="_lbl:N",
    )
    return apply_theme(bars + text, height=height), omitted


def omitted_note(omitted: list[str]) -> None:
    if omitted:
        st.caption("Nil this period (not plotted): " + ", ".join(omitted))
