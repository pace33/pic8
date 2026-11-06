"""Rotation tests use newly generated credentials and private temporary state only."""
import concurrent.futures
import json
import secrets
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from api import initialize, make_server
from core import Store, ApiError
from library import Library


class PasswordApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.config = initialize(self.home, ['https://pace33.github.io'])
        self.old = (self.home / 'admin-password.txt').read_text().rstrip('\n')
        self.new = secrets.token_urlsafe(24)
        self.store = Store(self.home / 'registrations.sqlite', self.config)
        self.server = None

    def tearDown(self):
        if self.server:
            self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.tmp.cleanup()

    def body(self, **extra):
        return dict(currentPassword=self.old, newPassword=self.new, confirmPassword=self.new, **extra)

    def error(self, status, fn):
        with self.assertRaises(ApiError) as got: fn()
        self.assertEqual(status, got.exception.status)

    def start(self):
        self.server = make_server(self.home, '127.0.0.1', 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def http(self, body=None, method='POST', origin='https://pace33.github.io', extra=None, path='/admin/password'):
        headers = {'Content-Type':'application/json'}
        if origin is not None: headers['Origin'] = origin
        if extra: headers.update(extra)
        # Send headers and body together so early Origin rejection cannot race
        # urllib's separate body write on Windows and hide the HTTP response.
        import socket
        from http.client import HTTPResponse
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else b''
        headers.update({'Host':'127.0.0.1','Content-Length':str(len(data)),'Connection':'close'})
        raw=(method+' /api'+path+' HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers.items())+'\r\n').encode()+data
        with socket.create_connection(('127.0.0.1',self.server.server_port),timeout=15) as sock:
            sock.sendall(raw)
            response=HTTPResponse(sock); response.begin()
            with response:
                raw=response.read()
                return response.status,dict(response.headers),json.loads(raw) if raw else None

    def test_wrong_current_has_no_credential_session_or_initial_file_changes(self):
        token = self.store.login({'password':self.old}, 'login')['accessToken']
        before = (self.home/'config.json').read_bytes()
        body = self.body(); body['currentPassword'] = secrets.token_urlsafe(28)
        self.error(401, lambda:self.store.change_password(body, 'bad'))
        self.assertTrue(before == (self.home/'config.json').read_bytes())
        self.assertTrue((self.home/'admin-password.txt').exists())
        self.store.authorize(token)

    def test_empty_lengths_confirmation_and_invalid_unicode_do_not_change(self):
        before = (self.home/'config.json').read_bytes()
        cases = [('currentPassword',''), ('currentPassword',None), ('currentPassword','x'*1025),
                 ('newPassword',''), ('newPassword',None), ('newPassword','x'*3), ('newPassword','x'*1025),
                 ('confirmPassword',None), ('confirmPassword','different'), ('newPassword','\ud800'*4)]
        for n,(key,value) in enumerate(cases):
            body = self.body(); body[key] = value
            self.error(400, lambda:self.store.change_password(body, 'validation'+str(n)))
            self.assertTrue(before == (self.home/'config.json').read_bytes())

    def test_rotation_revokes_every_session_and_survives_restart(self):
        preserved = {k:v for k,v in self.config.items() if k not in ('admin_salt','admin_hash','admin_session_epoch')}
        tokens = [self.store.login({'password':self.old}, 'login'+str(n))['accessToken'] for n in range(4)]
        self.assertTrue(self.store.change_password(self.body(), 'change')['passwordChanged'])
        for token in tokens:self.error(401, lambda:self.store.authorize(token))
        self.error(401, lambda:self.store.login({'password':self.old}, 'old'))
        self.assertFalse((self.home/'admin-password.txt').exists())
        fresh = Store(self.store.path, json.loads((self.home/'config.json').read_text()))
        token = fresh.login({'password':self.new}, 'new')['accessToken']; fresh.authorize(token)
        self.assertTrue(all(v != self.new for v in fresh.config.values()))
        self.assertTrue(all(v == fresh.config[k] for k,v in preserved.items()))

    def test_unicode_code_points_spaces_and_maximum_round_trip(self):
        for n,value in enumerate(['😀'*4, ' '+secrets.token_urlsafe(10)+' ', '😀'*1024]):
            body = dict(currentPassword=self.old, newPassword=value, confirmPassword=value)
            self.store.change_password(body, 'unicode'+str(n))
            self.store.login({'password':value}, 'login'+str(n))
            if value.strip() != value:self.error(401, lambda:self.store.login({'password':value.strip()}, 'trim'))
            self.old = value

    def test_save_replace_failure_retains_old_authentication_and_tokens(self):
        token = self.store.login({'password':self.old}, 'login')['accessToken']
        before = (self.home/'config.json').read_bytes()
        with patch('auth.os.replace', side_effect=OSError):
            self.error(503, lambda:self.store.change_password(self.body(), 'fail'))
        self.assertTrue(before == (self.home/'config.json').read_bytes())
        self.store.authorize(token); self.store.login({'password':self.old}, 'login')
        self.assertFalse(list(self.home.glob('.config-*.tmp')))

    def test_stage_failure_does_not_remove_initial_file(self):
        before = (self.home/'config.json').read_bytes()
        with patch('auth.os.fsync', side_effect=OSError):
            self.error(503, lambda:self.store.change_password(self.body(), 'fail'))
        self.assertTrue(before == (self.home/'config.json').read_bytes())
        self.assertTrue((self.home/'admin-password.txt').exists())

    def test_stale_initial_file_cleanup_failure_aborts_before_commit(self):
        before = (self.home/'config.json').read_bytes()
        real = Path.unlink
        def fail(path,*a,**kw):
            if path.name == 'admin-password.txt':raise PermissionError()
            return real(path,*a,**kw)
        with patch.object(Path, 'unlink', fail):
            self.error(503, lambda:self.store.change_password(self.body(), 'fail'))
        self.assertTrue(before == (self.home/'config.json').read_bytes())
        self.assertTrue((self.home/'admin-password.txt').exists())
        self.store.change_password(self.body(), 'retry')
        self.assertFalse((self.home/'admin-password.txt').exists())

    def test_concurrent_changes_have_exactly_one_winner(self):
        body = self.body()
        def change(n):
            other = Store(self.store.path, dict(self.config))
            try:other.change_password(body, 'race'+str(n)); return 200
            except ApiError as e:return e.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:statuses=list(pool.map(change, range(6)))
        self.assertEqual(statuses.count(200), 1); self.assertEqual(statuses.count(401), 5)
        self.store.login({'password':self.new}, 'winner')

    def test_durable_epoch_revokes_sessions_even_when_cleanup_fails(self):
        token = self.store.login({'password':self.old}, 'login')['accessToken']
        # save_credentials's atomic commit still succeeds; only session cleanup fails.
        from auth import save_credentials
        with self.store.auth_guard():
            with patch.object(self.store, 'db', side_effect=sqlite3.OperationalError):
                self.store.persist_password(self.new)
        self.error(401, lambda:self.store.authorize(token))
        fresh = Store(self.store.path, dict(self.config)); self.error(401, lambda:fresh.authorize(token))

    def test_cross_process_serialization_and_live_refresh(self):
        import subprocess, sys
        body = self.body()
        program = ("import sys,json;from pathlib import Path;from core import Store,ApiError;"
                   "h=Path(sys.argv[1]);s=Store(h/'registrations.sqlite',json.loads((h/'config.json').read_text()));"
                   "body=json.loads(sys.stdin.read());\n"
                   "try:s.change_password(body,'process'+sys.argv[2]);print(200)\n"
                   "except ApiError as e:print(e.status)\n")
        def run(n):
            r=subprocess.run([sys.executable,'-B','-c',program,str(self.home),str(n)],input=json.dumps(body),
                text=True,capture_output=True,cwd=Path(__file__).parent,timeout=30)
            self.assertEqual(r.returncode,0); return int(r.stdout)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(run,range(2)))
        self.assertTrue(sorted(statuses)==[200,401])
        # The already-running Store must pick up another process's change.
        self.error(401,lambda:self.store.login({'password':self.old},'old'))
        self.store.login({'password':self.new},'new')

    def test_sessions_never_bypass_current_password(self):
        token = self.store.login({'password':self.old}, 'login')['accessToken']
        self.start(); body=self.body();body['currentPassword']=''
        self.assertEqual(self.http(body, extra={'Authorization':'Bearer '+token})[0],400)
        body['currentPassword']=secrets.token_urlsafe(29)
        self.assertEqual(self.http(body, extra={'Authorization':'Bearer '+token})[0],401)
        self.store.authorize(token)

    def test_origin_cors_qa_header_and_qa_password_cannot_rotate(self):
        config = json.loads((self.home/'config.json').read_text()); config['qa_enabled']=True
        (self.home/'config.json').write_text(json.dumps(config))
        self.start(); before=(self.home/'config.json').read_bytes()
        for origin in [None, 'null', 'https://evil.example']:
            self.assertEqual(self.http(self.body(),origin=origin)[0],403)
        for value in ['', config['qa_token']]:
            self.assertEqual(self.http(self.body(),extra={'X-Pic8-QA':value})[0],403)
        body=self.body();body['currentPassword']=config['qa_admin_password']
        self.assertEqual(self.http(body)[0],401)
        qa=Store(self.home/'qa.sqlite',config,qa=True)
        self.error(403,lambda:qa.change_password(self.body(),'qa'))
        self.assertTrue(before==(self.home/'config.json').read_bytes())
        status,headers,_=self.http(method='OPTIONS',extra={'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        self.assertEqual(status,204);self.assertEqual(headers['Access-Control-Allow-Origin'],'https://pace33.github.io')
        self.assertEqual(headers['Cache-Control'],'no-store')

    def test_http_success_restart_and_full_unicode_payload(self):
        self.start(); body=self.body();body['newPassword']=body['confirmPassword']='😀'*1024
        status,headers,data=self.http(body)
        self.assertEqual(status,200);self.assertEqual(set(data),{'passwordChanged','reauthenticationRequired'})
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.server.shutdown();self.server.server_close();self.thread.join();self.server=None
        self.start()
        self.assertEqual(self.http({'password':self.old},path='/admin/login')[0],401)
        self.assertEqual(self.http({'password':body['newPassword']},path='/admin/login')[0],200)

    def test_failed_attempts_are_limited(self):
        body=self.body();body['currentPassword']=secrets.token_urlsafe(26)
        for _ in range(6):self.error(401,lambda:self.store.change_password(body,'limited'))
        self.error(429,lambda:self.store.change_password(self.body(),'limited'))
        self.store.login({'password':self.old},'unchanged')

    def test_registration_pin_selection_library_views_settings_preserved(self):
        self.store.activate(confirmed_empty=True,source_writes_stopped=True)
        pin='0042';identity=dict(action='register',region='시험',school='시험학교',name='보존시험',pin=pin)
        participant=self.store.registration(identity,'participant')['participant']
        token=self.store.login({'password':self.old},'login')['accessToken']
        self.store.manage(token,dict(id=participant['id'],selected=True))
        self.store.views('preserved',True)
        lib=Library(self.home/'library.sqlite',self.store)
        resource=lib.resources('POST',dict(title='격리자료',url='https://example.org',author='시험',description='보존',subject='수학',grade='전 학년',tags='검증'),token,'lib')['resource']
        lib.resources('PATCH',dict(id=resource['id']),'','view')
        settings=lib.settings('GET',None,'','read'); lib.settings('PUT',dict(title='보존 제목',revision=settings['revision']),token,'settings')
        with self.store.db() as db:before=[tuple(r) for r in db.execute('SELECT * FROM participants')];meta=[tuple(r) for r in db.execute('SELECT * FROM metadata')]
        resources=lib.resources('GET',None,'','read');settings=lib.settings('GET',None,'','read')
        self.store.change_password(self.body(),'change')
        with self.store.db() as db:self.assertTrue(before==[tuple(r) for r in db.execute('SELECT * FROM participants')]);self.assertTrue(meta==[tuple(r) for r in db.execute('SELECT * FROM metadata')])
        self.assertTrue(resources==lib.resources('GET',None,'','read'));self.assertTrue(settings==lib.settings('GET',None,'','read'))
        self.assertEqual(self.store.views('preserved')['views'],1)
        self.assertTrue(self.store.registration(dict(identity,action='lookup'),'lookup')['participant']['id']==participant['id'])
        self.error(401,lambda:lib.resources('POST',{},token,'old'))


if __name__ == '__main__':unittest.main()
