"""Fresh-start authorization is NOT a legacy import or source write-freeze attestation."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from core import Store
from api import initialize


class FreshStartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.config = initialize(self.home, ['https://pace33.github.io'])
        self.path = self.home / 'registrations.sqlite'
        self.store = Store(self.path, self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self):
        with self.store.db() as db:
            return {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table)]
                    for table in ['participants', 'sessions', 'limits', 'resource_views', 'sqlite_sequence']}

    def test_explicit_authorization_required_and_failure_unchanged(self):
        before = self.snapshot()
        for value in [False, None, 'true', 1]:
            with self.assertRaises(ValueError):
                self.store.fresh_start(user_authorized=value)
        self.assertFalse(self.store.active())
        self.assertEqual(before, self.snapshot())
        with self.store.db() as db:
            self.assertEqual(dict(db.execute('SELECT key,value FROM metadata')), {'active': '0'})

    def test_existing_target_records_credentials_and_sessions_preserved(self):
        fixture = Store(self.path, self.config, qa=True)
        body = dict(action='register', region='검증지역', school='대상검증학교', name='대상검증', pin='0042')
        ident = fixture.registration(body, 'local')['participant']['id']
        password = (self.home / 'admin-password.txt').read_text().strip()
        token = self.store.login({'password': password}, 'local')['accessToken']
        self.store.manage(token, {'id': ident, 'selected': True})
        self.store.views('preserved-view', True)
        before = self.snapshot()
        config_bytes = (self.home / 'config.json').read_bytes()
        password_bytes = (self.home / 'admin-password.txt').read_bytes()
        self.store.fresh_start(user_authorized=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((self.home / 'config.json').read_bytes(), config_bytes)
        self.assertEqual((self.home / 'admin-password.txt').read_bytes(), password_bytes)
        reopened = Store(self.path, self.config)
        self.assertEqual(reopened.manage(token)['participants'][0]['id'], ident)
        self.assertEqual(reopened.registration(dict(body, action='lookup'), 'local')['participant']['id'], ident)
        reopened.login({'password': password}, 'another-ip')
        status = reopened.status()
        self.assertTrue(status['readyForCutover'])
        self.assertEqual(status['operationMode'], 'fresh-start-without-legacy-import')
        for key in ['sourceNotImported', 'legacyWritesNotControlled', 'userAuthorizedFreshStart']:
            self.assertIs(status[key], True)
        with reopened.db() as db:
            meta = dict(db.execute('SELECT key,value FROM metadata'))
        self.assertEqual(meta['targetExistingCountAtFreshStart'], '1')
        self.assertNotIn('complete_import', meta)
        self.assertEqual(meta['legacyDataMigrated'], '0')
        self.assertEqual(meta['legacyWritesStopped'], '0')

    def test_idempotent_audit_and_guarded_legacy_activation(self):
        self.store.fresh_start(user_authorized=True)
        with self.store.db() as db:
            before = dict(db.execute('SELECT key,value FROM metadata'))
        self.store.fresh_start(user_authorized=True)
        with self.store.db() as db:
            self.assertEqual(before, dict(db.execute('SELECT key,value FROM metadata')))
        with self.assertRaises(ValueError):
            self.store.activate()
        with self.assertRaises(ValueError):
            self.store.activate(source_writes_stopped=True)

    def test_existing_import_is_not_relabelled_as_unimported(self):
        self.store.import_records(dict(event='teacher-workshop-jingu-2026', confirmedComplete=True, sourceRowCount=0, participants=[]))
        with self.assertRaises(ValueError):
            self.store.fresh_start(user_authorized=True)
        self.assertFalse(self.store.active())
        self.store.activate(source_writes_stopped=True)
        self.assertTrue(self.store.active())

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('api.py')),
                               '--home', str(self.home), *args], capture_output=True, text=True)

    def test_cli_fresh_start_requires_its_own_truthful_flag(self):
        self.assertNotEqual(self.cli('fresh-start').returncode, 0)
        self.assertNotEqual(self.cli('fresh-start', '--confirmed-empty', '--legacy-writes-stopped').returncode, 0)
        self.assertFalse(self.store.active())
        self.assertNotEqual(self.cli('fresh-start', '--user-authorized-fresh-start', '--legacy-writes-stopped').returncode, 0)
        self.assertFalse(self.store.active())
        completed = self.cli('fresh-start', '--user-authorized-fresh-start')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)['readyForCutover'])
        self.assertNotEqual(self.cli('activate', '--user-authorized-fresh-start').returncode, 0)
        self.assertTrue(self.store.active())

    def test_cli_backup_readable_and_connection_closed(self):
        dest = self.home / 'backup.sqlite'
        result = self.cli('backup', '--input', str(dest))
        self.assertEqual(result.returncode, 0, result.stderr)
        db = sqlite3.connect(dest)
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        db.close()
        dest.unlink()


if __name__ == '__main__':
    unittest.main(verbosity=2)
