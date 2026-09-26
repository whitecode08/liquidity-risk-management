"""
LCR Engine — Liquidity Coverage Ratio Calculation
==================================================
Do NOT modify calculation rates or logic without regulatory review.

Reference (BPD / bank umum konvensional):
    POJK 42/POJK.03/2015 jo. POJK 19/2024 — Kewajiban Pemenuhan Rasio
    Kecukupan Likuiditas (LCR) bagi Bank Umum.

    (This engine previously cited POJK No. 20 Tahun 2025, which applies to
    bank syariah — BUS/UUS — only. OJK's own FAQ describes POJK 20/2025 as a
    harmonisation of the BUK pair above, so the structure is parallel; the
    instruments, nomenclature and some factors differ.)

The Excel export mappings at the bottom of this file still target the OJK
template as originally laid out and were deliberately left untouched by the
BPD revision — see docs/REVISI_LIQUIDITY_RISK_BPD.md Fase 2.
"""

import io
import logging
import math
import numpy as np
import pandas as pd
from openpyxl import load_workbook

log = logging.getLogger(__name__)


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


try:  # Rust-based reader, ~5-6x faster than openpyxl on the source files.
    import python_calamine  # noqa: F401
    _EXCEL_ENGINE = "calamine"
except ImportError:  # optional — `pip install python-calamine` to enable
    _EXCEL_ENGINE = None


def safe_read_excel(file, **kwargs) -> pd.DataFrame:
    if _EXCEL_ENGINE and "engine" not in kwargs:
        try:
            return pd.read_excel(file, engine=_EXCEL_ENGINE, **kwargs)
        except Exception:
            # Any calamine-specific failure falls back to the default reader
            # below rather than failing the upload.
            if hasattr(file, "seek"):
                file.seek(0)
    try:
        return pd.read_excel(file, **kwargs)
    except ValueError:
        if hasattr(file, "seek"):
            file.seek(0)
        return pd.read_excel(file, **kwargs)


# ── Customer categories ──────────────────────────────────────────────────────
# Source files carry `jenisNasabah` verbatim; this maps the reported spelling
# onto the five categories the run-off tables are keyed on. Keep in sync with
# JENIS_NASABAH in scripts/generate_dummy_data.py.
JENIS_NASABAH_MAP = {
    "perorangan": "Retail", "retail": "Retail", "individu": "Retail",
    "umk": "UMK", "umkm": "UMK", "usaha mikro dan kecil": "UMK",
    "korporasi": "Korporasi", "korporat": "Korporasi", "perusahaan": "Korporasi",
    # Entitas Sektor Publik — Pemda (RKUD), BUMD, instansi/BLUD. Deliberately
    # NOT folded into "Korporasi": for a BPD this is the largest and most
    # concentrated funding block, and it runs off on its own (APBD) cycle.
    "pemda": "Entitas Sektor Publik",
    "pemerintah daerah": "Entitas Sektor Publik",
    "bumd": "Entitas Sektor Publik",
    "instansi/blud": "Entitas Sektor Publik",
    "instansi": "Entitas Sektor Publik",
    "blud": "Entitas Sektor Publik",
    # Funding sourced from other banks / financial institutions.
    "bank lain": "Bank", "bank": "Bank", "lembaga keuangan": "Bank",
}

CATEGORIES = ("Retail", "UMK", "Korporasi", "Entitas Sektor Publik", "Bank")

# LPS deposit-insurance coverage limit per customer, per bank.
LPS_COVERAGE_LIMIT = 2_000_000_000.0

# PERLU KONFIRMASI — LPS also withdraws the guarantee entirely (not just above
# LPS_COVERAGE_LIMIT) from any account priced above the "tingkat bunga
# penjaminan" LPS publishes for the period, per UU No. 24/2004 jo. UU P2SK
# Pasal 27 and LPS's own periodic rate announcement. That published rate
# changes every period and differs by currency (rupiah vs valas) and by
# institution type (bank umum vs BPR) — confirm the rate in force on the
# reporting date before relying on this figure; this is NOT the same number as
# a bank's own deposit pricing.
LPS_RATE_CEILING = 4.25  # PERLU KONFIRMASI — tingkat bunga penjaminan LPS, rupiah, bank umum

