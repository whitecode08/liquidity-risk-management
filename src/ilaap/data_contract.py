"""
Data contract — normalizes the same source sheets already used by
lcr_engine.py / nsfr_engine.py (Tabungan, Giro, Deposito, Pinjaman) into one
transaction ledger for the Survival Period ladder (ilaap/survival_period.py).

Design decision — HQLA assets are NOT included in this ledger:
    Available HQLA (Kas, Penempatan BI, SBI unencumbered) is treated as an
    immediately-monetizable DAY-0 STOCK (see ilaap/available_hqla.py), not as
    a future maturity-bucket inflow. Projecting SBI/PenempatanBI redemption
    into the ladder AND counting it in available_hqla_day0 would double-count
    the same asset. This mirrors standard liquidity-gap methodology and the
    algorithm in determine_survival_period(), which nets the ladder's
    cumulative outflow against a separate day-0 HQLA figure.

Only non-HQLA balance-sheet items enter the ledger:
    - Tabungan, Giro       -> funding, on-demand (no contractual tenor), outflow
    - Deposito             -> funding, has tanggalJatuhTempo, outflow
    - Pinjaman             -> financing, has tanggalJatuhTempo, inflow
    - RKA off-balance items (undrawn commitment, guarantee) -> outflow,
      no tenor, aggregate only (no per-transaction detail available)

`kategori_arus` on each row is a declarative label consumed by
survival_period.get_rate_for_row(), which maps it to the single-source-of-truth
rate tables in lcr_engine.py (get_runoff_rate / get_inflow_rate /
get_additional_outflow_rate). This keeps the ladder's rates identical to the
LCR engine's rates without duplicating the numbers.
"""
from __future__ import annotations

import sys
import pathlib

import numpy as np
import pandas as pd

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from lcr_engine import dpk_organize  # noqa: E402 — reuse existing categorization, no duplication

LEDGER_COLUMNS = [
    "sumber", "arah", "nilai_dasar", "tanggal_jatuh_tempo_kontraktual",
    "mata_uang", "segmen_nasabah", "kategori_arus",
]


def _lps_threshold_flag(active_amount: pd.Series) -> pd.Series:
    """Same IDR 2 miliar LPS/stability threshold used throughout lcr_engine.py."""
    return active_amount <= 2e9


def _funding_rows(df: pd.DataFrame, sumber: str, asof_date: str,
                   has_tenor: bool) -> pd.DataFrame:
    """Tabungan/Giro (has_tenor=False) or Deposito (has_tenor=True) -> ledger rows."""
    df = df.copy()
    active = df["jumlahBulanLaporanActive"]
    stabil = _lps_threshold_flag(active)
    dijamin_lps = _lps_threshold_flag(active)

    if has_tenor:
        tenor_hari = (pd.to_datetime(df["tanggalJatuhTempo"]) - pd.to_datetime(asof_date)).dt.days
        # Same 30-day heuristic outflow_corp() in lcr_engine.py uses to decide
        # whether a corporate account is "operational" (short-tenor placements
        # behave like operating balances) — reused here for consistency.
        operasional = (tenor_hari <= 30) & (tenor_hari > 0)
        jatuh_tempo = pd.to_datetime(df["tanggalJatuhTempo"])
    else:
        operasional = pd.Series(True, index=df.index)  # giro/tabungan corp = always operational
        jatuh_tempo = pd.Series(pd.NaT, index=df.index)

    segmen = df["kategoriNasabah"].str.lower().map({
        "retail": "retail", "umk": "umk", "korporasi": "korporasi",
    })

    kategori_arus = np.select(
        [
            segmen.eq("retail") & stabil,
            segmen.eq("retail") & ~stabil,
            segmen.eq("umk") & stabil,
            segmen.eq("umk") & ~stabil,
            segmen.eq("korporasi") & operasional & dijamin_lps,
            segmen.eq("korporasi") & operasional & ~dijamin_lps,
            segmen.eq("korporasi") & ~operasional & dijamin_lps,
            segmen.eq("korporasi") & ~operasional & ~dijamin_lps,
        ],
        [
            "retail_stabil", "retail_tidak_stabil", "umk_stabil", "umk_tidak_stabil",
            "korporasi_op_lps", "korporasi_op_nonlps",
            "korporasi_nonop_lps", "korporasi_nonop_nonlps",
        ],
        default="tidak_diketahui",
    )

    return pd.DataFrame({
        "sumber": sumber,
        "arah": "keluar",
        "nilai_dasar": active,
        "tanggal_jatuh_tempo_kontraktual": jatuh_tempo,
        "mata_uang": "IDR",
        "segmen_nasabah": segmen,
        "kategori_arus": kategori_arus,
    })


