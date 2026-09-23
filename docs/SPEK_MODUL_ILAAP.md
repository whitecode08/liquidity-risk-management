# Spesifikasi Modul ILAAP
## Perluasan atas `liquidity-risk-management` (whitecode08)

**Status:** Spesifikasi teknis untuk implementasi — dibawa ke Claude Code
**Acuan regulasi:** SEOJK No. 26/SEOJK.03/2025 tentang Proses Asesmen Kecukupan
Likuiditas secara Internal (ILAAP) bagi Bank Umum, ditetapkan 19 November 2025.
Berlaku bertahap berdasarkan pengelompokan KBMI Bank per 31 Desember 2025.
**Basis kode:** Repo existing sudah punya `lcr_engine.py` dan `nsfr_engine.py`
(Python murni, tanpa UI). Modul di bawah ini mengikuti pola yang sama:
mesin kalkulasi terpisah dari Streamlit, dapat diuji dan dipanggil dari notebook.

> Catatan penting untuk Claude Code: repo referensi (`whitecode08/liquidity-risk-management`)
> ditulis untuk **BUS/UUS** (nomenklatur syariah — FASBIS, SUKBI, pembiayaan, kualitas).
> Jika target implementasi adalah **BUK**, seluruh contoh field di bawah perlu
> disesuaikan namanya (mis. `pembiayaan` → `kredit`, `kualitas` → `kolektibilitas`),
> tapi **struktur modul dan algoritmanya tidak berubah**. Konfirmasi dulu BUS/UUS
> atau BUK sebelum mulai coding.

---

## 1. Ringkasan Gap dan Prioritas

| # | Modul | Status di repo saat ini | Prioritas |
|---|---|---|---|
| 1 | Available HQLA (vs HQLA biasa) | Sebagian ada (GWM sudah dikurangi), PLM belum | Tinggi — fondasi modul lain |
| 2 | Survival Period Monitoring + Pillar 2 add-on | Tidak ada | Tinggi — modul inti |
| 3 | LCR per Mata Uang Signifikan | Tidak ada | Sedang — tergantung eksposur valas Bank |
| 4 | Roll Over Funding Monitoring | Tidak ada | Sedang |
| 5 | Likuiditas Intrahari & Intragrup | Tidak ada | **Di luar lingkup** — lihat §9 |
| 6 | Laporan Profil Pendanaan | Tidak ada | Sedang — laporan baru di versi final SEOJK |

Urutan implementasi yang disarankan: **1 → 2 → 6 → 4 → 3**. Modul 2 (Survival
Period) adalah yang paling kompleks dan paling bernilai; kerjakan setelah
Available HQLA (modul 1) selesai karena modul 2 memakainya sebagai input.

---

## 2. Struktur Direktori Baru

```
src/
├── app.py
├── lcr_engine.py            # sudah ada — tidak diubah
├── nsfr_engine.py           # sudah ada — tidak diubah
├── ilaap/
│   ├── __init__.py
│   ├── available_hqla.py    # Modul 1
│   ├── survival_period.py   # Modul 2 — inti
│   ├── funding_profile.py   # Modul 6
│   ├── roll_over.py         # Modul 4
│   ├── fx_significant.py    # Modul 3
│   ├── config/
│   │   ├── time_buckets.yaml       # 19 bucket, definisi batas hari
│   │   ├── stress_scenarios.yaml   # parameter skenario stres
│   │   └── add_on_rules.yaml       # aturan penentuan Pillar 2 add-on
│   └── audit.py              # perluasan jejak audit khusus ILAAP
├── pages/
│   ├── ...                   # halaman existing
│   ├── 6_Survival_Period.py
│   ├── 7_LCR_Mata_Uang.py
│   ├── 8_Roll_Over_Funding.py
│   └── 9_Profil_Pendanaan.py
└── audit_log.py               # sudah ada — di-extend, bukan diganti
```

---

## 3. Perluasan Skema Data (Kontrak Data)

