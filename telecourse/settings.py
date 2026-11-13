"""Configuração local. Dados de sessão e SQLite nunca vão para o Git."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATA_DIR = Path(os.getenv('TELECOURSE_DATA_DIR', str(ROOT / 'data'))).expanduser().resolve()
DB_PATH = DATA_DIR / 'telecourse.db'
BACKUP_DIR = DATA_DIR / 'backups'
MEDIA_DIR = DATA_DIR / 'media'  # aulas baixadas para assistir offline
SESSION_PATH = DATA_DIR / 'telegram'
API_ID = int(os.getenv('API_ID') or 0)
API_HASH = os.getenv('API_HASH', '')
# Desligado por padrão: canais/mensagens com "restringir salvamento de conteúdo" ficam bloqueados.
ALLOW_PROTECTED = os.getenv('TELECOURSE_ALLOW_PROTECTED', '').strip().lower() in ('1', 'true', 'yes', 'sim')


def ensure_directories():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        DATA_DIR.chmod(0o700)
