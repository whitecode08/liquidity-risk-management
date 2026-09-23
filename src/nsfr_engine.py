"""
NSFR Engine — Net Stable Funding Ratio Calculation
====================================================
Implements POJK No. 20 Tahun 2025 — ASF and RSF factors for Islamic Banks (BUS & UUS).

Formula:
    NSFR = ASF / RSF × 100%   ≥ 100% required

ASF (Available Stable Funding): weighted liabilities + equity by maturity bucket
RSF (Required Stable Funding):  weighted assets by maturity bucket

Maturity buckets:
  Bucket A — No maturity / < 6 months  (demand deposits, short-term)
  Bucket B — ≥ 6 months < 1 year
  Bucket C — ≥ 1 year                  (long-term stable)

Reference: POJK No. 20 Tahun 2025, Lampiran NSFR
"""

import io
import math
import pandas as pd
import numpy as np
from openpyxl import load_workbook


# ── Helpers ───────────────────────────────────────────────────────────────────

def _days_to_maturity(df: pd.DataFrame, asof_date: str, col: str = 'tanggalJatuhTempo') -> pd.Series:
    return (pd.to_datetime(df[col]) - pd.to_datetime(asof_date)).dt.days


def _bucket(days: float) -> str:
    """Classify remaining days into NSFR maturity bucket."""
    if pd.isna(days) or days < 0:
        return 'A'  # no maturity or overdue → short-term bucket
    if days < 180:   # < 6 months
        return 'A'
    if days < 365:   # 6m – 1yr
        return 'B'
    return 'C'       # ≥ 1 year


def fmt_currency(x: float) -> str:
    try:
        return f"{x:,.0f}"
    except Exception:
        return "-"


def to_million(v) -> float:
    try:
        return float(v) / 1e6
    except Exception:
        return 0.0


# ── ASF — Available Stable Funding ────────────────────────────────────────────

