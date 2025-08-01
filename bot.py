
import json
import datetime
import logging
import asyncio
import time
import os
from flask import Flask
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
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === CONFIG LOADING ===
try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    logger.error("config.json not found!")
    exit(1)

BOT_TOKEN = config["bot_token"]
ADMIN_USERNAME = config["admin"]
MIN_WITHDRAW = config["min_withdraw"]
TASKS = config["tasks"]
DAILY_LIMIT = config["daily_limit"]
BONUS_REFERRAL = config["referral_bonus"]

# Data storage
users = {}
withdrawals = []
user_tasks = {}  # Store active tasks with timestamps

# === FLASK SETUP ===
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is alive and running!"

@app.route('/health')
def health():
    return {"status": "ok", "users": len(users), "active_tasks": len(user_tasks)}

def run_flask():
    try:
        app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask error: {e}")

# Start Flask in background
Thread(target=run_flask, daemon=True).start()

# === HELPER FUNCTIONS ===
def save_data():
    """Save user data to prevent loss on restart"""
    try:
        data = {
            "users": users,
            "withdrawals": withdrawals,
            "user_tasks": user_tasks
        }
        with open("data.json", "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_data():
    """Load user data on startup"""
    global users, withdrawals, user_tasks
    try:
        if os.path.exists("data.json"):
            with open("data.json") as f:
                data = json.load(f)
                users = data.get("users", {})
                withdrawals = data.get("withdrawals", [])
                user_tasks = data.get("user_tasks", {})
                logger.info(f"Loaded data: {len(users)} users, {len(withdrawals)} withdrawals")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def reset_daily_tasks():
    """Reset daily tasks for all users"""
    today = str(datetime.date.today())
    for uid in users:
        if users[uid]["last_reset"] != today:
            users[uid]["completed_tasks"] = []
            users[uid]["last_reset"] = today
    save_data()

def get_main_keyboard():
    """Get the main menu keyboard"""
    return [
        [InlineKeyboardButton("🌐 Visit Website (25s)", callback_data="visit")],
        [InlineKeyboardButton("👍 Like Video (10s)", callback_data="like")],
        [InlineKeyboardButton("💬 Comment (10s)", callback_data="comment")],
        [InlineKeyboardButton("🔔 Subscribe (10s)", callback_data="subscribe")],
        [InlineKeyboardButton("⏱ Watch 3 Min Video (180s)", callback_data="watch")],
        [InlineKeyboardButton("📺 Watch Live (600s)", callback_data="live")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("📞 Contact", callback_data="contact")],
    ]

def is_task_completed(uid, task_key):
    """Check if user has completed the task timing requirement"""
    if str(uid) not in user_tasks or task_key not in user_tasks[str(uid)]:
        return False
    
    task_start_time = user_tasks[str(uid)][task_key]
    required_wait = TASKS[task_key]["wait"]
    elapsed_time = time.time() - task_start_time
    
    return elapsed_time >= required_wait

def start_task_timer(uid, task_key):
    """Start the timer for a task"""
    uid_str = str(uid)
    if uid_str not in user_tasks:
        user_tasks[uid_str] = {}
    user_tasks[uid_str][task_key] = time.time()
    save_data()

def get_remaining_time(uid, task_key):
    """Get remaining wait time for a task"""
    uid_str = str(uid)
    if uid_str not in user_tasks or task_key not in user_tasks[uid_str]:
        return TASKS[task_key]["wait"]
    
    task_start_time = user_tasks[uid_str][task_key]
    required_wait = TASKS[task_key]["wait"]
    elapsed_time = time.time() - task_start_time
    remaining = max(0, required_wait - elapsed_time)
    
    return int(remaining)

def format_time(seconds):
    """Format seconds into readable time"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    else:
        return f"{seconds//3600}h {(seconds%3600)//60}m"

# === BOT COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id
        username = update.effective_user.username or ""
        name = update.effective_user.first_name or "User"
        ref = context.args[0] if context.args else None

        uid_str = str(uid)
        if uid_str not in users:
            users[uid_str] = {
                "username": username,
                "name": name,
                "balance": 0,
                "ref": ref,
                "completed_tasks": [],
                "last_reset": str(datetime.date.today()),
                "join_date": str(datetime.datetime.now()),
            }
            
            # Add referral bonus if applicable
            if ref and ref.isdigit():
                ref_uid_str = ref
                if ref_uid_str in users:
                    users[ref_uid_str]["balance"] += BONUS_REFERRAL
                    try:
                        await context.bot.send_message(
                            chat_id=int(ref),
                            text=f"🎉 You earned {BONUS_REFERRAL} rub referral bonus from @{username}!"
                        )
                    except:
                        pass
            
            save_data()
            logger.info(f"New user registered: {uid} (@{username})")

        reset_daily_tasks()
        
        keyboard = get_main_keyboard()
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👋 Welcome {name}!\n\n"
            f"💰 Your Balance: {users[uid_str]['balance']:.2f} rub\n"
            f"✅ Tasks Completed Today: {len(users[uid_str]['completed_tasks'])}/{DAILY_LIMIT}\n\n"
            f"📋 Available Tasks:\n"
            f"• Visit Website (25 seconds) - 0.05 rub\n"
            f"• Like Video (10 seconds) - 0.02 rub\n"
            f"• Comment Video (10 seconds) - 0.02 rub\n"
            f"• Subscribe Channel (10 seconds) - 0.05 rub\n"
            f"• Watch 3 Min Video (180 seconds) - 0.25 rub\n"
            f"• Watch Live Stream (600 seconds) - 3.00 rub\n\n"
            f"⚠️ You MUST complete the full waiting time to receive rewards!\n"
            f"🔗 Your referral link: https://t.me/your_bot?start={uid}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again later.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        uid = query.from_user.id
        await query.answer()
        data = query.data

        uid_str = str(uid)
        if uid_str not in users:
            users[uid_str] = {
                "username": query.from_user.username or "",
                "name": query.from_user.first_name or "User",
                "balance": 0,
                "ref": None,
                "completed_tasks": [],
                "last_reset": str(datetime.date.today()),
                "join_date": str(datetime.datetime.now()),
            }
            save_data()

        reset_daily_tasks()

        if data in TASKS:
            # Check daily limit
            if len(users[uid_str]["completed_tasks"]) >= DAILY_LIMIT:
                await query.edit_message_text(
                    f"❌ Daily limit reached!\n\n"
                    f"You can complete {DAILY_LIMIT} tasks per day.\n"
                    f"Come back tomorrow at 00:00 UTC!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]])
                )
                return
                
            # Check if task already completed today
            if data in users[uid_str]["completed_tasks"]:
                await query.edit_message_text(
                    "❌ You already completed this task today!\n\n"
                    "Try other tasks or come back tomorrow.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]])
                )
                return
            
            task = TASKS[data]
            
            # Start the timer for this task
            start_task_timer(uid, data)
            
            keyboard = [
                [InlineKeyboardButton("✅ I Completed the Task", callback_data=f"verify_{data}")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            task_time_formatted = format_time(task['wait'])
            
            await query.edit_message_text(
                f"📋 **{task['title']}**\n\n"
                f"💰 Reward: **{task['reward']} rub**\n"
                f"⏱ Required Time: **{task_time_formatted}**\n"
                f"🌐 Link: {task['link']}\n\n"
                f"📋 **INSTRUCTIONS:**\n"
                f"1️⃣ Click the link above\n"
                f"2️⃣ Complete the task as described\n"
                f"3️⃣ Wait for the FULL {task_time_formatted}\n"
                f"4️⃣ Click 'I Completed the Task'\n\n"
                f"⚠️ **WARNING:** You must wait the complete time!\n"
                f"⏰ Timer started: {datetime.datetime.now().strftime('%H:%M:%S')}",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode='Markdown'
            )
        
        elif data.startswith("verify_"):
            task_key = data.replace("verify_", "")
            task = TASKS[task_key]
            
            # Check if enough time has passed
            if not is_task_completed(uid, task_key):
                remaining = get_remaining_time(uid, task_key)
                remaining_formatted = format_time(remaining)
                
                await query.edit_message_text(
                    f"⏳ **PLEASE WAIT!**\n\n"
                    f"📋 Task: {task['title']}\n"
                    f"⏱ Time remaining: **{remaining_formatted}**\n"
                    f"🕐 Current time: {datetime.datetime.now().strftime('%H:%M:%S')}\n\n"
                    f"❌ You cannot claim the reward yet!\n"
                    f"Please wait for the timer to complete.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Check Again", callback_data=f"verify_{task_key}")],
                        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
                    ]),
                    parse_mode='Markdown'
                )
                return
            
            # Task completed successfully - award the user
            users[uid_str]["completed_tasks"].append(task_key)
            users[uid_str]["balance"] += task["reward"]
            
            # Remove task from active tasks
            if uid_str in user_tasks and task_key in user_tasks[uid_str]:
                del user_tasks[uid_str][task_key]
            
            save_data()
            
            keyboard = get_main_keyboard()
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"🎉 **TASK COMPLETED!**\n\n"
                f"✅ {task['title']}\n"
                f"💰 Earned: **+{task['reward']} rub**\n\n"
                f"💳 Your Balance: **{users[uid_str]['balance']:.2f} rub**\n"
                f"📊 Tasks Today: **{len(users[uid_str]['completed_tasks'])}/{DAILY_LIMIT}**\n"
                f"🕐 Completed at: {datetime.datetime.now().strftime('%H:%M:%S')}\n\n"
                f"Choose another task:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            logger.info(f"User {uid} completed task {task_key} and earned {task['reward']} rub")
        
        elif data == "balance":
            bal = users[uid_str]["balance"]
            completed_count = len(users[uid_str]["completed_tasks"])
            
            keyboard = [
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"💰 **YOUR WALLET**\n\n"
                f"💳 Balance: **{bal:.2f} rub**\n"
                f"✅ Tasks Today: **{completed_count}/{DAILY_LIMIT}**\n"
                f"📅 Member Since: {users[uid_str].get('join_date', 'Unknown')[:10]}\n\n"
                f"🔗 **Your Referral Link:**\n"
                f"`https://t.me/your_bot?start={uid}`\n\n"
                f"💸 **Minimum Withdrawals:**\n"
                f"• Payeer: {MIN_WITHDRAW['payeer']} rub\n"
                f"• FaucetPay: {MIN_WITHDRAW['faucetpay']} rub",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        elif data == "withdraw":
            keyboard = [
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"💸 **WITHDRAWAL REQUEST**\n\n"
                f"Send your request in this format:\n"
                f"`method account_number amount`\n\n"
                f"**Examples:**\n"
                f"• `payeer P12345678 5`\n"
                f"• `faucetpay your@email.com 100`\n\n"
                f"**Minimum amounts:**\n"
                f"• Payeer: {MIN_WITHDRAW['payeer']} rub\n"
                f"• FaucetPay: {MIN_WITHDRAW['faucetpay']} rub\n\n"
                f"💳 Your balance: **{users[uid_str]['balance']:.2f} rub**\n\n"
                f"⏰ Processing time: 24 hours",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        
        elif data == "contact":
            keyboard = [
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"📞 **CONTACT SUPPORT**\n\n"
                f"📧 Email: farawayme90@gmail.com\n"
                f"👨‍💼 Admin: @{ADMIN_USERNAME}\n\n"
                f"**For help with:**\n"
                f"• Withdrawals\n"
                f"• Technical issues\n"
                f"• Account problems\n"
                f"• General questions\n\n"
                f"💬 We respond within 24 hours!",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        elif data == "back_to_menu":
            keyboard = get_main_keyboard()
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"🏠 **MAIN MENU**\n\n"
                f"💰 Balance: **{users[uid_str]['balance']:.2f} rub**\n"
                f"✅ Tasks Today: **{len(users[uid_str]['completed_tasks'])}/{DAILY_LIMIT}**\n\n"
                f"Choose an option:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        try:
            await query.edit_message_text(
                "❌ An error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]])
            )
        except:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id
        msg = update.message.text.strip()
        
        uid_str = str(uid)
        if uid_str not in users:
            await update.message.reply_text("❌ Please use /start first.")
            return

        parts = msg.split()
        if len(parts) == 3:
            method, account, amount = parts
            method = method.lower()
            
            try:
                amount = float(amount)
            except:
                await update.message.reply_text("❌ Invalid amount. Please enter a valid number.")
                return
            
            if method not in MIN_WITHDRAW:
                await update.message.reply_text("❌ Invalid method. Use 'payeer' or 'faucetpay'.")
                return
                
            if amount < MIN_WITHDRAW[method]:
                await update.message.reply_text(f"❌ Amount below minimum. Minimum for {method}: {MIN_WITHDRAW[method]} rub")
                return
            
            if users[uid_str]["balance"] < amount:
                await update.message.reply_text(f"❌ Insufficient balance. Your balance: {users[uid_str]['balance']:.2f} rub")
                return
            
            # Process withdrawal
            users[uid_str]["balance"] -= amount
            withdrawal = {
                "uid": uid_str,
                "username": users[uid_str]["username"],
                "method": method,
                "account": account,
                "amount": amount,
                "timestamp": datetime.datetime.now().isoformat(),
                "status": "pending"
            }
            withdrawals.append(withdrawal)
            save_data()
            
            await update.message.reply_text(
                f"✅ **WITHDRAWAL SUBMITTED!**\n\n"
                f"💰 Amount: **{amount} rub**\n"
                f"🏦 Method: **{method.upper()}**\n"
                f"📧 Account: **{account}**\n"
                f"🕐 Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"⏰ Processing time: **24 hours**\n"
                f"💳 Remaining balance: **{users[uid_str]['balance']:.2f} rub**",
                parse_mode='Markdown'
            )
            
            # Notify admin
            try:
                admin_msg = (
                    f"📤 **NEW WITHDRAWAL REQUEST**\n\n"
                    f"👤 User: @{users[uid_str]['username']} (ID: {uid})\n"
                    f"💰 Amount: {amount} rub\n"
                    f"🏦 Method: {method.upper()}\n"
                    f"📧 Account: {account}\n"
                    f"🕐 Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await context.bot.send_message(chat_id=ADMIN_USERNAME.replace('@', ''), text=admin_msg, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")
                
        else:
            await update.message.reply_text(
                "⚠️ Unknown command. Use the menu buttons or follow the withdrawal format:\n"
                "`method account_number amount`"
            )
    except Exception as e:
        logger.error(f"Error in message handler: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id
        uid_str = str(uid)
        if uid_str not in users:
            await update.message.reply_text("❌ Please use /start first.")
            return
        
        reset_daily_tasks()
        bal = users[uid_str]["balance"]
        completed_count = len(users[uid_str]["completed_tasks"])
        await update.message.reply_text(
            f"💰 Balance: **{bal:.2f} rub**\n"
            f"✅ Tasks Today: **{completed_count}/{DAILY_LIMIT}**\n"
            f"🔗 Referral Link: `https://t.me/your_bot?start={uid}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in balance command: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")

# === ADMIN COMMANDS ===
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.username != ADMIN_USERNAME.replace('@', ''):
            return
        
        if not withdrawals:
            await update.message.reply_text("📭 No pending withdrawals.")
            return
        
        pending = [w for w in withdrawals if w.get('status', 'pending') == 'pending']
        if not pending:
            await update.message.reply_text("📭 No pending withdrawals.")
            return
        
        msg = "📤 **PENDING WITHDRAWALS:**\n\n"
        for i, w in enumerate(pending, 1):
            msg += f"{i}. @{w['username']} (ID: {w['uid']})\n"
            msg += f"   💰 {w['amount']} rub via {w['method'].upper()}\n"
            msg += f"   📧 {w['account']}\n"
            msg += f"   ⏰ {w['timestamp'][:19]}\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in admin command: {e}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.username != ADMIN_USERNAME.replace('@', ''):
            return
            
        total_users = len(users)
        total_balance = sum(user["balance"] for user in users.values())
        today = str(datetime.date.today())
        active_today = sum(1 for user in users.values() if user["last_reset"] == today and user["completed_tasks"])
        pending_withdrawals = len([w for w in withdrawals if w.get('status', 'pending') == 'pending'])
        
        await update.message.reply_text(
            f"📊 **BOT STATISTICS:**\n\n"
            f"👥 Total Users: **{total_users}**\n"
            f"💰 Total Balance: **{total_balance:.2f} rub**\n"
            f"📈 Active Today: **{active_today}**\n"
            f"💸 Pending Withdrawals: **{pending_withdrawals}**\n"
            f"🕐 Bot Uptime: Online\n"
            f"📅 Date: {datetime.date.today()}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in stats command: {e}")

# === ERROR HANDLER ===
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(f"Exception while handling an update: {context.error}")

# === MAIN ===
def main():
    try:
        # Load existing data
        load_data()
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("balance", balance_cmd))
        application.add_handler(CommandHandler("admin", admin))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CallbackQueryHandler(handle_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        logger.info("🤖 Bot is starting...")
        print("🤖 Bot is starting...")
        
        # Run the bot
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Fatal error: {e}")

if __name__ == '__main__':
    main()
