# ai_fusion.py
# Dual-AI decision engine: Claude + OpenAI + local heuristic + fusion layer
import json
import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import SETTINGS
from storage import execute

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Data classes
# -------------------------------------------------------------------
@dataclass
class AIDecision:
    action: str = 'HOLD'         # ENTER, EXIT, HOLD
    side: Optional[str] = None   # BUY, SELL, None
    confidence: float = 0.0
    setup_quality: float = 0.0
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    risk_flags: list = field(default_factory=list)
    source: str = 'local'        # 'local', 'claude', 'openai'
    raw_response: Optional[str] = None
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return {
            'action': self.action, 'side': self.side,
            'confidence': round(self.confidence, 3),
            'setup_quality': round(self.setup_quality, 3),
            'reasons': self.reasons, 'warnings': self.warnings,
            'risk_flags': self.risk_flags, 'source': self.source,
            'latency_ms': self.latency_ms,
        }

@dataclass
class FusionResult:
    final_action: str = 'HOLD'
    final_side: Optional[str] = None
    final_confidence: float = 0.0
    policy_used: str = 'local_only'
    decisions: list = field(default_factory=list)
    consensus_notes: str = ''
    was_overridden: bool = False

    def to_dict(self) -> dict:
        return {
            'final_action': self.final_action,
            'final_side': self.final_side,
            'final_confidence': round(self.final_confidence, 3),
            'policy_used': self.policy_used,
            'decisions': [d.to_dict() for d in self.decisions],
            'consensus_notes': self.consensus_notes,
            'was_overridden': self.was_overridden,
        }

# -------------------------------------------------------------------
# Prompt builder
# -------------------------------------------------------------------
_SYSTEM_PROMPT = """You are a professional crypto trading analyst. Analyze the market data and respond with a JSON object only.

Required JSON schema:
{
  "action": "ENTER" or "EXIT" or "HOLD",
  "side": "BUY" or "SELL" or null,
  "confidence": 0.0 to 1.0,
  "setup_quality": 0.0 to 1.0,
  "reasons": ["reason1", "reason2"],
  "warnings": ["warning1"],
  "risk_flags": ["flag1"]
}

Rules:
- ENTER only when multiple signals align with high confidence
- HOLD when context is mixed or uncertain
- EXIT when strong opposing signals appear
- Be conservative. When in doubt, HOLD."""

def _build_prompt(features: dict) -> str:
    pair = features.get('pair', '?')
    merged = features.get('merged', {})
    by_tf = features.get('by_tf', {})

    lines = [f"Symbol: {pair}"]
    lines.append(f"Merged direction: {merged.get('merged_direction', '?')}")
    lines.append(f"Merged score: {merged.get('merged_score', 0):.3f}")
    lines.append(f"Regime: {merged.get('regime', '?')}")

    regime_detail = merged.get('regime_detail')
    if regime_detail:
        lines.append(f"Regime type: {regime_detail.get('regime', '?')} (conf={regime_detail.get('confidence', 0):.2f})")

    for tf, sig in by_tf.items():
        snap = sig.get('snapshot', {})
        lines.append(f"\n--- {tf} ---")
        lines.append(f"Direction: {sig.get('direction', '?')} | Score: {sig.get('score', 0):.2f}")
        lines.append(f"ADX: {snap.get('adx', '?'):.1f} | RSI: {snap.get('rsi', '?'):.1f} | ATR: {snap.get('atr', '?'):.4f}")
        lines.append(f"MACD: {snap.get('macd', '?'):.4f} | Stoch K: {snap.get('stoch_k', '?'):.1f} D: {snap.get('stoch_d', '?'):.1f}")
        lines.append(f"BB position: {snap.get('bb_position', '?'):.2f} | EMA9>21: {snap.get('ema9_gt_ema21', '?')}")
        lines.append(f"Reasons: {sig.get('reasons', '')}")

        candles = snap.get('candles')
        if candles:
            lines.append(f"Candles: bull={candles.get('bullish_count',0)} bear={candles.get('bearish_count',0)} net={candles.get('net_score',0):.2f}")

    return "\n".join(lines)

