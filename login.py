"""Autenticação interativa; telefone, código e senha nunca passam pelo navegador."""
import asyncio
from telecourse import settings


async def main():
    if not settings.API_ID or not settings.API_HASH or settings.API_HASH == 'substitua_pelo_api_hash':
        raise SystemExit('Configure API_ID e API_HASH no .env (copie .env.example)')
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise SystemExit('Instale as dependências: pip install -r requirements.txt') from exc
    settings.ensure_directories()
    async with TelegramClient(str(settings.SESSION_PATH), settings.API_ID, settings.API_HASH) as client:
        await client.start()
        me = await client.get_me()
        print(f'Conta conectada com sucesso: {me.first_name}. Sessão salva apenas em data/.')


if __name__ == '__main__':
    asyncio.run(main())
