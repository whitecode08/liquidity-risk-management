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
    - Pinjaman             -> kredit (loans), has tanggalJatuhTempo, inflow
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

from lcr_engine import (  # noqa: E402 — reuse existing categorization, no duplication
    dpk_organize, split_lps, hubungan_mapan,
    rka_liability_amount, RKA_UNDRAWN_PATTERN, RKA_GUARANTEE_PATTERN,
)

LEDGER_COLUMNS = [
    "sumber", "arah", "nilai_dasar", "tanggal_jatuh_tempo_kontraktual",
    "mata_uang", "segmen_nasabah", "kategori_arus",
]


_SEGMEN_OF_KATEGORI = {
    "Retail": "retail",
    "UMK": "umk",
    "Korporasi": "korporasi",
    "Entitas Sektor Publik": "sektor_publik",
    "Bank": "bank",
}


def _funding_rows(df: pd.DataFrame, sumber: str, asof_date: str,
                   has_tenor: bool) -> pd.DataFrame:
    """Tabungan/Giro (has_tenor=False) or Deposito (has_tenor=True) -> ledger rows.

    Each account can yield TWO ledger rows: one for the LPS-guaranteed slice and
    one for the uninsured excess above the limit, mirroring lcr_engine.split_lps().
    Rating the whole balance at a single rate — the previous behaviour — moved a
    Rp5 miliar account entirely into the uninsured bucket, which is neither what
    LPS coverage does nor what the LCR engine now computes.
    """
    df = df.copy()
    active = df["jumlahBulanLaporanActive"]
    dijamin, excess = split_lps(active, df.get("sukuBungaBulanLaporan"))
    mapan = (df["hubunganMapan"] if "hubunganMapan" in df.columns
             else hubungan_mapan(df, asof_date))

    if has_tenor:
        jatuh_tempo = pd.to_datetime(df["tanggalJatuhTempo"], errors="coerce")
        tenor_hari = (jatuh_tempo - pd.to_datetime(asof_date)).dt.days
        # Same 30-day heuristic outflow_corp() in lcr_engine.py uses to decide
        # whether a corporate account is "operational" (short-tenor placements
        # behave like operating balances) — reused here for consistency.
        # Already-matured rows (tenor <= 0) are handled separately below.
        operasional = tenor_hari <= 30
        sudah_jatuh_tempo = tenor_hari <= 0
    else:
        operasional = pd.Series(True, index=df.index)  # giro/tabungan corp = always operational
        jatuh_tempo = pd.Series(pd.NaT, index=df.index)
        sudah_jatuh_tempo = pd.Series(False, index=df.index)

    segmen = df["kategoriNasabah"].map(_SEGMEN_OF_KATEGORI)

    def _kategori(is_guaranteed: bool) -> np.ndarray:
        dijamin_lps = pd.Series(is_guaranteed, index=df.index)
        stabil = dijamin_lps & mapan
        return np.select(
            [
                sudah_jatuh_tempo,
                segmen.eq("bank"),
                segmen.eq("retail") & stabil,
                segmen.eq("retail") & ~stabil,
                segmen.eq("umk") & stabil,
                segmen.eq("umk") & ~stabil,
                segmen.eq("korporasi") & operasional & dijamin_lps,
                segmen.eq("korporasi") & operasional & ~dijamin_lps,
                segmen.eq("korporasi") & ~operasional & dijamin_lps,
                segmen.eq("korporasi") & ~operasional & ~dijamin_lps,
                segmen.eq("sektor_publik") & operasional & dijamin_lps,
                segmen.eq("sektor_publik") & operasional & ~dijamin_lps,
                segmen.eq("sektor_publik") & ~operasional & dijamin_lps,
                segmen.eq("sektor_publik") & ~operasional & ~dijamin_lps,
            ],
            [
                "deposito_jatuh_tempo", "bank",
                "retail_stabil", "retail_tidak_stabil",
                "umk_stabil", "umk_tidak_stabil",
                "korporasi_op_lps", "korporasi_op_nonlps",
                "korporasi_nonop_lps", "korporasi_nonop_nonlps",
                "sektor_publik_op_lps", "sektor_publik_op_nonlps",
                "sektor_publik_nonop_lps", "sektor_publik_nonop_nonlps",
            ],
            default="tidak_diketahui",
        )

    def _slice(nilai: pd.Series, is_guaranteed: bool) -> pd.DataFrame:
        return pd.DataFrame({
            "sumber": sumber,
            "arah": "keluar",
            "nilai_dasar": nilai,
            "tanggal_jatuh_tempo_kontraktual": jatuh_tempo,
            "mata_uang": "IDR",
            "segmen_nasabah": segmen,
            "kategori_arus": _kategori(is_guaranteed),
        })

    rows = pd.concat([_slice(dijamin, True), _slice(excess, False)], ignore_index=True)
    return rows[rows["nilai_dasar"] > 0]


def _kredit_rows(df_fin: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    """Pinjaman -> ledger inflow rows.

    Eligibility mirrors lcr_engine.inflow_counterparty(): only kualitas == 1
    is treated as a reliable performing inflow (50% haircut, same rate as
    LCR). kualitas >= 2 (including NSFR's broader "performing" kualitas == 2)
    is conservatively excluded here (0%) — the LCR inflow definition, not the
    NSFR one, is what the source spec asks this module to reuse.
    """
    df = df_fin.copy()
    jatuh_tempo = pd.to_datetime(df["tanggalJatuhTempo"], errors="coerce")
    # Coerced rather than compared directly — see lcr_engine.inflow_counterparty().
    kualitas = pd.to_numeric(df["kualitas"], errors="coerce")
    kategori_arus = np.where(kualitas == 1, "inflow_performing", "inflow_non_performing")
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
    aggregate only — reuses lcr_engine's own RKA matcher, so the ladder and the
    LCR outflow can never read different rows out of the same sheet)."""
    komitmen = rka_liability_amount(df_rka, RKA_UNDRAWN_PATTERN)
    garansi = rka_liability_amount(df_rka, RKA_GUARANTEE_PATTERN)

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
        _kredit_rows(df_fin, asof_date),
        _off_balance_rows(df_rka),
    ]
    ledger = pd.concat(parts, ignore_index=True, sort=False)[LEDGER_COLUMNS]
    ledger["nilai_dasar"] = ledger["nilai_dasar"].astype(float)
    return ledger


def ensure_dpk_organized(df_tab: pd.DataFrame, df_giro: pd.DataFrame, df_depo: pd.DataFrame):
    """Convenience wrapper so callers don't need to import lcr_engine directly."""
    return dpk_organize(df_tab, df_giro, df_depo)
