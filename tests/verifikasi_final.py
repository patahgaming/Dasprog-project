"""Verifikasi final PayGuard CLI — suite unittest + integritas data + spot-check.

Skrip manual QA (BUKAN unittest, tidak ditemukan oleh `unittest discover`).
Tidak mengubah file aplikasi (``payguard/*.py``) maupun data asli
(``payguard/data/*.json``); semua uji aplikasi dijalankan pada SALINAN di
``tests/_tmp/spot_<uuid>`` (tanpa ``tempfile.mkdtemp()`` karena sandbox Windows).

Tahapan:

1. Snapshot SHA256 ``payguard/data/*.json`` + manifest seluruh file di
   ``payguard`` (di luar ``tests/`` dan ``__pycache__``) SEBELUM suite.
2. Pastikan fixtures DATA (users/products/logs) masih byte-identik dengan data asli.
   ``perangkat.json`` adalah konfigurasi deployment: fixture-nya selalu mode simulasi
   (hermetis) sedangkan data asli bisa mode soap untuk perangkat X100C nyata, sehingga
   dikecualikan dari uji byte-identik (hash config asli tetap dipantau).
3. Jalankan ``python -m unittest discover -s tests -v`` dari folder ``payguard``.
4. Catat SHA256 data SESUDAH suite + bandingkan dengan snapshot.
5. Spot-check independen TUI pada salinan data (14 skenario):
   - admin create/update/delete produk lalu customer melihat katalog kembali;
   - budi top up 100.000 lalu checkout Beras 5kg x1 (risk AMAN);
   - siti beli Cokelat Premium x3, Risk Shield PERINGATAN SEDANG dijawab `n`;
   - siti beli Cokelat Premium x3, dijawab `y` + PIN sampai sukses;
   - lockout siti 3x PIN salah -> admin unlock -> siti login lagi;
   - register user baru `rina` -> login -> top up -> beli -> logout;
   - admin kelola sidik jari X100C (enroll/lihat/hapus/validasi mapping);
   - login sidik jari budi 1001 -> checkout tanpa PIN -> data & log
     `CHECKOUT_FINGER_...` benar;
   - protokol SOAP X100C (root elemen = perintah) + mode soap host mati
     menampilkan pesan error dan tetap exit 0;
   - mock X100C SOAP: login via GetAttLog + checkout lewat tap sidik jari kedua;
   - replay event & event kadaluwarsa ditolak (tidak ada login ganda);
   - tap sidik jari milik user lain saat checkout -> **hold keranjang** (stok
     turun, keranjang.json +1, saldo/transaksi tetap, log HOLD_CART);
   - resume hold lewat menu 4 (`y`) + tap sukses -> saldo/transaksi/log
     `CHECKOUT_FINGER_...`, hold hilang, stok tidak dobel;
   - admin lihat daftar hold + batalkan (`y`) -> stok kembali, log HOLD_CANCEL.
6. Verifikasi akhir: data asli identik, manifest app/data tidak berubah,
   fixtures sinkron, ``tests/_tmp`` bersih.
7. Cetak kesimpulan LULUS/GAGAL (exit code 0 hanya jika semua lolos).

Cara pakai dari folder ``payguard``::

    python tests/verifikasi_final.py
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
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]   # .../payguard
TESTS_DIR = Path(__file__).resolve().parent          # .../payguard/tests
DATA_DIR = PROJECT_DIR / "data"
FIXTURES_DIR = TESTS_DIR / "fixtures"
BASE_TMP = TESTS_DIR / "_tmp"

DATA_FILES = ("users.json", "products.json", "logs.json", "keranjang.json", "perangkat.json")

# users/products/logs = DATA -> wajib byte-identik fixtures <-> data asli.
# perangkat.json = KONFIGURASI DEPLOYMENT: data asli bisa mode "soap" untuk perangkat
# X100C nyata; fixtures selalu mode "simulasi" agar verifikasi hermetis. Karena itu
# perangkat.json dikecualikan dari uji byte-identik (hash-nya tetap dipantau).
FIXTURE_IDENTIK_FILES = ("users.json", "products.json", "logs.json", "keranjang.json")
MODE_PERANGKAT_TEST = "simulasi"

APP_TIMEOUT = 60

WARNING_SALDO = "Transaksi ini menghabiskan lebih dari 70% sisa saldomu."
WARNING_LIMIT = "Pembelian ini akan melampaui limit anggaran harianmu!"
WARNING_TERSIER = "Kamu membeli barang tersier saat saldo mendekati batas minimum."

PESAN_KONEKSI_GAGAL = (
    "Perangkat X100C tidak terhubung. Periksa kabel/jaringan dan konfigurasi."
)

DRIVER_PROTOKOL = r'''
import json
import sys

sys.path.insert(0, sys.argv[1])

import fingerprint

print(json.dumps({
    "xml_attlog": fingerprint.buat_xml("GetAttLog", {"PIN": "All"}, 0),
    "xml_userinfo": fingerprint.buat_xml("GetUserInfo", {"PIN": "1001"}, 0),
}))
'''


# ---------------------------------------------------------------------------
# Helper murni
# ---------------------------------------------------------------------------

def sha256_file(jalur):
    return hashlib.sha256(Path(jalur).read_bytes()).hexdigest()


def baca_json(jalur):
    return json.loads(Path(jalur).read_text(encoding="utf-8"))


def normalisasi(teks):
    return " ".join(str(teks).lower().split())


def teks_ada(keluaran, potongan):
    return normalisasi(potongan) in normalisasi(keluaran)


def rupiah(angka):
    angka = int(round(float(angka)))
    if angka < 0:
        return "Rp-" + f"{abs(angka):,}".replace(",", ".")
    return "Rp" + f"{angka:,}".replace(",", ".")


def cek(bukti, kondisi, label_ok, label_gagal=None):
    """Catat hasil satu cek ke daftar bukti; return bool kondisi."""
    if kondisi:
        bukti.append("OK    " + label_ok)
        return True
    bukti.append("GAGAL " + (label_gagal or label_ok))
    return False


def manifest_payguard():
    """Manifest file app/data di payguard (di luar tests/ dan __pycache__).

    ``data/finger_state.json`` = runtime aplikasi (dibuat setelah login sidik jari
    di mesin nyata), sehingga tidak dihitung sebagai perubahan kode/data.
    """
    hasil = {}
    for jalur in sorted(PROJECT_DIR.rglob("*")):
        if not jalur.is_file():
            continue
        if jalur == TESTS_DIR or TESTS_DIR in jalur.parents:
            continue
        if "__pycache__" in jalur.parts:
            continue
        if jalur == DATA_DIR / "finger_state.json":
            continue
        hasil[str(jalur.relative_to(PROJECT_DIR))] = sha256_file(jalur)
    return hasil


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


def env_anak():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def port_tertutup():
    """Port 127.0.0.1 yang (hampir pasti) tidak ada listener-nya."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soket:
        soket.bind(("127.0.0.1", 0))
        return soket.getsockname()[1]


def jalankan_driver_spot(workdir, driver, tambahan=()):
    return subprocess.run(
        [sys.executable, "-c", driver, str(workdir)] + [str(a) for a in tambahan],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=APP_TIMEOUT,
        env=env_anak(),
    )


# ---------------------------------------------------------------------------
# Spot-check: folder kerja salinan + runner TUI
# ---------------------------------------------------------------------------

def buat_workdir_spot():
    BASE_TMP.mkdir(parents=True, exist_ok=True)
    workdir = BASE_TMP / ("spot_" + uuid.uuid4().hex)
    workdir.mkdir()
    folder_data = workdir / "data"
    folder_data.mkdir()
    for nama in DATA_FILES:
        shutil.copyfile(FIXTURES_DIR / nama, folder_data / nama)
    for berkas in sorted(PROJECT_DIR.glob("*.py")):
        shutil.copyfile(berkas, workdir / berkas.name)
    return workdir


def jalankan_spot(workdir, teks_input):
    for percobaan in range(3):
        hasil = subprocess.run(
            [sys.executable, str(workdir / "main.py")],
            cwd=str(workdir),
            input=teks_input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=APP_TIMEOUT,
            env=env_anak(),
        )
        # Windows: os.replace() kadang PermissionError sesaat (bukan bug app)
        if (hasil.returncode == 1
                and "PermissionError" in (hasil.stderr or "")
                and ("Access is denied" in (hasil.stderr or "")
                     or "WinError 5" in (hasil.stderr or ""))):
            if percobaan == 2:
                return hasil
            time.sleep(0.3 * (percobaan + 1))
            continue
        return hasil
    return hasil


