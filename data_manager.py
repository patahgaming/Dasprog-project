import json
import os
from datetime import datetime

# semua file JSON disimpan di folder data/ di sebelah file ini
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
PRODUCTS_FILE = os.path.join(DATA_DIR, 'products.json')
LOGS_FILE = os.path.join(DATA_DIR, 'logs.json')


def pastikan_data():
    # buat folder data + file kosong kalau belum ada
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.isfile(USERS_FILE):
        tulis_json(USERS_FILE, {})
    if not os.path.isfile(PRODUCTS_FILE):
        tulis_json(PRODUCTS_FILE, {})
    if not os.path.isfile(LOGS_FILE):
        tulis_json(LOGS_FILE, [])


def baca_json(nama_file, bawaan):
    # baca file JSON; kalau belum ada / rusak, kembalikan nilai bawaan
    try:
        with open(nama_file, encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        return bawaan
    except ValueError:
        return bawaan


def tulis_json(nama_file, data):
    # tulis JSON secara aman: tulis ke file sementara lalu ganti file aslinya
    folder = os.path.dirname(nama_file)
    if folder != '' and not os.path.isdir(folder):
        os.makedirs(folder)
    file_sementara = nama_file + '.tmp'
    with open(file_sementara, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(file_sementara, nama_file)


def baca_users():
    return baca_json(USERS_FILE, {})


def simpan_users(users):
    tulis_json(USERS_FILE, users)


def baca_products():
    return baca_json(PRODUCTS_FILE, {})


def simpan_products(products):
    tulis_json(PRODUCTS_FILE, products)


def baca_logs():
    return baca_json(LOGS_FILE, [])


def simpan_logs(logs):
    tulis_json(LOGS_FILE, logs)


def waktu_sekarang():
    # contoh: 2026-10-26T00:15:30
    return datetime.now().isoformat(timespec='seconds')


def catat_log(username, action, detail=''):
    # tambah satu baris audit trail ke logs.json
    logs = baca_logs()
    logs.append({
        'time': waktu_sekarang(),
        'username': username,
        'action': action,
        'detail': detail,
    })
    simpan_logs(logs)


def id_produk_baru(products):
    # cari nomor terbesar dari ID P001, P002, ... lalu +1
    nomor = 0
    for kode in products:
        if kode.startswith('P') and kode[1:].isdigit():
            if int(kode[1:]) > nomor:
                nomor = int(kode[1:])
    return 'P' + str(nomor + 1).zfill(3)


def rupiah(angka):
    # 1212000 -> Rp1.212.000
    angka = int(round(float(angka)))
    if angka < 0:
        return 'Rp-' + f"{abs(angka):,}".replace(',', '.')
    return 'Rp' + f"{angka:,}".replace(',', '.')
