"""
NSFR Engine — Net Stable Funding Ratio Calculation
====================================================
ASF and RSF factors for a conventional bank (BPD / bank umum konvensional).

Formula:
    NSFR = ASF / RSF × 100%   ≥ 100% required

ASF (Available Stable Funding): weighted liabilities + equity by maturity bucket
RSF (Required Stable Funding):  weighted assets by maturity bucket

Maturity buckets:
  Bucket M — already matured (contractually payable now) → 0% ASF
  Bucket A — No maturity / < 6 months  (demand deposits, short-term)
  Bucket B — ≥ 6 months < 1 year
  Bucket C — ≥ 1 year                  (long-term stable)

Reference: POJK 50/POJK.03/2017 jo. POJK 20/2024 — Kewajiban Pemenuhan Rasio
Pendanaan Stabil Bersih (NSFR) bagi Bank Umum, Lampiran NSFR.

    (This engine previously cited POJK No. 20 Tahun 2025, which covers bank
    syariah — BUS/UUS — only.)

Customer categorisation, the LPS split and the stable-deposit test all come
from lcr_engine.py so the two ratios cannot drift apart. The Excel export at
the bottom of this file still targets the original OJK template layout and was
deliberately left untouched — see docs/REVISI_LIQUIDITY_RISK_BPD.md Fase 2.
"""

import io
import math
import pathlib
import sys

import pandas as pd
import numpy as np
from openpyxl import load_workbook

_SRC_DIR = pathlib.Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from lcr_engine import assign_kategori, hubungan_mapan, split_lps  # noqa: E402


# ── Regulatory factors needing confirmation ─────────────────────────────────
#
# PERLU KONFIRMASI — RSF factor for encumbered (pledged) securities.
# Lampiran POJK 50/POJK.03/2017 scales the RSF of an encumbered asset by how
# long the encumbrance runs, not by the paper's own tenor, and the source data
# does not report the encumbrance period. 100% is the conservative end of that
# range and is used as an explicit placeholder: it cannot understate RSF, but
# it will overstate it for short-dated pledges. Confirm the applicable factor
# (and, if it is period-dependent, add an encumbrance-end date to the SBI
# sheet) before any figure from this engine is reported.
RSF_SURAT_BERHARGA_DIAGUNKAN = 1.00  # PERLU KONFIRMASI


# ── Helpers ───────────────────────────────────────────────────────────────────

def _days_to_maturity(df: pd.DataFrame, asof_date: str, col: str = 'tanggalJatuhTempo') -> pd.Series:
    return (pd.to_datetime(df[col]) - pd.to_datetime(asof_date)).dt.days


def _bucket(days: float) -> str:
    """Classify remaining days into an NSFR maturity bucket.

    A contractually matured deposit gets its own bucket 'M' and 0% ASF — it is
    money already payable, not stable funding. It used to fall into bucket 'A'
    and be counted as up to 95% stable, while lcr_engine dropped the same rows
    from its outflow altogether: the two engines disagreed about the same
    balance. Both now treat it as maturing on day 0.
    """
    if pd.isna(days):
        return 'A'   # no contractual maturity (giro/tabungan) → short-term
    if days <= 0:
        return 'M'   # already matured
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

def _stability_frame(df: pd.DataFrame, asof_date: str, label: str,
                      has_tenor: bool) -> pd.DataFrame:
    """Long-form (kategori, stabil, bucket, amt) view of one DPK sheet.

    Each account contributes up to TWO rows, because the LPS limit cuts through
    the account rather than around it: the insured slice (≤ Rp2 miliar) is
    stable when the relationship is established, and the uninsured excess above
    the limit is never stable. Stability is therefore the LPS split AND the
    relationship test — the same two conditions lcr_engine applies — not the
    single `balance ≤ 2e9` test this function used to perform.
    """
    if 'jumlahBulanLaporanActive' not in df.columns:
        df['jumlahBulanLaporanActive'] = df['jumlahBulanLaporan'] - df['nominalDiblokir']
    kategori = (df['kategoriNasabah'] if 'kategoriNasabah' in df.columns
                else assign_kategori(df, label))
    mapan = (df['hubunganMapan'] if 'hubunganMapan' in df.columns
             else hubungan_mapan(df, asof_date))

    if has_tenor:
        bucket = _days_to_maturity(df, asof_date).apply(_bucket)
    else:
        bucket = pd.Series('A', index=df.index)

    dijamin, excess = split_lps(df['jumlahBulanLaporanActive'], df.get('sukuBungaBulanLaporan'))
    stable_amt = dijamin.where(mapan, 0.0)
    unstable_amt = dijamin.where(~mapan, 0.0) + excess

    return pd.concat([
        pd.DataFrame({'kategori': kategori, 'stabil': True, 'bucket': bucket, 'amt': stable_amt}),
        pd.DataFrame({'kategori': kategori, 'stabil': False, 'bucket': bucket, 'amt': unstable_amt}),
    ], ignore_index=True)


