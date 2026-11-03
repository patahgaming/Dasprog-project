"""Suite test fitur **HOLD KERANJANG** PayGuard CLI (unittest, stdlib).

Kontrak acuan: ``payguard/SPESIFIKASI_HOLD_KERANJANG.md`` (§1–§7) dan
``SPESIFIKASI_SIDIK_JARI.md``.

Fitur: bila tap sidik jari saat checkout GAGAL, belanjaan tidak dibatalkan tetapi
ditahan di ``data/keranjang.json`` dan stok langsung dikurangi; user bisa melanjutkan
pembayaran lewat menu 4 (tap sidik jari berikutnya) atau admin membatalkan hold dan
mengembalikan stok.

Pola pengujian sama dengan ``test_fingerprint.py`` (import base class & helper dari
modul itu): folder kerja ``tests/_tmp/kasus_<uuid>``, salinan semua ``*.py`` + data
fixtures (termasuk ``keranjang.json``), aplikasi dijalankan sebagai subprocess dengan
``cwd`` folder kerja. Fixtures perangkat tetap mode simulasi (hermetis, tidak
menghubungi device asli 192.168.1.201).
"""

import json
import unittest

from test_fingerprint import (  # noqa: E402 - satu folder tests/
    DasarTest,
    KELUAR,
    LOGOUT_CUSTOMER,
    input_login,
    input_sidik_jari,
)

# ---------------------------------------------------------------------------
# Driver unit helper hold (subprocess di folder kerja salinan)
# ---------------------------------------------------------------------------

DRIVER_BACA_SIMPAN = r'''
import json
import os
import sys

sys.path.insert(0, sys.argv[1])

import customer

hasil = {}
try:
    hasil["awal"] = customer.BacaKeranjangTertahan()
    contoh = [{
        "id": "HOLD-TES-1",
        "username": "budi",
        "waktu": "2026-11-03T23:00:00",
        "items": [{"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 1}],
        "total": 2000.0,
        "percobaan": 1,
        "status": "tertahan",
    }]
    customer.SimpanKeranjangTertahan(contoh)
    hasil["setelah"] = customer.BacaKeranjangTertahan()
    jalur = os.path.join(sys.argv[1], "data", "keranjang.json")
    hasil["file_ada"] = os.path.isfile(jalur)
    if hasil["file_ada"]:
        with open(jalur, encoding="utf-8") as berkas:
            hasil["file"] = json.load(berkas)
except Exception as galat:  # noqa: BLE001
    hasil["exception"] = type(galat).__name__ + ": " + str(galat)
print(json.dumps(hasil))
'''

DRIVER_CARI_HAPUS = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

import customer

