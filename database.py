import sqlite3
import json

class Database:
    def __init__(self):
        self.conn = sqlite3.connect("messages.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        cursor = self.conn.cursor()
        
        # Таблица пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица подключений (business_connection_id -> user_id)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                bc_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL
            )
        """)
        
        # Таблица сообщений
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                bc_id TEXT,
                msg_id INTEGER,
                user_id INTEGER,
                fullname TEXT,
                text TEXT,
                files TEXT,
                is_temporary BOOLEAN DEFAULT 0,
                ttl_seconds INTEGER DEFAULT 0,
                media_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (bc_id, msg_id)
            )
        """)
        
        # Таблица замученных чатов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS muted_chats (
                user_id INTEGER,
                chat_id INTEGER,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        
        # Таблица для игр в крестики-нолики
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ttt_games (
                chat_id INTEGER PRIMARY KEY,
                board TEXT,
                turn TEXT,
                player_x INTEGER,
                player_o INTEGER,
                game_id TEXT
            )
        """)
        
        # Индексы для ускорения запросов
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_connections_bc_id ON connections(bc_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_connections_user_id ON connections(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_bc_id_msg_id ON messages(bc_id, msg_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_muted_chats_user_id ON muted_chats(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)")
        
        self.conn.commit()

    # ==================== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ====================
    def register_user(self, user_id, username, first_name, last_name=""):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, first_name, last_name))
        self.conn.commit()
        return cursor.rowcount > 0

    def is_user_registered(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

    def get_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

    # ==================== РАБОТА С ПОДКЛЮЧЕНИЯМИ ====================
    def set_connection(self, bc_id, user_id):
        cursor = self.conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO connections (bc_id, user_id) VALUES (?, ?)", (bc_id, user_id))
        self.conn.commit()

    def get_user_by_bc_id(self, bc_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM connections WHERE bc_id = ?", (bc_id,))
        row = cursor.fetchone()
        return row["user_id"] if row else None

    def delete_connection(self, bc_id):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM connections WHERE bc_id = ?", (bc_id,))
        self.conn.commit()

    def get_all_connections(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT bc_id, user_id FROM connections")
        return cursor.fetchall()

    # ==================== РАБОТА С СООБЩЕНИЯМИ ====================
    def save_message(self, bc_id, msg_id, user_id, fullname, text, files_list=None, is_temporary=False, ttl_seconds=0, media_type=None):
        cursor = self.conn.cursor()
        files_json = json.dumps(files_list) if files_list else None
        cursor.execute("""
            INSERT OR REPLACE INTO messages (bc_id, msg_id, user_id, fullname, text, files, is_temporary, ttl_seconds, media_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (bc_id, msg_id, user_id, fullname, text, files_json, is_temporary, ttl_seconds, media_type))
        self.conn.commit()

    def update_message_text(self, bc_id, msg_id, new_text):
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE messages SET text = ? WHERE bc_id = ? AND msg_id = ?
        """, (new_text, bc_id, msg_id))
        self.conn.commit()

    def update_message_fullname(self, bc_id, msg_id, new_fullname):
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE messages SET fullname = ? WHERE bc_id = ? AND msg_id = ?
        """, (new_fullname, bc_id, msg_id))
        self.conn.commit()

    def get_message(self, bc_id, msg_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE bc_id = ? AND msg_id = ?", (bc_id, msg_id))
        return cursor.fetchone()

    def delete_message(self, bc_id, msg_id):
        cursor = self.conn.cursor()
        # Получаем пути к файлам перед удалением
        cursor.execute("SELECT files FROM messages WHERE bc_id = ? AND msg_id = ?", (bc_id, msg_id))
        row = cursor.fetchone()
        if row and row["files"]:
            try:
                files_list = json.loads(row["files"])
                for file_path in files_list:
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            logger.info(f"[DELETE] Удалён файл: {file_path}")
                    except Exception as e:
                        logger.error(f"[DELETE] Ошибка удаления файла {file_path}: {e}")
            except:
                pass
        
        cursor.execute("DELETE FROM messages WHERE bc_id = ? AND msg_id = ?", (bc_id, msg_id))
        self.conn.commit()

    def get_messages_by_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return cursor.fetchall()

    def get_messages_by_chat(self, bc_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE bc_id = ? ORDER BY created_at DESC", (bc_id,))
        return cursor.fetchall()

    def delete_old_messages(self, days=30):
        """Удаляет сообщения старше указанного количества дней"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT bc_id, msg_id, files FROM messages 
            WHERE created_at < datetime('now', '-' || ? || ' days')
        """, (days,))
        rows = cursor.fetchall()
        
        for row in rows:
            if row["files"]:
                try:
                    files_list = json.loads(row["files"])
                    for file_path in files_list:
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except:
                            pass
                except:
                    pass
        
        cursor.execute("""
            DELETE FROM messages 
            WHERE created_at < datetime('now', '-' || ? || ' days')
        """, (days,))
        self.conn.commit()
        return len(rows)

    # ==================== РАБОТА С MUTE ====================
    def add_muted_chat(self, user_id: int, chat_id: int):
        cursor = self.conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO muted_chats (user_id, chat_id) VALUES (?, ?)", (user_id, chat_id))
        self.conn.commit()

    def remove_muted_chat(self, user_id: int, chat_id: int):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM muted_chats WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        self.conn.commit()

    def is_chat_muted(self, user_id: int, chat_id: int) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM muted_chats WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        return cursor.fetchone() is not None

    def get_muted_chats(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute("SELECT chat_id FROM muted_chats WHERE user_id = ?", (user_id,))
        return [row["chat_id"] for row in cursor.fetchall()]

    # ==================== РАБОТА С ИГРАМИ (TTT) ====================
    def save_ttt_game(self, chat_id, board, turn, player_x, player_o, game_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO ttt_games (chat_id, board, turn, player_x, player_o, game_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, json.dumps(board), turn, player_x, player_o, game_id))
        self.conn.commit()

    def get_ttt_game(self, chat_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM ttt_games WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row:
            return {
                "chat_id": row["chat_id"],
                "board": json.loads(row["board"]),
                "turn": row["turn"],
                "player_x": row["player_x"],
                "player_o": row["player_o"],
                "game_id": row["game_id"]
            }
        return None

    def delete_ttt_game(self, chat_id):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM ttt_games WHERE chat_id = ?", (chat_id,))
        self.conn.commit()

    def update_ttt_game(self, chat_id, board, turn):
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE ttt_games SET board = ?, turn = ? WHERE chat_id = ?
        """, (json.dumps(board), turn, chat_id))
        self.conn.commit()

    def update_ttt_player_o(self, chat_id, player_o):
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE ttt_games SET player_o = ? WHERE chat_id = ?
        """, (player_o, chat_id))
        self.conn.commit()

    def get_ttt_game_by_id(self, chat_id, game_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM ttt_games WHERE chat_id = ? AND game_id = ?", (chat_id, game_id))
        row = cursor.fetchone()
        if row:
            return {
                "chat_id": row["chat_id"],
                "board": json.loads(row["board"]),
                "turn": row["turn"],
                "player_x": row["player_x"],
                "player_o": row["player_o"],
                "game_id": row["game_id"]
            }
        return None

    # ==================== СТАТИСТИКА ====================
    def get_users_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        return cursor.fetchone()[0]

    def get_messages_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages")
        return cursor.fetchone()[0]

    def get_connections_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM connections")
        return cursor.fetchone()[0]

    def get_muted_chats_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM muted_chats")
        return cursor.fetchone()[0]

    def close(self):
        self.conn.close()
