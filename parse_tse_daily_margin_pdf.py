import csv
import os
import re
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PDF = os.path.expanduser('~/Downloads/20260925_mtall.pdf')
CODE_PATTERN = re.compile(r'(?<![0-9A-Z])([0-9A-Z]{5})\s+([A-Z]{2}[0-9A-Z]{10})(?![0-9A-Z])')
ISIN_PATTERN = re.compile(r'(?<![0-9A-Z])([A-Z]{2}[0-9]{1}[0-9A-Z]{9})(?![0-9A-Z])')
TOKEN_PATTERN = re.compile(r'▲\s*[\d,]+|[\d,]+(?:\.\d+)?%?|\*|-')
EXPECTED_TOKENS = 14
SHARES_MARKER = '株数 Shs.'
AMOUNT_PATTERN = re.compile(r'金額.*?Val\.')
LOOSE_CODE_PATTERN = re.compile(r'(?<![0-9A-Z,.])(\d{4}[0-9A-Z])(?![0-9A-Z,.%])')
CODE_LOOKBACK_LINES = 4
TOTAL_MARKER = '総合計'


def to_number(token):
    if token in ('*', '-'):
        return None
    negative = token.startswith('▲')
    cleaned = token.replace('▲', '').replace(',', '').replace('%', '').strip()
    value = float(cleaned)
    return -value if negative else value


def tokens_after(line, marker):
    tail = line.split(marker, 1)[1]
    return [to_number(token) for token in TOKEN_PATTERN.findall(tail)]


def tokens_after_pattern(line, pattern):
    matched = pattern.search(line)
    tail = line[matched.end():]
    return [to_number(token) for token in TOKEN_PATTERN.findall(tail)]


def count(values, position):
    return 0 if values[position] is None else int(values[position])


def parse(pdf_path):
    lines = subprocess.run(['pdftotext', '-layout', pdf_path, '-'], capture_output=True, text=True).stdout.splitlines()
    records = {}
    totals = {}
    code_by_isin = {}
    current_isin = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(TOTAL_MARKER) and SHARES_MARKER in line:
            totals['shares'] = tokens_after(line, SHARES_MARKER)
            continue
        if stripped.startswith('total') and AMOUNT_PATTERN.search(line) and 'amounts' not in totals:
            totals['amounts'] = tokens_after_pattern(line, AMOUNT_PATTERN)
            continue
        isin_match = ISIN_PATTERN.search(line)
        if isin_match:
            current_isin = isin_match.group(1)
            if current_isin not in code_by_isin:
                pair = CODE_PATTERN.search(line)
                if pair:
                    code_by_isin[current_isin] = pair.group(1)
                else:
                    for back in range(0, CODE_LOOKBACK_LINES + 1):
                        candidates = LOOSE_CODE_PATTERN.findall(lines[index - back])
                        if candidates:
                            code_by_isin[current_isin] = candidates[-1]
                            break
        if SHARES_MARKER in line:
            values = tokens_after(line, SHARES_MARKER)
            if len(values) == EXPECTED_TOKENS and current_isin:
                records.setdefault(current_isin, {})['shares'] = values
        elif AMOUNT_PATTERN.search(line):
            values = tokens_after_pattern(line, AMOUNT_PATTERN)
            if len(values) == EXPECTED_TOKENS and current_isin:
                records.setdefault(current_isin, {})['amounts'] = values
                current_isin = None
    for isin, record in records.items():
        record['code'] = code_by_isin.get(isin)
    return records, totals


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PDF
    output = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE_DIR, 'data', '東証_銘柄別信用残_20260925.csv')
    records, totals = parse(pdf_path)
    rows = []
    incomplete = []
    for isin, record in records.items():
        code = record.get('code')
        if 'shares' not in record or 'amounts' not in record or not code:
            incomplete.append(isin)
            continue
        shares, amounts = record['shares'], record['amounts']
        rows.append({'コード': code[:4], '売残株数': count(shares, 0), '買残株数': count(shares, 3), '買残前日比': count(shares, 4), '買残一般信用': count(shares, 10), '買残制度信用': count(shares, 12),
                     '売残金額(円)': count(amounts, 0), '買残金額(円)': count(amounts, 3)})
    with open(output, 'w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    total_shares, total_amounts = totals['shares'], totals['amounts']
    print(f'銘柄数 {len(rows)}（PDFの総合計は4261）、読み取れなかった銘柄 {len(incomplete)} {incomplete[:5]}')
    print(f'買残株数 読み取り {sum(row["買残株数"] for row in rows):,} / PDFの総合計 {count(total_shares, 3):,}')
    print(f'売残株数 読み取り {sum(row["売残株数"] for row in rows):,} / PDFの総合計 {count(total_shares, 0):,}')
    print(f'買残金額 読み取り {sum(row["買残金額(円)"] for row in rows):,} / PDFの総合計 {count(total_amounts, 3):,}')
    print(f'出力: {output}')


if __name__ == '__main__':
    main()
