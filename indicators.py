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
