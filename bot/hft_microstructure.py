import ccxt.async_support as ccxt
import numpy as np
import pandas as pd

class HFTMicrostructure:
    """
    Quantitative microstructure metrics used by HFT desks.
    """
    def __init__(self, ex: ccxt.Exchange, symbol: str):
        self.ex = ex
        self.symbol = symbol

    async def fetch_tick_data(self, limit=1000) -> pd.DataFrame:
        """Fetches raw tick-level trade data."""
        trades = await self.ex.fetch_trades(self.symbol, limit=limit)
        if not trades: return pd.DataFrame()
        df = pd.DataFrame(trades)
        df['price'] = pd.to_numeric(df['price'])
        df['amount'] = pd.to_numeric(df['amount'])
        df['timestamp'] = pd.to_numeric(df['timestamp'])
        return df

    async def calculate_vpin(self, bucket_vol_usd=50000) -> dict:
        """
        Volume-Synchronized Probability of Informed Trading (VPIN).
        Bloomberg/HFT metric. High VPIN = Institutions are aggressively 
        entering the market (Toxic Order Flow). Low VPIN = Retail noise.
        """
        df = await self.fetch_tick_data(limit=1000)
        if df.empty: return {"vpin": 0.0, "toxic_flow": False}

        # Group trades into volume buckets (e.g., every $50k traded)
        df['usd_vol'] = df['price'] * df['amount']
        df['bucket'] = (df['usd_vol'].cumsum() // bucket_vol_usd)
        
        buckets = df.groupby('bucket')
        vpin_values = []
        
        for _, bucket in buckets:
            buys = bucket[bucket['side'] == 'buy']['amount'].sum()
            sells = bucket[bucket['side'] == 'sell']['amount'].sum()
            total = buys + sells
            if total > 0:
                vpin_values.append(abs(buys - sells) / total)
                
        # Look at the last 50 buckets
        recent_vpin = np.mean(vpin_values[-50:]) if len(vpin_values) >= 50 else np.mean(vpin_values)
        toxic = recent_vpin > 0.6  # If >60% imbalance, it's toxic (informed) flow
        
        return {
            "vpin": float(recent_vpin),
            "toxic_flow": bool(toxic)
        }

    async def calculate_kyle_lambda(self) -> dict:
        """
        Kyle's Lambda (Price Impact / Market Elasticity).
        Measures how much price moves per unit of volume.
        Low Lambda (High Volume, Low Price Move) = Institutional Absorption.
        High Lambda (Low Volume, High Price Move) = Retail driven / Illiquid (Trap).
        """
        df = await self.fetch_tick_data(limit=500)
        if len(df) < 50: return {"lambda": 0.0, "absorption": False}

        # Calculate price change and volume per tick
        df['price_change'] = df['price'].diff().abs()
        df['volume'] = df['amount']
        
        # Lambda = Cov(PriceChange, Volume) / Var(Volume)
        cov = np.cov(df['price_change'].dropna(), df['volume'].dropna())[0, 1]
        var_vol = np.var(df['volume'].dropna())
        
        lambda_val = (cov / var_vol) * 1e6 if var_vol > 0 else 0 # Scale for readability
        
        # Absorption = Huge volume, but tiny price movement (Lambda near 0)
        avg_vol = df['amount'].mean()
        recent_vol = df['amount'].tail(50).mean()
        recent_price_move = (df['price'].iloc[-1] - df['price'].iloc[-50]) / df['price'].iloc[-50]
        
        absorption = (recent_vol > avg_vol * 1.5) and (abs(recent_price_move) < 0.0005)
        
        return {
            "lambda": float(lambda_val),
            "absorption": bool(absorption)
        }