import concurrent.futures
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from core import Store, ApiError, ANNOUNCEMENT_TS
from api import initialize, make_server


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.config = initialize(self.home, ['https://pace33.github.io'])
        self.now = ANNOUNCEMENT_TS - 3600
        self.store = Store(self.home / 'test.sqlite', self.config, clock=lambda: self.now, qa=True)
        self.token = self.store.login({'password': self.config['qa_admin_password']}, 'local')['accessToken']

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, n=0, action='register', **extra):
        return dict(region='충북', school='검증전용학교', name='검증' + str(n), pin='9876', action=action, **extra)

    def error(self, status, fn):
        with self.assertRaises(ApiError) as got:
            fn()
        self.assertEqual(status, got.exception.status)

    def test_privacy_and_announcement(self):
        result = self.store.registration(self.body(), 'local')['participant']
        self.assertEqual(result['name'], '검**')
        self.store.manage(self.token, {'id': result['id'], 'selected': True})
        before = self.store.registration(self.body(action='lookup'), 'local')['participant']
        self.assertEqual(before['status'], 'received')
        self.assertNotIn('selected_slot', before)
        self.now = ANNOUNCEMENT_TS
        self.assertEqual(self.store.registration(self.body(action='lookup'), 'local')['participant']['status'], 'selected')
        status = self.store.status()
        self.assertEqual(status['participants'], [])
        self.assertIsNone(status['count'])
        self.assertTrue(status['published'])

    def test_duplicate_wrong_pin_cancel_identity(self):
        original = self.store.registration(self.body(), 'local')['participant']
        again = self.store.registration(self.body(), 'local')['participant']
        self.assertEqual(original['id'], again['id'])
        bad = self.body(action='lookup'); bad['pin'] = '0000'
        self.error(404, lambda: self.store.registration(bad, 'local'))
        cancel = self.body(action='cancel', id='someone-else')
        self.error(404, lambda: self.store.registration(cancel, 'local'))
        self.assertEqual(self.store.manage(self.token)['totalCount'], 1)
        cancel['id'] = original['id']
        self.store.registration(cancel, 'local')
        self.error(404, lambda: self.store.registration(self.body(action='lookup'), 'local'))
        self.assertEqual(self.store.manage(self.token)['totalCount'], 0)
        fresh = self.store.registration(self.body(), 'local')['participant']
        self.assertNotEqual(original['id'], fresh['id'])

    def test_validation(self):
        for value in ['123456', '１２３４', 1234, '', None, '1234\n']:
            body = self.body(); body['pin'] = value
            self.error(400, lambda: self.store.registration(body, 'local'))
        for key, value in [('region',''), ('school','x'*81), ('name','a'), ('name','가\u0000나')]:
            body = self.body();body[key] = value
            self.error(400, lambda: self.store.registration(body, 'local'))
        self.error(400, lambda: self.store.registration(self.body(action='delete_all'), 'local'))

    def test_capacity_concurrent_and_unlimited_intake(self):
        ids = [self.store.registration(self.body(n), 'local')['participant']['id'] for n in range(25)]
        def select(ident):
            try:
                self.store.manage(self.token, {'id': ident, 'selected': True})
                return 200
            except ApiError as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(select, ids))
        self.assertEqual(statuses.count(200), 20)
        self.assertEqual(statuses.count(409), 5)
        data = self.store.manage(self.token)
        self.assertEqual(data['totalCount'], 25)
        self.assertEqual(data['selectedCount'], 20)
        chosen = next(row for row in data['participants'] if row['selected_slot'] is not None)
        waiting = next(row for row in data['participants'] if row['selected_slot'] is None)
        self.store.manage(self.token, {'id': chosen['id'], 'selected': False})
        self.store.manage(self.token, {'id': waiting['id'], 'selected': True})
        self.assertEqual(self.store.manage(self.token)['selectedCount'], 20)

    def test_admin_delete_confirmation_counts_and_slot_reuse(self):
        ids = [self.store.registration(self.body(n), 'local')['participant']['id'] for n in range(21)]
        for ident in ids[:20]:
            self.store.manage(self.token, {'id': ident, 'selected': True})
        self.error(401, lambda: self.store.delete_registration('', {'id': ids[0], 'confirmed': True}))
        for body in [{'id': ids[0]}, {'id': ids[0], 'confirmed': False}, {'id': ids[0], 'confirmed': 1}, {'id': '', 'confirmed': True}, {'id': 'x'*81, 'confirmed': True}]:
            self.error(400, lambda: self.store.delete_registration(self.token, body))
        self.assertEqual(self.store.manage(self.token)['totalCount'], 21)
        result = self.store.delete_registration(self.token, {'id': ids[-1], 'confirmed': True})
        self.assertEqual(result, {'deleted': True, 'wasSelected': False})
        self.assertEqual(self.store.manage(self.token)['selectedCount'], 20)
        result = self.store.delete_registration(self.token, {'id': ids[0], 'confirmed': True})
        self.assertTrue(result['wasSelected'])
        data = self.store.manage(self.token)
        self.assertEqual((data['totalCount'], data['selectedCount']), (19, 19))
        self.error(404, lambda: self.store.registration(self.body(action='lookup'), 'local'))
        self.error(404, lambda: self.store.delete_registration(self.token, {'id': ids[0], 'confirmed': True}))
        fresh = self.store.registration(self.body(), 'local')['participant']
        self.assertNotEqual(fresh['id'], ids[0])
        self.store.manage(self.token, {'id': fresh['id'], 'selected': True})
        self.assertEqual(self.store.manage(self.token)['selectedCount'], 20)
        self.store.logout(self.token)
        self.error(401, lambda: self.store.delete_registration(self.token, {'id': fresh['id'], 'confirmed': True}))

    def test_auth_session_persistence_logout_and_no_pin_leak(self):
        self.error(401, lambda: self.store.manage(''))
        self.error(401, lambda: self.store.login({'password':'wrong'}, 'other'))
        self.store.registration(self.body(), 'local')
        second = Store(self.store.path, self.config, clock=lambda: self.now, qa=True)
        data = second.manage(self.token)
        row = data['participants'][0]
        self.assertIsInstance(row['created_at'], int)
        self.assertEqual(set(row), {'id','region','school','full_name','created_at','receipt_order','selected_slot'})
        self.assertNotIn('9876', json.dumps(data))
        second.logout(self.token)
        self.error(401, lambda: self.store.manage(self.token))

    def test_pin_rate_limit_including_duplicate_registration(self):
        self.store.registration(self.body(), 'local')
        for n in range(11):
            body = self.body();body['pin'] = '0000'
            self.error(409, lambda: self.store.registration(body, 'local'))
        self.error(429, lambda: self.store.registration(self.body(), 'different-ip'))

    def test_atomic_views_and_validation(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.store.views('material-01', True), range(40)))
        self.assertEqual(self.store.views('material-01'), {'views': 40})
        for ident in ['../secret', '', 'x'*101, 'bad/id', '한글']:
            self.error(400, lambda: self.store.views(ident))

    def test_migration_gate_and_non_destructive_failure(self):
        production = Store(self.home / 'prod.sqlite', self.config, clock=lambda: self.now)
        self.error(503, lambda: production.registration(self.body(), 'local'))
        with self.assertRaises(ValueError):
            production.activate(source_writes_stopped=True)
        row = dict(id='legacy-id',region='충북',school='이관검증',full_name='검증자',pin='9876',receipt_order=14,created_at=1700000000000,selected_slot=1)
        document = {'confirmedComplete':True,'event':'teacher-workshop-jingu-2026','sourceRowCount':1,'participants':[row]}
        broken = dict(document,participants=[dict(row,pin=None)])
        with self.assertRaises(ApiError):
            production.import_records(broken)
        with production.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM participants').fetchone()[0], 0)
        production.import_records(document)
        self.assertFalse(production.active())
        with self.assertRaises(ValueError):
            production.activate()
        production.activate(source_writes_stopped=True)
        result = production.registration(dict(row,name=row['full_name'],action='lookup'), 'local')['participant']
        self.assertEqual(result['id'], 'legacy-id')
        with self.assertRaises(ValueError):
            production.import_records(document)
        self.assertEqual(production.registration(dict(row,name=row['full_name'],action='lookup'), 'local')['participant']['id'], 'legacy-id')


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.home = Path(self.tmp.name)
        self.config = initialize(self.home, ['https://pace33.github.io'])
        self.server = make_server(self.home, '127.0.0.1', 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self, path, method='GET', body=None, origin='https://pace33.github.io', headers=None):
        head = {'Origin':origin,'Content-Type':'application/json'};head.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base+path,data=data,method=method,headers=head)
        try:
            response = urllib.request.urlopen(req,timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status,dict(response.headers),json.loads(raw) if raw else None

    def test_cors_preflight_and_denial(self):
        status,head,_ = self.request('/api/admin/login','OPTIONS',headers={'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,authorization'})
        self.assertEqual(status,204)
        self.assertEqual(head['Access-Control-Allow-Origin'],'https://pace33.github.io')
        status,head,_ = self.request('/api/registrations',origin='https://evil.example')
        self.assertEqual(status,403);self.assertNotIn('Access-Control-Allow-Origin',head)
        self.assertEqual(self.request('/api/health','OPTIONS',headers={'Access-Control-Request-Method':'PUT'})[0],403)

    def test_http_privacy_auth_and_gate(self):
        status,head,data = self.request('/api/registrations')
        self.assertEqual(status,200);self.assertEqual(data['participants'],[]);self.assertIsNone(data['count']);self.assertFalse(data['readyForCutover'])
        self.assertEqual(self.request('/api/manage')[0],401)
        self.assertEqual(self.request('/api/manage','DELETE',{'id':'x','confirmed':True})[0],401)
        self.assertEqual(self.request('/api/manage','DELETE',{'id':'x','confirmed':True},origin='https://evil.example')[0],403)
        self.assertEqual(self.request('/api/manage','POST',{'id':'x','selected':True})[0],401)
        self.assertEqual(self.request('/api/registrations','POST',{'action':'register','region':'충북','school':'학교','name':'검증','pin':'123456'})[0],400)
        self.assertEqual(self.request('/api/registrations','POST',{'action':'register','region':'충북','school':'학교','name':'검증','pin':'1234'})[0],503)
        self.assertEqual(self.request('/api/health',headers={'X-Pic8-QA':'not-a-secret'})[0],404)

    def test_http_confirmed_admin_delete(self):
        # Use only this test's temporary database, with no production records.
        store = Store(self.home / 'registrations.sqlite', self.config)
        store.activate(confirmed_empty=True, source_writes_stopped=True)
        password = (self.home / 'admin-password.txt').read_text().strip()
        status, _, login = self.request('/api/admin/login', 'POST', {'password': password})
        self.assertEqual(status, 200)
        headers = {'Authorization': 'Bearer ' + login['accessToken']}
        body = {'action': 'register', 'region': '충북', 'school': '검증학교', 'name': '삭제검증', 'pin': '9876'}
        status, _, data = self.request('/api/registrations', 'POST', body)
        self.assertEqual(status, 200)
        ident = data['participant']['id']
        self.assertEqual(self.request('/api/manage', 'POST', {'id': ident, 'selected': True}, headers=headers)[0], 200)
        self.assertEqual(self.request('/api/manage', 'DELETE', {'id': ident}, headers=headers)[0], 400)
        status, _, data = self.request('/api/manage', 'DELETE', {'id': ident, 'confirmed': True}, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(data, {'deleted': True, 'wasSelected': True})
        self.assertEqual(self.request('/api/manage', headers=headers)[2]['totalCount'], 0)
        self.assertEqual(self.request('/api/manage', headers=headers)[2]['selectedCount'], 0)
        body['action'] = 'lookup'
        self.assertEqual(self.request('/api/registrations', 'POST', body)[0], 404)


if __name__ == '__main__':
    unittest.main(verbosity=2)
