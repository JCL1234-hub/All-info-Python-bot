import os
import html
import json
import asyncio
import logging
from datetime import datetime, timedelta
import aiohttp
import aiosqlite
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ConversationHandler, ContextTypes
)
from telegram.error import TelegramError

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 8368189873

# Conversation States
WAITING_INPUT = 1

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= DB INITIALIZATION =================
async def init_db():
    async with aiosqlite.connect('database.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS admins 
                            (user_id INTEGER PRIMARY KEY)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS groups 
                            (group_id INTEGER PRIMARY KEY, link TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS channels 
                            (channel_id INTEGER PRIMARY KEY, link TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS settings 
                            (key TEXT PRIMARY KEY, value TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS search_logs 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, search_type TEXT, query TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Insert owner and default settings
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_status', 'ON')")
        await db.commit()

# ================= HELPER FUNCTIONS =================
async def is_admin(user_id: int) -> bool:
    async with aiosqlite.connect('database.db') as db:
        async with db.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def is_group_approved(chat_id: int) -> bool:
    async with aiosqlite.connect('database.db') as db:
        async with db.execute("SELECT group_id FROM groups WHERE group_id = ?", (chat_id,)) as cursor:
            return await cursor.fetchone() is not None

async def check_maintenance(user_id: int) -> bool:
    async with aiosqlite.connect('database.db') as db:
        async with db.execute("SELECT value FROM settings WHERE key='bot_status'") as cursor:
            row = await cursor.fetchone()
            status = row[0] if row else 'ON'
    if status == 'OFF' and not await is_admin(user_id):
        return False
    return True

async def check_force_sub(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    async with aiosqlite.connect('database.db') as db:
        async with db.execute("SELECT channel_id FROM channels") as cursor:
            channels = await cursor.fetchall()
    
    for (channel_id,) in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except TelegramError:
            pass # If bot can't reach channel, assume user not joined
    return True

async def fetch_api(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=20) as response:
                if response.status == 200:
                    try:
                        return await response.json()
                    except:
                        return {"error": "Invalid JSON response from API"}
                return {"error": f"API Error: Status {response.status}"}
        except Exception as e:
            return {"error": str(e)}

def format_json_to_html(data, indent=0):
    html_out = ""
    space = "&nbsp;&nbsp;&nbsp;&nbsp;" * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                html_out += f"{space}<b>{html.escape(str(k)).capitalize()}</b>:\n{format_json_to_html(v, indent+1)}"
            else:
                html_out += f"{space}<b>{html.escape(str(k)).capitalize()}</b>: <code>{html.escape(str(v))}</code>\n"
    elif isinstance(data, list):
        for i, item in enumerate(data):
            html_out += f"{space}<b>Item {i+1}</b>:\n{format_json_to_html(item, indent+1)}"
    else:
        html_out += f"{space}<code>{html.escape(str(data))}</code>\n"
    return html_out

# ================= MAIN MENU & START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type in ['group', 'supergroup']:
        if not await is_group_approved(chat.id):
            await update.message.reply_text("This group is not approved.")
            return ConversationHandler.END

    if not await check_maintenance(user.id):
        await update.message.reply_text("Bot is currently under maintenance.")
        return ConversationHandler.END

    # Register user
    async with aiosqlite.connect('database.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)", 
                         (user.id, user.username, user.first_name))
        await db.commit()

    # Get channels for force sub buttons
    async with aiosqlite.connect('database.db') as db:
        async with db.execute("SELECT link FROM channels") as cursor:
            channels = await cursor.fetchall()

    buttons = []
    for (link,) in channels:
        buttons.append([InlineKeyboardButton("✅ Join Channel", url=link)])
    
    buttons.append([InlineKeyboardButton("✅ Verify", callback_data="verify_sub")])
    reply_markup = InlineKeyboardMarkup(buttons)
    
    await update.message.reply_text(
        f"Hello {user.first_name}! Welcome to Code Craft All Info Bot.\n"
        "Please join our channels and click 'Verify' to access the main menu.",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

async def send_main_menu(message_obj):
    keyboard = [
        [InlineKeyboardButton("📱 Number Info", callback_data="api_number"), InlineKeyboardButton("🪪 Aadhar Info", callback_data="api_aadhar")],
        [InlineKeyboardButton("🚗 Car Info", callback_data="api_car"), InlineKeyboardButton("📧 Gmail Info", callback_data="api_gmail")],
        [InlineKeyboardButton("🌐 IP Info", callback_data="api_ip"), InlineKeyboardButton("🐙 Github Info", callback_data="api_github")],
        [InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/username_506"), InlineKeyboardButton("📢 Official Channel", url="https://t.me/jcodeslab")],
        [InlineKeyboardButton("❌ Close", callback_data="close_menu")]
    ]
    await message_obj.edit_text("<b>Main Menu</b>\nSelect an option below:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# ================= BUTTON ROUTER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    chat = update.effective_chat
    await query.answer()

    if chat.type in ['group', 'supergroup'] and not await is_group_approved(chat.id):
        await query.message.reply_text("This group is not approved.")
        return ConversationHandler.END

    if not await check_maintenance(user.id):
        await query.message.reply_text("Bot is currently under maintenance.")
        return ConversationHandler.END

    data = query.data

    # Main Menu Actions
    if data == "verify_sub":
        if await check_force_sub(user.id, context):
            await send_main_menu(query.message)
        else:
            await query.message.reply_text("You must join all channels first.")
        return ConversationHandler.END

    elif data == "close_menu":
        await query.message.delete()
        return ConversationHandler.END

    elif data.startswith("api_"):
        action = data.split("_")[1]
        context.user_data['action'] = action
        prompts = {
            "number": "Send Mobile Number with country code. (Example: +916204458125)",
            "aadhar": "Send Aadhar Number",
            "car": "Send Vehicle Number (Example: RJ18CF3690)",
            "gmail": "Send Gmail Address",
            "ip": "Send IP Address",
            "github": "Send Github Username"
        }
        await query.message.reply_text(f"Please {prompts[action]}")
        return WAITING_INPUT

    # Admin Panel Actions
    elif data.startswith("admin_"):
        if not await is_admin(user.id):
            await query.message.reply_text("You are not authorized.")
            return ConversationHandler.END

        if data == "admin_status_toggle":
            async with aiosqlite.connect('database.db') as db:
                async with db.execute("SELECT value FROM settings WHERE key='bot_status'") as cursor:
                    status = (await cursor.fetchone())[0]
                new_status = "OFF" if status == "ON" else "ON"
                await db.execute("UPDATE settings SET value=? WHERE key='bot_status'", (new_status,))
                await db.commit()
            await query.message.reply_text(f"Bot Status changed to: {new_status}")
            return ConversationHandler.END

        elif data == "admin_users":
            async with aiosqlite.connect('database.db') as db:
                async with db.execute("SELECT user_id, username, first_name, reg_date FROM users") as cursor:
                    users = await cursor.fetchall()
            
            with open("users.txt", "w", encoding="utf-8") as f:
                f.write("User ID | Username | First Name | Reg Date\n")
                f.write("-" * 50 + "\n")
                for u in users:
                    f.write(f"{u[0]} | {u[1]} | {u[2]} | {u[3]}\n")
            
            await context.bot.send_document(chat_id=chat.id, document=open("users.txt", "rb"))
            os.remove("users.txt")
            return ConversationHandler.END

        elif data in ["admin_add_group", "admin_remove_group", "admin_add_channel", "admin_remove_channel", "admin_add_admin", "admin_remove_admin", "admin_broadcast"]:
            context.user_data['action'] = data
            prompts = {
                "admin_add_group": "Send Group ID and Link separated by space.\nExample: -100123456789 https://t.me/link",
                "admin_remove_group": "Send Group ID to remove.",
                "admin_add_channel": "Send Channel ID and Link separated by space.",
                "admin_remove_channel": "Send Channel ID to remove.",
                "admin_add_admin": "Send User ID to add as Admin.",
                "admin_remove_admin": "Send User ID to remove from Admins.",
                "admin_broadcast": "Send the message you want to broadcast."
            }
            await query.message.reply_text(prompts[data])
            return WAITING_INPUT

        elif data in ["admin_show_groups", "admin_show_channels", "admin_show_admins"]:
            table_map = {"admin_show_groups": "groups", "admin_show_channels": "channels", "admin_show_admins": "admins"}
            table = table_map[data]
            async with aiosqlite.connect('database.db') as db:
                async with db.execute(f"SELECT * FROM {table}") as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                await query.message.reply_text(f"No records found in {table}.")
            else:
                msg = f"<b>Records in {table}:</b>\n"
                for row in rows:
                    msg += f"<code>{row}</code>\n"
                await query.message.reply_text(msg, parse_mode="HTML")
            return ConversationHandler.END

# ================= INPUT PROCESSOR =================
async def process_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    action = context.user_data.get('action')
    user = update.effective_user

    # Handle APIs
    api_urls = {
        "number": "https://number-aadvance-info-noobster.com-dashbord63hh7qe4.workers.dev/?key=demo&mobile={}",
        "aadhar": "https://adhaar2info-noobster.com-dashbord63hh7qe4.workers.dev/?key=@noob11001&id={}",
        "car": "https://vehicleto-adavanceinfo-noobster.com-dashbord63hh7qe4.workers.dev/?rc={}",
        "gmail": "https://gmail-advance-info-noobster.com-dashbord63hh7qe4.workers.dev/?key=demo&email={}",
        "ip": "https://ipwho.is/{}",
        "github": "https://github2info-noobster.com-dashbord63hh7qe4.workers.dev/?username={}"
    }

    if action in api_urls:
        status_msg = await update.message.reply_text("Searching... ⏳")
        url = api_urls[action].format(text)
        data = await fetch_api(url)
        
        # Log Search
        async with aiosqlite.connect('database.db') as db:
            await db.execute("INSERT INTO search_logs (user_id, search_type, query) VALUES (?, ?, ?)", 
                             (user.id, action, text))
            await db.commit()

        result_html = f"<b>Result for {html.escape(text)}</b>\n\n" + format_json_to_html(data)
        if len(result_html) > 4000:
            result_html = result_html[:3900] + "\n...[Truncated]"
        
        await status_msg.edit_text(result_html, parse_mode="HTML")
        return ConversationHandler.END

    # Handle Admin Inputs
    if action.startswith("admin_"):
        if not await is_admin(user.id):
            return ConversationHandler.END
        
        try:
            if action == "admin_broadcast":
                status_msg = await update.message.reply_text("Broadcasting... ⏳")
                async with aiosqlite.connect('database.db') as db:
                    async with db.execute("SELECT user_id FROM users") as cursor:
                        users = await cursor.fetchall()
                
                success, failed = 0, 0
                for (uid,) in users:
                    try:
                        await context.bot.copy_message(chat_id=uid, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
                        success += 1
                        await asyncio.sleep(0.05)
                    except:
                        failed += 1
                
                await status_msg.edit_text(f"<b>Broadcast Completed!</b>\nSuccess: {success}\nFailed: {failed}\nTotal: {success+failed}", parse_mode="HTML")

            elif action in ["admin_add_group", "admin_add_channel"]:
                parts = text.split()
                if len(parts) != 2:
                    await update.message.reply_text("Invalid format. Send ID and Link separated by space.")
                    return ConversationHandler.END
                target_id = int(parts[0])
                link = parts[1]
                
                # Verify admin status in that chat
                member = await context.bot.get_chat_member(chat_id=target_id, user_id=context.bot.id)
                if member.status not in ['administrator', 'creator']:
                    await update.message.reply_text("Bot is not an admin in that chat!")
                    return ConversationHandler.END

                table = "groups" if action == "admin_add_group" else "channels"
                col = "group_id" if action == "admin_add_group" else "channel_id"
                
                async with aiosqlite.connect('database.db') as db:
                    await db.execute(f"INSERT OR REPLACE INTO {table} ({col}, link) VALUES (?, ?)", (target_id, link))
                    await db.commit()
                await update.message.reply_text(f"Successfully added to {table}.")

            elif action in ["admin_remove_group", "admin_remove_channel"]:
                target_id = int(text)
                table = "groups" if action == "admin_remove_group" else "channels"
                col = "group_id" if action == "admin_remove_group" else "channel_id"
                
                async with aiosqlite.connect('database.db') as db:
                    await db.execute(f"DELETE FROM {table} WHERE {col} = ?", (target_id,))
                    await db.commit()
                await update.message.reply_text(f"Removed from {table}.")

            elif action == "admin_add_admin":
                uid = int(text)
                async with aiosqlite.connect('database.db') as db:
                    await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (uid,))
                    await db.commit()
                await update.message.reply_text("Admin added successfully.")

            elif action == "admin_remove_admin":
                uid = int(text)
                if uid == OWNER_ID:
                    await update.message.reply_text("Cannot remove Owner!")
                    return ConversationHandler.END
                async with aiosqlite.connect('database.db') as db:
                    await db.execute("DELETE FROM admins WHERE user_id = ?", (uid,))
                    await db.commit()
                await update.message.reply_text("Admin removed.")

        except Exception as e:
            await update.message.reply_text(f"An error occurred: {str(e)}")
            
        return ConversationHandler.END

    return ConversationHandler.END

# ================= ADMIN PANEL =================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_admin(user.id):
        await update.message.reply_text("You do not have admin access.")
        return ConversationHandler.END

    # Fetch Stats
    async with aiosqlite.connect('database.db') as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM groups") as cursor:
            total_groups = (await cursor.fetchone())[0]
        
        forty_eight_hours_ago = datetime.utcnow() - timedelta(hours=48)
        async with db.execute("SELECT COUNT(*) FROM search_logs WHERE timestamp >= ?", (forty_eight_hours_ago,)) as cursor:
            total_searches = (await cursor.fetchone())[0]
            
        async with db.execute("SELECT value FROM settings WHERE key='bot_status'") as cursor:
            bot_status = (await cursor.fetchone())[0]

    stats_text = (
        "👑 <b>Admin Panel</b>\n\n"
        f"👥 Total Users: <code>{total_users}</code>\n"
        f"🛡 Total Groups: <code>{total_groups}</code>\n"
        f"🔍 Searches (48h): <code>{total_searches}</code>\n"
        f"🤖 Bot Status: <b>{bot_status}</b>"
    )

    keyboard = [
        [InlineKeyboardButton("➕ Add Group", callback_data="admin_add_group"), InlineKeyboardButton("➖ Remove Group", callback_data="admin_remove_group")],
        [InlineKeyboardButton("📋 Show Groups", callback_data="admin_show_groups")],
        [InlineKeyboardButton("➕ Add Channel", callback_data="admin_add_channel"), InlineKeyboardButton("➖ Remove Channel", callback_data="admin_remove_channel")],
        [InlineKeyboardButton("📋 Show Channels", callback_data="admin_show_channels")],
        [InlineKeyboardButton("➕ Add Admin", callback_data="admin_add_admin"), InlineKeyboardButton("➖ Remove Admin", callback_data="admin_remove_admin")],
        [InlineKeyboardButton("📋 Show Admins", callback_data="admin_show_admins")],
        [InlineKeyboardButton("🟢 ON / ?
