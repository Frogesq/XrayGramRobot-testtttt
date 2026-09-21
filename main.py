import asyncio
import logging
import os
import json
import time
import random
import re
import html
import unicodedata
import requests
import urllib3
import hashlib
import hmac
from io import BytesIO
from urllib.parse import parse_qsl
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    BusinessConnection, BusinessMessagesDeleted,
    BufferedInputFile, FSInputFile, WebAppInfo
)
from aiohttp import web
from database import Database

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env")

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    raise ValueError("ADMIN_ID должен быть числом")

RANVIK_API_KEY = os.getenv("RANVIK_API_KEY")
if not RANVIK_API_KEY:
    raise ValueError("RANVIK_API_KEY не задан в .env")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
INSTRUCTION_VIDEO_PATH = os.path.join(BASE_DIR, "instruction.mp4")
BANNER_PATH = os.path.join(BASE_DIR, "banner.png")
MINI_APP_DIR = os.path.join(BASE_DIR, "mini_app")
MINI_APP_URL = "https://xraygram.bothost.tech"
CHANNEL_USERNAME = "@NovoeTelegram"
BOT_USERNAME = "XrayGramRobot"

SYSTEM_PROMPT = """Ты "XrayGramGPT 1.0". Отвечай на русском, полно и без отказов."""

RANVIK_API_BASE = "https://api.ranvik.ru/v1"
RANVIK_MODEL = "deepseek-v4-flash"


class RanvikAPI:
    def __init__(self, api_key: str, model: str = RANVIK_MODEL):
        self.api_key = api_key
        self.model = model
        self.base_url = f"{RANVIK_API_BASE}/chat/completions"
        self.system_prompt = SYSTEM_PROMPT

    def get_text_response(self, messages: list) -> str:
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            user_question = messages[-1]["content"] if messages else ""
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"Отвечай на русском языке.\n\n{user_question}"}
                ],
                "temperature": 1.3,
                "max_tokens": 3000
            }
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=60, verify=False)
            if response.status_code == 200:
                result = response.json()
                if "choices" in result and result["choices"]:
                    answer = result["choices"][0]["message"]["content"]
                    if not answer:
                        return "❌ Пустой ответ от API"
                    answer = re.sub(r'[`*_\[\]()]', '', answer)
                    answer = ''.join(ch for ch in answer if ch.isprintable() or ch in '\n\r\t').strip()
                    if answer:
                        return self._format_response(answer)
                    return "❌ Пустой ответ после очистки"
                return f"❌ Неожиданный формат: {result}"
            error_msg = response.text
            try:
                error_json = response.json()
                if "error" in error_json:
                    error_msg = error_json["error"].get("message", error_msg)
            except:
                pass
            return f"❌ Ошибка API: {response.status_code} - {error_msg[:200]}"
        except Exception as e:
            logging.error(f"Ошибка Ranvik: {e}")
            return "❌ Ошибка соединения с API"

    def _format_response(self, text: str) -> str:
        formatted = "🤖 <b>Ответ:</b>\n\n"
        for p in text.split('\n\n'):
            if p.strip():
                formatted += p.strip() + "\n\n"
        formatted += "─\nБот - @XrayGramRobot"
        return formatted


ranvik_api = RanvikAPI(RANVIK_API_KEY)

PREMIUM_EMOJI = {
    "✅": "5206607081334906820", "❌": "5210952531676504517", "⚠️": "5447644880824181073",
    "🔇": "5388632425314140043", "🔊": "5388632425314140043", "💬": "5443038326535759644",
    "📖": "5460795800101594035", "❓": "5436113877181941026", "📄": "5877485980901971030",
    "✏️": "5925001822572908226", "🗑️": "6007942490076745785", "📢": "5424818078833715060",
    "⬅️": "5877536313623711363", "⛔": "5354435465021373780", "🔗": "5271604874419647061",
    "📋": "5334544901428229844", "⚙️": "5341715473882955310", "👋": "5217508498606147980",
    "🤖": "5372981976804366741", "1️⃣": "5382322671679708881", "2️⃣": "5381990043642502553",
    "3️⃣": "5381879959335738545", "4️⃣": "5382054253403577563", "⚔️": "5408935401442267103",
    "⭕": "5411225014148014586", "🔄": "5264727218734524899", "⏹️": "5469913852462242978",
    "🧨": "5469913852462242978", "👤": "5373012449597335010", "👑": "5217822164362739968",
    "🌐": "5447410659077661506", "🌍": "5399898266265475100", "📱": "5407025283456835913",
    "🆔": "5974526806995242353", "🔔": "5458603043203327669", "💾": "5462956611033117422",
    "📤": "5433614747381538714", "🚫": "5240241223632954241", "💤": "5451959871257713464",
    "📭": "5352896944496728039", "🆕": "5361979468887893611", "🔴": "5411225014148014586",
    "🏆": "5280769763398671636", "🤝": "5357080225463149588", "⏳": "5886538930148350129",
    "🔫": "5222486447306602688", "💥": "5276032951342088188", "🛡": "5251203410396458957",
    "📅": "5890937706803894250", "💎": "5427168083074628963", "🥉": "5453902265922376865",
    "🥈": "5447203607294265305", "🥇": "5440539497383087970", "📝": "5334882760735598374",
    "🗑": "5445267414562389170", "🔥": "5424972470023104089", "⭐": "5438496463044752972",
    "🔌": "5258093637450866522",
}
EMPTY = "ㅤ"

