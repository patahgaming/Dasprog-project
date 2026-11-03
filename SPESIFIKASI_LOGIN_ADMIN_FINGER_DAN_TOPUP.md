# SPESIFIKASI: Login Sidik Jari Admin & Top Up oleh Admin

Dua perubahan akses:
1. Login sidik jari X100C mengikuti **role** akun: `admin` -> Menu Admin,
   `customer` -> Menu Pelanggan.
2. **Top up hanya oleh admin.** Customer tidak lagi punya menu top up (hanya lihat
   saldo). Admin punya menu baru `9. Isi Saldo Pelanggan`.

Gaya tetap: TUI, prosedural, stdlib saja, pesan Bahasa Indonesia.

## 1. Login sidik jari berdasarkan role (`main.py`)

`LoginFingerFlow()` saat event sidik jari cocok (`fingerprint.cari_user_dari_pin`):

```
Sidik jari dikenali: <username>.
```

lalu:

- `user["role"] == "admin"`:
  ```
  Login berhasil! Selamat datang, admin.
  ```
  -> `admin.AdminMenu()` (tanpa PIN, tanpa CustomerMenu).
- selain itu (customer):
  -> `customer.CustomerMenu(user, metode_login='sidik_jari')` seperti sekarang.

Catatan:
- Akun admin harus punya `finger_id` (dipetakan lewat menu admin
  `7. Kelola Sidik Jari` -> `1. Daftarkan sidik jari ke akun`, username `admin`,
  PIN perangkat yang belum dipakai akun lain). Tanpa mapping, login sidik jari
  akan `Sidik jari belum terdaftar. Hubungi admin.`
- Satu `finger_id` hanya untuk satu akun; kalau ingin admin & customer memakai
  sidik jari, daftarkan dua jari/PIN perangkat berbeda.
- Cek `is_locked` tetap berlaku untuk semua role.

## 2. Menu pelanggan `customer.py`

Menu menjadi (nomor tetap 6 opsi):

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

- `1` -> fungsi `LihatSaldo(current_user)`:
  cetak `Saldo Anda: <Rp>.`
- **Tidak ada lagi top up di menu customer.** `HandleTopUp` dihapus dari menu
  (boleh tetap ada sebagai fungsi internal tapi tidak dipanggil; bila tidak dipakai
  lain, hapus agar bersih).
- Opsi 2-6 tetap seperti sekarang (termasuk resume keranjang tertahan di opsi 4).

## 3. Menu admin & top up (`admin.py`)

Menu admin menjadi **10 opsi** (opsi 1-8 tidak berubah; logout bergeser):

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

- `9` -> `IsiSaldoPelanggan()`:

```
--- ISI SALDO PELANGGAN ---
Masukan username pelanggan: <input>
```

Validasi/pesan:
- username kosong/tidak ada -> `User tidak ditemukan.`
- role bukan `customer` -> `Hanya akun pelanggan yang bisa diisi saldo.`
- print `Saldo saat ini: <Rp>`
- `Masukan nominal isi saldo: <input>`; bukan angka bulat / <= 0 ->
  `Nominal isi saldo tidak valid!`
- sukses: `balance` target += nominal; simpan users;
  `catat_log("admin", "TOPUP", "<username>:<nominal>")`;
  print `Isi saldo berhasil! Saldo <username> sekarang <Rp>.`

- `10` Logout -> `catat_log("admin","LOGOUT")`, `Logout berhasil.` return.

Fungsi baru admin: `IsiSaldoPelanggan()`; submenu lain tetap.
Tidak ada perubahan pada CRUD produk/audit/unlock/sidik jari/keranjang tertahan.

## 4. Dampak file

| File | Perubahan |
|---|---|
| `main.py` | routing role pada `LoginFingerFlow` |
| `customer.py` | menu 1 jadi `Lihat Saldo`; top up dihapus dari menu |
| `admin.py` | menu 10 opsi + `IsiSaldoPelanggan()` |
| `README.md` / spesifikasi | menu & alur top up diperbarui |
| `tests/` | test lama top up customer & nomor menu disesuaikan |

Data (`users.json`, `products.json`, `logs.json`, `keranjang.json`,
`perangkat.json`) tidak perlu diubah.

## 5. Test wajib (QA)

- Login sidik jari admin: fixture/work copy diberi `admin.finger_id` (mis.
  `2001`), mode simulasi input `2001` -> tampil `Menu Admin`, bukan Menu Pelanggan;
  admin menu 10 opsi & prompt `1-10`.
- Login sidik jari customer (budi 1001) -> tetap Menu Pelanggan.
- Customer menu 1: hanya `Saldo Anda: ...`, tidak ada prompt top up/nominal.
- Admin menu 9 top up customer: saldo target bertambah, log
  `admin: TOPUP` detail `<target>:<nominal>`, saldo admin/target lain tidak berubah;
  username tidak ada & role admin ditolak; nominal `abc`, `0`, `-5` ditolak.
- Regresi: CRUD produk, sidik jari (enroll/unenroll), keranjang tertahan, checkout,
  lockout/unlock.
- Update nomor menu admin: logout `9` -> `10`, prompt `1-10`; sesuaikan semua
  skenario stdin. Test top up lama (customer) dipindah ke alur admin.
- `verifikasi_final.py`: spot-check top up memakai admin; tambah spot-check login
  sidik jari admin bila memungkinkan. Hermetis (fixtures perangkat simulasi,
  `.env` tidak disalin).
- Suite + verifikasi final harus LULUS.

## 6. Kriteria penerimaan

1. Sidik jari akun admin -> Menu Admin; sidik jari customer -> Menu Pelanggan.
2. Customer tidak bisa top up dari menu; hanya melihat saldo.
3. Admin bisa isi saldo customer (validasi & log), menu 9; logout 10.
4. Semua test + verifikasi final LULUS; data asli tidak berubah karena test.