def _parse_ai_response(text: str, source: str) -> AIDecision:
    """Parse JSON from AI response. Robust against markdown wrapping."""
    try:
        # Strip markdown code blocks if present
        cleaned = text.strip()
        if cleaned.startswith('```'):
            lines = cleaned.split('\n')
            lines = [l for l in lines if not l.strip().startswith('```')]
            cleaned = '\n'.join(lines)

        data = json.loads(cleaned)
        return AIDecision(
            action=str(data.get('action', 'HOLD')).upper(),
            side=data.get('side'),
            confidence=float(data.get('confidence', 0.5)),
            setup_quality=float(data.get('setup_quality', 0.5)),
            reasons=data.get('reasons', []),
            warnings=data.get('warnings', []),
            risk_flags=data.get('risk_flags', []),
            source=source,
            raw_response=text[:500],
        )
    except Exception as e:
        log.warning("Failed to parse %s response: %s", source, e)
        return AIDecision(action='HOLD', source=source, warnings=[f'parse error: {e}'])

# -------------------------------------------------------------------
# AI providers
# -------------------------------------------------------------------
async def _call_claude(features: dict) -> AIDecision:
    if not SETTINGS.CLAUDE_API_KEY:
        return AIDecision(action='HOLD', source='claude', warnings=['no API key'])
    start = time.time()
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=SETTINGS.CLAUDE_API_KEY)
        prompt = _build_prompt(features)

        # Run sync client in executor to not block event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: client.messages.create(
            model=SETTINGS.CLAUDE_MODEL,
            max_tokens=500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ))
        text = response.content[0].text
        dec = _parse_ai_response(text, 'claude')
        dec.latency_ms = int((time.time() - start) * 1000)
        return dec
    except Exception as e:
        log.warning("Claude call failed: %s", e)
        return AIDecision(action='HOLD', source='claude', warnings=[f'API error: {e}'],
                         latency_ms=int((time.time() - start) * 1000))


async def _call_openai(features: dict) -> AIDecision:
    if not SETTINGS.OPENAI_API_KEY:
        return AIDecision(action='HOLD', source='openai', warnings=['no API key'])
    start = time.time()
    try:
        import openai
        client = openai.OpenAI(api_key=SETTINGS.OPENAI_API_KEY)
        prompt = _build_prompt(features)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: client.chat.completions.create(
            model=SETTINGS.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.3,
        ))
        text = response.choices[0].message.content
        dec = _parse_ai_response(text, 'openai')
        dec.latency_ms = int((time.time() - start) * 1000)
        return dec
    except Exception as e:
        log.warning("OpenAI call failed: %s", e)
        return AIDecision(action='HOLD', source='openai', warnings=[f'API error: {e}'],
                         latency_ms=int((time.time() - start) * 1000))

