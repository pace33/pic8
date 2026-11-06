/* User-authorized fresh intake. Aiedue is the ONLY backend, even during outages. */
(() => {
  'use strict';
  const primary = 'https://aiedue.ddns.net/db-pic8/api';
  const state = Object.freeze({backend: 'aiedue'});
  const resolved = Promise.resolve(primary);
  // Never select another server, probe legacy health, or replay a failed mutation.
  // The registration status response controls availability, not backend selection.
  window.Pic8Api = Object.freeze({primary, state, resolve: () => resolved});
})();
