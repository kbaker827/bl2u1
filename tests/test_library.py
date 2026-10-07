import io

import pytest

import library
from conftest import build_3mf, plate, read_settings

TOKEN = 'correct horse battery staple'


def _upload(client, *files, headers=None):
    data = {'files': [(io.BytesIO(content), name) for name, content in files]}
    return client.post('/api/inventory/upload', data=data,
                       content_type='multipart/form-data', headers=headers or {})


def test_upload_converts_bambu_file_and_lists_it(client):
    res = _upload(client, ('Bambu Part.3mf', build_3mf(slice_info=plate([1, 2]))))

    assert res.status_code == 200
    item = res.get_json()['items'][0]
    assert item['was_converted'] is True
    assert item['source_printer'] == 'C11'
    assert item['title'] == 'Bambu Part'
    assert item['filament_count'] == 4

    download = client.get(f"/api/inventory/{item['id']}/download")
    assert download.status_code == 200
    assert read_settings(download.data)['printer_settings_id'].startswith('Snapmaker U1')

    ids = [i['id'] for i in client.get('/api/inventory?q=Bambu').get_json()]
    assert item['id'] in ids


def test_upload_keeps_u1_files_as_is(client):
    original = build_3mf(slice_info=plate([1], printer='Snapmaker U1'))

    item = _upload(client, ('native.3mf', original)).get_json()['items'][0]

    assert item['was_converted'] is False
    assert client.get(f"/api/inventory/{item['id']}/download").data == original


def test_upload_reports_per_file_errors(client):
    res = _upload(client, ('notes.txt', b'hi'), ('broken.3mf', b'nope'),
                  ('empty.3mf', build_3mf(colors=[], slice_info=None)))

    assert res.status_code == 400
    errors = {e['filename']: e['error'] for e in res.get_json()['errors']}
    assert errors['notes.txt'] == 'Not a .3mf file'
    assert 'not a valid' in errors['broken.3mf']
    assert 'any filaments' in errors['empty.3mf']


def test_upload_hides_unexpected_errors(client, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError('secret internal detail')
    monkeypatch.setattr(library.db, 'add_item', boom)

    res = _upload(client, ('ok.3mf', build_3mf()))

    assert res.get_json()['errors'][0]['error'] == 'Could not process this file'


def test_upload_limits(client, flask_app, monkeypatch):
    assert client.post('/api/inventory/upload', data={}).status_code == 400
    monkeypatch.setitem(flask_app.config, 'MAX_BATCH', 1)
    assert _upload(client, ('a.3mf', build_3mf()), ('b.3mf', build_3mf())).status_code == 400


def test_edit_and_delete_item(client):
    item = _upload(client, ('edit me.3mf', build_3mf())).get_json()['items'][0]
    url = f"/api/inventory/{item['id']}"

    updated = client.patch(url, json={'title': 'New', 'description': 'Desc',
                                      'tags': 'red, , blue'}).get_json()
    assert (updated['title'], updated['description'], updated['tags']) == ('New', 'Desc', ['red', 'blue'])
    assert client.patch(url, json={'tags': ['x' * 80]}).get_json()['tags'] == ['x' * 50]
    assert client.patch(url, json={'tags': 5}).get_json()['tags'] == ['x' * 50]
    assert client.patch(url, data='nope').status_code == 400

    assert client.delete(url).get_json() == {'ok': True}
    assert client.delete(url).status_code == 404


@pytest.mark.parametrize('method', ['get', 'patch', 'delete'])
def test_invalid_item_ids(client, method):
    suffix = '/download' if method == 'get' else ''
    res = getattr(client, method)(f'/api/inventory/not-an-id{suffix}', json={'title': 'x'})
    assert res.status_code == 400


def test_download_missing_file_on_disk(client, flask_app):
    import os
    item = _upload(client, ('gone.3mf', build_3mf())).get_json()['items'][0]
    os.remove(os.path.join(flask_app.config['INVENTORY_FOLDER'], item['stored_name']))

    assert client.get(f"/api/inventory/{item['id']}/download").status_code == 404


def test_token_protects_every_library_route(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'ADMIN_TOKEN', TOKEN)

    assert client.get('/api/inventory').status_code == 401
    assert client.get('/api/inventory', headers={'X-Admin-Token': 'wrong'}).status_code == 401
    assert _upload(client, ('a.3mf', build_3mf())).status_code == 401
    assert client.delete(f"/api/inventory/{'a' * 32}").status_code == 401
    assert client.get('/api/inventory', headers={'X-Admin-Token': TOKEN}).status_code == 200
    # The converter itself stays public
    assert client.get('/filament-types').status_code == 200


def test_library_can_be_disabled(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'LIBRARY_ENABLED', False)
    assert client.get('/api/inventory').status_code == 404
