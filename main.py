# ... (весь код до TTT остаётся без изменений) ...

# ==================== TTT (исправленный) ====================
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
    
    # ================================================
    # ========== СТРОГАЯ ПРОВЕРКА РОЛЕЙ ==============
    # ================================================
    
    if turn == "X":
        # Ходят только крестики (владелец)
        if user_id != player_x:
            await callback.answer("⏳ Сейчас ход крестиков! (ваш ход)", show_alert=True)
            return
    else:  # turn == "O"
        # Если игрок O ещё не определён, запоминаем его
        if player_o == 0:
            player_o = user_id
            game["player_o"] = user_id
            logger.info(f"[TTT] Игрок O определён: {user_id}")
            ttt_games[chat_id] = game
        
        # Проверяем, что ходит именно игрок O
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
    
    game["turn"] = "O" if turn == "X" else "X"
    
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

# ... (весь код после TTT остаётся без изменений) ...
