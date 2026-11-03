# customer.py - menu pelanggan PayGuard CLI
# Isi: lihat saldo, cari/belanja produk, pengurutan katalog,
# keranjang & checkout (PIN atau sidik jari X100C, termasuk hold keranjang saat
# sidik jari gagal), riwayat transaksi & track record, logout.
# Top up saldo hanya dapat dilakukan admin (tidak ada di menu pelanggan).
# Gaya mengikuti project cashless: fungsi prosedural + TUI, stdlib saja.

import os
from datetime import datetime

import fingerprint
from data_manager import (DATA_DIR, baca_json, baca_products, baca_users, catat_log,
                          pastikan_data, rupiah, simpan_products, simpan_users,
                          tulis_json)
from risk_assistant import EvaluatePurchaseRisk, DisplayRiskShieldNotice
from auth import VerifyPIN, LogoutUser

# keranjang belanja adalah state sesi (di memori modul), tidak disimpan ke users.json
keranjang_sesi = []
# keranjang yang ditahan karena sidik jari gagal disimpan persisten di data/keranjang.json
KERANJANG_FILE = os.path.join(DATA_DIR, 'keranjang.json')


def FormatProductRow(product):
    # satu baris katalog: <id> | <nama> | <Rp harga> | stok <stok> | <kategori>
    return (product['id'] + ' | ' + product['name'] + ' | ' + rupiah(product['price']) +
            ' | stok ' + str(product['stock']) + ' | ' + product['category'])


def GetUserCart(current_user):
    # kembalikan keranjang milik sesi yang sedang berjalan
    return keranjang_sesi


def AddToCart(product, qty):
    # tambah produk ke keranjang; kalau id-nya sudah ada, jumlahnya digabung
    for item in keranjang_sesi:
        if item['id'] == product['id']:
            item['qty'] = item['qty'] + int(qty)
            return
    keranjang_sesi.append({
        'id': product['id'],
        'name': product['name'],
        'price': float(product['price']),
        'qty': int(qty),
    })


def ClearUserCart(current_user):
    # kosongkan keranjang sesi
    del keranjang_sesi[:]


def BacaKeranjangTertahan():
    # baca daftar keranjang yang ditahan dari data/keranjang.json
    daftar = baca_json(KERANJANG_FILE, [])
    if not isinstance(daftar, list):
        return []
    return daftar


def SimpanKeranjangTertahan(daftar):
    # simpan daftar keranjang tertahan secara atomic lewat data_manager
    tulis_json(KERANJANG_FILE, daftar)


def CariKeranjangTertahan(username):
    # cari hold terbaru (status tertahan) milik user; None kalau tidak ada
    username = '' if username is None else str(username).strip()
    hasil = None
    for record in BacaKeranjangTertahan():
        if str(record.get('username', '')) != username:
            continue
        if str(record.get('status', 'tertahan')) != 'tertahan':
            continue
        # bandingkan waktu ISO; kalau sama, entri yang lebih akhir menang
        if hasil is None or str(record.get('waktu', '')) >= str(hasil.get('waktu', '')):
            hasil = record
    return hasil


def HapusKeranjangTertahan(record_id):
    # hapus entri hold berdasarkan id; return True kalau ada yang terhapus
    record_id = str(record_id)
    daftar = BacaKeranjangTertahan()
    sisa = []
    terhapus = False
    for record in daftar:
        if not terhapus and str(record.get('id', '')) == record_id:
            terhapus = True
            continue
        sisa.append(record)
    if terhapus:
        SimpanKeranjangTertahan(sisa)
    return terhapus


def TahanKeranjang(current_user, cart, total):
    # kurangi stok, simpan keranjang sebagai hold, catat log; return record hold
    products = baca_products()
    for item in cart:
        kode = item['id']
        if kode in products:
            sisa_stok = int(products[kode]['stock']) - int(item['qty'])
            if sisa_stok < 0:
                sisa_stok = 0
            products[kode]['stock'] = sisa_stok
    simpan_products(products)

    sekarang = datetime.now()
    record = {
        'id': 'HOLD-' + sekarang.strftime('%Y%m%d%H%M%S'),
        'username': current_user['username'],
        'waktu': sekarang.isoformat(timespec='seconds'),
        'items': [],
        'total': float(total),
        'percobaan': 1,
        'status': 'tertahan',
    }
    for item in cart:
        record['items'].append({
            'id': item['id'],
            'name': item['name'],
            'price': float(item['price']),
            'qty': int(item['qty']),
        })
    daftar = BacaKeranjangTertahan()
    daftar.append(record)
    SimpanKeranjangTertahan(daftar)
    catat_log(current_user['username'], 'HOLD_CART',
              record['id'] + ':' + str(record['total']))
    return record


