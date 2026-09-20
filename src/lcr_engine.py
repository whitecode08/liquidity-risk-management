"""
LCR Engine — Liquidity Coverage Ratio Calculation
==================================================
All business logic is preserved from the original lcr_st.py.
Do NOT modify calculation rates or logic without regulatory review.

Reference: POJK No. 20 Tahun 2025
"""

import io
import math
import numpy as np
import pandas as pd
from openpyxl import load_workbook


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_currency(x: float) -> str:
    try:
        return f"{x:,.0f}"
    except Exception:
        return "-"


def parse_number_from_str(v) -> float:
    s = str(v).strip() if v is not None else ""
    if not s or s == "-":
        return 0.0
    s = s.replace("Rp", "").replace(" ", "").replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        return 0.0


def to_million(v) -> float:
    return parse_number_from_str(v) / 1e6


def safe_read_excel(file, **kwargs) -> pd.DataFrame:
    try:
        return pd.read_excel(file, **kwargs)
    except ValueError:
        if hasattr(file, "seek"):
            file.seek(0)
        return pd.read_excel(file, **kwargs)


# ── HQLA ─────────────────────────────────────────────────────────────────────

def hqla_calc(df_nrc_aset: pd.DataFrame, df_nrc_rangkuman: pd.DataFrame,
              df_pbi: pd.DataFrame, df_sukbi: pd.DataFrame) -> dict:
    """Calculate High-Quality Liquid Assets (Level 1 only — bank has no Level 2)."""
    total_dpk    = df_nrc_rangkuman.loc[df_nrc_rangkuman['KETERANGAN'] == 'DPK (GIRO+TAB+DEPO)', 'REALISASI'].values[0]
    estimate_gwm = total_dpk * 0.035
    total_kas    = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'KAS', 'REALISASI'].values[0]
    total_sukbi  = df_sukbi.loc[df_sukbi.get("SedangDiagunkan").eq("Tidak"), 'nominal'].sum()
    total_giro_bi = df_pbi.loc[df_pbi.get("jenisPenempatan").eq("F09"), 'jumlah'].sum() - estimate_gwm
    total_fasbis  = df_pbi.loc[df_pbi.get("jenisPenempatan").eq("F08"), 'jumlah'].sum()
    penempatan_bi = total_sukbi + total_giro_bi + total_fasbis
    hqla_level_1  = total_kas + penempatan_bi
    hqla_level_2  = 0.0
    total_hqla    = hqla_level_1 + hqla_level_2
    return {
        "Cash & Cash Equivalents":   total_kas,
        "Placement at Central Bank": penempatan_bi,
        "HQLA Level 1":              hqla_level_1,
        "HQLA Level 2":              hqla_level_2,
        "Total HQLA":                total_hqla,
    }


# ── DPK Organisation ──────────────────────────────────────────────────────────

def dpk_organize(df_tab: pd.DataFrame, df_giro: pd.DataFrame, df_depo: pd.DataFrame):
    """Net blocked amounts and assign customer category."""
    for df in (df_tab, df_giro, df_depo):
        df['jumlahBulanLaporanActive'] = df['jumlahBulanLaporan'] - df['nominalDiblokir']

    def _fallback_cat(x):
        v = x.get('kategoriNasabah')
        if pd.isna(v) or not v:
            amt = x['jumlahBulanLaporanActive']
            if amt <= 500_000_000:
                return 'Retail'
            elif amt <= 1_000_000_000:
                return 'UMK'
            return 'Korporasi'
        return v

    df_tab['kategoriNasabah']  = df_tab.apply(_fallback_cat,  axis=1)
    df_giro['kategoriNasabah'] = df_giro.apply(_fallback_cat, axis=1)
    df_depo['kategoriNasabah'] = df_depo.apply(_fallback_cat, axis=1)
    return df_tab, df_giro, df_depo


# ── Cash Outflows ─────────────────────────────────────────────────────────────

