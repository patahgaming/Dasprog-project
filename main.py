import data_manager
import auth
import admin
import customer
import fingerprint


def SplashScreen():
    # tampilan pembuka PayGuard
    print("=" * 44)
    print("     PAYGUARD CLI - E-WALLET & RISK SHIELD")
    print("=" * 44)


def LoginFlow():
    # alur login: minta username + PIN, lalu buka menu sesuai role
    print("--- LOGIN ---")
    username = input("Username: ").strip()
    pin = input("PIN: ").strip()
    user = auth.LoginUser(username, pin)
    if user is None:
        # pesan gagal sudah dicetak oleh LoginUser, kembali ke menu utama
        return
    if user["role"] == "admin":
        print("Login berhasil! Selamat datang, admin.")
        admin.AdminMenu()
    else:
        print("Login berhasil! Selamat datang, " + user["username"] + ".")
        customer.CustomerMenu(user)


def LoginFingerFlow():
    # alur login sidik jari X100C: tap jari menggantikan username + PIN
    print("--- LOGIN SIDIK JARI (X100C) ---")
    event = fingerprint.tunggu_sidik_jari()
    if event is None:
        # prompt/menunggu/pesan tidak terbaca sudah dicetak oleh fingerprint
        return
    pin = event.get("PIN")
    if pin is None:
        pin = event.get("pin", "")
    user = fingerprint.cari_user_dari_pin(pin)
    if user is None:
        print("Sidik jari belum terdaftar. Hubungi admin.")
        return
    if user["is_locked"]:
        print("Akun terblokir karena percobaan PIN salah berulang kali. Hubungi Admin.")
        return
    print("Sidik jari dikenali: " + user["username"] + ".")
    if user["role"] == "admin":
        print("Login berhasil! Selamat datang, admin.")
        admin.AdminMenu()
    else:
        customer.CustomerMenu(user, metode_login='sidik_jari')


def RegisterFlow():
    # alur register: minta username + PIN baru lalu panggil RegisterUser
    print("--- REGISTER ---")
    username = input("Username baru: ").strip()
    pin = input("PIN baru: ").strip()
    auth.RegisterUser(username, pin)


def MainMenu():
    # menu utama: diulang sampai pengguna memilih keluar
    while 1:
        print("=== MENU UTAMA ===")
        print("1. Login")
        print("2. Register")
        print("3. Login Sidik Jari (X100C)")
        print("4. Keluar")
        pilih = input("Pilih menu (1-4): ").strip()
        if pilih == '1':
            LoginFlow()
        elif pilih == '2':
            RegisterFlow()
        elif pilih == '3':
            LoginFingerFlow()
        elif pilih == '4':
            print("Terima kasih telah menggunakan PayGuard.")
            return
        else:
            print("Pilihan tidak valid!")


def main():
    # program utama: siapkan file data, splash, lalu menu utama
    data_manager.pastikan_data()
    SplashScreen()
    MainMenu()


if __name__ == "__main__":
    main()