Sheet sumber existing (`nrc01`, `krp01`/`pembiayaan`, `dep01`, `tab01`, `gir01`,
dst.) sudah cukup untuk LCR/NSFR karena hanya butuh kategori agregat. Modul
ILAAP butuh **granularitas transaksi**, karena setiap baris harus dipetakan ke
salah satu dari 19 time bucket berdasarkan tanggal jatuh tempo kontraktual.

### 3.1 Field wajib tambahan pada setiap sheet sumber transaksi

```yaml
# ilaap/config/data_contract_addendum.yaml
required_additional_fields:
  tanggal_jatuh_tempo_kontraktual:
    type: date
    description: >
      WAJIB untuk seluruh instrumen bertenor. Untuk instrumen tanpa
      tenor kontraktual (giro, tabungan on-demand), field ini kosong
      dan baris ditangani lewat aturan distribusi §5.3.
  mata_uang:
    type: string
    enum: [IDR, USD, EUR, JPY, SGD, ...]  # sesuaikan dengan eksposur Bank
    default: IDR
  segmen_nasabah:
    type: string
    enum: [ritel_perorangan, umk, korporasi_operasional, korporasi_non_operasional, bank, lembaga_keuangan, bank_sentral]
    description: menentukan run-off/inflow rate mana yang dipakai (sama seperti LCR)
  dijamin_lps:
    type: boolean
    nullable: true  # hanya relevan untuk simpanan
  jenis_agunan:
    type: string
    enum: [hqla_level1, hqla_level2a, hqla_level2b_eba, hqla_level2b_korporasi, hqla_level2b_saham, lainnya, tidak_ada]
    nullable: true  # hanya relevan untuk secured funding
```

### 3.2 Validasi tambahan (di `ilaap/available_hqla.py` dan `survival_period.py`)

- Baris tanpa `tanggal_jatuh_tempo_kontraktual` **dan** tanpa penanda "on-demand"
  eksplisit → ditolak (kontrak data existing di repo sudah punya pola ini untuk
  `krp01`, tinggal direplikasi).
- `mata_uang` tidak boleh kosong; default `IDR` hanya boleh diterapkan jika
  eksplisit dikonfigurasi, bukan diam-diam.

---

## 4. Modul 1 — Available HQLA

### 4.1 Formula

```
Available HQLA = HQLA (sesuai POJK LCR, dengan haircut Pasal 10/11/12)
                  − Kewajiban GWM
                  − Kewajiban PLM (Penyangga Likuiditas Makroprudensial)
                  − Sumber likuiditas dari Bank Sentral
```

Repo existing (`lcr_engine.py` fungsi `hqla_calc`) sudah mengurangi GWM (3,5% ×
DPK, untuk versi syariah). **PLM belum ada** — ini penambahan.

### 4.2 Implementasi

```python
# ilaap/available_hqla.py
def available_hqla_calc(hqla_df, gwm_obligation, plm_obligation, bi_sourced_liquidity):
    """
    hqla_df: DataFrame hasil hqla_calc() dari lcr_engine.py — JANGAN dihitung
    ulang, panggil fungsi existing untuk menghindari duplikasi logika haircut.
    gwm_obligation, plm_obligation, bi_sourced_liquidity: nilai skalar per
    tanggal posisi, diambil dari input manual atau sheet terpisah.
    """
    total_hqla = hqla_df["nilai_setelah_haircut"].sum()
    available = total_hqla - gwm_obligation - plm_obligation - bi_sourced_liquidity
    return {
        "total_hqla": total_hqla,
        "gwm_obligation": gwm_obligation,
        "plm_obligation": plm_obligation,
        "bi_sourced_liquidity": bi_sourced_liquidity,
        "available_hqla": max(available, 0),  # tidak boleh negatif
        "_formula": "total_hqla - gwm - plm - bi_sourced",  # untuk jejak audit
    }
```

### 4.3 Sumber nilai `gwm_obligation` dan `plm_obligation`

Ini kemungkinan besar **tidak ada di sheet Excel existing** (`nrc01`, `pbi01`,
dst.) — perlu satu input manual tambahan per periode (mis. sheet baru
`kewajiban_gwm_plm.xlsx` atau field input di UI). Klarifikasi ini ke Bank
sebelum implementasi: apakah GWM/PLM harian tersedia sebagai ekstraksi
otomatis atau harus diinput manual tiap periode.

