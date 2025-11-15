import json, urllib.request
from typing import Dict
from config import SETTINGS

def _remote(features: Dict)->Dict:
 if not SETTINGS.AI_BASE_URL or not SETTINGS.AI_API_KEY:
 raise RuntimeError('no-remote')
 url=SETTINGS.AI_BASE_URL.rstrip('/')+'/decide'
 req=urllib.request.Request(url,method='POST')
 req.add_header('Content-Type','application/json')
 req.add_header('Authorization',f'Bearer {SETTINGS.AI_API_KEY}')
 data=json.dumps({'features':features}).encode('utf-8')
 with urllib.request.urlopen(req,data=data,timeout=10) as r:
 out=json.loads(r.read().decode('utf-8'))
 return {
 'decision': out.get('decision','HOLD'),
 'confidence': float(out.get('confidence',0.55)),
 'notes': out.get('notes','remote')
 }

def _heur(features: Dict)->Dict:
 m=features.get('merged',{})
 d=m.get('merged_direction','HOLD')
 sc=float(m.get('merged_score',0.0))
 decision='HOLD'; conf=0.55; notes='Heuristic fallback'
 if d=='BUY' and sc>=float(getattr(SETTINGS,'SIGNAL_SCORE_MIN',0.6)):
 decision='ENTER'; conf=min(0.95, 0.55+sc/2); notes='Heuristic BUY'
 elif d=='SELL' and sc<=-float(getattr(SETTINGS,'SIGNAL_SCORE_MIN',0.6)):
 decision='EXIT'; conf=min(0.95, 0.55+abs(sc)/2); notes='Heuristic SELL'
 return {'decision':decision,'confidence':conf,'notes':notes}

def decide(features: Dict)->Dict:
 try:
 return _remote(features)
 except Exception:
 return _heur(features)

class Decider:
 def decide(self, features: Dict)->Dict:
 return decide(features)
