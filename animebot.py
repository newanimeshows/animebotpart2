import os
import re
import sqlite3
import requests
import asyncio
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Your Telegram bot token
TOKEN = os.getenv('BOT_TOKEN')

# Initialize SQLite databases
def init_db():
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            user_id INTEGER,
            anime_name TEXT,
            remind_time TEXT,
            PRIMARY KEY (user_id, anime_name, remind_time)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_interaction TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            anime_name TEXT,
            PRIMARY KEY (user_id, anime_name)
        )
    ''')
    conn.commit()
    conn.close()

def init_welcome_db():
    try:
        conn = sqlite3.connect('welcome.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS welcome_status (
                user_id INTEGER PRIMARY KEY,
                last_welcome_date TEXT
            )
        ''')
        conn.commit()
        conn.close()
        print("SQLite database initialized successfully.")
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")

def has_been_welcomed_today(user_id):
    try:
        conn = sqlite3.connect('welcome.db')
        cursor = conn.cursor()
        cursor.execute('SELECT last_welcome_date FROM welcome_status WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            last_welcome_date = datetime.strptime(result[0], '%Y-%m-%d').date()
            today = date.today()
            return last_welcome_date == today
        else:
            return False
    except sqlite3.Error as e:
        print(f"SQLite error in has_been_welcomed_today(): {e}")
        return False

def update_welcome_status(user_id):
    try:
        conn = sqlite3.connect('welcome.db')
        cursor = conn.cursor()
        today = date.today().isoformat()
        cursor.execute('INSERT OR REPLACE INTO welcome_status (user_id, last_welcome_date) VALUES (?, ?)', (user_id, today))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"SQLite error in update_welcome_status(): {e}")

# Database functions
def add_reminder(user_id, anime_name, remind_time):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO reminders (user_id, anime_name, remind_time) VALUES (?, ?, ?)',
                   (user_id, anime_name, remind_time))
    conn.commit()
    conn.close()

def remove_reminder(user_id, anime_name):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM reminders WHERE user_id = ? AND anime_name = ?', (user_id, anime_name))
    conn.commit()
    conn.close()

def show_reminders(user_id):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('SELECT anime_name, remind_time FROM reminders WHERE user_id = ?', (user_id,))
    reminders = cursor.fetchall()
    conn.close()
    return reminders

def add_favorite(user_id, anime_name, english_title=None):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    title_to_store = english_title if english_title else anime_name
    cursor.execute('INSERT OR IGNORE INTO favorites (user_id, anime_name) VALUES (?, ?)', (user_id, title_to_store))
    conn.commit()
    conn.close()

def remove_favorite(user_id, anime_name, english_title=None):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    if english_title:
        cursor.execute('DELETE FROM favorites WHERE user_id = ? AND anime_name = ?', (user_id, english_title))
    else:
        cursor.execute('DELETE FROM favorites WHERE user_id = ? AND anime_name = ?', (user_id, anime_name))
    conn.commit()
    conn.close()

