"""
Generate synthetic dummy source files for a CONVENTIONAL bank scenario,
matching the schema the LCR/NSFR engines expect, for two reporting dates
so results can be compared month-over-month.

All data is 100% synthetic (no real customer data). Output goes to
database/dummy/ so any real sample files kept locally in database/ are
left untouched.

Run from the project root:
    python scripts/generate_dummy_data.py
"""
import pathlib
import numpy as np
import pandas as pd

RNG = np.random.default_rng(20250923)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "database" / "dummy"
OUT_DIR.mkdir(parents=True, exist_ok=True)

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


# ── Tabungan (was tab01) ───────────────────────────────────────────────────
def gen_tabungan(n, date, target_sum, noise=1.0):
    i = np.arange(1, n + 1)
    shape = np.clip(RNG.lognormal(13.0, 1.4, n), 50_000, None)
    balances = rescale_to(shape, target_sum * noise)
    blocked_mask = RNG.random(n) < 0.03
    blocked = np.where(blocked_mask, balances * RNG.uniform(0.05, 0.3, n), 0.0)
    open_days = RNG.integers(60, 3600, n)
    return pd.DataFrame({
        "idPelapor": BANK_ID,
        "periodeLaporan": "M",
        "periodeData": date,
        "nomorRekening": [acc("2010", x) for x in i],
        "jumlahRekening": 1,
        "idPihakLawan": [cif(x) for x in i],
        "statusDana": "S",
        "fiturTambahan": where_obj(RNG.random(n) < 0.25, "T"),
        "jenisAkad": 10.0,
        "jenisValuta": "IDR",
        "klasifikasiLiabilitasKeuangan": np.nan,
        "lokasiKCKCP": 996,
        "jenisSukuBunga": np.nan,
        "sukuBungaPersentaseImbalanBulanLaporan": np.round(RNG.uniform(0.5, 2.75, n), 2),
        "persentaseImbalanAwalKontrak": np.round(RNG.uniform(0.5, 2.75, n), 2),
        "metodeBagiHasil": np.nan,
        "persentaseNisbah": np.nan,
        "tanggalMulai": (pd.Timestamp(date) - pd.to_timedelta(open_days, unit="D")).strftime("%Y-%m-%d"),
        "tanggalJatuhTempo": np.nan,
        "nominal": np.nan,
        "nominalDiblokir": blocked.round(0),
        "alasanDiblokir": where_obj(blocked_mask, "Blokir Pengadilan"),
        "jumlahBulanLalu": np.nan,
        "jumlahDebet": np.nan,
        "jumlahKredit": np.nan,
        "jumlahLainnya": np.nan,
        "jumlahBulanLaporan": balances.round(0),
    })


