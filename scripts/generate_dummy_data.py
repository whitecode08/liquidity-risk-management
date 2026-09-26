"""
Generate synthetic dummy source files for a CONVENTIONAL BPD (Bank Pembangunan
Daerah) scenario, matching the schema the LCR/NSFR engines expect, for two
reporting dates so results can be compared month-over-month.

BPD profile modelled here (see docs/REVISI_LIQUIDITY_RISK_BPD.md Fase 1):
  - `jenisNasabah` is written explicitly on every DPK row (Perorangan, UMK,
    Korporasi, Pemda, BUMD, Instansi/BLUD, Bank Lain) so the engines read the
    real customer category instead of guessing it from the balance.
  - Dana Pemda (RKUD) sits in a handful of very large giro accounts and follows
    the APBD cycle — high in semester I, drawn down towards year-end.
  - Payroll ASN accounts are flagged (`flagPayroll` / `instansiPayroll`); the
    engines use that flag as the "established relationship" leg of the
    stable-deposit test.
  - `KREDIT_ASN` (potong gaji) is a first-class loan type: long tenor, low NPL.

All data is 100% synthetic (no real customer data). Output goes to
database/dummy/ so any real sample files kept locally in database/ are
left untouched.

Run from the project root:
    python scripts/generate_dummy_data.py
"""
import pathlib
import sys

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20250923)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "database" / "dummy"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Reuse the engine's own LPS rate ceiling rather than keeping a second copy
# here that could silently drift from what lcr_engine.split_lps() applies.
sys.path.insert(0, str(ROOT / "src"))
from lcr_engine import LPS_RATE_CEILING  # noqa: E402

BANK_ID = 999000001
DATE_PREV = "2025-08-31"   # comparison baseline
DATE_CUR = "2025-09-30"    # current period


def save(df_or_sheets, name, date):
    path = OUT_DIR / f"{name}_{date}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        if isinstance(df_or_sheets, dict):
            for sheet, df in df_or_sheets.items():
                df.to_excel(xw, sheet_name=sheet, index=False)
        else:
            df_or_sheets.to_excel(xw, sheet_name="GENERATE", index=False)
    print("wrote", path)


def acc(prefix, i):
    return f"{prefix}{i:08d}"


def cif(i):
    return f"{i:08d}"


def where_obj(mask, true_val, false_val=np.nan):
    return np.array([true_val if m else false_val for m in mask], dtype=object)


def rescale_to(arr, target_sum):
    """Scale a positive-value array so it sums exactly to target_sum,
    preserving its relative shape (distribution across accounts)."""
    arr = np.asarray(arr, dtype=float)
    current = arr.sum()
    if current <= 0:
        return arr
    return arr * (target_sum / current)


# ── BPD customer profile ────────────────────────────────────────────────────
# `jenisNasabah` values consumed by lcr_engine._normalize_cat() / nsfr_engine.
# Keep these spellings in sync with JENIS_NASABAH_MAP in src/lcr_engine.py.
JENIS_NASABAH = ["Perorangan", "UMK", "Korporasi", "Pemda", "BUMD",
                 "Instansi/BLUD", "Bank Lain"]

# Mix per product. A BPD's book is dominated by Perorangan (largely ASN
# payroll) on tabungan, while giro carries the Pemda/BUMD concentration.
MIX_TABUNGAN = {"Perorangan": 0.90, "UMK": 0.07, "Instansi/BLUD": 0.02, "Korporasi": 0.01}
# Pemda is deliberately a SMALL count with a LARGE share of the balance — the
# RKUD concentration is the defining liquidity risk of a BPD's giro book.
MIX_GIRO = {"Perorangan": 0.20, "UMK": 0.18, "Korporasi": 0.34, "Pemda": 0.03,
            "BUMD": 0.09, "Instansi/BLUD": 0.14, "Bank Lain": 0.02}
MIX_DEPOSITO = {"Perorangan": 0.62, "UMK": 0.10, "Korporasi": 0.15, "Pemda": 0.05,
                "BUMD": 0.04, "Instansi/BLUD": 0.03, "Bank Lain": 0.01}

INSTANSI_PAYROLL = [
    "Pemprov - Sekretariat Daerah", "Dinas Pendidikan", "Dinas Kesehatan",
    "Dinas Pekerjaan Umum", "RSUD Provinsi", "Badan Keuangan Daerah",
    "Inspektorat Daerah", "Pemkab - Sekretariat Daerah", "Dinas Sosial",
    "Satpol PP",
]

# Share of the giro book that belongs to the RKUD / Pemda concentration at the
# seasonal peak. Multiplied by pemda_seasonal_factor() for the reporting month.
PEMDA_GIRO_PEAK_SHARE = 0.34

# Share of Perorangan tabungan that is an ASN payroll account. Sized so every
# KREDIT_ASN borrower can be matched to a payroll account at this bank —
# salary deduction (potong gaji) only works when the salary lands here.
PAYROLL_SHARE_PERORANGAN = 0.45

# Disjoint CIF ranges per source, so one CIF never carries two different
# jenisNasabah across products. KREDIT_ASN borrowers reuse their payroll CIF.
CIF_BASE = {"tabungan": 0, "giro": 100_000, "deposito": 200_000, "debitur": 300_000}


# PLACEHOLDER — BI Deposit Facility rate (conventional standing facility; the
# sharia counterpart is FASBIS). Confirm against BI's rate on the reporting date.
DEPOSIT_FACILITY_RATE_ASSUMPTION = 3.75


def draw_jenis_nasabah(mix: dict, n: int) -> np.ndarray:
    labels = list(mix)
    probs = np.array([mix[k] for k in labels], dtype=float)
    return RNG.choice(labels, size=n, p=probs / probs.sum())


def pemda_seasonal_factor(date: str) -> float:
    """APBD cycle multiplier for Pemda (RKUD) giro balances.

    Transfers from the centre land early and are spent down as the budget is
    realised, so the RKUD balance peaks around Q1-Q2 and bottoms out in
    December. Deliberately a simple month lookup — not a fitted seasonal model.
    """
    month = pd.Timestamp(date).month
    by_month = {1: 1.15, 2: 1.20, 3: 1.18, 4: 1.10, 5: 1.05, 6: 1.00,
                7: 0.92, 8: 0.84, 9: 0.76, 10: 0.64, 11: 0.48, 12: 0.28}
    return by_month[month]


