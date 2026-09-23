"""
Unit tests for the ILAAP module (Modul 1 — Available HQLA, Modul 2 —
Survival Period Monitoring). Run with:

    python -m unittest discover -s tests -v

(No pytest dependency in this repo — plain unittest is used deliberately.)
"""
import pathlib
import sys
import unittest

import pandas as pd

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC_DIR))

from lcr_engine import (  # noqa: E402
    get_runoff_rate, get_inflow_rate, get_additional_outflow_rate,
    hqla_calc, dpk_organize, outflow_retail, outflow_umk, outflow_corp,
    outflow_additional, inflow_counterparty, lcr_calculation, safe_read_excel,
)
from ilaap.available_hqla import available_hqla_calc  # noqa: E402
from ilaap import data_contract  # noqa: E402
from ilaap import survival_period as sp  # noqa: E402
from ilaap import audit as ilaap_audit  # noqa: E402

_DUMMY_DIR = pathlib.Path(__file__).resolve().parent.parent / "database" / "dummy"


# ── Rate table tests ─────────────────────────────────────────────────────────

class TestRateTables(unittest.TestCase):
    def test_runoff_retail_umk(self):
        self.assertEqual(get_runoff_rate("retail", stabilitas="stabil"), 0.05)
        self.assertEqual(get_runoff_rate("retail", stabilitas="tidak_stabil"), 0.10)
        self.assertEqual(get_runoff_rate("umk", stabilitas="stabil"), 0.05)
        self.assertEqual(get_runoff_rate("umk", stabilitas="tidak_stabil"), 0.10)

    def test_runoff_korporasi(self):
        self.assertEqual(get_runoff_rate("korporasi", operasional=True, dijamin_lps=True), 0.05)
        self.assertEqual(get_runoff_rate("korporasi", operasional=True, dijamin_lps=False), 0.25)
        self.assertEqual(get_runoff_rate("korporasi", operasional=False, dijamin_lps=True), 0.20)
        self.assertEqual(get_runoff_rate("korporasi", operasional=False, dijamin_lps=False), 0.40)

    def test_additional_and_inflow_rates(self):
        self.assertEqual(get_additional_outflow_rate("undrawn_commitment"), 0.10)
        self.assertEqual(get_additional_outflow_rate("guarantee"), 0.05)
        self.assertEqual(get_inflow_rate("counterparty_performing"), 0.5)
        self.assertEqual(get_inflow_rate("interbank_placement"), 0.0)

    def test_unknown_inputs_raise(self):
        with self.assertRaises(ValueError):
            get_runoff_rate("unknown_segment")
        with self.assertRaises(ValueError):
            get_runoff_rate("retail")  # missing stabilitas


# ── Bucket assignment tests ──────────────────────────────────────────────────

class TestBucketAssignment(unittest.TestCase):
    def setUp(self):
        self.buckets = sp.load_time_buckets()

    def test_bucket_count(self):
        self.assertEqual(len(self.buckets), 19)

    def test_overnight_and_boundaries(self):
        self.assertEqual(sp.assign_bucket(0, self.buckets), "overnight")
        self.assertEqual(sp.assign_bucket(1, self.buckets), "h2")
        self.assertEqual(sp.assign_bucket(29, self.buckets), "h14_1bln")
        self.assertEqual(sp.assign_bucket(30, self.buckets), "b1_2bln")
        self.assertEqual(sp.assign_bucket(364, self.buckets), "b9_12bln")
        self.assertEqual(sp.assign_bucket(365, self.buckets), "b12bln_2thn")
        self.assertEqual(sp.assign_bucket(1825, self.buckets), "diatas_5thn")
        self.assertEqual(sp.assign_bucket(50_000, self.buckets), "diatas_5thn")

    def test_overdue_maps_negative_days(self):
        self.assertEqual(sp.assign_bucket(-5, self.buckets), "overdue")

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            sp.assign_bucket(float("nan"), self.buckets)


# ── Golden pattern tests (source doc §5.6 — Bank A / Bank B) ────────────────
# These use a simplified monthly bucket set (not the production 19-bucket
# config) matching the source table's month-by-month granularity, to directly
# exercise determine_survival_period()'s depletion/target-met logic — the
# function is generic over any ordered bucket list. Bucket-mapping mechanics
# for the real 19-bucket structure are covered separately in
# TestBucketAssignment above.