def asf_calc(df_tab: pd.DataFrame, df_giro: pd.DataFrame, df_depo: pd.DataFrame,
             df_nrc_rangkuman: pd.DataFrame, asof_date: str) -> dict:
    """Calculate ASF components and bucket them strictly for OJK template matching."""
    for df in (df_tab, df_giro, df_depo):
        df['jumlahBulanLaporanActive'] = df['jumlahBulanLaporan'] - df['nominalDiblokir']

    def _cat(x):
        v = x.get('kategoriNasabah')
        if pd.isna(v) or not v:
            amt = x['jumlahBulanLaporanActive']
            return 'Retail' if amt <= 500_000_000 else ('UMK' if amt <= 1_000_000_000 else 'Korporasi')
        return v

    for df in (df_tab, df_giro, df_depo):
        df['kategoriNasabah'] = df.apply(_cat, axis=1)
        df['stabil'] = df['jumlahBulanLaporanActive'] <= 2e9

    df_depo['tenorDays'] = _days_to_maturity(df_depo, asof_date)
    df_depo['bucket']    = df_depo['tenorDays'].apply(_bucket)
    df_tab['bucket']  = 'A'
    df_giro['bucket'] = 'A'

    def _sum_by(df, cat, stabil, bucket=None):
        mask = (df['kategoriNasabah'] == cat) & (df['stabil'] == stabil)
        if bucket:
            mask &= df['bucket'] == bucket
        return df.loc[mask, 'jumlahBulanLaporanActive'].sum()

    # Retail
    ret_stable_demand   = _sum_by(df_tab,  'Retail', True)  + _sum_by(df_giro, 'Retail', True)
    ret_stable_depo_A   = _sum_by(df_depo, 'Retail', True,  'A')
    ret_stable_depo_B   = _sum_by(df_depo, 'Retail', True,  'B')
    ret_stable_depo_C   = _sum_by(df_depo, 'Retail', True,  'C')
    ret_unstable_demand = _sum_by(df_tab,  'Retail', False) + _sum_by(df_giro, 'Retail', False)
    ret_unstable_depo_A = _sum_by(df_depo, 'Retail', False, 'A')
    ret_unstable_depo_B = _sum_by(df_depo, 'Retail', False, 'B')
    ret_unstable_depo_C = _sum_by(df_depo, 'Retail', False, 'C')

    asf_ret_stable   = 0.95 * (ret_stable_demand + ret_stable_depo_A + ret_stable_depo_B) + 1.0 * ret_stable_depo_C
    asf_ret_unstable = 0.90 * (ret_unstable_demand + ret_unstable_depo_A + ret_unstable_depo_B) + 1.0 * ret_unstable_depo_C

    # SME (UMK)
    umk_stable_demand   = _sum_by(df_tab,  'UMK', True)  + _sum_by(df_giro, 'UMK', True)
    umk_stable_depo_A   = _sum_by(df_depo, 'UMK', True, 'A')
    umk_stable_depo_B   = _sum_by(df_depo, 'UMK', True, 'B')
    umk_stable_depo_C   = _sum_by(df_depo, 'UMK', True, 'C')
    umk_unstable_demand = _sum_by(df_tab,  'UMK', False) + _sum_by(df_giro, 'UMK', False)
    umk_unstable_depo_A = _sum_by(df_depo, 'UMK', False, 'A')
    umk_unstable_depo_B = _sum_by(df_depo, 'UMK', False, 'B')
    umk_unstable_depo_C = _sum_by(df_depo, 'UMK', False, 'C')

    asf_umk_stable   = 0.95 * (umk_stable_demand + umk_stable_depo_A + umk_stable_depo_B) + 1.0 * umk_stable_depo_C
    asf_umk_unstable = 0.90 * (umk_unstable_demand + umk_unstable_depo_A + umk_unstable_depo_B) + 1.0 * umk_unstable_depo_C

    # Corporate
    corp_op = (_sum_by(df_tab,  'Korporasi', True)  + _sum_by(df_tab,  'Korporasi', False)
             + _sum_by(df_giro, 'Korporasi', True)  + _sum_by(df_giro, 'Korporasi', False))
    corp_nop_A = _sum_by(df_depo, 'Korporasi', True,  'A') + _sum_by(df_depo, 'Korporasi', False, 'A')
    corp_nop_B = _sum_by(df_depo, 'Korporasi', True,  'B') + _sum_by(df_depo, 'Korporasi', False, 'B')
    corp_nop_C = _sum_by(df_depo, 'Korporasi', True,  'C') + _sum_by(df_depo, 'Korporasi', False, 'C')

    asf_corp_op = 0.50 * corp_op
    # Corp non-op <6m is 50%, 6-1y is 50%, >=1y is 100%
    asf_corp_nop = 0.50 * (corp_nop_A + corp_nop_B) + 1.0 * corp_nop_C

    tier1_capital = 0.0
    asf_capital   = 1.00 * tier1_capital

    total_asf = asf_ret_stable + asf_ret_unstable + asf_umk_stable + asf_umk_unstable + asf_corp_op + asf_corp_nop + asf_capital

    return {
        "ret_stable_demand": ret_stable_demand,
        "ret_stable_depo_A": ret_stable_depo_A,
        "ret_stable_depo_B": ret_stable_depo_B,
        "ret_stable_depo_C": ret_stable_depo_C,
        "ret_unstable_demand": ret_unstable_demand,
        "ret_unstable_depo_A": ret_unstable_depo_A,
        "ret_unstable_depo_B": ret_unstable_depo_B,
        "ret_unstable_depo_C": ret_unstable_depo_C,
        "umk_stable_demand": umk_stable_demand,
        "umk_stable_depo_A": umk_stable_depo_A,
        "umk_stable_depo_B": umk_stable_depo_B,
        "umk_stable_depo_C": umk_stable_depo_C,
        "umk_unstable_demand": umk_unstable_demand,
        "umk_unstable_depo_A": umk_unstable_depo_A,
        "umk_unstable_depo_B": umk_unstable_depo_B,
        "umk_unstable_depo_C": umk_unstable_depo_C,
        "corp_op": corp_op,
        "corp_nop_A": corp_nop_A,
        "corp_nop_B": corp_nop_B,
        "corp_nop_C": corp_nop_C,
        "tier1_capital": tier1_capital,
        
        # Display outputs
        "ASF Retail Stable (95%)": asf_ret_stable,
        "ASF Retail Unstable (90%)": asf_ret_unstable,
        "ASF SME Stable (95%)": asf_umk_stable,
        "ASF SME Unstable (90%)": asf_umk_unstable,
        "ASF Corporate (50%)": asf_corp_op + asf_corp_nop,
        "Total ASF": total_asf,
    }


