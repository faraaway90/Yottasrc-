import json
import datetime
import logging
import asyncio
import time
import os
import random
import sys
import locale

# UTF-8 ENCODING FIXES FOR VPS
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['LC_ALL'] = 'C.UTF-8'
os.environ['LANG'] = 'C.UTF-8'

try:
    locale.setlocale(locale.LC_ALL, 'C.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        pass

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception as e:
    print(f"Warning: Could not reconfigure stdout/stderr encoding: {e}")

try:
    import codecs
    if hasattr(sys.stdout, 'detach'):
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    if hasattr(sys.stderr, 'detach'):
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())
except Exception as e:
    print(f"Warning: Could not set UTF-8 writers: {e}")

from flask import Flask, render_template, jsonify
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

try:
    with open("config.json", encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    logger.error("config.json not found!")
    exit(1)

BOT_TOKEN = os.getenv("BOT_TOKEN", config.get("bot_token", ""))
if not BOT_TOKEN:
    logger.error("Bot token not found!")
    exit(1)

ADMIN_USERNAME = config["admin"]
ADMIN_ID = config["admin_id"]
MIN_WITHDRAW = config["min_withdraw"]
TASKS = config["tasks"]
DAILY_LIMIT = config["daily_limit"]
BONUS_REFERRAL = config["referral_bonus"]
CURRENCY = config["currency"]
PAYOUT_CONFIG = config.get("payout_config", {})

users = {}
withdrawals = []
user_tasks = {}
payout_requests = {}

EMOJIS = {
    'rocket': '\U0001F680',
    'money': '\U0001F4B0',
    'chart': '\U0001F4CA',
    'check': '\U00002705',
    'people': '\U0001F465',
    'chart_up': '\U0001F4C8',
    'card': '\U0001F4B3',
    'payout': '\U0001F4B8',
    'info': '\U00002139\U0000FE0F',
    'thumbs_up': '\U0001F44D',
    'comment': '\U0001F4AC',
    'bell': '\U0001F514',
    'eyes': '\U0001F440',
    'clock': '\U000023F0',
    'news': '\U0001F4F0',
    'back': '\U0001F519',
    'target': '\U0001F3AF',
    'diamond': '\U0001F48E',
    'fire': '\U0001F525',
    'star': '\U00002B50',
    'warning': '\U000026A0\U0000FE0F',
    'error': '\U0000274C',
    'party': '\U0001F389',
    'folder': '\U0001F4CB',
    'link': '\U0001F517',
    'time': '\U0000231B',
    'loading': '\U000023F3',
    'done': '\U00002728',
    'down_arrow': '\U0001F447',
    'video': '\U0001F4FA'
}

def safe_emoji(emoji_key, fallback=""):
    return EMOJIS.get(emoji_key, fallback)

def format_message(message):
    try:
        if isinstance(message, str):
            return message.encode('utf-8').decode('utf-8')
        return str(message)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return message.encode('ascii', errors='ignore').decode('ascii')

# FLASK SETUP - Using different port to avoid conflicts
app = Flask(__name__)

@app.route('/')
def home():
    pending_payouts = len([req for req in payout_requests.values() if req['status'] == 'pending'])
    return render_template('dashboard.html', 
                         users=len(users), 
                         withdrawals=len(withdrawals),
                         active_tasks=len(user_tasks),
                         pending_payouts=pending_payouts)

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "users": len(users),
        "active_tasks": len(user_tasks),
        "withdrawals": len(withdrawals),
        "payout_requests": len(payout_requests)
    })

@app.route('/api/stats')
def stats():
    total_balance = sum(user['balance'] for user in users.values())
    total_earned = sum(user['total_earned'] for user in users.values())
    pending_payouts = len([req for req in payout_requests.values() if req['status'] == 'pending'])
    approved_payouts = len([req for req in payout_requests.values() if req['status'] == 'approved'])
    
    return jsonify({
        "total_users": len(users),
        "total_balance": round(total_balance, 2),
        "total_earned": round(total_earned, 2),
        "active_tasks": len(user_tasks),
        "pending_withdrawals": len(withdrawals),
        "pending_payouts": pending_payouts,
        "approved_payouts": approved_payouts
    })

def run_flask():
    # Use port 5001 to avoid conflicts
    app.run(host='0.0.0.0', port=5001, debug=False)

