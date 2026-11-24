# PAYGUARD CLI - Smart E-Wallet & Financial Risk Shield

Aplikasi CLI (TUI) berbasis Python untuk ekosistem dompet digital (E-Wallet) +
katalog toko virtual (Marketplace) + **Risk Assistant** pencegah pengeluaran impulsif.
Dibuat baru berdasarkan dokumen *Pseudocode & Alur Logika Aplikasi PayGuard CLI*.

- 100% standard library Python (tanpa pip), tanpa GUI.
- Data disimpan sebagai JSON terstruktur di folder `data/`.
- Gaya kode mengikuti project lama `cashless`: prosedural, TUI `input()`/`print()`,
  fungsi didefinisikan di atas lalu dipanggil, pesan & komentar Bahasa Indonesia.

## Cara menjalankan

```powershell
cd payguard
Copy-Item .env.example .env   # sekali saja, lalu isi nilai lokal
python main.py
```

### Konfigurasi environment (`.env`)

Konfigurasi perangkat/lokal **tidak disimpan di repo**. Salin template lalu isi
sesuai jaringan X100C lokal:

```dotenv
PAYGUARD_X100C_MODE=soap          # "simulasi" jika tanpa alat
PAYGUARD_X100C_HOST=192.168.1.201
PAYGUARD_X100C_PORT=80
PAYGUARD_X100C_COM_KEY=0          # isi PC connection/comm key X100C kamu
PAYGUARD_X100C_TIMEOUT=6
PAYGUARD_X100C_JENDELA_DETIK=30
PAYGUARD_X100C_BATAS_TUNGGU_DETIK=20
```

- Urutan prioritas: nilai default -> `data/perangkat.json` -> `.env` -> environment OS.
- `.env` **di-ignore git** (lihat `.gitignore`); yang di-commit hanya `.env.example`.
- `data/perangkat.json` yang ada di repo berisi mode `simulasi` (aman untuk publik);
  alat asli diaktifkan lewat `.env`.
- Untuk mode simulasi (tanpa alat), cukup biarkan `PAYGUARD_X100C_MODE=simulasi`.

Akun demo (PIN disimpan sebagai `sha256(PIN + salt)`):

| Username | PIN      | Role     | Saldo awal | Catatan |
|----------|----------|----------|------------|---------|
| `admin`  | `123456` | admin    | Rp0        | akses Menu Admin/Merchant |
| `budi`   | `111111` | customer | Rp500.000  | punya 1 transaksi lama |
| `siti`   | `222222` | customer | Rp150.000  | limit harian Rp300.000 |
| `andi`   | `333333` | customer | Rp50.000   | **terblokir** (demo buka blokir admin) |
| `Prabu`  | `123456` | customer | Rp0        | akun pemilik alat; sidik jari X100C PIN `11733` |

## Fitur

### Menu utama
`Login` / `Register` / **`Login Sidik Jari (X100C)`** / `Keluar`. Akun baru default:
role `customer`, saldo 0, limit harian Rp500.000. PIN minimal 4 digit angka; 3x PIN
salah -> akun terkunci.

### Menu Admin / Merchant (`admin.py`)
1. **Create** – tambah produk baru (nama, harga, stok, kategori Needs/Wants).
2. **Read** – tampilkan seluruh katalog.
3. **Update** – ubah harga atau stok produk.
4. **Delete** – hapus produk dari katalog (dengan konfirmasi).
5. Audit System Logs – 20 aktivitas terakhir.
6. Buka blokir akun pelanggan.
7. **Kelola Sidik Jari (X100C)** – daftar/hapus/lihat mapping sidik jari & tes koneksi.
8. **Kelola Keranjang Tertahan** – lihat hold, batalkan & kembalikan stok.
9. **Isi Saldo Pelanggan** – top up saldo customer (hanya admin).
10. Logout Admin.

### Menu Pelanggan (`customer.py`)
1. Lihat saldo (top up dilakukan admin).
2. Cari & belanja produk (search katalog).
3. Pengurutan katalog (harga termurah/termahal, nama A-Z, stok terbanyak).
4. Lihat keranjang & **checkout** (termasuk melanjutkan keranjang tertahan).
5. Riwayat transaksi & track record.
6. Logout.

### Risk Shield (`risk_assistant.py`)
Skor risiko dihitung dari 3 indikator sebelum checkout:

| Indikator | Skor |
|---|---|
| Sisa saldo setelah transaksi < 30% saldo | +2 |
| Pengeluaran hari ini + transaksi > limit harian | +3 |
| Membeli barang `Wants` saat sisa saldo < Rp100.000 | +2 |