def baca_data(workdir, nama):
    return baca_json(workdir / "data" / nama)


def fixture(nama):
    return baca_json(FIXTURES_DIR / nama)


def baris_attlog(pin, saat):
    """Satu Row GetAttLog: PIN, DateTime, Verified, Status, WorkCode."""
    if isinstance(saat, datetime):
        saat = saat.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "PIN": str(pin),
        "DateTime": str(saat),
        "Verified": "1",
        "Status": "1",
        "WorkCode": "0",
    }


def tulis_perangkat(workdir, config):
    (workdir / "data" / "perangkat.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class MockX100C:
    """Mock webserver X100C minimal (mode soap) untuk spot-check independen.

    Kontrak §4.2: root elemen = nama perintah; request dengan wrapper <Command>
    ditolak (HTTP 400). Response root <GetAttLogResponse>.
    """

    def __init__(self, ambil_attlog=None):
        self.ambil_attlog = ambil_attlog or (lambda: [])
        self.catatan = []
        self.status = []
        self.galat = []
        mock = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
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
                    mock.catatan.append(isi_teks)
                    cocok = re.search(r"<\s*([A-Za-z][A-Za-z0-9_.-]*)", isi_teks)
                    command = cocok.group(1) if cocok else None
                    if command != "GetAttLog":
                        mock.status.append(400)
                        alasan = (f"command tidak diizinkan: {command!r}; "
                                  "root elemen harus GetAttLog (kontrak §4.2)")
                        awak = alasan.encode("utf-8")
                        self.request.sendall(
                            b"HTTP/1.0 400 Bad Request\r\nContent-Type: text/plain\r\n"
                            b"Content-Length: " + str(len(awak)).encode("ascii")
                            + b"\r\n\r\n" + awak
                        )
                        return
                    bagian = []
                    for baris in mock.ambil_attlog():
                        isi_row = "".join(
                            f"<{kunci}>{nilai}</{kunci}>" for kunci, nilai in baris.items()
                        )
                        bagian.append("<Row>" + isi_row + "</Row>")
                    xml = ('<?xml version="1.0" encoding="UTF-8"?><GetAttLogResponse>'
                           + "".join(bagian) + "</GetAttLogResponse>")
                    awak = xml.encode("utf-8")
                    mock.status.append(200)
                    self.request.sendall(
                        b"HTTP/1.0 200 OK\r\nContent-Type: text/xml; charset=utf-8\r\n"
                        b"Content-Length: " + str(len(awak)).encode("ascii")
                        + b"\r\n\r\n" + awak
                    )
                except Exception as galat:  # noqa: BLE001 - dicatat untuk diagnosa
                    mock.galat.append(repr(galat))

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, tipe, nilai, jejak):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        return False

    def perangkat(self, **tambahan):
        config = {
            "mode": "soap",
            "host": "127.0.0.1",
            "port": self.port,
            "com_key": 0,
            "timeout": 2,
            "jendela_detik": 30,
            "batas_tunggu_detik": 2,
        }
        config.update(tambahan)
        return config


# ---------------------------------------------------------------------------
# Spot-check 1: siklus CRUD admin lalu katalog customer kembali seperti semula
# ---------------------------------------------------------------------------

def spot_admin_crud():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        seed_products = fixture("products.json")
        # run 1: login admin -> create produk -> update stok -> logout
        h = jalankan_spot(
            workdir,
            "1\nadmin\n123456\n"
            "1\nProduk Uji QA\n12345\n7\nWants\n"   # Create
            "3\nP010\n2\n3\n"                        # Update stok P010 -> 3
            "9\n4\n",
        )
        ok = cek(bukti, h.returncode == 0, "run1 (create+update) exit 0",
                 f"run1 exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "berhasil ditambahkan"),
                 "run1: pesan produk ditambahkan tampil") and ok
        ok = cek(bukti, teks_ada(h.stdout, "berhasil diupdate"),
                 "run1: pesan update tampil") and ok
        products = baca_data(workdir, "products.json")
        p010 = products.get("P010") or {}
        ok = cek(
            bukti,
            p010.get("name") == "Produk Uji QA"
            and p010.get("price") == 12345.0
            and p010.get("stock") == 3,
            "run1: P010 ada dengan harga 12345 & stok 3 (setelah update)",
            f"run1: P010 tidak sesuai: {p010!r}",
        ) and ok

        # run 2: login admin -> delete P010 -> logout; katalog harus kembali seed
        h = jalankan_spot(workdir, "1\nadmin\n123456\n4\nP010\ny\n9\n4\n")
        ok = cek(bukti, h.returncode == 0, "run2 (delete) exit 0",
                 f"run2 exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "berhasil dihapus"),
                 "run2: pesan delete tampil") and ok
        products = baca_data(workdir, "products.json")
        ok = cek(bukti, products == seed_products,
                 "run2: products.json kembali sama dengan seed", "run2: products.json beda dari seed")

        # run 3: login customer -> urutkan katalog (tampil semua) -> logout
        h = jalankan_spot(workdir, "1\nbudi\n111111\n3\n3\n6\n4\n")
        ok = cek(bukti, h.returncode == 0, "run3 (katalog customer) exit 0",
                 f"run3 exit {h.returncode}") and ok
        semua_nama = [item["name"] for item in seed_products.values()]
        ok = cek(bukti, all(teks_ada(h.stdout, nama) for nama in semua_nama),
                 "run3: seluruh 9 produk seed tampil di katalog",
                 "run3: ada produk seed yang tidak tampil") and ok
        ok = cek(bukti, not teks_ada(h.stdout, "Produk Uji QA"),
                 "run3: produk uji buatan admin sudah tidak tampil",
                 "run3: produk uji masih tampil setelah dihapus") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 2: budi top up 100.000 lalu checkout Beras 5kg x1 (risk AMAN)
# ---------------------------------------------------------------------------

def spot_budi_topup_checkout():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        logs_awal = fixture("logs.json")
        saldo_awal = users_awal["budi"]["balance"]
        harga = products_awal["P001"]["price"]
        stok_awal = products_awal["P001"]["stock"]
        saldo_setelah_topup = saldo_awal + 100000
        saldo_harap = saldo_setelah_topup - harga

        h = jalankan_spot(
            workdir,
            "1\nbudi\n111111\n"
            "1\n100000\n"                 # top up 100.000 -> 600.000
            "2\nberas\nP001\n1\n"         # tambah Beras 5kg x1
            "4\n111111\n"                 # checkout (risk AMAN) + PIN
            "6\n4\n",
        )
        ok = cek(bukti, h.returncode == 0, "exit 0", f"exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Top up berhasil! Saldo baru: " + rupiah(saldo_setelah_topup)),
                 f"top up -> saldo {rupiah(saldo_setelah_topup)}",
                 "pesan top up / saldo baru salah") and ok
        ok = cek(bukti, teks_ada(h.stdout, "[STATUS: AMAN]"),
                 "Risk Shield AMAN (tanpa konfirmasi)",
                 "Risk Shield bukan AMAN") and ok
        ok = cek(bukti, teks_ada(h.stdout, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan."),
                 "checkout berhasil & resi terbit", "checkout gagal") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Sisa Saldo: " + rupiah(saldo_harap)),
                 f"resi sisa saldo {rupiah(saldo_harap)}",
                 f"resi sisa saldo bukan {rupiah(saldo_harap)}") and ok

        users = baca_data(workdir, "users.json")
        budi = users["budi"]
        ok = cek(bukti, budi["balance"] == saldo_harap,
                 f"users.json saldo budi = {rupiah(saldo_harap)} (dapat {rupiah(budi['balance'])})") and ok
        transaksi = budi["transactions"]
        ok = cek(bukti, len(transaksi) == len(users_awal["budi"]["transactions"]) + 1,
                 "users.json: transaksi bertambah 1") and ok
        trx = transaksi[-1]
        ok = cek(
            bukti,
            trx["total"] == harga and trx["risk_score"] == 0
            and trx["items"][0]["id"] == "P001" and trx["items"][0]["qty"] == 1,
            f"transaksi tercatat total={rupiah(harga)}, risk=0, P001 x1",
            f"transaksi tidak sesuai: {trx!r}",
        ) and ok
        products = baca_data(workdir, "products.json")
        ok = cek(bukti, products["P001"]["stock"] == stok_awal - 1,
                 f"stok P001 = {stok_awal - 1} (semula {stok_awal})") and ok

        logs = baca_data(workdir, "logs.json")
        aksi = [catatan["action"] for catatan in logs[len(logs_awal):]]
        ok = cek(bukti, "TOPUP" in aksi,
                 "logs.json: TOPUP tercatat", f"TOPUP tidak ada di log baru: {aksi}") and ok
        ok = cek(bukti, "CHECKOUT_SUCCESS_RP_" + str(int(round(harga))) in aksi,
                 f"logs.json: CHECKOUT_SUCCESS_RP_{int(round(harga))} tercatat",
                 f"log checkout tidak ada: {aksi}") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 3: risk PERINGATAN SEDANG dijawab `n` -> tidak ada perubahan
