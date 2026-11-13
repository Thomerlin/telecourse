"""API local e single-user do TeleCourse.

NÃO publique esta API em rede pública: login Telegram fica na sessão local.
Use `python run.py` (host 127.0.0.1 fixo).
"""
import asyncio
import math
import re
import shutil
import sqlite3
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import __version__, settings
from .database import backup_database, connect, initialize, row
from .organizer import media_info, organize, propose
from .telegram_gateway import gateway, FloodWaitError, RPCError

STATIC = settings.ROOT / 'static'


@asynccontextmanager
async def lifespan(_app):
    was_existing = settings.DB_PATH.exists()
    initialize()
    # Um backup diário de abertura, se já existir um banco de dados anterior.
    if was_existing:
        backups = sorted(settings.BACKUP_DIR.glob('telecourse-*.db'))
        if not backups or (datetime.now(timezone.utc).timestamp() - backups[-1].stat().st_mtime) > 86400:
            backup_database()
    try:
        await gateway.connect()
    except (OSError, TimeoutError, ConnectionError):
        pass  # Biblioteca local pode abrir sem conexão, conteúdo depende do Telegram.
    global _download_slots
    _download_slots = asyncio.Semaphore(1)  # um download por vez, para não disputar banda com o player
    yield
    pending = list(_download_tasks.values())
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    await gateway.disconnect()


app = FastAPI(title='TeleCourse', version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])


@app.middleware('http')
async def security_headers(request, call_next):
    # Escritas só são aceitas da própria interface: bloqueia CSRF vindo de outros sites/portas.
    origin = request.headers.get('origin')
    cross_origin = bool(origin) and urlsplit(origin).netloc != request.headers.get('host', '')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and (
            cross_origin or request.headers.get('sec-fetch-site') == 'cross-site'):
        response = JSONResponse({'detail': 'Origem não permitida'}, status_code=403)
    else:
        response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; media-src 'self' blob:; frame-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'self'; form-action 'self'"
    )
    return response


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html')


@app.get('/static/{filename}')
def asset(filename: str):
    if filename not in ('app.js', 'styles.css'):
        raise HTTPException(404, 'Arquivo não encontrado')
    return FileResponse(STATIC / filename)


@app.get('/api/status')
async def status():
    configured = bool(gateway.client)
    connected = False
    label = ''
    message = 'Configure .env e execute python login.py'
    if configured:
        try:
            await gateway.ensure_connected()
            connected = bool(await gateway.client.is_user_authorized())
            if connected:
                profile = await gateway.client.get_me()
                label = getattr(profile, 'first_name', '') or 'Telegram'
                message = 'Conectado'
        except (OSError, ConnectionError, RuntimeError, RPCError, HTTPException):
            message = 'Sem internet — só aulas baixadas'
    return {'configured': configured, 'ready': connected, 'name': label,
            'message': message,
            'version': __version__}


@app.get('/api/chats')
async def list_chats():
    try:
        return await gateway.dialogs()
    except FloodWaitError as exc:
        raise HTTPException(429, f'Telegram solicitou pausa de {exc.seconds}s') from exc


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chat_id: int
    limit: int = Field(default=600, ge=1, le=3000)
    from_id: int | None = Field(default=None, ge=1)
    to_id: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def ordered_bounds(self):
        if self.from_id is not None and self.to_id is not None and self.from_id > self.to_id:
            raise ValueError('ID inicial não pode ser maior que o final')
        return self


