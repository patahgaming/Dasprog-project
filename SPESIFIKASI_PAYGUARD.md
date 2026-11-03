# SPESIFIKASI PAYGUARD CLI (v1 - kontrak kerja)

Project baru di folder `payguard/`, mengikuti PDF **Pseudocode & Alur Logika Aplikasi
PayGuard CLI**. Gaya penulisan kode mengikuti project `cashless`: TUI sederhana
(`input`/`print`), fungsi prosedural (tanpa class/OOP), pesan & komentar Bahasa
Indonesia, stdlib Python saja, tanpa pip. Setiap script bisa dijalankan langsung dan
memakai `if __name__ == "__main__":` di bagian bawah.

## 0. Aturan kerja tim

- **Anggota 1** (`main.py`, `admin.py`), **Anggota 2** (`auth.py`,
  `risk_assistant.py`), **Anggota 3** (`customer.py`), **QA** (`tests/`).
- Folder `data/` dan `data_manager.py` sudah **final** — jangan diubah. Kalau butuh
  tambahan helper, kabari Lead (jangan edit file orang lain).
- Jangan menjalankan aplikasi dengan `cwd`/file data asli: salin dulu folder
  `payguard` (semua `.py` + `data/`) ke folder kerja di `payguard/tests/_tmp/...`
  lalu jalankan dari sana. Data asli tidak boleh berubah karena uji coba.
- Satu file = satu pemilik. Jangan edit file anggota lain; integrasi & perbaikan
  akhir dilakukan Lead.

## 1. Struktur file

| File | Pemilik | Fungsi utama |
|---|---|---|
| `main.py` | Anggota 1 | splash screen, menu utama (Login/Register/Login Sidik Jari/Keluar), routing role |
| `auth.py` | Anggota 2 | hash+salt PIN, RegisterUser, LoginUser, VerifyPIN, LogoutUser |
| `admin.py` | Anggota 1 | CRUD produk, audit log, buka blokir akun, isi saldo pelanggan |
| `customer.py` | Anggota 3 | lihat saldo, cari/belanja, pengurutan, keranjang, checkout, riwayat |
| `risk_assistant.py` | Anggota 2 | heuristic risk engine + tampilan Risk Shield |
| `fingerprint.py` | Anggota 2 | klien X100C, event sidik jari, anti-replay |
| `data_manager.py` | Lead (final) | I/O JSON: users/products/logs, log, id produk, rupiah |
| `data/users.json` | Lead (final) | data pengguna |
| `data/products.json` | Lead (final) | katalog produk |
| `data/logs.json` | Lead (final) | audit trail |
| `data/perangkat.json` | deployment | default config X100C (simulasi; override `.env`) |
| `data/keranjang.json` | Lead (final) | keranjang tertahan (hold) |
| `tests/` | QA | unittest stdlib + fixtures |

Dependensi import (jangan dibalik, tidak boleh circular):

```
main      -> auth, admin, customer, fingerprint
admin     -> data_manager, fingerprint, customer
customer  -> data_manager, risk_assistant, auth, fingerprint
risk      -> data_manager (boleh) / hanya stdlib
auth      -> data_manager
```

## 2. Format JSON (final)

`data/users.json`: object `username -> user`

```
user = {
  "username": str, "pin_hash": str(sha256hex), "salt": str(hex16),
  "balance": float, "daily_limit": float, "role": "admin"|"customer",
  "is_locked": bool, "failed_attempts": int, "finger_id": str,
  "transactions": [transaction, ...]
}
transaction = {"id": "TRX-YYYYmmddHHMMSS", "date": ISO "YYYY-MM-DDTHH:MM:SS",
               "total": float, "risk_score": int,
               "items": [{"id": str, "name": str, "price": float, "qty": int}, ...]}
```

`finger_id` = ID perangkat (PIN) pada mesin X100C untuk pembayaran sidik jari
(detail: lihat `SPESIFIKASI_SIDIK_JARI.md`).

`data/products.json`: object `id -> product`

