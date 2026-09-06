import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

class LiquidityEngine:
    def __init__(self, ex: ccxt.Exchange, symbol: str):
        self.ex = ex
        self.symbol = symbol

    async def detect_liquidity_pools(self, df_15m: pd.DataFrame, lookback: int = 50) -> dict:
        """
        Scans the M15 chart for Equal Highs (EQH) and Equal Lows (EQL).
        These are magnets for MM stop-liquidity sweeps.
        """
        recent = df_15m.tail(lookback)
        highs = recent['high'].values
        lows = recent['low'].values
        
        def find_equals(levels):
            equals = []
            for i in range(len(levels)):
                for j in range(i+1, len(levels)):
                    if abs(levels[i] - levels[j]) / levels[i] < 0.0005:
                        price = (levels[i] + levels[j]) / 2
                        if not any(abs(price - e) / e < 0.0005 for e in equals):
                            equals.append(float(price))
            return equals

        return {
            "equal_highs": find_equals(highs),
            "equal_lows": find_equals(lows),
            "has_liquidity_pool": len(find_equals(highs)) > 0 or len(find_equals(lows)) > 0
        }

    async def get_real_delta(self, limit: int = 1000) -> dict:
        """
        Fetches actual tick-by-tick trade data to calculate True Aggressor Delta.
        Market Buys vs Market Sells.
        """
        try:
            trades = await self.ex.fetch_trades(self.symbol, limit=limit)
            buy_vol = sum(t['amount'] for t in trades if t['side'] == 'buy')
            sell_vol = sum(t['amount'] for t in trades if t['side'] == 'sell')
            total_vol = buy_vol + sell_vol
            
            return {
                "buy_vol": float(buy_vol),
                "sell_vol": float(sell_vol),
                "delta": float(buy_vol - sell_vol),
                "delta_pct": float((buy_vol - sell_vol) / total_vol) if total_vol > 0 else 0
            }
        except Exception as e:
            print(f"[LiquidityEngine] Delta error: {e}")
            return {"buy_vol": 0, "sell_vol": 0, "delta": 0, "delta_pct": 0}