Status: **AMAN** (skor 0, lanjut otomatis) → **PERINGATAN SEDANG** (skor ≤3,
konfirmasi y/n) → **RISIKO TINGGI** (wajib ketik `SAYA YAKIN`). Transaksi juga
meminta PIN e-wallet; batal di tahap ini tidak mengubah saldo/stok. Khusus jalur
sidik jari, tap yang gagal akan **menahan belanjaan** (lihat bagian Keranjang Tertahan).

## Pembayaran Sidik Jari (X100C)

Pengguna bisa **login dan membayar tanpa mengetik username/PIN** memakai mesin
**ZKTeco X100C** yang terhubung ke PC via jaringan. Template sidik jari tetap di
mesin; PC hanya membaca log verifikasi terbaru.

### Cara pakai (tanpa hardware / development)

Mode default `simulasi`: cukup ketik ID perangkat saat diminta. Contoh:

1. Menu utama -> `3. Login Sidik Jari (X100C)` -> ketik `1001` (ID budi).
2. Belanja -> checkout -> saat diminta, ketik `1001` lagi untuk otorisasi.
3. Transaksi sukses tanpa PIN. ID perangkat tiap akun: budi `1001`, siti `1002`,
   andi `1003`.

### Login admin dengan sidik jari

- Admin juga bisa login lewat menu `3. Login Sidik Jari (X100C)`.
- Pencocokan tetap memakai `finger_id`: login admin biasa -> menu
  `7. Kelola Sidik Jari` -> `1. Daftarkan sidik jari ke akun`, username `admin`,
  ID perangkat jari **kedua** (harus berbeda dari finger_id customer).
- Setelah tap, aplikasi melihat `role` akun: admin -> **Menu Admin**, customer ->
  Menu Pelanggan. Satu `finger_id` hanya boleh untuk satu akun.

### Setup perangkat X100C yang sebenarnya

Setup yang sudah diverifikasi di mesin ini (X100C langsung ke port LAN laptop):

1. Hubungkan X100C ke port Ethernet laptop dengan kabel LAN (langsung, tanpa router).
2. Atur **IP statis laptop** di adapter Ethernet satu subnet dengan alat, mis.
   `192.168.1.100 / 255.255.255.0` (tanpa gateway), dan **IP statis X100C**
   `192.168.1.201 / 255.255.255.0`. Wi-Fi tetap dipakai untuk internet.
3. Di X100C: aktifkan jaringan & **PC connection**; set **comm key** = `<com_key>`
   (menu Communication/Komunikasi). Tidak perlu webserver HTTPS; yang aktif adalah
   **ZK Web Server HTTP port 80**.
4. Daftarkan user di mesin X100C dengan **ID angka** + sidik jari. ID ini yang
   dipetakan ke akun PayGuard (`finger_id`).
5. Buat `.env` dari `.env.example`, lalu isi mode `soap`, host/port, dan
   `PAYGUARD_X100C_COM_KEY` sesuai mesin (lihat bagian Konfigurasi environment).
   `data/perangkat.json` di repo tetap mode `simulasi` agar aman.
6. Login admin -> `7. Kelola Sidik Jari (X100C)`:
   - `1` daftarkan username ke ID perangkat (PIN unik),
   - `3` lihat daftar, `4` tes koneksi.
7. Uji koneksi juga bisa lewat `python fingerprint.py` (read-only, menampilkan
   jumlah log & beberapa event terakhir).
8. Untuk pengujian/test tanpa alat, set `PAYGUARD_X100C_MODE=simulasi` di `.env`;
   **test suite selalu memakai fixtures mode simulasi** agar tidak menyentuh alat asli.

Catatan jam: perangkat ini sempat tertinggal (`2026-05-19`). Jam sudah
disinkronkan ke PC (`2026-11-03`). Jika X100C mati lama/clock drift, set ulang lewat
menu **System -> Date/Time**, karena event sidik jari hanya diterima bila jamnya
masih dalam `jendela_detik` dari jam PC.

#### Troubleshooting "log tidak masuk"

1. **`Koneksi OK (0 log)` padahal mesin punya log** -> hampir pasti **COM key
   salah**. Kalau `ArgComKey` tidak cocok, webserver X100C membalas **HTTP 200**
   dengan XML **valid tapi kosong** (`<GetAttLogResponse></GetAttLogResponse>`),
   jadi tidak ada error sama sekali. Cek `PAYGUARD_X100C_COM_KEY` di `.env`
   (pabrik: `0`); bandingkan lewat `python fingerprint.py`.
2. **Log ada tapi tap baru selalu ditolak** -> jam mesin **maju** lebih besar
   dari `jendela_detik`, sehingga tanggal event ada di masa depan. Pesan
   `Tidak ada sidik jari terbaca.` akan disertai keterangan `Jam X100C maju N
   detik dari jam PC (...) padahal jendela_detik=...`. Sinkronkan jam mesin,
   atau perbesar `PAYGUARD_X100C_JENDELA_DETIK` (konsekuensi: toleransi
   anti-replay ikut melebar, karena keunikan event tetap dijaga
   `data/finger_state.json`).
