import numpy as np, pandas as pd
def ema(s,p): return s.ewm(span=p,adjust=False).mean()
def rsi(s,period=14):
    d=s.diff(); g=(d.where(d>0,0)).rolling(period).mean(); l=(-d.where(d<0,0)).rolling(period).mean()
    rs=g/(l.replace(0,np.nan)); return (100-(100/(1+rs))).fillna(50)
def macd(s,fast=12,slow=26,signal=9):
    ef,es=ema(s,fast),ema(s,slow); line=ef-es; sig=ema(line,signal); return line,sig,line-sig
def stochastic(h,l,c,kp=14,dp=3):
    ll=l.rolling(kp).min(); hh=h.rolling(kp).max(); k=100*(c-ll)/(hh-ll); d=k.rolling(dp).mean(); return k.fillna(50),d.fillna(50)
def vol_ma(v,period=20): return v.rolling(period).mean()
def ema_pair(c,p1=9,p2=21): return ema(c,p1),ema(c,p2)

def atr(high,low,close,period=14):
    tr=pd.concat([high-low,(high-close.shift(1)).abs(),(low-close.shift(1)).abs()],axis=1).max(axis=1)
    return tr.ewm(span=period,adjust=False).mean()

def adx(high,low,close,period=14):
    up=high.diff(); dn=-low.diff()
    plus_dm=np.where((up>dn)&(up>0),up,0.0); minus_dm=np.where((dn>up)&(dn>0),dn,0.0)
    a=atr(high,low,close,period)
    plus_di=100*pd.Series(plus_dm,index=close.index).ewm(span=period,adjust=False).mean()/a
    minus_di=100*pd.Series(minus_dm,index=close.index).ewm(span=period,adjust=False).mean()/a
    dx=(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)*100
    adx_line=dx.ewm(span=period,adjust=False).mean().fillna(0)
    return adx_line,plus_di.fillna(0),minus_di.fillna(0)

def bollinger(close,period=20,std=2.0):
    mid=close.rolling(period).mean(); s=close.rolling(period).std()
    return mid+s*std, mid, mid-s*std

def ichimoku(high, low, close, tenkan_p=9, kijun_p=26, senkou_b_p=52, displacement=26):
    """Ichimoku Cloud: tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span."""
    tenkan = (high.rolling(tenkan_p).max() + low.rolling(tenkan_p).min()) / 2
    kijun = (high.rolling(kijun_p).max() + low.rolling(kijun_p).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(displacement)
    senkou_b = ((high.rolling(senkou_b_p).max() + low.rolling(senkou_b_p).min()) / 2).shift(displacement)
    chikou = close.shift(-displacement)
    return tenkan, kijun, senkou_a, senkou_b, chikou
