import telebot
from telebot import types
import time
import os
import sys
import subprocess
import yt_dlp
import threading
import re
import math
import hashlib
from flask import Flask, request

BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not found in environment")
    sys.exit(1)

ADMIN_ID = 8460989245
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

users_db = set()
user_states = {}
temp_links = {}
user_messages = {}

COOKIE_FILES = {
    'youtube': 'cookies_youtube.txt',
    'instagram': 'cookies_instagram.txt',
    'facebook': 'cookies_facebook.txt',
    'tiktok': 'cookies_tiktok.txt'
}

MAX_VIDEO_SIZE = 50000000
CHUNK_SIZE = 50 * 1024 * 1024

PLATFORM_NAMES = {
    'youtube': 'يوتيوب',
    'instagram': 'انستغرام',
    'facebook': 'فيسبوك',
    'tiktok': 'تيك توك'
}

def update_packages():
    try:
        print("🔄 جاري تحديث pip...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
            check=False, timeout=180,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print("🔄 جاري تحديث yt-dlp...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            check=False, timeout=180,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print("✅ تم تحديث المكتبات بنجاح")
    except Exception as e:
        print(f"⚠️ فشل تحديث المكتبات: {e}")

def cleanup_temp_files():
    try:
        os.system("rm -f /home/container/download_* /home/container/input_* /home/container/audio_* /home/container/final_* /home/container/vocals_* /home/container/*.part")
        print("✅ تم حذف الملفات المؤقتة")
    except Exception as e:
        print(f"⚠️ فشل حذف الملفات: {e}")

update_packages()
cleanup_temp_files()

def set_bot_commands():
    try:
        commands = [
            types.BotCommand("start", "🎬 ابدأ التحميل"),
            types.BotCommand("admin", "🔐 لوحة المطور"),
            types.BotCommand("cookies", "🍪 إدارة الكوكيز"),
            types.BotCommand("checkcookies", "🔍 التحقق من الكوكيز"),
            types.BotCommand("deletecookies", "🗑️ حذف الكوكيز"),
        ]
        bot.set_my_commands(commands)
    except Exception as e:
        print(f"Error: {e}")

set_bot_commands()

def get_platform_from_url(url):
    if not url:
        return None
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    elif 'instagram.com' in url or 'instagr.am' in url:
        return 'instagram'
    elif 'facebook.com' in url or 'fb.watch' in url:
        return 'facebook'
    elif 'tiktok.com' in url:
        return 'tiktok'
    return None

def extract_instagram_cookies(cookies_text):
    lines = cookies_text.split('\n')
    insta_lines = ["# Netscape HTTP Cookie File"]
    for line in lines:
        if 'instagram.com' in line and not line.startswith('#'):
            parts = line.split('\t')
            if len(parts) >= 7:
                insta_lines.append(line)
    return '\n'.join(insta_lines)

def save_cookies_from_text(platform, cookies_text):
    try:
        filename = COOKIE_FILES.get(platform)
        if not filename:
            return False
        if platform == 'instagram':
            cookies_text = extract_instagram_cookies(cookies_text)
            if len(cookies_text.split('\n')) < 3:
                return False
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(cookies_text)
        return True
    except Exception as e:
        print(f"Error saving cookies: {e}")
        return False

def save_cookies_from_file(platform, file_content):
    try:
        filename = COOKIE_FILES.get(platform)
        if not filename:
            return False
        if isinstance(file_content, bytes):
            file_content = file_content.decode('utf-8', errors='ignore')
        if platform == 'instagram':
            file_content = extract_instagram_cookies(file_content)
            if len(file_content.split('\n')) < 3:
                return False
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(file_content)
        return True
    except Exception as e:
        print(f"Error saving cookies from file: {e}")
        return False

def has_cookies(platform):
    if not platform:
        return False
    filename = COOKIE_FILES.get(platform)
    if not filename:
        return False
    return os.path.exists(filename) and os.path.getsize(filename) > 0

def delete_cookies(platform):
    try:
        filename = COOKIE_FILES.get(platform)
        if not filename:
            return False
        if os.path.exists(filename):
            os.remove(filename)
            return True
        return False
    except Exception:
        return False

def delete_all_cookies():
    count = 0
    for platform, filename in COOKIE_FILES.items():
        if os.path.exists(filename):
            try:
                os.remove(filename)
                count += 1
            except Exception:
                pass
    return count

def delete_user_messages(user_id, keep_last=None):
    if user_id not in user_messages:
        return
    messages = user_messages[user_id]
    if keep_last is not None and keep_last > 0:
        messages = messages[:-keep_last]
    for msg_id in messages:
        try:
            bot.delete_message(user_id, msg_id)
        except Exception:
            pass
    if keep_last is not None and keep_last > 0:
        user_messages[user_id] = user_messages[user_id][-keep_last:]
    else:
        user_messages[user_id] = []

def add_user_message(user_id, message_id):
    if user_id not in user_messages:
        user_messages[user_id] = []
    user_messages[user_id].append(message_id)
    if len(user_messages[user_id]) > 50:
        user_messages[user_id] = user_messages[user_id][-50:]

def generate_short_id(url):
    hash_obj = hashlib.md5(f"{url}_{time.time()}".encode())
    return hash_obj.hexdigest()[:10]

def format_time(seconds):
    if seconds < 60:
        return f"{int(seconds)} ثانية"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes} دقيقة {secs} ثانية"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours} ساعة {minutes} دقيقة"

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f} MB"
    else:
        return f"{size_bytes / (1024*1024*1024):.2f} GB"

