import pandas as pd

def is_bullish_engulfing(prev: pd.Series, cur: pd.Series) -> bool:
    if prev['close'] >= prev['open']: return False
    if cur['close'] <= cur['open']: return False
    return (cur['open'] <= prev['close']) and (cur['close'] >= prev['open'])

def is_bearish_engulfing(prev: pd.Series, cur: pd.Series) -> bool:
    if prev['close'] <= prev['open']: return False
    if cur['close'] >= cur['open']: return False
    return (cur['open'] >= prev['close']) and (cur['close'] <= prev['open'])

def is_rejection_candle(c: pd.Series, min_wick_ratio: float = 0.55) -> tuple[bool, str]:
    rng = c['high'] - c['low']
    if rng == 0: return False, ""
    upper = c['high'] - max(c['open'], c['close'])
    lower = min(c['open'], c['close']) - c['low']
    body = abs(c['close'] - c['open'])

    if upper > rng * min_wick_ratio and body < rng * 0.4: return True, 'bear'
    if lower > rng * min_wick_ratio and body < rng * 0.4: return True, 'bull'
    return False, ""

def volume_spike(df: pd.DataFrame, lookback: int = 20, ratio: float = 1.5) -> bool:
    if len(df) < lookback + 1: return False
    avg = df['volume'].iloc[-lookback-1:-1].mean()
    return df['volume'].iloc[-1] > avg * ratio