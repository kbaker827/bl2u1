import gc
import io
import os
import time
import zipfile

import pytest

import app as app_module
from conftest import FOUR_COLORS, build_3mf, plate, read_settings


def _upload(client, data=None, name='My Model.3mf'):
    payload = {'file': (io.BytesIO(data if data is not None else build_3mf(slice_info=plate([1, 2]))), name)}
    return client.post('/analyze', data=payload, content_type='multipart/form-data')


def _session(client, **kwargs):
    res = _upload(client, **kwargs)
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_index_and_health(client):
    page = client.get('/')
    assert page.status_code == 200
    assert b'const LIBRARY_ENABLED = true' in page.data
    assert client.get('/healthz').get_json() == {'ok': True}
    assert client.get('/filament-types').get_json()[0]['type'] == 'PLA'


def test_index_hides_library_when_disabled(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'LIBRARY_ENABLED', False)
    assert b'const LIBRARY_ENABLED = false' in client.get('/').data


def test_analyze_returns_filaments_with_mapping_and_usage(client):
    body = _session(client)

    assert len(body['session_id']) == 32
    assert [f['used'] for f in body['filaments']] == [True, True, False, False]
    assert body['filaments'][0]['mapped_type'] == 'PLA'


@pytest.mark.parametrize('kwargs, message', [
    ({'name': 'model.stl'}, 'Only .3mf'),
    ({'data': b'not a zip'}, 'not a valid'),
    ({'data': build_3mf(colors=[], slice_info=None)}, 'any filaments'),
])
def test_analyze_rejects_bad_uploads(client, kwargs, message):
    res = _upload(client, **kwargs)
    assert res.status_code == 400
    assert message in res.get_json()['error']


def test_analyze_requires_a_file(client):
    assert client.post('/analyze', data={}).status_code == 400
    empty_name = {'file': (io.BytesIO(b''), '')}
    assert client.post('/analyze', data=empty_name, content_type='multipart/form-data').status_code == 400


def test_analyze_handles_unexpected_errors(client, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError('secret internal detail')
    monkeypatch.setattr(app_module.converter, 'parse_filaments', boom)

    res = _upload(client)

    assert res.status_code == 400
    assert 'secret' not in res.get_json()['error']


def test_rejects_oversized_upload(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'MAX_CONTENT_LENGTH', 10)
    assert _upload(client).status_code == 413


def test_convert_and_download_roundtrip(client):
    body = _session(client)
    colors = {'1': {'color': '#123456', 'type': 'PLA'}}

    res = client.post('/convert', json={'session_id': body['session_id'], 'colors': colors})

    assert res.status_code == 200
    result = res.get_json()
    assert result['download_name'] == 'My Model-U1.3mf'
    download = client.get(result['download_url'])
    assert download.status_code == 200
    assert 'My Model-U1.3mf' in download.headers['Content-Disposition']
    settings = read_settings(download.data)
    assert settings['filament_colour'][0] == '#123456FF'
    assert settings['filament_colour'][1:] == FOUR_COLORS[1:]


@pytest.mark.parametrize('payload, status', [
    (None, 400),
    ({'session_id': 'nope'}, 400),
    ({'session_id': 12}, 400),
    ({'session_id': 'a' * 32}, 404),
])
def test_convert_rejects_bad_requests(client, payload, status):
    res = client.post('/convert', json=payload) if payload else client.post('/convert', data='x')
    assert res.status_code == status


def test_convert_reports_invalid_colours(client):
    body = _session(client)
    res = client.post('/convert', json={'session_id': body['session_id'],
                                        'colors': {'1': {'color': 'red', 'type': 'PLA'}}})
    assert res.status_code == 400
    assert 'Invalid color' in res.get_json()['error']


def test_convert_hides_unexpected_errors(client, monkeypatch):
    body = _session(client)
    monkeypatch.setattr(app_module.converter, 'convert',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))

    res = client.post('/convert', json={'session_id': body['session_id'], 'colors': {}})

    assert res.status_code == 500
    assert 'boom' not in res.get_json()['error']


def test_keep_settings_flag(client):
    extra = {'wall_loops': '5', 'different_settings_to_system': ['wall_loops', '']}
    for keep, expected in ((True, '5'), (False, '2')):
        body = _session(client, data=build_3mf(settings_extra=extra))
        res = client.post('/convert', json={'session_id': body['session_id'], 'colors': {},
                                            'keep_settings': keep})
        assert read_settings(client.get(res.get_json()['download_url']).data)['wall_loops'] == expected


def test_batch_convert_and_zip(client):
    first, second = _session(client), _session(client)
    sessions = {first['session_id']: {'colors': {}}, second['session_id']: {},
                'b' * 32: {'colors': {}}}

    res = client.post('/convert-batch', json={'sessions': sessions})

    body = res.get_json()
    assert res.status_code == 200
    assert len(body['results']) == 2 and len(body['errors']) == 1

    ids = [first['session_id'], second['session_id']]
    zipped = client.post('/download-zip', json={'session_ids': ids})
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.data)) as z:
        assert sorted(z.namelist()) == ['My Model-U1 (2).3mf', 'My Model-U1.3mf']
    zipped.close()
    gc.collect()
    leftovers = [n for n in os.listdir(app_module.UPLOAD_FOLDER) if not n.endswith('.3mf')]
    assert leftovers == []


@pytest.mark.parametrize('payload, status', [
    (None, 400),
    ({'sessions': {}}, 400),
    ({'sessions': {str(i): {} for i in range(app_module.MAX_BATCH + 1)}}, 400),
    ({'sessions': {'c' * 32: {}}}, 500),
])
def test_batch_convert_errors(client, payload, status):
    res = client.post('/convert-batch', json=payload) if payload else client.post('/convert-batch', data='x')
    assert res.status_code == status


@pytest.mark.parametrize('payload, status', [
    (None, 400),
    ({'session_ids': []}, 400),
    ({'session_ids': ['../etc']}, 400),
    ({'session_ids': ['d' * 32]}, 404),
])
def test_download_zip_errors(client, payload, status):
    res = client.post('/download-zip', json=payload) if payload else client.post('/download-zip', data='x')
    assert res.status_code == status


def test_download_zip_handles_write_failure(client, monkeypatch):
    def boom(*_a):
        raise OSError('disk full')
    monkeypatch.setattr(app_module, '_write_bundle', boom)
    assert client.post('/download-zip', json={'session_ids': ['e' * 32]}).status_code == 500


def test_download_rejects_bad_names(client):
    assert client.get('/download/..%2Fapp.py').status_code in (400, 404)
    assert client.get('/download/evil.3mf').status_code == 400
    assert client.get(f'/download/{"f" * 32}_U1_Ready.3mf').status_code == 404


def test_cleanup_removes_old_uploads_and_sessions(client):
    body = _session(client)
    old = os.path.join(app_module.UPLOAD_FOLDER, f"{body['session_id']}_input.3mf")
    stale = time.time() - (app_module.MAX_FILE_AGE_HOURS + 1) * 3600
    os.utime(old, (stale, stale))

    app_module.cleanup_old_files()

    assert not os.path.exists(old)
    assert body['session_id'] not in app_module._session_names
