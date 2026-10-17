import csv
import datetime
import json
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_CSV = os.path.join(BASE_DIR, 'data', 'nikkei_daily.csv')
WEEKLY_CSV = os.path.join(BASE_DIR, 'data', 'nikkei_weekly.csv')
CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EN225?period1={start}&period2={end}&interval=1d'
USER_AGENT = 'Mozilla/5.0'
OVERLAP_DAYS = 7
DEFAULT_WEEKLY_END = '2026-09-25'
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 8
UTC = datetime.timezone.utc


def last_weekly_date():
    if not os.path.exists(WEEKLY_CSV):
        return DEFAULT_WEEKLY_END
    with open(WEEKLY_CSV, encoding='utf-8-sig') as file:
        return max(row[0] for row in list(csv.reader(file))[1:])


def load_stored():
    if not os.path.exists(DAILY_CSV):
        return {}
    with open(DAILY_CSV, encoding='utf-8-sig') as file:
        return {row['date']: float(row['close']) for row in csv.DictReader(file)}


def save_stored(closes):
    with open(DAILY_CSV, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['date', 'close'])
        for date in sorted(closes):
            writer.writerow([date, closes[date]])


def fetch_closes(start_date):
    start = int(datetime.datetime.combine(start_date, datetime.time(), tzinfo=UTC).timestamp())
    end = int(time.time()) + 86400
    url = CHART_URL.format(start=start, end=end)
    for attempt in range(RETRY_ATTEMPTS):
        result = subprocess.run(['curl', '-s', '-L', '-A', USER_AGENT, '--max-time', str(REQUEST_TIMEOUT), '-w', '\n%{http_code}', url], capture_output=True)
        body, _, status_text = result.stdout.rpartition(b'\n')
        if status_text.strip() == b'200':
            chart = json.loads(body.decode('utf-8'))['chart']['result'][0]
            offset = chart['meta']['gmtoffset']
            closes = chart['indicators']['quote'][0]['close']
            return {
                datetime.datetime.fromtimestamp(stamp + offset, UTC).strftime('%Y-%m-%d'): round(close, 2)
                for stamp, close in zip(chart['timestamp'], closes)
                if close is not None
            }
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_WAIT_SECONDS)
    return None


def main():
    stored = load_stored()
    weekly_end = datetime.date.fromisoformat(last_weekly_date())
    latest_stored = datetime.date.fromisoformat(max(stored)) if stored else weekly_end
    start_date = max(weekly_end, latest_stored - datetime.timedelta(days=OVERLAP_DAYS))
    fetched = fetch_closes(start_date)
    if fetched is None:
        print('Yahooから日経平均を取得できませんでした。保存済みの値を使います。')
        return
    added = len([date for date in fetched if date not in stored])
    stored.update(fetched)
    save_stored(stored)
    print(f'日経平均(日次): 取得 {len(fetched)}日、新規 {added}日、保存 {len(stored)}日、最新 {max(stored)}')


if __name__ == '__main__':
    sys.exit(main())
