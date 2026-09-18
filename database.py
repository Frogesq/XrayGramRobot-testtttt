import sqlite3
import json
import os
import logging
import shutil
import time

logger = logging.getLogger(__name__)

DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "messages.db")


def _is_valid_sqlite(path):
    if not os.path.exists(path):
        return False
    size = os.path.getsize(path)
    if size < 100:
        return False
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        if header != b"SQLite format 3\x00":
            return False
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA schema_version;")
        conn.execute("SELECT name FROM sqlite_master LIMIT 1;")
        conn.close()
        return True
    except Exception:
        return False


def _try_recover(path):
    try:
        backup_path = f"{path}.broken.{int(time.time())}"
        shutil.copy2(path, backup_path)
        new_path = f"{path}.recovered"
        conn_src = sqlite3.connect(path)
        conn_dst = sqlite3.connect(new_path)
        with conn_dst:
            for line in conn_src.iterdump():
                try:
                    conn_dst.execute(line)
                except Exception:
                    pass
        conn_src.close()
        conn_dst.close()
        if os.path.exists(new_path) and os.path.getsize(new_path) > 0:
            os.replace(new_path, path)
            return True
    except Exception as e:
        logger.error(f"[DB] Не удалось восстановить: {e}")
    return False


def _ensure_valid_db(path):
    if not os.path.exists(path):
        return
    size = os.path.getsize(path)
    if _is_valid_sqlite(path):
        return
    if size < 100:
        try:
            os.remove(path)
        except Exception:
            pass
        return
    if _try_recover(path):
        return
    try:
        os.remove(path)
    except Exception:
        pass


