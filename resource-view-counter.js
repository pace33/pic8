/* 배움 링크 자료별 조회수 모듈
 * 원본 웹앱의 자료 버튼에 data-resource-id="고유한-자료ID"를 지정하고
 * <script src="./resource-view-counter.js" defer></script>를 추가해 사용합니다.
 * 공용 조회수 저장 API가 있다면 script에 data-views-api="/api/resource-views"를 지정합니다.
 * 미지정 시 이 브라우저에서만 조회수가 저장되며 "이 기기 조회수"로 표시됩니다.
 */
(() => {
  'use strict';

  const script = document.currentScript;
  const apiBase = script && script.dataset.viewsApi
    ? script.dataset.viewsApi.replace(/\/$/, '')
    : '';
  const keyPrefix = 'aiedue.pic8.views.v1.';
  const textFor = count => Number.isSafeInteger(count) && count >= 0 ? count.toLocaleString('ko-KR') : '—';
  const escapeId = id => encodeURIComponent(id);
  const cards = () => Array.from(document.querySelectorAll('[data-resource-id]'));
  const validId = id => typeof id === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(id);
  const counterNodes = new Map();

  function getLocal(id) {
    try { return Math.max(0, Number.parseInt(localStorage.getItem(keyPrefix + id) || '0', 10) || 0); }
    catch { return 0; }
  }

  function setLocal(id, n) {
    try { localStorage.setItem(keyPrefix + id, String(n)); } catch {}
  }

  function updateBadges(id, count) {
    (counterNodes.get(id) || []).forEach(node => {
      node.textContent = `👁 ${apiBase ? '조회수' : '이 기기 조회수'} ${textFor(count)}`;
    });
  }

  async function readShared(id) {
    const response = await fetch(`${apiBase}/${escapeId(id)}`, {cache:'no-store'});
    if (!response.ok) throw Error('조회수 요청 실패');
    const json = await response.json();
    if (!Number.isSafeInteger(json.views) || json.views < 0) throw Error('잘못된 조회수');
    return json.views;
  }

  async function increaseShared(id) {
    const response = await fetch(`${apiBase}/${escapeId(id)}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: '{}', cache: 'no-store', keepalive: true
    });
    if (!response.ok) throw Error('조회수 저장 실패');
    const json = await response.json();
    if (!Number.isSafeInteger(json.views) || json.views < 0) throw Error('잘못된 조회수');
    return json.views;
  }

  async function refresh(id) {
    if (!apiBase) return updateBadges(id, getLocal(id));
    try { updateBadges(id, await readShared(id)); }
    catch { updateBadges(id, null); }
  }

  function installBadges() {
    for (const element of cards()) {
      if (element.dataset.resourceViewReady === 'true') continue;
      const id = element.dataset.resourceId;
      if (!validId(id)) continue;
      element.dataset.resourceViewReady = 'true';
      const badge = document.createElement('span');
      badge.className = 'resource-view-count';
      badge.setAttribute('aria-live', 'polite');
      badge.style.cssText = 'display:inline-block;margin-inline-start:8px;font-size:.83em;color:#536676;white-space:nowrap';
      element.appendChild(badge);
      if (!counterNodes.has(id)) counterNodes.set(id, []);
      counterNodes.get(id).push(badge);
      refresh(id);
    }
  }

  document.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target.closest('[data-resource-id]') : null;
    const id = target && target.dataset.resourceId;
    if (!validId(id)) return;
    if (apiBase) {
      increaseShared(id).then(n => updateBadges(id, n)).catch(() => updateBadges(id, null));
    } else {
      const n = getLocal(id) + 1;
      setLocal(id, n);
      updateBadges(id, n);
    }
  }, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', installBadges, {once: true});
  } else installBadges();

  new MutationObserver(installBadges).observe(document.documentElement, {childList: true, subtree: true});
})();