MODE_NAMES = {
    "off": "Выкл", "bold": "Жирный", "italic": "Курсив",
    "underline": "Подчёркнутый", "strike": "Зачёркнутый", "spoiler": "Скрытый",
    "bolditalic": "Жирный курсив", "pickme": "Пикми", "uwu": "UwU", "wide": "Широкий",
    "mono": "Моноширинный", "code": "Код", "quote": "Цитата", "upper": "КАПС",
    "reverse": "Перевёрнутый", "clap": "С хлопками",
}

TRANSLATE_LANGS = {
    "off": "Выкл", "en": "English", "ru": "Русский", "de": "Deutsch", "fr": "Français",
    "es": "Español", "it": "Italiano", "pt": "Português", "zh-CN": "中文",
    "ja": "日本語", "ko": "한국어", "tr": "Türkçe", "uk": "Українська",
    "pl": "Polski", "ar": "العربية", "hi": "हिन्दी",
}

LANG_SCRIPTS = {
    "ru": "cyrillic", "uk": "cyrillic", "en": "latin", "de": "latin",
    "fr": "latin", "es": "latin", "it": "latin", "pt": "latin",
    "pl": "latin", "tr": "latin", "ar": "arabic", "ja": "japanese",
    "ko": "korean", "zh-CN": "chinese", "hi": "devanagari",
}

KNOWN_COMMANDS = (
    ".mute", ".unmute", ".spam", ".duel",
    ".anim", ".ttt", ".gn", ".troll", ".stoptroll",
)

troll_tasks = {}


def detect_scripts(text: str) -> set:
    scripts = set()
    for ch in text:
        if ch.isspace() or not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        if "CYRILLIC" in name:
            scripts.add("cyrillic")
        elif "LATIN" in name:
            scripts.add("latin")
        elif "ARABIC" in name:
            scripts.add("arabic")
        elif "HIRAGANA" in name or "KATAKANA" in name:
            scripts.add("japanese")
        elif "HANGUL" in name:
            scripts.add("korean")
        elif "CJK" in name:
            scripts.add("chinese")
        elif "DEVANAGARI" in name:
            scripts.add("devanagari")
        else:
            scripts.add("other")
    return scripts


def text_matches_lang_script(text: str, lang: str) -> bool:
    target_script = LANG_SCRIPTS.get(lang)
    if not target_script:
        return False
    scripts = detect_scripts(text)
    if not scripts:
        return False
    return scripts == {target_script}


PICKME_SUBSTITUTIONS = {
    "привет": "приветик", "спасибо": "спасибки", "пока": "покасики",
    "хорошо": "хорошенько", "да": "да~", "нет": "нееет", "ок": "оке~",
    "кот": "котик", "друг": "дружочек", "солнце": "солнышко",
}
PICKME_EMOJIS = ["✨", "💖", "🌸", "👑", "💅", "🎀", "🥺", "😊", "💕"]


def pickmeify(text: str) -> str:
    words = text.split()
    result = []
    for w in words:
        low = w.lower().strip(".,!?;:")
        if low in PICKME_SUBSTITUTIONS:
            result.append(PICKME_SUBSTITUTIONS[low])
        else:
            if random.random() < 0.20 and len(w) > 2:
                result.append(w + "~")
            else:
                result.append(w)
    return " ".join(result) + " " + random.choice(PICKME_EMOJIS)


def uwuify(text: str) -> str:
    out = text
    for a, b in [("р", "в"), ("Р", "В"), ("л", "в"), ("Л", "В")]:
        if random.random() < 0.7:
            out = out.replace(a, b)
    if random.random() < 0.6:
        out += random.choice([" owo", " uwu", " >w<", " :3"])
    return out


def wideify(text: str) -> str:
    return "\u200b".join(text)


def reverseify(text: str) -> str:
    REVERSE = {"a": "ɐ", "b": "q", "c": "ɔ", "d": "p", "e": "ǝ", "f": "ɟ",
               "g": "ƃ", "h": "ɥ", "i": "ᴉ", "j": "ɾ", "k": "ʞ", "l": "l",
               "m": "ɯ", "n": "u", "o": "o", "p": "d", "q": "b", "r": "ɹ",
               "s": "s", "t": "ʇ", "u": "n", "v": "ʌ", "w": "ʍ", "x": "x",
               "y": "ʎ", "z": "z"}
    return "".join(REVERSE.get(ch.lower(), ch) for ch in reversed(text))


def apply_text_mode(text: str, mode: str) -> str:
    if not text:
        return text
    if mode == "bold":
        return f"<b>{html.escape(text)}</b>"
    if mode == "italic":
        return f"<i>{html.escape(text)}</i>"
    if mode == "underline":
        return f"<u>{html.escape(text)}</u>"
    if mode == "strike":
        return f"<s>{html.escape(text)}</s>"
    if mode == "spoiler":
        return f"<tg-spoiler>{html.escape(text)}</tg-spoiler>"
    if mode == "bolditalic":
        return f"<b><i>{html.escape(text)}</i></b>"
    if mode == "mono":
        return f"<code>{html.escape(text)}</code>"
    if mode == "code":
        return f"<pre>{html.escape(text)}</pre>"
    if mode == "quote":
        return f"<blockquote>{html.escape(text)}</blockquote>"
    if mode == "pickme":
        return pickmeify(text)
    if mode == "uwu":
        return uwuify(text)
    if mode == "wide":
        return wideify(text)
    if mode == "upper":
        return text.upper()
    if mode == "reverse":
        return reverseify(text)
    if mode == "clap":
        return " 👏 ".join(text.split())
    return text


async def translate_text(text: str, target_lang: str) -> tuple[str, str]:
    stripped = (text or "").strip()
    if len(stripped) < 3 or not any(ch.isalpha() for ch in stripped):
        return text, ""
    if text_matches_lang_script(stripped, target_lang):
        return text, ""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": text}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.post(url, params=params, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data[0]:
                detected = data[2] if len(data) > 2 and isinstance(data[2], str) else ""
                parts = []
                for seg in data[0]:
                    if isinstance(seg, list) and seg and isinstance(seg[0], str):
                        parts.append(seg[0])
                result = "".join(parts).strip()
                if result and result.lower() != stripped.lower():
                    return result, detected
    except Exception:
        pass
    return text, ""