# ASUMSI (not a POJK figure) — the "established relationship" leg of the
# stable-deposit test. A deposit counts as stable only if it is BOTH within the
# LPS limit AND held in an account with an established relationship: a payroll
# account (flagPayroll — ASN salary routed through the bank) or an account open
# at least this long. Adjust to match the Bank's own behavioural study.
RELATIONSHIP_TENURE_DAYS = 365


def normalize_kategori(value) -> str | None:
    """Map a reported `jenisNasabah` onto a CATEGORIES member, or None if the
    value is missing/unrecognised (caller falls back to the balance heuristic)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    key = str(value).strip().lower()
    if not key or key in ("nan", "none"):
        return None
    return JENIS_NASABAH_MAP.get(key) or (value if value in CATEGORIES else None)


# ── Regulatory rate tables ─────────────────────────────────────────────────
#
# PERLU KONFIRMASI — Entitas Sektor Publik (Pemda / BUMD / instansi / BLUD).
# POJK 42/2015 jo. POJK 19/2024 Pasal 25 treats Entitas Sektor Publik as its
# own counterparty class, separate from non-financial corporates. The four
# rates below are PLACEHOLDERS that simply mirror the corporate ladder — they
# have NOT been verified against the POJK/SEOJK text. Confirm each against
# Pasal 25 and its Lampiran before any figure produced by this engine is used
# for reporting, and change them here (they are used nowhere else).
RUNOFF_PSE_OP_LPS = 0.05       # PERLU KONFIRMASI
RUNOFF_PSE_OP_NONLPS = 0.25    # PERLU KONFIRMASI
RUNOFF_PSE_NONOP_LPS = 0.20    # PERLU KONFIRMASI
RUNOFF_PSE_NONOP_NONLPS = 0.40  # PERLU KONFIRMASI

# Funding from banks / other financial institutions runs off in full within the
# 30-day horizon. This one is the standard Basel LCR treatment carried into the
# POJK, not a placeholder.
RUNOFF_BANK = 1.00

# Single source of truth for LCR run-off / inflow factors. Extracted so the
# ILAAP Survival Period module (src/ilaap/survival_period.py) can reuse the
# same factors without duplicating the numbers — it does NOT reuse
# lcr_calculation() itself (that applies the 75% inflow cap, which does not
# apply to survival period per SEOJK 26/2025 §10.21).

def get_runoff_rate(segmen: str, *, stabilitas: str | None = None,
                     operasional: bool | None = None,
                     dijamin_lps: bool | None = None) -> float:
    """LCR cash-outflow run-off rate for a funding row.

    segmen: 'retail' | 'umk' | 'korporasi' (case-insensitive)
    stabilitas: 'stabil' | 'tidak_stabil' — required for retail/umk
    operasional, dijamin_lps: bool — required for korporasi
    """
    segmen = segmen.strip().lower()
    if segmen in ("retail", "umk"):
        if stabilitas is None:
            raise ValueError("stabilitas is required for retail/umk run-off rate")
        return 0.05 if stabilitas.strip().lower() == "stabil" else 0.10
    if segmen == "korporasi":
        if operasional is None or dijamin_lps is None:
            raise ValueError("operasional and dijamin_lps are required for korporasi run-off rate")
        if operasional and dijamin_lps:
            return 0.05
        if operasional and not dijamin_lps:
            return 0.25
        if not operasional and dijamin_lps:
            return 0.20
        return 0.40
    if segmen in ("sektor_publik", "pse"):
        if operasional is None or dijamin_lps is None:
            raise ValueError("operasional and dijamin_lps are required for sektor_publik run-off rate")
        if operasional:
            return RUNOFF_PSE_OP_LPS if dijamin_lps else RUNOFF_PSE_OP_NONLPS
        return RUNOFF_PSE_NONOP_LPS if dijamin_lps else RUNOFF_PSE_NONOP_NONLPS
    if segmen == "bank":
        return RUNOFF_BANK
    raise ValueError(f"Unknown segmen for run-off rate: {segmen!r}")


def get_additional_outflow_rate(jenis: str) -> float:
    """Off-balance-sheet LCR outflow rate. jenis: 'undrawn_commitment' | 'guarantee'."""
    jenis = jenis.strip().lower()
    if jenis == "undrawn_commitment":
        return 0.10
    if jenis == "guarantee":
        return 0.05
    raise ValueError(f"Unknown jenis for additional outflow rate: {jenis!r}")


def get_inflow_rate(jenis_counterparty: str) -> float:
    """LCR cash-inflow rate. jenis_counterparty:
    'counterparty_performing' (receivables, performing, <=30d) -> 50%
    'interbank_placement' (placement at other banks)            -> 0%
    """
    jenis_counterparty = jenis_counterparty.strip().lower()
    if jenis_counterparty == "counterparty_performing":
        return 0.5
    if jenis_counterparty == "interbank_placement":
        return 0.0
    raise ValueError(f"Unknown jenis_counterparty for inflow rate: {jenis_counterparty!r}")


# ── HQLA ─────────────────────────────────────────────────────────────────────

def hqla_calc(df_nrc_aset: pd.DataFrame, df_nrc_rangkuman: pd.DataFrame,
              df_pbi: pd.DataFrame, df_sbi: pd.DataFrame) -> dict:
    """Calculate High-Quality Liquid Assets (Level 1 only — bank has no Level 2)."""
    total_dpk    = df_nrc_rangkuman.loc[df_nrc_rangkuman['KETERANGAN'] == 'DPK (GIRO+TAB+DEPO)', 'REALISASI'].values[0]
    estimate_gwm = total_dpk * 0.035
    total_kas    = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'KAS', 'REALISASI'].values[0]
    total_sbi  = df_sbi.loc[df_sbi.get("SedangDiagunkan").eq("Tidak"), 'nominal'].sum()
    total_giro_bi = df_pbi.loc[df_pbi.get("jenisPenempatan").eq("F09"), 'jumlah'].sum() - estimate_gwm
    total_deposit_facility  = df_pbi.loc[df_pbi.get("jenisPenempatan").eq("F08"), 'jumlah'].sum()
    penempatan_bi = total_sbi + total_giro_bi + total_deposit_facility
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

def _balance_heuristic_cat(amount: float) -> str:
    """Last-resort guess when `jenisNasabah`/`kategoriNasabah` is absent.

    This is a safety net only — it cannot tell a wealthy individual from a
    company, and for a BPD it silently misfiles every Pemda giro account as a
    corporate. Whenever it fires, dpk_organize() logs a warning naming the
    sheet and the number of rows affected; fix the source file rather than
    tuning these thresholds.
    """
    if amount <= 500_000_000:
        return 'Retail'
    if amount <= 1_000_000_000:
        return 'UMK'
    return 'Korporasi'


def assign_kategori(df: pd.DataFrame, label: str = "DPK") -> pd.Series:
    """Customer category per row, taken from the source data where available."""
    reported = pd.Series(None, index=df.index, dtype=object)
    for col in ('jenisNasabah', 'kategoriNasabah'):
        if col in df.columns:
            filled = df[col].map(normalize_kategori)
            reported = reported.where(reported.notna(), filled)

    missing = reported.isna()
    if missing.any():
        unknown = sorted({str(v) for v in df.loc[missing].get(
            'jenisNasabah', pd.Series(dtype=object)).dropna().unique()})
        log.warning(
            "%s: %d of %d rows have no usable jenisNasabah/kategoriNasabah — "
            "falling back to the balance-size heuristic, which cannot identify "
            "Pemda/BUMD funding.%s",
            label, int(missing.sum()), len(df),
            f" Unrecognised values: {unknown}." if unknown else "",
        )
        reported = reported.where(
            ~missing, df['jumlahBulanLaporanActive'].map(_balance_heuristic_cat))
    return reported


def split_lps(active: pd.Series, suku_bunga: pd.Series | None = None) -> tuple[pd.Series, pd.Series]:
    """Split each balance into (LPS-guaranteed portion, uninsured excess).

    Coverage is per account up to LPS_COVERAGE_LIMIT — an account holding more
    than that is partly insured, not wholly uninsured, so the two portions are
    rated separately rather than the whole balance taking one rate.

    `suku_bunga`, when given, applies the OTHER LPS disqualifier: an account
    priced above LPS_RATE_CEILING loses the guarantee on its ENTIRE balance,
    not just the excess over the coverage limit — a Rp500 juta account paying
    an above-ceiling rate is fully uninsured, unlike a Rp500 juta account
    under the coverage limit at a normal rate. Missing rates (NaN, or the
    caller passing None because the sheet has no rate column) are treated as
    compliant so a data gap doesn't silently zero out the guarantee.
    """
    active = active.clip(lower=0)
    dijamin = active.clip(upper=LPS_COVERAGE_LIMIT)
    if suku_bunga is not None:
        disqualified = suku_bunga.reindex(active.index) > LPS_RATE_CEILING
        dijamin = dijamin.where(~disqualified.fillna(False), 0.0)
    return dijamin, active - dijamin


# Columns that date the CUSTOMER RELATIONSHIP, most authoritative first.
# `tanggalMulai` is only a fallback: on a Deposito sheet it dates the placement
# of that particular deposit, not the relationship, so a long-standing customer
# rolling a 1-month deposit would otherwise look like a brand-new depositor and
# the whole term-deposit book would be classed less stable.
RELATIONSHIP_DATE_COLUMNS = ('tanggalMulaiHubungan', 'tanggalMulaiNasabah', 'tanggalMulai')


def hubungan_mapan(df: pd.DataFrame, asof_date: str | None) -> pd.Series:
    """Established-relationship leg of the stable-deposit test — SEPARATE from
    LPS coverage. Payroll (ASN salary) accounts qualify outright; so does a
    relationship at least RELATIONSHIP_TENURE_DAYS old."""
    mapan = pd.Series(False, index=df.index)
    if 'flagPayroll' in df.columns:
        mapan = mapan | df['flagPayroll'].fillna(False).astype(bool)
    if asof_date is not None:
        col = next((c for c in RELATIONSHIP_DATE_COLUMNS if c in df.columns), None)
        if col is not None:
            umur = (pd.to_datetime(asof_date) - pd.to_datetime(df[col], errors='coerce')).dt.days
            mapan = mapan | (umur >= RELATIONSHIP_TENURE_DAYS).fillna(False)
    return mapan


def dpk_organize(df_tab: pd.DataFrame, df_giro: pd.DataFrame, df_depo: pd.DataFrame,
                  asof_date: str | None = None):
    """Net blocked amounts, assign customer category, flag stable relationships.

    `asof_date` is optional only for backwards compatibility; without it the
    account-tenure half of the relationship test cannot run and stability rests
    on flagPayroll alone.
    """
    for label, df in (("Tabungan", df_tab), ("Giro", df_giro), ("Deposito", df_depo)):
        df['jumlahBulanLaporanActive'] = df['jumlahBulanLaporan'] - df['nominalDiblokir']
        df['kategoriNasabah'] = assign_kategori(df, label)
        df['hubunganMapan'] = hubungan_mapan(df, asof_date)
    return df_tab, df_giro, df_depo


# ── Cash Outflows ─────────────────────────────────────────────────────────────

# A deposit whose tanggalJatuhTempo has already passed is contractually payable
# now, so it is treated as maturing on day 0 and runs off in full. Both engines
# apply the same treatment (NSFR gives it 0% ASF) — previously LCR dropped these
# rows entirely while NSFR counted them as stable funding.
RUNOFF_DEPOSITO_JATUH_TEMPO = 1.00


def _tenor_hari(df: pd.DataFrame, asof_date: str) -> pd.Series:
    return (pd.to_datetime(df['tanggalJatuhTempo'], errors='coerce')
            - pd.to_datetime(asof_date)).dt.days


def _depo_within_30d(df_depo: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    """Deposits landing inside the 30-day stress horizon, overdue ones included
    (tenorHari <= 0 means already payable — see RUNOFF_DEPOSITO_JATUH_TEMPO)."""
    df = df_depo.copy()
    df['tenorHari'] = _tenor_hari(df, asof_date)
    return df[df['tenorHari'].notna() & (df['tenorHari'] <= 30)]


def _stabilitas_amounts(frames) -> tuple[float, float, float]:
    """Sum (stable, unstable) across frames.

    Stable = the LPS-guaranteed slice of an account with an established
    relationship. The uninsured excess above the LPS limit is always unstable,
    even on the very same account — so a Rp5 miliar payroll account contributes
    Rp2 miliar stable and Rp3 miliar unstable, not Rp5 miliar of either.
    Already-matured deposits bypass this split and run off in full.
    """
    stable = unstable = matured = 0.0
    for df in frames:
        if df.empty:
            continue
        active = df['jumlahBulanLaporanActive']
        if 'tenorHari' in df.columns:
            jatuh_tempo = df['tenorHari'] <= 0
            matured += float(active[jatuh_tempo].sum())
            keep = ~jatuh_tempo
            df, active = df[keep], active[keep]
            if df.empty:
                continue
        dijamin, excess = split_lps(active, df.get('sukuBungaBulanLaporan'))
        mapan = df['hubunganMapan'] if 'hubunganMapan' in df.columns else pd.Series(False, index=df.index)
        stable += float(dijamin[mapan].sum())
        unstable += float(dijamin[~mapan].sum()) + float(excess.sum())
    return stable, unstable, matured


def _outflow_stabilitas(df_tab, df_giro, df_depo, asof_date: str, *,
                         kategori: str, segmen: str) -> tuple[float, float, float, float]:
    frames = [
        df_tab[df_tab['kategoriNasabah'] == kategori],
        df_giro[df_giro['kategoriNasabah'] == kategori],
        _depo_within_30d(df_depo[df_depo['kategoriNasabah'] == kategori], asof_date),
    ]
    stable, unstable, matured = _stabilitas_amounts(frames)
    out = (get_runoff_rate(segmen, stabilitas="stabil") * stable
           + get_runoff_rate(segmen, stabilitas="tidak_stabil") * unstable
           + RUNOFF_DEPOSITO_JATUH_TEMPO * matured)
    return stable, unstable, matured, out


def outflow_retail(df_tab, df_giro, df_depo, asof_date: str) -> dict:
    """Retail (Perorangan) outflow: stable 5%, unstable 10%."""
    stable, unstable, matured, out = _outflow_stabilitas(
        df_tab, df_giro, df_depo, asof_date, kategori='Retail', segmen='retail')
    return {
        "Retail Stable Funding":              stable,
        "Retail Unstable Funding":            unstable,
        "Retail Matured Deposits":            matured,
        "Outflow — Retail Stable (5%)":       get_runoff_rate("retail", stabilitas="stabil") * stable,
        "Outflow — Retail Unstable (10%)":    get_runoff_rate("retail", stabilitas="tidak_stabil") * unstable,
        "Outflow — Retail Matured (100%)":    RUNOFF_DEPOSITO_JATUH_TEMPO * matured,
        "Total Outflow Pendanaan Perorangan": out,
    }


def outflow_umk(df_tab, df_giro, df_depo, asof_date: str) -> dict:
    """SME (UMK) outflow: stable 5%, unstable 10%."""
    stable, unstable, matured, out = _outflow_stabilitas(
        df_tab, df_giro, df_depo, asof_date, kategori='UMK', segmen='umk')
    return {
        "SME Stable Funding":            stable,
        "SME Unstable Funding":          unstable,
        "SME Matured Deposits":          matured,
        "Outflow — SME Stable (5%)":     get_runoff_rate("umk", stabilitas="stabil") * stable,
        "Outflow — SME Unstable (10%)":  get_runoff_rate("umk", stabilitas="tidak_stabil") * unstable,
        "Outflow — SME Matured (100%)":  RUNOFF_DEPOSITO_JATUH_TEMPO * matured,
        "Total Outflow Pendanaan UMK":   out,
    }


def _outflow_op_lps(df_tab, df_giro, df_depo, asof_date: str, *, kategori: str):
    """Shared op/non-op × insured/uninsured grid used by corporates and by
    Entitas Sektor Publik. Returns (op_lps, op_nlps, nop_lps, nop_nlps, matured)."""
    df_tab_c = df_tab[df_tab['kategoriNasabah'] == kategori].copy()
    df_giro_c = df_giro[df_giro['kategoriNasabah'] == kategori].copy()
    df_depo_c = df_depo[df_depo['kategoriNasabah'] == kategori].copy()

    df_tab_c['kategoriRekening'] = "Operasional"
    df_giro_c['kategoriRekening'] = "Operasional"
    df_depo_c['tenorHari'] = _tenor_hari(df_depo_c, asof_date)
    matured_mask = df_depo_c['tenorHari'] <= 0
    matured = float(df_depo_c.loc[matured_mask, 'jumlahBulanLaporanActive'].sum())
    df_depo_c = df_depo_c[~matured_mask]
    df_depo_c['kategoriRekening'] = np.where(
        df_depo_c['tenorHari'] <= 30, 'Operasional', 'Non Operasional')

    totals = {("Operasional", True): 0.0, ("Operasional", False): 0.0,
              ("Non Operasional", True): 0.0, ("Non Operasional", False): 0.0}
    for df in (df_tab_c, df_giro_c, df_depo_c):
        if df.empty:
            continue
        dijamin, excess = split_lps(df['jumlahBulanLaporanActive'], df.get('sukuBungaBulanLaporan'))
        for rek in ("Operasional", "Non Operasional"):
            mask = df['kategoriRekening'] == rek
            totals[(rek, True)] += float(dijamin[mask].sum())
            totals[(rek, False)] += float(excess[mask].sum())
    return (totals[("Operasional", True)], totals[("Operasional", False)],
            totals[("Non Operasional", True)], totals[("Non Operasional", False)],
            matured)


def outflow_corp(df_tab, df_giro, df_depo, asof_date: str) -> dict:
    """Corporate outflow: op-LPS 5%, op-nonLPS 25%, nonOp-LPS 20%, nonOp-nonLPS 40%."""
    op_lps, op_nlps, nop_lps, nop_nlps, matured = _outflow_op_lps(
        df_tab, df_giro, df_depo, asof_date, kategori='Korporasi')

    out_op_lps   = get_runoff_rate("korporasi", operasional=True,  dijamin_lps=True)  * op_lps
    out_op_nlps  = get_runoff_rate("korporasi", operasional=True,  dijamin_lps=False) * op_nlps
    out_nop_lps  = get_runoff_rate("korporasi", operasional=False, dijamin_lps=True)  * nop_lps
    out_nop_nlps = get_runoff_rate("korporasi", operasional=False, dijamin_lps=False) * nop_nlps
    out_matured  = RUNOFF_DEPOSITO_JATUH_TEMPO * matured
    return {
        "Corp Operational — LPS Covered":            op_lps,
        "Corp Operational — LPS Covered (5%)":       out_op_lps,
        "Corp Operational — Not LPS Covered":        op_nlps,
        "Corp Operational — Not LPS Covered (25%)":  out_op_nlps,
        "Corp Non-Op — LPS Covered":                 nop_lps,
        "Corp Non-Op — LPS Covered (20%)":           out_nop_lps,
        "Corp Non-Op — Not LPS Covered":             nop_nlps,
        "Corp Non-Op — Not LPS Covered (40%)":       out_nop_nlps,
        "Corp Matured Deposits":                     matured,
        "Corp Matured Deposits (100%)":              out_matured,
        "Total Corporate Funding":                   op_lps + op_nlps + nop_lps + nop_nlps + matured,
        "Total Outflow Pendanaan Korporasi":         out_op_lps + out_op_nlps + out_nop_lps + out_nop_nlps + out_matured,
    }


def outflow_sektor_publik(df_tab, df_giro, df_depo, asof_date: str) -> dict:
    """Entitas Sektor Publik (Pemda/RKUD, BUMD, instansi/BLUD).

    Rated on its own ladder rather than folded into Korporasi — for a BPD this
    is the concentration that drives the LCR. The four rates are PLACEHOLDERS
    pending confirmation against POJK 42/2015 jo. 19/2024 Pasal 25; see the
    RUNOFF_PSE_* constants at the top of this file.
    """
    op_lps, op_nlps, nop_lps, nop_nlps, matured = _outflow_op_lps(
        df_tab, df_giro, df_depo, asof_date, kategori='Entitas Sektor Publik')

    out_op_lps   = get_runoff_rate("sektor_publik", operasional=True,  dijamin_lps=True)  * op_lps
    out_op_nlps  = get_runoff_rate("sektor_publik", operasional=True,  dijamin_lps=False) * op_nlps
    out_nop_lps  = get_runoff_rate("sektor_publik", operasional=False, dijamin_lps=True)  * nop_lps
    out_nop_nlps = get_runoff_rate("sektor_publik", operasional=False, dijamin_lps=False) * nop_nlps
    out_matured  = RUNOFF_DEPOSITO_JATUH_TEMPO * matured
    return {
        "PSE Operational — LPS Covered":       op_lps,
        "PSE Operational — Not LPS Covered":   op_nlps,
        "PSE Non-Op — LPS Covered":            nop_lps,
        "PSE Non-Op — Not LPS Covered":        nop_nlps,
        "PSE Matured Deposits":                matured,
        "Total Public Sector Funding":         op_lps + op_nlps + nop_lps + nop_nlps + matured,
        "Total Outflow Pendanaan Sektor Publik":
            out_op_lps + out_op_nlps + out_nop_lps + out_nop_nlps + out_matured,
    }


def outflow_bank(df_tab, df_giro, df_depo, asof_date: str) -> dict:
    """Funding placed with this bank by other banks / financial institutions —
    100% run-off within the 30-day horizon."""
    total = 0.0
    for df in (df_tab, df_giro, _depo_within_30d(df_depo, asof_date)):
        sel = df[df['kategoriNasabah'] == 'Bank']
        total += float(sel['jumlahBulanLaporanActive'].sum())
    return {
        "Bank/FI Funding":                          total,
        "Total Outflow Pendanaan Lembaga Keuangan": get_runoff_rate("bank") * total,
    }


# RKA row labels. The sheet carries a TAGIHAN (receivable) block and a
# KEWAJIBAN (obligation) block, and both sides use the same row names — only the
# KEWAJIBAN side is a cash outflow, so the match is scoped to that section
# rather than run over the whole sheet.
RKA_UNDRAWN_PATTERN = r"FASILITAS\s+(?:KREDIT|PEMBIAYAAN)\s+YANG\s+BELUM\s+DITARIK"
RKA_GUARANTEE_PATTERN = r"GARANSI\s+YANG\s+DIBERIKAN"
RKA_LIABILITY_SECTIONS = r"^KEWAJIBAN\b"


def rka_liability_amount(df_rka: pd.DataFrame, pattern: str) -> float:
    """Sum RKA rows matching `pattern`, counting only rows inside a KEWAJIBAN
    section. Section headers are the rows whose NILAI is blank."""
    df = df_rka.copy()
    if 'KETERANGAN' not in df.columns:
        return 0.0
    df['KETERANGAN'] = df['KETERANGAN'].astype(str).str.strip()
    nilai = pd.to_numeric(df['NILAI'], errors='coerce')

    is_header = nilai.isna()
    section = df['KETERANGAN'].where(is_header).ffill()
    in_liability = section.str.contains(RKA_LIABILITY_SECTIONS, case=False, na=False, regex=True)

    mask = (~is_header) & in_liability & df['KETERANGAN'].str.contains(
        pattern, case=False, na=False, regex=True)
    return float(nilai[mask].fillna(0).sum())


def outflow_additional(df_rka: pd.DataFrame) -> dict:
    """Additional outflows: undrawn credit commitments 10%, guarantees 5%."""
    total_komitmen   = rka_liability_amount(df_rka, RKA_UNDRAWN_PATTERN)
    total_kontijensi = rka_liability_amount(df_rka, RKA_GUARANTEE_PATTERN)
    out_komitmen     = get_additional_outflow_rate("undrawn_commitment") * total_komitmen
    out_kontijensi   = get_additional_outflow_rate("guarantee") * total_kontijensi
    return {
        "Undrawn Credit Commitment":             total_komitmen,
        "Undrawn Credit Commitment (10%)":       out_komitmen,
        "Guarantee Contingency":                 total_kontijensi,
        "Guarantee Contingency (5%)":            out_kontijensi,
        "Total Outflow Tambahan":                out_komitmen + out_kontijensi,
    }


# ── Cash Inflows ──────────────────────────────────────────────────────────────

def inflow_counterparty(df_fin: pd.DataFrame, df_nrc_aset: pd.DataFrame, asof_date: str) -> dict:
    """Performing counterparty receivables ≤30d: 50%. Other bank placement: 0%."""
    df = df_fin.copy()
    df['tenorHari'] = (pd.to_datetime(df['tanggalJatuhTempo'], errors='coerce')
                       - pd.to_datetime(asof_date)).dt.days
    df = df[(df['tenorHari'] > 0) & (df['tenorHari'] <= 30)]
    # Coerced rather than compared directly: some core-banking exports carry
    # `kualitas` as text ("1", "01") rather than an int. An uncoerced `== 1`
    # would then compare int to str, match nothing, and silently zero out this
    # entire inflow line with no error to flag it.
    kualitas = pd.to_numeric(df['kualitas'], errors='coerce')
    df = df[kualitas == 1]
    total_tagihan   = df['jumlah'].sum()
    rate_tagihan    = get_inflow_rate("counterparty_performing") * total_tagihan
    total_placement = df_nrc_aset.loc[df_nrc_aset['KETERANGAN'] == 'PENEMPATAN PADA BANK LAIN', 'REALISASI'].values[0]
    rate_placement  = get_inflow_rate("interbank_placement") * total_placement
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
    Minimum required: 100% per POJK 42/2015 jo. POJK 19/2024.

    Every "Total Outflow Pendanaan ..." line in `hasil_outflow` is summed, plus
    "Total Outflow Tambahan". Adding a funding segment therefore only means
    emitting its own total — there is no second list of keys to keep in step,
    which is what previously let a new segment be silently left out.
    """
    total_hqla    = hasil_hqla['Total HQLA']
    total_outflow = sum(
        parse_number_from_str(v) for k, v in hasil_outflow.items()
        if k.startswith('Total Outflow Pendanaan') or k == 'Total Outflow Tambahan'
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
        # Cell addresses are unchanged (Fase 2 — template untouched); only the
        # result-dict key was renamed alongside the RKA relabelling.
        "D113": to_million(hasil_outflow.get('Undrawn Credit Commitment')),
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
