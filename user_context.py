# user_context.py
# Per-user context object that carries all user-specific settings through call chains.
# This replaces reading from global SETTINGS for user-specific parameters.

import logging
from dataclasses import dataclass
from typing import Optional
from config import SETTINGS

log = logging.getLogger(__name__)


@dataclass
class UserContext:
    """Carries all per-user settings through the execution pipeline."""
    user_id: int
    tg_username: str = ''
    tier: str = 'BASIC'

    # Trading settings
    capital_usd: float = 1000.0
    risk_per_trade: float = 0.01
    max_open_trades: int = 2
    daily_loss_limit: float = 50.0
    paper_trading: bool = True
    trade_mode: str = 'PAPER'
    autotrade_enabled: bool = False

    # Exchange credentials (decrypted, ephemeral — never persist these)
    exchange_name: str = 'kraken'
    exchange_key: str = ''
    exchange_secret: str = ''

    # Portfolio settings
    max_portfolio_exposure: float = 0.50
    capital_per_trade_pct: float = 0.10
    ai_fusion_policy: str = 'local_only'

    # Mode system
    mode: str = 'signal_only'
    ai_mode: str = 'signal_only'
    panic_stopped: bool = False

    # Visual settings
    visuals_enabled: bool = True
    visuals_style: str = 'dark'
    visuals_density: str = 'detailed'
    show_indicators: bool = True
    show_ichimoku: bool = True
    show_rsi: bool = True
    show_macd: bool = True
    show_levels: bool = False
    show_divergence_marks: bool = True
    show_volume: bool = False

    @classmethod
    def load(cls, user_id: int) -> 'UserContext':
        """Load user settings from database and decrypt exchange keys."""
        from storage import fetchone
        row = fetchone(
            "SELECT tg_username, tier, autotrade_enabled, trade_mode, "
            "daily_loss_limit, max_open_trades, "
            "capital_usd, risk_per_trade, exchange_key_enc, exchange_secret_enc, "
            "exchange_name, paper_trading, max_portfolio_exposure, capital_per_trade_pct, "
            "ai_fusion_policy "
            "FROM users WHERE user_id=?",
            (user_id,)
        )
        if not row:
            log.warning("UserContext.load: user %d not found, using defaults", user_id)
            return cls(user_id=user_id)

        (tg_username, tier, autotrade, trade_mode,
         dll, mot,
         capital, rpt, key_enc, secret_enc,
         ex_name, paper, mpe, cptp,
         aifp) = row

        # Decrypt exchange credentials
        ex_key = ''
        ex_secret = ''
        if key_enc and secret_enc:
            try:
                from crypto_utils import decrypt_credential
                ex_key = decrypt_credential(key_enc)
                ex_secret = decrypt_credential(secret_enc)
            except Exception as e:
                log.warning("Failed to decrypt credentials for user %d: %s", user_id, e)

        ctx = cls(
            user_id=user_id,
            tg_username=tg_username or '',
            tier=tier or 'BASIC',
            capital_usd=float(capital) if capital else SETTINGS.CAPITAL_USD,
            risk_per_trade=float(rpt) if rpt else SETTINGS.RISK_PER_TRADE,
            max_open_trades=int(mot) if mot else SETTINGS.MAX_OPEN_TRADES,
            daily_loss_limit=float(dll) if dll else SETTINGS.DAILY_LOSS_LIMIT_USD,
            paper_trading=bool(int(paper)) if paper is not None else SETTINGS.PAPER_TRADING,
            trade_mode=trade_mode or 'PAPER',
            autotrade_enabled=bool(int(autotrade)) if autotrade else False,
            exchange_name=ex_name or SETTINGS.EXCHANGE,
            exchange_key=ex_key,
            exchange_secret=ex_secret,
            max_portfolio_exposure=float(mpe) if mpe else SETTINGS.MAX_PORTFOLIO_EXPOSURE,
            capital_per_trade_pct=float(cptp) if cptp else SETTINGS.CAPITAL_PER_TRADE_PCT,
            ai_fusion_policy=aifp or SETTINGS.AI_FUSION_POLICY,
        )

        # Load from user_settings table (mode, ai_mode, panic_stop)
        try:
            from storage import get_user_settings
            settings = get_user_settings(user_id)
            if settings:
                ctx.mode = settings.get('mode') or 'signal_only'
                ctx.ai_mode = settings.get('ai_mode') or 'signal_only'
                ctx.panic_stopped = bool(settings.get('panic_stop'))
                if settings.get('default_exchange'):
                    ctx.exchange_name = settings['default_exchange']
                ctx.paper_trading = ctx.mode != 'live'
                ctx.trade_mode = 'LIVE' if ctx.mode == 'live' else 'PAPER'
                # Visual settings
                if settings.get('visuals_enabled') is not None:
                    ctx.visuals_enabled = bool(settings['visuals_enabled'])
                if settings.get('visuals_style'):
                    ctx.visuals_style = settings['visuals_style']
                if settings.get('visuals_density'):
                    ctx.visuals_density = settings['visuals_density']
                for key in ('show_indicators', 'show_ichimoku', 'show_rsi', 'show_macd',
                            'show_levels', 'show_divergence_marks', 'show_volume'):
                    if settings.get(key) is not None:
                        setattr(ctx, key, bool(settings[key]))
        except Exception:
            pass

        # Try credentials table (V2 envelope encryption) with fallback to users table
        try:
            from storage import get_credential
            cred = get_credential(user_id, 'ccxt')
            if cred:
                from crypto_utils import decrypt_exchange_keys
                dk, ds = decrypt_exchange_keys(
                    cred['api_key_enc'], cred['api_secret_enc'],
                    cred.get('data_key_enc', ''), cred.get('encryption_version', 1))
                if dk and ds:
                    ctx.exchange_key = dk
                    ctx.exchange_secret = ds
                    ctx.exchange_name = cred.get('exchange_id') or ctx.exchange_name
        except Exception:
            pass

        return ctx

    @classmethod
    def from_settings(cls, user_id: int) -> 'UserContext':
        """Backward-compat: build from global SETTINGS. For single-user deployments."""
        return cls(
            user_id=user_id,
            capital_usd=SETTINGS.CAPITAL_USD,
            risk_per_trade=SETTINGS.RISK_PER_TRADE,
            max_open_trades=SETTINGS.MAX_OPEN_TRADES,
            daily_loss_limit=SETTINGS.DAILY_LOSS_LIMIT_USD,
            paper_trading=SETTINGS.PAPER_TRADING,
            trade_mode='PAPER' if SETTINGS.PAPER_TRADING else 'LIVE',
            autotrade_enabled=False,
            exchange_name=SETTINGS.EXCHANGE,
            exchange_key=SETTINGS.KRAKEN_API_KEY,
            exchange_secret=SETTINGS.KRAKEN_API_SECRET,
            max_portfolio_exposure=SETTINGS.MAX_PORTFOLIO_EXPOSURE,
            capital_per_trade_pct=SETTINGS.CAPITAL_PER_TRADE_PCT,
            ai_fusion_policy=SETTINGS.AI_FUSION_POLICY,
        )

    @property
    def is_live(self) -> bool:
        return not self.paper_trading and self.trade_mode == 'LIVE'

    @property
    def has_exchange_keys(self) -> bool:
        return bool(self.exchange_key and self.exchange_secret)

    def get_owner_id(self) -> int:
        """Return user_id — used for passing through query chains."""
        return self.user_id
