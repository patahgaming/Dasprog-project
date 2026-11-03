# HASIL TEST & CATATAN PAYGUARD CLI

Project baru `payguard/` dibuat mengikuti PDF *Pseudocode & Alur Logika Aplikasi
PayGuard CLI*, dengan gaya penulisan kode mengikuti project lama `cashless`
(TUI sederhana, fungsi prosedural, pesan & komentar Bahasa Indonesia, stdlib saja).

Tanggal: 2026-10-26 (ronde 1) · **2026-11-03 (ronde 2: sidik jari X100C)** ·
Python 3.14.6 · Windows · TUI (stdio)

## 1. Yang dibuat

| Modul | Isi |
|---|---|
| `main.py` | Splash screen, menu utama (Login/Register/Keluar), routing role |
| `auth.py` | `GenerateRandomHex`, `HashPasswordWithSalt` (sha256+salt), `RegisterUser`, `LoginUser` (lockout 3x), `VerifyPIN`, `LogoutUser` |
| `admin.py` | `AdminMenu` + CRUD produk (Create/Read/Update/Delete), audit log, buka blokir akun |
| `customer.py` | Top up, search/browse, sort katalog, keranjang, checkout (saldo + Risk Shield + PIN), riwayat & track record |
| `risk_assistant.py` | `CalculateTodayExpenses`, `EvaluatePurchaseRisk` (3 indikator), `DisplayRiskShieldNotice` (AMAN/PERINGATAN SEDANG/RISIKO TINGGI) |
| `data_manager.py` | I/O JSON users/products/logs (atomic write), `catat_log`, `id_produk_baru`, `rupiah` |
| `data/*.json` | Data seed: 4 user, 9 produk, 2 log |
| `tests/` | Suite QA (77 test unittest) + fixtures + spot-check |

Akun demo: `admin`/`123456` (admin), `budi`/`111111` (saldo 500.000),
`siti`/`222222` (saldo 150.000), `andi`/`333333` (terblokir untuk demo unlock).

## 2. Uji project (Lead, end-to-end TUI)

8 skenario dijalankan lewat `python main.py` dengan stdin di **salinan folder**
(`_pg_smoke`), data asli tidak disentuh. Semua exit code 0:

| Skenario | Hasil |
|---|---|
| Admin login → Create P010 → Read → Update harga → Delete → Lihat logs → Unlock `andi` → Logout → Keluar | OK; produk P010 dibuat/diubah/dihapus; `andi` terbuka; log CREATE/UPDATE/DELETE/UNLOCK/LOGOUT bertambah |
| Budi login → cari "beras" → beli P001 x1 → checkout AMAN → PIN → riwayat → logout | OK; saldo 500.000→435.000; stok 20→19; transaksi +1; log CHECKOUT; resi tampil |
| Siti → beli Headset 350.000 → checkout | OK; `Checkout Gagal: Saldo e-wallet tidak mencukupi!`, data tidak berubah |
| Siti → beli Cokelat x3 (75.000) → risk PERINGATAN SEDANG → `n` batal → ulang → `y` + PIN | OK; batal tidak mengubah data; lanjut sukses: saldo 75.000, stok 15→12, risk_score 2 |
| Budi → top up 400.000 → beli Headset x2 (700.000) → RISIKO TINGGI → `SAYA YAKIN` + PIN | OK; saldo akhir 200.000, stok 5→3, risk_score 5, log TOPUP + CHECKOUT |
| Siti PIN salah 3x → akun terkunci → admin unlock `siti` → login sukses | OK; log ACCOUNT_LOCKED_BRUTEFORCE + UNLOCK_ACCOUNT |
| Register `rina`/`999999` → login → top up 50.000 → beli Kopi x2 → checkout `y` + PIN | OK; user baru dibuat, saldo akhir 46.000, stok 100→98 |
| Menu invalid, username tak ada, register duplikat | OK; pesan sesuai, exit 0 |

`python -m py_compile main.py auth.py admin.py customer.py risk_assistant.py data_manager.py`
→ exit 0.

## 3. Uji otomatis QA

```powershell
cd payguard
python -m unittest discover -s tests -v
```

Hasil: **77 test, OK (exit 0)** — 65 test integrasi TUI (subprocess) + unit test
(read-only) + test integritas data. Detail bukti & inventaris ada di
[`tests/HASIL_QA.md`](tests/HASIL_QA.md).

