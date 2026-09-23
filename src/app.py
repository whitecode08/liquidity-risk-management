"""
Liquidity Risk Management — App Router
========================================
Run with:  streamlit run src/app.py
"""
import pathlib, sys
import streamlit as st

_SRC_DIR  = pathlib.Path(__file__).resolve().parent
_CSS_FILE = _SRC_DIR / "assets" / "style.css"
(_SRC_DIR.parent / "output").mkdir(parents=True, exist_ok=True)
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from assets.icons import NAV, icon  # noqa: E402
from assets.theme import css_variables  # noqa: E402

st.set_page_config(
    page_title="Liquidity Risk Management",
    page_icon=NAV["lcr"],
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def _stylesheet(mtime: float) -> str:
    # Colour tokens first (generated from assets/theme.py), then the stylesheet.
    return f"<style>{css_variables()}\n{_CSS_FILE.read_text(encoding='utf-8')}</style>"


if _CSS_FILE.exists():
    st.markdown(_stylesheet(_CSS_FILE.stat().st_mtime), unsafe_allow_html=True)

with st.sidebar:
    st.markdown(
        f'<div class="sidebar-brand"><div class="brand-icon">{icon("droplet", 20, stroke=2)}</div>'
        '<div class="brand-title">LIQUIDITY RISK<br/>MANAGEMENT</div>'
        '<div class="brand-live"><span class="pulse-dot"></span> System Active</div></div>',
        unsafe_allow_html=True,
    )

pg = st.navigation([
    st.Page("pages/0_Home.py",  title="Home",            icon=NAV["home"], default=True),
    st.Page("pages/1_LCR.py",  title="LCR Calculator",  icon=NAV["lcr"], url_path="lcr"),
    st.Page("pages/2_NSFR.py", title="NSFR Calculator",  icon=NAV["nsfr"], url_path="nsfr"),
    st.Page("pages/3_AI_Summary.py", title="AI Executive Summary", icon=NAV["ai"], url_path="ai-summary"),
    st.Page("pages/4_Stress_Testing.py", title="ILAAP Stress Testing", icon=NAV["stress"], url_path="stress-testing"),
    st.Page("pages/5_Audit_Log.py", title="Audit Log", icon=NAV["audit"], url_path="audit-log"),
])
pg.run()
