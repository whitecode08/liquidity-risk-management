"""
Liquidity Risk Management — App Router
========================================
Run with:  streamlit run src/app.py
"""
import pathlib, streamlit as st

_SRC_DIR  = pathlib.Path(__file__).resolve().parent
_CSS_FILE = _SRC_DIR / "assets" / "style.css"
(_SRC_DIR.parent / "output").mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="Liquidity Risk Management",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

if _CSS_FILE.exists():
    st.markdown(f"<style>{_CSS_FILE.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
      <div class="brand-icon">💧</div>
      <div class="brand-title">LIQUIDITY RISK<br/>MANAGEMENT</div>
      <div class="brand-live"><span class="pulse-dot"></span> System Active</div>
    </div>
    """, unsafe_allow_html=True)

pg = st.navigation([
    st.Page("pages/0_Home.py",  title="Home",            icon="🏠", default=True),
    st.Page("pages/1_LCR.py",  title="LCR Calculator",  icon="💧", url_path="lcr"),
    st.Page("pages/2_NSFR.py", title="NSFR Calculator",  icon="🏦", url_path="nsfr"),
    st.Page("pages/3_AI_Summary.py", title="AI Executive Summary", icon="🤖", url_path="ai-summary"),
    st.Page("pages/4_Stress_Testing.py", title="ILAAP Stress Testing", icon="🌩️", url_path="stress-testing"),
    st.Page("pages/5_Audit_Log.py", title="Audit Log", icon="📒", url_path="audit-log"),
])
pg.run()
