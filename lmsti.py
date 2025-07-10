import json
import logging
import sqlite3
import requests
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters
)

TOKEN = '' # Insert your bot token inside quotes
ENDPOINT = 'http://127.0.0.1:9090/v1/chat/completions'
DATABASE = 'userdata.db'
MODELS = [
    # Add available models
    "gemma-3-27b-it-Q6_K.gguf",
]

logging.basicConfig(
    filename='journal.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            model INTEGER NOT NULL DEFAULT 0            
        )
    ''')
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR IGNORE INTO users(user_id) VALUES(?)',
        (user_id,)
    )
    conn.commit()
    conn.close()

def create_table(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS u{user_id} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            output TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_entry(user_id, message, output):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(f'''
        INSERT INTO u{user_id} (message, output)
        VALUES (?, ?)
    ''', (message, output))
    conn.commit()
    conn.close()

def get_history(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(f'SELECT message, output FROM u{user_id}')
    history = cursor.fetchall()
    conn.close()
    return history

def get_model(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT model FROM users WHERE user_id = ?',
        (user_id)
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return 0

    idx = row[0]
    if idx < 0 or idx >= len(MODELS):
        return 0

    return idx

def set_model(user_id, idx):
    if idx < 0 or idx >= len(MODELS):
        return False

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE users SET model = ? WHERE user_id = ?',
        (idx, user_id)
    )
    
    conn.commit()
    conn.close()
    return True

def purge_data(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(f'DROP TABLE IF EXISTS u{user_id}')
    conn.commit()
    conn.close()

async def start(update, context):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"LM Studio Telegram Interface 0.4\n"
            f"Number of available models: {len(MODELS)}."
        )
    )

async def purge(update, context):
    user_id = update.effective_user.id
    purge_data(user_id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Success."
    )

async def cmd_set(update, context):
    user_id = update.effective_user.id

    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Usage: /set <index 1 to {len(MODELS)}>."
        )
        return

    try:
        idx = int(context.args[0])
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Index must be a number."
        )
        return

    add_user(user_id)
    update_model = set_model(user_id, idx - 1)

    if update_model:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Set to {MODELS[idx - 1]}."
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No such model."
        )

async def interact(update, context):
    user_id = update.effective_user.id
    add_user(user_id)
    create_table(user_id)
    message = update.message.text
    chat = update.effective_chat.id
    
    userdata = get_history(user_id)
    model = get_model(user_id)
    history = []

    for msg, out in userdata:
        history.append({'role': 'user', 'content': msg})
        history.append({'role': 'assistant', 'content': out})
    
    payload = {
        "model": MODELS[model],
        "messages": [
            { "role": "system", "content": history },
            { "role": "user", "content": message }
        ],
        "temperature": 0.3,
        "max_tokens": 512,
        "stream": False
    }

    try:
        response = requests.post(
            ENDPOINT,
            headers={"Content-Type": "application/json"},
            json=payload
        )

        response.raise_for_status()
        data = response.json()

        output = (
            data['choices'][0]['message']['content'].strip()
            if 'content' in data['choices'][0]['message']
            else "Model produced no output."
        )

        add_entry(user_id, message, output)

        await context.bot.send_message(
            chat_id=chat,
            text=output
        )
    except requests.exceptions.RequestException as e:
        logging.error(e)
        await context.bot.send_message(
            chat_id=chat,
            text="Could not reach LM Studio."
        )
    except json.JSONDecodeError:
        logging.error("Check LMS JSON formats.")
        await context.bot.send_message(
            chat_id=chat,
            text="Model produced invalid output."
        )
    except Exception as e:
        logging.error(e)
        await context.bot.send_message(
            chat_id=chat,
            text="Unknown exception (see logs)."
        )

def main():
    init_db()
    app = (
        Application.builder()
        .token(TOKEN)
        .concurrent_updates(True)
        .read_timeout(15)
        .write_timeout(15)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("purge", purge))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            interact
        )
    )    
    app.run_polling()    

if __name__ == '__main__':
    main()
