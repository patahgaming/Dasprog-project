# SPESIFIKASI: Hold Keranjang saat Sidik Jari Gagal

Fitur tambahan PayGuard: jika verifikasi sidik jari saat **checkout gagal**, transaksi
**tidak langsung dibatalkan**. Belanjaan **ditahan** di `data/keranjang.json`, **stok
barang di toko langsung dikurangi**, dan pembayaran dapat dilanjutkan dengan tap sidik
jari berikutnya. Saldo baru dipotong saat pembayaran berhasil.

Gaya tetap sama: TUI, prosedural, stdlib saja, pesan Bahasa Indonesia, tanpa pip.

## 1. Alur

1. User (login sidik jari) mengisi keranjang, buka menu `4. Lihat Keranjang & Checkout`.
2. Saldo & Risk Shield diperiksa seperti biasa (jika batal di sini, **tidak ada hold**).
3. Aplikasi meminta tap sidik jari (`Tempelkan sidik jari untuk mengotorisasi pembayaran...`).
4. **Gagal tap (percobaan pertama):**
   - stok produk di `data/products.json` **dikurangi** sesuai isi keranjang (dijepit >= 0);
   - keranjang disimpan sebagai entri baru di `data/keranjang.json` (status `tertahan`);
   - saldo **tidak** berubah, transaksi **tidak** dibuat;
   - keranjang memori dikosongkan;
   - pesan:
     ```
     Sidik jari gagal. Belanjaan ditahan di keranjang dan stok sudah dikurangi.
     Coba lagi lewat menu 4 untuk melanjutkan pembayaran.
     ```
   - log `HOLD_CART` detail `<id>:<total>`.
5. Saat user membuka menu `4` lagi dan keranjang memori kosong tetapi ada hold miliknya:
   ```
   Ada keranjang tertahan atas nama <username>: <id> total <Rp>.
   Lanjutkan pembayaran sekarang? (y/n):
   ```
   - `n` -> kembali ke menu (hold tetap).
   - `y` -> lanjut ke checkout memakai item hold. Risk Shield dihitung ulang
     (tanpa memotong stok lagi), lalu minta tap sidik jari.
6. **Tap berikutnya:**
   - gagal lagi -> `percobaan` hold bertambah; pesan:
     `Sidik jari gagal lagi. Belanjaan tetap ditahan (percobaan ke-<n>).`
     Data saldo/stok/transaksi tidak berubah; hold tetap.
   - berhasil -> hold dihapus dari `data/keranjang.json`; saldo dipotong; transaksi +
     resi dibuat; log `CHECKOUT_FINGER_RP_<total>`; **stok tidak dipotong ulang**.
7. Admin dapat membatalkan hold dan mengembalikan stok (menu admin baru).

## 2. File data baru: `data/keranjang.json`

List (awalnya `[]`):

```json
[
  {
    "id": "HOLD-20261103234500",
    "username": "Prabu",
    "waktu": "2026-11-03T23:45:00",
    "items": [
      {"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 1}
    ],
    "total": 2000.0,
    "percobaan": 1,
    "status": "tertahan"
  }
]
```

- `id` = `HOLD-` + `datetime.now().strftime('%Y%m%d%H%M%S')`.
- `items` sama seperti item keranjang `{"id","name","price","qty"}`.
- `total` = jumlah `price * qty`.
- `percobaan` mulai 1, bertambah tiap tap gagal lanjutan.
- Satu user boleh punya >1 hold (masing-masing entri); menu 4 mengambil hold
  **paling baru** milik user.

## 3. Perubahan `customer.py`

Fungsi baru (nama mengikuti gaya project):

```python
BacaKeranjangTertahan() -> list                 # data/keranjang.json, default []
SimpanKeranjangTertahan(daftar) -> None
CariKeranjangTertahan(username) -> dict | None  # entri terbaru status tertahan
HapusKeranjangTertahan(record_id) -> bool
TahanKeranjang(current_user, cart, total) -> dict
    # kurangi stok products, buat record, append ke keranjang.json,
    # catat_log('HOLD_CART', id+':'+total), return record
TambahPercobaanKeranjang(record) -> None
KembalikanStokKeranjang(record) -> None          # untuk admin cancel
```

