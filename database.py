import sqlite3
import json

class Database:
    def __init__(self):
        self.conn = sqlite3.connect("messages.db", check_same_thread=False)
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
        self.conn.commit()

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

    def set_connection(self, bc_id, user_id):
        cursor = self.conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO connections (bc_id, user_id) VALUES (?, ?)", (bc_id, user_id))
        self.conn.commit()

    def get_user_by_bc_id(self, bc_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM connections WHERE bc_id = ?", (bc_id,))
        row = cursor.fetchone()
        return row["user_id"] if row else None

    def save_message(self, bc_id, msg_id, user_id, fullname, text, files_list=None, is_temporary=False):
        cursor = self.conn.cursor()
        files_json = json.dumps(files_list) if files_list else None
        cursor.execute("""
            INSERT OR REPLACE INTO messages (bc_id, msg_id, user_id, fullname, text, files, is_temporary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (bc_id, msg_id, user_id, fullname, text, files_json, is_temporary))
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
        cursor.execute("DELETE FROM messages WHERE bc_id = ? AND msg_id = ?", (bc_id, msg_id))
        self.conn.commit()

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

    def close(self):
        self.conn.close()