---

## 5. Modul 2 — Survival Period Monitoring (inti)

### 5.1 Struktur 19 Time Bucket

```yaml
# ilaap/config/time_buckets.yaml
buckets:
  - id: overnight
    label: "Overnight"
    hari_mulai: 0
    hari_selesai: 1
  - id: h2
    label: "Hari-2"
    hari_mulai: 1
    hari_selesai: 2
  - id: h3
    hari_mulai: 2
    hari_selesai: 3
  - id: h4
    hari_mulai: 3
    hari_selesai: 4
  - id: h5
    hari_mulai: 4
    hari_selesai: 5
  - id: h6
    hari_mulai: 5
    hari_selesai: 6
  - id: h7
    hari_mulai: 6
    hari_selesai: 7
  - id: h7_14
    label: "7 s.d. 14 hari"
    hari_mulai: 7
    hari_selesai: 14
  - id: h14_1bln
    label: "> 14 hari s.d. 1 bulan"
    hari_mulai: 14
    hari_selesai: 30
  - id: 1_2bln
    hari_mulai: 30
    hari_selesai: 60
  - id: 2_3bln
    hari_mulai: 60
    hari_selesai: 90
  - id: 3_6bln
    hari_mulai: 90
    hari_selesai: 180
  - id: 6_9bln
    hari_mulai: 180
    hari_selesai: 270
  - id: 9_12bln
    hari_mulai: 270
    hari_selesai: 365
  - id: 12bln_2thn
    hari_mulai: 365
    hari_selesai: 730
  - id: 2_3thn
    hari_mulai: 730
    hari_selesai: 1095
  - id: 3_5thn
    hari_mulai: 1095
    hari_selesai: 1825
  - id: diatas_5thn
    hari_mulai: 1825
    hari_selesai: null   # tak terhingga
```

### 5.2 Perbedaan kritis dari `lcr_engine.py` — JANGAN pakai ulang inflow cap

> **Paragraf 10.21 dokumen sumber, dikutip eksplisit:** "pembatasan arus kas
> masuk sebagaimana perhitungan LCR yang diatur dalam POJK mengenai LCR tidak
> digunakan" untuk survival period.

Jadi `survival_period.py` **tidak memanggil** fungsi `lcr_calculation()` dari
`lcr_engine.py` secara langsung (fungsi itu menerapkan cap 75%). Yang dipakai
ulang hanya **tabel run-off/inflow rate per kategori** dari `lcr_engine.py`
(faktor 5%/10%/25%/40%/dst.), bukan fungsi agregasi akhirnya. Refactor yang
disarankan: ekstrak tabel faktor itu menjadi fungsi/konstanta terpisah yang
bisa dipanggil dari kedua modul (`lcr_engine.py` DAN `survival_period.py`)
tanpa duplikasi angka.

```python
# lcr_engine.py — refactor yang disarankan agar bisa dipakai ulang
def get_runoff_rate(segmen, stabilitas, dijamin_lps=None) -> float:
    """Tabel faktor run-off LCR. Dipanggil oleh lcr_calculation() DAN
    oleh ilaap/survival_period.py. Single source of truth untuk faktor."""
    ...

def get_inflow_rate(segmen, jenis_counterparty) -> float:
    ...
```

### 5.3 Algoritma Proyeksi Arus Kas