def outflow_retail(df_tab, df_giro, df_depo, asof_date: str) -> dict:
    """Retail outflow: stable 5%, unstable 10%."""
    df_tab_r  = df_tab[df_tab['kategoriNasabah']  == 'Retail'].copy()
    df_giro_r = df_giro[df_giro['kategoriNasabah'] == 'Retail'].copy()
    df_depo_r = df_depo[df_depo['kategoriNasabah'] == 'Retail'].copy()

    for df in (df_tab_r, df_giro_r, df_depo_r):
        df['kategoriStabilitas'] = np.where(df['jumlahBulanLaporanActive'] <= 2e9, 'Stabil', 'Tidak Stabil')

    df_depo_r['tenorHari'] = (pd.to_datetime(df_depo_r['tanggalJatuhTempo']) - pd.to_datetime(asof_date)).dt.days
    df_depo_r = df_depo_r[(df_depo_r['tenorHari'] <= 30) & (df_depo_r['tenorHari'] > 0)]

    stable   = (df_tab_r.loc[df_tab_r['kategoriStabilitas']   == 'Stabil',       'jumlahBulanLaporanActive'].sum()
              + df_giro_r.loc[df_giro_r['kategoriStabilitas'] == 'Stabil',        'jumlahBulanLaporanActive'].sum()
              + df_depo_r.loc[df_depo_r['kategoriStabilitas'] == 'Stabil',        'jumlahBulanLaporanActive'].sum())
    unstable = (df_tab_r.loc[df_tab_r['kategoriStabilitas']   == 'Tidak Stabil', 'jumlahBulanLaporanActive'].sum()
              + df_giro_r.loc[df_giro_r['kategoriStabilitas'] == 'Tidak Stabil', 'jumlahBulanLaporanActive'].sum()
              + df_depo_r.loc[df_depo_r['kategoriStabilitas'] == 'Tidak Stabil', 'jumlahBulanLaporanActive'].sum())
    out_stable   = 0.05 * stable
    out_unstable = 0.10 * unstable
    return {
        "Retail Stable Funding":              stable,
        "Retail Unstable Funding":            unstable,
        "Outflow — Retail Stable (5%)":       out_stable,
        "Outflow — Retail Unstable (10%)":    out_unstable,
        "Total Outflow Pendanaan Perorangan": out_stable + out_unstable,
    }


def outflow_umk(df_tab, df_giro, df_depo, asof_date: str) -> dict:
    """SME (UMK) outflow: stable 5%, unstable 10%."""
    df_tab_u  = df_tab[df_tab['kategoriNasabah']   == 'UMK'].copy()
    df_giro_u = df_giro[df_giro['kategoriNasabah'] == 'UMK'].copy()
    df_depo_u = df_depo[df_depo['kategoriNasabah'] == 'UMK'].copy()

    for df in (df_tab_u, df_giro_u, df_depo_u):
        df['kategoriStabilitas'] = np.where(df['jumlahBulanLaporanActive'] <= 2e9, 'Stabil', 'Tidak Stabil')

    df_depo_u['tenorHari'] = (pd.to_datetime(df_depo_u['tanggalJatuhTempo']) - pd.to_datetime(asof_date)).dt.days
    df_depo_u = df_depo_u[(df_depo_u['tenorHari'] <= 30) & (df_depo_u['tenorHari'] > 0)]

    stable   = (df_tab_u.loc[df_tab_u['kategoriStabilitas']   == 'Stabil',       'jumlahBulanLaporanActive'].sum()
              + df_giro_u.loc[df_giro_u['kategoriStabilitas'] == 'Stabil',        'jumlahBulanLaporanActive'].sum()
              + df_depo_u.loc[df_depo_u['kategoriStabilitas'] == 'Stabil',        'jumlahBulanLaporanActive'].sum())
    unstable = (df_tab_u.loc[df_tab_u['kategoriStabilitas']   == 'Tidak Stabil', 'jumlahBulanLaporanActive'].sum()
              + df_giro_u.loc[df_giro_u['kategoriStabilitas'] == 'Tidak Stabil', 'jumlahBulanLaporanActive'].sum()
              + df_depo_u.loc[df_depo_u['kategoriStabilitas'] == 'Tidak Stabil', 'jumlahBulanLaporanActive'].sum())
    out_stable   = 0.05 * stable
    out_unstable = 0.10 * unstable
    return {
        "SME Stable Funding":            stable,
        "SME Unstable Funding":          unstable,
        "Outflow — SME Stable (5%)":     out_stable,
        "Outflow — SME Unstable (10%)":  out_unstable,
        "Total Outflow Pendanaan UMK":   out_stable + out_unstable,
    }


