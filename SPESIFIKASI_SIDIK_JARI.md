# SPESIFIKASI FITUR: Pembayaran Sidik Jari X100C

Fitur baru di project `payguard/`: pembayaran dengan sidik jari memakai mesin
**ZKTeco X100C** yang terhubung ke PC lewat jaringan (mode webserver/SOAP).
Pengguna cukup menempelkan sidik jari — **tanpa mengetik username, PIN, atau
password** — untuk login dan mengotorisasi pembayaran.

Fitur ditambahkan dengan gaya yang sama seperti project: TUI (`input`/`print`),
fungsi prosedural, pesan Bahasa Indonesia, **stdlib saja (tanpa pip)**, dan tetap
bisa dipakai tanpa perangkat lewat mode simulasi.

## 1. Ringkasan alur

1. Admin mendaftarkan sidik jari: `username` PayGuard ↔ **ID perangkat (PIN X100C)**
   (sidik jari sendiri di-enroll di mesin X100C).
2. Di menu utama pengguna memilih **Login Sidik Jari (X100C)**.
3. Pengguna menempelkan sidik jari di mesin; PC membaca log verifikasi terbaru dari
   X100C (`GetAttLog`), mencocokkan PIN perangkat ke akun PayGuard.
4. Setelah dikenali, menu pelanggan terbuka (tanpa PIN).
5. Saat checkout, pengguna menempelkan sidik jari **sekali lagi** untuk otorisasi
   pembayaran; PIN tidak diminta, saldo langsung dipotong dan struk dicetak.

## 2. Batasan & keamanan

- Fingerprint hanya dipakai sebagai **kredensial pembayaran**; template sidik jari
  tetap tersimpan di mesin X100C, PC hanya menerima log (PIN, waktu, status).
- Event hanya valid jika:
  - waktunya (`DateTime` perangkat) masih dalam **`jendela_detik`** dari waktu PC;
  - belum pernah diproses (tidak bisa replay) — disimpan di `data/finger_state.json`;
  - `PIN` event cocok dengan `finger_id` akun yang sedang login (untuk checkout).
- PIN perangkat **unik** antar akun PayGuard.
- Akun terblokir tidak boleh login sidik jari.
- Sidik jari yang belum dipetakan ditolak: `Sidik jari belum terdaftar. Hubungi admin.`
- Untuk meminimalkan salah-trigger dari log absensi, mesin X100C sebaiknya
  **dikhususkan untuk pembayaran** dan jam perangkat disinkronkan dengan PC.
- Mode `simulasi` (default) untuk development/tanpa alat: input ID perangkat
  diketik manual.

## 3. File & perubahan data

### 3.1 `data/perangkat.json` (baru, konfigurasi)

```json
{
  "mode": "simulasi",
  "host": "192.168.1.201",
  "port": 80,
  "com_key": 0,
  "timeout": 5,
  "jendela_detik": 30,
  "batas_tunggu_detik": 20
}
```

| Key | Arti |
|---|---|
| `mode` | `"simulasi"` (tanpa alat) atau `"soap"` (X100C via LAN) |
| `host` | IP mesin X100C |
| `port` | port webserver X100C (default 80) |
| `com_key` | communication key perangkat (default 0) |
| `timeout` | timeout socket (detik) |
| `jendela_detik` | umur maksimum event agar dianggap valid |
| `batas_tunggu_detik` | lama menunggu sidik jari di mode soap |

File boleh tidak ada → default `simulasi`. Nilai config dibaca ulang setiap kali
fungsi perangkat dipanggil (tanpa cache).

### 3.2 `data/users.json` — field baru

Setiap user punya `finger_id` (string, default `""`). Seed:

| Username | finger_id |
|---|---|
| admin | `""` |
| budi | `"1001"` |
| siti | `"1002"` |
| andi | `"1003"` |

`RegisterUser` wajib menambahkan `"finger_id": ""` untuk user baru.

### 3.3 `data/finger_state.json` (runtime, dibuat otomatis)

```json
{"terproses": ["1001|2026-11-03 12:00:00|1"]}
```

Menyimpan minimal 200 kunci event terakhir (format
`<pin>|<datetime>|<status>`) supaya tidak diproses dua kali.

## 4. Modul baru: `fingerprint.py` (stdlib saja)

### 4.1 Konfigurasi & state

```python
MODE_SIMULASI = 'simulasi'
MODE_SOAP = 'soap'
PERANGKAT_FILE = <payguard>/data/perangkat.json
STATE_FILE     = <payguard>/data/finger_state.json

baca_perangkat() -> dict      # default + isi file; file rusak/tidak ada -> default
baca_state() -> dict          # {"terproses": [...]}
simpan_state(state) -> None   # tulis lewat data_manager.tulis_json (atomic)
```

