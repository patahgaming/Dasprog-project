import data_manager
import fingerprint
import customer


def CreateProduct():
    # menu 1: tambah produk baru ke katalog
    nama = input("Masukan nama produk: ").strip()
    if nama == '':
        print("Nama produk tidak boleh kosong!")
        return
    harga_teks = input("Masukan harga: ").strip()
    try:
        harga = float(harga_teks)
    except ValueError:
        print("Harga harus berupa angka lebih dari 0!")
        return
    if not (0 < harga < 1000000000000000):
        print("Harga harus berupa angka lebih dari 0!")
        return
    stok_teks = input("Masukan stok: ").strip()
    try:
        stok = int(stok_teks)
    except ValueError:
        print("Stok harus berupa angka bulat minimal 0!")
        return
    if stok < 0:
        print("Stok harus berupa angka bulat minimal 0!")
        return
    kategori = input("Masukan kategori (Needs/Wants): ").strip()
    if kategori != 'Needs' and kategori != 'Wants':
        print("Kategori harus Needs atau Wants!")
        return
    products = data_manager.baca_products()
    produk_id = data_manager.id_produk_baru(products)
    products[produk_id] = {
        "id": produk_id,
        "name": nama,
        "price": harga,
        "stock": stok,
        "category": kategori,
    }
    data_manager.simpan_products(products)
    data_manager.catat_log("admin", "CREATE_PRODUCT", produk_id)
    print("Produk " + produk_id + " '" + nama + "' berhasil ditambahkan.")


def ReadAllProducts():
    # menu 2: tampilkan seluruh katalog produk
    products = data_manager.baca_products()
    print("ID | Nama | Harga | Stok | Kategori")
    if not products:
        print("Katalog kosong.")
        return
    for produk_id in sorted(products):
        produk = products[produk_id]
        print(produk_id + " | " + produk["name"] + " | " +
              data_manager.rupiah(produk["price"]) + " | " +
              str(produk["stock"]) + " | " + produk["category"])


def UpdateProductDetails():
    # menu 3: update harga atau stok produk
    products = data_manager.baca_products()
    produk_id = input("Masukan ID produk: ").strip()
    if produk_id not in products:
        print("ID produk tidak ditemukan.")
        return
    produk = products[produk_id]
    print("Harga saat ini: " + data_manager.rupiah(produk["price"]) +
          ", Stok saat ini: " + str(produk["stock"]))
    pilih = input("Pilih yang diupdate (1=harga, 2=stok): ").strip()
    if pilih != '1' and pilih != '2':
        print("Pilihan tidak valid!")
        return
    nilai_teks = input("Masukan nilai baru: ").strip()
    if pilih == '1':
        try:
            harga_baru = float(nilai_teks)
        except ValueError:
            print("Nilai baru tidak valid!")
            return
        if not (0 < harga_baru < 1000000000000000):
            print("Nilai baru tidak valid!")
            return
        produk["price"] = harga_baru
    else:
        try:
            stok_baru = int(nilai_teks)
        except ValueError:
            print("Nilai baru tidak valid!")
            return
        if stok_baru < 0:
            print("Nilai baru tidak valid!")
            return
        produk["stock"] = stok_baru
    data_manager.simpan_products(products)
    data_manager.catat_log("admin", "UPDATE_PRODUCT", produk_id)
    print("Produk " + produk_id + " berhasil diupdate.")


def DeleteProduct():
    # menu 4: hapus produk dari katalog
    products = data_manager.baca_products()
    produk_id = input("Masukan ID produk: ").strip()
    if produk_id not in products:
        print("ID produk tidak ditemukan.")
        return
    produk = products[produk_id]
    jawab = input("Yakin ingin menghapus '" + produk["name"] + "'? (y/n): ").strip().lower()
    if jawab == 'y' or jawab == 'ya':
        del products[produk_id]
        data_manager.simpan_products(products)
        data_manager.catat_log("admin", "DELETE_PRODUCT", produk_id)
        print("Produk " + produk_id + " berhasil dihapus.")
    else:
        print("Penghapusan dibatalkan.")


