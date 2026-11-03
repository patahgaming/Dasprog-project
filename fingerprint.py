# fingerprint.py - integrasi mesin sidik jari ZKTeco X100C untuk PayGuard.
# Mode "simulasi" dipakai saat tidak ada perangkat: ID perangkat diketik manual.
# Mode "soap" memanggil POST /iWsService ke host:port mesin lewat socket TCP,
# lalu membaca XML balasan dengan xml.etree.ElementTree.
# Stdlib saja (socket, xml, time, datetime, os) tanpa pip.

import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import data_manager

MODE_SIMULASI = 'simulasi'
MODE_SOAP = 'soap'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
PERANGKAT_FILE = os.path.join(DATA_DIR, 'perangkat.json')
STATE_FILE = os.path.join(DATA_DIR, 'finger_state.json')
ENV_FILE = os.path.join(BASE_DIR, '.env')

# nilai default kalau data/perangkat.json belum ada / rusak
PERANGKAT_DEFAULT = {
    'mode': MODE_SIMULASI,
    'host': '192.168.1.201',
    'port': 80,
    'com_key': 0,
    'timeout': 5,
    'jendela_detik': 30,
    'batas_tunggu_detik': 20,
}

# environment variable -> kunci config perangkat + tipe nilainya.
# Nilai di .env / environment menimpa data/perangkat.json (config deployment
# tidak disimpan di repo; lihat .env.example).
ENV_CONFIG = {
    'PAYGUARD_X100C_MODE': ('mode', lambda v: str(v).strip()),
    'PAYGUARD_X100C_HOST': ('host', lambda v: str(v).strip()),
    'PAYGUARD_X100C_PORT': ('port', int),
    'PAYGUARD_X100C_COM_KEY': ('com_key', int),
    'PAYGUARD_X100C_TIMEOUT': ('timeout', float),
    'PAYGUARD_X100C_JENDELA_DETIK': ('jendela_detik', float),
    'PAYGUARD_X100C_BATAS_TUNGGU_DETIK': ('batas_tunggu_detik', float),
}

# state hanya menyimpan 200 kunci event terakhir supaya file tidak membengkak
BATAS_STATE = 200
FORMAT_WAKTU = '%Y-%m-%d %H:%M:%S'
PESAN_GAGAL_KONEKSI = ('Perangkat X100C tidak terhubung. '
                       'Periksa kabel/jaringan dan konfigurasi.')


def _baca_env(nama_file=None):
    # baca file .env sederhana: KEY=VALUE, abaikan komentar/baris kosong
    if nama_file is None:
        nama_file = ENV_FILE
    hasil = {}
    try:
        with open(nama_file, encoding='utf-8') as file:
            for baris in file:
                baris = baris.strip()
                if baris == '' or baris.startswith('#') or '=' not in baris:
                    continue
                if baris.startswith('export '):
                    baris = baris[7:].strip()
                kunci, nilai = baris.split('=', 1)
                kunci = kunci.strip()
                nilai = nilai.strip()
                if len(nilai) >= 2 and nilai[0] == nilai[-1] and nilai[0] in ('"', "'"):
                    nilai = nilai[1:-1]
                hasil[kunci] = nilai
    except FileNotFoundError:
        pass
    return hasil


def _terapkan_env(perangkat):
    # prioritas: default < data/perangkat.json < .env < environment OS
    sumber = _baca_env()
    for nama, nilai in os.environ.items():
        if nama in ENV_CONFIG:
            sumber[nama] = nilai
    for nama_env, (kunci, konversi) in ENV_CONFIG.items():
        if nama_env not in sumber:
            continue
        try:
            perangkat[kunci] = konversi(sumber[nama_env])
        except (TypeError, ValueError, OverflowError):
            # nilai env tidak valid -> pakai nilai dari file/default
            continue
    return perangkat


def _ke_float(nilai, bawaan):
    # ubah nilai config ke float; kalau gagal pakai nilai bawaan
    try:
        return float(nilai)
    except (TypeError, ValueError):
        return bawaan


def _waktu_kejadian(teks):
    # "2026-11-03 12:00:00" -> datetime; None kalau format salah
    try:
        return datetime.strptime(str(teks).strip(), FORMAT_WAKTU)
    except (TypeError, ValueError):
        return None


