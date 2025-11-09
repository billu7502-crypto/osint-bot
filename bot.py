import os
import sqlite3
import random
import string
import requests
from datetime import datetime
from telebot import TeleBot, types

# ============================
# CONFIG — REPLACE THESE 2 ONLY
# ============================
BOT_TOKEN = "8282247701:AAHMYoquP4oFJg_D6D68I3BCMrlrIVke8xw"
VPLINK_API_KEY = "bc7622086045fb1a6029b2c2df6f87deee61b71e"

BOT_USERNAME = "Osintinfopatcher_bot"   # without @
ADMIN_CHANNEL = -1003174018278

CREDITS_PER_AD = 3
CREDITS_PER_REF = 1
COST_PER_SERVICE = 3

DB_PATH = "bot.db"

bot = TeleBot(BOT_TOKEN, parse_mode="HTML")


# ============================
# DATABASE SETUP
# ============================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS users(
 user_id INTEGER PRIMARY KEY,
 credits INTEGER DEFAULT 0,
 joined_verified INTEGER DEFAULT 0,
 referred_by INTEGER,
 referred_rewarded INTEGER DEFAULT 0,
 created_at TEXT
);

CREATE TABLE IF NOT EXISTS channels(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 chat_id INTEGER,
 title TEXT,
 invite_link TEXT
);

CREATE TABLE IF NOT EXISTS codes(
 code TEXT PRIMARY KEY,
 created_by INTEGER,
 used_by INTEGER,
 created_at TEXT,
 used_at TEXT
);
""")
conn.commit()


# ============================
# HELPERS
# ============================
def get_user(uid):
    row = cur.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        cur.execute("INSERT INTO users(user_id,created_at) VALUES(?,?)",
                    (uid, datetime.utcnow().isoformat()))
        conn.commit()
        row = cur.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    return row


def gen_code():
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))


def check_channels(uid):
    missing = []
    rows = cur.execute("SELECT * FROM channels").fetchall()

    for ch in rows:
        try:
            member = bot.get_chat_member(ch["chat_id"], uid)
            if member.status not in ("member", "administrator", "creator"):
                missing.append(ch["title"])
        except:
            missing.append(ch["title"])

    return (len(missing) == 0, missing)


def main_menu(chat_id, uid):
    user = get_user(uid)
    balance = user["credits"]

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("1) Number → Info ☠️", callback_data="svc_number"))
    kb.add(types.InlineKeyboardButton("2) Vehicle Details", callback_data="svc_vehicle"))
    kb.add(types.InlineKeyboardButton(f"💳 Credits: {balance}", callback_data="x"))
    kb.add(types.InlineKeyboardButton("🎬 Get 3 Credits (Watch Ad)", callback_data="get_credits"))
    kb.add(types.InlineKeyboardButton("👥 Refer & Earn (+1)", callback_data="ref_link"))

    bot.send_message(chat_id, "<b>Main Menu</b>", reply_markup=kb)


# ============================
# START COMMAND
# ============================
@bot.message_handler(commands=["start"])
def start(message):
    uid = message.from_user.id
    get_user(uid)

    payload = message.text.split(" ", 1)
    payload = payload[1] if len(payload) > 1 else ""

    # Redeem ad code
    if payload.startswith("ad_"):
        code = payload[3:]

        row = cur.execute("SELECT * FROM codes WHERE code=?", (code,)).fetchone()
        if not row:
            return bot.reply_to(message, "❌ Invalid or expired code.")

        if row["used_by"]:
            return bot.reply_to(message, "❌ Code already used.")

        # Redeem credits
        cur.execute("UPDATE codes SET used_by=?, used_at=? WHERE code=?",
                    (uid, datetime.utcnow().isoformat(), code))
        cur.execute("UPDATE users SET credits=credits+? WHERE user_id=?",
                    (CREDITS_PER_AD, uid))
        conn.commit()

        bot.reply_to(message, f"✅ +{CREDITS_PER_AD} Credits Added.")
        return show_gate(message)

    # Referral link
    if payload.startswith("ref_"):
        ref_id = int(payload[4:])
        if ref_id != uid:
            row = cur.execute("SELECT referred_by FROM users WHERE user_id=?", (uid,)).fetchone()
            if row and row[0] is None:
                cur.execute("UPDATE users SET referred_by=? WHERE user_id=?", (ref_id, uid))
                conn.commit()

    show_gate(message)


# ============================
# CHANNEL GATE
# ============================
def show_gate(message):
    uid = message.from_user.id
    ok, missing = check_channels(uid)

    if ok:
        main_menu(message.chat.id, uid)
        return

    kb = types.InlineKeyboardMarkup()
    rows = cur.execute("SELECT * FROM channels").fetchall()

    for ch in rows:
        kb.add(types.InlineKeyboardButton(f"Join {ch['title']}", url=ch["invite_link"]))

    kb.add(types.InlineKeyboardButton("✅ I Joined All", callback_data="verify_join"))

    bot.send_message(message.chat.id,
                     "<b>Join all required channels to unlock the bot.</b>",
                     reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "verify_join")
def verify_join(call):
    uid = call.from_user.id
    ok, _ = check_channels(uid)

    if not ok:
        bot.answer_callback_query(call.id, "❌ Join all channels first")
        return

    # Referral reward
    row = cur.execute("SELECT referred_by, referred_rewarded FROM users WHERE user_id=?", (uid,)).fetchone()
    if row and row[0] and row[1] == 0:
        cur.execute("UPDATE users SET credits=credits+?, referred_rewarded=1 WHERE user_id=?",
                    (CREDITS_PER_REF, row[0]))
        conn.commit()

    main_menu(call.message.chat.id, uid)


# ============================
# EARNING — VP LINK METHOD
# ============================
@bot.callback_query_handler(func=lambda c: c.data == "get_credits")
def get_credits(call):
    uid = call.from_user.id

    code = gen_code()
    cur.execute("INSERT INTO codes(code, created_by, created_at) VALUES(?,?,?)",
                (code, uid, datetime.utcnow().isoformat()))
    conn.commit()

    final = f"https://t.me/{BOT_USERNAME}?start=ad_{code}"

    # Call VPLink API
    api_url = f"https://vplink.in/api?api={VPLINK_API_KEY}&url={final}"
    try:
        r = requests.get(api_url).json()
        if r.get("status") == "success":
            short = r.get("shortenedUrl")
        else:
            short = final
    except:
        short = final

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎬 Watch Ad", url=short))

    bot.send_message(call.message.chat.id,
                     "Click below to watch ads. After completion you will return automatically.",
                     reply_markup=kb)


# ============================
# REFERRAL LINK
# ============================
@bot.callback_query_handler(func=lambda c: c.data == "ref_link")
def ref_link(call):
    uid = call.from_user.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    bot.send_message(call.message.chat.id,
                     f"<b>Your referral link:</b>\n<code>{link}</code>\nEarn +1 credit per unlock!")


# ============================
# SERVICE HANDLERS
# ============================
@bot.callback_query_handler(func=lambda c: c.data == "svc_number")
def svc_number(call):
    uid = call.from_user.id
    row = get_user(uid)

    if row["credits"] < COST_PER_SERVICE:
        return bot.send_message(call.message.chat.id,
                                "❌ Not enough credits.")

    cur.execute("UPDATE users SET credits=credits-? WHERE user_id=?",
                (COST_PER_SERVICE, uid))
    conn.commit()

    bot.send_message(call.message.chat.id,
                     "Enter the number with country code:")

    bot.register_next_step_handler(call.message, recv_number)


def recv_number(message):
    uid = message.from_user.id
    target = message.text

    bot.send_message(message.chat.id, "✅ You will receive result in 15 minutes.")

    txt = f"""