```python
# ilaap/survival_period.py

def project_cashflow_ladder(transactions_df, buckets, scenario):
    """
    transactions_df: gabungan seluruh sheet sumber, sudah dinormalisasi,
        dengan kolom tanggal_jatuh_tempo_kontraktual, segmen_nasabah, dst.
    scenario: salah satu dari stress_scenarios.yaml (lihat §5.4)

    Return: DataFrame dengan kolom [bucket_id, arus_keluar_kumulatif,
        arus_masuk_kumulatif, net_outflow_kumulatif]
    """
    # 1. Pisahkan transaksi dengan tenor kontraktual vs tanpa tenor (on-demand)
    with_tenor = transactions_df[transactions_df["tanggal_jatuh_tempo_kontraktual"].notna()]
    without_tenor = transactions_df[transactions_df["tanggal_jatuh_tempo_kontraktual"].isna()]

    # 2. Untuk transaksi bertenor: petakan tiap baris ke bucket berdasarkan
    #    selisih hari dari tanggal posisi ke tanggal jatuh tempo
    with_tenor = with_tenor.assign(
        hari_ke_jatuh_tempo=(with_tenor["tanggal_jatuh_tempo_kontraktual"] - scenario["tanggal_posisi"]).dt.days
    )
    with_tenor["bucket_id"] = with_tenor["hari_ke_jatuh_tempo"].apply(
        lambda h: assign_bucket(h, buckets)
    )

    # 3. Untuk transaksi tanpa tenor (giro/tabungan on-demand): terapkan
    #    aturan distribusi sesuai skenario (lihat §5.4 — beda per skenario!)
    without_tenor_distributed = distribute_no_tenor(without_tenor, scenario)

    combined = pd.concat([with_tenor, without_tenor_distributed])

    # 4. Terapkan run-off/inflow rate (dari get_runoff_rate/get_inflow_rate)
    combined["nilai_terbobot"] = combined.apply(
        lambda row: row["nilai_dasar"] * get_rate_for_row(row, scenario), axis=1
    )

    # 5. Agregasi per bucket, lalu kumulatifkan sepanjang urutan bucket
    per_bucket = combined.groupby(["bucket_id", "arah"])["nilai_terbobot"].sum().unstack()
    per_bucket = per_bucket.reindex([b["id"] for b in buckets])  # jaga urutan
    per_bucket["arus_keluar_kumulatif"] = per_bucket["keluar"].cumsum()
    per_bucket["arus_masuk_kumulatif"] = per_bucket["masuk"].cumsum()
    per_bucket["net_outflow_kumulatif"] = (
        per_bucket["arus_keluar_kumulatif"] - per_bucket["arus_masuk_kumulatif"]
    )
    return per_bucket


def assign_bucket(hari, buckets):
    for b in buckets:
        if b["hari_selesai"] is None or (b["hari_mulai"] <= hari < b["hari_selesai"]):
            return b["id"]
    raise ValueError(f"Hari {hari} tidak masuk bucket manapun — cek data jatuh tempo")
```

### 5.4 Skenario Stres (`stress_scenarios.yaml`)

Tiga keluarga skenario dari dokumen sumber, masing-masing dengan aturan
distribusi arus kas tanpa-tenor yang **berbeda**:

```yaml
scenarios:
  - id: lcr_30_hari
    label: "Stress Testing LCR (30 hari)"
    horizon_hari: 30
    no_tenor_distribution: hari_pertama   # semua materialisasi di H+0
    catatan: >
      Run-off/inflow rate LCR untuk transaksi ritel & korporasi terjadi
      pada hari pertama stres. Arus kas keluar off-balance-sheet tanpa
      tenor (mis. kebutuhan agunan derivatif) juga di hari pertama, ATAU
      diratakan selama 30 hari (mis. KPR disetujui belum ditarik) —
      tentukan per jenis instrumen, lihat tabel klasifikasi §5.5.

  - id: benchmark_90_hari_ritel
    label: "Benchmark 90 hari — stres segmen ritel"
    horizon_hari: 90
    no_tenor_distribution: satu_kali_h1_sampai_h30  # materialisasi sekali, tersebar acak/merata H1-H30
    segmen_terdampak: [ritel_perorangan, umk]

  - id: benchmark_90_hari_korporasi
    label: "Benchmark 90 hari — stres segmen korporasi"
    horizon_hari: 90
    no_tenor_distribution: satu_kali_h1_sampai_h30
    segmen_terdampak: [korporasi_operasional, korporasi_non_operasional]

  - id: benchmark_90_hari_gabungan
    label: "Benchmark 90 hari — ritel + korporasi bersamaan"
    horizon_hari: 90
    no_tenor_distribution: satu_kali_h1_sampai_h30
    segmen_terdampak: [ritel_perorangan, umk, korporasi_operasional, korporasi_non_operasional]

  # Skenario "enhance" opsional (§10.26 dokumen) — implementasi setelah
  # tiga skenario inti di atas selesai dan tervalidasi
  - id: enhance_ritel_runoff_tinggi
    label: "Enhance — run-off ritel tanpa LPS lebih tinggi"
    base_scenario: benchmark_90_hari_ritel
    override_rate_multiplier:
      segmen: ritel_perorangan
      dijamin_lps: false
      multiplier: 1.5   # PLACEHOLDER — konfirmasi angka ke Bank/Manajemen Risiko

  - id: enhance_korporasi_penarikan_penuh
    label: "Enhance — korporasi menarik setengah/seluruh dana"
    base_scenario: benchmark_90_hari_korporasi
    override_rate_multiplier:
      segmen: korporasi_operasional
      multiplier: 2.0   # 100% penarikan vs baseline — konfirmasi ke Bank
```