def get_progress_bar(percent, width=20):
    filled = int(width * percent / 100)
    bar = '█' * filled + '░' * (width - filled)
    return bar

def update_download_timer(user_id, message_id, progress_data, media_type):
    seconds = 0
    last_update_time = 0
    while not progress_data.get('stop', False):
        time.sleep(0.3)
        seconds += 0.3
        if progress_data.get('stop', False):
            break
        try:
            downloaded = progress_data.get('downloaded', 0)
            total = progress_data.get('total', 1)
            speed = progress_data.get('speed', 0)
            percent = (downloaded / total) * 100 if total > 0 else 0
            bar = get_progress_bar(percent)
            if percent < 25:
                color = '🔴'
            elif percent < 50:
                color = '🟠'
            elif percent < 75:
                color = '🟡'
            else:
                color = '🟢'
            eta_text = "جاري الحساب..."
            if speed > 0 and total > downloaded:
                remaining_time = (total - downloaded) / speed
                eta_text = format_time(remaining_time)
            speed_text = format_size(speed) + "/ث" if speed > 0 else "جاري الحساب..."
            current_time = time.time()
            if current_time - last_update_time >= 0.5:
                last_update_time = current_time
                status_text = (
                    f"📥 **تحميل {media_type}**\n\n"
                    f"┌─────────────────────────────────────┐\n"
                    f"│      {color} {bar} {color}      │\n"
                    f"└─────────────────────────────────────┘\n"
                    f"          **{percent:.1f}%**\n\n"
                    f"⏱️ **المدة:** {format_time(int(seconds))}\n"
                    f"📦 **الحجم:** {format_size(downloaded)} / {format_size(total)}\n"
                    f"⚡ **السرعة:** {speed_text}\n"
                    f"⏳ **المتبقي:** {eta_text}"
                )
                try:
                    bot.edit_message_text(status_text, chat_id=user_id, message_id=message_id, parse_mode='Markdown')
                except Exception:
                    pass
        except Exception as e:
            print(f"Timer error: {e}")
            break

def split_file(file_path, chunk_size=CHUNK_SIZE):
    parts = []
    file_size = os.path.getsize(file_path)
    num_chunks = math.ceil(file_size / chunk_size)
    with open(file_path, 'rb') as f:
        for i in range(num_chunks):
            part_path = f"{file_path}.part{i+1}"
            with open(part_path, 'wb') as part_file:
                chunk = f.read(chunk_size)
                part_file.write(chunk)
            parts.append(part_path)
    return parts, num_chunks

