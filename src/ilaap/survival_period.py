"""
Survival Period Monitoring — Modul 2 (SEOJK No. 26/SEOJK.03/2025).
====================================================================

Critical difference from lcr_engine.py — the 75% inflow cap is NOT used here.
Source document §10.21, quoted verbatim: "pembatasan arus kas masuk
sebagaimana perhitungan LCR yang diatur dalam POJK mengenai LCR tidak
digunakan" for survival period. So this module does NOT call
lcr_calculation() — it only reuses the run-off/inflow RATE TABLES from
lcr_engine.py (get_runoff_rate / get_inflow_rate / get_additional_outflow_rate)
so the same regulatory factors are never duplicated as separate numbers.

`compute_add_on_percent()` is intentionally left unimplemented — see its
docstring. Do not guess the conversion formula.
"""
from __future__ import annotations

import sys
import pathlib
from typing import Optional

import numpy as np
import pandas as pd
import yaml

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from lcr_engine import (  # noqa: E402
    get_runoff_rate, get_inflow_rate, get_additional_outflow_rate,
    RUNOFF_DEPOSITO_JATUH_TEMPO,
)

_CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "config"


# ── Config loading ──────────────────────────────────────────────────────────

def load_time_buckets(path: pathlib.Path | None = None) -> list[dict]:
    path = path or (_CONFIG_DIR / "time_buckets.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["buckets"]


def load_stress_scenarios(path: pathlib.Path | None = None) -> dict[str, dict]:
    path = path or (_CONFIG_DIR / "stress_scenarios.yaml")
    with open(path, "r", encoding="utf-8") as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    return {s["id"]: s for s in scenarios}


# ── Bucket assignment ───────────────────────────────────────────────────────

def assign_bucket(hari: float, buckets: list[dict]) -> str:
    """Map a day-count to its bucket id. `hari` < 0 (overdue / bad data) maps
    to the dedicated 'overdue' bucket rather than raising, so a single bad
    maturity date doesn't crash the whole ladder — it still shows up (and
    gets flagged) in the output instead of silently vanishing."""
    if pd.isna(hari):
        raise ValueError("assign_bucket() received NaN — on-demand rows must go "
                          "through distribute_no_tenor() first, not assign_bucket()")
    if hari < 0:
        return "overdue"
    for b in buckets:
        if b["id"] == "overdue":
            continue
        lo, hi = b["hari_mulai"], b["hari_selesai"]
        if hi is None:
            if hari >= lo:
                return b["id"]
        elif lo <= hari < hi:
            return b["id"]
    raise ValueError(f"Hari {hari} tidak masuk bucket manapun — cek data jatuh tempo")


def assign_buckets(hari: pd.Series, buckets: list[dict]) -> pd.Series:
    """Vectorised assign_bucket() over a whole Series — same rules, same errors.

    The ladder used to call assign_bucket() once per row via .apply(), which
    was a measurable share of the Stress Testing page's latency.
    """
    if hari.isna().any():
        raise ValueError("assign_buckets() received NaN — on-demand rows must go "
                          "through distribute_no_tenor() first, not assign_buckets()")
    result = pd.Series(pd.NA, index=hari.index, dtype=object)
    result[hari < 0] = "overdue"
    for b in buckets:
        if b["id"] == "overdue":
            continue
        lo, hi = b["hari_mulai"], b["hari_selesai"]
        mask = (hari >= lo) if hi is None else ((hari >= lo) & (hari < hi))
        result[mask & result.isna()] = b["id"]
    if result.isna().any():
        bad = hari[result.isna()].iloc[0]
        raise ValueError(f"Hari {bad} tidak masuk bucket manapun — cek data jatuh tempo")
    return result


def bucket_order(buckets: list[dict]) -> list[str]:
    """Ordered bucket ids, 'overdue' first (already-due), then ascending tenor."""
    regular = [b["id"] for b in buckets if b["id"] != "overdue"]
    return ["overdue"] + regular if any(b["id"] == "overdue" for b in buckets) else regular


def bucket_to_days(bucket_id: str, buckets: list[dict]) -> Optional[float]:
    """Upper bound (in days) of a bucket — 'having survived this bucket' means
    surviving up to this many days. None for the unbounded last bucket."""
    for b in buckets:
        if b["id"] == bucket_id:
            return b["hari_selesai"]
    raise ValueError(f"Unknown bucket_id: {bucket_id}")


def days_to_bucket(days: float, buckets: list[dict]) -> str:
    return assign_bucket(days, buckets)


# ── Rate lookup (declarative — mirrors lcr_engine.py factors) ───────────────

_RATE_MAP = {
    "retail_stabil":          lambda: get_runoff_rate("retail", stabilitas="stabil"),
    "retail_tidak_stabil":    lambda: get_runoff_rate("retail", stabilitas="tidak_stabil"),
    "umk_stabil":             lambda: get_runoff_rate("umk", stabilitas="stabil"),
    "umk_tidak_stabil":       lambda: get_runoff_rate("umk", stabilitas="tidak_stabil"),
    "korporasi_op_lps":       lambda: get_runoff_rate("korporasi", operasional=True, dijamin_lps=True),
    "korporasi_op_nonlps":    lambda: get_runoff_rate("korporasi", operasional=True, dijamin_lps=False),
    "korporasi_nonop_lps":    lambda: get_runoff_rate("korporasi", operasional=False, dijamin_lps=True),
    "korporasi_nonop_nonlps": lambda: get_runoff_rate("korporasi", operasional=False, dijamin_lps=False),
    "sektor_publik_op_lps":       lambda: get_runoff_rate("sektor_publik", operasional=True, dijamin_lps=True),
    "sektor_publik_op_nonlps":    lambda: get_runoff_rate("sektor_publik", operasional=True, dijamin_lps=False),
    "sektor_publik_nonop_lps":    lambda: get_runoff_rate("sektor_publik", operasional=False, dijamin_lps=True),
    "sektor_publik_nonop_nonlps": lambda: get_runoff_rate("sektor_publik", operasional=False, dijamin_lps=False),
    "bank":                       lambda: get_runoff_rate("bank"),
    "deposito_jatuh_tempo":       lambda: RUNOFF_DEPOSITO_JATUH_TEMPO,
    "outflow_undrawn_commitment": lambda: get_additional_outflow_rate("undrawn_commitment"),
    "outflow_guarantee":          lambda: get_additional_outflow_rate("guarantee"),
    "inflow_performing":     lambda: get_inflow_rate("counterparty_performing"),
    "inflow_non_performing": lambda: 0.0,  # conservative: NPL is not a reliable cash inflow
}

# Segment used to test whether a benchmark scenario's segmen_terdampak filter
# applies to a given funding row's kategori_arus.
_SEGMENT_OF_KATEGORI = {
    "retail_stabil": "retail", "retail_tidak_stabil": "retail",
    "umk_stabil": "umk", "umk_tidak_stabil": "umk",
    "korporasi_op_lps": "korporasi", "korporasi_op_nonlps": "korporasi",
    "korporasi_nonop_lps": "korporasi", "korporasi_nonop_nonlps": "korporasi",
    "sektor_publik_op_lps": "sektor_publik", "sektor_publik_op_nonlps": "sektor_publik",
    "sektor_publik_nonop_lps": "sektor_publik", "sektor_publik_nonop_nonlps": "sektor_publik",
    "bank": "bank",
}


def get_rate_for_row(kategori_arus: str) -> float:
    try:
        return _RATE_MAP[kategori_arus]()
    except KeyError:
        raise ValueError(f"Unknown kategori_arus: {kategori_arus!r}")


def rates_for(kategori_arus: pd.Series) -> pd.Series:
    """get_rate_for_row() over a Series, looked up once per distinct category
    rather than once per row. Unknown categories still raise ValueError."""
    lookup = {k: get_rate_for_row(k) for k in kategori_arus.unique()}
    return kategori_arus.map(lookup).astype(float)


# ── No-tenor (on-demand) distribution ───────────────────────────────────────

def _day_weighted_shares(buckets: list[dict], day_start: int, day_end_exclusive: int) -> dict:
    """Split a [day_start, day_end_exclusive) window proportionally across the
    buckets it overlaps, weighted by the number of days each bucket
    contributes. Used for the 'spread evenly' no-tenor treatments."""
    span = day_end_exclusive - day_start
    shares = {}
    for b in buckets:
        if b["id"] == "overdue":
            continue
        lo, hi = b["hari_mulai"], (b["hari_selesai"] if b["hari_selesai"] is not None else day_end_exclusive)
        overlap = max(0, min(hi, day_end_exclusive) - max(lo, day_start))
        if overlap > 0:
            shares[b["id"]] = overlap / span
    return shares


def distribute_no_tenor(without_tenor: pd.DataFrame, scenario: dict,
                         buckets: list[dict]) -> pd.DataFrame:
    """Expand each no-tenor row into one row per bucket it materializes in,
    per the scenario's distribution rule. Off-balance-sheet rows
    (undrawn commitment / guarantee) use a fixed per-instrument treatment
    regardless of scenario, per §5.4's "tentukan per jenis instrumen" note:
      - undrawn commitment -> spread evenly over the first 30 days
      - guarantee claims    -> materializes entirely at H+0 (overnight)
    Giro/Tabungan on-demand funding follows the scenario's own rule.
    """
    if without_tenor.empty:
        return without_tenor.assign(bucket_id=pd.Series(dtype=object), nilai_bucket=pd.Series(dtype=float))

    mode = scenario["no_tenor_distribution"]
    if mode not in ("hari_pertama", "satu_kali_h1_sampai_h30"):
        raise ValueError(f"Unknown no_tenor_distribution mode: {mode!r}")
    segmen_terdampak = scenario.get("segmen_terdampak")

    # Every row falls into one of only a handful of distribution rules, so the
    # rows are grouped by rule and each group is expanded across its buckets in
    # one vectorised step. (The previous per-row iterrows()/row.copy() loop
    # produced the same rows but dominated the Stress Testing page's latency.)
    sumber = without_tenor["sumber"]
    is_guarantee = sumber.eq("off_balance_guarantee")
    is_undrawn = sumber.eq("off_balance_undrawn")
    funding = ~is_guarantee & ~is_undrawn

    groups = [
        (is_guarantee, {"overnight": 1.0}),
        (is_undrawn, _day_weighted_shares(buckets, 0, 30)),
    ]
    if mode == "hari_pertama":
        groups.append((funding, {"overnight": 1.0}))
    else:
        in_scope = funding
        if segmen_terdampak is not None:
            # This benchmark scenario isolates specific segments — funding
            # from segments not under test is assumed to stay in place
            # (not stressed) for this run, so it contributes no outflow.
            row_segmen = without_tenor["kategori_arus"].map(_SEGMENT_OF_KATEGORI)
            in_scope = funding & row_segmen.isin(segmen_terdampak)
        groups.append((in_scope, _day_weighted_shares(buckets, 1, 30)))

    parts = []
    for mask, shares in groups:
        subset = without_tenor[mask]
        if subset.empty:
            continue
        for bucket_id, frac in shares.items():
            parts.append(subset.assign(bucket_id=bucket_id,
                                       nilai_bucket=subset["nilai_dasar"] * frac))
    if not parts:
        return without_tenor.iloc[0:0].assign(bucket_id=pd.Series(dtype=object),
                                               nilai_bucket=pd.Series(dtype=float))
    return pd.concat(parts, ignore_index=True)


# ── Cash-flow ladder ─────────────────────────────────────────────────────────

def project_cashflow_ladder(transactions_df: pd.DataFrame, buckets: list[dict],
                             scenario: dict, asof_date: str) -> pd.DataFrame:
    """
    transactions_df: output of ilaap.data_contract.build_transactions_ledger()
    scenario: one entry from load_stress_scenarios()

    Returns a DataFrame indexed by bucket_id (in ladder order) with columns
    [arus_keluar, arus_masuk, arus_keluar_kumulatif, arus_masuk_kumulatif,
     net_outflow_kumulatif].
    """
    df = transactions_df.copy()
    asof = pd.Timestamp(asof_date)

    with_tenor = df[df["tanggal_jatuh_tempo_kontraktual"].notna()].copy()
    without_tenor = df[df["tanggal_jatuh_tempo_kontraktual"].isna()].copy()

    with_tenor["hari_ke_jatuh_tempo"] = (with_tenor["tanggal_jatuh_tempo_kontraktual"] - asof).dt.days
    with_tenor["bucket_id"] = assign_buckets(with_tenor["hari_ke_jatuh_tempo"], buckets)
    with_tenor["nilai_bucket"] = with_tenor["nilai_dasar"]

    without_tenor_expanded = distribute_no_tenor(without_tenor, scenario, buckets)

    combined = pd.concat([with_tenor, without_tenor_expanded], ignore_index=True, sort=False)
    combined["rate"] = rates_for(combined["kategori_arus"])
    combined["nilai_terbobot"] = combined["nilai_bucket"] * combined["rate"]

    order = bucket_order(buckets)
    per_bucket = (combined.groupby(["bucket_id", "arah"])["nilai_terbobot"]
                  .sum().unstack(fill_value=0.0))
    for col in ("keluar", "masuk"):
        if col not in per_bucket.columns:
            per_bucket[col] = 0.0
    per_bucket = per_bucket.reindex(order, fill_value=0.0)
    per_bucket = per_bucket.rename(columns={"keluar": "arus_keluar", "masuk": "arus_masuk"})

    per_bucket["arus_keluar_kumulatif"] = per_bucket["arus_keluar"].cumsum()
    per_bucket["arus_masuk_kumulatif"] = per_bucket["arus_masuk"].cumsum()
    per_bucket["net_outflow_kumulatif"] = (
        per_bucket["arus_keluar_kumulatif"] - per_bucket["arus_masuk_kumulatif"]
    )
    return per_bucket[["arus_keluar", "arus_masuk", "arus_keluar_kumulatif",
                        "arus_masuk_kumulatif", "net_outflow_kumulatif"]]


# ── Survival period determination + Pillar 2 add-on ─────────────────────────

def compute_add_on_percent(shortfall: float, current_hqla_day0: float) -> float:
    """NOT IMPLEMENTED — DO NOT GUESS THIS FORMULA.

    The source document (SEOJK 26/2025 §10.19-10.27) describes the *concept*
    of a Pillar 2 add-on when survival period falls short of the Bank's
    target, but gives no explicit, uniform formula for converting a HQLA
    shortfall into an additional LCR percentage requirement. This must be
    confirmed with the Bank's Risk Management & Compliance division — it is
    likely to require a separate internal policy paper. See
    docs/SPEK_MODUL_ILAAP.md §5.5 and §12 item 3.
    """
    raise NotImplementedError(
        "compute_add_on_percent() requires a Bank-approved shortfall-to-LCR-%"
        " conversion methodology that does not yet exist. See docstring."
    )


def determine_survival_period(ladder_df: pd.DataFrame, available_hqla_day0: float,
                               target_survival_days: int, buckets: list[dict]) -> dict:
    """
    ladder_df: output of project_cashflow_ladder()
    available_hqla_day0: from ilaap.available_hqla.available_hqla_calc()
    target_survival_days: Bank's risk-appetite target (see docs §12 item 4)
    """
    ladder = ladder_df.copy()
    ladder["available_hqla_kumulatif"] = available_hqla_day0 - ladder["net_outflow_kumulatif"]

    depleted = ladder[ladder["available_hqla_kumulatif"] <= 0]
    survival_bucket = depleted.index[0] if not depleted.empty else None
    survival_hari = bucket_to_days(survival_bucket, buckets) if survival_bucket else None

    memenuhi_target = survival_bucket is None or (
        survival_hari is None or survival_hari >= target_survival_days
    )

    result = {
        "ladder": ladder,
        "survival_bucket": survival_bucket,
        "survival_hari": survival_hari,
        "target_survival_days": target_survival_days,
        "available_hqla_day0": available_hqla_day0,
        "memenuhi_target": memenuhi_target,
        "add_on_required": not memenuhi_target,
    }

    if not memenuhi_target:
        target_bucket = days_to_bucket(target_survival_days, buckets)
        shortfall = -ladder.loc[target_bucket, "available_hqla_kumulatif"]
        result["target_bucket"] = target_bucket
        result["shortfall_pada_target"] = max(shortfall, 0.0)
        result["add_on_lcr_percent"] = None
        result["add_on_note"] = "compute_add_on_percent() belum diimplementasikan — lihat docstring fungsi tsb."

    return result
