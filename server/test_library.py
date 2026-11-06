import concurrent.futures
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from api import initialize, make_server
from core import Store, ApiError
from library import Library


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.config = initialize(self.home, ['https://pace33.github.io', 'https://aiedue.ddns.net'])
        self.auth = Store(self.home / 'registrations.sqlite', self.config)
        password = (self.home / 'admin-password.txt').read_text().strip()
        self.token = self.auth.login({'password': password}, 'test')['accessToken']
        self.library = Library(self.home / 'library.sqlite', self.auth)
        self.body = dict(title='테스트 자료', url='https://example.org/?a=1', author='검증', description='설명\n둘째 줄', subject='수학', grade='전 학년', tags='수업, 도구')

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method, body=None, token=None, ip='test'):
        return self.library.resources(method, body, self.token if token is None else token, ip)

    def error(self, status, fn):
        with self.assertRaises(ApiError) as error:
            fn()
        self.assertEqual(error.exception.status, status)

    def test_crud_public_contract_and_server_fields(self):
        r = self.call('POST', dict(self.body, id='forged', views=900, createdBy='forged', createdAt='fake'))['resource']
        self.assertNotEqual(r['id'], 'forged'); self.assertEqual(r['views'], 0)
        self.assertEqual(r['createdBy'], 'aiedue-admin'); self.assertEqual(json.loads(r['tags']), ['수업', '도구'])
        public = self.call('GET', token='')['resources']
        self.assertEqual(public, [r]); self.assertEqual(set(r), {'id','title','url','author','description','subject','grade','tags','views','createdBy','createdAt','revision'})
        changed = self.call('PUT', dict(self.body, id=r['id'], revision=1, title='수정됨'))['resource']
        self.assertEqual(changed['title'], '수정됨'); self.assertEqual(changed['createdAt'], r['createdAt']); self.assertEqual(changed['revision'], 2)
        self.error(409, lambda: self.call('PUT', dict(self.body, id=r['id'], revision=1)))
        self.error(400, lambda: self.call('DELETE', dict(id=r['id'], revision=2)))
        self.error(409, lambda: self.call('DELETE', dict(id=r['id'], revision=1, confirmed=True)))
        self.assertTrue(self.call('DELETE', dict(id=r['id'], revision=2, confirmed=True))['deleted'])
        self.assertEqual(self.call('GET')['resources'], [])

    def test_all_writes_require_existing_admin_session(self):
        for method in ['POST', 'PUT', 'DELETE']:
            for token in ['', 'forged-token']:
                self.error(401, lambda: self.call(method, self.body, token=token))
        self.error(401, lambda: self.library.settings('PUT', {'title':'실패','revision':1}, '', 'test'))
        self.auth.logout(self.token)
        self.error(401, lambda: self.call('POST', self.body))
        self.assertEqual(self.call('GET')['resources'], [])

    def test_validation_does_not_write(self):
        bad = [('title',''), ('title','x'*81), ('author','x'*41), ('description','x'*301), ('subject','없음'), ('grade','없음'), ('tags','a,b,c,d,e,f'), ('tags',[42]), ('tags',['x'*31])]
        bad += [('url', x) for x in ['javascript:alert(1)','data:text/html,hi','file:///etc/passwd','//example.org','https://user:pass@example.org','https://example.org:bad','https://example.org/space here','https://example.org\\evil']]
        for key, value in bad:
            with self.subTest(key=key, value=value):
                self.error(400, lambda: self.call('POST', dict(self.body, **{key:value})))
        self.assertEqual(self.call('GET')['resources'], [])

    def test_views_atomic_public_and_missing_id(self):
        r = self.call('POST', self.body)['resource']
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda n: self.call('PATCH', {'id':r['id']}, token='', ip=str(n)), range(40)))
        self.assertEqual(sorted(x['resource']['views'] for x in results), list(range(1,41)))
        self.assertEqual(self.call('GET')['resources'][0]['views'], 40)
        self.error(404, lambda: self.call('PATCH', {'id':'missing'}, token=''))
        self.error(400, lambda: self.call('PATCH', {'id':'../bad'}, token=''))

    def test_settings_cas_and_reinitialization_preserves_data(self):
        old = self.library.settings('GET', None, '', 'test')
        new = self.library.settings('PUT', {'title':'변경 제목','revision':old['revision']}, self.token, 'test')
        self.assertEqual(new['revision'], old['revision']+1)
        self.error(409, lambda: self.library.settings('PUT', {'title':'충돌','revision':old['revision']}, self.token, 'test'))
        r = self.call('POST', self.body)['resource']
        again = Library(self.home/'library.sqlite', self.auth)
        self.assertEqual(again.resources('GET',None,'','test')['resources'],[r])
        self.assertEqual(again.settings('GET',None,'','test'),new)
        self.assertEqual(self.auth.status()['operationMode'],'pending')
        self.assertEqual(self.auth.manage(self.token)['totalCount'],0)

    def test_view_rate_limit(self):
        r = self.call('POST', self.body)['resource']
        for _ in range(240): self.call('PATCH', {'id':r['id']}, token='', ip='limited')
        self.error(429, lambda: self.call('PATCH', {'id':r['id']}, token='', ip='limited'))
        self.assertEqual(self.call('GET')['resources'][0]['views'],240)

    def test_http_cors_auth_and_training_regression(self):
        server = make_server(self.home,'127.0.0.1',0)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        def http(path, method='GET', body=None, origin='https://pace33.github.io', token='', extra=None):
            headers={'Origin':origin,'Content-Type':'application/json'}
            if token: headers['Authorization']='Bearer '+token
            if extra: headers.update(extra)
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,method=method,headers=headers,data=None if body is None else json.dumps(body).encode())
            try:r=urllib.request.urlopen(req)
            except urllib.error.HTTPError as error:r=error
            with r:
                raw=r.read();return r.status,r.headers,json.loads(raw) if raw else None
        try:
            self.assertEqual(http('/api/resources')[0],200)
            self.assertEqual(http('/api/resources',origin='https://evil.example')[0],403)
            self.assertEqual(http('/api/resources','POST',self.body)[0],401)
            self.assertEqual(http('/api/settings','PUT',{'title':'x','revision':1})[0],401)
            for method in ['PUT','PATCH','DELETE']:
                status,headers,_=http('/api/resources','OPTIONS',extra={'Access-Control-Request-Method':method,'Access-Control-Request-Headers':'authorization,content-type'})
                self.assertEqual(status,204); self.assertIn(method,headers['Access-Control-Allow-Methods'])
            self.assertEqual(http('/api/resources','OPTIONS',extra={'Access-Control-Request-Method':'TRACE'})[0],403)
            status,headers,data=http('/api/resources','POST',self.body,token=self.token)
            self.assertEqual(status,200); self.assertEqual(headers['Access-Control-Allow-Origin'],'https://pace33.github.io')
            self.assertEqual(http('/api/admin/login',token=self.token)[2],{'authenticated':True})
            self.assertEqual(http('/api/manage',token=self.token)[2]['totalCount'],0)
            health=http('/api/health')[2];self.assertEqual(health['participants'],[]);self.assertIsNone(health['count'])
            self.assertEqual(http('/api/admin/login','POST',{'password':'synthetic-wrong'})[0],401)
            self.assertEqual(http('/api/resources','DELETE',{'id':data['resource']['id'],'revision':1,'confirmed':True},token=self.token)[0],200)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == '__main__': unittest.main()
