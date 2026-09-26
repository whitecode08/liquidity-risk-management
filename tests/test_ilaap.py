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
    outflow_sektor_publik, outflow_bank,
    outflow_additional, inflow_counterparty, lcr_calculation, safe_read_excel,
    split_lps, normalize_kategori, rka_liability_amount,
    LPS_COVERAGE_LIMIT, LPS_RATE_CEILING, RKA_UNDRAWN_PATTERN,
    RUNOFF_PSE_OP_LPS, RUNOFF_PSE_OP_NONLPS,
    RUNOFF_PSE_NONOP_LPS, RUNOFF_PSE_NONOP_NONLPS, RUNOFF_BANK,
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

    def test_runoff_sektor_publik_and_bank(self):
        """The Entitas Sektor Publik rates are placeholders pending confirmation
        (see RUNOFF_PSE_* in lcr_engine.py); this only pins the table wiring, so
        that changing a constant there changes the rate the engine applies."""
        self.assertEqual(get_runoff_rate("sektor_publik", operasional=True, dijamin_lps=True),
                         RUNOFF_PSE_OP_LPS)
        self.assertEqual(get_runoff_rate("sektor_publik", operasional=True, dijamin_lps=False),
                         RUNOFF_PSE_OP_NONLPS)
        self.assertEqual(get_runoff_rate("sektor_publik", operasional=False, dijamin_lps=True),
                         RUNOFF_PSE_NONOP_LPS)
        self.assertEqual(get_runoff_rate("sektor_publik", operasional=False, dijamin_lps=False),
                         RUNOFF_PSE_NONOP_NONLPS)
        self.assertEqual(get_runoff_rate("bank"), RUNOFF_BANK)
        with self.assertRaises(ValueError):
            get_runoff_rate("sektor_publik")  # missing operasional/dijamin_lps


class TestCategorisationAndLpsSplit(unittest.TestCase):
    def test_jenis_nasabah_maps_to_categories(self):
        self.assertEqual(normalize_kategori("Perorangan"), "Retail")
        self.assertEqual(normalize_kategori("UMK"), "UMK")
        self.assertEqual(normalize_kategori("Korporasi"), "Korporasi")
        for pse in ("Pemda", "BUMD", "Instansi/BLUD"):
            self.assertEqual(normalize_kategori(pse), "Entitas Sektor Publik", pse)
        self.assertEqual(normalize_kategori("Bank Lain"), "Bank")

    def test_unknown_or_missing_category_returns_none(self):
        for bad in (None, float("nan"), "", "   ", "Koperasi Serba Usaha"):
            self.assertIsNone(normalize_kategori(bad), bad)

    def test_lps_split_cuts_through_the_account(self):
        """An account above the LPS limit is PARTLY insured, not wholly
        uninsured — the balance splits, it does not pick one side."""
        balances = pd.Series([1e9, LPS_COVERAGE_LIMIT, 5e9])
        dijamin, excess = split_lps(balances)
        self.assertEqual(list(dijamin), [1e9, 2e9, 2e9])
        self.assertEqual(list(excess), [0.0, 0.0, 3e9])
        # Nothing is created or lost by the split.
        self.assertTrue(((dijamin + excess) == balances).all())

    def test_lps_split_rate_above_ceiling_forfeits_the_whole_balance(self):
        """A deposit priced above LPS_RATE_CEILING loses the guarantee on its
        ENTIRE balance — even the portion under LPS_COVERAGE_LIMIT — unlike the
        coverage-limit rule, which only strips the excess above it."""
        balances = pd.Series([500_000_000.0, 5_000_000_000.0])
        rates = pd.Series([LPS_RATE_CEILING + 0.5, LPS_RATE_CEILING - 0.5])
        dijamin, excess = split_lps(balances, rates)
        self.assertEqual(list(dijamin), [0.0, LPS_COVERAGE_LIMIT])
        self.assertEqual(list(excess), [500_000_000.0, 3_000_000_000.0])

    def test_lps_split_missing_rate_defaults_to_compliant(self):
        """No rate column (None) or a blank rate (NaN) on some rows must not
        silently zero out the guarantee — only an actual above-ceiling value
        disqualifies an account."""
        balances = pd.Series([1_000_000_000.0, 1_000_000_000.0])
        dijamin_no_rate, _ = split_lps(balances, None)
        self.assertEqual(list(dijamin_no_rate), [1_000_000_000.0, 1_000_000_000.0])

        rates = pd.Series([float("nan"), LPS_RATE_CEILING + 1.0])
        dijamin, excess = split_lps(balances, rates)
        self.assertEqual(list(dijamin), [1_000_000_000.0, 0.0])
        self.assertEqual(list(excess), [0.0, 1_000_000_000.0])


class TestRkaSectionScoping(unittest.TestCase):
    """Both the TAGIHAN and the KEWAJIBAN block of the RKA sheet carry a row
    named 'FASILITAS KREDIT YANG BELUM DITARIK'. Only the KEWAJIBAN one is an
    outflow, so a whole-sheet match would double-count it."""

    def test_only_liability_section_counted(self):
        df = pd.DataFrame([
            ("TAGIHAN KOMITMEN", float("nan")),
            ("FASILITAS KREDIT YANG BELUM DITARIK", 500.0),
            ("KEWAJIBAN KOMITMEN", float("nan")),
            ("FASILITAS KREDIT YANG BELUM DITARIK", 800.0),
        ], columns=["KETERANGAN", "NILAI"])
        self.assertEqual(rka_liability_amount(df, RKA_UNDRAWN_PATTERN), 800.0)

    def test_matches_both_kredit_and_legacy_pembiayaan_wording(self):
        for label in ("FASILITAS KREDIT YANG BELUM DITARIK",
                       "FASILITAS PEMBIAYAAN YANG BELUM DITARIK"):
            df = pd.DataFrame([("KEWAJIBAN KOMITMEN", float("nan")), (label, 700.0)],
                              columns=["KETERANGAN", "NILAI"])
            self.assertEqual(rka_liability_amount(df, RKA_UNDRAWN_PATTERN), 700.0, label)


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

