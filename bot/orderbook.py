import numpy as np
import pandas as pd
import ccxt.async_support as ccxt
from collections import deque

class OrderbookAnalyzer:
    """
    Institutional Microstructure Analyzer.
    Tracks Order Flow Imbalance (OFI), Micro-Price, Spoofing, and Icebergs.
    """
    def __init__(self, ex: ccxt.Exchange, symbol: str, limit: int = 100):
        self.ex = ex
        self.symbol = symbol
        self.limit = limit
        # Store recent snapshots to detect spoofing (walls appearing/disappearing)
        self.book_history = deque(maxlen=5) 

    async def fetch(self) -> dict:
        ob = await self.ex.fetch_order_book(self.symbol, limit=self.limit)
        # Save snapshot for historical comparison
        self.book_history.append({
            'bids': {p: s for p, s in ob['bids']},
            'asks': {p: s for p, s in ob['asks']}
        })
        return ob

    def compute_microprice(self, bids: list, asks: list) -> float:
        """
        Calculates Micro-Price. Unlike mid-price, this weights the mid by 
        the volume imbalance at the top of the book. MM algorithms use this 
        to hide their true directional bias.
        """
        if not bids or not asks: return 0.0
        best_bid, bid_vol = bids[0][0], bids[0][1]
        best_ask, ask_vol = asks[0][0], asks[0][1]
        
        total_vol = bid_vol + ask_vol
        if total_vol == 0: return (best_bid + best_ask) / 2
        
        # Microprice formula: Ask + (BidVol / TotalVol) * (Bid - Ask)
        microprice = best_ask + (bid_vol / total_vol) * (best_bid - best_ask)
        return float(microprice)

    def compute_ofi(self, bids: list, asks: list) -> dict:
        """
        Order Flow Imbalance (OFI). Tracks the net aggressor pressure.
        MM algorithms accumulate by placing passive limit orders. 
        When被动 (passive) liquidity is consumed, OFI spikes.
        """
        if len(self.book_history) < 2: return {"ofi_5lvl": 0.0, "ofi_10lvl": 0.0}
        
        prev = self.book_history[-2]
        curr = self.book_history[-1]
        
        # Calculate delta in top 5 and 10 levels
        def _ofi(side_str, levels):
            delta = 0.0
            for p, s in levels:
                prev_s = prev[side_str].get(p, 0.0)
                # If size increased, passive liquidity added. If decreased, consumed by aggressors.
                delta += (s - prev_s)
            return delta

        bid_ofi_5 = _ofi('bids', bids[:5])
        ask_ofi_5 = _ofi('asks', asks[:5])
        bid_ofi_10 = _ofi('bids', bids[:10])
        ask_ofi_10 = _ofi('asks', asks[:10])

        # Positive = Buyers consuming passive asks, Negative = Sellers consuming passive bids
        return {
            "ofi_5lvl": float(bid_ofi_5 - ask_ofi_5),
            "ofi_10lvl": float(bid_ofi_10 - ask_ofi_10)
        }

    def detect_spoofing(self, bids: list, asks: list, last_price: float) -> dict:
        """
        Ghost Walls (Spoofing): Institutions place massive limit orders 
        to trick retail into thinking there is support/resistance, then 
        cancel them before execution.
        """
        spoof_signals = {"bid_spoof": False, "ask_spoof": False}
        if len(self.book_history) < 2: return spoof_signals

        def _check_side(levels, side_str, direction):
            if not levels: return False
            # Find largest wall in current book within 0.5% of price
            for p, s in levels:
                if abs(p - last_price) / last_price <= 0.005:
                    avg_size = np.mean([sz for _, sz in levels])
                    if s > avg_size * 4.0:  # Wall is 4x larger than average
                        # Check previous snapshot. Did it just appear? (Flash order)
                        prev_size = self.book_history[-2][side_str].get(p, 0.0)
                        if prev_size < s * 0.2: # Suddenly appeared out of nowhere
                            return True
            return False

        return {
            "bid_spoof": _check_side(bids, 'bids', 'bull'),
            "ask_spoof": _check_side(asks, 'asks', 'bear')
        }

    def compute(self, ob: dict, last_price: float) -> dict:
        bids = ob.get('bids', [])
        asks = ob.get('asks', [])
        
        microprice = self.compute_microprice(bids, asks)
        ofi = self.compute_ofi(bids, asks)
        spoof = self.detect_spoofing(bids, asks, last_price)

        # Overall Depth Imbalance
        bid_vol = np.sum([s for _, s in bids[:50]])
        ask_vol = np.sum([s for _, s in asks[:50]])
        total = bid_vol + ask_vol
        depth_imbalance = (bid_vol - ask_vol) / total if total > 0 else 0

        # Score mapping (-10 to 10)
        score = 0
        # Microprice leads price: if Microprice > Last Price, institutions are bullish
        if microprice > last_price: score += 2
        else: score -= 2
        
        # OFI aggressive buying
        if ofi["ofi_5lvl"] > 0: score += 2
        else: score -= 2
        
        # Spoofing usually indicates a trap. If ask spoof exists, MM wants price to go up 
        # (to liquidate shorts) before dropping. Bullish short-term, bearish mid-term.
        if spoof["ask_spoof"]: score += 3 
        if spoof["bid_spoof"]: score -= 3

        score += (depth_imbalance * 4)

        return {
            "microprice": float(microprice),
            "ofi_5lvl": float(ofi["ofi_5lvl"]),
            "ofi_10lvl": float(ofi["ofi_10lvl"]),
            "depth_imbalance": float(depth_imbalance),
            "spoofing": spoof,
            "score": float(np.clip(score, -10, 10)),
            "strong_imbalance": abs(depth_imbalance) > 0.2
        }

    @staticmethod
    def detect_sweep(touch_candle: pd.Series, ob_info: dict, side: str) -> bool:
        """
        Liquidity Sweep / Stop Hunt: Price pierces a key level (triggering stops),
        but Microprice and OFI immediately reverse, confirming a trap.
        """
        # side here is expected_dir ('bull' or 'bear')
        
        # Bullish Sweep: Price sweeps BID liquidity (Equal Lows), traps shorts, then closes UP.
        if side == 'bull':
            if touch_candle['low'] <= touch_candle['open'] * 0.998 and touch_candle['close'] > touch_candle['open']:
                # Confirm with orderbook: Did MMs absorb the sells? (Bid imbalance > 0.2 OR Ask spoof tricking sellers)
                if ob_info.get('depth_imbalance', 0) > 0.2 or ob_info.get('spoofing', {}).get('ask_spoof'):
                    return True
                    
        # Bearish Sweep: Price sweeps ASK liquidity (Equal Highs), traps longs, then closes DOWN.
        elif side == 'bear':
            if touch_candle['high'] >= touch_candle['open'] * 1.002 and touch_candle['close'] < touch_candle['open']:
                # Confirm with orderbook: Did MMs absorb the buys? (Ask imbalance < -0.2 OR Bid spoof tricking buyers)
                if ob_info.get('depth_imbalance', 0) < -0.2 or ob_info.get('spoofing', {}).get('bid_spoof'):
                    return True
                    
        return False