# ---------------------------------------------------------------------------

def spot_risk_sedang_batal():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        logs_awal = fixture("logs.json")

        # siti: Cokelat Premium 25.000 x3 = 75.000; sisa 75.000 < 100.000 (Wants)
        # -> indikator 3 (+2) -> skor 2 -> PERINGATAN SEDANG
        h = jalankan_spot(workdir, "1\nsiti\n222222\n2\ncokelat\nP006\n3\n4\nn\n6\n4\n")
        ok = cek(bukti, h.returncode == 0, "exit 0", f"exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "[STATUS: PERINGATAN SEDANG]"),
                 "Risk Shield PERINGATAN SEDANG", "status risk bukan PERINGATAN SEDANG") and ok
        ok = cek(bukti, WARNING_TERSIER in h.stdout,
                 "warning indikator 3 tampil", "warning indikator 3 tidak tampil") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Transaksi dibatalkan oleh pengguna/Risk Shield."),
                 "pesan batal tampil", "pesan batal tidak tampil") and ok

        ok = cek(bukti, baca_data(workdir, "users.json") == users_awal,
                 "users.json tidak berubah (saldo/transaksi tetap)",
                 "users.json BERUBAH padahal dibatalkan") and ok
        ok = cek(bukti, baca_data(workdir, "products.json") == products_awal,
                 "products.json tidak berubah (stok tetap)", "products.json BERUBAH") and ok
        logs = baca_data(workdir, "logs.json")
        log_baru = logs[len(logs_awal):]
        aksi = [catatan["action"] for catatan in log_baru]
        ok = cek(bukti, aksi == ["LOGIN_SUCCESS", "LOGOUT"],
                 "logs.json: hanya LOGIN_SUCCESS + LOGOUT (tidak ada checkout)",
                 f"log baru tidak sesuai: {aksi}") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 4: risk PERINGATAN SEDANG dijawab `y` + PIN -> sukses
# ---------------------------------------------------------------------------

def spot_risk_sedang_lanjut():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        logs_awal = fixture("logs.json")
        harga = products_awal["P006"]["price"]
        total = harga * 3
        saldo_harap = users_awal["siti"]["balance"] - total
        stok_harap = products_awal["P006"]["stock"] - 3

        h = jalankan_spot(workdir, "1\nsiti\n222222\n2\ncokelat\nP006\n3\n4\ny\n222222\n6\n4\n")
        ok = cek(bukti, h.returncode == 0, "exit 0", f"exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "[STATUS: PERINGATAN SEDANG]"),
                 "Risk Shield PERINGATAN SEDANG") and ok
        ok = cek(bukti, teks_ada(h.stdout, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan."),
                 "checkout lanjut & berhasil") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Skor Risiko: 2"), "skor risiko tersimpan 2") and ok

        siti = baca_data(workdir, "users.json")["siti"]
        ok = cek(bukti, siti["balance"] == saldo_harap,
                 f"saldo siti = {rupiah(saldo_harap)}", f"saldo siti salah: {siti['balance']}") and ok
        ok = cek(bukti, len(siti["transactions"]) == 1
                 and siti["transactions"][0]["total"] == total
                 and siti["transactions"][0]["risk_score"] == 2,
                 f"transaksi tercatat total={rupiah(total)}, risk=2") and ok
        ok = cek(bukti, baca_data(workdir, "products.json")["P006"]["stock"] == stok_harap,
                 f"stok P006 = {stok_harap}") and ok
        logs = baca_data(workdir, "logs.json")
        aksi = [catatan["action"] for catatan in logs[len(logs_awal):]]
        ok = cek(bukti, "CHECKOUT_SUCCESS_RP_" + str(int(round(total))) in aksi,
                 f"logs.json: CHECKOUT_SUCCESS_RP_{int(round(total))}") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 5: lockout 3x -> admin unlock -> siti login lagi
# ---------------------------------------------------------------------------

def spot_lockout_unlock():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        logs_awal = fixture("logs.json")
        # run 1: siti 3x PIN salah -> terkunci
        h = jalankan_spot(workdir, "1\nsiti\n000000\n" * 3 + "4\n")
        ok = cek(bukti, h.returncode == 0, "run1 exit 0", f"run1 exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "AKUN DIKUNCI DEMI KEAMANAN."),
                 "run1: pesan akun dikunci tampil", "run1: pesan lockout tidak tampil") and ok
        siti = baca_data(workdir, "users.json")["siti"]
        ok = cek(bukti, siti["is_locked"] is True and siti["failed_attempts"] == 3,
                 "run1: siti is_locked=true, failed_attempts=3",
                 f"run1: status siti salah: {siti!r}") and ok
        logs = baca_data(workdir, "logs.json")
        aksi = [catatan["action"] for catatan in logs[len(logs_awal):]]
        ok = cek(bukti, "ACCOUNT_LOCKED_BRUTEFORCE" in aksi,
                 "run1: log ACCOUNT_LOCKED_BRUTEFORCE tercatat") and ok

        # run 2: admin membuka blokir siti
        h = jalankan_spot(workdir, "1\nadmin\n123456\n6\nsiti\n9\n4\n")
        ok = cek(bukti, h.returncode == 0, "run2 exit 0", f"run2 exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "berhasil dibuka blokirnya"),
                 "run2: pesan unlock tampil") and ok
        siti = baca_data(workdir, "users.json")["siti"]
        ok = cek(bukti, siti["is_locked"] is False and siti["failed_attempts"] == 0,
                 "run2: siti is_locked=false, failed_attempts=0",
                 f"run2: status siti salah: {siti!r}") and ok
        logs = baca_data(workdir, "logs.json")
        aksi = [catatan["action"] for catatan in logs[len(logs_awal):]]
        ok = cek(bukti, "UNLOCK_ACCOUNT" in aksi, "run2: log UNLOCK_ACCOUNT tercatat") and ok

        # run 3: siti bisa login lagi
        h = jalankan_spot(workdir, "1\nsiti\n222222\n6\n4\n")
        ok = cek(bukti, h.returncode == 0, "run3 exit 0", f"run3 exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Login berhasil! Selamat datang, siti."),
                 "run3: siti login sukses setelah unlock") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 6: register -> login -> top up -> beli -> logout (exit 0)
# ---------------------------------------------------------------------------

