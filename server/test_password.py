import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from api import initialize
from core import Store, ApiError

class PasswordChangeTests(unittest.TestCase):
    def test_four_character_password_preserves_records_and_revokes_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            config = initialize(home, ['https://pace33.github.io'])
            old_password = (home / 'admin-password.txt').read_text().strip()
            store = Store(home / 'registrations.sqlite', config)
            store.activate(confirmed_empty=True, source_writes_stopped=True)
            participant = store.registration({'action':'register','region':'검증','school':'검증학교','name':'변경검증','pin':'0042'}, 'local')['participant']
            token = store.login({'password':old_password}, 'local')['accessToken']
            store.manage(token, {'id':participant['id'],'selected':True})
            with store.db() as db:
                before = [dict(row) for row in db.execute('SELECT * FROM participants')]
            program = "import sys; from unittest.mock import patch; from api import main; sys.argv=['api.py','--home',sys.argv[1],'set-password']; m=patch('getpass.getpass',side_effect=['2468','2468']); m.start(); main()"
            result = subprocess.run([sys.executable,'-B','-c',program,str(home)], cwd=Path(__file__).parent, capture_output=True,text=True,check=True)
            self.assertTrue(json.loads(result.stdout)['passwordChanged'])
            changed = json.loads((home / 'config.json').read_text())
            for key in config:
                if key not in ('admin_salt','admin_hash'):
                    self.assertEqual(config[key], changed[key])
            fresh = Store(home / 'registrations.sqlite', changed)
            with fresh.db() as db:
                self.assertEqual(before, [dict(row) for row in db.execute('SELECT * FROM participants')])
            for password in (old_password,'wrong'):
                with self.assertRaises(ApiError):
                    fresh.login({'password':password}, 'local')
            with self.assertRaises(ApiError):
                fresh.manage(token)
            new_token = fresh.login({'password':'2468'},'local')['accessToken']
            self.assertEqual(fresh.manage(new_token)['selectedCount'],1)
            self.assertEqual(fresh.registration({'action':'lookup','region':'검증','school':'검증학교','name':'변경검증','pin':'0042'},'local')['participant']['id'],participant['id'])
            self.assertNotIn('2468', (home / 'config.json').read_text())
            self.assertFalse((home / 'admin-password.txt').exists())

if __name__ == '__main__':
    unittest.main()
