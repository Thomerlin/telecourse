/* TeleCourse — interface local, sem rastreamento e sem bibliotecas externas. */
'use strict';
const $ = id => document.getElementById(id);
const esc = val => String(val ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {library:[], course:null, lesson:null, batch:null, preview:[], filtered:false,
  watched:0, lastTick:0, lastSave:0, saving:Promise.resolve(), dragging:null, ignoreMedia:false};

async function api(path,options={}) {
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  if (!response.ok) {
    let message=`Falha ${response.status}`;
    try { const payload=await response.json();message=typeof payload.detail==='string'?payload.detail:JSON.stringify(payload.detail||payload); } catch {}
    throw new Error(message);
  }
  return response.json();
}
function alertMessage(err) { $('alert').textContent = err instanceof Error ? err.message : String(err);$('alert').classList.remove('hidden');window.scrollTo({top:0,behavior:'smooth'}); }
function clearAlert() {$('alert').classList.add('hidden');}
function percent(done,total){return total?Math.round(done*100/total):0;}
function fmt(seconds) {const s=Math.floor(Number(seconds)||0);return `${Math.floor(s/3600)?String(Math.floor(s/3600))+':':''}${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;}
function allLessons() {return state.course?.modules.flatMap(m=>m.lessons)||[];}
function view(page){const home=page==='home';$('home-view').classList.toggle('hidden',!home);$('course-view').classList.toggle('hidden',home);$('main-heading').textContent=home?'O que vamos aprender hoje?':'Hora de estudar';$('nav-library').classList.toggle('active',home&&!state.filtered);$('nav-continue').classList.toggle('active',home&&state.filtered);}
function card(course,compact=false) {
  const p=percent(course.completed,course.total), art=['◈','⌘','✦','◎','♧'][course.id%5];
  return `<button type="button" class="course-card" data-course="${course.id}" aria-label="Abrir ${esc(course.title)}"><div class="cover"><span class="cover-tag">${compact?'EM ANDAMENTO':'MEU CURSO'}</span><span class="cover-art">${art}</span></div><div class="card-body"><h3>${esc(course.title)}</h3><div class="card-meta">${course.total} materiais · ${course.completed} concluídos</div><div class="card-progress"><span>Progresso</span><span>${p}%</span></div><div class="progress-track"><div class="progress-fill" style="width:${p}%"></div></div></div></button>`;
}
function renderLibrary(){
  const query=$('course-search').value.toLocaleLowerCase('pt-BR').trim();
  const matches=state.library.filter(c=>c.title.toLocaleLowerCase('pt-BR').includes(query));
  const resumable=state.library.filter(c=>c.resume_lesson_id || (c.started>0&&c.completed<c.total));
  $('course-count').textContent=`${state.library.length} curso(s)`;
  $('resume-count').textContent=`${resumable.length} em andamento`;
  $('resume-grid').innerHTML=resumable.length?resumable.map(c=>card(c,true)).join(''):'<div class="empty">Quando começar um vídeo, o curso aparecerá aqui.</div>';
  $('courses-grid').innerHTML=matches.length?matches.map(c=>card(c)).join(''):'<div class="empty">Nenhum curso encontrado. Importe um canal ou grupo para começar.</div>';
  $('courses-grid').classList.toggle('hidden',state.filtered);
  $('library-heading').classList.toggle('hidden',state.filtered);
  $('course-search').parentElement.classList.toggle('hidden',state.filtered);
  $('resume-grid').parentElement.querySelector('.section-heading')?.classList.remove('hidden');
}
async function refreshLibrary(){state.library=await api('/api/library');renderLibrary();}
function renderCourse(){
  const data=state.course;if(!data)return;
  $('course-title').textContent=data.course.title;
  $('course-description').textContent=`${data.modules.length} módulos · ${data.total} materiais`+(data.course.description?` · ${data.course.description}`:'');
  $('course-progress-pct').textContent=`${percent(data.completed,data.total)}%`;
  $('course-progress-fill').style.width=`${percent(data.completed,data.total)}%`;
  $('playlist-count').textContent=`${data.completed}/${data.total}`;
  const html=data.modules.map(m=>{
    const lessons=m.lessons.map(l=>`<div class="lesson-row ${state.lesson?.id===l.id?'selected':''}" data-lesson-row="${l.id}" draggable="true"><span class="lesson-status ${l.completed?'done':''}">${l.completed?'✓':l.kind==='pdf'?'▤':'▷'}</span><button class="lesson-main" data-play="${l.id}"><span class="lesson-name">${esc(l.title)}</span><span class="lesson-small">${l.kind==='pdf'?'PDF':'Vídeo'}${l.duration?' · '+fmt(l.duration):''}${l.position_seconds&&!l.completed?' · '+fmt(l.position_seconds)+' assistidos':''}</span></button><div class="lesson-tools"><button data-up="${l.id}" title="Mover para cima">↑</button><button data-down="${l.id}" title="Mover para baixo">↓</button><button data-edit="${l.id}" title="Editar aula">✎</button></div></div>`).join('');
    return `<section class="module-block" data-module="${m.id}"><div class="module-top"><strong>${esc(m.title)} <small>(${m.lessons.filter(l=>l.completed).length}/${m.lessons.length})</small></strong><button data-rename-module="${m.id}" title="Renomear módulo">✎ Renomear</button></div><div class="module-body">${lessons}</div></section>`;
  }).join('');
  $('playlist').innerHTML=html||'<div class="empty">Curso sem aulas. Use “Importar mais aulas”.</div>';
}
async function loadCourse(id,autoplay=true){
  await stopPlayer();state.course=await api(`/api/courses/${id}`);state.lesson=null;renderCourse();view('course');
  $('media-container').innerHTML='<div class="player-empty"><span>▶</span><p>Selecione uma aula na lista</p></div>';
  $('now-playing-title').textContent='Selecione uma aula';
  $('now-playing-type').textContent='CONTEÚDO DO CURSO';
  window.scrollTo(0,0);
  if(!autoplay)return;
  const entry=state.library.find(c=>c.id===id);
  const lessons=allLessons();
  const next=lessons.find(l=>l.id===entry?.resume_lesson_id) || lessons.find(l=>!l.completed) || lessons[0];
  if(next)await playLesson(next.id);
}
async function reloadCourse(){if(!state.course)return;const courseId=state.course.course.id;const lessonId=state.lesson?.id;
  state.course=await api(`/api/courses/${courseId}`);state.lesson=allLessons().find(l=>l.id===lessonId)||null;renderCourse();}
function currentVideo(){return $('media-container').querySelector('video');}
function heartbeat(force=false,finished=false){
  const video=currentVideo(),lesson=state.lesson;
  if(!video||!lesson||state.ignoreMedia)return Promise.resolve();
  const now=performance.now();
  if(!force&&now-state.lastSave<8000)return Promise.resolve();
  const accumulated=Math.min(30,Math.max(0,state.watched));state.watched=0;state.lastSave=now;
  const id=lesson.id,pos=Number(video.currentTime||0);
  state.saving=state.saving.catch(()=>{}).then(async()=>{
    const result=await api(`/api/lessons/${id}/progress`,{method:'PUT',body:JSON.stringify({position_seconds:pos,played_delta_seconds:accumulated,completed:finished?true:null})});
    if(state.lesson?.id===id){state.lesson.position_seconds=result.position_seconds;state.lesson.played_seconds=result.played_seconds;state.lesson.completed=Number(result.completed);}
    if(result.completed)await reloadCourse();
  }).catch(alertMessage);
  return state.saving;
}
async function stopPlayer(){
  const video=currentVideo();if(video){video.pause();await heartbeat(true);}
  state.ignoreMedia=true;$('media-container').replaceChildren();state.ignoreMedia=false;state.watched=0;state.lastTick=0;
}
async function playLesson(id){
  const selected=allLessons().find(l=>l.id===Number(id));if(!selected)return;
  await stopPlayer();state.lesson=selected;state.watched=0;state.lastTick=0;state.lastSave=0;
  $('now-playing-title').textContent=selected.title;
  $('now-playing-type').textContent=selected.kind==='pdf'?'MATERIAL COMPLEMENTAR':'ASSISTINDO AGORA';
  $('mark-done').textContent=selected.completed?'↶ Desmarcar conclusão':'✓ Marcar concluída';
  const box=$('media-container'),url=`/api/lessons/${selected.id}/stream`;
  if(selected.kind==='pdf'){
    const frame=document.createElement('iframe');frame.src=url;frame.title=selected.title;box.append(frame);
  }else{
    const v=document.createElement('video');v.controls=true;v.preload='metadata';v.playsInline=true;v.src=url;
    v.addEventListener('loadedmetadata',()=>{if(selected.position_seconds>0&&Number.isFinite(v.duration)&&selected.position_seconds<v.duration-3){v.currentTime=selected.position_seconds;}});
    v.addEventListener('timeupdate',()=>{
      const t=Number(v.currentTime||0);if(state.lastTick>0&&!v.paused&&!v.seeking){const delta=t-state.lastTick;
        // Acelerar o vídeo conta como tempo efetivamente assistido, saltar não.
        if(delta>0&&delta<3)state.watched+=Math.min(delta/Math.max(.25,v.playbackRate||1),3);
      }
      state.lastTick=t;heartbeat();
    });
    v.addEventListener('seeking',()=>{state.lastTick=0;});
    v.addEventListener('pause',()=>{heartbeat(true);});
    v.addEventListener('ended',async()=>{await heartbeat(true);if(!state.lesson)return;const next=allLessons().findIndex(l=>l.id===selected.id);if(next>=0&&allLessons()[next+1])playLesson(allLessons()[next+1].id).catch(alertMessage);});
    v.addEventListener('error',()=>{if(v.error)alertMessage('Não foi possível reproduzir a mídia. Verifique a conexão com o Telegram e o formato (MP4/H.264/AAC é o mais compatível).');});
    box.append(v);
  }
  renderCourse();
}
async function updateCompletion(){if(!state.lesson)return;const id=state.lesson.id,done=!state.lesson.completed;
  await heartbeat(true);
  await api(`/api/lessons/${id}/progress`,{method:'PUT',body:JSON.stringify({position_seconds:state.lesson.position_seconds||0,played_delta_seconds:0,completed:done})});
  await reloadCourse();$('mark-done').textContent=done?'↶ Desmarcar conclusão':'✓ Marcar concluída';
}
async function nextLesson(){const list=allLessons(),index=list.findIndex(l=>l.id===state.lesson?.id);if(index>=0&&list[index+1])await playLesson(list[index+1].id);}
async function persistOrder(){
  const modules=[...$('playlist').querySelectorAll('.module-block')].map(element=>({module_id:Number(element.dataset.module),lesson_ids:[...element.querySelectorAll('[data-lesson-row]')].map(e=>Number(e.dataset.lessonRow))}));
  await api(`/api/courses/${state.course.course.id}/order`,{method:'PUT',body:JSON.stringify({modules})});await reloadCourse();
}
async function moveLesson(id,delta){
  const rows=[...$('playlist').querySelectorAll('[data-lesson-row]')],idx=rows.findIndex(e=>Number(e.dataset.lessonRow)===id),target=rows[idx+delta];
  if(idx<0||!target)return;
  if(delta<0)target.before(rows[idx]);else target.after(rows[idx]);
  await persistOrder();
}
async function editLesson(id){
  const lesson=allLessons().find(l=>l.id===id);if(!lesson)return;
  const title=prompt('Nome da aula',lesson.title);if(title===null)return;
  const module=state.course.modules.find(m=>m.id===lesson.module_id);
  const name=prompt('Mover para qual módulo? (nome exato de um módulo existente)',module?.title||'');if(name===null)return;
  const target=state.course.modules.find(m=>m.title.trim()===name.trim());
  if(!target)throw new Error('Módulo não encontrado. Crie-o com “Novo módulo” antes de mover a aula.');
  if(!title.trim())throw new Error('Informe um nome para a aula.');
  await api(`/api/lessons/${id}`,{method:'PATCH',body:JSON.stringify({title:title.trim(),module_id:target.id})});await reloadCourse();
}
async function showImporter(){
  clearAlert();state.batch=null;state.preview=[];setWizardStep(1);$('import-dialog').showModal();
  $('chat-select').innerHTML='<option value="">Buscando fontes…</option>';
  try {const chats=await api('/api/chats');$('chat-select').innerHTML='<option value="">Selecione um canal/grupo</option>'+chats.map(c=>`<option value="${c.chat_id}" ${c.protected?'disabled':''}>${esc(c.title)} · ${esc(c.kind)}${c.protected?' (protegido)':''}</option>`).join('');}
  catch(e){$('chat-select').innerHTML='<option value="">Telegram desconectado</option>';alertMessage(e);}
}
function setWizardStep(step){$('wizard-source').classList.toggle('hidden',step!==1);$('wizard-review').classList.toggle('hidden',step!==2);$('wizard-title').textContent=step===1?'Escolher origem':'Revisar e organizar';$('step-one').classList.toggle('active',step===1);$('step-two').classList.toggle('active',step===2);}
async function scan(event){event.preventDefault();const chat_id=Number($('chat-select').value);if(!chat_id)throw new Error('Selecione um canal ou grupo.');
  const payload={chat_id,limit:Number($('scan-limit').value)};if($('msg-from').value)payload.from_id=Number($('msg-from').value);if($('msg-to').value)payload.to_id=Number($('msg-to').value);
  const btn=$('scan-button');btn.disabled=true;btn.textContent='Analisando mensagens…';
  try{const result=await api('/api/imports/preview',{method:'POST',body:JSON.stringify(payload)});
    state.batch=result;state.preview=result.items.map(item=>({...item,selected:true,module:item.proposed_module}));
    $('import-stats').innerHTML=`<span>${result.batch.scanned} mensagens analisadas</span><span>${result.items.filter(i=>i.kind==='video').length} vídeos</span><span>${result.items.filter(i=>i.kind==='pdf').length} PDFs</span><span>${result.items.filter(i=>i.uncertain).length} para conferir</span>`;
    $('course-target').innerHTML='<option value="new">✦ Novo curso</option>'+state.library.map(c=>`<option value="${c.id}">${esc(c.title)}</option>`).join('');
    if(state.course)$('course-target').value=String(state.course.course.id);
    const source=$('chat-select').selectedOptions[0]?.textContent||'Meu curso';$('new-course-title').value=source.replace(/ · .+$/,'').slice(0,150);
    toggleCourseTarget();renderPreview();setWizardStep(2);
    if(!result.items.length)alertMessage('Nenhum vídeo ou PDF encontrado nesse intervalo. Amplie o limite e tente novamente.');
  }finally{btn.disabled=false;btn.textContent='Analisar mensagens →';}
}
function toggleCourseTarget(){$('new-course-name').classList.toggle('hidden',$('course-target').value!=='new');}
function renderPreview(){
  const selected=state.preview.filter(i=>i.selected).length;$('select-all').checked=selected===state.preview.length&&selected>0;
  $('preview-items').innerHTML=state.preview.map(i=>`<div class="preview-row ${i.selected?'chosen':''}" draggable="true" data-preview="${i.message_id}"><label class="checkline"><input type="checkbox" data-select="${i.message_id}" ${i.selected?'checked':''} aria-label="Incluir mensagem ${i.message_id}"></label><div class="preview-name"><input data-title="${i.message_id}" maxlength="200" value="${esc(i.title)}" aria-label="Nome da aula"></div><div class="preview-mod"><input data-module-title="${i.message_id}" maxlength="120" value="${esc(i.module)}" aria-label="Nome do módulo"></div><div class="preview-meta"><span class="drag-handle">⠿</span> <span class="kind-chip">${i.kind.toUpperCase()}</span> #${i.message_id} ${i.uncertain?'<span class="uncertain">⚠ Confira</span>':''}</div></div>`).join('');
}
async function commitImport(){
  const items=state.preview.filter(i=>i.selected).map(i=>({message_id:i.message_id,title:i.title.trim(),module:i.module.trim()}));
  if(!items.length)throw new Error('Selecione pelo menos uma aula.');
  if(items.some(i=>!i.title||!i.module))throw new Error('Todas as aulas selecionadas precisam de um nome e um módulo.');
  const target=$('course-target').value,payload={items};if(target==='new')payload.title=$('new-course-title').value.trim();else payload.course_id=Number(target);
  const button=$('confirm-import');button.disabled=true;button.textContent='Salvando…';
  try{const result=await api(`/api/imports/${state.batch.batch.id}/commit`,{method:'POST',body:JSON.stringify(payload)});
    $('import-dialog').close();state.course=null;await refreshLibrary();await loadCourse(result.course_id,false);
    if(result.duplicates||result.conflicts)alertMessage(`Importação concluída: ${result.added} aulas adicionadas; ${result.duplicates} repetidas; ${result.conflicts} já atribuídas a outro curso.`);
  }finally{button.disabled=false;button.textContent='Publicar na biblioteca';}
}
function downloadJson(filename,value){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function action(handler){return async event=>{try{await handler(event);}catch(error){alertMessage(error);}};}

// Eventos
for(const target of ['courses-grid','resume-grid'])$(target).addEventListener('click',action(async e=>{const id=e.target.closest('[data-course]')?.dataset.course;if(id)await loadCourse(Number(id));}));
$('course-search').addEventListener('input',renderLibrary);
$('nav-library').addEventListener('click',action(async()=>{await stopPlayer();state.filtered=false;view('home');await refreshLibrary();}));
$('nav-continue').addEventListener('click',action(async()=>{await stopPlayer();state.filtered=true;view('home');await refreshLibrary();}));
$('back-to-library').addEventListener('click',action(async()=>{await stopPlayer();state.course=null;state.lesson=null;state.filtered=false;view('home');await refreshLibrary();}));
for(const id of ['import-open','hero-import','import-into-course'])$(id).addEventListener('click',action(showImporter));
$('close-modal').addEventListener('click',()=>$('import-dialog').close());
document.querySelectorAll('.cancel-import').forEach(el=>el.addEventListener('click',()=>$('import-dialog').close()));
$('scan-form').addEventListener('submit',action(scan));
$('back-to-source').addEventListener('click',()=>setWizardStep(1));
$('course-target').addEventListener('change',toggleCourseTarget);
$('select-all').addEventListener('change',e=>{state.preview.forEach(i=>i.selected=e.target.checked);renderPreview();});
$('preview-items').addEventListener('change',e=>{const id=Number(e.target.dataset.select);if(id){state.preview.find(i=>i.message_id===id).selected=e.target.checked;renderPreview();}});
$('preview-items').addEventListener('input',e=>{const id=Number(e.target.dataset.title||e.target.dataset.moduleTitle);if(!id)return;const item=state.preview.find(i=>i.message_id===id);if(item){if(e.target.dataset.title)item.title=e.target.value;else item.module=e.target.value;}});
$('preview-items').addEventListener('dragstart',e=>{const row=e.target.closest('[data-preview]');if(!row)return;state.dragging=Number(row.dataset.preview);row.classList.add('dragging');e.dataTransfer.effectAllowed='move';});
$('preview-items').addEventListener('dragover',e=>{const target=e.target.closest('[data-preview]');if(!target)return;e.preventDefault();target.classList.add('drag-target');});
$('preview-items').addEventListener('dragleave',e=>{e.target.closest('[data-preview]')?.classList.remove('drag-target');});
$('preview-items').addEventListener('drop',e=>{const target=e.target.closest('[data-preview]');if(!target||!state.dragging)return;e.preventDefault();const from=state.preview.findIndex(i=>i.message_id===state.dragging),to=state.preview.findIndex(i=>i.message_id===Number(target.dataset.preview));if(from>=0&&to>=0){const item=state.preview.splice(from,1)[0];state.preview.splice(to,0,item);}state.dragging=null;renderPreview();});
$('preview-items').addEventListener('dragend',()=>{state.dragging=null;renderPreview();});
$('confirm-import').addEventListener('click',action(commitImport));
$('playlist').addEventListener('click',action(async e=>{
  const play=e.target.closest('[data-play]');if(play)return playLesson(Number(play.dataset.play));
  const up=e.target.closest('[data-up]');if(up)return moveLesson(Number(up.dataset.up),-1);
  const down=e.target.closest('[data-down]');if(down)return moveLesson(Number(down.dataset.down),1);
  const edit=e.target.closest('[data-edit]');if(edit)return editLesson(Number(edit.dataset.edit));
  const rename=e.target.closest('[data-rename-module]');if(rename){const id=Number(rename.dataset.renameModule),old=state.course.modules.find(m=>m.id===id),title=prompt('Novo nome do módulo',old.title);if(title?.trim()){await api(`/api/modules/${id}`,{method:'PATCH',body:JSON.stringify({title:title.trim()})});await reloadCourse();}}
}));
$('playlist').addEventListener('dragstart',e=>{const row=e.target.closest('[data-lesson-row]');if(!row)return;state.dragging=Number(row.dataset.lessonRow);row.classList.add('dragging');e.dataTransfer.effectAllowed='move';});
$('playlist').addEventListener('dragover',e=>{const target=e.target.closest('[data-lesson-row],.module-body');if(!target||!state.dragging)return;e.preventDefault();target.classList.add('drag-insert');});
$('playlist').addEventListener('dragleave',e=>e.target.closest('[data-lesson-row],.module-body')?.classList.remove('drag-insert'));
$('playlist').addEventListener('drop',action(async e=>{const target=e.target.closest('[data-lesson-row],.module-body');if(!target||!state.dragging)return;e.preventDefault();const moving=$(`[data-lesson-row="${state.dragging}"]`);if(!moving)return;if(target.classList.contains('module-body'))target.append(moving);else if(target!==moving)target.before(moving);state.dragging=null;await persistOrder();}));
$('playlist').addEventListener('dragend',()=>{state.dragging=null;document.querySelectorAll('.dragging,.drag-insert').forEach(e=>e.classList.remove('dragging','drag-insert'));});
$('mark-done').addEventListener('click',action(updateCompletion));
$('next-lesson').addEventListener('click',action(nextLesson));
$('edit-course').addEventListener('click',action(async()=>{if(!state.course)return;const title=prompt('Nome do curso',state.course.course.title);if(title===null)return;const description=prompt('Descrição do curso',state.course.course.description||'');if(description===null)return;await api(`/api/courses/${state.course.course.id}`,{method:'PATCH',body:JSON.stringify({title,description})});await reloadCourse();await refreshLibrary();}));
$('add-module').addEventListener('click',action(async()=>{if(!state.course)return;const name=prompt('Nome do módulo');if(!name?.trim())return;await api(`/api/courses/${state.course.course.id}/modules`,{method:'POST',body:JSON.stringify({title:name.trim()})});await reloadCourse();}));
$('delete-course').addEventListener('click',action(async()=>{if(!state.course||!confirm(`Excluir "${state.course.course.title}" da biblioteca local? Aulas e progresso desse curso serão removidos do SQLite. NADA será excluído do Telegram.`))return;await stopPlayer();await api(`/api/courses/${state.course.course.id}`,{method:'DELETE'});state.course=null;state.lesson=null;state.filtered=false;view('home');await refreshLibrary();}));
$('make-backup').addEventListener('click',action(async()=>{const data=await api('/api/backup',{method:'POST'});alertMessage(`Backup local criado em ${data.location}${data.filename}`);}));
$('export-progress').addEventListener('click',action(async()=>downloadJson('telecourse-progress.json',await api('/api/export/progress'))));
window.addEventListener('pagehide',()=>{const v=currentVideo();if(v&&state.lesson){const body=JSON.stringify({position_seconds:v.currentTime||0,played_delta_seconds:Math.min(30,state.watched),completed:null});fetch(`/api/lessons/${state.lesson.id}/progress`,{method:'PUT',headers:{'Content-Type':'application/json'},body,keepalive:true}).catch(()=>{});}});
(async()=>{try{const status=await api('/api/status');$('connection-name').textContent=status.ready?`Conectado: ${status.name}`:status.message;$('connection-dot').style.background=status.ready?'#50ca96':'#f6ba62';await refreshLibrary();}catch(e){alertMessage(e);}})();
