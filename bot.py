import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import asyncio
import time
import io
import sqlite3
import logging
import os
from PIL import Image
import google.generativeai as genai
from datetime import datetime, timedelta

# =================================================================
# LOGGING & CONFIG
# =================================================================
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "7323573439:AAFgI-8NsUisjgoHIieR-snIfrOeXavI7YA"
ADMIN_USER_ID = 6940333640
GEMINI_API_KEY = "AIzaSyCmDeRgNvIttHTpWMNFF3-CYOwzYm5wtL8"
AFFILIATE_LINK = "https://quotex.com"
REFERRAL_BASE_LINK = "https://t.me/YourBotUsername?start="
DB_NAME = 'user_data.db'
DAILY_FREE_SIGNAL_LIMIT = 5
ASSETS_DIR = "assets"

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-2.5-flash')

# =================================================================
# DATABASE - FIXED FOR OLD DB
# =================================================================
def create_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            status TEXT DEFAULT 'pending',
            signals_used INTEGER DEFAULT 0,
            last_reset_date TEXT,
            joined_date TEXT
        )
    ''')

    # ADD quotex_id IF NOT EXISTS
    try:
        cursor.execute('SELECT quotex_id FROM users LIMIT 1')
    except sqlite3.OperationalError:
        logger.info("Adding column: quotex_id")
        cursor.execute('ALTER TABLE users ADD COLUMN quotex_id TEXT')

    # ADD username IF NOT EXISTS (OLD DB FIX)
    try:
        cursor.execute('SELECT username FROM users LIMIT 1')
    except sqlite3.OperationalError:
        logger.info("Adding column: username")
        cursor.execute('ALTER TABLE users ADD COLUMN username TEXT')

    # Create stats table
    cursor.execute('CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER)')
    cursor.execute('INSERT OR IGNORE INTO stats (key, value) VALUES (?, ?)', ('lifetime_users', 0))
    
    conn.commit()
    conn.close()

def update_username(user_id, username):
    if not username:
        username = "No Username"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET username = ? WHERE user_id = ?', (username, user_id))
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT status, signals_used, last_reset_date, username, quotex_id FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    today = time.strftime("%Y-%m-%d")
    
    if result:
        status, signals_used, last_reset_date, username, quotex_id = result
        if last_reset_date != today:
            signals_used = 0
            set_user_signals_used(user_id, 0)
            reset_daily_active()
        return {
            'status': status,
            'signals_used': signals_used,
            'username': username or "No Username",
            'quotex_id': quotex_id
        }
    else:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (user_id, status, last_reset_date, joined_date) VALUES (?, ?, ?, ?)',
                       (user_id, 'pending', today, today))
        cursor.execute('UPDATE stats SET value = value + 1 WHERE key = "lifetime_users"')
        conn.commit()
        conn.close()
        return {'status': 'pending', 'signals_used': 0, 'username': "No Username", 'quotex_id': None}

def set_quotex_id(user_id, quotex_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET quotex_id = ? WHERE user_id = ?', (quotex_id, user_id))
    conn.commit()
    conn.close()

def set_user_status(user_id, status, username=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = time.strftime("%Y-%m-%d")
    cursor.execute('INSERT OR REPLACE INTO users (user_id, username, status, last_reset_date) VALUES (?, ?, ?, ?)',
                   (user_id, username, status, today))
    conn.commit()
    conn.close()

def set_user_signals_used(user_id, count):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = time.strftime("%Y-%m-%d")
    cursor.execute('UPDATE users SET signals_used = ?, last_reset_date = ? WHERE user_id = ?', (count, today, user_id))
    conn.commit()
    conn.close()

def increment_active_today():
    today = time.strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO stats (key, value) VALUES (?, ?)', (f'active_{today}', 0))
    cursor.execute('UPDATE stats SET value = value + 1 WHERE key = ?', (f'active_{today}',))
    conn.commit()
    conn.close()

def reset_daily_active():
    today = time.strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE stats SET value = 0 WHERE key = ?', (f'active_{today}',))
    conn.commit()
    conn.close()

def get_bot_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM stats WHERE key = "lifetime_users"')
    row = cursor.fetchone()
    lifetime = row[0] if row else 0
    today = time.strftime("%Y-%m-%d")
    cursor.execute('SELECT value FROM stats WHERE key = ?', (f'active_{today}',))
    row = cursor.fetchone()
    active_today = row[0] if row else 0
    conn.close()
    return lifetime, active_today

create_db()

# =================================================================
# IMAGE LOADER
# =================================================================
def load_image(path):
    full_path = os.path.join(ASSETS_DIR, path)
    if not os.path.exists(full_path):
        logger.error(f"Image not found: {full_path}")
        return None
    return open(full_path, 'rb')
async def analyze_screenshot_ai(image_bytes: bytes) -> tuple:
    if not gemini_model:
        return "AI module not initialized.", "WAIT", "signal_wait.jpg"
    try:
        image = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return "Invalid image. Upload JPG/PNG.", "WAIT", "signal_wait.jpg"

# =================================================================
# ULTRA FAST SIGNAL + LOADER (MATCHING YOUR DESIGN)
# =================================================================
async def analyze_screenshot_ai(image_bytes: bytes) -> tuple:
    if not gemini_model:
        return "AI module not initialized.", "WAIT", "signal_wait.jpg"
    try:
        image = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return "Invalid image. Upload JPG/PNG.", "WAIT", "signal_wait.jpg"

    # FIXED INDENTATION - ULTRA FAST PROMPT
    prompt = """
You are an **Ultra-fastest, most advanced 1-Minute Binary Options Analyst.**
Analyze the uploaded M1 chart screenshot and generate a precise 60-second trading signal.

Your internal reasoning must include and balance the following 6 Core Confluences:
1 Price Action – candle body size, wick ratio, rejection shadows, engulfing patterns, momentum flow, breakout or trap structure.
2 Indicator Logic – EMA(8/21) alignment, crossover, RSI(14) strength & divergence, Stochastic momentum zone, MACD histogram slope and signal line position.
3 Smart Money Concepts – liquidity sweep, stop hunt, order block touch/reaction, fair value gap fill, premium vs discount zone.
4 Chart Structure – trendline break/retest, S/R reaction, consolidation/expansion phase, micro double top/bottom, wedge/triangle formation.
5 Volume & Volatility Context – candle consistency, spread vs wick volume indication, volume exhaustion or acceleration.
6 Market Bias & Timing – current session (OTC volatility level), micro-trend direction, momentum alignment with the last 3–5 candles.

Rules:
- Always analyze as if trading on 1-minute OTC chart.
- Detect Asset name from the chart (e.g., EUR/JPY(OTC)).
- Detect current time from the chart.
- If price is in indecision or mixed signals → output WAIT.
- Decide direction (UP / DOWN / WAIT) based on majority confluence.
- Output STRICTLY in this format only (NO extra lines, no markdown):
Aspironix Ai Analyzer Trade 🌐
•••••••••••••••••••••••••••••••••••••••
🕦 Time: [HH:MM]
📊 Asset: [Asset]
🏆 DIRECTION: [UP🔺 / DOWN🔻 / WAIT]
💪🏼 CONFIDENCE: [High / Moderate / Low]
🧠 RISK LEVEL: [Low / Medium / High]
Then provide 5–6 concise, technical lines summarizing your reasoning:
— Include short references to candle strength, trend confirmation, indicator alignment, liquidity, and momentum flow.
•••••••••••••••••••••••••••••••••••••••
©️ AI Model By Monem Sixnine
"""

    try:
        response = await asyncio.to_thread(gemini_model.generate_content, [image, prompt])
        full_report = response.text.strip()

        # Extract DIRECTION
        direction = "WAIT"
        if "UP" in full_report and "DOWN" not in full_report:
            direction = "UP"
        elif "DOWN" in full_report:
            direction = "DOWN"

        img_map = {
            "UP": "signal_higher.jpg",
            "DOWN": "signal_lower.jpg",
            "WAIT": "signal_wait.jpg"
        }
        return full_report, direction, img_map.get(direction, "signal_wait.jpg")

    except Exception as e:
        logger.error(f"Gemini Error: {e}")
        return "AI temporarily down. Try again.", "WAIT", "signal_wait.jpg"

# =================================================================
# WELCOME
# =================================================================
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_name = user.first_name or "Trader"
    photo = load_image("welcome_header.png")
    if not photo:
        await update.message.reply_text(
            f"Hi {first_name}!\n\nWelcome to our smart trading assistant at Aspironix AI !\n\n"
            "Here you will find winning signals based on in-depth market analysis using advanced neural network technologies.\n\n"
            "Let's take your trading to the next level—smarter, faster, and more profitable!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Get Started", callback_data='show_main_menu')]])
        )
        return
    keyboard = [[InlineKeyboardButton("Get Started", callback_data='show_main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = (
        f"Hi {first_name}!\n\n"
        "Welcome to our smart trading assistant at Aspironix AI !\n\n"
        "Here you will find winning signals based on in-depth market analysis using advanced neural network technologies.\n\n"
        "Let's take your trading to the next level—smarter, faster, and more profitable!"
    )
    await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
    photo.close()

# =================================================================
# MENUS (Same as before)
# =================================================================
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, query=None):
    user_data = get_user_data(user_id)
    is_registered = user_data['status'] == 'allowed'
    referral_link = f"{REFERRAL_BASE_LINK}{user_id}"
    status_text = "You are registered" if is_registered else "You are not registered"
    photo = load_image("main_menu_trading.png")
    if not photo:
        await (query.edit_message_text if query else update.message.reply_text)("Error loading image.")
        return
    text = (
        f"**Let's start Trading !**\n"
        f"_{status_text}_\n\n"
        "_All our experience is provided absolutely free there are no hidden fees or commissions! At the same time, Quotex Binary AI Bot is the most advanced tool for successful trading_\n\n"
        "**Referral Program:** _Invite friends to get +1 signal per referral !_ **Your Link:** `{referral_link}`"
    )
    keyboard = [
        [InlineKeyboardButton("Get a bot", callback_data='show_affiliate_page')],
        [InlineKeyboardButton("User reviews", callback_data='show_reviews_0')],
        [InlineKeyboardButton("Video review", url='https://youtube.com')],
        [
            InlineKeyboardButton("Check Status/Free Signals...", callback_data='show_status_menu'),
            InlineKeyboardButton("How the bot works ...", callback_data='how_bot_works')
        ],
        [InlineKeyboardButton("Ask a Question", url='https://t.me/support')],
        [
            InlineKeyboardButton("Giveaways", callback_data='show_giveaways'),
            InlineKeyboardButton("Status", callback_data='show_general_status')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if query:
        await query.edit_message_media(
            media=InputMediaPhoto(media=photo, caption=text, parse_mode='Markdown'),
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_photo(photo=photo, caption=text, reply_markup=reply_markup, parse_mode='Markdown')
    photo.close()

async def show_affiliate_page(query, context):
    photo = load_image("make_new_account.png")
    if not photo:
        await query.edit_message_text("Image missing.")
        return
    keyboard = [
        [InlineKeyboardButton("Create a new account", url=AFFILIATE_LINK)],
        [InlineKeyboardButton("I created an account, check ID", callback_data='show_id_guide')],
        [InlineKeyboardButton("Back", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "_To successfully log in and activate the bot, create a new account on the Quotex Binary broker using our link and start trading successfully right now_\n\n"
        "_IMPORTANT: You must register using the button below. Otherwise, the bot will not be able to confirm that you have registered a new account_\n\n"
        "_We honestly admit that we use an affiliate program, but remember that it makes no sense for us to provide incorrect signals. Our success depends on your success, so we strive to provide only accurate and useful advice_"
    )
    await query.edit_message_media(
        media=InputMediaPhoto(media=photo, caption=text, parse_mode='Markdown'),
        reply_markup=reply_markup
    )
    photo.close()

async def show_id_guide(query, context):
    photo = load_image("id_check_guide.png")
    if not photo:
        await query.edit_message_text("Guide image missing.")
        return
    text = (
        "**Send me your new Quotex ID.**\n"
        "_You only need to enter the numbers:_"
    )
    keyboard = [[InlineKeyboardButton("Back", callback_data='show_affiliate_page')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_media(
        media=InputMediaPhoto(media=photo, caption=text),
        reply_markup=reply_markup
    )
    photo.close()
    context.user_data['waiting_for'] = 'quotex_id'

# =================================================================
# REVIEWS
# =================================================================
REVIEWS = [
    {
        "caption": "**Stone Shotter**\n\"This bot is a game-changer! The signals are incredibly accurate, and the risk management advice has saved me from bad decisions. My profitability has skyrocketed since I started using it. Highly recommended!\"",
        "photo": "review_1.jpg"
    },
    {
        "caption": "**Rehman Sixnine**\n\"I've tried many signal bots, but this one stands out. The AI analysis is spot-on, and the daily free signals are a huge bonus. Upgraded to VIP and never looked back!\"",
        "photo": "review_2.jpg"
    },
    {
        "caption": "**Kai Trader**\n\"As a new trader, I was lost. This bot gave me confidence with clear UP/DOWN signals and explanations. Made my first profit on day 3! Thank you!\"",
        "photo": "review_3.jpg"
    }
]

async def show_reviews(query, context, index=0):
    review = REVIEWS[index]
    total = len(REVIEWS)
    photo = load_image(review["photo"])
    if not photo:
        await query.edit_message_text("Review image missing.")
        return
    keyboard = [
        [InlineKeyboardButton(f"{index+1}/{total}", callback_data='no_op'),
         InlineKeyboardButton("Next", callback_data=f'review_next_{index}')],
        [InlineKeyboardButton("Write a review", url='https://t.me/review_channel')],
        [InlineKeyboardButton("Back", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_media(
        media=InputMediaPhoto(media=photo, caption=review["caption"], parse_mode='Markdown'),
        reply_markup=reply_markup
    )
    photo.close()

# =================================================================
# OTHER MENUS
# =================================================================
async def show_status_menu(query, context):
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    remaining = DAILY_FREE_SIGNAL_LIMIT - user_data['signals_used']
    photo = load_image("test_menu.png")
    if not photo:
        await query.edit_message_text("Image missing.")
        return
    status_text = "VIP User (Unlimited)" if user_data['status'] == 'allowed' else "Free User"
    remaining_text = "Unlimited" if user_data['status'] == 'allowed' else str(max(0, remaining))
    text = (
        "**Check your daily free signal status.**\n"
        "_You can get 5 free signals today._\n"
        "_This daily limit resets at 00:00 UTC._\n\n"
        "_To gain unlimited signals and advanced features, you must complete the authorization process._\n\n"
        f"**Your Status:** Free User\n"
        f"**Daily Free Signals Remaining:** {remaining_text}"
    )
    keyboard = [
        [InlineKeyboardButton("Get a Signal Now (Send Image)", callback_data='get_signal_now')],
        [InlineKeyboardButton("Go through Authorization (VIP Access)", callback_data='show_affiliate_page')],
        [InlineKeyboardButton("Back", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_media(
        media=InputMediaPhoto(media=photo, caption=text, parse_mode='Markdown'),
        reply_markup=reply_markup
    )
    photo.close()

async def show_general_status(query, context):
    lifetime, active_today = get_bot_stats()
    photo = load_image("bot_status_update.png")
    if not photo:
        await query.edit_message_text("Image missing.")
        return
    text = (
        "Bot Status\n"
        f"Lifetime Users: {lifetime}\n"
        f"Active Today: {active_today}\n"
        "Aspironix AI Analyzer - Always serving you better!"
    )
    keyboard = [[InlineKeyboardButton("Back to Main Menu", callback_data='back_to_main')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_media(
        media=InputMediaPhoto(media=photo, caption=text),
        reply_markup=reply_markup
    )
    photo.close()

async def show_giveaways(query, context):
    photo = load_image("giveaways_menu.png")
    if not photo:
        await query.edit_message_text("Image missing.")
        return
    text = (
        "There is no giveaway at this time\n\n"
        "Activate the bot to automatically take part in the next giveaways!"
    )
    keyboard = [
        [InlineKeyboardButton("Activate and participate", callback_data='show_affiliate_page')],
        [InlineKeyboardButton("Back", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_media(
        media=InputMediaPhoto(media=photo, caption=text),
        reply_markup=reply_markup
    )
    photo.close()

# =================================================================
# ADMIN PANEL
# =================================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return
    lifetime, active_today = get_bot_stats()
    keyboard = [
        [InlineKeyboardButton("View All Users", callback_data='admin_list_users')],
        [InlineKeyboardButton("Send Notice", callback_data='admin_send_notice')],
        [InlineKeyboardButton("Refresh Stats", callback_data='admin_panel')],
        [InlineKeyboardButton("Close", callback_data='admin_close')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        f"**ADMIN PANEL**\n\n"
        f"Lifetime Users: `{lifetime}`\n"
        f"Active Today: `{active_today}`\n\n"
        f"Select an action:"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_list_users(query, context):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, status, signals_used, quotex_id FROM users ORDER BY joined_date DESC')
    users = cursor.fetchall()
    conn.close()
    
    if not users:
        await query.edit_message_text("No users yet.")
        return

    chunks = []
    current = "**User List**\n\n"
    for user in users:
        uid, username, status, sig, qid = user
        username = f"@{username}" if username and username != "No Username" else "No Username"
        qid = f" | Quotex: `{qid}`" if qid else ""
        line = f"• `{uid}` | {username} | {status.upper()} | Signals: {sig}{qid}\n"
        if len(current + line) > 3800:
            chunks.append(current)
            current = "**User List (cont.)**\n\n" + line
        else:
            current += line
    chunks.append(current)

    keyboard = [[InlineKeyboardButton("Back", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(chunks[0], reply_markup=reply_markup, parse_mode='Markdown')
    for chunk in chunks[1:]:
        await query.message.reply_text(chunk, parse_mode='Markdown')

async def admin_send_notice_start(query, context):
    await query.edit_message_text(
        "**Send Notice to All Users**\n\n"
        "Reply with the message you want to broadcast:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='admin_panel')]]),
        parse_mode='Markdown'
    )
    context.user_data['waiting_for'] = 'admin_notice'

async def handle_admin_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID or context.user_data.get('waiting_for') != 'admin_notice':
        return
    notice = update.message.text.strip()
    context.user_data['waiting_for'] = None

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    user_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    success = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(uid, f"**NOTICE**\n\n{notice}", parse_mode='Markdown')
            success += 1
            await asyncio.sleep(0.1)
        except:
            pass

    await update.message.reply_text(f"Notice sent to {success}/{len(user_ids)} users.")

# =================================================================
# QUOTEX ID + ADMIN NOTIFY
# =================================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    bd_time = datetime.utcnow() + timedelta(hours=6)
    time_str = bd_time.strftime("%I:%M %p, %d %B %Y")

    if context.user_data.get('waiting_for') == 'quotex_id':
        text = update.message.text.strip()
        if not text.isdigit():
            return await update.message.reply_text("Please enter only numbers.")
        
        set_quotex_id(user_id, text)
        update_username(user_id, username)
        set_user_status(user_id, 'pending', username)

        await update.message.reply_text(f"ID `{text}` submitted. Awaiting approval.", parse_mode='Markdown')

        keyboard = [
            [InlineKeyboardButton("Approve", callback_data=f'admin_approve_{user_id}')],
            [InlineKeyboardButton("Reject", callback_data=f'admin_reject_{user_id}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        admin_msg = (
            f"**New Quotex ID Submission**\n\n"
            f"**User:** @{username or 'NoUsername'} (`{user_id}`)\n"
            f"**Quotex ID:** `{text}`\n"
            f"**Time:** {time_str} (BD)\n\n"
            f"_Click to Approve or Reject_"
        )
        await context.bot.send_message(
            ADMIN_USER_ID,
            admin_msg,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        context.user_data['waiting_for'] = None

    elif context.user_data.get('waiting_for') == 'admin_notice' and user_id == ADMIN_USER_ID:
        await handle_admin_notice(update, context)
    else:
        await update.message.reply_text("Use /start or send a chart screenshot.")

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith('admin_approve_') and not data.startswith('admin_reject_'):
        return
    action, uid = data.split('_', 2)[1:]
    uid = int(uid)
    if action == 'approve':
        set_user_status(uid, 'allowed')
        await context.bot.send_message(uid, "Congratulations! You now have unlimited access. /start")
        await query.edit_message_text(f"User {uid} has been **APPROVED**.", parse_mode='Markdown')
    elif action == 'reject':
        set_user_status(uid, 'banned')
        await context.bot.send_message(uid, "Your access has been revoked.")
        await query.edit_message_text(f"User {uid} has been **REJECTED**.", parse_mode='Markdown')
# =================================================================
# ULTRA FAST SIGNAL + LOADER
# =================================================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if user_data['status'] == 'banned':
        return await update.message.reply_text("Banned.")
    if user_data['status'] != 'allowed' and user_data['signals_used'] >= DAILY_FREE_SIGNAL_LIMIT:
        return await update.message.reply_text("Limit reached. /start")

    loader_msg = await update.message.reply_text(
        "**Aspironix AI Analyzing...**\n\n□□□□□□ 0%\nInitializing ultra-fast model...",
        parse_mode='Markdown'
    )

    progress = [0, 25, 50, 75, 100]
    bars = ["", "■■", "■■■■", "■■■■■■", "■■■■■■■■"]
    messages = ["Initializing...", "Scanning...", "Detecting...", "Finalizing..."]

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        for i, p in enumerate(progress):
            if p < 100:
                await loader_msg.edit_text(f"**Aspironix AI Analyzing...**\n\n{bars[i]} {p}%\n{messages[i]}", parse_mode='Markdown')
                await asyncio.sleep(0.7)

        full_report, direction, img_path = await analyze_screenshot_ai(bytes(photo_bytes))

        await loader_msg.edit_text(f"**Aspironix AI Analyzing...**\n\n{bars[-1]} 100%\nSignal ready!", parse_mode='Markdown')
        await asyncio.sleep(0.3)
        await loader_msg.delete()

        result_photo = load_image(img_path)
        if result_photo:
            await update.message.reply_photo(photo=result_photo, caption=full_report, parse_mode='Markdown')
            result_photo.close()
        else:
            await update.message.reply_text(full_report, parse_mode='Markdown')

        if user_data['status'] != 'allowed':
            set_user_signals_used(user_id, user_data['signals_used'] + 1)

    except Exception as e:
        logger.error(f"Error: {e}")
        try: await loader_msg.delete()
        except: pass
        await update.message.reply_text("Failed. Try again.")

# =================================================================
# CALLBACK HANDLER
# =================================================================
async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id == ADMIN_USER_ID and data.startswith('admin_'):
        await handle_admin_action(update, context)
        return

    if data == 'show_main_menu' or data == 'back_to_main':
        await show_main_menu(update, context, user_id, query=query)
    elif data == 'show_affiliate_page':
        await show_affiliate_page(query, context)
    elif data == 'show_id_guide':
        await show_id_guide(query, context)
    elif data == 'show_status_menu':
        await show_status_menu(query, context)
    elif data == 'show_general_status':
        await show_general_status(query, context)
    elif data == 'show_giveaways':
        await show_giveaways(query, context)
    elif data == 'get_signal_now':
        await query.edit_message_text(
            "Upload your Quotex chart screenshot now.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='show_status_menu')]])
        )
        context.user_data['waiting_for'] = 'chart_image'
    elif data.startswith('show_reviews_'):
        idx = int(data.split('_')[-1])
        await show_reviews(query, context, idx)
    elif data.startswith('review_next_'):
        idx = int(data.split('_')[-1])
        next_idx = (idx + 1) % len(REVIEWS)
        await show_reviews(query, context, next_idx)
    elif data == 'how_bot_works':
        await query.edit_message_text("Coming soon!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='back_to_main')]]))
    elif data == 'admin_panel':
        await admin_panel(update, context)
    elif data == 'admin_list_users':
        await admin_list_users(query, context)
    elif data == 'admin_send_notice':
        await admin_send_notice_start(query, context)
    elif data == 'admin_close':
        await query.delete_message()
    elif data == 'no_op':
        pass

# =================================================================
# COMMANDS
# =================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    update_username(user_id, username)
    get_user_data(user_id)
    increment_active_today()
    await send_welcome(update, context)

async def allow_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID: return
    try:
        uid = int(context.args[0])
        set_user_status(uid, 'allowed')
        await update.message.reply_text(f"User {uid} is now VIP.")
        await context.bot.send_message(uid, "Congratulations! You now have unlimited access. /start")
    except: await update.message.reply_text("Usage: /allow <user_id>")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID: return
    try:
        uid = int(context.args[0])
        set_user_status(uid, 'banned')
        await update.message.reply_text(f"User {uid} banned.")
        await context.bot.send_message(uid, "Your access has been revoked.")
    except: await update.message.reply_text("Usage: /ban <user_id>")
# =================================================================
# MAIN - FINAL FIXED VERSION
# =================================================================
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Required for v21+
    await app.initialize()
    await app.start()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("allow", allow_user))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(handle_button_click))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("Bot is running...")
    
    # Start polling
    await app.updater.start_polling()
    
    # Keep the bot running
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())