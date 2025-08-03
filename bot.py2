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

# Data storage
users = {}
withdrawals = []
user_tasks = {}

# === FLASK SETUP ===
app = Flask(__name__)

@app.route('/')
def home():
    return render_template('dashboard.html', 
                         users=len(users), 
                         withdrawals=len(withdrawals),
                         active_tasks=len(user_tasks))

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "users": len(users),
        "active_tasks": len(user_tasks),
        "withdrawals": len(withdrawals)
    })

@app.route('/api/stats')
def stats():
    total_balance = sum(user['balance'] for user in users.values())
    total_earned = sum(user['total_earned'] for user in users.values())
    
    return jsonify({
        "total_users": len(users),
        "total_balance": round(total_balance, 2),
        "total_earned": round(total_earned, 2),
        "active_tasks": len(user_tasks),
        "pending_withdrawals": len(withdrawals)
    })

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

# === UTILITY FUNCTIONS ===
def load_data():
    global users, withdrawals
    try:
        with open("data.json", "r") as f:
            data = json.load(f)
            users = data.get("users", {})
            withdrawals = data.get("withdrawals", [])
            logger.info(f"Loaded data: {len(users)} users, {len(withdrawals)} withdrawals")
    except FileNotFoundError:
        logger.info("No data.json found, starting fresh")
        users = {}
        withdrawals = []