def batch_details(batch_id):
    with connect() as db:
        batch = db.execute('''SELECT b.*, s.title AS source_title, s.chat_id AS chat_id
                              FROM import_batches b JOIN sources s ON s.id=b.source_id
                              WHERE b.id=?''', (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404, 'Prévia não encontrada')
        items = [dict(r) for r in db.execute('''SELECT message_id,title,filename,proposed_module,
            sort_order,kind,mime_type,file_size,duration,topic_id,uncertain FROM import_items
            WHERE batch_id=? ORDER BY sort_order,message_id''', (batch_id,))]
    return {'batch': dict(batch), 'items': items}


@app.post('/api/imports/preview')
async def preview_import(payload: PreviewRequest):
    tg = await gateway.authorized()
    entity = await gateway.entity(payload.chat_id)
    source_title = getattr(entity, 'title', None) or 'Conversa Telegram'
    kind = 'Canal' if getattr(entity, 'broadcast', False) else 'Grupo'
    candidates = []
    scanned = 0
    # O intervalo é aplicado pelo Telegram (limites exclusivos), então o limite conta
    # mensagens dentro do intervalo, e não apenas as mais recentes da conversa.
    bounds = {}
    if payload.from_id is not None:
        bounds['min_id'] = payload.from_id - 1
    if payload.to_id is not None:
        bounds['max_id'] = payload.to_id + 1
    try:
        async for message in tg.iter_messages(entity, limit=payload.limit, **bounds):
            scanned += 1
            if not settings.ALLOW_PROTECTED and getattr(message, 'noforwards', False):
                continue
            media = media_info(message)
            if media:
                candidates.append(propose(message, media))
    except FloodWaitError as exc:
        raise HTTPException(429, f'Telegram solicitou pausa de {exc.seconds}s') from exc
    except RPCError as exc:
        raise HTTPException(502, f'Falha ao ler o histórico: {type(exc).__name__}') from exc
    candidates = organize(candidates)
    batch_id = uuid4().hex
    with connect() as db:
        db.execute("DELETE FROM import_batches WHERE created_at < datetime('now','-7 days')")
        db.execute('INSERT INTO sources (chat_id,title,kind) VALUES (?,?,?) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title',
                   (payload.chat_id, source_title, kind))
        source_id = db.execute('SELECT id FROM sources WHERE chat_id=?', (payload.chat_id,)).fetchone()['id']
        db.execute('INSERT INTO import_batches (id,source_id,scanned) VALUES (?,?,?)', (batch_id, source_id, scanned))
        for index, item in enumerate(candidates):
            db.execute('''INSERT INTO import_items (batch_id,message_id,title,filename,proposed_module,
                sort_order,kind,mime_type,file_size,duration,topic_id,uncertain)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (batch_id,item['message_id'],item['title'],item['filename'],item['proposed_module'],
                 index,item['kind'],item['mime_type'],item['file_size'],item['duration'],item['topic_id'],item['uncertain']))
    return batch_details(batch_id)


@app.get('/api/imports/{batch_id}')
def get_preview(batch_id: str):
    return batch_details(batch_id)


class SelectedItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    module: str = Field(min_length=1, max_length=120)


class CommitRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    course_id: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=150)
    items: list[SelectedItem] = Field(min_length=1, max_length=3000)

    @model_validator(mode='after')
    def target(self):
        if self.course_id is None and not (self.title and self.title.strip()):
            raise ValueError('Informe um nome para o novo curso ou selecione um existente')
        if len({item.message_id for item in self.items}) != len(self.items):
            raise ValueError('A mesma mensagem foi selecionada duas vezes')
        return self


@app.post('/api/imports/{batch_id}/commit')
def commit_import(batch_id: str, payload: CommitRequest):
    with connect() as db:
        batch = db.execute('SELECT * FROM import_batches WHERE id=?', (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404, 'Prévia não encontrada')
        if batch['status'] != 'preview':
            raise HTTPException(409, 'Esta prévia já foi importada')
        staged = {r['message_id']: r for r in db.execute('SELECT * FROM import_items WHERE batch_id=?', (batch_id,))}
        if any(item.message_id not in staged for item in payload.items):
            raise HTTPException(400, 'Seleção contém mensagem que não foi analisada')
        if payload.course_id:
            course = db.execute('SELECT id FROM courses WHERE id=?', (payload.course_id,)).fetchone()
            if not course:
                raise HTTPException(404, 'Curso de destino não encontrado')
            course_id = payload.course_id
        else:
            course_id = db.execute('INSERT INTO courses (title) VALUES (?)', (payload.title.strip(),)).lastrowid
        db.execute('INSERT OR IGNORE INTO course_sources (course_id,source_id) VALUES (?,?)',
                   (course_id,batch['source_id']))
        next_module = db.execute('SELECT COALESCE(MAX(sort_order),-1)+1 FROM modules WHERE course_id=?',
                                 (course_id,)).fetchone()[0]
        orders = {r['module_id']: r['max_order'] + 1 for r in db.execute(
            'SELECT module_id,MAX(sort_order) AS max_order FROM lessons WHERE course_id=? GROUP BY module_id',
            (course_id,))}
        added = duplicates = conflicts = 0
        for selection in payload.items:  # posição enviada pelo usuário = ordem de estudo
            data = staged[selection.message_id]
            prior = db.execute('SELECT id,course_id FROM lessons WHERE source_id=? AND message_id=?',
                               (batch['source_id'],selection.message_id)).fetchone()
            if prior:
                if prior['course_id'] == course_id:
                    duplicates += 1
                else:
                    conflicts += 1
                continue
            module_title = selection.module.strip()
            mod = db.execute('SELECT id FROM modules WHERE course_id=? AND title=?',
                             (course_id,module_title)).fetchone()
            if mod:
                module_id = mod['id']
            else:
                module_id = db.execute('INSERT INTO modules (course_id,title,sort_order) VALUES (?,?,?)',
                                       (course_id,module_title,next_module)).lastrowid
                next_module += 1
            position = orders.get(module_id,0)
            orders[module_id] = position + 1
            db.execute('''INSERT INTO lessons (course_id,module_id,source_id,message_id,title,original_title,
                filename,kind,mime_type,file_size,duration,sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (course_id,module_id,batch['source_id'],selection.message_id,selection.title.strip(),data['title'],
                 data['filename'],data['kind'],data['mime_type'],data['file_size'],data['duration'],position))
            added += 1
        db.execute('UPDATE import_batches SET status=? WHERE id=?', ('committed',batch_id))
        db.execute('UPDATE courses SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (course_id,))
    return {'course_id': course_id, 'added': added, 'duplicates': duplicates, 'conflicts': conflicts}


@app.get('/api/library')
def library():
    with connect() as db:
        rows = db.execute('''SELECT c.id,c.title,c.description,c.updated_at,
            COUNT(l.id) AS total,COALESCE(SUM(p.completed),0) AS completed,
            COALESCE(SUM(l.duration),0) AS duration_seconds,
            COALESCE(SUM(CASE WHEN p.completed=1 THEN l.duration ELSE COALESCE(p.played_seconds,0) END),0) AS watched_seconds,
            COALESCE(SUM(CASE WHEN p.played_seconds>0 OR p.position_seconds>0 THEN 1 ELSE 0 END),0) AS started,
            (SELECT l2.id FROM lessons l2 JOIN progress p2 ON p2.lesson_id=l2.id
             WHERE l2.course_id=c.id AND l2.hidden=0 AND p2.completed=0
             ORDER BY p2.updated_at DESC,l2.id DESC LIMIT 1) AS resume_lesson_id
            FROM courses c LEFT JOIN lessons l ON l.course_id=c.id AND l.hidden=0
            LEFT JOIN progress p ON p.lesson_id=l.id
            GROUP BY c.id ORDER BY c.updated_at DESC,c.id DESC''').fetchall()
        sizes = downloaded_sizes()
        owners = {r['id']: r['course_id'] for r in db.execute('SELECT id,course_id FROM lessons WHERE hidden=0')} if sizes else {}
    courses = [dict(r, downloaded=0, downloaded_bytes=0) for r in rows]
    by_id = {course['id']: course for course in courses}
    for lesson_id, size in sizes.items():
        course = by_id.get(owners.get(lesson_id))
        if course:
            course['downloaded'] += 1
            course['downloaded_bytes'] += size
    return courses


@app.get('/api/courses/{course_id}')
def get_course(course_id: int):
    with connect() as db:
        course = db.execute('SELECT * FROM courses WHERE id=?', (course_id,)).fetchone()
        if not course:
            raise HTTPException(404, 'Curso não encontrado')
        mods = [dict(r) for r in db.execute(
            'SELECT * FROM modules WHERE course_id=? ORDER BY sort_order,id', (course_id,))]
        lessons = [dict(r) for r in db.execute('''SELECT l.*, COALESCE(p.position_seconds,0) AS position_seconds,
            COALESCE(p.played_seconds,0) AS played_seconds, COALESCE(p.completed,0) AS completed,
            p.updated_at AS last_played_at FROM lessons l LEFT JOIN progress p ON p.lesson_id=l.id
            WHERE l.course_id=? AND l.hidden=0 ORDER BY l.sort_order,l.id''', (course_id,))]
        sources = [dict(r) for r in db.execute('''SELECT s.id,s.title,s.chat_id,s.kind FROM sources s
            JOIN course_sources cs ON cs.source_id=s.id WHERE cs.course_id=? ORDER BY s.id''', (course_id,))]
    sizes = downloaded_sizes()
    for lesson in lessons:
        lesson['downloaded'] = lesson['id'] in sizes
        lesson['local_bytes'] = sizes.get(lesson['id'], 0)
    for mod in mods:
        mod['lessons'] = [lesson for lesson in lessons if lesson['module_id'] == mod['id']]
        mod['duration_seconds'] = sum(lesson['duration'] for lesson in mod['lessons'])
    # Aula concluída conta inteira; em andamento conta o tempo já assistido.
    watched = sum(l['duration'] if l['completed'] else l['played_seconds'] for l in lessons)
    return {'course':dict(course), 'modules':mods, 'sources':sources,
            'duration_seconds':sum(l['duration'] for l in lessons), 'watched_seconds':watched,
            'downloaded_count':sum(l['downloaded'] for l in lessons),
            'downloaded_bytes':sum(l['local_bytes'] for l in lessons),
            'total':len(lessons),'completed':sum(l['completed'] for l in lessons)}


class CourseEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1500)


@app.patch('/api/courses/{course_id}')
def edit_course(course_id: int, payload: CourseEdit):
    with connect() as db:
        if not db.execute('SELECT 1 FROM courses WHERE id=?', (course_id,)).fetchone():
            raise HTTPException(404,'Curso não encontrado')
        if payload.title is not None:
            if not payload.title.strip():
                raise HTTPException(422,'Nome vazio')
            db.execute('UPDATE courses SET title=? WHERE id=?',(payload.title.strip(),course_id))
        if payload.description is not None:
            db.execute('UPDATE courses SET description=? WHERE id=?',(payload.description.strip(),course_id))
        db.execute('UPDATE courses SET updated_at=CURRENT_TIMESTAMP WHERE id=?',(course_id,))
    return {'ok':True}


@app.delete('/api/courses/{course_id}')
def delete_course(course_id: int):
    with connect() as db:
        lesson_ids = [r['id'] for r in db.execute('SELECT id FROM lessons WHERE course_id=?',(course_id,))]
        count = db.execute('DELETE FROM courses WHERE id=?',(course_id,)).rowcount
    if not count:
        raise HTTPException(404,'Curso não encontrado')
    for lesson_id in lesson_ids:
        discard_download(lesson_id)
    return {'ok':True,'telegram_untouched':True}


class ModuleCreate(BaseModel):
    title: str = Field(min_length=1,max_length=120)


@app.post('/api/courses/{course_id}/modules')
def add_module(course_id:int,payload:ModuleCreate):
    with connect() as db:
        if not db.execute('SELECT 1 FROM courses WHERE id=?',(course_id,)).fetchone():
            raise HTTPException(404,'Curso não encontrado')
        position = db.execute('SELECT COALESCE(MAX(sort_order),-1)+1 FROM modules WHERE course_id=?',
                              (course_id,)).fetchone()[0]
        try:
            ident = db.execute('INSERT INTO modules(course_id,title,sort_order) VALUES (?,?,?)',
                               (course_id,payload.title.strip(),position)).lastrowid
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409,'Já existe um módulo com esse nome') from exc
    return {'id':ident}


@app.patch('/api/modules/{module_id}')
def rename_module(module_id:int,payload:ModuleCreate):
    with connect() as db:
        try:
            found = db.execute('UPDATE modules SET title=? WHERE id=?',(payload.title.strip(),module_id)).rowcount
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409,'Já existe um módulo com esse nome') from exc
        if not found:
            raise HTTPException(404,'Módulo não encontrado')
    return {'ok':True}


class LessonEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None,min_length=1,max_length=200)
    module_id: int | None = Field(default=None,ge=1)


@app.patch('/api/lessons/{lesson_id}')
def edit_lesson(lesson_id:int,payload:LessonEdit):
    with connect() as db:
        lesson = db.execute('SELECT * FROM lessons WHERE id=?',(lesson_id,)).fetchone()
        if not lesson:
            raise HTTPException(404,'Aula não encontrada')
        if payload.module_id is not None and payload.module_id != lesson['module_id']:
            module = db.execute('SELECT id FROM modules WHERE id=? AND course_id=?',
                                (payload.module_id,lesson['course_id'])).fetchone()
            if not module:
                raise HTTPException(400,'Módulo pertence a outro curso')
            pos = db.execute('SELECT COALESCE(MAX(sort_order),-1)+1 FROM lessons WHERE module_id=?',
                             (payload.module_id,)).fetchone()[0]
            db.execute('UPDATE lessons SET module_id=?,sort_order=? WHERE id=?',
                       (payload.module_id,pos,lesson_id))
        if payload.title is not None:
            if not payload.title.strip():
                raise HTTPException(422,'Nome vazio')
            db.execute('UPDATE lessons SET title=? WHERE id=?',(payload.title.strip(),lesson_id))
    return {'ok':True}


