/* TeleCourse — interface local, sem rastreamento e sem bibliotecas externas. */
'use strict';
const $ = id => document.getElementById(id);
const esc = val => String(val ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {library:[], course:null, lesson:null, batch:null, preview:[], filter:null,
  watched:0, lastTick:0, lastSave:0, saving:Promise.resolve(), dragging:null, ignoreMedia:false,
  jobs:{}, seenErrors:new Set(), pollTimer:0, alertTimer:0};

async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json', ...(options.headers||{})}});
  if (!response.ok) {
    let message = `Falha ${response.status}`;
    try { const payload = await response.json(); message = typeof payload.detail==='string' ? payload.detail : JSON.stringify(payload.detail||payload); } catch {}
    throw new Error(message);
  }
  return response.json();
}
function alertMessage(err) {
  const box = $('alert');
  box.textContent = err instanceof Error ? err.message : String(err);
  box.classList.remove('hidden');
  clearTimeout(state.alertTimer);
  state.alertTimer = setTimeout(clearAlert, 9000);
}
function clearAlert() { $('alert').classList.add('hidden'); }
function action(handler) { return async event => { try { await handler(event); } catch (error) { alertMessage(error); } }; }

// Formatação
function percent(done, total) { return total ? Math.round(done*100/total) : 0; }
function fmt(seconds) { const s = Math.floor(Number(seconds)||0); return `${Math.floor(s/3600) ? Math.floor(s/3600)+':' : ''}${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`; }
function hours(seconds) { const m = Math.round((Number(seconds)||0)/60), h = Math.floor(m/60); return h ? `${h}h ${String(m%60).padStart(2,'0')}min` : `${m}min`; }
function size(bytes) { const mb = (Number(bytes)||0)/1048576; return mb >= 1024 ? `${(mb/1024).toFixed(1).replace('.',',')} GB` : `${Math.round(mb)} MB`; }
function hue(id) { return (Number(id)*67+200) % 360; }
function initial(title) { return (String(title).trim().match(/[\p{L}\p{N}]/u)||['▶'])[0].toUpperCase(); }
function allLessons() { return state.course?.modules.flatMap(m => m.lessons) || []; }

