import re
import subprocess
import sys

RECORD_START = re.compile(r'(?<![0-9A-Za-z.\-])([0-9]{3}[0-9A-Z]0)(?=\s+[●○]?\s*[^\s0-9\-ｹ△◎□＃◇])')
NUMBER = re.compile(r'[△◎□＃◇]*(-?[\d,]+(?:\.\d+)?)$')
QUOTE_MARK = 'ｹ'
PRICE_COUNT = 4
CLOSE_POSITION = 3


def to_number(token):
    matched = NUMBER.match(token)
    return float(matched.group(1).replace(',', '')) if matched else None


def parse_record(segment):
    tokens = segment.split()
    index = 1
    if index < len(tokens) and tokens[index] in ('●', '○'):
        index += 1
    name = tokens[index] if index < len(tokens) else ''
    rest = tokens[index + 1:]
    numbers_before_quote = []
    quote_value = None
    for position, token in enumerate(rest):
        if token == QUOTE_MARK:
            if position + 1 < len(rest):
                quote_value = to_number(rest[position + 1])
            break
        value = to_number(token)
        if value is None:
            break
        numbers_before_quote.append(value)
    if len(numbers_before_quote) >= PRICE_COUNT:
        return numbers_before_quote[CLOSE_POSITION], '終値', name
    if quote_value is not None:
        return quote_value, '最終気配', name
    return None, '', name


def parse(pdf_path):
    text = subprocess.run(['pdftotext', '-layout', pdf_path, '-'], capture_output=True, text=True).stdout
    records = {}
    for line in text.splitlines():
        starts = [match.start() for match in RECORD_START.finditer(line)]
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(line)
            segment = line[start:end]
            price, kind, name = parse_record(segment)
            code = segment.split()[0][:4]
            if price:
                records[code] = {'price': price, 'kind': kind, 'name': name}
    return records


def main():
    records = parse(sys.argv[1])
    traded = sum(1 for record in records.values() if record['kind'] == '終値')
    print(f'銘柄数 {len(records)}（終値 {traded}、最終気配 {len(records) - traded}）')


if __name__ == '__main__':
    main()