@app.delete('/api/lessons/{lesson_id}')
def hide_lesson(lesson_id:int):
    with connect() as db:
        updated = db.execute('UPDATE lessons SET hidden=1 WHERE id=?',(lesson_id,)).rowcount
    if not updated:
        raise HTTPException(404,'Aula não encontrada')
    discard_download(lesson_id)
    return {'ok':True,'telegram_untouched':True}


class ModuleOrder(BaseModel):
    module_id: int
    lesson_ids: list[int]


class CourseOrder(BaseModel):
    modules: list[ModuleOrder]


@app.put('/api/courses/{course_id}/order')
def reorder_course(course_id:int,payload:CourseOrder):
    with connect() as db:
        existing_modules = {r['id'] for r in db.execute('SELECT id FROM modules WHERE course_id=?',(course_id,))}
        existing_lessons = {r['id'] for r in db.execute('SELECT id FROM lessons WHERE course_id=? AND hidden=0',(course_id,))}
        submitted_modules = [m.module_id for m in payload.modules]
        submitted_lessons = [x for module in payload.modules for x in module.lesson_ids]
        if (set(submitted_modules) != existing_modules or len(submitted_modules) != len(existing_modules) or
            set(submitted_lessons) != existing_lessons or len(submitted_lessons) != len(existing_lessons)):
            raise HTTPException(400,'A ordenação precisa conter todos os módulos e aulas visíveis exatamente uma vez')
        for mod_index,module in enumerate(payload.modules):
            db.execute('UPDATE modules SET sort_order=? WHERE id=?',(mod_index,module.module_id))
            for lesson_index, lesson_id in enumerate(module.lesson_ids):
                db.execute('UPDATE lessons SET module_id=?,sort_order=? WHERE id=?',
                           (module.module_id,lesson_index,lesson_id))
    return {'ok':True}


class ProgressInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    position_seconds: float = Field(ge=0, le=864000)
    played_delta_seconds: float = Field(default=0, ge=0, le=30)
    completed: bool | None = None

    @model_validator(mode='after')
    def finite_values(self):
        if not math.isfinite(self.position_seconds) or not math.isfinite(self.played_delta_seconds):
            raise ValueError('Valores de progresso devem ser finitos')
        return self


@app.put('/api/lessons/{lesson_id}/progress')
def update_progress(lesson_id:int,payload:ProgressInput):
    with connect() as db:
        lesson = db.execute('SELECT duration FROM lessons WHERE id=? AND hidden=0',(lesson_id,)).fetchone()
        if not lesson:
            raise HTTPException(404,'Aula não encontrada')
        old = db.execute('SELECT * FROM progress WHERE lesson_id=?',(lesson_id,)).fetchone()
        duration = int(lesson['duration'])
        pos = min(payload.position_seconds,float(duration)) if duration else payload.position_seconds
        played = (old['played_seconds'] if old else 0) + payload.played_delta_seconds
        if duration:
            played = min(played,float(duration))
        if payload.completed is False and old and old['completed']:
            played = 0.0  # desmarcar zera o tempo assistido, senão a regra dos 90% remarcaria a aula
        if payload.completed is not None:
            done = int(payload.completed)
        else:
            done = int((old['completed'] if old else 0) or (duration > 0 and played >= duration*0.9))
        db.execute('''INSERT INTO progress (lesson_id,position_seconds,played_seconds,completed,updated_at)
            VALUES (?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(lesson_id) DO UPDATE SET position_seconds=excluded.position_seconds,
            played_seconds=excluded.played_seconds,completed=excluded.completed,updated_at=CURRENT_TIMESTAMP''',
            (lesson_id,pos,played,done))
    return {'position_seconds':pos,'played_seconds':played,'completed':bool(done)}


