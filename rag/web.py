"""Serve the Campus Policy Assistant on the local machine."""

import argparse
import errno
import hashlib
import hmac
import io
import json
import os
import sqlite3
import tempfile
import unicodedata
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlencode, urlsplit

from .agent import Agent
from .cli import NSBM_QUESTION, ROOT, components, config, ingest_files
from .ingest import PDFIngestor
from .retrieval import HybridRetriever, VectorStore
from .web_admin import AdminAuth, prompt_for_password


ASSETS = ROOT / 'rag/web_assets'
NSBM_FILES = {'exam-regulations.pdf', 'extenuating-circumstances.pdf', 'repeat-coursework.pdf'}
EXAMPLES = {
    'nsbm': [
        ['Exam room rules', 'Is a mobile phone permitted in the examination room?'],
        ['Repeat coursework', 'How do I register for repeat coursework?'],
        ['Ask a two-part question', NSBM_QUESTION],
    ],
    'sample': [
        ['Repeat a failed module', 'Can I repeat a failed module? How do I register?'],
        ['Repeat registration', 'How do I register for a repeat module?'],
        ['Module withdrawal', 'Can I withdraw from a module without an academic penalty?'],
    ],
}
MAX_QUESTION = 1000
MAX_PDF_BYTES = 20 * 1024**2


def source_url(document, page=None):
    params = {'document': document}
    if page is not None:
        params['page'] = page
    return '/source?' + urlencode(params)