def outflow_corp(df_tab, df_giro, df_depo, asof_date: str) -> dict:
    """Corporate outflow: op-LPS 5%, op-nonLPS 25%, nonOp-LPS 20%, nonOp-nonLPS 40%."""
    df_tab_c  = df_tab[df_tab['kategoriNasabah']   == 'Korporasi'].copy()
    df_giro_c = df_giro[df_giro['kategoriNasabah'] == 'Korporasi'].copy()
    df_depo_c = df_depo[df_depo['kategoriNasabah'] == 'Korporasi'].copy()

    df_tab_c['kategoriRekening']  = "Operasional"
    df_giro_c['kategoriRekening'] = "Operasional"
    df_depo_c['tenorHari']        = (pd.to_datetime(df_depo_c['tanggalJatuhTempo']) - pd.to_datetime(asof_date)).dt.days
    df_depo_c['kategoriRekening'] = np.where(
        (df_depo_c['tenorHari'] <= 30) & (df_depo_c['tenorHari'] > 0), 'Operasional', 'Non Operasional')

    for df in (df_tab_c, df_giro_c, df_depo_c):
        df['kategoriLPS'] = np.where(df['jumlahBulanLaporanActive'] <= 2e9, 'Dijamin LPS', 'Tidak Dijamin LPS')

    def sum_amt(df, rek, lps):
        return df[(df['kategoriRekening'] == rek) & (df['kategoriLPS'] == lps)]['jumlahBulanLaporanActive'].sum()

    total_op_lps   = sum_amt(df_tab_c, 'Operasional',     'Dijamin LPS')       + sum_amt(df_giro_c, 'Operasional',     'Dijamin LPS')       + sum_amt(df_depo_c, 'Operasional',     'Dijamin LPS')
    total_op_nlps  = sum_amt(df_tab_c, 'Operasional',     'Tidak Dijamin LPS') + sum_amt(df_giro_c, 'Operasional',     'Tidak Dijamin LPS') + sum_amt(df_depo_c, 'Operasional',     'Tidak Dijamin LPS')
    total_nop_lps  = sum_amt(df_tab_c, 'Non Operasional', 'Dijamin LPS')       + sum_amt(df_giro_c, 'Non Operasional', 'Dijamin LPS')       + sum_amt(df_depo_c, 'Non Operasional', 'Dijamin LPS')
    total_nop_nlps = sum_amt(df_tab_c, 'Non Operasional', 'Tidak Dijamin LPS') + sum_amt(df_giro_c, 'Non Operasional', 'Tidak Dijamin LPS') + sum_amt(df_depo_c, 'Non Operasional', 'Tidak Dijamin LPS')
    total_corp     = total_op_lps + total_op_nlps + total_nop_lps + total_nop_nlps

    out_op_lps   = 0.05 * total_op_lps
    out_op_nlps  = 0.25 * total_op_nlps
    out_nop_lps  = 0.20 * total_nop_lps
    out_nop_nlps = 0.40 * total_nop_nlps
    return {
        "Corp Operational — LPS Covered":            total_op_lps,
        "Corp Operational — LPS Covered (5%)":       out_op_lps,
        "Corp Operational — Not LPS Covered":        total_op_nlps,
        "Corp Operational — Not LPS Covered (25%)":  out_op_nlps,
        "Corp Non-Op — LPS Covered":                 total_nop_lps,
        "Corp Non-Op — LPS Covered (20%)":           out_nop_lps,
        "Corp Non-Op — Not LPS Covered":             total_nop_nlps,
        "Corp Non-Op — Not LPS Covered (40%)":       out_nop_nlps,
        "Total Corporate Funding":                   total_corp,
        "Total Outflow Pendanaan Korporasi":         out_op_lps + out_op_nlps + out_nop_lps + out_nop_nlps,
    }


def outflow_additional(df_rka: pd.DataFrame) -> dict:
    """Additional outflows: undrawn financing 10%, guarantees 5%."""
    df = df_rka.copy()
    if 'KETERANGAN' in df.columns:
        df['KETERANGAN'] = df['KETERANGAN'].astype(str).str.strip()

    def sum_by_pattern(pat: str) -> float:
        mask = df['KETERANGAN'].str.contains(pat, case=False, na=False, regex=True)
        return float(df.loc[mask, 'NILAI'].fillna(0).sum())

    total_komitmen   = sum_by_pattern(r"FASILITAS\s+(PEMBIAYAAN)\s+YANG\s+BELUM\s+DITARIK")
    total_kontijensi = sum_by_pattern(r"GARANSI\s+YANG\s+DIBERIKAN")
    out_komitmen     = 0.10 * total_komitmen
    out_kontijensi   = 0.05 * total_kontijensi
    return {
        "Undrawn Financing Commitment":          total_komitmen,
        "Undrawn Financing Commitment (10%)":    out_komitmen,
        "Guarantee Contingency":                 total_kontijensi,
        "Guarantee Contingency (5%)":            out_kontijensi,
        "Total Outflow Tambahan":                out_komitmen + out_kontijensi,
    }


