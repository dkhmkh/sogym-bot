import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

DB_PATH = "sogym.db"

ANIMAL_TYPES = {
    "cow": "🐄 Сиыр (Корова)",
    "horse": "🐎 Жылқы (Лошадь)",
    "sheep": "🐑 Қой (Овца)",
}

SHARES_COUNT = {
    "cow": 4,
    "horse": 4,
    "sheep": 2,
}

PRICE_PER_KG = {
    "cow": 2500,
    "horse": 3000,
    "sheep": 2000,
}

WEIGHT_PER_ANIMAL = {
    "cow": 200,
    "horse": 220,
    "sheep": 45,
}

# Conversation states
WAITING_TITLE, WAITING_ANIMAL, WAITING_PRICE, WAITING_DATE, WAITING_LOCATION = range(5)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                animal_type TEXT NOT NULL,
                price_per_kg INTEGER NOT NULL,
                total_weight INTEGER NOT NULL,
                total_shares INTEGER NOT NULL,
                event_date TEXT,
                location TEXT,
                creator_id INTEGER NOT NULL,
                creator_name TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                status TEXT DEFAULT 'open',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                shares INTEGER DEFAULT 1,
                paid INTEGER DEFAULT 0,
                joined_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (purchase_id) REFERENCES purchases(id),
                UNIQUE(purchase_id, user_id)
            );
        """)


def get_purchase_summary(purchase_id: int) -> str:
    with get_db() as conn:
        purchase = conn.execute(
            "SELECT * FROM purchases WHERE id = ?", (purchase_id,)
        ).fetchone()

        if not purchase:
            return "Тапсырыс табылмады."

        participants = conn.execute(
            "SELECT * FROM participants WHERE purchase_id = ?", (purchase_id,)
        ).fetchall()

    taken_shares = sum(p["shares"] for p in participants)
    free_shares = purchase["total_shares"] - taken_shares
    price_per_share = (purchase["price_per_kg"] * purchase["total_weight"]) // purchase["total_shares"]

    animal_emoji = ANIMAL_TYPES.get(purchase["animal_type"], "🥩")
    status_text = "🟢 Ашық" if purchase["status"] == "open" else "🔴 Жабық"

    text = (
        f"{'━' * 30}\n"
        f"📦 *{purchase['title']}*\n"
        f"{'━' * 30}\n"
        f"{animal_emoji}\n"
        f"📅 Күні: {purchase['event_date'] or 'Белгіленбеген'}\n"
        f"📍 Орны: {purchase['location'] or 'Белгіленбеген'}\n"
        f"⚖️ Салмақ: ~{purchase['total_weight']} кг\n"
        f"💰 Бағасы: {purchase['price_per_kg']} тг/кг\n"
        f"📊 Статус: {status_text}\n\n"
        f"*Үлестер:* {taken_shares}/{purchase['total_shares']}\n"
        f"💵 1 үлес = ~{price_per_share:,} тг\n\n"
    )

    if participants:
        text += "*Қатысушылар:*\n"
        for p in participants:
            paid_icon = "✅" if p["paid"] else "⏳"
            text += f"  {paid_icon} {p['user_name']} — {p['shares']} үлес\n"
    else:
        text += "_Әлі ешкім қосылмаған_\n"

    if free_shares > 0 and purchase["status"] == "open":
        text += f"\n🆓 Бос үлес: *{free_shares}* дана"
    elif purchase["status"] == "open":
        text += "\n🎯 Барлық үлестер таратылды!"

    return text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Жаңа согым ашу", callback_data="new_purchase")],
        [InlineKeyboardButton("📋 Белсенді согымдар", callback_data="list_purchases")],
        [InlineKeyboardButton("ℹ️ Анықтама", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🥩 *Согым боты*\n\n"
        "Бұл бот арқылы сіз:\n"
        "• Согым үшін топтасып сатып ала аласыз\n"
        "• Туша үлестерін бөліп ала аласыз\n"
        "• Қатысушылар мен төлемдерді басқара аласыз\n\n"
        "Не істейміз?",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Команды:*\n\n"
        "/start — Басты мәзір\n"
        "/new — Жаңа согым ашу\n"
        "/list — Белсенді согымдар тізімі\n"
        "/my — Менің согымдарым\n"
        "/cancel — Жоюға болмайды\n\n"
        "❓ *Согым дегеніміз не?*\n"
        "Согым — қазақ дәстүрі бойынша күзде мал сойып, ет дайындау. "
        "Бірнеше отбасы бірігіп бір тұтас туша сатып алады."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "new_purchase":
        await start_new_purchase(update, context)
    elif data == "list_purchases":
        await show_purchases_list(update, context)
    elif data == "help":
        await help_command(update, context)
    elif data.startswith("view_"):
        purchase_id = int(data.split("_")[1])
        await show_purchase_detail(update, context, purchase_id)
    elif data.startswith("join_"):
        purchase_id = int(data.split("_")[1])
        await join_purchase(update, context, purchase_id)
    elif data.startswith("leave_"):
        purchase_id = int(data.split("_")[1])
        await leave_purchase(update, context, purchase_id)
    elif data.startswith("paid_"):
        parts = data.split("_")
        purchase_id, user_id = int(parts[1]), int(parts[2])
        await mark_paid(update, context, purchase_id, user_id)
    elif data.startswith("close_"):
        purchase_id = int(data.split("_")[1])
        await close_purchase(update, context, purchase_id)
    elif data.startswith("animal_"):
        animal = data.split("_")[1]
        context.user_data["animal_type"] = animal
        await ask_price(update, context)
    elif data == "back_to_list":
        await show_purchases_list(update, context)
    elif data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("➕ Жаңа согым ашу", callback_data="new_purchase")],
            [InlineKeyboardButton("📋 Белсенді согымдар", callback_data="list_purchases")],
            [InlineKeyboardButton("ℹ️ Анықтама", callback_data="help")],
        ]
        await query.edit_message_text(
            "🥩 *Согым боты* — Басты мәзір",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def start_new_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["creating"] = True
    context.user_data["step"] = "title"

    await query.edit_message_text(
        "➕ *Жаңа согым ашу*\n\n"
        "Согымның атауын енгізіңіз:\n"
        "_(мысалы: 'Абай көшесі', 'Достар согымы')_",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("creating"):
        return

    step = context.user_data.get("step")
    text = update.message.text.strip()

    if step == "title":
        context.user_data["title"] = text
        context.user_data["step"] = "animal"

        keyboard = [
            [InlineKeyboardButton("🐄 Сиыр (Корова)", callback_data="animal_cow")],
            [InlineKeyboardButton("🐎 Жылқы (Лошадь)", callback_data="animal_horse")],
            [InlineKeyboardButton("🐑 Қой (Овца)", callback_data="animal_sheep")],
        ]
        await update.message.reply_text(
            f"✅ Атауы: *{text}*\n\nМал түрін таңдаңыз:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif step == "price":
        try:
            price = int(text.replace(" ", "").replace(",", ""))
            context.user_data["price_per_kg"] = price
            context.user_data["step"] = "date"
            await update.message.reply_text(
                f"✅ Баға: *{price:,} тг/кг*\n\n"
                "📅 Союу күнін енгізіңіз:\n_(мысалы: 15.11.2026 немесе 'белгісіз')_",
                parse_mode="Markdown",
            )
        except ValueError:
            await update.message.reply_text("❌ Қате! Тек сан енгізіңіз. Мысалы: 2500")

    elif step == "date":
        context.user_data["event_date"] = text if text.lower() != "белгісіз" else None
        context.user_data["step"] = "location"
        await update.message.reply_text(
            f"✅ Күні: *{text}*\n\n"
            "📍 Орынды енгізіңіз:\n_(мысалы: 'Алматы, Алатау ауданы' немесе 'белгісіз')_",
            parse_mode="Markdown",
        )

    elif step == "location":
        context.user_data["location"] = text if text.lower() != "белгісіз" else None
        context.user_data["creating"] = False
        await finalize_purchase(update, context)


async def ask_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    animal = context.user_data["animal_type"]
    default_price = PRICE_PER_KG[animal]
    weight = WEIGHT_PER_ANIMAL[animal]
    shares = SHARES_COUNT[animal]

    context.user_data["step"] = "price"
    context.user_data["total_weight"] = weight
    context.user_data["total_shares"] = shares

    await query.edit_message_text(
        f"✅ Мал түрі: *{ANIMAL_TYPES[animal]}*\n"
        f"⚖️ Болжамды салмақ: ~{weight} кг\n"
        f"📊 Үлестер саны: {shares}\n\n"
        f"💰 Бағасын енгізіңіз (тг/кг):\n"
        f"_(ұсынылатын баға: {default_price} тг/кг)_",
        parse_mode="Markdown",
    )


async def finalize_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat_id

    data = context.user_data

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO purchases
               (title, animal_type, price_per_kg, total_weight, total_shares,
                event_date, location, creator_id, creator_name, chat_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["title"],
                data["animal_type"],
                data["price_per_kg"],
                data["total_weight"],
                data["total_shares"],
                data.get("event_date"),
                data.get("location"),
                user.id,
                user.full_name,
                chat_id,
            )
        )
        purchase_id = cursor.lastrowid

    context.user_data.clear()

    summary = get_purchase_summary(purchase_id)
    keyboard = [
        [InlineKeyboardButton("✋ Қосылу", callback_data=f"join_{purchase_id}")],
        [InlineKeyboardButton("📋 Тізімге оралу", callback_data="list_purchases")],
    ]

    await update.message.reply_text(
        f"🎉 *Согым сәтті ашылды!*\n\n{summary}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_purchases_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        purchases = conn.execute(
            "SELECT p.*, "
            "(SELECT SUM(shares) FROM participants WHERE purchase_id = p.id) as taken_shares "
            "FROM purchases p WHERE status = 'open' ORDER BY created_at DESC LIMIT 10"
        ).fetchall()

    if not purchases:
        keyboard = [[InlineKeyboardButton("➕ Жаңа согым ашу", callback_data="new_purchase")]]
        text = "📭 Белсенді согымдар жоқ.\n\nЖаңа согым ашыңыз!"
    else:
        text = "📋 *Белсенді согымдар:*\n\n"
        keyboard = []
        for p in purchases:
            taken = p["taken_shares"] or 0
            free = p["total_shares"] - taken
            bar = "🟩" * taken + "⬜" * free
            text += f"{bar} *{p['title']}*\n"
            text += f"   {ANIMAL_TYPES.get(p['animal_type'], '🥩')} • {taken}/{p['total_shares']} үлес\n\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"👁 {p['title']} ({free} бос)",
                    callback_data=f"view_{p['id']}"
                )
            ])

    keyboard.append([InlineKeyboardButton("🏠 Басты бет", callback_data="back_to_main")])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def show_purchase_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, purchase_id: int):
    query = update.callback_query
    user_id = query.from_user.id

    with get_db() as conn:
        purchase = conn.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        participant = conn.execute(
            "SELECT * FROM participants WHERE purchase_id = ? AND user_id = ?",
            (purchase_id, user_id)
        ).fetchone()
        taken_shares = conn.execute(
            "SELECT SUM(shares) FROM participants WHERE purchase_id = ?", (purchase_id,)
        ).fetchone()[0] or 0

    if not purchase:
        await query.edit_message_text("❌ Табылмады.")
        return

    summary = get_purchase_summary(purchase_id)
    keyboard = []

    free_shares = purchase["total_shares"] - taken_shares
    is_creator = purchase["creator_id"] == user_id

    if purchase["status"] == "open":
        if participant:
            keyboard.append([InlineKeyboardButton("❌ Шығу", callback_data=f"leave_{purchase_id}")])
        elif free_shares > 0:
            keyboard.append([InlineKeyboardButton("✋ Қосылу", callback_data=f"join_{purchase_id}")])

    if is_creator:
        keyboard.append([InlineKeyboardButton("🔒 Жабу", callback_data=f"close_{purchase_id}")])

        with get_db() as conn:
            participants = conn.execute(
                "SELECT * FROM participants WHERE purchase_id = ? AND paid = 0",
                (purchase_id,)
            ).fetchall()
        for p in participants:
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ {p['user_name']} төледі",
                    callback_data=f"paid_{purchase_id}_{p['user_id']}"
                )
            ])

    keyboard.append([InlineKeyboardButton("◀️ Артқа", callback_data="back_to_list")])

    await query.edit_message_text(
        summary, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def join_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, purchase_id: int):
    query = update.callback_query
    user = query.from_user

    with get_db() as conn:
        purchase = conn.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        if not purchase or purchase["status"] != "open":
            await query.answer("❌ Согым жабық немесе табылмады.", show_alert=True)
            return

        taken = conn.execute(
            "SELECT SUM(shares) FROM participants WHERE purchase_id = ?", (purchase_id,)
        ).fetchone()[0] or 0

        if taken >= purchase["total_shares"]:
            await query.answer("❌ Барлық үлестер таратылды!", show_alert=True)
            return

        existing = conn.execute(
            "SELECT id FROM participants WHERE purchase_id = ? AND user_id = ?",
            (purchase_id, user.id)
        ).fetchone()

        if existing:
            await query.answer("⚠️ Сіз бұрыннан қосылдыңыз!", show_alert=True)
            return

        conn.execute(
            "INSERT INTO participants (purchase_id, user_id, user_name, shares) VALUES (?, ?, ?, 1)",
            (purchase_id, user.id, user.full_name)
        )

    await query.answer("✅ Сіз согымға қосылдыңыз!")
    await show_purchase_detail(update, context, purchase_id)


async def leave_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, purchase_id: int):
    query = update.callback_query
    user_id = query.from_user.id

    with get_db() as conn:
        conn.execute(
            "DELETE FROM participants WHERE purchase_id = ? AND user_id = ?",
            (purchase_id, user_id)
        )

    await query.answer("✅ Согымнан шықтыңыз.")
    await show_purchase_detail(update, context, purchase_id)


async def mark_paid(update: Update, context: ContextTypes.DEFAULT_TYPE, purchase_id: int, user_id: int):
    query = update.callback_query

    with get_db() as conn:
        purchase = conn.execute("SELECT creator_id FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        if purchase["creator_id"] != query.from_user.id:
            await query.answer("❌ Тек ұйымдастырушы белгілей алады.", show_alert=True)
            return
        conn.execute(
            "UPDATE participants SET paid = 1 WHERE purchase_id = ? AND user_id = ?",
            (purchase_id, user_id)
        )

    await query.answer("✅ Төлем белгіленді!")
    await show_purchase_detail(update, context, purchase_id)


async def close_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, purchase_id: int):
    query = update.callback_query

    with get_db() as conn:
        purchase = conn.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        if purchase["creator_id"] != query.from_user.id:
            await query.answer("❌ Тек ұйымдастырушы жаба алады.", show_alert=True)
            return
        conn.execute("UPDATE purchases SET status = 'closed' WHERE id = ?", (purchase_id,))

    await query.answer("🔒 Согым жабылды.")

    summary = get_purchase_summary(purchase_id)
    keyboard = [[InlineKeyboardButton("◀️ Тізімге", callback_data="back_to_list")]]
    await query.edit_message_text(
        f"🔒 *Согым жабылды*\n\n{summary}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_purchases_list(update, context)


async def my_purchases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    with get_db() as conn:
        as_creator = conn.execute(
            "SELECT * FROM purchases WHERE creator_id = ? ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        ).fetchall()

        as_participant = conn.execute(
            """SELECT p.*, par.shares FROM purchases p
               JOIN participants par ON p.id = par.purchase_id
               WHERE par.user_id = ? ORDER BY p.created_at DESC LIMIT 5""",
            (user_id,)
        ).fetchall()

    text = "👤 *Менің согымдарым:*\n\n"
    keyboard = []

    if as_creator:
        text += "🎯 *Ұйымдастырдым:*\n"
        for p in as_creator:
            status = "🟢" if p["status"] == "open" else "🔴"
            text += f"  {status} {p['title']}\n"
            keyboard.append([InlineKeyboardButton(f"📋 {p['title']}", callback_data=f"view_{p['id']}")])

    if as_participant:
        text += "\n✋ *Қатыстым:*\n"
        for p in as_participant:
            status = "🟢" if p["status"] == "open" else "🔴"
            text += f"  {status} {p['title']} — {p['shares']} үлес\n"
            keyboard.append([InlineKeyboardButton(f"📋 {p['title']}", callback_data=f"view_{p['id']}")])

    if not as_creator and not as_participant:
        text += "_Сіз әлі бірде-бір согымға қатыспадыңыз_"

    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )


def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("my", my_purchases))
    app.add_handler(CommandHandler("new", lambda u, c: button_handler(
        type("obj", (object,), {"callback_query": type("q", (object,), {
            "answer": lambda: None, "data": "new_purchase",
            "edit_message_text": lambda **kw: None
        })()})(), c
    )))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🥩 Согым боты іске қосылды...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