// Biblioteca
function view(page) {
  const home = page==='home';
  $('home-view').classList.toggle('hidden', !home);
  $('course-view').classList.toggle('hidden', home);
  $('nav-library').classList.toggle('active', home && !state.filter);
  $('nav-continue').classList.toggle('active', home && state.filter==='continue');
  $('nav-downloads').classList.toggle('active', home && state.filter==='downloads');
  history.replaceState(null, '', home ? '#' : `#/curso/${state.course.course.id}`);
  updateNav();
}
function updateNav() { $('nav').classList.toggle('solid', window.scrollY > 20 || !$('course-view').classList.contains('hidden') || !!state.filter); }
function card(course, mode) {
  const p = percent(course.completed, course.total);
  const detail = mode==='downloads'
    ? `<strong>⇩ ${course.downloaded} aula(s) baixada(s)</strong> · ${size(course.downloaded_bytes)}`
    : `${p}% concluído · ${hours(course.watched_seconds)} assistidas`;
  return `<button type="button" class="course-card" data-course="${course.id}" style="--hue:${hue(course.id)}" aria-label="Abrir ${esc(course.title)}">
    <div class="cover"><span class="cover-initial">${esc(initial(course.title))}</span><span class="cover-title">${esc(course.title)}</span>
      ${course.downloaded && mode!=='downloads' ? `<span class="badge">⇩ ${course.downloaded}</span>` : ''}
      ${p ? `<div class="progress-track"><div class="progress-fill" style="width:${p}%"></div></div>` : ''}</div>
    <div class="card-body"><div class="card-meta">${course.total} aulas · ${hours(course.duration_seconds)}</div><div class="card-meta">${detail}</div></div></button>`;
}
function renderBillboard(course) {
  const box = $('billboard');
  if (!course) {
    box.style.setProperty('--hue', 255);
    box.innerHTML = `<span class="billboard-art">▶</span><div class="billboard-copy"><span class="eyebrow">SUA BIBLIOTECA PESSOAL</span><h1>Seus cursos.<br>Na ordem certa.</h1><p>Transforme canais e grupos do Telegram em trilhas de estudo. Retome de onde parou e baixe aulas para assistir sem internet.</p><div class="billboard-actions"><button class="primary big" data-import>＋ Adicionar meu primeiro curso</button></div></div>`;
    return;
  }
  const p = percent(course.completed, course.total), started = course.started>0;
  box.style.setProperty('--hue', hue(course.id));
  box.innerHTML = `<span class="billboard-art">${esc(initial(course.title))}</span><div class="billboard-copy"><span class="eyebrow">${started ? 'CONTINUE DE ONDE PAROU' : 'COMECE A ESTUDAR'}</span><h1>${esc(course.title)}</h1><p>${course.total} aulas · ${hours(course.duration_seconds)} · ${p}% concluído</p><div class="progress-track"><div class="progress-fill" style="width:${p}%"></div></div><div class="billboard-actions"><button class="primary big" data-course="${course.id}">▶ ${started ? 'Continuar' : 'Assistir'}</button><button class="secondary big" data-import>＋ Importar aulas</button></div></div>`;
}
function renderLibrary() {
  const query = $('course-search').value.toLocaleLowerCase('pt-BR').trim();
  const matches = state.library.filter(c => c.title.toLocaleLowerCase('pt-BR').includes(query));
  const resumable = state.library.filter(c => c.resume_lesson_id || (c.started>0 && c.completed<c.total));
  const offline = state.library.filter(c => c.downloaded>0);
  const filter = state.filter;
  renderBillboard(resumable[0] || state.library[0]);
  $('billboard').classList.toggle('hidden', !!filter || !!query);
  $('home-view').style.paddingTop = filter || query ? '84px' : '';
  $('resume-row').classList.toggle('hidden', !!query || (filter ? filter!=='continue' : !resumable.length));
  $('downloads-row').classList.toggle('hidden', !!query || (filter ? filter!=='downloads' : !offline.length));
  $('library-row').classList.toggle('hidden', !!filter);
  $('resume-count').textContent = `${resumable.length} em andamento`;
  $('downloads-count').textContent = `${offline.reduce((sum,c) => sum+c.downloaded, 0)} aula(s) · ${size(offline.reduce((sum,c) => sum+c.downloaded_bytes, 0))} em disco`;
  $('course-count').textContent = `${state.library.length} curso(s) · ${hours(state.library.reduce((sum,c) => sum+c.duration_seconds, 0))} de vídeo`;
  $('resume-grid').innerHTML = resumable.length ? resumable.map(c => card(c)).join('') : '<div class="empty">Quando começar um vídeo, o curso aparece aqui.</div>';
  $('downloads-grid').innerHTML = offline.length ? offline.map(c => card(c,'downloads')).join('') : '<div class="empty">Nenhuma aula baixada. Abra um curso e use ⇩ para assistir sem internet.</div>';
  $('courses-grid').innerHTML = matches.length ? matches.map(c => card(c)).join('') : '<div class="empty">Nenhum curso encontrado. Importe um canal ou grupo para começar.</div>';
  updateNav();
}
async function refreshLibrary() { state.library = await api('/api/library'); renderLibrary(); }