📩 <b>New Number Info Request</b>

<b>User ID:</b> {uid}
<b>Username:</b> @{message.from_user.username}
<b>Target Number:</b> {target}
<b>Time:</b> {datetime.utcnow()}
"""
    bot.send_message(ADMIN_CHANNEL, txt)


@bot.callback_query_handler(func=lambda c: c.data == "svc_vehicle")
def svc_vehicle(call):
    uid = call.from_user.id
    row = get_user(uid)

    if row["credits"] < COST_PER_SERVICE:
        return bot.send_message(call.message.chat.id,
                                "❌ Not enough credits.")

    cur.execute("UPDATE users SET credits=credits-? WHERE user_id=?",
                (COST_PER_SERVICE, uid))
    conn.commit()

    bot.send_message(call.message.chat.id, "Enter the vehicle number:")

    bot.register_next_step_handler(call.message, recv_vehicle)


def recv_vehicle(message):
    uid = message.from_user.id
    target = message.text

    bot.send_message(message.chat.id, "✅ You will receive result in 15 minutes.")

    txt = f"""
📩 <b>New Vehicle Info Request</b>

<b>User ID:</b> {uid}
<b>Username:</b> @{message.from_user.username}
<b>Vehicle Number:</b> {target}
<b>Time:</b> {datetime.utcnow()}
"""
    bot.send_message(ADMIN_CHANNEL, txt)


# ============================
# RUN BOT
# ============================
print("Bot starting…")
bot.infinity_polling(skip_pending=True)
