"""Testes locais sem credenciais nem acesso à rede Telegram."""
from types import SimpleNamespace
import sqlite3
import pytest
from fastapi.testclient import TestClient

from telecourse import server, settings
from telecourse.database import initialize, connect, backup_database
from telecourse.organizer import media_info, propose, organize
from telecourse.server import app, range_of


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(settings, 'DB_PATH', tmp_path / 'telecourse.db')
    monkeypatch.setattr(settings, 'BACKUP_DIR', tmp_path / 'backups')
    monkeypatch.setattr(settings, 'MEDIA_DIR', tmp_path / 'media')
    monkeypatch.setattr(settings, 'SESSION_PATH', tmp_path / 'telegram')
    # Com .env preenchido o gateway global teria um cliente real; os testes nunca devem usá-lo.
    monkeypatch.setattr(server.gateway, 'client', None)
    server._media_cache.clear()
    server.download_jobs.clear()
    with TestClient(app) as c:
        yield c


def stage_example():
    with connect() as db:
        source = db.execute("INSERT INTO sources(chat_id,title,kind) VALUES(-123456,'Curso privado','Canal')").lastrowid
        db.execute("INSERT INTO import_batches(id,source_id,scanned) VALUES('batch',?,4)", (source,))
        for ix,(msg,title,module,kind) in enumerate([
            (42,'Introdução','Módulo 01','video'),
            (43,'Laboratório','Módulo 01','video'),
            (44,'Materiais','Módulo 01','pdf'),
        ]):
            db.execute("""INSERT INTO import_items(batch_id,message_id,title,filename,proposed_module,sort_order,kind,mime_type,file_size,duration,uncertain)
              VALUES('batch',?,?,?,?,?,?,?,?,?,0)""", (msg,title,title+'.mp4',module,ix,kind,'application/pdf' if kind=='pdf' else 'video/mp4',500,120 if kind=='video' else 0))


def publish(client):
    stage_example()
    r=client.post('/api/imports/batch/commit',json={'title':'Curso teste','items':[
        {'message_id':42,'title':'Introdução','module':'Fundamentos'},
        {'message_id':43,'title':'Laboratório','module':'Fundamentos'},
        {'message_id':44,'title':'PDF','module':'Materiais'},
    ]})
    assert r.status_code==200, r.text
    return r.json()['course_id']


def test_import_preview_and_course_progress(client):
    c=publish(client)
    assert client.get('/api/library').json()[0]['total']==3
    course=client.get(f'/api/courses/{c}').json()
    assert len(course['modules'])==2
    lesson=course['modules'][0]['lessons'][0]['id']
    assert client.put(f'/api/lessons/{lesson}/progress',json={
        'position_seconds':46,'played_delta_seconds':10}).json()['completed'] is False
    assert client.put(f'/api/lessons/{lesson}/progress',json={
        'position_seconds':72,'played_delta_seconds':25}).json()['played_seconds']==35
    assert client.get(f'/api/courses/{c}').json()['modules'][0]['lessons'][0]['position_seconds']==72
    assert client.put(f'/api/lessons/{lesson}/progress',json={
        'position_seconds':90,'completed':True}).json()['completed'] is True
    assert client.get('/api/library').json()[0]['completed']==1
    assert client.put(f'/api/lessons/{lesson}/progress',json={
        'position_seconds':93,'completed':False}).json()['completed'] is False
    assert client.get('/api/export/progress').json()['lessons'][0]['position_seconds']==93


def test_reordering_is_saved_and_does_not_reset_progress(client):
    c=publish(client)
    course=client.get(f'/api/courses/{c}').json()
    one,two=course['modules']
    first=one['lessons'][0]['id']
    client.put(f'/api/lessons/{first}/progress',json={'position_seconds':17,'played_delta_seconds':5})
    data={'modules':[{'module_id':two['id'],'lesson_ids':[two['lessons'][0]['id'],first]},
                     {'module_id':one['id'],'lesson_ids':[one['lessons'][1]['id']]}]}
    r=client.put(f'/api/courses/{c}/order',json=data)
    assert r.status_code==200, r.text
    refreshed=client.get(f'/api/courses/{c}').json()
    assert refreshed['modules'][0]['lessons'][1]['id']==first
    assert refreshed['modules'][0]['lessons'][1]['position_seconds']==17
    assert client.put(f'/api/courses/{c}/order',json={'modules':[]}).status_code==400