// Curso
function downloadControl(lesson) {
  const job = state.jobs[lesson.id];
  if (lesson.downloaded) return {cls:'saved', label:'✓', attr:'data-remove-download', title:'Baixada — clique para remover do computador'};
  if (job?.state==='error') return {cls:'failed', label:'⚠', attr:'data-download', title:`${job.error} — clique para tentar de novo`};
  if (job) return {cls:'busy', label:job.state==='queued' ? '···' : `${percent(job.done, job.total)}%`, attr:'data-remove-download', title:'Baixando — clique para cancelar'};
  return {cls:'', label:'⇩', attr:'data-download', title:'Baixar para assistir sem internet'};
}
function renderDownloadSummary() {
  const data = state.course; if (!data) return;
  const waiting = allLessons().filter(l => state.jobs[l.id] && state.jobs[l.id].state!=='error').length;
  const parts = [];
  if (data.downloaded_count) parts.push(`⇩ ${data.downloaded_count} de ${data.total} aulas baixadas · ${size(data.downloaded_bytes)}`);
  if (waiting) parts.push(`${waiting} na fila de download`);
  $('download-summary').textContent = parts.join(' · ');
  $('remove-downloads').classList.toggle('hidden', !data.downloaded_count && !waiting);
}
function renderCourse() {
  const data = state.course; if (!data) return;
  const pct = percent(data.completed, data.total);
  $('course-title').textContent = data.course.title;
  $('course-description').textContent = `${data.modules.length} módulo(s) · ${data.total} aulas · ${hours(data.watched_seconds)} de ${hours(data.duration_seconds)} assistidas` + (data.course.description ? ` · ${data.course.description}` : '');
  $('course-progress-pct').textContent = `${pct}%`;
  $('course-progress-fill').style.width = `${pct}%`;
  $('playlist-count').textContent = `${data.completed}/${data.total} concluídas`;
  let number = 0;
  const html = data.modules.map(m => {
    const lessons = m.lessons.map(l => {
      number += 1;
      const dl = downloadControl(l);
      const details = [l.kind==='pdf' ? 'PDF' : 'Vídeo'];
      if (l.duration) details.push(fmt(l.duration));
      if (l.position_seconds && !l.completed) details.push(`${fmt(l.position_seconds)} assistidos`);
      if (l.downloaded) details.push(`<span class="offline">offline · ${size(l.local_bytes)}</span>`);
      return `<div class="lesson-row ${state.lesson?.id===l.id ? 'selected' : ''}" data-lesson-row="${l.id}" draggable="true">
        <span class="lesson-status ${l.completed ? 'done' : ''}">${l.completed ? '✓' : number}</span>
        <button class="lesson-main" data-play="${l.id}"><span class="lesson-name">${esc(l.title)}</span><span class="lesson-small">${details.join(' · ')}</span></button>
        <div class="lesson-tools"><button class="reorder" data-up="${l.id}" title="Mover para cima">↑</button><button class="reorder" data-down="${l.id}" title="Mover para baixo">↓</button><button class="reorder" data-edit="${l.id}" title="Editar aula">✎</button><button class="dl ${dl.cls}" ${dl.attr}="${l.id}" data-dl="${l.id}" title="${esc(dl.title)}">${dl.label}</button></div></div>`;
    }).join('');
    return `<section class="module-block" data-module="${m.id}"><div class="module-top"><strong>${esc(m.title)} <small>${m.lessons.filter(l => l.completed).length}/${m.lessons.length}${m.duration_seconds ? ' · '+hours(m.duration_seconds) : ''}</small></strong><div class="module-tools"><button data-download-module="${m.id}" title="Baixar todas as aulas deste módulo">⇩</button><button data-rename-module="${m.id}" title="Renomear módulo">✎</button></div></div><div class="module-body">${lessons}</div></section>`;
  }).join('');
  $('playlist').innerHTML = html || '<div class="empty">Curso sem aulas. Use “Importar mais aulas”.</div>';
  renderDownloadSummary();
}
async function loadCourse(id, autoplay=true) {
  await stopPlayer();
  state.course = await api(`/api/courses/${id}`); state.lesson = null;
  renderCourse(); view('course');
  $('media-container').innerHTML = '<div class="player-empty"><span>▶</span><p>Selecione uma aula na lista</p></div>';
  $('now-playing-title').textContent = 'Selecione uma aula';
  $('now-playing-type').textContent = 'CONTEÚDO DO CURSO';
  window.scrollTo(0, 0);
  if (!autoplay) return;
  const entry = state.library.find(c => c.id===id);
  const lessons = allLessons();
  const next = lessons.find(l => l.id===entry?.resume_lesson_id) || lessons.find(l => !l.completed) || lessons[0];
  if (next) await playLesson(next.id);
}
async function reloadCourse() {
  if (!state.course) return;
  const courseId = state.course.course.id, lessonId = state.lesson?.id;
  state.course = await api(`/api/courses/${courseId}`);
  state.lesson = allLessons().find(l => l.id===lessonId) || null;
  renderCourse();
}