```
product = {"id": "P001", "name": str, "price": float, "stock": int,
           "category": "Needs"|"Wants"}
```

`data/logs.json`: list

```
log = {"time": ISO datetime, "username": str, "action": str, "detail": str}
```

`data/keranjang.json`: list keranjang tertahan (fitur hold saat sidik jari gagal;
detail di `SPESIFIKASI_HOLD_KERANJANG.md`), awal `[]`.

Akun & produk seed (jangan diubah):

| Username | PIN | Role | Saldo | Daily limit | Catatan |
|---|---|---|---|---|---|
| `admin` | `123456` | admin | 0 | 0 | akun admin |
| `budi` | `111111` | customer | 500000 | 500000 | punya 1 transaksi lama (2026-10-20) |
| `siti` | `222222` | customer | 150000 | 300000 | — |
| `andi` | `333333` | customer | 50000 | 200000 | `is_locked: true` (untuk demo unlock) |

Produk: P001 Beras 5kg 65000 Needs stok 20; P002 Minyak Goreng 1L 18000 Needs 30;
P003 Telur Ayam 1kg 30000 Needs 25; P004 Sabun Mandi 5000 Needs 50;
P005 Kopi Sachet 2000 Wants 100; P006 Cokelat Premium 25000 Wants 15;
P007 Headset Gaming 350000 Wants 5; P008 Buku Tulis 8000 Needs 40;
P009 Boba Premium 22000 Wants **stok 0**.

`pin_hash = sha256(PIN + salt).hexdigest()` (sesuai pseudocode HashPasswordWithSalt).

## 3. API data_manager (final, jangan diubah)

```python
pastikan_data()                     # buat folder/file data kalau belum ada
baca_users() -> dict;  simpan_users(users)
baca_products() -> dict;  simpan_products(products)
baca_logs() -> list;  simpan_logs(logs)
waktu_sekarang() -> str             # "YYYY-MM-DDTHH:MM:SS"
catat_log(username, action, detail='')
id_produk_baru(products) -> str     # ID berikutnya, mis. "P010"
rupiah(angka) -> str                # 1.212.000 -> "Rp1.212.000"
```

## 4. Kontrak modul & pesan TUI

Aturan umum: menu memakai loop `while 1`, pilihan tidak dikenal -> `Pilihan tidak valid!`.
Semua nominal uang ditampilkan dengan `data_manager.rupiah()`.

### 4.1 `main.py`

```
============================================
     PAYGUARD CLI - E-WALLET & RISK SHIELD
============================================
```

Menu utama (setelah splash, diulang sampai keluar):

```
=== MENU UTAMA ===
1. Login
2. Register
3. Login Sidik Jari (X100C)
4. Keluar
Pilih menu (1-4):
```

- `4` -> `Terima kasih telah menggunakan PayGuard.` exit code 0.
- `3` Login sidik jari: detail alur & pesan ada di `SPESIFIKASI_SIDIK_JARI.md` §5.1.
  Ringkas: tap sidik jari di X100C -> `Sidik jari dikenali: <username>.` ->
  role `admin` -> `AdminMenu()` (dadm login admin via sidik jari);
  role customer -> `CustomerMenu(user, metode_login='sidik_jari')` (checkout tanpa PIN).
- `1` LoginFlow:
  ```
  --- LOGIN ---
  Username: <input>
  PIN: <input>
  ```
  LoginUser(username, pin):
  - sukses & role admin -> `Login berhasil! Selamat datang, admin.` lalu `AdminMenu()`
  - sukses & customer -> `Login berhasil! Selamat datang, <username>.` lalu `CustomerMenu(user)`
  - gagal -> pesan dari LoginUser, kembali ke menu utama
- `2` RegisterFlow:
  ```
  --- REGISTER ---
  Username baru: <input>
  PIN baru: <input>
  ```
  panggil `RegisterUser(username, pin)`; kembali ke menu utama setelah selesai.

### 4.2 `auth.py`

