import io
import json
import os
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from sleepapp import __version__
from sleepapp import server
from sleepapp.analysis import analysis
from sleepapp.model import VERSION, recommend, research
from sleepapp.server import STATIC, application, hostname, shell_version
from tests.test_model import NOW, phone_plan, sample

WEB = Path(__file__).resolve().parents[1] / 'web'


def request(path='/', method='GET', body=None, raw=None, **extra):
    if raw is None:
        raw = json.dumps(body).encode() if body is not None else b''
    env = {'PATH_INFO': path, 'REQUEST_METHOD': method, 'HTTP_HOST': 'localhost:8000',
           'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)),
           'wsgi.input': io.BytesIO(raw), 'wsgi.url_scheme': 'http', **extra}
    result = {}

    def start(status, headers):
        result.update(status=status, headers=dict(headers), header_list=headers)

    result['body'] = b''.join(application(env, start))
    return result


def body_json(r):
    return json.loads(r['body'])


class StaticAndHeaderTests(unittest.TestCase):
    def test_health(self):
        r = request('/healthz')
        self.assertEqual(r['status'], '200 OK')
        self.assertEqual(body_json(r), {'status': 'ok', 'version': __version__})

    def test_all_assets_with_types(self):
        for path, (_, ctype) in STATIC.items():
            with self.subTest(path=path):
                r = request(path)
                self.assertEqual(r['status'], '200 OK')
                self.assertEqual(r['headers']['Content-Type'], ctype)
                self.assertEqual(int(r['headers']['Content-Length']), len(r['body']))
                self.assertGreater(len(r['body']), 10)

    def test_no_source_or_traversal(self):
        for p in ('/../run.py', '/sleepapp/model.py', '/docs/MODEL.md', '/.env', '/web/app.js',
                  '/%2e%2e/run.py', '/tests/test_model.py', '/api', '/api/'):
            with self.subTest(p=p):
                self.assertEqual(request(p)['status'], '404 Not Found')

    def test_security_headers(self):
        h = request('/')['headers']
        self.assertEqual(h['X-Frame-Options'], 'DENY')
        self.assertEqual(h['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(h['Referrer-Policy'], 'no-referrer')
        self.assertEqual(h['Cross-Origin-Opener-Policy'], 'same-origin')
        self.assertEqual(h['Cache-Control'], 'no-store')
        csp = h['Content-Security-Policy']
        for part in ("default-src 'self'", "script-src 'self'", "object-src 'none'", "frame-ancestors 'none'"):
            self.assertIn(part, csp)
        self.assertNotIn('unsafe-inline', csp)
        self.assertNotIn('Strict-Transport-Security', h)

    def test_hsts_only_over_https(self):
        self.assertIn('Strict-Transport-Security', request('/', **{'wsgi.url_scheme': 'https'})['headers'])
        self.assertIn('Strict-Transport-Security', request('/', HTTP_X_FORWARDED_PROTO='https')['headers'])
        self.assertNotIn('Strict-Transport-Security', request('/', HTTP_X_FORWARDED_PROTO='http')['headers'])

    def test_head_has_headers_without_body(self):
        r = request('/', method='HEAD')
        self.assertEqual(r['status'], '200 OK')
        self.assertEqual(r['body'], b'')
        self.assertGreater(int(r['headers']['Content-Length']), 100)

    def test_method_not_allowed_has_allow_header(self):
        r = request('/', method='POST', body={})
        self.assertEqual(r['status'], '405 Method Not Allowed')
        self.assertEqual(r['headers']['Allow'], 'GET, HEAD')
        r = request('/api/summary')
        self.assertEqual(r['status'], '405 Method Not Allowed')
        self.assertEqual(r['headers']['Allow'], 'POST')
        self.assertEqual(request('/healthz', method='DELETE')['status'], '405 Method Not Allowed')

    def test_allowed_hosts(self):
        with patch.dict(os.environ, {'RHYTHM_ALLOWED_HOSTS': 'rhythm.example.org, localhost'}):
            self.assertEqual(request('/')['status'], '200 OK')
            self.assertEqual(request('/', HTTP_HOST='RHYTHM.example.org')['status'], '200 OK')
            self.assertEqual(request('/', HTTP_HOST='evil.example')['status'], '400 Bad Request')
            self.assertEqual(request('/api/summary', 'POST', {}, HTTP_HOST='evil.example')['status'], '400 Bad Request')
            # platform health probes may use an internal host name
            self.assertEqual(request('/healthz', HTTP_HOST='10.0.0.7:10000')['status'], '200 OK')
        with patch.dict(os.environ, {'RHYTHM_ALLOWED_HOSTS': '[::1]'}):
            self.assertEqual(request('/', HTTP_HOST='[::1]:8000')['status'], '200 OK')

    def test_hostname_helper(self):
        self.assertEqual(hostname('LocalHost:8000'), 'localhost')
        self.assertEqual(hostname('[::1]:8000'), '[::1]')
        self.assertEqual(hostname('example.org'), 'example.org')


class APITests(unittest.TestCase):
    def test_invalid_json(self):
        self.assertEqual(request('/api/recommend', 'POST', raw=b'bad')['status'], '400 Bad Request')

    def test_nan_and_infinity_rejected(self):
        for raw in (b'{"profile":{"age_group":NaN}}', b'{"x":Infinity}', b'{"x":-Infinity}'):
            with self.subTest(raw=raw):
                self.assertEqual(request('/api/summary', 'POST', raw=raw)['status'], '400 Bad Request')

    def test_non_utf8_rejected(self):
        self.assertEqual(request('/api/summary', 'POST', raw=b'\xff\xfe{}')['status'], '400 Bad Request')

    def test_deep_nesting_rejected_not_crash(self):
        raw = b'[' * 100000 + b']' * 100000
        self.assertEqual(request('/api/summary', 'POST', raw=raw)['status'], '400 Bad Request')

    def test_cross_origin_blocked(self):
        self.assertEqual(request('/api/summary', 'POST', {}, HTTP_ORIGIN='https://other.example')['status'], '403 Forbidden')
        self.assertEqual(request('/api/summary', 'POST', {}, HTTP_ORIGIN='null')['status'], '403 Forbidden')
        self.assertEqual(request('/api/summary', 'POST', {}, HTTP_SEC_FETCH_SITE='cross-site')['status'], '403 Forbidden')

    def test_same_origin_allowed(self):
        self.assertEqual(request('/api/summary', 'POST', {}, HTTP_ORIGIN='http://localhost:8000')['status'], '200 OK')
        self.assertEqual(request('/api/summary', 'POST', {}, HTTP_ORIGIN='http://LOCALHOST:8000')['status'], '200 OK')
        self.assertEqual(request('/api/summary', 'POST', {}, HTTP_SEC_FETCH_SITE='same-origin')['status'], '200 OK')

    def test_json_content_type_required(self):
        self.assertEqual(request('/api/summary', 'POST', {}, CONTENT_TYPE='text/plain')['status'], '415 Unsupported Media Type')
        self.assertEqual(request('/api/summary', 'POST', {}, CONTENT_TYPE='application/json; charset=utf-8')['status'], '200 OK')

    def test_length_rules(self):
        self.assertEqual(request('/api/summary', 'POST', {}, CONTENT_LENGTH='')['status'], '411 Length Required')
        self.assertEqual(request('/api/summary', 'POST', {}, CONTENT_LENGTH='abc')['status'], '411 Length Required')
        self.assertEqual(request('/api/summary', 'POST', {}, CONTENT_LENGTH='524289')['status'], '413 Content Too Large')
        self.assertEqual(request('/api/summary', 'POST', raw=b'{}', CONTENT_LENGTH='10')['status'], '400 Bad Request')

    def test_body_at_limit_is_read(self):
        raw = b'{"pad":"' + b'a' * (524288 - 10) + b'"}'
        self.assertEqual(len(raw), 524288)
        self.assertEqual(request('/api/summary', 'POST', raw=raw)['status'], '200 OK')

    def test_unknown_api(self):
        self.assertEqual(request('/api/delete-everything', 'POST', {})['status'], '404 Not Found')

    def test_validate_normalizes_records(self):
        d = sample()
        d['records'] = d['records'][:1]
        r = request('/api/validate', 'POST', d)
        self.assertEqual(r['status'], '200 OK')
        out = body_json(r)
        self.assertTrue(out['valid'])
        self.assertIn('+00:00', out['records'][0]['start'])
        self.assertEqual(out['profile']['age_group'], 'teen')

    def test_validation_error_is_user_message(self):
        d = sample()
        first = d['records'][0]
        d['records'].append({'id': 'nap', 'start': first['start'], 'end': first['end'][:11] + '06:00+09:00', 'kind': 'nap'})
        r = request('/api/validate', 'POST', d)
        self.assertEqual(r['status'], '400 Bad Request')
        self.assertIn('겹치는', body_json(r)['error'])

    def test_bad_shapes_are_400_not_500(self):
        bodies = ([], None, 'hello', 3, {'profile': []}, {'records': [None]}, {'profile': {'age_group': []}},
                  {'records': 'x'}, {'observations': [{}]}, {'schema_version': True},
                  {'profile': {'timezone': '../../etc/passwd'}}, {'profile': {'timezone': 'A' * 500}})
        for b in bodies:
            for path in ('/api/recommend', '/api/research', '/api/summary', '/api/validate', '/api/analysis'):
                with self.subTest(b=b, path=path):
                    self.assertEqual(request(path, 'POST', raw=json.dumps(b).encode())['status'], '400 Bad Request')
        for plan in ([], None, {}, {'wake': 5}, {'earliest': '2026-10-10T21:00'}):
            with self.subTest(plan=plan):
                d = sample()
                d['plan'] = plan
                self.assertEqual(request('/api/recommend', 'POST', d)['status'], '400 Bad Request')
                self.assertEqual(request('/api/summary', 'POST', d)['status'], '200 OK')  # plan is not used there

    def test_recommend_research_and_analysis_through_api(self):
        fixed = {'/api/recommend': lambda p: recommend(p, NOW), '/api/research': lambda p: research(p, NOW),
                 '/api/analysis': lambda p: analysis(p, NOW)}
        with patch.dict(server.API, fixed):
            for payload in (sample(), phone_plan(sample(), periods=[('09:00', '09:50'), ('13:50', '14:40')])):
                r = request('/api/recommend', 'POST', payload)
                self.assertEqual(r['status'], '200 OK')
                out = body_json(r)
                self.assertEqual(out['model_version'], VERSION)
                self.assertIn(out['status'], ('ready', 'partial'))
                self.assertEqual(len(out['chart']), 97)
            self.assertEqual(len(out['targets']), 2)
            self.assertTrue(out['auto_range'])
            r = request('/api/research', 'POST', sample())
            self.assertEqual(r['status'], '200 OK')
            self.assertIn('metrics', body_json(r))
            r = request('/api/analysis', 'POST', sample())
            self.assertEqual(r['status'], '200 OK')
            out = body_json(r)
            self.assertEqual(out['status'], 'ready')
            self.assertTrue(all({'tone', 'title', 'text'} <= set(c) for c in out['comments']))

    def test_analysis_is_registered(self):
        self.assertIs(server.API['/api/analysis'], analysis)
        r = request('/api/analysis', 'POST', {'schema_version': 1, 'profile': {}, 'records': [], 'observations': []})
        self.assertEqual((r['status'], body_json(r)['status']), ('200 OK', 'empty'))

    def test_internal_error_is_generic_and_does_not_echo_input(self):
        def boom(payload):
            raise RuntimeError('secret ' + json.dumps(payload))

        log = io.StringIO()
        with patch.dict(server.API, {'/api/summary': boom}), patch('sys.stderr', log):
            r = request('/api/summary', 'POST', {'note': 'PRIVATE-SLEEP-DATA'})
        self.assertEqual(r['status'], '500 Internal Server Error')
        self.assertNotIn(b'PRIVATE-SLEEP-DATA', r['body'])
        self.assertIn('RuntimeError at test_server.py:', log.getvalue())  # operators see where, not what
        self.assertNotIn('PRIVATE-SLEEP-DATA', log.getvalue())
        self.assertNotIn(b'Traceback', r['body'])
        self.assertIn(__version__, body_json(r)['error'])

    def test_request_does_not_write_files(self):
        with patch('builtins.open', side_effect=AssertionError('no writes')):
            self.assertEqual(request('/api/summary', 'POST', sample())['status'], '200 OK')


class MarkupTests(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / 'index.html').read_text(encoding='utf-8')
        self.js = (WEB / 'app.js').read_text(encoding='utf-8')

    def test_ids_unique_and_every_js_reference_exists(self):
        ids = re.findall(r'\bid="([^"]+)"', self.html)
        self.assertEqual(len(ids), len(set(ids)))
        refs = set(re.findall(r"\$\('([^']+)'\)", self.js))
        refs |= set(re.findall(r"\$\(([a-z]+)\)", self.js)) - {'id', 'k'}
        self.assertTrue(refs)
        for target in refs:
            self.assertIn(target, ids)
        for tab in re.findall(r'data-tab="([a-z]+)"', self.html):  # navigate() shows 'tab-' + name
            self.assertIn(f'tab-{tab}', ids)

    def test_phone_home_order_and_intro_buttons(self):
        # calculate button, record status, focus periods, sleep button, then the wake-up time
        order = [self.html.index(marker) for marker in
                 ('id="calc-button"', 'id="status-title"', 'id="focus-title"', 'id="sleep-button"', 'id="wake-time"')]
        self.assertEqual(order, sorted(order))
        intro = self.html[self.html.index('id="intro-dialog"'):]
        self.assertIn('>닫기</button>', intro)
        self.assertIn('>이 창 재접속까지 보지 않기</button>', intro)
        self.assertIn('좋은 수면의 시작은', intro)
        self.assertIn('sessionStorage.setItem(INTRO_HIDDEN', self.js)  # hidden until the app is reopened
        self.assertNotIn('localStorage.setItem(INTRO_HIDDEN', self.js)
        for label in ('홈', '기록', '분석', '계산 근거', '설정'):
            self.assertIn(f'<span>{label}</span></button>', self.html)

    def test_no_inline_handlers_or_styles(self):
        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                for k, _ in attrs:
                    if k.startswith('on') or k == 'style':
                        raise AssertionError('inline handler/style violates CSP')
                if tag == 'script' and not dict(attrs).get('src'):
                    raise AssertionError('inline script violates CSP')

        Parser().feed(self.html)
        self.assertNotRegex(self.js, r'\sstyle=|\.style\.|onclick=')

    def test_labels_point_to_controls(self):
        ids = set(re.findall(r'\bid="([^"]+)"', self.html))
        for target in re.findall(r'<label for="([^"]+)"', self.html):
            self.assertIn(target, ids)
        for control in re.findall(r'<(?:input|select)\b[^>]*\bid="([^"]+)"', self.html):
            if control == 'import-file':
                continue
            self.assertRegex(self.html, rf'for="{control}"|aria-label', control)

    def test_external_links_are_safe(self):
        for tag in re.findall(r'<a [^>]*target="_blank"[^>]*>', self.html):
            self.assertIn('noopener', tag)
            self.assertIn('noreferrer', tag)

    def test_manifest_assets(self):
        m = json.loads((WEB / 'manifest.webmanifest').read_text(encoding='utf-8'))
        self.assertEqual(m['start_url'], '/')
        for icon in m['icons']:
            self.assertTrue((WEB / icon['src'].lstrip('/')).exists())

    def test_service_worker_scope(self):
        s = (WEB / 'sw.js').read_text(encoding='utf-8')
        self.assertIn("e.request.method !== 'GET'", s)
        self.assertIn('!SHELL.includes(u.pathname)', s)
        shell = re.search(r'const SHELL = \[(.*?)\]', s).group(1)
        for path in re.findall(r"'([^']+)'", shell):
            self.assertIn(path, STATIC)
            self.assertFalse(path.startswith('/api'))
        for path in set(STATIC) - {'/sw.js'}:  # the worker script itself is never served from cache
            self.assertIn(f"'{path}'", shell)

    def test_service_worker_gets_shell_hash(self):
        body = request('/sw.js')['body'].decode()
        self.assertNotIn('__SHELL_VERSION__', body)
        self.assertIn(f"const CACHE = 'rhythm-shell-{shell_version()}';", body)
        self.assertRegex(shell_version(), r'^[0-9a-f]{12}$')
        real = shell_version()
        original = Path.read_bytes
        with patch.object(Path, 'read_bytes', lambda self: original(self) + (b'/* edit */' if self.name == 'app.js' else b'')):
            self.assertNotEqual(shell_version(), real)  # editing any shell file changes the worker

    def test_no_sources_in_the_app(self):
        self.assertNotIn('출처', self.html)
        self.assertNotIn('<a ', self.html)  # no reference links left in the page
        for word in ('CDC', 'AASM', 'Hong', 'Wittmann', 'doi.org'):
            self.assertNotIn(word, self.html)
            self.assertNotIn(word, self.js)
        self.assertNotIn('source-list', (WEB / 'style.css').read_text(encoding='utf-8'))

    def test_timetable_tools_and_unsaved_notes(self):
        settings = self.html[self.html.index('id="tab-settings"'):]
        for marker in ('id="add-period"', 'id="remove-period"', 'id="timetable-dirty"', 'id="profile-dirty"', 'id="period-limit"'):
            self.assertIn(marker, settings)
        self.assertIn('교시 추가하기', settings)
        self.assertIn('id="obs-last"', self.html)

    def test_versions_agree(self):
        self.assertIn(f'v{__version__.rsplit(".", 1)[0]}', self.html)
        self.assertTrue(VERSION.endswith(__version__.rsplit('.', 1)[0]))


if __name__ == '__main__':
    unittest.main()