def _nama_tag(tag):
    # buang namespace XML kalau ada: "{ns}Row" -> "Row"
    if isinstance(tag, str) and '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def _respons_selesai(data):
    # hentikan pembacaan socket begitu tag penutup response XML terlihat,
    # mis. </GetAttLogResponse> atau </GetUserInfoResponse>
    return re.search(rb'</[A-Za-z0-9_]+Response\s*>', data) is not None


def baca_perangkat():
    # baca default -> data/perangkat.json -> .env/environment (config rahasia)
    perangkat = dict(PERANGKAT_DEFAULT)
    isi = data_manager.baca_json(PERANGKAT_FILE, {})
    if isinstance(isi, dict):
        for kunci in isi:
            perangkat[kunci] = isi[kunci]
    return _terapkan_env(perangkat)


def baca_state():
    # state runtime penyimpan event yang sudah diproses
    state = data_manager.baca_json(STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    daftar = state.get('terproses', [])
    if not isinstance(daftar, list):
        daftar = []
    state['terproses'] = [str(kunci) for kunci in daftar]
    return state


def simpan_state(state):
    # tulis state lewat data_manager.tulis_json (atomic)
    if not isinstance(state, dict):
        state = {}
    if not isinstance(state.get('terproses'), list):
        state['terproses'] = []
    data_manager.tulis_json(STATE_FILE, state)


def buat_xml(command, args=None, com_key=0):
    # bentuk XML perintah X100C: root elemen = nama perintah
    # <GetAttLog><ArgComKey xsi:type="xsd:integer">0</ArgComKey>
    #   <Arg><PIN>All</PIN></Arg></GetAttLog>
    nama_command = str(command)
    potongan = ['<' + nama_command + '>']
    potongan.append('<ArgComKey xsi:type="xsd:integer">' +
                    str(com_key) + '</ArgComKey>')
    if args:
        potongan.append('<Arg>')
        for nama in args:
            potongan.append('<' + str(nama) + '>' + str(args[nama]) +
                            '</' + str(nama) + '>')
        potongan.append('</Arg>')
    potongan.append('</' + nama_command + '>')
    return ''.join(potongan)


def kirim_soap(xml_teks, perangkat=None):
    # kirim HTTP POST /iWsService lewat socket, balikan body response (str)
    # raise OSError/TimeoutError kalau perangkat tidak terhubung
    if perangkat is None:
        perangkat = baca_perangkat()
    host = str(perangkat.get('host', PERANGKAT_DEFAULT['host']))
    port = int(perangkat.get('port', PERANGKAT_DEFAULT['port']))
    timeout = _ke_float(perangkat.get('timeout', PERANGKAT_DEFAULT['timeout']), 5.0)

    isi = str(xml_teks).encode('utf-8')
    header = ('POST /iWsService HTTP/1.0\r\n' +
              'Content-Length: ' + str(len(isi)) + '\r\n' +
              'Content-Type: text/xml;\r\n' +
              '\r\n')

    potongan = []
    with socket.create_connection((host, port), timeout=timeout) as koneksi:
        koneksi.sendall(header.encode('utf-8') + isi)
        while True:
            data = koneksi.recv(4096)
            if not data:
                break
            potongan.append(data)
            if _respons_selesai(b''.join(potongan)):
                break

    respons = b''.join(potongan)
    # buang header HTTP: body ada setelah baris kosong pertama
    pemisah = respons.find(b'\r\n\r\n')
    if pemisah != -1:
        respons = respons[pemisah + 4:]
    return respons.decode('utf-8', errors='replace')


def parse_rows(xml_teks):
    # ambil semua <Row> dari response XML -> list dict field
    hasil = []
    teks = '' if xml_teks is None else str(xml_teks).strip()
    if teks == '':
        return hasil
    posisi = teks.find('<')
    if posisi > 0:
        teks = teks[posisi:]
    try:
        akar = ET.fromstring(teks)
    except ET.ParseError:
        return hasil
    for elemen in akar.iter():
        if _nama_tag(elemen.tag) != 'Row':
            continue
        data = {}
        for field in list(elemen):
            data[_nama_tag(field.tag)] = (field.text or '').strip()
        hasil.append(data)
    return hasil


def get_attlog(perangkat=None):
    # baca semua log verifikasi sidik jari dari mesin (GetAttLog, PIN=All)
    if perangkat is None:
        perangkat = baca_perangkat()
    com_key = perangkat.get('com_key', PERANGKAT_DEFAULT['com_key'])
    xml_teks = buat_xml('GetAttLog', {'PIN': 'All'}, com_key)
    balasan = kirim_soap(xml_teks, perangkat)
    return parse_rows(balasan)


def get_user_info(pin, perangkat=None):
    # cek apakah PIN terdaftar di perangkat (GetUserInfo); return dict/None
    if perangkat is None:
        perangkat = baca_perangkat()
    com_key = perangkat.get('com_key', PERANGKAT_DEFAULT['com_key'])
    xml_teks = buat_xml('GetUserInfo', {'PIN': str(pin)}, com_key)
    balasan = kirim_soap(xml_teks, perangkat)
    rows = parse_rows(balasan)
    if rows:
        return rows[0]
    return None


def tes_koneksi(perangkat=None):
    # tes koneksi + hitung log; return (ok, pesan siap ditampilkan)
    if perangkat is None:
        perangkat = baca_perangkat()
    mode = str(perangkat.get('mode', MODE_SIMULASI))
    if mode != MODE_SOAP:
        return True, 'Mode simulasi: perangkat tidak dihubungi.'
    host = str(perangkat.get('host', PERANGKAT_DEFAULT['host']))
    port = perangkat.get('port', PERANGKAT_DEFAULT['port'])
    try:
        daftar_log = get_attlog(perangkat)
    except (OSError, TimeoutError):
        return False, 'Koneksi X100C GAGAL: ' + PESAN_GAGAL_KONEKSI
    return True, ('Koneksi X100C OK: ' + host + ':' + str(port) +
                  ' (' + str(len(daftar_log)) + ' log).')


def kunci_kejadian(event):
    # kunci unik event untuk dedupe/replay: "<pin>|<datetime>|<status>"
    return (str(event.get('PIN', '')).strip() + '|' +
            str(event.get('DateTime', '')).strip() + '|' +
            str(event.get('Status', '')).strip())


def ambil_kejadian_baru(perangkat=None, jendela_detik=None):
    # GetAttLog -> hanya event fresh (dalam jendela_detik) yang belum terproses,
    # diurutkan dari yang paling lama
    if perangkat is None:
        perangkat = baca_perangkat()
    if jendela_detik is None:
        jendela_detik = perangkat.get('jendela_detik',
                                      PERANGKAT_DEFAULT['jendela_detik'])
    jendela = _ke_float(jendela_detik, 30.0)

    semua_kejadian = get_attlog(perangkat)
    terproses = baca_state().get('terproses', [])
    sekarang = datetime.now()

    hasil = []
    for event in semua_kejadian:
        waktu = _waktu_kejadian(event.get('DateTime', ''))
        if waktu is None:
            continue
        selisih = abs((sekarang - waktu).total_seconds())
        if selisih > jendela:
            continue
        if kunci_kejadian(event) in terproses:
            continue
        hasil.append((waktu, event))

    hasil.sort(key=lambda pasangan: pasangan[0])
    return [event for _, event in hasil]


def tandai_kejadian(event):
    # simpan kunci event ke state supaya tidak bisa dipakai ulang (anti-replay)
    state = baca_state()
    daftar = state.get('terproses', [])
    kunci = kunci_kejadian(event)
    if kunci in daftar:
        daftar.remove(kunci)
    daftar.append(kunci)
    state['terproses'] = daftar[-BATAS_STATE:]
    simpan_state(state)


def cari_user_dari_pin(pin):
    # cari akun PayGuard dengan finger_id == pin; None kalau tidak ada
    pin = '' if pin is None else str(pin).strip()
    if pin == '':
        return None
    users = data_manager.baca_users()
    for username in users:
        user = users[username]
        finger_id = user.get('finger_id', '')
        finger_id = '' if finger_id is None else str(finger_id).strip()
        if finger_id != '' and finger_id == pin:
            return user
    return None


def kejadian_simulasi(pin):
    # event palsu untuk mode simulasi: waktu sekarang, status verifikasi "1"
    return {
        'PIN': str(pin).strip(),
        'DateTime': datetime.now().strftime(FORMAT_WAKTU),
        'Verified': '1',
        'Status': '1',
        'WorkCode': '0',
    }


def tunggu_sidik_jari(perangkat=None):
    # tunggu satu event sidik jari; return event dict atau None
    if perangkat is None:
        perangkat = baca_perangkat()
    mode = str(perangkat.get('mode', MODE_SIMULASI))

    if mode != MODE_SOAP:
        # mode simulasi: ID perangkat diketik manual
        teks = input('(SIMULASI) Masukkan ID perangkat: ')
        teks = '' if teks is None else str(teks).strip()
        if teks == '':
            return None
        event = kejadian_simulasi(teks)
        tandai_kejadian(event)
        return event

    # mode soap: polling GetAttLog sampai batas_tunggu_detik
    print('Menunggu sidik jari pada perangkat X100C...')
    batas = _ke_float(perangkat.get('batas_tunggu_detik',
                                    PERANGKAT_DEFAULT['batas_tunggu_detik']), 20.0)
    mulai = time.time()
    while time.time() - mulai <= batas:
        try:
            daftar = ambil_kejadian_baru(perangkat)
        except (OSError, TimeoutError):
            print(PESAN_GAGAL_KONEKSI)
            return None
        if daftar:
            # pakai event terbaru; semua event fresh yang ikut terbaca ditandai
            # supaya tap lama tidak bisa dipakai untuk login berikutnya
            for event in daftar:
                tandai_kejadian(event)
            return daftar[-1]
        time.sleep(0.5)
    print('Tidak ada sidik jari terbaca.')
    return None


def verifikasi_sidik_jari(user, perangkat=None):
    # minta sidik jari user untuk otorisasi pembayaran; return (ok, event)
    if perangkat is None:
        perangkat = baca_perangkat()

    finger_id = ''
    if user:
        finger_id = user.get('finger_id', '')
        finger_id = '' if finger_id is None else str(finger_id).strip()
    if finger_id == '':
        print('Akun belum terdaftar sidik jari.')
        return False, None

    mode = str(perangkat.get('mode', MODE_SIMULASI))

    if mode != MODE_SOAP:
        # mode simulasi: cocokkan ID perangkat yang diketik dengan akun
        teks = input('(SIMULASI) Masukkan ID perangkat: ')
        teks = '' if teks is None else str(teks).strip()
        if teks == finger_id:
            event = kejadian_simulasi(teks)
            tandai_kejadian(event)
            return True, event
        print('Sidik jari tidak cocok.')
        return False, None

    # mode soap: polling; event PIN lain tidak dikonsumsi
    print('Menunggu sidik jari pada perangkat X100C...')
    batas = _ke_float(perangkat.get('batas_tunggu_detik',
                                    PERANGKAT_DEFAULT['batas_tunggu_detik']), 20.0)
    mulai = time.time()
    ada_pin_lain = False
    while time.time() - mulai <= batas:
        try:
            daftar = ambil_kejadian_baru(perangkat)
        except (OSError, TimeoutError):
            print(PESAN_GAGAL_KONEKSI)
            return False, None
        for event in daftar:
            pin_event = str(event.get('PIN', '')).strip()
            if pin_event == finger_id:
                tandai_kejadian(event)
                return True, event
            ada_pin_lain = True
        time.sleep(0.5)

    if ada_pin_lain:
        print('Sidik jari tidak cocok.')
    else:
        print('Sidik jari tidak terbaca.')
    return False, None


if __name__ == '__main__':
    # demo read-only: tidak menandai event / tidak mengubah data
    print('--- DEMO FINGERPRINT X100C (read-only) ---')
    perangkat_demo = baca_perangkat()
    mode_demo = str(perangkat_demo.get('mode', MODE_SIMULASI))
    print('Mode perangkat: ' + mode_demo)
    print('Host: ' + str(perangkat_demo.get('host', '')) + ':' +
          str(perangkat_demo.get('port', '')))

    ok_demo, pesan_demo = tes_koneksi(perangkat_demo)
    print('Hasil tes koneksi: ' + pesan_demo)

    if mode_demo == MODE_SOAP and ok_demo:
        try:
            daftar_log = get_attlog(perangkat_demo)
        except (OSError, TimeoutError):
            print(PESAN_GAGAL_KONEKSI)
            daftar_log = []
        print('Jumlah log terbaca: ' + str(len(daftar_log)))
        for kejadian in daftar_log[-5:]:
            print(' - ' + kunci_kejadian(kejadian))
    else:
        contoh = kejadian_simulasi('1001')
        print('Contoh event simulasi: ' + kunci_kejadian(contoh))