def send_file(user_id, file_path, is_video=True):
    try:
        file_size = os.path.getsize(file_path)
        if file_size <= MAX_VIDEO_SIZE:
            with open(file_path, 'rb') as f:
                if is_video:
                    bot.send_video(user_id, f, caption="✅ تم التحميل بنجاح!", timeout=300)
                else:
                    bot.send_audio(user_id, f, caption="✅ تم التحميل بنجاح!", timeout=300)
            return True
        bot.send_message(user_id, f"📦 الملف كبير ({format_size(file_size)})، جاري التقسيم...")
        parts, num_chunks = split_file(file_path)
        info = f"📁 الملف مقسم إلى {num_chunks} أجزاء:\n\n"
        for i, part in enumerate(parts, 1):
            part_size = os.path.getsize(part)
            info += f"📎 الجزء {i}: {format_size(part_size)}\n"
        bot.send_message(user_id, info)
        for i, part in enumerate(parts, 1):
            with open(part, 'rb') as f:
                bot.send_document(user_id, f, caption=f"📎 الجزء {i} من {num_chunks}", timeout=300)
            os.remove(part)
            time.sleep(0.5)
        bot.send_message(user_id, "✅ تم إرسال جميع الأجزاء بنجاح!\n💡 لدمجها: استخدم برنامج 7-Zip أو WinRAR")
        return True
    except Exception as e:
        bot.send_message(user_id, f"❌ خطأ في الإرسال: {str(e)}")
        return False

def download_with_progress(user_id, message_id, url, is_video, media_type):
    progress_data = {'stop': False, 'downloaded': 0, 'total': 1, 'speed': 0}
    timer_thread = threading.Thread(target=update_download_timer, args=(user_id, message_id, progress_data, media_type))
    timer_thread.daemon = True
    timer_thread.start()

    def progress_hook(d):
        if d['status'] == 'downloading':
            progress_data['downloaded'] = d.get('downloaded_bytes', 0)
            progress_data['total'] = d.get('total_bytes', 1)
            progress_data['speed'] = d.get('speed', 0)
        elif d['status'] == 'finished':
            progress_data['stop'] = True
            progress_data['downloaded'] = progress_data['total']

    ydl_opts = {
        'outtmpl': f'download_{user_id}_{int(time.time())}.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
        'noplaylist': True,
        'socket_timeout': 300,
        'retries': 10,
        'progress_hooks': [progress_hook],
        'nocheckcertificate': True,
        'extractor_retries': 5,
        'file_access_retries': 5,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        },
    }

    platform = get_platform_from_url(url)
    if platform and has_cookies(platform):
        cookie_file = COOKIE_FILES.get(platform)
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

    if platform == 'youtube':
        ydl_opts['extractor_args'] = {'youtube': {'player_client': ['android', 'web']}}
    elif platform == 'tiktok':
        ydl_opts['extractor_args'] = {'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}}

    ydl_opts['format'] = 'best[ext=mp4]/best' if is_video else 'bestaudio/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                progress_data['stop'] = True
                raise Exception("فشل استخراج معلومات الفيديو.")
            filename = ydl.prepare_filename(info)
            if not filename:
                progress_data['stop'] = True
                raise Exception("فشل تحديد اسم الملف.")
            if not is_video:
                base_name = os.path.splitext(filename)[0]
                for ext in ['.mp3', '.m4a', '.webm', '.opus', '.ogg']:
                    if os.path.exists(f"{base_name}{ext}"):
                        filename = f"{base_name}{ext}"
                        break
            progress_data['stop'] = True
            timer_thread.join(timeout=2)
            return filename
    except Exception as e:
        progress_data['stop'] = True
        timer_thread.join(timeout=2)
        raise e

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    users_db.add(user_id)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("▶️ يوتيوب", callback_data="platform_youtube"),
        types.InlineKeyboardButton("📸 انستغرام", callback_data="platform_instagram"),
        types.InlineKeyboardButton("📘 فيسبوك", callback_data="platform_facebook"),
        types.InlineKeyboardButton("🎵 تيك توك", callback_data="platform_tiktok")
    )
    msg = bot.send_message(user_id, "✨ **مرحباً بك!**\n\n👇 اختر المنصة:", parse_mode='Markdown', reply_markup=markup)
    add_user_message(user_id, msg.message_id)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "❌ هذا الأمر للمطور فقط")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
        types.InlineKeyboardButton("📢 الإذاعة", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🍪 إدارة الكوكيز", callback_data="admin_cookies"),
        types.InlineKeyboardButton("🗑️ حذف الكوكيز", callback_data="admin_delete"),
        types.InlineKeyboardButton("ℹ️ معلومات", callback_data="admin_info"),
        types.InlineKeyboardButton("🔄 إعادة تشغيل", callback_data="admin_restart")
    )
    msg = bot.send_message(ADMIN_ID, "🔐 **لوحة تحكم المطور**", reply_markup=markup)
    add_user_message(ADMIN_ID, msg.message_id)