3. **PIN mesin tidak ada di `users.json`** -> `Sidik jari belum terdaftar.
   Hubungi admin.`; daftarkan lewat admin `7. Kelola Sidik Jari (X100C)`.

PC memanggil webserver X100C dengan `POST /iWsService` dan perintah `GetAttLog`
(`<GetAttLog><ArgComKey .../><Arg><PIN>All</PIN></Arg></GetAttLog>`). Implementasi
memakai `socket` + `xml.etree.ElementTree` (stdlib, tanpa pip); detail di
[`SPESIFIKASI_SIDIK_JARI.md`](SPESIFIKASI_SIDIK_JARI.md). Port 4370 (ZK SDK) dipakai
hanya untuk diagnosa/sinkronisasi jam, bukan alur pembayaran.

### Keamanan

- Event sidik jari hanya diterima jika waktunya masih dalam `jendela_detik` dan
  belum pernah diproses (`data/finger_state.json`) -> anti-replay.
- Checkout jalur sidik jari tetap meminta **tap ulang** dan memastikan PIN perangkat
  cocok dengan akun yang login; PIN tidak diminta.
- Sidik jari tak dikenal, akun terkunci, atau perangkat mati -> transaksi batal /
  pesan error, data tidak berubah.
- Sebaiknya mesin X100C **dikhususkan untuk pembayaran** dan jam perangkat
  disinkronkan dengan PC (log absensi biasa juga masuk ke `GetAttLog`).


## Keranjang Tertahan (Hold Otomatis)

Kalau **verifikasi sidik jari gagal** saat checkout, belanjaan **tidak langsung
dibatalkan**:

1. **Stok barang di toko langsung dikurangi** sesuai isi keranjang.
2. Keranjang disimpan sebagai entri baru di `data/keranjang.json` (status
   `tertahan`, ID `HOLD-…`, jumlah percobaan).
3. Saldo **belum** dipotong dan transaksi belum dibuat.
4. Pesan: `Sidik jari gagal. Belanjaan ditahan di keranjang dan stok sudah dikurangi.`
5. Buka lagi menu `4. Lihat Keranjang & Checkout` → muncul
   `Lanjutkan pembayaran sekarang? (y/n)` → `y` lalu tap sidik jari.
   - sukses → hold dihapus, saldo dipotong, resi + transaksi, log
     `CHECKOUT_FINGER_RP_...`; stok tidak dipotong lagi.
   - gagal lagi → `percobaan` bertambah, hold tetap.
6. Admin dapat membatalkan hold lewat menu `8. Kelola Keranjang Tertahan`
   (stok dikembalikan, log `HOLD_CANCEL`).

File data & kontrak lengkap: [`data/keranjang.json`](data/keranjang.json) ·
[`SPESIFIKASI_HOLD_KERANJANG.md`](SPESIFIKASI_HOLD_KERANJANG.md).

## Struktur file

| File | Fungsi |
|---|---|
| `main.py` | Splash screen, menu utama, login/register, routing role |
| `auth.py` | Hash+salt PIN, register, login, lockout, verify PIN, logout |
| `admin.py` | CRUD katalog produk, audit log, buka blokir akun, kelola sidik jari, hold, isi saldo |
| `customer.py` | Lihat saldo, marketplace, keranjang, checkout (PIN/sidik jari), riwayat |
| `risk_assistant.py` | Heuristic risk engine & tampilan Risk Shield |
| `fingerprint.py` | Klien X100C (SOAP websocket), event sidik jari, anti-replay |
| `data_manager.py` | I/O JSON (users/products/logs), id produk, log, rupiah |
| `data/users.json` | Data pengguna + transaksi + `finger_id` |
| `data/products.json` | Katalog produk |
| `data/logs.json` | Audit trail aktivitas |
| `data/perangkat.json` | Konfigurasi X100C (mode/host/port/timeout) |
| `data/keranjang.json` | Keranjang tertahan (hold saat sidik jari gagal) |
| `SPESIFIKASI_PAYGUARD.md` | Kontrak kerja & pseudocode TUI |
| `SPESIFIKASI_SIDIK_JARI.md` | Kontrak fitur sidik jari X100C |
| `SPESIFIKASI_HOLD_KERANJANG.md` | Kontrak fitur hold keranjang |
| `tests/` | Test suite otomatis (unittest) |

## Format data JSON

`data/users.json` — object `username -> user`:

```json
{
  "budi": {
    "username": "budi",
    "pin_hash": "<sha256(PIN+salt)>",
    "salt": "1111111111111111",
    "balance": 500000.0,
    "daily_limit": 500000.0,
    "role": "customer",
    "is_locked": false,
    "failed_attempts": 0,
    "finger_id": "1001",
    "transactions": [
      {"id": "TRX-20261020101500", "date": "2026-10-20T10:15:00", "total": 14000.0,
       "risk_score": 0,
       "items": [{"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 2}]}
    ]
  }
}
```

`data/products.json` — object `id -> product`:

```json
{"P001": {"id": "P001", "name": "Beras 5kg", "price": 65000.0, "stock": 20, "category": "Needs"}}
```

`data/logs.json` — list audit trail:

```json
[{"time": "2026-10-20T09:00:00", "username": "admin", "action": "INIT_DATA", "detail": "..."}]
```

`data/keranjang.json` — list keranjang tertahan:

```json
[{"id": "HOLD-20261103234500", "username": "Prabu", "waktu": "2026-11-03T23:45:00",
  "items": [{"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 1}],
  "total": 2000.0, "percobaan": 1, "status": "tertahan"}]
```

## CRUD di PayGuard

| Entitas | Create | Read | Update | Delete |
|---|---|---|---|---|
| Produk | `CreateProduct` | `ReadAllProducts`, browse/search customer | `UpdateProductDetails`, `DeductProductStock` saat checkout | `DeleteProduct` |
| User | `RegisterUser` | `LoginUser`, cek saldo | isi saldo (admin), potong saldo, `failed_attempts`/`is_locked`, transaksi | tidak ada (blokir akun = soft delete) |
| Transaksi | `CreateReceipt` + `SaveTransactionToUserHistory` | `ViewTransactionHistory` | – | – (append-only) |
| Log | `catat_log` | `DisplaySystemLogs` | – | – (append-only) |
| Keranjang | `AddToCart` | `GetUserCart` / lihat keranjang | qty gabungan | `ClearUserCart` |

## Pembagian tugas (sesuai PDF, maks. 3 orang)

| Anggota | Modul | Tanggung jawab |
|---|---|---|
| Anggota 1 | `main.py`, `admin.py` | Splash & routing menu, CRUD produk, audit log, unlock akun, integrasi |
| Anggota 2 | `auth.py`, `data_manager.py`, `risk_assistant.py` | Keamanan PIN (hash+salt, lockout), I/O JSON, risk engine |
| Anggota 3 | `customer.py` | Lihat saldo, marketplace, search/sort, keranjang, checkout, riwayat |

Dependensi: `main` → `auth`/`admin`/`customer`/`fingerprint`; `customer` →
`risk_assistant`/`auth`/`data_manager`/`fingerprint`; `admin` → `data_manager`/
`fingerprint`; `fingerprint` → `data_manager`. Tidak ada import melingkar.

## Testing

```powershell
cd payguard
python -m unittest discover -s tests -v
python tests\verifikasi_final.py   # opsional: spot-check end-to-end (exit 0 = lulus)
```

Test memakai salinan `tests/fixtures/` di folder `tests/_tmp/...` (bukan
`tempfile.mkdtemp()` karena batasan sandbox Windows), sehingga data asli
`payguard/data/` tidak berubah. Hasil suite: **147 test OK** (termasuk mock perangkat
X100C berbasis `socketserver`) — lihat [`HASIL_TEST.md`](HASIL_TEST.md) dan
[`tests/HASIL_QA.md`](tests/HASIL_QA.md).

## Repositori Git / GitHub

Repo lokal sudah diinisialisasi (branch `main`). Yang **tidak** ikut di-commit:

- `.env` (berisi IP/com key X100C lokal) — buat dari `.env.example`;
- `data/finger_state.json` (state runtime sidik jari);
- `tests/_tmp/`, `tests/_*.log`, `__pycache__/`.

Push ke GitHub (buat repo kosong dulu di GitHub):

```powershell
cd payguard
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

Setelah clone di komputer lain: `Copy-Item .env.example .env`, isi nilai lokal,
lalu `python main.py`.

## Catatan

- Ini project *baru*; project `cashless` lama tetap ada di folder terpisah.
- Sandi/PIN disimpan sebagai SHA-256 + salt per user (sesuai pseudocode), bukan
  plaintext. Cocok untuk latihan, bukan produksi.
- Integrasi X100C sudah diuji dengan **perangkat asli** (login & bayar sidik jari
  tanpa PIN) dan tetap punya **mock perangkat** untuk test otomatis. Konfigurasi
  lokalnya dipisah ke `.env`; `data/perangkat.json` di repo default `simulasi`.
- Data JSON dibuat untuk demo; jangan diedit manual saat aplikasi berjalan.
- Jika memakai aplikasi setelah clone, sesuaikan data/`tests/fixtures` bila perlu
  (fixtures harus sama dengan data agar test integritas lulus).
