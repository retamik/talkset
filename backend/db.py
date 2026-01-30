import sqlite3
from config import settings


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projects (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      short_context TEXT NOT NULL,
      project_summary TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'active'
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS kus (
      id TEXT PRIMARY KEY,
      project_id TEXT,
      type TEXT NOT NULL,
      title TEXT NOT NULL,
      status TEXT NOT NULL,
      content_ai_json TEXT NOT NULL,
      content_human TEXT NOT NULL DEFAULT '',
      created_at INTEGER NOT NULL,
      last_activity_at INTEGER NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id TEXT NOT NULL,
      user_id TEXT,
      user_name TEXT,
      message_id TEXT,
      sent_at INTEGER,
      text TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS open_batches (
      chat_id TEXT PRIMARY KEY,
      started_at INTEGER NOT NULL
    );
    """)

    conn.commit()
    conn.close()