### 4.2 Klien SOAP X100C (tanpa library eksternal)

Protokol (berdasarkan interface webserver X100C/Solution):

- Buka TCP ke `host:port`, kirim HTTP POST:
  ```
  POST /iWsService HTTP/1.0
  Content-Length: <panjang xml>
  Content-Type: text/xml;

  <XML>
  ```
- **Root elemen XML = nama perintah**, dengan `ArgComKey` + `Arg` di dalamnya.
  Contoh request `GetAttLog` (PIN `All`):
  ```xml
  <GetAttLog><ArgComKey xsi:type="xsd:integer">0</ArgComKey>
    <Arg><PIN>All</PIN></Arg></GetAttLog>
  ```
  Contoh `GetUserInfo`:
  ```xml
  <GetUserInfo><ArgComKey xsi:type="xsd:integer">0</ArgComKey>
    <Arg><PIN>1001</PIN></Arg></GetUserInfo>
  ```
  `buat_xml('GetAttLog', {'PIN': 'All'}, 0)` harus menghasilkan persis bentuk di
  atas (tanpa wrapper `<Command>`/`<CommandName>`).
- Response berisi root `<GetAttLogResponse>` dengan elemen `<Row>` (atau
  `<GetUserInfoResponse><Row>`); setiap Row berisi field `<PIN>`, `<DateTime>`,
  `<Verified>`, `<Status>`, `<WorkCode>` (untuk GetAttLog).
- Baca sampai koneksi ditutup / XML response lengkap; ambil body setelah
  `\r\n\r\n`, parse dengan `xml.etree.ElementTree`.
- Command yang dipakai: `GetAttLog` (arg `PIN` = `All` atau PIN), `GetUserInfo`
  (arg `PIN`).

Fungsi:

```python
buat_xml(command, args=None, com_key=0) -> str
kirim_soap(xml_teks, perangkat=None) -> str        # body response; raise OSError/TimeoutError
parse_rows(xml_teks) -> list[dict]                 # semua <Row> -> dict field
get_attlog(perangkat=None) -> list[dict]           # semua log verifikasi
get_user_info(pin, perangkat=None) -> dict|None    # cek PIN ada di perangkat
tes_koneksi(perangkat=None) -> (bool, str)         # (ok, pesan)
```

Pesan error koneksi (ditangkap pemanggil):
`Perangkat X100C tidak terhubung. Periksa kabel/jaringan dan konfigurasi.`

### 4.3 Event & pencocokan

```python
kunci_kejadian(event) -> str                       # "<pin>|<datetime>|<status>"
ambil_kejadian_baru(perangkat=None, jendela_detik=None) -> list[dict]
    # baca GetAttLog -> filter DateTime masih fresh -> buang yang sudah terproses
    # -> urutkan dari paling lama -> list event
tandai_kejadian(event) -> None                     # simpan kunci ke state (maks 200)
cari_user_dari_pin(pin) -> dict|None               # cari user dengan finger_id == pin
kejadian_simulasi(pin) -> dict                     # event palsu: datetime sekarang, status "1"
tunggu_sidik_jari(perangkat=None) -> dict|None     # baca event berikutnya
verifikasi_sidik_jari(user, perangkat=None) -> (bool, dict|None)
```

- Mode `simulasi`:
  - `tunggu_sidik_jari`: print prompt `(SIMULASI) Masukkan ID perangkat: ` lalu
    `input()`; input kosong -> `None`; selain itu `kejadian_simulasi(pin)`.
  - `verifikasi_sidik_jari`: prompt yang sama, cocokkan `pin` dengan
    `user["finger_id"]`; salah -> print `Sidik jari tidak cocok.`, return `(False, None)`.
- Mode `soap`:
  - `tunggu_sidik_jari`: print `Menunggu sidik jari pada perangkat X100C...`; polling
    tiap 0.5 detik sampai `batas_tunggu_detik`; event pertama/terbaru yang fresh
    dipakai lalu `tandai_kejadian`; tidak ada -> print `Tidak ada sidik jari terbaca.`
    dan return `None`; error koneksi -> print pesan error di atas, return `None`.
  - `verifikasi_sidik_jari`: sama, tetapi hanya menerima event milik user
    (`pin == user["finger_id"]`); event user lain tidak dikonsumsi; jika habis waktu
    print `Sidik jari tidak terbaca.`; jika ada event user lain/PIN beda ->
    `Sidik jari tidak cocok.`.
  - `verifikasi_sidik_jari` untuk user tanpa `finger_id` -> print
    `Akun belum terdaftar sidik jari.`, `(False, None)`.
  - Diagnosa jam (`pesan_tidak_terbaca`, read-only): kalau log terakhir di mesin
    **bertanggal di masa depan** (> 2 detik dari jam PC), jam X100C pasti maju
    sehingga tap baru ditolak `jendela_detik`; pesan di atas ditambah keterangan
    `Jam X100C maju N detik dari jam PC (...) padahal jendela_detik=...
    Sinkronkan jam mesin (Menu > System > Date/Time) atau perbesar
    PAYGUARD_X100C_JENDELA_DETIK.` Selisih negatif tidak dilaporkan karena tidak
    bisa dibedakan dari log yang memang sudah lama.