**Untuk monetisasi HQLA pasca-stres (opsional, §10.25 dokumen):** skenario di
atas bisa dikombinasikan dengan stres profil available HQLA — hanya kas,
penempatan BI, dan hasil monetisasi HQLA berbentuk surat berharga yang
dihitung menutup kebutuhan likuiditas harian. Implementasikan sebagai flag
`hqla_stress: true` pada skenario, bukan skenario terpisah, agar tidak
menggandakan kombinasi.

### 5.5 Penentuan Survival Period dan Pillar 2 Add-On

```python
def determine_survival_period(ladder_df, available_hqla_day0, target_survival_days):
    """
    ladder_df: hasil dari project_cashflow_ladder()
    available_hqla_day0: dari available_hqla.py, nilai pada hari 0
    target_survival_days: ditetapkan Bank sesuai risk appetite (mis. 90 hari)

    Return dict berisi:
        - available_hqla_per_bucket (hasil hari 0 dikurangi net_outflow_kumulatif)
        - survival_period_hari (bucket pertama di mana nilai <= 0)
        - memenuhi_target: bool
        - add_on_required: bool
        - shortfall_pada_target: nilai kekurangan HQLA pada bucket target (jika ada)
    """
    ladder_df["available_hqla_kumulatif"] = (
        available_hqla_day0 - ladder_df["net_outflow_kumulatif"]
    )

    depleted = ladder_df[ladder_df["available_hqla_kumulatif"] <= 0]
    survival_bucket = depleted.index[0] if not depleted.empty else None

    memenuhi_target = (
        survival_bucket is None
        or bucket_to_days(survival_bucket) >= target_survival_days
    )

    result = {
        "ladder": ladder_df,
        "survival_bucket": survival_bucket,
        "survival_hari": bucket_to_days(survival_bucket) if survival_bucket else None,
        "memenuhi_target": memenuhi_target,
        "add_on_required": not memenuhi_target,
    }

    if not memenuhi_target:
        # Shortfall pada bucket yang bersesuaian dengan target survival period
        target_bucket = days_to_bucket(target_survival_days)
        shortfall = -ladder_df.loc[target_bucket, "available_hqla_kumulatif"]
        result["shortfall_pada_target"] = max(shortfall, 0)
        # Add-on dinyatakan sebagai LCR tambahan — lihat add_on_rules.yaml
        # untuk formula konversi shortfall → persentase LCR add-on.
        result["add_on_lcr_percent"] = compute_add_on_percent(shortfall, current_hqla_day0=available_hqla_day0)

    return result
```

**`add_on_rules.yaml` — bagian ini butuh keputusan kebijakan internal Bank,
bukan murni teknis.** Dokumen sumber (§10.19–10.27) menjelaskan *konsep* add-on
(dikenakan jika survival period tidak capai target) tapi tidak memberi rumus
konversi shortfall-ke-persentase-LCR yang eksplisit dan seragam. Sebelum
implementasi `compute_add_on_percent()`, ini **wajib dikonfirmasi ke Divisi
Manajemen Risiko dan Kepatuhan Bank** — kemungkinan besar perlu policy
paper internal terpisah yang menetapkan metodologi konversi. Tandai fungsi
ini sebagai `NotImplementedError` dengan komentar jelas sampai keputusan
turun, jangan menebak rumusnya.