# -------------------------------------------------------------------
# Local heuristic (ported from original ai_decider)
# -------------------------------------------------------------------
def _local_heuristic(features: dict) -> AIDecision:
    merged = features.get('merged', {})
    d = str(merged.get('merged_direction', 'HOLD')).upper()
    try:
        sc = float(merged.get('merged_score', 0.0))
    except Exception:
        sc = 0.0

    # Gather context from snapshots
    by_tf = features.get('by_tf', {})
    adx_vals, rsi_vals, bb_vals = [], [], []
    for tf, sig in by_tf.items():
        snap = sig.get('snapshot', {})
        if snap.get('adx') is not None: adx_vals.append(float(snap['adx']))
        if snap.get('rsi') is not None: rsi_vals.append(float(snap['rsi']))
        if snap.get('bb_position') is not None: bb_vals.append(float(snap['bb_position']))

    avg_adx = sum(adx_vals) / len(adx_vals) if adx_vals else 25.0
    avg_rsi = sum(rsi_vals) / len(rsi_vals) if rsi_vals else 50.0
    avg_bb = sum(bb_vals) / len(bb_vals) if bb_vals else 0.5

    # Base confidence
    conf = 0.50 + abs(sc) * 0.15
    reasons = []
    warnings = []
    risk_flags = []

    # ADX modulation
    if avg_adx >= SETTINGS.ADX_STRONG_TREND:
        conf += 0.10; reasons.append(f'Strong trend ADX={avg_adx:.0f}')
    elif avg_adx < SETTINGS.ADX_TREND_MIN:
        conf -= 0.10; warnings.append(f'Weak trend ADX={avg_adx:.0f}')

    # Bollinger modulation
    if d == 'BUY' and avg_bb < 0.25:
        conf += 0.05; reasons.append('Near BB lower')
    elif d == 'SELL' and avg_bb > 0.75:
        conf += 0.05; reasons.append('Near BB upper')
    elif d == 'BUY' and avg_bb > 0.85:
        conf -= 0.08; risk_flags.append('Buying near BB upper')
    elif d == 'SELL' and avg_bb < 0.15:
        conf -= 0.08; risk_flags.append('Selling near BB lower')

    # RSI extremes
    if d == 'BUY' and avg_rsi > 75:
        conf -= 0.10; risk_flags.append(f'RSI overbought {avg_rsi:.0f}')
    elif d == 'SELL' and avg_rsi < 25:
        conf -= 0.10; risk_flags.append(f'RSI oversold {avg_rsi:.0f}')

    # Decisiveness boost when a per-TF divergence trigger fired.
    # The trigger is a high-bar signal (strong divergence + candle confirm)
    # so we give it a small confidence bump to avoid gating it out.
    triggered = False
    for tf, sig in by_tf.items():
        if 'TRIGGER:' in str(sig.get('reasons', '')):
            triggered = True
            break
    if triggered:
        conf += 0.05
        reasons.append('Divergence trigger fired')

    conf = max(0.0, min(1.0, conf))

    # Decision
    action = 'HOLD'
    side = None
    if d == 'BUY' and sc > SETTINGS.SIGNAL_SCORE_MIN and conf >= SETTINGS.AI_CONFIDENCE_MIN:
        action = 'ENTER'; side = 'BUY'
        reasons.append(f'Score {sc:.2f} > {SETTINGS.SIGNAL_SCORE_MIN}')
    elif d == 'SELL' and sc < -SETTINGS.SIGNAL_SCORE_MIN and conf >= SETTINGS.AI_CONFIDENCE_MIN:
        action = 'EXIT'; side = 'SELL'
        reasons.append(f'Score {sc:.2f} < -{SETTINGS.SIGNAL_SCORE_MIN}')

    return AIDecision(
        action=action, side=side, confidence=conf,
        setup_quality=abs(sc) / 2,
        reasons=reasons, warnings=warnings, risk_flags=risk_flags,
        source='local',
    )

