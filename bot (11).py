import json
import datetime
import logging
import asyncio
import time
import os
import random
import sys
import locale
import requests
from typing import Optional, Dict, Any

# === UTF-8 ENCODING FIXES FOR VPS ===
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
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("🚀 BitcoRise Bot starting with enhanced confirmation system...")

# === CONFIG LOADING ===
try:
    with open("config.json", encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    logger.error("config.json not found!")
    exit(1)

BOT_TOKEN = os.getenv("BOT_TOKEN", config.get("bot_token", ""))
if not BOT_TOKEN:
    logger.error("Bot token not found in environment variables or config!")
    exit(1)

ADMIN_USERNAME = config["admin"]
ADMIN_ID = config["admin_id"]
API_BASE_URL = config.get("api_base_url", "http://localhost:5000/api")

# === EMOJI CONSTANTS ===
EMOJIS = {
    'rocket': '🚀', 'money': '💰', 'chart': '📊', 'check': '✅',
    'people': '👥', 'chart_up': '📈', 'card': '💳', 'payout': '💸',
    'info': 'ℹ️', 'thumbs_up': '👍', 'comment': '💬', 'bell': '🔔',
    'eyes': '👀', 'clock': '⏰', 'news': '📰', 'back': '🔙',
    'target': '🎯', 'diamond': '💎', 'fire': '🔥', 'star': '⭐',
    'warning': '⚠️', 'error': '❌', 'party': '🎉', 'folder': '📋',
    'link': '🔗', 'time': '⏱️', 'loading': '⏳', 'done': '✨',
    'down_arrow': '👇', 'video': '📺', 'gift': '🎁', 'confirm': '✅',
    'cancel': '❌', 'task': '📋', 'wait': '⏰', 'complete': '🎯'
}

def safe_emoji(emoji_key: str, fallback: str = "") -> str:
    return EMOJIS.get(emoji_key, fallback)

def format_message(message: str) -> str:
    try:
        if isinstance(message, str):
            return message.encode('utf-8').decode('utf-8')
        return str(message)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return message.encode('ascii', errors='ignore').decode('ascii')

# === API CLIENT ===
class APIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
    
    def get(self, endpoint: str) -> Dict[str, Any]:
        try:
            response = self.session.get(f"{self.base_url}{endpoint}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API GET error for {endpoint}: {e}")
            return {}
    
    def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self.session.post(f"{self.base_url}{endpoint}", json=data)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API POST error for {endpoint}: {e}")
            return {}
    
    def patch(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self.session.patch(f"{self.base_url}{endpoint}", json=data)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API PATCH error for {endpoint}: {e}")
            return {}

api = APIClient(API_BASE_URL)

# === USER TASK TRACKING ===
class TaskManager:
    def __init__(self):
        self.active_tasks = {}  # user_id -> {task_key: start_time}
    
    def start_task(self, user_id: str, task_key: str) -> bool:
        if user_id not in self.active_tasks:
            self.active_tasks[user_id] = {}
        
        self.active_tasks[user_id][task_key] = time.time()
        
        # Create user task in API
        user_task_data = {
            "userId": user_id,
            "taskKey": task_key,
            "status": "started"
        }
        result = api.post("/user-tasks", user_task_data)
        return bool(result)
    
    def is_task_completed(self, user_id: str, task_key: str, wait_time: int) -> bool:
        if user_id not in self.active_tasks or task_key not in self.active_tasks[user_id]:
            return False
        
        elapsed = time.time() - self.active_tasks[user_id][task_key]
        return elapsed >= wait_time
    
    def get_remaining_time(self, user_id: str, task_key: str, wait_time: int) -> int:
        if user_id not in self.active_tasks or task_key not in self.active_tasks[user_id]:
            return 0
        
        elapsed = time.time() - self.active_tasks[user_id][task_key]
        return max(0, int(wait_time - elapsed))
    
    def complete_task(self, user_id: str, task_key: str) -> bool:
        if user_id in self.active_tasks and task_key in self.active_tasks[user_id]:
            del self.active_tasks[user_id][task_key]
        return True

task_manager = TaskManager()

def get_or_create_user(user_id: str, username: str) -> Dict[str, Any]:
    """Get existing user or create new one"""
    user = api.get(f"/users/{user_id}")
    if not user:
        user_data = {
            "username": username,
            "balance": 0.0,
            "totalEarned": 0.0,
            "tasksCompleted": 0,
            "referrals": 0,
            "dailyEarned": 0.0
        }
        user = api.post("/users", user_data)
    return user or {}

def can_earn_today(user: Dict[str, Any], daily_limit: float) -> bool:
    """Check if user can earn more today"""
    daily_earned = user.get('dailyEarned', 0)
    last_activity = user.get('lastActivity', '')
    
    if last_activity:
        try:
            last_date = datetime.datetime.fromisoformat(last_activity.replace('Z', '+00:00')).date()
            today = datetime.date.today()
            if last_date < today:
                return True
        except ValueError:
            pass
    
    return daily_earned < daily_limit

def add_user_earnings(user_id: str, amount: float) -> bool:
    """Add earnings to user balance"""
    user = api.get(f"/users/{user_id}")
    if not user:
        return False
    
    updates = {
        'balance': user.get('balance', 0) + amount,
        'totalEarned': user.get('totalEarned', 0) + amount,
        'dailyEarned': user.get('dailyEarned', 0) + amount,
        'tasksCompleted': user.get('tasksCompleted', 0) + 1
    }
    
    result = api.patch(f"/users/{user_id}", updates)
    return bool(result)

def format_time(seconds: int) -> str:
    """Format seconds into human readable time"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    else:
        return f"{seconds//3600}h {(seconds%3600)//60}m"

# === BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enhanced start command with better UI"""
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or f"user_{user_id}"
    full_username = f"@{username}" if not username.startswith('@') else username
    
    # Get or create user
    user = get_or_create_user(user_id, full_username)
    
    # Handle referral system
    if context.args and len(context.args) > 0:
        referrer_id = context.args[0]
        if referrer_id != user_id:
            referrer = api.get(f"/users/{referrer_id}")
            if referrer:
                settings = api.get("/bot-settings")
                referral_bonus = settings.get('referralBonus', 1.0)
                
                # Add referral bonus to referrer
                add_user_earnings(referrer_id, referral_bonus)
                
                # Update referrer's referral count
                new_referrals = referrer.get('referrals', 0) + 1
                api.patch(f"/users/{referrer_id}", {'referrals': new_referrals})
                
                # Notify referrer
                try:
                    await context.bot.send_message(
                        chat_id=int(referrer_id),
                        text=format_message(f"{safe_emoji('party')} **New Referral Bonus!**\n\n"
                            f"You earned ${referral_bonus} from a new referral!\n"
                            f"Keep sharing your link to earn more!")
                    )
                except Exception:
                    pass

    # Get bot settings for display
    settings = api.get("/bot-settings")
    daily_limit = settings.get('dailyLimit', 5.0)
    min_withdraw = settings.get('minWithdraw', 10.0)
    currency = settings.get('currency', '$')
    task_rewards = settings.get('taskRewards', {})
    
    # Refresh user data
    user = api.get(f"/users/{user_id}") or {}
    
    welcome_message = format_message(f"""
{safe_emoji('rocket')} **Welcome to BitcoRise Bot!**

{safe_emoji('money')} **Earn crypto by completing tasks:**
• YouTube Like: {currency}{task_rewards.get('like', 0.05)}
• YouTube Comment: {currency}{task_rewards.get('comment', 0.10)}
• Channel Subscribe: {currency}{task_rewards.get('subscribe', 0.15)}
• Watch Video 45s: {currency}{task_rewards.get('watch', 0.08)}
• Watch Video 3min: {currency}{task_rewards.get('watch_3min', 0.20)}
• Visit Article: {currency}{task_rewards.get('visit', 0.03)}

{safe_emoji('diamond')} **Your Dashboard:**
{safe_emoji('money')} Balance: {currency}{user.get('balance', 0):.2f}
{safe_emoji('chart')} Total Earned: {currency}{user.get('totalEarned', 0):.2f}
{safe_emoji('task')} Tasks Done: {user.get('tasksCompleted', 0)}
{safe_emoji('people')} Referrals: {user.get('referrals', 0)}

{safe_emoji('info')} Daily Limit: {currency}{daily_limit} | Min Payout: {currency}{min_withdraw}

Choose your action below! {safe_emoji('down_arrow')}""")
    
    keyboard = [
        [
            InlineKeyboardButton(f"{safe_emoji('target')} Start Earning", callback_data="show_tasks"),
            InlineKeyboardButton(f"{safe_emoji('card')} My Balance", callback_data="show_balance")
        ],
        [
            InlineKeyboardButton(f"{safe_emoji('payout')} Request Payout", callback_data="show_payout"),
            InlineKeyboardButton(f"{safe_emoji('people')} Referrals", callback_data="show_referrals")
        ],
        [
            InlineKeyboardButton(f"{safe_emoji('folder')} My Requests", callback_data="show_requests"),
            InlineKeyboardButton(f"{safe_emoji('info')} Help & FAQ", callback_data="show_help")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enhanced button handler with proper confirmation system"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = str(query.from_user.id)
    username = query.from_user.username or f"user_{user_id}"
    full_username = f"@{username}" if not username.startswith('@') else username
    
    # Get current user and settings
    user = get_or_create_user(user_id, full_username)
    settings = api.get("/bot-settings")
    daily_limit = settings.get('dailyLimit', 5.0)
    min_withdraw = settings.get('minWithdraw', 10.0)
    currency = settings.get('currency', '$')
    task_rewards = settings.get('taskRewards', {})
    
    if data == "show_tasks":
        await handle_show_tasks(query, user, daily_limit, currency, task_rewards)
    elif data == "show_balance":
        await handle_show_balance(query, user, currency)
    elif data == "show_payout":
        await handle_show_payout(query, user, min_withdraw, currency)
    elif data == "show_referrals":
        await handle_show_referrals(query, user, settings, context)
    elif data == "show_requests":
        await handle_show_requests(query, user_id)
    elif data == "show_help":
        await handle_show_help(query, settings)
    elif data == "back_main":
        await handle_back_to_main(query, user, settings)
    elif data.startswith("task_"):
        await handle_task_start(query, data, user_id, user, task_rewards, currency, daily_limit)
    elif data.startswith("confirm_task_"):
        await handle_task_confirm(query, data, user_id, task_rewards, currency)
    elif data.startswith("claim_task_"):
        await handle_task_claim(query, data, user_id, user, task_rewards, currency)

async def handle_show_tasks(query, user: Dict, daily_limit: float, currency: str, task_rewards: Dict):
    """Show available tasks with enhanced UI"""
    if not can_earn_today(user, daily_limit):
        message = format_message(f"{safe_emoji('warning')} **Daily Limit Reached!**\n\n"
            f"You've earned {currency}{user.get('dailyEarned', 0):.2f} today.\n"
            f"Daily limit: {currency}{daily_limit}\n\n"
            f"Come back tomorrow to continue earning! {safe_emoji('clock')}")
        
        keyboard = [[InlineKeyboardButton(f"{safe_emoji('back')} Back to Menu", callback_data="back_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        return
    
    tasks = api.get("/tasks")
    active_tasks_message = f"{safe_emoji('target')} **Available Earning Tasks**\n\n"
    
    keyboard = []
    if tasks:
        for task in tasks:
            if task.get('isActive', True):
                task_key = task.get('key', '')
                reward = task_rewards.get(task_key, 0)
                wait_time = task.get('waitTime', 30)
                
                # Check if user has active task
                remaining_time = task_manager.get_remaining_time(user_id=str(query.from_user.id), 
                                                               task_key=task_key, 
                                                               wait_time=wait_time)
                
                if remaining_time > 0:
                    button_text = f"{safe_emoji('wait')} {task['name']} - Wait {format_time(remaining_time)}"
                    callback_data = f"claim_task_{task_key}"
                else:
                    button_text = f"{safe_emoji('money')} {task['name']} - {currency}{reward}"
                    callback_data = f"task_{task_key}"
                
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    if not keyboard:
        active_tasks_message += f"{safe_emoji('info')} No tasks available at the moment.\n"
    else:
        active_tasks_message += f"Choose a task to start earning! Each task has a wait time before you can claim your reward.\n\n"
        active_tasks_message += f"{safe_emoji('info')} **Today's Progress:** {currency}{user.get('dailyEarned', 0):.2f} / {currency}{daily_limit}"
    
    keyboard.append([InlineKeyboardButton(f"{safe_emoji('back')} Back to Menu", callback_data="back_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        format_message(active_tasks_message), 
        reply_markup=reply_markup, 
        parse_mode='Markdown'
    )

async def handle_task_start(query, data: str, user_id: str, user: Dict, task_rewards: Dict, currency: str, daily_limit: float):
    """Handle task start with confirmation"""
    task_key = data.replace("task_", "")
    
    if not can_earn_today(user, daily_limit):
        await query.answer("Daily earning limit reached!", show_alert=True)
        return
    
    # Get task details
    tasks = api.get("/tasks")
    task = None
    for t in tasks:
        if t.get('key') == task_key:
            task = t
            break
    
    if not task:
        await query.answer("Task not found!", show_alert=True)
        return
    
    reward = task_rewards.get(task_key, 0)
    wait_time = task.get('waitTime', 30)
    
    # Check if already started
    remaining_time = task_manager.get_remaining_time(user_id, task_key, wait_time)
    if remaining_time > 0:
        await query.answer(f"Task already in progress! Wait {format_time(remaining_time)}", show_alert=True)
        return
    
    confirmation_message = format_message(f"""
{safe_emoji('confirm')} **Start Task Confirmation**

{safe_emoji('task')} **Task:** {task.get('name', '')}
{safe_emoji('info')} **Description:** {task.get('description', '')}
{safe_emoji('money')} **Reward:** {currency}{reward}
{safe_emoji('time')} **Wait Time:** {format_time(wait_time)}

{safe_emoji('warning')} **Instructions:**
1. Click "Start Task" to begin
2. Complete the required action
3. Wait for the timer to finish
4. Claim your reward

Ready to start? {safe_emoji('target')}""")
    
    keyboard = [
        [
            InlineKeyboardButton(f"{safe_emoji('confirm')} Start Task", callback_data=f"confirm_task_{task_key}"),
            InlineKeyboardButton(f"{safe_emoji('cancel')} Cancel", callback_data="show_tasks")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(confirmation_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_task_confirm(query, data: str, user_id: str, task_rewards: Dict, currency: str):
    """Handle task confirmation and start timer"""
    task_key = data.replace("confirm_task_", "")
    
    # Start the task timer
    success = task_manager.start_task(user_id, task_key)
    if not success:
        await query.answer("Failed to start task. Please try again.", show_alert=True)
        return
    
    # Get task details
    tasks = api.get("/tasks")
    task = None
    for t in tasks:
        if t.get('key') == task_key:
            task = t
            break
    
    reward = task_rewards.get(task_key, 0)
    wait_time = task.get('waitTime', 30)
    
    task_started_message = format_message(f"""
{safe_emoji('loading')} **Task Started Successfully!**

{safe_emoji('task')} **Task:** {task.get('name', '')}
{safe_emoji('money')} **Reward:** {currency}{reward}
{safe_emoji('time')} **Timer:** {format_time(wait_time)}

{safe_emoji('info')} **Next Steps:**
1. ✅ Task timer started
2. 🔗 Click the task links below to complete the action
3. ⏰ Wait for timer to finish ({format_time(wait_time)})
4. 💰 Return to claim your reward

{safe_emoji('warning')} **Important:** Complete the action now, but you can only claim the reward after the timer finishes!""")
    
    # Add task links if available
    if task and task.get('links'):
        links = task.get('links', [])
        link_buttons = []
        
        for i, link in enumerate(links[:3]):  # Limit to 3 links
            if task_key == "visit":
                button_text = f"{safe_emoji('news')} Article {i+1}"
            elif task_key == "subscribe":
                button_text = f"{safe_emoji('bell')} Channel {i+1}"
            else:
                button_text = f"{safe_emoji('video')} Video {i+1}"
            
            link_buttons.append([InlineKeyboardButton(button_text, url=link)])
    else:
        link_buttons = []
    
    keyboard = link_buttons + [
        [
            InlineKeyboardButton(f"{safe_emoji('complete')} Check Status", callback_data=f"claim_task_{task_key}"),
            InlineKeyboardButton(f"{safe_emoji('back')} Back to Tasks", callback_data="show_tasks")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(task_started_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_task_claim(query, data: str, user_id: str, user: Dict, task_rewards: Dict, currency: str):
    """Handle task reward claiming"""
    task_key = data.replace("claim_task_", "")
    
    # Get task details
    tasks = api.get("/tasks")
    task = None
    for t in tasks:
        if t.get('key') == task_key:
            task = t
            break
    
    if not task:
        await query.answer("Task not found!", show_alert=True)
        return
    
    wait_time = task.get('waitTime', 30)
    reward = task_rewards.get(task_key, 0)
    
    # Check if task can be claimed
    if not task_manager.is_task_completed(user_id, task_key, wait_time):
        remaining_time = task_manager.get_remaining_time(user_id, task_key, wait_time)
        if remaining_time > 0:
            await query.answer(f"Please wait {format_time(remaining_time)} more to claim your reward!", show_alert=True)
            return
        else:
            await query.answer("Task not started yet! Please start the task first.", show_alert=True)
            return
    
    # Award the reward
    success = add_user_earnings(user_id, reward)
    if success:
        # Complete the task
        task_manager.complete_task(user_id, task_key)
        
        # Get updated user data
        updated_user = api.get(f"/users/{user_id}") or {}
        
        success_message = format_message(f"""
{safe_emoji('party')} **Congratulations!**

{safe_emoji('done')} **Task Completed:** {task.get('name', '')}
{safe_emoji('money')} **Reward Earned:** {currency}{reward}
{safe_emoji('card')} **New Balance:** {currency}{updated_user.get('balance', 0):.2f}
{safe_emoji('chart')} **Total Earned:** {currency}{updated_user.get('totalEarned', 0):.2f}

{safe_emoji('target')} Keep completing tasks to earn more! {safe_emoji('fire')}""")
        
        keyboard = [
            [
                InlineKeyboardButton(f"{safe_emoji('target')} More Tasks", callback_data="show_tasks"),
                InlineKeyboardButton(f"{safe_emoji('card')} Balance", callback_data="show_balance")
            ],
            [InlineKeyboardButton(f"{safe_emoji('back')} Main Menu", callback_data="back_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(success_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await query.answer("Failed to process reward. Please try again.", show_alert=True)

async def handle_show_balance(query, user: Dict, currency: str):
    """Show user balance and statistics"""
    balance_message = format_message(f"""
{safe_emoji('card')} **Your Balance & Stats**

{safe_emoji('money')} **Current Balance:** {currency}{user.get('balance', 0):.2f}
{safe_emoji('chart')} **Total Earned:** {currency}{user.get('totalEarned', 0):.2f}
{safe_emoji('task')} **Tasks Completed:** {user.get('tasksCompleted', 0)}
{safe_emoji('people')} **Referrals:** {user.get('referrals', 0)}
{safe_emoji('chart_up')} **Daily Earned:** {currency}{user.get('dailyEarned', 0):.2f}

{safe_emoji('info')} **Account Info:**
👤 Username: {user.get('username', 'N/A')}
📅 Joined: {user.get('joined', 'N/A')[:10] if user.get('joined') else 'N/A'}

{safe_emoji('payout')} Ready to withdraw? Use the payout option!""")
    
    keyboard = [
        [
            InlineKeyboardButton(f"{safe_emoji('payout')} Request Payout", callback_data="show_payout"),
            InlineKeyboardButton(f"{safe_emoji('target')} Earn More", callback_data="show_tasks")
        ],
        [InlineKeyboardButton(f"{safe_emoji('back')} Back to Menu", callback_data="back_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(balance_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_show_payout(query, user: Dict, min_withdraw: float, currency: str):
    """Show payout options and requirements"""
    balance = user.get('balance', 0)
    
    if balance < min_withdraw:
        payout_message = format_message(f"""
{safe_emoji('warning')} **Insufficient Balance for Payout**

{safe_emoji('money')} **Your Balance:** {currency}{balance:.2f}
{safe_emoji('payout')} **Minimum Required:** {currency}{min_withdraw}
{safe_emoji('chart_up')} **Need More:** {currency}{(min_withdraw - balance):.2f}

{safe_emoji('target')} **How to reach minimum:**
• Complete more tasks to earn money
• Refer friends to get bonus rewards
• Check back daily for new opportunities

{safe_emoji('fire')} Keep earning to unlock payouts!""")
        
        keyboard = [
            [
                InlineKeyboardButton(f"{safe_emoji('target')} Start Earning", callback_data="show_tasks"),
                InlineKeyboardButton(f"{safe_emoji('people')} Referrals", callback_data="show_referrals")
            ],
            [InlineKeyboardButton(f"{safe_emoji('back')} Back to Menu", callback_data="back_main")]
        ]
    else:
        payout_message = format_message(f"""
{safe_emoji('payout')} **Payout Request Available**

{safe_emoji('money')} **Available Balance:** {currency}{balance:.2f}
{safe_emoji('check')} **Minimum Met:** {currency}{min_withdraw} ✓

{safe_emoji('info')} **Payment Methods Available:**
💳 PayPal (Email required)
₿ Bitcoin (BTC address)
💵 USDT TRC20 (USDT address)
⟠ Ethereum (ETH address)

{safe_emoji('warning')} **Important:**
• Payouts are processed manually by admin
• Processing time: 24-48 hours
• Make sure your payment details are correct
• You can track your request status

Ready to request a payout?""")
        
        keyboard = [
            [InlineKeyboardButton(f"{safe_emoji('payout')} Start Payout Request", url=f"https://t.me/{ADMIN_USERNAME}")],
            [
                InlineKeyboardButton(f"{safe_emoji('folder')} My Requests", callback_data="show_requests"),
                InlineKeyboardButton(f"{safe_emoji('back')} Back to Menu", callback_data="back_main")
            ]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(payout_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_show_referrals(query, user: Dict, settings: Dict, context):
    """Show referral system information"""
    referral_bonus = settings.get('referralBonus', 1.0)
    currency = settings.get('currency', '$')
    
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={query.from_user.id}"
    
    referral_message = format_message(f"""
{safe_emoji('people')} **Referral Program**

{safe_emoji('gift')} **Your Referral Stats:**
👥 Total Referrals: {user.get('referrals', 0)}
💰 Bonus per Referral: {currency}{referral_bonus}
🎯 Total Referral Earnings: {currency}{user.get('referrals', 0) * referral_bonus}

{safe_emoji('info')} **How it works:**
1. Share your unique referral link
2. When someone joins using your link
3. You instantly earn {currency}{referral_bonus}
4. They can start earning immediately too!

{safe_emoji('link')} **Your Referral Link:**
`{referral_link}`

{safe_emoji('fire')} **Pro Tips:**
• Share on social media for more referrals
• Tell friends about earning opportunities
• Both you and your referrals benefit!""")
    
    keyboard = [
        [InlineKeyboardButton(f"{safe_emoji('link')} Share Referral Link", url=f"https://t.me/share/url?url={referral_link}&text=Join me on BitcoRise Bot to earn cryptocurrency!")],
        [InlineKeyboardButton(f"{safe_emoji('back')} Back to Menu", callback_data="back_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(referral_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_show_requests(query, user_id: str):
    """Show user's payout requests"""
    requests = api.get("/payout-requests")
    user_requests = [req for req in requests if req.get('userId') == user_id] if requests else []
    
    if not user_requests:
        requests_message = format_message(f"""
{safe_emoji('folder')} **Your Payout Requests**

{safe_emoji('info')} You haven't made any payout requests yet.

{safe_emoji('payout')} When you're ready to withdraw your earnings, you can request a payout through the balance menu.

{safe_emoji('target')} Keep earning to reach the minimum payout amount!""")
    else:
        requests_message = format_message(f"{safe_emoji('folder')} **Your Payout Requests**\n\n")
        
        for i, req in enumerate(user_requests[-5:], 1):  # Show last 5 requests
            status_emoji = {
                'pending': safe_emoji('clock'),
                'approved': safe_emoji('check'),
                'completed': safe_emoji('done'),
                'rejected': safe_emoji('error')
            }.get(req.get('status', ''), safe_emoji('info'))
            
            requests_message += f"**{i}. Request #{req.get('id', 'N/A')[-4:]}**\n"
            requests_message += f"💰 Amount: ${req.get('amount', 0):.2f}\n"
            requests_message += f"💳 Method: {req.get('paymentMethod', 'N/A')}\n"
            requests_message += f"{status_emoji} Status: {req.get('status', 'unknown').title()}\n"
            requests_message += f"📅 Date: {req.get('createdAt', 'N/A')[:10] if req.get('createdAt') else 'N/A'}\n\n"
        
        if len(user_requests) > 5:
            requests_message += f"{safe_emoji('info')} Showing last 5 requests. Total: {len(user_requests)}"
    
    keyboard = [
        [
            InlineKeyboardButton(f"{safe_emoji('payout')} New Request", callback_data="show_payout"),
            InlineKeyboardButton(f"{safe_emoji('card')} Balance", callback_data="show_balance")
        ],
        [InlineKeyboardButton(f"{safe_emoji('back')} Back to Menu", callback_data="back_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(requests_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_show_help(query, settings: Dict):
    """Show help and FAQ"""
    currency = settings.get('currency', '$')
    daily_limit = settings.get('dailyLimit', 5.0)
    min_withdraw = settings.get('minWithdraw', 10.0)
    
    help_message = format_message(f"""
{safe_emoji('info')} **Help & FAQ**

{safe_emoji('target')} **How to Earn:**
1. Click "Start Earning" to see available tasks
2. Choose a task and confirm to start the timer
3. Complete the required action (like, subscribe, etc.)
4. Wait for timer to finish, then claim your reward

{safe_emoji('payout')} **Payouts:**
• Minimum withdrawal: {currency}{min_withdraw}
• Processing time: 24-48 hours
• Supported: PayPal, Bitcoin, USDT, Ethereum
• Contact admin for payout requests

{safe_emoji('clock')} **Limits & Rules:**
• Daily earning limit: {currency}{daily_limit}
• Each task has a wait time before claiming
• Complete tasks honestly for fair rewards
• Referral bonus for each friend you invite

{safe_emoji('people')} **Need Support?**
Contact our admin: @{ADMIN_USERNAME}

{safe_emoji('fire')} Happy earning!""")
    
    keyboard = [
        [InlineKeyboardButton(f"👨‍💼 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")],
        [InlineKeyboardButton(f"{safe_emoji('back')} Back to Menu", callback_data="back_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(help_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_back_to_main(query, user: Dict, settings: Dict):
    """Return to main menu"""
    currency = settings.get('currency', '$')
    
    main_message = format_message(f"""
{safe_emoji('rocket')} **BitcoRise Bot - Main Menu**

{safe_emoji('diamond')} **Your Quick Stats:**
{safe_emoji('money')} Balance: {currency}{user.get('balance', 0):.2f}
{safe_emoji('chart')} Total Earned: {currency}{user.get('totalEarned', 0):.2f}
{safe_emoji('task')} Tasks Completed: {user.get('tasksCompleted', 0)}

{safe_emoji('target')} Ready to earn more? Choose an option below!""")
    
    keyboard = [
        [
            InlineKeyboardButton(f"{safe_emoji('target')} Start Earning", callback_data="show_tasks"),
            InlineKeyboardButton(f"{safe_emoji('card')} My Balance", callback_data="show_balance")
        ],
        [
            InlineKeyboardButton(f"{safe_emoji('payout')} Request Payout", callback_data="show_payout"),
            InlineKeyboardButton(f"{safe_emoji('people')} Referrals", callback_data="show_referrals")
        ],
        [
            InlineKeyboardButton(f"{safe_emoji('folder')} My Requests", callback_data="show_requests"),
            InlineKeyboardButton(f"{safe_emoji('info')} Help & FAQ", callback_data="show_help")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(main_message, reply_markup=reply_markup, parse_mode='Markdown')

# === MAIN APPLICATION ===
def main() -> None:
    """Start the bot with enhanced error handling"""
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # Add error handler
        async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            logger.error(f"Exception while handling an update: {context.error}")
        
        application.add_error_handler(error_handler)
        
        logger.info("🎯 BitcoRise Bot started successfully!")
        logger.info("✅ Enhanced confirmation system active")
        logger.info("💰 Manual payout system integrated")  
        logger.info("🎨 Attractive interface loaded")
        logger.info("🔧 All errors fixed and optimized")
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        exit(1)

if __name__ == '__main__':
    main()