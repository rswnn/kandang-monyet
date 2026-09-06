import json, os, asyncio
from datetime import datetime
import pandas as pd
import ccxt.async_support as ccxt

class AlertManager:
    def __init__(self, data_file, ex: ccxt.Exchange, tier_evaluator_factory, notify_fn):
        self.data_file = data_file
        self.ex = ex
        self.tier_factory = tier_evaluator_factory
        self.notify = notify_fn
        self.alerts = []
        os.makedirs(os.path.dirname(data_file), exist_ok=True)
        self._load()

    def _load(self):
        if os.path.exists(self.data_file):
            with open(self.data_file) as f: self.alerts = json.load(f)

    def _save(self):
        with open(self.data_file, 'w') as f: json.dump(self.alerts, f, indent=2)

    def add_alert(self, chat_id, symbol, price, side, timeframe="15m"):
        alert = {
            "id": f"{symbol.replace('/','_')}_{side}_{price}_{int(datetime.utcnow().timestamp())}",
            "chat_id": chat_id, "symbol": symbol, "price": float(price),
            "side": side, "timeframe": timeframe, "status": "watching",
            "created_at": datetime.utcnow().isoformat()
        }
        self.alerts.append(alert)
        self._save()
        return alert

    def list_alerts(self, chat_id):
        return [a for a in self.alerts if a['chat_id'] == chat_id]

    def remove_alert(self, alert_id):
        self.alerts = [a for a in self.alerts if a['id'] != alert_id]
        self._save()

    async def monitor_loop(self):
        while True:
            try:
                if not self.alerts: await asyncio.sleep(5); continue
                symbols = {a['symbol'] for a in self.alerts}
                for symbol in symbols:
                    try:
                        last_price = (await self.ex.fetch_ticker(symbol))['last']
                        for alert in list(self.alerts):
                            if alert['symbol'] != symbol or alert['status'] != 'watching': continue
                            touched = (alert['side'] == 'above' and last_price >= alert['price']) or \
                                      (alert['side'] == 'below' and last_price <= alert['price'])
                            if touched: await self._on_touched(alert, last_price)
                    except Exception as e: print(f"[tick error {symbol}]: {e}")
            except Exception as e: print(f"[AlertManager] error: {e}")

    async def _on_touched(self, alert, last_price):
        msg = (f"🔔 *PRICE TOUCHED*\nSymbol: `{alert['symbol']}`\nSide: {alert['side']}\n"
               f"Alert Price: `{alert['price']}`\nCurrent Price: `{last_price}`\n"
               f"⏳ Waiting for next 15m candle close to evaluate Tier...")
        await self.notify(alert['chat_id'], msg)
        alert['status'] = 'awaiting_confirmation'
        self._save()
        await self._await_confirmation(alert)

    async def _await_confirmation(self, alert):
        symbol = alert['symbol']
        initial = await self.ex.fetch_ohlcv(symbol, timeframe='15m', limit=1)
        initial_close_time = initial[-1][0]

        while True:
            await asyncio.sleep(15)
            data = await self.ex.fetch_ohlcv(symbol, timeframe='15m', limit=2)
            if data[-1][0] != initial_close_time:
                new_close_time = data[-1][0] + 15 * 60 * 1000
                while True:
                    await asyncio.sleep(15)
                    now_ms = int((await self.ex.fetch_ticker(symbol))['timestamp'])
                    if now_ms and now_ms >= new_close_time: break
                break

        ohlcv = await self.ex.fetch_ohlcv(symbol, timeframe='15m', limit=25)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        evaluator = self.tier_factory(symbol)
        result = await evaluator.evaluate(df, touch_idx=-2, side=alert['side'])
        await self._send_tier_alert(alert, result, df)
        alert['status'] = 'done'
        self._save()

    async def _send_tier_alert(self, alert, result, df):
        tier = result.get('tier')
        emoji = {"SS": "💎", "S": "⭐", "A": "🟢", "B": "🟡", "C": "⚪"}.get(tier, "❌")
        if tier:
            msg = (f"{emoji} *TIER {tier} SIGNAL*\nSymbol: `{alert['symbol']}`\n"
                   f"Alert Price: `{alert['price']}`\nLast Close: `{df['close'].iloc[-1]}`\n\n"
                   f"📊 *Analysis*\n" + "\n".join(f"• {r}" for r in result.get('reasons', [])) +
                   f"\n\n⚠️ Not financial advice. Manage your risk.")
        else:
            msg = (f"❌ *NO VALID TIER*\nSymbol: `{alert['symbol']}`\nConditions not met:\n" +
                   "\n".join(f"• {r}" for r in result.get('reasons', [])))
        await self.notify(alert['chat_id'], msg)