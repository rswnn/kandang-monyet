import pandas as pd
from .candle_analysis import (is_bullish_engulfing, is_bearish_engulfing,
                              is_rejection_candle, volume_spike)
from .orderbook import OrderbookAnalyzer
from .indicators import vwap, volume_profile, vsa_signal, calculate_cvd, detect_fvg
from .market_data import MarketMakerData
from .liquidity_engine import LiquidityEngine
from .hft_microstructure import HFTMicrostructure
from .ai_microstructure import AIMicrostructure

class TierEvaluator:
    def __init__(self, exchange, symbol: str, config):
        self.ex = exchange
        self.symbol = symbol
        self.cfg = config
        self.ob_analyzer = OrderbookAnalyzer(exchange, symbol, limit=config.ORDERBOOK_LIMIT)
        self.mm_data = MarketMakerData(exchange, symbol)
        self.liq_engine = LiquidityEngine(exchange, symbol)
        self.hft = HFTMicrostructure(exchange, symbol)
        self.ai_engine = AIMicrostructure(exchange, symbol)

    async def evaluate(self, df: pd.DataFrame, touch_idx: int, side: str) -> dict:
        if len(df) < 22: return {"tier": None, "reasons": ["insufficient data"]}

        touch = df.iloc[-2]
        conf = df.iloc[-1]
        last_price = float(conf['close'])

        # 1. ENFORCE ALERT DIRECTION STRICTLY
        if side == 'above':
            expected_dir = 'bear'
        elif side == 'below':
            expected_dir = 'bull'
        else:
            return {"tier": None, "reasons": ["Invalid alert side"]}

        rej, rej_dir = is_rejection_candle(touch)
        if rej and rej_dir != expected_dir:
            return {"tier": None, "reasons": [f"Alert was {side.upper()}, but candle rejected {rej_dir.upper()}. Wrong direction."]}

        if expected_dir == 'bull':
            engulfing = is_bullish_engulfing(touch, conf)
        else:
            engulfing = is_bearish_engulfing(touch, conf)

        reasons = [
            f"Alert Side: {side.upper()} | Expected Reversal: {expected_dir.upper()}",
            f"Rejection Candle: {rej} ({rej_dir})",
            f"Engulfing Confirmation: {engulfing}"
        ]
        
        if not (rej and engulfing):
            return {"tier": None, "reasons": reasons}

        # 2. MICROSTRUCTURE (ORDERBOOK)
        ob = await self.ob_analyzer.fetch()
        ob_info = self.ob_analyzer.compute(ob, last_price)
        sweep = self.ob_analyzer.detect_sweep(touch, ob_info, expected_dir)
        ob_supports = (expected_dir == 'bull' and ob_info['score'] > 1) or (expected_dir == 'bear' and ob_info['score'] < -1)
        ob_advanced = ob_supports and sweep

        # 3. INDICATORS (SMC)
        vwap_series = vwap(df)
        vp = volume_profile(df.tail(50))
        cvd = calculate_cvd(df)
        fvg = detect_fvg(df)
        avg_vol = df['volume'].iloc[-21:-1].mean()
        vsa = vsa_signal(df.iloc[-2], df.iloc[-1], avg_vol)

        vwap_val = float(vwap_series.iloc[-1]) if not vwap_series.empty else None
        vwap_dev = abs(last_price - vwap_val) / vwap_val if vwap_val is not None else 1.0
        vwap_near = vwap_dev < self.cfg.VWAP_DEVIATION_BAND
        
        poc = vp.get('poc')
        hvns = vp.get('hvns', [])
        lvns = vp.get('lvns', [])
        
        # --- DIRECTION ALIGNMENT FOR INDICATORS ---
        ind_supports = False
        
        # Base SMC Check: VSA, VWAP, and VP must align with expected_dir
        if expected_dir == 'bull':
            vp_supports = (poc is not None and last_price < poc * 1.002) # Price below POC (Discount)
            if vsa == 'bull' or vwap_near or vp_supports:
                ind_supports = True
                
        elif expected_dir == 'bear':
            vp_supports = (poc is not None and last_price > poc * 0.998) # Price above POC (Premium)
            if vsa == 'bear' or vwap_near or vp_supports:
                ind_supports = True

        # Strict FVG Alignment: If an FVG forms in the OPPOSITE direction, kill the signal
        if fvg.get('type') == 'bull' and expected_dir == 'bear':
            ind_supports = False
        if fvg.get('type') == 'bear' and expected_dir == 'bull':
            ind_supports = False

        # Strict CVD Alignment: If divergence is in the OPPOSITE direction, kill the signal
        if cvd['bear_divergence'] and expected_dir == 'bull':
            ind_supports = False # Distribution happening, don't buy!
        if cvd['bull_divergence'] and expected_dir == 'bear':
            ind_supports = False # Accumulation happening, don't short!

        # 4. DERIVATIVES DATA
        mm = await self.mm_data.fetch_mm_conditions()
        mm_confirms = (expected_dir == 'bull' and mm.get('shorts_trapped')) or (expected_dir == 'bear' and mm.get('longs_trapped'))
        mm_trap = (expected_dir == 'bull' and mm.get('longs_trapped')) or (expected_dir == 'bear' and mm.get('shorts_trapped'))

        # 5. LIQUIDITY & HFT
        liq_pools = await self.liq_engine.detect_liquidity_pools(df)
        real_delta = await self.liq_engine.get_real_delta(limit=1000)
        vpin_data = await self.hft.calculate_vpin()
        kyle_data = await self.hft.calculate_kyle_lambda()
        ai_anomaly = await self.ai_engine.detect_mm_anomaly()
        
        touched_liq_pool = False
        if expected_dir == 'bull' and any(abs(last_price - p) / p < 0.001 for p in liq_pools.get('equal_lows', [])):
            touched_liq_pool = True
        if expected_dir == 'bear' and any(abs(last_price - p) / p < 0.001 for p in liq_pools.get('equal_highs', [])):
            touched_liq_pool = True

        delta_confirms = (expected_dir == 'bull' and real_delta['delta'] > 0) or (expected_dir == 'bear' and real_delta['delta'] < 0)
        vol_spike = volume_spike(df, lookback=20, ratio=self.cfg.VOLUME_SPIKE_RATIO)

        # REASONS LOG
        reasons.append(f"Microprice: {ob_info['microprice']:.2f} | OB Score: {ob_info['score']:.2f} | OFI 5-lvl: {ob_info['ofi_5lvl']:.2f}")
        reasons.append(f"Spoofing: Bid={ob_info['spoofing']['bid_spoof']} | Ask={ob_info['spoofing']['ask_spoof']}")
        reasons.append(f"Liquidity Sweep (Trap avoided): {sweep} | Touched M15 Liq Pool: {touched_liq_pool}")
        reasons.append(f"VSA: {vsa} | CVD Div: Bull={cvd['bull_divergence']}, Bear={cvd['bear_divergence']}")
        reasons.append(f"FVG: {fvg.get('type', 'None')} | VP POC: {poc} (HVN:{len(hvns)}, LVN:{len(lvns)})")
        reasons.append(f"Volume Spike: {vol_spike}")
        reasons.append(f"Funding: {mm['funding_rate']*100:.4f}% (LongsTrapped={mm['longs_trapped']})")
        reasons.append(f"Tick Delta: {real_delta['delta']:.2f} ({real_delta['delta_pct']*100:.2f}% Buy/Sell)")
        reasons.append(f"VPIN (Toxic Flow): {vpin_data['vpin']:.2f} (Informed={vpin_data['toxic_flow']})")
        reasons.append(f"Kyle's Lambda (Impact): {kyle_data['lambda']:.4f} (Absorbing={kyle_data['absorption']})")
        reasons.append(f"AI Anomaly Score: {ai_anomaly['score']:.4f} (Manipulation: {ai_anomaly['is_anomaly']})")
        
        if mm_trap:
            reasons.append("❌ MM TRAP DETECTED: Retail overleveraged. Aborting Tier.")
            return {"tier": None, "reasons": reasons}

        # ---------- THE FINAL AI-DRIVEN MATRIX ----------
        
        # Tier SS
        if ob_advanced and ind_supports and mm_confirms and touched_liq_pool and delta_confirms:
            if vpin_data['toxic_flow'] and kyle_data['absorption'] and ai_anomaly['is_anomaly']:
                return self._result("SS", reasons, ob_info, vp, vwap_val)

        # Tier S
        if (ob_advanced or ind_supports) and delta_confirms and vpin_data['toxic_flow']:
            return self._result("S", reasons, ob_info, vp, vwap_val)

        # Tier A
        if ob_supports and delta_confirms:
            return self._result("A", reasons, ob_info, vp, vwap_val)

        # Tier B
        if vol_spike:
            return self._result("B", reasons, ob_info, vp, vwap_val)

        # Tier C
        return self._result("C", reasons, ob_info, vp, vwap_val)

    def _result(self, tier, reasons, ob_info, vp, vwap_val):
        return {
            "tier": tier, "reasons": reasons, "orderbook": ob_info,
            "volume_profile_poc": vp.get('poc'),
            "vwap": vwap_val
        }