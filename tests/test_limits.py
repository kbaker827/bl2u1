import io

import app as app_module
from conftest import build_3mf, plate
from limits import RateLimiter, folder_size


def _upload(client):
    payload = {'file': (io.BytesIO(build_3mf(slice_info=plate([1]))), 'm.3mf')}
    return client.post('/analyze', data=payload, content_type='multipart/form-data')


def test_rate_limiter_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr('limits.time.monotonic', lambda: clock[0])
    limiter = RateLimiter(2, window=60)

    assert limiter.allow('a') and limiter.allow('a')
    assert not limiter.allow('a')
    assert limiter.is_blocked('a') and not limiter.is_blocked('b')
    assert limiter.allow('b')

    clock[0] += 61
    assert not limiter.is_blocked('a')
    assert limiter.allow('a')
    clock[0] += 61
    limiter.prune()
    assert limiter._hits == {}


def test_rate_limiter_disabled():
    limiter = RateLimiter(0)
    assert all(limiter.allow('a') for _ in range(100))
    assert not limiter.is_blocked('a')


def test_folder_size(tmp_path):
    (tmp_path / 'a').write_bytes(b'x' * 10)
    (tmp_path / 'b').write_bytes(b'x' * 5)
    (tmp_path / 'sub').mkdir()
    assert folder_size(str(tmp_path)) == 15
    assert folder_size(str(tmp_path / 'missing')) == 0


def test_uploads_are_rate_limited_per_visitor(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'UPLOAD_LIMITER', RateLimiter(2))

    assert _upload(client).status_code == 200
    assert _upload(client).status_code == 200
    res = _upload(client)
    assert res.status_code == 429
    assert 'Too many uploads' in res.get_json()['error']

    other = client.post('/analyze', data={'file': (io.BytesIO(build_3mf()), 'm.3mf')},
                        content_type='multipart/form-data',
                        environ_base={'REMOTE_ADDR': '10.0.0.9'})
    assert other.status_code == 200
    # Other routes are not limited
    assert client.get('/filament-types').status_code == 200


def test_uploads_stop_when_storage_is_full(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'MAX_UPLOAD_STORAGE_MB', 1)
    monkeypatch.setattr(app_module, 'folder_size', lambda _path: 2 * 1024 * 1024)

    res = _upload(client)
    assert res.status_code == 503
    assert 'busy' in res.get_json()['error']


def test_health_check_fails_without_templates(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'U1_TEMPLATES', {})
    res = client.get('/healthz')
    assert res.status_code == 503
    assert res.get_json()['ok'] is False


def test_wrong_library_passwords_are_limited(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'ADMIN_TOKEN', 'secret')
    monkeypatch.setitem(flask_app.config, 'AUTH_FAIL_LIMITER', RateLimiter(2))

    # Opening the page without a password does not count as a guess
    for _ in range(5):
        assert client.get('/api/inventory').status_code == 401
    for _ in range(2):
        assert client.get('/api/inventory', headers={'X-Admin-Token': 'wrong'}).status_code == 401

    blocked = client.get('/api/inventory', headers={'X-Admin-Token': 'secret'})
    assert blocked.status_code == 429
