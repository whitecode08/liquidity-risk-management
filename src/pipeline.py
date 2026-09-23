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


# ── LCR ──────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, max_entries=8)
def _run_lcr(key: str, asof: str, _src: dict[str, bytes]) -> dict:
    df_nrc_aset      = read(_src["NeracaHarian"], "ASET")
    df_nrc_rangkuman = read(_src["NeracaHarian"], "RANGKUMAN")
    df_rka           = read(_src["NeracaHarian"], "RKA")
    df_pbi           = read(_src["PenempatanBI"])
    df_sukbi         = read(_src["SBI"])
    df_tab           = read(_src["Tabungan"])
    df_giro          = read(_src["Giro"])
    df_depo          = read(_src["Deposito"])
    df_fin           = read(_src["Pinjaman"])

    df_tab, df_giro, df_depo = dpk_organize(df_tab, df_giro, df_depo)
    hasil_hqla  = hqla_calc(df_nrc_aset, df_nrc_rangkuman, df_pbi, df_sukbi)
    out_retail  = outflow_retail(df_tab, df_giro, df_depo, asof)
    out_umk     = outflow_umk(df_tab, df_giro, df_depo, asof)
    out_corp    = outflow_corp(df_tab, df_giro, df_depo, asof)
    out_add     = outflow_additional(df_rka)
    hasil_outflow = {
        **out_retail, **out_umk, **out_corp, **out_add,
        "Total Outflow": (
            out_retail["Total Outflow Pendanaan Perorangan"]
            + out_umk["Total Outflow Pendanaan UMK"]
            + out_corp["Total Outflow Pendanaan Korporasi"]
            + out_add["Total Outflow Tambahan"]
        ),
    }
    inflow = inflow_counterparty(df_fin, df_nrc_aset, asof)
    hasil_inflow = {**inflow, "Total Cash Inflow": inflow["Total Inflow Tagihan Counterparty (50%)"]}
    hasil_lcr = lcr_calculation(
        hasil_hqla,
        {k: hasil_outflow[k] for k in
         ["Total Outflow Pendanaan Perorangan", "Total Outflow Pendanaan UMK",
          "Total Outflow Pendanaan Korporasi", "Total Outflow Tambahan"]},
        hasil_inflow,
    )
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
    df_sukbi         = read(_src["SBI"])
    df_tab           = read(_src["Tabungan"])
    df_giro          = read(_src["Giro"])
    df_depo          = read(_src["Deposito"])
    df_fin           = read(_src["Pinjaman"])

    # dpk_organize adds jumlahBulanLaporanActive & kategoriNasabah
    df_tab, df_giro, df_depo = dpk_organize(df_tab, df_giro, df_depo)

    hasil_asf  = asf_calc(df_tab, df_giro, df_depo, df_nrc_rangkuman, asof)
    hasil_rsf  = rsf_calc(df_nrc_aset, df_fin, df_pbi, df_sukbi, df_nrc_rangkuman, asof)
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
