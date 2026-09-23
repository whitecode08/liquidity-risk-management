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

from lcr_engine import get_runoff_rate, get_inflow_rate, get_additional_outflow_rate  # noqa: E402

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
    "outflow_undrawn_commitment": lambda: get_additional_outflow_rate("undrawn_commitment"),
    "outflow_guarantee":          lambda: get_additional_outflow_rate("guarantee"),
    "inflow_performing":     lambda: get_inflow_rate("counterparty_performing"),
    "inflow_non_performing": lambda: 0.0,  # conservative: NPF is not a reliable cash inflow
}

# Segment used to test whether a benchmark scenario's segmen_terdampak filter
# applies to a given funding row's kategori_arus.
_SEGMENT_OF_KATEGORI = {
    "retail_stabil": "retail", "retail_tidak_stabil": "retail",
    "umk_stabil": "umk", "umk_tidak_stabil": "umk",
    "korporasi_op_lps": "korporasi", "korporasi_op_nonlps": "korporasi",
    "korporasi_nonop_lps": "korporasi", "korporasi_nonop_nonlps": "korporasi",
}


def get_rate_for_row(kategori_arus: str) -> float:
    try:
        return _RATE_MAP[kategori_arus]()
    except KeyError:
        raise ValueError(f"Unknown kategori_arus: {kategori_arus!r}")


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
    segmen_terdampak = scenario.get("segmen_terdampak")
    rows = []
    for _, row in without_tenor.iterrows():
        if row["sumber"] == "off_balance_guarantee":
            shares = {"overnight": 1.0}
        elif row["sumber"] == "off_balance_undrawn":
            shares = _day_weighted_shares(buckets, 0, 30)
        elif mode == "hari_pertama":
            shares = {"overnight": 1.0}
        elif mode == "satu_kali_h1_sampai_h30":
            row_segmen = _SEGMENT_OF_KATEGORI.get(row["kategori_arus"])
            if segmen_terdampak is not None and row_segmen not in segmen_terdampak:
                # This benchmark scenario isolates specific segments — funding
                # from segments not under test is assumed to stay in place
                # (not stressed) for this run, so it contributes no outflow.
                continue
            shares = _day_weighted_shares(buckets, 1, 30)
        else:
            raise ValueError(f"Unknown no_tenor_distribution mode: {mode!r}")

        for bucket_id, frac in shares.items():
            new_row = row.copy()
            new_row["bucket_id"] = bucket_id
            new_row["nilai_bucket"] = row["nilai_dasar"] * frac
            rows.append(new_row)

    return pd.DataFrame(rows)


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
    with_tenor["bucket_id"] = with_tenor["hari_ke_jatuh_tempo"].apply(lambda h: assign_bucket(h, buckets))
    with_tenor["nilai_bucket"] = with_tenor["nilai_dasar"]

    without_tenor_expanded = distribute_no_tenor(without_tenor, scenario, buckets)

    combined = pd.concat([with_tenor, without_tenor_expanded], ignore_index=True, sort=False)
    combined["rate"] = combined["kategori_arus"].apply(get_rate_for_row)
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
