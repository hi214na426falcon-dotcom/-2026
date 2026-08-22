import urllib.request, os
PAIRS=['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCHF','USDCAD','EURJPY','GBPJPY','EURGBP','XAUUSD']
BASE='https://raw.githubusercontent.com/ejtraderLabs/historical-data/main/'
OUT=os.path.join(os.path.dirname(__file__),'..','data')
for p in PAIRS:
    url=f'{BASE}{p}/{p}m15.csv'
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        data=urllib.request.urlopen(req,timeout=60).read()
        open(os.path.join(OUT,f'{p}_m15.csv'),'wb').write(data)
        print('saved',p,len(data),'bytes')
    except Exception as e:
        print('FAIL',p,repr(e)[:60])
