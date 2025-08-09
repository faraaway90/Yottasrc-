import json
import datetime
import logging
import asyncio
import time
import os
import random
import sys
import locale

# === UTF-8 ENCODING FIXES FOR VPS ===
# Set environment variables for UTF-8 encoding
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['LC_ALL'] = 'C.UTF-8'
os.environ['LANG'] = 'C.UTF-8'

# Set locale to UTF-8
try:
    locale.setlocale(locale.LC_ALL, 'C.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        pass  # Fallback to system default

# Fix encoding for VPS deployment - Enhanced version
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception as e:
    print(f"Warning: Could not reconfigure stdout/stderr encoding: {e}")

# Force UTF-8 for all string operations
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

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

# Configure logging with UTF-8 support
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ])
logger = logging.getLogger(__name__)
logger.info("🚀 Bot starting with UTF-8 encoding support...")

# === CONFIG LOADING ===
try:
    with open("config.json", encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    logger.error("config.json not found!")
    exit(1)

# Get bot token from environment variable or config
BOT_TOKEN = os.getenv("BOT_TOKEN", config.get("bot_token", ""))
if not BOT_TOKEN:
    logger.error("Bot token not found in environment variables or config!")
    exit(1)

print(f"Using bot token: {BOT_TOKEN[:10]}...")  # Debug print
ADMIN_USERNAME = config["admin"]
ADMIN_ID = config["admin_id"]
MIN_WITHDRAW = config["min_withdraw"]
TASKS = config["tasks"]
DAILY_LIMIT = config["daily_limit"]
BONUS_REFERRAL = config["referral_bonus"]
CURRENCY = config["currency"]
PAYOUT_CONFIG = config.get("payout_config", {})

# Data storage
users = {}
withdrawals = []
user_tasks = {}
payout_requests = {}  # New: Store payout requests

# === EMOJI CONSTANTS FOR VPS COMPATIBILITY ===
# Using Unicode escape sequences to prevent corruption during copy-paste
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
    """Safely get emoji with fallback"""
    return EMOJIS.get(emoji_key, fallback)

def format_message(message):
    """Format message with proper UTF-8 encoding"""
    try:
        # Ensure message is properly encoded
        if isinstance(message, str):
            return message.encode('utf-8').decode('utf-8')
        return str(message)
    except (UnicodeEncodeError, UnicodeDecodeError):
        # Fallback: remove problematic characters
        return message.encode('ascii', errors='ignore').decode('ascii')

# === FLASK SETUP ===
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
    app.run(host='0.0.0.0', port=5000, debug=False)

# === UTILITY FUNCTIONS ===
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

def start_task_timer(user_id, task_key):
    """Start a timer for task completion"""
    user_tasks[f"{user_id}_{task_key}"] = time.time()

def is_task_completed(user_id, task_key):
    """Check if task wait time has passed"""
    task_start = user_tasks.get(f"{user_id}_{task_key}")
    if not task_start:
        return False
    
    required_wait = TASKS[task_key]["wait"]
    elapsed = time.time() - task_start
    return elapsed >= required_wait

def get_remaining_time(user_id, task_key):
    """Get remaining wait time for task"""
    task_start = user_tasks.get(f"{user_id}_{task_key}")
    if not task_start:
        return 0
    
    required_wait = TASKS[task_key]["wait"]
    elapsed = time.time() - task_start
    remaining = max(0, required_wait - elapsed)
    return int(remaining)

def format_time(seconds):
    """Format time in human readable format"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    else:
        return f"{seconds//3600}h {(seconds%3600)//60}m"

def get_task_buttons(task_key):
    """Get inline keyboard buttons for task links"""
    task = TASKS[task_key]
    buttons = []
    
    if "links" in task and task["links"]:
        print(f"DEBUG: Task {task_key} has {len(task['links'])} links available")
        # Create rows of 2 buttons each
        for i in range(0, len(task["links"]), 2):
            row = []
            for j in range(2):
                if i + j < len(task["links"]):
                    link_num = i + j + 1
                    if task_key == "visit":
                        button_text = f"{safe_emoji('news')} Article {link_num}"
                    elif task_key == "subscribe":
                        button_text = f"{safe_emoji('bell')} Channel {link_num}"
                    else:
                        button_text = f"{safe_emoji('video')} Video {link_num}"
                    row.append(InlineKeyboardButton(button_text, url=task["links"][i + j]))
            buttons.append(row)
    elif "link" in task:
        if task_key == "visit":
            buttons.append([InlineKeyboardButton(f"{safe_emoji('news')} Article Link", url=task["link"])])
        else:
            buttons.append([InlineKeyboardButton(f"{safe_emoji('link')} Task Link", url=task["link"])])
    
    return buttons

def generate_request_id():
    """Generate unique request ID"""
    return f"REQ_{int(time.time())}_{random.randint(1000, 9999)}"

def create_payout_request(user_id, username, amount, payment_method, payment_address):
    """Create a new payout request"""
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

def get_user_pending_requests(user_id):
    """Get pending requests for a user"""
    return [req for req in payout_requests.values() if req['user_id'] == user_id and req['status'] == 'pending']

# === BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # Handle referral
    if context.args and len(context.args) > 0:
        referrer_id = context.args[0]
        if referrer_id != str(user_id) and referrer_id in users:
            users[referrer_id]["referrals"] += 1
            add_earnings(int(referrer_id), BONUS_REFERRAL)
            message = format_message(f"{safe_emoji('party', '🎉')} You got a new referral! Bonus: {BONUS_REFERRAL}{CURRENCY}")
            await context.bot.send_message(
                chat_id=int(referrer_id),
                text=message)
    
    welcome_message = format_message(f"""
{safe_emoji('rocket', '🚀')} **Welcome to BitcoRise Earning Bot!**

{safe_emoji('money', '💰')} **Earn cryptocurrency by completing simple tasks:**
• Like YouTube videos: {TASKS['like']['reward']}{CURRENCY}
• Comment on videos: {TASKS['comment']['reward']}{CURRENCY}
• Subscribe to channels: {TASKS['subscribe']['reward']}{CURRENCY}
• Watch videos (45s): {TASKS['watch']['reward']}{CURRENCY}
• Watch videos (3min): {TASKS['watch_3min']['reward']}{CURRENCY}
• Visit articles: {TASKS['visit']['reward']}{CURRENCY}

{safe_emoji('diamond', '💎')} **Your Stats:**
{safe_emoji('money', '💰')} Balance: {user['balance']}{CURRENCY}
{safe_emoji('chart', '📊')} Total Earned: {user['total_earned']}{CURRENCY}
{safe_emoji('check', '✅')} Tasks Completed: {user['tasks_completed']}
{safe_emoji('people', '👥')} Referrals: {user['referrals']}

{safe_emoji('chart_up', '📈')} **Daily Limit:** {DAILY_LIMIT}{CURRENCY}
{safe_emoji('payout', '💸')} **Min Payout:** {MIN_WITHDRAW}{CURRENCY}

Ready to start earning? Choose an option below! {safe_emoji('down_arrow')}
""")
    
    keyboard = [
        [InlineKeyboardButton(f"{safe_emoji('money', '💰')} Start Tasks", callback_data="tasks"),
         InlineKeyboardButton(f"{safe_emoji('card', '💳')} Balance", callback_data="balance")],
        [InlineKeyboardButton(f"{safe_emoji('payout', '💸')} Request Payout", callback_data="payout"),
         InlineKeyboardButton(f"{safe_emoji('people', '👥')} Referrals", callback_data="referrals")],
        [InlineKeyboardButton(f"{safe_emoji('folder', '📋')} My Requests", callback_data="my_requests"),
         InlineKeyboardButton(f"{safe_emoji('info', 'ℹ️')} Help", callback_data="help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard buttons"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    uid = query.from_user.id
    user = get_user(uid)
    
    if data == "tasks":
        if not can_earn_today(uid):
            message = format_message(f"{safe_emoji('error', '❌')} **Daily Limit Reached!**\n\n"
                f"You've reached your daily earning limit of {DAILY_LIMIT}{CURRENCY}.\n"
                f"Come back tomorrow to continue earning!")
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
            return
            
        keyboard = [
            [InlineKeyboardButton(f"{safe_emoji('thumbs_up', '👍')} Like Videos | {TASKS['like']['reward']}{CURRENCY}",
                                  callback_data="like"),
             InlineKeyboardButton(f"{safe_emoji('comment', '💬')} Comment Videos | {TASKS['comment']['reward']}{CURRENCY}",
                                  callback_data="comment")],
            [InlineKeyboardButton(f"{safe_emoji('bell', '🔔')} Subscribe Channels | {TASKS['subscribe']['reward']}{CURRENCY}",
                                  callback_data="subscribe"),
             InlineKeyboardButton(f"{safe_emoji('eyes', '👀')} Watch 45s | {TASKS['watch']['reward']}{CURRENCY}",
                                  callback_data="watch")],
            [InlineKeyboardButton(f"{safe_emoji('clock', '⏰')} Watch 3min | {TASKS['watch_3min']['reward']}{CURRENCY}",
                                  callback_data="watch_3min"),
             InlineKeyboardButton(f"{safe_emoji('news', '📰')} Visit Article | {TASKS['visit']['reward']}{CURRENCY}",
                                  callback_data="visit")],
            [InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = format_message(f"{safe_emoji('target', '🎯')} **Choose a Task to Complete**\n\n"
            f"{safe_emoji('money', '💰')} Today's Earnings: {user['daily_earned']}{CURRENCY} / {DAILY_LIMIT}{CURRENCY}\n"
            f"{safe_emoji('card', '💳')} Current Balance: {user['balance']}{CURRENCY}\n\n"
            f"Select any task below to start earning! {safe_emoji('down_arrow')}")
        await query.edit_message_text(
            message,
            reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "balance":
        pending_requests = get_user_pending_requests(uid)
        pending_amount = sum(req['amount'] for req in pending_requests)
        today_remaining = DAILY_LIMIT - user['daily_earned']
        
        message = format_message(f"{safe_emoji('card', '💳')} **Your Balance**\n\n"
            f"{safe_emoji('money', '💰')} **Current Balance:** {user['balance']}{CURRENCY}\n"
            f"{safe_emoji('chart', '📊')} **Total Earned:** {user['total_earned']}{CURRENCY}\n"
            f"{safe_emoji('check', '✅')} **Tasks Completed:** {user['tasks_completed']}\n"
            f"{safe_emoji('people', '👥')} **Referrals:** {user['referrals']}\n\n"
            f"{safe_emoji('chart_up', '📈')} **Today's Progress:**\n"
            f"• Earned: {user['daily_earned']}{CURRENCY} / {DAILY_LIMIT}{CURRENCY}\n"
            f"• Remaining: {today_remaining}{CURRENCY}\n\n"
            f"{safe_emoji('loading', '⏳')} **Pending Payouts:** {len(pending_requests)}\n"
            f"{safe_emoji('money', '💰')} **Pending Amount:** {pending_amount}{CURRENCY}\n\n"
            f"{safe_emoji('info', 'ℹ️')} **Min Payout:** {MIN_WITHDRAW}{CURRENCY}")
            
        keyboard = [
            [InlineKeyboardButton(f"{safe_emoji('payout', '💸')} Request Payout", callback_data="payout"),
             InlineKeyboardButton(f"{safe_emoji('folder', '📋')} My Requests", callback_data="my_requests")],
            [InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "payout":
        if user['balance'] < MIN_WITHDRAW:
            message = format_message(f"{safe_emoji('warning', '⚠️')} **Insufficient Balance**\n\n"
                f"Your balance: {user['balance']}{CURRENCY}\n"
                f"Minimum payout: {MIN_WITHDRAW}{CURRENCY}\n\n"
                f"Complete more tasks to reach the minimum payout amount!")
            
            keyboard = [[InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            return
        
        # Check if user has pending requests
        pending_requests = get_user_pending_requests(uid)
        if pending_requests:
            message = format_message(f"{safe_emoji('loading', '⏳')} **Pending Payout Request**\n\n"
                f"You already have {len(pending_requests)} pending payout request(s).\n"
                f"Please wait for admin approval before requesting again.\n\n"
                f"{safe_emoji('info', 'ℹ️')} **Pending Amount:** {sum(req['amount'] for req in pending_requests)}{CURRENCY}")
            
            keyboard = [
                [InlineKeyboardButton(f"{safe_emoji('folder', '📋')} View My Requests", callback_data="my_requests")],
                [InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            return
        
        # Show payout options
        message = format_message(f"{safe_emoji('payout', '💸')} **Request Payout**\n\n"
            f"{safe_emoji('money', '💰')} **Available Balance:** {user['balance']}{CURRENCY}\n"
            f"{safe_emoji('info', 'ℹ️')} **Minimum Payout:** {MIN_WITHDRAW}{CURRENCY}\n\n"
            f"Choose your preferred payment method:")
        
        keyboard = []
        for method_key, method_config in PAYOUT_CONFIG.items():
            keyboard.append([InlineKeyboardButton(
                f"{method_config.get('emoji', '💳')} {method_config['name']}", 
                callback_data=f"payout_method_{method_key}"
            )])
        
        keyboard.append([InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data.startswith("payout_method_"):
        method_key = data.replace("payout_method_", "")
        method_config = PAYOUT_CONFIG.get(method_key)
        
        if not method_config:
            await query.edit_message_text("Invalid payment method selected.")
            return
        
        message = format_message(f"{safe_emoji('payout', '💸')} **{method_config['name']} Payout**\n\n"
            f"{safe_emoji('info', 'ℹ️')} Please send your {method_config['name']} address in the format:\n"
            f"**{method_config['format']}**\n\n"
            f"{safe_emoji('warning', '⚠️')} **Important:**\n"
            f"• Double-check your address before sending\n"
            f"• Incorrect addresses may result in lost funds\n"
            f"• Minimum payout: {MIN_WITHDRAW}{CURRENCY}\n"
            f"• Maximum payout: {user['balance']}{CURRENCY}\n\n"
            f"Send your payout request as: **PAYOUT {user['balance']} {method_key.upper()} your_address_here**")
        
        keyboard = [[InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Payout", callback_data="payout")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "referrals":
        referral_link = f"https://t.me/{context.bot.username}?start={uid}"
        message = format_message(f"{safe_emoji('people', '👥')} **Referral System**\n\n"
            f"{safe_emoji('star', '⭐')} **Your Referral Stats:**\n"
            f"• Total Referrals: {user['referrals']}\n"
            f"• Referral Bonus: {BONUS_REFERRAL}{CURRENCY} per referral\n"
            f"• Total from Referrals: {user['referrals'] * BONUS_REFERRAL}{CURRENCY}\n\n"
            f"{safe_emoji('fire', '🔥')} **Your Referral Link:**\n"
            f"`{referral_link}`\n\n"
            f"{safe_emoji('info', 'ℹ️')} Share this link with friends to earn {BONUS_REFERRAL}{CURRENCY} for each person who joins!")
        
        keyboard = [[InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "my_requests":
        user_requests = [req for req in payout_requests.values() if req['user_id'] == uid]
        
        if not user_requests:
            message = format_message(f"{safe_emoji('folder', '📋')} **My Payout Requests**\n\n"
                f"{safe_emoji('info', 'ℹ️')} You haven't made any payout requests yet.\n"
                f"When you're ready to withdraw your earnings, use the Request Payout option.")
        else:
            message = format_message(f"{safe_emoji('folder', '📋')} **My Payout Requests**\n\n")
            
            for i, req in enumerate(user_requests[-5:], 1):  # Show last 5 requests
                status_emoji = {
                    'pending': safe_emoji('loading', '⏳'),
                    'approved': safe_emoji('check', '✅'),
                    'rejected': safe_emoji('error', '❌')
                }.get(req['status'], '❓')
                
                created_date = datetime.datetime.fromisoformat(req['created_at']).strftime('%Y-%m-%d %H:%M')
                message += f"{i}. {status_emoji} **{req['status'].upper()}**\n"
                message += f"   Amount: {req['amount']}{CURRENCY}\n"
                message += f"   Method: {req['payment_method'].upper()}\n"
                message += f"   Date: {created_date}\n"
                if req['admin_note']:
                    message += f"   Note: {req['admin_note']}\n"
                message += "\n"
        
        keyboard = [[InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "help":
        message = format_message(f"{safe_emoji('info', 'ℹ️')} **Help & Information**\n\n"
            f"{safe_emoji('target', '🎯')} **How to Earn:**\n"
            f"1. Click 'Start Tasks' to see available tasks\n"
            f"2. Choose a task and click the link\n"
            f"3. Complete the task (like, subscribe, etc.)\n"
            f"4. Wait for the timer to complete\n"
            f"5. Click 'Claim Reward' to get your earnings\n\n"
            f"{safe_emoji('payout', '💸')} **How to Withdraw:**\n"
            f"1. Reach minimum balance ({MIN_WITHDRAW}{CURRENCY})\n"
            f"2. Click 'Request Payout'\n"
            f"3. Choose your payment method\n"
            f"4. Send your payment details\n"
            f"5. Wait for admin approval\n\n"
            f"{safe_emoji('people', '👥')} **Referral System:**\n"
            f"• Get {BONUS_REFERRAL}{CURRENCY} for each referral\n"
            f"• Share your referral link from 'Referrals' section\n\n"
            f"{safe_emoji('warning', '⚠️')} **Daily Limit:** {DAILY_LIMIT}{CURRENCY}\n"
            f"{safe_emoji('info', 'ℹ️')} **Admin:** @{ADMIN_USERNAME}")
        
        keyboard = [[InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "back_to_menu":
        # Recreate the main menu
        welcome_message = format_message(f"{safe_emoji('rocket', '🚀')} **Welcome Back!**\n\n"
            f"{safe_emoji('diamond', '💎')} **Your Stats:**\n"
            f"{safe_emoji('money', '💰')} Balance: {user['balance']}{CURRENCY}\n"
            f"{safe_emoji('chart', '📊')} Total Earned: {user['total_earned']}{CURRENCY}\n"
            f"{safe_emoji('check', '✅')} Tasks Completed: {user['tasks_completed']}\n"
            f"{safe_emoji('people', '👥')} Referrals: {user['referrals']}\n\n"
            f"What would you like to do? {safe_emoji('', '👇')}")
        
        keyboard = [
            [InlineKeyboardButton(f"{safe_emoji('money', '💰')} Start Tasks", callback_data="tasks"),
             InlineKeyboardButton(f"{safe_emoji('card', '💳')} Balance", callback_data="balance")],
            [InlineKeyboardButton(f"{safe_emoji('payout', '💸')} Request Payout", callback_data="payout"),
             InlineKeyboardButton(f"{safe_emoji('people', '👥')} Referrals", callback_data="referrals")],
            [InlineKeyboardButton(f"{safe_emoji('folder', '📋')} My Requests", callback_data="my_requests"),
             InlineKeyboardButton(f"{safe_emoji('info', 'ℹ️')} Help", callback_data="help")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')
    
    # Task handlers
    elif data in TASKS:
        task = TASKS[data]
        task_id = f"{uid}_{data}"
        
        if not can_earn_today(uid):
            message = format_message(f"{safe_emoji('error', '❌')} **Daily Limit Reached!**\n\n"
                f"You've reached your daily earning limit of {DAILY_LIMIT}{CURRENCY}.\n"
                f"Come back tomorrow to continue earning!")
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Tasks", callback_data="tasks")
            ]]), parse_mode='Markdown')
            return
        
        # Check if task is already in progress
        if task_id in user_tasks:
            if is_task_completed(uid, data):
                # Task completed, allow claiming
                message = format_message(f"{safe_emoji('done', '✨')} **Task Completed!**\n\n"
                    f"{safe_emoji('target', '🎯')} **Task:** {task['name']}\n"
                    f"{safe_emoji('money', '💰')} **Reward:** {task['reward']}{CURRENCY}\n\n"
                    f"{safe_emoji('check', '✅')} You can now claim your reward!")
                
                keyboard = [
                    [InlineKeyboardButton(f"{safe_emoji('money', '💰')} Claim Reward", callback_data=f"claim_{data}")],
                    [InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Tasks", callback_data="tasks")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                # Task still in progress
                remaining = get_remaining_time(uid, data)
                message = format_message(f"{safe_emoji('loading', '⏳')} **Task in Progress**\n\n"
                    f"{safe_emoji('target', '🎯')} **Task:** {task['name']}\n"
                    f"{safe_emoji('money', '💰')} **Reward:** {task['reward']}{CURRENCY}\n"
                    f"{safe_emoji('time', '⌛')} **Time Remaining:** {format_time(remaining)}\n\n"
                    f"{safe_emoji('info', 'ℹ️')} Please wait for the timer to complete before claiming your reward.")
                
                keyboard = [
                    [InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Tasks", callback_data="tasks")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            # Start new task
            message = format_message(f"{safe_emoji('target', '🎯')} **{task['name']}**\n\n"
                f"{safe_emoji('money', '💰')} **Reward:** {task['reward']}{CURRENCY}\n"
                f"{safe_emoji('time', '⌛')} **Wait Time:** {format_time(task['wait'])}\n\n"
                f"{safe_emoji('info', 'ℹ️')} **Instructions:**\n"
                f"{task['description']}\n\n"
                f"1. Click the link(s) below\n"
                f"2. Complete the required action\n"
                f"3. Come back after {format_time(task['wait'])}\n"
                f"4. Claim your reward!")
            
            # Get task-specific buttons
            task_buttons = get_task_buttons(data)
            task_buttons.append([InlineKeyboardButton(f"{safe_emoji('check', '✅')} I Completed the Task", callback_data=f"start_{data}")])
            task_buttons.append([InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Tasks", callback_data="tasks")])
            
            reply_markup = InlineKeyboardMarkup(task_buttons)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data.startswith("start_"):
        task_key = data.replace("start_", "")
        if task_key in TASKS:
            # Start the task timer
            start_task_timer(uid, task_key)
            task = TASKS[task_key]
            
            message = format_message(f"{safe_emoji('loading', '⏳')} **Task Started!**\n\n"
                f"{safe_emoji('target', '🎯')} **Task:** {task['name']}\n"
                f"{safe_emoji('money', '💰')} **Reward:** {task['reward']}{CURRENCY}\n"
                f"{safe_emoji('time', '⌛')} **Wait Time:** {format_time(task['wait'])}\n\n"
                f"{safe_emoji('info', 'ℹ️')} Timer started! Come back in {format_time(task['wait'])} to claim your reward.")
            
            keyboard = [[InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Tasks", callback_data="tasks")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data.startswith("claim_"):
        task_key = data.replace("claim_", "")
        if task_key in TASKS and is_task_completed(uid, task_key):
            task = TASKS[task_key]
            
            # Add earnings
            add_earnings(uid, task['reward'])
            
            # Remove completed task
            task_id = f"{uid}_{task_key}"
            if task_id in user_tasks:
                del user_tasks[task_id]
            
            # Update user stats
            updated_user = get_user(uid)
            
            message = format_message(f"{safe_emoji('party', '🎉')} **Reward Claimed!**\n\n"
                f"{safe_emoji('check', '✅')} **Task Completed:** {task['name']}\n"
                f"{safe_emoji('money', '💰')} **Earned:** {task['reward']}{CURRENCY}\n\n"
                f"{safe_emoji('diamond', '💎')} **Updated Stats:**\n"
                f"• Balance: {updated_user['balance']}{CURRENCY}\n"
                f"• Total Earned: {updated_user['total_earned']}{CURRENCY}\n"
                f"• Tasks Completed: {updated_user['tasks_completed']}\n"
                f"• Today's Earnings: {updated_user['daily_earned']}{CURRENCY}/{DAILY_LIMIT}{CURRENCY}\n\n"
                f"{safe_emoji('fire', '🔥')} Keep earning!")
            
            keyboard = [
                [InlineKeyboardButton(f"{safe_emoji('money', '💰')} More Tasks", callback_data="tasks"),
                 InlineKeyboardButton(f"{safe_emoji('card', '💳')} Balance", callback_data="balance")],
                [InlineKeyboardButton(f"{safe_emoji('back', '🔙')} Back to Menu", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_payout_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle payout request messages"""
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    
    # Check if it's a payout request
    if not text.upper().startswith('PAYOUT '):
        return
    
    try:
        # Parse payout request: PAYOUT amount method address
        parts = text.split(' ', 3)
        if len(parts) < 4:
            message = format_message(f"{safe_emoji('error', '❌')} **Invalid Payout Format**\n\n"
                f"Please use this format:\n"
                f"**PAYOUT amount method address**\n\n"
                f"Example: PAYOUT 5.0 BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
            await update.message.reply_text(message, parse_mode='Markdown')
            return
        
        amount_str = parts[1]
        method = parts[2].lower()
        address = parts[3]
        
        # Validate amount
        try:
            amount = float(amount_str)
        except ValueError:
            message = format_message(f"{safe_emoji('error', '❌')} **Invalid Amount**\n\n"
                f"Please enter a valid number for the amount.")
            await update.message.reply_text(message, parse_mode='Markdown')
            return
        
        user = get_user(user_id)
        
        # Check if user has sufficient balance
        if amount > user['balance']:
            message = format_message(f"{safe_emoji('error', '❌')} **Insufficient Balance**\n\n"
                f"Requested: {amount}{CURRENCY}\n"
                f"Your balance: {user['balance']}{CURRENCY}")
            await update.message.reply_text(message, parse_mode='Markdown')
            return
        
        # Check minimum payout
        if amount < MIN_WITHDRAW:
            message = format_message(f"{safe_emoji('error', '❌')} **Below Minimum Payout**\n\n"
                f"Requested: {amount}{CURRENCY}\n"
                f"Minimum: {MIN_WITHDRAW}{CURRENCY}")
            await update.message.reply_text(message, parse_mode='Markdown')
            return
        
        # Check if method is supported
        if method not in PAYOUT_CONFIG:
            supported_methods = ', '.join(PAYOUT_CONFIG.keys())
            message = format_message(f"{safe_emoji('error', '❌')} **Unsupported Payment Method**\n\n"
                f"Supported methods: {supported_methods}")
            await update.message.reply_text(message, parse_mode='Markdown')
            return
        
        # Check for pending requests
        pending_requests = get_user_pending_requests(user_id)
        if pending_requests:
            message = format_message(f"{safe_emoji('loading', '⏳')} **Pending Request Exists**\n\n"
                f"You have {len(pending_requests)} pending payout request(s).\n"
                f"Please wait for admin approval before submitting another request.")
            await update.message.reply_text(message, parse_mode='Markdown')
            return
        
        # Create payout request
        request_id = create_payout_request(user_id, username, amount, method, address)
        
        # Deduct amount from user balance (will be restored if rejected)
        user['balance'] -= amount
        save_data()
        
        # Notify user
        message = format_message(f"{safe_emoji('check', '✅')} **Payout Request Submitted**\n\n"
            f"{safe_emoji('folder', '📋')} **Request ID:** {request_id}\n"
            f"{safe_emoji('money', '💰')} **Amount:** {amount}{CURRENCY}\n"
            f"{safe_emoji('card', '💳')} **Method:** {method.upper()}\n"
            f"{safe_emoji('link', '🔗')} **Address:** `{address}`\n\n"
            f"{safe_emoji('loading', '⏳')} Your request is pending admin approval.\n"
            f"{safe_emoji('info', 'ℹ️')} You will be notified when processed.\n\n"
            f"{safe_emoji('money', '💰')} **Remaining Balance:** {user['balance']}{CURRENCY}")
        await update.message.reply_text(message, parse_mode='Markdown')
        
        # Notify admin
        admin_message = format_message(f"{safe_emoji('bell', '🔔')} **NEW PAYOUT REQUEST**\n\n"
            f"{safe_emoji('folder', '📋')} **Request ID:** {request_id}\n"
            f"{safe_emoji('people', '👥')} **User:** @{username} ({user_id})\n"
            f"{safe_emoji('money', '💰')} **Amount:** {amount}{CURRENCY}\n"
            f"{safe_emoji('card', '💳')} **Method:** {method.upper()}\n"
            f"{safe_emoji('link', '🔗')} **Address:** `{address}`\n\n"
            f"Reply with:\n"
            f"• `/approve {request_id}` to approve\n"
            f"• `/reject {request_id} reason` to reject")
        
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    
    except Exception as e:
        logger.error(f"Error processing payout request: {e}")
        message = format_message(f"{safe_emoji('error', '❌')} **Error Processing Request**\n\n"
            f"Please try again or contact admin @{ADMIN_USERNAME}")
        await update.message.reply_text(message, parse_mode='Markdown')

async def approve_payout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to approve payout"""
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
    
    # Update request status
    request['status'] = 'approved'
    request['processed_at'] = datetime.datetime.now().isoformat()
    save_data()
    
    # Notify admin
    message = format_message(f"{safe_emoji('check', '✅')} **Payout Approved**\n\n"
        f"{safe_emoji('folder', '📋')} **Request ID:** {request_id}\n"
        f"{safe_emoji('people', '👥')} **User:** @{request['username']}\n"
        f"{safe_emoji('money', '💰')} **Amount:** {request['amount']}{CURRENCY}\n"
        f"{safe_emoji('card', '💳')} **Method:** {request['payment_method'].upper()}\n\n"
        f"{safe_emoji('info', 'ℹ️')} User has been notified.")
    await update.message.reply_text(message, parse_mode='Markdown')
    
    # Notify user
    user_message = format_message(f"{safe_emoji('party', '🎉')} **Payout Approved!**\n\n"
        f"{safe_emoji('folder', '📋')} **Request ID:** {request_id}\n"
        f"{safe_emoji('money', '💰')} **Amount:** {request['amount']}{CURRENCY}\n"
        f"{safe_emoji('card', '💳')} **Method:** {request['payment_method'].upper()}\n"
        f"{safe_emoji('link', '🔗')} **Address:** `{request['payment_address']}`\n\n"
        f"{safe_emoji('check', '✅')} Your payout has been processed and sent!\n"
        f"{safe_emoji('fire', '🔥')} Keep earning more!")
    
    try:
        await context.bot.send_message(chat_id=request['user_id'], text=user_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify user {request['user_id']}: {e}")

async def reject_payout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to reject payout"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /reject <request_id> <reason>")
        return
    
    request_id = context.args[0]
    reason = ' '.join(context.args[1:])
    
    if request_id not in payout_requests:
        await update.message.reply_text(f"Request {request_id} not found.")
        return
    
    request = payout_requests[request_id]
    if request['status'] != 'pending':
        await update.message.reply_text(f"Request {request_id} is already {request['status']}.")
        return
    
    # Update request status
    request['status'] = 'rejected'
    request['processed_at'] = datetime.datetime.now().isoformat()
    request['admin_note'] = reason
    
    # Restore user balance
    user_id = str(request['user_id'])
    if user_id in users:
        users[user_id]['balance'] += request['amount']
    
    save_data()
    
    # Notify admin
    message = format_message(f"{safe_emoji('error', '❌')} **Payout Rejected**\n\n"
        f"{safe_emoji('folder', '📋')} **Request ID:** {request_id}\n"
        f"{safe_emoji('people', '👥')} **User:** @{request['username']}\n"
        f"{safe_emoji('money', '💰')} **Amount:** {request['amount']}{CURRENCY}\n"
        f"{safe_emoji('info', 'ℹ️')} **Reason:** {reason}\n\n"
        f"{safe_emoji('money', '💰')} Balance restored to user.")
    await update.message.reply_text(message, parse_mode='Markdown')
    
    # Notify user
    user_message = format_message(f"{safe_emoji('error', '❌')} **Payout Rejected**\n\n"
        f"{safe_emoji('folder', '📋')} **Request ID:** {request_id}\n"
        f"{safe_emoji('money', '💰')} **Amount:** {request['amount']}{CURRENCY}\n"
        f"{safe_emoji('info', 'ℹ️')} **Reason:** {reason}\n\n"
        f"{safe_emoji('money', '💰')} Your balance has been restored: {users[str(request['user_id'])]['balance']}{CURRENCY}\n"
        f"{safe_emoji('info', 'ℹ️')} You can submit a new payout request.")
    
    try:
        await context.bot.send_message(chat_id=request['user_id'], text=user_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify user {request['user_id']}: {e}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to get bot statistics"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    total_balance = sum(user['balance'] for user in users.values())
    total_earned = sum(user['total_earned'] for user in users.values())
    pending_payouts = len([req for req in payout_requests.values() if req['status'] == 'pending'])
    approved_payouts = len([req for req in payout_requests.values() if req['status'] == 'approved'])
    rejected_payouts = len([req for req in payout_requests.values() if req['status'] == 'rejected'])
    
    message = format_message(f"{safe_emoji('chart', '📊')} **Bot Statistics**\n\n"
        f"{safe_emoji('people', '👥')} **Users:** {len(users)}\n"
        f"{safe_emoji('money', '💰')} **Total Balance:** {total_balance:.2f}{CURRENCY}\n"
        f"{safe_emoji('chart', '📊')} **Total Earned:** {total_earned:.2f}{CURRENCY}\n"
        f"{safe_emoji('target', '🎯')} **Active Tasks:** {len(user_tasks)}\n\n"
        f"{safe_emoji('folder', '📋')} **Payout Requests:**\n"
        f"• {safe_emoji('loading', '⏳')} Pending: {pending_payouts}\n"
        f"• {safe_emoji('check', '✅')} Approved: {approved_payouts}\n"
        f"• {safe_emoji('error', '❌')} Rejected: {rejected_payouts}\n\n"
        f"{safe_emoji('info', 'ℹ️')} **System Status:** Operational")
    
    await update.message.reply_text(message, parse_mode='Markdown')

def main():
    """Main function to run the bot"""
    # Load data
    load_data()
    
    # Start Flask in a separate thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask dashboard started on port 5000")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("approve", approve_payout))
    application.add_handler(CommandHandler("reject", reject_payout))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payout_message))
    
    # Run bot
    logger.info("Bot is starting...")
    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Bot error: {e}")
        raise

if __name__ == '__main__':
    main()