Verifikasi final QA (independen, 26/10/2026): **FINAL: SEMUA LULUS** — 77/77 test
OK, `tests/verifikasi_final.py` exit 0 dengan 6/6 spot-check, SHA256 data asli
identik sebelum = sesudah, fixtures byte-identik, `tests/_tmp` bersih, dan tidak
ada file app/data yang berubah di luar `payguard/tests/`.

Cakupan: login admin/customer, PIN salah, lockout 3x, register (sukses/duplikat/PIN
invalid/username kosong), admin CRUD + semua validasi, audit log, unlock akun,
top up, search/stok habis/qty, sort 4 opsi, keranjang gabung item, checkout sukses
(saldo, stok, transaksi, log, resi, riwayat), saldo kurang & saldo pas, risk shield
3 level (termasuk batal), PIN salah checkout, riwayat + track record, menu invalid,
exit code, serta unit `HashPasswordWithSalt`, `GenerateRandomHex`, `VerifyPIN`,
`EvaluatePurchaseRisk`, `CalculateTodayExpenses`, `rupiah`.

## 4. Integritas data

- Test selalu menyalin `tests/fixtures/` atau `data/` ke folder kerja
  `tests/_tmp/kasus_<uuid>` (bukan `tempfile.mkdtemp()` karena batasan sandbox
  Windows) dan menjalankan app dengan `cwd` folder kerja.
- SHA256 `payguard/data/users.json`, `products.json`, `logs.json` **identik**
  sebelum vs sesudah seluruh pengujian; `tests/_tmp` bersih setelah run.
- Data asli tidak pernah dijadikan `cwd` aplikasi.

## 5. CRUD di PayGuard

| Entitas | Create | Read | Update | Delete |
|---|---|---|---|---|
| Produk | `CreateProduct` (menu admin 1) | `ReadAllProducts` (admin 2), browse/search (customer 2) | `UpdateProductDetails` (admin 3), stok berkurang saat checkout | `DeleteProduct` (admin 4) |
| User | `RegisterUser` | `LoginUser`, cek saldo | top up, potong saldo, `failed_attempts`/`is_locked`, transaksi | tidak ada → blokir akun (soft delete) |
| Transaksi | `CreateReceipt` + `SaveTransactionToUserHistory` | `ViewTransactionHistory` | – | – (append-only) |
| Log | `catat_log` | `DisplaySystemLogs` | – | – (append-only) |
| Keranjang | `AddToCart` | `GetUserCart` / lihat keranjang | qty digabung | `ClearUserCart` |

## 6. Pembagian tugas (sesuai PDF, 3 anggota)

| Anggota | Modul | Status |
|---|---|---|
| Anggota 1 | `main.py`, `admin.py` | selesai (tim: `pg-main-admin`) |
| Anggota 2 | `auth.py`, `data_manager.py`, `risk_assistant.py` | selesai (`data_manager` oleh Lead) |
| Anggota 3 | `customer.py` | selesai (`pg-customer`) |
| QA | `tests/` | **121 test OK** (ronde 2; `pg-qa`) |

## 7. Catatan / keterbatasan

- Project ini **baru**; folder `cashless/` lama tetap ada dan tidak diubah.
- Risk Shield memakai 3 indikator sesuai pseudocode; keputusan akhir tetap di
  pengguna (konfirmasi / ketik `SAYA YAKIN`).
- Keranjang adalah state sesi di memori modul dan dikosongkan saat logout.
- Beberapa detail di luar pseudocode bersifat pilihan implementasi: format tabel
  `ReadAllProducts` (`ID | Nama | Harga | Stok | Kategori`), konfirmasi hapus
  menerima `y/ya`, harga item di keranjang memakai snapshot saat ditambahkan
  (stok & kategori dibaca ulang saat checkout).
- PIN disimpan sebagai SHA-256 + salt per user (sesuai pseudocode) — untuk latihan,
  bukan produksi.

## 8. Ronde 2 — Pembayaran Sidik Jari X100C

Fitur baru: login & pembayaran dengan sidik jari memakai mesin **ZKTeco X100C**
(webserver/SOAP) lewat jaringan, **tanpa mengetik akun/PIN**.

### Perubahan