def asf_calc(df_tab: pd.DataFrame, df_giro: pd.DataFrame, df_depo: pd.DataFrame,
             df_nrc_rangkuman: pd.DataFrame, asof_date: str) -> dict:
    """Calculate ASF components and bucket them strictly for OJK template matching."""
    for df in (df_tab, df_giro, df_depo):
        df['jumlahBulanLaporanActive'] = df['jumlahBulanLaporan'] - df['nominalDiblokir']

    L_tab = _stability_frame(df_tab, asof_date, "Tabungan", has_tenor=False)
    L_giro = _stability_frame(df_giro, asof_date, "Giro", has_tenor=False)
    L_depo = _stability_frame(df_depo, asof_date, "Deposito", has_tenor=True)

    def _sum_by(L, cat, stabil, bucket=None):
        mask = (L['kategori'] == cat) & (L['stabil'] == stabil)
        if bucket:
            mask &= L['bucket'] == bucket
        return float(L.loc[mask, 'amt'].sum())

    # Retail
    ret_stable_demand   = _sum_by(L_tab,  'Retail', True)  + _sum_by(L_giro, 'Retail', True)
    ret_stable_depo_A   = _sum_by(L_depo, 'Retail', True,  'A')
    ret_stable_depo_B   = _sum_by(L_depo, 'Retail', True,  'B')
    ret_stable_depo_C   = _sum_by(L_depo, 'Retail', True,  'C')
    ret_unstable_demand = _sum_by(L_tab,  'Retail', False) + _sum_by(L_giro, 'Retail', False)
    ret_unstable_depo_A = _sum_by(L_depo, 'Retail', False, 'A')
    ret_unstable_depo_B = _sum_by(L_depo, 'Retail', False, 'B')
    ret_unstable_depo_C = _sum_by(L_depo, 'Retail', False, 'C')

    asf_ret_stable   = 0.95 * (ret_stable_demand + ret_stable_depo_A + ret_stable_depo_B) + 1.0 * ret_stable_depo_C
    asf_ret_unstable = 0.90 * (ret_unstable_demand + ret_unstable_depo_A + ret_unstable_depo_B) + 1.0 * ret_unstable_depo_C

    # SME (UMK)
    umk_stable_demand   = _sum_by(L_tab,  'UMK', True)  + _sum_by(L_giro, 'UMK', True)
    umk_stable_depo_A   = _sum_by(L_depo, 'UMK', True, 'A')
    umk_stable_depo_B   = _sum_by(L_depo, 'UMK', True, 'B')
    umk_stable_depo_C   = _sum_by(L_depo, 'UMK', True, 'C')
    umk_unstable_demand = _sum_by(L_tab,  'UMK', False) + _sum_by(L_giro, 'UMK', False)
    umk_unstable_depo_A = _sum_by(L_depo, 'UMK', False, 'A')
    umk_unstable_depo_B = _sum_by(L_depo, 'UMK', False, 'B')
    umk_unstable_depo_C = _sum_by(L_depo, 'UMK', False, 'C')

    asf_umk_stable   = 0.95 * (umk_stable_demand + umk_stable_depo_A + umk_stable_depo_B) + 1.0 * umk_stable_depo_C
    asf_umk_unstable = 0.90 * (umk_unstable_demand + umk_unstable_depo_A + umk_unstable_depo_B) + 1.0 * umk_unstable_depo_C

    # Corporate + Entitas Sektor Publik (Pemda/RKUD, BUMD, instansi/BLUD).
    # Both are "other legal entity" funding under the NSFR ladder and carry the
    # same factors — 50% under 1 year, 100% at or beyond 1 year — so they share
    # the template's corporate rows. They are still summed separately below so
    # the Pemda concentration is visible in the UI rather than buried.
    def _demand(cat):
        return sum(_sum_by(L, cat, st) for L in (L_tab, L_giro) for st in (True, False))

    def _depo(cat, bucket):
        return _sum_by(L_depo, cat, True, bucket) + _sum_by(L_depo, cat, False, bucket)

    pse = 'Entitas Sektor Publik'
    corp_op_korporasi, corp_op_pse = _demand('Korporasi'), _demand(pse)
    corp_op = corp_op_korporasi + corp_op_pse
    corp_nop_A = _depo('Korporasi', 'A') + _depo(pse, 'A')
    corp_nop_B = _depo('Korporasi', 'B') + _depo(pse, 'B')
    corp_nop_C = _depo('Korporasi', 'C') + _depo(pse, 'C')
    pse_total = corp_op_pse + _depo(pse, 'A') + _depo(pse, 'B') + _depo(pse, 'C')

    asf_corp_op = 0.50 * corp_op
    # Corp non-op <6m is 50%, 6-1y is 50%, >=1y is 100%
    asf_corp_nop = 0.50 * (corp_nop_A + corp_nop_B) + 1.0 * corp_nop_C

    # Funding from other banks / financial institutions: 0% ASF under 6 months,
    # 50% for 6m-1y, 100% at or beyond 1 year.
    #
    # NOTE (Fase 2): the OJK export template has no mapped row for this block,
    # so it contributes to the Streamlit NSFR but not to the exported workbook.
    # On the dummy BPD book it is a fraction of a percent of DPK; wire it into
    # the template when the template itself is revised.
    bank_demand = _demand('Bank')
    bank_A, bank_B, bank_C = _depo('Bank', 'A'), _depo('Bank', 'B'), _depo('Bank', 'C')
    asf_bank = 0.50 * bank_B + 1.0 * bank_C  # demand + <6m get 0%

    # Already-matured deposits (bucket 'M'): contractually payable now, so 0%
    # ASF — the mirror of the 100% run-off lcr_engine applies to the same rows.
    matured_depo = sum(_depo(cat, 'M') for cat in ('Retail', 'UMK', 'Korporasi', pse, 'Bank'))

    tier1_capital = 0.0
    asf_capital   = 1.00 * tier1_capital

    total_asf = (asf_ret_stable + asf_ret_unstable + asf_umk_stable + asf_umk_unstable
                 + asf_corp_op + asf_corp_nop + asf_bank + asf_capital)

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
        "ASF Corporate + Public Sector (50%)": asf_corp_op + asf_corp_nop,
        "Public Sector Funding (Pemda/BUMD/BLUD)": pse_total,
        "Bank/FI Funding": bank_demand + bank_A + bank_B + bank_C,
        "ASF Bank/FI": asf_bank,
        "Matured Deposits (0% ASF)": matured_depo,
        "Total ASF": total_asf,
    }