- `data/keranjang.json` dibaca/ditulis lewat `data_manager.tulis_json` (atomic).
- `CheckoutProcess(current_user, metode_login='pin', keranjang_tertahan=None)`:
  - `keranjang_tertahan` diisi saat melanjutkan hold. Item diambil dari record;
    jangan potong stok saat sukses; hapus hold saat sukses.
  - Jalur PIN (`metode_login != 'sidik_jari'`) **tidak berubah**: PIN salah tetap
    `PIN Salah! Transaksi Dibatalkan.` (tanpa hold).
  - Hanya jalur sidik jari yang memicu hold.
- `CustomerMenu(current_user, metode_login='pin')` menu `4`:
  - Jika `GetUserCart()` kosong dan ada hold user -> prompt resume seperti §1.5.
  - Jika tidak -> perilaku lama.
- Pesan persis seperti §1; jangan ubah pesan lama yang tidak terkait.

## 4. Perubahan `admin.py`

Menu admin menjadi 9 opsi: tambahkan **`8. Kelola Keranjang Tertahan`**, sehingga
`9. Logout Admin` (sebelumnya 8). Submenu:

```
=== KELOLA KERANJANG TERTAHAN ===
1. Lihat keranjang tertahan
2. Batalkan & kembalikan stok
3. Kembali
Pilih menu (1-3):
```

1. List: tiap baris
   `<id> | <username> | Total <Rp> | percobaan <n> | <nama1> x<qty1>, <nama2> x<qty2>`;
   kosong -> `Tidak ada keranjang tertahan.`
2. `Masukan ID keranjang tertahan: `; tidak ada ->
   `ID keranjang tertahan tidak ditemukan.`;
   `Yakin batalkan dan kembalikan stok? (y/n): `;
   ya -> stok dikembalikan (`qty` ditambahkan), hold dihapus,
   `catat_log('admin','HOLD_CANCEL', id)`,
   `Keranjang <id> dibatalkan, stok dikembalikan.`; tidak ->
   `Pembatalan dibatalkan.`
3. Kembali.

## 5. Aturan bisnis & keamanan

- Saldo **tidak** dipotong saat hold; hanya saat sukses bayar.
- Stok dipotong tepat sekali: saat hold dibuat; sukses bayar tidak memotong lagi;
  admin cancel mengembalikan.
- Transaksi hanya dibuat saat sukses (append-only).
- Anti-replay fingerprint tetap berlaku (`finger_state.json`); hold tidak
  menghapus/mengubah state.
- Risk Shield & cek saldo tetap dilakukan **sebelum** tap sidik jari; gagal di tahap
  itu tidak membuat hold.
- Hold tidak kedaluwarsa otomatis (bisa dibatalkan admin).

## 6. Testing (QA)

Tambahan wajib:
- Unit helper hold (baca/simpan/cari/hapus, tambah percobaan, kembalikan stok).
- Integrasi sidik jari gagal #1: stok turun, `keranjang.json` +1 record benar,
  saldo & transaksi & log checkout tidak berubah, hold tidak ada di products? dst.
- Lanjutkan hold -> tap sukses: saldo turun, transaksi + resi + log
  `CHECKOUT_FINGER_RP_...`, hold hilang, stok **tidak** turun lagi.
- Lanjutkan hold -> tap gagal lagi: `percobaan` +1, hold tetap, saldo/stok/transaksi tetap.
- Resume `n` -> hold tetap, tidak ada perubahan.
- Jalur PIN salah tetap tanpa hold.
- Admin list/cancel: stok kembali, hold hilang, log `HOLD_CANCEL`; ID tidak ada.
- `keranjang.json` ditambahkan ke `DATA_FILES`/fixtures (awal `[]`) dan uji integritas;
  fixture tetap simulasi perangkat.
- Jalankan `python -m unittest discover -s tests -v` + `tests\verifikasi_final.py`.

## 7. Kriteria penerimaan

1. Tap sidik jari gagal 1x saat checkout TIDAK membatalkan belanjaan; stok berkurang
   dan `data/keranjang.json` bertambah.
2. Pembayaran bisa dilanjutkan (menu 4) dan sukses tanpa PIN; saldo dipotong,
   transaksi tercatat, stok tidak dobel.
3. Gagal lanjutan menambah `percobaan` tanpa mengubah saldo/stok/transaksi.
4. Admin bisa membatalkan hold & mengembalikan stok.
5. Data lama (users/products/logs/perangkat/finger_state) tetap kompatibel;
   test lama tetap lulus.
