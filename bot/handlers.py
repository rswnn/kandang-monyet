from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          ContextTypes, MessageHandler, filters)
from .price_alerts import AlertManager

COINS = [
    ("BTC", "BTC/USDT:USDT"), ("ETH", "ETH/USDT:USDT"), ("SOL", "SOL/USDT:USDT"),
    ("BNB", "BNB/USDT:USDT"), ("XRP", "XRP/USDT:USDT")
]

HELP_TEXT = """
🤖 *Crypto Futures Alert Bot*

Tap /menu to open the interactive dashboard!

*Session Reminders* — automatic (GMT+7 / WIB):
• Asia (Tokyo) – reminders before 06:00
• London – reminders before 14:00
• NewYork – reminders before 20:30

*Price Alert Tiers* (evaluated on 15m confirmation candle):
• Tier SS 💎 – Rejection + Engulfing + Orderbook (Sweep/Trap avoided) AND Indicators (VP/VWAP/VSA)
• Tier S  ⭐ – Rejection + Engulfing + Orderbook (Sweep/Trap avoided) OR Indicators (VP/VWAP/VSA)
• Tier A  🟢 – Rejection + Engulfing + Orderbook (basic imbalance)
• Tier B  🟡 – Rejection + Engulfing + Volume spike
• Tier C  ⚪ – Rejection + Engulfing
"""

def register_handlers(app: Application, alert_manager: AlertManager, chat_whitelist):
    async def start(update: Update, ctx):
        if chat_whitelist and update.effective_chat.id not in chat_whitelist:
            await update.message.reply_text("⛔ Unauthorized.")
            return
        await update.message.reply_markdown(HELP_TEXT)

    async def menu_cmd(update: Update, ctx):
        if chat_whitelist and update.effective_chat.id not in chat_whitelist: return
        keyboard = [
            [InlineKeyboardButton("➕ Add Alert", callback_data="nav_add")],
            [InlineKeyboardButton("🗑 View / Delete Alerts", callback_data="nav_view")]
        ]
        await update.message.reply_text("🎛 *Main Menu*\nWhat do you want to do?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if chat_whitelist and query.message.chat.id not in chat_whitelist: return

        data = query.data
        chat_id = query.message.chat.id

        if data == "nav_add":
            keyboard = [[InlineKeyboardButton(label, callback_data=f"coin_{symbol}")] for label, symbol in COINS]
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="nav_main")])
            await query.edit_message_text("Select a coin to set alert:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "nav_view":
            items = alert_manager.list_alerts(chat_id)
            if not items:
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="nav_main")]]
                await query.edit_message_text("You have no active alerts.", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            
            keyboard = []
            for a in items:
                status_emoji = "⏳" if a['status'] == 'watching' else "🟢" if 'awaiting' in a['status'] else "✅"
                btn_text = f"{a['symbol'].split('/')[0]} {a['side']} {a['price']} {status_emoji}"
                keyboard.append([
                    InlineKeyboardButton(btn_text, callback_data="noop"),
                    InlineKeyboardButton("❌ Delete", callback_data=f"del_{a['id']}")
                ])
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="nav_main")])
            await query.edit_message_text("Your active alerts:\n(Tap ❌ to delete)", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "nav_main":
            keyboard = [
                [InlineKeyboardButton("➕ Add Alert", callback_data="nav_add")],
                [InlineKeyboardButton("🗑 View / Delete Alerts", callback_data="nav_view")]
            ]
            await query.edit_message_text("🎛 *Main Menu*\nWhat do you want to do?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif data.startswith("coin_"):
            symbol = data.split("coin_")[1]
            ctx.user_data['awaiting_price_for'] = symbol
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="nav_main")]]
            await query.edit_message_text(f"You selected *{symbol}*.\n\nPlease type the price level (numbers only):", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif data.startswith("del_"):
            alert_id = data.split("del_")[1]
            alert_manager.remove_alert(alert_id)
            items = alert_manager.list_alerts(chat_id)
            keyboard = []
            if not items:
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="nav_main")]]
                await query.edit_message_text("Alert deleted. You have no active alerts.", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                for a in items:
                    status_emoji = "⏳" if a['status'] == 'watching' else "🟢" if 'awaiting' in a['status'] else "✅"
                    btn_text = f"{a['symbol'].split('/')[0]} {a['side']} {a['price']} {status_emoji}"
                    keyboard.append([InlineKeyboardButton(btn_text, callback_data="noop"), InlineKeyboardButton("❌ Delete", callback_data=f"del_{a['id']}")])
                keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="nav_main")])
                await query.edit_message_text("✅ Alert deleted!\nRemaining alerts:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "noop": pass

    async def handle_text_input_v2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if chat_whitelist and update.effective_chat.id not in chat_whitelist: return
        symbol = ctx.user_data.get('awaiting_price_for')
        if not symbol: return

        text = update.message.text.strip()
        try:
            price = float(text)
        except ValueError:
            await update.message.reply_text("⚠️ Invalid price. Please send numbers only (e.g. 65000).")
            return

        ctx.user_data['pending_price'] = price
        ctx.user_data['pending_symbol'] = symbol
        del ctx.user_data['awaiting_price_for']

        keyboard = [
            [InlineKeyboardButton("⬆️ Above", callback_data="side_above"), InlineKeyboardButton("⬇️ Below", callback_data="side_below")],
            [InlineKeyboardButton("❌ Cancel", callback_data="nav_main")]
        ]
        await update.message.reply_text(f"Price set to *{price}*\nSelect direction:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def side_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if chat_whitelist and query.message.chat.id not in chat_whitelist: return

        side = query.data.split("side_")[1]
        price = ctx.user_data.get('pending_price')
        symbol = ctx.user_data.get('pending_symbol')

        if not price or not symbol:
            await query.edit_message_text("⚠️ Session expired. Please go to /menu and start again.")
            return

        alert = alert_manager.add_alert(query.message.chat.id, symbol, price, side)
        ctx.user_data.clear()
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="nav_main")]]
        
        await query.edit_message_text(
            f"✅ *Alert Added!*\nCoin: `{symbol}`\nPrice: `{price}`\nDirection: {side}\n\nI will notify you when price touches and evaluate the tier.",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
        )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input_v2))
    app.add_handler(CallbackQueryHandler(button_callback, pattern="^(nav_|coin_|del_|noop)"))
    app.add_handler(CallbackQueryHandler(side_callback, pattern="^side_"))