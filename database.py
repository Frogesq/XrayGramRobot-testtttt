import sqlite3
import json
import os

class Database:
    def __init__(self):
        self.conn = sqlite3.connect("messages.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
        self._migrate()

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
                fullname TEXT,
                text TEXT,
                files TEXT,
                file_id TEXT,
                media_type TEXT,
                is_temporary BOOLEAN DEFAULT 0,
                ttl_seconds INTEGER DEFAULT 0,
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_connections_bc_id ON connections(bc_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_connections_user_id ON connections(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_bc_id_msg_id ON messages(bc_id, msg_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_muted_chats_user_id ON muted_chats(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)")
        self.conn.commit()

    def _migrate(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(messages)")
        columns = [col[1] for col in cursor.fetchall()]
        if "ttl_seconds" not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN ttl_seconds INTEGER DEFAULT 0")
        if "file_id" not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN file_id TEXT")
        if "media_type" not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN media_type TEXT")
        self.conn.commit()

    # ---- Остальные методы без изменений (register_user, set_connection, get_user_by_bc_id, ...) ----
    # Для краткости я опускаю их, но они должны быть скопированы из вашего текущего database.py.
    # Ниже я приведу только изменённый метод save_message.

    def save_message(self, bc_id, msg_id, user_id, fullname, text, files_list=None, file_id=None, media_type=None, is_temporary=False, ttl_seconds=0):
        cursor = self.conn.cursor()
        files_json = json.dumps(files_list) if files_list else None
        cursor.execute("""
            INSERT OR REPLACE INTO messages 
            (bc_id, msg_id, user_id, fullname, text, files, file_id, media_type, is_temporary, ttl_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (bc_id, msg_id, user_id, fullname, text, files_json, file_id, media_type, is_temporary, ttl_seconds))
        self.conn.commit()
