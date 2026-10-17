import csv
import datetime
import os
import re
import sys

import openpyxl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import daily_update as updater

PAGE_URL = 'https://www.jpx.co.jp/markets/statistics-equities/margin/04.html'
SITE_URL = 'https://www.jpx.co.jp'
FILE_LINK = re.compile(r'href="([^"]*?/(\d{8})_mtcurrent\.xlsx)"')
OUTPUT_CSV = os.path.join(BASE_DIR, 'data', 'quick_weekly_calc.csv')
WORKBOOK_PATH = os.path.join(updater.RAW_DIR, 'mtcurrent_temp.xlsx')
FIRST_DATE = '20260925'
EXPECTED_LABELS = {'B14': '信用取引残高合計', 'B16': '社内対当', 'B17': '貸借取引残高', 'B19': '自己貸株・自己融資', 'D15': '金額'}
CELL_AMOUNT_TOTAL = 'G15'
CELL_INTERNAL_SHARES = 'G16'
CELL_LOAN_SHARES = 'G17'
CELL_LOAN_AMOUNT = 'G18'
CELL_OWN_SHARES = 'G19'
CELL_OWN_AMOUNT = 'G20'


def load_saved():
    if not os.path.exists(OUTPUT_CSV):
        return {}
    with open(OUTPUT_CSV, encoding='utf-8-sig') as file:
        return {row['date']: float(row['quick']) for row in csv.DictReader(file)}


def save(values):
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['date', 'quick'])
        for date in sorted(values):
            writer.writerow([date, values[date]])


def compute_value(path):
    sheet = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    for cell, label in EXPECTED_LABELS.items():
        if label not in str(sheet[cell].value):
            raise ValueError(f'想定と違うレイアウトです: {cell} = {sheet[cell].value}')
    amount_total = float(sheet[CELL_AMOUNT_TOTAL].value)
    loan_amount = float(sheet[CELL_LOAN_AMOUNT].value)
    own_amount = float(sheet[CELL_OWN_AMOUNT].value)
    finance_shares = float(sheet[CELL_LOAN_SHARES].value) + float(sheet[CELL_OWN_SHARES].value)
    average_price = (loan_amount + own_amount) / finance_shares
    cost = average_price * float(sheet[CELL_INTERNAL_SHARES].value) + loan_amount + own_amount
    return round((cost - amount_total) / amount_total * 100, 3)


def main():
    saved = load_saved()
    fetcher = updater.Fetcher()
    try:
        page = fetcher.get(PAGE_URL)
        if page is None:
            print('JPXのページを取得できませんでした。')
            return
        links = {match.group(2): SITE_URL + match.group(1) if match.group(1).startswith('/') else match.group(1) for match in FILE_LINK.finditer(page.decode('utf-8', errors='ignore'))}
        added = []
        for date in sorted(links):
            iso = f'{date[:4]}-{date[4:6]}-{date[6:]}'
            if date < FIRST_DATE or iso in saved:
                continue
            body = fetcher.get(links[date])
            if body is None:
                continue
            with open(WORKBOOK_PATH, 'wb') as file:
                file.write(body)
            try:
                saved[iso] = compute_value(WORKBOOK_PATH)
                added.append(iso)
            except (ValueError, TypeError, KeyError) as error:
                print(f'{iso}: 計算できませんでした ({error})')
            finally:
                os.remove(WORKBOOK_PATH)
        save(saved)
        print(f'QUICK方式(週次): 追加 {added}、保存 {len(saved)}週、最新 {max(saved) if saved else "なし"}')
    except updater.StopRequested as error:
        print(f'停止しました: {error}')


if __name__ == '__main__':
    main()
