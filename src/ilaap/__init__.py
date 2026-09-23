"""
ILAAP module — Internal Liquidity Adequacy Assessment Process.
================================================================
Extends lcr_engine.py / nsfr_engine.py per SEOJK No. 26/SEOJK.03/2025.

Implemented in this package:
  - available_hqla.py   Modul 1: Available HQLA (HQLA − GWM − PLM − BI-sourced)
  - survival_period.py  Modul 2: Survival Period Monitoring (19-bucket ladder)
  - data_contract.py    Normalizes source sheets into one transaction ledger
  - audit.py            ILAAP-specific audit trail + independent reconciliation

Not implemented (out of scope for this revision — see docs/SPEK_MODUL_ILAAP.md
§11/§12): funding_profile.py (Modul 6), roll_over.py (Modul 4),
fx_significant.py (Modul 3). Each needs additional confirmation from the Bank
(official SEOJK 26/2025 annex format, rollover identification method) before
implementation.
"""