# ── RSF — Required Stable Funding ─────────────────────────────────────────────

def rsf_calc(df_nrc_aset: pd.DataFrame, df_fin: pd.DataFrame,
             df_pbi: pd.DataFrame, df_sukbi: pd.DataFrame,
             df_nrc_rangkuman: pd.DataFrame, asof_date: str) -> dict:
    
    total_kas = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'KAS', 'REALISASI'].values[0]
    total_fasbis = df_pbi.loc[df_pbi.get('jenisPenempatan').eq('F08'), 'jumlah'].sum()
    total_giro_bi = df_pbi.loc[df_pbi.get('jenisPenempatan').eq('F09'), 'jumlah'].sum()
    total_sukbi = df_sukbi.loc[df_sukbi.get('SedangDiagunkan').eq('Tidak'), 'nominal'].sum()
    
    interbank = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'PENEMPATAN PADA BANK LAIN', 'REALISASI'].values[0]
    rsf_interbank = 0.15 * interbank

    df_f = df_fin.copy()
    df_f['tenorDays'] = _days_to_maturity(df_f, asof_date)
    df_f['bucket']    = df_f['tenorDays'].apply(_bucket)

    perf_A = df_f[(df_f['kualitas'] <= 2) & (df_f['bucket'] == 'A')]['jumlah'].sum()
    perf_B = df_f[(df_f['kualitas'] <= 2) & (df_f['bucket'] == 'B')]['jumlah'].sum()
    perf_C = df_f[(df_f['kualitas'] <= 2) & (df_f['bucket'] == 'C')]['jumlah'].sum()
    npf    = df_f[df_f['kualitas'] >= 3]['jumlah'].sum()

    rsf_perf_A = 0.50 * perf_A
    rsf_perf_B = 0.50 * perf_B
    rsf_perf_C = 0.65 * perf_C  # Template applies 0.65 for >=1y performing
    rsf_npf    = 1.00 * npf

    aset_tetap = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'ASET TETAP DAN INVENTARIS', 'REALISASI']
    fixed_assets = float(aset_tetap.values[0]) if len(aset_tetap) > 0 else 0.0
    
    other_assets_row = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'].str.contains('ASET LAINNYA', case=False, na=False), 'REALISASI']
    other_assets = float(other_assets_row.values[0]) if len(other_assets_row) > 0 else 0.0
    
    surat_berharga_row = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'SURAT BERHARGA YANG DIMILIKI', 'REALISASI']
    total_sb = float(surat_berharga_row.values[0]) if len(surat_berharga_row) > 0 else 0.0
    sukuk_bi_row = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'SUKUK BI', 'REALISASI']
    sukuk_bi = float(sukuk_bi_row.values[0]) if len(sukuk_bi_row) > 0 else 0.0
    non_hqla_sb = max(total_sb - sukuk_bi, 0.0)
    rsf_sb = 0.50 * non_hqla_sb

    total_rsf = rsf_interbank + rsf_perf_A + rsf_perf_B + rsf_perf_C + rsf_npf + fixed_assets + other_assets + rsf_sb

    return {
        "kas": total_kas,
        "fasbis": total_fasbis + total_giro_bi,
        "sukbi": total_sukbi,
        "interbank": interbank,
        "perf_A": perf_A,
        "perf_B": perf_B,
        "perf_C": perf_C,
        "npf": npf,
        "fixed": fixed_assets,
        "other": other_assets,
        "non_hqla_sb": non_hqla_sb,
        
        # Display outputs
        "Cash (KAS)": total_kas,
        "BI Placement (FASBIS + Giro BI)": total_fasbis + total_giro_bi,
        "Interbank Placement": interbank,
        "Performing Financing < 6m": perf_A,
        "Performing Financing 6m-1yr": perf_B,
        "Performing Financing ≥1yr": perf_C,
        "Non-Performing Financing (NPF)": npf,
        "Fixed Assets": fixed_assets,
        "Other Assets": other_assets,
        
        "RSF — HQLA (0%)": 0.0,
        "RSF — Performing Financing <6m (50%)": rsf_perf_A,
        "RSF — Performing Financing 6m-1yr (50%)": rsf_perf_B,
        "RSF — Performing Financing ≥1yr (65%)": rsf_perf_C,
        "RSF — NPF (100%)": rsf_npf,
        "RSF — Fixed Assets (100%)": fixed_assets,
        
        "Total RSF": total_rsf,
    }