### 5.6 Kasus Uji — Angka Referensi dari Dokumen (Bank A)

Gunakan tabel ini sebagai *golden test* — hasil perhitungan modul harus
mereproduksi pola ini (angka dalam satuan yang sama seperti dokumen, mis.
Triliun Rupiah):

| Bulan ke- | Arus keluar kumulatif | Arus masuk kumulatif | Net outflow kumulatif | Available HQLA |
|---|---|---|---|---|
| 0 (awal) | — | — | — | 1.200 |
| 1 | 511 | 405 | 106 | 1.094 |
| 2 | 933 | 693 | 240 | 960 |
| 3 | 1.433 | 875 | 558 | 642 |
| 4 | 1.485 | 911 | 574 | 626 |
| 5 | 1.666 | 956 | 710 | 490 |
| 6 (akhir data) | 2.192 | 1.131 | 1.061 | 139 |

Bank A dengan target survival period 3 bulan: pada bulan ke-6 masih positif
(139), sehingga target 3 bulan terpenuhi dan **tidak ada add-on**. Tulis unit
test yang memuat data sintetis setara pola ini dan assert `memenuhi_target ==
True`, `add_on_required == False`.

Buat juga kasus uji "Bank B" (disebut di dokumen tapi tabelnya tidak
terekstrak lengkap dari PDF): defisit terjadi pada bulan ke-2, target 3 bulan
**tidak terpenuhi** → assert `add_on_required == True`. Untuk detail angka
Bank B, cek langsung halaman 73 dokumen sumber (`pdftoppm` halaman tersebut
untuk membaca tabel secara visual — ekstraksi teks tidak menangkapnya utuh).

---

## 6. Modul 3 — LCR per Mata Uang Signifikan

### 6.1 Formula

```
LCR_mata_uang_signifikan = HQLA_mata_uang_signifikan / Arus_kas_keluar_bersih_mata_uang_signifikan
```

Definisi HQLA dan arus kas sama seperti LCR agregat, tapi difilter per
`mata_uang`, dengan aturan konversi memakai kurs tengah BI dan **tanpa
offsetting** antar mata uang.

### 6.2 Implementasi

```python
# ilaap/fx_significant.py

def identify_significant_currencies(transactions_df, threshold=0.05):
    """Mata uang dianggap signifikan jika kewajiban dalam mata uang tsb
    >= 5% dari total kewajiban Bank (semua mata uang, dikonversi ke IDR)."""
    liabilities_by_ccy = transactions_df[transactions_df["arah"] == "kewajiban"].groupby("mata_uang")["nilai_idr"].sum()
    total = liabilities_by_ccy.sum()
    return liabilities_by_ccy[liabilities_by_ccy / total >= threshold].index.tolist()


def lcr_per_currency(transactions_df, currency, kurs_tengah_bi):
    filtered = transactions_df[transactions_df["mata_uang"] == currency]
    # Panggil ulang lcr_engine.hqla_calc() dan lcr_calculation() dengan
    # filtered df — JANGAN duplikasi logika haircut/run-off/cap, cukup
    # filter input sebelum memanggil fungsi existing.
    from lcr_engine import hqla_calc, lcr_calculation
    hqla = hqla_calc(filtered)
    result = lcr_calculation(filtered, hqla)
    result["mata_uang"] = currency
    result["nilai_dalam_idr"] = result["hqla_total"] * kurs_tengah_bi
    return result
```

Perhatikan: modul ini **memanggil ulang** `lcr_calculation()` dari
`lcr_engine.py` apa adanya (termasuk cap 75%-nya) — beda dari Survival Period
yang eksplisit tidak pakai cap. Jangan disamakan perlakuannya.

---

## 7. Modul 4 — Roll Over Funding Monitoring

Memantau ketergantungan pada perpanjangan pendanaan jatuh tempo. Laporan
bulanan, terpisah dari SPM (semesteran) meski satu keluarga laporan.