| File | Perubahan |
|---|---|
| `fingerprint.py` (baru) | Konfigurasi perangkat, klien SOAP X100C (`POST /iWsService`, `GetAttLog`, `GetUserInfo`), event fresh + anti-replay, mode simulasi |
| `main.py` | Menu utama 4 opsi: Login / Register / **Login Sidik Jari (X100C)** / Keluar |
| `admin.py` | Menu 8 opsi + submenu **Kelola Sidik Jari (X100C)**: daftar/hapus/lihat mapping + tes koneksi |
| `customer.py` | Checkout jalur sidik jari (tap ulang, tanpa PIN) + log `CHECKOUT_FINGER_RP_...` |
| `auth.py` | User baru punya `finger_id: ""` |
| `data/users.json` | Field `finger_id` (budi 1001, siti 1002, andi 1003); data pengguna lain dipertahankan (termasuk `NaNas`) |
| `data/perangkat.json` (baru) | Konfigurasi mode/host/port/timeout X100C |
| `data/finger_state.json` | Runtime anti-replay (tidak disimpan ke repo/data asli) |
| `SPESIFIKASI_SIDIK_JARI.md` (baru) | Kontrak fitur, alur, keamanan, pengujian |

### Uji Lead end-to-end (7 skenario, semua exit 0)

| Skenario | Hasil |
|---|---|
| Simulasi: login budi (1001) → beli Kopi x2 → checkout tap 1001 | OK; tanpa PIN, saldo 500.000→496.000, stok 100→98, log `CHECKOUT_FINGER_RP_4000` |
| SOAP (mock X100C): `GetAttLog` event 1001 → login → checkout tap kedua | OK; sukses tanpa PIN, data/log benar |
| SOAP: login budi, tap PIN lain (1002) saat checkout | OK; `Sidik jari tidak cocok.` + `Transaksi dibatalkan.`, data tidak berubah |
| SOAP: host/port mati | OK; `Perangkat X100C tidak terhubung...`, exit 0 |
| SOAP: event kadaluwarsa (2 jam) | OK; `Tidak ada sidik jari terbaca.`, tidak login |
| SOAP: PIN 9999 tidak dikenal | OK; `Sidik jari belum terdaftar. Hubungi admin.` |
| Admin: enroll NaNas↔2001 via SOAP, lihat daftar, tes koneksi | OK; `PIN ditemukan di perangkat`, daftar benar, `Koneksi X100C OK ... (n log)` |

Catatan uji: mock X100C (`socketserver`) menerima request X100C yang memakai
`xsi:type` tanpa namespace (seperti library referensi); parser mock dibuat toleran.
Klien diverifikasi memakai format protokol yang benar (root = nama perintah, bukan
`<Command>`).

### Uji otomatis QA ronde 2

- Suite menjadi **121 test** (77 test lama diupdate + 44 test baru):
  unit XML/dedupe/config, mock X100C SOAP (termasuk menolak format `<Command>`
  lama), integrasi simulasi login/checkout sidik jari, replay, event kadaluwarsa,
  PIN beda, perangkat mati, admin mapping, integritas data.
- Status: **121 test OK, exit 0**; fixtures disinkronkan ulang (users/products/logs/
  perangkat); data asli tidak berubah.
- Verifikasi final QA (kode beku, 2026-11-03 13:03 WIB): **FINAL: SEMUA LULUS** —
  121/121 test OK, `verifikasi_final.py` 2× exit 0 dengan 12/12 spot-check,
  SHA256 4 file data asli identik sebelum = sesudah, fixtures byte-identik,
  `tests/_tmp` bersih, tidak ada `data/finger_state.json` di data asli.
- Detail bukti: [`tests/HASIL_QA.md`](tests/HASIL_QA.md).

### Keamanan & batasan

- Event hanya valid jika masih dalam `jendela_detik` dan belum diproses
  (`finger_state.json`) → anti-replay; checkout meminta tap ulang untuk user yang
  sama; PIN perangkat unik per akun; akun terkunci/tak dikenal ditolak.
- Integrasi hardware diuji lewat **mock perangkat** dan sudah diverifikasi juga pada
  **perangkat X100C asli** (lihat §9); setup IP/webserver/X100C ada di [README](README.md).
- Mesin X100C disarankan dikhususkan untuk pembayaran + jam disinkronkan, karena
  `GetAttLog` juga memuat log absensi biasa.

## 9. Ronde 4 — Uji Perangkat X100C Asli (2026-11-03)

Alat X100C langsung ke port LAN laptop (tanpa router):

