"""Suite test fitur **pembayaran sidik jari X100C** PayGuard CLI (unittest, stdlib).

Kontrak acuan:
- ``payguard/SPESIFIKASI_SIDIK_JARI.md`` (seluruh §1–§7, terutama §6)
- ``payguard/SPESIFIKASI_PAYGUARD.md`` versi terbaru (menu utama 4 opsi, menu admin 8 opsi,
  field ``finger_id``, checkout jalur sidik jari)

Pola pengujian sama dengan ``test_payguard.py``:
- folder kerja ``tests/_tmp/kasus_<uuid>`` (``Path.mkdir``, BUKAN ``tempfile.mkdtemp()``);
- setiap test menyalin SEMUA ``payguard/*.py`` + ``data/`` hasil fixtures ke folder kerja,
  aplikasi dijalankan sebagai subprocess dengan ``cwd`` = folder kerja;
- unit test ``fingerprint.py`` dijalankan lewat driver subprocess di folder kerja (agar
  ``PERANGKAT_FILE``/``STATE_FILE`` modul selalu menunjuk ke data SALINAN, bukan data asli);
- mock perangkat X100C memakai ``socketserver`` TCP lokal di ``127.0.0.1:<port acak>``
  yang meniru ``POST /iWsService`` + response XML ``GetAttLog``/``GetUserInfo``;
- data asli ``payguard/data/*.json`` di-hash SHA256 saat modul diimpor dan diverifikasi
  ulang oleh ``TestZZIntegritasAkhir`` (test terakhir modul).

Catatan deployment (ronde 3): ``data/perangkat.json`` asli bisa mode ``soap`` untuk
perangkat X100C nyata (192.168.1.201), sedangkan ``tests/fixtures/perangkat.json``
SELALU mode ``simulasi`` (hermetis, tidak menyentuh perangkat asli). Karena itu
``perangkat.json`` dikecualikan dari uji "fixtures byte-identik"; hash config asli
tetap dipantau agar QA tidak mengubahnya.
"""

import hashlib
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import time
import threading
import unittest
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Lokasi & konstanta
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parents[1]      # .../payguard
TESTS_DIR = Path(__file__).resolve().parent            # .../payguard/tests
FIXTURES_DIR = TESTS_DIR / "fixtures"
BASE_TMP = TESTS_DIR / "_tmp"
DATA_DIR = PROJECT_DIR / "data"

DATA_FILES = ("users.json", "products.json", "logs.json", "keranjang.json", "perangkat.json")

# users/products/logs = DATA, wajib byte-identik fixtures <-> data asli.
# perangkat.json = KONFIGURASI DEPLOYMENT: data asli boleh mode "soap" untuk
# perangkat X100C nyata (192.168.1.201), sedangkan fixtures SELALU mode "simulasi"
# agar test hermetis / tidak menyentuh perangkat asli. Karena itu perangkat.json
# DIKECUALIKAN dari uji byte-identik, tetapi hash-nya tetap dipantau (QA tidak boleh
# mengubah config deployment).
FIXTURE_IDENTIK_FILES = ("users.json", "products.json", "logs.json", "keranjang.json")
MODE_PERANGKAT_TEST = "simulasi"

APP_TIMEOUT = 60
DRIVER_TIMEOUT = 30

KELUAR = "4\n"
LOGOUT_ADMIN = "10\n"
LOGOUT_CUSTOMER = "6\n"

PROMPT_SIMULASI = "(SIMULASI) Masukkan ID perangkat:"
PESAN_KONEKSI_GAGAL = (
    "Perangkat X100C tidak terhubung. Periksa kabel/jaringan dan konfigurasi."
)

