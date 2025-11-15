import pandas as pd
def _pivots(s):
 hi=s[(s.shift(1)<s)&(s.shift(-1)<s)]; lo=s[(s.shift(1)>s)&(s.shift(-1)>s)]
 lh=hi.dropna().tail(10).index[-2:] if hi.dropna().shape[0]>=2 else []
 ll=lo.dropna().tail(10).index[-2:] if lo.dropna().shape[0]>=2 else []
 return list(lh),list(ll)
def detect_divergence(price,osc):
 if len(price)<50: return "none"
 hi,lo=_pivots(price)
 if len(hi)==2:
 p1,p2=price.loc[hi[0]],price.loc[hi[1]]; o1,o2=osc.loc[hi[0]],osc.loc[hi[1]]
 if p2>p1 and o2<o1: return "bearish"
 if len(lo)==2:
 p1,p2=price.loc[lo[0]],price.loc[lo[1]]; o1,o2=osc.loc[lo[0]],osc.loc[lo[1]]
 if p2<p1 and o2>o1: return "bullish"
 return "none"