def spot_register_baru():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        products_awal = fixture("products.json")
        harga = products_awal["P005"]["price"]
        stok_harap = products_awal["P005"]["stock"] - 2
        saldo_harap = 50000.0 - harga * 2

        h = jalankan_spot(
            workdir,
            "2\nrina\n999999\n"            # register
            "1\nrina\n999999\n"            # login
            "1\n50000\n"                   # top up 50.000
            "2\nkopi\nP005\n2\n"           # beli Kopi Sachet x2 (risk skor 2)
            "4\ny\n999999\n"               # risk PERINGATAN SEDANG -> y + PIN
            "6\n4\n",
        )
        ok = cek(bukti, h.returncode == 0, "exit 0", f"exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Registrasi Berhasil!"),
                 "register rina berhasil", "register rina gagal") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Login berhasil! Selamat datang, rina."),
                 "login rina berhasil") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Top up berhasil! Saldo baru: " + rupiah(50000)),
                 "top up 50.000 berhasil", "top up rina gagal") and ok
        ok = cek(bukti, teks_ada(h.stdout, "[STATUS: PERINGATAN SEDANG]"),
                 "Risk Shield PERINGATAN SEDANG muncul (skor 2)") and ok
        ok = cek(bukti, teks_ada(h.stdout, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan."),
                 "checkout rina berhasil") and ok

        users = baca_data(workdir, "users.json")
        ok = cek(bukti, "rina" in users, "users.json: rina terdaftar") and ok
        rina = users.get("rina") or {}
        ok = cek(bukti, rina.get("balance") == saldo_harap,
                 f"rina saldo = {rupiah(saldo_harap)} (dapat {rupiah(rina.get('balance', 0))})") and ok
        transaksi = rina.get("transactions", [])
        ok = cek(bukti, len(transaksi) == 1
                 and transaksi[0]["total"] == harga * 2
                 and transaksi[0]["risk_score"] == 2,
                 f"rina transaksi tercatat total={rupiah(harga * 2)}, risk=2") and ok
        ok = cek(bukti, baca_data(workdir, "products.json")["P005"]["stock"] == stok_harap,
                 f"stok P005 = {stok_harap}") and ok
        logs = baca_data(workdir, "logs.json")
        aksi = [catatan["action"] for catatan in logs
                if catatan.get("username") == "rina"]
        for aksi_harap in ("REGISTER", "LOGIN_SUCCESS", "TOPUP",
                           "CHECKOUT_SUCCESS_RP_" + str(int(round(harga * 2))), "LOGOUT"):
            ok = cek(bukti, aksi_harap in aksi,
                     f"logs.json: {aksi_harap} tercatat untuk rina",
                     f"logs.json: {aksi_harap} tidak ada untuk rina; aksi={aksi}") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 7: admin kelola sidik jari X100C (mode simulasi)
# ---------------------------------------------------------------------------

def spot_admin_sidik_jari():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        # data-driven: pilih customer yang BELUM punya finger_id + PIN unik baru
        target = next((nama for nama, user in users_awal.items()
                       if user.get("role") == "customer"
                       and str(user.get("finger_id", "")) == ""), None)
        if target is None:
            return True, ["SKIP: tidak ada customer tanpa finger_id di data live"]
        dipakai = {str(user.get("finger_id", "")) for user in users_awal.values()}
        pin_baru = 2001
        while str(pin_baru) in dipakai:
            pin_baru += 1
        pemilik_pin = {str(user.get("finger_id", "")): nama
                       for nama, user in users_awal.items()
                       if str(user.get("finger_id", "")) != ""}
        pemilik_duplikat = pemilik_pin.get("1001")
        isi_validasi_duplikat = ""
        if pemilik_duplikat:
            isi_validasi_duplikat = "1\n" + target + "\n1001\n"
        isi = (
            "1\nadmin\n123456\n"
            "7\n1\n" + target + "\n" + str(pin_baru) + "\n"   # enroll
            "3\n"                                              # lihat daftar
            "2\n" + target + "\n"                              # hapus
            "1\ntidakada\n"                                    # username tidak ada
            "1\n" + target + "\n\n"                            # PIN kosong
            "1\n" + target + "\nabc\n"                         # PIN bukan angka
            + isi_validasi_duplikat                            # PIN duplikat
            + "5\n9\n4\n"                                      # kembali, logout, keluar
        )
        h = jalankan_spot(workdir, isi)
        ok = cek(bukti, h.returncode == 0, "exit 0", f"exit {h.returncode}") and ok
        ok = cek(
            bukti,
            teks_ada(h.stdout, "Sidik jari akun '" + target
                     + "' terdaftar dengan ID perangkat " + str(pin_baru) + "."),
            f"enroll {target} -> PIN {pin_baru} berhasil",
            "pesan enroll tidak muncul",
        ) and ok
        ok = cek(bukti, teks_ada(h.stdout, target + " -> PIN " + str(pin_baru)),
                 f"daftar sidik jari menampilkan {target} -> PIN {pin_baru}") and ok
        ok = cek(bukti, teks_ada(h.stdout,
                 "Pendaftaran sidik jari akun '" + target + "' dihapus."),
                 f"hapus pendaftaran {target} berhasil") and ok
        ok = cek(bukti, teks_ada(h.stdout, "User tidak ditemukan."),
                 "validasi: username tidak ada ditolak") and ok
        ok = cek(bukti, teks_ada(h.stdout, "ID perangkat tidak boleh kosong."),
                 "validasi: PIN kosong ditolak") and ok
        ok = cek(bukti, teks_ada(h.stdout, "ID perangkat harus berupa angka."),
                 "validasi: PIN bukan angka ditolak") and ok
        if pemilik_duplikat:
            ok = cek(bukti, teks_ada(h.stdout, "sudah dipakai akun '" + pemilik_duplikat + "'."),
                     f"validasi: PIN duplikat ditolak & menyebut pemiliknya ({pemilik_duplikat})",
                     "validasi: pesan PIN duplikat tidak sesuai") and ok

        users = baca_data(workdir, "users.json")
        ok = cek(bukti, users[target]["finger_id"] == "",
                 f"finger_id {target} kosong kembali setelah dihapus") and ok
        ok = cek(bukti, users == users_awal,
                 "users.json kembali identik seed setelah enroll+hapus") and ok
        ok = cek(bukti, baca_data(workdir, "products.json") == products_awal,
                 "products.json tidak berubah") and ok
        aksi = [catatan.get("action") for catatan in baca_data(workdir, "logs.json")]
        ok = cek(bukti, "FINGER_ENROLL" in aksi, "log FINGER_ENROLL tercatat") and ok
        ok = cek(bukti, "FINGER_UNENROLL" in aksi, "log FINGER_UNENROLL tercatat") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 8: login sidik jari budi 1001 + checkout tanpa PIN
# ---------------------------------------------------------------------------

def spot_checkout_sidik_jari():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        logs_awal = fixture("logs.json")
        harga = products_awal["P005"]["price"]
        qty = 2
        total = harga * qty
        saldo_harap = users_awal["budi"]["balance"] - total
        stok_harap = products_awal["P005"]["stock"] - qty

        h = jalankan_spot(
            workdir,
            "3\n1001\n"                  # login sidik jari budi (1001)
            "2\nkopi\nP005\n" + str(qty) + "\n"   # beli Kopi Sachet x2
            "4\n"                        # checkout (risk AMAN)
            "1001\n"                     # tempel sidik jari untuk otorisasi
            "6\n4\n",                    # logout, keluar
        )
        ok = cek(bukti, h.returncode == 0, "exit 0", f"exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Sidik jari dikenali: budi."),
                 "login sidik jari budi dikenali") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Pembayaran diotorisasi dengan sidik jari."),
                 "checkout diotorisasi sidik jari") and ok
        ok = cek(bukti, not teks_ada(h.stdout, "Masukan PIN E-Wallet"),
                 "jalur sidik jari TIDAK meminta PIN E-Wallet") and ok
        ok = cek(bukti, teks_ada(h.stdout, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan."),
                 "transaksi sidik jari berhasil") and ok

        budi = baca_data(workdir, "users.json")["budi"]
        ok = cek(bukti, budi["balance"] == saldo_harap,
                 f"saldo budi = {rupiah(saldo_harap)} (dapat {rupiah(budi['balance'])})") and ok
        trx = budi["transactions"][-1]
        ok = cek(bukti, len(budi["transactions"]) == len(users_awal["budi"]["transactions"]) + 1,
                 "users.json: transaksi bertambah 1") and ok
        ok = cek(bukti, trx["total"] == total and trx["items"][0]["id"] == "P005",
                 f"transaksi tercatat total={rupiah(total)} P005 x{qty}") and ok
        ok = cek(bukti, baca_data(workdir, "products.json")["P005"]["stock"] == stok_harap,
                 f"stok P005 = {stok_harap}") and ok

        log_baru = baca_data(workdir, "logs.json")[len(logs_awal):]
        aksi = [catatan.get("action") for catatan in log_baru]
        ok = cek(bukti, "CHECKOUT_FINGER_RP_" + str(int(round(total))) in aksi,
                 f"log CHECKOUT_FINGER_RP_{int(round(total))} tercatat") and ok
        ok = cek(bukti, not any(str(a).startswith("CHECKOUT_SUCCESS_RP_") for a in aksi),
                 "log checkout jalur PIN TIDAK dipakai") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 9: protokol SOAP X100C (root = perintah) + mode soap host mati
# ---------------------------------------------------------------------------

def spot_protokol_dan_soap_mati():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        h = jalankan_driver_spot(workdir, DRIVER_PROTOKOL)
        ok = cek(bukti, h.returncode == 0, "driver protokol exit 0",
                 f"driver exit {h.returncode}: {h.stderr}") and ok
        data = {}
        try:
            data = json.loads(h.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            data = {}
        xml = data.get("xml_attlog", "")
        xml_user = data.get("xml_userinfo", "")
        ok = cek(bukti, "<GetAttLog>" in xml and "</GetAttLog>" in xml,
                 "buat_xml-> root <GetAttLog> (tanpa wrapper)",
                 f"xml salah: {xml!r}") and ok
        ok = cek(bukti, "<Command>" not in xml and "<CommandName>" not in xml,
                 "tidak memakai wrapper <Command>/<CommandName>",
                 f"masih ada wrapper: {xml!r}") and ok
        ok = cek(bukti, "<PIN>All</PIN>" in xml and "ArgComKey" in xml,
                 "request memuat PIN All + ArgComKey") and ok
        ok = cek(bukti, "<GetUserInfo>" in xml_user and "<PIN>1001</PIN>" in xml_user,
                 "buat_xml(GetUserInfo, PIN 1001) benar") and ok

        # mode soap ke host yang tidak mendengarkan -> pesan error, tidak crash, exit 0
        (workdir / "data" / "perangkat.json").write_text(
            json.dumps({
                "mode": "soap", "host": "127.0.0.1", "port": port_tertutup(),
                "com_key": 0, "timeout": 1, "jendela_detik": 30,
                "batas_tunggu_detik": 1,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        h = jalankan_spot(workdir, "3\n4\n")
        ok = cek(bukti, h.returncode == 0, "soap host mati: exit 0",
                 f"exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Menunggu sidik jari pada perangkat X100C..."),
                 "pesan menunggu sidik jari tampil") and ok
        ok = cek(bukti, teks_ada(h.stdout, PESAN_KONEKSI_GAGAL),
                 "pesan error koneksi sesuai kontrak",
                 "pesan error koneksi tidak muncul") and ok
        gabungan = str(h.stdout) + str(h.stderr)
        ok = cek(bukti, "Traceback" not in gabungan,
                 "tidak ada traceback/crash") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Terima kasih telah menggunakan PayGuard."),
                 "aplikasi kembali ke menu utama & keluar normal") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 10: mock X100C SOAP — login GetAttLog + checkout tap kedua
# ---------------------------------------------------------------------------

def spot_soap_login_checkout_tap2():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        logs_awal = fixture("logs.json")
        harga = products_awal["P005"]["price"]
        qty = 2
        total = harga * qty
        saldo_harap = users_awal["budi"]["balance"] - total
        stok_harap = products_awal["P005"]["stock"] - qty

        sekarang = datetime.now()
        # Device "bertahap": tap login muncul saat polling login; tap kedua baru
        # muncul saat polling checkout (realistis: user menempel dua kali).
        urutan_event = [
            [baris_attlog("1001", sekarang - timedelta(seconds=3))],
            [baris_attlog("1001", sekarang - timedelta(seconds=2))],
        ]

        def ambil_attlog():
            if urutan_event:
                return [dict(baris) for baris in urutan_event.pop(0)]
            return []

        with MockX100C(ambil_attlog) as mock:
            tulis_perangkat(workdir, mock.perangkat(batas_tunggu_detik=2))
            h = jalankan_spot(
                workdir,
                "3\n"                                  # login sidik jari via GetAttLog
                "2\nkopi\nP005\n" + str(qty) + "\n"    # beli Kopi Sachet x2
                "4\n"                                  # checkout -> tap sidik jari kedua
                "6\n4\n",                              # logout, keluar
            )

        ok = cek(bukti, h.returncode == 0, "exit 0", f"exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Sidik jari dikenali: budi."),
                 "login via GetAttLog (root tag) sukses") and ok
        ok = cek(bukti,
                 teks_ada(h.stdout, "Tempelkan sidik jari untuk mengotorisasi pembayaran..."),
                 "checkout menunggu tap sidik jari kedua") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Pembayaran diotorisasi dengan sidik jari."),
                 "tap kedua mengotorisasi pembayaran") and ok
        ok = cek(bukti, not teks_ada(h.stdout, "Masukan PIN E-Wallet"),
                 "jalur SOAP tidak meminta PIN") and ok
        ok = cek(bukti, teks_ada(h.stdout, "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan."),
                 "transaksi berhasil") and ok

        budi = baca_data(workdir, "users.json")["budi"]
        ok = cek(bukti, budi["balance"] == saldo_harap,
                 f"saldo budi = {rupiah(saldo_harap)} (dapat {rupiah(budi['balance'])})") and ok
        trx = budi["transactions"][-1]
        ok = cek(bukti,
                 len(budi["transactions"]) == len(users_awal["budi"]["transactions"]) + 1
                 and trx["total"] == total and trx["items"][0]["id"] == "P005",
                 f"transaksi tercatat total={rupiah(total)} P005 x{qty}") and ok
        ok = cek(bukti, baca_data(workdir, "products.json")["P005"]["stock"] == stok_harap,
                 f"stok P005 = {stok_harap}") and ok
        aksi = [catatan.get("action")
                for catatan in baca_data(workdir, "logs.json")[len(logs_awal):]]
        ok = cek(bukti, "CHECKOUT_FINGER_RP_" + str(int(round(total))) in aksi,
                 f"log CHECKOUT_FINGER_RP_{int(round(total))} tercatat") and ok
        ok = cek(bukti, not any(str(a).startswith("CHECKOUT_SUCCESS_RP_") for a in aksi),
                 "log jalur PIN tidak dipakai") and ok
        ok = cek(bukti,
                 all("<GetAttLog>" in body and "<Command>" not in body
                     for body in mock.catatan),
                 "semua request X100C root <GetAttLog>, tanpa wrapper <Command>",
                 f"request tidak sesuai: {mock.catatan!r}") and ok
        ok = cek(bukti, 200 in mock.status and 400 not in mock.status,
                 "mock menerima semua request (HTTP 200, tanpa 400)") and ok
        state = baca_data(workdir, "finger_state.json")
        ok = cek(bukti, len(state.get("terproses", [])) >= 2,
                 "state: event login + event tap checkout sama-sama ditandai",
                 f"state={state!r}") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 11: mock X100C SOAP — replay & event kadaluwarsa ditolak
# ---------------------------------------------------------------------------

def spot_soap_replay_dan_kadaluwarsa():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        sekarang = datetime.now()

        # (a) replay: device SELALU mengembalikan event yang sama
        event_tetap = baris_attlog("1001", sekarang - timedelta(seconds=2))
        with MockX100C(lambda: [dict(event_tetap)]) as mock:
            tulis_perangkat(workdir, mock.perangkat(batas_tunggu_detik=1))
            h = jalankan_spot(workdir, "3\n6\n3\n4\n")
        ok = cek(bukti, h.returncode == 0, "replay: exit 0", f"exit {h.returncode}") and ok
        jumlah_login = normalisasi(h.stdout).count("sidik jari dikenali: budi.")
        ok = cek(bukti, jumlah_login == 1,
                 "replay: hanya login pertama dikenali (login kedua ditolak)",
                 f"login dikenali {jumlah_login}x (event dipakai ulang)") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Tidak ada sidik jari terbaca."),
                 "replay: login kedua -> 'Tidak ada sidik jari terbaca.'") and ok
        jumlah_menu = normalisasi(h.stdout).count("=== menu pelanggan ===")
        ok = cek(bukti, jumlah_menu == 1,
                 "replay: menu pelanggan hanya terbuka 1x",
                 f"menu pelanggan terbuka {jumlah_menu}x") and ok

        # (b) event kadaluwarsa: device hanya punya event lama (2 jam lalu)
        event_lama = baris_attlog("1001", sekarang - timedelta(hours=2))
        with MockX100C(lambda: [dict(event_lama)]) as mock2:
            tulis_perangkat(workdir, mock2.perangkat(batas_tunggu_detik=1))
            h2 = jalankan_spot(workdir, "3\n4\n")
        ok = cek(bukti, h2.returncode == 0, "kadaluwarsa: exit 0", f"exit {h2.returncode}") and ok
        ok = cek(bukti, teks_ada(h2.stdout, "Tidak ada sidik jari terbaca."),
                 "kadaluwarsa: event lama tidak diterima") and ok
        ok = cek(bukti, not teks_ada(h2.stdout, "Sidik jari dikenali:"),
                 "kadaluwarsa: tidak ada login sidik jari") and ok
        ok = cek(bukti, teks_ada(h2.stdout, "Terima kasih telah menggunakan PayGuard."),
                 "kadaluwarsa: aplikasi keluar normal") and ok

        state = baca_data(workdir, "finger_state.json")
        ok = cek(bukti, len(state.get("terproses", [])) == 1,
                 "state: replay tidak menambah kunci event",
                 f"state={state!r}") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 12: tap sidik jari user lain saat checkout -> HOLD, bukan batal
