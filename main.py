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

async def load_media_to_buffer(file_id: str) -> bytes | None:
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
            logger.info(f"Файл сохранён: {path}")
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

# ============ ПРОВЕРКА НА СКАМ/СПАМ ============
async def check_scam(user_id: int) -> tuple[bool, str]:
    try:
        chat = await bot.get_chat(user_id)
        if getattr(chat, 'is_scam', False):
            return True, "Telegram пометил как SCAM"
        if getattr(chat, 'is_fake', False):
            return True, "Telegram пометил как FAKE"
    except Exception as e:
        logger.debug(f"[SCAM] get_chat {user_id}: {e}")

    try:
        resp = requests.get(
            f"https://api.intellivoid.net/spamprotection/v1/lookup?query={user_id}",
            timeout=8,
            verify=False
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                results = data.get("results", {})
                attrs = results.get("attributes", {})
                if attrs.get("is_blacklisted"):
                    reason = attrs.get("blacklist_reason") or "найден в базе спама"
                    return True, f"SpamProtection: {reason}"
    except Exception as e:
        logger.debug(f"[SCAM] SpamProtection {user_id}: {e}")

    return False, ""
# ===============================================

# ============ ФУНКЦИИ ДЛЯ ТРОЛЛИНГА ============
def split_into_chunks(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    i = 0
    while i < len(words):
        chunk_size = random.choice([3, 4])
        chunk = words[i:i+chunk_size]
        chunks.append(" ".join(chunk))
        i += chunk_size
    return chunks

async def troll_spam_task(chat_id: int, bc_id: str, user_id: int):
    while True:
        template = random.choice(TROLL_MESSAGES)
        chunks = split_into_chunks(template)
        if not chunks:
            continue
        for chunk in chunks:
            try:
                await bot.send_message(chat_id, text=chunk, business_connection_id=bc_id)
            except Exception as e:
                logger.error(f"Ошибка отправки троллинга в чат {chat_id}: {e}")
            await asyncio.sleep(random.uniform(2, 4))
            if asyncio.current_task().cancelled():
                return
# ================================================

# ============ ФУНКЦИИ ДЛЯ ПРОВЕРКИ ОДНОРАЗОВОГО МЕДИА ============
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
        model_dump = getattr(obj, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump(exclude_none=True)
                if isinstance(dumped, dict):
                    values.extend(dumped.values())
            except Exception:
                pass
        extra = getattr(obj, "model_extra", None)
        if isinstance(extra, dict):
            values.extend(extra.values())
        raw_dict = getattr(obj, "__dict__", None)
        if isinstance(raw_dict, dict):
            values.extend(raw_dict.values())

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
# ==================================================================

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
            try:
                await message.delete()
            except:
                pass
            await bot.send_message(message.chat.id, new_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            logger.error(f"Ошибка редактирования: {e}")
            try:
                await message.delete()
            except:
                pass
            try:
                await bot.send_message(message.chat.id, new_text, parse_mode="HTML", reply_markup=reply_markup)
            except Exception as e2:
                logger.error(f"Ошибка отправки: {e2}")

# ---- Command handlers ----
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user = message.from_user
    db.register_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    # ---- РЕФЕРАЛЬНАЯ ССЫЛКА ----
    try:
        parts = (message.text or "").split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            referrer_id = int(parts[1][4:])
            if referrer_id != user.id:
                if db.set_referrer_if_empty(user.id, referrer_id):
                    logger.info(f"[REF] {user.id} пришёл по ссылке от {referrer_id}")
    except (ValueError, IndexError):
        pass
    # ---------------------------

    is_admin = (user.id == ADMIN_ID)
    first_name = user.first_name or "друг"
    main_text = premium(
        f"<b>👋 Привет, {html.escape(first_name)}, добро пожаловать в XrayGram!</b>\n\n"
        "<b>🤖 Что умеет бот:</b>\n"
        "<blockquote expandable>Отслеживает удалённые сообщения в ваших личных чатах и присылает их копии.\n\n"
        "Показывает изменения в отредактированных сообщениях (было → стало).\n\n"
        "Сохраняет самоуничтожающиеся медиа. (Чтобы сохранить надо ответить на сообщение с одноразовым медиа)\n\n"
        "Генерирует ответы на вопросы прямо в чате с помощью XrayGPT 1.0.\n\n"
        "Может выполнять всякие команды в личных чатах. (Чтобы узнать подробнее нажмите в меню кнопку «Команды».)\n\n"
        "Проверяет собеседника на СКАМ/СПАМ.\n\n"
        "Может автоматически редактироваать ваши собственные сообщения, применяя выбранный стиль.\n\n"
        "Авто переводит личные сообщения.</blockquote>"
    )
    if os.path.exists(BANNER_PATH):
        banner = FSInputFile(BANNER_PATH)
        await message.answer_photo(photo=banner, caption=main_text, parse_mode="HTML", reply_markup=main_menu_keyboard(is_admin))
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

@dp.message(Command("gn"))
async def cmd_gn(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    bc_id = message.business_connection_id
    question = message.text.replace("/gn", "").strip()
    if not question:
        await message.answer(premium("<b>❌ Напишите вопрос после команды!\nПример: .gn Как дела?</b>"))
        return
    loading = await message.answer(premium("<b>🤔 Думаю...</b>"), parse_mode="HTML")
    try:
        answer = ranvik_api.get_text_response([{"role": "user", "content": question}])
        await loading.delete()
        if bc_id:
            await bot.send_message(chat_id, premium(f"<b>❓ Ваш вопрос:</b>\n{question}\n\n{answer}"),
                                   parse_mode="HTML", business_connection_id=bc_id)
        else:
            await bot.send_message(chat_id, premium(f"<b>❓ Ваш вопрос:</b>\n{question}\n\n{answer}"), parse_mode="HTML")
    except Exception as e:
        await loading.delete()
        await bot.send_message(chat_id, premium(f"<b>❌ Ошибка при обращении к Нейросети:\n{str(e)}</b>"), parse_mode="HTML")

# ---- Game functions ----
async def start_duel(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if message.chat.type != "private":
        await message.answer(premium("<b>❌ Дуэль доступна только в личных чатах!</b>"))
        return
    msg = await message.answer(premium("⚔️ ДУЭЛЬ НАЧИНАЕТСЯ!"), parse_mode="HTML")
    stages = ["⚔️ 3...", "⚔️ 2...", "⚔️ 1...", "🔫 ПРИЦЕЛИВАЙСЯ!", "💥 ВЫСТРЕЛ!"]
    for s in stages:
        await asyncio.sleep(0.7)
        await msg.edit_text(premium(f"<b>{s}</b>"), parse_mode="HTML")
    await asyncio.sleep(0.5)
    winner = random.choice([user_id, chat_id])
    if winner == user_id:
        result = f"🏆 ПОБЕДИТЕЛЬ: {format_user_info(message.from_user)}!\n\n🎉 Выстрел был точным! Противник повержен! 🎉"
    else:
        result = "🏆 ПОБЕДИТЕЛЬ: ВАШ СОБЕСЕДНИК!\n\n💀 Вы были быстрее, но удача была на его стороне..."
    await msg.edit_text(premium(f"<b>{result}</b>"), parse_mode="HTML")

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
    ttt_games[chat_id] = {"board": board, "turn": "X", "player_x": user_id, "player_o": 0, "game_id": game_id}
    player_x_name = format_user_info(message.from_user)
    await message.answer(
        premium(f"<b>❌⭕ Крестики-Нолики</b>\n\nХод: <b>❌ ({player_x_name})</b>\n{EMPTY}{EMPTY}{EMPTY}\n{EMPTY}{EMPTY}{EMPTY}\n{EMPTY}{EMPTY}{EMPTY}"),
        parse_mode="HTML", reply_markup=ttt_keyboard(board, game_id)
    )

@dp.callback_query(lambda c: c.data.startswith("ttt_"))
async def ttt_callback(callback: types.CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    if data == "ttt_no":
        await callback.answer("⏳ Занято!")
        return
    if data.startswith("ttt_end_"):
        game_id = int(data.replace("ttt_end_", ""))
        if chat_id in ttt_games and ttt_games[chat_id]["game_id"] == game_id:
            del ttt_games[chat_id]
        await callback.message.delete()
        await callback.answer("🔴 Игра завершена!")
        return
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
    if chat_id not in ttt_games:
        await callback.answer("❌ Игра не найдена!")
        return
    game = ttt_games[chat_id]
    if game["game_id"] != game_id:
        await callback.answer("❌ Игра не найдена!")
        return
    board = game["board"]
    turn = game["turn"]
    player_x = game["player_x"]
    player_o = game["player_o"]
    if turn == "X":
        if user_id != player_x:
            await callback.answer("⏳ Сейчас ход крестиков! (ваш ход)", show_alert=True)
            return
    else:
        if player_o == 0:
            player_o = user_id
            game["player_o"] = user_id
            ttt_games[chat_id] = game
        if user_id != game["player_o"]:
            await callback.answer("⏳ Сейчас ход ноликов! (ход соперника)", show_alert=True)
            return
    if board[cell] != " ":
        await callback.answer("⏳ Занято!")
        return
    board[cell] = turn
    winner = ttt_check_winner(board)
    if winner:
        try:
            px = format_user_info(await bot.get_chat(player_x))
        except:
            px = "Игрок X"
        try:
            po = format_user_info(await bot.get_chat(player_o)) if player_o else "Игрок O"
        except:
            po = "Игрок O"
        if winner == "X":
            res = f"🏆 <b>Победили КРЕСТИКИ! ({px})</b>"
        elif winner == "O":
            res = f"🏆 <b>Победили НОЛИКИ! ({po})</b>"
        else:
            res = "🤝 <b>Ничья!</b>"
        await callback.message.edit_text(premium(f"{ttt_board_to_text(board)}\n\n{res}"), parse_mode="HTML")
        del ttt_games[chat_id]
        await callback.answer("🏆 Игра завершена!")
        return
    game["turn"] = "O" if turn == "X" else "X"
    try:
        px = format_user_info(await bot.get_chat(player_x))
    except:
        px = "Игрок X"
    try:
        po = format_user_info(await bot.get_chat(player_o)) if player_o else "Ожидание соперника..."
    except:
        po = "Игрок O"
    new_turn = game["turn"]
    ts = "❌" if new_turn == "X" else "⭕"
    tp = px if new_turn == "X" else po
    await callback.message.edit_text(
        premium(f"<b>❌⭕ Крестики-Нолики</b>\n\nХод: <b>{ts} ({tp})</b>\n{ttt_board_to_text(board)}"),
        parse_mode="HTML", reply_markup=ttt_keyboard(board, game_id)
    )
    await callback.answer()

# ---- Callbacks for menus ----
@dp.callback_query(lambda c: c.data.startswith("check_subscription"))
async def check_subscription(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split("|")
    action = parts[1] if len(parts) > 1 else None
    _sub_cache.pop(user_id, None)
    if await is_subscribed(user_id):
        _sub_notified.pop(user_id, None)
        await callback.message.delete()
        if action == "show_instruction":
            await show_instruction_logic(user_id)
        else:
            is_admin = (user_id == ADMIN_ID)
            first_name = callback.from_user.first_name or "друг"
            main_text = premium(
                f"<b>👋 Привет, {html.escape(first_name)}, добро пожаловать в XrayGram!</b>\n\n"
                "<b>🤖 Что умеет бот:</b>\n"
                "<blockquote expandable>Отслеживает удалённые сообщения в ваших личных чатах и присылает их копии.\n\n"
                "Показывает изменения в отредактированных сообщениях (было → стало).\n\n"
                "Сохраняет самоуничтожающиеся медиа. (Чтобы сохранить надо ответить на сообщение с одноразовым медиа)\n\n"
                "Генерирует ответы на вопросы прямо в чате с помощью XrayGPT 1.0.\n\n"
                "Может выполнять всякие команды в личных чатах. (Чтобы узнать подробнее нажмите в меню кнопку «Команды».)\n\n"
                "Проверяет собеседника на СКАМ/СПАМ.\n\n"
                "Может автоматически редактироваать ваши собственные сообщения, применяя выбранный стиль.\n\n"
                "Авто переводит личные сообщения.</blockquote>"
            )
            if os.path.exists(BANNER_PATH):
                banner = FSInputFile(BANNER_PATH)
                await bot.send_photo(
                    chat_id=user_id,
                    photo=banner,
                    caption=main_text,
                    parse_mode="HTML",
                    reply_markup=main_menu_keyboard(is_admin)
                )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=main_text,
                    parse_mode="HTML",
                    reply_markup=main_menu_keyboard(is_admin)
                )
        await callback.answer("✅ Подписка подтверждена!", show_alert=True)
    else:
        await callback.answer("❌ Вы ещё не подписаны. Подпишитесь и попробуйте снова.", show_alert=True)

async def show_instruction_logic(user_id: int):
    instruction_text = premium(
        "<b>📖 Инструкция по подключению XrayGram\n\n"
        "1️⃣ Для использования бота НЕОБЯЗАТЕЛЬНО иметь телеграм премиум\n"
        "2️⃣ Зайдите в свой профиль → Редактировать → Автоматизация чатов.\n"
        "3️⃣ Нажмите Добавить бота и введите @XrayGramRobot.\n"
        "4️⃣ Добавьте все разрешения которые находятся на видео сверху.\n\n"
        "❓ Заметили ошибку? Бот завис? Долго грузит? Сообщите нам — поддержка отреагирует оперативно: @SupXrayGramRobot.</b>"
    )
    try:
        if os.path.exists(INSTRUCTION_VIDEO_PATH):
            video = FSInputFile(INSTRUCTION_VIDEO_PATH)
            await bot.send_video(
                chat_id=user_id,
                video=video,
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
    _sub_cache.pop(user_id, None)
    if not await is_subscribed(user_id):
        _sub_notified[user_id] = time.time()
        text = premium(
            "<b>📢 Для доступа к инструкции необходима подписка на канал!</b>\n\n"
            "Подпишитесь на @NovoeTelegram.\n\n"
            "<i>После подписки инструкция придёт сюда автоматически в течение 5 секунд.</i>"
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=subscription_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=subscription_keyboard())

        # Запускаем авто-ожидание подписки
        _spawn_sub_watcher(user_id)

        await callback.answer()
        return
    _sub_notified.pop(user_id, None)
    await callback.message.delete()
    await show_instruction_logic(user_id)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "mini_app")
async def mini_app_callback(callback: types.CallbackQuery):
    await callback.answer("soon", show_alert=True)

# ============ КНОПКА АНМУТ ============
@dp.callback_query(lambda c: c.data.startswith("unmute_"))
async def unmute_callback(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка!", show_alert=True)
        return
    try:
        target_user_id = int(parts[1])
        target_chat_id = int(parts[2])
    except:
        await callback.answer("❌ Ошибка!", show_alert=True)
        return

    if callback.from_user.id != target_user_id:
        await callback.answer("⛔ Это не ваша кнопка.", show_alert=True)
        return

    db.remove_muted_chat(target_user_id, target_chat_id)

    cursor = db.conn.cursor()
    cursor.execute("SELECT bc_id FROM connections WHERE user_id = ?", (target_user_id,))
    row = cursor.fetchone()
    bc_id = row["bc_id"] if row else None

    if bc_id:
        try:
            await bot.send_message(
                target_chat_id,
                premium("<b>🔊 Вы размучены. Ваши сообщения больше не будут удаляться.</b>"),
                business_connection_id=bc_id, parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"[UNMUTE] Не удалось отправить в чат {target_chat_id}: {e}")

    try:
        await callback.message.edit_text(
            premium(f"<b>🔊 Чат {target_chat_id} размучен.\nСообщения снова сохраняются.</b>"),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[UNMUTE] Не удалось изменить сообщение: {e}")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass

    logger.info(f"[CMD] Мут снят через кнопку для чата {target_chat_id}")
    await callback.answer("✅ Мут снят")
# ==================================

@dp.callback_query(lambda c: c.data == "show_commands")
async def show_commands(callback: types.CallbackQuery):
    commands_text = premium(
        "<b>📋 Список доступных команд</b>\n\n"
        "<blockquote>🔇 .mute – заглушить чат. (.unmute чтобы размутить)\n"
        "💬 .spam &lt;число&gt; &lt;текст&gt; – спам одинаковых сообщений в чат.\n"
        "⚔️ .duel – начать дуэль с собеседником.\n"
        "🔄 .anim &lt;текст&gt; – анимация текста.\n"
        "❌⭕ .ttt – начать игру в крестики-нолики.\n"
        "🤖 .gn &lt;вопрос&gt; – задать вопрос XrayGPT 1.0.\n"
        "🧨 .troll – запустить бесконечный спам оскорбительными фразами. (.stoptroll чтобы остановить.)</blockquote>\n\n"
        "<b>Примеры:</b>\n"
        "<blockquote>.mute\n"
        ".unmute\n"
        ".spam 5 Привет!\n"
        ".duel\n"
        ".anim Привет мир!\n"
        ".ttt\n"
        ".gn Как дела?\n"
        ".troll\n"
        ".stoptroll</blockquote>\n\n"
        "❓ Остались вопросы? Пишите @SupXrayGramRobot."
    )
    await safe_edit_or_send(callback.message, commands_text, commands_keyboard())
    await callback.answer()

# ============ ПРОФИЛЬ ============
@dp.callback_query(lambda c: c.data == "profile")
async def show_profile(callback: types.CallbackQuery):
    user = callback.from_user
    user_id = user.id

    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без имени"
    username = f"@{user.username}" if user.username else "без username"

    row = db.get_user(user_id)
    if row and row["registered_at"]:
        registered_at = row["registered_at"]
    else:
        registered_at = "неизвестно"

    if user_id == ADMIN_ID:
        tariff = "👑 Админ"
    else:
        tariff = "👤 Free"

    text = premium(
        "<b>👤 Профиль</b>\n\n"
        f"Имя: {full_name}\n"
        f"Username: {username}\n"
        f"ID: <code>{user_id}</code>\n"
        f"Регистрация: {registered_at}\n"
        f"Тариф: {tariff}"
    )
    await safe_edit_or_send(callback.message, text, profile_keyboard())
    await callback.answer()
# ================================

# ============ РЕФЕРАЛЬНАЯ СИСТЕМА (МЕНЮ) ============
@dp.callback_query(lambda c: c.data == "referral_menu")
async def referral_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    invited_total = db.count_referrals_invited(user_id)
    invited_credited = db.count_referrals(user_id)
    stars = db.get_user_stars(user_id)

    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

    text = premium(
        "<b>⭐ Заработать звёзды</b>\n\n"
        "<b>Как это работает:</b>\n"
        "<blockquote>"
        "1. Отправьте свою реферальную ссылку друзьям.\n"
        "2. Когда друг перейдёт по ссылке и <b>подключит бота</b> (автоматизацию чатов), "
        "вам начислится <b>+1.5 ⭐</b> в ожидающие.\n"
        "3. Админ выдаёт звёзды вручную.\n"
        "</blockquote>\n"
        f"<b>🔗 Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"<b>📊 Статистика:</b>\n"
        f"• Зашли по ссылке: <b>{invited_total}</b>\n"
        f"• Подключили бота: <b>{invited_credited}</b>\n"
        f"• Ожидают выдачи: <b>{stars['pending']:.1f} ⭐</b>\n"
        f"• Уже выдано: <b>{stars['awarded']:.1f} ⭐</b>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=referral_keyboard(), parse_mode="HTML")
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await bot.send_message(user_id, text, reply_markup=referral_keyboard(), parse_mode="HTML")

    await callback.answer()
# ====================================================

# ============ НАСТРОЙКИ ============
@dp.callback_query(lambda c: c.data == "settings")
async def show_settings(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    text = premium(
        "<b>⚙️ Настройки</b>\n\n"
        "<b>Проверка на СКАМ/СПАМ</b>\n"
        "Когда включено, бот проверяет каждого собеседника, который вам пишет:\n"
        "• встроенные флаги Telegram (SCAM/FAKE)\n"
        "• базу SpamProtection API\n\n"
        "<b>Режим текста</b>\n"
        "Бот автоматически редактирует ваши собственные сообщения, применяя выбранный стиль (жирный, курсив, скрытый, пикми, uwu и т.д.).\n\n"
        "<b>Авто перевод</b>\n"
        "Бот присылает вам в лс перевод входящих сообщений на выбранный язык.\n\n"
        "<b>Онлайн мод</b>\n"
        "Когда включено, ваш аккаунт постоянно находится в статусе «в сети»."
    )
    await safe_edit_or_send(callback.message, text, settings_keyboard(user_id))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "toggle_scam_check")
async def toggle_scam_check(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_state = not db.get_scam_check(user_id)
    db.set_scam_check(user_id, new_state)
    status = "включена" if new_state else "выключена"
    await callback.answer(f"Проверка на СКАМ/СПАМ {status}", show_alert=True)
    text = premium(
        "<b>⚙️ Настройки</b>\n\n"
        "<b>Проверка на СКАМ/СПАМ</b>\n"
        "Когда включено, бот проверяет каждого собеседника, который вам пишет:\n"
        "• встроенные флаги Telegram (SCAM/FAKE)\n"
        "• базу SpamProtection API\n\n"
        "<b>Режим текста</b>\n"
        "Бот автоматически редактирует ваши собственные сообщения, применяя выбранный стиль (жирный, курсив, скрытый, пикми, uwu и т.д.).\n\n"
        "<b>Авто перевод</b>\n"
        "Бот присылает вам в лс перевод входящих сообщений на выбранный язык.\n\n"
        "<b>Онлайн мод</b>\n"
        "Когда включено, ваш аккаунт постоянно находится в статусе «в сети»."
    )
    await safe_edit_or_send(callback.message, text, settings_keyboard(user_id))

@dp.callback_query(lambda c: c.data == "toggle_online_mode")
async def toggle_online_mode(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_state = not db.get_online_mode(user_id)
    db.set_online_mode(user_id, new_state)
    status = "включён" if new_state else "выключен"
    await callback.answer(f"Онлайн мод {status}", show_alert=True)
    text = premium(
        "<b>⚙️ Настройки</b>\n\n"
        "<b>Проверка на СКАМ/СПАМ</b>\n"
        "Когда включено, бот проверяет каждого собеседника, который вам пишет:\n"
        "• встроенные флаги Telegram (SCAM/FAKE)\n"
        "• базу SpamProtection API\n\n"
        "<b>Режим текста</b>\n"
        "Бот автоматически редактирует ваши собственные сообщения, применяя выбранный стиль (жирный, курсив, скрытый, пикми, uwu и т.д.).\n\n"
        "<b>Авто перевод</b>\n"
        "Бот присылает вам в лс перевод входящих сообщений на выбранный язык.\n\n"
        "<b>Онлайн мод</b>\n"
        "Когда включено, ваш аккаунт постоянно находится в статусе «в сети»."
    )
    await safe_edit_or_send(callback.message, text, settings_keyboard(user_id))

# ---- Режим текста ----
@dp.callback_query(lambda c: c.data == "text_mode_menu")
async def text_mode_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    text = premium(
        "<b>✏️ Режим текста</b>\n\n"
        "Выберите стиль, который бот будет применять к вашим сообщениям в чатах.\n\n"
        "<b>HTML-стили:</b>\n"
        "• Жирный, Курсив, Подчёркнутый, Зачёркнутый, Скрытый, Жирный курсив, Моноширинный, Код, Цитата\n\n"
        "<b>Специальные стили:</b>\n"
        "• <b>Пикми</b> — милый стиль с уменьшительно-ласкательными словами и эмодзи ✨💖\n"
        "• <b>UwU</b> — замены букв и смайлики owo uwu :3\n"
        "• <b>Широкий</b> — пробелы между буквами\n"
        "• <b>КАПС</b> — всё капсом\n"
        "• <b>Перевёрнутый</b> — текст перевёрнут вверх ногами\n"
        "• <b>С хлопками</b> — 👏 между словами"
    )
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
    text = premium(
        "<b>✏️ Режим текста</b>\n\n"
        "Выберите стиль, который бот будет применять к вашим сообщениям в чатах.\n\n"
        "<b>HTML-стили:</b>\n"
        "• Жирный, Курсив, Подчёркнутый, Зачёркнутый, Скрытый, Жирный курсив, Моноширинный, Код, Цитата\n\n"
        "<b>Специальные стили:</b>\n"
        "• <b>Пикми</b> — милый стиль с уменьшительно-ласкательными словами и эмодзи ✨💖\n"
        "• <b>UwU</b> — замены букв и смайлики owo uwu :3\n"
        "• <b>Широкий</b> — пробелы между буквами\n"
        "• <b>КАПС</b> — всё капсом\n"
        "• <b>Перевёрнутый</b> — текст перевёрнут вверх ногами\n"
        "• <b>С хлопками</b> — 👏 между словами"
    )
    await safe_edit_or_send(callback.message, text, text_mode_keyboard(user_id))

# ---- Авто перевод ----
@dp.callback_query(lambda c: c.data == "translate_menu")
async def translate_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    text = premium(
        "<b>🌐 Авто перевод</b>\n\n"
        "Выберите язык, на который бот будет переводить входящие сообщения от ваших собеседников."
    )
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
    text = premium(
        "<b>🌐 Авто перевод</b>\n\n"
        "Выберите язык, на который бот будет переводить входящие сообщения от ваших собеседников."
    )
    await safe_edit_or_send(callback.message, text, translate_keyboard(user_id))
# ==================================

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_admin = (user_id == ADMIN_ID)
    first_name = callback.from_user.first_name or "друг"
    main_text = premium(
        f"<b>👋 Привет, {html.escape(first_name)}, добро пожаловать в XrayGram!</b>\n\n"
        "<b>🤖 Что умеет бот:</b>\n"
        "<blockquote expandable>Отслеживает удалённые сообщения в ваших личных чатах и присылает их копии.\n\n"
        "Показывает изменения в отредактированных сообщениях (было → стало).\n\n"
        "Сохраняет самоуничтожающиеся медиа. (Чтобы сохранить надо ответить на сообщение с одноразовым медиа)\n\n"
        "Генерирует ответы на вопросы прямо в чате с помощью XrayGPT 1.0.\n\n"
        "Может выполнять всякие команды в личных чатах. (Чтобы узнать подробнее нажмите в меню кнопку «Команды».)\n\n"
        "Проверяет собеседника на СКАМ/СПАМ.\n\n"
        "Может автоматически редактироваать ваши собственные сообщения, применяя выбранный стиль.\n\n"
        "Авто переводит личные сообщения.</blockquote>"
    )
    try:
        await callback.message.delete()
    except:
        pass
    if os.path.exists(BANNER_PATH):
        banner = FSInputFile(BANNER_PATH)
        await bot.send_photo(
            chat_id=user_id,
            photo=banner,
            caption=main_text,
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(is_admin)
        )
    else:
        await bot.send_message(
            chat_id=user_id,
            text=main_text,
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(is_admin)
        )
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

# ------- РАССЫЛКА -------
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
    blocked = 0
    no_dialog = 0

    status_msg = await message.answer(premium("<b>⏳ Рассылка запущена...</b>"), parse_mode="HTML")

    for (user_id,) in users:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            err_text = str(e).lower()
            if "flood" in err_text or "retry after" in err_text or "too many requests" in err_text:
                await asyncio.sleep(3)
                try:
                    await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
                    sent += 1
                except Exception as e2:
                    logger.error(f"Ошибка рассылки {user_id} (retry): {e2}")
                    failed += 1
            elif "blocked" in err_text:
                db.delete_user_completely(user_id)
                blocked += 1
                logger.info(f"[BROADCAST] {user_id} заблокировал бота — удалён из БД")
            elif "can't initiate" in err_text or "chat not found" in err_text:
                no_dialog += 1
            else:
                logger.error(f"Ошибка рассылки {user_id}: {e}")
                failed += 1
            await asyncio.sleep(0.05)

    try:
        await status_msg.delete()
    except:
        pass

    report = (
        f"<b>✅ Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: {sent}\n"
        f"🚫 Заблокировали (удалены из БД): {blocked}\n"
        f"💤 Не начинали диалог: {no_dialog}\n"
        f"❌ Прочие ошибки: {failed}"
    )
    await message.answer(premium(report), parse_mode="HTML", reply_markup=back_to_admin_keyboard())
    await state.clear()
# -------------------------------------------------------

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
    content += f"Всего: {len(users)}\n" + "="*50 + "\n\n"
    for u in users:
        uid, uname, fname, lname, reg = u
        name = f"{fname or ''} {lname or ''}".strip() or "Без имени"
        un = f"@{uname}" if uname else f"ID: {uid}"
        content += f"{name} ({un})\nID: {uid}\nЗарегистрирован: {reg}\n" + "-"*30 + "\n"
    await callback.message.answer_document(BufferedInputFile(content.encode("utf-8"), filename="users_list.txt"),
                                           caption=premium("<b>📄 Список всех пользователей (txt)</b>"), parse_mode="HTML")
    await callback.answer()

# ------- АКТИВНЫЕ ПОДКЛЮЧЕНИЯ -------
@dp.callback_query(lambda c: c.data == "active_connections")
async def active_connections(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    cursor = db.conn.cursor()
    cursor.execute("SELECT bc_id, user_id FROM connections")
    all_conns = cursor.fetchall()

    if not all_conns:
        await callback.answer("Нет активных подключений.", show_alert=True)
        return

    active_ids = []
    removed = 0

    for row in all_conns:
        bc_id = row["bc_id"]
        user_id = row["user_id"]
        try:
            conn = await bot.get_business_connection(bc_id)
            if conn and conn.is_enabled:
                active_ids.append(user_id)
            else:
                db.delete_user_completely(user_id)
                removed += 1
                logger.info(f"[ACTIVE] {user_id} отключил бота — удалён из БД")
        except Exception as e:
            db.delete_user_completely(user_id)
            removed += 1
            logger.info(f"[ACTIVE] bc_id {bc_id} невалиден — {user_id} удалён из БД")

    if not active_ids:
        await callback.answer(f"Нет активных подключений. Очищено: {removed}", show_alert=True)
        return

    placeholders = ",".join("?" for _ in active_ids)
    cursor.execute(f"SELECT user_id, username, first_name, last_name FROM users WHERE user_id IN ({placeholders})", active_ids)
    users = cursor.fetchall()

    content = "Активные подключения XrayGram\n"
    content += f"Всего активных: {len(users)}\n"
    content += f"Очищено мёртвых: {removed}\n"
    content += "=" * 50 + "\n\n"
    for u in users:
        uid, uname, fname, lname = u
        name = f"{fname or ''} {lname or ''}".strip() or "Без имени"
        un = f"@{uname}" if uname else f"ID: {uid}"
        content += f"{name} ({un})\nID: {uid}\n" + "-" * 30 + "\n"

    await callback.message.answer_document(
        BufferedInputFile(content.encode("utf-8"), filename="active_connections.txt"),
        caption=premium(f"<b>🔗 Активные подключения (txt)\nВсего: {len(users)} | Очищено мёртвых: {removed}</b>"),
        parse_mode="HTML"
    )
    await callback.answer()
# -------------------------------------------------------

# ============ АДМИН: РЕФЕРАЛЫ ============
@dp.callback_query(lambda c: c.data == "ref_admin")
async def ref_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    refs = db.get_all_referrers()
    if not refs:
        await callback.answer("Пока нет рефералов.", show_alert=True)
        return

    total_pending = sum(r["pending_stars"] for r in refs)
    total_credited = sum(r["invited_credited"] for r in refs)

    content = "Реферальная статистика XrayGram\n"
    content += f"Всего рефереров: {len(refs)}\n"
    content += f"Всего подключений по ссылкам: {total_credited}\n"
    content += f"Суммарно ожидает выдачи: {total_pending:.1f} ⭐\n"
    content += "=" * 60 + "\n\n"

    for r in refs:
        name = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip() or "Без имени"
        un = f"@{r['username']}" if r["username"] else f"ID: {r['user_id']}"
        content += (
            f"{name} ({un})\n"
            f"ID: {r['user_id']}\n"
            f"Зашли по ссылке: {r['invited_total']}\n"
            f"Подключили бота: {r['invited_credited']}\n"
            f"Ожидает выдачи: {r['pending_stars']:.1f} ⭐\n"
            f"Уже выдано: {r['awarded_stars']:.1f} ⭐\n"
            + "-" * 40 + "\n"
        )

    await callback.message.answer_document(
        BufferedInputFile(content.encode("utf-8"), filename="referrals.txt"),
        caption=premium(f"<b>⭐ Рефералы (txt)\nРефереров: {len(refs)} | Подключений: {total_credited} | К выдаче: {total_pending:.1f} ⭐</b>"),
        parse_mode="HTML"
    )
    await callback.answer()
# ========================================

# ---- Business handlers ----
@dp.business_connection()
async def handle_business_connection(connection: BusinessConnection):
    bc_id = connection.id
    user_id = connection.user.id
    is_enabled = connection.is_enabled
    if not is_enabled:
        logger.info(f"[CONN] Отключено: bc_id={bc_id}, user_id={user_id}")
        db.delete_user_completely(user_id)
        return
    logger.info(f"[CONN] Новое подключение: bc_id={bc_id}, user_id={user_id}")
    db.set_connection(bc_id, user_id)
    if not db.is_user_registered(user_id):
        user = connection.user
        db.register_user(user_id, user.username, user.first_name, user.last_name)

    # ---- РЕФЕРАЛЬНОЕ НАЧИСЛЕНИЕ ----
    try:
        referrer_id = db.get_referrer(user_id)
        if referrer_id and not db.is_referral_credited(user_id):
            db.mark_referral_credited(user_id)
            db.add_pending_stars(referrer_id, 1.5)
            try:
                await bot.send_message(
                    referrer_id,
                    premium(
                        "<b>🎉 По вашей реферальной ссылке подключился новый пользователь!</b>\n\n"
                        "Вам начислено <b>+1.5 ⭐</b> (ожидают выдачи).\n"
                        "Звёзды выдаст администратор."
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.debug(f"[REF] Не удалось уведомить {referrer_id}: {e}")
            logger.info(f"[REF] {referrer_id} получил +1.5⭐ за подключение {user_id}")
    except Exception as e:
        logger.error(f"[REF] Ошибка начисления: {e}")
    # -------------------------------

    # ---- ОБЯЗАТЕЛЬНАЯ ПОДПИСКА (АВТО-ПРОВЕРКА) ----
    _sub_cache.pop(user_id, None)
    subscribed = await is_subscribed(user_id)
    if subscribed:
        _sub_notified.pop(user_id, None)
        try:
            await bot.send_message(user_id,
                premium("<b>✅ Ваш бизнес-аккаунт успешно подключён к XrayGram!\n\n"
                        "Теперь я буду отслеживать все ваши личные чаты и присылать вам копии удалённых или изменённых сообщений.\n\n"
                        "Если у вас возникнут вопросы — обратитесь в поддержку @CryptoViktor.</b>"),
                parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

        # Автоматически присылаем инструкцию после подключения
        try:
            await show_instruction_logic(user_id)
            logger.info(f"[CONN] Инструкция автоматически отправлена {user_id}")
        except Exception as e:
            logger.error(f"[CONN] Не удалось отправить инструкцию {user_id}: {e}")
    else:
        # Пользователь не подписан — требуем подписку и запускаем авто-ожидание
        await ensure_subscription(user_id, notify=True, force_notify=True)
        _spawn_sub_watcher(user_id)
    # -----------------------------------------------

    try:
        user = connection.user
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без имени"
        username = f"@{user.username}" if user.username else "без username"
        await bot.send_message(ADMIN_ID,
            premium(f"<b>🔔 Новое подключение!</b>\n\n"
                    f"👤 <b>Пользователь:</b> {full_name}\n"
                    f"📱 <b>Username:</b> {username}\n"
                    f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                    f"🔗 <b>bc_id:</b> <code>{bc_id}</code>"),
            parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")

@dp.business_message()
async def handle_business_message(message: types.Message):
    bc_id = message.business_connection_id
    if not bc_id:
        logger.warning("business_connection_id отсутствует")
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
        logger.warning(f"bc_id={bc_id} не найден, fallback user_id={user_id}")

    if not user_id:
        logger.warning(f"Не удалось определить user_id для bc_id={bc_id}")
        return

    if not db.get_user_by_bc_id(bc_id):
        logger.info(f"[SKIP] bc_id={bc_id} не активен — сообщение не сохраняется")
        return

    if not db.is_user_registered(user_id):
        if message.from_user:
            db.register_user(user_id, message.from_user.username or "", message.from_user.first_name or "", message.from_user.last_name or "")
        else:
            db.register_user(user_id, "", "Unknown", "")

    # ---- ОБЯЗАТЕЛЬНАЯ ПОДПИСКА (АВТО-ПРОВЕРКА) ----
    if not await ensure_subscription(user_id, notify=True):
        logger.info(f"[SUB] {user_id} не подписан — сообщение не обрабатывается")
        return
    # -----------------------------------------------

    chat_id = message.chat.id
    sender_id = message.from_user.id if message.from_user else None
    is_owner = (sender_id == user_id)

    # ---- ПРОВЕРКА НА СКАМ/СПАМ ----
    if not is_owner and sender_id and db.get_scam_check(user_id):
        try:
            is_scam, reason = await check_scam(sender_id)
            if is_scam:
                await bot.send_message(
                    user_id,
                    premium(
                        f"<b>⚠️ ВНИМАНИЕ! Возможный скамер/спамер</b>\n\n"
                        f"От: {format_user_info(message.from_user)}\n"
                        f"ID: <code>{sender_id}</code>\n"
                        f"Причина: {reason}"
                    ),
                    parse_mode="HTML"
                )
                logger.info(f"[SCAM] {sender_id} помечен: {reason}")
        except Exception as e:
            logger.error(f"[SCAM] Ошибка проверки: {e}")
    # ------------------------------

    # ---- АВТО ПЕРЕВОД ----
    if not is_owner and message.text and not message.text.startswith('.'):
        try:
            translate_to = db.get_translate_to(user_id)
            if translate_to and translate_to != "off":
                original = message.text.strip()

                if not text_matches_lang_script(original, translate_to):
                    translated, detected = await translate_text(original, translate_to)

                    def _lang_base(code: str) -> str:
                        return (code or "").split("-")[0].lower()

                    same_lang = _lang_base(detected) and _lang_base(detected) == _lang_base(translate_to)

                    is_valid = (
                        not same_lang
                        and translated
                        and translated.strip().lower() != original.lower()
                        and any(ch.isalpha() for ch in translated)
                    )

                    if is_valid:
                        sender_info = format_user_info(message.from_user) if message.from_user else "Неизвестный"
                        lang_name = TRANSLATE_LANGS.get(translate_to, translate_to)
                        notif_text = (
                            f"<b>🌐 Перевод сообщения</b>\n\n"
                            f"👤 <b>От:</b> {sender_info}\n"
                            f"🆔 <b>ID:</b> <code>{sender_id}</code>\n"
                            f"🌍 <b>Перевод на:</b> {lang_name}\n\n"
                            f"<b>Оригинал:</b>\n{html.escape(original)}\n\n"
                            f"<b>Перевод:</b>\n{html.escape(translated)}"
                        )
                        await bot.send_message(user_id, notif_text, parse_mode="HTML")
                        logger.info(f"[TRANSLATE] {sender_id}: {detected} → {translate_to}")
        except Exception as e:
            logger.error(f"[TRANSLATE] Ошибка: {e}")
    # ----------------------------------------

    # ---- РЕЖИМ ТЕКСТА ----
    if is_owner and message.text and not message.text.startswith('.'):
        try:
            mode = db.get_text_mode(user_id)
            if mode and mode != "off":
                new_text = apply_text_mode(message.text, mode)
                if new_text and new_text != message.text:
                    try:
                        await bot.edit_message_text(
                            text=new_text,
                            chat_id=chat_id,
                            message_id=message.message_id,
                            business_connection_id=bc_id,
                            parse_mode="HTML"
                        )
                        logger.info(f"[TEXT_MODE] Применён режим '{mode}' к сообщению {message.message_id}")
                    except Exception as e:
                        logger.error(f"[TEXT_MODE] Не удалось изменить сообщение: {e}")
        except Exception as e:
            logger.error(f"[TEXT_MODE] Ошибка: {e}")
    # -------------------------------------------------------

    if message.reply_to_message and is_owner:
        replied = message.reply_to_message
        if is_restricted_media(replied):
            media_type, file_id = extract_media(replied)
            if file_id and media_type:
                sender_info = format_user_info(replied.from_user) if replied.from_user else "Неизвестный"
                caption_text = f"💾 Сохранено одноразовое медиа от {sender_info}"
                if replied.caption:
                    caption_text += f"\n\nПодпись: {replied.caption}"
                data = await load_media_to_buffer(file_id)
                if data:
                    try:
                        if media_type == "photo":
                            await bot.send_photo(user_id, BufferedInputFile(data, filename="photo.jpg"), caption=caption_text)
                        elif media_type == "video":
                            await bot.send_video(user_id, BufferedInputFile(data, filename="video.mp4"), caption=caption_text)
                        elif media_type == "voice":
                            await bot.send_voice(user_id, BufferedInputFile(data, filename="voice.ogg"), caption=caption_text)
                        elif media_type == "video_note":
                            await bot.send_video_note(user_id, BufferedInputFile(data, filename="video_note.mp4"))
                            await bot.send_message(user_id, caption_text)
                        elif media_type == "audio":
                            await bot.send_audio(user_id, BufferedInputFile(data, filename="audio.mp3"), caption=caption_text)
                        elif media_type == "document":
                            await bot.send_document(user_id, BufferedInputFile(data, filename="document.bin"), caption=caption_text)
                        elif media_type == "animation":
                            await bot.send_animation(user_id, BufferedInputFile(data, filename="animation.mp4"), caption=caption_text)
                        elif media_type == "sticker":
                            await bot.send_sticker(user_id, file_id)
                            await bot.send_message(user_id, caption_text)
                        else:
                            await bot.send_message(user_id, caption_text)
                        logger.info(f"[REPLY] Одноразовое медиа ({media_type}) сохранено для {user_id}")
                    except Exception as e:
                        logger.error(f"[REPLY] Ошибка отправки медиа: {e}")
                else:
                    await bot.send_message(user_id, f"⚠️ Не удалось скачать медиа.\n{caption_text}")
        else:
            logger.info(f"[REPLY] Ответ на обычное медиа (не одноразовое) – пропущено")

    if is_owner and message.text:
        _first_word = message.text.strip().split()[0] if message.text.strip() else ""
        _is_known_cmd = _first_word in KNOWN_COMMANDS
    else:
        _is_known_cmd = False

    if is_owner and message.text and _is_known_cmd:
        text = message.text.strip()
        try:
            await bot.delete_business_messages(business_connection_id=bc_id, message_ids=[message.message_id])
            logger.info(f"[CMD] Команда '{text}' удалена")
        except Exception as e:
            logger.error(f"[CMD] Не удалось удалить команду: {e}")

        if text == ".mute":
            db.add_muted_chat(user_id, chat_id)

            unmute_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔊 Анмут",
                    callback_data=f"unmute_{user_id}_{chat_id}",
                    style="success"
                )]
            ])

            try:
                await bot.send_message(
                    chat_id,
                    premium("<b>🔇 Вы были заглушены. Ваши сообщения будут удаляться.</b>\n\n<i>Бот - @XrayGramRobot</i>"),
                    business_connection_id=bc_id,
                    parse_mode="HTML",
                    reply_markup=unmute_kb
                )
                logger.info(f"[MUTE] Уведомление с кнопкой Анмут отправлено в чат {chat_id}")
            except Exception as e:
                logger.error(f"[MUTE] Ошибка отправки в чат {chat_id}: {e}")

            try:
                await bot.send_message(
                    user_id,
                    premium(f"<b>🔇 Чат {chat_id} замучен.\nСообщения от собеседника не будут сохраняться и будут удаляться.</b>"),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"[MUTE] Ошибка отправки уведомления пользователю {user_id}: {e}")

            logger.info(f"[CMD] .mute выполнен для чата {chat_id}")
            return

        if text == ".unmute":
            db.remove_muted_chat(user_id, chat_id)
            await bot.send_message(chat_id, premium("<b>🔊 Вы размучены. Ваши сообщения больше не будут удаляться.</b>"),
                                   business_connection_id=bc_id, parse_mode="HTML")
            await bot.send_message(user_id, premium(f"<b>🔊 Чат {chat_id} размучен.\nСообщения снова сохраняются.</b>"),
                                   parse_mode="HTML")
            logger.info(f"[CMD] .unmute выполнен для чата {chat_id}")
            return

        if text.startswith(".spam "):
            parts = text.split(maxsplit=2)
            if len(parts) >= 3:
                try:
                    count = int(parts[1])
                    spam_text = parts[2]
                    if count <= 0:
                        raise ValueError
                except:
                    await bot.send_message(user_id, premium("<b>❌ Неверный формат: .spam <число> <текст></b>"), parse_mode="HTML")
                    return
                for _ in range(count):
                    await bot.send_message(chat_id, text=spam_text, business_connection_id=bc_id)
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
            loading = await bot.send_message(user_id, premium("<b>🤔 Думаю...</b>"), parse_mode="HTML")
            try:
                answer = ranvik_api.get_text_response([{"role": "user", "content": question}])
                await loading.delete()
                await bot.send_message(chat_id, premium(f"<b>❓ Ваш вопрос:</b>\n{question}\n\n{answer}"),
                                       parse_mode="HTML", business_connection_id=bc_id)
            except Exception as e:
                await loading.delete()
                await bot.send_message(user_id, premium(f"<b>❌ Ошибка при обращении к Нейросети:\n{str(e)}</b>"), parse_mode="HTML")
            return

        if text == ".troll":
            if chat_id in troll_tasks:
                await bot.send_message(user_id, "⚠️ Троллинг уже запущен в этом чате.", parse_mode="HTML")
            else:
                task = asyncio.create_task(troll_spam_task(chat_id, bc_id, user_id))
                troll_tasks[chat_id] = task
                await bot.send_message(user_id, "✅ Троллинг запущен! Сообщения будут отправляться собеседнику.", parse_mode="HTML")
            return

        if text == ".stoptroll":
            if chat_id in troll_tasks:
                task = troll_tasks.pop(chat_id)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                await bot.send_message(user_id, "⏹ Троллинг остановлен.", parse_mode="HTML")
            else:
                await bot.send_message(user_id, "❌ Троллинг не был запущен.", parse_mode="HTML")
            return

        return

    if db.is_chat_muted(user_id, chat_id) and not is_owner:
        try:
            await bot.delete_business_messages(business_connection_id=bc_id, message_ids=[message.message_id])
            logger.info(f"[MUTE] Сообщение {message.message_id} удалено")
        except Exception as e:
            if "message to delete not found" not in str(e):
                logger.error(f"[MUTE] Ошибка удаления: {e}")
        return

    msg_id = message.message_id
    sender = message.from_user
    fullname = format_user_info(sender) if sender else "Неизвестный"
    text = message.text or message.caption or ""

    files = await download_files(message, user_id)
    db.save_message(bc_id, msg_id, user_id, fullname, text, files,
                    is_temporary=message.has_media_spoiler, chat_id=chat_id)
    logger.info(f"[SAVE] Сохранено {msg_id} для {user_id} (chat_id={chat_id})")

    if message.has_media_spoiler and files:
        notif_text = premium(f"<b>⚠️ Самоуничтожающееся сообщение от {fullname}\n\n{text}</b>") if text else premium(f"<b>⚠️ Самоуничтожающееся медиа от {fullname}</b>")
        await send_notification(user_id, notif_text, files)

@dp.edited_business_message()
async def handle_edited_business_message(message: types.Message):
    bc_id = message.business_connection_id
    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id or not db.is_user_registered(user_id):
        return
    # ---- ОБЯЗАТЕЛЬНАЯ ПОДПИСКА (АВТО-ПРОВЕРКА) ----
    if not await ensure_subscription(user_id, notify=False):
        return
    # -----------------------------------------------
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
    files_list = json.loads(files) if files else []
    notif_text = premium(f"<b>✏️ Сообщение изменено от {old_fullname}\n\nБыло: {old_text}\nСтало: {new_text}</b>")
    await send_notification(user_id, notif_text, files_list)

@dp.deleted_business_messages()
async def handle_deleted_business_messages(event: BusinessMessagesDeleted):
    bc_id = event.business_connection_id
    user_id = db.get_user_by_bc_id(bc_id)
    if not user_id or not db.is_user_registered(user_id):
        return
    # ---- ОБЯЗАТЕЛЬНАЯ ПОДПИСКА (АВТО-ПРОВЕРКА) ----
    if not await ensure_subscription(user_id, notify=False):
        return
    # -----------------------------------------------
    for msg_id in event.message_ids:
        data = db.get_message(bc_id, msg_id)
        if not data:
            continue
        fullname = data["fullname"]
        text = data["text"] or ""
        files = data["files"]
        files_list = json.loads(files) if files else []
        notif_text = premium(f"<b>❌ Сообщение удалено от {fullname}\n\n{text}</b>") if text else premium(f"<b>❌ Сообщение удалено от {fullname}</b>")
        await send_notification(user_id, notif_text, files_list)
        db.delete_message(bc_id, msg_id)

# ============ ФОНОВАЯ ЗАДАЧА: ОНЛАЙН МОД ============
async def online_mode_loop():
    """Пингует бизнес-аккаунт через send_chat_action, чтобы он отображался в сети."""
    logger.info("[ONLINE] Фоновая задача запущена")
    while True:
        try:
            connections = db.get_online_connections()
            for conn in connections:
                try:
                    bc_id = conn["bc_id"]
                    user_id = conn["user_id"]
                except Exception:
                    continue

                chat_id = db.get_last_chat_for_bc(bc_id)
                if not chat_id:
                    continue

                try:
                    await bot.send_chat_action(
                        chat_id=chat_id,
                        action="typing",
                        business_connection_id=bc_id
                    )
                    logger.debug(f"[ONLINE] Пинг {bc_id} → chat {chat_id}")
                except Exception as e:
                    logger.debug(f"[ONLINE] Ошибка пинга {bc_id}: {e}")

        except Exception as e:
            logger.error(f"[ONLINE] Ошибка цикла: {e}")

        await asyncio.sleep(20)
# ====================================================

async def main():
    try:
        me = await bot.get_me()
        logger.info(f"✅ Бот успешно запущен: @{me.username}")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Telegram API: {e}")
        raise

    asyncio.create_task(online_mode_loop())

    await bot.set_my_commands([types.BotCommand(command="start", description=premium("Главное меню"))])
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