- `GenerateRandomHex(panjang=16) -> str` : salt acak 16 karakter hex.
- `HashPasswordWithSalt(password, existing_salt=None) -> (hash_result, salt)` :
  jika salt None, generate salt; `sha256(str(password)+salt).hexdigest()`.
- `RegisterUser(username, raw_pin) -> bool`:
  - username kosong -> `Username tidak boleh kosong!` return False
  - PIN bukan angka / panjang < 4 -> `PIN harus berupa angka minimal 4 digit!` False
  - username sudah ada -> `Error: Username sudah terdaftar!` False
  - sukses: user baru default (`balance` 0.0, `daily_limit` 500000.0, role
    `customer`, `is_locked` False, `failed_attempts` 0, `transactions` []);
    simpan; `catat_log(username, "REGISTER", "akun baru")`; print `Registrasi Berhasil!`; True
- `LoginUser(username, input_pin) -> dict|None`:
  - tidak ada -> `Username tidak ditemukan.` None
  - `is_locked` -> `Akun terblokir karena percobaan PIN salah berulang kali. Hubungi Admin.` None
  - hash cocok -> `failed_attempts=0`, simpan, `catat_log(username,"LOGIN_SUCCESS")`, return user
  - salah -> `failed_attempts += 1`; print `PIN salah! Percobaan: <n>/3`;
    jika n >= 3: `is_locked=True`; print `AKUN DIKUNCI DEMI KEAMANAN.`;
    `catat_log(username,"ACCOUNT_LOCKED_BRUTEFORCE")`; simpan; None
- `VerifyPIN(user, input_pin) -> bool` : cek hash saja, **tidak** menambah failed_attempts.
- `LogoutUser(user)` : `catat_log(user["username"], "LOGOUT")`.

### 4.3 `risk_assistant.py`

- `CalculateTodayExpenses(transactions) -> float` : jumlah `total` transaksi yang
  tanggalnya (`date[:10]`) sama dengan tanggal hari ini.
- `EvaluatePurchaseRisk(user, total_cart_value, item_categories) -> (risk_score, warnings)`:
  - `remaining_after = balance - total_cart_value`
  - indikator 1: `remaining_after < 0.3 * balance` -> +2, warning
    `Transaksi ini menghabiskan lebih dari 70% sisa saldomu.`
  - indikator 2: `today_spent + total_cart_value > daily_limit` -> +3, warning
    `Pembelian ini akan melampaui limit anggaran harianmu!`
  - indikator 3: `"Wants"` ada di kategori dan `remaining_after < 100000` -> +2,
    warning `Kamu membeli barang tersier saat saldo mendekati batas minimum.`
- `DisplayRiskShieldNotice(risk_score, warnings) -> bool` cetak banner:
  ```
  ===========================================================
                PAYGUARD FINANCIAL RISK SHIELD
  ===========================================================
  ```
  - score 0: `[STATUS: AMAN] Kondisi keuanganmu stabil untuk transaksi ini.` -> True
  - score <= 3: `[STATUS: PERINGATAN SEDANG]`; tiap warning ` - <warning>`;
    `Apakah kamu yakin tetap ingin melanjutkan checkout? (y/n)`; input y/y -> True
  - selain itu: `[STATUS: RISIKO TINGGI / IMPULSIVE BUYING DETECTED]`; warnings;
    `Rekomendasi AI: Tunda transaksi ini demi kesehatan finansialmu.`;
    `Ketik 'SAYA YAKIN' untuk memaksa transaksi:`; True hanya jika input persis
    `SAYA YAKIN` (setelah strip).

### 4.4 `customer.py`

Menu (PDF, disesuaikan: top up dipindah ke admin):
```
=== MENU PELANGGAN ===
1. Lihat Saldo
2. Cari & Belanja Produk
3. Pengurutan Katalog
4. Lihat Keranjang & Checkout
5. Riwayat Transaksi & Track Record
6. Logout
Pilih menu (1-6):
```

Cart adalah state sesi (modul), bukan di users.json:

- `GetUserCart(current_user) -> list` : list `{"id","name","price","qty"}`.
- `AddToCart(product, qty)` : gabung item dengan id sama (qty ditambah).
- `ClearUserCart(current_user)` : kosongkan cart.

1. `LihatSaldo(current_user)`: print `Saldo Anda: <Rp>.`
   (Customer **tidak** bisa top up; top up dilakukan admin — §4.5.9.)
2. `SearchAndBrowseMarketplace(current_user)`:
   - `Masukan kata kunci produk: ` ; tampilkan produk yang name/id-nya mengandung
     kata kunci (case-insensitive), format baris:
     `<id> | <nama> | <Rp harga> | stok <stok> | <kategori>`
   - tidak ada hasil -> `Produk tidak ditemukan.` return
   - `Masukan ID produk yang ingin dibeli (0 untuk kembali): `; `0` -> return;
     ID tidak ada -> `ID produk tidak ditemukan.` return
   - stok <= 0 -> `Stok produk habis!` return
   - `Masukan jumlah: ` ; harus int > 0 dan <= stok, selain itu
     `Jumlah tidak valid atau melebihi stok!` return
   - `AddToCart(product, qty)`; print `'<nama>' x<jumlah> ditambahkan ke keranjang.`
3. `SortCatalogInteractive()`:
   ```
   === PENGURUTAN KATALOG ===
   1. Harga termurah
   2. Harga termahal
   3. Nama A-Z
   4. Stok terbanyak
   Pilih pengurutan (1-4):
   ```
   tampilkan daftar produk terurut dengan format baris yang sama; invalid -> `Pilihan tidak valid!`
4. `CheckoutProcess(current_user, metode_login='pin', keranjang_tertahan=None)`:
   - print `=== KERANJANG BELANJA ===`; kosong -> `Keranjang belanja kosong!` return
   - tampilkan tiap item `<nama> x<jumlah> = <Rp>`; `Total: <Rp>`
   - saldo < total -> `Checkout Gagal: Saldo e-wallet tidak mencukupi!`;
     `Saldo: <Rp> | Total: <Rp>`; return (data tidak berubah)
   - risk_score, warnings = EvaluatePurchaseRisk(...)
   - proceed = DisplayRiskShieldNotice(...); jika False ->
     `Transaksi dibatalkan oleh pengguna/Risk Shield.` return
   - `Masukan PIN E-Wallet untuk konfirmasi pembayaran: `; VerifyPIN salah ->
     `PIN Salah! Transaksi Dibatalkan.` return (data tidak berubah)
   - **Jalur `metode_login == 'sidik_jari'`**: minta tap; jika gagal pertama ->
     `TahanKeranjang(...)` (stok products turun, record masuk `data/keranjang.json`,
     saldo & transaksi tidak berubah; lihat `SPESIFIKASI_HOLD_KERANJANG.md`).
     Resume hold `keranjang_tertahan` -> tap gagal menambah `percobaan`, tap sukses
     menghapus hold + potong saldo (stok tidak dipotong lagi).
   - potong saldo & stok, `CreateReceipt`, `SaveTransactionToUserHistory`,
     `ClearUserCart`, simpan users+products, `catat_log(username,
     "CHECKOUT_SUCCESS_RP_<total bulat>", trx_id)` (jalur sidik jari sukses:
     `CHECKOUT_FINGER_RP_<total bulat>`)
   - print `TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.` lalu blok:
     ```
     --- RESI PEMBAYARAN ---
     ID: <trx_id>
     Tanggal: <date>
     <nama> x<jumlah> = <Rp>
     Total: <Rp>
     Skor Risiko: <risk_score>
     Sisa Saldo: <Rp>
     ```
5. `ViewTransactionHistory(current_user)`:
   - kosong -> `Belum ada transaksi.`
   - `=== RIWAYAT TRANSAKSI ===`; tiap transaksi:
     `- <date> | <id> | Total <Rp> | Risiko <score> | <item1>, <item2>, ...`
   - `=== TRACK RECORD ===`; `Jumlah transaksi: <n>`;
     `Total pengeluaran: <Rp>`; `Rata-rata transaksi: <Rp>`
