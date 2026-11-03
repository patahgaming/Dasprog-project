import hashlib
import secrets

import data_manager

# panjang salt default (16 karakter hex) dan batas percobaan PIN sebelum akun dikunci
PANJANG_SALT = 16
BATAS_PERCOBAAN_PIN = 3


def GenerateRandomHex(panjang=16):
    # buat salt acak berisi karakter hex (0-9, a-f)
    karakter = '0123456789abcdef'
    hasil = ''
    for _ in range(panjang):
        hasil += secrets.choice(karakter)
    return hasil


def HashPasswordWithSalt(password, existing_salt=None):
    # hitung pin_hash = sha256(str(password) + salt).hexdigest()
    # kalau existing_salt None, buat salt baru dulu
    if existing_salt is None:
        salt = GenerateRandomHex(PANJANG_SALT)
    else:
        salt = str(existing_salt)
    hash_result = hashlib.sha256((str(password) + salt).encode('utf-8')).hexdigest()
    return hash_result, salt


def RegisterUser(username, raw_pin):
    # daftarkan akun customer baru; return True kalau berhasil
    username = '' if username is None else str(username).strip()
    if username == '':
        print('Username tidak boleh kosong!')
        return False

    pin = '' if raw_pin is None else str(raw_pin).strip()
    if not pin.isdigit() or len(pin) < 4:
        print('PIN harus berupa angka minimal 4 digit!')
        return False

    users = data_manager.baca_users()
    if username in users:
        print('Error: Username sudah terdaftar!')
        return False

    pin_hash, salt = HashPasswordWithSalt(pin)
    users[username] = {
        'username': username,
        'pin_hash': pin_hash,
        'salt': salt,
        'balance': 0.0,
        'daily_limit': 500000.0,
        'role': 'customer',
        'is_locked': False,
        'failed_attempts': 0,
        'finger_id': '',
        'transactions': [],
    }
    data_manager.simpan_users(users)
    data_manager.catat_log(username, 'REGISTER', 'akun baru')
    print('Registrasi Berhasil!')
    return True


def LoginUser(username, input_pin):
    # coba login; return dict user kalau berhasil, None kalau gagal
    username = '' if username is None else str(username).strip()
    users = data_manager.baca_users()
    if username not in users:
        print('Username tidak ditemukan.')
        return None

    user = users[username]
    if user.get('is_locked', False):
        print('Akun terblokir karena percobaan PIN salah berulang kali. Hubungi Admin.')
        return None

    hash_input, _ = HashPasswordWithSalt(input_pin, user.get('salt', ''))
    if hash_input == user.get('pin_hash'):
        # login sukses: reset riwayat percobaan salah
        user['failed_attempts'] = 0
        users[username] = user
        data_manager.simpan_users(users)
        data_manager.catat_log(username, 'LOGIN_SUCCESS')
        return user

    # PIN salah: tambah percobaan, kunci akun kalau sudah 3 kali
    user['failed_attempts'] = user.get('failed_attempts', 0) + 1
    print('PIN salah! Percobaan: ' + str(user['failed_attempts']) + '/3')
    if user['failed_attempts'] >= BATAS_PERCOBAAN_PIN:
        user['is_locked'] = True
        print('AKUN DIKUNCI DEMI KEAMANAN.')
        data_manager.catat_log(username, 'ACCOUNT_LOCKED_BRUTEFORCE')
    users[username] = user
    data_manager.simpan_users(users)
    return None


def VerifyPIN(user, input_pin):
    # cek PIN saja (tanpa menambah failed_attempts) -> dipakai saat konfirmasi checkout
    if not user:
        return False
    hash_input, _ = HashPasswordWithSalt(input_pin, user.get('salt', ''))
    return hash_input == user.get('pin_hash')


def LogoutUser(user):
    # catat logout user ke audit log
    if not user:
        return
    data_manager.catat_log(user.get('username', ''), 'LOGOUT')


if __name__ == '__main__':
    # demo singkat (tidak mengubah data/users.json)
    print('--- DEMO AUTH PAYGUARD ---')
    contoh_hash, contoh_salt = HashPasswordWithSalt('123456', '0123456789abcdef')
    print('Salt tetap : ' + contoh_salt)
    print('PIN hash   : ' + contoh_hash)
    akun_demo = {'username': 'demo', 'pin_hash': contoh_hash, 'salt': contoh_salt}
    print('VerifyPIN benar: ' + str(VerifyPIN(akun_demo, '123456')))
    print('VerifyPIN salah: ' + str(VerifyPIN(akun_demo, '000000')))
    print('Contoh salt acak: ' + GenerateRandomHex())