# ── Giro (was gir01) ────────────────────────────────────────────────────────
def gen_giro(n, date, target_sum, noise=1.0):
    i = np.arange(1, n + 1)
    # giro skews to larger corporate/business balances than tabungan
    shape = np.clip(RNG.lognormal(14.5, 2.0, n), 500_000, None)
    balances = rescale_to(shape, target_sum * noise)
    open_days = RNG.integers(30, 6000, n)
    return pd.DataFrame({
        "idPelapor": BANK_ID,
        "periodeLaporan": "M",
        "periodeData": date,
        "nomorRekening": [acc("2011", x) for x in i],
        "jumlahRekening": 1,
        "idPihakLawan": [cif(x) for x in i],
        "statusDana": "S",
        "jenisAkad": 10,
        "jenisValuta": "IDR",
        "klasifikasiLiabilitasKeuangan": np.nan,
        "lokasiKCKCP": 996,
        "jenisSukuBunga": np.nan,
        "persentaseImbalanAwalKontrak": np.nan,
        "sukuBungaPersentaseImbalanBulanLaporan": np.round(RNG.uniform(0.0, 1.0, n), 2),
        "metodeBagiHasil": np.nan,
        "persentaseNisbah": np.nan,
        "tanggalMulai": (pd.Timestamp(date) - pd.to_timedelta(open_days, unit="D")).strftime("%Y-%m-%d"),
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
    start_days_ago = RNG.integers(1, 350, n)
    tenor_choice = RNG.choice([1, 3, 6, 12, 24], size=n, p=[0.35, 0.30, 0.20, 0.10, 0.05])
    tenor_days = (tenor_choice * 30).astype(int)
    tgl_mulai = pd.Timestamp(date) - pd.to_timedelta(start_days_ago, unit="D")
    tgl_jt = tgl_mulai + pd.to_timedelta(tenor_days, unit="D")
    return pd.DataFrame({
        "idPelapor": BANK_ID,
        "periodeLaporan": "M",
        "periodeData": date,
        "nomorRekening": [acc("2012", x) for x in i],
        "idPihakLawan": [cif(x) for x in i],
        "statusDana": "X",
        "fiturTambahan": "T",
        "jenisValuta": "IDR",
        "klasifikasiLiabilitasKeuangan": np.nan,
        "lokasiKCKCP": 996,
        "jenisSukuBunga": np.nan,
        "persentaseImbalanAwalKontrak": np.round(RNG.uniform(2.5, 6.0, n), 2),
        "sukuBungaPersentaseImbalanBulanLaporan": np.round(RNG.uniform(2.5, 6.0, n), 2),
        "sukuBungaPenjaminanLps": np.round(RNG.uniform(2.0, 4.25, n), 2),
        "metodeBagiHasil": np.nan,
        "persentaseNisbah": np.nan,
        "tanggalMulai": tgl_mulai.strftime("%Y-%m-%d"),
        "tanggalJatuhTempo": tgl_jt.strftime("%Y-%m-%d"),
        "nominal": np.nan,
        "nominalDiblokir": 0,
        "alasanDiblokir": np.nan,
        "jumlahBulanLalu": np.nan,
        "jumlahDebet": np.nan,
        "jumlahKredit": np.nan,
        "jumlahLainnya": np.nan,
        "jumlahBulanLaporan": balances.round(0),
    })


# ── Pinjaman / Kredit (was krp01) ────────────────────────────────────────────
LOAN_TYPES = ["KMK", "KI", "KPR", "KKB", "MULTIGUNA"]


def gen_pinjaman(n, date, target_sum, amort=1.0):
    i = np.arange(1, n + 1)
    shape = np.clip(RNG.lognormal(14.5, 1.3, n), 5_000_000, None)
    draw_ratio = RNG.uniform(0.35, 0.98, n)
    jumlah = rescale_to(shape, target_sum * amort)
    plafon = (jumlah / draw_ratio).round(0)
    jumlah = jumlah.round(0)
    kualitas = RNG.choice([1, 2, 3, 4, 5], size=n, p=[0.90, 0.05, 0.02, 0.015, 0.015])
    start_days_ago = RNG.integers(30, 2500, n)
    tenor_days = RNG.choice([25, 90, 270, 400, 900, 1800], size=n,
                            p=[0.10, 0.15, 0.20, 0.20, 0.20, 0.15])
    tgl_mulai = pd.Timestamp(date) - pd.to_timedelta(start_days_ago, unit="D")
    tgl_jt = pd.Timestamp(date) + pd.to_timedelta(tenor_days, unit="D")
    n_cols = {
        "idPelapor": BANK_ID, "periodeLaporan": "M", "periodeData": date,
        "nomorRekening": [acc("5010", x) for x in i],
        "idDebitur": [10_000_000 + x for x in i],
        "jenisKreditPembiayaan": RNG.choice(LOAN_TYPES, size=n),
        "nomorAkadAwal": [f"PK{x:08d}" for x in i],
        "tanggalAkadAwal": tgl_mulai.strftime("%Y-%m-%d"),
        "nomorAkadAkhir": np.nan, "tanggalAkadAkhir": np.nan,
        "tanggalAwal": tgl_mulai.strftime("%Y-%m-%d"),
        "tanggalMulai": tgl_mulai.strftime("%Y-%m-%d"),
        "tanggalJatuhTempo": tgl_jt.strftime("%Y-%m-%d"),
        "kategoriUsahaDebitur": RNG.choice(["Mikro", "Kecil", "Menengah", "Non UMKM"], size=n),
        "kategoriPortofolio": 1,
        "skimPembiayaanSyariah": np.nan,
        "jenisAkad": 0,
        "karakteristikSumberDana": "NMT",
        "sifatInvestasi": np.nan, "metodeBagiHasil": np.nan,
        "persentaseNisbah": np.nan, "persentaseRBHterhadapPBH": np.nan,
        "sifatKreditPembiayaan": 1, "jenisPenggunaan": 1, "orientasiPenggunaan": 1,
        "jenisValuta": "IDR", "klasifikasiAsetKeuangan": np.nan,
        "kreditProgramPemerintah": 0, "sektorKreditUsahaRakyat": np.nan,
        "sektorEkonomi": RNG.integers(1, 20, n), "lokasiPenggunaan": 996,
        "jenisAset": np.nan, "waktuPerolehanAset": np.nan, "jenisValutaAset": np.nan,
        "hargaPerolehanAset": np.nan, "jumlahPeriodePenyusutanAmortisasi": np.nan,
        "metodePenyusutanAmortisasi": np.nan, "nilaiKontrak": 0,
        "periodePembayaranSewa": np.nan, "nilaiSewaPerPeriode": np.nan,
        "akumulasiPenyusutanAmortisasi": np.nan, "ckpnAsetIjarah": np.nan,
        "uangMukaIjarah": np.nan, "jenisSukuBungaImbalan": 1,
        "persentaseImbalanAwalKontrak": np.round(RNG.uniform(6.0, 14.0, n), 2),
        "sukuBungaPersentaseImbalanBulanLaporan": np.round(RNG.uniform(6.0, 14.0, n), 2),
        "kualitas": kualitas,
        "plafonAwal": plafon.round(0), "plafon": plafon.round(0),
        "saldoHargaPokok": 0, "saldoMarginDitangguhkan": 0,
        "bakiDebet": jumlah, "realisasiPencairanBulanBerjalan": 0,
        "pendapatanBungaImbalanYangAkanDiterima": 0,
        "jumlah": jumlah,
        "kelonggaranTarikCommitted": np.round(plafon * RNG.uniform(0.0, 0.15, n), 0),
        "kelonggaranTarikUncommitted": np.round(plafon * RNG.uniform(0.0, 0.05, n), 0),
        "nilaiAgunanYangDapatDiperhitungkanKredit": np.round(jumlah * RNG.uniform(0.8, 1.5, n), 0),
        "nilaiAgunanYangDapatDiperhitungkanKelonggaranTarik": 0,
        "cadanganKerugianPenurunanNilaiAsetBaik": np.nan,
        "cadanganKerugianPenurunanNilaiAsetKurangBaik": np.nan,
        "cadanganKerugianPenurunanNilaiAsetTidakBaik": np.nan,
        "tunggakanPokok": np.where(kualitas >= 3, (jumlah * 0.05).round(0), 0),
        "tunggakanMarginImbalan": np.where(kualitas >= 3, (jumlah * 0.01).round(0), 0),
        "jumlahHariTunggakan": np.where(kualitas == 1, 0, np.where(kualitas == 2, RNG.integers(1, 90, n), RNG.integers(90, 270, n))),
        "jumlahHariTunggakanPokok": np.nan,
        "jumlahHariTunggakanBagiHasil": np.nan,
    }
    return pd.DataFrame(n_cols)


# ── Agunan (was agn01) — kept for completeness, NOT used by the engine ──────
AGUNAN_TYPES = ["AN020101", "AN02010301", "AN020201", "AN020301"]


def gen_agunan(n, date, noise=1.0):
    i = np.arange(1, n + 1)
    nilai = np.clip(RNG.lognormal(18.0, 1.2, n), 5_000_000, 8_000_000_000) * noise
    return pd.DataFrame({
        "idPelapor": BANK_ID,
        "periodeLaporan": "M",
        "periodeData": date,
        "noAgunan": [f"AG{x:09d}" for x in i],
        "jenisAgunan": RNG.choice(AGUNAN_TYPES, size=n),
        "nilaiAgunan": nilai.round(0).astype(np.int64),
    })


# ── SBI — Sertifikat Bank Indonesia (was sym01 / SUKBI) ─────────────────────
def gen_sbi(date, total_target, n=6):
    cuts = np.concatenate([[0.0], np.sort(RNG.uniform(0, total_target, n - 1)), [total_target]])
    nominal = np.diff(cuts)
    nominal = np.round(np.clip(nominal, 5_000_000_000, None))
    diagunkan = RNG.choice(["Tidak", "Tidak", "Tidak", "Ya"], size=n)
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
        "kualitas": 1, "karakteristikSumberDana": "NMT", "jenisAkad": 0,
        "metodeBagiHasil": np.nan, "persentaseNisbah": np.nan,
        "periodePembayaranImbalan": "X",
        "persentaseImbalanAwalKontrak": np.round(RNG.uniform(4.5, 6.5, n), 2),
        "sukuBungaPersentaseImbalanBulanLaporan": np.round(RNG.uniform(4.5, 6.5, n), 2),
        "jenisSukuBunga": np.nan,
        "nominal": nominal.astype(np.int64),
        "hargaPerolehan": 0, "premiumDiskonto": 0,
        "jumlahBulanLalu": np.nan, "jumlahDebet": np.nan, "jumlahKredit": np.nan, "jumlahLainnya": np.nan,
        "jumlahBulanLaporan": nominal.astype(np.int64),
        "pendapatanBungaImbalanYangAkanDiterima": 0,
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
def gen_penempatan_bi(date, fasbis, giro_bi):
    tgl_mulai = date
    tgl_jt = (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "idPelapor": BANK_ID, "periodeLaporan": "M", "periodeData": date,
        "idData": [50301, 50302],
        "jenisPenempatan": ["F08", "F09"],
        "jenisValuta": "IDR",
        "tanggalMulai": tgl_mulai,
        "tanggalJatuhTempo": tgl_jt,
        "karakteristikSumberDana": "NMT",
        "sukuBungaPersentaseImbalan": [5.75, 0.0],
        "jumlah": [int(fasbis), int(giro_bi)],
    })


# ── Neraca Harian (was nrc01) ────────────────────────────────────────────────
def gen_neraca(date, agg):
    """agg: dict with cross-file aggregate figures used to keep the balance
    sheet internally consistent with the detail files generated above.

    NOTE: KETERANGAN labels 'KAS', 'PENEMPATAN PADA BANK LAIN',
    'ASET TETAP DAN INVENTARIS', 'SURAT BERHARGA YANG DIMILIKI', 'SUKUK BI'
    (ASET) and 'DPK (GIRO+TAB+DEPO)' (RANGKUMAN), plus the
    'FASILITAS PEMBIAYAAN YANG BELUM DITARIK' / 'GARANSI YANG DIBERIKAN'
    substrings (RKA), are read by exact/substring match in lcr_engine.py /
    nsfr_engine.py — keep them verbatim even though this file otherwise uses
    conventional-bank wording. See PR notes for why 'SUKUK BI' itself is
    intentionally left as-is (engine-hardcoded, out of this revision's scope).
    """
    kas = agg["kas"]
    fasbis = agg["fasbis"]
    giro_bi_total = agg["giro_bi_total"]          # F09 total (BI current account)
    giro_bi_split = round(giro_bi_total * 0.77)   # GIRO line
    giro_bi_fast = giro_bi_total - giro_bi_split  # GIRO BI FAST line
    penempatan_bi_sub = fasbis + giro_bi_total

    interbank_giro = agg["interbank_giro"]
    interbank_tab = 0
    interbank_depo = agg["interbank_depo"]
    penempatan_bank_lain = interbank_giro + interbank_tab + interbank_depo

    total_sb = agg["sbi_total"]        # matches SBI file total nominal
    sbi_line = total_sb                # entire securities book is SBI in this dummy

    piutang_lain = agg["kredit_total"] * 0.02
    kredit_modal_kerja = agg["kredit_total"] * 0.55
    kredit_investasi = agg["kredit_total"] * 0.43

    aset_tetap = agg["aset_tetap"]
    aset_lainnya = agg["aset_lainnya"]
    ckpn = -agg["kredit_total"] * 0.012

    aset_rows = [
        ("KAS", kas),
        ("PENEMPATAN PADA BANK INDONESIA", penempatan_bi_sub),
        ("GIRO", giro_bi_split),
        ("FASBIS", fasbis),
        ("GIRO BI FAST", giro_bi_fast),
        ("PENEMPATAN PADA BANK LAIN", penempatan_bank_lain),
        ("GIRO", interbank_giro),
        ("TABUNGAN", interbank_tab),
        ("DEPOSITO", interbank_depo),
        ("SURAT-SURAT BERHARGA YANG DIBELI DGN JANJI DIJUAL KEMBALI (REVERSE REPO)", 0),
        ("TAGIHAN SPOT DAN DERIVATIF/FORWARD", 0),
        ("SURAT BERHARGA YANG DIMILIKI", total_sb),
        ("SUKUK BI", sbi_line),  # engine-hardcoded label — kept verbatim, see docstring
        ("OBLIGASI KORPORASI", 0),
        ("TAGIHAN AKSEPTASI", 0),
        ("PIUTANG :", agg["kredit_total"] + piutang_lain),
        ("-  KREDIT MODAL KERJA", kredit_modal_kerja),
        ("-  KREDIT INVESTASI", kredit_investasi),
        ("-  KREDIT KONSUMSI", piutang_lain),
        ("PENYERTAAN MODAL", 0),
        ("ASET KEUANGAN LAINNYA", round(agg["kredit_total"] * 0.002)),
        ("CADANGAN KERUGIAN PENURUNAN NILAI ASET PRODUKTIF -/-", round(ckpn)),
        ("ASET TIDAK BERWUJUD", 0),
        ("AKUMULASI AMORTISASI -/- ASET TDK BERWUJUD", 0),
        ("ASET TETAP DAN INVENTARIS", aset_tetap),
        ("AKUMULASI PENYUSUTAN ASET TETAP DAN INVENTARIS -/-", round(-aset_tetap * 0.58)),
        ("PROPERTI TERBENGKALAI", 0),
        ("AGUNAN YANG DIAMBIL ALIH", round(agg["kredit_total"] * 0.004)),
        ("REKENING TUNDA", 0),
        ("ASET ANTAR KANTOR", 0),
        ("PERSEDIAAN", 0),
        ("ASET LAINNYA", aset_lainnya),
    ]
    total_aset = sum(v for k, v in aset_rows if k not in
                      ("-  KREDIT MODAL KERJA", "-  KREDIT INVESTASI", "-  KREDIT KONSUMSI",
                       "GIRO BI FAST", "FASBIS", "GIRO", "TABUNGAN", "DEPOSITO",
                       "SUKUK BI"))
    aset_rows.append(("TOTAL ASET", round(total_aset)))
    df_aset = pd.DataFrame([(k, round(v) if isinstance(v, (int, float)) else v) for k, v in aset_rows],
                           columns=["KETERANGAN", "REALISASI"])

    dpk_total = agg["dpk_total"]
    liab_rows = [
        ("SIMPANAN GIRO :", agg["giro_total"]),
        ("-  GIRO", agg["giro_total"]),
        ("SIMPANAN TABUNGAN :", agg["tabungan_total"]),
        ("-  TABUNGAN", agg["tabungan_total"]),
        ("SIMPANAN BERJANGKA (DEPOSITO) :", agg["deposito_total"]),
        ("-  DEPOSITO", agg["deposito_total"]),
        ("UANG ELEKTRONIK", 0),
        ("LIABILITAS KEPADA BANK INDONESIA", 0),
        ("LIABILITAS KEPADA BANK LAIN", round(agg["kredit_total"] * 0.015)),
        ("LIABILITAS SPOT DAN FORWARD", 0),
        ("LIABILITAS AKSEPTASI", 0),
        ("SURAT BERHARGA DITERBITKAN", 0),
        ("PINJAMAN YANG DITERIMA", round(agg["kredit_total"] * 0.03)),
        ("SETORAN JAMINAN", 0),
        ("LIABILITAS ANTAR KANTOR", round(total_aset * 0.14)),
        ("LIABILITAS LAINNYA", round(agg["kredit_total"] * 0.003)),
        ("MODAL DISETOR", 0),
        ("TAMBAHAN MODAL DISETOR", 0),
        ("PENGHASILAN KOMPREHENSIF LAINNYA", 0),
        ("CADANGAN", 0),
        ("LABA/RUGI", round(total_aset * 0.012)),
        ("-  TAHUN-TAHUN LALU", 0),
        ("-  TAHUN BERJALAN", round(total_aset * 0.012)),
        ("-  DEVIDEN YANG DIBAYARKAN", 0),
    ]
    total_liab = (agg["giro_total"] + agg["tabungan_total"] + agg["deposito_total"]
                  + round(agg["kredit_total"] * 0.015) + round(agg["kredit_total"] * 0.03)
                  + round(total_aset * 0.14) + round(agg["kredit_total"] * 0.003)
                  + round(total_aset * 0.012))
    liab_rows.append(("TOTAL LIABILITAS", total_liab))
    df_liab = pd.DataFrame(liab_rows, columns=["KETERANGAN", "REALISASI"])

    df_laba = pd.DataFrame([
        ("PENDAPATAN BUNGA", round(agg["kredit_total"] * 0.085)),
        ("PENEMPATAN PADA BANK INDONESIA", round(penempatan_bi_sub * 0.04)),
        ("DARI PENEMPATAN PADA BANK LAIN", round(penempatan_bank_lain * 0.04)),
        ("DARI KREDIT YANG DIBERIKAN", round(agg["kredit_total"] * 0.08)),
        ("BEBAN BUNGA", round(dpk_total * 0.025)),
        ("LABA BERSIH", round(total_aset * 0.012)),
    ], columns=["KETERANGAN", "REALISASI"])

    komitmen_belum_ditarik = agg["kredit_total"] * 0.02
    garansi = agg["kredit_total"] * 0.0015
    df_rka = pd.DataFrame([
        ("TAGIHAN KOMITMEN", np.nan),
        ("FASILITAS KREDIT YANG BELUM DITARIK", 0.0),
        ("POSISI VALAS YANG AKAN DITERIMA DARI TRANSAKSI SPOT DAN", 0.0),
        ("LAINNYA", 0.0),
        ("TAGIHAN KONTINJENSI", np.nan),
        ("GARANSI YANG DITERIMA", 0.0),
        ("PENDAPATAN DALAM PENYELESAIAN", round(agg["npf_total"] * 0.05)),
        ("LAINNYA", round(agg["kredit_total"] * 0.001)),
        ("KEWAJIBAN KOMITMEN", np.nan),
        ("FASILITAS PEMBIAYAAN YANG BELUM DITARIK", round(komitmen_belum_ditarik)),  # engine regex-matched, kept verbatim
        ("IRREVOCABLE L/C YANG MASIH BERJALAN", 0.0),
        ("POSISI VALAS YANG AKAN DISERAHKAN DARI TRANSAKSI SPOT DAN", 0.0),
        ("LAINNYA", 0.0),
        ("KEWAJIBAN KONTINJENSI", np.nan),
        ("GARANSI YANG DIBERIKAN", round(garansi)),  # engine regex-matched, kept verbatim
        ("LAINNYA", 0.0),
    ], columns=["KETERANGAN", "NILAI"])

    df_rangkuman = pd.DataFrame([
        ("KREDIT", agg["kredit_total"]),
        ("DPK (GIRO+TAB+DEPO+MTN non Bank)", dpk_total),
        ("DPK (GIRO+TAB+DEPO)", dpk_total),  # engine-hardcoded label — kept verbatim
        ("LDR", round(agg["kredit_total"] / dpk_total, 4)),
        ("TOTAL PENDAPATAN", round(agg["kredit_total"] * 0.085)),
        ("TOTAL BEBAN", round(dpk_total * 0.025)),
        ("LABA", round(total_aset * 0.012)),
    ], columns=["KETERANGAN", "REALISASI"])

    return {
        "ASET": df_aset, "LIABILITAS": df_liab, "LABA RUGI": df_laba,
        "RKA": df_rka, "RANGKUMAN": df_rangkuman,
    }


def build_period(date, is_current):
    noise_deposit = 1.0 if is_current else RNG.uniform(0.94, 0.99)
    amort = 1.0 if is_current else 1.03  # loans were slightly higher a month earlier

    df_tab = gen_tabungan(3000, date, 260_000_000_000, noise_deposit)
    df_gir = gen_giro(600, date, 280_000_000_000, noise_deposit)
    df_dep = gen_deposito(1200, date, 260_000_000_000, noise_deposit)
    df_pin = gen_pinjaman(2500, date, 620_000_000_000, amort)
    df_agn = gen_agunan(4000, date, noise_deposit)

    kredit_total = df_pin["jumlah"].sum()
    npf_total = df_pin.loc[df_pin["kualitas"] >= 3, "jumlah"].sum()
    tabungan_total = df_tab["jumlahBulanLaporan"].sum()
    giro_total = df_gir["jumlahBulanLaporan"].sum()
    deposito_total = df_dep["jumlahBulanLaporan"].sum()
    dpk_total = tabungan_total + giro_total + deposito_total

    sbi_total_target = 70_000_000_000 * noise_deposit
    df_sbi = gen_sbi(date, sbi_total_target)
    sbi_total = df_sbi["nominal"].sum()

    fasbis = round(35_000_000_000 * noise_deposit)
    giro_bi_total = round(20_000_000_000 * noise_deposit)
    df_pbi = gen_penempatan_bi(date, fasbis, giro_bi_total)

    agg = {
        "kas": round(12_000_000_000 * noise_deposit),
        "fasbis": fasbis,
        "giro_bi_total": giro_bi_total,
        "interbank_giro": round(8_000_000_000 * noise_deposit),
        "interbank_depo": round(6_000_000_000 * noise_deposit),
        "sbi_total": int(sbi_total),
        "kredit_total": int(kredit_total),
        "npf_total": int(npf_total),
        "tabungan_total": int(tabungan_total),
        "giro_total": int(giro_total),
        "deposito_total": int(deposito_total),
        "dpk_total": int(dpk_total),
        "aset_tetap": round(15_000_000_000 * noise_deposit),
        "aset_lainnya": round(10_000_000_000 * noise_deposit),
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