// Player e progresso
function currentVideo() { return $('media-container').querySelector('video'); }
function heartbeat(force=false) {
  const video = currentVideo(), lesson = state.lesson;
  if (!video || !lesson || state.ignoreMedia) return Promise.resolve();
  const now = performance.now();
  if (!force && now-state.lastSave < 8000) return Promise.resolve();
  const accumulated = Math.min(30, Math.max(0, state.watched)); state.watched = 0; state.lastSave = now;
  const id = lesson.id, pos = Number(video.currentTime||0);
  state.saving = state.saving.catch(() => {}).then(async () => {
    const result = await api(`/api/lessons/${id}/progress`, {method:'PUT', body:JSON.stringify({position_seconds:pos, played_delta_seconds:accumulated, completed:null})});
    const wasDone = state.lesson?.id===id && state.lesson.completed;
    if (state.lesson?.id===id) { state.lesson.position_seconds = result.position_seconds; state.lesson.played_seconds = result.played_seconds; state.lesson.completed = Number(result.completed); }
    if (result.completed && !wasDone) await reloadCourse();
  }).catch(alertMessage);
  return state.saving;
}
async function stopPlayer() {
  const video = currentVideo(); if (video) { video.pause(); await heartbeat(true); }
  state.ignoreMedia = true; $('media-container').replaceChildren(); state.ignoreMedia = false; state.watched = 0; state.lastTick = 0;
}
async function playLesson(id) {
  const selected = allLessons().find(l => l.id===Number(id)); if (!selected) return;
  await stopPlayer(); state.lesson = selected; state.watched = 0; state.lastTick = 0; state.lastSave = 0;
  $('now-playing-title').textContent = selected.title;
  $('now-playing-type').textContent = (selected.kind==='pdf' ? 'MATERIAL COMPLEMENTAR' : 'ASSISTINDO AGORA') + (selected.downloaded ? ' · OFFLINE' : '');
  $('mark-done').textContent = selected.completed ? '↶ Desmarcar conclusão' : '✓ Marcar concluída';
  const box = $('media-container'), url = `/api/lessons/${selected.id}/stream`;
  if (selected.kind==='pdf') {
    const frame = document.createElement('iframe'); frame.src = url; frame.title = selected.title; box.append(frame);
  } else {
    const v = document.createElement('video'); v.controls = true; v.preload = 'metadata'; v.playsInline = true; v.src = url;
    v.addEventListener('loadedmetadata', () => { if (selected.position_seconds>0 && Number.isFinite(v.duration) && selected.position_seconds<v.duration-3) v.currentTime = selected.position_seconds; });
    v.addEventListener('timeupdate', () => {
      const t = Number(v.currentTime||0);
      if (state.lastTick>0 && !v.paused && !v.seeking) {
        const delta = t-state.lastTick;
        // Conta em tempo de mídia, para que o limite de 90% da duração valha em qualquer velocidade.
        if (delta>0 && delta<3*Math.max(1, v.playbackRate||1)) state.watched += delta;
      }
      state.lastTick = t; heartbeat();
    });
    v.addEventListener('seeking', () => { state.lastTick = 0; });
    v.addEventListener('pause', () => { heartbeat(true); });
    v.addEventListener('ended', async () => { await heartbeat(true); if (state.lesson?.id===selected.id) nextLesson().catch(alertMessage); });
    v.addEventListener('error', () => { if (v.error) alertMessage('Não foi possível reproduzir a mídia. Verifique a conexão com o Telegram e o formato (MP4/H.264/AAC é o mais compatível).'); });
    box.append(v);
  }
  renderCourse();
  $('playlist').querySelector('.lesson-row.selected')?.scrollIntoView({block:'nearest'});
}
async function updateCompletion() {
  if (!state.lesson) return;
  const id = state.lesson.id, done = !state.lesson.completed;
  await heartbeat(true);
  await api(`/api/lessons/${id}/progress`, {method:'PUT', body:JSON.stringify({position_seconds:state.lesson.position_seconds||0, played_delta_seconds:0, completed:done})});
  await reloadCourse(); $('mark-done').textContent = done ? '↶ Desmarcar conclusão' : '✓ Marcar concluída';
}
async function nextLesson() { const list = allLessons(), index = list.findIndex(l => l.id===state.lesson?.id); if (index>=0 && list[index+1]) await playLesson(list[index+1].id); }