6. Logout -> `LogoutUser(current_user)`; print `Logout berhasil.`; return.

Helper yang harus ada: `CreateReceipt(cart, total_price, risk_score) -> dict`
(id `TRX-` + `datetime.now().strftime("%Y%m%d%H%M%S")`), dan
`SaveTransactionToUserHistory(current_user, record)` (append ke
`current_user["transactions"]` + simpan users).

### 4.5 `admin.py`

```
=== MENU ADMIN / MERCHANT ===
1. Tambah Produk Baru (Create)
2. Tampilkan Semua Produk (Read)
3. Update Harga / Stok Produk (Update)
4. Hapus Produk dari Katalog (Delete)
5. Lihat Audit System Logs
6. Buka Blokir Akun Pelanggan
7. Kelola Sidik Jari (X100C)
8. Kelola Keranjang Tertahan
9. Isi Saldo Pelanggan
10. Logout Admin
Pilih menu (1-10):
```

1. `CreateProduct()`:
   - `Masukan nama produk: ` -> kosong: `Nama produk tidak boleh kosong!`
   - `Masukan harga: ` -> bukan angka / <= 0: `Harga harus berupa angka lebih dari 0!`
   - `Masukan stok: ` -> bukan int / < 0: `Stok harus berupa angka bulat minimal 0!`
   - `Masukan kategori (Needs/Wants): ` -> selain Needs/Wants:
     `Kategori harus Needs atau Wants!`
   - ID otomatis `id_produk_baru`; simpan; `catat_log("admin","CREATE_PRODUCT", id)`;
     print `Produk <id> '<nama>' berhasil ditambahkan.`
2. `ReadAllProducts()`: header `ID | Nama | Harga | Stok | Kategori` + baris;
   kosong -> `Katalog kosong.`
3. `UpdateProductDetails()`:
   - `Masukan ID produk: `; tidak ada -> `ID produk tidak ditemukan.`
   - print `Harga saat ini: <Rp>, Stok saat ini: <stok>`
   - `Pilih yang diupdate (1=harga, 2=stok): `; invalid -> `Pilihan tidak valid!`
   - `Masukan nilai baru: `; harga harus angka > 0 / stok int >= 0, kalau salah
     `Nilai baru tidak valid!`
   - simpan; `catat_log("admin","UPDATE_PRODUCT", id)`; `Produk <id> berhasil diupdate.`
4. `DeleteProduct()`:
   - `Masukan ID produk: `; tidak ada -> `ID produk tidak ditemukan.`
   - `Yakin ingin menghapus '<nama>'? (y/n): `; ya -> hapus, simpan,
     `catat_log("admin","DELETE_PRODUCT", id)`, `Produk <id> berhasil dihapus.`;
     tidak -> `Penghapusan dibatalkan.`
5. `DisplaySystemLogs()`: `--- AUDIT SYSTEM LOGS (20 TERAKHIR) ---`; tampilkan 20
   log terakhir format `[time] username: action - detail`; kosong -> `Belum ada log.`
6. `UnlockCustomerAccount()`:
   - `Masukan username pelanggan: `; tidak ada -> `Username tidak ditemukan.`
   - tidak terkunci -> `Akun tidak sedang terblokir.`
   - terkunci -> `is_locked=False`, `failed_attempts=0`, simpan,
     `catat_log("admin","UNLOCK_ACCOUNT", username)`,
     `Akun '<username>' berhasil dibuka blokirnya.`
7. `MenuSidikJari()` -> kelola pendaftaran sidik jari X100C (daftar/hapus/lihat/
   tes koneksi); detail menu & pesan persis di `SPESIFIKASI_SIDIK_JARI.md` §5.3.
8. `MenuKeranjangTertahan()` -> hold keranjang: list/cancel/restore
   (`SPESIFIKASI_HOLD_KERANJANG.md` §4).