# ---------------------------------------------------------------------------

def spot_tap_sidik_lain_membuat_hold():
    """Tap sidik jari salah TIDAK membatalkan belanjaan: hold + stok turun."""
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        logs_awal = fixture("logs.json")
        harga = float(products_awal["P005"]["price"])
        total_hold = harga * 2
        h = jalankan_spot(
            workdir,
            "3\n1001\n"                  # login sidik jari budi (1001)
            "2\nkopi\nP005\n2\n"         # beli Kopi Sachet x2
            "4\n"                        # checkout
            "1002\n"                     # tap sidik jari MILIK SITI -> gagal
            "6\n4\n",                    # logout, keluar
        )
        ok = cek(bukti, h.returncode == 0, "exit 0", f"exit {h.returncode}") and ok
        ok = cek(bukti, teks_ada(h.stdout, "Sidik jari tidak cocok."),
                 "pesan 'Sidik jari tidak cocok.' tampil") and ok
        ok = cek(bukti, teks_ada(
            h.stdout,
            "Sidik jari gagal. Belanjaan ditahan di keranjang dan stok sudah dikurangi."),
            "pesan hold (belanjaan ditahan) tampil", "pesan hold tidak muncul") and ok
        ok = cek(bukti, teks_ada(
            h.stdout, "Coba lagi lewat menu 4 untuk melanjutkan pembayaran."),
            "anjuran resume lewat menu 4 tampil") and ok
        ok = cek(bukti, not teks_ada(h.stdout, "--- RESI PEMBAYARAN ---"),
                 "tidak ada resi (belum bayar)") and ok

        keranjang = baca_data(workdir, "keranjang.json")
        ok = cek(bukti, len(keranjang) == 1, f"keranjang.json berisi 1 hold (dapat {len(keranjang)})") and ok
        record = keranjang[0] if keranjang else {}
        ok = cek(bukti, str(record.get("id", "")).startswith("HOLD-"),
                 f"id hold valid ({record.get('id')})") and ok
        ok = cek(bukti, record.get("username") == "budi"
                 and record.get("total") == total_hold
                 and record.get("percobaan") == 1
                 and record.get("status") == "tertahan",
                 f"record hold: budi, total {rupiah(total_hold)}, percobaan 1, "
                 "status tertahan") and ok
        ok = cek(bukti, record.get("items") == [
            {"id": "P005", "name": products_awal["P005"]["name"],
             "price": harga, "qty": 2}],
            "items hold sama dengan isi keranjang") and ok

        budi = baca_data(workdir, "users.json")["budi"]
        ok = cek(bukti, budi["balance"] == users_awal["budi"]["balance"],
                 f"saldo budi TETAP {rupiah(budi['balance'])}") and ok
        ok = cek(bukti, len(budi["transactions"]) == len(users_awal["budi"]["transactions"]),
                 "transaksi budi tidak bertambah") and ok
        ok = cek(bukti, baca_data(workdir, "products.json")["P005"]["stock"]
                 == products_awal["P005"]["stock"] - 2,
                 f"stok P005 turun jadi {products_awal['P005']['stock'] - 2}") and ok
        aksi = [catatan for catatan in baca_data(workdir, "logs.json")[len(logs_awal):]]
        log_hold = [c for c in aksi if c.get("action") == "HOLD_CART"]
        ok = cek(bukti, len(log_hold) == 1, "log HOLD_CART tercatat") and ok
        detail = str(log_hold[0].get("detail", "")) if log_hold else ""
        ok = cek(bukti, detail.startswith(str(record.get("id", "")) + ":")
                 and float(detail.split(":", 1)[1]) == total_hold,
                 f"detail log HOLD_CART = <id>:{int(round(total_hold))} ({detail})") and ok
        ok = cek(bukti, not any(str(c.get("action", "")).startswith("CHECKOUT_FINGER_RP_")
                                for c in aksi),
                 "tidak ada log CHECKOUT_FINGER (belum bayar)") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 13: resume hold (menu 4 -> y) + tap sidik jari sukses
