"""Isola a conexão MTProto para os testes de domínio funcionarem offline."""
from fastapi import HTTPException
from . import settings

try:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError, RPCError
except ImportError:  # testes do catálogo podem rodar sem acesso à rede / Telethon
    TelegramClient = None
    class FloodWaitError(Exception):
        seconds = 0
    class RPCError(Exception):
        pass


class Gateway:
    def __init__(self):
        self.client = None
        if settings.API_ID and settings.API_HASH and TelegramClient:
            settings.ensure_directories()
            self.client = TelegramClient(str(settings.SESSION_PATH), settings.API_ID, settings.API_HASH)

    async def connect(self):
        if self.client:
            await self.client.connect()

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()

    async def authorized(self):
        if not self.client:
            raise HTTPException(503, 'Preencha API_ID/API_HASH no .env e instale as dependências')
        if not await self.client.is_user_authorized():
            raise HTTPException(401, 'Execute python login.py no terminal para conectar sua conta')
        return self.client

    async def dialogs(self):
        client = await self.authorized()
        output = []
        async for item in client.iter_dialogs(limit=500):
            if not (item.is_channel or item.is_group):
                continue
            protected = bool(getattr(item.entity, 'noforwards', False))
            output.append({'chat_id': int(item.id), 'title': item.name or 'Sem título',
                           'kind': 'Canal' if item.is_channel else 'Grupo', 'protected': protected})
        return output

    async def entity(self, chat_id):
        client = await self.authorized()
        try:
            entity = await client.get_entity(chat_id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(404, 'Conversa não encontrada: abra o canal no Telegram primeiro') from exc
        if getattr(entity, 'noforwards', False):
            raise HTTPException(403, 'O canal ou grupo protege seu conteúdo contra cópia')
        return entity


gateway = Gateway()
