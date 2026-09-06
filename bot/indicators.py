import pandas as pd
import numpy as np

def vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df['high'] + df['low'] + df['close']) / 3
    return (tp * df['volume']).cumsum() / df['volume'].cumsum()

def detect_fvg(df: pd.DataFrame) -> dict:
    """
    Fair Value Gap (FVG) / Imbalance Zone detection.
    Institutions leave 3-candle imbalances when executing massive blocks.
    If price revisits an FVG, it's a high-probability entry zone.
    """
    if len(df) < 3: return {}
    
    # Bullish FVG: Low of candle 3 > High of candle 1
    c1_high = df['high'].iloc[-3]
    c3_low = df['low'].iloc[-1]
    
    # Bearish FVG: High of candle 3 < Low of candle 1
    c1_low = df['low'].iloc[-3]
    c3_high = df['high'].iloc[-1]
    
    if c3_low > c1_high:
        return {"type": "bull", "top": float(c3_low), "bottom": float(c1_high)}
    elif c3_high < c1_low:
        return {"type": "bear", "top": float(c1_low), "bottom": float(c3_high)}
    return {}

def volume_profile(df: pd.DataFrame, bins: int = 50) -> dict:
    """
    HVN (High Volume Nodes) & LVN (Low Volume Nodes).
    HVN = Institutional Accumulation/Distribution zones (Magnets).
    LVN = Rejection zones (Price slices through these rapidly).
    """
    if df.empty: return {}
    
    price_min, price_max = df['low'].min(), df['high'].max()
    edges = np.linspace(price_min, price_max, bins + 1)
    hist = np.zeros(bins)
    
    for _, row in df.iterrows():
        for i in range(bins):
            lo, hi = edges[i], edges[i+1]
            if row['high'] >= lo and row['low'] <= hi:
                hist[i] += row['volume']
                
    poc_idx = int(np.argmax(hist))
    avg_vol = np.mean(hist)
    std_vol = np.std(hist)
    
    # Identify extreme HVN and LVN
    hvns = []
    lvns = []
    for i, vol in enumerate(hist):
        if vol > avg_vol + std_vol * 1.5:  # HVN
            hvns.append(float((edges[i] + edges[i+1]) / 2))
        elif vol < avg_vol - std_vol * 0.5 and vol > 0: # LVN
            lvns.append(float((edges[i] + edges[i+1]) / 2))

    return {
        "poc": float((edges[poc_idx] + edges[poc_idx+1]) / 2),
        "hvns": hvns,
        "lvns": lvns
    }

def calculate_cvd(df: pd.DataFrame) -> dict:
    """
    Cumulative Volume Delta Proxy & Delta Divergence.
    Delta Divergence: Price makes a higher high, but Delta makes a lower high.
    This means institutions are absorbing buy aggressors (Distribution / Bearish Churn).
    """
    rng = (df['high'] - df['low']).replace(0, 1e-9)
    # Proxy: Close near high = aggressive buying, Close near low = aggressive selling
    buy_pressure = ((df['close'] - df['low']) / rng) * df['volume']
    sell_pressure = df['volume'] - buy_pressure
    delta = buy_pressure - sell_pressure
    cvd = delta.cumsum()
    
    # Divergence logic (lookback 5 candles)
    price_high_now = df['close'].iloc[-1]
    price_high_prev = df['close'].iloc[-5]
    delta_high_now = cvd.iloc[-1]
    delta_high_prev = cvd.iloc[-5]
    
    is_bear_div = price_high_now > price_high_prev and delta_high_now < delta_high_prev
    is_bull_div = price_high_now < price_high_prev and delta_high_now > delta_high_prev
    
    return {
        "cvd": float(cvd.iloc[-1]),
        "bear_divergence": bool(is_bear_div),  # Institutional distribution
        "bull_divergence": bool(is_bull_div)   # Institutional accumulation
    }

def vsa_signal(prev: pd.Series, cur: pd.Series, avg_vol: float) -> str:
    """
    Wyckoff / SMC Volume Spread Analysis.
    """
    spread = cur['high'] - cur['low']
    body = cur['close'] - cur['open']
    close_pos = (cur['close'] - cur['low']) / spread if spread > 0 else 0.5
    
    # 1. Stopping Volume (Pin bar + High Volume + closes near high on down bar)
    if cur['volume'] > avg_vol * 2.0 and body < 0 and close_pos > 0.7:
        return 'bull'  # Institutions absorbing sells
        
    # 2. Upthrust (Pin bar + High Volume + closes near low on up bar)
    if cur['volume'] > avg_vol * 2.0 and body > 0 and close_pos < 0.3:
        return 'bear'  # Institutions absorbing buys
        
    # 3. Effort vs Result (High volume, tiny spread -> churn / trap)
    if cur['volume'] > avg_vol * 1.5 and spread < (avg_vol * 0.0001):
        return 'neutral' 

    return 'neutral'