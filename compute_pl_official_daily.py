import csv
import json
import os
import re
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import parse_nse_daily_report as report_parser
import parse_nse_margin_pdf as nse_parser
import parse_tse_daily_margin_pdf as tse_parser

DATA_DIR = os.path.join(BASE_DIR, 'data')
STQ_CODE_PATTERN = re.compile(r'[0-9][0-9A-Z]{3}[0-9A-Z]?')
STQ_AFTERNOON_CLOSE_COLUMN = 11
STQ_MORNING_CLOSE_COLUMN = 7
STQ_NAME_COLUMN = 3
OLD_CODE_COLUMN = '証券コード'
OLD_PRICE_COLUMN = '計算用株価(円)'
OLD_MARKET_COLUMN = '市場'
TOKEN_COUNT = 14
SOURCE_TSE = '当日(東証)'
SOURCE_NSE_REPORT = '当日(名証日報)'
SOURCE_FALLBACK = '直近の終値(前の取得分)'
SOURCE_NONE = 'なし'
SAME_DAY_SOURCES = (SOURCE_TSE, SOURCE_NSE_REPORT)
NUMBER_PATTERN = re.compile(r'\s*([\d,]+(?:\.\d+)?)')


def to_float(text):
    matched = NUMBER_PATTERN.match(str(text))
    return float(matched.group(1).replace(',', '')) if matched else None


def load_stq_prices(path):
    prices = {}
    names = {}
    with open(path, encoding='utf-8-sig') as file:
        for row in csv.reader(file):
            if len(row) <= STQ_AFTERNOON_CLOSE_COLUMN or row[0].startswith('!') or not STQ_CODE_PATTERN.fullmatch(row[0].strip()):
                continue
            code = row[0].strip()[:4]
            price = to_float(row[STQ_AFTERNOON_CLOSE_COLUMN]) or to_float(row[STQ_MORNING_CLOSE_COLUMN])
            if price:
                prices[code] = price
                names[code] = row[STQ_NAME_COLUMN].strip()
    return prices, names


def load_old_format_prices(path):
    prices = {}
    with open(path, encoding='cp932') as file:
        for row in csv.DictReader(file):
            code = row[OLD_CODE_COLUMN].strip()
            price = to_float(row[OLD_PRICE_COLUMN])
            if price is None:
                continue
            is_tokyo = row[OLD_MARKET_COLUMN].startswith('東証')
            if code not in prices or is_tokyo:
                prices[code] = price
    return prices


def load_prices_any(path):
    if os.path.basename(path).startswith('stq'):
        return load_stq_prices(path)[0]
    return load_old_format_prices(path)


def merge_fallback_prices(paths):
    merged = {}
    for path in reversed(paths):
        merged.update(load_prices_any(path))
    return merged


