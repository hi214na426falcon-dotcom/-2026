"""
データ取得スクリプト
GitHub(ejtraderLabs)から主要通貨ペアのH1(時間足)OHLCVを落とす。
価格は10万倍の整数で入っているので、使う側で /100000 する。
NZDUSDは元リポジトリに無い(404)。時間足はh1のみ確認済み。
他の時間足(m15等)が要る場合は末尾の 'h1' を 'm15' 等に変えて要検証。
"""
import urllib.request, os

PAIRS = ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCHF',
         'USDCAD','EURJPY','GBPJPY','EURGBP','XAUUSD']
BASE = 'https://raw.githubusercontent.com/ejtraderLabs/historical-data/main/'
OUT = os.path.join(os.path.dirname(__file__), '..', 'data')

def fetch(tf='h1'):
    os.makedirs(OUT, exist_ok=True)
    for p in PAIRS:
        url = f'{BASE}{p}/{p}{tf}.csv'
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            data = urllib.request.urlopen(req, timeout=40).read()
            path = os.path.join(OUT, f'{p}.csv')
            open(path, 'wb').write(data)
            print('saved', p, len(data), 'bytes')
        except Exception as e:
            print('FAIL', p, repr(e)[:60])

if __name__ == '__main__':
    fetch('h1')