def test_staging_and_duplicate_prevention(client):
    c=publish(client)
    r=client.post('/api/imports/batch/commit',json={'course_id':c,'items':[{'message_id':42,'title':'Repetida','module':'Fundamentos'}]})
    assert r.status_code==409
    with connect() as db:
        db.execute("INSERT INTO import_batches(id,source_id,scanned) SELECT 'new',source_id,1 FROM import_batches WHERE id='batch'")
        db.execute("""INSERT INTO import_items(batch_id,message_id,title,filename,proposed_module,sort_order,kind,mime_type,file_size,duration)
            SELECT 'new',message_id,title,filename,proposed_module,sort_order,kind,mime_type,file_size,duration
            FROM import_items WHERE batch_id='batch' AND message_id=42""")
    r=client.post('/api/imports/new/commit',json={'course_id':c,'items':[{'message_id':42,'title':'Repetida','module':'Fundamentos'}]})
    assert r.status_code==200 and r.json()['duplicates']==1
    assert client.get('/api/library').json()[0]['total']==3


def test_backup_sqlite_snapshot(client):
    c=publish(client)
    r=client.post('/api/backup');assert r.status_code==200
    backup=settings.BACKUP_DIR/r.json()['filename']
    assert backup.is_file()
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT count(*) FROM courses').fetchone()[0]==1


def test_progress_validation_and_security(client):
    c=publish(client)
    lesson=client.get(f'/api/courses/{c}').json()['modules'][0]['lessons'][0]['id']
    assert client.put(f'/api/lessons/{lesson}/progress',json={'position_seconds':-5}).status_code==422
    assert client.put(f'/api/lessons/{lesson}/progress',json={'position_seconds':5,'played_delta_seconds':31}).status_code==422
    assert client.get('/static/secret.txt').status_code==404
    assert client.get('/').headers['x-frame-options']=='SAMEORIGIN'
    assert client.get('/',headers={'host':'untrusted.example'}).status_code==400


def test_organizer_does_not_trust_message_order():
    def fake(mid,filename):
        doc=SimpleNamespace(mime_type='video/mp4',size=1000,attributes=[SimpleNamespace(duration=80)])
        return SimpleNamespace(id=mid,document=doc,file=SimpleNamespace(name=filename),raw_text='',reply_to=None)
    a=fake(4,'mod2_aula3.mp4'); b=fake(9,'mod1_aula1.mp4'); c=fake(12,'mod2_aula1.mp4')
    values=organize([propose(x,media_info(x)) for x in [a,b,c]])
    assert [item['message_id'] for item in values]==[9,12,4]
    assert values[0]['uncertain']==0
    d=fake(15,'random_video.mp4')
    assert propose(d,media_info(d))['uncertain']==1


def test_range_parsing():
    assert range_of(None,100)==(0,99,False)
    assert range_of('bytes=25-49',100)==(25,49,True)
    assert range_of('bytes=-10',100)==(90,99,True)
    assert range_of('bytes=25-',100)==(25,99,True)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:range_of('bytes=100-',100)
    assert e.value.status_code==416


def test_rename_keeps_position_and_unmarking_sticks(client):
    c=publish(client)
    first,second=client.get(f'/api/courses/{c}').json()['modules'][0]['lessons']
    r=client.patch(f"/api/lessons/{first['id']}",json={'title':'Renomeada','module_id':first['module_id']})
    assert r.status_code==200
    lessons=client.get(f'/api/courses/{c}').json()['modules'][0]['lessons']
    assert [l['id'] for l in lessons]==[first['id'],second['id']]
    assert lessons[0]['title']=='Renomeada'
    url=f"/api/lessons/{first['id']}/progress"
    for _ in range(4):
        done=client.put(url,json={'position_seconds':100,'played_delta_seconds':30}).json()['completed']
    assert done is True
    assert client.put(url,json={'position_seconds':100,'completed':False}).json()['completed'] is False
    assert client.put(url,json={'position_seconds':101,'played_delta_seconds':5}).json()['completed'] is False


def test_cross_origin_writes_are_rejected(client):
    assert client.post('/api/backup',headers={'origin':'http://evil.example'}).status_code==403
    assert client.post('/api/backup',headers={'sec-fetch-site':'cross-site'}).status_code==403
    assert client.post('/api/backup',headers={'origin':'http://testserver'}).status_code==200
    assert client.get('/api/library',headers={'origin':'http://evil.example'}).status_code==200


