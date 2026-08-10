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

class BroadcastStates(StatesGroup):
    waiting_for_content = State()

# ==================== TTT (новая реализация) ====================
ttt_games = {}

def ttt_board_to_text(board):
    """Преобразует доску в текст"""
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
    """Проверяет победителя"""
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
    """Создаёт клавиатуру для игры"""
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

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
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

# ==================== TTT НОВАЯ РЕАЛИЗАЦИЯ ====================

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
        "player_o": 0,  # 0 = ещё не определён
        "game_id": game_id
    }
    
    player_x_name = format_user_info(message.from_user)
    
    await message.answer(
        premium(
            f"<b>❌⭕ Крестики-Нолики</b>\n\n"
            f"Ход: <b>❌ ({player_x_name})</b>\n"
            f"{EMPTY}{EMPTY}{EMPTY}\n{EMPTY}{EMPTY}{EMPTY}\n{EMPTY}{EMPTY}{EMPTY}"
        ),
        parse_mode="HTML",
        reply_markup=ttt_keyboard(board, game_id)
    )

@dp.callback_query(lambda c: c.data.startswith("ttt_"))
async def ttt_callback(callback: types.CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    
    # Если кнопка уже занята
    if data == "ttt_no":
        await callback.answer("⏳ Занято!")
        return
    
    # Завершение игры
    if data.startswith("ttt_end_"):
        game_id = int(data.replace("ttt_end_", ""))
        if chat_id in ttt_games and ttt_games[chat_id]["game_id"] == game_id:
            del ttt_games[chat_id]
        await callback.message.delete()
        await callback.answer("🔴 Игра завершена!")
        return
    
    # Разбор callback_data
    parts = data.split("_")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка!")
        return
    
    try:
        game_id = int(parts[1])
        cell = int(parts[2])
    except:
        await callback.answer("❌ Ошибка!")
        return
    
    # Проверка наличия игры
    if chat_id not in ttt_games:
        await callback.answer("❌ Игра не найдена!")
        return
    
    game = ttt_games[chat_id]
    
    # Проверка game_id
    if game["game_id"] != game_id:
        await callback.answer("❌ Игра не найдена!")
        return
    
    board = game["board"]
    turn = game["turn"]
    player_x = game["player_x"]
    player_o = game["player_o"]
    
    # ========================================
    # ========== ОСНОВНАЯ ЛОГИКА ============
    # ========================================
    
    # 1. Проверяем, кто ходит
    if turn == "X":
        # Ходят только крестики (владелец)
        if user_id != player_x:
            await callback.answer("⏳ Сейчас ход крестиков! (ваш ход)", show_alert=True)
            return
    else:  # turn == "O"
        # Если игрок O ещё не определён, запоминаем
        if player_o == 0:
            player_o = user_id
            game["player_o"] = user_id
            logger.info(f"[TTT] Игрок O определён: {user_id}")
        # Проверяем, что ходит именно игрок O
        if user_id != player_o:
            await callback.answer("⏳ Сейчас ход ноликов! (ход соперника)", show_alert=True)
            return
    
    # 2. Проверяем, свободна ли клетка
    if board[cell] != " ":
        await callback.answer("⏳ Занято!")
        return
    
    # 3. Делаем ход
    board[cell] = turn
    
    # 4. Проверяем победу
    winner = ttt_check_winner(board)
    
    if winner:
        try:
            player_x_name = format_user_info(await bot.get_chat(player_x))
        except:
            player_x_name = "Игрок X"
        
        if player_o:
            try:
                player_o_name = format_user_info(await bot.get_chat(player_o))
            except:
                player_o_name = "Игрок O"
        else:
            player_o_name = "Игрок O"
        
        if winner == "X":
            result_text = f"🏆 <b>Победили КРЕСТИКИ! ({player_x_name})</b>"
        elif winner == "O":
            result_text = f"🏆 <b>Победили НОЛИКИ! ({player_o_name})</b>"
        else:
            result_text = "🤝 <b>Ничья!</b>"
        
        await callback.message.edit_text(
            premium(f"{ttt_board_to_text(board)}\n\n{result_text}"),
            parse_mode="HTML"
        )
        del ttt_games[chat_id]
        await callback.answer("🏆 Игра завершена!")
        return
    
    # 5. Меняем ход
    game["turn"] = "O" if turn == "X" else "X"
    
    # 6. Обновляем сообщение
    try:
        player_x_name = format_user_info(await bot.get_chat(player_x))
    except:
        player_x_name = "Игрок X"
    
    if player_o:
        try:
            player_o_name = format_user_info(await bot.get_chat(player_o))
        except:
            player_o_name = "Игрок O"
    else:
        player_o_name = "Ожидание соперника..."
    
    new_turn = game["turn"]
    turn_symbol = "❌" if new_turn == "X" else "⭕"
    turn_player = player_x_name if new_turn == "X" else player_o_name
    
    await callback.message.edit_text(
        premium(
            f"<b>❌⭕ Крестики-Нолики</b>\n\n"
            f"Ход: <b>{turn_symbol} ({turn_player})</b>\n"
            f"{ttt_board_to_text(board)}"
        ),
        parse_mode="HTML",
        reply_markup=ttt_keyboard(board, game_id)
    )
    await callback.answer()

# ==================== ОСТАЛЬНЫЕ CALLBACK ====================
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
            is_admin = (user_id == ADMIN_ID)
            main_text = premium(
                "<b>👋 Добро пожаловать в XrayGram!</b>\n\n"
                "<b>🤖 Что умеет бот:</b>\n"
                "<blockquote>Отслеживает удалённые сообщения в ваших личных чатах и присылает их копии.\n"
                "Показывает изменения в отредактированных сообщениях (было → стало).\n"
                "Сохраняет самоуничтожающиеся медиа.</blockquote>\n\n"
                "📋 Нажмите «Команды», чтобы узнать о дополнительных возможностях."
            )
            await bot.send_message(user_id, main_text, reply_markup=main_menu_keyboard(is_admin), parse_mode="HTML")
        await callback.answer("✅ Подписка подтверждена!", show_alert=True)
    else:
        await callback.answer("❌ Вы ещё не подписаны. Подпишитесь и нажмите снова.", show_alert=True)

async def show_instruction_logic(user_id: int):
    instruction_text = premium(
        "<b>📖 Инструкция по подключению XrayGram\n\n"
        "1️⃣ Убедитесь, что у вас есть подписка Телеграм Премиум.\n"
        "2️⃣ Откройте Настройки → Телеграм для бизнеса → Чат-боты.\n"
        "3️⃣ Нажмите Добавить бота и введите @XrayGramRobot.\n"
        "4️⃣ Добавьте все разрешения которые находятся на фото сверху.\n\n"
        "❓ Заметили ошибку? Бот завис? Долго грузит? Сообщите нам — поддержка отреагирует оперативно: @CryptoViktor.</b>"
    )
    try:
        if os.path.exists(INSTRUCTION_IMAGE_PATH):
            photo = FSInputFile(INSTRUCTION_IMAGE_PATH)
            await bot.send_photo(
                chat_id=user_id,
                photo=photo,
                caption=instruction_text,
                parse_mode="HTML",
                reply_markup=instruction_keyboard()
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=instruction_text,
                parse_mode="HTML",
                reply_markup=instruction_keyboard()
            )
    except Exception as e:
        logger.error(f"Ошибка отправки инструкции пользователю {user_id}: {e}")
        await bot.send_message(
            chat_id=user_id,
            text=instruction_text,
            parse_mode="HTML",
            reply_markup=instruction_keyboard()
        )

@dp.callback_query(lambda c: c.data == "show_instruction")
async def show_instruction(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not await is_subscribed(user_id):
        text = premium("<b>📢 Для доступа к инструкции необходимо подписаться на канал!\n\nПодпишитесь на @NovoeTelegram и нажмите «Проверить подписку».</b>")
        await callback.message.edit_text(text, reply_markup=subscription_keyboard("show_instruction"), parse_mode="HTML")
        await callback.answer()
        return

    await callback.message.delete()
    await show_instruction_logic(user_id)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "show_commands")
async def show_commands(callback: types.CallbackQuery):
    commands_text = premium(
        "<b>📋 Список доступных команд</b>\n\n"
        "<b>Эти команды работают в личных чатах, где активен бизнес-режим.</b>\n\n"
        "<blockquote>🔇 .mute – заглушить чат (собеседник получит уведомление, его сообщения будут удаляться).\n"
        "🔊 .unmute – размутить чат (сообщения снова сохраняются).\n"
        "💬 .spam &lt;число&gt; &lt;текст&gt; – отправить несколько одинаковых сообщений в чат.\n"
        "⚔️ .duel – начать дуэль с собеседником (случайный победитель).\n"
        "🔄 .anim &lt;текст&gt; – анимация текста (появление по буквам).\n"
        "❌⭕ .ttt – начать игру в крестики-нолики с СОБЕСЕДНИКОМ.</blockquote>\n\n"
        "<b>Примеры:</b>\n"
        "<blockquote>.mute\n"
        ".unmute\n"
        ".spam 5 Привет!\n"
        ".duel\n"
        ".anim Привет мир!\n"
        ".ttt</blockquote>\n\n"
        "❓ Остались вопросы? Пишите @CryptoViktor."
    )
    await safe_edit_or_send(callback.message, commands_text, commands_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_admin = (user_id == ADMIN_ID)
    main_text = premium(
        "<b>👋 Добро пожаловать в XrayGram!</b>\n\n"
        "<b>🤖 Что умеет бот:</b>\n"
        "<blockquote>Отслеживает удалённые сообщения в ваших личных чатах и присылает их копии.\n"
        "Показывает изменения в отредактированных сообщениях (было → стало).\n"
        "Сохраняет самоуничтожающиеся медиа.</blockquote>\n\n"
        "📋 Нажмите «Команды», чтобы узнать о дополнительных возможностях."
    )
    await safe_edit_or_send(callback.message, main_text, main_menu_keyboard(is_admin))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    text = premium("<b>⚙️ Админ-панель XrayGram\n\nВыберите действие:</b>")
    await safe_edit_or_send(callback.message, text, admin_panel_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    text = premium("<b>⚙️ Админ-панель XrayGram\n\nВыберите действие:</b>")
    await safe_edit_or_send(callback.message, text, admin_panel_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "broadcast")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.message.delete()
    text = premium("<b>📢 Введите текст или отправьте медиа для рассылки\n\nВсе зарегистрированные пользователи получат это сообщение.\nДля отмены нажмите кнопку ниже.</b>")
    await bot.send_message(callback.from_user.id, text, parse_mode="HTML", reply_markup=cancel_keyboard())
    await state.set_state(BroadcastStates.waiting_for_content)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_broadcast")
async def cancel_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await state.clear()
    await callback.message.delete()
    text = premium("<b>⚙️ Админ-панель XrayGram\n\nВыберите действие:</b>")
    await bot.send_message(callback.from_user.id, text, parse_mode="HTML", reply_markup=admin_panel_keyboard())
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
        await message.answer(premium("<b>📭 Нет зарегистрированных пользователей.</b>"), parse_mode="HTML")
        await state.clear()
        return

    sent = 0
    failed = 0
    for (user_id,) in users:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
            failed += 1

    result_text = premium(f"<b>✅ Рассылка завершена!\nОтправлено: {sent}\nНе удалось: {failed}</b>")
    await message.answer(result_text, parse_mode="HTML", reply_markup=back_to_admin_keyboard())
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
        await callback.message.answer(premium("<b>📭 Нет зарегистрированных пользователей.</b>"), parse_mode="HTML")
        await callback.answer()
        return

    content = "Список всех зарегистрированных пользователей XrayGram\n"
    content += f"Всего: {len(users)}\n"
    content += "=" * 50 + "\n\n"
    for user in users:
        user_id, username, first_name, last_name, reg_time = user
        name = f"{first_name or ''} {last_name or ''}".strip() or "Без имени"
        uname = f"@{username}" if username else f"ID: {user_id}"
        content += f"{name} ({uname})\n"
        content += f"ID: {user_id}\n"
        content += f"Зарегистрирован: {reg_time}\n"
        content += "-" * 30 + "\n"

    file_bytes = content.encode("utf-8")
    await callback.message.answer_document(
        BufferedInputFile(file_bytes, filename="users_list.txt"),
        caption=premium("<b>📄 Список всех пользователей (txt)</b>"),
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
    conn_users = cursor.fetchall()
    if not conn_users:
        text = premium("<b>🔗 Активные подключения\n\nНет пользователей с активным бизнес-подключением.</b>")
    else:
        user_ids = [row[0] for row in conn_users]
        placeholders = ",".join("?" for _ in user_ids)
        cursor.execute(f"SELECT user_id, username, first_name, last_name FROM users WHERE user_id IN ({placeholders})", user_ids)
        users = cursor.fetchall()
        lines = [f"• {u[2] or ''} {u[3] or ''} (@{u[1]}) - ID: {u[0]}" for u in users]
        text = premium(f"<b>🔗 Активные подключения ({len(users)})\n\n" + "\n".join(lines) + "</b>")

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_admin_keyboard())
    await callback.answer()

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

    # ========== ВСЕ КОМАНДЫ ВЛАДЕЛЬЦА ==========
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

@dp.edited_business_message()
async def handle_edited_business_message(message: types.Message):
    bc_id = message.business_connection_id
    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id or not db.is_user_registered(user_id):
        return

    chat_id = message.chat.id
    if db.is_chat_muted(user_id, chat_id):
        return

    msg_id = message.message_id
    new_text = message.text or message.caption or ""

    old_data = db.get_message(bc_id, msg_id)
    if not old_data:
        return

    old_text = old_data["text"] or ""
    old_fullname = old_data["fullname"]

    if new_text.strip() == old_text.strip():
        return

    db.update_message_text(bc_id, msg_id, new_text)

    new_sender = message.from_user
    if new_sender:
        new_fullname = format_user_info(new_sender)
        if new_fullname != old_fullname:
            db.update_message_fullname(bc_id, msg_id, new_fullname)
            old_fullname = new_fullname

    files = old_data["files"]
    if files:
        files_list = json.loads(files) if isinstance(files, str) else files
    else:
        files_list = []

    notif_text = premium(f"<b>✏️ Сообщение изменено от {old_fullname}\n\nБыло: {old_text}\nСтало: {new_text}</b>")
    await send_notification(user_id, notif_text, files_list)

@dp.deleted_business_messages()
async def handle_deleted_business_messages(event: BusinessMessagesDeleted):
    bc_id = event.business_connection_id
    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id or not db.is_user_registered(user_id):
        return

    for msg_id in event.message_ids:
        data = db.get_message(bc_id, msg_id)
        if not data:
            continue
        fullname = data["fullname"]
        text = data["text"] or ""
        files = data["files"]
        if files:
            files_list = json.loads(files) if isinstance(files, str) else files
        else:
            files_list = []

        notif_text = premium(f"<b>❌ Сообщение удалено от {fullname}\n\n{text}</b>") if text else premium(f"<b>❌ Сообщение удалено от {fullname}</b>")
        await send_notification(user_id, notif_text, files_list)

        db.delete_message(bc_id, msg_id)

async def main():
    try:
        me = await bot.get_me()
        logger.info(f"✅ Бот успешно запущен: @{me.username}")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Telegram API: {e}")
        raise

    await bot.set_my_commands([
        types.BotCommand(command="start", description=premium("Главное меню"))
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
            break
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
            break
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            logger.info("Перезапуск через 15 секунд...")
            time.sleep(15)
