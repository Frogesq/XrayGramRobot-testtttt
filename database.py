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
REFERRAL_DB_PATH = os.path.join(DATA_DIR, "referrals.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

REFERRAL_DAILY_LIMIT = 20
REFERRAL_MIN_INTERVAL = 60
BACKUP_KEEP = 5


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


def _enable_wal(conn):
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.commit()
    except Exception as e:
        logger.warning(f"[DB] Не удалось включить WAL: {e}")


class Database:
    def __init__(self):
        _ensure_valid_db(DB_PATH)
        _ensure_valid_db(REFERRAL_DB_PATH)

        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        _enable_wal(self.conn)

        self.ref_conn = sqlite3.connect(REFERRAL_DB_PATH, check_same_thread=False)
        self.ref_conn.row_factory = sqlite3.Row
        _enable_wal(self.ref_conn)

        self._init_tables()
        self._init_referral_tables()

    # ================================================================
    # ОСНОВНАЯ БД (messages.db)
    # ================================================================
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

        # Миграции user_settings
        cursor.execute("PRAGMA table_info(user_settings)")
        cols = [row["name"] for row in cursor.fetchall()]
        if "scam_check" not in cols:
            cursor.execute("ALTER TABLE user_settings ADD COLUMN scam_check BOOLEAN DEFAULT 0")
        if "text_mode" not in cols:
            cursor.execute("ALTER TABLE user_settings ADD COLUMN text_mode TEXT DEFAULT 'off'")
        if "translate_to" not in cols:
            cursor.execute("ALTER TABLE user_settings ADD COLUMN translate_to TEXT DEFAULT 'off'")
        if "online_mode" not in cols:
            cursor.execute("ALTER TABLE user_settings ADD COLUMN online_mode BOOLEAN DEFAULT 0")

        # Миграция messages
        cursor.execute("PRAGMA table_info(messages)")
        msg_cols = [row["name"] for row in cursor.fetchall()]
        if "chat_id" not in msg_cols:
            cursor.execute("ALTER TABLE messages ADD COLUMN chat_id INTEGER")

        # Legacy-колонки в users (оставлены для совместимости, не используются)
        cursor.execute("PRAGMA table_info(users)")
        user_cols = [row["name"] for row in cursor.fetchall()]
        if "referrer_id" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
        if "referral_credited" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN referral_credited INTEGER DEFAULT 0")
        if "pending_stars" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN pending_stars REAL DEFAULT 0")
        if "awarded_stars" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN awarded_stars REAL DEFAULT 0")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_connections_bc_id ON connections(bc_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_connections_user_id ON connections(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_bc_id_msg_id ON messages(bc_id, msg_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_muted_chats_user_id ON muted_chats(user_id)")
        self.conn.commit()

    # ================================================================
    # РЕФЕРАЛЬНАЯ БД (referrals.db)
    # ================================================================
    def _init_referral_tables(self):
        cur = self.ref_conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS referral_relations (
                user_id INTEGER PRIMARY KEY,
                referrer_id INTEGER NOT NULL,
                credited INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS referral_balances (
                user_id INTEGER PRIMARY KEY,
                pending_stars REAL DEFAULT 0,
                awarded_stars REAL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS referral_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                invited_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(invited_id)
            )
        """)
        # ---- Статистика пользователя ----
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                deleted_count INTEGER DEFAULT 0,
                edited_count INTEGER DEFAULT 0
            )
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_referral_relations_referrer ON referral_relations(referrer_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_referral_events_referrer ON referral_events(referrer_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_referral_events_created ON referral_events(created_at)")
        self.ref_conn.commit()

        # Одноразовая миграция из старой схемы users
        try:
            cur.execute("SELECT COUNT(*) AS c FROM referral_relations")
            rel_count = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM referral_balances")
            bal_count = cur.fetchone()["c"]
            if rel_count == 0 and bal_count == 0:
                main_cur = self.conn.cursor()
                main_cur.execute("""
                    SELECT user_id, referrer_id, referral_credited,
                           COALESCE(pending_stars,0) AS ps, COALESCE(awarded_stars,0) AS as_
                    FROM users
                    WHERE referrer_id IS NOT NULL
                       OR COALESCE(pending_stars,0) > 0
                       OR COALESCE(awarded_stars,0) > 0
                """)
                migrated_rel = 0
                migrated_bal = 0
                for row in main_cur.fetchall():
                    uid = row["user_id"]
                    if row["referrer_id"] is not None:
                        cur.execute(
                            "INSERT OR IGNORE INTO referral_relations (user_id, referrer_id, credited) VALUES (?, ?, ?)",
                            (uid, row["referrer_id"], row["referral_credited"] or 0)
                        )
                        migrated_rel += 1
                    if row["ps"] > 0 or row["as_"] > 0:
                        cur.execute(
                            "INSERT OR IGNORE INTO referral_balances (user_id, pending_stars, awarded_stars) VALUES (?, ?, ?)",
                            (uid, row["ps"], row["as_"])
                        )
                        migrated_bal += 1
                if migrated_rel or migrated_bal:
                    logger.info(f"[DB] Миграция рефералов: связей {migrated_rel}, балансов {migrated_bal}")
                self.ref_conn.commit()
        except Exception as e:
            logger.error(f"[DB] Ошибка миграции рефералов: {e}")

    # ============ БЭКАПЫ ============
    def auto_backup(self) -> str:
        try:
            if not os.path.exists(REFERRAL_DB_PATH):
                return ""
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(BACKUP_DIR, f"referrals_{ts}.db")

            src = sqlite3.connect(REFERRAL_DB_PATH)
            dst = sqlite3.connect(backup_path)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()

            backups = sorted(
                [f for f in os.listdir(BACKUP_DIR) if f.startswith("referrals_") and f.endswith(".db")]
            )
            while len(backups) > BACKUP_KEEP:
                old = backups.pop(0)
                try:
                    os.remove(os.path.join(BACKUP_DIR, old))
                except Exception:
                    pass

            logger.info(f"[BACKUP] Создан бэкап: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"[BACKUP] Ошибка: {e}")
            return ""

    def list_backups(self) -> list:
        try:
            return sorted(
                [f for f in os.listdir(BACKUP_DIR) if f.startswith("referrals_") and f.endswith(".db")],
                reverse=True
            )
        except Exception:
            return []

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

    # ============ СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ ============
    def increment_stat(self, user_id: int, field: str):
        if field not in ("deleted_count", "edited_count"):
            return
        try:
            cur = self.ref_conn.cursor()
            cur.execute(f"""
                INSERT INTO user_stats (user_id, {field}) VALUES (?, 1)
                ON CONFLICT(user_id) DO UPDATE SET {field} = COALESCE(user_stats.{field}, 0) + 1
            """, (user_id,))
            self.ref_conn.commit()
        except Exception as e:
            logger.error(f"[DB] increment_stat: {e}")

    def get_user_stats(self, user_id: int) -> dict:
        try:
            cur = self.ref_conn.cursor()
            cur.execute(
                "SELECT COALESCE(deleted_count,0) AS d, COALESCE(edited_count,0) AS e "
                "FROM user_stats WHERE user_id = ?",
                (user_id,)
            )
            row = cur.fetchone()
            if row is None:
                return {"deleted": 0, "edited": 0}
            return {"deleted": int(row["d"] or 0), "edited": int(row["e"] or 0)}
        except Exception as e:
            logger.error(f"[DB] get_user_stats: {e}")
            return {"deleted": 0, "edited": 0}

    def get_user_messages_saved(self, user_id: int) -> int:
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM messages WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            return int(row["c"] or 0)
        except Exception:
            return 0

    def get_user_active_connections(self, user_id: int) -> int:
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM connections WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            return int(row["c"] or 0)
        except Exception:
            return 0

    # ============ РЕФЕРАЛЬНАЯ СИСТЕМА ============
    def set_referrer_if_empty(self, user_id: int, referrer_id: int) -> bool:
        if user_id == referrer_id:
            return False
        try:
            cur = self.ref_conn.cursor()
            cur.execute("SELECT 1 FROM referral_relations WHERE user_id = ?", (user_id,))
            if cur.fetchone() is not None:
                return False
            cur.execute(
                "INSERT INTO referral_relations (user_id, referrer_id, credited) VALUES (?, ?, 0)",
                (user_id, referrer_id)
            )
            self.ref_conn.commit()
            return True
        except Exception as e:
            logger.error(f"[DB] set_referrer_if_empty: {e}")
            return False

    def get_referrer(self, user_id: int):
        try:
            cur = self.ref_conn.cursor()
            cur.execute("SELECT referrer_id FROM referral_relations WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            return row["referrer_id"] if row else None
        except Exception:
            return None

    def is_referral_credited(self, user_id: int) -> bool:
        try:
            cur = self.ref_conn.cursor()
            cur.execute("SELECT credited FROM referral_relations WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row is None:
                return True
            return bool(row["credited"])
        except Exception:
            return True

    def mark_referral_credited(self, user_id: int):
        try:
            cur = self.ref_conn.cursor()
            cur.execute("UPDATE referral_relations SET credited = 1 WHERE user_id = ?", (user_id,))
            self.ref_conn.commit()
        except Exception as e:
            logger.error(f"[DB] mark_referral_credited: {e}")

    def count_referrals_today(self, referrer_id: int) -> int:
        try:
            cur = self.ref_conn.cursor()
            cur.execute("""
                SELECT COUNT(*) AS c FROM referral_events
                WHERE referrer_id = ?
                  AND created_at >= datetime('now', '-1 day')
            """, (referrer_id,))
            return int(cur.fetchone()["c"] or 0)
        except Exception:
            return 0

    def seconds_since_last_referral(self, referrer_id: int) -> float:
        try:
            cur = self.ref_conn.cursor()
            cur.execute("""
                SELECT created_at FROM referral_events
                WHERE referrer_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (referrer_id,))
            row = cur.fetchone()
            if row is None:
                return 1e9
            cur.execute("SELECT (julianday('now') - julianday(?)) * 86400.0 AS s", (row["created_at"],))
            return float(cur.fetchone()["s"] or 0)
        except Exception:
            return 1e9

    def log_referral_event(self, referrer_id: int, invited_id: int):
        try:
            cur = self.ref_conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO referral_events (referrer_id, invited_id) VALUES (?, ?)",
                (referrer_id, invited_id)
            )
            self.ref_conn.commit()
        except Exception as e:
            logger.error(f"[DB] log_referral_event: {e}")

    def add_pending_stars(self, user_id: int, amount: float):
        try:
            cur = self.ref_conn.cursor()
            cur.execute("""
                INSERT INTO referral_balances (user_id, pending_stars) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    pending_stars = COALESCE(referral_balances.pending_stars, 0) + ?
            """, (user_id, float(amount), float(amount)))
            self.ref_conn.commit()
        except Exception as e:
            logger.error(f"[DB] add_pending_stars: {e}")

    def get_user_stars(self, user_id: int) -> dict:
        try:
            cur = self.ref_conn.cursor()
            cur.execute(
                "SELECT COALESCE(pending_stars,0) AS p, COALESCE(awarded_stars,0) AS a "
                "FROM referral_balances WHERE user_id = ?",
                (user_id,)
            )
            row = cur.fetchone()
            if row is None:
                return {"pending": 0.0, "awarded": 0.0}
            return {"pending": float(row["p"] or 0), "awarded": float(row["a"] or 0)}
        except Exception:
            return {"pending": 0.0, "awarded": 0.0}

    def count_referrals(self, user_id: int) -> int:
        try:
            cur = self.ref_conn.cursor()
            cur.execute(
                "SELECT COUNT(*) AS c FROM referral_relations WHERE referrer_id = ? AND credited = 1",
                (user_id,)
            )
            return int(cur.fetchone()["c"] or 0)
        except Exception:
            return 0

    def count_referrals_invited(self, user_id: int) -> int:
        try:
            cur = self.ref_conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM referral_relations WHERE referrer_id = ?", (user_id,))
            return int(cur.fetchone()["c"] or 0)
        except Exception:
            return 0

    def get_all_referrers(self) -> list:
        try:
            cur = self.ref_conn.cursor()
            cur.execute("""
                SELECT
                    t.user_id AS user_id,
                    COALESCE(rb.pending_stars, 0) AS pending_stars,
                    COALESCE(rb.awarded_stars, 0) AS awarded_stars,
                    (SELECT COUNT(*) FROM referral_relations r WHERE r.referrer_id = t.user_id) AS invited_total,
                    (SELECT COUNT(*) FROM referral_relations r
                     WHERE r.referrer_id = t.user_id AND r.credited = 1) AS invited_credited
                FROM (
                    SELECT DISTINCT referrer_id AS user_id FROM referral_relations
                    UNION
                    SELECT user_id FROM referral_balances
                ) t
                LEFT JOIN referral_balances rb ON rb.user_id = t.user_id
            """)
            ref_rows = cur.fetchall()

            result = []
            main_cur = self.conn.cursor()
            for r in ref_rows:
                uid = r["user_id"]
                pending = float(r["pending_stars"] or 0)
                awarded = float(r["awarded_stars"] or 0)
                invited_total = int(r["invited_total"] or 0)
                invited_credited = int(r["invited_credited"] or 0)

                if invited_total == 0 and pending == 0 and awarded == 0:
                    continue

                main_cur.execute(
                    "SELECT username, first_name, last_name FROM users WHERE user_id = ?",
                    (uid,)
                )
                u = main_cur.fetchone()
                result.append({
                    "user_id": uid,
                    "username": u["username"] if u else None,
                    "first_name": u["first_name"] if u else None,
                    "last_name": u["last_name"] if u else None,
                    "pending_stars": pending,
                    "awarded_stars": awarded,
                    "invited_total": invited_total,
                    "invited_credited": invited_credited,
                })

            result.sort(key=lambda x: (x["pending_stars"], x["invited_credited"]), reverse=True)
            return result
        except Exception as e:
            logger.error(f"[DB] get_all_referrers: {e}")
            return []

    def mark_stars_awarded(self, user_id: int):
        try:
            cur = self.ref_conn.cursor()
            cur.execute("""
                UPDATE referral_balances
                SET awarded_stars = COALESCE(awarded_stars, 0) + COALESCE(pending_stars, 0),
                    pending_stars = 0
                WHERE user_id = ?
            """, (user_id,))
            self.ref_conn.commit()
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

    # ============ СТАТИСТИКА ОБЩАЯ ============
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
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.ref_conn.close()
        except Exception:
            pass
