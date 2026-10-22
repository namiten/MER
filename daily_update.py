import csv
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import compute_pl_official_daily as pl
import parse_jpx_stock_quotations as quotation_parser

DATA_DIR = os.path.join(BASE_DIR, 'data')
RAW_DIR = os.path.join(BASE_DIR, 'daily_raw')
TSE_DIR = os.path.join(RAW_DIR, 'tse')
NSE_DIR = os.path.join(RAW_DIR, 'nse')
STQ_DIR = os.path.join(RAW_DIR, 'stq')
REPORT_DIR = os.path.join(RAW_DIR, 'nse_report')
LEGACY_PRICE_CSV = os.path.join(RAW_DIR, 'price_legacy_20261005.csv')
SUMMARY_CSV = os.path.join(DATA_DIR, '信用評価損益率_日次_公式.csv')
VERSION_JSON = os.path.join(DATA_DIR, '東証PDFの版.json')
LOG_PATH = os.path.join(RAW_DIR, 'daily_update.log')
TSE_PAGE = 'https://www.jpx.co.jp/markets/statistics-equities/margin/01.html'
TSE_SITE = 'https://www.jpx.co.jp'
NSE_PAGE = 'https://www.nse.or.jp/market/statistics/balances/'
NSE_SITE = 'https://www.nse.or.jp'
QUOTATION_LIST = 'https://www.jpx.co.jp/automation/markets/statistics-equities/daily/json/tsedaily_report_{month}.json'
REPORT_PAGE = 'https://www.nse.or.jp/market/condition/report/'
REPORT_BASE = 'https://www.nse.or.jp/market/condition/report/files/'
TEMP_PDF = os.path.join(RAW_DIR, 'quotation_temp.pdf')
TSE_LINK = re.compile(r'href="([^"]*?/(\d{8})_mtall(?:_(\d+))?\.pdf)"')
TSE_VERSION = re.compile(r'_mtall_(\d+)\.pdf$')
NSE_LINK = re.compile(r'href="([^"]*?/msinyo(\d{6})\.pdf)"')
REPORT_LINK = re.compile(r'href="files/(\d{8})\.pdf"')
FIRST_DATE = '20260925'
FALLBACK_DAYS = 12
USER_AGENT = 'Mozilla/5.0'
WAIT_RANGE = (1.0, 1.5)
RETRY_WAIT_RANGE = (5.0, 10.0)
RETRY_ATTEMPTS = 3
STOP_STATUSES = (401, 403, 429)
MAX_CONSECUTIVE_ERRORS = 5
REQUEST_TIMEOUT = 90


class StopRequested(Exception):
    pass


class Fetcher:
    def __init__(self):
        self.consecutive_errors = 0
        self.first_request = True

    def get(self, url):
        if not self.first_request:
            time.sleep(random.uniform(*WAIT_RANGE))
        self.first_request = False
        for attempt in range(RETRY_ATTEMPTS):
            result = subprocess.run(
                ['curl', '-s', '-L', '-A', USER_AGENT, '--max-time', str(REQUEST_TIMEOUT), '-w', '\n%{http_code}', url],
                capture_output=True,
            )
            body, _, status_text = result.stdout.rpartition(b'\n')
            status = int(status_text) if status_text.strip().isdigit() else 0
            if status == 200 and body:
                self.consecutive_errors = 0
                return body
            if status in STOP_STATUSES:
                raise StopRequested(f'HTTP {status}: {url}')
            if status == 404:
                self.consecutive_errors = 0
                return None
            self.consecutive_errors += 1
            if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                raise StopRequested(f'{MAX_CONSECUTIVE_ERRORS}回連続で取得できませんでした: {url}')
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(random.uniform(*RETRY_WAIT_RANGE))
        return None


def log(message):
    line = f'{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} {message}'
    print(line)
    with open(LOG_PATH, 'a', encoding='utf-8') as file:
        file.write(line + '\n')


def list_links(fetcher, page_url, pattern, site, date_of):
    body = fetcher.get(page_url)
    if body is None:
        raise StopRequested(f'一覧ページを取得できません: {page_url}')
    html = body.decode('utf-8', errors='ignore')
    links = {}
    versions = {}
    for match in pattern.finditer(html):
        href = match.group(1)
        date = date_of(match.group(2))
        version = int(match.group(3)) if pattern.groups >= 3 and match.group(3) else 0
        if versions.get(date, -1) > version:
            continue
        versions[date] = version
        links[date] = href if href.startswith('http') else (site + href if href.startswith('/') else href)
    return links


def tse_version(url):
    match = TSE_VERSION.search(url)
    return int(match.group(1)) if match else 0


def load_versions():
    if not os.path.exists(VERSION_JSON):
        return {}
    with open(VERSION_JSON, encoding='utf-8') as file:
        return json.load(file)


def save_versions(versions):
    with open(VERSION_JSON, 'w', encoding='utf-8') as file:
        json.dump(dict(sorted(versions.items())), file, ensure_ascii=False, indent=1)


