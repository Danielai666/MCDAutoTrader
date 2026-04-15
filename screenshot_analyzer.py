# screenshot_analyzer.py
# Screenshot-based chart analysis using AI vision (Claude or OpenAI).
# Flow: /analyze_screens → user sends up to 12 images → /done triggers analysis.
# Images saved to temp dir, analyzed, then deleted.
# Feature-flagged: FEATURE_SCREENSHOTS must be true.

import os
import time
import json
import base64
import logging
import tempfile
import shutil
from dataclasses import dataclass, field
from typing import List, Optional
from config import SETTINGS

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Session management
# -------------------------------------------------------------------

@dataclass
class ScreenshotSession:
    user_id: int
    chat_id: int
    started_ts: float = 0.0
    image_paths: List[str] = field(default_factory=list)
    temp_dir: str = ''

    @property
    def image_count(self) -> int:
        return len(self.image_paths)

    @property
    def is_full(self) -> bool:
        return self.image_count >= SETTINGS.SCREENSHOT_MAX_IMAGES

    @property
    def is_expired(self) -> bool:
        return time.time() - self.started_ts > 600  # 10 min TTL


_sessions: dict = {}  # uid -> ScreenshotSession


def start_session(user_id: int, chat_id: int) -> ScreenshotSession:
    """Start a new screenshot analysis session."""
    # Cleanup previous session
    end_session(user_id)

    temp_dir = tempfile.mkdtemp(prefix=f"mcd_screenshots_{user_id}_")
    session = ScreenshotSession(
        user_id=user_id,
        chat_id=chat_id,
        started_ts=time.time(),
        temp_dir=temp_dir,
    )
    _sessions[user_id] = session
    return session


def get_session(user_id: int) -> Optional[ScreenshotSession]:
    session = _sessions.get(user_id)
    if session and session.is_expired:
        end_session(user_id)
        return None
    return session


def add_image(user_id: int, file_path: str) -> bool:
    """Add an image to the current session. Returns False if session full."""
    session = get_session(user_id)
    if not session:
        return False
    if session.is_full:
        return False
    session.image_paths.append(file_path)
    return True


def end_session(user_id: int):
    """End session and cleanup temp files."""
    session = _sessions.pop(user_id, None)
    if session and session.temp_dir and os.path.exists(session.temp_dir):
        try:
            shutil.rmtree(session.temp_dir)
        except Exception as e:
            log.warning("Failed to cleanup screenshot dir: %s", e)


# -------------------------------------------------------------------
# Analysis prompt
# -------------------------------------------------------------------

_ANALYSIS_PROMPT = """You are a professional technical chart analyst providing CONTEXT and CONFIRMATION for a signal pipeline whose PRIMARY divergence detection comes from indicator math (RSI/MACD) elsewhere in the system.

Your role is NOT to be the primary divergence detector. Treat any divergence you see on the chart as a CONFIRMATION cue only — the authoritative divergence signal comes from the indicator engine, not from vision. Focus your value on: market context, candlestick/price-action patterns, structural levels, and confluence that the indicator engine cannot compute from OHLCV alone.

For each chart, identify and report:

1. **Symbol & Timeframe** (if visible)
2. **Trend Summary**: overall direction (bullish/bearish/sideways), strength
3. **Divergence (confirmation only)**: note if chart visually agrees/disagrees with a potential RSI/MACD divergence. Do NOT treat this as a standalone trigger.
4. **Indicator States**: RSI level, MACD position, moving average alignment
5. **Candlestick Patterns**: any reversal or continuation patterns at key levels (PRIMARY vision value)
6. **Key Levels**: support/resistance, previous highs/lows (PRIMARY vision value)
7. **Actionable Plan**:
   - Entry zone (price range)
   - Stop Loss level
   - Take Profit 1 and Take Profit 2
   - Invalidation level (where the setup fails)
8. **Confidence**: HIGH / MEDIUM / LOW with reasoning

Respond in this JSON format:
{
  "charts": [
    {
      "symbol": "...",
      "timeframe": "...",
      "trend": "bullish|bearish|sideways",
      "trend_strength": "strong|moderate|weak",
      "divergence": {"type": "none|regular_bullish|regular_bearish|hidden_bullish|hidden_bearish", "details": "..."},
      "indicators": {"rsi": "...", "macd": "...", "ma": "..."},
      "patterns": ["..."],
      "key_levels": {"support": [...], "resistance": [...]},
      "plan": {
        "bias": "BUY|SELL|HOLD",
        "entry": "...",
        "stop_loss": "...",
        "tp1": "...",
        "tp2": "...",
        "invalidation": "..."
      },
      "confidence": "HIGH|MEDIUM|LOW",
      "reasoning": "..."
    }
  ],
  "overall_summary": "..."
}
"""


# -------------------------------------------------------------------
# AI Vision Analysis
# -------------------------------------------------------------------