hasil = {}
try:
    daftar = [
        {"id": "HOLD-A", "username": "budi", "waktu": "2026-11-03T23:00:00",
         "items": [{"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 1}],
         "total": 2000.0, "percobaan": 1, "status": "tertahan"},
        {"id": "HOLD-B", "username": "budi", "waktu": "2026-11-03T23:05:00",
         "items": [{"id": "P006", "name": "Cokelat Premium", "price": 25000.0, "qty": 1}],
         "total": 25000.0, "percobaan": 1, "status": "tertahan"},
        {"id": "HOLD-C", "username": "siti", "waktu": "2026-11-03T23:06:00",
         "items": [{"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 2}],
         "total": 4000.0, "percobaan": 1, "status": "tertahan"},
    ]
    customer.SimpanKeranjangTertahan(daftar)
    terbaru_budi = customer.CariKeranjangTertahan("budi")
    hasil["terbaru_budi"] = None if terbaru_budi is None else terbaru_budi.get("id")
    hasil["terbaru_siti"] = (customer.CariKeranjangTertahan("siti") or {}).get("id")
    hasil["tidak_ada"] = customer.CariKeranjangTertahan("tidakada")
    hasil["hapus_ada"] = customer.HapusKeranjangTertahan("HOLD-A")
    hasil["hapus_tidak"] = customer.HapusKeranjangTertahan("HOLD-ZZZ")
    hasil["sisa"] = [r.get("id") for r in customer.BacaKeranjangTertahan()]
except Exception as galat:  # noqa: BLE001
    hasil["exception"] = type(galat).__name__ + ": " + str(galat)
print(json.dumps(hasil))
'''

DRIVER_TAHAN = r'''
import json
import os
import sys

sys.path.insert(0, sys.argv[1])

import customer

hasil = {}
try:
    folder = os.path.join(sys.argv[1], "data")
    with open(os.path.join(folder, "users.json"), encoding="utf-8") as berkas:
        users = json.load(berkas)
    budi = users["budi"]
    saldo_awal = budi["balance"]
    jumlah_trx_awal = len(budi.get("transactions", []))
    cart = [{"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 2}]
    record = customer.TahanKeranjang(budi, cart, 4000.0)
    with open(os.path.join(folder, "products.json"), encoding="utf-8") as berkas:
        products = json.load(berkas)
    with open(os.path.join(folder, "logs.json"), encoding="utf-8") as berkas:
        logs = json.load(berkas)
    hasil = {
        "record": record,
        "stok_p005": products["P005"]["stock"],
        "keranjang": customer.BacaKeranjangTertahan(),
        "log_baru": logs[-2:],
        "saldo_awal": saldo_awal,
        "jumlah_trx_awal": jumlah_trx_awal,
        "keranjang_file": os.path.isfile(os.path.join(folder, "keranjang.json")),
    }
except Exception as galat:  # noqa: BLE001
    hasil = {"exception": type(galat).__name__ + ": " + str(galat)}
print(json.dumps(hasil))
'''

DRIVER_PERCOBAAN_STOK = r'''
import json
import os
import sys

sys.path.insert(0, sys.argv[1])

import customer

hasil = {}
try:
    folder = os.path.join(sys.argv[1], "data")
    with open(os.path.join(folder, "users.json"), encoding="utf-8") as berkas:
        users = json.load(berkas)
    cart = [{"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 2}]
    record = customer.TahanKeranjang(users["budi"], cart, 4000.0)
    with open(os.path.join(folder, "products.json"), encoding="utf-8") as berkas:
        stok_setelah_hold = json.load(berkas)["P005"]["stock"]
    customer.TambahPercobaanKeranjang(record)
    daftar = customer.BacaKeranjangTertahan()
    customer.KembalikanStokKeranjang(record)
    with open(os.path.join(folder, "products.json"), encoding="utf-8") as berkas:
        stok_setelah_kembali = json.load(berkas)["P005"]["stock"]
    hasil = {
        "percobaan_file": daftar[0]["percobaan"] if daftar else None,
        "percobaan_record": record.get("percobaan"),
        "stok_setelah_hold": stok_setelah_hold,
        "stok_setelah_kembali": stok_setelah_kembali,
    }
except Exception as galat:  # noqa: BLE001
    hasil = {"exception": type(galat).__name__ + ": " + str(galat)}
print(json.dumps(hasil))
'''


# ---------------------------------------------------------------------------
# 1. Unit helper hold (customer.py) — dijalankan di folder kerja salinan
# ---------------------------------------------------------------------------

class TestUnitHelperHold(DasarTest):
    def test_unit_baca_dan_simpan_keranjang(self):
        data = self.jalankan_driver(DRIVER_BACA_SIMPAN)
        self.assertNotIn("exception", data, msg=str(data))
        self.assertEqual(data["awal"], [], msg="keranjang.json seed harus []")
        self.assertEqual(len(data["setelah"]), 1)
        record = data["setelah"][0]
        self.assertEqual(record["id"], "HOLD-TES-1")
        self.assertEqual(record["username"], "budi")
        self.assertEqual(record["total"], 2000.0)
        self.assertEqual(record["status"], "tertahan")
        self.assertTrue(data["file_ada"])
        self.assertEqual(data["file"], data["setelah"],
                         msg="isi file keranjang.json harus sama dengan hasil baca")

    def test_unit_cari_terbaru_dan_hapus(self):
        data = self.jalankan_driver(DRIVER_CARI_HAPUS)
        self.assertNotIn("exception", data, msg=str(data))
        self.assertEqual(data["terbaru_budi"], "HOLD-B",
                         msg="CariKeranjangTertahan harus mengembalikan hold terbaru")
        self.assertEqual(data["terbaru_siti"], "HOLD-C")
        self.assertIsNone(data["tidak_ada"])
        self.assertTrue(data["hapus_ada"])
        self.assertFalse(data["hapus_tidak"])
        self.assertEqual(data["sisa"], ["HOLD-B", "HOLD-C"])

    def test_unit_tahan_keranjang_kurangi_stok_dan_log(self):
        data = self.jalankan_driver(DRIVER_TAHAN)
        self.assertNotIn("exception", data, msg=str(data))
        record = data["record"]
        self.assertRegex(record["id"], r"^HOLD-\d{14}$")
        self.assertEqual(record["username"], "budi")
        self.assertRegex(record["waktu"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.assertEqual(record["items"],
                         [{"id": "P005", "name": "Kopi Sachet", "price": 2000.0, "qty": 2}])
        self.assertEqual(record["total"], 4000.0)
        self.assertEqual(record["percobaan"], 1)
        self.assertEqual(record["status"], "tertahan")
        self.assertEqual(len(data["keranjang"]), 1)
        self.assertEqual(data["keranjang"][0]["id"], record["id"])
        self.assertEqual(data["stok_p005"], 98, msg="stok harus langsung turun saat hold")
        self.assertTrue(data["keranjang_file"])
        # log HOLD_CART detail <id>:<total>
        aksi = [catatan.get("action") for catatan in data["log_baru"]]
        self.assertIn("HOLD_CART", aksi)
        catatan = [c for c in data["log_baru"] if c.get("action") == "HOLD_CART"][0]
        self.assertEqual(catatan.get("username"), "budi")
        detail = str(catatan.get("detail", ""))
        self.assertTrue(detail.startswith(record["id"] + ":"), msg=f"detail={detail!r}")
        self.assertEqual(float(detail.split(":", 1)[1]), 4000.0)

    def test_unit_tambah_percobaan_dan_kembalikan_stok(self):
        data = self.jalankan_driver(DRIVER_PERCOBAAN_STOK)
        self.assertNotIn("exception", data, msg=str(data))
        self.assertEqual(data["percobaan_file"], 2,
                         msg="TambahPercobaanKeranjang harus menaikkan percobaan di file")
        self.assertEqual(data["percobaan_record"], 2)
        self.assertEqual(data["stok_setelah_hold"], 98)
        self.assertEqual(data["stok_setelah_kembali"], 100,
                         msg="KembalikanStokKeranjang harus mengembalikan stok")


# ---------------------------------------------------------------------------
# 2. Integrasi: hold keranjang saat checkout sidik jari gagal (mode simulasi)
# ---------------------------------------------------------------------------

class TestHoldKeranjang(DasarTest):
    def _prefix_hold(self, qty=2):
        """Login sidik jari budi -> beli Kopi Sachet xqty -> checkout dengan tap salah.

        Setelah prefix ini, hold sudah terbentuk dan kembali ke menu pelanggan.
        """
        return (
            input_sidik_jari("1001")
            + "2\nkopi\nP005\n" + str(qty) + "\n"
            + "4\n1002\n"          # tap sidik jari siti -> gagal -> hold
        )

    def _baca_hold(self):
        return self.baca_keranjang_hasil()

    def _siapkan_hold_persisten(self, qty=2):
        hasil = self.jalankan_app(self._prefix_hold(qty) + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        holds = self._baca_hold()
        self.assertEqual(len(holds), 1, msg=f"holds={holds!r}" + self.info(hasil))
        return hasil, holds[0]

    # -- pembentukan hold ---------------------------------------------------

    def test_tap_gagal_pertama_membuat_hold_dan_cart_memori_kosong(self):
        produk = self.produk_fixture("P005")
        total = float(produk["price"]) * 2
        hasil = self.jalankan_app(
            self._prefix_hold()
            + "4\n"
            + "n\n"
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        record = self._assert_hold_pertama(hasil)
        self.assert_teks(hasil, "Ada keranjang tertahan atas nama budi:")
        self.assert_teks(hasil, record["id"])
        self.assert_teks(hasil, "total " + self.rupiah_teks(total) + ".")
        self.assert_teks(hasil, "Lanjutkan pembayaran sekarang? (y/n):")
        self.assert_tidak_ada_teks(hasil, "Keranjang belanja kosong!")
        holds = self._baca_hold()
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]["percobaan"], 1)
        self.assertEqual(holds[0]["status"], "tertahan")
        self.assert_stok("P005", self.stok_awal("P005") - 2)
        self.assertEqual(self.baca_users_hasil()["budi"]["balance"],
                         self.saldo_awal("budi"))
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_FINGER_RP_")

    # -- resume hold --------------------------------------------------------

    def test_resume_n_hold_tetap(self):
        hasil = self.jalankan_app(
            self._prefix_hold()
            + "4\nn\n"
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Lanjutkan pembayaran sekarang? (y/n):")
        holds = self._baca_hold()
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]["percobaan"], 1)
        self.assert_stok("P005", self.stok_awal("P005") - 2)
        self.assertEqual(self.baca_users_hasil()["budi"]["balance"],
                         self.saldo_awal("budi"))
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_FINGER_RP_")


    def test_resume_y_tap_sukses(self):
        produk = self.produk_fixture("P005")
        total = float(produk["price"]) * 2
        saldo_harap = self.saldo_awal("budi") - total
        stok_harap = int(produk["stock"]) - 2
        hasil = self.jalankan_app(
            self._prefix_hold()
            + "4\ny\n1001\n"
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Lanjutkan pembayaran sekarang? (y/n):")
        self.assert_teks(hasil, "Tempelkan sidik jari untuk mengotorisasi pembayaran...")
        self.assert_teks(hasil, "Pembayaran diotorisasi dengan sidik jari.")
        self.assert_teks(hasil, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.")
        self.assert_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_rupiah(hasil, saldo_harap)

        budi = self.baca_users_hasil()["budi"]
        self.assertEqual(budi["balance"], saldo_harap)
        self.assertEqual(len(budi["transactions"]), self.jumlah_trx_awal("budi") + 1)
        trx = budi["transactions"][-1]
        self.assertEqual(trx["total"], total)
        self.assertEqual(trx["items"][0]["id"], "P005")
        self.assertEqual(trx["items"][0]["qty"], 2)
        self.assert_stok("P005", stok_harap)
        self.assertEqual(self._baca_hold(), [], msg="hold harus hilang setelah sukses")

        self.assert_log_ada(username="budi",
                            action="CHECKOUT_FINGER_RP_" + str(int(round(total))))
        self.assert_log_ada(username="budi", action="HOLD_CART")
        self.assert_log_tidak_ada(username="budi", awalan_action="CHECKOUT_SUCCESS_RP_")


    def test_resume_y_tap_gagal_lagi_percobaan_bertambah(self):
        produk = self.produk_fixture("P005")
        hasil = self.jalankan_app(
            self._prefix_hold()
            + "4\ny\n1002\n"
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Lanjutkan pembayaran sekarang? (y/n):")
        self.assert_teks(hasil, "Sidik jari gagal lagi. Belanjaan tetap ditahan (percobaan ke-2).")
        self.assert_tidak_ada_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_tidak_ada_teks(hasil, "TRANSAKSI BERHASIL!")
        holds = self._baca_hold()
        self.assertEqual(len(holds), 1, msg=f"holds={holds!r}")
        self.assertEqual(holds[0]["percobaan"], 2)
        self.assertEqual(holds[0]["status"], "tertahan")
        budi = self.baca_users_hasil()["budi"]
        self.assertEqual(budi["balance"], self.saldo_awal("budi"))
        self.assertEqual(len(budi["transactions"]), self.jumlah_trx_awal("budi"))
        self.assert_stok("P005", int(produk["stock"]) - 2)
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_FINGER_RP_")


    def test_hold_terbaru_dipakai_saat_resume(self):
        produk = self.produk_fixture("P005")
        harga = float(produk["price"])
        stok_awal = int(produk["stock"])
        saldo_awal = self.saldo_awal("budi")
        self._siapkan_hold_persisten(qty=2)
        hasil = self.jalankan_app(
            input_sidik_jari("1001")
            + "2\nkopi\nP005\n1\n"
            + "4\n1002\n"
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        holds = self._baca_hold()
        self.assertEqual(len(holds), 2, msg=f"holds={holds!r}" + self.info(hasil))
        id_lama, id_baru = holds[0]["id"], holds[1]["id"]
        self.assert_stok("P005", stok_awal - 3)

        hasil = self.jalankan_app(
            input_sidik_jari("1001")
            + "4\ny\n1001\n"
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, id_baru)
        total_baru = harga * 1
        budi = self.baca_users_hasil()["budi"]
        self.assertEqual(budi["balance"], saldo_awal - total_baru)
        self.assertEqual(budi["transactions"][-1]["total"], total_baru)
        self.assert_stok("P005", stok_awal - 3)
        sisa = self._baca_hold()
        self.assertEqual([r["id"] for r in sisa], [id_lama],
                         msg="hold lama (belum diresume) harus tetap ada")

    # -- jalur non-sidik-jari sudah aman -----------------------------------

    def test_jalur_pin_salah_tetap_tanpa_hold(self):
        produk = self.produk_fixture("P005")
        saldo_awal = self.saldo_awal("budi")
        stok_awal = int(produk["stock"])
        hasil = self.jalankan_app(
            input_login("budi", "111111")
            + "2\nkopi\nP005\n2\n"
            + "4\n000000\n"
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, "PIN Salah! Transaksi Dibatalkan.")
        self.assert_tidak_ada_teks(hasil, "Sidik jari gagal.")
        self.assert_tidak_ada_teks(hasil, "Ada keranjang tertahan")
        self.assertEqual(self._baca_hold(), [], msg="jalur PIN salah tidak boleh membuat hold")
        self.assert_stok("P005", stok_awal)
        self.assertEqual(self.baca_users_hasil()["budi"]["balance"], saldo_awal)
        self.assert_log_tidak_ada(awalan_action="HOLD_CART")


    def test_risk_shield_batal_tidak_membuat_hold(self):
        produk = self.produk_fixture("P001")
        total = float(produk["price"]) * 2
        saldo = self.saldo_awal("siti")
        limit = float(self.user_fixture("siti")["daily_limit"])
        sisa = saldo - total
        skor = 0
        if sisa < 0.3 * saldo:
            skor += 2
        if total > limit:
            skor += 3
        if "Wants" in [produk["category"]] and sisa < 100000:
            skor += 2
        if skor == 0:
            self.skipTest("data live tidak menghasilkan status risk untuk skenario ini")
        hasil = self.sesi_sidik_jari("1002", "2\nberas\nP001\n2\n4\nn\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Transaksi dibatalkan oleh pengguna/Risk Shield.")
        self.assertEqual(self._baca_hold(), [],
                         msg="batal di Risk Shield tidak boleh membuat hold")
        self.assert_stok("P001", int(produk["stock"]))
        self.assert_log_tidak_ada(awalan_action="HOLD_CART")


    def test_saldo_kurang_tidak_membuat_hold(self):
        saldo = self.saldo_awal("siti")
        pilihan = None
        for pid, produk in self.fixture_products().items():
            stok = int(produk["stock"])
            harga = float(produk["price"])
            if stok <= 0 or harga <= 0:
                continue
            qty = int(saldo // harga) + 1
            if 0 < qty <= stok:
                pilihan = (pid, produk, qty)
                break
        if pilihan is None:
            self.skipTest("tidak ada produk+qty melebihi saldo pada data live")
        pid, produk, qty = pilihan
        kata = produk["name"].split()[0].lower()
        hasil = self.sesi_sidik_jari("1002",
                                     f"2\n{kata}\n{pid}\n{qty}\n4\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Checkout Gagal: Saldo e-wallet tidak mencukupi!")
        self.assertEqual(self._baca_hold(), [],
                         msg="saldo kurang tidak boleh membuat hold")
        self.assert_stok(pid, int(produk["stock"]))
        self.assert_log_tidak_ada(awalan_action="HOLD_CART")


# ---------------------------------------------------------------------------
# 3. Admin kelola keranjang tertahan (menu admin 9 opsi)
# ---------------------------------------------------------------------------

class TestAdminHoldKeranjang(DasarTest):
    def _siapkan_hold_persisten(self):
        hasil = self.jalankan_app(
            input_sidik_jari("1001")
            + "2\nkopi\nP005\n2\n"
            + "4\n1002\n"
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        holds = self.baca_keranjang_hasil()
        self.assertEqual(len(holds), 1, msg=f"holds={holds!r}" + self.info(hasil))
        return holds[0]

    def test_menu_admin_sembilan_opsi(self):
        hasil = self.jalankan_app(input_login("admin", "123456") + "9\n" + KELUAR)
        self.cek_exit(hasil)
        for teks in (
            "1. Tambah Produk Baru (Create)",
            "2. Tampilkan Semua Produk (Read)",
            "3. Update Harga / Stok Produk (Update)",
            "4. Hapus Produk dari Katalog (Delete)",
            "5. Lihat Audit System Logs",
            "6. Buka Blokir Akun Pelanggan",
            "7. Kelola Sidik Jari (X100C)",
            "8. Kelola Keranjang Tertahan",
            "9. Logout Admin",
        ):
            self.assert_teks(hasil, teks)
        self.assert_teks(hasil, "Pilih menu (1-9):")
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_teks(hasil, "Terima kasih telah menggunakan PayGuard.")


    def test_admin_list_dan_cancel_hold(self):
        produk = self.produk_fixture("P005")
        total = float(produk["price"]) * 2
        stok_awal = int(produk["stock"])
        saldo_awal = self.saldo_awal("budi")
        record = self._siapkan_hold_persisten()
        jumlah_trx = self.jumlah_trx_awal("budi")
        hasil = self.sesi_admin(
            "8\n"
            "1\n"
            "2\n" + record["id"] + "\nn\n"
            "2\n" + record["id"] + "\ny\n"
            "3\n"
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, "=== KELOLA KERANJANG TERTAHAN ===")
        for teks in ("1. Lihat keranjang tertahan",
                     "2. Batalkan & kembalikan stok",
                     "3. Kembali",
                     "Pilih menu (1-3):"):
            self.assert_teks(hasil, teks)
        baris = (record["id"] + " | budi | Total " + self.rupiah_teks(total)
                 + " | percobaan 1 | " + produk["name"] + " x2")
        self.assert_teks(hasil, baris)
        self.assert_teks(hasil, "Pembatalan dibatalkan.")
        self.assert_teks(hasil, "Keranjang " + record["id"]
                         + " dibatalkan, stok dikembalikan.")
        self.assertEqual(self.baca_keranjang_hasil(), [],
                         msg="hold harus hilang setelah admin cancel")
        self.assert_stok("P005", stok_awal)
        budi = self.baca_users_hasil()["budi"]
        self.assertEqual(budi["balance"], saldo_awal)
        self.assertEqual(len(budi["transactions"]), jumlah_trx)
        log_cancel = self.assert_log_ada(username="admin", action="HOLD_CANCEL")
        self.assertEqual(log_cancel.get("detail"), record["id"])

    def test_admin_list_kosong(self):
        hasil = self.sesi_admin("8\n1\n3\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "=== KELOLA KERANJANG TERTAHAN ===")
        self.assert_teks(hasil, "Tidak ada keranjang tertahan.")

    def test_admin_cancel_id_tidak_ditemukan(self):
        hasil = self.sesi_admin("8\n2\nHOLD-99999999999999\n3\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "ID keranjang tertahan tidak ditemukan.")
        self.assertEqual(self.baca_keranjang_hasil(), [])

    def test_admin_submenu_pilihan_invalid(self):
        hasil = self.sesi_admin("8\n9\n3\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Pilihan tidak valid!")
        self.assertGreaterEqual(
            self.hitung_teks(hasil, "=== KELOLA KERANJANG TERTAHAN ==="), 2,
            msg=self.info(hasil),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