def save_data():
    data = {
        "users": users,
        "withdrawals": withdrawals
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
💸 **Min Withdrawal:** {MIN_WITHDRAW}{CURRENCY}

Ready to start earning? Choose an option below! 👇
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 Start Tasks", callback_data="tasks"),
         InlineKeyboardButton("💳 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"),
         InlineKeyboardButton("👥 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
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
        await query.edit_message_text(
            f"💳 **Your Balance Information**\n\n"
            f"💰 Current Balance: {user['balance']}{CURRENCY}\n"
            f"📊 Total Earned: {user['total_earned']}{CURRENCY}\n"
            f"📈 Today's Earnings: {user['daily_earned']}{CURRENCY} / {DAILY_LIMIT}{CURRENCY}\n"
            f"✅ Tasks Completed: {user['tasks_completed']}\n"
            f"👥 Referrals: {user['referrals']}\n\n"
            f"💸 Minimum withdrawal: {MIN_WITHDRAW}{CURRENCY}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"),
                InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
            ]]), parse_mode='Markdown')
    
    elif data == "withdraw":
        if user['balance'] < MIN_WITHDRAW:
            await query.edit_message_text(
                f"❌ **Insufficient Balance**\n\n"
                f"💰 Current Balance: {user['balance']}{CURRENCY}\n"
                f"💸 Minimum Required: {MIN_WITHDRAW}{CURRENCY}\n"
                f"📈 Need: {MIN_WITHDRAW - user['balance']}{CURRENCY} more\n\n"
                f"Complete more tasks to reach the minimum withdrawal amount!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💰 Start Tasks", callback_data="tasks"),
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
        else:
            keyboard = [
                [InlineKeyboardButton("💳 FaucetPay", callback_data="withdraw_faucetpay"),
                 InlineKeyboardButton("💎 Payeer", callback_data="withdraw_payeer")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            await query.edit_message_text(
                f"💸 **Choose Withdrawal Method**\n\n"
                f"💰 Available Balance: {user['balance']}{CURRENCY}\n\n"
                f"**Payment Options:**\n"
                f"💳 **FaucetPay** - Min: 0.05{CURRENCY} (50 BTC Satoshi)\n"
                f"💎 **Payeer** - Min: 2.0{CURRENCY}\n\n"
                f"Select your preferred payment method:",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data.startswith("withdraw_"):
        method = data.replace("withdraw_", "")
        await query.edit_message_text(
            f"💸 **Withdrawal Request**\n\n"
            f"💰 Amount: {user['balance']}{CURRENCY}\n"
            f"💳 Method: {method.title()}\n\n"
            f"Please send your {method.title()} wallet address:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="withdraw")
            ]]), parse_mode='Markdown')
        
        context.user_data['withdrawal_method'] = method
        context.user_data['withdrawal_amount'] = user['balance']
    
    elif data == "referrals":
        bot_username = (await context.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={uid}"
        
        await query.edit_message_text(
            f"👥 **Referral Program**\n\n"
            f"💰 Bonus per referral: {BONUS_REFERRAL}{CURRENCY}\n"
            f"📊 Your referrals: {user['referrals']}\n"
            f"💎 Total referral earnings: {user['referrals'] * BONUS_REFERRAL}{CURRENCY}\n\n"
            f"🔗 **Your referral link:**\n`{referral_link}`\n\n"
            f"Share this link with friends and earn {BONUS_REFERRAL}{CURRENCY} for each person who joins!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
            ]]), parse_mode='Markdown')
    
    elif data == "help":
        await query.edit_message_text(
            f"ℹ️ **How to Use BitcoRise Bot**\n\n"
            f"**Step 1:** Choose a task from the tasks menu\n"
            f"**Step 2:** Click the Video/Article button to open the link\n"
            f"**Step 3:** Complete the required action (like, comment, etc.)\n"
            f"**Step 4:** Take a screenshot of your completion\n"
            f"**Step 5:** Share the screenshot in @bitcorise channel\n"
            f"**Step 6:** Wait for the required time\n"
            f"**Step 7:** Click 'I Completed the Task' to claim reward\n\n"
            f"💰 **Important:** All tasks require screenshot verification in @bitcorise channel\n"
            f"⏰ **Daily Limit:** {DAILY_LIMIT}{CURRENCY}\n"
            f"💸 **Min Withdrawal:** {MIN_WITHDRAW}{CURRENCY}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
            ]]), parse_mode='Markdown')
    
    elif data == "back_to_menu":
        await start_command_handler(update, context)
    
    elif data in TASKS:
        # Handle task selection
        if not can_earn_today(uid):
            await query.edit_message_text(
                f"❌ **Daily Limit Reached!**\n\n"
                f"You've reached your daily earning limit of {DAILY_LIMIT}{CURRENCY}.\n"
                f"Come back tomorrow to continue earning!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
                ]]), parse_mode='Markdown')
            return

        task = TASKS[data]

        # Get task buttons for this task
        task_buttons = get_task_buttons(data)

        # Start the timer for this task
        start_task_timer(uid, data)

        # Create keyboard with task buttons + action buttons
        keyboard = task_buttons + [
            [InlineKeyboardButton("✅ I Completed the Task",
                                 callback_data=f"verify_{data}")],
            [InlineKeyboardButton("🔙 Back to Menu",
                                 callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        task_time_formatted = format_time(task['wait'])

        instructions = ""
        if data == "visit":
            instructions = (
                f"1️⃣ Click any Article button above to open the link\n"
                f"2️⃣ Read the article for {task_time_formatted}\n"
                f"3️⃣ **IMPORTANT:** Click on any ad placed on header\n"
                f"4️⃣ Take screenshot for task approval\n"
                f"5️⃣ Share screenshot in @bitcorise channel\n"
                f"6️⃣ Wait for the FULL {task_time_formatted}\n"
                f"7️⃣ Click 'I Completed the Task'")
        elif data == "like":
            instructions = (
                f"1️⃣ Click any Video button above to open the link\n"
                f"2️⃣ Like the video\n"
                f"3️⃣ Take screenshot of the like\n"
                f"4️⃣ Share screenshot in @bitcorise channel\n"
                f"5️⃣ Wait for {task_time_formatted}\n"
                f"6️⃣ Click 'I Completed the Task'")
        elif data == "comment":
            instructions = (
                f"1️⃣ Click any Video button above to open the link\n"
                f"2️⃣ Leave a meaningful comment on the video\n"
                f"3️⃣ Take screenshot of your comment\n"
                f"4️⃣ Share screenshot in @bitcorise channel\n"
                f"5️⃣ Wait for {task_time_formatted}\n"
                f"6️⃣ Click 'I Completed the Task'")
        elif data == "subscribe":
            instructions = (f"1️⃣ Click any Channel button above to open the link\n"
                            f"2️⃣ Subscribe to the YouTube channel\n"
                            f"3️⃣ Take screenshot of subscription\n"
                            f"4️⃣ Share screenshot in @bitcorise channel\n"
                            f"5️⃣ Wait for {task_time_formatted}\n"
                            f"6️⃣ Click 'I Completed the Task'")
        elif data == "watch" or data == "watch_3min":
            instructions = (
                f"1️⃣ Click any Video button above to open the link\n"
                f"2️⃣ Watch the video for {task_time_formatted}\n"
                f"3️⃣ Take screenshot showing video progress\n"
                f"4️⃣ Share screenshot in @bitcorise channel\n"
                f"5️⃣ Wait for the FULL {task_time_formatted}\n"
                f"6️⃣ Click 'I Completed the Task'")

        await query.edit_message_text(
            f"🎯 **{task['name']}**\n\n"
            f"💰 **Reward:** {task['reward']}{CURRENCY}\n"
            f"⏱️ **Time Required:** {task_time_formatted}\n\n"
            f"📋 **Instructions:**\n{instructions}\n\n"
            f"⚠️ **Important:** You must wait the full time before claiming!",
            reply_markup=reply_markup,
            parse_mode='Markdown')

    elif data.startswith("verify_"):
        task_key = data.replace("verify_", "")
        
        if task_key not in TASKS:
            await query.edit_message_text("❌ Invalid task!")
            return

        if not is_task_completed(uid, task_key):
            remaining = get_remaining_time(uid, task_key)
            await query.edit_message_text(
                f"⏳ **Please wait!**\n\n"
                f"You need to wait **{format_time(remaining)}** more before claiming this reward.\n\n"
                f"⚠️ This is to ensure you actually completed the task!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Menu",
                                         callback_data="back_to_menu")
                ]]),
                parse_mode='Markdown')
            return

        # Task completed successfully
        task = TASKS[task_key]
        reward = task['reward']
        
        add_earnings(uid, reward)
        
        # Remove task from active tasks
        task_id = f"{uid}_{task_key}"
        if task_id in user_tasks:
            del user_tasks[task_id]
        
        updated_user = get_user(uid)
        await query.edit_message_text(
            f"✅ **Task Completed Successfully!**\n\n"
            f"🎯 Task: {task['name']}\n"
            f"💰 Reward: +{reward}{CURRENCY}\n"
            f"💳 New Balance: {updated_user['balance']}{CURRENCY}\n"
            f"📊 Today's Earnings: {updated_user['daily_earned']}{CURRENCY} / {DAILY_LIMIT}{CURRENCY}\n\n"
            f"🎉 Great job! Keep completing tasks to earn more!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 More Tasks", callback_data="tasks"),
                InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
            ]]),
            parse_mode='Markdown')

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper function to handle start command from button callbacks"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
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
💸 **Min Withdrawal:** {MIN_WITHDRAW}{CURRENCY}

