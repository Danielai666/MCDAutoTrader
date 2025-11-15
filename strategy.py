import pandas as pd

from indicators import macd,rsi,stochastic,ema_pair,vol_ma
from divergence import detect_divergence
def tf_signal(df: pd.DataFrame)->dict:
 mline,msig,mhist=macd(df['close']); r=rsi(df['close'],14); k,d=stochastic(df['high'],df['low'],df['close'],14,3)
 e9,e21=ema_pair(df['close'],9,21); vma=vol_ma(df['volume'],20)
 md=detect_divergence(df['close'],mline); rd=detect_divergence(df['close'],r)
 vol_ok=df['volume'].iloc[-1]>vma.iloc[-1]; st_buy=(k.iloc[-1]>d.iloc[-1]) and (k.iloc[-1]<80); st_sell=(k.iloc[-1]<d.iloc[-1]) and (k.iloc[-1]>20)
 up=e9.iloc[-1]>e21.iloc[-1]; down=e9.iloc[-1]<e21.iloc[-1]
 score=0; reasons=[]
 if md=='bullish': score+=1; reasons.append('MACD bullish div')
 if rd=='bullish': score+=1; reasons.append('RSI bullish div')
 if md=='bearish': score-=1; reasons.append('MACD bearish div')
 if rd=='bearish': score-=1; reasons.append('RSI bearish div')
 if vol_ok: reasons.append('Volume > MA20')
 if up: reasons.append('EMA9>EMA21')
 if down: reasons.append('EMA9<EMA21')
 if st_buy: reasons.append('StochK>D (bullish zone)')
 if st_sell: reasons.append('StochK<D (bearish zone)')
 direction='HOLD'
 if score>=2 and vol_ok and up and st_buy: direction='BUY'
 elif score<=-2 and vol_ok and down and st_sell: direction='SELL'
 return {'direction':direction,'score':score,'reasons':', '.join(reasons),
 'snapshot':{'macd':float(mline.iloc[-1]),'rsi':float(r.iloc[-1]),'stoch_k':float(k.iloc[-1]),'stoch_d':float(d.iloc[-1]),'ema9_gt_ema21':bool(up)}}
def merge_mtf(signals:dict)->dict:
 w={'30m':1.0,'1h':1.5,'4h':2.0}; regime=signals.get('1d',{}).get('direction','HOLD'); wsum=0; s=0
 for tf,sig in signals.items():
 if tf=='1d': continue
 v=1 if sig.get('direction')=='BUY' else -1 if sig.get('direction')=='SELL' else 0
 s+=v*w.get(tf,1.0); wsum+=w.get(tf,1.0)
 m=s/wsum if wsum else 0.0; md='HOLD'
 if m>0.4: md='BUY'
 if m<-0.4: md='SELL'
 if regime=='SELL' and md=='BUY': md='HOLD'
 if regime=='BUY' and md=='SELL': md='HOLD'
 return {'merged_direction':md,'merged_score':m,'regime':regime}