# ---------------------------------------------------------------------------

def spot_resume_hold_sukses():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        logs_awal = fixture("logs.json")
        harga = products_awal["P005"]["price"]
        total = harga * 2
        saldo_harap = users_awal["budi"]["balance"] - total

        # run 1: buat hold (tap salah)
        h1 = jalankan_spot(
            workdir,
            "3\n1001\n2\nkopi\nP005\n2\n4\n1002\n6\n4\n",
        )
        ok = cek(bukti, h1.returncode == 0, "run1 buat hold exit 0",
                 f"run1 exit {h1.returncode}") and ok
        keranjang = baca_data(workdir, "keranjang.json")
        ok = cek(bukti, len(keranjang) == 1, "run1: hold terbentuk") and ok
        record = keranjang[0] if keranjang else {}

        # run 2: resume hold -> y -> tap sidik jari budi (benar) -> sukses
        h2 = jalankan_spot(
            workdir,
            "3\n1001\n"           # login sidik jari budi
            "4\n"                 # menu 4 -> tawaran resume
            "y\n"                 # lanjutkan pembayaran
            "1001\n"              # tap sidik jari benar
            "6\n4\n",             # logout, keluar
        )
        ok = cek(bukti, h2.returncode == 0, "run2 resume exit 0",
                 f"run2 exit {h2.returncode}") and ok
        ok = cek(bukti, teks_ada(h2.stdout, "Ada keranjang tertahan atas nama budi:"),
                 "prompt resume hold tampil") and ok
        ok = cek(bukti, teks_ada(h2.stdout, str(record.get("id", ""))),
                 "ID hold yang ditawarkan benar") and ok
        ok = cek(bukti, teks_ada(h2.stdout, "Lanjutkan pembayaran sekarang? (y/n):"),
                 "pertanyaan y/n resume tampil") and ok
        ok = cek(bukti, teks_ada(h2.stdout, "Pembayaran diotorisasi dengan sidik jari."),
                 "tap sidik jari kedua mengotorisasi pembayaran") and ok
        ok = cek(bukti, teks_ada(h2.stdout,
                 "TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan."),
                 "transaksi resume berhasil") and ok
        ok = cek(bukti, not teks_ada(h2.stdout, "Masukan PIN E-Wallet"),
                 "resume jalur sidik jari tidak meminta PIN") and ok

        budi = baca_data(workdir, "users.json")["budi"]
        ok = cek(bukti, budi["balance"] == saldo_harap,
                 f"saldo budi = {rupiah(saldo_harap)} (dapat {rupiah(budi['balance'])})") and ok
        transaksi = budi["transactions"]
        ok = cek(bukti, len(transaksi) == len(users_awal["budi"]["transactions"]) + 1,
                 "transaksi bertambah 1") and ok
        trx = transaksi[-1]
        ok = cek(bukti, trx["total"] == total and trx["items"][0]["id"] == "P005",
                 f"transaksi tercatat total={rupiah(total)} P005 x2") and ok
        ok = cek(bukti, baca_data(workdir, "products.json")["P005"]["stock"]
                 == products_awal["P005"]["stock"] - 2,
                 "stok P005 TIDAK dipotong dua kali") and ok
        ok = cek(bukti, baca_data(workdir, "keranjang.json") == [],
                 "hold hilang dari keranjang.json setelah sukses") and ok
        aksi = [c.get("action") for c in baca_data(workdir, "logs.json")[len(logs_awal):]]
        ok = cek(bukti, "HOLD_CART" in aksi, "log HOLD_CART tercatat") and ok
        ok = cek(bukti, "CHECKOUT_FINGER_RP_" + str(int(round(total))) in aksi,
                 f"log CHECKOUT_FINGER_RP_{int(round(total))} tercatat") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Spot-check 14: admin lihat daftar hold + batalkan (stok kembali)
# ---------------------------------------------------------------------------

