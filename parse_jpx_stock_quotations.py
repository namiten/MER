import csv
import re
import subprocess
import sys

ROW_START = re.compile(r'^\s*([0-9]{3}[0-9A-Z])\d?(?:\s+[#＃*A-Z]+)?\s+([\d,]+)\s+(\S.*)$')
TOKEN = re.compile(r'-?[\d,]+\.\d+|－')
COLUMN_COUNT = 13
MORNING_CLOSE = 3
AFTERNOON_CLOSE = 7
POSITION_TOLERANCE = 6
MIN_TOKEN_END = 50
MIN_REFERENCE_TOKENS = 12
FORM_FEED = '\f'
OUTPUT_HEADER = ['コード', 'フラグ', '売買単位', '銘柄名', '午前始値', '午前高値', '午前安値', '午前終値', '午後始値', '午後高値', '午後安値', '午後終値', '最終気配', '前日比', '売買高加重平均価格', '売買高(千株)', '売買代金(千円)']


def to_value(text):
    return None if text == '－' else float(text.replace(',', ''))


def split_row(line):
    matched = ROW_START.match(line)
    if not matched:
        return None
    code, unit, rest = matched.group(1), matched.group(2), matched.group(3)
    rest_start = line.index(rest)
    tokens = [(rest_start + token.end(), token.group(0)) for token in TOKEN.finditer(rest) if rest_start + token.end() >= MIN_TOKEN_END]
    name_match = re.match(r'(\S+)', rest)
    name = name_match.group(1) if name_match else ''
    return code, int(unit.replace(',', '')), name, tokens


def parse_page(lines):
    rows = []
    reference = None
    for line in lines:
        parsed = split_row(line)
        if not parsed:
            continue
        code, unit, name, tokens = parsed
        if reference is None and len(tokens) >= MIN_REFERENCE_TOKENS:
            reference = [end for end, _ in tokens][:COLUMN_COUNT]
        rows.append((code, unit, name, tokens))
    return rows, reference


def assign_columns(tokens, reference):
    values = [None] * COLUMN_COUNT
    for end, text in tokens:
        distances = [abs(end - reference_end) for reference_end in reference]
        index = min(range(len(reference)), key=distances.__getitem__)
        if distances[index] <= POSITION_TOLERANCE:
            values[index] = to_value(text)
    return values


def parse(pdf_path):
    text = subprocess.run(['pdftotext', '-layout', pdf_path, '-'], capture_output=True, text=True).stdout
    records = {}
    for page in text.split(FORM_FEED):
        rows, reference = parse_page(page.splitlines())
        if reference is None:
            continue
        for code, unit, name, tokens in rows:
            values = assign_columns(tokens, reference)
            close = values[AFTERNOON_CLOSE] if values[AFTERNOON_CLOSE] is not None else values[MORNING_CLOSE]
            if close and code not in records:
                records[code] = {'unit': unit, 'name': name, 'values': values, 'close': close}
    return records


def write_csv(records, path):
    with open(path, 'w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['!株価データ'])
        writer.writerow(['! コード', 'フラグ', '売買単位', '銘柄名'] + OUTPUT_HEADER[4:])
        for code in sorted(records):
            record = records[code]
            writer.writerow([code, '', record['unit'], record['name']] + ['' if value is None else value for value in record['values']])


def main():
    records = parse(sys.argv[1])
    print(f'銘柄数 {len(records)}')
    if len(sys.argv) > 2:
        write_csv(records, sys.argv[2])


if __name__ == '__main__':
    main()