# ── Tabungan (was tab01) ───────────────────────────────────────────────────
def gen_tabungan(n, date, target_sum, noise=1.0):
    i = np.arange(1, n + 1)
    jenis = draw_jenis_nasabah(MIX_TABUNGAN, n)

    # Payroll ASN: roughly a third of the Perorangan book is a salary account
    # routed through the BPD. These balances are less dispersed (salary in,
    # spent down over the month) — that low dispersion is the point, it is what
    # makes them "stabil" under the engines' stable-deposit test.
    payroll_mask = (jenis == "Perorangan") & (RNG.random(n) < PAYROLL_SHARE_PERORANGAN)
    shape = np.clip(RNG.lognormal(13.0, 1.4, n), 50_000, None)
    shape = np.where(payroll_mask, np.clip(RNG.lognormal(14.6, 0.55, n), 1_000_000, None), shape)

    balances = rescale_to(shape, target_sum * noise)
    # Blocked balances: at a BPD most blocks are savings pledged as cash
    # collateral for a loan, not court seizures.
    blocked_mask = RNG.random(n) < 0.03
    blocked = np.where(blocked_mask, balances * RNG.uniform(0.05, 0.3, n), 0.0)
    alasan_blokir = RNG.choice(["Jaminan Kredit", "Permintaan Nasabah", "Sita/Blokir Pengadilan"],
                               size=n, p=[0.60, 0.25, 0.15])
    # Payroll accounts are long-tenured relationships; others are mixed.
    open_days = np.where(payroll_mask, RNG.integers(400, 4000, n), RNG.integers(60, 3600, n))
    return pd.DataFrame({
        "idPelapor": BANK_ID,
        "periodeLaporan": "M",
        "periodeData": date,
        "nomorRekening": [acc("2010", x) for x in i],
        "jumlahRekening": 1,
        "idPihakLawan": [cif(CIF_BASE["tabungan"] + x) for x in i],
        "jenisNasabah": jenis,
        "flagPayroll": payroll_mask,
        "instansiPayroll": np.where(payroll_mask, RNG.choice(INSTANSI_PAYROLL, size=n), None),
        "statusDana": "S",
        "fiturTambahan": where_obj(RNG.random(n) < 0.25, "T"),
        "jenisValuta": "IDR",
        "klasifikasiLiabilitasKeuangan": np.nan,
        "lokasiKCKCP": 996,
        "jenisSukuBunga": np.nan,
        "sukuBungaBulanLaporan": np.round(RNG.uniform(0.5, 2.75, n), 2),
        "sukuBungaAwalKontrak": np.round(RNG.uniform(0.5, 2.75, n), 2),
        "tanggalMulai": (pd.Timestamp(date) - pd.to_timedelta(open_days, unit="D")).strftime("%Y-%m-%d"),
        # Customer-relationship start. On tabungan/giro it coincides with the
        # account opening; the engines read it in preference to tanggalMulai.
        "tanggalMulaiHubungan": (pd.Timestamp(date) - pd.to_timedelta(open_days, unit="D")).strftime("%Y-%m-%d"),
        "tanggalJatuhTempo": np.nan,
        "nominal": np.nan,
        "nominalDiblokir": blocked.round(0),
        "alasanDiblokir": np.where(blocked_mask, alasan_blokir, None),
        "jumlahBulanLalu": np.nan,
        "jumlahDebet": np.nan,
        "jumlahKredit": np.nan,
        "jumlahLainnya": np.nan,
        "jumlahBulanLaporan": balances.round(0),
    })


# ── Giro (was gir01) ────────────────────────────────────────────────────────
def gen_giro(n, date, target_sum, noise=1.0):
    """Giro book. `target_sum` is the NON-Pemda target; the Pemda (RKUD) block
    is sized separately from PEMDA_GIRO_PEAK_SHARE × pemda_seasonal_factor(),
    so the giro total genuinely moves with the APBD cycle instead of being
    normalised away."""
    i = np.arange(1, n + 1)
    jenis = draw_jenis_nasabah(MIX_GIRO, n)
    is_pemda = jenis == "Pemda"

    # giro skews to larger corporate/business balances than tabungan
    shape = np.clip(RNG.lognormal(14.5, 2.0, n), 500_000, None)
    balances = rescale_to(np.where(is_pemda, 0.0, shape), target_sum * noise)

    # RKUD: a handful of very large accounts (kas daerah + a few SKPD), sized
    # against the non-Pemda book and drawn down towards year-end.
    pemda_target = (target_sum * noise * PEMDA_GIRO_PEAK_SHARE
                    * pemda_seasonal_factor(date))
    pemda_shape = np.clip(RNG.lognormal(1.0, 0.7, n), 0.2, None)
    balances = np.where(is_pemda,
                        rescale_to(np.where(is_pemda, pemda_shape, 0.0), pemda_target),
                        balances)

    # Pemda/BUMD/instansi relationships are institutional and long-standing.
    institutional = np.isin(jenis, ["Pemda", "BUMD", "Instansi/BLUD"])
    open_days = np.where(institutional, RNG.integers(900, 6000, n), RNG.integers(30, 6000, n))
    return pd.DataFrame({
        "idPelapor": BANK_ID,
        "periodeLaporan": "M",
        "periodeData": date,
        "nomorRekening": [acc("2011", x) for x in i],
        "jumlahRekening": 1,
        "idPihakLawan": [cif(CIF_BASE["giro"] + x) for x in i],
        "jenisNasabah": jenis,
        "flagPayroll": False,
        "instansiPayroll": None,
        "statusDana": "S",
        "jenisValuta": "IDR",
        "klasifikasiLiabilitasKeuangan": np.nan,
        "lokasiKCKCP": 996,
        "jenisSukuBunga": np.nan,
        "sukuBungaAwalKontrak": np.nan,
        "sukuBungaBulanLaporan": np.round(RNG.uniform(0.0, 1.0, n), 2),
        "tanggalMulai": (pd.Timestamp(date) - pd.to_timedelta(open_days, unit="D")).strftime("%Y-%m-%d"),
        "tanggalMulaiHubungan": (pd.Timestamp(date) - pd.to_timedelta(open_days, unit="D")).strftime("%Y-%m-%d"),
        "nominal": np.nan,
        "nominalDiblokir": 0,
        "alasanDiblokir": np.nan,
        "jumlahBulanLalu": np.nan,
        "jumlahDebet": np.nan,
        "jumlahKredit": np.nan,
        "jumlahLainnya": np.nan,
        "jumlahBulanLaporan": balances.round(0),
    })