```python
# ilaap/roll_over.py

def roll_over_funding_ratio(maturing_funding_df, rolled_over_df, period):
    """
    maturing_funding_df: pendanaan yang jatuh tempo pada periode berjalan
    rolled_over_df: bagian dari maturing_funding_df yang diperpanjang
        (rollover) oleh counterparty yang sama atau setara

    Return: rasio roll-over per segmen (mis. per jenis counterparty:
        interbank, korporasi, ritel) dan tren dibanding periode sebelumnya
        (butuh riwayat — simpan hasil per periode ke folder audit, lihat §8).
    """
    by_segment = maturing_funding_df.groupby("segmen_nasabah")["nilai"].sum()
    rolled_by_segment = rolled_over_df.groupby("segmen_nasabah")["nilai"].sum()
    ratio = (rolled_by_segment / by_segment).fillna(0)
    return ratio.to_dict()
```

Data `rolled_over_df` kemungkinan tidak tersedia otomatis dari sheet sumber
existing — perlu klarifikasi apakah bank punya cara mengidentifikasi mana
pendanaan yang "diperpanjang oleh counterparty yang sama" vs "digantikan
pendanaan baru dari sumber berbeda". Jika tidak bisa dibedakan otomatis,
modul ini butuh input manual per periode.

---

## 8. Ekspor dan Pemetaan ke Lampiran

| Lampiran (SEOJK 26/2025) | Modul sumber | Format keluaran |
|---|---|---|
| Lampiran I — Format Laporan ILAAP | Gabungan seluruh modul + narasi manual | Excel + placeholder untuk narasi kualitatif |
| Lampiran III — LCR Mata Uang Asing Signifikan | `fx_significant.py` | Excel per mata uang |
| Lampiran IV — Survival Period Monitoring | `survival_period.py` | Excel dengan 19 kolom bucket sesuai format asli |

Pola ekspor mengikuti yang sudah ada di repo (`openpyxl`, isi templat dengan
format asli terjaga — lihat cara `lcr_engine.py`/`nsfr_engine.py` memetakan
ke `Template LCR.xlsx`/`Template NSFR.xlsx`). Buat templat serupa untuk
Lampiran III dan IV berdasarkan struktur tabel yang diekstrak di §5.1 (19
kolom bucket) dan §6.

---

## 9. Di Luar Lingkup — Likuiditas Intrahari & Intragrup

**Rekomendasi eksplisit: JANGAN implementasikan otomasi penuh untuk kedua
modul ini di fase sekarang.** Alasannya struktural, bukan soal effort:

- Likuiditas intrahari butuh data granularitas per-jam dari sistem
  pembayaran (RTGS/SKN/SWIFT), bukan ekstraksi harian dari core banking.
  Sumber datanya berbeda total dari seluruh sheet yang dipakai modul lain.
- Likuiditas intragrup butuh data dari entitas lain dalam grup (anak
  perusahaan/induk), yang kemungkinan besar bukan kewenangan Divisi
  Manajemen Risiko satu bank untuk diakses langsung.

**Yang disarankan sebagai pengganti:** buat halaman input manual sederhana
(`pages/10_Input_Manual_Intrahari_Intragrup.py`) yang menerima hasil rekap
dari sistem/tim lain sebagai angka ringkasan, lalu digabung ke Laporan ILAAP
gabungan (Lampiran I) sebagai lampiran terpisah. Ini konsisten dengan posisi
"perangkat kuantitatif pendukung ILAAP" yang sudah disepakati — bukan
otomasi penuh atas segala hal.

---

## 10. Perluasan Jejak Audit

Modul-modul di atas menghasilkan objek yang lebih kompleks dari LCR/NSFR
(ladder 19-bucket, bukan satu angka). Perluas `audit_log.py` existing:

```python
# ilaap/audit.py — melengkapi audit_log.py, bukan menggantikan

def log_survival_period_run(ladder_df, scenario_id, result, manifest):
    """Simpan: skenario yang dipakai, seluruh ladder per-bucket (bukan hanya
    angka akhir), titik defisit, dan hasil add-on. reconcile() versi ILAAP
    harus menjumlah ulang net_outflow_kumulatif secara independen dari hasil
    project_cashflow_ladder(), sama seperti reconcile() existing untuk LCR/NSFR."""
    ...
```