def _monthly_buckets(n_months=6):
    return [{"id": f"month_{k}", "hari_mulai": 30 * (k - 1) + 1, "hari_selesai": 30 * k + 1}
            for k in range(1, n_months + 1)]


class TestSurvivalPeriodGolden(unittest.TestCase):
    def test_bank_a_target_met_no_addon(self):
        """Source doc table: Bank A stays positive through month 6, 3-month
        target is met, no add-on required."""
        buckets = _monthly_buckets(6)
        ladder = pd.DataFrame({
            "net_outflow_kumulatif": [106, 240, 558, 574, 710, 1061],
        }, index=[b["id"] for b in buckets])

        result = sp.determine_survival_period(
            ladder, available_hqla_day0=1200, target_survival_days=90, buckets=buckets,
        )

        self.assertIsNone(result["survival_bucket"])
        self.assertTrue(result["memenuhi_target"])
        self.assertFalse(result["add_on_required"])

    def test_bank_b_deficit_month_2_addon_required(self):
        """Deficit hits in month 2 (< 3-month/90-day target) -> add-on required."""
        buckets = _monthly_buckets(6)
        ladder = pd.DataFrame({
            "net_outflow_kumulatif": [150, 250, 320, 400, 480, 560],
        }, index=[b["id"] for b in buckets])

        result = sp.determine_survival_period(
            ladder, available_hqla_day0=200, target_survival_days=90, buckets=buckets,
        )

        self.assertEqual(result["survival_bucket"], "month_2")
        self.assertFalse(result["memenuhi_target"])
        self.assertTrue(result["add_on_required"])
        self.assertGreater(result["shortfall_pada_target"], 0)

    def test_add_on_percent_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            sp.compute_add_on_percent(shortfall=100, current_hqla_day0=200)


# ── End-to-end against dummy data ────────────────────────────────────────────

def _load_period(date: str):
    D = _DUMMY_DIR
    df_aset = safe_read_excel(D / f"NeracaHarian_{date}.xlsx", sheet_name="ASET")
    df_rangkuman = safe_read_excel(D / f"NeracaHarian_{date}.xlsx", sheet_name="RANGKUMAN")
    df_rka = safe_read_excel(D / f"NeracaHarian_{date}.xlsx", sheet_name="RKA")
    df_pbi = safe_read_excel(D / f"PenempatanBI_{date}.xlsx")
    df_sbi = safe_read_excel(D / f"SBI_{date}.xlsx")
    df_tab = safe_read_excel(D / f"Tabungan_{date}.xlsx")
    df_giro = safe_read_excel(D / f"Giro_{date}.xlsx")
    df_depo = safe_read_excel(D / f"Deposito_{date}.xlsx")
    df_fin = safe_read_excel(D / f"Pinjaman_{date}.xlsx")
    df_gwm_plm = safe_read_excel(D / f"KewajibanGWMPLM_{date}.xlsx")
    return df_aset, df_rangkuman, df_rka, df_pbi, df_sbi, df_tab, df_giro, df_depo, df_fin, df_gwm_plm


