"""Restaure com o servidor parado. Exige argumento --confirmar."""
import argparse
import shutil
import sqlite3
from pathlib import Path
from telecourse import settings

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Restaura um backup após parar o TeleCourse.')
    parser.add_argument('backup', type=Path)
    parser.add_argument('--confirmar', action='store_true')
    args = parser.parse_args()
    if not args.confirmar:
        raise SystemExit('Pare o servidor e execute novamente com --confirmar.')
    if not args.backup.is_file():
        raise SystemExit('Backup não encontrado.')
    with sqlite3.connect(args.backup) as source:
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('O backup falhou na verificação de integridade.')
    settings.ensure_directories()
    if settings.DB_PATH.exists():
        from telecourse.database import backup_database
        print('Cópia de segurança do banco atual:', backup_database())
    for suffix in ('-wal', '-shm'):
        Path(str(settings.DB_PATH) + suffix).unlink(missing_ok=True)
    shutil.copy2(args.backup, settings.DB_PATH)
    print('Backup restaurado. Reinicie o TeleCourse.')