@app.post('/api/backup')
def do_backup():
    path = backup_database()
    return {'ok':True,'filename':path.name,'location':'data/backups/'}


@app.get('/api/export/progress')
def export_progress():
    with connect() as db:
        result = [dict(r) for r in db.execute('''SELECT c.title AS course,m.title AS module,l.title AS lesson,
           s.chat_id,l.message_id,p.position_seconds,p.played_seconds,p.completed,p.updated_at
           FROM progress p JOIN lessons l ON l.id=p.lesson_id JOIN courses c ON c.id=l.course_id
           JOIN modules m ON m.id=l.module_id JOIN sources s ON s.id=l.source_id
           ORDER BY c.id,m.sort_order,l.sort_order''')]
    return {'version':1,'exported_at':datetime.now(timezone.utc).isoformat(),'lessons':result}


DISK_RESERVE = 1024 ** 3  # nunca encher o disco: mantém 1 GB livre
download_jobs = {}    # lesson_id -> {'state': queued|downloading|error, 'done', 'total', 'error'}
_download_tasks = {}  # lesson_id -> asyncio.Task em andamento
_download_slots = None


def media_path(lesson_id):
    return settings.MEDIA_DIR / f'{int(lesson_id)}.media'


def downloaded_sizes():
    if not settings.MEDIA_DIR.is_dir():
        return {}
    return {int(p.stem): p.stat().st_size for p in settings.MEDIA_DIR.glob('*.media') if p.stem.isdigit()}


def discard_download(lesson_id):
    """Cancela o download em andamento e apaga a cópia local. False se o arquivo está em uso."""
    task = _download_tasks.pop(lesson_id, None)
    download_jobs.pop(lesson_id, None)
    if task:
        task.cancel()  # a própria tarefa apaga o .part ao ser cancelada
    try:
        media_path(lesson_id).unlink(missing_ok=True)
    except PermissionError:  # Windows: arquivo aberto pelo player
        return False
    return True


async def run_download(lesson_id):
    job = download_jobs[lesson_id]
    partial = media_path(lesson_id).with_suffix('.part')
    try:
        async with _download_slots:
            job['state'] = 'downloading'
            tg = await gateway.authorized()
            lesson = source_asset(lesson_id)
            entity = await gateway.entity(lesson['chat_id'])
            message = await tg.get_messages(entity, ids=lesson['message_id'])
            if not message or not getattr(message, 'document', None):
                raise HTTPException(404, 'A mensagem original não está mais acessível')
            # Mesmo com TELECOURSE_ALLOW_PROTECTED, conteúdo com salvamento restrito só toca por streaming.
            if getattr(entity, 'noforwards', False) or getattr(message, 'noforwards', False):
                raise HTTPException(403, 'Canal com salvamento restrito: aula disponível só por streaming')
            total = int(message.document.size or 0)
            if total <= 0:
                raise HTTPException(404, 'Mídia sem tamanho válido')
            settings.ensure_directories()
            if shutil.disk_usage(settings.MEDIA_DIR).free < total + DISK_RESERVE:
                raise HTTPException(507, 'Espaço em disco insuficiente')
            job['total'] = total
            with open(partial, 'wb') as out:
                async for block in telegram_bytes(tg, message, 0, total - 1, total):
                    out.write(block)
                    job['done'] += len(block)
            if job['done'] != total:
                raise HTTPException(502, 'Download incompleto; tente de novo')
            partial.replace(media_path(lesson_id))
            download_jobs.pop(lesson_id, None)
    except asyncio.CancelledError:
        partial.unlink(missing_ok=True)
        raise
    except HTTPException as exc:
        partial.unlink(missing_ok=True)
        job.update(state='error', error=str(exc.detail))
    except (RPCError, OSError, ConnectionError) as exc:
        partial.unlink(missing_ok=True)
        job.update(state='error', error=f'Falha no download ({type(exc).__name__})')
    finally:
        if _download_tasks.get(lesson_id) is asyncio.current_task():
            del _download_tasks[lesson_id]