def test_stream_serves_requested_range_and_caches_message(client,monkeypatch):
    c=publish(client)
    lesson=client.get(f'/api/courses/{c}').json()['modules'][0]['lessons'][0]['id']
    data=bytes(range(256))*4
    calls=[]

    class Download:
        def __init__(self,offset,size):
            assert offset%size==0
            self.blocks=iter([data[offset:offset+size]] if offset<len(data) else [])
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return next(self.blocks)
            except StopIteration:
                raise StopAsyncIteration
        async def close(self):
            pass

    class FakeTelegram:
        async def get_messages(self,entity,ids):
            calls.append(ids)
            return SimpleNamespace(document=SimpleNamespace(size=len(data)),media=object(),noforwards=False)
        def iter_download(self,media,offset,request_size,**_):
            return Download(offset,request_size)

    fake=FakeTelegram()
    async def authorized():
        return fake
    async def entity(chat_id):
        return object()
    monkeypatch.setattr(server.gateway,'authorized',authorized)
    monkeypatch.setattr(server.gateway,'entity',entity)
    monkeypatch.setattr(server,'STREAM_PART',128)  # várias partes paralelas num arquivo pequeno
    r=client.get(f'/api/lessons/{lesson}/stream',headers={'range':'bytes=10-409'})
    assert r.status_code==206 and r.content==data[10:410]
    assert r.headers['content-range']==f'bytes 10-409/{len(data)}'
    assert client.get(f'/api/lessons/{lesson}/stream').content==data
    assert calls==[42]


def test_schema_version_is_recorded(client):
    with connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==1


def test_course_hours_are_totalled(client):
    c=publish(client)
    course=client.get(f'/api/courses/{c}').json()
    assert course['duration_seconds']==240 and course['watched_seconds']==0
    assert [m['duration_seconds'] for m in course['modules']]==[240,0]
    first,second=course['modules'][0]['lessons']
    client.put(f"/api/lessons/{first['id']}/progress",json={'position_seconds':30,'played_delta_seconds':30})
    client.put(f"/api/lessons/{second['id']}/progress",json={'position_seconds':0,'completed':True})
    assert client.get(f'/api/courses/{c}').json()['watched_seconds']==150
    entry=client.get('/api/library').json()[0]
    assert entry['duration_seconds']==240 and entry['watched_seconds']==150


def test_download_plays_offline_and_can_be_removed(client,monkeypatch):
    import time
    c=publish(client)
    first,second=client.get(f'/api/courses/{c}').json()['modules'][0]['lessons']
    data=bytes(range(256))*4
    monkeypatch.setattr(server,'STREAM_PART',128)
    monkeypatch.setattr(server,'DISK_RESERVE',0)

    class Download:
        def __init__(self,offset,size):
            self.blocks=iter([data[offset:offset+size]] if offset<len(data) else [])
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return next(self.blocks)
            except StopIteration:
                raise StopAsyncIteration
        async def close(self):
            pass

    class FakeTelegram:
        async def get_messages(self,entity,ids):
            return SimpleNamespace(document=SimpleNamespace(size=len(data)),media=object(),noforwards=ids==43)
        def iter_download(self,media,offset,request_size,**_):
            return Download(offset,request_size)

    fake=FakeTelegram()
    async def authorized():
        return fake
    async def entity(chat_id):
        return SimpleNamespace(noforwards=False)
    async def offline():
        raise server.HTTPException(503,'Sem conexão')
    monkeypatch.setattr(server.gateway,'authorized',authorized)
    monkeypatch.setattr(server.gateway,'entity',entity)

    def settle():
        for _ in range(200):
            jobs=client.get('/api/downloads').json()['jobs']
            if all(j['state']=='error' for j in jobs.values()):
                return jobs
            time.sleep(0.02)
        raise AssertionError('download não terminou')

    assert client.post(f'/api/courses/{c}/download').status_code==202
    jobs=settle()
    # A mensagem 43 tem salvamento restrito: fica só no streaming.
    assert list(jobs)==[str(second['id'])] and 'restrito' in jobs[str(second['id'])]['error']
    course=client.get(f'/api/courses/{c}').json()
    assert course['downloaded_count']==2 and course['downloaded_bytes']==2*len(data)
    assert client.get('/api/library').json()[0]['downloaded']==2
    monkeypatch.setattr(server.gateway,'authorized',offline)
    r=client.get(f"/api/lessons/{first['id']}/stream",headers={'range':'bytes=5-600'})
    assert r.status_code==206 and r.content==data[5:601]
    assert client.get(f"/api/lessons/{second['id']}/stream").status_code==503
    assert client.delete(f"/api/lessons/{first['id']}/download").status_code==200
    assert client.get(f'/api/courses/{c}').json()['downloaded_count']==1
    assert client.delete(f'/api/courses/{c}/download').json()['failed']==0
    assert client.get('/api/downloads').json()=={'jobs':{},'count':0,'bytes':0}
    assert list(settings.MEDIA_DIR.iterdir())==[]