Ready to start earning? Choose an option below! 👇
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 Start Tasks", callback_data="tasks"),
         InlineKeyboardButton("💳 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"),
         InlineKeyboardButton("👥 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages for withdrawal addresses"""
    if 'withdrawal_method' in context.user_data:
        method = context.user_data['withdrawal_method']
        amount = context.user_data['withdrawal_amount']
        address = update.message.text
        user_id = update.effective_user.id
        
        # Create withdrawal request
        withdrawal = {
            "user_id": user_id,
            "method": method,
            "amount": amount,
            "address": address,
            "status": "pending",
            "date": datetime.datetime.now().isoformat()
        }
        
        withdrawals.append(withdrawal)
        
        # Deduct balance
        user = get_user(user_id)
        user['balance'] = 0.0
        save_data()
        
        await update.message.reply_text(
            f"✅ **Withdrawal Request Submitted!**\n\n"
            f"💳 Method: {method.title()}\n"
            f"💰 Amount: {amount}{CURRENCY}\n"
            f"🏦 Address: `{address}`\n\n"
            f"⏳ Your request is being processed. You'll receive payment within 24-48 hours.",
            parse_mode='Markdown')
        
        # Clear withdrawal data
        del context.user_data['withdrawal_method']
        del context.user_data['withdrawal_amount']
        
        # Notify admin
        if ADMIN_ID:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💸 **New Withdrawal Request**\n\n"
                     f"👤 User ID: {user_id}\n"
                     f"💳 Method: {method.title()}\n"
                     f"💰 Amount: {amount}{CURRENCY}\n"
                     f"🏦 Address: `{address}`",
                parse_mode='Markdown')

def main():
    """Main function to run the bot"""
    load_data()
    
    # Start Flask in a separate thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("Bot started successfully!")
    print("✅ Bot is running...")
    print("🌐 Web dashboard available at: http://localhost:5000")
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()