def queue_download(lesson_id):
    if media_path(lesson_id).exists() or lesson_id in _download_tasks:
        return False
    download_jobs[lesson_id] = {'state': 'queued', 'done': 0, 'total': 0, 'error': ''}
    _download_tasks[lesson_id] = asyncio.ensure_future(run_download(lesson_id))
    return True


@app.get('/api/downloads')
def list_downloads():
    sizes = downloaded_sizes()
    return {'jobs': {str(k): v for k, v in download_jobs.items()},
            'count': len(sizes), 'bytes': sum(sizes.values())}


@app.post('/api/lessons/{lesson_id}/download', status_code=202)
async def download_lesson(lesson_id: int):
    source_asset(lesson_id)
    await gateway.authorized()
    return {'queued': int(queue_download(lesson_id))}


@app.delete('/api/lessons/{lesson_id}/download')
async def remove_download(lesson_id: int):
    if not discard_download(lesson_id):
        raise HTTPException(409, 'Arquivo em uso. Pare o vídeo e tente de novo.')
    return {'ok': True}


def course_lesson_ids(course_id, module_id=None):
    with connect() as db:
        if not db.execute('SELECT 1 FROM courses WHERE id=?', (course_id,)).fetchone():
            raise HTTPException(404, 'Curso não encontrado')
        rows = db.execute("""SELECT l.id FROM lessons l JOIN modules m ON m.id=l.module_id
            WHERE l.course_id=? AND l.hidden=0 AND (? IS NULL OR l.module_id=?)
            ORDER BY m.sort_order,m.id,l.sort_order,l.id""", (course_id, module_id, module_id)).fetchall()
    return [r['id'] for r in rows]


@app.post('/api/courses/{course_id}/download', status_code=202)
async def download_course(course_id: int, module_id: int | None = None):
    lesson_ids = course_lesson_ids(course_id, module_id)
    await gateway.authorized()
    return {'queued': sum(queue_download(lesson_id) for lesson_id in lesson_ids)}


@app.delete('/api/courses/{course_id}/download')
async def remove_course_downloads(course_id: int):
    results = [discard_download(lesson_id) for lesson_id in course_lesson_ids(course_id)]
    return {'ok': True, 'failed': results.count(False)}


def source_asset(lesson_id):
    lesson = row('''SELECT l.*,s.chat_id FROM lessons l JOIN sources s ON s.id=l.source_id
                    WHERE l.id=? AND l.hidden=0''',(lesson_id,))
    if not lesson:
        raise HTTPException(404,'Aula não encontrada')
    return lesson


STREAM_PART = 512 * 1024  # maior parte aceita pelo Telegram; os offsets precisam ser múltiplos dela
STREAM_PARALLEL = 4
MEDIA_TTL = 300 # segundos; bem abaixo da validade das referências de arquivo do Telegram
_media_cache = {}