def spot_admin_cancel_hold():
    bukti = []
    ok = True
    workdir = buat_workdir_spot()
    try:
        users_awal = fixture("users.json")
        products_awal = fixture("products.json")
        logs_awal = fixture("logs.json")
        harga_p005 = float(products_awal["P005"]["price"])
        total_hold = harga_p005 * 2
        # run 1: buat hold budi (Kopi x2)
        h1 = jalankan_spot(workdir, "3\n1001\n2\nkopi\nP005\n2\n4\n1002\n6\n4\n")
        ok = cek(bukti, h1.returncode == 0, "run1 buat hold exit 0",
                 f"run1 exit {h1.returncode}") and ok
        keranjang = baca_data(workdir, "keranjang.json")
        ok = cek(bukti, len(keranjang) == 1, "run1: hold terbentuk") and ok
        record = keranjang[0] if keranjang else {}

        # run 2: admin -> menu 8 (kelola keranjang tertahan) -> list -> cancel n -> cancel y
        h2 = jalankan_spot(
            workdir,
            "1\nadmin\n123456\n"
            "8\n"                              # menu 8: Kelola Keranjang Tertahan
            "1\n"                              # lihat daftar
            "2\n" + str(record.get("id", "")) + "\nn\n"   # batal -> n
            "2\n" + str(record.get("id", "")) + "\ny\n"   # batal -> y
            "3\n"                              # kembali ke menu admin
            "9\n4\n",                          # logout admin, keluar
        )
        ok = cek(bukti, h2.returncode == 0, "run2 admin exit 0",
                 f"run2 exit {h2.returncode}") and ok
        ok = cek(bukti, teks_ada(h2.stdout, "=== KELOLA KERANJANG TERTAHAN ==="),
                 "submenu keranjang tertahan tampil") and ok
        ok = cek(bukti, teks_ada(h2.stdout,
                 str(record.get("id", "")) + " | budi | Total " + rupiah(total_hold)
                 + " | percobaan 1 | " + products_awal["P005"]["name"] + " x2"),
                 "baris daftar hold sesuai format kontrak") and ok
        ok = cek(bukti, teks_ada(h2.stdout, "Pembatalan dibatalkan."),
                 "jawaban n -> pembatalan dibatalkan") and ok
        ok = cek(bukti, teks_ada(h2.stdout, "Keranjang " + str(record.get("id", ""))
                 + " dibatalkan, stok dikembalikan."),
                 "jawaban y -> hold dibatalkan & stok dikembalikan") and ok

        ok = cek(bukti, baca_data(workdir, "keranjang.json") == [],
                 "keranjang.json kosong setelah cancel") and ok
        ok = cek(bukti, baca_data(workdir, "products.json")["P005"]["stock"]
                 == products_awal["P005"]["stock"],
                 f"stok P005 kembali seperti semula ({products_awal['P005']['stock']})") and ok
        budi = baca_data(workdir, "users.json")["budi"]
        ok = cek(bukti, budi["balance"] == users_awal["budi"]["balance"],
                 "saldo budi tetap (tidak dipotong karena hold)") and ok
        ok = cek(bukti, len(budi["transactions"]) == len(users_awal["budi"]["transactions"]),
                 "transaksi budi tidak bertambah") and ok
        aksi = [c for c in baca_data(workdir, "logs.json")[len(logs_awal):]]
        log_cancel = [c for c in aksi if c.get("action") == "HOLD_CANCEL"]
        ok = cek(bukti, len(log_cancel) == 1, "log HOLD_CANCEL tercatat") and ok
        ok = cek(bukti, log_cancel and log_cancel[0].get("detail") == record.get("id"),
                 "detail log HOLD_CANCEL = id hold") and ok
    finally:
        hapus_pohon(workdir)
    return ok, bukti


# ---------------------------------------------------------------------------
# Utama
# ---------------------------------------------------------------------------

