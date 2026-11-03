"""Suite test otomatis PayGuard CLI (unittest, 100% stdlib, tanpa pip).

Kontrak acuan: ``payguard/SPESIFIKASI_PAYGUARD.md`` (v1).

Pola pengujian (mengikuti gaya test ``cashless/tests/test_login_admin.py``):

- Setiap test integrasi membuat folder kerja baru di ``payguard/tests/_tmp/kasus_<uuid>``
  dengan ``Path.mkdir()`` (BUKAN ``tempfile.mkdtemp()`` karena di sandbox Windows
  folder mode 0o700 hasil mkdtemp tidak bisa ditulisi child process python).
- Ke folder kerja tersebut disalin SEMUA ``payguard/*.py`` + ``data/`` dari
  ``tests/fixtures/`` (salinan byte-identik ``payguard/data/*.json``).
- Aplikasi dijalankan ``python <folder kerja>/main.py`` dengan ``cwd`` = folder kerja,
  jadi ``data_manager.DATA_DIR`` menunjuk ke salinan data, BUKAN data asli.
- Output dibaca ``encoding="utf-8", errors="replace"``; assertion memeriksa stdout
  dan isi JSON hasil (``json.load``).
- Folder kerja dihapus di ``tearDown``; ``tests/_tmp`` dibersihkan di akhir modul.
- Data asli ``payguard/data/*.json`` di-hash SHA256 saat modul diimpor dan
  diverifikasi ulang oleh kelas ``TestZZIntegritasAkhir`` (test terakhir).

Unit test read-only (``auth``, ``risk_assistant``, ``data_manager``) mengimpor modul
langsung dari folder ``payguard`` lewat ``sys.path.insert`` dan hanya memanggil fungsi
baca/hitung (tidak ada fungsi penulis yang menyentuh data asli).
"""

import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# jangan kotori folder project dengan __pycache__ saat unit test mengimpor modul app
sys.dont_write_bytecode = True

# ---------------------------------------------------------------------------
# Lokasi & konstanta
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parents[1]      # .../payguard
TESTS_DIR = Path(__file__).resolve().parent            # .../payguard/tests
FIXTURES_DIR = TESTS_DIR / "fixtures"
BASE_TMP = TESTS_DIR / "_tmp"                          # folder kerja sementara
DATA_DIR = PROJECT_DIR / "data"

DATA_FILES = ("users.json", "products.json", "logs.json", "keranjang.json", "perangkat.json")

# users/products/logs = DATA -> wajib byte-identik fixtures <-> data asli.
# perangkat.json = KONFIGURASI DEPLOYMENT (data asli bisa mode "soap" untuk perangkat
# X100C nyata; fixtures selalu mode "simulasi" agar test hermetis) -> dikecualikan
# dari uji byte-identik, hash-nya tetap dipantau agar tidak diubah QA.
FIXTURE_IDENTIK_FILES = ("users.json", "products.json", "logs.json", "keranjang.json")
MODE_PERANGKAT_TEST = "simulasi"

MAIN_SCRIPT = "main.py"
APP_TIMEOUT = 60

PINS = {
    "admin": "123456",
    "budi": "111111",
    "siti": "222222",
    "andi": "333333",
}

# Pesan-pesan warning Risk Shield sesuai kontrak §4.3.
WARNING_SALDO = "Transaksi ini menghabiskan lebih dari 70% sisa saldomu."
WARNING_LIMIT = "Pembelian ini akan melampaui limit anggaran harianmu!"
WARNING_TERSIER = "Kamu membeli barang tersier saat saldo mendekati batas minimum."

# Urutan katalog untuk test pengurutan (dihitung dari fixtures produk seed).
URUTAN_HARGA_TERMURAH = [
    "Kopi Sachet", "Sabun Mandi", "Buku Tulis", "Minyak Goreng 1L", "Boba Premium",
    "Cokelat Premium", "Telur Ayam 1kg", "Beras 5kg", "Headset Gaming",
]
URUTAN_HARGA_TERMAHAL = list(reversed(URUTAN_HARGA_TERMURAH))
URUTAN_NAMA_AZ = [
    "Beras 5kg", "Boba Premium", "Buku Tulis", "Cokelat Premium", "Headset Gaming",
    "Kopi Sachet", "Minyak Goreng 1L", "Sabun Mandi", "Telur Ayam 1kg",
]
URUTAN_STOK_TERBANYAK = [
    "Kopi Sachet", "Sabun Mandi", "Buku Tulis", "Minyak Goreng 1L", "Telur Ayam 1kg",
    "Beras 5kg", "Cokelat Premium", "Headset Gaming", "Boba Premium",
]

# ---------------------------------------------------------------------------
# Snapshot hash data asli SEBELUM suite (untuk test integritas di akhir suite)
# ---------------------------------------------------------------------------