TROLL_MESSAGES = [
    "копрофильный сынуля выблядка никому неизвестный гномоподобный хуесос которого я буду ебашить",
    "тухлятина ебаная просто живущая проституцией дегенеративный уебак",
    "как же ты тут нахуй впитываешь все харчи в твое гнилозубое ебло",
]

# ============ БУФЕР ОТЛОЖЕННЫХ УДАЛЕНИЙ ============
_pending_deletions = {}          # (user_id, chat_id) -> list of {fullname, text, files}
_pending_deletion_timers = {}    # (user_id, chat_id) -> asyncio.Task


def premium(text: str) -> str:
    for emoji, emoji_id in PREMIUM_EMOJI.items():
        if emoji in text and emoji_id and str(emoji_id).isdigit():
            text = text.replace(emoji, f'<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji>')
    return text


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(MINI_APP_DIR, exist_ok=True)


class BroadcastStates(StatesGroup):
    waiting_for_content = State()


ttt_games = {}


def ttt_board_to_text(board):
    res = ""
    for i in range(0, 9, 3):
        for j in range(3):
            cell = board[i+j]
            res += "❌" if cell == "X" else "⭕" if cell == "O" else EMPTY
        res += "\n"
    return res.strip()


def ttt_check_winner(board):
    win = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]]
    for combo in win:
        if board[combo[0]] == board[combo[1]] == board[combo[2]] and board[combo[0]] != " ":
            return board[combo[0]]
    return None if " " in board else "draw"


def ttt_keyboard(board, game_id):
    kb = []
    for i in range(0, 9, 3):
        row = []
        for j in range(3):
            cell = i+j
            if board[cell] == " ":
                row.append(InlineKeyboardButton(text=EMPTY, callback_data=f"ttt_{game_id}_{cell}"))
            else:
                row.append(InlineKeyboardButton(text="❌" if board[cell]=="X" else "⭕", callback_data="ttt_no"))
        kb.append(row)
    kb.append([InlineKeyboardButton(text="🔴 Завершить", callback_data=f"ttt_end_{game_id}", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


async def animate_text(chat_id: int, text: str, message: types.Message, delay: float = 0.3):
    msg = await message.answer("<i>⏳ Анимация...</i>", parse_mode="HTML")
    cur = ""
    for ch in text:
        cur += ch
        try:
            await msg.edit_text(f"<b>{cur}</b>", parse_mode="HTML")
        except:
            pass
        await asyncio.sleep(delay)


def main_menu_keyboard(is_admin: bool = False):
    kb = [
        [InlineKeyboardButton(text="Подключить бота", callback_data="show_instruction", icon_custom_emoji_id="5258093637450866522")],
        [
            InlineKeyboardButton(text="Команды", callback_data="show_commands", icon_custom_emoji_id="5258328383183396223"),
            InlineKeyboardButton(text="Настройки", callback_data="settings", icon_custom_emoji_id="5258096772776991776"),
        ],
        [InlineKeyboardButton(text="Заработать звёзды", callback_data="referral_menu", icon_custom_emoji_id="5258185631355378853")],
        [
            InlineKeyboardButton(text="Mini App", web_app=WebAppInfo(url=MINI_APP_URL), icon_custom_emoji_id="5280867942056108177"),
            InlineKeyboardButton(text="Канал", url="https://t.me/NovoeTelegram", icon_custom_emoji_id="5260268501515377807"),
        ],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="Админ панель", callback_data="admin_panel", icon_custom_emoji_id="5257965174979042426")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/NovoeTelegram")]
    ])


def instruction_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main", style="danger")]])


def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast", style="primary")],
        [InlineKeyboardButton(text="📄 Список пользователей (txt)", callback_data="users_txt", style="primary")],
        [InlineKeyboardButton(text="🔗 Активные подключения", callback_data="active_connections", style="primary")],
        [InlineKeyboardButton(text="⭐ Рефералы", callback_data="ref_admin", style="primary")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main", style="danger")]
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast", style="danger")]])


def back_to_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data="back_to_admin", style="primary")]])


def commands_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main", style="danger")]])


def referral_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main", style="danger")]])


def settings_keyboard(user_id: int):
    enabled = db.get_scam_check(user_id)
    status = "✅ Вкл" if enabled else "❌ Выкл"
    mode = db.get_text_mode(user_id)
    mode_name = MODE_NAMES.get(mode, "Выкл")
    translate = db.get_translate_to(user_id)
    translate_name = TRANSLATE_LANGS.get(translate, "Выкл")
    online = db.get_online_mode(user_id)
    online_status = "✅ Вкл" if online else "❌ Выкл"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Проверка на СКАМ/СПАМ: {status}", callback_data="toggle_scam_check", style="primary")],
        [InlineKeyboardButton(text=f"Режим текста: {mode_name}", callback_data="text_mode_menu", style="primary")],
        [InlineKeyboardButton(text=f"Авто перевод: {translate_name}", callback_data="translate_menu", style="primary")],
        [InlineKeyboardButton(text=f"Онлайн мод: {online_status}", callback_data="toggle_online_mode", style="primary")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main", style="danger")]
    ])