@bot.message_handler(commands=['cookies'])
def manage_cookies(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "❌ هذا الأمر للمطور فقط")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("▶️ يوتيوب", callback_data="cookies_youtube"),
        types.InlineKeyboardButton("📸 انستغرام", callback_data="cookies_instagram"),
        types.InlineKeyboardButton("📘 فيسبوك", callback_data="cookies_facebook"),
        types.InlineKeyboardButton("🎵 تيك توك", callback_data="cookies_tiktok"),
        types.InlineKeyboardButton("🔍 عرض الكل", callback_data="cookies_check_all")
    )
    msg = bot.send_message(ADMIN_ID, "🍪 **إدارة الكوكيز:**", reply_markup=markup)
    add_user_message(ADMIN_ID, msg.message_id)

@bot.message_handler(commands=['deletecookies'])
def delete_cookies_menu(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "❌ هذا الأمر للمطور فقط")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🗑️ يوتيوب", callback_data="delete_youtube"),
        types.InlineKeyboardButton("🗑️ انستغرام", callback_data="delete_instagram"),
        types.InlineKeyboardButton("🗑️ فيسبوك", callback_data="delete_facebook"),
        types.InlineKeyboardButton("🗑️ تيك توك", callback_data="delete_tiktok"),
        types.InlineKeyboardButton("🗑️🗑️ حذف الكل", callback_data="delete_all")
    )
    msg = bot.send_message(ADMIN_ID, "🗑️ **اختر المنصة:**", reply_markup=markup)
    add_user_message(ADMIN_ID, msg.message_id)