def _financing_rows(df_fin: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    """Pinjaman -> ledger inflow rows.

    Eligibility mirrors lcr_engine.inflow_counterparty(): only kualitas == 1
    is treated as a reliable performing inflow (50% haircut, same rate as
    LCR). kualitas >= 2 (including NSFR's broader "performing" kualitas == 2)
    is conservatively excluded here (0%) — the LCR inflow definition, not the
    NSFR one, is what the source spec asks this module to reuse.
    """
    df = df_fin.copy()
    jatuh_tempo = pd.to_datetime(df["tanggalJatuhTempo"])
    kategori_arus = np.where(df["kualitas"] == 1, "inflow_performing", "inflow_non_performing")
    return pd.DataFrame({
        "sumber": "pinjaman",
        "arah": "masuk",
        "nilai_dasar": df["jumlah"],
        "tanggal_jatuh_tempo_kontraktual": jatuh_tempo,
        "mata_uang": "IDR",
        "segmen_nasabah": None,
        "kategori_arus": kategori_arus,
    })


def _off_balance_rows(df_rka: pd.DataFrame) -> pd.DataFrame:
    """RKA undrawn commitment / guarantee -> ledger outflow rows (no tenor,
    aggregate only — same regex patterns as lcr_engine.outflow_additional())."""
    df = df_rka.copy()
    df["KETERANGAN"] = df["KETERANGAN"].astype(str).str.strip()

    def sum_by_pattern(pat: str) -> float:
        mask = df["KETERANGAN"].str.contains(pat, case=False, na=False, regex=True)
        return float(df.loc[mask, "NILAI"].fillna(0).sum())

    komitmen = sum_by_pattern(r"FASILITAS\s+(PEMBIAYAAN)\s+YANG\s+BELUM\s+DITARIK")
    garansi = sum_by_pattern(r"GARANSI\s+YANG\s+DIBERIKAN")

    rows = []
    if komitmen:
        rows.append({
            "sumber": "off_balance_undrawn", "arah": "keluar", "nilai_dasar": komitmen,
            "tanggal_jatuh_tempo_kontraktual": pd.NaT, "mata_uang": "IDR",
            "segmen_nasabah": None, "kategori_arus": "outflow_undrawn_commitment",
        })
    if garansi:
        rows.append({
            "sumber": "off_balance_guarantee", "arah": "keluar", "nilai_dasar": garansi,
            "tanggal_jatuh_tempo_kontraktual": pd.NaT, "mata_uang": "IDR",
            "segmen_nasabah": None, "kategori_arus": "outflow_guarantee",
        })
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)


def build_transactions_ledger(df_tab: pd.DataFrame, df_giro: pd.DataFrame,
                               df_depo: pd.DataFrame, df_fin: pd.DataFrame,
                               df_rka: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    """Build the unified transaction ledger for the Survival Period ladder.

    df_tab/df_giro/df_depo must already have gone through
    lcr_engine.dpk_organize() (adds jumlahBulanLaporanActive + kategoriNasabah)
    — pass the same dataframes you use for the LCR/NSFR run so the ledger
    matches exactly what the LCR figure was based on.
    """
    parts = [
        _funding_rows(df_tab, "tabungan", asof_date, has_tenor=False),
        _funding_rows(df_giro, "giro", asof_date, has_tenor=False),
        _funding_rows(df_depo, "deposito", asof_date, has_tenor=True),
        _financing_rows(df_fin, asof_date),
        _off_balance_rows(df_rka),
    ]
    ledger = pd.concat(parts, ignore_index=True, sort=False)[LEDGER_COLUMNS]
    ledger["nilai_dasar"] = ledger["nilai_dasar"].astype(float)
    return ledger


def ensure_dpk_organized(df_tab: pd.DataFrame, df_giro: pd.DataFrame, df_depo: pd.DataFrame):
    """Convenience wrapper so callers don't need to import lcr_engine directly."""
    return dpk_organize(df_tab, df_giro, df_depo)
