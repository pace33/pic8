"""pic8 workshop API. Standard library only; no existing database is reset."""
import contextlib
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import unicodedata
from datetime import datetime
from pathlib import Path

CAPACITY = 20
ANNOUNCEMENT = '2026-11-17T00:00:00+09:00'
ANNOUNCEMENT_TS = datetime.fromisoformat(ANNOUNCEMENT).timestamp()
PIN_RE = re.compile(r'[0-9]{4}\Z')
RESOURCE_RE = re.compile(r'[a-zA-Z0-9_-]{1,100}\Z')


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def text(value, field, maximum, minimum=1):
    if not isinstance(value, str):
        raise ApiError(400, field + ' 형식을 확인해 주세요.')
    value = unicodedata.normalize('NFC', value).strip()
    if not minimum <= len(value) <= maximum or any(unicodedata.category(c).startswith('C') for c in value):
        raise ApiError(400, field + ' 길이와 형식을 확인해 주세요.')
    return value


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 180000).hex()


class Store:
    def __init__(self, path, config, clock=time.time, qa=False):
        self.path, self.config, self.clock, self.qa = Path(path), config, clock, qa
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS participants (
                    receipt_order INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE, region TEXT NOT NULL, school TEXT NOT NULL,
                    full_name TEXT NOT NULL, created_at INTEGER NOT NULL,
                    pin_salt TEXT NOT NULL, pin_hash TEXT NOT NULL,
                    selected_slot INTEGER UNIQUE CHECK(selected_slot BETWEEN 1 AND 20),
                    UNIQUE(region,school,full_name));
                CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS limits (key TEXT PRIMARY KEY, start REAL NOT NULL, hits INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS resource_views (id TEXT PRIMARY KEY, views INTEGER NOT NULL CHECK(views>=0));
            ''')
            db.execute("INSERT OR IGNORE INTO metadata VALUES('active','0')")
        self.path.chmod(0o600)

    @contextlib.contextmanager
    def db(self, write=False):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=15000')
        db.execute('PRAGMA journal_mode=WAL')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def active(self):
        if self.qa:
            return True
        with self.db() as db:
            return db.execute("SELECT value FROM metadata WHERE key='active'").fetchone()[0] == '1'

    def status(self):
        return {'capacity': CAPACITY, 'published': self.clock() >= ANNOUNCEMENT_TS,
                'announcementAt': ANNOUNCEMENT, 'count': None, 'participants': [],
                'readyForCutover': self.active(), 'storage': 'aiedue-project-sqlite'}

    def limit(self, bucket, maximum, seconds):
        key = hmac.new(self.config['pepper'].encode(), bucket.encode(), 'sha256').hexdigest()
        now = self.clock()
        with self.db(True) as db:
            db.execute('DELETE FROM limits WHERE start<?', (now - 86400,))
            row = db.execute('SELECT start,hits FROM limits WHERE key=?', (key,)).fetchone()
            if row and row['start'] + seconds > now:
                if row['hits'] >= maximum:
                    raise ApiError(429, '요청이 많습니다. 잠시 후 다시 시도해 주세요.')
                db.execute('UPDATE limits SET hits=hits+1 WHERE key=?', (key,))
            else:
                db.execute('INSERT INTO limits VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET start=excluded.start,hits=1', (key, now))

    def identity(self, body):
        region = text(body.get('region'), '지역명', 40)
        school = text(body.get('school'), '학교이름', 80)
        name = text(body.get('name'), '성명', 40, 2)
        pin = body.get('pin')
        if not isinstance(pin, str) or not PIN_RE.fullmatch(pin):
            raise ApiError(400, '조회·취소 비밀번호는 숫자 4자리여야 합니다.')
        return region, school, name, pin

    def pin_hash(self, pin, salt):
        keyed = hmac.new(self.config['pepper'].encode(), pin.encode(), 'sha256').hexdigest()
        return password_hash(keyed, salt)

    def participant(self, row):
        selected = row['selected_slot'] is not None
        status = ('selected' if selected else 'not_selected') if self.clock() >= ANNOUNCEMENT_TS else 'received'
        return {'id': row['id'], 'name': row['full_name'][0] + '*' * (len(row['full_name']) - 1),
                'region': row['region'], 'school': row['school'], 'status': status}

    def registration(self, body, ip):
        action = body.get('action')
        if action not in ('register', 'lookup', 'cancel'):
            raise ApiError(400, '지원하지 않는 신청 작업입니다.')
        region, school, name, pin = self.identity(body)
        if not self.active():
            raise ApiError(503, '기존 신청 데이터 이관 확인 중입니다. 기존 신청 페이지를 이용해 주세요.')
        self.limit('requests:' + ip, 240, 600)
        identity = json.dumps([region, school, name], ensure_ascii=False)
        self.limit('identity:' + identity, 12, 600)
        with self.db(True) as db:
            row = db.execute('SELECT * FROM participants WHERE region=? AND school=? AND full_name=?', (region, school, name)).fetchone()
            if action == 'register':
                if row:
                    if not hmac.compare_digest(row['pin_hash'], self.pin_hash(pin, row['pin_salt'])):
                        raise ApiError(409, '이미 접수된 신청입니다. 본인 신청 확인에서 조회해 주세요.')
                    return {'participant': self.participant(row), 'alreadyRegistered': True}
                salt = secrets.token_hex(16)
                ident = secrets.token_urlsafe(18)
                db.execute('INSERT INTO participants(id,region,school,full_name,created_at,pin_salt,pin_hash) VALUES(?,?,?,?,?,?,?)',
                           (ident, region, school, name, int(self.clock() * 1000), salt, self.pin_hash(pin, salt)))
                row = db.execute('SELECT * FROM participants WHERE id=?', (ident,)).fetchone()
                return {'participant': self.participant(row)}
            valid = row is not None
            check_salt = row['pin_salt'] if row else '00' * 16
            check = self.pin_hash(pin, check_salt)
            valid = valid and hmac.compare_digest(check, row['pin_hash'])
            if action == 'cancel' and body.get('id') is not None:
                valid = valid and isinstance(body['id'], str) and body['id'] == row['id']
            if not valid:
                raise ApiError(404, '신청 정보와 비밀번호를 확인해 주세요.')
            if action == 'lookup':
                return {'participant': self.participant(row)}
            db.execute('DELETE FROM participants WHERE id=?', (row['id'],))
            return {'ok': True, 'cancelled': True}

    def login(self, body, ip):
        self.limit('admin:' + ip, 12, 900)
        password = body.get('password')
        if not isinstance(password, str) or not 1 <= len(password) <= 1024:
            raise ApiError(401, '관리자 비밀번호를 확인해 주세요.')
        prefix = 'qa_admin_' if self.qa else 'admin_'
        if not hmac.compare_digest(password_hash(password, self.config[prefix + 'salt']), self.config[prefix + 'hash']):
            raise ApiError(401, '관리자 비밀번호를 확인해 주세요.')
        token = secrets.token_urlsafe(32)
        with self.db(True) as db:
            db.execute('DELETE FROM sessions WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), self.clock() + 8 * 3600))
        return {'accessToken': token}

    def authorize(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            raise ApiError(401, '관리자 로그인이 필요합니다.')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as db:
            row = db.execute('SELECT expires FROM sessions WHERE digest=?', (digest,)).fetchone()
        if not row or row['expires'] <= self.clock():
            raise ApiError(401, '관리자 로그인이 필요합니다.')
        return digest

    def logout(self, token):
        digest = self.authorize(token)
        with self.db(True) as db:
            db.execute('DELETE FROM sessions WHERE digest=?', (digest,))
        return {'ok': True}

    def manage(self, token, body=None):
        self.authorize(token)
        if body is not None:
            ident, selected = body.get('id'), body.get('selected')
            if not isinstance(ident, str) or type(selected) is not bool:
                raise ApiError(400, '선정 요청 형식을 확인해 주세요.')
            with self.db(True) as db:
                row = db.execute('SELECT selected_slot FROM participants WHERE id=?', (ident,)).fetchone()
                if not row:
                    raise ApiError(404, '신청을 찾을 수 없습니다.')
                if selected and row['selected_slot'] is None:
                    used = {r[0] for r in db.execute('SELECT selected_slot FROM participants WHERE selected_slot IS NOT NULL')}
                    free = next((n for n in range(1, CAPACITY + 1) if n not in used), None)
                    if free is None:
                        raise ApiError(409, '참가자는 최대 20명까지 선정할 수 있습니다.')
                    db.execute('UPDATE participants SET selected_slot=? WHERE id=?', (free, ident))
                elif not selected:
                    db.execute('UPDATE participants SET selected_slot=NULL WHERE id=?', (ident,))
        with self.db() as db:
            rows = [dict(r) for r in db.execute('SELECT id,region,school,full_name,created_at,receipt_order,selected_slot FROM participants ORDER BY receipt_order')]
        return {'participants': rows, 'totalCount': len(rows),
                'selectedCount': sum(r['selected_slot'] is not None for r in rows),
                'capacity': CAPACITY, 'readyForCutover': self.active()}

    def delete_registration(self, token, body):
        self.authorize(token)
        ident = body.get('id')
        if not isinstance(ident, str) or not ident.strip() or len(ident) > 80 or body.get('confirmed') is not True:
            raise ApiError(400, '삭제할 신청자와 삭제 확인 여부를 확인해 주세요.')
        with self.db(True) as db:
            row = db.execute('SELECT selected_slot FROM participants WHERE id=?', (ident,)).fetchone()
            if row is None:
                raise ApiError(404, '이미 삭제되었거나 취소된 신청입니다.')
            db.execute('DELETE FROM participants WHERE id=?', (ident,))
        return {'deleted': True, 'wasSelected': row['selected_slot'] is not None}

    def views(self, ident, increment=False, ip='local'):
        if not RESOURCE_RE.fullmatch(ident):
            raise ApiError(400, '잘못된 자료 ID입니다.')
        if increment:
            self.limit('views:' + ip, 180, 60)
        with self.db(increment) as db:
            if increment:
                db.execute('INSERT INTO resource_views VALUES(?,1) ON CONFLICT(id) DO UPDATE SET views=views+1', (ident,))
            row = db.execute('SELECT views FROM resource_views WHERE id=?', (ident,)).fetchone()
        return {'views': row[0] if row else 0}

    def activate(self, confirmed_empty=False, source_writes_stopped=False):
        if source_writes_stopped is not True:
            raise ValueError('Confirm the legacy backend is write-frozen before activation')
        with self.db(True) as db:
            imported = db.execute("SELECT value FROM metadata WHERE key='complete_import'").fetchone()
            count = db.execute('SELECT COUNT(*) FROM participants').fetchone()[0]
            if not imported and not (confirmed_empty and count == 0):
                raise ValueError('Complete legacy export with compatible PINs or explicit empty-source confirmation required')
            db.execute("UPDATE metadata SET value='1' WHERE key='active'")

    def import_records(self, document):
        if document.get('confirmedComplete') is not True or document.get('event') != 'teacher-workshop-jingu-2026':
            raise ValueError('A complete export attestation and the matching event are required')
        rows = document.get('participants')
        if not isinstance(rows, list) or document.get('sourceRowCount') != len(rows):
            raise ValueError('Source row count does not match export')
        prepared = []
        for row in rows:
            region, school, name, pin = self.identity(dict(row, name=row.get('full_name')))
            ident = text(row.get('id'), 'ID', 150)
            order, created, selected = row.get('receipt_order'), row.get('created_at'), row.get('selected_slot')
            if type(order) is not int or order < 1 or type(created) is not int or created < 0 or (selected is not None and (type(selected) is not int or not 1 <= selected <= 20)):
                raise ValueError('Invalid receipt order, timestamp, or selection slot')
            salt = secrets.token_hex(16)
            prepared.append((order, ident, region, school, name, created, salt, self.pin_hash(pin, salt), selected))
        with self.db(True) as db:
            if db.execute("SELECT value FROM metadata WHERE key='active'").fetchone()[0] != '0' or db.execute('SELECT COUNT(*) FROM participants').fetchone()[0] != 0:
                raise ValueError('Refusing to replace active or existing records')
            db.executemany('INSERT INTO participants(receipt_order,id,region,school,full_name,created_at,pin_salt,pin_hash,selected_slot) VALUES(?,?,?,?,?,?,?,?,?)', prepared)
            db.execute("INSERT INTO metadata VALUES('complete_import','1')")
        return {'imported': len(prepared), 'active': False}
