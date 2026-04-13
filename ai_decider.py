# ai_decider.py
# Thin wrapper for backward compatibility. Real logic is in ai_fusion.py.
from typing import Dict
from ai_fusion import decide as _fusion_decide, _local_heuristic


async def decide_async(features: Dict) -> Dict:
    """Async entry point used by scheduler. Returns fusion result as dict."""
    result = await _fusion_decide(features)
    return {
        'decision': result.final_action,
        'confidence': result.final_confidence,
        'notes': result.consensus_notes,
        'side': result.final_side,
        'fusion': result.to_dict(),
    }


def decide(features: Dict) -> Dict:
    """Sync fallback for backward compatibility."""
    local = _local_heuristic(features)
    return {
        'decision': local.action,
        'confidence': local.confidence,
        'notes': ', '.join(local.reasons),
        'side': local.side,
    }
