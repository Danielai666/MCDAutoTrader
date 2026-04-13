import ccxt, pandas as pd
from config import SETTINGS
def get_client(): return getattr(ccxt, SETTINGS.EXCHANGE)({'enableRateLimit':True,'apiKey':SETTINGS.KRAKEN_API_KEY or None,'secret':SETTINGS.KRAKEN_API_SECRET or None})
def fetch_ohlcv(pair,timeframe,limit):
    ex=get_client(); data=ex.fetch_ohlcv(pair,timeframe=timeframe,limit=limit)
    df=pd.DataFrame(data,columns=['ts','open','high','low','close','volume']); df['ts']=pd.to_datetime(df['ts'],unit='ms'); return df
def market_price(pair):
    ex=get_client(); t=ex.fetch_ticker(pair); return float(t['last'])
def place_market_order(pair,side,amount):
    if SETTINGS.PAPER_TRADING: return {'id':f'paper-{pair}-{side}','status':'filled','side':side,'amount':amount}
    ex=get_client(); return ex.create_order(symbol=pair,type='market',side=side.lower(),amount=amount)
