# HASIL QA — PayGuard CLI

Laporan QA untuk project **PayGuard CLI** (Python 3.14, TUI, stdlib saja, tanpa pip).
Acuan kontrak: [`SPESIFIKASI_PAYGUARD.md`](../SPESIFIKASI_PAYGUARD.md) (v1, §2–§7).

> **Ronde 2 — fitur pembayaran sidik jari X100C:** suite sudah diperbarui ke kontrak
> [`SPESIFIKASI_SIDIK_JARI.md`](../SPESIFIKASI_SIDIK_JARI.md) (menu utama 4 opsi,
> menu admin 8 opsi, `finger_id`, mock SOAP, checkout tanpa PIN) dengan **44 test
> baru** di `test_fingerprint.py`. Ringkasan status di **§10** dan verifikasi final
> ronde 2 di **§11**.
>
> **Ronde 3 — perangkat X100C nyata (deployment):** Lead mengubah
> `payguard/data/perangkat.json` asli menjadi mode **soap** (host `192.168.1.201`,
> com key `<com_key>`) untuk pemakaian nyata. `tests/fixtures/perangkat.json` **tetap
> mode simulasi** agar test hermetis; `perangkat.json` dikecualikan dari uji
> "fixtures byte-identik" (config deployment). Ringkasan: **§12**.
>
> **Ronde 5 — fitur HOLD KERANJANG:** tap sidik jari gagal saat checkout kini
> **menahan belanjaan** di `data/keranjang.json` + stok langsung dikurangi, bisa
> dilanjutkan lewat menu 4; admin punya submenu **Kelola Keranjang Tertahan**
> (menu admin 9 opsi, logout `9`). Suite + **17 test baru**
> (`test_hold_keranjang.py`). Ringkasan: **§13**.
>
> **Ronde 6 — data live berubah (stok/saldo/riwayat):** setelah pemakaian nyata
> (`P001` stok 10, Prabu saldo Rp999.350.000 + 1 transaksi Rp650.000, logs 12),
> 10 test yang masih hardcode nilai seed diubah menjadi **data-driven** (expected
> dihitung dari fixtures/data live). Config deployment dipisah ke `.env`; fixtures
> perangkat tetap **simulasi** (hermetis). Ringkasan: **§14**.
>
> **Ronde 7 — login sidik jari admin & top up oleh admin:** login sidik jari kini
> mengikuti **role** (admin -> Menu Admin, customer -> Menu Pelanggan); customer
> menu 1 hanya **Lihat Saldo** (top up dihapus); admin menu **10 opsi** dengan
> **9. Isi Saldo Pelanggan** dan logout **10**. Suite + **7 test baru** (total
> **147**); semua stdin admin (logout `9`->`10`) disesuaikan. Ringkasan: **§15**.
>
> Tabel di bawah ini adalah ringkasan ronde 1; status terbaru ada di **§11**
> (ronde 2), **§12** (ronde 3), **§13** (ronde 5), **§14** (ronde 6), dan **§15**
> (ronde 7).

| Item | Nilai |
|---|---|
| Tanggal verifikasi final | 2026-10-26 00:22–00:23 WIB |
| Status kode aplikasi | **FINAL / dibekukan** (tidak ada perubahan app/data selama verifikasi) |
| Python | 3.14.6 (MSC v.1944 64-bit) |
| Lokasi suite | `payguard/tests/` |
| Jumlah test | **77 test** (14 kelas) |
| Hasil verifikasi final | **OK — 0 failure, 0 error, exit code 0** |
| Durasi suite | ±10,8 detik (77 test, mayoritas subprocess TUI) |
| Spot-check independen | **6/6 skenario OK** (semuanya di salinan data) |
| Data asli | **tidak berubah** — SHA256 `payguard/data/*.json` sebelum == sesudah |
| Fixtures | masih **byte-identik** dengan `payguard/data/*.json` |
| `tests/_tmp` | **bersih** — tidak menyisakan folder |
| File di luar `payguard/tests/` | **tidak ada yang baru/berubah** (manifest app/data 12 file identik) |
| Dependensi | 100% stdlib (`unittest`, `subprocess`, `json`, `hashlib`, `pathlib`, `shutil`, `uuid`, `os`, `re`, `importlib`) |
| **Kesimpulan** | **LAYAK — FINAL: SEMUA LULUS** |

