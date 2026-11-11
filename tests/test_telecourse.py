"""Testes locais sem credenciais nem acesso à rede Telegram."""
from types import SimpleNamespace
import sqlite3
import pytest
from fastapi.testclient import TestClient

from telecourse import settings
from telecourse.database import initialize, connect, backup_database
from telecourse.organizer import media_info, propose, organize
from telecourse.server import app, range_of


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(settings, 'DB_PATH', tmp_path / 'telecourse.db')
    monkeypatch.setattr(settings, 'BACKUP_DIR', tmp_path / 'backups')
    monkeypatch.setattr(settings, 'SESSION_PATH', tmp_path / 'telegram')
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
