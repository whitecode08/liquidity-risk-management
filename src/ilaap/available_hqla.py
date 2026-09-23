"""
Available HQLA — Modul 1 (SEOJK No. 26/SEOJK.03/2025).
========================================================

Formula (source doc §4.1):
    Available HQLA = HQLA (POJK LCR, haircut Pasal 10/11/12)
                      - Kewajiban GWM
                      - Kewajiban PLM (Penyangga Likuiditas Makroprudensial)
                      - Sumber likuiditas dari Bank Sentral

Deviation from the spec's pseudocode, documented here rather than silently:
the spec's draft assumed `hqla_calc()` returns a DataFrame with a
"nilai_setelah_haircut" column. The real lcr_engine.hqla_calc() (unchanged,
per instructions) returns a plain dict with a "Total HQLA" key — this module
reads that key directly instead of inventing a fake DataFrame shape.

gwm_obligation is deliberately expected to be 0 for this repo: lcr_engine.py's
hqla_calc() already nets the GWM estimate (3.5% x DPK) out of the Giro BI
balance before it ever reaches "Total HQLA" (see its `estimate_gwm` line).
Subtracting it again here would double-count the same obligation. This module
still accepts gwm_obligation as a parameter (per the source spec) so a future
bank whose HQLA figure does NOT already net GWM can pass a nonzero value —
but the dummy data generator passes 0, with the reasoning captured in the
"KEWAJIBAN GWM" row of KewajibanGWMPLM_<date>.xlsx (kept for transparency,
not fed into the subtraction).
"""
from __future__ import annotations


def available_hqla_calc(hqla_result: dict, gwm_obligation: float,
                         plm_obligation: float, bi_sourced_liquidity: float) -> dict:
    """
    hqla_result: the dict returned by lcr_engine.hqla_calc() — NOT recomputed
        here, to avoid duplicating the haircut logic.
    gwm_obligation, plm_obligation, bi_sourced_liquidity: scalar values for
        the reporting date (see docs/SPEK_MODUL_ILAAP.md §4.3 — for this repo
        these come from the dummy generator's KewajibanGWMPLM_<date>.xlsx).
    """
    total_hqla = float(hqla_result["Total HQLA"])
    available = total_hqla - gwm_obligation - plm_obligation - bi_sourced_liquidity
    return {
        "total_hqla": total_hqla,
        "gwm_obligation": gwm_obligation,
        "plm_obligation": plm_obligation,
        "bi_sourced_liquidity": bi_sourced_liquidity,
        "available_hqla": max(available, 0.0),  # cannot be negative
        "_formula": "total_hqla - gwm_obligation - plm_obligation - bi_sourced_liquidity",
    }
