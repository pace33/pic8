"""Separate, non-importing learning library storage. Mutations require existing admin auth."""
import json
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit
from core import Store, ApiError, text, RESOURCE_RE

SUBJECTS = ('국어', '수학', '사회', '과학', '영어', '예술', '창의·코딩', '기타')
GRADES = ('전 학년', '초등 저학년', '초등 고학년', '중학교', '고등학교', '교사용')
DEFAULT_TITLE = '이은학교 학습 자료방'
FIELDS = ('id', 'title', 'url', 'author', 'description', 'subject', 'grade', 'tags', 'views', 'createdBy', 'createdAt', 'revision')


class Library:
    # Reuse connection/transaction implementation, not training's schema or data.
    db = Store.db

    def __init__(self, path, auth):
        self.path, self.auth = path, auth
        with self.db(True) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS resources (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                    author TEXT NOT NULL, description TEXT NOT NULL,
                    subject TEXT NOT NULL, grade TEXT NOT NULL, tags TEXT NOT NULL,
                    views INTEGER NOT NULL DEFAULT 0 CHECK(views>=0),
                    createdBy TEXT NOT NULL, createdAt TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS settings (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    title TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
            ''')
            db.execute('INSERT OR IGNORE INTO settings(singleton,title) VALUES(1,?)', (DEFAULT_TITLE,))
        self.path.chmod(0o600)

    def ident(self, body):
        ident = body.get('id')
        if not isinstance(ident, str) or not RESOURCE_RE.fullmatch(ident):
            raise ApiError(400, '자료 ID를 확인해 주세요.')
        return ident

    def revision(self, body):
        revision = body.get('revision')
        if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
            raise ApiError(400, '변경 버전을 확인해 주세요. 새로고침 후 다시 시도해 주세요.')
        return revision

    def payload(self, body):
        title = text(body.get('title'), '자료 이름', 80)
        author = text(body.get('author'), '작성자', 40)
        url = text(body.get('url'), '웹 주소', 2048)
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password and parsed.port != 0
        except ValueError:
            valid = False
        if not valid or re.search(r'[\s\\]', url):
            raise ApiError(400, 'http 또는 https 웹 주소를 입력해 주세요.')
        description = body.get('description', '')
        if not isinstance(description, str) or len(description) > 300 or any(unicodedata.category(c).startswith('C') and c not in '\n\r\t' for c in description):
            raise ApiError(400, '설명은 300자 이내로 입력해 주세요.')
        subject, grade = body.get('subject', '기타'), body.get('grade', '전 학년')
        if subject not in SUBJECTS or grade not in GRADES:
            raise ApiError(400, '과목과 추천 학년을 확인해 주세요.')
        tags = body.get('tags', '')
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',') if t.strip()]
        if not isinstance(tags, list) or len(tags) > 5:
            raise ApiError(400, '태그는 최대 5개까지 입력해 주세요.')
        tags = list(dict.fromkeys(text(t, '태그', 30) for t in tags))
        return (title, url, author, description.strip(), subject, grade, json.dumps(tags, ensure_ascii=False))

    def public(self, row):
        return {key: row[key] for key in FIELDS}

    def resources(self, method, body, token, ip):
        if method == 'GET':
            with self.db() as db:
                return {'resources': [self.public(r) for r in db.execute('SELECT * FROM resources ORDER BY createdAt DESC,id DESC')]}
        if method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
            raise ApiError(405, '지원하지 않는 자료 작업입니다.')
        if method != 'PATCH':
            self.auth.authorize(token)
            self.auth.limit('library-write:' + ip, 120, 600)
        else:
            self.auth.limit('library-view:' + ip, 240, 600)
        ident = secrets.token_urlsafe(18) if method == 'POST' else self.ident(body)
        payload = self.payload(body) if method in ('POST', 'PUT') else None
        revision = self.revision(body) if method in ('PUT', 'DELETE') else None
        with self.db(True) as db:
            if method != 'POST':
                row = db.execute('SELECT * FROM resources WHERE id=?', (ident,)).fetchone()
                if row is None:
                    raise ApiError(404, '자료를 찾을 수 없습니다.')
                if revision is not None and row['revision'] != revision:
                    raise ApiError(409, '다른 창에서 자료가 변경되었습니다. 새로고침 후 확인해 주세요.')
            if method == 'POST':
                created = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
                db.execute('INSERT INTO resources(id,title,url,author,description,subject,grade,tags,createdBy,createdAt) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (ident, *payload, 'aiedue-admin', created))
            elif method == 'PUT':
                db.execute('UPDATE resources SET title=?,url=?,author=?,description=?,subject=?,grade=?,tags=?,revision=revision+1 WHERE id=?', (*payload, ident))
            elif method == 'DELETE':
                if body.get('confirmed') is not True:
                    raise ApiError(400, '삭제 확인이 필요합니다.')
                db.execute('DELETE FROM resources WHERE id=?', (ident,))
                return {'deleted': True, 'id': ident}
            else:
                db.execute('UPDATE resources SET views=views+1 WHERE id=?', (ident,))
            return {'resource': self.public(db.execute('SELECT * FROM resources WHERE id=?', (ident,)).fetchone())}

    def settings(self, method, body, token, ip):
        if method == 'PUT':
            self.auth.authorize(token)
            self.auth.limit('library-settings:' + ip, 60, 600)
            title, revision = text(body.get('title'), '사이트 제목', 30), self.revision(body)
            with self.db(True) as db:
                changed = db.execute('UPDATE settings SET title=?,revision=revision+1 WHERE singleton=1 AND revision=?', (title, revision)).rowcount
                if not changed:
                    raise ApiError(409, '다른 창에서 제목이 변경되었습니다. 새로고침 후 확인해 주세요.')
        elif method != 'GET':
            raise ApiError(405, '지원하지 않는 제목 작업입니다.')
        with self.db() as db:
            return dict(db.execute('SELECT title,revision FROM settings WHERE singleton=1').fetchone())