def to_full_date(text):
    return text if len(text) == 8 else '20' + text


def saved_dates():
    if not os.path.exists(SUMMARY_CSV):
        return set()
    with open(SUMMARY_CSV, encoding='utf-8-sig') as file:
        return {row['日付'].replace('-', '') for row in csv.DictReader(file)}


def download_pdf(fetcher, url, path):
    if os.path.exists(path):
        return True
    body = fetcher.get(url)
    if body is None or not body.startswith(b'%PDF'):
        return False
    with open(path, 'wb') as file:
        file.write(body)
    return True


def list_quotation_reports(fetcher):
    today = datetime.date.today()
    previous_month = (today.replace(day=1) - datetime.timedelta(days=1))
    reports = {}
    for month in (previous_month.strftime('%Y%m'), today.strftime('%Y%m')):
        body = fetcher.get(QUOTATION_LIST.format(month=month))
        if body is None:
            continue
        for row in json.loads(body.decode('utf-8')).get('TableDatas', []):
            if row.get('Stocks'):
                reports[row['TradeDate']] = TSE_SITE + row['Stocks']
    return reports


def download_stq(fetcher, url, path):
    if os.path.exists(path):
        return True
    body = fetcher.get(url)
    if body is None or not body.startswith(b'%PDF'):
        return False
    with open(TEMP_PDF, 'wb') as file:
        file.write(body)
    records = quotation_parser.parse(TEMP_PDF)
    os.remove(TEMP_PDF)
    if not records:
        return False
    quotation_parser.write_csv(records, path)
    return True


def prepare_fallbacks(fetcher, stq_urls, date):
    earlier = sorted((day for day in stq_urls if day < date), reverse=True)[:FALLBACK_DAYS]
    for day in earlier:
        download_stq(fetcher, stq_urls[day], os.path.join(STQ_DIR, f'stq_{day}.csv'))


def fallback_price_files(date):
    earlier = sorted((name for name in os.listdir(STQ_DIR) if name.startswith('stq_') and name[4:12] < date), reverse=True)[:FALLBACK_DAYS]
    paths = [os.path.join(STQ_DIR, name) for name in earlier]
    if os.path.exists(LEGACY_PRICE_CSV):
        paths.append(LEGACY_PRICE_CSV)
    return paths


def main():
    recompute = '--recompute' in sys.argv
    for directory in (TSE_DIR, NSE_DIR, STQ_DIR, REPORT_DIR):
        os.makedirs(directory, exist_ok=True)
    fetcher = Fetcher()
    try:
        tse_links = list_links(fetcher, TSE_PAGE, TSE_LINK, TSE_SITE, lambda text: text)
        nse_links = list_links(fetcher, NSE_PAGE, NSE_LINK, NSE_SITE, to_full_date)
        stq_urls = list_quotation_reports(fetcher)
        report_dates = {match.group(1) for match in REPORT_LINK.finditer(fetcher.get(REPORT_PAGE).decode('utf-8', errors='ignore'))}
        done = set() if recompute else saved_dates()
        versions = load_versions()
        candidates = sorted(date for date in tse_links if date >= FIRST_DATE and (date not in done or tse_version(tse_links[date]) > versions.get(date, 0)))
        log(f'東証 {len(tse_links)}日分、名証 {len(nse_links)}日分、株価 {len(stq_urls)}日分が公表中。未算出の候補 {candidates}')
        for date in candidates:
            missing = [label for label, source in (('名証PDF', nse_links), ('株価', stq_urls), ('名証日報', dict.fromkeys(report_dates))) if date not in source]
            if missing:
                log(f'{date}: {"、".join(missing)}がまだ公表されていないため、見送りました')
                continue
            tse_path = os.path.join(TSE_DIR, os.path.basename(tse_links[date]))
            nse_path = os.path.join(NSE_DIR, f'msinyo{date[2:]}.pdf')
            stq_path = os.path.join(STQ_DIR, f'stq_{date}.csv')
            report_path = os.path.join(REPORT_DIR, f'{date}.pdf')
            if not (download_pdf(fetcher, tse_links[date], tse_path) and download_pdf(fetcher, nse_links[date], nse_path) and download_stq(fetcher, stq_urls[date], stq_path) and download_pdf(fetcher, REPORT_BASE + date + '.pdf', report_path)):
                log(f'{date}: ダウンロードできないファイルがあり、見送りました')
                continue
            prepare_fallbacks(fetcher, stq_urls, date)
            result = pl.run(date, tse_path, nse_path, stq_path, fallback_price_files(date), report_path)
            if tse_version(tse_links[date]):
                versions[date] = tse_version(tse_links[date])
                save_versions(versions)
            log(f'{date}: 評価損益率 {result}% を算出しました（{os.path.basename(tse_path)}）')
    except StopRequested as error:
        log(f'停止しました: {error}')
        sys.exit(1)


if __name__ == '__main__':
    main()