Prinsip `reconcile()` yang sudah ada di repo (hitung ulang independen,
bandingkan, PASS/FAIL) **wajib direplikasi** untuk Survival Period — ini
modul paling kompleks dan paling rawan bug pemetaan bucket yang salah tapi
"kelihatan masuk akal".

---

## 11. Rencana Kerja untuk Claude Code

Urutan task, masing-masing sebaiknya jadi sesi/PR terpisah:

1. **Refactor** `lcr_engine.py`: ekstrak `get_runoff_rate()`/`get_inflow_rate()`
   jadi fungsi reusable (§5.2). Jalankan test existing untuk pastikan LCR/NSFR
   agregat tidak berubah hasilnya setelah refactor.
2. **Modul 1** (`available_hqla.py`) + unit test. Butuh klarifikasi sumber
   data GWM/PLM (§4.3) sebelum mulai.
3. **Modul 2** (`survival_period.py`) — bertahap:
   a. `time_buckets.yaml` + `assign_bucket()` + unit test pemetaan bucket
   b. `project_cashflow_ladder()` untuk skenario `lcr_30_hari` saja dulu
   c. Validasi terhadap kasus uji Bank A (§5.6) — **gerbang wajib lulus**
      sebelum lanjut ke skenario lain
   d. Tambah skenario `benchmark_90_hari_*`
   e. `determine_survival_period()` — tandai `compute_add_on_percent()`
      sebagai belum diimplementasi sampai metodologi dikonfirmasi Bank (§5.5)
4. **Modul 6** (`funding_profile.py`) — Laporan Profil Pendanaan (laporan baru
   di versi final SEOJK, belum ada spesifikasi rinci di consultative paper
   2021 yang jadi acuan; perlu cek Lampiran resmi SEOJK 26/2025 untuk format
   pastinya sebelum implementasi).
5. **Modul 4** (`roll_over.py`) setelah struktur data tenor dari Modul 2 stabil.
6. **Modul 3** (`fx_significant.py`) — independen, bisa dikerjakan paralel
   dengan 4–5 jika ada lebih dari satu developer.
7. Ekspor Excel per lampiran (§8) dan halaman Streamlit terkait.
8. Perluasan jejak audit (§10) — kerjakan bersamaan dengan tiap modul, bukan
   di akhir.

---

## 12. Hal yang Wajib Dikonfirmasi Sebelum/Selama Implementasi

| # | Pertanyaan | Ke siapa |
|---|---|---|
| 1 | BUS/UUS atau BUK? (menentukan nomenklatur field) | Bank |
| 2 | Sumber data GWM dan PLM harian — otomatis atau input manual? | Divisi TI/Manajemen Risiko |
| 3 | Metodologi konversi shortfall survival period → persentase LCR add-on | Manajemen Risiko & Kepatuhan |
| 4 | Target survival period internal Bank (mis. 90 hari) — sudah ditetapkan? | Manajemen Risiko |
| 5 | Format resmi Lampiran Laporan Profil Pendanaan (SEOJK 26/2025) | Cek dokumen resmi SEOJK, bukan consultative paper 2021 |
| 6 | Cara mengidentifikasi "rolled over" vs "pendanaan baru" di data existing | Divisi TI |
| 7 | KBMI Bank per 31 Des 2025 (menentukan jadwal wajib lapor efektif) | Bank |
| 8 | Parameter skenario "enhance" (§5.4) — multiplier run-off tinggi, dll. | Manajemen Risiko |

**Item 5 penting:** spesifikasi di dokumen ini disusun dari consultative
paper 2021 karena itu yang diunggah. Sebelum implementasi Modul 6 (Profil
Pendanaan) khususnya, tarik dan baca **SEOJK No. 26/SEOJK.03/2025 beserta
lampirannya** dari situs resmi OJK — laporan ini tidak ada di draf 2021 dan
formatnya belum diverifikasi terhadap dokumen final.
