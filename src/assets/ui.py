"""
Shared HTML components for the pages (KPI cards, hero, status panel).
All markup is single-line so st.markdown never mistakes indentation for a
code block. Colours come from CSS variables defined off assets/theme.py.
"""
import html

import streamlit as st

from assets.icons import icon
from assets.theme import STATUS_LABEL


def md(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def hero(title: str, subtitle: str, badge: str, icon_name: str, variant: str = "blue") -> None:
    md(f'<div class="lr-hero lr-hero--{variant}"><div class="lr-hero__badge">{icon(icon_name, 14)}'
       f'<span>{badge}</span></div><h1>{title}</h1><p>{subtitle}</p></div>')


def section(title: str) -> None:
    md(f'<div class="section-label">{title}</div>')


def kpi_card(icon_name: str, label: str, value: str, status: str | None = None) -> str:
    """status: 'healthy' | 'warning' | 'critical' drives the top bar; None = neutral
    (for amounts that have no threshold, e.g. Total ASF)."""
    return (f'<div class="kpi-card"><div class="kpi-card__status-bar kpi-card__status-bar--{status or "neutral"}"></div>'
            f'<span class="kpi-card__icon">{icon(icon_name, 18)}</span>'
            f'<div class="kpi-card__value">{html.escape(value)}</div>'
            f'<div class="kpi-card__label">{label}</div></div>')


def kpi_grid(cards: list[str]) -> None:
    md(f'<div class="kpi-grid">{"".join(cards)}</div>')


def pill(text: str, status: str) -> str:
    return f'<span class="status-pill status-pill--{status}">{text}</span>'


def status_panel(title: str, display: str, status: str, *, label: str | None = None,
                 fill_pct: float | None = None, scale_labels: tuple = (), note: str = "") -> None:
    """Headline status block: big figure + status pill, optional gauge and note."""
    gauge = ""
    if fill_pct is not None:
        ticks = "".join(f"<span>{t}</span>" for t in scale_labels)
        gauge = (f'<div class="gauge-track"><div class="gauge-fill gauge-fill--{status}" '
                 f'style="width:{fill_pct:.1f}%;"></div></div><div class="gauge-labels">{ticks}</div>')
    note_html = f'<div class="status-panel__note">{note}</div>' if note else ""
    md(f'<div class="status-panel status-panel--{status}"><div class="status-panel__title">{title}</div>'
       f'<div class="status-panel__row"><span class="status-panel__value">{display}</span>'
       f'{pill(label or STATUS_LABEL[status], status)}</div>{gauge}{note_html}</div>')


def file_badge(key: str, filename: str | None) -> str:
    ok = filename is not None
    return (f'<div class="file-badge file-badge--{"ok" if ok else "missing"}">'
            f'{icon("circle-check" if ok else "circle-alert", 16)}'
            f'<span class="file-badge__label">{key}</span>'
            f'<span class="file-badge__name">{html.escape(filename) if ok else "not uploaded"}</span></div>')


def empty_state(icon_name: str, title: str, body: str) -> None:
    md(f'<div class="empty-state">{icon(icon_name, 32, stroke=1.5)}<h3>{title}</h3><p>{body}</p></div>')


def footer(text: str) -> None:
    md(f'<div class="lr-footer">{text}</div>')