# ── Deposito (was dep01) ─────────────────────────────────────────────────────
def gen_deposito(n, date, target_sum, noise=1.0):
    i = np.arange(1, n + 1)
    shape = np.clip(RNG.lognormal(15.0, 1.2, n), 5_000_000, None)
    balances = rescale_to(shape, target_sum * noise)
    jenis = draw_jenis_nasabah(MIX_DEPOSITO, n)

    # Pick the tenor first, then place the start date INSIDE that tenor, so the
    # deposit is still live at the reporting date. Placing start date and tenor
    # independently (the old approach) left ~62% of the book already matured but
    # still carrying a full balance — data that is both unrealistic and good at
    # hiding real engine bugs.
    tenor_choice = RNG.choice([1, 3, 6, 12, 24], size=n, p=[0.35, 0.30, 0.20, 0.10, 0.05])
    tenor_days = (tenor_choice * 30).astype(int)
    elapsed = np.maximum(1, (tenor_days * RNG.uniform(0.02, 0.97, n)).astype(int))
    # Keep a thin overdue tail (~1.5%): deposits whose ARO has not been posted
    # yet. That happens in live data, and both engines must handle it.
    overdue = RNG.random(n) < 0.015
    start_days_ago = np.where(overdue, tenor_days + RNG.integers(1, 20, n), elapsed)

    tgl_mulai = pd.Timestamp(date) - pd.to_timedelta(start_days_ago, unit="D")
    tgl_jt = tgl_mulai + pd.to_timedelta(tenor_days, unit="D")

    # The customer relationship is older than the individual deposit — a
    # depositor who has banked here for years keeps rolling short tenors.
    # Without this the placement date would be read as the relationship date
    # and the whole term-deposit book would look like new money.
    hubungan_days = np.maximum(start_days_ago, RNG.integers(60, 15 * 365, n))
    tgl_hubungan = pd.Timestamp(date) - pd.to_timedelta(hubungan_days, unit="D")

    # Deposit pricing. Retail/UMK counter rates sit at or below the LPS
    # guarantee rate. Institutional depositors (Pemda, BUMD, instansi,
    # korporasi) often negotiate a special rate ABOVE it — which under LPS
    # rules leaves that deposit outside the guarantee. Interbank deposits are
    # priced off the money market.
    institutional = np.isin(jenis, ["Pemda", "BUMD", "Instansi/BLUD", "Korporasi"])
    special_rate = institutional & (RNG.random(n) < 0.60)
    bunga = np.select(
        [jenis == "Bank Lain", special_rate],
        [RNG.uniform(LPS_RATE_CEILING + 0.75, LPS_RATE_CEILING + 2.00, n),
         RNG.uniform(LPS_RATE_CEILING + 0.25, LPS_RATE_CEILING + 1.50, n)],
        default=RNG.uniform(2.25, LPS_RATE_CEILING, n)).round(2)

    # Deposits pledged in full as cash collateral for a loan (back-to-back).
    blocked_mask = (jenis != "Bank Lain") & (RNG.random(n) < 0.03)

    return pd.DataFrame({
        "idPelapor": BANK_ID,
        "periodeLaporan": "M",
        "periodeData": date,
        "nomorRekening": [acc("2012", x) for x in i],
        "idPihakLawan": [cif(CIF_BASE["deposito"] + x) for x in i],
        "jenisNasabah": jenis,
        "flagPayroll": False,
        "instansiPayroll": None,
        "statusDana": "X",
        "fiturTambahan": "T",
        "jenisValuta": "IDR",
        "klasifikasiLiabilitasKeuangan": np.nan,
        "lokasiKCKCP": 996,
        "jenisSukuBunga": np.nan,
        # A time deposit's rate is fixed for its tenor.
        "sukuBungaAwalKontrak": bunga,
        "sukuBungaBulanLaporan": bunga,
        "sukuBungaPenjaminanLps": LPS_RATE_CEILING,
        "tanggalMulai": tgl_mulai.strftime("%Y-%m-%d"),
        "tanggalMulaiHubungan": tgl_hubungan.strftime("%Y-%m-%d"),
        "tanggalJatuhTempo": tgl_jt.strftime("%Y-%m-%d"),
        "nominal": np.nan,
        "nominalDiblokir": np.where(blocked_mask, balances, 0.0).round(0),
        "alasanDiblokir": np.where(blocked_mask, "Jaminan Kredit", None),
        "jumlahBulanLalu": np.nan,
        "jumlahDebet": np.nan,
        "jumlahKredit": np.nan,
        "jumlahLainnya": np.nan,
        "jumlahBulanLaporan": balances.round(0),
    })


# ── Pinjaman / Kredit (was krp01) ────────────────────────────────────────────
LOAN_TYPES = ["KMK", "KI", "KPR", "KKB", "MULTIGUNA", "KREDIT_ASN"]
# KREDIT_ASN dominates a BPD's book: consumer loans to civil servants, repaid by
# salary deduction (potong gaji) through the payroll account the bank already
# holds. Long tenor (5-15y), materially lower NPL than KMK/KI.
LOAN_TYPE_WEIGHTS = [0.18, 0.12, 0.10, 0.07, 0.08, 0.45]

# Jenis penggunaan kredit bank konvensional: Modal Kerja / Investasi / Konsumsi.
# Numeric codes are this dummy's own — align them with the reference table of
# the Bank's actual reporting feed if it differs.
JENIS_PENGGUNAAN = {"KMK": 1, "KI": 2, "KPR": 3, "KKB": 3, "MULTIGUNA": 3, "KREDIT_ASN": 3}

# Contractual interest rate range (% p.a.) per product — dummy but ordered the
# way a BPD's pricing typically is: secured mortgages cheapest, unsecured
# consumer/multiguna dearest, potong-gaji ASN loans in between.
SUKU_BUNGA_RANGE = {"KMK": (9.0, 13.0), "KI": (9.5, 12.5), "KPR": (7.0, 10.5),
                    "KKB": (8.0, 11.0), "MULTIGUNA": (10.0, 14.0), "KREDIT_ASN": (8.5, 11.5)}

# Share of Mikro/Kecil KMK channelled as KUR (Kredit Usaha Rakyat) — a BPD is a
# KUR distribution channel for its region.
KUR_SHARE_MIKRO_KECIL = 0.40