def load_data():
    global users, withdrawals, payout_requests
    try:
        with open("data.json", "r", encoding='utf-8') as f:
            data = json.load(f)
            users = data.get("users", {})
            withdrawals = data.get("withdrawals", [])
            payout_requests = data.get("payout_requests", {})
            logger.info(f"Loaded data: {len(users)} users, {len(withdrawals)} withdrawals, {len(payout_requests)} payout requests")
    except FileNotFoundError:
        logger.info("No data.json found, starting fresh")
        users = {}
        withdrawals = []
        payout_requests = {}

def save_data():
    data = {
        "users": users,
        "withdrawals": withdrawals,
        "payout_requests": payout_requests
    }
    with open("data.json", "w", encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_user(user_id):
    if str(user_id) not in users:
        users[str(user_id)] = {
            "balance": 0.0,
            "total_earned": 0.0,
            "tasks_completed": 0,
            "referrals": 0,
            "daily_earned": 0.0,
            "last_activity": datetime.datetime.now().isoformat(),
            "joined": datetime.datetime.now().isoformat()
        }
        save_data()
    return users[str(user_id)]

def can_earn_today(user_id):
    user = get_user(user_id)
    today = datetime.datetime.now().date()
    last_activity = datetime.datetime.fromisoformat(user["last_activity"]).date()
    
    if last_activity < today:
        user["daily_earned"] = 0.0
        
    return user["daily_earned"] < DAILY_LIMIT

def add_earnings(user_id, amount):
    user = get_user(user_id)
    user["balance"] += amount
    user["total_earned"] += amount
    user["daily_earned"] += amount
    user["tasks_completed"] += 1
    user["last_activity"] = datetime.datetime.now().isoformat()
    save_data()

def generate_request_id():
    return f"REQ_{int(time.time())}_{random.randint(1000, 9999)}"

def create_payout_request(user_id, username, amount, payment_method, payment_address):
    request_id = generate_request_id()
    payout_requests[request_id] = {
        "user_id": user_id,
        "username": username,
        "amount": amount,
        "payment_method": payment_method,
        "payment_address": payment_address,
        "status": "pending",
        "created_at": datetime.datetime.now().isoformat(),
        "processed_at": None,
        "admin_note": ""
    }
    save_data()
    return request_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if context.args and len(context.args) > 0:
        referrer_id = context.args[0]
        if referrer_id != str(user_id) and referrer_id in users:
            users[referrer_id]["referrals"] += 1
            add_earnings(int(referrer_id), BONUS_REFERRAL)
            message = format_message(f"{safe_emoji('party')} You got a new referral! Bonus: {BONUS_REFERRAL}{CURRENCY}")
            await context.bot.send_message(chat_id=int(referrer_id), text=message)
    
    welcome_message = format_message(f"""
{safe_emoji('rocket')} **Welcome to BitcoRise Earning Bot!**

{safe_emoji('money')} **Earn cryptocurrency by completing simple tasks:**
• Like YouTube videos: {TASKS['like']['reward']}{CURRENCY}
• Comment on videos: {TASKS['comment']['reward']}{CURRENCY}
• Subscribe to channels: {TASKS['subscribe']['reward']}{CURRENCY}
• Watch videos (45s): {TASKS['watch']['reward']}{CURRENCY}
• Watch videos (3min): {TASKS['watch_3min']['reward']}{CURRENCY}
• Visit articles: {TASKS['visit']['reward']}{CURRENCY}

{safe_emoji('diamond')} **Your Stats:**
{safe_emoji('money')} Balance: {user['balance']}{CURRENCY}
{safe_emoji('chart')} Total Earned: {user['total_earned']}{CURRENCY}
{safe_emoji('check')} Tasks Completed: {user['tasks_completed']}
{safe_emoji('people')} Referrals: {user['referrals']}

{safe_emoji('chart_up')} **Daily Limit:** {DAILY_LIMIT}{CURRENCY}
{safe_emoji('payout')} **Min Payout:** {MIN_WITHDRAW}{CURRENCY}

Ready to start earning? Choose an option below! {safe_emoji('down_arrow')}
""")
    
    keyboard = [
        [InlineKeyboardButton(f"{safe_emoji('money')} Start Tasks", callback_data="tasks"),
         InlineKeyboardButton(f"{safe_emoji('card')} Balance", callback_data="balance")],
        [InlineKeyboardButton(f"{safe_emoji('payout')} Request Payout", callback_data="payout"),
         InlineKeyboardButton(f"{safe_emoji('people')} Referrals", callback_data="referrals")],
        [InlineKeyboardButton(f"{safe_emoji('folder')} My Requests", callback_data="my_requests"),
         InlineKeyboardButton(f"{safe_emoji('info')} Help", callback_data="help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    uid = query.from_user.id
    
    if data == "back_to_menu":
        await start(update, context)
        return

async def approve_payout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Usage: /approve <request_id>")
        return
    
    request_id = context.args[0]
    
    if request_id not in payout_requests:
        await update.message.reply_text(f"Request {request_id} not found.")
        return
    
    request = payout_requests[request_id]
    if request['status'] != 'pending':
        await update.message.reply_text(f"Request {request_id} is already {request['status']}.")
        return
    
    request['status'] = 'approved'
    request['processed_at'] = datetime.datetime.now().isoformat()
    save_data()
    
    message = format_message(f"{safe_emoji('check')} **Payout Approved**\n\n"
        f"{safe_emoji('folder')} **Request ID:** {request_id}\n"
        f"{safe_emoji('people')} **User:** @{request['username']}\n"
        f"{safe_emoji('money')} **Amount:** {request['amount']}{CURRENCY}\n"
        f"{safe_emoji('card')} **Method:** {request['payment_method'].upper()}\n\n"
        f"{safe_emoji('info')} User has been notified.")
    await update.message.reply_text(message, parse_mode='Markdown')
    
    user_message = format_message(f"{safe_emoji('party')} **Payout Approved!**\n\n"
        f"{safe_emoji('folder')} **Request ID:** {request_id}\n"
        f"{safe_emoji('money')} **Amount:** {request['amount']}{CURRENCY}\n"
        f"{safe_emoji('card')} **Method:** {request['payment_method'].upper()}\n"
        f"{safe_emoji('link')} **Address:** `{request['payment_address']}`\n\n"
        f"{safe_emoji('check')} Your payout has been processed and sent!\n"
        f"{safe_emoji('fire')} Keep earning more!")
    
    try:
        await context.bot.send_message(chat_id=request['user_id'], text=user_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify user {request['user_id']}: {e}")

async def reject_payout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /reject <request_id> <reason>")
        return
    
    request_id = context.args[0]
    reason = " ".join(context.args[1:])
    
    if request_id not in payout_requests:
        await update.message.reply_text(f"Request {request_id} not found.")
        return
    
    request = payout_requests[request_id]
    if request['status'] != 'pending':
        await update.message.reply_text(f"Request {request_id} is already {request['status']}.")
        return
    
    request['status'] = 'rejected'
    request['processed_at'] = datetime.datetime.now().isoformat()
    request['admin_note'] = reason
    
    user_id = str(request['user_id'])
    if user_id in users:
        users[user_id]['balance'] += request['amount']
    
    save_data()
    
    message = format_message(f"{safe_emoji('error')} **Payout Rejected**\n\n"
        f"{safe_emoji('folder')} **Request ID:** {request_id}\n"
        f"{safe_emoji('people')} **User:** @{request['username']}\n"
        f"{safe_emoji('money')} **Amount:** {request['amount']}{CURRENCY}\n"
        f"{safe_emoji('info')} **Reason:** {reason}\n\n"
        f"{safe_emoji('money')} Balance restored to user.")
    await update.message.reply_text(message, parse_mode='Markdown')
    
    user_message = format_message(f"{safe_emoji('error')} **Payout Rejected**\n\n"
        f"{safe_emoji('folder')} **Request ID:** {request_id}\n"
        f"{safe_emoji('money')} **Amount:** {request['amount']}{CURRENCY}\n"
        f"{safe_emoji('info')} **Reason:** {reason}\n\n"
        f"{safe_emoji('money')} Your balance has been restored: {users[str(request['user_id'])]['balance']}{CURRENCY}\n"
        f"{safe_emoji('info')} You can submit a new payout request.")
    
    try:
        await context.bot.send_message(chat_id=request['user_id'], text=user_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify user {request['user_id']}: {e}")

def main():
    load_data()
    
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask dashboard started on port 5001")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(CommandHandler("approve", approve_payout))
    application.add_handler(CommandHandler("reject", reject_payout))
    
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()