def TambahPercobaanKeranjang(record):
    # tambah jumlah percobaan tap sidik jari yang gagal pada hold ini
    if not record:
        return
    record_id = str(record.get('id', ''))
    daftar = BacaKeranjangTertahan()
    for entri in daftar:
        if str(entri.get('id', '')) == record_id:
            entri['percobaan'] = int(entri.get('percobaan', 1)) + 1
            record['percobaan'] = entri['percobaan']
            SimpanKeranjangTertahan(daftar)
            return
    # entri tidak ada di file (mis. record dibuat manual): cukup naikkan di memori
    record['percobaan'] = int(record.get('percobaan', 1)) + 1


def KembalikanStokKeranjang(record):
    # kembalikan stok produk dari hold yang dibatalkan (dipakai admin)
    if not record:
        return
    products = baca_products()
    for item in record.get('items', []):
        kode = item.get('id', '')
        if kode in products:
            products[kode]['stock'] = int(products[kode]['stock']) + int(item.get('qty', 0))
    simpan_products(products)


def CreateReceipt(cart, total_price, risk_score):
    # buat record transaksi (append-only) dari isi keranjang
    sekarang = datetime.now()
    record = {
        'id': 'TRX-' + sekarang.strftime('%Y%m%d%H%M%S'),
        'date': sekarang.isoformat(timespec='seconds'),
        'total': float(total_price),
        'risk_score': int(risk_score),
        'items': [],
    }
    for item in cart:
        record['items'].append({
            'id': item['id'],
            'name': item['name'],
            'price': float(item['price']),
            'qty': int(item['qty']),
        })
    return record


def SaveTransactionToUserHistory(current_user, record):
    # tambahkan transaksi ke riwayat user lalu simpan ke users.json
    if 'transactions' not in current_user:
        current_user['transactions'] = []
    current_user['transactions'].append(record)
    users = baca_users()
    users[current_user['username']] = current_user
    simpan_users(users)


def LihatSaldo(current_user):
    # menu 1: tampilkan saldo e-wallet saat ini (top up hanya oleh admin)
    print('Saldo Anda: ' + rupiah(current_user['balance']) + '.')


def SearchAndBrowseMarketplace(current_user):
    # menu 2: cari produk berdasarkan kata kunci lalu masukkan ke keranjang
    kata_kunci = input('Masukan kata kunci produk: ').strip().lower()
    products = baca_products()
    hasil = []
    for kode in products:
        product = products[kode]
        if kata_kunci in product['name'].lower() or kata_kunci in product['id'].lower():
            hasil.append(product)
    if len(hasil) == 0:
        print('Produk tidak ditemukan.')
        return
    for product in hasil:
        print(FormatProductRow(product))

    id_pilihan = input('Masukan ID produk yang ingin dibeli (0 untuk kembali): ').strip()
    if id_pilihan == '0':
        return
    product = None
    for kode in products:
        if products[kode]['id'].lower() == id_pilihan.lower():
            product = products[kode]
            break
    if product is None:
        print('ID produk tidak ditemukan.')
        return
    if int(product['stock']) <= 0:
        print('Stok produk habis!')
        return

    teks_jumlah = input('Masukan jumlah: ').strip()
    try:
        jumlah = int(teks_jumlah)
    except ValueError:
        print('Jumlah tidak valid atau melebihi stok!')
        return
    if jumlah <= 0 or jumlah > int(product['stock']):
        print('Jumlah tidak valid atau melebihi stok!')
        return
    AddToCart(product, jumlah)
    print("'" + product['name'] + "' x" + str(jumlah) + ' ditambahkan ke keranjang.')


def SortCatalogInteractive():
    # menu 3: tampilkan katalog terurut sesuai pilihan pengguna
    print('=== PENGURUTAN KATALOG ===')
    print('1. Harga termurah')
    print('2. Harga termahal')
    print('3. Nama A-Z')
    print('4. Stok terbanyak')
    pilih = input('Pilih pengurutan (1-4): ').strip()
    products = baca_products()
    daftar = []
    for kode in products:
        daftar.append(products[kode])
    if pilih == '1':
        daftar.sort(key=lambda product: float(product['price']))
    elif pilih == '2':
        daftar.sort(key=lambda product: float(product['price']), reverse=True)
    elif pilih == '3':
        daftar.sort(key=lambda product: product['name'].lower())
    elif pilih == '4':
        daftar.sort(key=lambda product: int(product['stock']), reverse=True)
    else:
        print('Pilihan tidak valid!')
        return
    for product in daftar:
        print(FormatProductRow(product))