def gen_pinjaman(n, date, target_sum, amort=1.0, payroll: pd.DataFrame | None = None):
    """Kredit book of a conventional BPD.

    Column names follow conventional terminology (jenisKredit, perjanjian
    kredit, suku bunga, tunggakan bunga). Sharia-only fields that the original
    sample carried — ijarah asset/lease fields, murabahah saldoHargaPokok,
    karakteristikSumberDana (mudharabah muqayyadah/mutlaqah split) — are not
    generated at all; they have no meaning for a conventional credit.

    Behaviour modelled per product:
      - KMK: revolving (rekening koran) — partially drawn, the undrawn part is
        a committed/uncommitted facility; a share of Mikro/Kecil is KUR.
      - KI: drawn in stages as the project progresses — mostly drawn.
      - KPR / KKB / MULTIGUNA / KREDIT_ASN: installment loans, fully disbursed
        at realisasi, amortising — outstanding below the original plafon and
        no undrawn headroom.
      - KREDIT_ASN: repaid by salary deduction; the "collateral" is the
        employee's SK, which is not a creditable agunan (nilai agunan 0).
        The borrower IS a payroll customer: `payroll` (the payroll rows of
        the Tabungan sheet) supplies their CIF and instansi, so the loan and
        the salary account it is deducted from share one idDebitur/CIF.
    """
    i = np.arange(1, n + 1)
    jenis_kredit = RNG.choice(LOAN_TYPES, size=n, p=LOAN_TYPE_WEIGHTS)
    is_asn = jenis_kredit == "KREDIT_ASN"
    is_kmk = jenis_kredit == "KMK"
    is_ki = jenis_kredit == "KI"
    is_installment = ~(is_kmk | is_ki)

    shape = np.clip(RNG.lognormal(14.5, 1.3, n), 5_000_000, None)
    jumlah = rescale_to(shape, target_sum * amort).round(0)

    # Facility limit vs outstanding. Only KMK (revolving) and KI (staged
    # drawdown) carry undrawn headroom; installment loans are disbursed in
    # full at realisasi, so their current limit equals the outstanding.
    draw_ratio = np.select([is_kmk, is_ki], [RNG.uniform(0.35, 0.98, n), RNG.uniform(0.70, 1.0, n)],
                           default=1.0)
    plafon = (jumlah / draw_ratio).round(0)
    undrawn = plafon - jumlah
    committed_share = RNG.uniform(0.6, 1.0, n)
    kelonggaran_committed = (undrawn * committed_share).round(0)
    kelonggaran_uncommitted = undrawn - kelonggaran_committed

    # Original plafon: installment loans have amortised since realisasi, so the
    # original amount sits above today's outstanding.
    sisa_pokok = RNG.uniform(0.30, 0.98, n)
    plafon_awal = np.where(is_installment, (jumlah / sisa_pokok).round(0), plafon)

    kualitas = RNG.choice([1, 2, 3, 4, 5], size=n, p=[0.90, 0.05, 0.02, 0.015, 0.015])
    kualitas_asn = RNG.choice([1, 2, 3, 4, 5], size=n, p=[0.975, 0.015, 0.004, 0.003, 0.003])
    kualitas = np.where(is_asn, kualitas_asn, kualitas)

    start_days_ago = RNG.integers(30, 2500, n)

    # Remaining days to maturity, drawn CONTINUOUSLY within one of six bands
    # (same weights/shape as before) rather than from six fixed values. A fixed
    # value put every matching loan on the exact same calendar day relative to
    # the reporting date — e.g. every 25-day loan matured on the same single
    # day — so the whole near-term half of the Survival Period ladder
    # (overnight .. b9_12bln) read as a single spike with every other bucket
    # sitting at exactly zero. Bands are aligned to the ladder's own bucket
    # edges (ilaap/config/time_buckets.yaml) so real coverage reaches every
    # near/medium-term bucket instead of just one.
    band_choice = RNG.choice(6, size=n, p=[0.10, 0.15, 0.20, 0.20, 0.20, 0.15])
    band_edges = [(1, 30), (30, 180), (180, 365), (365, 730), (730, 1095), (1095, 1825)]
    tenor_days = np.array([RNG.integers(lo, hi) for lo, hi in
                           (band_edges[b] for b in band_choice)])
    # 5-15 years remaining for KREDIT_ASN.
    tenor_days = np.where(is_asn, RNG.integers(5 * 365, 15 * 365, n), tenor_days)
    tgl_mulai = pd.Timestamp(date) - pd.to_timedelta(start_days_ago, unit="D")
    tgl_jt = pd.Timestamp(date) + pd.to_timedelta(tenor_days, unit="D")

    # Debtor segment: consumer loans are to individuals (Non UMKM); productive
    # loans (KMK/KI) skew to UMKM, as a regional development bank's do.
    kategori_usaha = np.where(
        is_installment, "Non UMKM",
        RNG.choice(["Mikro", "Kecil", "Menengah", "Non UMKM"], size=n, p=[0.35, 0.30, 0.20, 0.15]))
    is_kur = is_kmk & np.isin(kategori_usaha, ["Mikro", "Kecil"]) & (RNG.random(n) < KUR_SHARE_MIKRO_KECIL)

    # Interest rate per product (contractual rate; the current-month rate
    # drifts slightly from it for floating-rate facilities).
    lo = np.array([SUKU_BUNGA_RANGE[k][0] for k in jenis_kredit])
    hi = np.array([SUKU_BUNGA_RANGE[k][1] for k in jenis_kredit])
    bunga_awal = np.round(RNG.uniform(lo, hi), 2)
    bunga_kini = np.round(np.clip(bunga_awal + RNG.normal(0, 0.35, n), lo - 1, hi + 1), 2)
    # KUR carries the government-subsidised rate, well below commercial KMK.
    bunga_awal = np.where(is_kur, 6.0, bunga_awal)
    bunga_kini = np.where(is_kur, 6.0, bunga_kini)

    # Creditable collateral. KREDIT_ASN is backed by the employee's SK and the
    # salary-deduction arrangement, not by a creditable agunan.
    agunan_mult = np.select(
        [is_asn, jenis_kredit == "KPR", jenis_kredit == "KKB", jenis_kredit == "MULTIGUNA", is_kur],
        [0.0, RNG.uniform(1.2, 1.6, n), RNG.uniform(1.0, 1.3, n), RNG.uniform(0.0, 1.0, n),
         RNG.uniform(0.0, 0.5, n)],
        default=RNG.uniform(0.8, 1.5, n))

    # Debtor CIF. Non-ASN borrowers get their own CIF range; KREDIT_ASN
    # borrowers are drawn from the payroll accounts, carrying over the
    # instansi their salary is paid by.
    id_debitur = np.array([cif(CIF_BASE["debitur"] + x) for x in i], dtype=object)
    instansi = np.full(n, None, dtype=object)
    if payroll is not None and not payroll.empty:
        asn_idx = np.flatnonzero(is_asn)
        pick = RNG.choice(len(payroll), size=len(asn_idx), replace=len(asn_idx) > len(payroll))
        id_debitur[asn_idx] = payroll["idPihakLawan"].to_numpy()[pick]
        instansi[asn_idx] = payroll["instansiPayroll"].to_numpy()[pick]
    else:
        instansi = np.where(is_asn, RNG.choice(INSTANSI_PAYROLL, size=n), None)

    n_cols = {
        "idPelapor": BANK_ID, "periodeLaporan": "M", "periodeData": date,
        "nomorRekening": [acc("5010", x) for x in i],
        "idDebitur": id_debitur,
        "jenisKredit": jenis_kredit,
        "nomorPerjanjianKreditAwal": [f"PK{x:08d}" for x in i],
        "tanggalPerjanjianKreditAwal": tgl_mulai.strftime("%Y-%m-%d"),
        "nomorPerjanjianKreditAkhir": np.nan, "tanggalPerjanjianKreditAkhir": np.nan,
        "tanggalMulai": tgl_mulai.strftime("%Y-%m-%d"),
        "tanggalJatuhTempo": tgl_jt.strftime("%Y-%m-%d"),
        "kategoriUsahaDebitur": kategori_usaha,
        "kategoriPortofolio": 1,
        "sifatKredit": 1,
        "jenisPenggunaan": [JENIS_PENGGUNAAN[k] for k in jenis_kredit],
        "orientasiPenggunaan": 1,
        "jenisValuta": "IDR", "klasifikasiAsetKeuangan": np.nan,
        # KUR sector code left blank — fill from the Bank's own reference table.
        "kreditProgramPemerintah": is_kur.astype(int), "sektorKreditUsahaRakyat": np.nan,
        "sektorEkonomi": RNG.integers(1, 20, n), "lokasiPenggunaan": 996,
        # Salary-deduction link back to the payroll relationship the BPD holds.
        "flagPotongGaji": is_asn,
        "instansiPotongGaji": instansi,
        "jenisSukuBunga": np.where(is_kmk, 2, 1),  # 1 = tetap, 2 = mengambang
        "sukuBungaAwalKontrak": bunga_awal,
        "sukuBungaBulanLaporan": bunga_kini,
        "kualitas": kualitas,
        "plafonAwal": plafon_awal, "plafon": plafon,
        "bakiDebet": jumlah, "realisasiPencairanBulanBerjalan": 0,
        "pendapatanBungaYangAkanDiterima": 0,
        "jumlah": jumlah,
        "kelonggaranTarikCommitted": kelonggaran_committed,
        "kelonggaranTarikUncommitted": kelonggaran_uncommitted,
        "nilaiAgunanYangDapatDiperhitungkanKredit": np.round(jumlah * agunan_mult, 0),
        "nilaiAgunanYangDapatDiperhitungkanKelonggaranTarik": 0,
        "cadanganKerugianPenurunanNilaiAsetBaik": np.nan,
        "cadanganKerugianPenurunanNilaiAsetKurangBaik": np.nan,
        "cadanganKerugianPenurunanNilaiAsetTidakBaik": np.nan,
        "tunggakanPokok": np.where(kualitas >= 3, (jumlah * 0.05).round(0), 0),
        "tunggakanBunga": np.where(kualitas >= 3, (jumlah * bunga_kini / 100 / 12
                                                    * RNG.integers(3, 9, n)).round(0), 0),
        # Days past due consistent with the collectability grade: Lancar 0,
        # DPK 1-90, Kurang Lancar 91-120, Diragukan 121-180, Macet > 180.
        "jumlahHariTunggakan": np.select(
            [kualitas == 1, kualitas == 2, kualitas == 3, kualitas == 4],
            [0, RNG.integers(1, 91, n), RNG.integers(91, 121, n), RNG.integers(121, 181, n)],
            default=RNG.integers(181, 721, n)),
        "jumlahHariTunggakanPokok": np.nan,
    }
    return pd.DataFrame(n_cols)