> Laporan ini memuat **status awal** (run #1–#2, §6) dan **verifikasi final**
> (run #3, §5 dan §9) atas kode aplikasi yang sudah dibekukan Lead.

---

## 1. File yang dibuat QA (hanya di `payguard/tests/`)

| File | Isi |
|---|---|
| `fixtures/users.json` | salinan **byte-identik** `payguard/data/users.json` |
| `fixtures/products.json` | salinan **byte-identik** `payguard/data/products.json` |
| `fixtures/logs.json` | salinan **byte-identik** `payguard/data/logs.json` |
| `test_payguard.py` | suite unittest stdlib (integrasi TUI + unit read-only) |
| `verifikasi_final.py` | verifikasi manual (bukan unittest): SHA256 sebelum/sesudah + jalankan suite + 6 spot-check independen + cek manifest app/data |
| `_run_final.log` | log bukti run langsung `python -m unittest discover -s tests -v` (verifikasi final) |
| `_verifikasi_final.log` | log bukti `python tests/verifikasi_final.py` (suite + integritas + spot-check) |

QA **tidak mengubah** file aplikasi (`main.py`, `auth.py`, `admin.py`, `customer.py`,
`risk_assistant.py`), `data_manager.py`, maupun `payguard/data/*.json`.

---

## 2. Cara menjalankan

Dari folder `payguard`:

```powershell
cd "C:\Users\Pongo\Downloads\cashless dasprog\payguard"
python -m unittest discover -s tests -v
```

Catatan: `unittest` menulis hasil ke **stderr**; kalau output di-redirect, pakai `2>&1`:

```powershell
python -m unittest discover -s tests -v 2>&1 | Tee-Object tests\_run.log
```

Spot-check manual + integritas data (SHA256 sebelum vs sesudah):

```powershell
python tests\verifikasi_final.py
```

Exit code 0 = semua test lulus, data asli identik, `tests/_tmp` bersih.

---

## 3. Isolasi pengujian & sandbox

Sesuai §0/§6 kontrak dan batasan sandbox mesin ini:

- **Tanpa `tempfile.mkdtemp()`** (gagal `PermissionError` di sandbox Windows ini).
  Folder kerja dibuat manual: `payguard/tests/_tmp/kasus_<uuid>` via `Path.mkdir()`.
- Setiap test integrasi:
  1. menyalin **semua** `payguard/*.py` + folder `data/` (dari `tests/fixtures/`)
     ke folder kerja;
  2. menjalankan `python <folder kerja>/main.py` dengan `cwd` = folder kerja,
     `input` = stdin TUI, `capture_output=True`, `text=True`,
     `encoding="utf-8"`, `errors="replace"`, `timeout=60`,
     `env` dengan `PYTHONIOENCODING=utf-8` dan `PYTHONDONTWRITEBYTECODE=1`.
- Karena `data_manager.DATA_DIR` diturunkan dari `__file__`, aplikasi yang dijalankan
  dari folder kerja **selalu** membaca/menulis `data/` salinan — **tidak pernah**
  data asli `payguard/data/`.
- `tearDown` menghapus folder kerja tiap test; `tearDownModule` menghapus
  `tests/_tmp` setelah seluruh suite.
- Unit test read-only (`auth`, `risk_assistant`, `data_manager`) mengimpor modul
  langsung dari folder `payguard` (`sys.path.insert`) dan **hanya** memanggil fungsi
  baca/hitung — tidak ada fungsi penulis (RegisterUser/LoginUser/CheckoutProcess dll.)
  yang dijalankan terhadap data asli.
- Assertion memeriksa **stdout** (pesan TUI) **dan isi JSON** hasil (`json.load`):
  saldo, stok, transaksi, log, status lock.

---

## 4. Inventaris test (77 test)

### 4.1 Integrasi TUI (65 test)

| Kelas | Jumlah | Cakupan |
|---|---:|---|
| `TestMenuUtama` | 2 | splash + menu utama, keluar exit code 0 & pesan terima kasih, pilihan invalid diulang |
| `TestAuthAlur` | 11 | login admin & customer sukses, PIN salah (admin/customer), username tidak ditemukan, **lockout 3x** + pesan + blokir login berikutnya, login sukses mereset `failed_attempts`, register sukses (+ langsung login & cek `pin_hash`/`salt`/default field), register duplikat, register PIN invalid (`abc`,`123`,`12a4`,kosong), username kosong (`""`, spasi) |
| `TestAdminCrud` | 13 | read semua produk (+ katalog kosong), create sukses (ID auto `P010`, log, produk lama tetap), create katalog kosong (`P001`), validasi name/harga/stok/kategori (9 kasus), update harga/stok sukses, update ID tidak ada, pilihan invalid, nilai invalid (4 kasus), delete batal/sukses/ID tidak ada |
| `TestAdminLogsUnlock` | 6 | lihat audit logs (format `[time] username: action - detail`, seed log tampil), hanya 20 log terakhir, unlock akun `andi` (seed terkunci) lalu login, unlock akun tidak terkunci, username tidak ada, lockout → admin unlock → login kembali |
| `TestCustomerTopup` | 2 | top up sukses (saldo & log TOPUP), nominal invalid (`abc`,`0`,`-50000`,kosong) data tidak berubah |
| `TestCustomerMarketplace` | 9 | cari produk ada (format baris `id | nama | Rp | stok n | kategori`), case-insensitive + kata kunci ID, multi hasil (`premium`), tidak ditemukan, stok habis `P009`, ID tidak ada, jumlah invalid (`999`,`0`,`-1`,`abc`,`2.5`), tambah ke keranjang, **cart gabung item sama** (x2 + x3 = x5) |
| `TestCustomerSort` | 5 | 4 opsi pengurutan (termurah/termahal/A-Z/stok terbanyak) dicek urutan barisnya, pilihan invalid |
| `TestCustomerCheckout` | 6 | checkout sukses (saldo & stok berkurang, transaksi masuk `users.json` + field benar, log `CHECKOUT_SUCCESS_RP_<total>` detail = ID, resi, riwayat run berikutnya), saldo kurang (data tidak berubah), PIN salah (data tidak berubah, `failed_attempts` tidak bertambah), keranjang kosong, **saldo pas == total** (batas `saldo < total`), **harga & stok terbaru** dari `products.json` |
| `TestRiskShield` | 5 | level AMAN (auto lanjut, tanpa pertanyaan), PERINGATAN SEDANG batal `n`, PERINGATAN SEDANG lanjut `y`, RISIKO TINGGI batal untuk string selain `SAYA YAKIN` (`ya`, `saya yakin`, `YAKIN`), RISIKO TINGGI lanjut dengan `SAYA YAKIN` (skor 5, dua warning, saldo/stok/transaksi benar) |
| `TestCustomerRiwayat` | 2 | riwayat transaksi lama budi + format baris kontrak + track record (jumlah/total/rata-rata), riwayat kosong |
| `TestMenuInvalid` | 2 | pilihan invalid pada menu admin & menu pelanggan (menu diulang, logout tetap normal) |
| `TestIntegritasData` | 2 | fixtures **byte-identik** dengan data asli, fixture JSON valid & struktur seed lengkap |
| `TestZZIntegritasAkhir` | 2 | SHA256 data asli sebelum == sesudah suite, `tests/_tmp` bersih (kelas sengaja berawalan `ZZ` agar dijalankan **terakhir**) |

### 4.2 Unit test read-only (10 test)

| Test | Cakupan |
|---|---|
| `test_hash_password_dengan_salt_tetap_cocok_pin_hash_seed` | `HashPasswordWithSalt(pin, salt_seed)` untuk 4 akun seed == `pin_hash` di `users.json` & `sha256(pin+salt)` |
| `test_hash_password_dengan_salt_baru` | salt baru 16 hex, hash = `sha256(pin+salt)`, salt berbeda tiap panggilan |
| `test_generate_random_hex` | default 16 hex, panjang custom 8, acak (10 sampel unik) |
| `test_verify_pin` | PIN seed benar/salah untuk 4 akun, **tidak** mengubah `failed_attempts`/`is_locked` |
| `test_calculate_today_expenses` | hanya transaksi tanggal hari ini (2 transaksi hari ini = 12.500,5), kemarin & 2020 tidak dihitung, list kosong/`None` = 0 |
| `test_evaluate_purchase_risk_kombinasi_indikator` | skor **0/2/3/4/5/7** dari kombinasi 3 indikator + **batas tepat** (sisa == 30%, today+total == limit, sisa == 100.000) + teks 3 warning + tipe `int`/`list` |
| `test_evaluate_purchase_risk_memakai_pengeluaran_hari_ini` | transaksi hari ini ikut dihitung ke indikator limit, transaksi kemarin tidak |
| `test_rupiah` | `Rp0`, `Rp999`, `Rp14.000`, `Rp1.212.000`, `Rp1.000.000`, float, negatif |
| `test_id_produk_baru` | `P010` dari seed, `P001` dari katalog kosong, `P101` dari `P100` |
| `test_waktu_sekarang` | format `YYYY-MM-DDTHH:MM:SS` |

### 4.3 Skenario khusus sesuai kontrak

- **Risk medium** (`skor 2 ≤ 3`): `siti` beli Beras 5kg x2 = 130.000 (sisa 20.000 < 30% dari 150.000).
- **Risk high** (`skor 5 > 3`): `budi` top up 400.000 → saldo 900.000, lalu checkout
  Headset Gaming x2 = 700.000 (**> daily_limit 500.000**, sisa 200.000 < 30% × 900.000).
- Transaksi lama budi (2026-10-20) **tidak** dihitung sebagai pengeluaran hari ini.
- Batas saldo: `saldo < total` gagal, `saldo == total` berhasil (skor 4 → wajib `SAYA YAKIN`).

---

## 5. Hasil verifikasi final (kode dibekukan)

Verifikasi final dijalankan **2026-10-26 00:22–00:23 WIB** setelah Lead menyatakan
kode aplikasi FINAL dan tidak ada perubahan kode app/data. Dua perintah dijalankan
terpisah dari folder `payguard`.

### 5.1 `python -m unittest discover -s tests -v`

```text
Ran 77 tests in 10.536s

OK
```

- Exit code: **0**
- Test OK: **77** — failure: **0**, error: **0**
- Durasi wall-clock: **10,75 detik**
- Log bukti: `tests/_run_final.log`

### 5.2 `python tests\verifikasi_final.py`

```text
[1] SHA256 payguard/data/*.json SEBELUM suite: (3 file, lihat §5.3)
[2] Fixtures byte-identik dengan data asli: YA
[4] Ringkasan test: exit code=0, durasi=10.5 detik, jumlah test=77
[6] Data asli identik sebelum vs sesudah suite: YA
[7] tests/_tmp bersih setelah suite: YA
[8] Hasil spot-check: 6/6 skenario OK
[9] INTEGRITAS AKHIR:
    (a) SHA256 data asli identik sebelum vs sesudah seluruh verifikasi: YA
    (b) fixtures masih byte-identik dengan data asli: YA
    (c) tests/_tmp tidak menyisakan folder: YA
    (d) manifest app/data tidak berubah: YA (12 file)
HASIL VERIFIKASI FINAL: LULUS
```

- Exit code: **0**, durasi ±12,0 detik
- Log bukti: `tests/_verifikasi_final.log`

### 5.3 Bukti integritas data (SHA256)

| File | SEBELUM verifikasi | SESUDAH verifikasi | Status |
|---|---|---|---|
| `users.json` | `1d2c4c5801bb1dffb0b8f570ffb08d14ecd220ce974c8d24eb8cce1c790cfe31` | `1d2c4c5801bb1dffb0b8f570ffb08d14ecd220ce974c8d24eb8cce1c790cfe31` | identik |
| `products.json` | `f427112c23fc43739d14f82c5f57dee3a0463f3e41966ac12e481684d4f3567a` | `f427112c23fc43739d14f82c5f57dee3a0463f3e41966ac12e481684d4f3567a` | identik |
| `logs.json` | `390ea0bbad0e1d9c8e69ef0c328e7c07819b3bdcd4ad3d813fc000a2840f26a5` | `390ea0bbad0e1d9c8e69ef0c328e7c07819b3bdcd4ad3d813fc000a2840f26a5` | identik |

- Fixtures `tests/fixtures/*.json` = salinan byte-identik data asli: **YA**
- `tests/_tmp` tidak menyisakan folder: **YA**
- Tidak ada file baru/berubah/hilang di luar `payguard/tests/` (manifest app/data
  **12 file** identik sebelum vs sesudah suite + spot-check): **YA**

### 5.4 Spot-check independen (6/6 OK, semua di salinan data)

| # | Skenario | Bukti kunci (OK) |
|---|---|---|
| 1 | admin login → create produk → update stok → delete → logout; customer lihat katalog | 3 run exit 0; `P010` harga 12345 & stok 3 setelah update; setelah delete `products.json` kembali = seed; katalog customer menampilkan 9 produk seed, produk uji hilang |
| 2 | budi top up 100.000 → beli Beras 5kg x1 checkout (risk AMAN) | saldo 600.000 → **535.000**; stok P001 20 → **19**; transaksi total Rp65.000 risk 0; log `TOPUP` + `CHECKOUT_SUCCESS_RP_65000`; exit 0 |
| 3 | siti beli Cokelat Premium x3 (risk PERINGATAN SEDANG) jawab `n` | `users.json` & `products.json` identik seed; log baru **hanya** `LOGIN_SUCCESS` + `LOGOUT`; exit 0 |
| 4 | siti beli Cokelat Premium x3 jawab `y` + PIN 222222 | saldo → **75.000**; stok P006 → **12**; transaksi total Rp75.000 risk 2; log `CHECKOUT_SUCCESS_RP_75000`; exit 0 |
| 5 | lockout siti 3x PIN salah → admin unlock → siti login | `is_locked=true`/`failed_attempts=3` + log `ACCOUNT_LOCKED_BRUTEFORCE`; setelah unlock `is_locked=false`/`failed_attempts=0` + log `UNLOCK_ACCOUNT`; siti login sukses; exit 0 |
| 6 | register `rina`/`999999` → login → top up → beli → logout | exit 0; saldo akhir **46.000**; stok P005 → **98**; transaksi Rp4.000 risk 2; log rina: `REGISTER`, `LOGIN_SUCCESS`, `TOPUP`, `CHECKOUT_SUCCESS_RP_4000`, `LOGOUT` |

### 5.5 Kesimpulan hasil

Tidak ada failure pada suite maupun spot-check; seluruh aturan bisnis §5 dan
kriteria penerimaan §7 terpenuhi pada kode final. Lihat **§9 Kesimpulan**.

---

## 6. Riwayat status (transparansi QA)

| Run | Jumlah | Hasil | Keterangan |
|---|---:|---|---|
| Run #1 (status awal) | 71 | 1 failure | `TestAdminCrud.test_read_semua_produk`: format baris **Read** produk memakai stok polos (`... | Rp65.000 | 20 | Needs`), sedangkan test semula menuntut label `stok 20` seperti format **search/sort**. Kontrak §4.5.2 hanya menyebut "header + baris" tanpa merinci format, jadi assertion Read dilonggarkan (label `stok ` opsional) — **bukan bug aplikasi**. Format eksplisit §4.4.2/§4.4.3 tetap diuji ketat dan **lolos**. |
| Run #2 | 77 | **OK** | Ditambah 6 test penguatan: katalog kosong (read/create), reset `failed_attempts`, saldo pas == total, harga/stok terbaru, audit log hanya 20 terakhir, plus batas indikator risk. Semua lulus. |
| Run #3 — **verifikasi final** (kode dibekukan) | 77 | **OK — FINAL: SEMUA LULUS** | Run langsung `python -m unittest discover -s tests -v`: 77 OK, exit 0, ±10,8 detik. `python tests\verifikasi_final.py`: exit 0, 6/6 spot-check OK, integritas (a)–(d) YA, data asli identik. |

Catatan: saat QA mulai, kelima modul aplikasi (`main.py`, `auth.py`, `admin.py`,
`customer.py`, `risk_assistant.py`) sudah tersedia; tidak ada kegagalan besar
"modul belum lengkap". Kemungkinan failure yang ditemui hanya pada assertion
format (lihat §7).

---

## 7. Catatan & ambiguitas kontrak (untuk Lead)

1. **Format baris `ReadAllProducts` (§4.5.2)** — kontrak hanya menulis header
   `ID | Nama | Harga | Stok | Kategori` + "baris", tanpa format baris eksplisit.
   Implementasi: `P001 | Beras 5kg | Rp65.000 | 20 | Needs` (stok polos, cocok
   dengan header). Format eksplisit `... | stok <n> | ...` hanya diwajibkan pada
   search (§4.4.2) & sort (§4.4.3) — dan implementasi **sudah** mematuhinya.
   Test Read saat ini toleran (label `stok ` opsional). Jika ingin seragam,
   minta Anggota 1 memakai `FormatProductRow` yang sama dan ketatkan test.
2. **`DisplaySystemLogs` (§4.5.5)** — kontrak menampilkan format
   `[time] username: action - detail`. Implementasi mencetak
   `[time] username: action` **tanpa** ` - ` bila `detail` kosong (mis. LOGIN_SUCCESS,
   LOGOUT). Ini kosmetik; test hanya mewajibkan action & detail (bila ada) tampil.
3. **Harga keranjang vs harga terbaru (§5)** — `customer.py` menyimpan harga saat
   `AddToCart`, lalu membaca ulang `products.json` saat checkout untuk stok &
   kategori. Dalam satu proses TUI, admin dan customer tidak aktif bersamaan,
   sehingga harga tidak bisa berubah di tengah sesi customer. Test "harga & stok
   terbaru" menguji perubahan admin → sesi customer berikutnya dalam proses yang
   sama, dan **lolos**.
4. **Unlock akun (§4.5.6)** — kontrak menyebut "username pelanggan"; implementasi
   juga mengizinkan unlock akun admin yang terkunci. Tidak diuji sebagai kegagalan
   (tidak melanggar aturan bisnis §5).
5. **Risk Shield batas medium (§4.3)** — `score <= 3` → PERINGATAN SEDANG, selain
   itu RISIKO TINGGI. Kombinasi skor yang mungkin: 2, 3 (medium) dan 4, 5, 7
   (tinggi). Kasus "saldo pas total" menghasilkan skor 4 sehingga wajib `SAYA
   YAKIN`; sudah diuji sesuai rumus kontrak.
6. **Perbandingan `SAYA YAKIN`** — kontrak "input persis `SAYA YAKIN` (setelah
   strip)". Implementasi: `jawab.strip() == 'SAYA YAKIN'` (case-sensitive). Test
   memastikan `ya`, `saya yakin`, `YAKIN` **batal**, dan `SAYA YAKIN` lanjut.
7. **Toleransi konfirmasi medium** — kontrak "input y/y"; implementasi menerima
   `y`/`Y` (`.lower() == 'y'`). Test memakai `y` dan `n` (huruf kecil) saja.
8. **PIN register** — divalidasi `.isdigit()` dan panjang ≥ 4; test memakai
   `abc`, `123`, `12a4`, `` (kosong) sebagai invalid dan `1234`/`4321` sebagai valid.

---

## 8. Pemetaan kriteria penerimaan (§7)

| Kriteria §7 | Bukti test |
|---|---|
| 1. 6 modul ada, impor sesuai aturan, tidak circular | seluruh test integrasi berjalan (impor `main -> auth/admin/customer -> data_manager/risk_assistant`) |
| 2. TUI penuh: splash → login/register → menu admin/pelanggan → logout | `TestMenuUtama`, `TestAuthAlur`, `TestAdminCrud`, `TestCustomer*`, `TestMenuInvalid` |
| 3. CRUD produk tervalidasi; stok berkurang saat checkout | `TestAdminCrud` (13 test), `TestCustomerCheckout` (`assert_stok`), `TestCustomerSort/Marketplace` |
| 4. Risk Shield 3 indikator + status AMAN/PERINGATAN SEDANG/RISIKO TINGGI + bisa batal | `TestRiskShield` (5 test) + `TestUnitModul` (risk) |
| 5. Lockout 3x + admin unlock | `TestAuthAlur.test_lockout_setelah_tiga_kali_pin_salah`, `TestAdminLogsUnlock` (3 test unlock) |
| 6. Persist ke JSON; transaksi & log bertambah (append-only) | `TestCustomerCheckout`, `TestAdminLogsUnlock`, `assert_log_lama_utuh`, verifikasi JSON |
| 7. Test suite lulus; data asli tidak berubah | 77 test OK; check SHA256 `TestZZIntegritasAkhir` + `verifikasi_final.py` |
| 8. Gaya kode mengikuti `cashless` (TUI, prosedural, pesan Indonesia) | tidak diuji otomatis (review kode); test memverifikasi pesan TUI berbahasa Indonesia sesuai kontrak |

---

## 9. Kesimpulan verifikasi final

**LAYAK** — **FINAL: SEMUA LULUS**.

- 77/77 test OK (0 failure, 0 error), suite exit code **0** (±10,8 detik).
- 6/6 spot-check independen OK — semua dijalankan pada **salinan** data, bukan data asli.
- Integritas: SHA256 `payguard/data/*.json` identik sebelum vs sesudah; fixtures
  byte-identik; `tests/_tmp` bersih; tidak ada file baru/berubah/hilang di luar
  `payguard/tests/` (manifest app/data 12 file identik).
- Ambiguitas yang tercatat di §7 (format baris `ReadAllProducts` dengan stok polos
  `20`, dan log tanpa detail dicetak tanpa `" - "`) sudah diterima Lead dan
  **tidak perlu diperbaiki di app**; test tetap toleran seperti sekarang.
- Kode aplikasi **FINAL dan dibekukan** selama verifikasi; QA hanya menulis di
  `payguard/tests/`.

Perintah reproduksi:

```powershell
cd "C:\Users\Pongo\Downloads\cashless dasprog\payguard"
python -m unittest discover -s tests -v
python tests\verifikasi_final.py
```

Jika ada perubahan kode aplikasi setelah laporan ini, suite harus dijalankan ulang
(hasil run di laporan ini tidak berlaku untuk kode yang berubah).

---

## 10. Ronde 2 — Fitur Pembayaran Sidik Jari X100C (status awal, siap verifikasi final)

Acuan: [`SPESIFIKASI_SIDIK_JARI.md`](../SPESIFIKASI_SIDIK_JARI.md) §1–§7 +
[`SPESIFIKASI_PAYGUARD.md`](../SPESIFIKASI_PAYGUARD.md) versi terbaru. Tanggal status:
**2026-11-03**. QA hanya menulis di `payguard/tests/`; file app/data asli tidak diubah.

### 10.1 Fixtures disalin ulang (data asli terbaru)

Data asli sekarang: **5 user** (bertambah `NaNas`), field baru `finger_id`
(`budi` 1001, `siti` 1002, `andi` 1003, `admin`/`NaNas` `""`), `budi.failed_attempts=1`,
dan file baru `data/perangkat.json`. Fixtures disalin ulang **byte-identik**:

| File | SHA256 (data asli == fixtures) |
|---|---|
| `users.json` | `d285c9d3ed4a19d44ddbeafed7593f175bda8e76295eefd8860c8754d977380c` |
| `products.json` | `f427112c23fc43739d14f82c5f57dee3a0463f3e41966ac12e481684d4f3567a` |
| `logs.json` | `7f3cc6c194237ea82bc16be4424e26cf0aa72179a4f8ef3b044cae02e1d7c620` |
| `perangkat.json` (baru) | `20be12ca3d71389ff3d1a044c893da86805ce755216cc47cf1e5f5bc590b4712` |

Catatan: `data/finger_state.json` adalah state runtime — **tidak** ada di fixtures
maupun data asli (ada test khusus yang memastikan).

### 10.2 Update test lama (`test_payguard.py`, tetap 77 test)

- Menu utama sekarang **4 opsi** (keluar `4`), menu admin **8 opsi** (logout `8`);
  label & prompt menu di-assert ulang; **seluruh skenario stdin** disesuaikan —
  tidak ada lagi input `3` untuk keluar (kini = Login Sidik Jari).
- Lockout & unlock-after-lockout memakai `siti` (seed `budi.failed_attempts=1`
  sehingga bukan titik awal ideal lagi); reset `failed_attempts` budi
  dinormalisasi di helper data.
- Register: user baru wajib mendapat `finger_id == ""`.
- Loop pemeriksaan "user lain tidak berubah" dibuat dinamis terhadap 5 user.
- `verifikasi_final.py`: nomor menu baru + **3 spot-check sidik jari** baru
  (admin kelola sidik jari, login+checkout tanpa PIN, protokol SOAP & host mati)
  → total **9 skenario**.
- Runner subprocess mendapat retry khusus flake Windows (`os.replace`
  `PermissionError` sesaat karena antivirus/indexer) — tidak menutupi bug app.

### 10.3 Test baru `test_fingerprint.py` (44 test)

| Kelas | Jumlah | Cakupan |
|---|---:|---|
| `TestUnitFingerprint` | 13 | `buat_xml` root=perintah (GetAttLog/GetUserInfo, tanpa `<Command>`), `parse_rows` (2 Row), `kejadian_simulasi` + `kunci_kejadian`, `cari_user_dari_pin` (1001/1002/1003/9999/""), `baca_state`/`simpan_state` atomic (tanpa `.tmp` sisa), dedupe state, event kadaluwarsa, replay antar-proses via `finger_state.json`, `baca_perangkat` default/override/file rusak/refresh tanpa cache, demo `fingerprint.py` read-only |
| `TestMockPerangkat` | 6 | mock `socketserver` TCP `127.0.0.1:<port acak>`: `get_attlog` + format request `POST /iWsService` (`Content-Length`, `Content-Type: text/xml`, root `<GetAttLog>`, `<PIN>All</PIN>`, `ArgComKey`), `tes_koneksi` OK, `get_user_info` dikenal/tidak, event fresh vs stale, host mati → `OSError`/`TimeoutError`, mock **menolak wrapper `<Command>` dengan HTTP 400** |
| `TestAdminSidikJari` | 8 | lihat daftar (`budi -> PIN 1001` dst, admin/NaNas tidak tampil), daftar sukses + log `FINGER_ENROLL` (`NaNas:2001`), validasi username tidak ada/PIN kosong/PIN bukan angka/PIN duplikat, duplikat antar akun baru, hapus + log `FINGER_UNENROLL`, hapus tanpa pendaftaran, tes koneksi mode simulasi, pilihan invalid |
| `TestLoginSidikJari` | 5 | login `budi` 1001 → menu pelanggan, `siti` 1002, `andi` 1003 **terkunci ditolak**, PIN 9999 tak dikenal, input kosong kembali menu (tidak menggantung) |
| `TestCheckoutSidikJari` | 4 | checkout sidik jari **sukses tanpa PIN** (saldo 496.000, stok P005 98, transaksi baru, log `CHECKOUT_FINGER_RP_4000` detail trx, bukan `CHECKOUT_SUCCESS_*`), sidik jari salah (1002) → `Sidik jari tidak cocok.` + `Transaksi dibatalkan.` data tetap, PIN tak dikenal (9999) batal, regresi jalur PIN normal tetap minta PIN |
| `TestModeSoap` | 3 | login soap via mock + state event tersimpan di salinan, **replay tidak bisa** (login kedua → `Tidak ada sidik jari terbaca.`, hanya 1 menu pelanggan), soap host mati → pesan `Perangkat X100C tidak terhubung...` tanpa traceback & exit 0 |
| `TestIntegritasData` | 3 | fixtures byte-identik 4 file, struktur seed (`finger_id`, 5 user, `perangkat.json`), tidak ada `finger_state.json` di data asli/fixtures |
| `TestZZIntegritasAkhir` | 2 | SHA256 data asli sebelum==sesudah suite, `tests/_tmp` bersih |

### 10.4 Koreksi protokol X100C (§4.2 terbaru) — sudah diterapkan di test

Lead memperjelas §4.2: **root elemen XML = nama perintah**, bukan wrapper
`<Command>`; response root `<GetAttLogResponse>` / `<GetUserInfoResponse>`.
Test dan mock sudah disesuaikan + ditegakkan:

- `buat_xml` diuji: `assertIn("<GetAttLog>", xml)` +
  `assertIn("<PIN>All</PIN>", xml)` dan **tidak boleh** ada
  `<Command>`/`<CommandName>`;
- mock menentukan command dari **root tag** dan **menolak** request ber-wrapper
  `<Command>` dengan HTTP 400 (ada test khusus);
- mock membalas dengan root `<GetAttLogResponse>`/`<GetUserInfoResponse>`;
- parser test toleran terhadap atribut `xsi:*` tanpa deklarasi namespace
  (sesuai contoh kontrak).

### 10.5 Hasil run status awal ronde 2 (2026-11-03)

- `python -m unittest discover -s tests -v` dari `payguard`:
  **Ran 121 tests in ±24–27 detik → OK** (77 test lama + 44 test baru),
  0 failure/error, exit code 0 — **stabil 3× run berturut-turut**.
- `python tests\verifikasi_final.py`: **exit code 0** — 121 test OK,
  **9/9 spot-check OK**, integritas (a)–(d) YA, **HASIL VERIFIKASI FINAL: LULUS**
  (2× run). Log bukti: `tests/_verifikasi_ronde2_awal.log`.
- Integritas: SHA256 `payguard/data/*.json` sebelum == sesudah (4 file); fixtures
  byte-identik; `tests/_tmp` bersih; manifest app/data **15 file** tidak berubah;
  tidak ada `finger_state.json` dibuat di data asli.
- Catatan flake: sempat muncul `PermissionError [WinError 5]` pada `os.replace`
  data salinan (antivirus/indexer Windows) — ditangani retry khusus di runner
  test/verifikasi (bukan bug aplikasi); setelahnya 5 run berturut-turut hijau.

### 10.6 Catatan & ambiguitas ronde 2

1. Login sidik jari tidak mewajibkan action log tertentu di kontrak; test hanya
   memeriksa alur/menu (tidak mengunci `LOGIN_SUCCESS` untuk jalur sidik jari).
2. Test replay/integrasi soap memakai `batas_tunggu_detik` kecil (1 detik) di
   `perangkat.json` salinan agar suite tetap cepat; mode default aplikasi tetap 20.
3. State event (`finger_state.json`) hanya dibuat di folder kerja salinan; test
   integritas memastikan data asli tidak tersentuh.
4. `NaNas` (user buatan user dengan saldo sangat besar) tidak dipakai pada alur
   checkout test agar tidak mengubah ekspektasi saldo seed; hanya dipakai untuk
   skenario enroll/hapus sidik jari.
5. Retry flake Windows di runner bukan "meloloskan bug": hanya aktif bila exit 1 +
   `PermissionError` + `Access is denied/WinError 5`; kegagalan assertion/logika
   tetap gagal normal.
6. `fingerprint.py`, `main.py`, `admin.py`, `customer.py` sudah berisi fitur
   X100C saat status ini diambil (protokol root-tag sudah benar); Lead tetap akan
   mengabari bila kode dibekukan untuk verifikasi final.

### 10.7 Status

**Sudah diverifikasi final** pada kode beku — hasil **LAYAK / FINAL: SEMUA LULUS**
(lihat **§11**). Perintah reproduksi sama seperti §2:

```powershell
cd "C:\Users\Pongo\Downloads\cashless dasprog\payguard"
python -m unittest discover -s tests -v
python tests\verifikasi_final.py
```

---

## 11. Verifikasi Final Ronde 2 (kode beku) — LAYAK

Dijalankan **2026-11-03 13:03 WIB** setelah Lead menyatakan kode aplikasi FINAL dan
dibekukan. QA hanya mengubah `payguard/tests/`; file app/data tidak disentuh.

### 11.1 Hasil run

| Perintah | Hasil |
|---|---|
| `python -m unittest discover -s tests -v` (cwd `payguard`) | **Ran 121 tests in 27.204s → OK**; 121 ok, 0 failure, 0 error; **exit code 0** (wall ±27,4 detik). Log: `_run_final_ronde2.log` |
| `python tests\verifikasi_final.py` | Dijalankan **2×**, keduanya **exit code 0 — LULUS**: 121 test OK, **12/12 spot-check OK**, integritas (a)–(e) YA (durasi ±31–32 detik/run). Log: `_verifikasi_final_ronde2.log` |

Rincian suite: 77 test ronde 1 (`test_payguard.py`, sudah diupdate ke menu baru) +
44 test baru (`test_fingerprint.py`) = **121 test**.

### 11.2 Integritas (sebelum vs sesudah verifikasi)

| File | SHA256 sebelum == sesudah |
|---|---|
| `users.json` | `d285c9d3ed4a19d44ddbeafed7593f175bda8e76295eefd8860c8754d977380c` |
| `products.json` | `f427112c23fc43739d14f82c5f57dee3a0463f3e41966ac12e481684d4f3567a` |
| `logs.json` | `7f3cc6c194237ea82bc16be4424e26cf0aa72179a4f8ef3b044cae02e1d7c620` |
| `perangkat.json` | `20be12ca3d71389ff3d1a044c893da86805ce755216cc47cf1e5f5bc590b4712` |

- (a) SHA256 data asli identik sebelum vs sesudah seluruh verifikasi: **YA**
- (b) fixtures `tests/fixtures/*.json` byte-identik dengan data asli: **YA**
- (c) `tests/_tmp` tidak menyisakan folder: **YA**
- (d) manifest app/data **15 file** tidak berubah/tidak ada file baru di luar
  `payguard/tests/`: **YA**
- (e) tidak ada `payguard/data/finger_state.json` di data asli: **YA**

### 11.3 Spot-check independen (12/12 OK, semua pada salinan data)

| # | Skenario | Status / bukti kunci |
|---|---|---|
| 1 | admin create+update+delete produk → customer lihat katalog | OK — katalog kembali = seed |
| 2 | budi top up 100.000 + checkout Beras 5kg x1 (risk AMAN) | OK — saldo 535.000, stok P001 19, log `CHECKOUT_SUCCESS_RP_65000` |
| 3 | siti risk PERINGATAN SEDANG dijawab `n` | OK — data & stok tetap, log hanya LOGIN/LOGOUT |
| 4 | siti risk PERINGATAN SEDANG dijawab `y` + PIN | OK — saldo 75.000, stok P006 12, risk 2 |
| 5 | lockout siti 3x → admin unlock → siti login | OK — locked/unlocked + log lockout/unlock |
| 6 | register `rina` → login → top up → beli → logout | OK — exit 0, data & log benar |
| 7 | admin kelola sidik jari X100C (daftar/hapus/lihat + validasi) | OK — enroll NaNas 2001, list, hapus; tolak username tak ada/PIN kosong/non-angka/duplikat `1001` milik budi; log `FINGER_ENROLL`/`FINGER_UNENROLL` |
| 8 | simulasi login sidik jari budi 1001 → checkout tanpa PIN | OK — saldo 496.000, stok P005 98, trx tercatat, log `CHECKOUT_FINGER_RP_4000` (tanpa `CHECKOUT_SUCCESS_*`) |
| 9 | protokol SOAP root=perintah + soap host mati | OK — `buat_xml` root `<GetAttLog>` tanpa `<Command>`; host mati → pesan error kontrak, tanpa traceback, exit 0 |
| 10 | **mock X100C SOAP: login via GetAttLog + checkout tap kedua** | OK — login <GetAttLog>, tap kedua mengotorisasi, saldo 496.000/stok 98/log `CHECKOUT_FINGER_RP_4000`, state 2 event; request root tag & HTTP 200 |
| 11 | **mock X100C SOAP: replay & event kadaluwarsa ditolak** | OK — login kedua → `Tidak ada sidik jari terbaca.`, menu pelanggan hanya 1×; event 2 jam lalu ditolak |
| 12 | **tap sidik jari user lain saat checkout → batal** | OK — `Sidik jari tidak cocok.` + `Transaksi dibatalkan.`; saldo/stok/transaksi/log tidak berubah |

### 11.4 Catatan verifikasi final

- Kode aplikasi tidak berubah selama verifikasi (manifest 15 file identik);
  tidak ada perubahan `data/*.json` dan tidak ada state runtime bocor ke data asli.
- Protokol X100C final sesuai koreksi §4.2: root elemen = nama perintah; mock
  menolak wrapper `<Command>` dengan HTTP 400; response root
  `<GetAttLogResponse>`/`<GetUserInfoResponse>`.
- Flake Windows `PermissionError [WinError 5]` pada `os.replace` data salinan
  (antivirus/indexer) tetap dimitigasi retry khusus di runner test/verifikasi;
  bukan bug aplikasi — run final stabil (suite langsung + 2× verifikasi hijau).
- Catatan & ambiguitas ronde 2 di §10.6 tetap berlaku; tidak ada failure tersisa.

### 11.5 Kesimpulan

**LAYAK — FINAL: SEMUA LULUS.**

Seluruh kriteria penerimaan `SPESIFIKASI_SIDIK_JARI.md` §7 (1–7) dan
`SPESIFIKASI_PAYGUARD.md` §7 terpenuhi pada kode final: mode simulasi & SOAP,
mapping sidik jari admin, klien X100C terhadap mock, anti-replay/event kadaluwarsa,
akun terkunci ditolak, checkout sidik jari tanpa PIN, data asli aman, dan suite
test lulus stabil.

---

## 12. Ronde 3 — Deployment perangkat X100C nyata vs fixture test (hermetis) — LULUS

Acuan: `task-13`. Konteks: perangkat **X100C asli aktif** di `192.168.1.201`
(webserver SOAP HTTP, **com key <com_key>**); Lead mengubah `payguard/data/perangkat.json`
asli untuk pemakaian nyata. QA hanya menulis di `payguard/tests/`; file app/data asli
(kode aplikasi & `data/perangkat.json` milik Lead) **tidak diubah**.

### 12.1 Konfigurasi deployment nyata vs fixture test

| Aspek | `payguard/data/perangkat.json` (DEPLOYMENT) | `tests/fixtures/perangkat.json` (TEST) |
|---|---|---|
| Mode | **`soap`** (perangkat nyata) | **`simulasi`** (hermetis, tanpa jaringan) |
| Host / port | `192.168.1.201` / `80` | `192.168.1.201` / `80` (tidak dipakai saat simulasi) |
| com_key | **`<com_key>`** | `0` |
| timeout / jendela / batas tunggu | 6 / 30 / 20 | 5 / 30 / 20 |
| Hash SHA256 | `3bf96cdc64256b8a198b18a548174f82c3f825a46d8cab19ca0e6009e8f87c2f` (dipantau, QA tidak mengubah) | `20be12ca3d71389ff3d1a044c893da86805ce755216cc47cf1e5f5bc590b4712` (tidak diubah QA) |

`perangkat.json` diperlakukan sebagai **konfigurasi deployment**, bukan data:
- fixture-nya **selalu mode `simulasi`** agar suite tidak pernah menyentuh device asli;
- fixture `perangkat.json` **dikecualikan** dari syarat "fixtures byte-identik dengan
  data asli"; hash config asli tetap dipantau supaya QA tidak mengubahnya;
- data `users.json`, `products.json`, `logs.json` **tetap wajib byte-identik**.

### 12.2 Perubahan test untuk pemisahan deployment ↔ test

- `test_fingerprint.py`:
  - `FIXTURE_IDENTIK_FILES = ("users.json","products.json","logs.json")`; helper
    `assert_fixtures_identik()` hanya membandingkan file DATA;
  - `test_fixtures_salinan_byte_identik` hanya DATA + test baru
    `test_perangkat_adalah_config_deployment_bukan_fixture_data` (fixture wajib
    simulasi, data asli boleh soap, config folder kerja wajib simulasi);
  - pengaman hermetis di `siapkan_app()`: test **fail** bila config di folder kerja
    bukan mode `simulasi` (mencegah fixture tak sengaja disalin dari deployment).
- `test_payguard.py`: `test_fixtures_salinan_byte_identik` hanya DATA; test baru
  `test_perangkat_deployment_dikecualikan_dari_byte_identik`; struktur dasar mengecek
  fixture `perangkat.json` mode simulasi; pengaman hermetis di `siapkan_app()`.
- `verifikasi_final.py`: cek **[2]** dipecah — fixtures DATA byte-identik +
  baris config perangkat (fixture `simulasi` vs data asli `soap`, dikecualikan);
  integritas akhir (b) hanya DATA dan **(f) baru**: fixtures/perangkat.json tetap
  mode simulasi; kelulusan mensyaratkan (b) dan (f).
- **Tidak ada test yang menghubungi `192.168.1.201`**: fixture mode simulasi +
  pengaman; seluruh uji SOAP memakai mock `127.0.0.1:<port acak>` atau host
  `127.0.0.1` tertutup. Dicek juga tidak ada koneksi TCP ke `192.168.1.201`.

### 12.3 Hasil run ronde 3 (2026-11-03 23:22–23:23 WIB)

- `python -m unittest discover -s tests -v` (cwd `payguard`):
  **Ran 123 tests in 25.014s → OK**; **123 ok**, 0 failure, 0 error;
  **exit code 0** (wall ±25,4 detik). Rincian: `test_payguard.py` **78 test** +
  `test_fingerprint.py` **45 test** (2 test pengaman config deployment baru vs ronde 2).
  Log: `_run_final_ronde3.log`.
- `python tests\verifikasi_final.py`: **exit code 0 — LULUS**; 123 test OK,
  **12/12 spot-check OK**, cek [2] fixtures DATA byte-identik **YA** + config
  perangkat (fixture simulasi, data soap, dikecualikan), integritas **(a)–(f) YA**;
  manifest app/data 15 file tidak berubah. Log: `_verifikasi_final_ronde3.log`.
- Integritas real data (sebelum == sesudah): `users.json`
  `d285c9d3…`, `products.json` `f427112c…`, `logs.json` `7f3cc6c1…`,
  `perangkat.json` `3bf96cdc…` (config deployment tidak berubah);
  fixtures/perangkat tetap `20be12ca…`.
- `tests/_tmp` bersih; tidak ada `payguard/data/finger_state.json`;
  tidak ada koneksi TCP ke `192.168.1.201`; tidak ada file baru/berubah di luar
  `payguard/tests/`.

### 12.4 Catatan deployment vs test

1. `data/perangkat.json` (mode soap, com key <com_key>) adalah **milik Lead untuk
   pemakaian device nyata** — QA tidak mengubahnya; nilainya dipantau lewat hash
   sebelum/sesudah suite.
2. Suite **selalu** menyalin `tests/fixtures/perangkat.json` (mode simulasi) ke folder
   kerja, sehingga pengujian tetap hermetis: login/checkout sidik jari di test memakai
   input `(SIMULASI) Masukkan ID perangkat:` atau mock lokal, bukan device fisik.
3. Bila `data/users.json`/`products.json`/`logs.json` berubah (mis. pemakaian nyata),
   fixtures file DATA tersebut perlu disalin ulang; `perangkat.json` **tidak**
   disalin dari data asli.
4. Mode `soap` di data asli hanya dipakai saat aplikasi dijalankan manual oleh Lead;
   test tidak membaca `data/perangkat.json` asli (selalu salinan fixture).

### 12.5 Kesimpulan ronde 3

**LAYAK — LULUS.** Deployment perangkat X100C nyata aktif (mode soap, com key
<com_key>) tanpa mengorbankan hermetisme test: **123 test OK**, 12/12 spot-check,
integritas (a)–(f) YA, `tests/_tmp` bersih, dan data asli (termasuk config deployment)
tidak berubah.

---

## 13. Ronde 5 — Fitur HOLD KERANJANG (sidik jari gagal) — LULUS

Acuan: [`SPESIFIKASI_HOLD_KERANJANG.md`](../SPESIFIKASI_HOLD_KERANJANG.md) §1–§7 +
`SPESIFIKASI_SIDIK_JARI.md`. QA hanya menulis `payguard/tests/` + `tests/fixtures/`;
kode app & data asli milik Lead tidak diubah.

### 13.1 Data & fixtures terbaru

Data asli terbaru dipakai sebagai basis (ada user baru hasil pemakaian nyata):
`Prabu` (saldo Rp1.000.000.000, `finger_id` `11733`), `logs.json` bertambah
(REGISTER/FINGER_ENROLL/LOGIN/TOPUP Prabu), dan file baru **`data/keranjang.json`**
(awal `[]`). Fixtures disalin ulang:

| File data | SHA256 (data asli == fixtures) |
|---|---|
| `users.json` | `ffe6fac8221f1c1276048ae83c674a49bb81ba77775ccd417565cf736e59c790` |
| `products.json` | `f427112c23fc43739d14f82c5f57dee3a0463f3e41966ac12e481684d4f3567a` |
| `logs.json` | `bfcba75a5b2cc62909f8f9c2f8d687b56745767ce11094c0806dc37c3765f4ca` |
| `keranjang.json` (baru) | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |

- `DATA_FILES` kini 5 file (termasuk `keranjang.json`) untuk disalin ke folder kerja
  dan dipantau hash-nya.
- `FIXTURE_IDENTIK_FILES` = users/products/logs/**keranjang** (byte-identik).
- `perangkat.json` tetap dikecualikan (config deployment; fixture simulasi) seperti §12.
- `finger_state.json` = runtime aplikasi nyata: tidak ikut fixtures; data asli boleh
  memilikinya (dicek JSON valid, bukan artefak test).
- Fixtures `perangkat.json` **tetap mode simulasi** → suite tetap hermetis, tidak
  menghubungi `192.168.1.201` (data asli tetap soap untuk pemakaian Lead).

### 13.2 Perubahan test lama

- Menu admin menjadi **9 opsi** (`8. Kelola Keranjang Tertahan`, `9. Logout Admin`,
  prompt `Pilih menu (1-9):`); semua skenario stdin logout admin `8` → `9`.
- Test `TestMenuInvalid.test_menu_admin_pilihan_invalid` memakai pilihan invalid
  `0`/`abc` (angka `9` kini logout yang sah).
- Test checkout sidik jari gagal di `test_fingerprint.py` diubah dari "batal & data
  tetap" menjadi "**hold keranjang**" sesuai kontrak baru (dua test lama diganti nama
  & assertion: stok turun, `keranjang.json` +1, saldo/transaksi tetap, log `HOLD_CART`).
- `keranjang.json` ditambahkan ke `siapkan_app`/`pulihkan_data`, integritas, dan
  `verifikasi_final.py` (DATA_FILES + cek [2]).

### 13.3 Test baru `test_hold_keranjang.py` (17 test)

| Kelas | Jumlah | Cakupan |
|---|---:|---|
| `TestUnitHelperHold` | 4 | `BacaKeranjangTertahan` (default `[]`), `SimpanKeranjangTertahan` (file atomic & konsisten), `CariKeranjangTertahan` (hold **terbaru** per user; `None` untuk yang tak ada), `HapusKeranjangTertahan` (ada/tidak), `TahanKeranjang` (record benar + stok turun + log `HOLD_CART` detail `<id>:<total>`), `TambahPercobaanKeranjang` (percobaan +1 persisten), `KembalikanStokKeranjang` (stok kembali) |
| `TestHoldKeranjang` | 8 | tap gagal #1 → hold (stok 100→98, keranjang +1, saldo/transaksi tetap, log `HOLD_CART`, pesan hold, cart memori kosong terbukti prompt resume); resume `n` → hold tetap; resume `y` + tap sukses → saldo 496.000, transaksi/log `CHECKOUT_FINGER_RP_4000`, hold hilang, stok **tidak** dobel; resume tap gagal lagi → `percobaan` 2, saldo/stok/transaksi tetap; hold terbaru dipakai saat resume (2 hold); jalur PIN salah **tanpa** hold; Risk Shield batal / saldo kurang **tanpa** hold |
| `TestAdminHoldKeranjang` | 5 | menu admin 9 opsi + prompt `(1-9)`; list format `<id> | user | Total <Rp> | percobaan <n> | items`; cancel `n` → "Pembatalan dibatalkan."; cancel `y` → stok kembali (98→100), hold hilang, log `HOLD_CANCEL`, saldo/transaksi tetap; list kosong; ID tidak ditemukan; submenu invalid |

### 13.4 Verifikasi hold di `verifikasi_final.py`

Spot-check ditambah/diubah (total **14 skenario**):
12. tap sidik jari user lain saat checkout → **hold** (bukan batal): stok turun,
    `keranjang.json` +1 record benar, saldo/transaksi tetap, log `HOLD_CART`;
13. resume hold lewat menu 4 (`y`) + tap sukses: saldo/transaksi/resi/log
    `CHECKOUT_FINGER_RP_4000`, hold hilang, stok tidak dobel;
14. admin lihat daftar hold + batalkan (`y`): stok kembali, hold hilang, log
    `HOLD_CANCEL`, saldo/transaksi tetap.

### 13.5 Hasil run ronde 5 (final 2026-11-03 23:53–23:54 WIB, setelah kode terbaru)

Catatan: `customer.py` sempat diperbarui anggota lain pada 23:47:12, sehingga run
pertama (23:46–23:47) diulang pada kode terbaru. Saat run terakhir juga terdeteksi
proses lain (Lead) menjalankan suite/verifikasi secara paralel + mengedit dokumen
(README/HASIL_TEST/SPESIFIKASI) dan membuat `_verif_lead.log`; verifikasi dibuat
tahan terhadap hal itu: yang **wajib** tidak berubah hanyalah **inti app/data**
(7 `*.py` + 5 `data/*.json`), sedangkan dokumen/artefak proses lain hanya dicatat.

- `python -m unittest discover -s tests -v` (kode final, 23:49 WIB):
  **Ran 140 tests in 29.245s → OK**; 140 ok, 0 failure/error, exit code **0**
  (wall ±29,4 detik). Rincian: `test_payguard.py` **78** + `test_fingerprint.py`
  **45** + `test_hold_keranjang.py` **17** = **140 test**.
  Log: `_run_final_ronde5.log`.
- `python tests\verifikasi_final.py` (23:54 WIB): exit code **0 — LULUS**;
  140 test OK, **14/14 spot-check OK**, cek [2] fixtures data
  (users/products/logs/keranjang) byte-identik **YA** + config perangkat
  dikecualikan, integritas **(a)–(f) YA**, **manifest inti app/data 12 file tidak
  berubah** (dokumen 5 file & artifak lain dicatat, bukan kegagalan).
  Log: `_verifikasi_final_ronde5.log`.
- Integritas real data (sebelum == sesudah): hash users/products/logs/keranjang/
  perangkat tidak berubah; fixtures data byte-identik; `tests/_tmp` bersih;
  `finger_state.json` runtime tervalidasi; tidak ada koneksi ke `192.168.1.201`.
- Hasil spot-check hold: tap salah → hold (stok turun, keranjang +1, saldo/transaksi
  tetap, log `HOLD_CART`) **OK**; resume `y` + tap sukses **OK**; admin cancel
  (stok kembali, log `HOLD_CANCEL`) **OK**.

### 13.6 Catatan ronde 5

1. Hold memakai **salinan** data di `tests/_tmp`; `data/keranjang.json` asli (deployment)
   tidak pernah ditulis oleh test — hash-nya dipantau sebelum/sesudah.
2. Bila pemakaian nyata menambah hold/user/log, fixtures data perlu disalin ulang
   (kecuali `perangkat.json`, yang tetap simulasi di fixtures).
3. Jumlah hold per user bisa >1; menu 4 memakai hold **terbaru** (diuji).
4. Anti-replay `finger_state.json` tidak diubah oleh alur hold (tetap dicatat di salinan).
5. Verifikasi final ronde ini dibuat tahan terhadap aktivitas Lead: perubahan
   **dokumen** (README/HASIL_TEST/SPESIFIKASI) dan **artefak non-kode** (mis.
   `_verif_lead.log` dari proses verifikasi Lead yang berjalan paralel) hanya
   dicatat sebagai catatan, tidak menggagalkan verifikasi; yang wajib identik
   hanya **inti app/data**: 7 `*.py` + 5 `data/*.json`. Karena ada run paralel
   yang sempat memakai `tests/_tmp` bersama, run final diulang saat idle dan
   LULUS stabil (140 test OK, 14/14 spot-check).

### 13.7 Kesimpulan ronde 5

**LAYAK — LULUS.** Kriteria `SPESIFIKASI_HOLD_KERANJANG.md` §7 (1–5) terpenuhi:
tap gagal tidak membatalkan belanjaan, stok berkurang sekali & tercatat sebagai hold;
resume sukses tanpa PIN dengan saldo/transaksi benar & stok tidak dobel; gagal
lanjutan menambah percobaan; admin bisa membatalkan & mengembalikan stok; test lama
tetap lulus (**140 test OK**, 14/14 spot-check, integritas aman).

---

## 14. Ronde 6 — Data live berubah: test **data-driven** — LULUS

Latar: user mengetes fitur hold lewat aplikasi asli sehingga data live berubah —
`products.json` **stok P001 = 10** (semula 20), `users.json` **Prabu saldo
Rp999.350.000 + 1 transaksi Rp650.000**, `logs.json` **12 entry**, `keranjang.json`
`[]`. Lead menyalin ulang fixtures dari data live. Akibatnya 10 test yang masih
**hardcode nilai seed** gagal meski aplikasi benar. Config deployment juga dipisah
ke `.env` (perangkat **tidak** lagi disimpan soap di `data/perangkat.json`; fixture
perangkat tetap **simulasi**, test tetap hermetis).

### 14.1 Perubahan: helper data-driven

Di base class (`test_payguard.DasarTest`, `test_fingerprint.DasarTest`) ditambah
helper yang membaca fixtures/data live saat test berjalan:

- `produk_fixture(pid)`, `harga_awal(pid)`, `stok_awal(pid)`, `saldo_awal(user)`,
  `user_fixture(user)`, `jumlah_trx_awal(user)`;
- `skor_risiko_fixture(user, total, kategori)` — menghitung skor Risk Shield yang
  diharapkan (termasuk transaksi hari ini) dari data fixtures;
- `konfirmasi_untuk_skor(skor)` — memilih `y` / `SAYA YAKIN` / tanpa konfirmasi;
- `urutan_produk_fixture(kunci, reverse)` — expected urutan sort dari data live;
- `rupiah_teks(angka)` untuk assertion pesan berformat Rupiah.

### 14.2 Test yang diperbaiki (10 failure → data-driven)

| Test | Perubahan |
|---|---|
| `TestAdminCrud.test_update_harga_sukses` | harga/stok "saat ini" dari fixtures (`P001`: Rp65.000, stok 10), bukan hardcode 20 |
| `TestCustomerMarketplace.test_search_produk_ada` | baris produk dari fixtures (harga/stok/nama live) |
| `test_search_case_insensitive_dan_kata_kunci_id` (3 subtest) | kata kunci & baris produk dihitung dari fixture |
| `TestCustomerSort.test_sort_stok_terbanyak` | urutan dihitung dari stok fixtures (P001=10 tidak lagi di posisi seed) |
| `TestCustomerCheckout.test_checkout_saldo_pas_total_berhasil` | pakai **user baru** `qabatas` + top up persis sebesar total (saldo == total) — lepas dari saldo seed |
| `TestRiskShield.test_risk_peringatan_sedang_lanjut_y` | total/saldo/stok/skor dihitung dari fixtures; konfirmasi & status mengikuti skor hasil hitung |
| `test_hold_keranjang.TestHoldKeranjang.test_risk_shield_batal_tidak_membuat_hold` | stok P001 dari fixtures; skor dihitung; skip jika data live tak lagi berstatus risk |
| `...test_saldo_kurang_tidak_membuat_hold` | produk+qty melebihi saldo dicari dinamis dari data live |

### 14.3 Test lain yang dijadikan dinamis (anti-regresi data live)

- Search/stok habis/multi-hasil, tambah keranjang, cart gabung, checkout sukses,
  checkout saldo kurang, PIN salah, top up, sort 4 opsi, riwayat/track record.
- **Risk Shield tinggi** diuji dengan **user baru `qa_high`** (top up
  `total + 100.000`; total dari harga P007 live) → skor 5 deterministik, tidak
  bergantung saldo/histori user seed.
- `test_hold_keranjang.py`: semua total/harga/stok/saldo hold, resume, admin
  list/cancel dihitung dari fixtures (`P005`/`budi`).
- `test_fingerprint.py`: helper hold (`_assert_hold_pertama`), checkout sidik jari
  sukses (`CHECKOUT_FINGER_RP_...`, saldo/stok/transaksi) dihitung dari data live.
- Asersi **hermetis**: `.env` deployment tidak ikut ke folder kerja test; fixture
  `perangkat.json` wajib mode simulasi.
- `verifikasi_final.py` spot-check dibuat fleksibel: S7 memilih customer tanpa
  `finger_id` + PIN unik dari fixtures; total hold/format daftar admin memakai
  harga+stok live; tidak ada spot yang mematok stok/saldo seed.

### 14.4 Hasil run ronde 6 (2026-11-04 00:46–00:48 WIB, serial)

- `python -m unittest discover -s tests -v`: **Ran 140 tests in 30.446s → OK**;
  140 ok, 0 failure/error, exit code **0** (78 `test_payguard` + 45
  `test_fingerprint` + 17 `test_hold_keranjang`).
  Log: `_run_final_ronde6.log`.
- `python tests\verifikasi_final.py`: exit code **0 — LULUS**; 140 test OK,
  **14/14 spot-check OK**, cek [2] fixtures data byte-identik **YA**, integritas
  **(a)–(f) YA**, manifest inti app/data 12 file tidak berubah.
  Log: `_verifikasi_final_ronde6.log`.
- Data live saat run (fixtures = data): `users.json`
  `3f65ce9543894fb528dc1ef801c971696baf1f9ba909f40cc89e909559869ff6`,
  `products.json` `261d19f4fa31a7b0ef1a5fb76f03f860e35c4705603b6bd132df4aa8ff06ccdc`,
  `logs.json` `abecc8ceb1cb38925250bcfefd337fd5577c0679a6d2f21c14327aeba10b59bc`,
  `keranjang.json` `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`;
  hash tidak berubah sebelum==sesudah suite; `tests/_tmp` bersih; tidak ada
  koneksi ke perangkat fisik.
- Scenario-premise yang tidak lagi cocok dengan data live (mis. skor bukan AMAN)
  memakai `skipTest` dengan alasan jelas — bukan failure palsu; data live yang
  benar-benar berubah tinggal disalin ulang ke fixtures (kecuali `perangkat.json`
  dan `.env` yang tetap simulasi/tidak disalin).

### 14.5 Kesimpulan ronde 6

**LAYAK — LULUS.** Tidak ada lagi test yang mematok nilai seed untuk stok/saldo/
riwayat yang berubah: **140 test OK** dan **14/14 spot-check** pada data live
terbaru, integritas data asli terjaga, suite tetap hermetis (fixtures simulasi;
`.env` tidak ikut).

---

## 15. Ronde 7 — Login sidik jari admin & top up oleh admin — LULUS

Kontrak: [`SPESIFIKASI_LOGIN_ADMIN_FINGER_DAN_TOPUP.md`](../SPESIFIKASI_LOGIN_ADMIN_FINGER_DAN_TOPUP.md).
Dua perubahan akses: (1) login sidik jari mengikuti **role** akun — `admin` ->
Menu Admin, `customer` -> Menu Pelanggan; (2) **top up hanya oleh admin**
(customer menu 1 = hanya `Saldo Anda: ...`).

### 15.1 Perubahan test (`payguard/tests/`)

1. **Menu admin 10 opsi**: `assert_menu_admin` memuat `9. Isi Saldo Pelanggan` &
   `10. Logout Admin` + prompt `Pilih menu (1-10):`; konstanta `LOGOUT_ADMIN`
   `"9\n"` -> `"10\n"`; semua skenario stdin admin (test + verifikasi) memakai
   logout `10`; test menu admin di `test_hold_keranjang` diperbarui ke 10 opsi.
2. **Customer menu 1**: `assert_menu_customer` -> `1. Lihat Saldo`; kelas
   `TestCustomerTopup` diganti `TestCustomerLihatSaldo` (2 test): menu 1 hanya
   `Saldo Anda: <Rp>`, **tidak ada** prompt top up/nominal, data tidak berubah,
   tidak ada log `TOPUP` dari customer.
3. **Login sidik jari admin** (2 test baru di `TestLoginSidikJari`): helper
   `set_finger_id_kerja()` menulis `finger_id` admin (mis. `2001`) ke **data
   SALINAN folder kerja** (bukan fixtures/data asli); input simulasi `2001` ->
   `Login berhasil! Selamat datang, admin.` + `=== MENU ADMIN / MERCHANT ===`
   (10 opsi, prompt 1-10), **bukan** Menu Pelanggan; customer budi `1001` tetap
   Menu Pelanggan. `.env` deployment tidak ikut ke workdir (hermetis).
4. **Admin `9. Isi Saldo Pelanggan`** (5 test baru `TestAdminIsiSaldo`): sukses
   (prompt username/saldo/nominal, saldo target naik, log `admin: TOPUP` detail
   `<target>:<nominal>`, saldo user lain & admin tidak berubah); username kosong/
   tidak ada -> `User tidak ditemukan.`; role admin ditolak -> `Hanya akun
   pelanggan yang bisa diisi saldo.`; nominal `abc`/`0`/`-5`/`1.5` ditolak.
   Target customer dipilih **dinamis** dari fixtures (`role == "customer"`),
   tidak hardcode Prabu/budi.
5. **Refactor test lama yang memakai top up customer**: setup saldo untuk
   `test_checkout_saldo_pas_total_berhasil` (user baru `qabatas`) dan
   `_siapkan_high_risk` (user baru `qa_high`) tidak lagi lewat menu customer —
   daftar user lalu set `balance` langsung pada **data SALINAN workdir**
   (fixtures-like setup). Cakupan fitur risk/checkout/saldo-pas tetap utuh.
6. **Tahan data live baru** (suplemen Lead: `P005` & `P009` stok 0, Prabu admin,
   Budhea admin, andi locked, NaNas saldo besar):
   - Helper `produk_uji_checkout(min_stok)` + `cari_skenario_risk()` memilih
     produk **yang stoknya > 0** (harga termurah) dari fixtures; tidak ada lagi
     checkout/hold/risk yang hardcode `P005`.
   - `_assert_hold_pertama`, checkout sidik jari, dan seluruh test
     `test_hold_keranjang.py` memakai produk dinamis tsb.; resume/hold/admin
     cancel memakai harga/stok hasil hitung.
   - Driver unit hold menormalkan stok produk pada **salinan workdir** (>=100)
     agar deterministic; expected stok = baseline - qty.
   - `verifikasi_final.py`: helper `normalisasi_stok_kerja()` menormalkan stok
     produk spot pada **salinan workdir** sebelum run; expected memakai baseline.
   - Topup admin target & user test dipilih dinamis berdasarkan `role`
     (`customer`), bukan asumsi Prabu customer.

### 15.2 Hasil run ronde 7 (2026-11-04 01:46–01:48 WIB, serial)

- `python -m unittest discover -s tests -v`: **Ran 147 tests in 32.535s → OK**
  (147 ok, 0 failure/error, exit 0; 83 `test_payguard` + 47 `test_fingerprint`
  + 17 `test_hold_keranjang`). Log: `_run_final_ronde7.log`.
- `python tests\verifikasi_final.py`: exit code **0 — LULUS**; **15/15
  spot-check OK** (termasuk *admin isi saldo budi + checkout budi*, *register
  rina -> admin isi saldo -> beli -> logout*, dan *login sidik jari admin ->
  Menu Admin 10 opsi*), cek [2] fixtures data byte-identik **YA**, integritas
  **(a)–(f) YA**, manifest inti app/data 12 file tidak berubah.
  Log: `_verifikasi_final_ronde7.log`.
- Data live saat run: `P005`/`P009` stok **0**; `Prabu` & `Budhea` role
  **admin**; andi locked; NaNas saldo 2.22e23; budi/siti customer; logs 19;
  fixtures (users/products/logs/keranjang) **= data live** dan byte-identik
  sebelum==sesudah suite; `tests/_tmp` bersih; fixtures perangkat **simulasi**;
  `.env` tidak tersentuh/tidak disalin. Hash data akhir: users
  `c87ed1f255d1ef899abcd009b4a5893aaf38bcdfb52acb472a7222c0f62155a1`,
  products `079465eef8ca561f4e28c4ad7a843ac22a7219388fdedc15a174a8aaffd95b52`,
  logs `65960ca2556f5b49ff3aa135b4a2846632ef2cde7ec8d4324344e1dce7b18bb5`,
  keranjang `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
- Catatan: fixture harus tetap **= data live** (jangan reset data asli); test
  kini tahan terhadap stok/role berubah lewat pemilihan produk/customer
  dinamis, normalisasi stok pada salinan workdir, dan `skipTest` bila premis
  skenario tidak lagi didukung data live.

### 15.3 Kesimpulan ronde 7

**LAYAK — LULUS.** Kriteria §6 spesifikasi terpenuhi: sidik jari admin ->
Menu Admin, sidik jari customer -> Menu Pelanggan; customer tidak bisa top up
(hanya lihat saldo); admin bisa isi saldo customer (validasi & log
`<target>:<nominal>`) di menu 9 dengan logout 10; **147 test OK**, **15/15
spot-check**, integritas data asli terjaga, suite hermetis.
