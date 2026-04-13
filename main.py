import os
import time
import argparse
from typing import List, Dict
from loguru import logger
from dotenv import load_dotenv
import pandas as pd

try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None

try:
    from ta.trend import MACD
    from ta.momentum import RSIIndicator
except Exception:
    raise SystemExit("Missing 'ta'. Run: pip install -r requirements.txt")

def env_list(name: str, default: str):
    raw = os.getenv(name, default)
    return [p.strip() for p in raw.split(",") if p.strip()]

def load_config() -> Dict:
    load_dotenv(override=False)
    return {
        "MODE": os.getenv("MODE", "paper").lower(),
        "SYMBOLS": env_list("SYMBOLS", "BTC/USDT,ETH/USDT"),
        "TIMEFRAMES": env_list("TIMEFRAMES", "15m,1h"),
        "POLL_SECONDS": int(os.getenv("POLL_SECONDS", "30")),
        "TRADE_AMOUNT_USD": float(os.getenv("TRADE_AMOUNT_USD", "20")),
        "KRAKEN_API_KEY": os.getenv("KRAKEN_API_KEY", ""),
        "KRAKEN_API_SECRET": os.getenv("KRAKEN_API_SECRET", ""),
    }

class KrakenWrap:
    def __init__(self, mode: str, key: str = "", secret: str = ""):
        self.mode = mode
        self._ex = None
        if ccxt is not None:
            self._ex = ccxt.kraken({"enableRateLimit": True, "apiKey": key, "secret": secret})
        else:
            logger.warning("ccxt not available; cannot fetch market data.")

        self.paper_cash = 10000.0
        self.paper_pos = {}

    @staticmethod
    def map_symbol(symbol: str) -> str:
        return symbol.replace("BTC/", "XBT/")

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        if self._ex is None:
            raise RuntimeError("ccxt not installed; cannot fetch OHLCV.")
        try:
            return self._ex.fetch_ohlcv(self.map_symbol(symbol), timeframe=timeframe, limit=limit)
        except Exception:
            return self._ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def paper_buy(self, symbol: str, usd: float, price: float):
        units = usd / max(1e-9, price)
        pos = self.paper_pos.get(symbol, {"units": 0.0, "avg": 0.0})
        new_units = pos["units"] + units
        new_avg = (pos["avg"] * pos["units"] + price * units) / max(1e-9, new_units)
        self.paper_pos[symbol] = {"units": new_units, "avg": new_avg}
        self.paper_cash -= usd
        logger.info(f"[PAPER] BUY {symbol}: ${usd:.2f} @ ~{price:.4f} -> units={new_units:.6f}, cash=${self.paper_cash:.2f}")

    def paper_sell(self, symbol: str, price: float):
        pos = self.paper_pos.get(symbol, {"units": 0.0, "avg": 0.0})
        if pos["units"] <= 0:
            logger.info(f"[PAPER] No position to sell for {symbol}.")
            return
        usd_value = pos["units"] * price
        self.paper_cash += usd_value
        logger.info(f"[PAPER] SELL {symbol}: units={pos['units']:.6f} @ ~{price:.4f} -> cash=${self.paper_cash:.2f}")
        self.paper_pos[symbol] = {"units": 0.0, "avg": 0.0}

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    macd = MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    rsi = RSIIndicator(close=df["close"], window=14)
    df["rsi"] = rsi.rsi()
    return df

def gen_signal(df: pd.DataFrame) -> str:
    if len(df) < 35:
        return "hold"
    macd = df["macd"]
    sig = df["macd_signal"]
    rsi = df["rsi"]
    prev = macd.iloc[-2] - sig.iloc[-2]
    curr = macd.iloc[-1] - sig.iloc[-1]
    if prev <= 0 and curr > 0 and rsi.iloc[-1] < 30:
        return "buy"
    if prev >= 0 and curr < 0 and rsi.iloc[-1] > 70:
        return "sell"
    return "hold"

def ohlcv_to_df(ohlcv):
    return pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])

def run_once(ex: KrakenWrap, symbols, timeframes, trade_usd, mode):
    for sym in symbols:
        for tf in timeframes:
            try:
                ohlcv = ex.fetch_ohlcv(sym, tf, limit=200)
            except Exception as e:
                logger.error(f"fetch_ohlcv failed for {sym} {tf}: {e}")
                continue
            df = ohlcv_to_df(ohlcv)
            df = compute_indicators(df)
            sig = gen_signal(df)
            price = float(df["close"].iloc[-1])
            logger.info(f"{sym} {tf} | last={price:.4f} | macd={df['macd'].iloc[-1]:.4f} sig={df['macd_signal'].iloc[-1]:.4f} rsi={df['rsi'].iloc[-1]:.2f} -> {sig}")
            if mode == "paper":
                if sig == "buy":
                    ex.paper_buy(sym, trade_usd, price)
                elif sig == "sell":
                    ex.paper_sell(sym, price)
            else:
                if sig in ("buy","sell"):
                    logger.info(f"[LIVE] Signal={sig} (order logic placeholder)")
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    ex = KrakenWrap(mode=cfg["MODE"], key=cfg["KRAKEN_API_KEY"], secret=cfg["KRAKEN_API_SECRET"])

    if args.once:
        run_once(ex, cfg["SYMBOLS"], cfg["TIMEFRAMES"], cfg["TRADE_AMOUNT_USD"], cfg["MODE"])
        return

    while True:
        try:
            run_once(ex, cfg["SYMBOLS"], cfg["TIMEFRAMES"], cfg["TRADE_AMOUNT_USD"], cfg["MODE"])
        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
            break
        except Exception as e:
            logger.exception(f"Loop error: {e}")
        time.sleep(max(5, cfg["POLL_SECONDS"]))

if __name__ == "__main__":
    logger.remove()
    logger.add(lambda m: print(m, end=""), format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
    logger.info("Starting MACD+RSI bot (post-backup kit)")
    main()