class CampusWeb:
    def __init__(self):
        self.settings = config()
        self.profile = self.settings.get('RAG_PROFILE', 'offline')
        if self.profile not in ('offline', 'ollama'):
            self.profile = 'offline'
        official = ROOT / 'data/nsbm'
        self.corpus = 'nsbm' if all((official / name).is_file() for name in NSBM_FILES) else 'sample'
        self.directory = official if self.corpus == 'nsbm' else ROOT / 'data/pdfs'
        self.uploads = ROOT / 'runtime/uploads'
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.removed_sources = ROOT / 'runtime/removed-sources'
        self.auth = AdminAuth(ROOT / 'runtime/admin.json')
        self.engines = {}
        self.index_lock = Lock()

    def all_documents(self):
        return {
            path.name: path
            for folder in (self.directory, self.uploads)
            for path in sorted(folder.iterdir())
            if path.is_file() and not path.is_symlink() and path.suffix.lower() == '.pdf'
        }

    def documents(self):
        return {name: path for name, path in self.all_documents().items()
                if not (self.removed_sources / name).exists()}

    def document_list(self, include_removed=False):
        items = []
        for name, path in self.all_documents().items():
            removed = (self.removed_sources / name).exists()
            if include_removed or not removed:
                items.append({
                    'name': name, 'url': source_url(name), 'uploaded': path.parent == self.uploads, 'removed': removed,
                })
        return items

    def set_source_removed(self, name, removed):
        with self.index_lock:
            if name not in self.all_documents():
                raise LookupError('Source document not found.')
            marker = self.removed_sources / name
            if removed:
                self.removed_sources.mkdir(exist_ok=True)
                marker.touch()
            else:
                marker.unlink(missing_ok=True)

    def options(self):
        return {
            'corpus': self.corpus, 'profile': self.profile, 'examples': EXAMPLES[self.corpus],
            'documents': self.document_list(),
        }

    def upload(self, name, data):
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        name = unicodedata.normalize('NFC', name.strip())
        if (not name.lower().endswith('.pdf') or name.startswith('.') or len(name.encode()) > 180
                or '/' in name or chr(92) in name or any(unicodedata.category(c).startswith('C') for c in name)):
            raise ValueError('Choose a PDF with a valid filename.')
        if not data.startswith(b'%PDF-'):
            raise ValueError('The selected file is not a PDF.')
        if name.casefold() in {existing.casefold() for existing in self.all_documents()}:
            raise FileExistsError('A PDF with that filename already exists.')
        with tempfile.TemporaryDirectory(dir=self.uploads) as staging:
            candidate = Path(staging) / name
            candidate.write_bytes(data)
            try:
                reader = PdfReader(candidate)
                if reader.is_encrypted:
                    raise ValueError('Remove the PDF password before uploading.')
                if len(reader.pages) > 300:
                    raise ValueError('Upload a PDF with no more than 300 pages.')
                PDFIngestor().chunks(candidate)
            except (PdfReadError, RecursionError) as exc:
                raise ValueError('This PDF could not be read. Try a readable copy.') from exc
            with self.index_lock:
                if name.casefold() in {existing.casefold() for existing in self.all_documents()}:
                    raise FileExistsError('A PDF with that filename already exists.')
                os.link(candidate, self.uploads / name)

    def engine(self, profile):
        with self.index_lock:
            documents = self.documents()
            if not documents:
                return None
            names = tuple(documents)
            cached = self.engines.get(profile)
            if cached is not None and cached[0] == names:
                return cached[1:]
            embedder, synthesizer = components(profile, self.settings)
            fingerprint = hashlib.sha256(embedder.signature.encode())
            for name, path in documents.items():
                fingerprint.update(name.encode())
                fingerprint.update(hashlib.sha256(path.read_bytes()).digest())
            tag = fingerprint.hexdigest()[:16]
            store = VectorStore(ROOT / f'runtime/web-{self.corpus}-{profile}-{tag}.sqlite3')
            try:
                retriever = HybridRetriever(store, embedder)
            except ValueError:
                ingest_files(documents.values(), store, embedder)
                retriever = HybridRetriever(store, embedder)
            agent = Agent(retriever, synthesizer)
            self.engines[profile] = names, agent, store
            return agent, store

    def ask(self, question, profile):
        engine = self.engine(profile)
        if engine is None:
            return {'claims': [], 'missing': [question], 'noDocuments': True}
        agent, store = engine
        result = agent.run(question)
        result.trace.append({'phase': 'Persistence', 'message': 'Saving evidence and answer in SQLite.'})
        store.save_run(result)
        evidence = {hit.chunk.id: hit.chunk for hit in result.evidence}
        claims = []
        for claim in result.claims:
            chunk = evidence[claim.chunk_id]
            claims.append({
                'text': claim.text, 'quote': claim.quote, 'document': chunk.document, 'page': chunk.page,
                'pageUrl': source_url(chunk.document, chunk.page),
                'documentUrl': source_url(chunk.document),
            })
        return {'claims': claims, 'missing': result.missing}

    def pdf(self, document, page_number):
        path = self.documents().get(document)
        if path is None:
            raise LookupError('Source document not found.')
        if page_number is None:
            return path.read_bytes()
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(path)
        if not 1 <= page_number <= len(reader.pages):
            raise LookupError('Source page not found.')
        writer = PdfWriter()
        writer.add_page(reader.pages[page_number - 1])
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    assets = {
        '/': ('index.html', 'text/html; charset=utf-8'),
        '/style.css': ('style.css', 'text/css; charset=utf-8'),
        '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
        '/admin': ('admin.html', 'text/html; charset=utf-8'),
        '/admin.js': ('admin.js', 'text/javascript; charset=utf-8'),
    }

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def send_data(self, data, content_type, status=HTTPStatus.OK, cookie=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data, status=HTTPStatus.OK, cookie=None):
        self.send_data(json.dumps(data).encode(), 'application/json; charset=utf-8', status, cookie)

    def allowed_host(self):
        port = self.server.server_port
        return self.headers.get('Host') in {f'127.0.0.1:{port}', f'localhost:{port}'}

    def do_GET(self):
        if not self.allowed_host():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        target = urlsplit(self.path)
        if target.path in self.assets:
            filename, content_type = self.assets[target.path]
            self.send_data((ASSETS / filename).read_bytes(), content_type)
        elif target.path == '/api/options':
            self.send_json(self.server.app.options())
        elif target.path == '/api/admin/status':
            auth = self.server.app.auth
            csrf = auth.session(auth.token(self.headers.get('Cookie')))
            self.send_json({'configured': auth.path.is_file(), 'csrf': csrf})
        elif target.path == '/api/admin/documents':
            auth = self.server.app.auth
            if auth.session(auth.token(self.headers.get('Cookie'))):
                self.send_json({'documents': self.server.app.document_list(include_removed=True)})
            else:
                self.send_json({'error': 'Sign in as admin to continue.'}, HTTPStatus.UNAUTHORIZED)
        elif target.path == '/source':
            query = parse_qs(target.query, keep_blank_values=True)
            try:
                document = query.get('document', [''])[0]
                page = int(query['page'][0]) if 'page' in query else None
                data = self.server.app.pdf(document, page)
            except (LookupError, ValueError):
                self.send_error(HTTPStatus.NOT_FOUND, 'Source page not found.')
            except ImportError:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, 'Install requirements.txt to preview one page.')
            except (OSError, RuntimeError):
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, 'Source PDF could not be opened.')
            else:
                self.send_data(data, 'application/pdf')
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        host = self.headers.get('Host')
        origin = self.headers.get('Origin')
        if not self.allowed_host() or origin not in (None, f'http://{host}'):
            self.send_json({'error': 'Open the assistant directly on this computer.'}, HTTPStatus.FORBIDDEN)
            return
        target = urlsplit(self.path)
        if target.path in ('/api/admin/login', '/api/admin/logout', '/api/admin/upload', '/api/admin/source'):
            if origin != f'http://{host}':
                self.send_json({'error': 'Use the admin page on this computer.'}, HTTPStatus.FORBIDDEN)
                return
            self.admin_post(target)
            return
        if self.path != '/api/ask':
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_json()
            question = payload.get('question')
            profile = payload.get('profile')
            if not isinstance(question, str) or not 0 < len(question.strip()) <= MAX_QUESTION:
                raise ValueError
            if profile not in ('offline', 'ollama'):
                raise ValueError
        except (ValueError, OSError):
            self.send_json({'error': f'Enter a question of 1–{MAX_QUESTION} characters and select a mode.'},
                           HTTPStatus.BAD_REQUEST)
            return
        try:
            answer = self.server.app.ask(question.strip(), profile)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self.log_error('%s', exc)
            message = ('Could not answer in Ollama mode. Start Ollama and check the configured models, or try Offline.'
                       if profile == 'ollama' else
                       'Could not search the PDFs. Check the source files and the terminal for details.')
            self.send_json({'error': message}, HTTPStatus.SERVICE_UNAVAILABLE)
        else:
            self.send_json(answer)

    def read_data(self, content_type, limit):
        size = int(self.headers.get('Content-Length', '0'))
        if self.headers.get_content_type() != content_type or not 0 < size <= limit:
            raise ValueError('Check the file type and size.')
        data = self.rfile.read(size)
        if len(data) != size:
            raise ValueError('The upload was incomplete.')
        return data

    def read_json(self):
        payload = json.loads(self.read_data('application/json', 8192))
        if not isinstance(payload, dict):
            raise ValueError('Invalid request.')
        return payload

    def admin_post(self, target):
        auth = self.server.app.auth
        token = auth.token(self.headers.get('Cookie'))
        if target.path == '/api/admin/login':
            try:
                payload = self.read_json()
                new_token = auth.login(payload.get('username'), payload.get('password'))
            except FileNotFoundError:
                self.send_json({'error': 'Set the admin password from the terminal first.'}, HTTPStatus.CONFLICT)
            except RuntimeError as exc:
                self.send_json({'error': str(exc)}, HTTPStatus.TOO_MANY_REQUESTS)
            except (ValueError, OSError):
                self.send_json({'error': 'Could not sign in.'}, HTTPStatus.BAD_REQUEST)
            else:
                if new_token is None:
                    self.send_json({'error': 'Incorrect username or password.'}, HTTPStatus.UNAUTHORIZED)
                else:
                    auth.logout(token)
                    self.send_json({'csrf': auth.session(new_token)}, cookie=auth.cookie(new_token))
            return
        csrf = auth.session(token)
        if csrf is None:
            self.send_json({'error': 'Sign in as admin to continue.'}, HTTPStatus.UNAUTHORIZED)
        elif not hmac.compare_digest(csrf.encode(), self.headers.get('X-CSRF-Token', '').encode()):
            self.send_json({'error': 'Reload the admin page and try again.'}, HTTPStatus.FORBIDDEN)
        elif target.path == '/api/admin/logout':
            auth.logout(token)
            self.send_json({}, cookie=auth.cookie(max_age=0))
        elif target.path == '/api/admin/source':
            self.set_source_status()
        else:
            try:
                name = parse_qs(target.query).get('name', [''])[0]
                data = self.read_data('application/pdf', MAX_PDF_BYTES)
                self.server.app.upload(name, data)
            except FileExistsError:
                self.send_json({'error': 'A PDF with that filename already exists.'}, HTTPStatus.CONFLICT)
            except ValueError as exc:
                self.send_json({'error': str(exc)}, HTTPStatus.BAD_REQUEST)
            except OSError as exc:
                self.log_error('%s', exc)
                self.send_json({'error': 'The PDF could not be saved.'}, HTTPStatus.SERVICE_UNAVAILABLE)
            else:
                self.send_json({'documents': self.server.app.document_list(include_removed=True)}, HTTPStatus.CREATED)

    def set_source_status(self):
        try:
            payload = self.read_json()
            name = payload.get('name')
            removed = payload.get('removed')
            if not isinstance(name, str) or not isinstance(removed, bool):
                raise ValueError
            self.server.app.set_source_removed(name, removed)
        except ValueError:
            self.send_json({'error': 'Select a PDF source and try again.'}, HTTPStatus.BAD_REQUEST)
        except LookupError as exc:
            self.send_json({'error': str(exc)}, HTTPStatus.NOT_FOUND)
        except OSError as exc:
            self.log_error('%s', exc)
            self.send_json({'error': 'The source could not be updated.'}, HTTPStatus.SERVICE_UNAVAILABLE)
        else:
            self.send_json({'documents': self.server.app.document_list(include_removed=True)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, help='Local port (defaults to 8765 when free).')
    parser.add_argument('--open', action='store_true', help='Open the assistant in the default browser.')
    parser.add_argument('--set-admin-password', action='store_true', help='Set or reset the local admin password.')
    args = parser.parse_args()
    if args.set_admin_password:
        try:
            prompt_for_password(ROOT / 'runtime/admin.json')
        except (EOFError, KeyboardInterrupt, OSError, ValueError) as exc:
            parser.exit(1, f'Password setup stopped. {exc}\n')
        return
    try:
        try:
            server = ThreadingHTTPServer(('127.0.0.1', 8765 if args.port is None else args.port), Handler)
        except OSError as exc:
            if args.port is not None or exc.errno != errno.EADDRINUSE:
                raise
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        with server:
            server.app = CampusWeb()
            url = f'http://127.0.0.1:{server.server_port}'
            print(f'Campus Policy Assistant is running at {url}', flush=True)
            if args.open:
                webbrowser.open(url)
            server.serve_forever()
    except KeyboardInterrupt:
        print('\nCampus Policy Assistant stopped.')
    except OSError as exc:
        parser.exit(1, f'Could not start the assistant: {exc}\n')


if __name__ == '__main__':
    main()
