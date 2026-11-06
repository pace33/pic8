/* Self-hosted API with an explicit, data-preserving migration gate. */
(() => {
  'use strict';
  const primary = 'https://aiedue.ddns.net/db-pic8/api';
  const legacy = 'https://teacher-workshop-jingu-2026.lejinku.chatgpt.site/api';
  let pending;
  const state = {backend: 'checking', readyForCutover: false};
  async function choose() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(primary + '/health', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw Error('Primary API not ready');
      const status = await response.json();
      if (status.ok === true && status.readyForCutover === true) {
        state.backend = 'aiedue';
        state.readyForCutover = true;
        return primary;
      }
    } catch {
      // No blind switch to an empty database, and no mutation is retried here.
    } finally {
      clearTimeout(timer);
    }
    state.backend = 'legacy-preserved';
    return legacy;
  }
  window.Pic8Api = Object.freeze({primary, legacy, state,
    // Pin the backend per page/session; a migration requires source write freeze
    // and a fresh page, never an automatic replay of a POST to another server.
    resolve: () => pending || (pending = choose())});
})();