def CheckoutProcess(current_user, metode_login='pin', keranjang_tertahan=None):
    # menu 4: tampilkan keranjang, validasi saldo -> risk shield -> otorisasi, lalu bayar
    # otorisasi: PIN untuk login biasa, sidik jari X100C untuk login sidik jari
    # keranjang_tertahan diisi kalau melanjutkan hold yang dibuat saat sidik jari gagal
    if keranjang_tertahan is None:
        cart = GetUserCart(current_user)
    else:
        cart = []
        for item in keranjang_tertahan.get('items', []):
            cart.append({
                'id': item.get('id', ''),
                'name': item.get('name', ''),
                'price': float(item.get('price', 0)),
                'qty': int(item.get('qty', 0)),
            })
    print('=== KERANJANG BELANJA ===')
    if len(cart) == 0:
        print('Keranjang belanja kosong!')
        return
    total = 0.0
    for item in cart:
        subtotal = float(item['price']) * int(item['qty'])
        total = total + subtotal
        print(item['name'] + ' x' + str(item['qty']) + ' = ' + rupiah(subtotal))
    print('Total: ' + rupiah(total))

    # validasi saldo dulu; kalau gagal, data tidak boleh berubah sama sekali
    saldo = float(current_user['balance'])
    if saldo < total:
        print('Checkout Gagal: Saldo e-wallet tidak mencukupi!')
        print('Saldo: ' + rupiah(saldo) + ' | Total: ' + rupiah(total))
        return

    # checkout selalu memakai data produk terbaru dari products.json
    products = baca_products()
    item_categories = []
    for item in cart:
        if item['id'] in products:
            item_categories.append(products[item['id']]['category'])
        else:
            item_categories.append('Needs')
    risk_score, warnings = EvaluatePurchaseRisk(current_user, total, item_categories)
    proceed = DisplayRiskShieldNotice(risk_score, warnings)
    if not proceed:
        print('Transaksi dibatalkan oleh pengguna/Risk Shield.')
        return

    # otorisasi pembayaran sebagai langkah terakhir sebelum data diubah
    if metode_login == 'sidik_jari':
        # jalur login sidik jari: konfirmasi lewat mesin X100C, tanpa mengetik PIN
        print('Tempelkan sidik jari untuk mengotorisasi pembayaran...')
        berhasil, _ = fingerprint.verifikasi_sidik_jari(current_user)
        if not berhasil:
            if keranjang_tertahan is not None:
                # gagal lagi saat melanjutkan hold: percobaan bertambah, hold tetap
                TambahPercobaanKeranjang(keranjang_tertahan)
                print('Sidik jari gagal lagi. Belanjaan tetap ditahan (percobaan ke-' +
                      str(int(keranjang_tertahan.get('percobaan', 1))) + ').')
                return
            # gagal pada percobaan pertama: belanjaan ditahan, stok langsung dikurangi
            TahanKeranjang(current_user, cart, total)
            ClearUserCart(current_user)
            print('Sidik jari gagal. Belanjaan ditahan di keranjang dan stok sudah dikurangi.')
            print('Coba lagi lewat menu 4 untuk melanjutkan pembayaran.')
            return
        print('Pembayaran diotorisasi dengan sidik jari.')
        kode_log = 'CHECKOUT_FINGER_RP_'
    else:
        # jalur login normal: konfirmasi PIN e-wallet
        pin = input('Masukan PIN E-Wallet untuk konfirmasi pembayaran: ').strip()
        if not VerifyPIN(current_user, pin):
            print('PIN Salah! Transaksi Dibatalkan.')
            return
        kode_log = 'CHECKOUT_SUCCESS_RP_'

    # semua otorisasi lolos: potong saldo & stok, catat transaksi, kosongkan keranjang
    if keranjang_tertahan is None:
        for item in cart:
            kode = item['id']
            if kode in products:
                sisa_stok = int(products[kode]['stock']) - int(item['qty'])
                if sisa_stok < 0:
                    sisa_stok = 0
                products[kode]['stock'] = sisa_stok
        simpan_products(products)
    else:
        # stok sudah dipotong saat hold dibuat -> jangan dipotong lagi, hapus hold
        HapusKeranjangTertahan(keranjang_tertahan.get('id', ''))
    current_user['balance'] = saldo - total
    record = CreateReceipt(cart, total, risk_score)
    SaveTransactionToUserHistory(current_user, record)  # di dalamnya menyimpan users
    ClearUserCart(current_user)
    total_bulat = int(round(total))
    catat_log(current_user['username'], kode_log + str(total_bulat), record['id'])

    # cetak resi; daftar item diambil dari record karena keranjang sudah dikosongkan
    print('TRANSAKSI BERHASIL! Resi pembayaran telah diterbitkan.')
    print('--- RESI PEMBAYARAN ---')
    print('ID: ' + record['id'])
    print('Tanggal: ' + record['date'])
    for item in record['items']:
        print(item['name'] + ' x' + str(item['qty']) + ' = ' +
              rupiah(float(item['price']) * int(item['qty'])))
    print('Total: ' + rupiah(record['total']))
    print('Skor Risiko: ' + str(record['risk_score']))
    print('Sisa Saldo: ' + rupiah(current_user['balance']))