# -------------------------------------------------------------------
# Fusion layer
# -------------------------------------------------------------------
def _fuse_decisions(local: AIDecision, remotes: list, policy: str) -> FusionResult:
    all_decisions = [local] + remotes

    if policy == 'local_only':
        return FusionResult(
            final_action=local.action, final_side=local.side,
            final_confidence=local.confidence, policy_used=policy,
            decisions=all_decisions,
            consensus_notes=f'Local only: {local.action} ({local.confidence:.2f})',
        )

    if policy == 'advisory':
        notes_parts = [f'Local: {local.action}']
        for r in remotes:
            notes_parts.append(f'{r.source}: {r.action} ({r.confidence:.2f})')
        return FusionResult(
            final_action=local.action, final_side=local.side,
            final_confidence=local.confidence, policy_used=policy,
            decisions=all_decisions,
            consensus_notes=' | '.join(notes_parts),
        )

    # For majority and strict_consensus, count votes
    valid = [d for d in all_decisions if d.action != 'HOLD' or True]
    votes = {}
    for d in valid:
        key = d.action
        if key not in votes:
            votes[key] = {'count': 0, 'confidence_sum': 0, 'side': d.side}
        votes[key]['count'] += 1
        votes[key]['confidence_sum'] += d.confidence

    if policy == 'majority':
        # Pick action with most votes; ties = HOLD
        best_action = 'HOLD'
        best_count = 0
        best_conf = 0
        best_side = None
        for act, info in votes.items():
            if info['count'] > best_count or (info['count'] == best_count and info['confidence_sum'] > best_conf):
                best_action = act
                best_count = info['count']
                best_conf = info['confidence_sum']
                best_side = info['side']

        avg_conf = best_conf / best_count if best_count > 0 else 0
        total = len(valid)
        overridden = best_action != local.action

        notes_parts = []
        for d in all_decisions:
            notes_parts.append(f'{d.source}={d.action}({d.confidence:.2f})')

        return FusionResult(
            final_action=best_action, final_side=best_side,
            final_confidence=avg_conf, policy_used=policy,
            decisions=all_decisions,
            consensus_notes=f'Majority {best_count}/{total}: ' + ' | '.join(notes_parts),
            was_overridden=overridden,
        )

    if policy == 'strict_consensus':
        actions = set(d.action for d in valid)
        if len(actions) == 1:
            action = actions.pop()
            avg_conf = sum(d.confidence for d in valid) / len(valid)
            side = valid[0].side
            notes = 'Unanimous: ' + ', '.join(f'{d.source}={d.action}' for d in valid)
            return FusionResult(
                final_action=action, final_side=side,
                final_confidence=avg_conf, policy_used=policy,
                decisions=all_decisions, consensus_notes=notes,
            )
        else:
            notes = 'No consensus: ' + ', '.join(f'{d.source}={d.action}' for d in valid)
            return FusionResult(
                final_action='HOLD', final_side=None,
                final_confidence=0.3, policy_used=policy,
                decisions=all_decisions, consensus_notes=notes,
            )

    # Fallback
    return FusionResult(
        final_action=local.action, final_side=local.side,
        final_confidence=local.confidence, policy_used='fallback',
        decisions=all_decisions, consensus_notes='Unknown policy, using local',
    )

# -------------------------------------------------------------------
# Log to DB
# -------------------------------------------------------------------
def _log_decision(pair: str, result: FusionResult):
    try:
        execute(
            """INSERT INTO ai_decisions(ts, pair, action, side, confidence, setup_quality,
               reasons, warnings, risk_flags, source, fusion_policy, was_executed)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,0)""",
            (int(time.time()), pair, result.final_action, result.final_side,
             result.final_confidence, 0,
             json.dumps([r for d in result.decisions for r in d.reasons]),
             json.dumps([w for d in result.decisions for w in d.warnings]),
             json.dumps([f for d in result.decisions for f in d.risk_flags]),
             ','.join(d.source for d in result.decisions),
             result.policy_used)
        )
    except Exception as e:
        log.warning("Failed to log AI decision: %s", e)

# -------------------------------------------------------------------
# Main entry point
# -------------------------------------------------------------------
async def decide(features: dict) -> FusionResult:
    """
    Main decision function.
    1. Run local heuristic (sync)
    2. If AI fusion enabled and policy != local_only, fire Claude + OpenAI concurrently
    3. Fuse according to policy
    4. Log to ai_decisions table
    """
    pair = features.get('pair', '?')
    local = _local_heuristic(features)

    policy = SETTINGS.AI_FUSION_POLICY
    remotes = []

    if SETTINGS.FEATURE_AI_FUSION and policy != 'local_only':
        tasks = []
        if SETTINGS.CLAUDE_API_KEY:
            tasks.append(_call_claude(features))
        if SETTINGS.OPENAI_API_KEY:
            tasks.append(_call_openai(features))

        if tasks:
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=SETTINGS.AI_TIMEOUT_SECONDS + 5
                )
                for r in results:
                    if isinstance(r, AIDecision):
                        remotes.append(r)
                    elif isinstance(r, Exception):
                        log.warning("AI provider error: %s", r)
            except asyncio.TimeoutError:
                log.warning("AI fusion timed out after %ds", SETTINGS.AI_TIMEOUT_SECONDS + 5)

    result = _fuse_decisions(local, remotes, policy)
    _log_decision(pair, result)
    return result
