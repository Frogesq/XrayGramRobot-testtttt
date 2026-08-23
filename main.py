import asyncio
import logging
import os
import json
import time
import random
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    BusinessConnection, BusinessMessagesDeleted,
    BufferedInputFile, FSInputFile
)
from database import Database

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env")

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    raise ValueError("ADMIN_ID должен быть числом")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
INSTRUCTION_IMAGE_PATH = os.path.join(BASE_DIR, "instruction.jpg")
CHANNEL_USERNAME = "@NovoeTelegram"

PREMIUM_EMOJI = {
    "✅": "5206607081334906820",
    "❌": "5210952531676504517",
    "⚠️": "5447644880824181073",
    "🔇": "5388632425314140043",
    "🔊": "5388632425314140043",
    "💬": "5443038326535759644",
    "📖": "5460795800101594035",
    "❓": "5436113877181941026",
    "📄": "5877485980901971030",
    "✏️": "5925001822572908226",
    "🗑️": "6007942490076745785",
    "📢": "5424818078833715060",
    "⬅️": "5877536313623711363",
    "⛔": "5354435465021373780",
    "🔗": "5271604874419647061",
    "📋": "5334544901428229844",
    "⚙️": "5341715473882955310",
    "👋": "5217508498606147980",
    "🤖": "5372981976804366741",
    "1️⃣": "5382322671679708881",
    "2️⃣": "5381990043642502553",
    "3️⃣": "5381879959335738545",
    "4️⃣": "5382054253403577563",
}

def premium(text: str) -> str:
    for emoji, emoji_id in PREMIUM_EMOJI.items():
        if emoji in text:
            text = text.replace(emoji, f'<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji>')
    return text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

if os.path.exists(INSTRUCTION_IMAGE_PATH):
    logger.info("✅ Картинка инструкции найдена")
else:
    logger.warning("❌ Картинка инструкции НЕ найдена")

class BroadcastStates(StatesGroup):
    waiting_for_content = State()

# ==================== АНИМАЦИЯ ====================
async def animate_text(chat_id: int, text: str, message: types.Message, delay: float = 0.3):
    msg = await message.answer("<i>⏳ Анимация запущена...</i>", parse_mode="HTML")
    current_text = ""
    last_text = ""
    for char in text:
        current_text += char
        if current_text != last_text:
            try:
                await msg.edit_text(f"<b>{current_text}</b>", parse_mode="HTML")
                last_text = current_text
            except:
                pass
        await asyncio.sleep(delay)
    await asyncio.sleep(0.5)
    if current_text != last_text:
        try:
            await msg.edit_text(f"<b>{current_text}</b>", parse_mode="HTML")
        except:
            pass

# ==================== КЛАВИАТУРЫ ====================
def main_menu_keyboard(is_admin: bool = False):
    kb = [
        [InlineKeyboardButton(text="🔗 Подключить бота", callback_data="show_instruction", style="primary")],
        [InlineKeyboardButton(text="📋 Команды", callback_data="show_commands", style="success")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def subscription_keyboard(action: str = None):
    callback_data = "check_subscription"
    if action:
        callback_data += f"|{action}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/NovoeTelegram")],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data=callback_data, style="success")]
        ]
    )

def instruction_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main", style="danger")]]
    )

def admin_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast", style="primary")],
            [InlineKeyboardButton(text="📄 Список пользователей (txt)", callback_data="users_txt", style="primary")],
            [InlineKeyboardButton(text="🔗 Активные подключения", callback_data="active_connections", style="primary")],
            [InlineKeyboardButton(text="🗑️ Очистить старые (30 дней)", callback_data="cleanup_old", style="danger")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main", style="danger")]
        ]
    )

def cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast", style="danger")]]
    )

def back_to_admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="back_to_admin", style="primary")]]
    )