# Snapshot SHA256 data asli SEBELUM suite (test integritas di akhir modul).
_HASH_DATA_ASLI = {}
for _nama_data in DATA_FILES:
    _jalur_data = DATA_DIR / _nama_data
    if _jalur_data.is_file():
        _HASH_DATA_ASLI[_nama_data] = hashlib.sha256(_jalur_data.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Helper murni
# ---------------------------------------------------------------------------

def normalisasi(teks):
    return " ".join(str(teks).lower().split())


def pola_rupiah(jumlah):
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


def baca_json_file(jalur):
    return json.loads(Path(jalur).read_text(encoding="utf-8"))


def muat_fixture(nama):
    return baca_json_file(FIXTURES_DIR / nama)


def hash_file(jalur):
    return hashlib.sha256(Path(jalur).read_bytes()).hexdigest()


def input_login(username, pin):
    return f"1\n{username}\n{pin}\n"


def input_register(username, pin):
    return f"2\n{username}\n{pin}\n"


def input_sidik_jari(pin):
    return f"3\n{pin}\n"


def port_tertutup():
    """Cari port 127.0.0.1 yang (hampir pasti) tidak ada listener-nya."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soket:
        soket.bind(("127.0.0.1", 0))
        return soket.getsockname()[1]


def xml_parse_toleran(teks):
    """Parse XML request dari X100C; abaikan atribut ``xsi:*`` tanpa deklarasi
    namespace (contoh kontrak §4.2 memakai ``xsi:type`` tanpa xmlns)."""
    bersih = re.sub(r'\s+xmlns:xsi="[^"]*"', "", str(teks))
    bersih = re.sub(r'\s+xsi:[A-Za-z_][\w.-]*="[^"]*"', "", bersih)
    return ET.fromstring(bersih)


# ---------------------------------------------------------------------------
# Mock perangkat ZKTeco X100C (stdlib socketserver)
# ---------------------------------------------------------------------------

class _MockX100CHandler(socketserver.BaseRequestHandler):
    """Handler HTTP sederhana: terima POST /iWsService berisi XML, balas XML."""

    def _kirim(self, kode, jenis_konten, awak):
        respons = (
            f"HTTP/1.0 {kode}\r\nContent-Type: {jenis_konten}\r\n"
            f"Content-Length: {len(awak)}\r\n\r\n"
        ).encode("utf-8") + awak
        self.request.sendall(respons)

    def handle(self):
        server = self.server
        try:
            self.request.settimeout(5)
            data = b""
            while b"\r\n\r\n" not in data:
                potongan = self.request.recv(4096)
                if not potongan:
                    break
                data += potongan
            header, _, sisa = data.partition(b"\r\n\r\n")
            header_teks = header.decode("utf-8", "replace")
            panjang = 0
            for baris in header_teks.split("\r\n")[1:]:
                if baris.lower().startswith("content-length:"):
                    try:
                        panjang = int(baris.split(":", 1)[1].strip())
                    except ValueError:
                        panjang = 0
            isi = sisa
            while len(isi) < panjang:
                potongan = self.request.recv(4096)
                if not potongan:
                    break
                isi += potongan
            isi_teks = isi.decode("utf-8", "replace")
            server.catatan.append({"header": header_teks, "body": isi_teks})

            # Kontrak §4.2: ROOT elemen XML = nama perintah, tanpa wrapper <Command>.
            # Root tag dideteksi via regex agar atribut xsi:* tanpa deklarasi
            # namespace (lihat contoh kontrak) tidak menggagalkan deteksi.
            command = None
            alasan = ""
            cocok_akar = re.search(r"<\s*([A-Za-z][A-Za-z0-9_.-]*)", isi_teks)
            if not cocok_akar:
                alasan = "body bukan XML / tidak ada root tag"
            else:
                command = cocok_akar.group(1)
            if command in ("Command", "CommandResponse"):
                alasan = ("wrapper <Command>/<CommandName> tidak diizinkan: "
                          "root elemen harus nama perintah (kontrak §4.2)")
                command = None
            elif command is not None and command not in ("GetAttLog", "GetUserInfo"):
                alasan = f"command tidak dikenal: {command!r}"
                command = None

            if command is None:
                server.status.append(400)
                self._kirim(400, "text/plain", alasan.encode("utf-8"))
                return

            if command == "GetAttLog":
                baris_balasan = server.ambil_attlog()
            else:
                cocok = re.search(r"<PIN>([^<]*)</PIN>", isi_teks)
                pin_diminta = cocok.group(1) if cocok else None
                baris_balasan = server.ambil_userinfo(pin_diminta)

            xml_balasan = MockX100C.buat_response(command, baris_balasan)
            server.status.append(200)
            self._kirim(200, "text/xml; charset=utf-8", xml_balasan.encode("utf-8"))
        except Exception as galat:  # noqa: BLE001 - catat untuk diagnosa test
            server.galat.append(repr(galat))


class MockX100C:
    """Server TCP lokal yang meniru webserver X100C (mode soap)."""

    def __init__(self, ambil_attlog=None, ambil_userinfo=None):
        self.ambil_attlog = ambil_attlog or (lambda: [])
        self.ambil_userinfo = ambil_userinfo or (lambda pin: [])
        self.catatan = []
        self.galat = []
        self.status = []
        self._server = socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0), _MockX100CHandler
        )
        self._server.daemon_threads = True
        self._server.catatan = self.catatan
        self._server.galat = self.galat
        self._server.status = self.status
        self._server.ambil_attlog = self.ambil_attlog
        self._server.ambil_userinfo = self.ambil_userinfo
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05},
            daemon=True,
        )

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        self._thread.start()
        return self

    def stop(self):
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            self._thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, tipe, nilai, jejak):
        self.stop()
        return False

    # -- response -----------------------------------------------------------
    @staticmethod
    def buat_response(command, baris_baris):
        """Response mengikuti kontrak §4.2: root ``<GetAttLogResponse>`` dst."""
        bagian = []
        for baris in baris_baris:
            isi = "".join(f"<{kunci}>{nilai}</{kunci}>" for kunci, nilai in baris.items())
            bagian.append("<Row>" + isi + "</Row>")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<{command}Response>" + "".join(bagian) + f"</{command}Response>"
        )

    # -- convenience --------------------------------------------------------
    def perangkat(self, **tambahan):
        """Config perangkat.json mode soap yang menunjuk ke mock ini."""
        config = {
            "mode": "soap",
            "host": "127.0.0.1",
            "port": self.port,
            "com_key": 0,
            "timeout": 3,
            "jendela_detik": 30,
            "batas_tunggu_detik": 2,
        }
        config.update(tambahan)
        return config


def buat_baris_attlog(pin, saat=None, status="1", verified="1", workcode="0"):
    if saat is None:
        saat = datetime.now()
    if isinstance(saat, datetime):
        saat = saat.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "PIN": str(pin),
        "DateTime": saat,
        "Verified": str(verified),
        "Status": str(status),
        "WorkCode": str(workcode),
    }


# ---------------------------------------------------------------------------
# Driver unit test (subprocess, agar file/state selalu di folder kerja salinan)
# ---------------------------------------------------------------------------

DRIVER_DASAR = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

import fingerprint

hasil = {}
try:
    hasil["buat_xml"] = fingerprint.buat_xml("GetAttLog", {"PIN": "All"}, 0)
    hasil["buat_xml_userinfo"] = fingerprint.buat_xml("GetUserInfo", {"PIN": "1001"}, 0)
    contoh_response = """<?xml version="1.0" encoding="UTF-8"?>
<GetAttLogResponse>
  <Row><PIN>1001</PIN><DateTime>2026-11-03 12:00:00</DateTime><Verified>1</Verified><Status>1</Status><WorkCode>0</WorkCode></Row>
  <Row><PIN>1002</PIN><DateTime>2026-11-03 12:01:02</DateTime><Verified>1</Verified><Status>1</Status><WorkCode>0</WorkCode></Row>
</GetAttLogResponse>"""
    hasil["parse_rows"] = fingerprint.parse_rows(contoh_response)
    hasil["parse_rows_kosong"] = fingerprint.parse_rows("<GetAttLogResponse></GetAttLogResponse>")
    kejadian = fingerprint.kejadian_simulasi("1001")
    hasil["kejadian_simulasi"] = kejadian
    hasil["kunci"] = fingerprint.kunci_kejadian(kejadian)
    hasil["state_awal"] = fingerprint.baca_state()
    hasil["cari"] = {}
    for pin in ("1001", "1002", "1003", "9999", ""):
        akun = fingerprint.cari_user_dari_pin(pin)
        hasil["cari"][pin] = None if akun is None else akun.get("username")
except Exception as galat:  # noqa: BLE001
    hasil["exception"] = type(galat).__name__ + ": " + str(galat)

print(json.dumps(hasil))
'''

DRIVER_BACA_PERANGKAT = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

import fingerprint

print(json.dumps(fingerprint.baca_perangkat()))
'''

DRIVER_STATE = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

import fingerprint

hasil = {}
try:
    hasil["state_awal"] = fingerprint.baca_state()
    fingerprint.simpan_state({"terproses": ["1001|2026-11-03 12:00:00|1"]})
    hasil["state_setelah"] = fingerprint.baca_state()
    hasil["state_file"] = fingerprint.STATE_FILE
    import os
    hasil["state_file_ada"] = os.path.isfile(fingerprint.STATE_FILE)
    folder = os.path.dirname(fingerprint.STATE_FILE)
    hasil["sisa_tmp"] = [n for n in os.listdir(folder) if n.endswith(".tmp")]
except Exception as galat:  # noqa: BLE001
    hasil["exception"] = type(galat).__name__ + ": " + str(galat)
print(json.dumps(hasil))
'''

DRIVER_DEDUPE = r'''
import datetime
import json
import sys

sys.path.insert(0, sys.argv[1])

import fingerprint

try:
    saat = datetime.datetime.strptime(sys.argv[2], "%Y-%m-%d %H:%M:%S")
    events = [
        {"PIN": "1001", "DateTime": sys.argv[2], "Verified": "1", "Status": "1", "WorkCode": "0"},
        {"PIN": "1002", "DateTime": (saat - datetime.timedelta(seconds=3600)).strftime("%Y-%m-%d %H:%M:%S"),
         "Verified": "1", "Status": "1", "WorkCode": "0"},
    ]
    fingerprint.get_attlog = lambda perangkat=None: list(events)
    baru_pertama = fingerprint.ambil_kejadian_baru(jendela_detik=30)
    for kejadian in baru_pertama:
        fingerprint.tandai_kejadian(kejadian)
    baru_kedua = fingerprint.ambil_kejadian_baru(jendela_detik=30)
    hasil = {
        "pertama": baru_pertama,
        "kedua": baru_kedua,
        "state": fingerprint.baca_state(),
        "state_file_ada": __import__("os").path.isfile(fingerprint.STATE_FILE),
    }
except Exception as galat:  # noqa: BLE001
    hasil = {"exception": type(galat).__name__ + ": " + str(galat)}
print(json.dumps(hasil))
'''

DRIVER_EVENT_TETAP = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

import fingerprint

try:
    teks = sys.argv[2]
    waktu = sys.argv[3]
    fingerprint.get_attlog = lambda perangkat=None: [
        {"PIN": teks, "DateTime": waktu, "Verified": "1", "Status": "1", "WorkCode": "0"}
    ]
    print(json.dumps({"events": fingerprint.ambil_kejadian_baru(jendela_detik=30)}))
except Exception as galat:  # noqa: BLE001
    print(json.dumps({"exception": type(galat).__name__ + ": " + str(galat)}))
'''

DRIVER_TANDAI_EVENT = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

import fingerprint

try:
    kejadian = {"PIN": sys.argv[2], "DateTime": sys.argv[3],
                "Verified": "1", "Status": "1", "WorkCode": "0"}
    fingerprint.tandai_kejadian(kejadian)
    print(json.dumps({"ok": True, "kunci": fingerprint.kunci_kejadian(kejadian)}))
except Exception as galat:  # noqa: BLE001
    print(json.dumps({"exception": type(galat).__name__ + ": " + str(galat)}))
'''

DRIVER_DEVICE = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

import fingerprint

aksi = sys.argv[2]
hasil = {}
try:
    if aksi == "attlog":
        hasil["attlog"] = fingerprint.get_attlog()
    elif aksi == "tes":
        ok, pesan = fingerprint.tes_koneksi()
        hasil["tes"] = {"ok": bool(ok), "pesan": pesan}
    elif aksi == "userinfo":
        hasil["userinfo"] = fingerprint.get_user_info(sys.argv[3])
    elif aksi == "events":
        hasil["events"] = fingerprint.ambil_kejadian_baru(jendela_detik=30)
    elif aksi == "soap_mati":
        hasil["raw"] = fingerprint.kirim_soap(
            fingerprint.buat_xml("GetAttLog", {"PIN": "All"}, 0)
        )
    elif aksi == "wrapper":
        # sengaja mengirim format LAMA <Command> supaya mock menolak (HTTP 400)
        hasil["raw"] = fingerprint.kirim_soap(
            "<Command><CommandName>GetAttLog</CommandName>"
            '<ArgComKey xsi:type="xsd:integer">0</ArgComKey>'
            "<Arg><PIN>All</PIN></Arg></Command>"
        )
except Exception as galat:  # noqa: BLE001
    hasil["exception"] = type(galat).__name__ + ": " + str(galat)
print(json.dumps(hasil))
'''


# ---------------------------------------------------------------------------
# Base class
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
    """Folder kerja terisolasi + helper runner aplikasi/driver + data helper."""

    maxDiff = None

    def setUp(self):
        BASE_TMP.mkdir(parents=True, exist_ok=True)
        self.workdir = BASE_TMP / ("kasus_" + uuid.uuid4().hex)
        self.workdir.mkdir()
        self.siapkan_app(self.workdir)

    def tearDown(self):
        hapus_pohon(self.workdir)

    # -- folder kerja -------------------------------------------------------
    def siapkan_app(self, workdir):
        folder_data = workdir / "data"
        folder_data.mkdir()
        for nama in DATA_FILES:
            shutil.copyfile(FIXTURES_DIR / nama, folder_data / nama)
        for berkas in sorted(PROJECT_DIR.glob("*.py")):
            shutil.copyfile(berkas, workdir / berkas.name)
        # Pengaman hermetis: config perangkat di folder kerja WAJIB mode simulasi
        # supaya test tidak pernah menghubungi perangkat X100C asli (192.168.1.201).
        config_perangkat = baca_json_file(folder_data / "perangkat.json")
        if config_perangkat.get("mode") != MODE_PERANGKAT_TEST:
            self.fail(
                "fixtures/perangkat.json harus mode 'simulasi' agar test hermetis; "
                f"dapat mode {config_perangkat.get('mode')!r}. "
                "Jangan salin config deployment (soap) ke fixtures."
            )

    def pulihkan_data(self):
        for nama in DATA_FILES:
            shutil.copyfile(FIXTURES_DIR / nama, self.workdir / "data" / nama)
        # state sidik jari runtime tidak ikut fixture -> bersihkan
        state = self.workdir / "data" / "finger_state.json"
        if state.exists():
            state.unlink()

    @property
    def data_dir_kerja(self):
        return self.workdir / "data"

    def tulis_perangkat(self, isi):
        (self.data_dir_kerja / "perangkat.json").write_text(
            json.dumps(isi, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def hapus_perangkat(self):
        jalur = self.data_dir_kerja / "perangkat.json"
        if jalur.exists():
            jalur.unlink()

    # -- proses -------------------------------------------------------------
    def _env(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def jalankan_app(self, teks_input, timeout=APP_TIMEOUT):
        perintah = [sys.executable, str(self.workdir / "main.py")]
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
                    timeout=timeout,
                    env=self._env(),
                )
            except subprocess.TimeoutExpired:
                self.fail(f"Aplikasi tidak selesai dalam {timeout} detik.\ninput={teks_input!r}")
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



    def jalankan_driver(self, driver, tambahan=(), timeout=DRIVER_TIMEOUT):
        perintah = [sys.executable, "-c", driver, str(self.workdir)] + [str(a) for a in tambahan]
        for percobaan in range(3):
            try:
                hasil = subprocess.run(
                    perintah,
                    cwd=str(self.workdir),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    env=self._env(),
                )
            except subprocess.TimeoutExpired:
                self.fail(f"Driver tidak selesai dalam {timeout} detik: {driver[:80]!r}")
            # Windows: os.replace() pada data salinan kadang PermissionError sesaat karena
            # antivirus/indexer memegang handle file; ulangi run (bukan bug app).
            if (hasil.returncode == 1
                    and "PermissionError" in (hasil.stderr or "")
                    and ("Access is denied" in (hasil.stderr or "")
                         or "WinError 5" in (hasil.stderr or ""))
                    and percobaan < 2):
                time.sleep(0.3 * (percobaan + 1))
                continue
            break

        if hasil.returncode != 0:
            self.fail(
                f"Driver fingerprint gagal (exit {hasil.returncode}).\n"
                f"stdout:\n{hasil.stdout}\nstderr:\n{hasil.stderr}"
            )
        baris = [b for b in hasil.stdout.splitlines() if b.strip()]
        self.assertTrue(baris, msg=f"driver tidak mengeluarkan JSON:\n{hasil.stdout}")
        try:
            return json.loads(baris[-1])
        except json.JSONDecodeError as galat:
            self.fail(f"output driver bukan JSON: {galat}\nstdout:\n{hasil.stdout}")

    # -- assertion ----------------------------------------------------------
    def info(self, hasil):
        return (
            f"\n--- exit code ---\n{hasil.returncode}"
            f"\n--- stdout ---\n{hasil.stdout}"
            f"\n--- stderr ---\n{hasil.stderr}"
        )

    def cek_exit(self, hasil, kode=0):
        self.assertEqual(hasil.returncode, kode, msg=self.info(hasil))

    def assert_teks(self, hasil, teks, msg=""):
        self.assertIn(normalisasi(teks), normalisasi(hasil.stdout), msg=msg + self.info(hasil))

    def assert_tidak_ada_teks(self, hasil, teks, msg=""):
        self.assertNotIn(normalisasi(teks), normalisasi(hasil.stdout), msg=msg + self.info(hasil))

    def hitung_teks(self, hasil, teks):
        return normalisasi(hasil.stdout).count(normalisasi(teks))

    def assert_rupiah(self, hasil, jumlah, msg=""):
        self.assertRegex(
            normalisasi(hasil.stdout), pola_rupiah(jumlah),
            msg=f"tidak menemukan nominal {jumlah}" + msg + self.info(hasil),
        )

    # -- data ---------------------------------------------------------------
    def baca_users_hasil(self):
        return baca_json_file(self.data_dir_kerja / "users.json")

    def baca_products_hasil(self):
        return baca_json_file(self.data_dir_kerja / "products.json")

    def baca_logs_hasil(self):
        return baca_json_file(self.data_dir_kerja / "logs.json")

    def baca_state_hasil(self):
        return baca_json_file(self.data_dir_kerja / "finger_state.json")

    def baca_keranjang_hasil(self):
        return baca_json_file(self.data_dir_kerja / "keranjang.json")

    def fixture_keranjang(self):
        return muat_fixture("keranjang.json")

    def assert_keranjang_kosong(self, msg=""):
        self.assertEqual(self.baca_keranjang_hasil(), [],
                         msg="keranjang.json harus kosong" + msg)
    # -- helper data-driven (nilai dari fixtures / data live) ----------------
    def produk_fixture(self, pid):
        return self.fixture_products()[pid]

    def harga_awal(self, pid):
        return float(self.produk_fixture(pid)["price"])

    def stok_awal(self, pid):
        return int(self.produk_fixture(pid)["stock"])

    def saldo_awal(self, username):
        return float(self.fixture_users()[username]["balance"])

    def user_fixture(self, username):
        return self.fixture_users()[username]

    def jumlah_trx_awal(self, username):
        return len(self.fixture_users()[username].get("transactions", []))

    def produk_uji_checkout(self, min_stok=1):
        """Pilih produk yang stoknya cukup di data live (harga termurah)."""
        kandidat = [(pid, item) for pid, item in self.fixture_products().items()
                    if int(item.get("stock", 0)) >= int(min_stok)]
        if not kandidat:
            self.skipTest(f"tidak ada produk stok >= {min_stok} pada data live")
        kandidat.sort(key=lambda pasangan: (float(pasangan[1]["price"]), pasangan[0]))
        return kandidat[0]

    def skor_risiko_fixture(self, username, total, kategori):
        user = self.fixture_users()[username]
        from datetime import datetime as _dt
        hari_ini = _dt.now().strftime("%Y-%m-%d")
        today_spent = sum(float(trx.get("total", 0))
                          for trx in user.get("transactions", [])
                          if str(trx.get("date", ""))[:10] == hari_ini)
        saldo = float(user["balance"])
        limit = float(user["daily_limit"])
        sisa = saldo - float(total)
        skor = 0
        if sisa < 0.3 * saldo:
            skor += 2
        if today_spent + float(total) > limit:
            skor += 3
        if "Wants" in kategori and sisa < 100000:
            skor += 2
        return skor

    def cari_skenario_risk(self, username, qty=2):
        for pid, produk in self.fixture_products().items():
            if int(produk.get("stock", 0)) < qty:
                continue
            total = float(produk["price"]) * qty
            skor = self.skor_risiko_fixture(username, total, produk["category"])
            if skor > 0:
                return pid, produk, qty, total, skor
        self.skipTest("data live tidak menghasilkan skenario risk")

    def set_finger_id_kerja(self, username, finger_id):
        """Set finger_id pada data SALINAN folder kerja (bukan fixtures/data asli)."""
        users = baca_json_file(self.data_dir_kerja / "users.json")
        users[username]["finger_id"] = str(finger_id)
        (self.data_dir_kerja / "users.json").write_text(
            json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def rupiah_teks(angka):
        angka = int(round(float(angka)))
        if angka < 0:
            return "Rp-" + f"{abs(angka):,}".replace(",", ".")
        return "Rp" + f"{angka:,}".replace(",", ".")



    def _assert_hold_pertama(self, hasil, username="budi"):
        """Assert hold terbentuk setelah tap sidik jari gagal (nilai dari fixtures)."""
        pid, produk = self.produk_uji_checkout(min_stok=2)
        harga = float(produk["price"])
        qty = 2
        total = harga * qty
        saldo_awal = self.saldo_awal(username)
        jumlah_trx = self.jumlah_trx_awal(username)
        stok_awal = int(produk["stock"])
        self.assert_teks(hasil, "Sidik jari tidak cocok.")
        self.assert_teks(
            hasil,
            "Sidik jari gagal. Belanjaan ditahan di keranjang dan stok sudah dikurangi.",
        )
        self.assert_teks(hasil, "Coba lagi lewat menu 4 untuk melanjutkan pembayaran.")
        self.assert_tidak_ada_teks(hasil, "--- RESI PEMBAYARAN ---")
        self.assert_tidak_ada_teks(hasil, "TRANSAKSI BERHASIL!")

        keranjang = self.baca_keranjang_hasil()
        self.assertEqual(len(keranjang), 1,
                         msg=f"keranjang={keranjang!r}" + self.info(hasil))
        record = keranjang[0]
        self.assertRegex(record["id"], r"^HOLD-\d{14}$")
        self.assertEqual(record["username"], username)
        self.assertRegex(record["waktu"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.assertEqual(record["items"],
                         [{"id": pid, "name": produk["name"],
                           "price": harga, "qty": qty}])
        self.assertEqual(record["total"], total)
        self.assertEqual(record["percobaan"], 1)
        self.assertEqual(record["status"], "tertahan")

        user = self.baca_users_hasil()[username]
        self.assertEqual(user["balance"], saldo_awal)
        self.assertEqual(len(user["transactions"]), jumlah_trx)
        self.assert_stok(pid, stok_awal - qty)
        log_hold = self.assert_log_ada(username=username, action="HOLD_CART")
        detail = str(log_hold.get("detail", ""))
        self.assertTrue(detail.startswith(record["id"] + ":"),
                        msg=f"detail log HOLD_CART salah: {detail!r}")
        self.assertEqual(float(detail.split(":", 1)[1]), total)
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_FINGER_RP_")
        self.assert_log_tidak_ada(awalan_action="CHECKOUT_SUCCESS_RP_")
        return record

    def fixture_users(self):
        return muat_fixture("users.json")

    def fixture_products(self):
        return muat_fixture("products.json")

    def fixture_logs(self):
        return muat_fixture("logs.json")

    def assert_saldo(self, username, nilai):
        users = self.baca_users_hasil()
        self.assertIn(username, users)
        self.assertEqual(users[username]["balance"], float(nilai),
                         msg=f"saldo {username} != {nilai}: {users[username]!r}")

    def assert_stok(self, pid, nilai):
        products = self.baca_products_hasil()
        self.assertIn(pid, products)
        self.assertEqual(products[pid]["stock"], int(nilai),
                         msg=f"stok {pid} != {nilai}: {products[pid]!r}")

    def assert_users_tetap(self, msg=""):
        hasil = self.baca_users_hasil()
        harap = self.fixture_users()
        # login sukses me-reset failed_attempts; normalisasi agar tidak flaky
        for username in harap:
            if username in hasil:
                harap[username]["failed_attempts"] = hasil[username]["failed_attempts"]
        self.assertEqual(hasil, harap,
                         msg="users.json berubah padahal seharusnya tidak." + msg)

    def assert_products_tetap(self, msg=""):
        self.assertEqual(self.baca_products_hasil(), self.fixture_products(),
                         msg="products.json berubah padahal seharusnya tidak." + msg)

    # -- log ----------------------------------------------------------------
    def log_baru(self):
        return self.baca_logs_hasil()[len(self.fixture_logs()):]

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
            msg=(f"log baru tidak ada (username={username}, action={action}, "
                 f"awalan={awalan_action}); log_baru={self.log_baru()!r}" + msg),
        )
        return daftar[0]

    def assert_log_tidak_ada(self, username=None, action=None, awalan_action=None, msg=""):
        daftar = self.cari_log(username=username, action=action, awalan_action=awalan_action)
        self.assertEqual(daftar, [], msg=f"ada log yang tidak seharusnya: {daftar!r}" + msg)

    def assert_fixtures_identik(self, nama=None):
        """Cek fixtures byte-identik data asli untuk file DATA (bukan config deployment).

        ``perangkat.json`` dikecualikan: fixture-nya mode simulasi (hermetis),
        data asli boleh mode soap untuk perangkat nyata.
        """
        for nama_berkas in ([nama] if nama else FIXTURE_IDENTIK_FILES):
            self.assertEqual(
                (FIXTURES_DIR / nama_berkas).read_bytes(),
                (DATA_DIR / nama_berkas).read_bytes(),
                msg=f"fixtures/{nama_berkas} tidak sinkron dengan payguard/data/",
            )

    # -- sesi --------------------------------------------------------------
    def sesi_admin(self, isi_menu):
        return self.jalankan_app(input_login("admin", "123456") + isi_menu + LOGOUT_ADMIN + KELUAR)

    def sesi_sidik_jari(self, pin, isi_menu):
        return self.jalankan_app(input_sidik_jari(pin) + isi_menu + LOGOUT_CUSTOMER + KELUAR)


# ---------------------------------------------------------------------------
# 1. Unit test fingerprint.py (via driver subprocess di folder kerja salinan)
# ---------------------------------------------------------------------------

class TestUnitFingerprint(DasarTest):
    def test_buat_xml_get_attlog(self):
        """Kontrak §4.2: root elemen = nama perintah, TANPA wrapper <Command>."""
        data = self.jalankan_driver(DRIVER_DASAR)
        self.assertNotIn("exception", data, msg=str(data))
        xml = data["buat_xml"]
        self.assertIn("<GetAttLog>", xml)
        self.assertIn("</GetAttLog>", xml)
        self.assertIn("<PIN>All</PIN>", xml)
        self.assertIn("ArgComKey", xml)
        self.assertIn("Arg>", xml)
        # wrapper protokol lama TIDAK boleh dipakai
        self.assertNotIn("<Command>", xml)
        self.assertNotIn("<CommandName>", xml)
        self.assertNotIn("</Command>", xml)
        # struktur XML valid: root tag = GetAttLog
        akar = xml_parse_toleran(xml)
        self.assertEqual(akar.tag, "GetAttLog")
        teks = {elemen.tag: (elemen.text or "") for elemen in akar.iter()}
        self.assertEqual(teks.get("ArgComKey"), "0")
        self.assertEqual(teks.get("PIN"), "All")

        # GetUserInfo: root = GetUserInfo, PIN sesuai argumen
        xml_user = data["buat_xml_userinfo"]
        akar_user = xml_parse_toleran(xml_user)
        self.assertEqual(akar_user.tag, "GetUserInfo")
        self.assertIn("<PIN>1001</PIN>", xml_user)
        self.assertNotIn("<Command>", xml_user)

    def test_parse_rows_response(self):
        data = self.jalankan_driver(DRIVER_DASAR)
        self.assertNotIn("exception", data, msg=str(data))
        rows = data["parse_rows"]
        self.assertEqual(len(rows), 2, msg=f"rows={rows!r}")
        self.assertEqual(rows[0]["PIN"], "1001")
        self.assertEqual(rows[0]["DateTime"], "2026-11-03 12:00:00")
        self.assertEqual(rows[0]["Status"], "1")
        self.assertEqual(rows[0]["Verified"], "1")
        self.assertEqual(rows[1]["PIN"], "1002")
        self.assertEqual(rows[1]["DateTime"], "2026-11-03 12:01:02")
        self.assertEqual(data["parse_rows_kosong"], [])

    def test_kejadian_simulasi_dan_kunci_kejadian(self):
        data = self.jalankan_driver(DRIVER_DASAR)
        self.assertNotIn("exception", data, msg=str(data))
        kejadian = data["kejadian_simulasi"]
        self.assertEqual(kejadian.get("PIN"), "1001")
        self.assertEqual(str(kejadian.get("Status")), "1")
        waktu = kejadian.get("DateTime")
        self.assertTrue(waktu, msg=f"event tanpa DateTime: {kejadian!r}")
        saat = None
        for format_waktu in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                saat = datetime.strptime(str(waktu), format_waktu)
                break
            except ValueError:
                continue
        self.assertIsNotNone(saat, msg=f"format DateTime tidak dikenali: {waktu!r}")
        self.assertLess(abs((datetime.now() - saat).total_seconds()), 10,
                        msg=f"DateTime event simulasi tidak 'sekarang': {waktu!r}")
        kunci_harap = f"{kejadian['PIN']}|{kejadian['DateTime']}|{kejadian['Status']}"
        self.assertEqual(data["kunci"], kunci_harap)

    def test_cari_user_dari_pin(self):
        data = self.jalankan_driver(DRIVER_DASAR)
        cari = data["cari"]
        self.assertEqual(cari["1001"], "budi")
        self.assertEqual(cari["1002"], "siti")
        self.assertEqual(cari["1003"], "andi")
        self.assertIsNone(cari["9999"])
        self.assertIsNone(cari[""])

    def test_baca_state_default_dan_simpan_state(self):
        data = self.jalankan_driver(DRIVER_DASAR)
        self.assertEqual(data["state_awal"], {"terproses": []})

        data = self.jalankan_driver(DRIVER_STATE)
        self.assertNotIn("exception", data, msg=str(data))
        self.assertEqual(data["state_setelah"], {"terproses": ["1001|2026-11-03 12:00:00|1"]})
        self.assertTrue(data["state_file_ada"])
        self.assertIn("finger_state.json", data["state_file"])
        # file state ada di folder SALINAN, bukan data asli
        self.assertTrue(str(data["state_file"]).startswith(str(self.workdir)),
                        msg=f"STATE_FILE salah lokasi: {data['state_file']}")
        self.assertEqual(data["sisa_tmp"], [], msg="ada file .tmp tertinggal (tulis tidak bersih)")

    def test_dedupe_state_event_tidak_diproses_dua_kali(self):
        waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = self.jalankan_driver(DRIVER_DEDUPE, [waktu])
        self.assertNotIn("exception", data, msg=str(data))
        # hanya event fresh (1001) yang lolos; event lama (1002) difilter jendela
        self.assertEqual(len(data["pertama"]), 1, msg=f"event pertama={data['pertama']!r}")
        self.assertEqual(data["pertama"][0]["PIN"], "1001")
        # setelah ditandai, event yang sama tidak muncul lagi (tidak bisa replay)
        self.assertEqual(data["kedua"], [], msg=f"event kedua={data['kedua']!r}")
        kunci = f"1001|{waktu}|1"
        self.assertIn(kunci, data["state"]["terproses"])
        self.assertTrue(data["state_file_ada"])

    def test_event_kadaluwarsa_ditolak(self):
        lama = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        data = self.jalankan_driver(DRIVER_EVENT_TETAP, ["1001", lama])
        self.assertNotIn("exception", data, msg=str(data))
        self.assertEqual(data["events"], [], msg="event kadaluwarsa tidak boleh lolos")

    def test_replay_antar_proses_via_state_file(self):
        waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pertama = self.jalankan_driver(DRIVER_EVENT_TETAP, ["1001", waktu])
        self.assertEqual(len(pertama["events"]), 1, msg=str(pertama))
        _ = self.jalankan_driver(DRIVER_TANDAI_EVENT, ["1001", waktu])
        kedua = self.jalankan_driver(DRIVER_EVENT_TETAP, ["1001", waktu])
        self.assertEqual(kedua["events"], [],
                         msg="event yang sudah ditandai masih muncul (bisa replay)")

    def test_baca_perangkat_default_tanpa_file(self):
        self.hapus_perangkat()
        config = self.jalankan_driver(DRIVER_BACA_PERANGKAT)
        self.assertEqual(config.get("mode"), "simulasi")
        self.assertEqual(int(config.get("port")), 80)
        self.assertEqual(int(config.get("com_key")), 0)
        self.assertEqual(int(config.get("timeout")), 5)
        self.assertEqual(int(config.get("jendela_detik")), 30)
        self.assertEqual(int(config.get("batas_tunggu_detik")), 20)

    def test_baca_perangkat_override_dari_file(self):
        kustom = {
            "mode": "soap",
            "host": "127.0.0.1",
            "port": 4321,
            "com_key": 7,
            "timeout": 2,
            "jendela_detik": 5,
            "batas_tunggu_detik": 3,
        }
        self.tulis_perangkat(kustom)
        config = self.jalankan_driver(DRIVER_BACA_PERANGKAT)
        for kunci, nilai in kustom.items():
            self.assertEqual(config.get(kunci), nilai, msg=f"key {kunci} salah: {config!r}")

    def test_baca_perangkat_file_rusak_pakai_default(self):
        (self.data_dir_kerja / "perangkat.json").write_text("ini bukan json", encoding="utf-8")
        config = self.jalankan_driver(DRIVER_BACA_PERANGKAT)
        self.assertEqual(config.get("mode"), "simulasi")

    def test_config_dibaca_ulang_setiap_pemanggilan(self):
        self.tulis_perangkat({"mode": "simulasi", "host": "127.0.0.1", "port": 80,
                              "com_key": 0, "timeout": 5,
                              "jendela_detik": 30, "batas_tunggu_detik": 20})
        pertama = self.jalankan_driver(DRIVER_BACA_PERANGKAT)
        self.assertEqual(pertama.get("mode"), "simulasi")
        self.tulis_perangkat({"mode": "soap", "host": "10.1.2.3", "port": 8080,
                              "com_key": 3, "timeout": 4,
                              "jendela_detik": 12, "batas_tunggu_detik": 6})
        kedua = self.jalankan_driver(DRIVER_BACA_PERANGKAT)
        self.assertEqual(kedua.get("mode"), "soap")
        self.assertEqual(kedua.get("host"), "10.1.2.3")
        self.assertEqual(int(kedua.get("port")), 8080)

    def test_demo_fingerprint_py_read_only(self):
        hasil = subprocess.run(
            [sys.executable, str(self.workdir / "fingerprint.py")],
            cwd=str(self.workdir), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=DRIVER_TIMEOUT, env=self._env(),
        )
        self.assertEqual(hasil.returncode, 0, msg=f"stdout:\n{hasil.stdout}\nstderr:\n{hasil.stderr}")
        self.assertIn("simulasi", normalisasi(hasil.stdout))
        data_awal = {nama: (self.data_dir_kerja / nama).read_bytes()
                     for nama in ("users.json", "products.json", "logs.json")}
        for nama, isi in data_awal.items():
            self.assertEqual((self.data_dir_kerja / nama).read_bytes(), isi,
                             msg=f"demo fingerprint.py mengubah {nama}")
        self.assertFalse((self.data_dir_kerja / "finger_state.json").exists(),
                         msg="demo fingerprint.py tidak boleh menandai/menulis state")


# ---------------------------------------------------------------------------
# 2. Mock perangkat X100C (klien SOAP)
# ---------------------------------------------------------------------------

class TestMockPerangkat(DasarTest):
    def _konfigurasi_soap(self, mock, **tambahan):
        self.tulis_perangkat(mock.perangkat(**tambahan))

    def test_get_attlog_lewat_mock(self):
        saat = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        baris = [buat_baris_attlog("1001", saat), buat_baris_attlog("1002", saat)]
        with MockX100C(ambil_attlog=lambda: list(baris)) as mock:
            self._konfigurasi_soap(mock)
            data = self.jalankan_driver(DRIVER_DEVICE, ["attlog"])
            self.assertNotIn("exception", data, msg=str(data))
            rows = data["attlog"]
            self.assertEqual(len(rows), 2, msg=f"rows={rows!r}")
            self.assertEqual(rows[0]["PIN"], "1001")
            self.assertEqual(rows[1]["PIN"], "1002")
            self.assertEqual(rows[0]["DateTime"], saat)
            self.assertEqual(rows[0]["Status"], "1")
            # request harus POST /iWsService dengan XML root = nama perintah
            self.assertGreaterEqual(len(mock.catatan), 1)
            header = mock.catatan[0]["header"]
            body = mock.catatan[0]["body"]
            self.assertIn("POST /iWsService", header)
            self.assertIn("Content-Length:", header)
            self.assertIn("Content-Type: text/xml", header)
            akar = xml_parse_toleran(body)
            self.assertEqual(akar.tag, "GetAttLog")
            self.assertIn("<PIN>All</PIN>", body)
            self.assertIn("ArgComKey", body)
            self.assertNotIn("<Command>", body)
            self.assertNotIn("<CommandName>", body)
            # response root harus <GetAttLogResponse>
            self.assertIn(200, mock.status)

    def test_mock_menolak_request_wrapper_command(self):
        """Mock menolak format protokol lama <Command>/<CommandName> (HTTP 400)."""
        with MockX100C() as mock:
            self._konfigurasi_soap(mock)
            data = self.jalankan_driver(DRIVER_DEVICE, ["wrapper"])
        self.assertIn(
            400, mock.status,
            msg=("mock harus menolak wrapper <Command> dengan HTTP 400; "
                 f"status={mock.status}, data={data!r}"),
        )
        self.assertNotIn(200, mock.status)
        self.assertGreaterEqual(len(mock.catatan), 1)

    def test_tes_koneksi_sukses(self):
        baris = [buat_baris_attlog("1001")]
        with MockX100C(ambil_attlog=lambda: list(baris)) as mock:
            self._konfigurasi_soap(mock)
            data = self.jalankan_driver(DRIVER_DEVICE, ["tes"])
            self.assertNotIn("exception", data, msg=str(data))
            tes = data["tes"]
            self.assertTrue(tes["ok"], msg=f"tes koneksi gagal: {tes!r}")
            pesan = normalisasi(tes["pesan"])
            self.assertIn("koneksi x100c ok", pesan)
            self.assertIn(f"127.0.0.1:{mock.port}", pesan)
            self.assertIn("1 log", pesan)

    def test_get_user_info_dikenal_dan_tidak_dikenal(self):
        def userinfo(pin):
            if str(pin) == "1001":
                return [{"PIN": "1001", "Name": "BUDI", "Pri": "0", "Passwd": ""}]
            return []

        with MockX100C(ambil_userinfo=userinfo) as mock:
            self._konfigurasi_soap(mock)
            data = self.jalankan_driver(DRIVER_DEVICE, ["userinfo", "1001"])
            self.assertNotIn("exception", data, msg=str(data))
            self.assertIsNotNone(data["userinfo"])
            self.assertEqual(data["userinfo"]["PIN"], "1001")
            data = self.jalankan_driver(DRIVER_DEVICE, ["userinfo", "9999"])
            self.assertIsNone(data["userinfo"])

    def test_event_fresh_dan_stale_via_mock(self):
        saat = datetime.now()
        baris = [
            buat_baris_attlog("1001", saat),
            buat_baris_attlog("1002", saat - timedelta(hours=2)),
        ]
        with MockX100C(ambil_attlog=lambda: list(baris)) as mock:
            self._konfigurasi_soap(mock, jendela_detik=30)
            data = self.jalankan_driver(DRIVER_DEVICE, ["events"])
            self.assertNotIn("exception", data, msg=str(data))
            pin = [kejadian.get("PIN") for kejadian in data["events"]]
            self.assertEqual(pin, ["1001"], msg=f"event={data['events']!r}")

    def test_soap_ke_host_mati_menghasilkan_oserror(self):
        self.tulis_perangkat({
            "mode": "soap", "host": "127.0.0.1", "port": port_tertutup(),
            "com_key": 0, "timeout": 1, "jendela_detik": 30, "batas_tunggu_detik": 1,
        })
        data = self.jalankan_driver(DRIVER_DEVICE, ["soap_mati"])
        self.assertIn("exception", data, msg=f"harus raise OSError: {data!r}")
        self.assertRegex(data["exception"], r"(OSError|TimeoutError)",
                         msg=f"exception={data['exception']!r}")


# ---------------------------------------------------------------------------
# 3. Integrasi: admin kelola sidik jari (mode simulasi)
# ---------------------------------------------------------------------------

class TestAdminSidikJari(DasarTest):
    def test_lihat_daftar_sidik_jari(self):
        hasil = self.sesi_admin("7\n3\n5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "=== KELOLA SIDIK JARI (X100C) ===")
        for teks in (
            "1. Daftarkan sidik jari ke akun",
            "2. Hapus pendaftaran sidik jari",
            "3. Lihat daftar sidik jari",
            "4. Tes koneksi X100C",
            "5. Kembali",
            "Pilih menu (1-5):",
        ):
            self.assert_teks(hasil, teks)
        self.assert_teks(hasil, "--- DAFTAR SIDIK JARI ---")
        self.assert_teks(hasil, "budi -> PIN 1001")
        self.assert_teks(hasil, "siti -> PIN 1002")
        self.assert_teks(hasil, "andi -> PIN 1003")
        self.assert_tidak_ada_teks(hasil, "admin -> PIN")
        self.assert_tidak_ada_teks(hasil, "NaNas -> PIN")
        # data tidak berubah
        self.assert_users_tetap()
        self.assert_products_tetap()

    def test_daftar_sidik_jari_sukses(self):
        hasil = self.sesi_admin("7\n1\nNaNas\n2001\n3\n5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Masukan username:")
        self.assert_teks(hasil, "Masukan ID perangkat (PIN X100C):")
        self.assert_teks(hasil, "Sidik jari akun 'NaNas' terdaftar dengan ID perangkat 2001.")
        self.assert_teks(hasil, "NaNas -> PIN 2001")

        users = self.baca_users_hasil()
        self.assertEqual(users["NaNas"]["finger_id"], "2001")
        # user lain tetap
        for username in ("admin", "budi", "siti", "andi"):
            self.assertEqual(users[username]["finger_id"],
                             self.fixture_users()[username]["finger_id"])
        log_enroll = self.assert_log_ada(username="admin", action="FINGER_ENROLL")
        self.assertEqual(log_enroll.get("detail"), "NaNas:2001")

    def test_daftar_sidik_jari_validasi(self):
        kasus = (
            ("7\n1\ntidakada\n5\n", "User tidak ditemukan.", "username tidak ada"),
            ("7\n1\nNaNas\n\n5\n", "ID perangkat tidak boleh kosong.", "PIN kosong"),
            ("7\n1\nNaNas\nabc\n5\n", "ID perangkat harus berupa angka.", "PIN bukan angka"),
            ("7\n1\nsiti\n1001\n5\n", "sudah dipakai akun", "PIN duplikat milik budi"),
        )
        for isi, pesan, label in kasus:
            with self.subTest(label=label):
                self.pulihkan_data()
                hasil = self.sesi_admin(isi)
                self.cek_exit(hasil)
                self.assert_teks(hasil, pesan)
                self.assert_log_tidak_ada(action="FINGER_ENROLL")
                self.assertEqual(
                    {u: d["finger_id"] for u, d in self.baca_users_hasil().items()},
                    {u: d["finger_id"] for u, d in self.fixture_users().items()},
                    msg="finger_id berubah padahal pendaftaran ditolak",
                )

    def test_daftar_sidik_jari_duplikat_antar_akun_baru(self):
        # daftarkan NaNas 2001 lalu coba pakai 2001 untuk siti -> ditolak, sebut NaNas
        hasil = self.sesi_admin("7\n1\nNaNas\n2001\n1\nsiti\n2001\n5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "sudah dipakai akun")
        self.assert_teks(hasil, "NaNas")
        users = self.baca_users_hasil()
        self.assertEqual(users["NaNas"]["finger_id"], "2001")
        self.assertEqual(users["siti"]["finger_id"], "1002")

    def test_hapus_pendaftaran_sidik_jari(self):
        hasil = self.sesi_admin("7\n1\nNaNas\n2001\n2\nNaNas\n5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Pendaftaran sidik jari akun 'NaNas' dihapus.")
        users = self.baca_users_hasil()
        self.assertEqual(users["NaNas"]["finger_id"], "")
        log_unenroll = self.assert_log_ada(username="admin", action="FINGER_UNENROLL")
        self.assertEqual(log_unenroll.get("detail"), "NaNas")

    def test_hapus_sidik_jari_yang_tidak_terdaftar(self):
        hasil = self.sesi_admin("7\n2\nadmin\n5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Akun tidak punya pendaftaran sidik jari.")
        self.assert_users_tetap()
        self.assert_log_tidak_ada(action="FINGER_UNENROLL")

    def test_tes_koneksi_mode_simulasi(self):
        hasil = self.sesi_admin("7\n4\n5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Mode simulasi: perangkat tidak dihubungi.")

    def test_menu_sidik_jari_pilihan_invalid(self):
        hasil = self.sesi_admin("7\n9\n5\n")
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Pilihan tidak valid!")
        self.assertGreaterEqual(self.hitung_teks(hasil, "=== KELOLA SIDIK JARI (X100C) ==="), 2,
                                msg=self.info(hasil))


# ---------------------------------------------------------------------------
# 4. Integrasi: login sidik jari (mode simulasi)
# ---------------------------------------------------------------------------

class TestLoginSidikJari(DasarTest):
    def test_login_budi_1001(self):
        hasil = self.jalankan_app(input_sidik_jari("1001") + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "--- LOGIN SIDIK JARI (X100C) ---")
        self.assert_teks(hasil, PROMPT_SIMULASI)
        self.assert_teks(hasil, "Sidik jari dikenali: budi.")
        self.assert_teks(hasil, "=== MENU PELANGGAN ===")
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_tidak_ada_teks(hasil, "=== MENU ADMIN / MERCHANT ===")

    def test_login_siti_1002(self):
        hasil = self.jalankan_app(input_sidik_jari("1002") + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Sidik jari dikenali: siti.")
        self.assert_teks(hasil, "=== MENU PELANGGAN ===")

    def test_login_andi_terkunci_ditolak(self):
        hasil = self.jalankan_app(input_sidik_jari("1003") + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(
            hasil, "Akun terblokir karena percobaan PIN salah berulang kali. Hubungi Admin."
        )
        self.assert_tidak_ada_teks(hasil, "Sidik jari dikenali:")
        self.assert_tidak_ada_teks(hasil, "=== MENU PELANGGAN ===")
        # data andi tetap terkunci
        self.assertTrue(self.baca_users_hasil()["andi"]["is_locked"])

    def test_login_pin_tidak_dikenal(self):
        hasil = self.jalankan_app(input_sidik_jari("9999") + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Sidik jari belum terdaftar. Hubungi admin.")
        self.assert_tidak_ada_teks(hasil, "=== MENU PELANGGAN ===")

    def test_login_input_kosong_kembali_menu(self):
        hasil = self.jalankan_app("3\n\n" + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "--- LOGIN SIDIK JARI (X100C) ---")
        self.assert_tidak_ada_teks(hasil, "=== MENU PELANGGAN ===")
        self.assertGreaterEqual(self.hitung_teks(hasil, "=== MENU UTAMA ==="), 2,
                                msg=self.info(hasil))
        self.assert_teks(hasil, "Terima kasih telah menggunakan PayGuard.")

    def test_login_sidik_jari_admin_ke_menu_admin(self):
        self.set_finger_id_kerja("admin", "2001")
        hasil = self.jalankan_app(
            input_sidik_jari("2001") + LOGOUT_ADMIN + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Sidik jari dikenali: admin.")
        self.assert_teks(hasil, "Login berhasil! Selamat datang, admin.")
        self.assert_teks(hasil, "=== MENU ADMIN / MERCHANT ===")
        self.assert_teks(hasil, "9. Isi Saldo Pelanggan")
        self.assert_teks(hasil, "10. Logout Admin")
        self.assert_teks(hasil, "Pilih menu (1-10):")
        self.assert_teks(hasil, "Logout berhasil.")
        self.assert_tidak_ada_teks(hasil, "=== MENU PELANGGAN ===")
        self.assert_tidak_ada_teks(hasil, "Masukan PIN E-Wallet")

    def test_login_sidik_jari_customer_tetap_menu_pelanggan(self):
        hasil = self.jalankan_app(
            input_sidik_jari("1001") + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Sidik jari dikenali: budi.")
        self.assert_teks(hasil, "=== MENU PELANGGAN ===")
        self.assert_teks(hasil, "1. Lihat Saldo")
        self.assert_tidak_ada_teks(hasil, "=== MENU ADMIN / MERCHANT ===")


# ---------------------------------------------------------------------------
# 5. Integrasi: checkout sidik jari (tanpa PIN)
# ---------------------------------------------------------------------------

class TestCheckoutSidikJari(DasarTest):

    def _input_checkout(self, pin_otorisasi, qty=2):
        pid, produk = self.produk_uji_checkout(min_stok=qty)
        return (
            input_sidik_jari("1001")            # login sidik jari budi
            + "2\n" + pid + "\n" + pid + "\n" + str(qty) + "\n"
            + "4\n"                             # checkout (risk dihitung app)
            + pin_otorisasi + "\n"              # tempel sidik jari
            + LOGOUT_CUSTOMER + KELUAR
        )



    def test_checkout_sidik_jari_sukses_tanpa_pin(self):
        pid, produk = self.produk_uji_checkout(min_stok=2)
        harga = float(produk["price"])
        qty = 2
        total = harga * qty
        saldo_harap = self.saldo_awal("budi") - total
        stok_harap = int(produk["stock"]) - qty
        hasil = self.jalankan_app(self._input_checkout("1001", qty=qty))
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Tempelkan sidik jari untuk mengotorisasi pembayaran...")
        self.assert_teks(hasil, "Pembayaran diotorisasi dengan sidik jari.")
        self.assert_teks(hasil, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.")
        self.assert_tidak_ada_teks(hasil, "Masukan PIN E-Wallet untuk konfirmasi pembayaran:")
        self.assert_tidak_ada_teks(hasil, "PIN Salah! Transaksi Dibatalkan.")

        users = self.baca_users_hasil()
        budi = users["budi"]
        self.assertEqual(budi["balance"], saldo_harap)
        self.assertEqual(len(budi["transactions"]), self.jumlah_trx_awal("budi") + 1)
        trx = budi["transactions"][-1]
        self.assertEqual(trx["total"], total)
        self.assertEqual(trx["items"][0]["id"], pid)
        self.assertEqual(trx["items"][0]["qty"], qty)
        self.assert_stok(pid, stok_harap)

        log_finger = self.assert_log_ada(username="budi", awalan_action="CHECKOUT_FINGER_RP_")
        self.assertEqual(log_finger.get("action"),
                         "CHECKOUT_FINGER_RP_" + str(int(round(total))))
        self.assertEqual(log_finger.get("detail"), trx["id"])
        self.assert_log_tidak_ada(username="budi", awalan_action="CHECKOUT_SUCCESS_RP_")

    def test_checkout_sidik_jari_gagal_menahan_keranjang(self):
        hasil = self.jalankan_app(self._input_checkout("1002"))  # sidik jari siti
        self.cek_exit(hasil)
        self._assert_hold_pertama(hasil)

    def test_checkout_sidik_jari_pin_tidak_dikenal_menahan_keranjang(self):
        hasil = self.jalankan_app(self._input_checkout("9999"))
        self.cek_exit(hasil)
        self._assert_hold_pertama(hasil)


    def test_checkout_jalur_pin_tetap_meminta_pin(self):
        # regresi: login PIN biasa tetap memakai PIN saat checkout
        pid, produk = self.produk_uji_checkout(min_stok=2)
        harga = float(produk["price"])
        total = harga * 2
        skor = self.skor_risiko_fixture("siti", total, produk["category"])
        konfirmasi = ""
        if skor > 3:
            konfirmasi = "SAYA YAKIN\n"
        elif skor > 0:
            konfirmasi = "y\n"
        hasil = self.jalankan_app(
            input_login("siti", "222222")
            + "2\n" + pid + "\n" + pid + "\n2\n4\n"
            + konfirmasi + "222222\n"
            + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Masukan PIN E-Wallet untuk konfirmasi pembayaran:")
        self.assert_teks(hasil, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.")
        self.assert_log_ada(username="siti",
                            action="CHECKOUT_SUCCESS_RP_" + str(int(round(total))))

    def sesi_customer_pin(self, username, pin, isi_menu):
        return self.jalankan_app(input_login(username, pin) + isi_menu + LOGOUT_CUSTOMER + KELUAR)


# ---------------------------------------------------------------------------
# 6. Integrasi: mode soap (mock perangkat) & error koneksi
# ---------------------------------------------------------------------------

class TestModeSoap(DasarTest):
    def test_soap_login_sukses_via_mock(self):
        saat = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        baris = [buat_baris_attlog("1001", saat)]
        with MockX100C(ambil_attlog=lambda: list(baris)) as mock:
            self.tulis_perangkat(mock.perangkat(batas_tunggu_detik=2))
            hasil = self.jalankan_app("3\n" + LOGOUT_CUSTOMER + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Menunggu sidik jari pada perangkat X100C...")
        self.assert_teks(hasil, "Sidik jari dikenali: budi.")
        self.assert_teks(hasil, "=== MENU PELANGGAN ===")
        # state event tersimpan di data SALINAN
        state = self.baca_state_hasil()
        self.assertIn(f"1001|{saat}|1", state["terproses"])
        self.assertTrue(str(self.data_dir_kerja).startswith(str(self.workdir)))

    def test_soap_event_tidak_bisa_replay(self):
        # mock SELALU mengembalikan event yang sama -> login kedua harus gagal
        saat = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        baris = [buat_baris_attlog("1001", saat)]
        with MockX100C(ambil_attlog=lambda: list(baris)) as mock:
            self.tulis_perangkat(mock.perangkat(batas_tunggu_detik=1))
            hasil = self.jalankan_app(
                "3\n"                       # login sidik jari #1 -> budi
                + LOGOUT_CUSTOMER
                + "3\n"                     # login sidik jari #2 -> event sudah dipakai
                + KELUAR
            )
        self.cek_exit(hasil)
        self.assertEqual(self.hitung_teks(hasil, "Sidik jari dikenali: budi."), 1,
                         msg="event yang sama dipakai dua kali (replay)" + self.info(hasil))
        self.assertEqual(self.hitung_teks(hasil, "=== MENU PELANGGAN ==="), 1)
        self.assert_teks(hasil, "Tidak ada sidik jari terbaca.")
        self.assertGreaterEqual(len(mock.catatan), 2, msg="polling kedua tidak terjadi")

    def test_soap_host_mati_pesan_error_exit_0(self):
        self.tulis_perangkat({
            "mode": "soap", "host": "127.0.0.1", "port": port_tertutup(),
            "com_key": 0, "timeout": 1, "jendela_detik": 30, "batas_tunggu_detik": 1,
        })
        hasil = self.jalankan_app("3\n" + KELUAR)
        self.cek_exit(hasil)
        self.assert_teks(hasil, "Menunggu sidik jari pada perangkat X100C...")
        self.assert_teks(hasil, PESAN_KONEKSI_GAGAL)
        self.assert_tidak_ada_teks(hasil, "Traceback")
        self.assertGreaterEqual(self.hitung_teks(hasil, "=== MENU UTAMA ==="), 2)
        self.assert_teks(hasil, "Terima kasih telah menggunakan PayGuard.")


# ---------------------------------------------------------------------------
# 7. Integritas fixtures & data asli
# ---------------------------------------------------------------------------

class TestIntegritasData(DasarTest):
    def test_fixtures_salinan_byte_identik(self):
        # users/products/logs: DATA -> wajib byte-identik
        for nama in FIXTURE_IDENTIK_FILES:
            with self.subTest(nama=nama):
                self.assertTrue((DATA_DIR / nama).is_file(), msg=f"{nama} tidak ada di data asli")
                self.assertTrue((FIXTURES_DIR / nama).is_file(), msg=f"fixtures/{nama} tidak ada")
                self.assert_fixtures_identik(nama)

    def test_perangkat_adalah_config_deployment_bukan_fixture_data(self):
        """perangkat.json = konfigurasi deployment: fixture simulasi, data asli soap.

        Tidak diwajibkan byte-identik, tetapi fixture WAJIB mode simulasi agar test
        tidak pernah menghubungi perangkat X100C asli (192.168.1.201).
        """
        fixture_cfg = muat_fixture("perangkat.json")
        self.assertEqual(
            fixture_cfg.get("mode"), MODE_PERANGKAT_TEST,
            msg="fixtures/perangkat.json wajib mode 'simulasi' (hermetis); "
                f"dapat {fixture_cfg.get('mode')!r}",
        )
        for kunci in ("host", "port", "com_key", "timeout",
                      "jendela_detik", "batas_tunggu_detik"):
            self.assertIn(kunci, fixture_cfg)

        data_cfg = baca_json_file(DATA_DIR / "perangkat.json")
        self.assertIn(data_cfg.get("mode"), ("simulasi", "soap"),
                      msg="data/perangkat.json deployment boleh simulasi/soap")
        # folder kerja test memakai SALINAN fixture => wajib simulasi
        work_cfg = baca_json_file(self.data_dir_kerja / "perangkat.json")
        self.assertEqual(work_cfg.get("mode"), MODE_PERANGKAT_TEST,
                         msg="config folder kerja test harus simulasi (tidak menyentuh device asli)")
        # .env (config deployment perangkat nyata) TIDAK ikut ke folder kerja test
        self.assertFalse((self.workdir / ".env").exists(),
                         msg=".env deployment tidak boleh ikut ke folder kerja test")

    def test_fixtures_struktur_seed_sidik_jari(self):
        users = muat_fixture("users.json")
        # akun seed wajib ada (jumlah bisa bertambah dari pemakaian nyata)
        for wajib in ("admin", "budi", "siti", "andi", "NaNas", "Prabu"):
            self.assertIn(wajib, users)
        self.assertEqual(users["budi"]["finger_id"], "1001")
        self.assertEqual(users["siti"]["finger_id"], "1002")
        self.assertEqual(users["andi"]["finger_id"], "1003")
        self.assertEqual(users["admin"]["finger_id"], "")
        self.assertEqual(users["NaNas"]["finger_id"], "")
        self.assertEqual(users["Prabu"]["finger_id"], "11733")
        self.assertTrue(users["andi"]["is_locked"])
        self.assertEqual(users["budi"]["failed_attempts"], 1)
        self.assertIsInstance(muat_fixture("keranjang.json"), list)
        perangkat = muat_fixture("perangkat.json")
        self.assertEqual(perangkat["mode"], "simulasi")
        for kunci in ("host", "port", "com_key", "timeout", "jendela_detik", "batas_tunggu_detik"):
            self.assertIn(kunci, perangkat)

    def test_state_sidik_jari_runtime_tidak_ikut_fixtures(self):
        # finger_state.json = state runtime aplikasi; tidak boleh ada di fixtures.
        self.assertFalse((FIXTURES_DIR / "finger_state.json").exists(),
                         msg="finger_state.json tidak boleh ada di fixtures")
        # data asli BOLEH punya state runtime karena aplikasi sudah dipakai nyata;
        # kalau ada, isinya harus JSON valid (bukan artefak test).
        jalur_state = DATA_DIR / "finger_state.json"
        if jalur_state.exists():
            state = json.loads(jalur_state.read_text(encoding="utf-8"))
            self.assertIsInstance(state, dict)
            self.assertIsInstance(state.get("terproses"), list)


# ---------------------------------------------------------------------------
# Test TERAKHIR modul: data asli tidak berubah + _tmp bersih
# ---------------------------------------------------------------------------

class TestZZIntegritasAkhir(unittest.TestCase):
    maxDiff = None

    def test_hash_data_asli_sama_sebelum_dan_sesudah_suite(self):
        for nama in DATA_FILES:
            with self.subTest(nama=nama):
                jalur = DATA_DIR / nama
                self.assertTrue(jalur.is_file(), msg=f"{jalur} hilang")
                self.assertEqual(
                    hash_file(jalur), _HASH_DATA_ASLI[nama],
                    msg=f"SHA256 payguard/data/{nama} berubah selama suite!",
                )

    def test_tmp_bersih_setelah_suite(self):
        if BASE_TMP.exists():
            sisa = sorted(str(p) for p in BASE_TMP.iterdir())
            self.assertEqual(sisa, [], msg=f"tests/_tmp tidak bersih: {sisa}")


def tearDownModule():
    if BASE_TMP.exists():
        hapus_pohon(BASE_TMP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
