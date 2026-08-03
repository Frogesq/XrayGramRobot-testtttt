import asyncio
import logging
import os
import json
import time
import random
import re
import requests
import urllib3
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

# Отключение предупреждений об SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
BANNER_PATH = os.path.join(BASE_DIR, "banner.png")
CHANNEL_USERNAME = "@NovoeTelegram"

# ==================== GIGACHAT НАСТРОЙКИ ====================
GIGACHAT_API_KEY = "MDE5YzE5MDUtNWZiMC03Y2Y1LWE2MDMtZWI1ZWYwY2I0N2QxOjc5Y2Y2OTRiLWQxMTEtNDc1Zi05YzIyLWYyMmY0ZGE0NGNmMg=="
GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

# ==================== PREMIUM ЭМОДЗИ ====================
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
    "⚔️": "5408935401442267103",
    "⭕": "5411225014148014586",
    "🔄": "5264727218734524899",
}

EMPTY = "ㅤ"

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

if os.path.exists(BANNER_PATH):
    logger.info("✅ Баннер найден")
else:
    logger.warning("❌ Баннер НЕ найден (файл banner.png отсутствует)")

class BroadcastStates(StatesGroup):
    waiting_for_content = State()

# ==================== GIGACHAT (РАБОЧАЯ ВЕРСИЯ) ====================
class GigaChatAPI:
    """Класс для работы с GigaChat API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._access_token = None
        self._token_expires = 0
        self._session = requests.Session()
        self._session.verify = False
        self._session.timeout = 60
        
    def _get_access_token(self) -> str | None:
        """Получение токена доступа"""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token
            
        try:
            headers = {
                "Authorization": f"Basic {self.api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
                "RqUID": "6f0b1291-c7f3-4c6a-a5e7-8a6b5d3e2f1a",
                "Accept": "application/json"
            }
            
            response = self._session.post(
                GIGACHAT_AUTH_URL,
                headers=headers,
                data={"scope": "GIGACHAT_API_PERS"},
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                token = data.get("access_token")
                if token:
                    self._access_token = token
                    self._token_expires = time.time() + 1500
                    logger.info("✅ Токен GigaChat получен")
                    return token
            else:
                logger.error(f"Ошибка получения токена: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Ошибка получения токена: {e}")
        
        return None
    
    def get_text_response(self, messages: list) -> str:
        """Получение ответа от GigaChat"""
        token = self._get_access_token()
        if not token:
            return "🔧 Сервис временно недоступен. Пожалуйста, попробуйте позже."
        
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            system_message = {
                "role": "system",
                "content": "Ты - полезный и вежливый ассистент. Отвечай на русском языке подробно и понятно."
            }
            
            data = {
                "model": "GigaChat",
                "messages": [system_message] + messages,
                "temperature": 0.7,
                "max_tokens": 2000
            }
            
            response = self._session.post(
                GIGACHAT_API_URL,
                headers=headers,
                json=data,
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    text = result["choices"][0]["message"]["content"]
                    text = re.sub(r'[`*_\[\]()]', '', text)
                    text = ''.join(char for char in text if char.isprintable() or char in '\n\r\t').strip()
                    if text:
                        return self._format_response(text)
            
            return "⚠️ Не удалось получить ответ. Попробуйте переформулировать вопрос."
            
        except Exception as e:
            logger.error(f"Ошибка GigaChat API: {e}")
            return "❌ Ошибка при обработке запроса. Пожалуйста, попробуйте позже."
    
    def _format_response(self, text: str) -> str:
        """Форматирование ответа"""
        formatted = "🤖 <b>Ответ:</b>\n\n"
        
        paragraphs = text.split('\n\n')
        for paragraph in paragraphs:
            if paragraph.strip():
                formatted += paragraph.strip() + "\n\n"
        
        formatted += "─\nБот - @XrayGramRobot"
        return formatted

# Инициализация GigaChat
giga_chat = GigaChatAPI(GIGACHAT_API_KEY)

# ==================== TTT ====================
ttt_games = {}

def ttt_board_to_text(board):
    result = ""
    for i in range(0, 9, 3):
        for j in range(3):
            cell = board[i+j]
            if cell == "X":
                result += "❌"
            elif cell == "O":
                result += "⭕"
            else:
                result += EMPTY
        result += "\n"
    return result.strip()

def ttt_check_winner(board):
    win = [
        [0,1,2], [3,4,5], [6,7,8],
        [0,3,6], [1,4,7], [2,5,8],
        [0,4,8], [2,4,6]
    ]
    for combo in win:
        if board[combo[0]] == board[combo[1]] == board[combo[2]] and board[combo[0]] != " ":
            return board[combo[0]]
    if " " not in board:
        return "draw"
    return None

def ttt_keyboard(board, game_id):
    kb = []
    for i in range(0, 9, 3):
        row = []
        for j in range(3):
            cell = i + j
            if board[cell] == " ":
                row.append(InlineKeyboardButton(
                    text=EMPTY,
                    callback_data=f"ttt_{game_id}_{cell}"
                ))
            else:
                row.append(InlineKeyboardButton(
                    text="❌" if board[cell] == "X" else "⭕",
                    callback_data="ttt_no"
                ))
        kb.append(row)
    kb.append([InlineKeyboardButton(
        text="🔴 Завершить",
        callback_data=f"ttt_end_{game_id}",
        style="danger"
    )])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==================== АНИМАЦИЯ ====================
async def animate_text(chat_id: int, text: str, message: types.Message, delay: float = 0.3):
    msg = await message.answer("<i>⏳ Анимация запущена...</i>", parse_mode="HTML")
    
    current_text = ""
    last_text = ""
    for i, char in enumerate(text):
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
        [
            InlineKeyboardButton(
                text="🔗 Подключить бота",
                callback_data="show_instruction",
                style="primary"
            )
        ],
        [
            InlineKeyboardButton(
                text="📋 Команды",
                callback_data="show_commands",
                style="success"
            )
        ]
    ]
    if is_admin:
        kb.append([
            InlineKeyboardButton(
                text="⚙️ Админ-панель",
                callback_data="admin_panel",
                style="danger"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def subscription_keyboard(action: str = None):
    callback_data = "check_subscription"
    if action:
        callback_data += f"|{action}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Подписаться на канал",
                    url="https://t.me/NovoeTelegram"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Проверить подписку",
                    callback_data=callback_data,
                    style="success"
                )
            ]
        ]
    )

def instruction_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_to_main",
                    style="danger"
                )
            ]
        ]
    )

def admin_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="broadcast",
                    style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📄 Список пользователей (txt)",
                    callback_data="users_txt",
                    style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Активные подключения",
                    callback_data="active_connections",
                    style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_to_main",
                    style="danger"
                )
            ]
        ]
    )

def cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_broadcast",
                    style="danger"
                )
            ]
        ]
    )

def back_to_admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в админ-панель",
                    callback_data="back_to_admin",
                    style="primary"
                )
            ]
        ]
    )

def commands_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_to_main",
                    style="danger"
                )
            ]
        ]
    )

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
async def is_subscribed(user_id: int) -> bool:
    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        chat_id = chat.id
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки для {user_id}: {e}")
        return True

def get_user_download_dir(user_id: int) -> str:
    user_dir = os.path.join(DOWNLOADS_DIR, f"user_{user_id}")
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

async def download_files(message: types.Message, user_id: int) -> list:
    file_paths = []
    if not message.content_type:
        return file_paths

    media_items = []
    if message.photo:
        media_items.append(("photo", message.photo[-1].file_id, f"photo_{message.message_id}.jpg"))
    elif message.video:
        media_items.append(("video", message.video.file_id, f"video_{message.message_id}.mp4"))
    elif message.voice:
        media_items.append(("voice", message.voice.file_id, f"voice_{message.message_id}.ogg"))
    elif message.audio:
        media_items.append(("audio", message.audio.file_id, f"audio_{message.message_id}.mp3"))
    elif message.document:
        file_name = message.document.file_name or f"document_{message.message_id}.bin"
        media_items.append(("document", message.document.file_id, file_name))
    elif message.sticker:
        media_items.append(("sticker", message.sticker.file_id, f"sticker_{message.message_id}.webp"))
    elif message.animation:
        media_items.append(("animation", message.animation.file_id, f"animation_{message.message_id}.mp4"))
    elif message.video_note:
        media_items.append(("video_note", message.video_note.file_id, f"video_note_{message.message_id}.mp4"))

    user_dir = get_user_download_dir(user_id)
    for media_type, file_id, original_name in media_items:
        try:
            file = await bot.get_file(file_id)
            safe_name = "".join(c for c in original_name if c.isalnum() or c in "._- ")
            if not safe_name:
                safe_name = f"{media_type}_{message.message_id}.bin"
            save_path = os.path.join(user_dir, safe_name)
            await bot.download_file(file.file_path, save_path)
            file_paths.append(save_path)
            logger.info(f"Файл сохранён: {save_path}")
        except Exception as e:
            logger.error(f"Ошибка скачивания файла {file_id}: {e}")

    return file_paths

def format_user_info(user: types.User) -> str:
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    return f"{full_name} (@{user.username})" if user.username else f"{full_name} (ID: {user.id})"

async def send_notification(chat_id: int, text: str, files: list = None, parse_mode: str = "HTML"):
    try:
        if files:
            await bot.send_document(chat_id, types.FSInputFile(files[0]), caption=premium(text), parse_mode=parse_mode)
            for file_path in files[1:]:
                await bot.send_document(chat_id, types.FSInputFile(file_path))
            for file_path in files:
                try:
                    os.remove(file_path)
                except:
                    pass
        else:
            await bot.send_message(chat_id, premium(text), parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю {chat_id}: {e}")

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
            logger.error(f"Ошибка редактирования: {e}")
            try:
                await message.delete()
            except:
                pass
            await bot.send_message(message.chat.id, new_text, parse_mode="HTML", reply_markup=reply_markup)

# ==================== ОБРАБОТЧИКИ КОМАНД (только для личных чатов и обычных сообщений) ====================
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user = message.from_user
    user_id = user.id
    db.register_user(user_id, user.username or "", user.first_name or "", user.last_name or "")

    is_admin = (user_id == ADMIN_ID)
    main_text = premium(
        "<b>👋 Добро пожаловать в XrayGram!</b>\n\n"
        "<b>🤖 Что умеет бот:</b>\n"
        "<blockquote>Отслеживает удалённые сообщения в ваших личных чатах и присылает их копии.\n"
        "Показывает изменения в отредактированных сообщениях (было → стало).\n"
        "Сохраняет самоуничтожающиеся медиа.</blockquote>\n\n"
        "📋 Нажмите «Команды», чтобы узнать о дополнительных возможностях."
    )
    
    if os.path.exists(BANNER_PATH):
        banner = FSInputFile(BANNER_PATH)
        await message.answer_photo(
            photo=banner,
            caption=main_text,
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(is_admin)
        )
    else:
        await message.answer(main_text, reply_markup=main_menu_keyboard(is_admin), parse_mode="HTML")

@dp.message(Command("duel"))
async def cmd_duel(message: types.Message):
    await start_duel(message)

@dp.message(Command("anim"))
async def cmd_anim(message: types.Message):
    text = message.text.replace("/anim", "").strip()
    if not text:
        await message.answer(premium("<b>❌ Напишите текст для анимации!\nПример: /anim Привет мир!</b>"))
        return
    await animate_text(message.chat.id, text, message)

@dp.message(Command("ttt"))
async def cmd_ttt(message: types.Message):
    await start_ttt(message)

# ==================== БИЗНЕС-ОБРАБОТЧИКИ ====================
@dp.business_connection()
async def handle_business_connection(connection: BusinessConnection):
    bc_id = connection.id
    user_id = connection.user.id
    is_enabled = connection.is_enabled

    if not is_enabled:
        logger.info(f"[CONN] Бизнес-подключение ОТКЛЮЧЕНО: bc_id={bc_id}, user_id={user_id}")
        return

    logger.info(f"[CONN] Новое бизнес-подключение: bc_id={bc_id}, user_id={user_id}")

    db.set_connection(bc_id, user_id)

    if not db.is_user_registered(user_id):
        user = connection.user
        db.register_user(user_id, user.username, user.first_name, user.last_name)

    try:
        await bot.send_message(
            user_id,
            premium("<b>✅ Ваш бизнес-аккаунт успешно подключён к XrayGram!\n\n"
                    "Теперь я буду отслеживать все ваши личные чаты и присылать вам копии удалённых или изменённых сообщений.\n\n"
                    "Если у вас возникнут вопросы — обратитесь в поддержку @CryptoViktor.</b>"),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[CONN] Не удалось отправить уведомление пользователю {user_id}: {e}")

    try:
        user = connection.user
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без имени"
        username = f"@{user.username}" if user.username else "без username"
        await bot.send_message(
            ADMIN_ID,
            premium(f"<b>🔔 Новое подключение!</b>\n\n"
                    f"👤 <b>Пользователь:</b> {full_name}\n"
                    f"📱 <b>Username:</b> {username}\n"
                    f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                    f"🔗 <b>bc_id:</b> <code>{bc_id}</code>"),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[CONN] Не удалось отправить уведомление админу: {e}")

# ==================== ОСНОВНОЙ ОБРАБОТЧИК БИЗНЕС-СООБЩЕНИЙ ====================
@dp.business_message()
async def handle_business_message(message: types.Message):
    bc_id = message.business_connection_id
    if not bc_id:
        logger.warning("[MUTE] business_connection_id отсутствует")
        return

    user_id = db.get_user_by_bc_id(bc_id)

    if not user_id and message.from_user and message.from_user.id == ADMIN_ID:
        db.set_connection(bc_id, ADMIN_ID)
        if not db.is_user_registered(ADMIN_ID):
            db.register_user(ADMIN_ID, message.from_user.username or "", message.from_user.first_name or "", message.from_user.last_name or "")
        user_id = ADMIN_ID
        logger.info(f"[FIX] Создана связь для владельца: bc_id={bc_id}, user_id={ADMIN_ID}")

    if not user_id and message.from_user:
        user_id = message.from_user.id
        logger.warning(f"[MUTE] bc_id={bc_id} не найден, используем fallback user_id={user_id}")

    if not user_id:
        logger.warning(f"[MUTE] Не удалось определить user_id для bc_id={bc_id}")
        return

    if not db.is_user_registered(user_id):
        if message.from_user:
            db.register_user(user_id, message.from_user.username or "", message.from_user.first_name or "", message.from_user.last_name or "")
        else:
            db.register_user(user_id, "", "Unknown", "")

    chat_id = message.chat.id
    sender_id = message.from_user.id if message.from_user else None
    is_owner = (sender_id == user_id)

    # ========== ВСЕ КОМАНДЫ ВЛАДЕЛЬЦА (ТОЛЬКО В БИЗНЕС-ОБРАБОТЧИКЕ) ==========
    if is_owner and message.text and message.text.startswith('.'):
        text = message.text.strip()

        try:
            await bot.delete_business_messages(
                business_connection_id=bc_id,
                message_ids=[message.message_id]
            )
            logger.info(f"[CMD] Сообщение с командой '{text}' удалено")
        except Exception as e:
            logger.error(f"[CMD] Не удалось удалить сообщение с командой: {e}")

        if text == ".mute":
            db.add_muted_chat(user_id, chat_id)
            await bot.send_message(
                chat_id,
                premium("<b>🔇 Вы были заглушены. Ваши сообщения будут удаляться.</b>\n\n<i>Бот - @XrayGramRobot</i>"),
                business_connection_id=bc_id,
                parse_mode="HTML"
            )
            await bot.send_message(
                user_id,
                premium(f"<b>🔇 Чат {chat_id} замучен.\nСообщения от собеседника не будут сохраняться и будут удаляться.</b>\n\n<i>Бот - @XrayGramRobot</i>"),
                parse_mode="HTML"
            )
            logger.info(f"[CMD] ✅ .mute выполнен для чата {chat_id}")
            return

        if text == ".unmute":
            db.remove_muted_chat(user_id, chat_id)
            await bot.send_message(
                chat_id,
                premium("<b>🔊 Вы размучены. Ваши сообщения больше не будут удаляться.</b>"),
                business_connection_id=bc_id,
                parse_mode="HTML"
            )
            await bot.send_message(
                user_id,
                premium(f"<b>🔊 Чат {chat_id} размучен.\nСообщения снова сохраняются.</b>"),
                parse_mode="HTML"
            )
            logger.info(f"[CMD] ✅ .unmute выполнен для чата {chat_id}")
            return

        if text.startswith(".spam "):
            parts = text.split(maxsplit=2)
            if len(parts) >= 3:
                try:
                    count = int(parts[1])
                    spam_text = parts[2]
                    if count <= 0:
                        raise ValueError
                except (ValueError, IndexError):
                    await bot.send_message(user_id, premium("<b>❌ Неверный формат: .spam <число> <текст></b>"), parse_mode="HTML")
                    return
                for i in range(count):
                    await bot.send_message(
                        chat_id=chat_id,
                        text=spam_text,
                        business_connection_id=bc_id
                    )
                    await asyncio.sleep(0.3)
                await bot.send_message(user_id, premium(f"<b>✅ Отправлено {count} сообщений в чат {chat_id}</b>"), parse_mode="HTML")
                return
            else:
                await bot.send_message(user_id, premium("<b>❌ Неверный формат: .spam <число> <текст></b>"), parse_mode="HTML")
                return

        if text == ".duel":
            await start_duel(message)
            return

        if text.startswith(".anim "):
            anim_text = text.replace(".anim", "").strip()
            if not anim_text:
                await bot.send_message(user_id, premium("<b>❌ Напишите текст для анимации!\nПример: .anim Привет мир!</b>"), parse_mode="HTML")
                return
            await animate_text(chat_id, anim_text, message)
            return

        if text == ".ttt":
            await start_ttt(message)
            return

        if text.startswith(".gn "):
            question = text.replace(".gn", "").strip()
            if not question:
                await bot.send_message(user_id, premium("<b>❌ Напишите вопрос после команды!\nПример: .gn Как дела?</b>"), parse_mode="HTML")
                return
            
            loading_msg = await bot.send_message(user_id, premium("<b>🤔 Думаю...</b>"), parse_mode="HTML")
            
            try:
                messages = [{"role": "user", "content": question}]
                answer = giga_chat.get_text_response(messages)
                
                await loading_msg.delete()
                
                # Отправляем ответ ТОЛЬКО в бизнес-чат
                await bot.send_message(
                    chat_id,
                    premium(f"<b>❓ Ваш вопрос:</b>\n{question}\n\n{answer}"),
                    parse_mode="HTML",
                    business_connection_id=bc_id
                )
            except Exception as e:
                await loading_msg.delete()
                await bot.send_message(
                    user_id,
                    premium(f"<b>❌ Ошибка при обращении к Gigachat:\n{str(e)}</b>"),
                    parse_mode="HTML"
                )
            return

        return

    # ========== МУТ ==========
    if db.is_chat_muted(user_id, chat_id) and not is_owner:
        try:
            await bot.delete_business_messages(
                business_connection_id=bc_id,
                message_ids=[message.message_id]
            )
            logger.info(f"[MUTE] ✅ Сообщение {message.message_id} УДАЛЕНО")
        except Exception as e:
            if "message to delete not found" in str(e):
                logger.info(f"[MUTE] ⏩ Сообщение {message.message_id} уже удалено, пропускаем")
            else:
                logger.error(f"[MUTE] ❌ Ошибка удаления {message.message_id}: {e}")
                await bot.send_message(
                    user_id,
                    premium(f"<b>⚠️ Ошибка удаления сообщения:\n{e}</b>"),
                    parse_mode="HTML"
                )
        return

    # ========== СОХРАНЕНИЕ ==========
    msg_id = message.message_id
    sender = message.from_user
    fullname = format_user_info(sender) if sender else "Неизвестный"
    text = message.text or message.caption or ""

    files = await download_files(message, user_id)
    db.save_message(bc_id, msg_id, user_id, fullname, text, files, is_temporary=message.has_media_spoiler)
    logger.info(f"[SAVE] Сохранено сообщение {msg_id} для {user_id}")

    if message.has_media_spoiler and files:
        notif_text = premium(f"<b>⚠️ Самоуничтожающееся сообщение от {fullname}\n\n{text}</b>") if text else premium(f"<b>⚠️ Самоуничтожающееся медиа от {fullname}</b>")
        await send_notification(user_id, notif_text, files)

# ==================== ФУНКЦИИ ДЛЯ ИГР ====================

async def start_duel(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer(premium("<b>❌ Дуэль доступна только в личных чатах!</b>"))
        return
    
    msg = await message.answer(premium("⚔️ ДУЭЛЬ НАЧИНАЕТСЯ!"), parse_mode="HTML")
    
    stages = [
        "⚔️ 3...",
        "⚔️ 2...",
        "⚔️ 1...",
        "🔫 ПРИЦЕЛИВАЙСЯ!",
        "💥 ВЫСТРЕЛ!"
    ]
    
    for stage in stages:
        await asyncio.sleep(0.7)
        await msg.edit_text(premium(f"<b>{stage}</b>"), parse_mode="HTML")
    
    await asyncio.sleep(0.5)
    
    winner = random.choice([user_id, chat_id])
    
    if winner == user_id:
        result = f"🏆 ПОБЕДИТЕЛЬ: {format_user_info(message.from_user)}!\n\n🎉 Выстрел был точным! Противник повержен! 🎉"
    else:
        result = "🏆 ПОБЕДИТЕЛЬ: ВАШ СОБЕСЕДНИК!\n\n💀 Вы были быстрее, но удача была на его стороне..."
    
    await msg.edit_text(premium(f"<b>{result}</b>"), parse_mode="HTML")

# ==================== TTT ====================

async def start_ttt(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.chat.type != "private":
        await message.answer(premium("<b>❌ Игра доступна только в личных чатах!</b>"))
        return
    
    if chat_id in ttt_games:
        await message.answer(premium("<b>⚠️ Игра уже идёт!</b>"))
        return
    
    board = [" "] * 9
    game_id = int(time.time())
    ttt_games[chat_id] = {
        "board": board,
        "turn": "X",
        "player_x": user_id,
        "player_o": 0,
        "game_id": game_id
    }
    
    player_x_name = format_user_info(message.from_user)
    
    await message.answer(
        premium(
            f"<b>❌⭕ Крестики-Н
