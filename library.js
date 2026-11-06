/* Standalone library: every read/write uses the Aiedue API, never the original app. */
(() => {
  'use strict';
  const API = 'https://aiedue.ddns.net/db-pic8/api';
  const $ = (selector) => document.querySelector(selector);
  let resources = [], settings = null, subject = '전체', editing = null, deleting = null;
  let token = sessionStorage.getItem('pic8-library-session') || '', pending = null, lastFocus = null;
  const message = (text) => { $('#library-message').textContent = text; };
  function authState() { $('#login-button').textContent = token ? '로그아웃' : '관리자 로그인'; }
  function clearAuth() { token = ''; sessionStorage.removeItem('pic8-library-session'); authState(); }
  async function request(path, method = 'GET', body) {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(API + path, { method, headers, cache: 'no-store', credentials: 'omit', ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401) clearAuth();
      throw new Error(data.error || '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    }
    return data;
  }
  function show(id) {
    lastFocus = document.activeElement;
    $('#' + id).hidden = false;
    document.body.style.overflow = 'hidden';
    const field = $('#' + id).querySelector('input,button');
    field?.focus();
  }
  function close(id) {
    $('#' + id).hidden = true;
    document.body.style.overflow = '';
    lastFocus?.focus();
    if (id === 'login-dialog') { $('#admin-password').value = ''; pending = null; }
  }
  function authenticated(action) {
    if (token) { action(); return; }
    pending = action; $('#login-error').textContent = ''; show('login-dialog'); $('#admin-password').focus();
  }
  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function applySettings(data) {
    settings = data; $('#site-title').textContent = data.title;
    $('#footer-title').textContent = data.title;
    $('.brand').setAttribute('aria-label', data.title + ' 홈');
    document.title = data.title + ' | 수업에 바로 쓰는 웹앱 모음';
  }
  function render() {
    const query = $('#search').value.trim().toLocaleLowerCase('ko');
    const filtered = resources.filter(r => (subject === '전체' || r.subject === subject) &&
      [r.title, r.author, r.description, r.subject, r.grade, r.tags, r.url].join(' ').toLocaleLowerCase('ko').includes(query));
    filtered.sort((a, b) => $('#sort').value === 'title' ? a.title.localeCompare(b.title, 'ko') :
      ($('#sort').value === 'popular' ? b.views - a.views : 0) || b.createdAt.localeCompare(a.createdAt) || b.id.localeCompare(a.id));
    $('#resource-count').textContent = resources.length;
    $('#hero-count').textContent = resources.length;
    $('#subject-count').textContent = new Set(resources.map(r => r.subject)).size;
    $('#view-max').textContent = resources.reduce((n, r) => Math.max(n, r.views), 0);
    const grid = $('#resource-grid'); grid.replaceChildren();
    for (const [i, r] of filtered.entries()) {
      const card = node('article', `resource-card ${['tone-lime','tone-coral','tone-sky','tone-lilac','tone-sun'][i % 5]}`);
      card.setAttribute('role', 'link'); card.tabIndex = 0; card.dataset.id = r.id;
      card.setAttribute('aria-label', r.title + ' 새 탭에서 열기');
      const top = node('div', 'card-topline'); top.append(node('span', 'subject-pill', r.subject), node('span', 'grade-label', r.grade));
      card.append(top, node('div', 'site-icon', '↗'), node('h3', '', r.title), node('span', 'resource-author', r.author), node('p', '', r.description || '수업에 활용할 수 있는 유용한 웹 학습자료입니다.'));
      const actions = node('div', 'card-manage-row');
      for (const [label, action, cls] of [['수정', () => openForm(r), ''], ['삭제', () => openDelete(r), ' danger']]) {
        const button = node('button', 'card-manage-button' + cls, label); button.type = 'button';
        button.setAttribute('aria-label', `${r.title} ${label}하기`);
        button.addEventListener('click', event => { event.stopPropagation(); authenticated(action); }); actions.append(button);
      }
      const footer = node('div', 'card-footer');
      const domain = node('span', 'domain', new URL(r.url).hostname.replace(/^www\./, ''));
      const meta = node('span', 'card-actions'); const views = node('span', 'view-count', String(r.views)); views.dataset.views = r.id;
      meta.append(views, node('span', 'open-label', '열기 ↗')); footer.append(domain, meta); card.append(actions, footer);
      card.addEventListener('click', () => openResource(r));
      card.addEventListener('keydown', event => { if (event.target === card && ['Enter', ' '].includes(event.key)) { event.preventDefault(); openResource(r); } });
      grid.append(card);
    }
    message(resources.length ? (filtered.length ? `${filtered.length}개의 자료를 찾았어요.` : '검색 조건에 맞는 자료가 없어요.') : '아직 등록된 자료가 없어요. 첫 학습자료를 올려보세요.');
  }
  function openResource(resource) {
    window.open(resource.url, '_blank', 'noopener,noreferrer');
    // Never invent a shared count; reflect only the server acknowledgement.
    request('/resources', 'PATCH', { id: resource.id }).then(({ resource: saved }) => {
      const current = resources.find(r => r.id === saved.id);
      if (current) current.views = Math.max(current.views, saved.views);
      render();
    }).catch(() => message('조회수를 기록하지 못했습니다. 잠시 후 다시 확인해 주세요.'));
  }
  function openForm(resource = null) {
    editing = resource ? { ...resource } : null;
    $('#resource-form').reset(); $('#resource-error').textContent = '';
    $('#modal-title').textContent = resource ? '학습자료 수정하기' : '새 학습자료 올리기';
    $('#save-resource').textContent = resource ? '수정 내용 저장하기' : '자료 등록하기';
    if (resource) {
      for (const key of ['title','url','author','description','subject','grade']) $('#resource-' + key).value = resource[key];
      $('#resource-tags').value = JSON.parse(resource.tags).join(', ');
    }
    show('resource-dialog'); $('#resource-title').focus();
  }
  function openDelete(resource) {
    deleting = { ...resource }; $('#delete-error').textContent = '';
    $('#delete-description').textContent = `“${resource.title}” 자료를 삭제할까요?`; show('delete-dialog');
  }
  async function busy(button, errorId, action) {
    button.disabled = true; $('#' + errorId).textContent = '';
    try { await action(); }
    catch (error) { $('#' + errorId).textContent = error instanceof TypeError ? '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.' : error.message; }
    finally { button.disabled = false; }
  }
  document.querySelectorAll('[data-register]').forEach(button => button.addEventListener('click', () => authenticated(() => openForm())));
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => close(button.dataset.close)));
  document.querySelectorAll('.modal-backdrop').forEach(backdrop => backdrop.addEventListener('click', event => { if (event.target === backdrop && !backdrop.querySelector('button:disabled')) close(backdrop.id); }));
  document.addEventListener('keydown', event => {
    const dialog = document.querySelector('.modal-backdrop:not([hidden])');
    if (!dialog) return;
    if (event.key === 'Escape' && !dialog.querySelector('button:disabled')) close(dialog.id);
    if (event.key === 'Tab') {
      const controls = [...dialog.querySelectorAll('input,textarea,select,button')].filter(el => !el.disabled);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  $('#login-button').addEventListener('click', async () => {
    if (!token) { pending = null; show('login-dialog'); $('#admin-password').focus(); return; }
    try { await request('/admin/login', 'DELETE'); clearAuth(); message('로그아웃되었습니다.'); }
    catch (error) { message(error.message); }
  });
  $('#login-form').addEventListener('submit', event => {
    event.preventDefault();
    busy($('#login-submit'), 'login-error', async () => {
      const data = await request('/admin/login', 'POST', { password: $('#admin-password').value });
      token = data.accessToken; sessionStorage.setItem('pic8-library-session', token); authState();
      const action = pending; close('login-dialog'); if (action) action();
    });
  });
  $('#resource-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget;
    const snapshot = editing;
    busy($('#save-resource'), 'resource-error', async () => {
      const body = Object.fromEntries(new FormData(form));
      if (snapshot) Object.assign(body, { id: snapshot.id, revision: snapshot.revision });
      const { resource } = await request('/resources', snapshot ? 'PUT' : 'POST', body);
      resources = snapshot ? resources.map(r => r.id === resource.id ? resource : r) : [resource, ...resources];
      close('resource-dialog'); render(); message(snapshot ? '학습자료가 수정됐어요.' : '학습자료가 새로 등록됐어요.');
    });
  });
  $('#confirm-delete').addEventListener('click', () => {
    const snapshot = deleting;
    busy($('#confirm-delete'), 'delete-error', async () => {
      await request('/resources', 'DELETE', { id: snapshot.id, revision: snapshot.revision, confirmed: true });
      resources = resources.filter(r => r.id !== snapshot.id); close('delete-dialog'); render(); message('학습자료가 삭제됐어요.');
    });
  });
  $('#edit-title').addEventListener('click', () => authenticated(() => {
    if (!settings) { message('사이트 제목을 불러오지 못했습니다. 새로고침해 주세요.'); return; }
    $('#title-input').value = settings.title; $('#title-error').textContent = ''; show('title-dialog'); $('#title-input').focus();
  }));
  $('#title-form').addEventListener('submit', event => {
    event.preventDefault(); const revision = settings.revision;
    busy($('#save-title'), 'title-error', async () => {
      applySettings(await request('/settings', 'PUT', { title: $('#title-input').value, revision })); close('title-dialog'); message('사이트 제목이 수정됐어요.');
    });
  });
  $('#search').addEventListener('input', render); $('#sort').addEventListener('change', render);
  document.querySelectorAll('[data-subject]').forEach(button => button.addEventListener('click', () => {
    subject = button.dataset.subject;
    document.querySelectorAll('[data-subject]').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button)); }); render();
  }));
  authState();
  request('/resources').then(data => { resources = data.resources; render(); }).catch(() => message('자료를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.'));
  request('/settings').then(applySettings).catch(() => message('사이트 제목을 불러오지 못했습니다. 잠시 후 새로고침해 주세요.'));
  if (token) request('/admin/login').catch(() => clearAuth());
})();
