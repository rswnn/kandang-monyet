# Add to requirements.txt: scikit-learn==1.5.2
import numpy as np
import ccxt.async_support as ccxt
from sklearn.ensemble import IsolationForest

class AIMicrostructure:
    """
    Uses Machine Learning (Isolation Forest) to detect institutional anomalies.
    Instead of hardcoded thresholds, the AI learns what a 'normal' orderbook 
    looks like and flags extreme manipulations dynamically.
    """
    def __init__(self, ex: ccxt.Exchange, symbol: str, limit=100):
        self.ex = ex
        self.symbol = symbol
        self.limit = limit
        # Train on recent book history (in memory)
        self.history_features = []
        self.model = IsolationForest(contamination=0.1, random_state=42) # 10% anomaly rate

    def _extract_features(self, bids: list, asks: list, last_price: float) -> list:
        if not bids or not asks: return []
        
        # Microstructure features
        bid_vol_5 = np.sum([s for _, s in bids[:5]])
        ask_vol_5 = np.sum([s for _, s in asks[:5]])
        total_vol = bid_vol_5 + ask_vol_5
        
        # Price impact / Skew
        microprice = asks[0][0] + (bid_vol_5 / total_vol) * (bids[0][0] - asks[0][0])
        skew = (microprice - last_price) / last_price
        
        # Wall detection
        bid_sizes = [s for _, s in bids[:20]]
        ask_sizes = [s for _, s in asks[:20]]
        max_bid_wall = max(bid_sizes) if bid_sizes else 0
        max_ask_wall = max(ask_sizes) if ask_sizes else 0
        
        # Feature vector
        return [bid_vol_5, ask_vol_5, skew, max_bid_wall, max_ask_wall]

    async def detect_mm_anomaly(self) -> dict:
        ob = await self.ex.fetch_order_book(self.symbol, limit=self.limit)
        ticker = await self.ex.fetch_ticker(self.symbol)
        last_price = ticker['last']
        
        features = self._extract_features(ob['bids'], ob['asks'], last_price)
        if not features: return {"is_anomaly": False, "score": 0}

        # Store history to train the model (requires at least 20 snapshots)
        self.history_features.append(features)
        if len(self.history_features) > 100:
            self.history_features.pop(0)
            
        if len(self.history_features) < 20:
            return {"is_anomaly": False, "score": 0, "msg": "Warming up AI model..."}

        # Retrain model dynamically on recent data (Adaptive AI)
        X = np.array(self.history_features)
        self.model.fit(X)
        
        # Predict if the current snapshot is an institutional anomaly (-1 = anomaly)
        is_anomaly = self.model.predict([features])[0] == -1
        anomaly_score = float(self.model.decision_function([features])[0]) # Lower = more anomalous
        
        return {
            "is_anomaly": bool(is_anomaly),
            "score": anomaly_score
        }