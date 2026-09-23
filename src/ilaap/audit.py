"""
ILAAP audit trail — extends audit_log.py, does not replace it.
==================================================================

Mirrors the reconcile() pattern already used for LCR/NSFR in audit_log.py:
recompute the final figure independently from the base transactions, compare
against the module's own output, PASS/FAIL. This module's ladder is the
riskiest of the two ("modul paling kompleks dan paling rawan bug pemetaan
bucket yang salah tapi kelihatan masuk akal" — source spec §10), so the
independent recompute deliberately re-derives the cumulative columns with a
fresh groupby/cumsum pass rather than trusting project_cashflow_ladder()'s
own aggregation step.
"""
from __future__ import annotations

import sys
import pathlib

import pandas as pd

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import audit_log as al  # noqa: E402 — reuse the existing session log store
from ilaap.survival_period import (  # noqa: E402
    assign_bucket, distribute_no_tenor, bucket_order, get_rate_for_row,
)


def log_survival_period_run(ladder_df: pd.DataFrame, scenario_id: str,
                             result: dict, manifest: dict) -> None:
    """Record a Survival Period run in the shared session audit trail.

    manifest: e.g. {"asof": ..., "target_survival_days": ..., "files": {...}}
    """
    al.record(
        "ILAAP — Survival Period", "RUN START",
        f"Survival Period calculation executed — scenario {scenario_id}",
        reference="SEOJK No. 26/SEOJK.03/2025",
        detail={"scenario_id": scenario_id, **manifest},
    )
    al.record_result(
        "ILAAP — Survival Period", "Survival horizon (days)",
        result.get("survival_hari"), reference="SEOJK No. 26/SEOJK.03/2025",
    )
    al.record_result(
        "ILAAP — Survival Period", "Target met",
        result.get("memenuhi_target"), reference="SEOJK No. 26/SEOJK.03/2025",
    )
    al.record(
        "ILAAP — Survival Period", "LADDER",
        f"Full {len(ladder_df)}-bucket cash-flow ladder",
        reference="SEOJK No. 26/SEOJK.03/2025 Lampiran IV",
        detail={"ladder": ladder_df.reset_index().to_dict(orient="records")},
    )
    if result.get("add_on_required"):
        al.record(
            "ILAAP — Survival Period", "PILLAR 2 ADD-ON",
            "Survival period target not met — add-on methodology not yet implemented",
            reference="SEOJK No. 26/SEOJK.03/2025 §10.19-10.27",
            detail={"shortfall_pada_target": result.get("shortfall_pada_target")},
        )


def reconcile_ladder(transactions_df: pd.DataFrame, ladder_df: pd.DataFrame,
                      buckets: list[dict], scenario: dict, asof_date: str,
                      tolerance: float = 1.0) -> pd.DataFrame:
    """Independently recompute net_outflow_kumulatif per bucket and compare
    against project_cashflow_ladder()'s own output. Returns a DataFrame with
    one row per bucket and a PASS/FAIL Status column — same contract as
    audit_log.reconcile() for LCR/NSFR.
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

    # Independent aggregation path: sum weighted value per (bucket, arah) via
    # a plain dict accumulation instead of groupby().unstack(), so a pivoting
    # bug in the main module's implementation wouldn't be replicated here.
    totals: dict[tuple[str, str], float] = {}
    for _, row in combined.iterrows():
        rate = get_rate_for_row(row["kategori_arus"])
        key = (row["bucket_id"], row["arah"])
        totals[key] = totals.get(key, 0.0) + row["nilai_bucket"] * rate

    order = bucket_order(buckets)
    rows = []
    keluar_cum = 0.0
    masuk_cum = 0.0
    for bucket_id in order:
        keluar = totals.get((bucket_id, "keluar"), 0.0)
        masuk = totals.get((bucket_id, "masuk"), 0.0)
        keluar_cum += keluar
        masuk_cum += masuk
        net_cum_check = keluar_cum - masuk_cum
        net_cum_engine = float(ladder_df.loc[bucket_id, "net_outflow_kumulatif"])
        diff = abs(net_cum_check - net_cum_engine)
        rows.append({
            "bucket_id": bucket_id,
            "net_outflow_kumulatif (independen)": net_cum_check,
            "net_outflow_kumulatif (engine)": net_cum_engine,
            "Selisih": diff,
            "Status": "PASS" if diff <= tolerance else "FAIL",
        })
    return pd.DataFrame(rows)