# ── Agunan (was agn01) — kept for completeness, NOT used by the engine ──────
# Collateral type per credit product. KREDIT_ASN has none (backed by the SK and
# salary deduction), so it never appears here.
AGUNAN_BY_PRODUK = {
    "KPR":       (["Tanah dan Bangunan"], [1.0]),
    "KKB":       (["Kendaraan Bermotor"], [1.0]),
    "KMK":       (["Tanah dan Bangunan", "Persediaan/Piutang Usaha", "Deposito/Tabungan (Cash Collateral)"],
                  [0.55, 0.30, 0.15]),
    "KI":        (["Tanah dan Bangunan", "Mesin dan Peralatan"], [0.60, 0.40]),
    "MULTIGUNA": (["Tanah dan Bangunan", "Kendaraan Bermotor"], [0.70, 0.30]),
}
PENGIKATAN_BY_AGUNAN = {
    "Tanah dan Bangunan": "Hak Tanggungan",
    "Kendaraan Bermotor": "Fidusia",
    "Mesin dan Peralatan": "Fidusia",
    "Persediaan/Piutang Usaha": "Fidusia",
    "Deposito/Tabungan (Cash Collateral)": "Gadai",
}


def gen_agunan(df_pin: pd.DataFrame, date):
    """One collateral record per loan that carries creditable collateral,
    linked by nomorRekening. `nilaiAgunan` is the appraisal value; the loan's
    nilaiAgunanYangDapatDiperhitungkanKredit is that value after haircut, so
    the appraisal always sits above it."""
    loans = df_pin[df_pin["nilaiAgunanYangDapatDiperhitungkanKredit"] > 0]
    jenis = [RNG.choice(AGUNAN_BY_PRODUK[k][0], p=AGUNAN_BY_PRODUK[k][1])
             for k in loans["jenisKredit"]]
    haircut_kept = RNG.uniform(0.50, 0.80, len(loans))
    nilai = (loans["nilaiAgunanYangDapatDiperhitungkanKredit"].to_numpy() / haircut_kept).round(0)
    return pd.DataFrame({
        "idPelapor": BANK_ID,
        "periodeLaporan": "M",
        "periodeData": date,
        "noAgunan": [f"AG{x:09d}" for x in range(1, len(loans) + 1)],
        "nomorRekening": loans["nomorRekening"].to_numpy(),
        "idDebitur": loans["idDebitur"].to_numpy(),
        "jenisAgunan": jenis,
        "nilaiAgunan": nilai.astype(np.int64),
        # Binding instrument follows the collateral type; a small share is
        # still in process (e.g. APHT not yet registered).
        "jenisPengikatan": np.where(
            RNG.random(len(loans)) < 0.08, "Dalam Proses Pengikatan",
            [PENGIKATAN_BY_AGUNAN[j] for j in jenis]),
    })


# ── SBI — Sertifikat Bank Indonesia (was sym01 / SUKBI) ─────────────────────
# Share of the SBI portfolio pledged as collateral. Pledged paper is excluded
# from HQLA (lcr_engine.hqla_calc) and carries RSF (nsfr_engine.rsf_calc), so it
# is kept deliberately modest and stable rather than left to chance.
SBI_ENCUMBERED_TARGET_SHARE = 0.15
def gen_sbi(date, total_target, n=6):
    cuts = np.concatenate([[0.0], np.sort(RNG.uniform(0, total_target, n - 1)), [total_target]])
    nominal = np.diff(cuts)
    nominal = np.round(np.clip(nominal, 5_000_000_000, None))

    # Pledge a controlled share of the book (repo/collateral), smallest lots
    # first, until the target share is covered. Drawing "Ya" independently per
    # security — the previous approach — has enormous variance over only ~6
    # lots: one run pledged the entire portfolio, which zeroes HQLA and pushes
    # the LCR into breach for no economic reason.
    diagunkan = np.array(["Tidak"] * n, dtype=object)
    budget = nominal.sum() * SBI_ENCUMBERED_TARGET_SHARE
    for idx in np.argsort(nominal):
        if nominal[idx] > budget:
            break
        diagunkan[idx] = "Ya"
        budget -= nominal[idx]
    tgl_terbit = pd.Timestamp(date) - pd.to_timedelta(RNG.integers(10, 80, n), unit="D")
    tgl_jt = pd.Timestamp(date) + pd.to_timedelta(RNG.integers(5, 90, n), unit="D")
    return pd.DataFrame({
        "idPelapor": BANK_ID, "periodeLaporan": "M", "periodeData": date,
        "nomorRekening": [f"SBI{x:07d}" for x in range(1, n + 1)],
        "nomorSuratBerharga": [f"SBI-{date.replace('-','')}-{x:03d}" for x in range(1, n + 1)],
        "jenisSuratBerharga": "SBI",
        "statusRegistrasi": 2, "fiturTambahan": "T", "statusSuratBerharga": 9,
        "jenisValuta": "IDR", "idPenerbit": 1, "jenisPenawaran": 2, "kategoriPortofolio": 10,
        "lembagaPemeringkat": np.nan, "peringkat": np.nan, "tanggalPemeringkatan": np.nan,
        "klasifikasiAsetKeuangan": "AC",
        "tanggalPenerbitan": tgl_terbit.strftime("%Y-%m-%d"),
        "tanggalPencatatan": tgl_terbit.strftime("%Y-%m-%d"),
        "tanggalJatuhTempo": tgl_jt.strftime("%Y-%m-%d"),
        "kualitas": 1,
        "periodePembayaranBunga": "X",
        "sukuBungaAwalKontrak": np.round(RNG.uniform(4.5, 6.5, n), 2),
        "sukuBungaBulanLaporan": np.round(RNG.uniform(4.5, 6.5, n), 2),
        "jenisSukuBunga": np.nan,
        "nominal": nominal.astype(np.int64),
        "hargaPerolehan": 0, "premiumDiskonto": 0,
        "jumlahBulanLalu": np.nan, "jumlahDebet": np.nan, "jumlahKredit": np.nan, "jumlahLainnya": np.nan,
        "jumlahBulanLaporan": nominal.astype(np.int64),
        "pendapatanBungaYangAkanDiterima": 0,
        "cadanganKerugianPenurunanNilaiAsetBaik": 0,
        "cadanganKerugianPenurunanNilaiAsetKurangBaik": np.nan,
        "cadanganKerugianPenurunanNilaiAsetTidakBaik": np.nan,
        "SedangDiagunkan": diagunkan,
    })