# ── Cash Inflows ──────────────────────────────────────────────────────────────

def inflow_counterparty(df_fin: pd.DataFrame, df_nrc_aset: pd.DataFrame, asof_date: str) -> dict:
    """Performing counterparty receivables ≤30d: 50%. Other bank placement: 0%."""
    df = df_fin.copy()
    df['tenorHari'] = (pd.to_datetime(df['tanggalJatuhTempo']) - pd.to_datetime(asof_date)).dt.days
    df = df[(df['tenorHari'] > 0) & (df['tenorHari'] <= 30)]
    df = df[df['kualitas'] == 1]
    total_tagihan   = df['jumlah'].sum()
    rate_tagihan    = 0.5 * total_tagihan
    total_placement = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'PENEMPATAN PADA BANK LAIN', 'REALISASI'].values[0]
    rate_placement  = 0.0
    return {
        "Counterparty Receivables (<=30d, Performing)": total_tagihan,
        "Total Inflow Tagihan Counterparty (50%)":       rate_tagihan,
        "Placement at Other Banks":                      total_placement,
        "Total Penempatan Dana Bank Lain (0%)":          rate_placement,
    }


# ── LCR ──────────────────────────────────────────────────────────────────────

def lcr_calculation(hasil_hqla: dict, hasil_outflow: dict, hasil_inflow: dict) -> dict:
    """
    LCR = HQLA / (Total Outflow - min(Inflow, 75% × Total Outflow)) × 100%
    Minimum required: 100% per POJK No. 20 Tahun 2025.
    """
    total_hqla    = hasil_hqla['Total HQLA']
    total_outflow = (
        parse_number_from_str(hasil_outflow['Total Outflow Pendanaan Perorangan'])
        + parse_number_from_str(hasil_outflow['Total Outflow Pendanaan UMK'])
        + parse_number_from_str(hasil_outflow['Total Outflow Pendanaan Korporasi'])
        + parse_number_from_str(hasil_outflow['Total Outflow Tambahan'])
    )
    total_inflow  = parse_number_from_str(hasil_inflow['Total Inflow Tagihan Counterparty (50%)'])
    cap_inflow    = min(total_outflow * 0.75, total_inflow)   # inflow capped at 75% of outflow
    denom         = total_outflow - cap_inflow
    lcr           = (total_hqla / denom * 100.0) if denom != 0 else float('inf')
    return {
        "Total HQLA":         total_hqla,
        "Total Cash Outflow": total_outflow,
        "Total Cash Inflow":  total_inflow,
        "LCR":                lcr,
    }


# ── Excel Report ──────────────────────────────────────────────────────────────

def generate_report_excel(template_file, hasil_hqla: dict, hasil_outflow: dict,
                           hasil_inflow: dict, asof_date: str) -> bytes:
    """Map LCR results into OJK Template LCR.xlsx and return as bytes."""
    wb = load_workbook(template_file, data_only=False)
    ws = wb['Sheet1']
    mapping = {
        "D5":   to_million(hasil_hqla.get('Cash & Cash Equivalents')),
        "D7":   to_million(hasil_hqla.get('Placement at Central Bank')),
        "D42":  to_million(hasil_outflow.get('Retail Stable Funding')),
        "D45":  to_million(hasil_outflow.get('Retail Unstable Funding')),
        "D56":  to_million(hasil_outflow.get('SME Stable Funding')),
        "D60":  to_million(hasil_outflow.get('SME Unstable Funding')),
        "D72":  to_million(hasil_outflow.get('Corp Operational — LPS Covered')),
        "D73":  to_million(hasil_outflow.get('Corp Operational — Not LPS Covered')),
        "D79":  to_million(hasil_outflow.get('Corp Non-Op — LPS Covered')),
        "D80":  to_million(hasil_outflow.get('Corp Non-Op — Not LPS Covered')),
        "D113": to_million(hasil_outflow.get('Undrawn Financing Commitment')),
        "D128": to_million(hasil_outflow.get('Guarantee Contingency')),
        "D154": to_million(hasil_inflow.get('Placement at Other Banks')),
        "D155": to_million(hasil_inflow.get('Counterparty Receivables (<=30d, Performing)')),
    }
    fmt = '_-* #,##0_-;[Red]_* (#,##0)_-;_-* "-"??_-;_-@_-'
    for addr, val in mapping.items():
        if val is not None:
            ws[addr].value = val
            ws[addr].number_format = fmt
    try:
        ws['B2'].value = f"Reporting Date: {asof_date}"
    except Exception:
        pass
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.read()