async def analyze_screenshots(session: ScreenshotSession) -> dict:
    """Analyze screenshots using AI vision model.
    Returns structured analysis result.
    """
    if not session.image_paths:
        return {'error': 'No images to analyze'}

    # Encode images to base64
    image_contents = []
    for path in session.image_paths:
        try:
            with open(path, 'rb') as f:
                data = f.read()
            b64 = base64.b64encode(data).decode()
            # Detect MIME type
            if path.lower().endswith('.png'):
                mime = 'image/png'
            elif path.lower().endswith(('.jpg', '.jpeg')):
                mime = 'image/jpeg'
            else:
                mime = 'image/png'
            image_contents.append({'data': b64, 'mime': mime, 'path': path})
        except Exception as e:
            log.warning("Failed to read screenshot %s: %s", path, e)

    if not image_contents:
        return {'error': 'Failed to read images'}

    # Try Claude first, then OpenAI
    result = None
    if SETTINGS.CLAUDE_API_KEY:
        result = await _analyze_with_claude(image_contents)
    if not result and SETTINGS.OPENAI_API_KEY:
        result = await _analyze_with_openai(image_contents)
    if not result:
        return {'error': 'No AI vision provider available. Set CLAUDE_API_KEY or OPENAI_API_KEY.'}

    return result


async def _analyze_with_claude(images: list) -> Optional[dict]:
    """Analyze using Claude vision."""
    import asyncio
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=SETTINGS.CLAUDE_API_KEY)

        # Build message content with images
        content = []
        for img in images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img['mime'],
                    "data": img['data'],
                }
            })
        content.append({"type": "text", "text": _ANALYSIS_PROMPT})

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: client.messages.create(
            model=SETTINGS.SCREENSHOT_VISION_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": content}],
        ))

        text = response.content[0].text
        return _parse_analysis(text)
    except Exception as e:
        log.error("Claude vision analysis failed: %s", e)
        return None


async def _analyze_with_openai(images: list) -> Optional[dict]:
    """Analyze using OpenAI GPT-4V."""
    import asyncio
    try:
        import openai
        client = openai.OpenAI(api_key=SETTINGS.OPENAI_API_KEY)

        content = []
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img['mime']};base64,{img['data']}"}
            })
        content.append({"type": "text", "text": _ANALYSIS_PROMPT})

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            max_tokens=2000,
        ))

        text = response.choices[0].message.content
        return _parse_analysis(text)
    except Exception as e:
        log.error("OpenAI vision analysis failed: %s", e)
        return None


def _parse_analysis(text: str) -> dict:
    """Parse JSON from AI response. Robust against markdown wrapping."""
    try:
        cleaned = text.strip()
        if cleaned.startswith('```'):
            lines = cleaned.split('\n')
            lines = [l for l in lines if not l.strip().startswith('```')]
            cleaned = '\n'.join(lines)
        return json.loads(cleaned)
    except Exception:
        # Return raw text if JSON parsing fails
        return {'raw_analysis': text, 'charts': []}


# -------------------------------------------------------------------
# Format result for Telegram
# -------------------------------------------------------------------

def format_analysis_result(result: dict) -> str:
    """Format analysis result for Telegram message."""
    if result.get('error'):
        return f"Analysis failed: {result['error']}"

    if result.get('raw_analysis'):
        # Couldn't parse JSON, return raw text (truncated)
        raw = result['raw_analysis']
        return raw[:3000] if len(raw) > 3000 else raw

    lines = []
    charts = result.get('charts', [])
    for i, chart in enumerate(charts, 1):
        symbol = chart.get('symbol', 'Unknown')
        tf = chart.get('timeframe', '?')
        trend = chart.get('trend', '?')
        confidence = chart.get('confidence', '?')

        lines.append(f"Chart {i}: {symbol} {tf}")
        lines.append(f"Trend: {trend} ({chart.get('trend_strength', '?')})")

        div = chart.get('divergence', {})
        if div.get('type') != 'none':
            lines.append(f"Divergence: {div.get('type', 'none')}")

        plan = chart.get('plan', {})
        if plan.get('bias') and plan['bias'] != 'HOLD':
            lines.append(f"Bias: {plan['bias']}")
            if plan.get('entry'):
                lines.append(f"Entry: {plan['entry']} | SL: {plan.get('stop_loss', '?')}")
            if plan.get('tp1'):
                lines.append(f"TP1: {plan['tp1']} | TP2: {plan.get('tp2', '?')}")

        lines.append(f"Confidence: {confidence}")
        if chart.get('reasoning'):
            lines.append(f"Note: {chart['reasoning'][:100]}")
        lines.append("")

    summary = result.get('overall_summary', '')
    if summary:
        lines.append(f"Summary: {summary}")

    return "\n".join(lines) if lines else "No analysis results."