def main():
    print("=" * 78)
    print("VERIFIKASI FINAL PAYGUARD CLI — suite + integritas data + spot-check")
    print("=" * 78)

    if not all((DATA_DIR / nama).is_file() for nama in DATA_FILES):
        print("[GAGAL] File data asli tidak lengkap:", DATA_DIR)
        return 1

    # 1) snapshot hash data + manifest app/data SEBELUM suite
    hash_sebelum = {nama: sha256_file(DATA_DIR / nama) for nama in DATA_FILES}
    manifest_sebelum = manifest_payguard()

    def pisahkan_manifest(manifest):
        """Pisahkan manifest menjadi inti, dokumen proyek (*.md), dan artifak lain.

        - inti = file ``*.py`` + ``data/*.json`` (kecuali finger_state runtime):
          WAJIB tidak berubah (bukti QA tidak mengubah kode/data).
        - dokumen (README/HASIL_TEST/SPESIFIKASI) + artifak lain (mis. log proses
          lain) milik Lead / proses eksternal: boleh berubah, hanya dicatat.
        """
        inti, dokumen, lain = {}, {}, {}
        for nama, nilai_hash in manifest.items():
            nama_normal = nama.replace("\\", "/")
            if nama_normal.startswith("data/") or nama_normal.endswith(".py"):
                inti[nama] = nilai_hash
            elif nama_normal.lower().endswith(".md"):
                dokumen[nama] = nilai_hash
            else:
                lain[nama] = nilai_hash
        return inti, dokumen, lain

    inti_sebelum, dokumen_sebelum, lain_sebelum = pisahkan_manifest(manifest_sebelum)
    print("\n[1] SHA256 payguard/data/*.json SEBELUM suite:")
    for nama in DATA_FILES:
        print(f"    {nama:16s} {hash_sebelum[nama]}")
    print(f"    (manifest inti app/data: {len(inti_sebelum)} file; "
          f"dokumen: {len(dokumen_sebelum)} file; artifak lain: {len(lain_sebelum)} file)")

    # 2) fixtures DATA wajib byte-identik; perangkat.json = config deployment
    fixtures_lengkap = all((FIXTURES_DIR / nama).is_file() for nama in DATA_FILES)
    selisih_fixture = [
        nama for nama in FIXTURE_IDENTIK_FILES
        if fixtures_lengkap
        and (FIXTURES_DIR / nama).read_bytes() != (DATA_DIR / nama).read_bytes()
    ]
    perangkat_fixture = {}
    if (FIXTURES_DIR / "perangkat.json").is_file():
        perangkat_fixture = baca_json(FIXTURES_DIR / "perangkat.json")
    perangkat_data = {}
    if (DATA_DIR / "perangkat.json").is_file():
        perangkat_data = baca_json(DATA_DIR / "perangkat.json")
    perangkat_fixture_ok = perangkat_fixture.get("mode") == MODE_PERANGKAT_TEST
    bytes_perangkat_fixture_awal = (
        (FIXTURES_DIR / "perangkat.json").read_bytes()
        if (FIXTURES_DIR / "perangkat.json").is_file() else b""
    )
    print("\n[2] Fixtures data (users/products/logs/keranjang) byte-identik dengan data asli:",
          "YA" if fixtures_lengkap and not selisih_fixture else f"TIDAK: {selisih_fixture}")
    print("    config perangkat: fixtures mode=", perangkat_fixture.get("mode"),
          "| data asli mode=", perangkat_data.get("mode"),
          "-> config deployment dikecualikan dari byte-identik;",
          "fixture wajib simulasi:", "YA" if perangkat_fixture_ok else "TIDAK")

    # 3) jalankan suite unittest lengkap
    perintah = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    print("\n[3] Menjalankan:", " ".join(perintah))
    print("-" * 78)
    mulai = time.time()
    hasil = subprocess.run(
        perintah,
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env_anak(),
    )
    durasi = time.time() - mulai
    print(hasil.stdout)
    if hasil.stderr.strip():
        print("--- stderr (unittest menulis hasil ke stderr) ---")
        print(hasil.stderr)
    print("-" * 78)
    keluaran = (hasil.stdout or "") + (hasil.stderr or "")

    # 4) ringkasan test
    jumlah = re.search(r"Ran (\d+) tests?", keluaran)
    print(f"[4] Ringkasan test: exit code={hasil.returncode}, durasi={durasi:.1f} detik, "
          f"jumlah test={jumlah.group(1) if jumlah else '?'}")

    # 5) snapshot SESUDAH suite + bandingkan
    hash_sesudah_suite = {nama: sha256_file(DATA_DIR / nama) for nama in DATA_FILES}
    print("\n[5] SHA256 payguard/data/*.json SESUDAH suite:")
    for nama in DATA_FILES:
        print(f"    {nama:16s} {hash_sesudah_suite[nama]}")
    identik_suite = hash_sebelum == hash_sesudah_suite
    print("\n[6] Data asli identik sebelum vs sesudah suite:", "YA" if identik_suite else "TIDAK")

    def cek_tmp_bersih():
        if not BASE_TMP.exists():
            return True
        return not any(BASE_TMP.iterdir())

    tmp_bersih = cek_tmp_bersih()
    print("[7] tests/_tmp bersih setelah suite:", "YA" if tmp_bersih else "TIDAK")

    # 8) spot-check independen pada salinan data
    print("\n[8] SPOT-CHECK INDEPENDEN (semua dijalankan pada salinan data):")
    skenario = (
        ("admin create+update+delete, customer lihat katalog", spot_admin_crud),
        ("budi top up 100.000 + checkout Beras 5kg x1 (AMAN)", spot_budi_topup_checkout),
        ("siti risk PERINGATAN SEDANG dijawab n (batal)", spot_risk_sedang_batal),
        ("siti risk PERINGATAN SEDANG dijawab y + PIN (sukses)", spot_risk_sedang_lanjut),
        ("lockout siti 3x -> admin unlock -> siti login", spot_lockout_unlock),
        ("register rina -> login -> top up -> beli -> logout", spot_register_baru),
        ("admin kelola sidik jari X100C (daftar/hapus/lihat/validasi)", spot_admin_sidik_jari),
        ("login sidik jari budi + checkout tanpa PIN", spot_checkout_sidik_jari),
        ("protokol SOAP root=perintah + soap host mati", spot_protokol_dan_soap_mati),
        ("mock SOAP: login GetAttLog + checkout tap kedua", spot_soap_login_checkout_tap2),
        ("mock SOAP: replay & event kadaluwarsa ditolak", spot_soap_replay_dan_kadaluwarsa),
        ("tap sidik jari user lain -> hold keranjang (bukan batal)", spot_tap_sidik_lain_membuat_hold),
        ("resume hold (menu 4 -> y) + tap sukses", spot_resume_hold_sukses),
        ("admin lihat & batalkan hold (stok kembali)", spot_admin_cancel_hold),
    )
    hasil_spot = []
    for judul, fungsi in skenario:
        try:
            ok_spot, bukti_spot = fungsi()
        except Exception as galat:  # noqa: BLE001 - laporkan, jangan hentikan skenario lain
            ok_spot, bukti_spot = False, ["GAGAL exception: " + repr(galat)]
        hasil_spot.append(ok_spot)
        print(f"\n  {'[OK]  ' if ok_spot else '[FAIL]'} {judul}")
        for baris in bukti_spot:
            print("        - " + baris)
    semua_spot = all(hasil_spot)
    print(f"\n[8] Hasil spot-check: {sum(hasil_spot)}/{len(hasil_spot)} skenario OK")

    # bersihkan folder _tmp bila kosong
    if BASE_TMP.exists() and not any(BASE_TMP.iterdir()):
        try:
            BASE_TMP.rmdir()
        except OSError:
            pass

    # 9) verifikasi akhir: hash data, manifest inti app/data, fixtures, _tmp
    hash_akhir = {nama: sha256_file(DATA_DIR / nama) for nama in DATA_FILES}
    manifest_akhir = manifest_payguard()
    inti_akhir, dokumen_akhir, lain_akhir = pisahkan_manifest(manifest_akhir)
    berkas_baru = sorted(set(inti_akhir) - set(inti_sebelum))
    berkas_hilang = sorted(set(inti_sebelum) - set(inti_akhir))
    berkas_berubah = sorted(
        nama for nama in set(inti_sebelum) & set(inti_akhir)
        if inti_sebelum[nama] != inti_akhir[nama]
    )
    dokumen_berubah = sorted(
        nama for nama in set(dokumen_sebelum) & set(dokumen_akhir)
        if dokumen_sebelum[nama] != dokumen_akhir[nama]
    )
    dokumen_baru = sorted(set(dokumen_akhir) - set(dokumen_sebelum))
    dokumen_hilang = sorted(set(dokumen_sebelum) - set(dokumen_akhir))
    lain_berubah = sorted(
        nama for nama in set(lain_sebelum) & set(lain_akhir)
        if lain_sebelum[nama] != lain_akhir[nama]
    )
    lain_baru = sorted(set(lain_akhir) - set(lain_sebelum))
    lain_hilang = sorted(set(lain_sebelum) - set(lain_akhir))
    data_identik = hash_akhir == hash_sebelum
    manifest_identik = not (berkas_baru or berkas_hilang or berkas_berubah)
    fixture_akhir = [
        nama for nama in FIXTURE_IDENTIK_FILES
        if (FIXTURES_DIR / nama).is_file()
        and (FIXTURES_DIR / nama).read_bytes() != (DATA_DIR / nama).read_bytes()
    ]
    perangkat_fixture_akhir = {}
    if (FIXTURES_DIR / "perangkat.json").is_file():
        perangkat_fixture_akhir = baca_json(FIXTURES_DIR / "perangkat.json")
    perangkat_akhir_ok = (
        perangkat_fixture_akhir.get("mode") == MODE_PERANGKAT_TEST
        and (FIXTURES_DIR / "perangkat.json").read_bytes() == bytes_perangkat_fixture_awal
    )
    tmp_akhir = cek_tmp_bersih()
    state_fixture = FIXTURES_DIR / "finger_state.json"
    state_fixture_aman = not state_fixture.exists()
    state_asli = DATA_DIR / "finger_state.json"
    state_asli_valid = True
    state_asli_info = "tidak ada (belum pernah login sidik jari di data asli)"
    if state_asli.exists():
        try:
            isi_state = baca_json(state_asli)
            state_asli_valid = (isinstance(isi_state, dict)
                                and isinstance(isi_state.get("terproses"), list))
            state_asli_info = ("ada (runtime aplikasi nyata, valid)" if state_asli_valid
                               else "ada tapi isinya TIDAK valid")
        except Exception:
            state_asli_valid = False
            state_asli_info = "ada tapi rusak"
    state_aman = state_fixture_aman and state_asli_valid

    print("\n[9] INTEGRITAS AKHIR:")
    print("    (a) SHA256 data asli identik sebelum vs sesudah seluruh verifikasi:",
          "YA" if data_identik else "TIDAK")
    if not data_identik:
        for nama in DATA_FILES:
            if hash_sebelum[nama] != hash_akhir[nama]:
                print(f"        BERUBAH: {nama} {hash_sebelum[nama]} -> {hash_akhir[nama]}")
    print("    (b) fixtures data (users/products/logs/keranjang) masih byte-identik dengan data asli:",
          "YA" if not fixture_akhir else f"TIDAK: {fixture_akhir}")
    print("    (c) tests/_tmp tidak menyisakan folder:", "YA" if tmp_akhir else "TIDAK")
    print(f"    (d) manifest inti app/data tidak berubah: "
          f"{'YA' if manifest_identik else 'TIDAK'} ({len(inti_sebelum)} file)")
    print("    (e) fixtures bebas finger_state.json; data asli boleh state runtime:",
          "YA" if state_aman else "TIDAK", f"({state_asli_info})")
    print("    (f) fixtures/perangkat.json tetap mode simulasi (config deployment aman):",
          "YA" if perangkat_akhir_ok else "TIDAK")
    if dokumen_berubah or dokumen_baru or dokumen_hilang:
        print("        catatan: dokumen proyek berubah selama verifikasi "
              "(README/HASIL_TEST/SPESIFIKASI milik Lead; BUKAN kegagalan QA):",
              sorted(set(dokumen_berubah) | set(dokumen_baru) | set(dokumen_hilang)))
    if lain_berubah or lain_baru or lain_hilang:
        print("        catatan: artifak non-kode berubah/baru selama verifikasi "
              "(mis. log proses Lead/QA lain; BUKAN kegagalan QA):",
              sorted(set(lain_berubah) | set(lain_baru) | set(lain_hilang)))
    if berkas_baru:
        print("        file BARU di luar tests/:", berkas_baru)
    if berkas_hilang:
        print("        file HILANG:", berkas_hilang)
    if berkas_berubah:
        print("        file BERUBAH:", berkas_berubah)

    lulus = (
        hasil.returncode == 0
        and identik_suite
        and data_identik
        and not selisih_fixture
        and not fixture_akhir
        and perangkat_fixture_ok
        and perangkat_akhir_ok
        and tmp_bersih
        and tmp_akhir
        and state_aman
        and manifest_identik
        and semua_spot
        and fixtures_lengkap
        and len(hasil_spot) == len(skenario)
    )
    print("\n" + "=" * 78)
    print("HASIL VERIFIKASI FINAL:", "LULUS" if lulus else "GAGAL")
    print("=" * 78)
    return 0 if lulus else 1


if __name__ == "__main__":
    sys.exit(main())