class TestLcrEndToEnd(unittest.TestCase):
    """End-to-end LCR against the dummy BPD book.

    Deliberately NOT pinned to a frozen ratio: the dummy generator is expected
    to keep evolving with the BPD profile, and a golden number would then fail
    for a reason that has nothing to do with the engine. What is asserted is
    that the figures hang together — every funding segment reaches the
    denominator, and the parts sum to the whole.
    """

    @unittest.skipUnless(_DUMMY_DIR.exists(), "dummy data not generated")
    def setUp(self):
        self.date = "2025-09-30"
        (self.df_aset, self.df_rangkuman, self.df_rka, self.df_pbi, self.df_sbi,
         df_tab, df_giro, df_depo, self.df_fin, _) = _load_period(self.date)
        self.df_tab, self.df_giro, self.df_depo = dpk_organize(df_tab, df_giro, df_depo, self.date)
        args = (self.df_tab, self.df_giro, self.df_depo, self.date)
        self.segments = {
            "Perorangan": outflow_retail(*args),
            "UMK": outflow_umk(*args),
            "Korporasi": outflow_corp(*args),
            "Sektor Publik": outflow_sektor_publik(*args),
            "Lembaga Keuangan": outflow_bank(*args),
            "Tambahan": outflow_additional(self.df_rka),
        }
        self.outflow = {k: v for seg in self.segments.values() for k, v in seg.items()}
        self.hqla = hqla_calc(self.df_aset, self.df_rangkuman, self.df_pbi, self.df_sbi)
        self.inflow = inflow_counterparty(self.df_fin, self.df_aset, self.date)
        self.lcr = lcr_calculation(self.hqla, self.outflow, self.inflow)

    def test_lcr_is_finite_and_positive(self):
        self.assertGreater(self.lcr["LCR"], 0)
        self.assertLess(self.lcr["LCR"], 10_000)
        self.assertGreater(self.lcr["Total Cash Outflow"], 0)

    def test_every_segment_reaches_the_total(self):
        """The bug this guards: lcr_calculation() used to sum a hard-coded list
        of four keys, so a newly added segment produced its own total and was
        then silently dropped from the denominator."""
        expected = sum(
            v for seg in self.segments.values() for k, v in seg.items()
            if k.startswith("Total Outflow Pendanaan") or k == "Total Outflow Tambahan"
        )
        self.assertAlmostEqual(self.lcr["Total Cash Outflow"], expected, places=2)
        for name in ("Sektor Publik", "Lembaga Keuangan"):
            total_key = next(k for k in self.segments[name] if k.startswith("Total Outflow"))
            self.assertGreater(self.segments[name][total_key], 0,
                               f"{name} contributed no outflow — check jenisNasabah in the source data")

    def test_dpk_categories_come_from_the_source_data(self):
        """jenisNasabah must be read, not guessed. If the balance heuristic were
        firing, no giro row could ever be categorised as Entitas Sektor Publik."""
        self.assertIn("Entitas Sektor Publik", set(self.df_giro["kategoriNasabah"]))
        self.assertIn("jenisNasabah", self.df_giro.columns)

    def test_stability_is_not_just_the_lps_threshold(self):
        """Stable funding requires an established relationship on top of LPS
        coverage, so it must be strictly less than everything under the limit."""
        insured_retail = 0.0
        for df in (self.df_tab, self.df_giro, self.df_depo):
            retail = df[df["kategoriNasabah"] == "Retail"]
            dijamin, _ = split_lps(retail["jumlahBulanLaporanActive"])
            insured_retail += float(dijamin.sum())
        self.assertGreater(self.outflow["Retail Stable Funding"], 0)
        self.assertLess(self.outflow["Retail Stable Funding"], insured_retail)

    def test_matured_deposits_are_charged_not_dropped(self):
        """Overdue deposits used to be filtered out of the LCR entirely while
        NSFR counted them as stable funding. Both engines now treat them as
        maturing on day 0."""
        tenor = (pd.to_datetime(self.df_depo["tanggalJatuhTempo"])
                 - pd.to_datetime(self.date)).dt.days
        # Bank/FI funding has no separate matured line — it runs off at 100%
        # whether or not it has matured, so there is nothing to distinguish.
        reported = self.df_depo["kategoriNasabah"] != "Bank"
        overdue = float(self.df_depo.loc[(tenor <= 0) & reported, "jumlahBulanLaporanActive"].sum())
        self.assertGreater(overdue, 0, "dummy data carries no overdue deposits to exercise this")
        charged = sum(v for k, v in self.outflow.items() if "Matured Deposits" in k
                      and not k.endswith("(100%)"))
        self.assertAlmostEqual(charged, overdue, places=2)


if __name__ == "__main__":
    unittest.main()