# ── Kewajiban GWM/PLM (for ilaap/available_hqla.py, Modul 1 ILAAP) ──────────
# PLM_RATE_ASSUMPTION is a PLACEHOLDER for demo/testing purposes only — the
# real Penyangga Likuiditas Makroprudensial ratio is a Bank Indonesia
# regulation that must be confirmed against the bank's actual PLM obligation
# before production use (see docs/SPEK_MODUL_ILAAP.md §4.3, §12 item 2).
PLM_RATE_ASSUMPTION = 0.03


def gen_kewajiban_gwm_plm(date, dpk_total, bi_sourced_liquidity):
    gwm = round(dpk_total * 0.035)
    plm = round(dpk_total * PLM_RATE_ASSUMPTION)
    return pd.DataFrame([
        ("KEWAJIBAN GWM (informasi — sudah dikurangi di Giro BI, tidak dipakai ulang di Available HQLA)", gwm),
        ("KEWAJIBAN PLM (Penyangga Likuiditas Makroprudensial, asumsi 3% x DPK — PLACEHOLDER, konfirmasi ke Bank/BI)", plm),
        ("SUMBER LIKUIDITAS DARI BANK SENTRAL (mis. repo/FTK BI, dari NeracaHarian LIABILITAS KEPADA BANK INDONESIA)", bi_sourced_liquidity),
    ], columns=["KETERANGAN", "NILAI"])


# ── Penempatan BI (was pbi01) ────────────────────────────────────────────────
# jenisPenempatan codes are read by lcr_engine.hqla_calc / nsfr_engine.rsf_calc:
#   F08 — Deposit Facility (BI's conventional overnight standing facility; this
#         row was FASBIS, its sharia counterpart, in the original sample)
#   F09 — Giro Rupiah di Bank Indonesia (demand balance, no maturity)
def gen_penempatan_bi(date, deposit_facility, giro_bi):
    overnight = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "idPelapor": BANK_ID, "periodeLaporan": "M", "periodeData": date,
        "idData": [50301, 50302],
        "jenisPenempatan": ["F08", "F09"],
        "keteranganPenempatan": ["Deposit Facility", "Giro Rupiah di Bank Indonesia"],
        "jenisValuta": "IDR",
        "tanggalMulai": date,
        "tanggalJatuhTempo": [overnight, np.nan],
        "sukuBunga": [DEPOSIT_FACILITY_RATE_ASSUMPTION, 0.0],
        "jumlah": [int(deposit_facility), int(giro_bi)],
    })


