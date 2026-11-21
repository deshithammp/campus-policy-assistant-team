"""Password and browser sessions for the local admin console."""

import getpass
import hashlib
import hmac
import json
import os
import secrets
import tempfile
from http.cookies import CookieError, SimpleCookie
from threading import Lock
from time import monotonic


COOKIE = 'campus_admin'
USER = 'admin'
SESSION_SECONDS = 8 * 60 * 60


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=3, maxmem=64 * 1024**2).hex()


def set_password(path, password):
    if not 12 <= len(password) <= 256 or not password.strip():
        raise ValueError('Use a password between 12 and 256 characters.')
    salt = secrets.token_bytes(16)
    record = {'salt': salt.hex(), 'hash': password_hash(password, salt)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as file:
        temporary = file.name
        json.dump(record, file)
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prompt_for_password(path):
    password = getpass.getpass('New admin password (at least 12 characters): ')
    if password != getpass.getpass('Confirm admin password: '):
        raise ValueError('Passwords did not match.')
    set_password(path, password)
    print('Admin password saved. Sign in with username: admin')


class AdminAuth:
    def __init__(self, path):
        self.path = path
        self.sessions = {}
        self.failures = []
        self.lock = Lock()

    def login(self, username, password):
        with self.lock:
            now = monotonic()
            self.failures = [attempt for attempt in self.failures if now - attempt < 60]
            if len(self.failures) >= 5:
                raise RuntimeError('Too many sign-in attempts. Try again in one minute.')
            record = json.loads(self.path.read_text())
            if (username != USER or not isinstance(password, str) or len(password) > 256
                    or not hmac.compare_digest(password_hash(password, bytes.fromhex(record['salt'])), record['hash'])):
                self.failures.append(now)
                return None
            self.failures.clear()
            self.sessions = {key: value for key, value in self.sessions.items() if value[0] > now}
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            self.sessions[token] = (now + SESSION_SECONDS, record['hash'], csrf)
            return token

    @staticmethod
    def cookie(token='', max_age=SESSION_SECONDS):
        return f'{COOKIE}={token}; Path=/api/admin; HttpOnly; SameSite=Strict; Max-Age={max_age}'

    @staticmethod
    def token(header):
        try:
            morsel = SimpleCookie(header or '').get(COOKIE)
            return morsel.value if morsel else None
        except CookieError:
            return None

    def session(self, token):
        with self.lock:
            session = self.sessions.get(token)
            if session and self.path.is_file():
                expiry, digest, csrf = session
                if expiry > monotonic() and digest == json.loads(self.path.read_text())['hash']:
                    return csrf
            self.sessions.pop(token, None)
            return None

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token, None)