# ── RSF — Required Stable Funding ─────────────────────────────────────────────

def rsf_calc(df_nrc_aset: pd.DataFrame, df_fin: pd.DataFrame,
             df_pbi: pd.DataFrame, df_sbi: pd.DataFrame,
             df_nrc_rangkuman: pd.DataFrame, asof_date: str) -> dict:
    
    total_kas = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'KAS', 'REALISASI'].values[0]
    total_deposit_facility = df_pbi.loc[df_pbi.get('jenisPenempatan').eq('F08'), 'jumlah'].sum()
    total_giro_bi = df_pbi.loc[df_pbi.get('jenisPenempatan').eq('F09'), 'jumlah'].sum()
    total_sbi = df_sbi.loc[df_sbi.get('SedangDiagunkan').eq('Tidak'), 'nominal'].sum()
    
    interbank = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'PENEMPATAN PADA BANK LAIN', 'REALISASI'].values[0]
    rsf_interbank = 0.15 * interbank

    df_f = df_fin.copy()
    df_f['tenorDays'] = _days_to_maturity(df_f, asof_date)
    df_f['bucket']    = df_f['tenorDays'].apply(_bucket)

    # A loan maturing today still requires funding today — fold bucket 'M' into
    # the <6m bucket rather than letting it drop out of every sum.
    df_f['bucket'] = df_f['bucket'].replace({'M': 'A'})

    # Coerced rather than compared directly — see the matching note in
    # lcr_engine.inflow_counterparty(): a text-typed `kualitas` column would
    # otherwise fail every comparison silently and zero out this whole block.
    kualitas = pd.to_numeric(df_f['kualitas'], errors='coerce')
    perf_A = df_f[(kualitas <= 2) & (df_f['bucket'] == 'A')]['jumlah'].sum()
    perf_B = df_f[(kualitas <= 2) & (df_f['bucket'] == 'B')]['jumlah'].sum()
    perf_C = df_f[(kualitas <= 2) & (df_f['bucket'] == 'C')]['jumlah'].sum()
    npl    = df_f[kualitas >= 3]['jumlah'].sum()

    rsf_perf_A = 0.50 * perf_A
    rsf_perf_B = 0.50 * perf_B
    # TODO (Fase 3.7) — POJK 50/2017 sets a lower RSF for ≥1y loans carrying a
    # low risk weight (e.g. KPR beragun rumah tinggal) than for the rest (e.g.
    # KREDIT_ASN, unsecured against property). Applying one flat 65% overstates
    # RSF on the mortgage book and understates it on the ASN book. Implementing
    # the split needs a risk-weight (ATMR) field on the Pinjaman sheet, which
    # the source data does not yet carry — add the field first, then split here.
    rsf_perf_C = 0.65 * perf_C  # Template applies 0.65 for >=1y performing
    rsf_npl    = 1.00 * npl

    aset_tetap = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'ASET TETAP DAN INVENTARIS', 'REALISASI']
    fixed_assets = float(aset_tetap.values[0]) if len(aset_tetap) > 0 else 0.0
    
    other_assets_row = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'].str.contains('ASET LAINNYA', case=False, na=False), 'REALISASI']
    other_assets = float(other_assets_row.values[0]) if len(other_assets_row) > 0 else 0.0
    
    surat_berharga_row = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'SURAT BERHARGA YANG DIMILIKI', 'REALISASI']
    total_sb = float(surat_berharga_row.values[0]) if len(surat_berharga_row) > 0 else 0.0
    # 'SBI' on the ASET sheet (renamed from 'SUKUK BI' for the conventional BPD
    # profile — see scripts/generate_dummy_data.py gen_neraca docstring).
    sbi_row = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'SBI', 'REALISASI']
    sbi_balance_sheet = float(sbi_row.values[0]) if len(sbi_row) > 0 else 0.0

    # Encumbered SBI. hqla_calc() correctly excludes pledged SBI from HQLA, but
    # RSF used to be derived as (total securities − the SBI balance-sheet line),
    # an aggregate difference that netted to zero and gave pledged securities a
    # 0% RSF — an asset excluded from HQLA and requiring no stable funding at
    # all. RSF is now read per instrument from the SBI file's SedangDiagunkan
    # flag, so pledged paper carries a real requirement.
    sbi_encumbered = float(df_sbi.loc[~df_sbi.get('SedangDiagunkan').eq('Tidak'), 'nominal'].sum())
    rsf_sbi_encumbered = RSF_SURAT_BERHARGA_DIAGUNKAN * sbi_encumbered

    # Securities that are neither SBI nor otherwise HQLA (corporate bonds etc).
    non_hqla_sb = max(total_sb - sbi_balance_sheet, 0.0)
    rsf_sb = 0.50 * non_hqla_sb

    total_rsf = (rsf_interbank + rsf_perf_A + rsf_perf_B + rsf_perf_C + rsf_npl
                 + fixed_assets + other_assets + rsf_sb + rsf_sbi_encumbered)

    return {
        "kas": total_kas,
        "penempatan_bi": total_deposit_facility + total_giro_bi,
        "sbi": total_sbi,
        "interbank": interbank,
        "perf_A": perf_A,
        "perf_B": perf_B,
        "perf_C": perf_C,
        "npl": npl,
        "fixed": fixed_assets,
        "other": other_assets,
        "non_hqla_sb": non_hqla_sb,
        "sbi_encumbered": sbi_encumbered,


        # Display outputs
        "Cash (KAS)": total_kas,
        "BI Placement (Deposit Facility + Giro BI)": total_deposit_facility + total_giro_bi,
        "Interbank Placement": interbank,
        "Performing Loans < 6m": perf_A,
        "Performing Loans 6m-1yr": perf_B,
        "Performing Loans ≥1yr": perf_C,
        "Non-Performing Loans (NPL)": npl,
        "Fixed Assets": fixed_assets,
        "Other Assets": other_assets,
        
        "RSF — HQLA (0%)": 0.0,
        "RSF — Performing Loans <6m (50%)": rsf_perf_A,
        "RSF — Performing Loans 6m-1yr (50%)": rsf_perf_B,
        "RSF — Performing Loans ≥1yr (65%)": rsf_perf_C,
        "RSF — NPL (100%)": rsf_npl,
        "RSF — Fixed Assets (100%)": fixed_assets,
        "Encumbered Securities (SBI Diagunkan)": sbi_encumbered,
        f"RSF — Encumbered Securities ({RSF_SURAT_BERHARGA_DIAGUNKAN:.0%})": rsf_sbi_encumbered,


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
    # rows the engine doesn't compute (e.g. row 118, the KPR / residential-mortgage
    # row, alone carries ~Rp 374 miliar of example data), and even on
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
        # intact and never actually surfacing the Deposit Facility/Giro BI figure.
        "E55": to_million(hasil_rsf.get("penempatan_bi")),
        "C57": to_million(hasil_rsf.get("sbi")),
        "E86": to_million(hasil_rsf.get("interbank")),
        "E93": to_million(hasil_rsf.get("perf_A")),
        "G93": to_million(hasil_rsf.get("perf_B")),
        "I93": to_million(hasil_rsf.get("perf_C")),
        "E130": to_million(hasil_rsf.get("non_hqla_sb")),
        "I142": to_million(hasil_rsf.get("npl")),
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
