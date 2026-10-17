import csv
import os
import re
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PDF = os.path.expanduser('~/Downloads/msinyo260925.pdf')
OUTPUT_CSV = os.path.join(BASE_DIR, 'data', '名証_銘柄別信用残_20260925.csv')
STOCK_LINE = re.compile(r'^\s*([PMN])\s+([0-9A-Z]{5})\s+([●○◎]?)\s*(.+?)\s+株数\s+(.*)$')
AMOUNT_LINE = re.compile(r'^\s*金額\s+(.*)$')
TOKEN = re.compile(r'[‑\-]?[\d,]+(?:\.\d+)?|\*|‑')
EXPECTED_TOKENS = 14


def to_number(token):
    if token in ('*', '‑'):
        return None
    return float(token.replace('‑', '-').replace(',', ''))


def count(values, position):
    return 0 if values[position] is None else int(values[position])


def parse(pdf_path):
    text = subprocess.run(['pdftotext', '-layout', pdf_path, '-'], capture_output=True, text=True).stdout.splitlines()
    rows = []
    for index, line in enumerate(text):
        matched = STOCK_LINE.match(line)
        if not matched:
            continue
        shares = [to_number(token) for token in TOKEN.findall(matched.group(5))]
        amount_match = AMOUNT_LINE.match(text[index + 1]) if index + 1 < len(text) else None
        amounts = [to_number(token) for token in TOKEN.findall(amount_match.group(1))] if amount_match else []
        assert len(shares) == EXPECTED_TOKENS, (line, shares)
        assert len(amounts) == EXPECTED_TOKENS, (text[index + 1], amounts)
        rows.append({
            '市場': matched.group(1), 'コード': matched.group(2)[:4], '印': matched.group(3), '銘柄名': matched.group(4).strip(),
            '売残株数': count(shares, 0), '買残株数': count(shares, 3), '買残前日比': count(shares, 4), '買残一般信用': count(shares, 10), '買残制度信用': count(shares, 12),
            '売残金額(円)': count(amounts, 0), '買残金額(円)': count(amounts, 3),
            '_shares': shares, '_amounts': amounts,
        })
    return rows


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PDF
    rows = parse(pdf_path)
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=[key for key in rows[0].keys() if not key.startswith('_')], extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(f'銘柄数 {len(rows)}、買残株数の合計 {sum(row["買残株数"] for row in rows):,}、売残株数の合計 {sum(row["売残株数"] for row in rows):,}、買残金額の合計 {sum(row["買残金額(円)"] for row in rows):,}円')
    print(f'出力: {OUTPUT_CSV}')


if __name__ == '__main__':
    main()