async def remind_me(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if len(context.args) < 2:
        await update.message.reply_text("Please provide valid Name and Time. \n\nUsage: /remind <anime_name> <time_in_minutes>")
        return
    
    anime_name = context.args[0]
    try:
        remind_in = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Please provide a valid time in minutes.")
        return
    
    remind_time = (datetime.now() + timedelta(minutes=remind_in)).isoformat()
    add_reminder(user_id, anime_name, remind_time)
    await update.message.reply_text(f"Reminder set for '{anime_name}' in {remind_in} minutes.")

async def show_reminders_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    reminders = show_reminders(user_id)
    if reminders:
        reminder_list = '\n'.join([f"{anime} at {time}" for anime, time in reminders])
        await update.message.reply_text(f"Your reminders:\n{reminder_list}")
    else:
        await update.message.reply_text("You have no reminders set.")

async def remove_reminder_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /removereminder <anime_name>")
        return
    
    anime_name = context.args[0]
    remove_reminder(user_id, anime_name)
    await update.message.reply_text(f"Removed reminder for '{anime_name}'.")

async def check_reminders():
    now = datetime.now().isoformat()
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, anime_name FROM reminders WHERE remind_time <= ?', (now,))
    reminders = cursor.fetchall()
    conn.close()

    bot = Bot(token=TOKEN)

    for user_id, anime_name in reminders:
        try:
            await bot.send_message(chat_id=user_id, text=f"Reminder: It's time to watch '{anime_name}'!")
        except Exception as e:
            print(f"Error sending reminder to user {user_id}: {e}")

    # Remove reminders that have been sent
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM reminders WHERE remind_time <= ?', (now,))
    conn.commit()
    conn.close()

async def get_favorites(user_id: int) -> list:
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('SELECT anime_name FROM favorites WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows if row[0] is not None]

def fetch_anime_data(query):
    url = 'https://graphql.anilist.co'
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, json={'query': query}, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

def get_weekly_top_anime():
    query = '''
    {
      Page {
        media(sort: POPULARITY_DESC, type: ANIME, season: WINTER, seasonYear: 2024) {
          title {
            romaji
            english
          }
          id
        }
      }
    }
    '''
    data = fetch_anime_data(query)
    if data and 'data' in data and 'Page' in data['data']:
        return data['data']['Page']['media']
    return None

def get_trending_anime():
    query = '''
    {
      Page {
        media(sort: TRENDING_DESC, type: ANIME) {
          title {
            romaji
            english
          }
          id
        }
      }
    }
    '''
    data = fetch_anime_data(query)
    if data and 'data' in data and 'Page' in data['data']:
        return data['data']['Page']['media']
    return None

def get_top_anime_list():
    query = '''
    {
      Page {
        media(sort: SCORE_DESC, type: ANIME) {
          title {
            romaji
            english
          }
          id
        }
      }
    }
    '''
    data = fetch_anime_data(query)
    if data and 'data' in data and 'Page' in data['data']:
        return data['data']['Page']['media']
    return None

async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if not has_been_welcomed_today(user_id):
        await update.message.reply_text('Welcome to the Anime Reminder Bot!')
        update_welcome_status(user_id)
    else:
        await update.message.reply_text('You have already been welcomed today.')

async def help_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "Commands:\n"
        "/start - Start the bot\n"
        "/help - Get help\n"
        "/remind <anime_name> <time_in_minutes> - Set a reminder\n"
        "/showreminders - Show your reminders\n"
        "/removereminder <anime_name> - Remove a reminder\n"
        "/favorites - Show your favorite anime\n"
        "/addfavorite <anime_name> - Add an anime to your favorites\n"
        "/removefavorite <anime_name> - Remove an anime from your favorites\n"
        "/topanime - Get top anime list\n"
        "/trendinganime - Get trending anime\n"
        "/weeklytopanime - Get weekly top anime"
    )

async def add_favorite_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /addfavorite <anime_name>")
        return
    anime_name = ' '.join(context.args)
    add_favorite(user_id, anime_name)
    await update.message.reply_text(f"Added '{anime_name}' to your favorites.")

async def remove_favorite_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /removefavorite <anime_name>")
        return
    anime_name = ' '.join(context.args)
    remove_favorite(user_id, anime_name)
    await update.message.reply_text(f"Removed '{anime_name}' from your favorites.")

async def top_anime(update: Update, context: CallbackContext) -> None:
    top_anime_list = get_top_anime_list()
    if top_anime_list:
        message = "Top Anime:\n" + "\n".join([f"{anime['title']['romaji']} ({anime['title'].get('english', 'No English Title')})" for anime in top_anime_list])
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("Failed to fetch top anime list.")

async def trending_anime(update: Update, context: CallbackContext) -> None:
    trending_anime_list = get_trending_anime()
    if trending_anime_list:
        message = "Trending Anime:\n" + "\n".join([f"{anime['title']['romaji']} ({anime['title'].get('english', 'No English Title')})" for anime in trending_anime_list])
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("Failed to fetch trending anime.")

async def weekly_top_anime(update: Update, context: CallbackContext) -> None:
    weekly_top_anime_list = get_weekly_top_anime()
    if weekly_top_anime_list:
        message = "Weekly Top Anime:\n" + "\n".join([f"{anime['title']['romaji']} ({anime['title'].get('english', 'No English Title')})" for anime in weekly_top_anime_list])
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("Failed to fetch weekly top anime.")

def main():
    init_db()
    init_welcome_db()

    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("remind", remind_me))
    application.add_handler(CommandHandler("showreminders", show_reminders_command))
    application.add_handler(CommandHandler("removereminder", remove_reminder_command))
    application.add_handler(CommandHandler("favorites", lambda u, c: c.bot.send_message(chat_id=u.message.chat_id, text="Your favorites")))
    application.add_handler(CommandHandler("addfavorite", add_favorite_command))
    application.add_handler(CommandHandler("removefavorite", remove_favorite_command))
    application.add_handler(CommandHandler("topanime", top_anime))
    application.add_handler(CommandHandler("trendinganime", trending_anime))
    application.add_handler(CommandHandler("weeklytopanime", weekly_top_anime))

    scheduler = BackgroundScheduler()
    async def async_check_reminders():
        await check_reminders()
    
    scheduler.add_job(asyncio.run(check_reminders), IntervalTrigger(minutes=1))
    scheduler.start()

    application.run_polling()

if __name__ == '__main__':
    main()