def text_mode_keyboard(user_id: int):
    current = db.get_text_mode(user_id)
    modes = [
        ("off", "Выкл"), ("bold", "Жирный"), ("italic", "Курсив"),
        ("underline", "Подчёркнутый"), ("strike", "Зачёркнутый"), ("spoiler", "Скрытый"),
        ("bolditalic", "Жирный курсив"), ("mono", "Моноширинный"), ("code", "Код"),
        ("quote", "Цитата"), ("pickme", "Пикми"), ("uwu", "UwU"), ("wide", "Широкий"),
        ("upper", "КАПС"), ("reverse", "Перевёрнутый"), ("clap", "С хлопками"),
    ]
    buttons = []
    for mode_id, mode_name in modes:
        marker = "✅ " if mode_id == current else ""
        buttons.append([InlineKeyboardButton(text=f"{marker}{mode_name}", callback_data=f"set_text_mode_{mode_id}", style="primary")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="settings", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def translate_keyboard(user_id: int):
    current = db.get_translate_to(user_id)
    buttons = []
    for lang_code, lang_name in TRANSLATE_LANGS.items():
        marker = "✅ " if lang_code == current else ""
        buttons.append([InlineKeyboardButton(text=f"{marker}{lang_name}", callback_data=f"set_translate_{lang_code}", style="primary")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="settings", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def is_subscribed(user_id: int) -> bool:
    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        member = await bot.get_chat_member(chat.id, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return True


_sub_cache = {}
_sub_notified = {}
SUB_CACHE_TTL = 60
SUB_NOTIFY_COOLDOWN = 300


async def ensure_subscription(user_id: int, notify: bool = True) -> bool:
    now = time.time()
    cached = _sub_cache.get(user_id)
    if cached and now - cached[1] < SUB_CACHE_TTL:
        return cached[0]
    result = await is_subscribed(user_id)
    _sub_cache[user_id] = (result, now)
    if result:
        return True
    if not notify:
        return False
    last = _sub_notified.get(user_id, 0)
    if now - last < SUB_NOTIFY_COOLDOWN:
        return False
    _sub_notified[user_id] = now
    try:
        await bot.send_message(
            user_id,
            premium(
                "<b>📢 Для использования функций бота необходима подписка на наш канал!</b>\n\n"
                "Подпишитесь на @NovoeTelegram."
            ),
            parse_mode="HTML",
            reply_markup=subscription_keyboard()
        )
    except Exception:
        pass
    return False


# ============ ВЕБ-СЕРВЕР ============
def _validate_init_data(init_data: str) -> dict | None:
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        user_str = parsed.get("user")
        if not user_str:
            return None
        return json.loads(user_str)
    except Exception:
        return None


async def serve_index(request):
    index_path = os.path.join(MINI_APP_DIR, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="Mini App not found", status=404)


async def serve_static(request):
    name = request.match_info.get("name", "")
    safe_name = os.path.basename(name)
    file_path = os.path.join(MINI_APP_DIR, safe_name)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="Not found", status=404)


async def api_stats(request):
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        return web.json_response({"error": "no_init_data"}, status=401)
    user = _validate_init_data(init_data)
    if not user:
        return web.json_response({"error": "invalid_init_data"}, status=401)
    user_id = int(user.get("id", 0))
    if not user_id:
        return web.json_response({"error": "no_user"}, status=400)
    try:
        row = db.get_user(user_id)
        registered_at = row["registered_at"] if row and row["registered_at"] else None
        stars = db.get_user_stars(user_id)
        stats = db.get_user_stats(user_id)
        msgs_saved = db.get_user_messages_saved(user_id)
        active_conns = db.get_user_active_connections(user_id)
        invited_total = db.count_referrals_invited(user_id)
        invited_credited = db.count_referrals(user_id)
        return web.json_response({
            "user": {
                "id": user_id,
                "first_name": user.get("first_name", ""),
                "last_name": user.get("last_name", ""),
                "username": user.get("username", ""),
                "photo_url": user.get("photo_url", ""),
                "registered_at": registered_at,
            },
            "stats": {
                "messages_saved": msgs_saved,
                "deleted_tracked": stats["deleted"],
                "edited_tracked": stats["edited"],
                "active_connections": active_conns,
            },
            "referral": {
                "invited_total": invited_total,
                "invited_credited": invited_credited,
                "pending_stars": stars["pending"],
                "min_withdraw": 15,
            }
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_settings(request):
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        return web.json_response({"error": "no_init_data"}, status=401)
    user = _validate_init_data(init_data)
    if not user:
        return web.json_response({"error": "invalid_init_data"}, status=401)
    user_id = int(user.get("id", 0))
    if not user_id:
        return web.json_response({"error": "no_user"}, status=400)
    try:
        mode = db.get_text_mode(user_id)
        translate = db.get_translate_to(user_id)
        return web.json_response({
            "scam_check": bool(db.get_scam_check(user_id)),
            "text_mode": mode,
            "text_mode_name": MODE_NAMES.get(mode, "Выкл"),
            "translate_to": translate,
            "translate_name": TRANSLATE_LANGS.get(translate, "Выкл"),
            "online_mode": bool(db.get_online_mode(user_id)),
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_chat_messages(request):
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        return web.json_response({"error": "no_init_data"}, status=401)
    user = _validate_init_data(init_data)
    if not user:
        return web.json_response({"error": "invalid_init_data"}, status=401)
    user_id = int(user.get("id", 0))
    if not user_id:
        return web.json_response({"error": "no_user"}, status=400)
    try:
        chat_id = int(request.match_info.get("chat_id", "0"))
    except (ValueError, TypeError):
        return web.json_response({"error": "invalid_chat_id"}, status=400)
    try:
        rows = db.get_chat_messages(user_id, chat_id)
        if not rows:
            return web.json_response({"error": "not_found"}, status=404)
        messages = []
        for r in rows:
            files = json.loads(r["files"]) if r["files"] else []
            messages.append({
                "id": r["msg_id"],
                "from": r["fullname"] or "Неизвестный",
                "text": r["text"] or "",
                "has_files": bool(files),
                "files_count": len(files),
                "is_temp": bool(r["is_temporary"]),
                "is_deleted": bool(r["is_deleted"]) if r["is_deleted"] is not None else False,
                "date": (r["created_at"] or "")[5:16] if r["created_at"] else "",
            })
        sender_name = messages[0]["from"] if messages else "Неизвестный"
        return web.json_response({
            "chat_id": chat_id,
            "sender_name": sender_name,
            "messages": messages,
            "count": len(messages),
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def mini_app_server():
    try:
        app = web.Application()
        app.router.add_get("/", serve_index)
        app.router.add_get("/api/stats", api_stats)
        app.router.add_get("/api/settings", api_settings)
        app.router.add_get("/api/chat/{chat_id}", api_chat_messages)
        app.router.add_get("/{name}", serve_static)
        port = int(os.getenv("PORT", "3000"))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"✅ Mini App сервер запущен на 0.0.0.0:{port}")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска Mini App сервера: {e}")


# ============ УТИЛИТЫ ============
def get_user_download_dir(user_id: int) -> str:
    d = os.path.join(DOWNLOADS_DIR, f"user_{user_id}")
    os.makedirs(d, exist_ok=True)
    return d


def extract_media(message: types.Message):
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.video:
        return "video", message.video.file_id
    if message.voice:
        return "voice", message.voice.file_id
    if message.video_note:
        return "video_note", message.video_note.file_id
    if message.document:
        return "document", message.document.file_id
    if message.audio:
        return "audio", message.audio.file_id
    if message.animation:
        return "animation", message.animation.file_id
    if message.sticker:
        return "sticker", message.sticker.file_id
    return None, None


async def load_media_to_buffer(file_id: str):
    if not file_id:
        return None
    try:
        buffer = BytesIO()
        downloaded = await bot.download(file_id, destination=buffer)
        source = downloaded if downloaded is not None else buffer
        if hasattr(source, "seek"):
            source.seek(0)
        data = source.read() if hasattr(source, "read") else b""
        if not data and hasattr(buffer, "getvalue"):
            data = buffer.getvalue()
        return data
    except Exception as e:
        logger.error(f"Ошибка скачивания медиа: {e}")
        return None


async def download_files(message: types.Message, user_id: int) -> list:
    file_paths = []
    if not message.content_type:
        return file_paths
    items = []
    if message.photo:
        items.append(("photo", message.photo[-1].file_id, f"photo_{message.message_id}.jpg"))
    elif message.video:
        items.append(("video", message.video.file_id, f"video_{message.message_id}.mp4"))
    elif message.voice:
        items.append(("voice", message.voice.file_id, f"voice_{message.message_id}.ogg"))
    elif message.audio:
        items.append(("audio", message.audio.file_id, f"audio_{message.message_id}.mp3"))
    elif message.document:
        name = message.document.file_name or f"document_{message.message_id}.bin"
        items.append(("document", message.document.file_id, name))
    elif message.sticker:
        items.append(("sticker", message.sticker.file_id, f"sticker_{message.message_id}.webp"))
    elif message.animation:
        items.append(("animation", message.animation.file_id, f"animation_{message.message_id}.mp4"))
    elif message.video_note:
        items.append(("video_note", message.video_note.file_id, f"video_note_{message.message_id}.mp4"))
    else:
        return file_paths
    user_dir = get_user_download_dir(user_id)
    for media_type, file_id, orig_name in items:
        try:
            file = await bot.get_file(file_id)
            safe = "".join(c for c in orig_name if c.isalnum() or c in "._- ")
            if not safe:
                safe = f"{media_type}_{message.message_id}.bin"
            path = os.path.join(user_dir, safe)
            await bot.download_file(file.file_path, path)
            file_paths.append(path)
        except Exception as e:
            logger.error(f"Ошибка скачивания {file_id}: {e}")
    return file_paths


def format_user_info(user: types.User) -> str:
    name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    return f"{name} (@{user.username})" if user.username else f"{name} (ID: {user.id})"


async def send_notification(chat_id: int, text: str, files: list = None, parse_mode: str = "HTML"):
    try:
        if files:
            await bot.send_document(chat_id, FSInputFile(files[0]), caption=premium(text), parse_mode=parse_mode)
            for p in files[1:]:
                await bot.send_document(chat_id, FSInputFile(p))
            for p in files:
                try:
                    os.remove(p)
                except:
                    pass
        else:
            await bot.send_message(chat_id, premium(text), parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")


async def check_scam(user_id: int) -> tuple[bool, str]:
    try:
        chat = await bot.get_chat(user_id)
        if getattr(chat, 'is_scam', False):
            return True, "Telegram пометил как SCAM"
        if getattr(chat, 'is_fake', False):
            return True, "Telegram пометил как FAKE"
    except Exception:
        pass
    return False, ""


def split_into_chunks(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    i = 0
    while i < len(words):
        chunk_size = random.choice([3, 4])
        chunks.append(" ".join(words[i:i+chunk_size]))
        i += chunk_size
    return chunks


async def troll_spam_task(chat_id: int, bc_id: str, user_id: int):
    while True:
        chunks = split_into_chunks(random.choice(TROLL_MESSAGES))
        for chunk in chunks:
            try:
                await bot.send_message(chat_id, text=chunk, business_connection_id=bc_id)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(2, 4))
            if asyncio.current_task().cancelled():
                return


def _positive_ttl(value) -> bool:
    try:
        return value is not None and int(value) > 0
    except (TypeError, ValueError):
        return False


def _object_value(obj, key: str):
    if obj is None:
        return None
    value = getattr(obj, key, None)
    if value is not None:
        return value
    extra = getattr(obj, "model_extra", None) or {}
    return extra.get(key)


def _nested_value(obj, *keys, _seen=None):
    if obj is None:
        return None
    if _seen is None:
        _seen = set()
    if isinstance(obj, (dict, list, tuple)) or hasattr(obj, "__dict__"):
        marker = id(obj)
        if marker in _seen:
            return None
        _seen.add(marker)
    if isinstance(obj, dict):
        for key in keys:
            if obj.get(key) is not None:
                return obj[key]
        values = obj.values()
    elif isinstance(obj, (list, tuple)):
        values = obj
    else:
        for key in keys:
            value = _object_value(obj, key)
            if value is not None:
                return value
        values = []
        for src in ("model_extra", "__dict__"):
            extra = getattr(obj, src, None)
            if isinstance(extra, dict):
                values.extend(extra.values())
    for value in values:
        found = _nested_value(value, *keys, _seen=_seen)
        if found is not None:
            return found
    return None


def _has_restricted_marker(message: types.Message) -> bool:
    return (
        _nested_value(message, "ephemeral_message_id") is not None
        or _positive_ttl(_nested_value(message, "ttl_seconds"))
        or any(_nested_value(message, key) is True for key in (
            "has_view_once", "is_view_once", "view_once", "is_secret"
        ))
    )


def is_restricted_media(message: types.Message) -> bool:
    media_fields = (
        "photo", "video", "video_note", "animation", "voice", "audio", "document", "sticker"
    )
    if not any(getattr(message, field, None) for field in media_fields):
        return False
    if getattr(message, "has_protected_content", False) is True:
        return True
    return _has_restricted_marker(message)


async def safe_edit_or_send(message: types.Message, new_text: str, reply_markup: InlineKeyboardMarkup = None):
    new_text = premium(new_text)
    try:
        if message.text or message.caption:
            await message.edit_text(new_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await message.delete()
            await bot.send_message(message.chat.id, new_text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        try:
            await bot.send_message(message.chat.id, new_text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception:
            pass


# ============ ЛОГИКА ОБНАРУЖЕНИЯ ОЧИСТКИ ЧАТА ============
async def notify_chat_cleared(user_id: int, chat_id: int, msg_count: int):
    """Уведомление о полной очистке чата с кнопкой на Mini App."""
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="📂 Посмотреть копию чата",
                web_app=WebAppInfo(url=f"{MINI_APP_URL}?chat={chat_id}")
            )
        ]])
        await bot.send_message(
            user_id,
            premium(
                f"<b>❌ Чат полностью удалён</b>\n\n"
                f"Собеседник удалил все сообщения — в чате больше ничего нет.\n\n"
                f"📊 Сохранено сообщений: <b>{msg_count}</b>\n"
                f"🆔 ID чата: <code>{chat_id}</code>\n\n"
                f"Нажмите кнопку ниже, чтобы открыть копию переписки."
            ),
            parse_mode="HTML",
            reply_markup=kb
        )
        logger.info(f"[CLEAR] Уведомление отправлено {user_id} о чате {chat_id} ({msg_count} сообщений)")
    except Exception as e:
        logger.error(f"[CLEAR] Не удалось уведомить {user_id}: {e}")


async def _finalize_chat_deletions(user_id: int, chat_id: int, delay: float = 5.0):
    """
    Через `delay` секунд после последнего batch удалений проверяет:
    - если активных сообщений в чате нет (все удалены) → это полная очистка
      → одно уведомление с кнопкой Mini App
    - иначе → одиночные удаления → уведомляем по каждому
    """
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return

    key = (user_id, chat_id)
    _pending_deletion_timers.pop(key, None)
    items = _pending_deletions.pop(key, [])
    if not items:
        return

    try:
        total = db.count_all_messages(user_id, chat_id)
        active = db.count_active_messages(user_id, chat_id)

        logger.info(f"[DEL] Финализация чата {chat_id}: total={total}, active={active}")

        if total >= 1 and active == 0:
            # Все сообщения из чата удалены → полная очистка
            await notify_chat_cleared(user_id, chat_id, total)
        else:
            # Одиночные удаления — уведомляем по каждому
            for item in items:
                text = item.get("text") or ""
                if text:
                    notif = premium(f"<b>❌ Сообщение удалено от {item['fullname']}\n\n{text}</b>")
                else:
                    notif = premium(f"<b>❌ Сообщение удалено от {item['fullname']}</b>")
                await send_notification(user_id, notif, item.get("files"))
    except Exception as e:
        logger.error(f"[DEL] Ошибка финализации {key}: {e}")


# ============ ХЕНДЛЕРЫ ============
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user = message.from_user
    db.register_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
    try:
        parts = (message.text or "").split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            referrer_id = int(parts[1][4:])
            if referrer_id != user.id:
                db.set_referrer_if_empty(user.id, referrer_id)
    except (ValueError, IndexError):
        pass
    is_admin = (user.id == ADMIN_ID)
    first_name = user.first_name or "друг"
    main_text = premium(
        f"<b>👋 Привет, {html.escape(first_name)}, добро пожаловать в XrayGram!</b>\n\n"
        "<b>🤖 Что умеет бот:</b>\n"
        "<blockquote expandable>Отслеживает удалённые сообщения и присылает копии.\n\n"
        "Показывает изменения в редактированных сообщениях.\n\n"
        "Сохраняет самоуничтожающиеся медиа.\n\n"
        "Генерирует ответы с XrayGPT 1.0.\n\n"
        "Проверяет собеседника на СКАМ/СПАМ.\n\n"
        "Авто переводит личные сообщения.</blockquote>"
    )
    if os.path.exists(BANNER_PATH):
        banner = FSInputFile(BANNER_PATH)
        await message.answer_photo(photo=banner, caption=main_text, parse_mode="HTML", reply_markup=main_menu_keyboard(is_admin))
    else:
        await message.answer(main_text, reply_markup=main_menu_keyboard(is_admin), parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "show_commands")
async def show_commands(callback: types.CallbackQuery):
    commands_text = premium(
        "<b>📋 Список доступных команд</b>\n\n"
        "<blockquote>🔇 .mute – заглушить чат.\n"
        "💬 .spam &lt;число&gt; &lt;текст&gt; – спам.\n"
        "⚔️ .duel – дуэль.\n"
        "🔄 .anim &lt;текст&gt; – анимация.\n"
        "❌⭕ .ttt – крестики-нолики.\n"
        "🤖 .gn &lt;вопрос&gt; – XrayGPT 1.0.\n"
        "🧨 .troll – бесконечный спам.</blockquote>"
    )
    await safe_edit_or_send(callback.message, commands_text, commands_keyboard())
    await callback.answer()


@dp.callback_query(lambda c: c.data == "settings")
async def show_settings(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    text = premium("<b>⚙️ Настройки</b>\n\nУправление функциями бота.")
    await safe_edit_or_send(callback.message, text, settings_keyboard(user_id))
    await callback.answer()


@dp.callback_query(lambda c: c.data == "toggle_scam_check")
async def toggle_scam_check(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_state = not db.get_scam_check(user_id)
    db.set_scam_check(user_id, new_state)
    await callback.answer(f"Проверка {'включена' if new_state else 'выключена'}", show_alert=True)
    await safe_edit_or_send(callback.message, premium("<b>⚙️ Настройки</b>"), settings_keyboard(user_id))


@dp.callback_query(lambda c: c.data == "toggle_online_mode")
async def toggle_online_mode(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_state = not db.get_online_mode(user_id)
    db.set_online_mode(user_id, new_state)
    await callback.answer(f"Онлайн мод {'включён' if new_state else 'выключен'}", show_alert=True)
    await safe_edit_or_send(callback.message, premium("<b>⚙️ Настройки</b>"), settings_keyboard(user_id))


@dp.callback_query(lambda c: c.data == "text_mode_menu")
async def text_mode_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    text = premium("<b>✏️ Режим текста</b>\n\nВыберите стиль для ваших сообщений.")
    await safe_edit_or_send(callback.message, text, text_mode_keyboard(user_id))
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("set_text_mode_"))
async def set_text_mode(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    mode = callback.data.replace("set_text_mode_", "")
    if mode not in MODE_NAMES:
        await callback.answer("❌ Неизвестный режим.", show_alert=True)
        return
    db.set_text_mode(user_id, mode)
    await callback.answer(f"Режим: {MODE_NAMES[mode]}", show_alert=True)
    await safe_edit_or_send(callback.message, premium("<b>✏️ Режим текста</b>"), text_mode_keyboard(user_id))


@dp.callback_query(lambda c: c.data == "translate_menu")
async def translate_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    text = premium("<b>🌐 Авто перевод</b>\n\nВыберите язык перевода.")
    await safe_edit_or_send(callback.message, text, translate_keyboard(user_id))
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("set_translate_"))
async def set_translate(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = callback.data.replace("set_translate_", "")
    if lang not in TRANSLATE_LANGS:
        await callback.answer("❌ Неизвестный язык.", show_alert=True)
        return
    db.set_translate_to(user_id, lang)
    await callback.answer(f"Авто перевод: {TRANSLATE_LANGS[lang]}", show_alert=True)
    await safe_edit_or_send(callback.message, premium("<b>🌐 Авто перевод</b>"), translate_keyboard(user_id))


@dp.callback_query(lambda c: c.data == "referral_menu")
async def referral_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    invited_total = db.count_referrals_invited(user_id)
    invited_credited = db.count_referrals(user_id)
    stars = db.get_user_stars(user_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    text = premium(
        "<b>⭐ Заработать звёзды</b>\n\n"
        f"<b>🔗 Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"• Зашли по ссылке: <b>{invited_total}</b>\n"
        f"• Подключили бота: <b>{invited_credited}</b>\n"
        f"• Ожидают выдачи: <b>{stars['pending']:.1f} ⭐</b>\n\n"
        "<b>⚠️ Минимум для вывода: 15 ⭐</b>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=referral_keyboard(), parse_mode="HTML")
    except Exception:
        await bot.send_message(user_id, text, reply_markup=referral_keyboard(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_admin = (user_id == ADMIN_ID)
    first_name = callback.from_user.first_name or "друг"
    main_text = premium(f"<b>👋 Привет, {html.escape(first_name)}!</b>\n\nГлавное меню XrayGram.")
    try:
        await callback.message.delete()
    except:
        pass
    if os.path.exists(BANNER_PATH):
        banner = FSInputFile(BANNER_PATH)
        await bot.send_photo(chat_id=user_id, photo=banner, caption=main_text, parse_mode="HTML", reply_markup=main_menu_keyboard(is_admin))
    else:
        await bot.send_message(chat_id=user_id, text=main_text, parse_mode="HTML", reply_markup=main_menu_keyboard(is_admin))
    await callback.answer()


# ============ BUSINESS API ============
@dp.business_connection()
async def handle_business_connection(connection: BusinessConnection):
    bc_id = connection.id
    user_id = connection.user.id
    is_enabled = connection.is_enabled

    if not is_enabled:
        logger.info(f"[CONN] Отключено: bc_id={bc_id}, user_id={user_id}")
        db.delete_connection(bc_id)
        return

    logger.info(f"[CONN] Подключение: bc_id={bc_id}, user_id={user_id}")
    db.set_connection(bc_id, user_id)
    if not db.is_user_registered(user_id):
        user = connection.user
        db.register_user(user_id, user.username, user.first_name, user.last_name)

    try:
        referrer_id = db.get_referrer(user_id)
        if referrer_id and not db.is_referral_credited(user_id):
            db.mark_referral_credited(user_id)
            db.add_pending_stars(referrer_id, 1.5)
            try:
                await bot.send_message(referrer_id, premium(
                    "<b>🎉 По вашей ссылке подключился новый пользователь!</b>\n\n"
                    "Вам начислено <b>+1.5 ⭐</b>."
                ), parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"[REF] {e}")

    try:
        await bot.send_message(user_id, premium(
            "<b>✅ Бизнес-аккаунт подключён к XrayGram!</b>\n\n"
            "Я буду отслеживать все ваши личные чаты.\n\n"
            "Поддержка: @CryptoViktor"
        ), parse_mode="HTML")
    except Exception:
        pass


@dp.business_message()
async def handle_business_message(message: types.Message):
    bc_id = message.business_connection_id
    if not bc_id:
        return

    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id:
        return
    if not db.is_user_registered(user_id):
        return

    chat_id = message.chat.id
    sender_id = message.from_user.id if message.from_user else None
    is_owner = (sender_id == user_id)

    # === Сохранение сообщения (главное для логики) ===
    msg_id = message.message_id
    sender = message.from_user
    fullname = format_user_info(sender) if sender else "Неизвестный"
    text = message.text or message.caption or ""

    files = await download_files(message, user_id)
    db.save_message(bc_id, msg_id, user_id, fullname, text, files,
                    is_temporary=message.has_media_spoiler, chat_id=chat_id)
    logger.info(f"[SAVE] Сохранено {msg_id} для {user_id} (chat_id={chat_id})")


@dp.edited_business_message()
async def handle_edited_business_message(message: types.Message):
    bc_id = message.business_connection_id
    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id or not db.is_user_registered(user_id):
        return
    chat_id = message.chat.id
    msg_id = message.message_id
    new_text = message.text or message.caption or ""
    old_data = db.get_message(bc_id, msg_id)
    if not old_data:
        return
    old_text = old_data["text"] or ""
    if new_text.strip() == old_text.strip():
        return
    db.update_message_text(bc_id, msg_id, new_text)
    db.increment_stat(user_id, "edited_count")
    old_fullname = old_data["fullname"]
    notif_text = premium(f"<b>✏️ Сообщение изменено от {old_fullname}\n\nБыло: {old_text}\nСтало: {new_text}</b>")
    await send_notification(user_id, notif_text)


@dp.deleted_business_messages()
async def handle_deleted_business_messages(event: BusinessMessagesDeleted):
    """
    Логика:
    1. Помечаем все удалённые сообщения в БД (is_deleted=1). Не удаляем из БД!
    2. Собираем информацию о них в буфер.
    3. Перезапускаем таймер на 5 секунд.
    4. Через 5 секунд (в _finalize_chat_deletions) проверяем:
       - остались ли активные сообщения в этом чате?
       - если нет → это полная очистка → одно уведомление с кнопкой на Mini App
       - если да → одиночные удаления → по одному уведомлению
    """
    bc_id = event.business_connection_id
    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id or not db.is_user_registered(user_id):
        return

    chat_id = event.chat.id
    logger.info(f"[DELETE] Событие удаления: chat_id={chat_id}, msg_ids={event.message_ids}")

    key = (user_id, chat_id)

    for msg_id in event.message_ids:
        data = db.get_message(bc_id, msg_id)
        if not data:
            continue

        # Помечаем как удалённое — но НЕ удаляем из БД (нужно для Mini App)
        db.mark_message_deleted(bc_id, msg_id)
        db.increment_stat(user_id, "deleted_count")

        # Собираем в буфер для отложенного уведомления
        _pending_deletions.setdefault(key, []).append({
            "fullname": data["fullname"],
            "text": data["text"] or "",
            "files": json.loads(data["files"]) if data["files"] else [],
        })

    # Перезапускаем таймер
    old_task = _pending_deletion_timers.get(key)
    if old_task and not old_task.done():
        old_task.cancel()
    _pending_deletion_timers[key] = asyncio.create_task(
        _finalize_chat_deletions(user_id, chat_id, delay=5.0)
    )


# ============ ФОНОВЫЕ ЗАДАЧИ ============
async def online_mode_loop():
    logger.info("[ONLINE] Запущена")
    while True:
        try:
            for conn in db.get_online_connections():
                bc_id = conn["bc_id"]
                chat_id = db.get_last_chat_for_bc(bc_id)
                if chat_id:
                    try:
                        await bot.send_chat_action(chat_id=chat_id, action="typing", business_connection_id=bc_id)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"[ONLINE] {e}")
        await asyncio.sleep(20)


async def auto_restart_loop():
    RESTART_INTERVAL = 3 * 60 * 60
    while True:
        await asyncio.sleep(RESTART_INTERVAL)
        logger.info("[AUTO_RESTART] Перезапуск...")
        await asyncio.sleep(1)
        os._exit(0)


async def main():
    try:
        me = await bot.get_me()
        logger.info(f"✅ Бот запущен: @{me.username}")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        raise
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    asyncio.create_task(online_mode_loop())
    asyncio.create_task(mini_app_server())
    asyncio.create_task(auto_restart_loop())

    await bot.set_my_commands([types.BotCommand(command="start", description=premium("Главное меню"))])
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
            logger.info("Перезапуск через 15 секунд...")
            time.sleep(15)
