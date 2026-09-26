"""
Cached orchestration around the calculation engines.
=====================================================
The engines (lcr_engine, nsfr_engine, ilaap/*) are untouched; this module
only memoises the calls the pages make, keyed on file *content* rather than
on UploadedFile objects (whose identity changes every rerun, so caching on
them would always miss).

Wins: LCR and NSFR share the parsed workbooks (the same 7 uploads), changing
only the as-of date skips Excel parsing, and on the ILAAP page moving the
PLM / BI-liquidity inputs no longer rebuilds the cash-flow ladder.

Audit-trail writes stay in the pages — they are per-run side effects and
must never be served from a cache.
"""
import hashlib
import io

import pandas as pd
import streamlit as st

from lcr_engine import (
    hqla_calc, dpk_organize, outflow_retail, outflow_umk, outflow_corp,
    outflow_sektor_publik, outflow_bank,
    outflow_additional, inflow_counterparty, lcr_calculation, safe_read_excel,
    generate_report_excel,
)
from nsfr_engine import asf_calc, rsf_calc, nsfr_calculation, generate_nsfr_report_excel
from ilaap import survival_period as sp
from ilaap import audit as ilaap_audit


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sources_digest(sources: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for key in sorted(sources):
        h.update(key.encode()); h.update(digest(sources[key]).encode())
    return h.hexdigest()


# ── Parsing ──────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, max_entries=64)
def _read(file_hash: str, _data: bytes, sheet_name) -> pd.DataFrame:
    kwargs = {} if sheet_name is None else {"sheet_name": sheet_name}
    return safe_read_excel(io.BytesIO(_data), **kwargs)


def read(data: bytes, sheet_name=None) -> pd.DataFrame:
    return _read(digest(data), data, sheet_name)


# ── As-of date, derived from the data ────────────────────────────────────────
# The reporting date is not something the user picks — every uploaded file
# already carries it in its own `periodeData` column, and every tenor/maturity
# calculation is only meaningful as of THAT date. A free-standing date picker
# defaulting to "today" used to be the actual input here, with nothing tying
# it to the files: leaving it unchanged silently computed a fully plausible
# but wrong LCR/NSFR (every deposit reads as matured early, outflow balloons,
# inflow evaporates) with no error to catch it. Reading the date out of the
# files themselves removes the chance to get it wrong.
_PERIODE_DATA_CANDIDATES = ("Tabungan", "Giro", "Deposito", "Pinjaman", "PenempatanBI", "SBI")


@st.cache_data(show_spinner=False, max_entries=32)
def _peek_periode_data(file_hash: str, _data: bytes) -> str | None:
    try:
        df = safe_read_excel(io.BytesIO(_data), nrows=1)
        val = df.get("periodeData")
        if val is None or val.empty or pd.isna(val.iloc[0]):
            return None
        return str(val.iloc[0])[:10]
    except Exception:
        return None


def detect_asof_dates(sources: dict[str, bytes]) -> dict[str, str]:
    """`periodeData` found in each of the given uploaded files, keyed by
    source name — only for files whose sheet actually carries the column
    (NeracaHarian's ASET/LIABILITAS/RKA/RANGKUMAN sheets don't). Files that
    fail to parse or carry no value are simply left out, not reported as an
    error here — callers decide what an incomplete result means."""
    found = {}
    for key in _PERIODE_DATA_CANDIDATES:
        data = sources.get(key)
        if not data:
            continue
        val = _peek_periode_data(digest(data), data)
        if val:
            found[key] = val
    return found


def resolve_asof_date(sources: dict[str, bytes]) -> tuple[str | None, dict[str, str]]:
    """The single as-of date to run the calculation for, derived from the
    files themselves.

    Returns (asof, per_file): `asof` is that date when every file that reports
    one agrees, and None when no file reports one yet OR the files disagree
    (mixed reporting periods) — either way the caller must not proceed with a
    calculation. `per_file` is always returned so the caller can show exactly
    which file said what.
    """
    per_file = detect_asof_dates(sources)
    dates = set(per_file.values())
    return (dates.pop() if len(dates) == 1 else None), per_file


# ── LCR ──────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, max_entries=8)
def _run_lcr(key: str, asof: str, _src: dict[str, bytes]) -> dict:
    df_nrc_aset      = read(_src["NeracaHarian"], "ASET")
    df_nrc_rangkuman = read(_src["NeracaHarian"], "RANGKUMAN")
    df_rka           = read(_src["NeracaHarian"], "RKA")
    df_pbi           = read(_src["PenempatanBI"])
    df_sbi         = read(_src["SBI"])
    df_tab           = read(_src["Tabungan"])
    df_giro          = read(_src["Giro"])
    df_depo          = read(_src["Deposito"])
    df_fin           = read(_src["Pinjaman"])

    df_tab, df_giro, df_depo = dpk_organize(df_tab, df_giro, df_depo, asof)
    hasil_hqla  = hqla_calc(df_nrc_aset, df_nrc_rangkuman, df_pbi, df_sbi)
    segments = [
        outflow_retail(df_tab, df_giro, df_depo, asof),
        outflow_umk(df_tab, df_giro, df_depo, asof),
        outflow_corp(df_tab, df_giro, df_depo, asof),
        outflow_sektor_publik(df_tab, df_giro, df_depo, asof),
        outflow_bank(df_tab, df_giro, df_depo, asof),
        outflow_additional(df_rka),
    ]
    hasil_outflow = {k: v for seg in segments for k, v in seg.items()}
    inflow = inflow_counterparty(df_fin, df_nrc_aset, asof)
    hasil_inflow = {**inflow, "Total Cash Inflow": inflow["Total Inflow Tagihan Counterparty (50%)"]}
    # lcr_calculation() sums every "Total Outflow Pendanaan ..." key plus
    # "Total Outflow Tambahan", so adding a funding segment above needs no
    # change here — and "Total Outflow" itself is not double-counted.
    hasil_lcr = lcr_calculation(hasil_hqla, hasil_outflow, hasil_inflow)
    hasil_outflow["Total Outflow"] = hasil_lcr["Total Cash Outflow"]
    return {
        "asof": asof,
        "dfs":  {"nrc_aset": df_nrc_aset, "nrc_rangkuman": df_nrc_rangkuman,
                 "rka": df_rka, "tab": df_tab, "giro": df_giro, "depo": df_depo, "fin": df_fin},
        "hqla": hasil_hqla, "outflow": hasil_outflow,
        "inflow": hasil_inflow, "lcr": hasil_lcr,
    }


def run_lcr(sources: dict[str, bytes], asof: str) -> dict:
    """sources: {"NeracaHarian": bytes, "PenempatanBI": bytes, ...}"""
    return _run_lcr(sources_digest(sources), asof, sources)


# ── NSFR ─────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, max_entries=8)
def _run_nsfr(key: str, asof: str, _src: dict[str, bytes]) -> dict:
    df_nrc_aset      = read(_src["NeracaHarian"], "ASET")
    df_nrc_rangkuman = read(_src["NeracaHarian"], "RANGKUMAN")
    df_pbi           = read(_src["PenempatanBI"])
    df_sbi         = read(_src["SBI"])
    df_tab           = read(_src["Tabungan"])
    df_giro          = read(_src["Giro"])
    df_depo          = read(_src["Deposito"])
    df_fin           = read(_src["Pinjaman"])

    # dpk_organize adds jumlahBulanLaporanActive, kategoriNasabah, hubunganMapan
    df_tab, df_giro, df_depo = dpk_organize(df_tab, df_giro, df_depo, asof)

    hasil_asf  = asf_calc(df_tab, df_giro, df_depo, df_nrc_rangkuman, asof)
    hasil_rsf  = rsf_calc(df_nrc_aset, df_fin, df_pbi, df_sbi, df_nrc_rangkuman, asof)
    hasil_nsfr = nsfr_calculation(hasil_asf, hasil_rsf)
    return {
        "asof": asof,
        "asf":  hasil_asf, "rsf": hasil_rsf, "nsfr": hasil_nsfr,
        "dfs":  {"nrc_aset": df_nrc_aset, "nrc_rangkuman": df_nrc_rangkuman,
                 "tab": df_tab, "giro": df_giro, "depo": df_depo, "fin": df_fin},
    }


def run_nsfr(sources: dict[str, bytes], asof: str) -> dict:
    return _run_nsfr(sources_digest(sources), asof, sources)


# ── OJK Excel reports (template bytes + results → workbook bytes) ────────────
@st.cache_data(show_spinner=False, max_entries=8)
def _lcr_report(tpl_hash, _tpl: bytes, hqla, outflow, inflow, asof) -> bytes:
    return generate_report_excel(io.BytesIO(_tpl), hqla, outflow, inflow, asof)


def lcr_report(tpl: bytes, hqla, outflow, inflow, asof) -> bytes:
    return _lcr_report(digest(tpl), tpl, hqla, outflow, inflow, asof)


@st.cache_data(show_spinner=False, max_entries=8)
def _nsfr_report(tpl_hash, _tpl: bytes, asf, rsf, asof) -> bytes:
    return generate_nsfr_report_excel(io.BytesIO(_tpl), asf, rsf, asof)


def nsfr_report(tpl: bytes, asf, rsf, asof) -> bytes:
    return _nsfr_report(digest(tpl), tpl, asf, rsf, asof)


# ── ILAAP ────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def time_buckets():
    return sp.load_time_buckets()


@st.cache_data(show_spinner=False)
def stress_scenarios():
    return sp.load_stress_scenarios()


@st.cache_data(show_spinner=False, max_entries=32)
def ladder_and_recon(ledger: pd.DataFrame, scenario_id: str, asof: str):
    """The expensive part of the ILAAP page (~4s). Depends only on the ledger,
    the scenario and the as-of date — NOT on the PLM / BI-liquidity inputs,
    so those can move freely without a rebuild. `ledger` is hashed by content."""
    buckets, scenario = time_buckets(), stress_scenarios()[scenario_id]
    ladder = sp.project_cashflow_ladder(ledger, buckets, scenario, asof)
    recon = ilaap_audit.reconcile_ladder(ledger, ladder, buckets, scenario, asof)
    return ladder, recon