# ── NSFR ─────────────────────────────────────────────────────────────────────

def nsfr_calculation(hasil_asf: dict, hasil_rsf: dict) -> dict:
    total_asf = hasil_asf["Total ASF"]
    total_rsf = hasil_rsf["Total RSF"]
    nsfr = (total_asf / total_rsf * 100.0) if total_rsf != 0 else float('inf')
    return {
        "Total ASF": total_asf,
        "Total RSF": total_rsf,
        "NSFR":      nsfr,
    }


# ── Excel Report ──────────────────────────────────────────────────────────────

def generate_nsfr_report_excel(template_file, hasil_asf: dict, hasil_rsf: dict, asof_date: str) -> bytes:
    wb = load_workbook(template_file, data_only=False)
    ws = wb.active
    fmt = '_-* #,##0_-;[Red]_* (#,##0)_-;_-* "-"??_-;_-@_-'

    # Fix the #REF! errors baked into the native template. The raw template
    # ships with FOUR broken `=#REF!` formulas (verified against
    # template/Template NSFR.xlsx): C54, E55, C66, G151.
    #   - C54 and E55 are legitimate value cells for "kas dan setara kas" and
    #     "penempatan pada Bank Indonesia" — the mappings below overwrite them
    #     with real figures, which clears the #REF! as a side effect.
    #   - C66 ("Simpanan/penempatan dana pada lembaga keuangan lain UNTUK
    #     aktivitas operasional — unencumbered") and G151 (undrawn commitment
    #     off-balance-sheet) have no corresponding figure anywhere in
    #     rsf_calc()'s output — the source data does not split interbank
    #     placements into operational vs. non-operational, so there is
    #     nothing legitimate to put there. Clear them explicitly rather than
    #     leaving a #REF! in the exported report.
    for ref_cell in ("C66", "G151"):
        try:
            ws[ref_cell].value = None
        except Exception:
            pass

    # Wipe leftover sample figures baked into the raw template. The template
    # ships pre-filled with a fictional example bank's numbers on many leaf
    # rows the engine doesn't compute (e.g. row 118 "pembiayaan beragun rumah
    # tinggal/KPR" alone carries ~Rp 374 miliar of example data), and even on
    # rows we DO map, only one of the four tenor-bucket columns is ours — the
    # other three still hold the example bank's figures. Because Total ASF /
    # Total RSF / NSFR% (column K, "Total Nilai Tertimbang") are computed by
    # the template's OWN formulas from these raw value cells, every leftover
    # number silently inflates the exported ratio with data that has nothing
    # to do with the bank whose files were actually uploaded — this is why
    # the exported Excel's NSFR% did not match the Streamlit-computed NSFR.
    # Fix: blank every plain-number leaf cell in the ASF (rows 5-44) and RSF
    # (rows 52-148) value columns (C/E/G/I only — factor columns D/F/H/J and
    # subtotal formula cells like "=SUM(...)" are left untouched) before
    # writing in the figures this engine actually computed.
    for r in list(range(5, 45)) + list(range(52, 149)):
        for col in ("C", "E", "G", "I"):
            cell = ws[f"{col}{r}"]
            if isinstance(cell.value, (int, float)):
                cell.value = None

    # Exact Cell Mappings
    mappings = {
        # ASF
        "C12": to_million(hasil_asf.get("ret_stable_demand")),
        "E13": to_million(hasil_asf.get("ret_stable_depo_A")),
        "G13": to_million(hasil_asf.get("ret_stable_depo_B")),
        "I13": to_million(hasil_asf.get("ret_stable_depo_C")),
        "C15": to_million(hasil_asf.get("ret_unstable_demand")),
        "E16": to_million(hasil_asf.get("ret_unstable_depo_A")),
        "G16": to_million(hasil_asf.get("ret_unstable_depo_B")),
        "I16": to_million(hasil_asf.get("ret_unstable_depo_C")),
        "C20": to_million(hasil_asf.get("umk_stable_demand")),
        "E21": to_million(hasil_asf.get("umk_stable_depo_A")),
        "G21": to_million(hasil_asf.get("umk_stable_depo_B")),
        "I21": to_million(hasil_asf.get("umk_stable_depo_C")),
        "C23": to_million(hasil_asf.get("umk_unstable_demand")),
        "E24": to_million(hasil_asf.get("umk_unstable_depo_A")),
        "G24": to_million(hasil_asf.get("umk_unstable_depo_B")),
        "I24": to_million(hasil_asf.get("umk_unstable_depo_C")),
        "C27": to_million(hasil_asf.get("corp_op")),
        "E29": to_million(hasil_asf.get("corp_nop_A")),
        "G29": to_million(hasil_asf.get("corp_nop_B")),
        "I29": to_million(hasil_asf.get("corp_nop_C")),
        # Row 7 ("1.1.1 Modal inti (Tier 1)") is the correct Tier 1 capital
        # cell. The previous mapping ("C39") targeted "Liabilitas dan ekuitas
        # lainnya" instead — a legitimate `=SUM(C41:C44)` subtotal — and
        # silently clobbered it with 0 on every export.
        "C7": to_million(hasil_asf.get("tier1_capital")),

        # RSF
        "C54": to_million(hasil_rsf.get("kas")),
        # Row 55 ("1.1.2 penempatan pada Bank Indonesia") reports under the
        # "< 6 bulan" column (E), not the "Tanpa Jangka Waktu" column (C) —
        # the previous mapping wrote to C55, leaving E55's #REF! formula
        # intact and never actually surfacing the FASBIS/Giro BI figure.
        "E55": to_million(hasil_rsf.get("fasbis")),
        "C57": to_million(hasil_rsf.get("sukbi")),
        "E86": to_million(hasil_rsf.get("interbank")),
        "E93": to_million(hasil_rsf.get("perf_A")),
        "G93": to_million(hasil_rsf.get("perf_B")),
        "I93": to_million(hasil_rsf.get("perf_C")),
        "E130": to_million(hasil_rsf.get("non_hqla_sb")),
        "I142": to_million(hasil_rsf.get("npf")),
        "I144": to_million(hasil_rsf.get("fixed")),
        "I148": to_million(hasil_rsf.get("other")),
    }

    for addr, val in mappings.items():
        if val is not None:
            try:
                ws[addr].value = val
                ws[addr].number_format = fmt
            except Exception:
                pass

    try:
        ws['A1'].value = f"TEMPLATE NET STABLE FUNDING RATIO (NSFR) — {asof_date}"
    except Exception:
        pass

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.read()