def DisplaySystemLogs():
    # menu 5: tampilkan 20 audit log terakhir
    print("--- AUDIT SYSTEM LOGS (20 TERAKHIR) ---")
    logs = data_manager.baca_logs()
    if not logs:
        print("Belum ada log.")
        return
    for log in logs[-20:]:
        detail = log.get("detail", "")
        if detail:
            print("[" + log["time"] + "] " + log["username"] + ": " +
                  log["action"] + " - " + detail)
        else:
            print("[" + log["time"] + "] " + log["username"] + ": " + log["action"])


def UnlockCustomerAccount():
    # menu 6: buka blokir akun pelanggan yang terkunci
    users = data_manager.baca_users()
    username = input("Masukan username pelanggan: ").strip()
    if username not in users:
        print("Username tidak ditemukan.")
        return
    user = users[username]
    if not user["is_locked"]:
        print("Akun tidak sedang terblokir.")
        return
    user["is_locked"] = False
    user["failed_attempts"] = 0
    data_manager.simpan_users(users)
    data_manager.catat_log("admin", "UNLOCK_ACCOUNT", username)
    print("Akun '" + username + "' berhasil dibuka blokirnya.")


def DaftarkanSidikJari():
    # submenu 7.1: petakan username PayGuard ke ID perangkat (PIN X100C)
    users = data_manager.baca_users()
    username = input("Masukan username: ").strip()
    if username not in users:
        print("User tidak ditemukan.")
        return
    pin = input("Masukan ID perangkat (PIN X100C): ").strip()
    if pin == '':
        print("ID perangkat tidak boleh kosong.")
        return
    if not pin.isdigit():
        print("ID perangkat harus berupa angka.")
        return
    for nama_lain in users:
        if nama_lain == username:
            continue
        if users[nama_lain].get("finger_id", "") == pin:
            print("ID perangkat sudah dipakai akun '" + nama_lain + "'.")
            return
    perangkat = fingerprint.baca_perangkat()
    if perangkat.get("mode", "simulasi") == "soap":
        # mode soap: pastikan PIN benar-benar ada di mesin X100C
        try:
            info = fingerprint.get_user_info(pin, perangkat)
        except OSError:
            print("Peringatan: perangkat tidak dapat dicek. Pendaftaran disimpan.")
        else:
            if info is None:
                print("Peringatan: PIN tidak ditemukan di perangkat. Pendaftaran disimpan.")
    users[username]["finger_id"] = pin
    data_manager.simpan_users(users)
    data_manager.catat_log("admin", "FINGER_ENROLL", username + ":" + pin)
    print("Sidik jari akun '" + username + "' terdaftar dengan ID perangkat " + pin + ".")


def HapusSidikJari():
    # submenu 7.2: hapus pendaftaran sidik jari sebuah akun
    users = data_manager.baca_users()
    username = input("Masukan username: ").strip()
    if username not in users:
        print("User tidak ditemukan.")
        return
    if users[username].get("finger_id", "") == "":
        print("Akun tidak punya pendaftaran sidik jari.")
        return
    users[username]["finger_id"] = ""
    data_manager.simpan_users(users)
    data_manager.catat_log("admin", "FINGER_UNENROLL", username)
    print("Pendaftaran sidik jari akun '" + username + "' dihapus.")


def LihatDaftarSidikJari():
    # submenu 7.3: tampilkan semua akun yang punya ID perangkat
    users = data_manager.baca_users()
    print("--- DAFTAR SIDIK JARI ---")
    ada = False
    for username in sorted(users):
        pin = users[username].get("finger_id", "")
        if pin != '':
            print(username + " -> PIN " + pin)
            ada = True
    if not ada:
        print("Belum ada akun terdaftar sidik jari.")


def TesKoneksiX100C():
    # submenu 7.4: cek koneksi ke mesin X100C (mode soap)
    perangkat = fingerprint.baca_perangkat()
    if perangkat.get("mode", "simulasi") == "simulasi":
        print("Mode simulasi: perangkat tidak dihubungi.")
        return
    ok, pesan = fingerprint.tes_koneksi(perangkat)
    if ok:
        if pesan.startswith("Koneksi X100C OK:"):
            print(pesan)
        else:
            print("Koneksi X100C OK: " + pesan)
    else:
        if pesan.startswith("Koneksi X100C GAGAL:"):
            print(pesan)
        else:
            print("Koneksi X100C GAGAL: " + pesan)


