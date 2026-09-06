import ccxt.async_support as ccxt

class MarketMakerData:
    """
    Fetches Derivatives Data (Open Interest & Funding Rates).
    Market Makers use this to time liquidation cascades.
    """
    def __init__(self, ex: ccxt.Exchange, symbol: str):
        self.ex = ex
        self.symbol = symbol

    async def fetch_mm_conditions(self) -> dict:
        try:
            # 1. Fetch Open Interest (Total outstanding leveraged positions)
            # Binance requires swapping '/' for '_' in API endpoints for futures OI
            market_id = self.symbol.replace('/', '_').replace(':USDT', '')
            oi_data = await self.ex.fetch_open_interest(market_id)
            current_oi = oi_data.get('openInterestValue') or oi_data.get('openInterestAmount')
            
            # 2. Fetch Funding Rate (Are longs paying shorts, or vice versa?)
            funding_rate = await self.ex.fetch_funding_rate(self.symbol)
            current_funding = funding_rate.get('fundingRate', 0.0)
            
            return {
                "open_interest": float(current_oi) if current_oi else 0.0,
                "funding_rate": float(current_funding),
                "longs_trapped": current_funding > 0.0001,  # Retail is heavily long
                "shorts_trapped": current_funding < -0.0001 # Retail is heavily short
            }
        except Exception as e:
            print(f"[MarketMakerData] Error fetching derivatives: {e}")
            return {"open_interest": 0.0, "funding_rate": 0.0, "longs_trapped": False, "shorts_trapped": False}