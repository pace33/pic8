#!/usr/bin/env python3
"""Loopback-only HTTP adapter. Production cutover is an explicit local operation."""
import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from core import ApiError, Store, password_hash
from library import Library


def initialize(home, origins):
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home.chmod(0o700)
    config_path = home / 'config.json'
    if config_path.exists():
        return json.loads(config_path.read_text(encoding='utf-8'))
    password, qa_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    salt, qa_salt = secrets.token_hex(16), secrets.token_hex(16)
    config = {'origins': origins, 'pepper': secrets.token_hex(32),
              'admin_salt': salt, 'admin_hash': password_hash(password, salt),
              'qa_admin_salt': qa_salt, 'qa_admin_hash': password_hash(qa_password, qa_salt),
              'qa_admin_password': qa_password, 'qa_token': secrets.token_urlsafe(32), 'qa_enabled': False}
    with config_path.open('x', encoding='utf-8') as file:
        json.dump(config, file, indent=2)
    config_path.chmod(0o600)
    with (home / 'admin-password.txt').open('x', encoding='utf-8') as file:
        file.write(password + '\n')
    (home / 'admin-password.txt').chmod(0o600)
    return config


def make_server(home, host, port):
    if host not in ('127.0.0.1', '::1'):
        raise ValueError('The service must bind loopback only')
    config = json.loads((home / 'config.json').read_text(encoding='utf-8'))
    production = Store(home / 'registrations.sqlite', config)
    qa = Store(home / 'qa.sqlite', config, qa=True) if config.get('qa_enabled') else None
    library = Library(home / 'library.sqlite', production)
    qa_library = Library(home / 'qa-library.sqlite', qa) if qa else None

    class Handler(BaseHTTPRequestHandler):
        server_version = 'Pic8API'

        def log_message(self, *_):
            pass  # Never log credentials, names, PINs, headers or query strings.

        def reply(self, status, data=None, scope='production'):
            body = b'' if data is None else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            origin = self.headers.get('Origin')
            if origin in config['origins']:
                self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Pic8-Data-Scope', scope)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            if self.command == 'OPTIONS' and status == 204:
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Pic8-QA')
                self.send_header('Access-Control-Max-Age', '300')
            self.end_headers()
            if body:
                self.wfile.write(body)

        def read_body(self):
            if self.headers.get_content_type() != 'application/json':
                raise ApiError(415, 'JSON 형식으로 요청해 주세요.')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise ApiError(400, '잘못된 요청 길이입니다.')
            maximum = 32768 if urlsplit(self.path).path == '/api/admin/password' else 8192
            if not 0 < length <= maximum:
                raise ApiError(413, '요청 크기를 확인해 주세요.')
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                raise ApiError(400, 'JSON 형식을 확인해 주세요.')
            if not isinstance(body, dict):
                raise ApiError(400, 'JSON 객체로 요청해 주세요.')
            return body

        def dispatch(self):
            scope = 'production'
            try:
                origin = self.headers.get('Origin')
                if origin is not None and origin not in config['origins']:
                    raise ApiError(403, '허용되지 않은 출처입니다.')
                path = unquote(urlsplit(self.path).path)
                if not path.startswith('/api/'):
                    raise ApiError(404, '경로를 찾을 수 없습니다.')
                method = self.command
                if path == '/api/admin/password':
                    if not origin:
                        raise ApiError(403, '출처를 확인해 주세요.')
                    if self.headers.get('X-Pic8-QA') is not None:
                        raise ApiError(403, '시험 인증으로 공통 관리자 비밀번호를 변경할 수 없습니다.')
                if method == 'OPTIONS':
                    if not origin:
                        raise ApiError(403, '출처를 확인해 주세요.')
                    requested = self.headers.get('Access-Control-Request-Method', 'GET')
                    headers = {h.strip().lower() for h in self.headers.get('Access-Control-Request-Headers', '').split(',') if h.strip()}
                    allowed = ('POST',) if path == '/api/admin/password' else ('GET', 'POST', 'PUT', 'PATCH', 'DELETE') if path == '/api/resources' else ('GET', 'PUT') if path == '/api/settings' else ('GET', 'POST', 'DELETE')
                    if requested not in allowed or not headers <= {'content-type', 'authorization', 'x-pic8-qa'}:
                        raise ApiError(403, '허용되지 않은 사전 요청입니다.')
                    self.reply(204)
                    return
                store = production
                qa_token = self.headers.get('X-Pic8-QA')
                if qa_token is not None:
                    if not qa or not hmac.compare_digest(qa_token, config['qa_token']):
                        raise ApiError(404, '경로를 찾을 수 없습니다.')
                    store, scope = qa, 'qa'
                # Only the scoped Caddy route sets this header; the service is loopback bound.
                ip = self.headers.get('X-Pic8-Client-IP', self.client_address[0])
                try:
                    ip = str(ipaddress.ip_address(ip))
                except ValueError:
                    ip = self.client_address[0]
                authorization = self.headers.get('Authorization', '')
                token = authorization[7:] if authorization.startswith('Bearer ') else ''
                if path == '/api/resources':
                    target = qa_library if scope == 'qa' else library
                    if method not in ('GET', 'PATCH'):
                        store.authorize(token)
                    result = target.resources(method, self.read_body() if method != 'GET' else None, token, ip)
                elif path == '/api/settings':
                    target = qa_library if scope == 'qa' else library
                    if method != 'GET':
                        store.authorize(token)
                    result = target.settings(method, self.read_body() if method != 'GET' else None, token, ip)
                elif path in ('/api/health', '/api/registrations') and method == 'GET':
                    result = store.status()
                    if path.endswith('/health'):
                        result.update(ok=True, service='pic8-training')
                elif path == '/api/registrations' and method == 'POST':
                    result = store.registration(self.read_body(), ip)
                elif path == '/api/admin/password' and method == 'POST':
                    result = production.change_password(self.read_body(), ip)
                elif path == '/api/admin/login' and method == 'POST':
                    result = store.login(self.read_body(), ip)
                elif path == '/api/admin/login' and method == 'GET':
                    store.authorize(token)
                    result = {'authenticated': True}
                elif path == '/api/admin/login' and method == 'DELETE':
                    result = store.logout(token)
                elif path == '/api/manage' and method == 'DELETE':
                    store.authorize(token)
                    result = store.delete_registration(token, self.read_body())
                elif path == '/api/manage' and method in ('GET', 'POST'):
                    store.authorize(token)
                    result = store.manage(token, self.read_body() if method == 'POST' else None)
                elif path.startswith('/api/resource-views/') and method in ('GET', 'POST'):
                    if method == 'POST':
                        self.read_body()
                    result = store.views(path[len('/api/resource-views/'):], method == 'POST', ip)
                else:
                    raise ApiError(404, '경로를 찾을 수 없습니다.')
                self.reply(200, result, scope)
            except ApiError as error:
                self.reply(error.status, {'error': error.message}, scope)
            except Exception:
                self.reply(500, {'error': '처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'}, scope)

        do_GET = dispatch
        do_POST = dispatch
        do_PUT = dispatch
        do_PATCH = dispatch
        do_DELETE = dispatch
        do_OPTIONS = dispatch

    return ThreadingHTTPServer((host, port), Handler)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--port', type=int, default=9058)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('command', choices=['serve', 'init', 'status', 'import', 'activate', 'fresh-start', 'backup', 'set-password'])
    parser.add_argument('--input', type=Path)
    parser.add_argument('--confirmed-empty', action='store_true')
    parser.add_argument('--legacy-writes-stopped', action='store_true')
    parser.add_argument('--user-authorized-fresh-start', action='store_true')
    args = parser.parse_args()
    if args.command == 'fresh-start':
        if not args.user_authorized_fresh_start or args.confirmed_empty or args.legacy_writes_stopped:
            parser.error('fresh-start requires --user-authorized-fresh-start, not legacy empty/write-freeze flags')
    elif args.user_authorized_fresh_start:
        parser.error('--user-authorized-fresh-start is only valid with fresh-start')
    origins = ['https://pace33.github.io', 'https://aiedue.ddns.net',
               'https://learning-webapp-library.lejinku.chatgpt.site']
    if args.command == 'init':
        initialize(args.home, origins)
        print(json.dumps({'initialized': True, 'active': False, 'passwordStoredPrivately': True}))
        return
    config_path = args.home / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if args.command == 'serve':
        server = make_server(args.home, args.host, args.port)
        print(json.dumps({'service': 'pic8-training', 'listen': args.host, 'port': server.server_port}), flush=True)
        server.serve_forever()
        return
    store = Store(args.home / 'registrations.sqlite', config)
    if args.command == 'status':
        print(json.dumps(store.status()))
    elif args.command == 'fresh-start':
        store.fresh_start(user_authorized=args.user_authorized_fresh_start)
        print(json.dumps(store.status()))
    elif args.command == 'activate':
        store.activate(args.confirmed_empty, args.legacy_writes_stopped)
        print(json.dumps({'active': True}))
    elif args.command == 'import':
        if args.input is None:
            parser.error('--input is required')
        print(json.dumps(store.import_records(json.loads(args.input.read_text(encoding='utf-8')))))
    elif args.command == 'backup':
        if args.input is None or args.input.exists():
            parser.error('--input must name a new private backup file')
        import sqlite3
        with store.db() as source:
            destination = sqlite3.connect(args.input)
            try:
                source.backup(destination)
            finally:
                destination.close()
        args.input.chmod(0o600)
        print(json.dumps({'backedUp': True}))
    elif args.command == 'set-password':
        import getpass
        password = getpass.getpass('New administrator password: ')
        if not 4 <= len(password) <= 1024:
            raise ValueError('Use between 4 and 1024 characters')
        if getpass.getpass('Repeat password: ') != password:
            raise ValueError('Passwords do not match')
        store.validate_new_password(password, password)
        with store.auth_guard():
            store.persist_password(password)
        print(json.dumps({'passwordChanged': True, 'restartRequired': False}))


if __name__ == '__main__':
    main()