| Item | Nilai |
|---|---|
| IP X100C | `192.168.1.201` (MAC `00-17-61-10-34-B9`, OUI ZKTeco) |
| IP laptop Ethernet | `192.168.1.100/24` (statis, tanpa gateway) |
| Port | `80` (ZK Web Server HTTP/SOAP) & `4370` (ZK SDK) |
| Com key | `<com_key>` (tanpa key, `GetAttLog` kosong) |
| Isi perangkat | **10.204 log**, **136 user** (data absensi lama tetap ada) |
| Jam perangkat | semula `2026-05-19` → disinkronkan ke PC `2026-11-03` via protokol ZK port 4370 |

### Uji bayar end-to-end dengan sidik jari asli

1. Tap #1 (login) `23:26:27` → PIN perangkat `11733` (nama: Prabu).
2. Di salinan uji, PIN dipetakan ke akun `budi`; aplikasi mencetak
   `Sidik jari dikenali: budi.` lalu masuk menu pelanggan **tanpa PIN**.
3. Tap #2 (otorisasi bayar) `23:28:50` → checkout berhasil:
   - Resi `TRX-20261103232855`, `Kopi Sachet x1 = Rp2.000`, risk 0
   - Saldo `Rp500.000 → Rp498.000`, stok `100 → 99`
   - Log `CHECKOUT_FINGER_RP_2000` (detail trx), tanpa prompt PIN, exit 0.
4. Data asli tidak dipakai untuk uji ini (dijalankan di salinan, lalu dihapus).

### Akun Prabu (data asli)

- Dibuat dengan `RegisterUser('Prabu', '123456')`; role `customer`, saldo awal Rp0,
  `finger_id = "11733"`; log `REGISTER` + `FINGER_ENROLL` (`Prabu:11733`).
- Setelah itu pemilik alat **langsung memakai aplikasi asli**: login sidik jari
  (event `23:31:46`) dan **top up Rp1.000.000.000** (`23:32:09`) tercatat di
  `data/logs.json` & `data/finger_state.json` → alur nyata terbukti berjalan.

### Test suite setelah data nyata berubah

- Fixtures `users.json` & `logs.json` disinkronkan ulang dari data asli (wajib setelah
  pemakaian nyata); fixtures `perangkat.json` tetap **simulasi** (hermetis).
- Test disesuaikan: `finger_state.json` boleh ada di data asli (runtime nyata), tetapi
  tidak boleh ada di fixtures; manifest verifikasi mengecualikan file runtime itu.
- Hasil akhir: **123 test OK**, `python tests\verifikasi_final.py` **LULUS**,
  12/12 spot-check, fixtures data byte-identik, data asli identik sebelum/sesudah,
  `tests/_tmp` bersih, tidak ada koneksi test ke `192.168.1.201`.
- Catatan: jalankan suite saat aplikasi asli tidak sedang dipakai; aktivitas user
  bersamaan dapat mengubah data asli di tengah suite (bukan bug test).

## 10. Ronde 5 — Hold Keranjang saat Sidik Jari Gagal (2026-11-03)

Kontrak: [`SPESIFIKASI_HOLD_KERANJANG.md`](SPESIFIKASI_HOLD_KERANJANG.md).

### Perilaku baru

- Tap sidik jari **gagal pertama** saat checkout **tidak membatalkan** belanjaan:
  stok produk langsung **dikurangi**, keranjang masuk `data/keranjang.json`
  (status `tertahan`, ID `HOLD-…`, `percobaan`), saldo & transaksi **tidak berubah**,
  log `HOLD_CART`.
- Menu pelanggan `4`: bila ada hold milik user -> prompt `Lanjutkan pembayaran sekarang? (y/n)`.
  - `y` + tap benar -> hold dihapus, saldo dipotong, resi/transaksi, log
    `CHECKOUT_FINGER_RP_...`, stok tidak dipotong dua kali.
  - tap gagal lagi -> `percobaan` bertambah, hold tetap.
- Admin menu `8. Kelola Keranjang Tertahan`: lihat, batalkan & kembalikan stok
  (log `HOLD_CANCEL`).
- Jalur PIN tidak berubah (PIN salah tetap dibatalkan tanpa hold).

### Perubahan file

| File | Perubahan |
|---|---|
| `customer.py` | 7 helper hold + `CheckoutProcess(..., keranjang_tertahan=None)` + resume di menu 4 |
| `admin.py` | menu jadi 9 opsi; submenu `MenuKeranjangTertahan()` (list/cancel) |
| `data/keranjang.json` (baru) | list keranjang tertahan, awal `[]` |
| `tests/fixtures/keranjang.json` (baru) | fixture sama (`[]`), masuk uji integritas |
| `SPESIFIKASI_PAYGUARD.md`, `SPESIFIKASI_SIDIK_JARI.md` | menu & log hold diperbarui |
| `tests/` | test baru hold (unittest), `verifikasi_final.py` + spot-check hold |