def commands_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main", style="danger")]]
    )

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
async def is_subscribed(user_id: int) -> bool:
    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        member = await bot.get_chat_member(chat.id, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return True

def get_user_download_dir(user_id: int) -> str:
    user_dir = os.path.join(DOWNLOADS_DIR, f"user_{user_id}")
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def get_ttl_seconds(message: types.Message) -> int:
    """
    Извлекает ttl_seconds из любого медиа-объекта.
    Использует прямой доступ к полям и fallback через content_type.
    """
    # Прямые поля
    for obj in [message.photo, message.video, message.voice, message.video_note,
                message.document, message.audio, message.animation]:
        if obj:
            ttl = getattr(obj, 'ttl_seconds', 0)
            if ttl:
                return ttl
    # Если не нашли, пробуем через content_type (для бизнес-сообщений)
    if message.content_type:
        # Получаем объект медиа по типу
        media_obj = None
        if message.content_type == 'photo':
            media_obj = message.photo[-1] if message.photo else None
        elif message.content_type == 'video':
            media_obj = message.video
        elif message.content_type == 'voice':
            media_obj = message.voice
        elif message.content_type == 'video_note':
            media_obj = message.video_note
        elif message.content_type == 'document':
            media_obj = message.document
        elif message.content_type == 'audio':
            media_obj = message.audio
        elif message.content_type == 'animation':
            media_obj = message.animation
        if media_obj:
            return getattr(media_obj, 'ttl_seconds', 0)
    return 0

def get_media_type(message: types.Message) -> str:
    """Определяет тип медиа (сначала прямые поля, затем content_type)"""
    if message.photo: return "photo"
    if message.video: return "video"
    if message.voice: return "voice"
    if message.video_note: return "video_note"
    if message.document: return "document"
    if message.audio: return "audio"
    if message.animation: return "animation"
    if message.sticker: return "sticker"
    # fallback на content_type
    if message.content_type:
        return message.content_type
    return None

def has_any_media(message: types.Message) -> bool:
    return bool(get_media_type(message))

async def download_media_files(message: types.Message, user_id: int) -> list:
    """
    Скачивает все медиа из сообщения.
    Использует прямые поля и fallback через content_type.
    """
    file_paths = []
    user_dir = get_user_download_dir(user_id)

    # Сначала пробуем прямые поля
    media_items = []
    if message.photo:
        photo = message.photo[-1]
        media_items.append(("photo", photo.file_id, f"photo_{message.message_id}.jpg"))
    if message.video:
        v = message.video
        media_items.append(("video", v.file_id, f"video_{message.message_id}.mp4"))
    if message.voice:
        v = message.voice
        media_items.append(("voice", v.file_id, f"voice_{message.message_id}.ogg"))
    if message.video_note:
        v = message.video_note
        media_items.append(("video_note", v.file_id, f"video_note_{message.message_id}.mp4"))
    if message.document:
        d = message.document
        name = d.file_name or f"document_{message.message_id}.bin"
        media_items.append(("document", d.file_id, name))
    if message.audio:
        a = message.audio
        ext = "m4a" if a.file_name and a.file_name.endswith('.m4a') else "mp3"
        media_items.append(("audio", a.file_id, f"audio_{message.message_id}.{ext}"))
    if message.animation:
        a = message.animation
        media_items.append(("animation", a.file_id, f"animation_{message.message_id}.mp4"))
    if message.sticker:
        s = message.sticker
        ext = "tgs" if s.is_animated else "webm" if s.is_video else "webp"
        media_items.append(("sticker", s.file_id, f"sticker_{message.message_id}.{ext}"))

    # Если прямые поля не дали результата, пытаемся через content_type
    if not media_items and message.content_type:
        content_type = message.content_type
        if content_type == 'photo' and message.photo:
            photo = message.photo[-1]
            media_items.append(("photo", photo.file_id, f"photo_{message.message_id}.jpg"))
        elif content_type == 'video' and message.video:
            v = message.video
            media_items.append(("video", v.file_id, f"video_{message.message_id}.mp4"))
        elif content_type == 'voice' and message.voice:
            v = message.voice
            media_items.append(("voice", v.file_id, f"voice_{message.message_id}.ogg"))
        elif content_type == 'video_note' and message.video_note:
            v = message.video_note
            media_items.append(("video_note", v.file_id, f"video_note_{message.message_id}.mp4"))
        elif content_type == 'document' and message.document:
            d = message.document
            name = d.file_name or f"document_{message.message_id}.bin"
            media_items.append(("document", d.file_id, name))
        elif content_type == 'audio' and message.audio:
            a = message.audio
            ext = "m4a" if a.file_name and a.file_name.endswith('.m4a') else "mp3"
            media_items.append(("audio", a.file_id, f"audio_{message.message_id}.{ext}"))
        elif content_type == 'animation' and message.animation:
            a = message.animation
            media_items.append(("animation", a.file_id, f"animation_{message.message_id}.mp4"))
        elif content_type == 'sticker' and message.sticker:
            s = message.sticker
            ext = "tgs" if s.is_animated else "webm" if s.is_video else "webp"
            media_items.append(("sticker", s.file_id, f"sticker_{message.message_id}.{ext}"))

    if not media_items:
        logger.warning(f"[DOWNLOAD] Не удалось найти медиа в сообщении {message.message_id}, content_type={message.content_type}")
        return file_paths

    for media_type, file_id, original_name in media_items:
        try:
            file = await bot.get_file(file_id)
            safe_name = "".join(c for c in original_name if c.isalnum() or c in "._-")
            if not safe_name:
                safe_name = f"{media_type}_{message.message_id}.bin"
            save_path = os.path.join(user_dir, safe_name)
            await bot.download_file(file.file_path, save_path)
            file_paths.append(save_path)
            logger.info(f"[DOWNLOAD] {media_type} сохранён: {save_path}")
        except Exception as e:
            logger.error(f"[DOWNLOAD] Ошибка скачивания {media_type} (file_id={file_id}): {e}")

    return file_paths

def format_user_info(user: types.User) -> str:
    full = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    return f"{full} (@{user.username})" if user.username else f"{full} (ID: {user.id})"

async def send_notification(chat_id: int, text: str, files: list = None, parse_mode: str = "HTML"):
    try:
        if files and len(files) > 0:
            await bot.send_document(chat_id, FSInputFile(files[0]), caption=premium(text), parse_mode=parse_mode)
            for f in files[1:]:
                await bot.send_document(chat_id, FSInputFile(f))
        else:
            await bot.send_message(chat_id, premium(text), parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"[NOTIFY] Ошибка: {e}")

async def safe_edit_or_send(message: types.Message, new_text: str, reply_markup: InlineKeyboardMarkup = None):
    new_text = premium(new_text)
    try:
        if message.text or message.caption:
            await message.edit_text(new_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await message.delete()
            await bot.send_message(message.chat.id, new_text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        if "there is no text" in str(e) or "message to edit not found" in str(e):
            await message.delete()
            await bot.send_message(message.chat.id, new_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            logger.error(f"[EDIT] Ошибка: {e}")
            try:
                await message.delete()
            except:
                pass
            await bot.send_message(message.chat.id, new_text, parse_mode="HTML", reply_markup=reply_markup)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user = message.from_user
    db.register_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
    await message.answer(
        premium("<b>👋 Добро пожаловать в XrayGram!\n\n"
                "🤖 Что умеет бот:\n"
                "• Отслеживает удалённые сообщения и присылает их копии.\n"
                "• Показывает изменения в отредактированных сообщениях.\n"
                "• Сохраняет самоуничтожающиеся медиа и голосовые.\n\n"
                "📋 Нажмите «Команды» для доп. возможностей.</b>"),
        reply_markup=main_menu_keyboard(user.id == ADMIN_ID),
        parse_mode="HTML"
    )

@dp.message(Command("duel"))
async def cmd_duel(message: types.Message):
    await start_duel(message)

@dp.message(Command("anim"))
async def cmd_anim(message: types.Message):
    text = message.text.replace("/anim", "").strip()
    if not text:
        await message.answer(premium("<b>❌ Напишите текст: /anim Привет!</b>"))
        return
    await animate_text(message.chat.id, text, message)

# ==================== ДУЭЛЬ ====================
async def start_duel(message: types.Message):
    if message.chat.type != "private":
        await message.answer(premium("<b>❌ Дуэль только в личных чатах!</b>"))
        return
    msg = await message.answer("⚔️ ДУЭЛЬ НАЧИНАЕТСЯ!", parse_mode="HTML")
    stages = ["⚔️ 3...", "⚔️ 2...", "⚔️ 1...", "🔫 ПРИЦЕЛИВАЙСЯ!", "💥 ВЫСТРЕЛ!"]
    for stage in stages:
        await asyncio.sleep(0.7)
        await msg.edit_text(f"<b>{stage}</b>", parse_mode="HTML")
    await asyncio.sleep(0.5)
    winner = random.choice([message.from_user.id, "собеседник"])
    if winner == message.from_user.id:
        result = f"🏆 ПОБЕДИТЕЛЬ: {format_user_info(message.from_user)}!"
    else:
        result = "🏆 ПОБЕДИТЕЛЬ: ВАШ СОБЕСЕДНИК!"
    await msg.edit_text(f"<b>{result}</b>", parse_mode="HTML")

# ==================== CALLBACK-ЗАПРОСЫ ====================
@dp.callback_query(lambda c: c.data.startswith("check_subscription"))
async def check_subscription(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split("|")
    action = parts[1] if len(parts) > 1 else None
    if await is_subscribed(user_id):
        await callback.message.delete()
        if action == "show_instruction":
            await show_instruction_logic(user_id)
        else:
            await bot.send_message(
                user_id,
                premium("<b>👋 Добро пожаловать в XrayGram!\n\n"
                        "🤖 Что умеет бот:\n"
                        "• Отслеживает удалённые сообщения и присылает их копии.\n"
                        "• Показывает изменения в отредактированных сообщениях.\n"
                        "• Сохраняет самоуничтожающиеся медиа и голосовые.\n\n"
                        "📋 Нажмите «Команды» для доп. возможностей.</b>"),
                reply_markup=main_menu_keyboard(user_id == ADMIN_ID),
                parse_mode="HTML"
            )
        await callback.answer("✅ Подписка подтверждена!", show_alert=True)
    else:
        await callback.answer("❌ Вы ещё не подписаны.", show_alert=True)

async def show_instruction_logic(user_id: int):
    text = premium(
        "<b>📖 Инструкция по подключению XrayGram\n\n"
        "1️⃣ Убедитесь, что у вас есть Телеграм Премиум.\n"
        "2️⃣ Откройте Настройки → Телеграм для бизнеса → Чат-боты.\n"
        "3️⃣ Нажмите Добавить бота и введите @XrayGramRobot.\n"
        "4️⃣ Добавьте все разрешения с фото.\n\n"
        "❓ Вопросы: @CryptoViktor.</b>"
    )
    try:
        if os.path.exists(INSTRUCTION_IMAGE_PATH):
            await bot.send_photo(user_id, FSInputFile(INSTRUCTION_IMAGE_PATH), caption=text, parse_mode="HTML", reply_markup=instruction_keyboard())
        else:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=instruction_keyboard())
    except Exception as e:
        logger.error(f"[INST] Ошибка: {e}")

@dp.callback_query(lambda c: c.data == "show_instruction")
async def show_instruction(callback: types.CallbackQuery):
    if not await is_subscribed(callback.from_user.id):
        await callback.message.edit_text(
            premium("<b>📢 Подпишитесь на @NovoeTelegram и нажмите «Проверить подписку».</b>"),
            reply_markup=subscription_keyboard("show_instruction"),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    await callback.message.delete()
    await show_instruction_logic(callback.from_user.id)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "show_commands")
async def show_commands(callback: types.CallbackQuery):
    text = premium(
        "<b>📋 Список команд\n\n"
        ".mute – заглушить чат\n"
        ".unmute – размутить\n"
        ".spam &lt;число&gt; &lt;текст&gt; – спам\n"
        ".duel – дуэль\n"
        ".anim &lt;текст&gt; – анимация\n\n"
        "Примеры:\n.mute\n.spam 5 Привет!\n.duel\n.anim Привет</b>"
    )
    await safe_edit_or_send(callback.message, text, commands_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await safe_edit_or_send(
        callback.message,
        premium("<b>👋 Добро пожаловать в XrayGram!\n\n"
                "🤖 Что умеет бот:\n"
                "• Отслеживает удалённые сообщения и присылает их копии.\n"
                "• Показывает изменения в отредактированных сообщениях.\n"
                "• Сохраняет самоуничтожающиеся медиа и голосовые.\n\n"
                "📋 Нажмите «Команды» для доп. возможностей.</b>"),
        main_menu_keyboard(user_id == ADMIN_ID)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await safe_edit_or_send(callback.message, premium("<b>⚙️ Админ-панель</b>"), admin_panel_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await safe_edit_or_send(callback.message, premium("<b>⚙️ Админ-панель</b>"), admin_panel_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "broadcast")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.message.delete()
    await bot.send_message(
        callback.from_user.id,
        premium("<b>📢 Введите текст или отправьте медиа для рассылки</b>"),
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(BroadcastStates.waiting_for_content)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_broadcast")
async def cancel_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await state.clear()
    await callback.message.delete()
    await bot.send_message(callback.from_user.id, premium("<b>⚙️ Админ-панель</b>"), parse_mode="HTML", reply_markup=admin_panel_keyboard())
    await callback.answer()

@dp.message(StateFilter(BroadcastStates.waiting_for_content))
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    cursor = db.conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    if not users:
        await message.answer(premium("<b>📭 Нет пользователей.</b>"), parse_mode="HTML")
        await state.clear()
        return
    sent = 0
    failed = 0
    for (uid,) in users:
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"[BROADCAST] {uid}: {e}")
            failed += 1
    await message.answer(
        premium(f"<b>✅ Рассылка завершена!\nОтправлено: {sent}\nНе удалось: {failed}</b>"),
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )
    await state.clear()

@dp.callback_query(lambda c: c.data == "users_txt")
async def users_txt(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    cursor = db.conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, last_name, registered_at FROM users ORDER BY registered_at DESC")
    users = cursor.fetchall()
    if not users:
        await callback.message.answer(premium("<b>📭 Нет пользователей.</b>"), parse_mode="HTML")
        await callback.answer()
        return
    content = "Список пользователей XrayGram\nВсего: " + str(len(users)) + "\n\n"
    for u in users:
        uid, uname, fname, lname, reg = u
        name = f"{fname or ''} {lname or ''}".strip() or "Без имени"
        content += f"{name} (@{uname}) ID:{uid} Зарегистрирован:{reg}\n"
    await callback.message.answer_document(
        BufferedInputFile(content.encode("utf-8"), filename="users_list.txt"),
        caption=premium("<b>📄 Список пользователей</b>"),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "active_connections")
async def active_connections(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    cursor = db.conn.cursor()
    cursor.execute("SELECT DISTINCT user_id FROM connections")
    rows = cursor.fetchall()
    if not rows:
        text = premium("<b>🔗 Активных подключений нет.</b>")
    else:
        user_ids = [r[0] for r in rows]
        placeholders = ",".join("?" for _ in user_ids)
        cursor.execute(f"SELECT user_id, username, first_name, last_name FROM users WHERE user_id IN ({placeholders})", user_ids)
        users = cursor.fetchall()
        lines = [f"• {u[2] or ''} {u[3] or ''} (@{u[1]}) - ID: {u[0]}" for u in users]
        text = premium(f"<b>🔗 Активные подключения ({len(users)})\n\n" + "\n".join(lines) + "</b>")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_admin_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cleanup_old")
async def cleanup_old_messages(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    deleted = db.delete_old_messages(30)
    await callback.message.edit_text(
        premium(f"<b>🗑️ Очистка завершена!\nУдалено сообщений: {deleted}\nФайлы удалены.</b>"),
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )
    await callback.answer()

# ==================== БИЗНЕС-ОБРАБОТЧИКИ ====================
@dp.business_connection()
async def handle_business_connection(connection: BusinessConnection):
    bc_id = connection.id
    user_id = connection.user.id
    if not connection.is_enabled:
        logger.info(f"[CONN] Отключено: {bc_id}")
        db.delete_connection(bc_id)
        return
    logger.info(f"[CONN] Новое подключение: {bc_id} -> {user_id}")
    db.set_connection(bc_id, user_id)
    if not db.is_user_registered(user_id):
        user = connection.user
        db.register_user(user_id, user.username, user.first_name, user.last_name)
    try:
        await bot.send_message(
            user_id,
            premium("<b>✅ Бизнес-аккаунт подключён к XrayGram!\n\n"
                    "Я сохраняю все медиа, включая самоуничтожающиеся.\n"
                    "Удалённые и изменённые сообщения тоже будут отправлены вам.\n\n"
                    "По вопросам: @CryptoViktor.</b>"),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[CONN] Ошибка уведомления: {e}")
    try:
        user = connection.user
        full = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без имени"
        await bot.send_message(
            ADMIN_ID,
            premium(f"<b>🔔 Новое подключение!</b>\n👤 {full}\n🆔 <code>{user_id}</code>\n🔗 <code>{bc_id}</code>"),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[CONN] Ошибка уведомления админа: {e}")

@dp.business_message()
async def handle_business_message(message: types.Message):
    bc_id = message.business_connection_id
    if not bc_id:
        logger.warning("[MSG] Нет bc_id")
        return

    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id and message.from_user and message.from_user.id == ADMIN_ID:
        db.set_connection(bc_id, ADMIN_ID)
        if not db.is_user_registered(ADMIN_ID):
            db.register_user(ADMIN_ID, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        user_id = ADMIN_ID
        logger.info(f"[FIX] Создана связь для админа: {bc_id}")
    if not user_id and message.from_user:
        user_id = message.from_user.id
        logger.warning(f"[MSG] fallback user_id={user_id}")
    if not user_id:
        logger.warning(f"[MSG] Не удалось определить user_id для {bc_id}")
        return

    if not db.is_user_registered(user_id) and message.from_user:
        db.register_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)

    chat_id = message.chat.id
    sender_id = message.from_user.id if message.from_user else None
    is_owner = (sender_id == user_id)

    # Обработка команд владельца
    if is_owner and message.text and message.text.startswith('.'):
        cmd = message.text.strip()
        try:
            await bot.delete_business_messages(bc_id, [message.message_id])
        except:
            pass
        if cmd == ".mute":
            db.add_muted_chat(user_id, chat_id)
            await bot.send_message(chat_id, premium("<b>🔇 Вы заглушены.</b>"), business_connection_id=bc_id, parse_mode="HTML")
            await bot.send_message(user_id, premium(f"<b>🔇 Чат {chat_id} замучен.</b>"), parse_mode="HTML")
            return
        if cmd == ".unmute":
            db.remove_muted_chat(user_id, chat_id)
            await bot.send_message(chat_id, premium("<b>🔊 Вы размучены.</b>"), business_connection_id=bc_id, parse_mode="HTML")
            await bot.send_message(user_id, premium(f"<b>🔊 Чат {chat_id} размучен.</b>"), parse_mode="HTML")
            return
        if cmd.startswith(".spam "):
            parts = cmd.split(maxsplit=2)
            if len(parts) >= 3:
                try:
                    count = int(parts[1])
                    if count < 1 or count > 50:
                        raise ValueError
                    for _ in range(count):
                        await bot.send_message(chat_id, parts[2], business_connection_id=bc_id)
                        await asyncio.sleep(0.3)
                    await bot.send_message(user_id, premium(f"<b>✅ Спам {count} сообщений отправлен.</b>"), parse_mode="HTML")
                except:
                    await bot.send_message(user_id, premium("<b>❌ Формат: .spam &lt;число&gt; &lt;текст&gt;</b>"), parse_mode="HTML")
            else:
                await bot.send_message(user_id, premium("<b>❌ Формат: .spam &lt;число&gt; &lt;текст&gt;</b>"), parse_mode="HTML")
            return
        if cmd == ".duel":
            await start_duel(message)
            return
        if cmd.startswith(".anim "):
            txt = cmd.replace(".anim", "").strip()
            if txt:
                await animate_text(chat_id, txt, message)
            else:
                await bot.send_message(user_id, premium("<b>❌ .anim &lt;текст&gt;</b>"), parse_mode="HTML")
            return
        return

    # Мут
    if db.is_chat_muted(user_id, chat_id) and not is_owner:
        try:
            await bot.delete_business_messages(bc_id, [message.message_id])
            logger.info(f"[MUTE] Удалено {message.message_id}")
        except:
            pass
        return

    # Сохранение
    msg_id = message.message_id
    sender = message.from_user
    fullname = format_user_info(sender) if sender else "Неизвестный"
    text = message.text or message.caption or ""

    ttl = get_ttl_seconds(message)
    media_type = get_media_type(message)
    has_media = bool(media_type)

    logger.info(f"[MSG] id={msg_id}, ttl={ttl}, type={media_type}, content_type={message.content_type}, owner={is_owner}")

    files = []
    if has_media:
        files = await download_media_files(message, user_id)
        logger.info(f"[MSG] Скачано файлов: {len(files)}")
    else:
        # Если по какой-то причине has_media False, но мы знаем, что медиа есть, пробуем скачать принудительно
        # через content_type (это уже сделано в download_media_files, но здесь мы можем попытаться ещё раз)
        if message.content_type and message.content_type != 'text':
            files = await download_media_files(message, user_id)
            if files:
                # Если файлы скачались, переопределяем тип
                media_type = message.content_type
                has_media = True
                logger.info(f"[MSG] Принудительное скачивание через content_type={media_type}, файлов: {len(files)}")

    db.save_message(
        bc_id, msg_id, user_id, fullname, text, files,
        is_temporary=getattr(message, 'has_media_spoiler', False),
        ttl_seconds=ttl,
        media_type=media_type
    )

    # Отправка уведомлений
    if ttl > 0 and files:
        if media_type == "voice":
            notif = premium(f"<b>🎤 Самоуничтожающееся голосовое от {fullname}</b>")
        else:
            notif = premium(f"<b>⚠️ Самоуничтожающееся медиа ({media_type}) от {fullname}</b>")
        if text:
            notif += premium(f"\n\n{text}")
        await send_notification(user_id, notif, files)
    elif has_media and files:
        if media_type == "voice":
            notif = premium(f"<b>🎤 Голосовое от {fullname}</b>")
        else:
            notif = premium(f"<b>📎 Медиа ({media_type}) от {fullname}</b>")
        if text:
            notif += premium(f"\n\n{text}")
        await send_notification(user_id, notif, files)

@dp.edited_business_message()
async def handle_edited_business_message(message: types.Message):
    bc_id = message.business_connection_id
    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id:
        return
    chat_id = message.chat.id
    if db.is_chat_muted(user_id, chat_id):
        return
    msg_id = message.message_id
    new_text = message.text or message.caption or ""
    old = db.get_message(bc_id, msg_id)
    if not old:
        return
    old_text = old["text"] or ""
    if new_text.strip() == old_text.strip():
        return
    db.update_message_text(bc_id, msg_id, new_text)
    if message.from_user:
        new_full = format_user_info(message.from_user)
        if new_full != old["fullname"]:
            db.update_message_fullname(bc_id, msg_id, new_full)
            old_fullname = new_full
        else:
            old_fullname = old["fullname"]
    else:
        old_fullname = old["fullname"]
    files = old["files"]
    files_list = json.loads(files) if files else []
    notif = premium(f"<b>✏️ Изменено от {old_fullname}\n\nБыло: {old_text}\nСтало: {new_text}</b>")
    await send_notification(user_id, notif, files_list)

@dp.deleted_business_messages()
async def handle_deleted_business_messages(event: BusinessMessagesDeleted):
    bc_id = event.business_connection_id
    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id:
        return
    for msg_id in event.message_ids:
        data = db.get_message(bc_id, msg_id)
        if not data:
            continue
        fullname = data["fullname"]
        text = data["text"] or ""
        files = data["files"]
        files_list = json.loads(files) if files else []
        ttl = data["ttl_seconds"] or 0
        media_type = data["media_type"] or ""
        if ttl > 0:
            if media_type == "voice":
                notif = premium(f"<b>🗑️ Самоуничтожающееся голосовое от {fullname} (сохранено)</b>")
            else:
                notif = premium(f"<b>🗑️ Самоуничтожающееся медиа ({media_type}) от {fullname} (сохранено)</b>")
        else:
            if files_list:
                notif = premium(f"<b>❌ Медиа удалено от {fullname}</b>")
            else:
                notif = premium(f"<b>❌ Сообщение удалено от {fullname}</b>")
        if text:
            notif += premium(f"\n\n{text}")
        await send_notification(user_id, notif, files_list)
        db.delete_message(bc_id, msg_id)

# ==================== ЗАПУСК ====================
async def main():
    try:
        me = await bot.get_me()
        logger.info(f"✅ Бот запущен: @{me.username}")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения: {e}")
        raise
    await bot.set_my_commands([types.BotCommand(command="start", description="Главное меню")])
    await dp.start_polling(bot)

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
            break
        except KeyboardInterrupt:
            logger.info("Остановлен")
            break
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            time.sleep(15)