// Organização
async function persistOrder() {
  const modules = [...$('playlist').querySelectorAll('.module-block')].map(element => ({module_id:Number(element.dataset.module), lesson_ids:[...element.querySelectorAll('[data-lesson-row]')].map(e => Number(e.dataset.lessonRow))}));
  await api(`/api/courses/${state.course.course.id}/order`, {method:'PUT', body:JSON.stringify({modules})}); await reloadCourse();
}
async function moveLesson(id, delta) {
  const rows = [...$('playlist').querySelectorAll('[data-lesson-row]')], idx = rows.findIndex(e => Number(e.dataset.lessonRow)===id), target = rows[idx+delta];
  if (idx<0 || !target) return;
  if (delta<0) target.before(rows[idx]); else target.after(rows[idx]);
  await persistOrder();
}
async function editLesson(id) {
  const lesson = allLessons().find(l => l.id===id); if (!lesson) return;
  const title = prompt('Nome da aula', lesson.title); if (title===null) return;
  const module = state.course.modules.find(m => m.id===lesson.module_id);
  const name = prompt('Mover para qual módulo? (nome exato de um módulo existente)', module?.title||''); if (name===null) return;
  const target = state.course.modules.find(m => m.title.trim()===name.trim());
  if (!target) throw new Error('Módulo não encontrado. Crie-o com “Novo módulo” antes de mover a aula.');
  if (!title.trim()) throw new Error('Informe um nome para a aula.');
  const payload = {title:title.trim()}; if (target.id!==lesson.module_id) payload.module_id = target.id;
  await api(`/api/lessons/${id}`, {method:'PATCH', body:JSON.stringify(payload)}); await reloadCourse();
}

// Downloads para assistir offline
async function pollDownloads() {
  clearTimeout(state.pollTimer);
  const activeKeys = jobs => Object.keys(jobs).filter(k => jobs[k].state!=='error').sort().join();
  const before = activeKeys(state.jobs);
  const data = await api('/api/downloads');
  state.jobs = data.jobs;
  for (const [id, job] of Object.entries(data.jobs)) {
    if (job.state!=='error') { state.seenErrors.delete(id); continue; }
    if (!state.seenErrors.has(id)) { state.seenErrors.add(id); alertMessage(`Download não concluído: ${job.error}`); }
  }
  if (before !== activeKeys(data.jobs)) {
    if (state.course) await reloadCourse(); else await refreshLibrary();
  } else if (state.course) {
    for (const lesson of allLessons()) {
      if (!state.jobs[lesson.id]) continue;
      const button = $('playlist').querySelector(`[data-dl="${lesson.id}"]`), control = downloadControl(lesson);
      if (button) { button.textContent = control.label; button.className = `dl ${control.cls}`; button.title = control.title; }
    }
    renderDownloadSummary();
  }
  if (activeKeys(data.jobs)) state.pollTimer = setTimeout(() => pollDownloads().catch(alertMessage), 1500);
}
async function startDownload(id) { await api(`/api/lessons/${id}/download`, {method:'POST'}); await pollDownloads(); }
async function removeDownload(id) {
  const lesson = allLessons().find(l => l.id===id); if (!lesson) return;
  const playing = state.lesson?.id===id && lesson.downloaded;
  if (lesson.downloaded && !confirm(`Remover "${lesson.title}" do computador?\nA aula continua na biblioteca e pode ser assistida por streaming.`)) return;
  if (playing) await stopPlayer();  // libera o arquivo antes de apagar
  await api(`/api/lessons/${id}/download`, {method:'DELETE'});
  state.jobs = {}; await pollDownloads(); await reloadCourse();
  if (playing) await playLesson(id);
}
async function downloadMany(moduleId) {
  const lessons = allLessons().filter(l => !l.downloaded && (!moduleId || l.module_id===moduleId));
  if (!lessons.length) throw new Error('Todas essas aulas já estão baixadas.');
  const total = lessons.reduce((sum,l) => sum+l.file_size, 0);
  if (!confirm(`Baixar ${lessons.length} aula(s) para assistir sem internet?\nEspaço necessário: ${size(total)}.`)) return;
  const query = moduleId ? `?module_id=${moduleId}` : '';
  await api(`/api/courses/${state.course.course.id}/download${query}`, {method:'POST'}); await pollDownloads();
}
async function removeAllDownloads() {
  const data = state.course;
  if (!confirm(`Remover do computador as aulas baixadas de "${data.course.title}" e cancelar downloads na fila?\nLibera ${size(data.downloaded_bytes)}. O curso e o progresso continuam na biblioteca.`)) return;
  const playing = state.lesson?.downloaded ? state.lesson.id : null;
  if (playing) await stopPlayer();
  const result = await api(`/api/courses/${data.course.id}/download`, {method:'DELETE'});
  state.jobs = {}; await pollDownloads(); await reloadCourse();
  if (result.failed) alertMessage(`${result.failed} arquivo(s) em uso não puderam ser removidos. Pare o vídeo e tente de novo.`);
  if (playing) await playLesson(playing);
}