### Hasil uji

- **QA: 140 test OK** (123 lama + 17 test hold) — `python -m unittest discover -s tests -v`.
- `python tests\verifikasi_final.py`: **LULUS**, **14/14 spot-check** (termasuk hold &
  admin cancel), fixtures data (users/products/logs/keranjang) byte-identik, data asli
  identik sebelum/sesudah, `tests/_tmp` bersih, tidak ada koneksi ke `192.168.1.201`.
- Smoke Lead independen di salinan (5 skenario): hold pertama (stok 100→98, saldo tetap);
  resume+sukses (saldo 496.000, trx +1, stok tetap 98, hold hilang); resume gagal
  (`percobaan` 1→2); admin list+cancel (stok kembali 100, log `HOLD_CANCEL`); jalur
  PIN salah tetap tanpa hold. Semua exit 0 dan data sesuai.
- `data/keranjang.json` asli tetap `[]` (belum ada hold nyata); data user Prabu dsb.
  tidak berubah karena fitur ini.

## 11. Ronde 7 — Login Sidik Jari Admin & Top Up oleh Admin (2026-11-04)

Kontrak: [`SPESIFIKASI_LOGIN_ADMIN_FINGER_DAN_TOPUP.md`](SPESIFIKASI_LOGIN_ADMIN_FINGER_DAN_TOPUP.md).

### Perubahan akses

- **Login sidik jari mengikuti role**: akun `admin` -> `Login berhasil! Selamat
  datang, admin.` + **Menu Admin**; customer tetap Menu Pelanggan.
  Admin harus punya `finger_id` (didaftarkan lewat menu `7. Kelola Sidik Jari`);
  satu `finger_id` hanya untuk satu akun.
- **Top up hanya oleh admin**: menu customer `1. Lihat Saldo` (tanpa top up);
  admin punya menu `9. Isi Saldo Pelanggan` dan logout menjadi `10. Logout Admin`
  (prompt `Pilih menu (1-10):`).
- Isi saldo: validasi username/customer, nominal bulat > 0, update saldo, log
  `admin: TOPUP` detail `<username>:<nominal>`.

### Perubahan file

| File | Perubahan |
|---|---|
| `main.py` | routing `LoginFingerFlow` berdasarkan `role` |
| `customer.py` | menu `1. Lihat Saldo`, top up customer dihapus (`HandleTopUp` dihapus) |
| `admin.py` | menu 10 opsi + `IsiSaldoPelanggan()` |
| `tests/` | test admin fingerprint login, admin isi saldo, customer lihat saldo; menu 10; data-driven |
| `SPESIFIKASI_PAYGUARD.md`, `SPESIFIKASI_SIDIK_JARI.md`, `README.md` | menu & alur diperbarui |
| `SPESIFIKASI_LOGIN_ADMIN_FINGER_DAN_TOPUP.md` (baru) | kontrak ronde ini |

### Hasil uji

- **QA: 147 test OK** (140 lama + 7 test baru; 83 payguard + 47 fingerprint + 17 hold)
  — semuanya data-driven terhadap data live (stok/role berubah).
- `python tests\verifikasi_final.py`: **LULUS**, **15/15 spot-check** (termasuk login
  sidik jari admin + admin isi saldo + antrian hold), integritas (a)–(f) YA, fixtures
  data byte-identik, `tests/_tmp` bersih, `.env` tidak disalin.
- Smoke Lead independen di salinan:
  1. login sidik jari `Prabu` (role admin, finger `11733`) -> Menu Admin (bukan
     Menu Pelanggan), opsi 9/10 tampil;
  2. admin `9. Isi Saldo Pelanggan` -> budi +Rp100.000, log `TOPUP` detail
     `budi:100000`;
  3. customer `1. Lihat Saldo` -> `Saldo Anda: Rp500.000.`, tanpa prompt top up.
  Semua exit 0.
- Data live saat ronde ini berubah karena pengujian user: `Prabu` & `Budhea` role
  admin, `P005`/`P009` stok 0, `NaNas` saldo besar, `andi` terkunci. Fixtures
  disinkronkan dan test memilih produk/customer secara dinamis serta menormalkan
  stok di **salinan** test.