async def telegram_asset(lesson_id):
    tg = await gateway.authorized()
    lesson = source_asset(lesson_id)
    # O player faz muitas requisições Range por aula; sem cache cada uma custaria uma RPC.
    key = (lesson['chat_id'], lesson['message_id'])
    cached = _media_cache.get(lesson_id)
    if cached and cached[0] > time.monotonic() and cached[1] == key:
        return tg, cached[2], lesson
    entity = await gateway.entity(lesson['chat_id'])
    try:
        message = await tg.get_messages(entity,ids=lesson['message_id'])
    except RPCError as exc:
        raise HTTPException(502,'Não foi possível buscar a mídia no Telegram') from exc
    if not message or not getattr(message,'document',None):
        raise HTTPException(404,'A mensagem original não está mais acessível')
    if not settings.ALLOW_PROTECTED and getattr(message,'noforwards',False):
        raise HTTPException(403,'A mensagem protege seu conteúdo contra cópia')
    if len(_media_cache) >= 64:
        _media_cache.clear()
    _media_cache[lesson_id] = (time.monotonic() + MEDIA_TTL, key, message)
    return tg, message, lesson


def range_of(header,total):
    if not header:
        return 0,total-1,False
    match = re.fullmatch(r'bytes=(\d*)-(\d*)',header.strip())
    if not match or (not match.group(1) and not match.group(2)):
        raise HTTPException(416,'Range inválido',headers={'Content-Range':f'bytes */{total}'})
    if match.group(1):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else total-1
    else:
        amount = int(match.group(2))
        if amount < 1:
            raise HTTPException(416,'Range inválido',headers={'Content-Range':f'bytes */{total}'})
        start,end = max(0,total-amount),total-1
    if start >= total or end < start:
        raise HTTPException(416,'Range fora do arquivo',headers={'Content-Range':f'bytes */{total}'})
    return start,min(end,total-1),True


async def telegram_bytes(tg, message, start, end, total):
    """Bytes [start, end] da mídia. Uma requisição por vez fica abaixo do bitrate de vídeos
    longos, então pedimos algumas partes alinhadas em paralelo e entregamos na ordem."""
    async def part(offset):
        stream = tg.iter_download(message.media,offset=offset,request_size=STREAM_PART,limit=1,file_size=total)
        try:
            async for block in stream:
                return bytes(block)
            return b''
        finally:
            await stream.close()

    offsets = iter(range(start - start % STREAM_PART, end + 1, STREAM_PART))
    pending = deque()
    try:
        while True:
            while len(pending) < STREAM_PARALLEL:
                offset = next(offsets, None)
                if offset is None:
                    break
                pending.append((offset, asyncio.ensure_future(part(offset))))
            if not pending:
                break
            offset, task = pending.popleft()
            block = await task
            portion = block[max(start, offset) - offset:end + 1 - offset]
            if not portion:
                break
            yield portion
    finally:
        for _, task in pending:
            task.cancel()


def local_bytes(path, start, end):
    with open(path, 'rb') as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


async def media_response(lesson_id, request, only_head=False):
    path = media_path(lesson_id)
    if path.exists():  # aula baixada: toca do disco, sem depender do Telegram
        lesson, tg, message = source_asset(lesson_id), None, None
        total = path.stat().st_size
    else:
        tg,message,lesson = await telegram_asset(lesson_id)
        total = int(message.document.size or 0)
    if total <= 0:
        raise HTTPException(404,'Mídia sem tamanho válido')
    start,end,partial = range_of(request.headers.get('range'),total)
    headers = {'Accept-Ranges':'bytes','Content-Length':str(end-start+1),
               'Cache-Control':'private, no-store'}
    if partial:
        headers['Content-Range'] = f'bytes {start}-{end}/{total}'
    status_code = 206 if partial else 200
    if only_head:
        return Response(status_code=status_code,headers=headers,media_type=lesson['mime_type'])
    body = local_bytes(path,start,end) if tg is None else telegram_bytes(tg,message,start,end,total)
    return StreamingResponse(body,status_code=status_code,media_type=lesson['mime_type'],headers=headers)


@app.get('/api/lessons/{lesson_id}/stream')
async def stream_media(lesson_id:int,request:Request):
    return await media_response(lesson_id,request)


@app.head('/api/lessons/{lesson_id}/stream')
async def head_media(lesson_id:int,request:Request):
    return await media_response(lesson_id,request,only_head=True)