// Importação
async function showImporter() {
  clearAlert(); state.batch = null; state.preview = []; setWizardStep(1); $('import-dialog').showModal();
  $('chat-select').innerHTML = '<option value="">Buscando fontes…</option>';
  try {
    const chats = await api('/api/chats');
    $('chat-select').innerHTML = '<option value="">Selecione um canal/grupo</option>' + chats.map(c => `<option value="${c.chat_id}" ${c.protected ? 'disabled' : ''}>${esc(c.title)} · ${esc(c.kind)}${c.protected ? ' (protegido)' : ''}</option>`).join('');
  } catch (e) { $('chat-select').innerHTML = '<option value="">Telegram desconectado</option>'; alertMessage(e); }
}
function setWizardStep(step) { $('wizard-source').classList.toggle('hidden', step!==1); $('wizard-review').classList.toggle('hidden', step!==2); $('wizard-title').textContent = step===1 ? 'Escolher origem' : 'Revisar e organizar'; $('step-one').classList.toggle('active', step===1); $('step-two').classList.toggle('active', step===2); }
async function scan(event) {
  event.preventDefault();
  const chat_id = Number($('chat-select').value); if (!chat_id) throw new Error('Selecione um canal ou grupo.');
  const payload = {chat_id, limit:Number($('scan-limit').value)};
  if ($('msg-from').value) payload.from_id = Number($('msg-from').value);
  if ($('msg-to').value) payload.to_id = Number($('msg-to').value);
  const btn = $('scan-button'); btn.disabled = true; btn.textContent = 'Analisando mensagens…';
  try {
    const result = await api('/api/imports/preview', {method:'POST', body:JSON.stringify(payload)});
    state.batch = result; state.preview = result.items.map(item => ({...item, selected:true, module:item.proposed_module}));
    $('import-stats').innerHTML = `<span>${result.batch.scanned} mensagens analisadas</span><span>${result.items.filter(i => i.kind==='video').length} vídeos</span><span>${result.items.filter(i => i.kind==='pdf').length} PDFs</span><span>${result.items.filter(i => i.uncertain).length} para conferir</span>`;
    $('course-target').innerHTML = '<option value="new">✦ Novo curso</option>' + state.library.map(c => `<option value="${c.id}">${esc(c.title)}</option>`).join('');
    if (state.course) $('course-target').value = String(state.course.course.id);
    const source = $('chat-select').selectedOptions[0]?.textContent || 'Meu curso'; $('new-course-title').value = source.replace(/ · .+$/, '').slice(0, 150);
    toggleCourseTarget(); renderPreview(); setWizardStep(2);
    if (!result.items.length) alertMessage('Nenhum vídeo ou PDF encontrado nesse intervalo. Amplie o limite e tente novamente.');
  } finally { btn.disabled = false; btn.textContent = 'Analisar mensagens →'; }
}
function toggleCourseTarget() { $('new-course-name').classList.toggle('hidden', $('course-target').value!=='new'); }
function renderPreview() {
  const selected = state.preview.filter(i => i.selected).length; $('select-all').checked = selected===state.preview.length && selected>0;
  $('preview-items').innerHTML = state.preview.map(i => `<div class="preview-row ${i.selected ? 'chosen' : ''}" draggable="true" data-preview="${i.message_id}"><label class="checkline"><input type="checkbox" data-select="${i.message_id}" ${i.selected ? 'checked' : ''} aria-label="Incluir mensagem ${i.message_id}"></label><div class="preview-name"><input data-title="${i.message_id}" maxlength="200" value="${esc(i.title)}" aria-label="Nome da aula"></div><div class="preview-mod"><input data-module-title="${i.message_id}" maxlength="120" value="${esc(i.module)}" aria-label="Nome do módulo"></div><div class="preview-meta"><span class="drag-handle">⠿</span> <span class="kind-chip">${i.kind.toUpperCase()}</span> #${i.message_id} ${i.uncertain ? '<span class="uncertain">⚠ Confira</span>' : ''}</div></div>`).join('');
}
async function commitImport() {
  const items = state.preview.filter(i => i.selected).map(i => ({message_id:i.message_id, title:i.title.trim(), module:i.module.trim()}));
  if (!items.length) throw new Error('Selecione pelo menos uma aula.');
  if (items.some(i => !i.title || !i.module)) throw new Error('Todas as aulas selecionadas precisam de um nome e um módulo.');
  const target = $('course-target').value, payload = {items};
  if (target==='new') payload.title = $('new-course-title').value.trim(); else payload.course_id = Number(target);
  const button = $('confirm-import'); button.disabled = true; button.textContent = 'Salvando…';
  try {
    const result = await api(`/api/imports/${state.batch.batch.id}/commit`, {method:'POST', body:JSON.stringify(payload)});
    $('import-dialog').close(); state.course = null; await refreshLibrary(); await loadCourse(result.course_id, false);
    if (result.duplicates || result.conflicts) alertMessage(`Importação concluída: ${result.added} aulas adicionadas; ${result.duplicates} repetidas; ${result.conflicts} já atribuídas a outro curso.`);
  } finally { button.disabled = false; button.textContent = 'Publicar na biblioteca'; }
}
function downloadJson(filename, value) { const blob = new Blob([JSON.stringify(value, null, 2)], {type:'application/json'}), url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }

// Eventos
async function goHome(filter) { await stopPlayer(); state.course = null; state.lesson = null; state.filter = filter; $('course-search').value = ''; view('home'); window.scrollTo(0, 0); await refreshLibrary(); }
$('home-view').addEventListener('click', action(async e => {
  if (e.target.closest('[data-import]')) return showImporter();
  const id = e.target.closest('[data-course]')?.dataset.course; if (id) await loadCourse(Number(id));
}));
$('course-search').addEventListener('input', action(async () => { if (state.course) await goHome(null); else renderLibrary(); }));
$('nav-library').addEventListener('click', action(() => goHome(null)));
$('nav-continue').addEventListener('click', action(() => goHome('continue')));
$('nav-downloads').addEventListener('click', action(() => goHome('downloads')));
$('back-to-library').addEventListener('click', action(() => goHome(null)));
$('alert').addEventListener('click', clearAlert);
window.addEventListener('scroll', updateNav, {passive:true});
document.addEventListener('click', e => { for (const menu of document.querySelectorAll('.menu[open]')) if (!menu.contains(e.target) || e.target.closest('.menu-list button')) menu.open = false; });
for (const id of ['import-open','import-into-course']) $(id).addEventListener('click', action(showImporter));
$('close-modal').addEventListener('click', () => $('import-dialog').close());
document.querySelectorAll('.cancel-import').forEach(el => el.addEventListener('click', () => $('import-dialog').close()));
$('scan-form').addEventListener('submit', action(scan));
$('back-to-source').addEventListener('click', () => setWizardStep(1));
$('course-target').addEventListener('change', toggleCourseTarget);
$('select-all').addEventListener('change', e => { state.preview.forEach(i => i.selected = e.target.checked); renderPreview(); });
$('preview-items').addEventListener('change', e => { const id = Number(e.target.dataset.select); if (id) { state.preview.find(i => i.message_id===id).selected = e.target.checked; renderPreview(); } });
$('preview-items').addEventListener('input', e => { const id = Number(e.target.dataset.title || e.target.dataset.moduleTitle); if (!id) return; const item = state.preview.find(i => i.message_id===id); if (item) { if (e.target.dataset.title) item.title = e.target.value; else item.module = e.target.value; } });
$('preview-items').addEventListener('dragstart', e => { const row = e.target.closest('[data-preview]'); if (!row) return; state.dragging = Number(row.dataset.preview); row.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; });
$('preview-items').addEventListener('dragover', e => { const target = e.target.closest('[data-preview]'); if (!target) return; e.preventDefault(); target.classList.add('drag-target'); });
$('preview-items').addEventListener('dragleave', e => { e.target.closest('[data-preview]')?.classList.remove('drag-target'); });
$('preview-items').addEventListener('drop', e => { const target = e.target.closest('[data-preview]'); if (!target || !state.dragging) return; e.preventDefault(); const from = state.preview.findIndex(i => i.message_id===state.dragging), to = state.preview.findIndex(i => i.message_id===Number(target.dataset.preview)); if (from>=0 && to>=0) { const item = state.preview.splice(from, 1)[0]; state.preview.splice(to, 0, item); } state.dragging = null; renderPreview(); });
$('preview-items').addEventListener('dragend', () => { state.dragging = null; renderPreview(); });
$('confirm-import').addEventListener('click', action(commitImport));
$('playlist').addEventListener('click', action(async e => {
  const pick = name => { const el = e.target.closest(`[data-${name}]`); return el ? Number(el.getAttribute(`data-${name}`)) : null; };
  let id;
  if ((id = pick('play'))) return playLesson(id);
  if ((id = pick('download'))) return startDownload(id);
  if ((id = pick('remove-download'))) return removeDownload(id);
  if ((id = pick('up'))) return moveLesson(id, -1);
  if ((id = pick('down'))) return moveLesson(id, 1);
  if ((id = pick('edit'))) return editLesson(id);
  if ((id = pick('download-module'))) return downloadMany(id);
  if ((id = pick('rename-module'))) {
    const old = state.course.modules.find(m => m.id===id), title = prompt('Novo nome do módulo', old.title);
    if (title?.trim()) { await api(`/api/modules/${id}`, {method:'PATCH', body:JSON.stringify({title:title.trim()})}); await reloadCourse(); }
  }
}));
$('playlist').addEventListener('dragstart', e => { const row = e.target.closest('[data-lesson-row]'); if (!row) return; state.dragging = Number(row.dataset.lessonRow); row.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; });
$('playlist').addEventListener('dragover', e => { const target = e.target.closest('[data-lesson-row],.module-body'); if (!target || !state.dragging) return; e.preventDefault(); target.classList.add('drag-insert'); });
$('playlist').addEventListener('dragleave', e => e.target.closest('[data-lesson-row],.module-body')?.classList.remove('drag-insert'));
$('playlist').addEventListener('drop', action(async e => { const target = e.target.closest('[data-lesson-row],.module-body'); if (!target || !state.dragging) return; e.preventDefault(); const moving = $('playlist').querySelector(`[data-lesson-row="${state.dragging}"]`); if (!moving) return; if (target.classList.contains('module-body')) target.append(moving); else if (target!==moving) target.before(moving); state.dragging = null; await persistOrder(); }));
$('playlist').addEventListener('dragend', () => { state.dragging = null; document.querySelectorAll('.dragging,.drag-insert').forEach(e => e.classList.remove('dragging', 'drag-insert')); });
$('mark-done').addEventListener('click', action(updateCompletion));
$('next-lesson').addEventListener('click', action(nextLesson));
$('download-course').addEventListener('click', action(() => downloadMany(null)));
$('remove-downloads').addEventListener('click', action(removeAllDownloads));
$('edit-course').addEventListener('click', action(async () => { if (!state.course) return; const title = prompt('Nome do curso', state.course.course.title); if (title===null) return; const description = prompt('Descrição do curso', state.course.course.description||''); if (description===null) return; await api(`/api/courses/${state.course.course.id}`, {method:'PATCH', body:JSON.stringify({title, description})}); await reloadCourse(); }));
$('add-module').addEventListener('click', action(async () => { if (!state.course) return; const name = prompt('Nome do módulo'); if (!name?.trim()) return; await api(`/api/courses/${state.course.course.id}/modules`, {method:'POST', body:JSON.stringify({title:name.trim()})}); await reloadCourse(); }));
$('delete-course').addEventListener('click', action(async () => { if (!state.course || !confirm(`Excluir "${state.course.course.title}" da biblioteca local? Aulas, progresso e downloads desse curso serão removidos do computador. NADA será excluído do Telegram.`)) return; await stopPlayer(); await api(`/api/courses/${state.course.course.id}`, {method:'DELETE'}); await goHome(null); }));
$('make-backup').addEventListener('click', action(async () => { const data = await api('/api/backup', {method:'POST'}); alertMessage(`Backup local criado em ${data.location}${data.filename}`); }));
$('export-progress').addEventListener('click', action(async () => downloadJson('telecourse-progress.json', await api('/api/export/progress'))));
window.addEventListener('pagehide', () => { const v = currentVideo(); if (v && state.lesson) { const body = JSON.stringify({position_seconds:v.currentTime||0, played_delta_seconds:Math.min(30, state.watched), completed:null}); fetch(`/api/lessons/${state.lesson.id}/progress`, {method:'PUT', headers:{'Content-Type':'application/json'}, body, keepalive:true}).catch(() => {}); } });
(async () => {
  try {
    const status = await api('/api/status');
    $('connection-name').textContent = status.ready ? `Conectado: ${status.name}` : status.message;
    $('connection-dot').style.background = status.ready ? '#46d39a' : '#f6ba62';
    await refreshLibrary();
    await pollDownloads();
    const route = location.hash.match(/^#\/curso\/(\d+)$/);
    if (route && state.library.some(c => c.id===Number(route[1]))) await loadCourse(Number(route[1]), false);
  } catch (e) { alertMessage(e); }
})();