_HASH_DATA_ASLI = {}
for _nama_data in DATA_FILES:
    _jalur_data = DATA_DIR / _nama_data
    if _jalur_data.is_file():
        _HASH_DATA_ASLI[_nama_data] = hashlib.sha256(_jalur_data.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Helper murni
# ---------------------------------------------------------------------------

def normalisasi(teks):
    """Huruf kecil + whitespace dirapatkan supaya perbandingan tahan format."""
    return " ".join(str(teks).lower().split())


def pola_rupiah(jumlah):
    """Regex yang menerima Rp20.000, Rp 20.000, Rp20000, Rp-198.000, dst."""
    jumlah = int(jumlah)
    varian = {str(jumlah), f"{jumlah:,}".replace(",", ".")}
    if jumlah < 0:
        varian.add("-" + f"{abs(jumlah):,}".replace(",", "."))
        varian.add("-" + str(abs(jumlah)))
    varian = sorted(varian, key=len, reverse=True)
    return re.compile(
        r"rp\s?(?:" + "|".join(re.escape(v) for v in varian) + r")(?!\d|\.\d)",
        re.IGNORECASE,
    )


def varian_angka(jumlah):
    """Semua varian penulisan angka (polos & bertitik ribuan), terpanjang dulu."""
    jumlah = int(jumlah)
    varian = {str(jumlah), f"{jumlah:,}".replace(",", ".")}
    return sorted(varian, key=len, reverse=True)


def baca_json_file(jalur):
    return json.loads(Path(jalur).read_text(encoding="utf-8"))


def muat_fixture(nama):
    """Muat isi fixture JSON (data awal)."""
    return baca_json_file(FIXTURES_DIR / nama)


def input_login(username, pin):
    return f"1\n{username}\n{pin}\n"


def input_register(username, pin):
    return f"2\n{username}\n{pin}\n"


KELUAR = "4\n"
LOGOUT_ADMIN = "9\n"
LOGOUT_CUSTOMER = "6\n"


# ---------------------------------------------------------------------------
# Base class: folder kerja + runner subprocess
# ---------------------------------------------------------------------------

def hapus_pohon(jalur, percobaan=12, jeda=0.1):
    """Hapus folder dengan retry: di Windows handle child process kadang belum
    dilepas saat tearDown sehingga ``rmtree(ignore_errors=True)`` bisa gagal."""
    jalur = Path(jalur)
    for _ in range(percobaan):
        shutil.rmtree(jalur, ignore_errors=True)
        if not jalur.exists():
            return True
        time.sleep(jeda)
    return not jalur.exists()


class DasarTest(unittest.TestCase):
    """Menyediakan folder kerja terisolasi dan helper menjalankan aplikasi."""

    maxDiff = None

    def setUp(self):
        BASE_TMP.mkdir(parents=True, exist_ok=True)
        self.workdir = BASE_TMP / ("kasus_" + uuid.uuid4().hex)
        self.workdir.mkdir()
        self.siapkan_app(self.workdir)

    def tearDown(self):
        hapus_pohon(self.workdir)

    # -- penyiapan folder kerja --------------------------------------------
    def siapkan_app(self, workdir):
        """Salin semua payguard/*.py + data/ (dari fixtures) ke folder kerja."""
        folder_data = workdir / "data"
        folder_data.mkdir()
        for nama in DATA_FILES:
            shutil.copyfile(FIXTURES_DIR / nama, folder_data / nama)
        for berkas in sorted(PROJECT_DIR.glob("*.py")):
            shutil.copyfile(berkas, workdir / berkas.name)
        # Pengaman hermetis: config perangkat di folder kerja WAJIB mode simulasi
        # agar test tidak pernah menghubungi perangkat X100C asli (192.168.1.201).
        config_perangkat = baca_json_file(folder_data / "perangkat.json")
        if config_perangkat.get("mode") != MODE_PERANGKAT_TEST:
            self.fail(
                "fixtures/perangkat.json harus mode 'simulasi' agar test hermetis; "
                f"dapat mode {config_perangkat.get('mode')!r}. "
                "Jangan salin config deployment (soap) ke fixtures."
            )

    def pulihkan_data(self):
        """Kembalikan data folder kerja ke kondisi fixture (untuk subTest)."""
        for nama in DATA_FILES:
            shutil.copyfile(FIXTURES_DIR / nama, self.workdir / "data" / nama)

    # -- runner -------------------------------------------------------------
    def _env_anak(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # jangan kotori folder project
        return env

    def jalankan_app(self, teks_input):
        """Jalankan main.py salinan dengan cwd = folder kerja."""
        perintah = [sys.executable, str(self.workdir / MAIN_SCRIPT)]
        for percobaan in range(3):
            try:
                hasil = subprocess.run(
                    perintah,
                    cwd=str(self.workdir),
                    input=teks_input,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=APP_TIMEOUT,
                    env=self._env_anak(),
                )
            except subprocess.TimeoutExpired:
                self.fail(
                    f"Aplikasi tidak selesai dalam {APP_TIMEOUT} detik.\n"
                    f"input={teks_input!r}"
                )
        # Windows: os.replace() pada data salinan kadang PermissionError sesaat karena
        # antivirus/indexer memegang handle file; ulangi run (bukan bug app).
            if (hasil.returncode == 1
                    and "PermissionError" in (hasil.stderr or "")
                    and ("Access is denied" in (hasil.stderr or "")
                         or "WinError 5" in (hasil.stderr or ""))):
                if percobaan == 2:
                    return hasil
                time.sleep(0.3 * (percobaan + 1))
                continue
            return hasil



    # -- helper pesan -------------------------------------------------------
    def info(self, hasil):
        return (
            f"\n--- input/stdout/stderr ---"
            f"\n--- exit code ---\n{hasil.returncode}"
            f"\n--- stdout ---\n{hasil.stdout}"
            f"\n--- stderr ---\n{hasil.stderr}"
        )

    def cek_exit(self, hasil, kode=0):
        self.assertEqual(hasil.returncode, kode, msg=self.info(hasil))

    def assert_teks(self, hasil, teks, msg=""):
        self.assertIn(
            normalisasi(teks), normalisasi(hasil.stdout),
            msg=(msg + self.info(hasil)),
        )

    def assert_tidak_ada_teks(self, hasil, teks, msg=""):
        self.assertNotIn(
            normalisasi(teks), normalisasi(hasil.stdout),
            msg=(msg + self.info(hasil)),
        )

    def assert_rupiah(self, hasil, jumlah, msg=""):
        self.assertRegex(
            normalisasi(hasil.stdout), pola_rupiah(jumlah),
            msg=(f"tidak menemukan nominal rupiah {jumlah}" + msg + self.info(hasil)),
        )

    def hitung_teks(self, hasil, teks):
        return normalisasi(hasil.stdout).count(normalisasi(teks))

    def assert_baris_produk(self, hasil, pid, nama, harga, stok, kategori, msg="",
                            label_stok=True):
        """Assert satu baris format katalog: <id> | <nama> | <Rp> | stok <n> | <kategori>.

        ``label_stok=False`` menoleransi baris admin Read yang mengikuti header
        ``ID | Nama | Harga | Stok | Kategori`` (nilai stok polos tanpa kata "stok").
        """
        bagian_stok = (r"stok\s+" if label_stok else r"(?:stok\s+)?") + str(int(stok))
        pola = re.compile(
            re.escape(pid.lower())
            + r"\s*\|\s*" + re.escape(nama.lower())
            + r"\s*\|\s*rp\s?(?:" + "|".join(re.escape(v) for v in varian_angka(harga)) + r")"
            + r"\s*\|\s*" + bagian_stok
            + r"\s*\|\s*" + re.escape(kategori.lower()),
        )
        self.assertRegex(
            normalisasi(hasil.stdout), pola,
            msg=(f"baris produk {pid} tidak sesuai format katalog" + msg + self.info(hasil)),
        )

    def assert_baris_item(self, hasil, nama, qty, total, msg=""):
        """Assert baris item keranjang/resi: <nama> x<jumlah> = <Rp>."""
        pola = re.compile(
            re.escape(nama.lower())
            + r"\s+x" + str(int(qty)) + r"\s*=\s*rp\s?(?:"
            + "|".join(re.escape(v) for v in varian_angka(total)) + r")(?!\d|\.\d)",
        )
        self.assertRegex(
            normalisasi(hasil.stdout), pola,
            msg=(f"baris item '{nama} x{qty}' tidak ditemukan" + msg + self.info(hasil)),
        )

    def assert_urutan_produk(self, hasil, urutan, msg=""):
        """Assert urutan kemunculan nama produk di stdout sesuai daftar."""
        teks = normalisasi(hasil.stdout)
        posisi_sebelum = -1
        posisi_semua = []
        for nama in urutan:
            pos = teks.find(nama.lower())
            self.assertGreaterEqual(
                pos, 0,
                msg=f"produk '{nama}' tidak muncul di output" + msg + self.info(hasil),
            )
            posisi_semua.append((nama, pos))
            self.assertGreater(
                pos, posisi_sebelum,
                msg=f"urutan produk salah. posisi={posisi_semua}" + msg + self.info(hasil),
            )
            posisi_sebelum = pos

    # -- helper isi data ----------------------------------------------------
    def baca_users_hasil(self):
        return baca_json_file(self.workdir / "data" / "users.json")

    def baca_products_hasil(self):
        return baca_json_file(self.workdir / "data" / "products.json")

    def baca_logs_hasil(self):
        return baca_json_file(self.workdir / "data" / "logs.json")

    def fixture_users(self):
        return muat_fixture("users.json")

    def fixture_products(self):
        return muat_fixture("products.json")

    def fixture_logs(self):
        return muat_fixture("logs.json")

    def assert_users_tetap(self, msg=""):
        hasil = self.baca_users_hasil()
        harap = self.fixture_users()
        # Seed ``budi`` punya failed_attempts=1; login PIN sukses me-reset field ini
        # ke 0 (kontrak §4.2). Nilainya dinormalkan di sini; perilaku reset diuji
        # khusus di TestAuthAlur.
        if "budi" in hasil and "budi" in harap:
            harap["budi"]["failed_attempts"] = hasil["budi"]["failed_attempts"]
        self.assertEqual(
            hasil, harap,
            msg=("users.json berubah padahal seharusnya tidak berubah." + msg
                 + f"\nhasil={hasil!r}\nfixture={harap!r}"),
        )

    def assert_products_tetap(self, msg=""):
        hasil = self.baca_products_hasil()
        harap = self.fixture_products()
        self.assertEqual(
            hasil, harap,
            msg=("products.json berubah padahal seharusnya tidak berubah." + msg
                 + f"\nhasil={hasil!r}\nfixture={harap!r}"),
        )

    def assert_data_tetap(self, msg=""):
        self.assert_users_tetap(msg)
        self.assert_products_tetap(msg)

    def assert_saldo(self, username, nilai):
        users = self.baca_users_hasil()
        self.assertIn(username, users, msg=f"user '{username}' tidak ada di users.json")
        self.assertEqual(
            users[username]["balance"], float(nilai),
            msg=f"saldo {username} != {nilai}; users={users[username]!r}",
        )

    def assert_stok(self, pid, nilai):
        products = self.baca_products_hasil()
        self.assertIn(pid, products, msg=f"produk '{pid}' tidak ada di products.json")
        self.assertEqual(
            products[pid]["stock"], int(nilai),
            msg=f"stok {pid} != {nilai}; products={products[pid]!r}",
        )

    # -- helper log baru (append-only) -------------------------------------
    def log_baru(self):
        logs = self.baca_logs_hasil()
        awal = self.fixture_logs()
        return logs[len(awal):]

    def cari_log(self, username=None, action=None, awalan_action=None):
        hasil = []
        for catatan in self.log_baru():
            if username is not None and catatan.get("username") != username:
                continue
            if action is not None and catatan.get("action") != action:
                continue
            if awalan_action is not None and not str(catatan.get("action", "")).startswith(awalan_action):
                continue
            hasil.append(catatan)
        return hasil

    def assert_log_ada(self, username=None, action=None, awalan_action=None, msg=""):
        daftar = self.cari_log(username=username, action=action, awalan_action=awalan_action)
        self.assertTrue(
            daftar,
            msg=(f"tidak ada log baru (username={username}, action={action}, "
                 f"awalan={awalan_action}). log_baru={self.log_baru()!r}" + msg),
        )
        return daftar[0]

    def assert_log_tidak_ada(self, username=None, action=None, awalan_action=None, msg=""):
        daftar = self.cari_log(username=username, action=action, awalan_action=awalan_action)
        self.assertEqual(
            daftar, [],
            msg=(f"ada log baru yang tidak seharusnya (username={username}, "
                 f"action={action}, awalan={awalan_action}): {daftar!r}" + msg),
        )

    def assert_log_lama_utuh(self):
        """Seed log harus tetap utuh di posisi awal (append-only)."""
        awal = self.fixture_logs()
        logs = self.baca_logs_hasil()
        self.assertEqual(len(logs) >= len(awal), True, msg=f"logs.json memendek: {logs!r}")
        self.assertEqual(logs[: len(awal)], awal, msg="baris log lama ikut berubah/hilang.")

    # -- sesi siap pakai ----------------------------------------------------
    def sesi_admin(self, isi_menu):
        """Login admin sukses, jalankan isi_menu, logout admin, lalu keluar."""
        return self.jalankan_app(
            input_login("admin", "123456") + isi_menu + LOGOUT_ADMIN + KELUAR
        )

    def sesi_customer(self, username, pin, isi_menu):
        """Login customer, jalankan isi_menu, logout, lalu keluar."""
        return self.jalankan_app(
            input_login(username, pin) + isi_menu + LOGOUT_CUSTOMER + KELUAR
        )

    # -- assert menu --------------------------------------------------------
    def assert_menu_admin(self, hasil):
        self.assert_teks(hasil, "=== MENU ADMIN / MERCHANT ===")
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

    def assert_menu_customer(self, hasil):
        self.assert_teks(hasil, "=== MENU PELANGGAN ===")
        for teks in (
            "1. Lihat Saldo & Top Up",
            "2. Cari & Belanja Produk",
            "3. Pengurutan Katalog",
            "4. Lihat Keranjang & Checkout",
            "5. Riwayat Transaksi & Track Record",
            "6. Logout",
        ):
            self.assert_teks(hasil, teks)
        self.assert_teks(hasil, "Pilih menu (1-6):")

    # -- helper data-driven: nilai awal dibaca dari fixtures (data live) ------
    def produk_fixture(self, pid):
        return self.fixture_products()[pid]

    def user_fixture(self, username):
        return self.fixture_users()[username]

    def harga_awal(self, pid):
        return float(self.produk_fixture(pid)["price"])

    def stok_awal(self, pid):
        return int(self.produk_fixture(pid)["stock"])

    def saldo_awal(self, username):
        return float(self.user_fixture(username)["balance"])

    def skor_risiko_fixture(self, username, total, kategori):
        """Hitung skor yang diharapkan dari data fixtures (bukan hardcode seed)."""
        user = self.user_fixture(username)
        hari_ini = datetime.now().strftime("%Y-%m-%d")
        today_spent = sum(
            float(trx.get("total", 0))
            for trx in user.get("transactions", [])
            if str(trx.get("date", ""))[:10] == hari_ini
        )
        saldo = float(user["balance"])
        limit = float(user["daily_limit"])
        daftar_kategori = kategori if isinstance(kategori, (list, tuple)) else [kategori]
        sisa = saldo - float(total)
        skor = 0
        if sisa < 0.3 * saldo:
            skor += 2
        if today_spent + float(total) > limit:
            skor += 3
        if "Wants" in daftar_kategori and sisa < 100000:
            skor += 2
        return skor

    @staticmethod
    def konfirmasi_untuk_skor(skor):
        if skor > 3:
            return "SAYA YAKIN"
        if skor > 0:
            return "y"
        return ""

    def urutan_produk_fixture(self, kunci, reverse=False):
        produk = list(self.fixture_products().values())
        return [item["name"] for item in sorted(produk, key=kunci, reverse=reverse)]


# ---------------------------------------------------------------------------
# Menu utama & splash (kontrak §4.1)
# ---------------------------------------------------------------------------

class TestMenuUtama(DasarTest):
    def test_splash_dan_keluar_exit_0(self):
        hasil = self.jalankan_app(KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "PAYGUARD CLI - E-WALLET & RISK SHIELD")
        self.assert_teks(hasil, "=== MENU UTAMA ===")
        self.assert_teks(hasil, "1. Login")
        self.assert_teks(hasil, "2. Register")
        self.assert_teks(hasil, "3. Login Sidik Jari (X100C)")
        self.assert_teks(hasil, "4. Keluar")
        self.assert_teks(hasil, "Pilih menu (1-4):")
        self.assert_teks(hasil, "Terima kasih telah menggunakan PayGuard.")
        # tidak boleh masuk menu apa pun
        self.assert_tidak_ada_teks(hasil, "=== MENU ADMIN / MERCHANT ===")
        self.assert_tidak_ada_teks(hasil, "=== MENU PELANGGAN ===")
        # aplikasi hanya membaca data: data asli di folder kerja tetap sama
        self.assert_data_tetap()

    def test_pilihan_menu_utama_invalid(self):
        hasil = self.jalankan_app("9\n0\nabc\n" + KELUAR)
        self.cek_exit(hasil)
        self.assertGreaterEqual(
            self.hitung_teks(hasil, "Pilihan tidak valid!"), 3,
            msg="pesan 'Pilihan tidak valid!' tidak muncul untuk tiap pilihan salah"
                + self.info(hasil),
        )
        self.assertGreaterEqual(
            self.hitung_teks(hasil, "=== MENU UTAMA ==="), 4,
            msg="menu utama tidak diulang setelah pilihan invalid" + self.info(hasil),
        )
        self.assert_teks(hasil, "Terima kasih telah menggunakan PayGuard.")


# ---------------------------------------------------------------------------
# Autentikasi & register (kontrak §4.1, §4.2, §5)
# ---------------------------------------------------------------------------

class TestAuthAlur(DasarTest):
    def test_login_admin_sukses(self):
        hasil = self.jalankan_app(input_login("admin", "123456") + LOGOUT_ADMIN + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "--- LOGIN ---")
        self.assert_teks(hasil, "Username:")
        self.assert_teks(hasil, "PIN:")
        self.assert_teks(hasil, "Login berhasil! Selamat datang, admin.")
        self.assert_menu_admin(hasil)
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_teks(hasil, "Terima kasih telah menggunakan PayGuard.")
        self.assert_tidak_ada_teks(hasil, "=== MENU PELANGGAN ===")

        # users.json tidak berubah secara semantik (failed_attempts tetap 0)
        self.assert_users_tetap()
        # log append-only: LOGIN_SUCCESS lalu LOGOUT
        self.assert_log_lama_utuh()
        self.assert_log_ada(username="admin", action="LOGIN_SUCCESS")
        self.assert_log_ada(username="admin", action="LOGOUT")

    def test_login_customer_sukses(self):
        hasil = self.jalankan_app(input_login("budi", "111111") + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Login berhasil! Selamat datang, budi.")
        self.assert_menu_customer(hasil)
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_tidak_ada_teks(hasil, "=== MENU ADMIN / MERCHANT ===")
        self.assert_users_tetap()
        self.assert_log_ada(username="budi", action="LOGIN_SUCCESS")
        self.assert_log_ada(username="budi", action="LOGOUT")

    def test_login_admin_pin_salah(self):
        hasil = self.jalankan_app(input_login("admin", "999999") + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "PIN salah! Percobaan: 1/3")
        self.assert_tidak_ada_teks(hasil, "Login berhasil!")
        self.assert_tidak_ada_teks(hasil, "=== MENU ADMIN / MERCHANT ===")
        users = self.baca_users_hasil()
        self.assertEqual(users["admin"]["failed_attempts"], 1)
        self.assertFalse(users["admin"]["is_locked"])
        self.assertEqual(users["admin"]["balance"], 0.0)
        self.assert_log_tidak_ada(username="admin", action="LOGIN_SUCCESS")

    def test_login_customer_pin_salah(self):
        hasil = self.jalankan_app(input_login("siti", "000000") + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "PIN salah! Percobaan: 1/3")
        self.assert_tidak_ada_teks(hasil, "Login berhasil!")
        self.assert_tidak_ada_teks(hasil, "=== MENU PELANGGAN ===")
        users = self.baca_users_hasil()
        self.assertEqual(users["siti"]["failed_attempts"], 1)
        self.assertFalse(users["siti"]["is_locked"])
        self.assertEqual(users["siti"]["balance"], 150000.0)
        self.assert_log_tidak_ada(username="siti", action="LOGIN_SUCCESS")

    def test_login_username_tidak_ditemukan(self):
        hasil = self.jalankan_app(input_login("hantu", "123456") + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Username tidak ditemukan.")
        self.assert_tidak_ada_teks(hasil, "Login berhasil!")
        self.assert_tidak_ada_teks(hasil, "=== MENU ADMIN / MERCHANT ===")
        self.assert_users_tetap()

    def test_login_sukses_mereset_failed_attempts(self):
        # 2x PIN salah lalu PIN benar: failed_attempts harus kembali 0 dan tidak terkunci
        hasil = self.jalankan_app(
            input_login("siti", "000000")
            + input_login("siti", "000000")
            + input_login("siti", "222222")
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, "PIN salah! Percobaan: 1/3")
        self.assert_teks(hasil, "PIN salah! Percobaan: 2/3")
        self.assert_teks(hasil, "Login berhasil! Selamat datang, siti.")
        siti = self.baca_users_hasil()["siti"]
        self.assertEqual(siti["failed_attempts"], 0)
        self.assertFalse(siti["is_locked"])
        self.assert_log_ada(username="siti", action="LOGIN_SUCCESS")

    def test_lockout_setelah_tiga_kali_pin_salah(self):
        siti_salah = input_login("siti", "000000") * 3
        hasil = self.jalankan_app(siti_salah + input_login("siti", "222222") + KELUAR)
        self.cek_exit(hasil)
        for percobaan in (1, 2, 3):
            self.assert_teks(hasil, f"PIN salah! Percobaan: {percobaan}/3")
        self.assert_teks(hasil, "AKUN DIKUNCI DEMI KEAMANAN.")
        # percobaan ke-4 dengan PIN benar harus ditolak karena akun terkunci
        self.assert_teks(
            hasil,
            "Akun terblokir karena percobaan PIN salah berulang kali. Hubungi Admin.",
        )
        self.assert_tidak_ada_teks(hasil, "Login berhasil!")
        self.assert_tidak_ada_teks(hasil, "=== MENU PELANGGAN ===")

        users = self.baca_users_hasil()
        self.assertTrue(users["siti"]["is_locked"])
        self.assertEqual(users["siti"]["failed_attempts"], 3)
        self.assertEqual(users["siti"]["balance"], 150000.0)
        self.assert_log_ada(
            username="siti", awalan_action="ACCOUNT_LOCKED_BRUTEFORCE"
        )
        self.assert_log_tidak_ada(username="siti", action="LOGIN_SUCCESS")

    def test_register_sukses_dan_langsung_bisa_login(self):
        hasil = self.jalankan_app(
            input_register("citra", "4321") + input_login("citra", "4321")
            + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, "--- REGISTER ---")
        self.assert_teks(hasil, "Username baru:")
        self.assert_teks(hasil, "PIN baru:")
        self.assert_teks(hasil, "Registrasi Berhasil!")
        self.assert_teks(hasil, "Login berhasil! Selamat datang, citra.")
        self.assert_menu_customer(hasil)

        users = self.baca_users_hasil()
        self.assertEqual(len(users), len(self.fixture_users()) + 1)
        self.assertIn("citra", users)
        citra = users["citra"]
        self.assertEqual(citra["username"], "citra")
        self.assertEqual(citra["balance"], 0.0)
        self.assertEqual(citra["daily_limit"], 500000.0)
        self.assertEqual(citra["role"], "customer")
        self.assertFalse(citra["is_locked"])
        self.assertEqual(citra["failed_attempts"], 0)
        self.assertEqual(citra["finger_id"], "")
        self.assertEqual(citra["transactions"], [])
        self.assertRegex(citra["salt"], r"^[0-9a-fA-F]{16}$")
        pin_hash_harap = hashlib.sha256(("4321" + citra["salt"]).encode("utf-8")).hexdigest()
        self.assertEqual(citra["pin_hash"], pin_hash_harap)
        # user lama tidak berubah
        for username in self.fixture_users():
            self.assertEqual(users[username], self.fixture_users()[username])

        log_register = self.assert_log_ada(username="citra", action="REGISTER")
        self.assertIn("akun baru", normalisasi(log_register.get("detail", "")))
        self.assert_log_ada(username="citra", action="LOGIN_SUCCESS")

    def test_register_username_duplikat(self):
        hasil = self.jalankan_app(input_register("budi", "5678") + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Error: Username sudah terdaftar!")
        self.assert_tidak_ada_teks(hasil, "Registrasi Berhasil!")
        self.assert_users_tetap()
        self.assert_log_tidak_ada(action="REGISTER")

    def test_register_pin_tidak_valid(self):
        for pin in ("abc", "123", "12a4", ""):
            with self.subTest(pin=pin):
                self.pulihkan_data()
                hasil = self.jalankan_app(input_register("userbaru", pin) + KELUAR)
                self.cek_exit(hasil)
                self.assert_teks(hasil, "PIN harus berupa angka minimal 4 digit!")
                self.assert_tidak_ada_teks(hasil, "Registrasi Berhasil!")
                self.assert_users_tetap()
                self.assert_log_tidak_ada(action="REGISTER")

    def test_register_username_kosong(self):
        for username in ("", " "):
            with self.subTest(username=username):
                self.pulihkan_data()
                hasil = self.jalankan_app(input_register(username, "1234") + KELUAR)
                self.cek_exit(hasil)
                self.assert_teks(hasil, "Username tidak boleh kosong!")
                self.assert_tidak_ada_teks(hasil, "Registrasi Berhasil!")
                self.assert_users_tetap()
                self.assert_log_tidak_ada(action="REGISTER")


# ---------------------------------------------------------------------------
# Admin: CRUD produk (kontrak §4.5)
# ---------------------------------------------------------------------------

class TestAdminCrud(DasarTest):
    def test_read_semua_produk(self):
        hasil = self.sesi_admin("2\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "ID | Nama | Harga | Stok | Kategori")
        produk = self.fixture_products()
        for pid, item in produk.items():
            self.assert_baris_produk(
                hasil, pid, item["name"], item["price"], item["stock"], item["category"],
                label_stok=False,  # format baris Read tidak dirinci eksplisit di kontrak
            )
        self.assert_data_tetap()

    def test_read_katalog_kosong(self):
        # katalog dikosongkan HANYA di folder kerja sementara
        (self.workdir / "data" / "products.json").write_text("{}", encoding="utf-8")
        hasil = self.sesi_admin("2\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "ID | Nama | Harga | Stok | Kategori")
        self.assert_teks(hasil, "Katalog kosong.")

    def test_create_produk_katalog_kosong_dapat_id_p001(self):
        (self.workdir / "data" / "products.json").write_text("{}", encoding="utf-8")
        hasil = self.sesi_admin("1\nProduk Pertama\n1000\n1\nNeeds\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "berhasil ditambahkan")
        products = self.baca_products_hasil()
        self.assertEqual(len(products), 1)
        self.assertIn("P001", products)
        self.assertEqual(products["P001"]["name"], "Produk Pertama")

    def test_create_produk_sukses(self):
        hasil = self.sesi_admin("1\nKopi Susu\n15000\n10\nWants\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Masukan nama produk:")
        self.assert_teks(hasil, "Masukan harga:")
        self.assert_teks(hasil, "Masukan stok:")
        self.assert_teks(hasil, "Masukan kategori (Needs/Wants):")
        self.assert_teks(hasil, "P010")
        self.assert_teks(hasil, "Kopi Susu")
        self.assert_teks(hasil, "berhasil ditambahkan")

        products = self.baca_products_hasil()
        self.assertEqual(len(products), len(self.fixture_products()) + 1)
        self.assertIn("P010", products)
        produk_baru = products["P010"]
        self.assertEqual(produk_baru["id"], "P010")
        self.assertEqual(produk_baru["name"], "Kopi Susu")
        self.assertEqual(produk_baru["price"], 15000.0)
        self.assertEqual(produk_baru["stock"], 10)
        self.assertEqual(produk_baru["category"], "Wants")
        # produk lama tetap sama
        for pid, item in self.fixture_products().items():
            self.assertEqual(products[pid], item, msg=f"produk {pid} ikut berubah")

        log_create = self.assert_log_ada(username="admin", action="CREATE_PRODUCT")
        self.assertEqual(log_create.get("detail"), "P010")

    def test_create_produk_validasi(self):
        kasus = (
            # (nama, harga, stok, kategori, pesan, label)
            ("", "5000", "5", "Needs", "Nama produk tidak boleh kosong!", "nama kosong"),
            ("Barang Uji", "abc", "5", "Needs", "Harga harus berupa angka lebih dari 0!", "harga bukan angka"),
            ("Barang Uji", "0", "5", "Needs", "Harga harus berupa angka lebih dari 0!", "harga nol"),
            ("Barang Uji", "-5", "5", "Needs", "Harga harus berupa angka lebih dari 0!", "harga negatif"),
            ("Barang Uji", "5000", "abc", "Needs", "Stok harus berupa angka bulat minimal 0!", "stok bukan angka"),
            ("Barang Uji", "5000", "-1", "Needs", "Stok harus berupa angka bulat minimal 0!", "stok negatif"),
            ("Barang Uji", "5000", "1.5", "Needs", "Stok harus berupa angka bulat minimal 0!", "stok desimal"),
            ("Barang Uji", "5000", "5", "Lain", "Kategori harus Needs atau Wants!", "kategori lain"),
            ("Barang Uji", "5000", "5", "lain", "Kategori harus Needs atau Wants!", "kategori huruf kecil"),
        )
        for nama, harga, stok, kategori, pesan, label in kasus:
            with self.subTest(label=label):
                self.pulihkan_data()
                isi = f"1\n{nama}\n{harga}\n{stok}\n{kategori}\n"
                hasil = self.sesi_admin(isi)
                self.cek_exit(hasil)
                self.assert_teks(hasil, pesan)
                self.assert_teks(hasil, "Logout berhasil.")
                self.assert_products_tetap()
                self.assert_log_tidak_ada(action="CREATE_PRODUCT")


    def test_update_harga_sukses(self):
        produk = self.produk_fixture("P001")
        harga_awal = float(produk["price"])
        stok_awal = int(produk["stock"])
        harga_baru = 70000.0
        hasil = self.sesi_admin("3\nP001\n1\n" + str(int(harga_baru)) + "\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Masukan ID produk:")
        self.assert_teks(hasil, "Harga saat ini:")
        self.assert_teks(hasil, "Stok saat ini:")
        self.assert_rupiah(hasil, harga_awal)   # harga saat ini (dari fixtures)
        self.assert_teks(hasil, str(stok_awal))  # stok saat ini (dari fixtures)
        self.assert_teks(hasil, "P001")
        self.assert_teks(hasil, "berhasil diupdate")

        products = self.baca_products_hasil()
        self.assertEqual(products["P001"]["price"], harga_baru)
        self.assertEqual(products["P001"]["stock"], stok_awal)
        for pid, item in self.fixture_products().items():
            if pid == "P001":
                continue
            self.assertEqual(products[pid], item, msg=f"produk {pid} ikut berubah")
        log_update = self.assert_log_ada(username="admin", action="UPDATE_PRODUCT")
        self.assertEqual(log_update.get("detail"), "P001")


    def test_update_stok_sukses(self):
        produk = self.produk_fixture("P002")
        harga_awal = float(produk["price"])
        stok_awal = int(produk["stock"])
        stok_baru = stok_awal + 5
        hasil = self.sesi_admin("3\nP002\n2\n" + str(stok_baru) + "\n")
        self.cek_exit(hasil)
        self.assert_rupiah(hasil, harga_awal)
        self.assert_teks(hasil, str(stok_awal))  # stok saat ini
        self.assert_teks(hasil, "berhasil diupdate")
        products = self.baca_products_hasil()
        self.assertEqual(products["P002"]["stock"], stok_baru)
        self.assertEqual(products["P002"]["price"], harga_awal)
        log_update = self.assert_log_ada(username="admin", action="UPDATE_PRODUCT")
        self.assertEqual(log_update.get("detail"), "P002")

    def test_update_id_tidak_ditemukan(self):
        hasil = self.sesi_admin("3\nP999\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "ID produk tidak ditemukan.")
        self.assert_products_tetap()
        self.assert_log_tidak_ada(action="UPDATE_PRODUCT")

    def test_update_pilihan_invalid(self):
        hasil = self.sesi_admin("3\nP001\n9\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Pilihan tidak valid!")
        self.assert_products_tetap()
        self.assert_log_tidak_ada(action="UPDATE_PRODUCT")

    def test_update_nilai_invalid(self):
        kasus = (("1", "abc"), ("1", "0"), ("2", "-1"), ("2", "1.5"))
        for pilihan, nilai in kasus:
            with self.subTest(pilihan=pilihan, nilai=nilai):
                self.pulihkan_data()
                hasil = self.sesi_admin(f"3\nP001\n{pilihan}\n{nilai}\n")
                self.cek_exit(hasil)
                self.assert_teks(hasil, "Nilai baru tidak valid!")
                self.assert_products_tetap()
                self.assert_log_tidak_ada(action="UPDATE_PRODUCT")

    def test_delete_batal(self):
        hasil = self.sesi_admin("4\nP008\nn\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Yakin ingin menghapus")
        self.assert_teks(hasil, "Buku Tulis")
        self.assert_teks(hasil, "Penghapusan dibatalkan.")
        self.assert_products_tetap()
        self.assert_log_tidak_ada(action="DELETE_PRODUCT")

    def test_delete_sukses(self):
        hasil = self.sesi_admin("4\nP008\ny\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Yakin ingin menghapus")
        self.assert_teks(hasil, "P008")
        self.assert_teks(hasil, "berhasil dihapus")
        products = self.baca_products_hasil()
        self.assertEqual(len(products), len(self.fixture_products()) - 1)
        self.assertNotIn("P008", products)
        for pid, item in self.fixture_products().items():
            if pid == "P008":
                continue
            self.assertEqual(products[pid], item, msg=f"produk {pid} ikut berubah")
        log_delete = self.assert_log_ada(username="admin", action="DELETE_PRODUCT")
        self.assertEqual(log_delete.get("detail"), "P008")

    def test_delete_id_tidak_ditemukan(self):
        hasil = self.sesi_admin("4\nP999\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "ID produk tidak ditemukan.")
        self.assert_products_tetap()
        self.assert_log_tidak_ada(action="DELETE_PRODUCT")


# ---------------------------------------------------------------------------
# Admin: audit logs & buka blokir akun (kontrak §4.5)
# ---------------------------------------------------------------------------

class TestAdminLogsUnlock(DasarTest):
    def test_lihat_audit_logs(self):
        hasil = self.sesi_admin("5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "--- AUDIT SYSTEM LOGS (20 TERAKHIR) ---")
        # seed log harus tampil (INIT_DATA detail "Data awal PayGuard dibuat")
        self.assert_teks(hasil, "INIT_DATA")
        self.assert_teks(hasil, "Data awal PayGuard dibuat")
        # aksi sesi ini (login admin) harus tampil sebagai log baru
        self.assert_teks(hasil, "LOGIN_SUCCESS")
        self.assert_users_tetap()
        self.assert_products_tetap()

    def test_audit_logs_hanya_20_terakhir(self):
        # isi 25 log buatan HANYA di folder kerja; app menampilkan 20 terakhir
        custom = []
        for i in range(1, 26):
            custom.append({
                "time": f"2026-01-01T00:{i:02d}:00",
                "username": "admin",
                "action": f"LOG-UJI-{i:02d}",
                "detail": f"detail-{i:02d}",
            })
        (self.workdir / "data" / "logs.json").write_text(
            json.dumps(custom, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # login admin menambah 1 log (LOGIN_SUCCESS) setelah 25 log buatan
        hasil = self.sesi_admin("5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "--- AUDIT SYSTEM LOGS (20 TERAKHIR) ---")
        # format baris: [time] username: action - detail
        self.assert_teks(hasil, "[2026-01-01T00:25:00] admin: LOG-UJI-25 - detail-25")
        # 25 buatan + 1 LOGIN_SUCCESS = 26; 20 terakhir = LOG-UJI-07..25 + LOGIN_SUCCESS
        for i in range(7, 26):
            self.assert_teks(hasil, f"LOG-UJI-{i:02d}")
        self.assertNotIn("LOG-UJI-06", hasil.stdout, msg="log ke-20 terakhir salah dipotong"
                                                         + self.info(hasil))
        self.assertNotIn("LOG-UJI-01", hasil.stdout, msg=self.info(hasil))
        self.assertEqual(
            normalisasi(hasil.stdout).count("log-uji-"), 19,
            msg="jumlah baris log buatan yang tampil harus 19 (20 terakhir termasuk login)"
                + self.info(hasil),
        )

    def test_unlock_akun_andi_lalu_login(self):
        hasil = self.jalankan_app(
            input_login("admin", "123456")
            + "6\nandi\n"
            + LOGOUT_ADMIN
            + input_login("andi", "333333")
            + LOGOUT_CUSTOMER
            + KELUAR
        )
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Masukan username pelanggan:")
        self.assert_teks(hasil, "andi")
        self.assert_teks(hasil, "berhasil dibuka blokirnya")
        # andi (seed is_locked=true) sekarang bisa login
        self.assert_teks(hasil, "Login berhasil! Selamat datang, andi.")
        self.assert_menu_customer(hasil)

        user_andi = self.baca_users_hasil()["andi"]
        self.assertFalse(user_andi["is_locked"])
        self.assertEqual(user_andi["failed_attempts"], 0)
        self.assert_log_ada(username="admin", action="UNLOCK_ACCOUNT")
        self.assert_log_ada(username="andi", action="LOGIN_SUCCESS")

    def test_unlock_akun_tidak_terkunci(self):
        hasil = self.sesi_admin("6\nbudi\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Akun tidak sedang terblokir.")
        self.assert_users_tetap()
        self.assert_log_tidak_ada(action="UNLOCK_ACCOUNT")

    def test_unlock_username_tidak_ditemukan(self):
        hasil = self.sesi_admin("6\nhantu\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Username tidak ditemukan.")
        self.assert_users_tetap()
        self.assert_log_tidak_ada(action="UNLOCK_ACCOUNT")

    def test_unlock_setelah_lockout(self):
        # 1) lockout siti karena 3x PIN salah
        hasil = self.jalankan_app(input_login("siti", "000000") * 3 + KELUAR)
        self.cek_exit(hasil)
        self.assertTrue(self.baca_users_hasil()["siti"]["is_locked"])
        # 2) admin membuka blokir
        hasil = self.sesi_admin("6\nsiti\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "berhasil dibuka blokirnya")
        user_siti = self.baca_users_hasil()["siti"]
        self.assertFalse(user_siti["is_locked"])
        self.assertEqual(user_siti["failed_attempts"], 0)
        self.assert_log_ada(username="admin", action="UNLOCK_ACCOUNT")
        # 3) siti dapat login kembali
        hasil = self.jalankan_app(input_login("siti", "222222") + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Login berhasil! Selamat datang, siti.")


# ---------------------------------------------------------------------------
# Customer: top up (kontrak §4.4.1)
# ---------------------------------------------------------------------------

class TestCustomerTopup(DasarTest):

    def test_topup_sukses(self):
        saldo_awal = self.saldo_awal("siti")
        nominal = 50000
        saldo_harap = saldo_awal + nominal
        hasil = self.sesi_customer("siti", "222222", "1\n" + str(nominal) + "\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Saldo saat ini:")
        self.assert_rupiah(hasil, saldo_awal)
        self.assert_teks(hasil, "Masukan nominal top up:")
        self.assert_teks(hasil, "Top up berhasil! Saldo baru:")
        self.assert_rupiah(hasil, saldo_harap)
        self.assert_saldo("siti", saldo_harap)

        users = self.baca_users_hasil()
        for username in [nama for nama in self.fixture_users() if nama != "siti"]:
            self.assertEqual(users[username], self.fixture_users()[username],
                             msg=f"user {username} ikut berubah")
        log_topup = self.assert_log_ada(username="siti", action="TOPUP")
        self.assertEqual(float(log_topup.get("detail")), float(nominal))

    def test_topup_nominal_invalid(self):
        for nominal in ("abc", "0", "-50000", ""):
            with self.subTest(nominal=nominal):
                self.pulihkan_data()
                hasil = self.sesi_customer("siti", "222222", f"1\n{nominal}\n")
                self.cek_exit(hasil)
                self.assert_teks(hasil, "Nominal top up tidak valid!")
                self.assert_saldo("siti", 150000)
                self.assert_log_tidak_ada(username="siti", action="TOPUP")


# ---------------------------------------------------------------------------
# Customer: cari produk / marketplace / keranjang (kontrak §4.4.2)
# ---------------------------------------------------------------------------

class TestCustomerMarketplace(DasarTest):

    def test_search_produk_ada(self):
        produk = self.produk_fixture("P001")
        hasil = self.sesi_customer("budi", "111111", "2\nberas\n0\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Masukan kata kunci produk:")
        self.assert_baris_produk(hasil, "P001", produk["name"], produk["price"],
                                 produk["stock"], produk["category"])
        self.assert_teks(hasil, "Masukan ID produk yang ingin dibeli (0 untuk kembali):")
        self.assert_data_tetap()


    def test_search_case_insensitive_dan_kata_kunci_id(self):
        produk = self.produk_fixture("P001")
        kata_uji = (produk["name"].split()[0].upper(),
                    produk["name"].split()[0].lower(),
                    produk["id"].lower())
        for kata in kata_uji:
            with self.subTest(kata=kata):
                hasil = self.sesi_customer("budi", "111111", f"2\n{kata}\n0\n")
                self.cek_exit(hasil)
                self.assert_baris_produk(hasil, "P001", produk["name"], produk["price"],
                                         produk["stock"], produk["category"])


    def test_search_multi_hasil(self):
        hasil = self.sesi_customer("budi", "111111", "2\npremium\n0\n")
        self.cek_exit(hasil)
        for pid in ("P006", "P009"):
            produk = self.produk_fixture(pid)
            self.assert_baris_produk(hasil, pid, produk["name"], produk["price"],
                                     produk["stock"], produk["category"])

    def test_search_tidak_ditemukan(self):
        hasil = self.sesi_customer("budi", "111111", "2\nzzzz\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Produk tidak ditemukan.")
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_data_tetap()


    def test_search_stok_habis(self):
        # cari produk dengan stok 0 dari fixtures (data live)
        kandidat = [(pid, item) for pid, item in self.fixture_products().items()
                    if int(item["stock"]) <= 0]
        if not kandidat:
            self.skipTest("tidak ada produk stok 0 pada data live")
        pid, produk = kandidat[0]
        kata = produk["name"].split()[0].lower()
        hasil = self.sesi_customer("budi", "111111", f"2\n{kata}\n{pid}\n4\n")
        self.cek_exit(hasil)
        self.assert_baris_produk(hasil, pid, produk["name"], produk["price"],
                                 produk["stock"], produk["category"])
        self.assert_teks(hasil, "Stok produk habis!")
        self.assert_teks(hasil, "Keranjang belanja kosong!")
        self.assert_data_tetap()

    def test_search_id_tidak_ditemukan(self):
        hasil = self.sesi_customer("budi", "111111", "2\nberas\nP999\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "ID produk tidak ditemukan.")
        self.assert_data_tetap()

    def test_search_jumlah_invalid(self):
        for qty in ("999", "0", "-1", "abc", "2.5"):
            with self.subTest(qty=qty):
                self.pulihkan_data()
                hasil = self.sesi_customer("budi", "111111", f"2\nberas\nP001\n{qty}\n")
                self.cek_exit(hasil)
                self.assert_teks(hasil, "Jumlah tidak valid atau melebihi stok!")
                self.assert_data_tetap()

    def test_search_tambah_ke_keranjang(self):
        hasil = self.sesi_customer("budi", "111111", "2\nberas\nP001\n2\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "ditambahkan ke keranjang")
        self.assert_teks(hasil, "Beras 5kg")
        self.assert_teks(hasil, "x2")
        # cart hanya state sesi: users.json / products.json tidak berubah
        self.assert_data_tetap()


    def test_cart_gabung_item_sama(self):
        # tambah P001 qty 2 lalu qty 3 -> keranjang bergabung jadi qty 5
        produk = self.produk_fixture("P001")
        harga = float(produk["price"])
        total = harga * 5
        isi = (
            "2\nberas\nP001\n2\n"
            "2\nberas\nP001\n3\n"
            "4\n"
            "000000\n"
        )
        hasil = self.sesi_customer("budi", "111111", isi)
        self.cek_exit(hasil)
        self.assert_baris_item(hasil, produk["name"], 5, total)
        self.assert_teks(hasil, "Total:")
        self.assert_rupiah(hasil, total)
        self.assert_teks(hasil, "PIN Salah! Transaksi Dibatalkan.")
        self.assert_data_tetap()


# ---------------------------------------------------------------------------
# Customer: pengurutan katalog (kontrak §4.4.3)
# ---------------------------------------------------------------------------

class TestCustomerSort(DasarTest):
    def assert_pengurutan(self, hasil, pilihan, urutan):
        self.cek_exit(hasil)
        self.assert_teks(hasil, "=== PENGURUTAN KATALOG ===")
        for teks in ("1. Harga termurah", "2. Harga termahal", "3. Nama A-Z", "4. Stok terbanyak"):
            self.assert_teks(hasil, teks)
        self.assert_teks(hasil, "Pilih pengurutan (1-4):")
        self.assert_urutan_produk(hasil, urutan)
        self.assert_data_tetap()


    def test_sort_harga_termurah(self):
        hasil = self.sesi_customer("budi", "111111", "3\n1\n")
        self.assert_pengurutan(hasil, 1, self.urutan_produk_fixture(lambda p: float(p["price"]), reverse=False))


    def test_sort_harga_termahal(self):
        hasil = self.sesi_customer("budi", "111111", "3\n2\n")
        self.assert_pengurutan(hasil, 2, self.urutan_produk_fixture(lambda p: float(p["price"]), reverse=True))


    def test_sort_nama_az(self):
        hasil = self.sesi_customer("budi", "111111", "3\n3\n")
        self.assert_pengurutan(hasil, 3, self.urutan_produk_fixture(lambda p: str(p["name"]).lower()))


    def test_sort_stok_terbanyak(self):
        hasil = self.sesi_customer("budi", "111111", "3\n4\n")
        self.assert_pengurutan(hasil, 4, self.urutan_produk_fixture(lambda p: int(p["stock"]), reverse=True))

    def test_sort_pilihan_invalid(self):
        hasil = self.sesi_customer("budi", "111111", "3\n9\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Pilihan tidak valid!")
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_data_tetap()


# ---------------------------------------------------------------------------
# Customer: checkout (kontrak §4.4.4, §5)
# ---------------------------------------------------------------------------

class TestCustomerCheckout(DasarTest):

    def test_checkout_sukses_data_dan_riwayat(self):
        produk = self.produk_fixture("P005")
        harga = float(produk["price"])
        qty = 2
        total = harga * qty
        siti = self.user_fixture("siti")
        saldo_awal = float(siti["balance"])
        saldo_harap = saldo_awal - total
        stok_harap = int(produk["stock"]) - qty
        skor = self.skor_risiko_fixture("siti", total, produk["category"])
        konfirmasi = self.konfirmasi_untuk_skor(skor)
        isi = "2\nkopi\nP005\n" + str(qty) + "\n4\n"
        if konfirmasi:
            isi += konfirmasi + "\n"
        isi += "222222\n"
        hasil = self.sesi_customer("siti", "222222", isi)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "=== KERANJANG BELANJA ===")
        self.assert_baris_item(hasil, produk["name"], qty, total)
        if skor == 0:
            self.assert_teks(hasil, "[STATUS: AMAN] Kondisi keuanganmu stabil untuk transaksi ini.")
            self.assert_tidak_ada_teks(hasil, "Apakah kamu yakin tetap ingin melanjutkan checkout?")
        elif skor <= 3:
            self.assert_teks(hasil, "[STATUS: PERINGATAN SEDANG]")
            self.assert_teks(hasil, "Apakah kamu yakin tetap ingin melanjutkan checkout? (y/n)")
        else:
            self.assert_teks(hasil, "[STATUS: RISIKO TINGGI / IMPULSIVE BUYING DETECTED]")
        self.assert_teks(hasil, "Masukan PIN E-Wallet untuk konfirmasi pembayaran:")
        self.assert_teks(hasil, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.")
        self.assert_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_teks(hasil, "Tanggal:")
        self.assert_teks(hasil, f"Skor Risiko: {skor}")
        self.assert_teks(hasil, "Sisa Saldo:")
        self.assert_rupiah(hasil, saldo_harap)

        users = self.baca_users_hasil()
        siti_hasil = users["siti"]
        self.assertEqual(siti_hasil["balance"], saldo_harap)
        self.assertEqual(len(siti_hasil["transactions"]), 1)
        trx = siti_hasil["transactions"][0]
        self.assertRegex(trx["id"], r"^TRX-\d{14}$")
        self.assertRegex(trx["date"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.assertEqual(trx["total"], total)
        self.assertEqual(trx["risk_score"], skor)
        self.assertEqual(trx["items"],
                         [{"id": "P005", "name": produk["name"], "price": harga, "qty": qty}])
        self.assertIn(trx["id"].lower(), normalisasi(hasil.stdout),
                      msg="ID transaksi di resi tidak sama dengan yang disimpan")
        for username in [nama for nama in self.fixture_users() if nama != "siti"]:
            self.assertEqual(users[username], self.fixture_users()[username])

        products = self.baca_products_hasil()
        self.assertEqual(products["P005"]["stock"], stok_harap)
        for pid, item in self.fixture_products().items():
            if pid == "P005":
                continue
            self.assertEqual(products[pid], item, msg=f"stok produk {pid} ikut berubah")

        self.assert_log_lama_utuh()
        self.assert_log_ada(username="siti", action="LOGIN_SUCCESS")
        log_checkout = self.assert_log_ada(
            username="siti", action="CHECKOUT_SUCCESS_RP_" + str(int(round(total))))
        self.assertEqual(log_checkout.get("detail"), trx["id"])

        hasil2 = self.jalankan_app(
            input_login("siti", "222222") + "5\n" + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil2)
        self.assert_teks(hasil2, "=== RIWAYAT TRANSAKSI ===")
        self.assert_teks(hasil2, trx["id"].lower())
        self.assert_teks(hasil2, produk["name"])
        self.assert_rupiah(hasil2, total)
        self.assert_teks(hasil2, f"Risiko {skor}")
        self.assert_teks(hasil2, "=== TRACK RECORD ===")
        self.assert_teks(hasil2, "Jumlah transaksi: 1")
        self.assert_teks(hasil2, "Total pengeluaran:")
        self.assert_rupiah(hasil2, total)
        self.assert_teks(hasil2, "Rata-rata transaksi:")
        self.assert_rupiah(hasil2, total)


    def test_checkout_saldo_kurang_data_tidak_berubah(self):
        # cari produk + qty yang totalnya melebihi saldo siti (data live)
        saldo = self.saldo_awal("siti")
        pilihan = None
        for pid, produk in self.fixture_products().items():
            stok = int(produk["stock"])
            harga = float(produk["price"])
            if stok <= 0 or harga <= 0:
                continue
            qty = int(saldo // harga) + 1
            if qty <= stok and qty > 0:
                pilihan = (pid, produk, qty)
                break
        if pilihan is None:
            self.skipTest("tidak ada produk+qty yang melebihi saldo pada data live")
        pid, produk, qty = pilihan
        total = float(produk["price"]) * qty
        kata = produk["name"].split()[0].lower()
        hasil = self.sesi_customer("siti", "222222",
                                   f"2\n{kata}\n{pid}\n{qty}\n4\n")
        self.cek_exit(hasil)
        self.assert_rupiah(hasil, total)   # total keranjang
        self.assert_teks(hasil, "Checkout Gagal: Saldo e-wallet tidak mencukupi!")
        self.assert_teks(hasil, "Saldo:")
        self.assert_teks(hasil, "Total:")
        self.assert_rupiah(hasil, saldo)
        self.assert_tidak_ada_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_data_tetap()
        self.assertEqual(self.baca_users_hasil()["siti"]["transactions"], [])
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_SUCCESS")


    def test_checkout_pin_salah_data_tidak_berubah(self):
        produk = self.produk_fixture("P005")
        harga = float(produk["price"])
        stok_awal = int(produk["stock"])
        saldo_awal = self.saldo_awal("budi")
        jumlah_trx = len(self.user_fixture("budi")["transactions"])
        skor = self.skor_risiko_fixture("budi", harga, produk["category"])
        konfirmasi = self.konfirmasi_untuk_skor(skor)
        isi = "2\nkopi\nP005\n1\n4\n" + (konfirmasi + "\n" if konfirmasi else "")
        isi += "000000\n"
        hasil = self.sesi_customer("budi", "111111", isi)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "PIN Salah! Transaksi Dibatalkan.")
        self.assert_tidak_ada_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_data_tetap()
        budi = self.baca_users_hasil()["budi"]
        self.assertEqual(budi["balance"], saldo_awal)
        self.assertEqual(len(budi["transactions"]), jumlah_trx)
        self.assertEqual(budi["failed_attempts"], 0)    # VerifyPIN tidak menambah attempt
        self.assert_stok("P005", stok_awal)
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_SUCCESS")
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_FINGER")

    def test_checkout_keranjang_kosong(self):
        hasil = self.sesi_customer("budi", "111111", "4\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "=== KERANJANG BELANJA ===")
        self.assert_teks(hasil, "Keranjang belanja kosong!")
        self.assert_tidak_ada_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_data_tetap()


    def test_checkout_saldo_pas_total_berhasil(self):
        # Pakai user BARU + top up persis sebesar total: saldo == total (batas
        # `saldo < total` false), sepenuhnya data-driven dari fixtures produk.
        produk = min(
            (item for item in self.fixture_products().values() if int(item["stock"]) >= 2),
            key=lambda item: (float(item["price"]), item["id"]),
        )
        harga = float(produk["price"])
        qty = 2
        total = harga * qty
        nominal_topup = int(round(total))
        # skenario user baru: saldo 0 -> top up -> saldo == total
        limit = 500000.0
        sisa = total - total
        skor = 0
        if sisa < 0.3 * total:
            skor += 2
        if total > limit:
            skor += 3
        if "Wants" in [produk["category"]] and sisa < 100000:
            skor += 2
        konfirmasi = self.konfirmasi_untuk_skor(skor)
        isi = (
            input_register("qabatas", "4321")
            + input_login("qabatas", "4321")
            + "1\n" + str(nominal_topup) + "\n"
            + "2\n" + produk["id"] + "\n" + produk["id"] + "\n" + str(qty) + "\n"
            + "4\n" + (konfirmasi + "\n" if konfirmasi else "")
            + "4321\n"
        )
        hasil = self.jalankan_app(isi + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        self.assert_rupiah(hasil, total)  # total keranjang
        if skor == 0:
            self.assert_teks(hasil, "[STATUS: AMAN]")
        elif skor <= 3:
            self.assert_teks(hasil, "[STATUS: PERINGATAN SEDANG]")
        else:
            self.assert_teks(hasil, "[STATUS: RISIKO TINGGI / IMPULSIVE BUYING DETECTED]")
        self.assert_teks(hasil, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.")
        self.assert_teks(hasil, f"Skor Risiko: {skor}")
        self.assert_teks(hasil, "Sisa Saldo:")
        self.assert_rupiah(hasil, 0)

        user = self.baca_users_hasil()["qabatas"]
        self.assertEqual(user["balance"], 0.0)
        self.assertEqual(len(user["transactions"]), 1)
        self.assertEqual(user["transactions"][0]["total"], total)
        self.assertEqual(user["transactions"][0]["risk_score"], skor)
        stok_harap = int(produk["stock"]) - qty
        self.assert_stok(produk["id"], stok_harap)
        self.assert_log_ada(username="qabatas",
                            action="CHECKOUT_SUCCESS_RP_" + str(int(round(total))))


    def test_checkout_pakai_harga_dan_stok_terbaru(self):
        harga_baru_p008 = 9000.0
        stok_awal_p007 = self.stok_awal("P007")
        stok_awal_p008 = self.stok_awal("P008")
        saldo_budi = self.saldo_awal("budi")
        isi = (
            "1\nadmin\n123456\n"
            "3\nP007\n2\n1\n"
            "3\nP008\n1\n" + str(int(harga_baru_p008)) + "\n"
            "9\n"
            "1\nbudi\n111111\n"
            "2\nheadset\nP007\n2\n"      # stok baru 1 -> jumlah 2 harus ditolak
            "2\nbuku\nP008\n1\n"         # harga baru 9.000
            "4\n111111\n"
            "6\n4\n"
        )
        hasil = self.jalankan_app(isi)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "berhasil diupdate")
        self.assert_teks(hasil, "Jumlah tidak valid atau melebihi stok!")
        self.assert_teks(hasil, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.")
        self.assert_rupiah(hasil, harga_baru_p008)  # total memakai harga baru
        self.assert_teks(hasil, "Skor Risiko: 0")

        products = self.baca_products_hasil()
        self.assertEqual(products["P007"]["stock"], 1)
        self.assertEqual(products["P008"]["price"], harga_baru_p008)
        self.assertEqual(products["P008"]["stock"], stok_awal_p008 - 1)
        budi = self.baca_users_hasil()["budi"]
        self.assertEqual(budi["balance"], saldo_budi - harga_baru_p008)
        trx = budi["transactions"][-1]
        self.assertEqual(trx["total"], harga_baru_p008)
        self.assertEqual(trx["items"][0]["price"], harga_baru_p008)
        self.assert_log_ada(username="budi",
                            action="CHECKOUT_SUCCESS_RP_" + str(int(round(harga_baru_p008))))


# ---------------------------------------------------------------------------
# Risk Shield (kontrak §4.3, §5)
# ---------------------------------------------------------------------------

class TestRiskShield(DasarTest):

    def test_risk_aman_tanpa_konfirmasi(self):
        produk = min(self.fixture_products().values(),
                     key=lambda item: (float(item["price"]), item["id"]))
        total = float(produk["price"])
        skor = self.skor_risiko_fixture("siti", total, produk["category"])
        if skor != 0:
            self.skipTest(f"data live tidak menghasilkan skor 0 (skor={skor})")
        hasil = self.sesi_customer(
            "siti", "222222",
            f"2\n{produk['id']}\n{produk['id']}\n1\n4\n999999\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "PAYGUARD FINANCIAL RISK SHIELD")
        self.assert_teks(hasil, "[STATUS: AMAN] Kondisi keuanganmu stabil untuk transaksi ini.")
        self.assert_tidak_ada_teks(hasil, "PERINGATAN SEDANG")
        self.assert_tidak_ada_teks(hasil, "RISIKO TINGGI")
        self.assert_tidak_ada_teks(hasil, "Apakah kamu yakin")
        self.assert_teks(hasil, "PIN Salah! Transaksi Dibatalkan.")
        self.assert_data_tetap()


    def test_risk_peringatan_sedang_batal_n(self):
        produk = self.produk_fixture("P001")
        qty = 2
        total = float(produk["price"]) * qty
        skor = self.skor_risiko_fixture("siti", total, produk["category"])
        if skor == 0:
            self.skipTest("data live tidak menghasilkan status risk (skor 0)")
        hasil = self.sesi_customer(
            "siti", "222222",
            f"2\nberas\nP001\n{qty}\n4\nn\n")
        self.cek_exit(hasil)
        if skor > 3:
            self.assert_teks(hasil, "[STATUS: RISIKO TINGGI / IMPULSIVE BUYING DETECTED]")
            self.assert_teks(hasil, "Ketik 'SAYA YAKIN' untuk memaksa transaksi:")
        else:
            self.assert_teks(hasil, "[STATUS: PERINGATAN SEDANG]")
            self.assert_teks(hasil, "Apakah kamu yakin tetap ingin melanjutkan checkout? (y/n)")
        self.assert_teks(hasil, "Transaksi dibatalkan oleh pengguna/Risk Shield.")
        self.assert_tidak_ada_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_data_tetap()
        self.assertEqual(self.baca_users_hasil()["siti"]["transactions"], [])
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_SUCCESS")


    def test_risk_peringatan_sedang_lanjut_y(self):
        produk = self.produk_fixture("P001")
        qty = 2
        total = float(produk["price"]) * qty
        saldo_awal = self.saldo_awal("siti")
        stok_awal = int(produk["stock"])
        skor = self.skor_risiko_fixture("siti", total, produk["category"])
        if skor == 0:
            self.skipTest("data live tidak menghasilkan status risk (skor 0)")
        konfirmasi = self.konfirmasi_untuk_skor(skor)
        hasil = self.sesi_customer(
            "siti", "222222",
            f"2\nberas\nP001\n{qty}\n4\n{konfirmasi}\n222222\n")
        self.cek_exit(hasil)
        if skor <= 3:
            self.assert_teks(hasil, "[STATUS: PERINGATAN SEDANG]")
        else:
            self.assert_teks(hasil, "[STATUS: RISIKO TINGGI / IMPULSIVE BUYING DETECTED]")
        self.assert_teks(hasil, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.")
        self.assert_teks(hasil, f"Skor Risiko: {skor}")
        saldo_harap = saldo_awal - total
        self.assert_rupiah(hasil, saldo_harap)

        siti = self.baca_users_hasil()["siti"]
        self.assertEqual(siti["balance"], saldo_harap)
        self.assertEqual(len(siti["transactions"]), 1)
        self.assertEqual(siti["transactions"][0]["total"], total)
        self.assertEqual(siti["transactions"][0]["risk_score"], skor)
        self.assert_stok("P001", stok_awal - qty)
        self.assert_log_ada(username="siti",
                            action="CHECKOUT_SUCCESS_RP_" + str(int(round(total))))


    def _siapkan_high_risk(self, frasa_konfirmasi, pin=""):
        """Skenario risk tinggi deterministik pakai user BARU (data-driven produk).

        User baru balance 0 -> top up (total + 100.000) -> beli P007 x2.
        Sisa 100.000 < 30% saldo & total > daily_limit 500.000 -> skor 5.
        Tidak bergantung pada saldo/histori user seed yang bisa berubah.
        """
        produk = self.produk_fixture("P007")
        qty = 2
        if int(produk["stock"]) < qty:
            self.skipTest("stok P007 di data live kurang dari 2")
        total = float(produk["price"]) * qty
        saldo_target = total + 100000.0
        sisa = saldo_target - total
        skor = 0
        if sisa < 0.3 * saldo_target:
            skor += 2
        if total > 500000.0:
            skor += 3
        if "Wants" in [produk["category"]] and sisa < 100000:
            skor += 2
        if skor <= 3:
            self.skipTest(f"data live tidak mendukung skenario risk tinggi (skor={skor})")
        isi = (
            input_register("qa_high", "4321")
            + input_login("qa_high", "4321")
            + "1\n" + str(int(round(saldo_target))) + "\n"
            + "2\n" + produk["id"] + "\n" + produk["id"] + "\n" + str(qty) + "\n"
            + "4\n" + frasa_konfirmasi + "\n"
            + (pin + "\n" if pin else "")
            + LOGOUT_CUSTOMER + KELUAR
        )
        return self.jalankan_app(isi), produk, qty, total, saldo_target, skor




    def test_risk_tinggi_batal_string_selain_saya_yakin(self):
        for frasa in ("ya", "saya yakin", "YAKIN"):
            with self.subTest(frasa=frasa):
                self.pulihkan_data()
                hasil, produk, qty, total, saldo_target, skor = \
                    self._siapkan_high_risk(frasa)
                self.cek_exit(hasil)
                self.assert_teks(hasil, "Top up berhasil!")
                self.assert_teks(hasil, "[STATUS: RISIKO TINGGI / IMPULSIVE BUYING DETECTED]")
                self.assert_teks(hasil, "Rekomendasi AI: Tunda transaksi ini demi kesehatan finansialmu.")
                self.assert_teks(hasil, "Ketik 'SAYA YAKIN' untuk memaksa transaksi:")
                self.assert_teks(hasil, "Transaksi dibatalkan oleh pengguna/Risk Shield.")
                self.assert_tidak_ada_teks(hasil, "--- RESI PEMBAYARAN ---")
                user = self.baca_users_hasil()["qa_high"]
                self.assertEqual(user["balance"], saldo_target)  # top up tetap
                self.assertEqual(len(user["transactions"]), 0)
                self.assert_stok("P007", int(produk["stock"]))
                self.assert_log_tidak_ada(awalan_action="CHECKOUT_FINGER_RP_")


    def test_risk_tinggi_saya_yakin_lanjut(self):
        hasil, produk, qty, total, saldo_target, skor = \
            self._siapkan_high_risk("SAYA YAKIN", "4321")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "[STATUS: RISIKO TINGGI / IMPULSIVE BUYING DETECTED]")
        self.assert_teks(hasil, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.")
        self.assert_teks(hasil, f"Skor Risiko: {skor}")
        sisa = saldo_target - total
        self.assert_teks(hasil, "Sisa Saldo:")
        self.assert_rupiah(hasil, sisa)

        user = self.baca_users_hasil()["qa_high"]
        self.assertEqual(user["balance"], sisa)
        self.assertEqual(len(user["transactions"]), 1)
        trx = user["transactions"][0]
        self.assertEqual(trx["total"], total)
        self.assertEqual(trx["risk_score"], skor)
        self.assertEqual(trx["items"][0]["id"], "P007")
        self.assertEqual(trx["items"][0]["qty"], qty)
        self.assert_stok("P007", int(produk["stock"]) - qty)
        self.assert_log_ada(username="qa_high",
                            action="CHECKOUT_SUCCESS_RP_" + str(int(round(total))))


# ---------------------------------------------------------------------------
# Customer: riwayat transaksi & track record (kontrak §4.4.5)
# ---------------------------------------------------------------------------

class TestCustomerRiwayat(DasarTest):

    def test_riwayat_transaksi_budi(self):
        transaksi = self.user_fixture("budi")["transactions"]
        if not transaksi:
            self.skipTest("budi tidak punya transaksi pada data live")
        hasil = self.sesi_customer("budi", "111111", "5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "=== RIWAYAT TRANSAKSI ===")
        total_semua = 0.0
        for trx in transaksi:
            total_semua += float(trx["total"])
            self.assert_teks(hasil, str(trx["date"]).lower())
            self.assert_teks(hasil, str(trx["id"]).lower())
            self.assert_rupiah(hasil, float(trx["total"]))
            self.assert_teks(hasil, f"Risiko {trx['risk_score']}")
            for item in trx["items"]:
                self.assert_teks(hasil, item["name"])
        self.assert_teks(hasil, "=== TRACK RECORD ===")
        self.assert_teks(hasil, f"Jumlah transaksi: {len(transaksi)}")
        self.assert_teks(hasil, "Total pengeluaran:")
        self.assert_rupiah(hasil, total_semua)
        rata = total_semua / len(transaksi)
        self.assert_teks(hasil, "Rata-rata transaksi:")
        self.assert_rupiah(hasil, rata)
        self.assert_data_tetap()

    def test_riwayat_kosong(self):
        hasil = self.sesi_customer("siti", "222222", "5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Belum ada transaksi.")
        self.assert_tidak_ada_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_data_tetap()


# ---------------------------------------------------------------------------
# Menu tidak valid pada menu admin & pelanggan (kontrak §4 umum)
# ---------------------------------------------------------------------------

class TestMenuInvalid(DasarTest):
    def test_menu_admin_pilihan_invalid(self):
        hasil = self.sesi_admin("0\nabc\n")
        self.cek_exit(hasil)
        self.assertGreaterEqual(
            self.hitung_teks(hasil, "Pilihan tidak valid!"), 2, msg=self.info(hasil)
        )
        self.assertGreaterEqual(
            self.hitung_teks(hasil, "=== MENU ADMIN / MERCHANT ==="), 3,
            msg="menu admin tidak diulang setelah pilihan invalid" + self.info(hasil),
        )
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_teks(hasil, "Terima kasih telah menggunakan PayGuard.")

    def test_menu_customer_pilihan_invalid(self):
        hasil = self.jalankan_app(
            input_login("budi", "111111") + "9\nabc\n" + LOGOUT_CUSTOMER + KELUAR
        )
        self.cek_exit(hasil)
        self.assertGreaterEqual(
            self.hitung_teks(hasil, "Pilihan tidak valid!"), 2, msg=self.info(hasil)
        )
        self.assertGreaterEqual(
            self.hitung_teks(hasil, "=== MENU PELANGGAN ==="), 3,
            msg="menu pelanggan tidak diulang setelah pilihan invalid" + self.info(hasil),
        )
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_teks(hasil, "Terima kasih telah menggunakan PayGuard.")


# ---------------------------------------------------------------------------
# Unit test read-only modul: auth, risk_assistant, data_manager (kontrak §6)
# ---------------------------------------------------------------------------

class TestUnitModul(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if str(PROJECT_DIR) not in sys.path:
            sys.path.insert(0, str(PROJECT_DIR))

    def impor(self, nama):
        try:
            return importlib.import_module(nama)
        except Exception as galat:  # noqa: BLE001 - laporkan semua kegagalan impor
            self.fail(f"Modul '{nama}' gagal diimpor dari {PROJECT_DIR}: {galat!r}")

    @staticmethod
    def buat_user(balance, daily_limit, transactions=None):
        return {
            "username": "uji",
            "pin_hash": "x",
            "salt": "x",
            "balance": float(balance),
            "daily_limit": float(daily_limit),
            "role": "customer",
            "is_locked": False,
            "failed_attempts": 0,
            "transactions": list(transactions or []),
        }

    # -- auth ---------------------------------------------------------------
    def test_hash_password_dengan_salt_tetap_cocok_pin_hash_seed(self):
        auth = self.impor("auth")
        users = muat_fixture("users.json")
        for username, pin in PINS.items():
            with self.subTest(username=username):
                user = users[username]
                hasil, salt = auth.HashPasswordWithSalt(pin, user["salt"])
                self.assertEqual(salt, user["salt"], msg="salt tetap harus dikembalikan apa adanya")
                self.assertEqual(hasil, user["pin_hash"],
                                 msg=f"hash PIN {username} tidak cocok dengan pin_hash seed")
                harap = hashlib.sha256((pin + user["salt"]).encode("utf-8")).hexdigest()
                self.assertEqual(hasil, harap)

    def test_hash_password_dengan_salt_baru(self):
        auth = self.impor("auth")
        hasil, salt = auth.HashPasswordWithSalt("123456")
        self.assertIsInstance(salt, str)
        self.assertRegex(salt, r"^[0-9a-fA-F]{16}$")
        harap = hashlib.sha256(("123456" + salt).encode("utf-8")).hexdigest()
        self.assertEqual(hasil, harap)
        self.assertIsInstance(hasil, str)
        self.assertRegex(hasil, r"^[0-9a-f]{64}$")
        # salt harus acak/berbeda tiap pemanggilan
        _, salt2 = auth.HashPasswordWithSalt("123456")
        self.assertNotEqual(salt, salt2)

    def test_generate_random_hex(self):
        auth = self.impor("auth")
        nilai = auth.GenerateRandomHex()
        self.assertIsInstance(nilai, str)
        self.assertRegex(nilai, r"^[0-9a-fA-F]{16}$")
        nilai8 = auth.GenerateRandomHex(8)
        self.assertRegex(nilai8, r"^[0-9a-fA-F]{8}$")
        kumpulan = {auth.GenerateRandomHex() for _ in range(10)}
        self.assertEqual(len(kumpulan), 10, msg="GenerateRandomHex tidak acak/berulang")

    def test_verify_pin(self):
        auth = self.impor("auth")
        users = muat_fixture("users.json")
        for username, pin in PINS.items():
            with self.subTest(username=username):
                import copy
                user = copy.deepcopy(users[username])
                self.assertTrue(auth.VerifyPIN(user, pin),
                                msg=f"VerifyPIN({username}, PIN benar) harus True")
                self.assertFalse(auth.VerifyPIN(user, "000000"),
                                 msg="VerifyPIN dengan PIN salah harus False")
                # VerifyPIN tidak boleh menambah failed_attempts / mengubah user
                self.assertEqual(user["failed_attempts"], users[username]["failed_attempts"])
                self.assertEqual(user["is_locked"], users[username]["is_locked"])

    # -- risk assistant -----------------------------------------------------
    def test_calculate_today_expenses(self):
        risk = self.impor("risk_assistant")
        sekarang = datetime.now()
        hari_ini = sekarang.strftime("%Y-%m-%d")
        kemarin = (sekarang - timedelta(days=1)).strftime("%Y-%m-%d")
        transactions = [
            {"id": "T1", "date": hari_ini + "T01:02:03", "total": 10000.0, "risk_score": 0, "items": []},
            {"id": "T2", "date": hari_ini + "T23:59:59", "total": 2500.5, "risk_score": 0, "items": []},
            {"id": "T3", "date": kemarin + "T10:00:00", "total": 4000.0, "risk_score": 0, "items": []},
            {"id": "T4", "date": "2020-01-01T10:00:00", "total": 14000.0, "risk_score": 0, "items": []},
        ]
        self.assertAlmostEqual(risk.CalculateTodayExpenses(transactions), 12500.5, places=6)
        self.assertEqual(float(risk.CalculateTodayExpenses([])), 0.0)
        self.assertEqual(float(risk.CalculateTodayExpenses(None)), 0.0)

    def test_evaluate_purchase_risk_kombinasi_indikator(self):
        risk = self.impor("risk_assistant")
        kasus = (
            # (balance, daily_limit, total, kategori, skor, warnings)
            (1000000, 500000, 100000, ["Needs"], 0, []),
            (1000000, 2000000, 700000, ["Needs"], 0, []),   # sisa tepat 30% -> tanpa ind.1
            (1000000, 100000, 100000, ["Needs"], 0, []),    # today+total tepat limit -> tanpa ind.2
            (200000, 1000000, 100000, ["Wants"], 0, []),    # sisa tepat 100.000 -> tanpa ind.3
            (1000000, 2000000, 800000, ["Needs"], 2, [WARNING_SALDO]),
            (1000000, 80000, 100000, ["Needs"], 3, [WARNING_LIMIT]),
            (100000, 500000, 10000, ["Wants"], 2, [WARNING_TERSIER]),
            (1000000, 2000000, 950000, ["Wants"], 4, [WARNING_SALDO, WARNING_TERSIER]),
            (1000000, 500000, 800000, ["Needs"], 5, [WARNING_SALDO, WARNING_LIMIT]),
            (1000000, 500000, 950000, ["Wants"], 7,
             [WARNING_SALDO, WARNING_LIMIT, WARNING_TERSIER]),
        )
        for balance, limit, total, kategori, skor_harap, warning_harap in kasus:
            with self.subTest(balance=balance, limit=limit, total=total, kategori=kategori):
                user = self.buat_user(balance, limit)
                skor, warnings = risk.EvaluatePurchaseRisk(user, float(total), kategori)
                self.assertIsInstance(skor, int,
                                      msg=f"risk_score harus int, dapat {type(skor)}")
                self.assertIsInstance(warnings, list)
                self.assertEqual(skor, skor_harap,
                                 msg=f"skor salah (dapat {skor}, harap {skor_harap})")
                self.assertEqual(
                    list(warnings), warning_harap,
                    msg=f"daftar warning salah: {warnings!r}",
                )

    def test_evaluate_purchase_risk_memakai_pengeluaran_hari_ini(self):
        risk = self.impor("risk_assistant")
        hari_ini = datetime.now().strftime("%Y-%m-%d")
        kemarin = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        trx_hari_ini = [
            {"id": "T1", "date": hari_ini + "T08:00:00", "total": 90000.0, "risk_score": 0, "items": []},
        ]
        trx_kemarin = [
            {"id": "T2", "date": kemarin + "T08:00:00", "total": 90000.0, "risk_score": 0, "items": []},
        ]
        # 90.000 (hari ini) + 50.000 > daily_limit 100.000 -> +3 (hanya indikator 2)
        user = self.buat_user(2000000, 100000, trx_hari_ini)
        skor, warnings = risk.EvaluatePurchaseRisk(user, 50000.0, ["Needs"])
        self.assertEqual(skor, 3)
        self.assertEqual(list(warnings), [WARNING_LIMIT])
        # transaksi kemarin tidak dihitung
        user = self.buat_user(2000000, 100000, trx_kemarin)
        skor, warnings = risk.EvaluatePurchaseRisk(user, 50000.0, ["Needs"])
        self.assertEqual(skor, 0)
        self.assertEqual(list(warnings), [])

    # -- data_manager (final, read-only) -----------------------------------
    def test_rupiah(self):
        dm = self.impor("data_manager")
        kasus = (
            (0, "Rp0"),
            (999, "Rp999"),
            (14000, "Rp14.000"),
            (1212000, "Rp1.212.000"),
            (1000000, "Rp1.000.000"),
            (5000.0, "Rp5.000"),
            (-198000, "Rp-198.000"),
        )
        for angka, harap in kasus:
            with self.subTest(angka=angka):
                self.assertEqual(dm.rupiah(angka), harap)

    def test_id_produk_baru(self):
        dm = self.impor("data_manager")
        self.assertEqual(dm.id_produk_baru(muat_fixture("products.json")), "P010")
        self.assertEqual(dm.id_produk_baru({}), "P001")
        self.assertEqual(dm.id_produk_baru({"P100": {}, "P001": {}}), "P101")

    def test_waktu_sekarang(self):
        dm = self.impor("data_manager")
        waktu = dm.waktu_sekarang()
        self.assertRegex(waktu, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.assertRegex(waktu, r"^\d{4}-\d{2}-\d{2}T")


# ---------------------------------------------------------------------------
# Integritas: fixtures = salinan byte-identik data asli
# ---------------------------------------------------------------------------

class TestIntegritasData(unittest.TestCase):
    maxDiff = None

    def test_fixtures_salinan_byte_identik(self):
        # users/products/logs = DATA -> wajib byte-identik dengan data asli
        for nama in FIXTURE_IDENTIK_FILES:
            with self.subTest(nama=nama):
                asli = DATA_DIR / nama
                fixture = FIXTURES_DIR / nama
                self.assertTrue(asli.is_file(), msg=f"{asli} tidak ada")
                self.assertTrue(fixture.is_file(), msg=f"{fixture} tidak ada")
                self.assertEqual(
                    fixture.read_bytes(), asli.read_bytes(),
                    msg=f"fixtures/{nama} tidak sinkron dengan payguard/data/{nama}. "
                        f"Salin ulang fixtures dari data asli.",
                )

    def test_perangkat_deployment_dikecualikan_dari_byte_identik(self):
        """perangkat.json = config deployment (data asli soap, fixture simulasi)."""
        fixture = FIXTURES_DIR / "perangkat.json"
        asli = DATA_DIR / "perangkat.json"
        self.assertTrue(fixture.is_file(), msg=f"{fixture} tidak ada")
        self.assertTrue(asli.is_file(), msg=f"{asli} tidak ada")
        self.assertEqual(
            muat_fixture("perangkat.json").get("mode"), MODE_PERANGKAT_TEST,
            msg="fixtures/perangkat.json wajib mode 'simulasi' (hermetis)",
        )
        self.assertIn(
            baca_json_file(asli).get("mode"), ("simulasi", "soap"),
            msg="data/perangkat.json deployment boleh simulasi/soap",
        )

    def test_fixtures_json_valid_dan_struktur_dasar(self):
        users = muat_fixture("users.json")
        products = muat_fixture("products.json")
        logs = muat_fixture("logs.json")
        self.assertIsInstance(users, dict)
        self.assertIsInstance(products, dict)
        self.assertIsInstance(logs, list)
        for username in ("admin", "budi", "siti", "andi"):
            self.assertIn(username, users)
        for pid in ("P001", "P002", "P003", "P004", "P005", "P006", "P007", "P008", "P009"):
            self.assertIn(pid, products)
        self.assertEqual(products["P009"]["stock"], 0)
        self.assertIn("Prabu", users)
        self.assertIsInstance(muat_fixture("keranjang.json"), list)
        self.assertEqual(muat_fixture("perangkat.json").get("mode"), MODE_PERANGKAT_TEST)


# ---------------------------------------------------------------------------
# Test TERAKHIR: data asli tidak berubah selama suite
# ---------------------------------------------------------------------------

class TestZZIntegritasAkhir(unittest.TestCase):
    """Kelas ini sengaja diberi awalan 'ZZ' agar dijalankan TERAKHIR oleh
    ``loadTestsFromModule`` (urutan nama class di ``dir(module)``).
    Memastikan seluruh suite tidak mengubah ``payguard/data/*.json`` (SHA256
    sebelum suite == sesudah suite) dan ``tests/_tmp`` bersih."""

    maxDiff = None

    def test_hash_data_asli_sama_sebelum_dan_sesudah_suite(self):
        for nama in DATA_FILES:
            with self.subTest(nama=nama):
                jalur = DATA_DIR / nama
                self.assertTrue(jalur.is_file(), msg=f"{jalur} hilang")
                hash_akhir = hashlib.sha256(jalur.read_bytes()).hexdigest()
                self.assertIn(nama, _HASH_DATA_ASLI,
                              msg=f"snapshot hash awal {nama} tidak ada")
                self.assertEqual(
                    hash_akhir, _HASH_DATA_ASLI[nama],
                    msg=(f"SHA256 payguard/data/{nama} berubah selama suite! "
                         f"awal={_HASH_DATA_ASLI[nama]} akhir={hash_akhir}"),
                )

    def test_tmp_bersih_setelah_suite(self):
        if BASE_TMP.exists():
            sisa = sorted(str(p) for p in BASE_TMP.iterdir())
            self.assertEqual(
                sisa, [],
                msg=f"tests/_tmp tidak bersih setelah suite: {sisa}",
            )


# ---------------------------------------------------------------------------
# Pembersihan folder _tmp setelah seluruh modul selesai
# ---------------------------------------------------------------------------

def tearDownModule():
    if BASE_TMP.exists():
        hapus_pohon(BASE_TMP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