# ── Neraca Harian (was nrc01) ────────────────────────────────────────────────
def gen_neraca(date, agg):
    """agg: dict with cross-file aggregate figures used to keep the balance
    sheet internally consistent with the detail files generated above.

    NOTE — labels read by exact/substring match in lcr_engine.py /
    nsfr_engine.py / src/ilaap/data_contract.py. Renaming any of these here
    REQUIRES the matching change in those files, or the affected figure
    silently collapses to zero:
      ASET      — 'KAS', 'PENEMPATAN PADA BANK LAIN',
                  'ASET TETAP DAN INVENTARIS', 'SURAT BERHARGA YANG DIMILIKI',
                  'SBI'  (was 'SUKUK BI' — renamed for the conventional BPD
                  profile; nsfr_engine.rsf_calc() matches the new spelling)
      RANGKUMAN — 'DPK (GIRO+TAB+DEPO)'
      RKA       — 'FASILITAS KREDIT YANG BELUM DITARIK' (was 'FASILITAS
                  PEMBIAYAAN ...') and 'GARANSI YANG DIBERIKAN'. Note both
                  the TAGIHAN and the KEWAJIBAN side of the RKA carry a row
                  with these names; the engines scope their match to the
                  KEWAJIBAN section, so keep the section header rows
                  ('KEWAJIBAN KOMITMEN' / 'KEWAJIBAN KONTINJENSI') intact.

    The OJK Excel export templates (generate_report_excel /
    generate_nsfr_report_excel) still map to the old template layout and were
    deliberately NOT touched by this revision.

    Consistency with the detail files:
      - Kredit breakdown (modal kerja / investasi / konsumsi) is summed from
        the Pinjaman sheet by jenisPenggunaan, not a fixed split.
      - Deposits placed by other banks sit in the Giro/Deposito detail (the
        engines rate them as Bank/FI funding) but are presented on the balance
        sheet under LIABILITAS KEPADA BANK LAIN, and excluded from DPK.
      - The balance sheet balances: equity carries the Pemda shareholders'
        paid-in capital instead of a zero equity plugged by antar-kantor.
      - LABA RUGI is year-to-date interest computed from the rates in the
        detail files.
    """
    kas = agg["kas"]
    deposit_facility = agg["deposit_facility"]
    giro_bi_total = agg["giro_bi_total"]          # F09 total (BI current account)
    giro_bi_split = round(giro_bi_total * 0.77)   # GIRO line
    giro_bi_fast = giro_bi_total - giro_bi_split  # GIRO BI FAST (prefunding) line
    penempatan_bi_sub = deposit_facility + giro_bi_total

    interbank_giro = agg["interbank_giro"]
    interbank_tab = 0
    interbank_depo = agg["interbank_depo"]
    penempatan_bank_lain = interbank_giro + interbank_tab + interbank_depo

    total_sb = agg["sbi_total"]        # matches SBI file total nominal
    sbi_line = total_sb                # entire securities book is SBI in this dummy

    kredit_total = agg["kredit_total"]
    aset_tetap = agg["aset_tetap"]
    aset_lainnya = agg["aset_lainnya"]
    ckpn = -kredit_total * 0.012

    aset_rows = [
        ("KAS", kas),
        ("PENEMPATAN PADA BANK INDONESIA", penempatan_bi_sub),
        ("GIRO", giro_bi_split),
        ("DEPOSIT FACILITY", deposit_facility),
        ("GIRO BI FAST", giro_bi_fast),
        ("PENEMPATAN PADA BANK LAIN", penempatan_bank_lain),
        ("GIRO", interbank_giro),
        ("TABUNGAN", interbank_tab),
        ("DEPOSITO", interbank_depo),
        ("SURAT-SURAT BERHARGA YANG DIBELI DGN JANJI DIJUAL KEMBALI (REVERSE REPO)", 0),
        ("TAGIHAN SPOT DAN DERIVATIF/FORWARD", 0),
        ("SURAT BERHARGA YANG DIMILIKI", total_sb),
        ("SBI", sbi_line),  # engine-matched label — see docstring before renaming
        ("OBLIGASI KORPORASI", 0),
        ("TAGIHAN AKSEPTASI", 0),
        ("KREDIT YANG DIBERIKAN :", kredit_total),
        ("-  KREDIT MODAL KERJA", agg["kredit_mk"]),
        ("-  KREDIT INVESTASI", agg["kredit_i"]),
        ("-  KREDIT KONSUMSI", agg["kredit_k"]),
        ("PENYERTAAN MODAL", 0),
        ("ASET KEUANGAN LAINNYA", round(kredit_total * 0.002)),
        ("CADANGAN KERUGIAN PENURUNAN NILAI ASET PRODUKTIF -/-", round(ckpn)),
        ("ASET TIDAK BERWUJUD", 0),
        ("AKUMULASI AMORTISASI -/- ASET TDK BERWUJUD", 0),
        ("ASET TETAP DAN INVENTARIS", aset_tetap),
        ("AKUMULASI PENYUSUTAN ASET TETAP DAN INVENTARIS -/-", round(-aset_tetap * 0.58)),
        ("PROPERTI TERBENGKALAI", 0),
        ("AGUNAN YANG DIAMBIL ALIH", round(kredit_total * 0.004)),
        ("REKENING TUNDA", 0),
        ("ASET ANTAR KANTOR", 0),
        ("PERSEDIAAN", 0),
        ("ASET LAINNYA", aset_lainnya),
    ]
    sub_items = ("-  KREDIT MODAL KERJA", "-  KREDIT INVESTASI", "-  KREDIT KONSUMSI",
                 "GIRO BI FAST", "DEPOSIT FACILITY", "GIRO", "TABUNGAN", "DEPOSITO", "SBI")
    total_aset = round(sum(v for k, v in aset_rows if k not in sub_items))
    aset_rows.append(("TOTAL ASET", total_aset))
    df_aset = pd.DataFrame([(k, round(v)) for k, v in aset_rows], columns=["KETERANGAN", "REALISASI"])

    # ── Laba rugi, year to date ──────────────────────────────────────────────
    ytd = pd.Timestamp(date).month / 12
    bunga_kredit = round(agg["bunga_kredit_setahun"] * ytd)
    bunga_bi = round(deposit_facility * DEPOSIT_FACILITY_RATE_ASSUMPTION / 100 * ytd)
    bunga_bank_lain = round(penempatan_bank_lain * 0.04 * ytd)
    bunga_sb = round(agg["bunga_sbi_setahun"] * ytd)
    pendapatan_bunga = bunga_kredit + bunga_bi + bunga_bank_lain + bunga_sb
    beban_bunga = round(agg["bunga_dana_setahun"] * ytd)
    # Operating cost, provisions and tax taken as a flat share of net interest
    # income — a dummy simplification, not a modelled cost base.
    laba_bersih = round((pendapatan_bunga - beban_bunga) * 0.35)

    df_laba = pd.DataFrame([
        ("PENDAPATAN BUNGA :", pendapatan_bunga),
        ("-  DARI PENEMPATAN PADA BANK INDONESIA", bunga_bi),
        ("-  DARI PENEMPATAN PADA BANK LAIN", bunga_bank_lain),
        ("-  DARI SURAT BERHARGA", bunga_sb),
        ("-  DARI KREDIT YANG DIBERIKAN", bunga_kredit),
        ("BEBAN BUNGA", beban_bunga),
        ("PENDAPATAN BUNGA BERSIH", pendapatan_bunga - beban_bunga),
        ("LABA BERSIH", laba_bersih),
    ], columns=["KETERANGAN", "REALISASI"])

    # ── Liabilitas & ekuitas ─────────────────────────────────────────────────
    antar_bank = round(kredit_total * 0.010)          # interbank call money borrowed
    liab_bank_lain = antar_bank + agg["dana_bank_lain"]
    # Small: a BPD funds itself overwhelmingly from DPK (Pemda, ASN payroll).
    pinjaman_diterima = round(kredit_total * 0.01)
    liab_lainnya = round(kredit_total * 0.003)
    total_liab = (agg["giro_dpk"] + agg["tabungan_dpk"] + agg["deposito_dpk"]
                  + liab_bank_lain + pinjaman_diterima + liab_lainnya)

    # Equity. A BPD's capital is paid in by its Pemprov/Pemkab shareholders;
    # it is the balancing item here, so the balance sheet actually balances.
    cadangan = round(total_aset * 0.02)
    modal_disetor = total_aset - total_liab - cadangan - laba_bersih
    if modal_disetor <= 0:
        raise ValueError(f"Dummy balance sheet has no room for paid-in capital "
                         f"(modal disetor {modal_disetor:,.0f}) — revisit the targets in build_period().")
    total_ekuitas = modal_disetor + cadangan + laba_bersih

    liab_rows = [
        ("SIMPANAN GIRO :", agg["giro_dpk"]),
        ("-  GIRO", agg["giro_dpk"]),
        ("SIMPANAN TABUNGAN :", agg["tabungan_dpk"]),
        ("-  TABUNGAN", agg["tabungan_dpk"]),
        ("SIMPANAN BERJANGKA (DEPOSITO) :", agg["deposito_dpk"]),
        ("-  DEPOSITO", agg["deposito_dpk"]),
        ("UANG ELEKTRONIK", 0),
        ("LIABILITAS KEPADA BANK INDONESIA", 0),
        ("LIABILITAS KEPADA BANK LAIN", liab_bank_lain),
        ("LIABILITAS SPOT DAN FORWARD", 0),
        ("LIABILITAS AKSEPTASI", 0),
        ("SURAT BERHARGA DITERBITKAN", 0),
        ("PINJAMAN YANG DITERIMA", pinjaman_diterima),
        ("SETORAN JAMINAN", 0),
        ("LIABILITAS ANTAR KANTOR", 0),  # consolidated report — nets to zero
        ("LIABILITAS LAINNYA", liab_lainnya),
        ("TOTAL LIABILITAS", total_liab),
        ("MODAL DISETOR", modal_disetor),
        ("TAMBAHAN MODAL DISETOR", 0),
        ("PENGHASILAN KOMPREHENSIF LAINNYA", 0),
        ("CADANGAN", cadangan),
        ("LABA/RUGI", laba_bersih),
        ("-  TAHUN-TAHUN LALU", 0),
        ("-  TAHUN BERJALAN", laba_bersih),
        ("-  DEVIDEN YANG DIBAYARKAN", 0),
        ("TOTAL EKUITAS", total_ekuitas),
        ("TOTAL LIABILITAS DAN EKUITAS", total_liab + total_ekuitas),
    ]
    df_liab = pd.DataFrame(liab_rows, columns=["KETERANGAN", "REALISASI"])

    # Committed undrawn credit facilities — summed from the Pinjaman sheet
    # (kelonggaranTarikCommitted) so the RKA the LCR reads agrees with the
    # loan-level detail, instead of a free-standing % of the loan book.
    komitmen_belum_ditarik = agg["undrawn_committed"]
    garansi = kredit_total * 0.0015
    df_rka = pd.DataFrame([
        ("TAGIHAN KOMITMEN", np.nan),
        ("FASILITAS KREDIT YANG BELUM DITARIK", 0.0),
        ("POSISI VALAS YANG AKAN DITERIMA DARI TRANSAKSI SPOT DAN", 0.0),
        ("LAINNYA", 0.0),
        ("TAGIHAN KONTINJENSI", np.nan),
        ("GARANSI YANG DITERIMA", 0.0),
        # Interest accrued but not collected on non-performing credit.
        ("PENDAPATAN BUNGA DALAM PENYELESAIAN", round(agg["npl_total"] * 0.05)),
        ("LAINNYA", round(kredit_total * 0.001)),
        ("KEWAJIBAN KOMITMEN", np.nan),
        ("FASILITAS KREDIT YANG BELUM DITARIK", round(komitmen_belum_ditarik)),  # engine regex-matched — see docstring
        ("IRREVOCABLE L/C YANG MASIH BERJALAN", 0.0),
        ("POSISI VALAS YANG AKAN DISERAHKAN DARI TRANSAKSI SPOT DAN", 0.0),
        ("LAINNYA", 0.0),
        ("KEWAJIBAN KONTINJENSI", np.nan),
        ("GARANSI YANG DIBERIKAN", round(garansi)),  # engine regex-matched, kept verbatim
        ("LAINNYA", 0.0),
    ], columns=["KETERANGAN", "NILAI"])

    dpk_total = agg["dpk_total"]
    df_rangkuman = pd.DataFrame([
        ("KREDIT", kredit_total),
        ("DPK (GIRO+TAB+DEPO+MTN non Bank)", dpk_total),
        ("DPK (GIRO+TAB+DEPO)", dpk_total),  # engine-hardcoded label — kept verbatim
        ("LDR", round(kredit_total / dpk_total, 4)),
        ("TOTAL PENDAPATAN", pendapatan_bunga),
        ("TOTAL BEBAN", beban_bunga),
        ("LABA", laba_bersih),
    ], columns=["KETERANGAN", "REALISASI"])

    return {
        "ASET": df_aset, "LIABILITAS": df_liab, "LABA RUGI": df_laba,
        "RKA": df_rka, "RANGKUMAN": df_rangkuman,
    }


