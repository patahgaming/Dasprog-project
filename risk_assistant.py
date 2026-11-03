from datetime import datetime


def CalculateTodayExpenses(transactions):
    # jumlah total transaksi yang tanggalnya (date[:10]) sama dengan hari ini
    hari_ini = datetime.now().strftime('%Y-%m-%d')
    total = 0.0
    if transactions is None:
        return total
    for transaksi in transactions:
        tanggal = str(transaksi.get('date', ''))[:10]
        if tanggal == hari_ini:
            total += float(transaksi.get('total', 0))
    return total


def EvaluatePurchaseRisk(user, total_cart_value, item_categories):
    # hitung skor risiko checkout dari 3 indikator, return (risk_score, warnings)
    balance = float(user.get('balance', 0) or 0)
    daily_limit = float(user.get('daily_limit', 0) or 0)
    total_cart_value = float(total_cart_value)
    today_spent = CalculateTodayExpenses(user.get('transactions', []))
    remaining_after = balance - total_cart_value

    risk_score = 0
    warnings = []

    # indikator 1: sisa saldo setelah transaksi di bawah 30% saldo
    if remaining_after < 0.3 * balance:
        risk_score += 2
        warnings.append('Transaksi ini menghabiskan lebih dari 70% sisa saldomu.')

    # indikator 2: pengeluaran hari ini + transaksi melewati limit harian
    if today_spent + total_cart_value > daily_limit:
        risk_score += 3
        warnings.append('Pembelian ini akan melampaui limit anggaran harianmu!')

    # indikator 3: beli barang Wants saat sisa saldo di bawah Rp100.000
    if item_categories is not None and 'Wants' in item_categories:
        if remaining_after < 100000:
            risk_score += 2
            warnings.append('Kamu membeli barang tersier saat saldo mendekati batas minimum.')

    return risk_score, warnings


def DisplayRiskShieldNotice(risk_score, warnings):
    # tampilkan banner Risk Shield; return True kalau transaksi boleh dilanjutkan
    print('=' * 59)
    print(' ' * 14 + 'PAYGUARD FINANCIAL RISK SHIELD')
    print('=' * 59)

    if risk_score == 0:
        print('[STATUS: AMAN] Kondisi keuanganmu stabil untuk transaksi ini.')
        return True

    if risk_score <= 3:
        print('[STATUS: PERINGATAN SEDANG]')
        if warnings:
            for pesan in warnings:
                print(' - ' + pesan)
        jawab = input('Apakah kamu yakin tetap ingin melanjutkan checkout? (y/n)')
        return jawab.strip().lower() == 'y'

    print('[STATUS: RISIKO TINGGI / IMPULSIVE BUYING DETECTED]')
    if warnings:
        for pesan in warnings:
            print(' - ' + pesan)
    print('Rekomendasi AI: Tunda transaksi ini demi kesehatan finansialmu.')
    jawab = input("Ketik 'SAYA YAKIN' untuk memaksa transaksi:")
    return jawab.strip() == 'SAYA YAKIN'


if __name__ == '__main__':
    # demo singkat: hitung pengeluaran hari ini + evaluasi risiko akun contoh
    print('--- DEMO RISK ASSISTANT PAYGUARD ---')
    hari_ini = datetime.now().strftime('%Y-%m-%d')
    contoh_transaksi = [
        {'id': 'TRX-1', 'date': hari_ini + 'T08:00:00', 'total': 25000.0},
        {'id': 'TRX-2', 'date': '2026-10-20T10:15:00', 'total': 14000.0},
    ]
    print('Pengeluaran hari ini: ' + str(CalculateTodayExpenses(contoh_transaksi)))

    akun_demo = {
        'username': 'demo',
        'balance': 500000.0,
        'daily_limit': 500000.0,
        'transactions': contoh_transaksi,
    }
    skor, peringatan = EvaluatePurchaseRisk(akun_demo, 30000.0, ['Needs'])
    print('Skor risiko: ' + str(skor))
    for pesan in peringatan:
        print(' - ' + pesan)
    DisplayRiskShieldNotice(skor, peringatan)