def ViewTransactionHistory(current_user):
    # menu 5: daftar transaksi + track record pengeluaran
    transaksi = current_user.get('transactions', [])
    if len(transaksi) == 0:
        print('Belum ada transaksi.')
        return
    print('=== RIWAYAT TRANSAKSI ===')
    for trx in transaksi:
        daftar_item = []
        for item in trx['items']:
            daftar_item.append(item['name'])
        print('- ' + trx['date'] + ' | ' + trx['id'] + ' | Total ' + rupiah(trx['total']) +
              ' | Risiko ' + str(trx['risk_score']) + ' | ' + ', '.join(daftar_item))
    print('=== TRACK RECORD ===')
    jumlah_transaksi = len(transaksi)
    total_pengeluaran = 0.0
    for trx in transaksi:
        total_pengeluaran = total_pengeluaran + float(trx['total'])
    rata_rata = total_pengeluaran / jumlah_transaksi
    print('Jumlah transaksi: ' + str(jumlah_transaksi))
    print('Total pengeluaran: ' + rupiah(total_pengeluaran))
    print('Rata-rata transaksi: ' + rupiah(rata_rata))


def CustomerMenu(current_user, metode_login='pin'):
    # menu utama pelanggan, diulang sampai logout
    # metode_login diteruskan ke checkout: 'pin' (biasa) atau 'sidik_jari' (X100C)
    while 1:
        print('=== MENU PELANGGAN ===')
        print('1. Lihat Saldo')
        print('2. Cari & Belanja Produk')
        print('3. Pengurutan Katalog')
        print('4. Lihat Keranjang & Checkout')
        print('5. Riwayat Transaksi & Track Record')
        print('6. Logout')
        pilih = input('Pilih menu (1-6): ').strip()
        if pilih == '1':
            LihatSaldo(current_user)
        elif pilih == '2':
            SearchAndBrowseMarketplace(current_user)
        elif pilih == '3':
            SortCatalogInteractive()
        elif pilih == '4':
            # kalau keranjang memori kosong tapi user punya hold, tawarkan lanjut bayar
            keranjang = GetUserCart(current_user)
            hold = None
            if len(keranjang) == 0:
                hold = CariKeranjangTertahan(current_user['username'])
            if hold is not None:
                print('Ada keranjang tertahan atas nama ' + str(hold.get('username', '')) +
                      ': ' + str(hold.get('id', '')) + ' total ' +
                      rupiah(hold.get('total', 0)) + '.')
                jawab = input('Lanjutkan pembayaran sekarang? (y/n): ').strip().lower()
                if jawab == 'y':
                    CheckoutProcess(current_user, metode_login, keranjang_tertahan=hold)
                # jawaban selain 'y' -> kembali ke menu, hold tetap tersimpan
            else:
                CheckoutProcess(current_user, metode_login)
        elif pilih == '5':
            ViewTransactionHistory(current_user)
        elif pilih == '6':
            ClearUserCart(current_user)
            LogoutUser(current_user)
            print('Logout berhasil.')
            return
        else:
            print('Pilihan tidak valid!')


if __name__ == '__main__':
    # demo singkat: jalankan menu pelanggan untuk akun contoh budi
    pastikan_data()
    data_users = baca_users()
    if 'budi' in data_users:
        CustomerMenu(data_users['budi'])
    else:
        print('Akun contoh tidak ditemukan. Jalankan main.py terlebih dahulu.')
