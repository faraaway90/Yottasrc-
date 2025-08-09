import json
import datetime
import logging
import asyncio
import time
import os
import random
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

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

# === CONFIG LOADING ===
try:
    with open("config.json") as f:
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
        with open("data.json", "r") as f:
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
    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

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
                        button_text = f"📰 Article {link_num}"
                    elif task_key == "subscribe":
                        button_text = f"🔔 Channel {link_num}"
                    else:
                        button_text = f"📺 Video {link_num}"
                    row.append(InlineKeyboardButton(button_text, url=task["links"][i + j]))
            buttons.append(row)
    elif "link" in task:
        if task_key == "visit":
            buttons.append([InlineKeyboardButton("📰 Article Link", url=task["link"])])
        else:
            buttons.append([InlineKeyboardButton("🔗 Task Link", url=task["link"])])
    
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
            await context.bot.send_message(
                chat_id=int(referrer_id),
                text=f"🎉 You got a new referral! Bonus: {BONUS_REFERRAL}{CURRENCY}")
    
    welcome_message = f"""
🚀 **Welcome to BitcoRise Earning Bot!**

💰 Earn cryptocurrency by completing simple tasks:
• Like YouTube videos: {TASKS['like']['reward']}{CURRENCY}
• Comment on videos: {TASKS['comment']['reward']}{CURRENCY}
• Subscribe to channels: {TASKS['subscribe']['reward']}{CURRENCY}
• Watch videos (45s): {TASKS['watch']['reward']}{CURRENCY}
• Watch videos (3min): {TASKS['watch_3min']['reward']}{CURRENCY}
• Visit articles: {TASKS['visit']['reward']}{CURRENCY}

💎 **Your Stats:**
Balance: {user['balance']}{CURRENCY}
Total Earned: {user['total_earned']}{CURRENCY}
Tasks Completed: {user['tasks_completed']}

📊 **Daily Limit:** {DAILY_LIMIT}{CURRENCY}
💸 **Min Payout:** {MIN_WITHDRAW}{CURRENCY}

Ready to start earning? Choose an option below! 👇
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 Start Tasks", callback_data="tasks"),
         InlineKeyboardButton("💳 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Request Payout", callback_data="payout"),
         InlineKeyboardButton("👥 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("📋 My Requests", callback_data="my_requests"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help")]
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
            await query.edit_message_text(
                f"❌ **Daily Limit Reached!**\n\n"
                f"You've reached your daily earning limit of {DAILY_LIMIT}{CURRENCY}.\n"
                f"Come back tomorrow to continue earning!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
            return
            
        keyboard = [
            [InlineKeyboardButton(f"👍 Like Video ({TASKS['like']['reward']}{CURRENCY})",
                                  callback_data="like"),
             InlineKeyboardButton(f"💬 Comment Video ({TASKS['comment']['reward']}{CURRENCY})",
                                  callback_data="comment")],
            [InlineKeyboardButton(f"🔔 Subscribe Channel ({TASKS['subscribe']['reward']}{CURRENCY})",
                                  callback_data="subscribe"),
             InlineKeyboardButton(f"👀 Watch 45s ({TASKS['watch']['reward']}{CURRENCY})",
                                  callback_data="watch")],
            [InlineKeyboardButton(f"⏰ Watch 3min ({TASKS['watch_3min']['reward']}{CURRENCY})",
                                  callback_data="watch_3min"),
             InlineKeyboardButton(f"📰 Visit Article ({TASKS['visit']['reward']}{CURRENCY})",
                                  callback_data="visit")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🎯 **Choose a Task to Complete**\n\n"
            f"💰 Today's Earnings: {user['daily_earned']}{CURRENCY} / {DAILY_LIMIT}{CURRENCY}\n"
            f"💳 Current Balance: {user['balance']}{CURRENCY}\n\n"
            f"Select any task below to start earning! 👇",
            reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "balance":
        pending_requests = get_user_pending_requests(uid)
        pending_amount = sum(req['amount'] for req in pending_requests)
        
        await query.edit_message_text(
            f"💳 **Your Balance Information**\n\n"
            f"💰 Current Balance: {user['balance']}{CURRENCY}\n"
            f"📊 Total Earned: {user['total_earned']}{CURRENCY}\n"
            f"📈 Today's Earnings: {user['daily_earned']}{CURRENCY} / {DAILY_LIMIT}{CURRENCY}\n"
            f"✅ Tasks Completed: {user['tasks_completed']}\n"
            f"👥 Referrals: {user['referrals']}\n"
            f"⏳ Pending Requests: {len(pending_requests)} ({pending_amount}{CURRENCY})\n\n"
            f"💸 Minimum payout: {MIN_WITHDRAW}{CURRENCY}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💸 Request Payout", callback_data="payout"),
                InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
            ]]), parse_mode='Markdown')
    
    elif data == "payout":
        pending_requests = get_user_pending_requests(uid)
        if pending_requests:
            await query.edit_message_text(
                f"⏳ **You have pending payout requests!**\n\n"
                f"Please wait for your current request(s) to be processed before submitting a new one.\n\n"
                f"Pending Requests: {len(pending_requests)}\n"
                f"Total Amount: {sum(req['amount'] for req in pending_requests)}{CURRENCY}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 View My Requests", callback_data="my_requests"),
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
            return
            
        if user['balance'] < MIN_WITHDRAW:
            await query.edit_message_text(
                f"❌ **Insufficient Balance**\n\n"
                f"💰 Current Balance: {user['balance']}{CURRENCY}\n"
                f"💸 Minimum Required: {MIN_WITHDRAW}{CURRENCY}\n"
                f"📈 Need: {MIN_WITHDRAW - user['balance']}{CURRENCY} more\n\n"
                f"Complete more tasks to reach the minimum payout amount!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💰 Start Tasks", callback_data="tasks"),
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
        else:
            keyboard = [
                [InlineKeyboardButton("💳 FaucetPay", callback_data="payout_faucetpay"),
                 InlineKeyboardButton("💎 Payeer", callback_data="payout_payeer")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            await query.edit_message_text(
                f"💸 **Request Payout**\n\n"
                f"💰 Available Balance: {user['balance']}{CURRENCY}\n\n"
                f"**Payment Options:**\n"
                f"💳 **FaucetPay** - Min: {PAYOUT_CONFIG.get('faucetpay_min', 0.05)}{CURRENCY}\n"
                f"💎 **Payeer** - Min: {PAYOUT_CONFIG.get('payeer_min', 2.0)}{CURRENCY}\n\n"
                f"⚠️ **Important:** Your request will be reviewed by admin and processed within {PAYOUT_CONFIG.get('processing_time', '24-48 hours')}.",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == "my_requests":
        user_requests = [req for req_id, req in payout_requests.items() if req['user_id'] == uid]
        
        if not user_requests:
            await query.edit_message_text(
                f"📋 **Your Payout Requests**\n\n"
                f"You haven't made any payout requests yet.\n\n"
                f"Current Balance: {user['balance']}{CURRENCY}\n"
                f"Minimum Payout: {MIN_WITHDRAW}{CURRENCY}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💸 Request Payout", callback_data="payout"),
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
        else:
            # Show last 5 requests
            recent_requests = sorted(user_requests, key=lambda x: x['created_at'], reverse=True)[:5]
            
            message = "📋 **Your Recent Payout Requests**\n\n"
            for req in recent_requests:
                status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(req['status'], "❓")
                created_date = datetime.datetime.fromisoformat(req['created_at']).strftime("%Y-%m-%d %H:%M")
                message += f"{status_emoji} **{req['amount']}{CURRENCY}** via {req['payment_method']}\n"
                message += f"   📅 {created_date} | Status: {req['status'].title()}\n"
                if req['admin_note']:
                    message += f"   📝 Note: {req['admin_note']}\n"
                message += "\n"
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💸 New Request", callback_data="payout"),
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
    
    elif data.startswith("payout_"):
        payment_method = data.split("_")[1]
        min_amount = PAYOUT_CONFIG.get(f"{payment_method}_min", MIN_WITHDRAW)
        
        if user['balance'] < min_amount:
            await query.edit_message_text(
                f"❌ **Insufficient Balance for {payment_method.title()}**\n\n"
                f"💰 Current Balance: {user['balance']}{CURRENCY}\n"
                f"💸 {payment_method.title()} Minimum: {min_amount}{CURRENCY}\n"
                f"📈 Need: {min_amount - user['balance']}{CURRENCY} more",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💰 Start Tasks", callback_data="tasks"),
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
            return
        
        # Store user context for address input
        if context.user_data is None:
            context.user_data = {}
        context.user_data['payout_method'] = payment_method
        context.user_data['payout_amount'] = user['balance']
        
        await query.edit_message_text(
            f"💸 **{payment_method.title()} Payout Request**\n\n"
            f"💰 Amount: {user['balance']}{CURRENCY}\n"
            f"💳 Method: {payment_method.title()}\n\n"
            f"📧 **Please send your {payment_method.title()} address:**\n"
            f"{'(e.g., your@email.com for FaucetPay)' if payment_method == 'faucetpay' else '(e.g., P1234567890 for Payeer)'}\n\n"
            f"⚠️ Make sure the address is correct! Wrong addresses may result in loss of funds.",
            parse_mode='Markdown')
    
    # Handle task callbacks
    elif data in TASKS:
        task_key = data
        task = TASKS[task_key]
        
        if not can_earn_today(uid):
            await query.edit_message_text(
                f"❌ **Daily Limit Reached!**\n\n"
                f"You've reached your daily earning limit of {DAILY_LIMIT}{CURRENCY}.\n"
                f"Come back tomorrow to continue earning!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
            return
        
        # Check if task is already in progress
        if f"{uid}_{task_key}" in user_tasks:
            if is_task_completed(uid, task_key):
              