@bot.message_handler(commands=['checkcookies'])
def check_all_cookies(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "❌ هذا الأمر للمطور فقط")
        return
    status_text = "🍪 **حالة الكوكيز:**\n\n"
    for platform, filename in COOKIE_FILES.items():
        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            status_text += f"✅ {platform.capitalize()}: {format_size(os.path.getsize(filename))}\n"
        else:
            status_text += f"❌ {platform.capitalize()}: غير موجودة\n"
    msg = bot.send_message(ADMIN_ID, status_text)
    add_user_message(ADMIN_ID, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_"))
def handle_platform(call):
    user_id = call.message.chat.id
    platform = call.data.replace("platform_", "")
    try:
        bot.delete_message(user_id, call.message.message_id)
    except Exception:
        pass
    delete_user_messages(user_id)
    msg = bot.send_message(user_id, f"📥 أرسل رابط {PLATFORM_NAMES.get(platform, platform)}:")
    add_user_message(user_id, msg.message_id)
    user_states[user_id] = f"waiting_link_{platform}"

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_messages(message):
    user_id = message.chat.id
    text = message.text
    if text.startswith('/'):
        return
    if user_states.get(user_id) == "waiting_for_broadcast":
        if user_id != ADMIN_ID:
            user_states[user_id] = None
            return
        user_states[user_id] = None
        count = 0
        for u_id in users_db:
            try:
                bot.send_message(u_id, text)
                count += 1
                time.sleep(0.1)
            except Exception:
                pass
        msg = bot.send_message(ADMIN_ID, f"✅ تم الإرسال إلى {count} مستخدم")
        add_user_message(ADMIN_ID, msg.message_id)
        return
    for platform in ['youtube', 'instagram', 'facebook', 'tiktok']:
        if user_states.get(user_id) == f"waiting_cookies_{platform}":
            if user_id != ADMIN_ID:
                user_states[user_id] = None
                return
            user_states[user_id] = None
            if save_cookies_from_text(platform, text):
                msg = bot.send_message(user_id, f"✅ تم حفظ كوكيز {platform.capitalize()}!")
                add_user_message(user_id, msg.message_id)
            else:
                msg = bot.send_message(user_id, "❌ خطأ في الحفظ")
                add_user_message(user_id, msg.message_id)
            return
    for platform in ['youtube', 'instagram', 'facebook', 'tiktok']:
        if user_states.get(user_id) == f"waiting_link_{platform}":
            user_states[user_id] = None
            url_match = re.search(r'https?://[^\s]+', text)
            if url_match:
                url = url_match.group()
                short_id = generate_short_id(url)
                temp_links[short_id] = url
                try:
                    bot.delete_message(user_id, message.message_id)
                except Exception:
                    pass
                delete_user_messages(user_id)
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("🎬 فيديو", callback_data=f"vid_{short_id}"),
                    types.InlineKeyboardButton("🎵 صوت", callback_data=f"aud_{short_id}")
                )
                msg = bot.send_message(user_id, "🎯 اختر النوع:", reply_markup=markup)
                add_user_message(user_id, msg.message_id)
            else:
                msg = bot.send_message(user_id, "⚠️ أرسل رابطاً صحيحاً")
                add_user_message(user_id, msg.message_id)
            return
    url_match = re.search(r'https?://[^\s]+', text)
    if url_match:
        url = url_match.group()
        short_id = generate_short_id(url)
        temp_links[short_id] = url
        try:
            bot.delete_message(user_id, message.message_id)
        except Exception:
            pass
        delete_user_messages(user_id)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🎬 فيديو", callback_data=f"vid_{short_id}"),
            types.InlineKeyboardButton("🎵 صوت", callback_data=f"aud_{short_id}")
        )
        msg = bot.send_message(user_id, "🎯 اختر النوع:", reply_markup=markup)
        add_user_message(user_id, msg.message_id)
    else:
        msg = bot.send_message(user_id, "⚠️ أرسل رابطاً صحيحاً")
        add_user_message(user_id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_") or call.data.startswith("aud_"))
def handle_download(call):
    user_id = call.message.chat.id
    data = call.data
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    is_video = data.startswith("vid_")
    short_id = data.replace("vid_", "") if is_video else data.replace("aud_", "")
    url = temp_links.get(short_id)
    if not url:
        msg = bot.send_message(user_id, "❌ انتهت صلاحية الرابط")
        add_user_message(user_id, msg.message_id)
        return
    if short_id in temp_links:
        del temp_links[short_id]
    media_type = "فيديو" if is_video else "صوت"
    try:
        bot.delete_message(user_id, call.message.message_id)
    except Exception:
        pass
    delete_user_messages(user_id)
    msg = bot.send_message(user_id, f"⏳ جاري تحميل {media_type}...")
    add_user_message(user_id, msg.message_id)
    timer_message_id = msg.message_id
    filename = None
    try:
        filename = download_with_progress(user_id, msg.message_id, url, is_video, media_type)
        if filename and os.path.exists(filename):
            try:
                bot.delete_message(user_id, timer_message_id)
            except Exception:
                pass
            if user_id in user_messages and timer_message_id in user_messages[user_id]:
                user_messages[user_id].remove(timer_message_id)
            send_file(user_id, filename, is_video)
            delete_user_messages(user_id)
        else:
            msg = bot.send_message(user_id, "❌ لم يتم العثور على الملف")
            add_user_message(user_id, msg.message_id)
    except Exception as e:
        error_msg = str(e)
        if "cookies" in error_msg.lower() or "authentication" in error_msg.lower() or "unreachable" in error_msg.lower():
            error_msg = f"❌ **هذا المحتوى يتطلب مصادقة**\n\n💡 استخدم /cookies لإضافتها"
        elif "not found" in error_msg.lower():
            error_msg = "❌ الرابط غير صحيح"
        else:
            error_msg = f"❌ خطأ: {error_msg[:150]}"
        try:
            bot.edit_message_text(error_msg, user_id, msg.message_id, parse_mode='Markdown')
        except Exception:
            msg = bot.send_message(user_id, error_msg)
            add_user_message(user_id, msg.message_id)
    finally:
        try:
            if filename and os.path.exists(filename):
                os.remove(filename)
                print(f"🗑️ تم حذف الملف المؤقت: {filename}")
        except Exception as e:
            print(f"⚠️ فشل حذف الملف: {e}")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    user_id = message.chat.id
    is_cookie_waiting = False
    platform = None
    for p in ['youtube', 'instagram', 'facebook', 'tiktok']:
        if user_states.get(user_id) == f"waiting_cookies_{p}":
            is_cookie_waiting = True
            platform = p
            break
    if is_cookie_waiting and user_id == ADMIN_ID:
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            file_content = downloaded_file.decode('utf-8', errors='ignore')
            if save_cookies_from_file(platform, file_content):
                msg = bot.send_message(user_id, f"✅ تم حفظ كوكيز {platform.capitalize()}!")
                add_user_message(user_id, msg.message_id)
                user_states[user_id] = None
            else:
                msg = bot.send_message(user_id, "❌ ملف غير صالح")
                add_user_message(user_id, msg.message_id)
        except Exception as e:
            msg = bot.send_message(user_id, f"❌ خطأ: {str(e)}")
            add_user_message(user_id, msg.message_id)
        return
    if user_states.get(user_id) == "waiting_for_broadcast" and user_id == ADMIN_ID:
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            count = 0
            for u_id in users_db:
                try:
                    bot.send_document(u_id, downloaded_file, caption=message.caption)
                    count += 1
                    time.sleep(0.1)
                except Exception:
                    pass
            user_states[user_id] = None
            bot.send_message(ADMIN_ID, f"✅ تم الإرسال إلى {count} مستخدم")
        except Exception as e:
            bot.send_message(ADMIN_ID, f"❌ خطأ: {str(e)}")
        return

@bot.message_handler(content_types=['photo', 'video', 'audio', 'voice', 'animation'])
def handle_broadcast_media(message):
    user_id = message.chat.id
    if user_states.get(user_id) != "waiting_for_broadcast" or user_id != ADMIN_ID:
        return
    count = 0
    for u_id in users_db:
        try:
            if message.photo:
                bot.send_photo(u_id, message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                bot.send_video(u_id, message.video.file_id, caption=message.caption)
            elif message.audio:
                bot.send_audio(u_id, message.audio.file_id, caption=message.caption)
            elif message.voice:
                bot.send_voice(u_id, message.voice.file_id)
            elif message.animation:
                bot.send_animation(u_id, message.animation.file_id, caption=message.caption)
            count += 1
            time.sleep(0.1)
        except Exception:
            pass
    user_states[user_id] = None
    bot.send_message(ADMIN_ID, f"✅ تم الإرسال إلى {count} مستخدم")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_") or call.data.startswith("cookies_") or call.data.startswith("delete_") or call.data.startswith("replace_") or call.data.startswith("keep_"))
def handle_admin_buttons(call):
    user_id = call.message.chat.id
    data = call.data
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    if user_id != ADMIN_ID:
        return
    if data.startswith("delete_"):
        if data == "delete_all":
            count = delete_all_cookies()
            msg = bot.send_message(user_id, f"🗑️ تم حذف {count} ملفات")
            add_user_message(user_id, msg.message_id)
            return
        platform = data.replace("delete_", "")
        if delete_cookies(platform):
            msg = bot.send_message(user_id, f"🗑️ تم حذف كوكيز {platform.capitalize()}")
            add_user_message(user_id, msg.message_id)
        else:
            msg = bot.send_message(user_id, f"ℹ️ لا توجد كوكيز")
            add_user_message(user_id, msg.message_id)
        return
    if data.startswith("cookies_"):
        platform = data.replace("cookies_", "")
        if platform == "check_all":
            status_text = "🍪 **حالة الكوكيز:**\n\n"
            for p, filename in COOKIE_FILES.items():
                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    status_text += f"✅ {p.capitalize()}: {format_size(os.path.getsize(filename))}\n"
                else:
                    status_text += f"❌ {p.capitalize()}: غير موجودة\n"
            msg = bot.send_message(user_id, status_text)
            add_user_message(user_id, msg.message_id)
            return
        if has_cookies(platform):
            size = os.path.getsize(COOKIE_FILES[platform])
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("🔄 استبدال", callback_data=f"replace_{platform}"),
                types.InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_{platform}")
            )
            msg = bot.send_message(user_id, f"🍪 **كوكيز {platform.capitalize()}**\n📦 {format_size(size)}", reply_markup=markup)
            add_user_message(user_id, msg.message_id)
            return
        msg = bot.send_message(user_id, f"📝 أرسل ملف الكوكيز لـ {platform.capitalize()}:")
        add_user_message(user_id, msg.message_id)
        user_states[user_id] = f"waiting_cookies_{platform}"
        return
    if data.startswith("replace_"):
        platform = data.replace("replace_", "")
        msg = bot.send_message(user_id, f"📝 أرسل ملف الكوكيز الجديد لـ {platform.capitalize()}:")
        add_user_message(user_id, msg.message_id)
        user_states[user_id] = f"waiting_cookies_{platform}"
        return
    if data == "admin_stats":
        msg = bot.send_message(ADMIN_ID, f"📊 المشتركين: {len(users_db)}")
        add_user_message(ADMIN_ID, msg.message_id)
    elif data == "admin_broadcast":
        msg = bot.send_message(ADMIN_ID, "✍️ أرسل المحتوى للإذاعة:")
        add_user_message(ADMIN_ID, msg.message_id)
        user_states[ADMIN_ID] = "waiting_for_broadcast"
    elif data == "admin_cookies":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("▶️ يوتيوب", callback_data="cookies_youtube"),
            types.InlineKeyboardButton("📸 انستغرام", callback_data="cookies_instagram"),
            types.InlineKeyboardButton("📘 فيسبوك", callback_data="cookies_facebook"),
            types.InlineKeyboardButton("🎵 تيك توك", callback_data="cookies_tiktok"),
            types.InlineKeyboardButton("🔍 عرض الكل", callback_data="cookies_check_all")
        )
        msg = bot.send_message(ADMIN_ID, "🍪 **إدارة الكوكيز:**", reply_markup=markup)
        add_user_message(ADMIN_ID, msg.message_id)
    elif data == "admin_delete":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🗑️ يوتيوب", callback_data="delete_youtube"),
            types.InlineKeyboardButton("🗑️ انستغرام", callback_data="delete_instagram"),
            types.InlineKeyboardButton("🗑️ فيسبوك", callback_data="delete_facebook"),
            types.InlineKeyboardButton("🗑️ تيك توك", callback_data="delete_tiktok"),
            types.InlineKeyboardButton("🗑️🗑️ حذف الكل", callback_data="delete_all")
        )
        msg = bot.send_message(ADMIN_ID, "🗑️ **اختر المنصة:**", reply_markup=markup)
        add_user_message(ADMIN_ID, msg.message_id)
    elif data == "admin_info":
        msg = bot.send_message(ADMIN_ID, "🧑‍💻 بوت تحميل الفيديو\n🛠️ المطور: أحمد")
        add_user_message(ADMIN_ID, msg.message_id)
    elif data == "admin_restart":
        msg = bot.send_message(ADMIN_ID, "🔄 جاري إعادة التشغيل...")
        add_user_message(ADMIN_ID, msg.message_id)
        time.sleep(2)
        try:
            os.execv(sys.executable, ['python'] + sys.argv)
        except Exception:
            os._exit(0)

def cleanup_temp_links():
    while True:
        time.sleep(3600)
        try:
            temp_links.clear()
        except Exception:
            pass

cleanup_thread = threading.Thread(target=cleanup_temp_links, daemon=True)
cleanup_thread.start()

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    bot.remove_webhook()
    RENDER_URL = "https://video-downloader-bot.onrender.com"
    bot.set_webhook(url=f"{RENDER_URL}/{BOT_TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))