def MenuSidikJari():
    # submenu admin: kelola pendaftaran sidik jari X100C
    while 1:
        print("=== KELOLA SIDIK JARI (X100C) ===")
        print("1. Daftarkan sidik jari ke akun")
        print("2. Hapus pendaftaran sidik jari")
        print("3. Lihat daftar sidik jari")
        print("4. Tes koneksi X100C")
        print("5. Kembali")
        pilih = input("Pilih menu (1-5): ").strip()
        if pilih == '1':
            DaftarkanSidikJari()
        elif pilih == '2':
            HapusSidikJari()
        elif pilih == '3':
            LihatDaftarSidikJari()
        elif pilih == '4':
            TesKoneksiX100C()
        elif pilih == '5':
            return
        else:
            print("Pilihan tidak valid!")


def LihatKeranjangTertahan():
    # submenu 8.1: tampilkan semua keranjang yang ditahan
    daftar = customer.BacaKeranjangTertahan()
    if not daftar:
        print("Tidak ada keranjang tertahan.")
        return
    for record in daftar:
        potongan_item = []
        for item in record.get("items", []):
            potongan_item.append(str(item.get("name", "")) + " x" +
                                 str(item.get("qty", 0)))
        print(str(record.get("id", "")) + " | " +
              str(record.get("username", "")) + " | Total " +
              data_manager.rupiah(record.get("total", 0)) + " | percobaan " +
              str(record.get("percobaan", 1)) + " | " + ", ".join(potongan_item))


def BatalkanKeranjangTertahan():
    # submenu 8.2: batalkan hold lalu kembalikan stok produk
    daftar = customer.BacaKeranjangTertahan()
    record_id = input("Masukan ID keranjang tertahan: ").strip()
    record = None
    for entri in daftar:
        if str(entri.get("id", "")) == record_id:
            record = entri
            break
    if record is None:
        print("ID keranjang tertahan tidak ditemukan.")
        return
    jawab = input("Yakin batalkan dan kembalikan stok? (y/n): ").strip().lower()
    if jawab == 'y' or jawab == 'ya':
        customer.KembalikanStokKeranjang(record)
        customer.HapusKeranjangTertahan(record["id"])
        data_manager.catat_log("admin", "HOLD_CANCEL", record["id"])
        print("Keranjang " + str(record["id"]) + " dibatalkan, stok dikembalikan.")
    else:
        print("Pembatalan dibatalkan.")


def MenuKeranjangTertahan():
    # submenu admin: kelola keranjang yang ditahan karena sidik jari gagal
    while 1:
        print("=== KELOLA KERANJANG TERTAHAN ===")
        print("1. Lihat keranjang tertahan")
        print("2. Batalkan & kembalikan stok")
        print("3. Kembali")
        pilih = input("Pilih menu (1-3): ").strip()
        if pilih == '1':
            LihatKeranjangTertahan()
        elif pilih == '2':
            BatalkanKeranjangTertahan()
        elif pilih == '3':
            return
        else:
            print("Pilihan tidak valid!")


def AdminMenu():
    # menu admin/merchant: CRUD produk, audit log, buka blokir akun
    while 1:
        print("=== MENU ADMIN / MERCHANT ===")
        print("1. Tambah Produk Baru (Create)")
        print("2. Tampilkan Semua Produk (Read)")
        print("3. Update Harga / Stok Produk (Update)")
        print("4. Hapus Produk dari Katalog (Delete)")
        print("5. Lihat Audit System Logs")
        print("6. Buka Blokir Akun Pelanggan")
        print("7. Kelola Sidik Jari (X100C)")
        print("8. Kelola Keranjang Tertahan")
        print("9. Logout Admin")
        pilih = input("Pilih menu (1-9): ").strip()
        if pilih == '1':
            CreateProduct()
        elif pilih == '2':
            ReadAllProducts()
        elif pilih == '3':
            UpdateProductDetails()
        elif pilih == '4':
            DeleteProduct()
        elif pilih == '5':
            DisplaySystemLogs()
        elif pilih == '6':
            UnlockCustomerAccount()
        elif pilih == '7':
            MenuSidikJari()
        elif pilih == '8':
            MenuKeranjangTertahan()
        elif pilih == '9':
            # sesuai §5, aksi LOGOUT wajib tercatat di logs.json
            data_manager.catat_log("admin", "LOGOUT")
            print("Logout berhasil.")
            return
        else:
            print("Pilihan tidak valid!")


if __name__ == "__main__":
    AdminMenu()