def _annual_interest(balance, rate_pct) -> float:
    return float((pd.Series(balance).fillna(0) * pd.Series(rate_pct).fillna(0) / 100).sum())


def build_period(date, is_current):
    noise_deposit = 1.0 if is_current else RNG.uniform(0.94, 0.99)
    amort = 1.0 if is_current else 1.03  # loans were slightly higher a month earlier

    # Sized so the balance sheet leaves a BPD-like equity cushion (~12-15% of
    # assets) once DPK, borrowings and the asset side are all accounted for.
    df_tab = gen_tabungan(3000, date, 235_000_000_000, noise_deposit)
    # gen_giro's target is the NON-Pemda giro book; the RKUD block is added on
    # top of it and swings with the APBD cycle, so the giro total is seasonal.
    df_gir = gen_giro(600, date, 200_000_000_000, noise_deposit)
    df_dep = gen_deposito(1200, date, 215_000_000_000, noise_deposit)
    payroll = df_tab.loc[df_tab["flagPayroll"], ["idPihakLawan", "instansiPayroll"]]
    df_pin = gen_pinjaman(2500, date, 620_000_000_000, amort, payroll=payroll)
    df_agn = gen_agunan(df_pin, date)

    kredit_total = df_pin["jumlah"].sum()
    by_use = df_pin.groupby("jenisPenggunaan")["jumlah"].sum()
    npl_total = df_pin.loc[df_pin["kualitas"] >= 3, "jumlah"].sum()
    undrawn_committed = df_pin["kelonggaranTarikCommitted"].sum()

    # Funds placed by other banks are not DPK (see gen_neraca docstring).
    def split_bank(df):
        bank = df["jenisNasabah"].eq("Bank Lain")
        return df.loc[~bank, "jumlahBulanLaporan"].sum(), df.loc[bank, "jumlahBulanLaporan"].sum()
    tabungan_dpk, tabungan_bank = split_bank(df_tab)
    giro_dpk, giro_bank = split_bank(df_gir)
    deposito_dpk, deposito_bank = split_bank(df_dep)
    dpk_total = tabungan_dpk + giro_dpk + deposito_dpk

    sbi_total_target = 70_000_000_000 * noise_deposit
    df_sbi = gen_sbi(date, sbi_total_target)
    sbi_total = df_sbi["nominal"].sum()

    deposit_facility = round(35_000_000_000 * noise_deposit)
    giro_bi_total = round(20_000_000_000 * noise_deposit)
    df_pbi = gen_penempatan_bi(date, deposit_facility, giro_bi_total)

    agg = {
        "kas": round(12_000_000_000 * noise_deposit),
        "deposit_facility": deposit_facility,
        "giro_bi_total": giro_bi_total,
        "interbank_giro": round(8_000_000_000 * noise_deposit),
        "interbank_depo": round(6_000_000_000 * noise_deposit),
        "sbi_total": int(sbi_total),
        "kredit_total": int(kredit_total),
        "kredit_mk": int(by_use.get(1, 0)),
        "kredit_i": int(by_use.get(2, 0)),
        "kredit_k": int(by_use.get(3, 0)),
        "undrawn_committed": int(undrawn_committed),
        "npl_total": int(npl_total),
        "tabungan_dpk": int(tabungan_dpk),
        "giro_dpk": int(giro_dpk),
        "deposito_dpk": int(deposito_dpk),
        "dana_bank_lain": int(tabungan_bank + giro_bank + deposito_bank),
        "dpk_total": int(dpk_total),
        # A BPD runs a branch network across its province — fixed assets are
        # a larger share of the balance sheet than at a single-office bank.
        "aset_tetap": round(50_000_000_000 * noise_deposit),
        "aset_lainnya": round(10_000_000_000 * noise_deposit),
        "bunga_kredit_setahun": _annual_interest(df_pin["jumlah"], df_pin["sukuBungaBulanLaporan"]),
        "bunga_sbi_setahun": _annual_interest(df_sbi["nominal"], df_sbi["sukuBungaBulanLaporan"]),
        "bunga_dana_setahun": sum(_annual_interest(d["jumlahBulanLaporan"], d["sukuBungaBulanLaporan"])
                                  for d in (df_tab, df_gir, df_dep)),
    }
    df_neraca = gen_neraca(date, agg)

    bi_sourced_liquidity = 0  # matches "LIABILITAS KEPADA BANK INDONESIA" row in gen_neraca (always 0 in this dummy)
    df_gwm_plm = gen_kewajiban_gwm_plm(date, dpk_total, bi_sourced_liquidity)

    save(df_neraca, "NeracaHarian", date)
    save(df_pbi, "PenempatanBI", date)
    save(df_sbi, "SBI", date)
    save(df_tab, "Tabungan", date)
    save(df_gir, "Giro", date)
    save(df_dep, "Deposito", date)
    save(df_pin, "Pinjaman", date)
    save(df_agn, "Agunan", date)
    save(df_gwm_plm, "KewajibanGWMPLM", date)


if __name__ == "__main__":
    build_period(DATE_PREV, is_current=False)
    build_period(DATE_CUR, is_current=True)
    print("done")