def update_summary(tag, row):
    path = os.path.join(DATA_DIR, '信用評価損益率_日次_公式.csv')
    rows = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8-sig') as file:
            rows = {item['日付']: item for item in csv.DictReader(file)}
    date = f'{tag[:4]}-{tag[4:6]}-{tag[6:]}'
    rows[date] = {'日付': date, **row}
    with open(path, 'w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=list(row.keys()) and ['日付'] + list(row.keys()))
        writer.writeheader()
        for key in sorted(rows):
            writer.writerow(rows[key])


def load_nse_report_prices(pdf_path):
    return {code: record['price'] for code, record in report_parser.parse(pdf_path).items()}


def tokens_or_zero(tokens):
    return [0 if value is None else value for value in tokens]


def load_tse_balances(pdf_path):
    records, totals = tse_parser.parse(pdf_path)
    rows = []
    for record in records.values():
        code = record.get('code')
        if 'shares' not in record or 'amounts' not in record or not code:
            continue
        shares, amounts = record['shares'], record['amounts']
        rows.append({
            'コード': code[:4], '買残株数': tse_parser.count(shares, 3), '売残株数': tse_parser.count(shares, 0),
            '買残金額(円)': tse_parser.count(amounts, 3), '売残金額(円)': tse_parser.count(amounts, 0),
        })
    return pd.DataFrame(rows), tokens_or_zero(totals['shares']), tokens_or_zero(totals['amounts'])


def load_nse_balances(pdf_path):
    rows = nse_parser.parse(pdf_path)
    frame = pd.DataFrame([{'コード': row['コード'], '買残株数': row['買残株数'], '売残株数': row['売残株数'], '買残金額(円)': row['買残金額(円)'], '売残金額(円)': row['売残金額(円)']} for row in rows])
    share_sums = [sum(tokens_or_zero(row['_shares'])[index] for row in rows) for index in range(TOKEN_COUNT)]
    amount_sums = [sum(tokens_or_zero(row['_amounts'])[index] for row in rows) for index in range(TOKEN_COUNT)]
    return frame, share_sums, amount_sums


def build_side(total_tokens):
    return {
        'sell': {'total': total_tokens[0], 'change': total_tokens[1], 'general': total_tokens[6], 'general_change': total_tokens[7], 'standard': total_tokens[8], 'standard_change': total_tokens[9]},
        'buy': {'total': total_tokens[3], 'change': total_tokens[4], 'general': total_tokens[10], 'general_change': total_tokens[11], 'standard': total_tokens[12], 'standard_change': total_tokens[13]},
    }


def update_panel(tag, panel):
    path = os.path.join(DATA_DIR, 'panel_daily.json')
    panels = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as file:
            panels = json.load(file)
    panels[f'{tag[:4]}-{tag[4:6]}-{tag[6:]}'] = panel
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(dict(sorted(panels.items())), file, ensure_ascii=False, separators=(',', ':'))


def price_source(code, stq_prices, nse_report_prices, fallback_prices):
    if code in stq_prices:
        return SOURCE_TSE
    if code in nse_report_prices:
        return SOURCE_NSE_REPORT
    return SOURCE_FALLBACK if code in fallback_prices else SOURCE_NONE


def run(tag, tse_pdf, nse_pdf, stq_csv, fallback_paths, nse_report_pdf=None):
    tse, tse_share_tokens, tse_amount_tokens = load_tse_balances(tse_pdf)
    nse, nse_share_tokens, nse_amount_tokens = load_nse_balances(nse_pdf)
    tse_total_cost = tse_amount_tokens[3]
    combined = pd.concat([tse.assign(市場='東証'), nse.assign(市場='名証')])
    per_code = combined.groupby('コード')[['買残株数', '買残金額(円)']].sum()
    per_code = per_code[per_code['買残株数'] > 0]
    stq_prices, stq_names = load_stq_prices(stq_csv)
    fallback_prices = merge_fallback_prices(fallback_paths)
    nse_report_prices = load_nse_report_prices(nse_report_pdf) if nse_report_pdf else {}
    per_code['株価'] = [stq_prices.get(code, nse_report_prices.get(code, fallback_prices.get(code))) for code in per_code.index]
    per_code['株価の出所'] = [price_source(code, stq_prices, nse_report_prices, fallback_prices) for code in per_code.index]
    priced = per_code['株価'].notna()
    value = float((per_code.loc[priced, '買残株数'] * per_code.loc[priced, '株価']).sum())
    cost_priced = float(per_code.loc[priced, '買残金額(円)'].sum())
    cost_parsed = float(per_code['買残金額(円)'].sum())
    nse_cost = float(nse['買残金額(円)'].sum())
    market_cost = tse_total_cost + nse_cost
    same_day_only = per_code[per_code['株価の出所'].isin(SAME_DAY_SOURCES)]
    value_same_day = float((same_day_only['買残株数'] * same_day_only['株価']).sum())
    cost_same_day = float(same_day_only['買残金額(円)'].sum())
    print(f'東証 {len(tse)}銘柄(買残>0 {int((tse["買残株数"] > 0).sum())})、名証 {len(nse)}銘柄(買残>0 {int((nse["買残株数"] > 0).sum())})、合算した買残のある銘柄 {len(per_code)}')
    print(f'買残金額: 東証PDFの総合計 {tse_total_cost:,}円 + 名証 {nse_cost:,.0f}円 = {market_cost:,.0f}円、読み取り {cost_parsed:,.0f}円 ({cost_parsed / market_cost * 100:.3f}%)')
    for source, group in per_code.groupby('株価の出所'):
        print(f'株価の出所 {source}: {len(group)}銘柄、買残株数 {int(group["買残株数"].sum()):,}、買残金額 {group["買残金額(円)"].sum():,.0f}円 ({group["買残金額(円)"].sum() / cost_parsed * 100:.3f}%)')
    print(f'買残の時価 {value:,.0f}円、約定代金(株価のある銘柄) {cost_priced:,.0f}円')
    print(f'評価損益率(銘柄別で完結、株価のある全銘柄): {(value / cost_priced - 1) * 100:.3f}%')
    print(f'評価損益率(当日の株価のある銘柄だけ): {(value_same_day / cost_same_day - 1) * 100:.3f}%')
    print(f'評価損益率(分母=東証PDFの総合計+名証、株価のない分は評価0): {(value / market_cost - 1) * 100:.3f}%')
    per_code = per_code.assign(時価=per_code['買残株数'] * per_code['株価'], 銘柄名=[stq_names.get(code, '') for code in per_code.index])
    per_code['損益'] = per_code['時価'] - per_code['買残金額(円)']
    output = os.path.join(DATA_DIR, f'信用評価損益率_{tag}_公式.csv')
    per_code.to_csv(output, encoding='utf-8-sig')
    ranked = per_code.dropna(subset=['損益']).sort_values('損益')
    print('損益の大きい銘柄(億円、下位5・上位5)')
    for code, row in pd.concat([ranked.head(5), ranked.tail(5)]).iterrows():
        print(f'  {row["銘柄名"]}（{code}） 買残 {int(row["買残株数"]):,}株 平均取得単価 {row["買残金額(円)"] / row["買残株数"]:,.1f}円 株価 {row["株価"]:,.1f}円 損益 {row["損益"] / 1e8:,.1f}億円')
    unpriced = per_code[per_code['株価の出所'] == SOURCE_NONE]
    substituted = per_code[per_code['株価の出所'] == SOURCE_FALLBACK]
    update_summary(tag, {
        '評価損益率(%)': round((value / cost_priced - 1) * 100, 3),
        '評価損益率・当日の株価のある銘柄だけ(%)': round((value_same_day / cost_same_day - 1) * 100, 3),
        '評価損益率・分母を総合計とし未評価分は0(%)': round((value / market_cost - 1) * 100, 3),
        '買残の時価(円)': int(value),
        '約定代金・株価のある銘柄(円)': int(cost_priced),
        '約定代金の総合計(円)': int(market_cost),
        '約定代金の読み取り率(%)': round(cost_parsed / market_cost * 100, 3),
        '東証の銘柄数(買残>0)': int((tse['買残株数'] > 0).sum()),
        '名証の銘柄数(買残>0)': int((nse['買残株数'] > 0).sum()),
        '当日の株価の銘柄数': int(per_code['株価の出所'].isin(SAME_DAY_SOURCES).sum()),
        'うち名証日報の株価の銘柄数': int((per_code['株価の出所'] == SOURCE_NSE_REPORT).sum()),
        '直近の終値で代用した銘柄数': len(substituted),
        '代用した買残金額の割合(%)': round(substituted['買残金額(円)'].sum() / cost_parsed * 100, 3),
        '株価なしの銘柄数': len(unpriced),
        '株価なしの買残金額の割合(%)': round(unpriced['買残金額(円)'].sum() / cost_parsed * 100, 3),
    })
    sell_code = combined.groupby('コード')[['売残株数', '売残金額(円)']].sum()
    sell_code = sell_code[sell_code['売残株数'] > 0]
    sell_code['株価'] = [stq_prices.get(code, nse_report_prices.get(code, fallback_prices.get(code))) for code in sell_code.index]
    sell_priced = sell_code[sell_code['株価'].notna()]
    sell_value = float((sell_priced['売残株数'] * sell_priced['株価']).sum())
    sell_cost = float(sell_priced['売残金額(円)'].sum())
    pl_sell = round((sell_cost - sell_value) / sell_cost * 100, 3)
    share_total = [a + b for a, b in zip(tse_share_tokens, nse_share_tokens)]
    amount_total = [a + b for a, b in zip(tse_amount_tokens, nse_amount_tokens)]
    panel = {
        'amount': build_side(amount_total),
        'shares': build_side(share_total),
        'pl_buy': round((value / cost_priced - 1) * 100, 3),
        'pl_sell': pl_sell,
        'ratio_amount': round(amount_total[3] / amount_total[0], 2),
        'ratio_shares': round(share_total[3] / share_total[0], 2),
    }
    update_panel(tag, panel)
    print(f'評価損益率(売り方): {pl_sell:.3f}%、信用倍率 金額 {panel["ratio_amount"]:.2f}倍 株数 {panel["ratio_shares"]:.2f}倍')
    print(f'出力: {output}')
    return round((value / cost_priced - 1) * 100, 3)


def main():
    tag, tse_pdf, nse_pdf, stq_csv = sys.argv[1:5]
    rest = sys.argv[5:]
    reports = [path for path in rest if path.startswith('--report=')]
    report_pdf = reports[0].split('=', 1)[1] if reports else None
    run(tag, tse_pdf, nse_pdf, stq_csv, [path for path in rest if not path.startswith('--report=')], report_pdf)


if __name__ == '__main__':
    main()
