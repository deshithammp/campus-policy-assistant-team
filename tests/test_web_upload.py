import io
import json
import shutil
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from rag import web
from rag.web_admin import set_password
from scripts.make_sample_pdfs import write_pdf


class WebUploadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        shutil.copytree(web.ROOT / 'data/pdfs', self.root / 'data/pdfs')
        root_patch = patch.object(web, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

        self.server = web.ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        self.server.app = web.CampusWeb()
        thread = threading.Thread(target=self.server.serve_forever)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, method, path, data=None, **headers):
        if isinstance(data, dict):
            data = json.dumps(data)
            headers['Content-Type'] = 'application/json'
        headers.setdefault('Origin', self.origin)
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            connection.request(method, path, data, headers)
            response = connection.getresponse()
            body = response.read()
            if response.getheader('Content-Type', '').startswith('application/json'):
                body = json.loads(body)
            return response.status, body, response.getheader('Set-Cookie')
        finally:
            connection.close()

    def test_admin_upload_reindexes_and_serves_cited_page(self):
        login = '/api/admin/login'
        upload = '/api/admin/upload?name=observatory+guide.pdf'
        question = {'question': 'When does the campus observatory close?', 'profile': 'offline'}
        password = 'demo-password-for-test-suite'
        self.assertFalse(self.request('GET', '/api/admin/status')[1]['configured'])
        self.assertEqual(self.request('POST', login, {'username': 'admin', 'password': password})[0], 409)
        set_password(self.server.app.auth.path, password)

        sample = self.root / 'new-source.pdf'
        write_pdf(sample, [
            ('Opening', 'The telescope is located next to the campus garden.'),
            ('Closing', 'The campus observatory closes at eight in the evening during term.'),
        ])
        pdf = sample.read_bytes()
        file_headers = {'Content-Type': 'application/pdf'}
        self.assertEqual(self.request('POST', upload, pdf, **file_headers)[0], 401)
        self.assertEqual(self.request('POST', login, {'username': 'admin', 'password': 'wrong'})[0], 401)
        status, body, cookie = self.request('POST', login, {'username': 'admin', 'password': password})
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        cookie = cookie.split(';', 1)[0]
        admin = {'Cookie': cookie, 'X-CSRF-Token': body['csrf']}
        self.assertEqual(self.request('POST', upload, pdf, Cookie=cookie, **file_headers)[0], 403)
        self.assertEqual(self.request('POST', upload, pdf, Origin='http://other.test', **admin, **file_headers)[0], 403)
        self.assertEqual(self.request('POST', upload, b'not a PDF', **admin, **file_headers)[0], 400)
        self.assertEqual(self.request('POST', '/api/admin/upload?name=../escape.pdf', pdf, **admin, **file_headers)[0], 400)

        self.assertTrue(self.request('POST', '/api/ask', question)[1]['missing'])
        status, body, _ = self.request('POST', upload, pdf, **admin, **file_headers)
        self.assertEqual(status, 201)
        self.assertIn('observatory guide.pdf', [item['name'] for item in body['documents'] if item['uploaded']])
        self.assertEqual(self.request('POST', upload, pdf, **admin, **file_headers)[0], 409)
        self.assertTrue(any(item['uploaded'] for item in web.CampusWeb().document_list()))

        answer = self.request('POST', '/api/ask', question)[1]
        self.assertFalse(answer['missing'])
        claim, = answer['claims']
        self.assertEqual((claim['document'], claim['page']), ('observatory guide.pdf', 2))
        self.assertIn('eight in the evening', claim['quote'])
        status, data, _ = self.request('GET', claim['pageUrl'])
        self.assertEqual(status, 200)
        source_page, = PdfReader(io.BytesIO(data)).pages
        self.assertIn('eight in the evening', source_page.extract_text())
        source_route = '/api/admin/source'
        remove = {'name': claim['document'], 'removed': True}
        self.assertEqual(self.request('GET', '/api/admin/documents')[0], 401)
        self.assertEqual(self.request('POST', source_route, remove)[0], 401)
        self.assertEqual(self.request('POST', source_route, remove, Cookie=cookie)[0], 403)
        self.assertEqual(self.request('POST', source_route, dict(remove, name='../escape.pdf'), **admin)[0], 404)
        status, body, _ = self.request('POST', source_route, remove, **admin)
        self.assertEqual(status, 200)
        self.assertIn(claim['document'], [item['name'] for item in body['documents'] if item['removed']])
        self.assertNotIn(claim['document'], [item['name'] for item in self.request('GET', '/api/options')[1]['documents']])
        self.assertEqual(self.request('GET', claim['pageUrl'])[0], 404)
        self.assertEqual(self.request('GET', claim['documentUrl'])[0], 404)
        self.assertTrue(self.request('POST', '/api/ask', question)[1]['missing'])
        self.assertNotIn(claim['document'], web.CampusWeb().documents())
        self.assertEqual(self.request('POST', upload, pdf, **admin, **file_headers)[0], 409)

        for item in self.request('GET', '/api/options')[1]['documents']:
            self.assertEqual(self.request('POST', source_route, {'name': item['name'], 'removed': True}, **admin)[0], 200)
        self.assertTrue(self.request('POST', '/api/ask', question)[1]['noDocuments'])

        self.assertEqual(self.request('POST', source_route, dict(remove, removed=False), **admin)[0], 200)
        restored, = self.request('POST', '/api/ask', question)[1]['claims']
        self.assertEqual(restored['pageUrl'], claim['pageUrl'])
        self.assertEqual(self.request('GET', restored['pageUrl'])[0], 200)
        self.assertEqual(self.request('POST', '/api/admin/logout', **admin)[0], 200)
        self.assertEqual(self.request('POST', upload, pdf, **admin, **file_headers)[0], 401)