class Database:
    def __init__(self):
        _ensure_valid_db(DB_PATH)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                bc_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                bc_id TEXT,
                msg_id INTEGER,
                user_id INTEGER,
                chat_id INTEGER,
                fullname TEXT,
                text TEXT,
                files TEXT,
                is_temporary BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (bc_id, msg_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS muted_chats (
                user_id INTEGER,
                chat_id INTEGER,
                PRIMARY KEY (user_id, chat_id)
            )
        """)

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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                scam_check BOOLEAN DEFAULT 0,
                text_mode TEXT DEFAULT 'off',
                translate_to TEXT DEFAULT 'off',
                online_mode BOOLEAN DEFAULT 0
            )
        """)

        # ============ МИГРАЦИИ ============
        cursor.execute("PRAGMA table_info(user_settings)")
        cols = [row["name"] for row in cursor.fetchall()]
        if "scam_check" not in cols:
            cursor.execute("ALTER TABLE user_settings ADD COLUMN scam_check BOOLEAN DEFAULT 0")
            logger.info("[DB] Миграция: добавлена колонка scam_check")
        if "text_mode" not in cols:
            cursor.execute("ALTER TABLE user_settings ADD COLUMN text_mode TEXT DEFAULT 'off'")
            logger.info("[DB] Миграция: добавлена колонка text_mode")
        if "translate_to" not in cols:
            cursor.execute("ALTER TABLE user_settings ADD COLUMN translate_to TEXT DEFAULT 'off'")
            logger.info("[DB] Миграция: добавлена колонка translate_to")
        if "online_mode" not in cols:
            cursor.execute("ALTER TABLE user_settings ADD COLUMN online_mode BOOLEAN DEFAULT 0")
            logger.info("[DB] Миграция: добавлена колонка online_mode")

        cursor.execute("PRAGMA table_info(messages)")
        msg_cols = [row["name"] for row in cursor.fetchall()]
        if "chat_id" not in msg_cols:
            cursor.execute("ALTER TABLE messages ADD COLUMN chat_id INTEGER")
            logger.info("[DB] Миграция: добавлена колонка chat_id в messages")

        # ============ МИГРАЦИИ: РЕФЕРАЛЬНАЯ СИСТЕМА ============
        cursor.execute("PRAGMA table_info(users)")
        user_cols = [row["name"] for row in cursor.fetchall()]
        if "referrer_id" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
            logger.info("[DB] Миграция: добавлена колонка referrer_id в users")
        if "referral_credited" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN referral_credited INTEGER DEFAULT 0")
            logger.info("[DB] Миграция: добавлена колонка referral_credited в users")
        if "pending_stars" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN pending_stars REAL DEFAULT 0")
            logger.info("[DB] Миграция: добавлена колонка pending_stars в users")
        if "awarded_stars" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN awarded_stars REAL DEFAULT 0")
            logger.info("[DB] Миграция: добавлена колонка awarded_stars в users")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_connections_bc_id ON connections(bc_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_connections_user_id ON connections(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_bc_id_msg_id ON messages(bc_id, msg_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_muted_chats_user_id ON muted_chats(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer_id ON users(referrer_id)")

        self.conn.commit()

    # ============ ПОЛЬЗОВАТЕЛИ ============
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

    def delete_user_completely(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM muted_chats WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM connections WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self.conn.commit()

    # ============ РЕФЕРАЛЬНАЯ СИСТЕМА ============
    def set_referrer_if_empty(self, user_id: int, referrer_id: int) -> bool:
        """Устанавливает referrer_id, только если он ещё не установлен."""
        if user_id == referrer_id:
            return False
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row is None:
                return False
            if row["referrer_id"] is not None:
                return False
            cursor.execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (referrer_id, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"[DB] set_referrer_if_empty: {e}")
            return False

    def get_referrer(self, user_id: int):
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return row["referrer_id"]
        except Exception:
            return None

    def is_referral_credited(self, user_id: int) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT referral_credited FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row is None:
                return True
            return bool(row["referral_credited"])
        except Exception:
            return True

    def mark_referral_credited(self, user_id: int):
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE users SET referral_credited = 1 WHERE user_id = ?", (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"[DB] mark_referral_credited: {e}")

    def add_pending_stars(self, user_id: int, amount: float):
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE users SET pending_stars = COALESCE(pending_stars, 0) + ? WHERE user_id = ?",
                (float(amount), user_id)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"[DB] add_pending_stars: {e}")

    def get_user_stars(self, user_id: int) -> dict:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COALESCE(pending_stars,0) AS p, COALESCE(awarded_stars,0) AS a FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return {"pending": 0.0, "awarded": 0.0}
            return {"pending": float(row["p"] or 0), "awarded": float(row["a"] or 0)}
        except Exception:
            return {"pending": 0.0, "awarded": 0.0}

    def count_referrals(self, user_id: int) -> int:
        """Сколько пользователей подключились по ссылке (credited)."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) AS c FROM users WHERE referrer_id = ? AND referral_credited = 1",
                (user_id,)
            )
            row = cursor.fetchone()
            return int(row["c"]) if row else 0
        except Exception:
            return 0

    def count_referrals_invited(self, user_id: int) -> int:
        """Сколько всего пользователей зашли по ссылке (даже если не подключились)."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM users WHERE referrer_id = ?", (user_id,))
            row = cursor.fetchone()
            return int(row["c"]) if row else 0
        except Exception:
            return 0

    def get_all_referrers(self) -> list:
        """Возвращает список всех, у кого есть приглашённые, со статистикой."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT
                    u.user_id AS user_id,
                    u.username AS username,
                    u.first_name AS first_name,
                    u.last_name AS last_name,
                    COALESCE(u.pending_stars, 0) AS pending_stars,
                    COALESCE(u.awarded_stars, 0) AS awarded_stars,
                    (SELECT COUNT(*) FROM users r WHERE r.referrer_id = u.user_id) AS invited_total,
                    (SELECT COUNT(*) FROM users r WHERE r.referrer_id = u.user_id AND r.referral_credited = 1) AS invited_credited
                FROM users u
                WHERE invited_total > 0
                ORDER BY pending_stars DESC, invited_credited DESC
            """)
            rows = cursor.fetchall()
            result = []
            for r in rows:
                result.append({
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "first_name": r["first_name"],
                    "last_name": r["last_name"],
                    "pending_stars": float(r["pending_stars"] or 0),
                    "awarded_stars": float(r["awarded_stars"] or 0),
                    "invited_total": int(r["invited_total"] or 0),
                    "invited_credited": int(r["invited_credited"] or 0),
                })
            return result
        except Exception as e:
            logger.error(f"[DB] get_all_referrers: {e}")
            return []

    def mark_stars_awarded(self, user_id: int):
        """Перемещает pending_stars в awarded_stars (вызывать после ручной выдачи звёзд)."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE users
                SET awarded_stars = COALESCE(awarded_stars, 0) + COALESCE(pending_stars, 0),
                    pending_stars = 0
                WHERE user_id = ?
            """, (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"[DB] mark_stars_awarded: {e}")

    # ============ НАСТРОЙКИ ============
    def get_scam_check(self, user_id: int) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT scam_check FROM user_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return bool(row["scam_check"]) if row else False

    def set_scam_check(self, user_id: int, enabled: bool):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO user_settings (user_id, scam_check) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET scam_check = excluded.scam_check
        """, (user_id, 1 if enabled else 0))
        self.conn.commit()

    def get_text_mode(self, user_id: int) -> str:
        cursor = self.conn.cursor()
        cursor.execute("SELECT text_mode FROM user_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return (row["text_mode"] if row and row["text_mode"] else "off")

    def set_text_mode(self, user_id: int, mode: str):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO user_settings (user_id, text_mode) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET text_mode = excluded.text_mode
        """, (user_id, mode))
        self.conn.commit()

    def get_translate_to(self, user_id: int) -> str:
        cursor = self.conn.cursor()
        cursor.execute("SELECT translate_to FROM user_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return (row["translate_to"] if row and row["translate_to"] else "off")

    def set_translate_to(self, user_id: int, lang: str):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO user_settings (user_id, translate_to) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET translate_to = excluded.translate_to
        """, (user_id, lang))
        self.conn.commit()

    def get_online_mode(self, user_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT online_mode FROM user_settings WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return bool(row["online_mode"]) if row and row["online_mode"] is not None else False
        except Exception:
            return False

    def set_online_mode(self, user_id: int, enabled: bool):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO user_settings (user_id, online_mode) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET online_mode = excluded.online_mode
        """, (user_id, 1 if enabled else 0))
        self.conn.commit()

    # ============ ПОДКЛЮЧЕНИЯ ============
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

    def get_online_connections(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT c.bc_id, c.user_id
            FROM connections c
            JOIN user_settings s ON s.user_id = c.user_id
            WHERE s.online_mode = 1
        """)
        return cursor.fetchall()

    # ============ СООБЩЕНИЯ ============
    def save_message(self, bc_id, msg_id, user_id, fullname, text, files_list=None,
                     is_temporary=False, chat_id=None):
        cursor = self.conn.cursor()
        files_json = json.dumps(files_list) if files_list else None
        cursor.execute("""
            INSERT OR REPLACE INTO messages
            (bc_id, msg_id, user_id, chat_id, fullname, text, files, is_temporary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (bc_id, msg_id, user_id, chat_id, fullname, text, files_json, is_temporary))
        self.conn.commit()

    def update_message_text(self, bc_id, msg_id, new_text):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE messages SET text = ? WHERE bc_id = ? AND msg_id = ?", (new_text, bc_id, msg_id))
        self.conn.commit()

    def update_message_fullname(self, bc_id, msg_id, new_fullname):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE messages SET fullname = ? WHERE bc_id = ? AND msg_id = ?", (new_fullname, bc_id, msg_id))
        self.conn.commit()

    def get_message(self, bc_id, msg_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE bc_id = ? AND msg_id = ?", (bc_id, msg_id))
        return cursor.fetchone()

    def delete_message(self, bc_id, msg_id):
        cursor = self.conn.cursor()
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

    def get_last_chat_for_bc(self, bc_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT chat_id FROM messages WHERE bc_id = ? AND chat_id IS NOT NULL ORDER BY msg_id DESC LIMIT 1",
            (bc_id,)
        )
        row = cursor.fetchone()
        return row["chat_id"] if row else None

    # ============ MUTE ============
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

    # ============ TTT ============
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
        cursor.execute("UPDATE ttt_games SET board = ?, turn = ? WHERE chat_id = ?", (json.dumps(board), turn, chat_id))
        self.conn.commit()

    def update_ttt_player_o(self, chat_id, player_o):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE ttt_games SET player_o = ? WHERE chat_id = ?", (player_o, chat_id))
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

    # ============ СТАТИСТИКА ============
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
