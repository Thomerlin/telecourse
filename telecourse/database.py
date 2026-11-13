"""Persistência SQLite, migrações iniciais e backups consistentes."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import settings

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL UNIQUE,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS courses (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL CHECK(length(trim(title)) > 0),
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS course_sources (
  course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  PRIMARY KEY(course_id, source_id)
);
CREATE TABLE IF NOT EXISTS modules (
  id INTEGER PRIMARY KEY,
  course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(course_id, title)
);
CREATE TABLE IF NOT EXISTS lessons (
  id INTEGER PRIMARY KEY,
  course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  message_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  original_title TEXT NOT NULL,
  filename TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL CHECK(kind IN ('video','pdf')),
  mime_type TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  duration INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_lessons_order ON lessons(course_id,module_id,sort_order);
CREATE TABLE IF NOT EXISTS progress (
  lesson_id INTEGER PRIMARY KEY REFERENCES lessons(id) ON DELETE CASCADE,
  position_seconds REAL NOT NULL DEFAULT 0,
  played_seconds REAL NOT NULL DEFAULT 0,
  completed INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_progress_latest ON progress(updated_at DESC);
CREATE TABLE IF NOT EXISTS import_batches (
  id TEXT PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  scanned INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'preview',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS import_items (
  batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
  message_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  filename TEXT NOT NULL DEFAULT '',
  proposed_module TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  kind TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  duration INTEGER NOT NULL DEFAULT 0,
  topic_id INTEGER,
  uncertain INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(batch_id,message_id)
);
"""


@contextmanager
def connect():
    settings.ensure_directories()
    connection = sqlite3.connect(settings.DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA busy_timeout=15000')
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# SCHEMA é a versão 1 e não deve mais ser alterado: mudanças de esquema entram aqui,
# um script SQL por versão (MIGRATIONS[0] leva o banco da versão 1 para a 2, e assim por diante).
MIGRATIONS = []


def initialize():
    with connect() as db:
        db.executescript(SCHEMA)
        db.execute('PRAGMA journal_mode=WAL')
        version = max(1, db.execute('PRAGMA user_version').fetchone()[0])
        for target, script in enumerate(MIGRATIONS, start=2):
            if version < target:
                db.executescript(script)
        db.execute(f'PRAGMA user_version={len(MIGRATIONS) + 1}')


def backup_database(keep=14) -> Path:
    """SQLite online backup; não copiar arquivo .db enquanto WAL está em uso."""
    settings.ensure_directories()
    if not settings.DB_PATH.exists():
        initialize()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = settings.BACKUP_DIR / f'telecourse-{timestamp}.db'
    with connect() as source, sqlite3.connect(destination) as target:
        source.backup(target)
    if hasattr(destination, 'chmod') and __import__('os').name != 'nt':
        destination.chmod(0o600)
    old_backups = sorted(settings.BACKUP_DIR.glob('telecourse-*.db'), reverse=True)
    for old in old_backups[keep:]:
        old.unlink(missing_ok=True)
    return destination


def row(sql, params=()):
    with connect() as db:
        record = db.execute(sql, params).fetchone()
    return dict(record) if record else None