- Event yang dipakai harus `tandai_kejadian` agar tidak bisa replay.

### 4.4 Demo `__main__`

`python fingerprint.py` menampilkan mode, hasil `tes_koneksi`, dan jumlah/log
terakhir — **read-only** (tidak menandai event).

## 5. Perubahan TUI

### 5.1 `main.py` — menu utama baru

```
1. Login
2. Register
3. Login Sidik Jari (X100C)
4. Keluar
Pilih menu (1-4):
```

- `3` -> `LoginFingerFlow()`:
  ```
  --- LOGIN SIDIK JARI (X100C) ---
  <prompt/menunggu dari fingerprint.tunggu_sidik_jari()>
  Sidik jari dikenali: <username>.
  ```
  lalu **berdasarkan role**:
  - role `admin` -> print `Login berhasil! Selamat datang, admin.` lalu
    `admin.AdminMenu()` (login admin via sidik jari, tanpa PIN).
  - role customer -> `customer.CustomerMenu(user, metode_login='sidik_jari')`.
  - event/tidak terbaca: pesan sudah dicetak `fingerprint`, kembali menu utama.
  - PIN tidak dikenal: `Sidik jari belum terdaftar. Hubungi admin.`
  - akun terkunci: `Akun terblokir karena percobaan PIN salah berulang kali. Hubungi Admin.`
  - Admin harus punya `finger_id` (dipetakan lewat menu admin `7`); satu `finger_id`
    hanya untuk satu akun (butuh jari/PIN perangkat berbeda untuk admin & customer).
- `4` -> `Terima kasih telah menggunakan PayGuard.` exit 0.
- `main.py` meng-import `fingerprint`, `admin`, dan `customer`.

### 5.2 `customer.py` — checkout tanpa PIN

- Signature baru: `CustomerMenu(current_user, metode_login='pin')` dan
  `CheckoutProcess(current_user, metode_login='pin', keranjang_tertahan=None)`
  (default `'pin'`, perilaku lama tetap).
- Pada checkout setelah Risk Shield disetujui:
  - `metode_login == 'sidik_jari'`:
    ```
    Tempelkan sidik jari untuk mengotorisasi pembayaran...
    ```
    panggil `fingerprint.verifikasi_sidik_jari(current_user)`.
    - gagal pada percobaan pertama (keranjang normal): **jangan batalkan**; panggil
      `TahanKeranjang(...)` — stok products berkurang, record masuk
      `data/keranjang.json`, saldo/transaksi tidak berubah, pesan sesuai
      `SPESIFIKASI_HOLD_KERANJANG.md`;
    - gagal saat melanjutkan hold: tambah `percobaan`, hold tetap;
    - sukses: hapus hold (jika resume), potong saldo, resi, transaksi, log
      `CHECKOUT_FINGER_RP_<total bulat>` (detail = trx id);
  - selain itu: perilaku lama (minta PIN).
  - `CustomerMenu` menu `4`: bila cart memori kosong dan ada hold user -> prompt
    resume (`y` lanjutkan, `n` kembali).

### 5.3 `admin.py` — kelola sidik jari

Menu admin menjadi:

```
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

`7` -> menu:
```
=== KELOLA SIDIK JARI (X100C) ===
1. Daftarkan sidik jari ke akun
2. Hapus pendaftaran sidik jari
3. Lihat daftar sidik jari
4. Tes koneksi X100C
5. Kembali
Pilih menu (1-5):
```

1. `Masukan username: `; tidak ada -> `User tidak ditemukan.`;
   `Masukan ID perangkat (PIN X100C): `; kosong -> `ID perangkat tidak boleh kosong.`;
   bukan angka -> `ID perangkat harus berupa angka.`;
   sudah dipakai akun lain -> `ID perangkat sudah dipakai akun '<username>'.`;
   mode soap: cek `get_user_info(pin)` -> jika perangkat tidak terhubung, print
   `Peringatan: perangkat tidak dapat dicek. Pendaftaran disimpan.`; jika PIN tidak
   ada di perangkat -> `Peringatan: PIN tidak ditemukan di perangkat. Pendaftaran disimpan.`
   Simpan `finger_id`, `catat_log("admin","FINGER_ENROLL", username+":"+pin)`,
   print `Sidik jari akun '<username>' terdaftar dengan ID perangkat <pin>.`
2. `Masukan username: `; tidak ada; tanpa finger_id -> `Akun tidak punya pendaftaran sidik jari.`;
   hapus field, `catat_log("admin","FINGER_UNENROLL", username)`,
   print `Pendaftaran sidik jari akun '<username>' dihapus.`
3. `--- DAFTAR SIDIK JARI ---`; tiap baris `<username> -> PIN <finger_id>`;
   kosong -> `Belum ada akun terdaftar sidik jari.`
4. `tes_koneksi()`: mode simulasi -> `Mode simulasi: perangkat tidak dihubungi.`;
   sukses -> `Koneksi X100C OK: <host>:<port> (<n> log).`;
   gagal -> `Koneksi X100C GAGAL: <pesan>.`
5. kembali ke menu admin.
- `8` -> `MenuKeranjangTertahan()` (lihat `SPESIFIKASI_HOLD_KERANJANG.md` §4:
  lihat / batalkan & kembalikan stok / kembali).
- `9` -> `IsiSaldoPelanggan()`: admin isi saldo customer
  (`SPESIFIKASI_PAYGUARD.md` §4.5.9); customer tidak lagi top up sendiri.
- `10` Logout -> log `LOGOUT`, print `Logout berhasil.`

## 6. Pengujian (QA)

Tambahan test wajib:

- Unit `fingerprint.py` tanpa perangkat:
  - `buat_xml('GetAttLog', {'PIN':'All'}, 0)` berisi tag yang benar;
  - `parse_rows` pada contoh XML response (2 Row) -> list dict benar;
  - `kunci_kejadian`, dedupe state (`tandai_kejadian` -> tidak muncul lagi);
  - `baca_perangkat` default ketika file tidak ada; override dari file.
- Mock perangkat X100C: server TCP lokal (stdlib `socketserver`) di
  `127.0.0.1:<port acak>` meniru respons `POST /iWsService` + XML `GetAttLog`,
  lalu test `get_attlog`/`tes_koneksi` lewat config `perangkat.json` salinan test.
- Integrasi simulasi (subprocess `main.py` dengan data salinan):
  - admin kelola sidik jari: daftar/hapus/lihat/unik/test (mode simulasi);
  - login sidik jari `budi` (1001) -> menu pelanggan; `andi` (1003, terkunci) ditolak;
    PIN 9999 tak dikenal -> `Sidik jari belum terdaftar. Hubungi admin.`;
  - checkout sidik jari: login 1001 -> beli -> checkout -> prompt simulasi 1001 ->
    sukses tanpa PIN, saldo/stok/transaksi/log `CHECKOUT_FINGER_...` benar;
  - checkout sidik jari PIN salah (input 1002) -> **hold keranjang** (stok turun,
    `keranjang.json` +1), saldo/transaksi tidak berubah; resume + tap benar -> bayar
    sukses; resume gagal -> `percobaan` +1 (detail `SPESIFIKASI_HOLD_KERANJANG.md`);
  - replay: event yang sudah dipakai tidak bisa dipakai ulang (state);
  - mode soap ke host yang tidak mendengarkan -> pesan `Perangkat X100C tidak
    terhubung...`, tidak crash, exit 0.
- Update seluruh test lama yang memakai nomor menu: keluar `3` -> `4`, logout admin
  `9`, menu admin 9 opsi (termasuk `8. Kelola Keranjang Tertahan`).
- Fixtures disalin ulang setelah `data/users.json`, `data/logs.json`,
  `data/keranjang.json`, atau `data/perangkat.json` berubah.
- Integritas: SHA256 `data/users|products|logs|keranjang.json` asli tetap sama
  sebelum/sesudah suite; fixture `perangkat.json` tetap simulasi.

## 7. Kriteria penerimaan

1. Mode simulasi: login & bayar sidik jari tanpa username/PIN, semua lulus test.
2. Mapping sidik jari bisa didaftarkan/dihapus/dilihat admin, unik, tercatat di log.
3. Klien SOAP X100C benar terhadap mock server (XML request & parsing response),
   error koneksi ditangani rapi.
4. Tidak ada event replay; event kadaluwarsa ditolak; akun terkunci ditolak.
5. Checkout jalur sidik jari tidak meminta PIN; jalur login normal tetap memakai PIN.
6. Data asli tidak berubah karena test; tidak ada dependensi pip baru (stdlib saja).
7. Dokumentasi setup X100C (IP/webserver/mapping) ada di README.