@unittest.skipUnless(_DUMMY_DIR.exists(), "dummy data not generated — run scripts/generate_dummy_data.py")
class TestAgainstDummyData(unittest.TestCase):
    DATE = "2025-09-30"

    def setUp(self):
        (self.df_aset, self.df_rangkuman, self.df_rka, self.df_pbi, self.df_sbi,
         df_tab, df_giro, df_depo, self.df_fin, self.df_gwm_plm) = _load_period(self.DATE)
        self.df_tab, self.df_giro, self.df_depo = dpk_organize(df_tab, df_giro, df_depo)
        self.buckets = sp.load_time_buckets()
        self.scenarios = sp.load_stress_scenarios()

    def test_available_hqla_no_double_count(self):
        hqla = hqla_calc(self.df_aset, self.df_rangkuman, self.df_pbi, self.df_sbi)
        plm = float(self.df_gwm_plm.loc[
            self.df_gwm_plm["KETERANGAN"].str.contains("PLM"), "NILAI"].iloc[0])
        bi_sourced = float(self.df_gwm_plm.loc[
            self.df_gwm_plm["KETERANGAN"].str.contains("BANK SENTRAL"), "NILAI"].iloc[0])

        result = available_hqla_calc(hqla, gwm_obligation=0, plm_obligation=plm,
                                      bi_sourced_liquidity=bi_sourced)

        self.assertEqual(result["total_hqla"], hqla["Total HQLA"])
        self.assertLess(result["available_hqla"], result["total_hqla"])
        self.assertGreaterEqual(result["available_hqla"], 0)

    def test_ladder_lcr_30_hari_and_reconcile(self):
        ledger = data_contract.build_transactions_ledger(
            self.df_tab, self.df_giro, self.df_depo, self.df_fin, self.df_rka, self.DATE,
        )
        self.assertFalse(ledger.empty)

        scenario = self.scenarios["lcr_30_hari"]
        ladder = sp.project_cashflow_ladder(ledger, self.buckets, scenario, self.DATE)

        # Cumulative outflow/inflow must be non-decreasing along the ladder.
        self.assertTrue((ladder["arus_keluar_kumulatif"].diff().dropna() >= -1e-6).all())
        self.assertTrue((ladder["arus_masuk_kumulatif"].diff().dropna() >= -1e-6).all())

        recon = ilaap_audit.reconcile_ladder(ledger, ladder, self.buckets, scenario, self.DATE)
        failing = recon[recon["Status"] != "PASS"]
        self.assertTrue(failing.empty, f"reconciliation FAILed for buckets:\n{failing}")

    def test_ladder_benchmark_scenarios_run(self):
        ledger = data_contract.build_transactions_ledger(
            self.df_tab, self.df_giro, self.df_depo, self.df_fin, self.df_rka, self.DATE,
        )
        for scenario_id in ("benchmark_90_hari_ritel", "benchmark_90_hari_korporasi",
                             "benchmark_90_hari_gabungan"):
            with self.subTest(scenario=scenario_id):
                scenario = self.scenarios[scenario_id]
                ladder = sp.project_cashflow_ladder(ledger, self.buckets, scenario, self.DATE)
                self.assertEqual(len(ladder), len(sp.bucket_order(self.buckets)))

    def test_determine_survival_period_runs_on_real_ladder(self):
        hqla = hqla_calc(self.df_aset, self.df_rangkuman, self.df_pbi, self.df_sbi)
        plm = float(self.df_gwm_plm.loc[
            self.df_gwm_plm["KETERANGAN"].str.contains("PLM"), "NILAI"].iloc[0])
        available = available_hqla_calc(hqla, gwm_obligation=0, plm_obligation=plm,
                                         bi_sourced_liquidity=0)

        ledger = data_contract.build_transactions_ledger(
            self.df_tab, self.df_giro, self.df_depo, self.df_fin, self.df_rka, self.DATE,
        )
        ladder = sp.project_cashflow_ladder(ledger, self.buckets, self.scenarios["lcr_30_hari"], self.DATE)
        result = sp.determine_survival_period(
            ladder, available["available_hqla"], target_survival_days=90, buckets=self.buckets,
        )
        self.assertIn("memenuhi_target", result)
        self.assertIn("add_on_required", result)


# ── Regression: refactor must not change LCR/NSFR results ──────────────────

class TestLcrRegressionAfterRefactor(unittest.TestCase):
    """get_runoff_rate/get_inflow_rate extraction must be behavior-preserving."""

    @unittest.skipUnless(_DUMMY_DIR.exists(), "dummy data not generated")
    def test_lcr_matches_known_value(self):
        date = "2025-09-30"
        (df_aset, df_rangkuman, df_rka, df_pbi, df_sbi,
         df_tab, df_giro, df_depo, df_fin, _) = _load_period(date)
        df_tab, df_giro, df_depo = dpk_organize(df_tab, df_giro, df_depo)

        hqla = hqla_calc(df_aset, df_rangkuman, df_pbi, df_sbi)
        outflow = {
            **outflow_retail(df_tab, df_giro, df_depo, date),
            **outflow_umk(df_tab, df_giro, df_depo, date),
            **outflow_corp(df_tab, df_giro, df_depo, date),
            **outflow_additional(df_rka),
        }
        inflow = inflow_counterparty(df_fin, df_aset, date)
        lcr = lcr_calculation(hqla, outflow, inflow)

        # Known-good value captured before/after the get_runoff_rate refactor.
        self.assertAlmostEqual(lcr["LCR"], 255.4816, places=3)


if __name__ == "__main__":
    unittest.main()
