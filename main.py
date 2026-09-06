import asyncio
import ccxt.async_support as ccxt
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from bot.handlers import register_handlers
from bot.price_alerts import AlertManager
from bot.sessions import schedule_session_reminders
from bot.tier_evaluator import TierEvaluator

async def main():
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'options': {'defaultType': config.EXCHANGE_TYPE},
    })

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    async def notify(chat_id, text):
        try:
            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown', disable_web_page_preview=True)
        except Exception as e:
            print(f"[notify error] {e}")

    def tier_factory(symbol):
        return TierEvaluator(exchange, symbol, config)

    alert_manager = AlertManager(
        data_file=config.DATA_FILE, ex=exchange,
        tier_evaluator_factory=tier_factory, notify_fn=notify
    )

    register_handlers(app, alert_manager, config.ALLOWED_CHAT_IDS)

    scheduler = AsyncIOScheduler()

    async def session_reminder(name: str):
        msg = (
            f"⏰ *{name} SESSION*\nMarket opens soon. Run your pre-market analysis:\n"
            f"• Check HTF bias (4H/1H)\n• Mark key liquidity zones & order blocks\n"
            f"• Draw session range (Asia range for London/NY)\n• Identify IFVG / FVG\n"
            f"• Check funding rate & open interest"
        )
        for cid in config.ALLOWED_CHAT_IDS:
            await notify(cid, msg)

    schedule_session_reminders(scheduler, session_reminder)

    async def alert_loop():
        await alert_manager.monitor_loop()

    async def post_init(app_):
        scheduler.start()
        asyncio.create_task(alert_loop())
        print("Bot started.")

    app.post_init = post_init

    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        print("Polling... Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await exchange.close()
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())