9. `IsiSaldoPelanggan()`:
   - `Masukan username pelanggan: `; tidak ada -> `User tidak ditemukan.`;
     role bukan customer -> `Hanya akun pelanggan yang bisa diisi saldo.`
   - print `Saldo saat ini: <Rp>`
   - `Masukan nominal isi saldo: `; bukan angka bulat / <= 0 ->
     `Nominal isi saldo tidak valid!`
   - sukses: balance target bertambah; simpan users;
     `catat_log("admin","TOPUP","<username>:<nominal>")`;
     print `Isi saldo berhasil! Saldo <username> sekarang <Rp>.`
10. Logout -> `catat_log("admin","LOGOUT")`, `Logout berhasil.`; return.

## 5. Aturan bisnis penting

- Saldo & stok **tidak boleh** berubah jika checkout gagal (saldo kurang / user
  batalkan risk shield / PIN salah).
- Checkout memakai harga & stok terbaru dari `products.json`.
- Login 3x PIN salah mengunci akun; unlock hanya lewat admin.
- Semua aksi penting dicatat ke logs.json: REGISTER, LOGIN_SUCCESS,
  ACCOUNT_LOCKED_BRUTEFORCE, LOGOUT, TOPUP, CHECKOUT_SUCCESS_RP_<total>,
  CHECKOUT_FINGER_RP_<total>, HOLD_CART, HOLD_CANCEL, CREATE_PRODUCT,
  UPDATE_PRODUCT, DELETE_PRODUCT, UNLOCK_ACCOUNT.
- Transaksi & log bersifat append-only (tidak diedit/dihapus).
- Jangan menyimpan cart di users.json.

## 6. Testing (QA)

- Test stdlib (`unittest`, `subprocess`, `csv` tidak perlu, `json`, `hashlib`,
  `pathlib`, `shutil`, `uuid`, `os`).
- **Jangan** pakai `tempfile.mkdtemp()` (di sandbox mesin ini permission error);
  buat folder `tests/_tmp/kasus_<uuid>` dengan `mkdir` biasa, hapus di tearDown.
- Setiap test integrasi: salin `payguard/*.py` + `payguard/data/` ke folder kerja,
  jalankan `python main.py` dengan `cwd` folder kerja (path script absolut), input
  stdin, cek stdout + isi `data/*.json`. Data asli tidak boleh berubah.
- Wajib ada test: login admin/customer, sandi salah, lockout 3x, register
  (sukses/duplikat/PIN invalid), admin CRUD (create/read/update/delete + validasi),
  logs, unlock akun, customer top up, search, sort, add cart, checkout sukses
  (saldo/stok/transaksi/log), checkout saldo kurang, risk shield (aman /
  peringatan konfirmasi y/n / risiko tinggi wajib `SAYA YAKIN` / batal), PIN salah,
  riwayat transaksi, menu invalid, exit code 0.
- Unit test read-only: `HashPasswordWithSalt` (dengan salt tetap), `GenerateRandomHex`,
  `VerifyPIN`, `EvaluatePurchaseRisk`, `CalculateTodayExpenses`, `rupiah`.
- Jalankan `python -m unittest discover -s tests -v` dari folder `payguard`.

## 7. Kriteria penerimaan

1. Semua 6 modul ada, mengimpor sesuai aturan, tidak circular.
2. TUI berjalan penuh: splash -> login/register -> menu admin / menu pelanggan -> logout.
3. CRUD produk berfungsi dan tervalidasi; stok berkurang saat checkout.
4. Risk Shield: 3 indikator, status AMAN/PERINGATAN SEDANG/RISIKO TINGGI sesuai
   pseudocode, bisa membatalkan transaksi.
5. Lockout 3x PIN salah, admin bisa unlock.
6. Semua data persist ke JSON; transaksi & log bertambah.
7. Test suite lulus; data asli `payguard/data` tidak berubah karena test.
8. Gaya kode mengikuti `cashless` (TUI, fungsi prosedural, pesan Indonesia).
