import io
import json
import os
import sys
import tempfile
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Point the app at throwaway folders *before* it is imported.
_TMP = tempfile.mkdtemp(prefix='bl2u1-tests-')
os.environ['BL2U1_UPLOAD_DIR'] = os.path.join(_TMP, 'uploads')
os.environ['BL2U1_INVENTORY_DIR'] = os.path.join(_TMP, 'inventory')
os.environ.pop('ADMIN_TOKEN', None)
os.environ.pop('LIBRARY_ENABLED', None)

import app as app_module  # noqa: E402
import converter  # noqa: E402

RED, GREEN, BLUE, YELLOW = '#FF0000FF', '#00FF00FF', '#0000FFFF', '#FFFF00FF'
FOUR_COLORS = [RED, GREEN, BLUE, YELLOW]

MODEL_SETTINGS = (
    '<?xml version="1.0" encoding="UTF-8"?><config>'
    '<object id="1"><metadata key="extruder" value="1"/></object>'
    '<object id="2"><metadata key="extruder" value="3"/></object>'
    '</config>'
)
PAINTED_MODEL = '<model><triangle v1="0" v2="1" v3="2" paint_color="3C"/></model>'


def plate(filament_ids, colors=FOUR_COLORS, printer='C11'):
    nodes = ''.join(
        f'<filament id="{i}" type="PLA" color="{colors[i - 1][:7]}" used_m="1" used_g="1"/>'
        for i in filament_ids
    )
    return (f'<plate><metadata key="printer_model_id" value="{printer}"/>'
            f'{nodes}</plate>')


def build_3mf(colors=FOUR_COLORS, types=None, slice_info='', settings_extra=None,
              include_settings=True, extra_entries=None) -> bytes:
    """Build a minimal Bambu-style .3mf. slice_info=None omits slice_info.config."""
    settings = {
        'filament_colour': list(colors),
        'filament_type': list(types or ['PLA'] * len(colors)),
        'enable_support': '0',
        'different_settings_to_system': ['', '', ''],
        **(settings_extra or {}),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        if include_settings:
            z.writestr(converter.PROJECT_SETTINGS, json.dumps(settings))
        z.writestr('Metadata/model_settings.config', MODEL_SETTINGS)
        z.writestr('3D/Objects/object_1.model', PAINTED_MODEL)
        if slice_info is not None:
            z.writestr(converter.SLICE_INFO, f'<?xml version="1.0"?><config>{slice_info}</config>')
        for name, data in (extra_entries or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def read_entry(path_or_bytes, name):
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes
    with zipfile.ZipFile(src) as z:
        return z.read(name)


def read_settings(path_or_bytes):
    return json.loads(read_entry(path_or_bytes, converter.PROJECT_SETTINGS))


@pytest.fixture
def flask_app(monkeypatch):
    monkeypatch.setitem(app_module.app.config, 'ADMIN_TOKEN', '')
    monkeypatch.setitem(app_module.app.config, 'LIBRARY_ENABLED', True)
    app_module.app.config['TESTING'] = True
    return app_module.app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def profiles():
    return app_module.app.config['FILAMENT_PROFILES']


@pytest.fixture
def templates():
    return app_module.app.config['U1_TEMPLATES']


@pytest.fixture
def write_3mf(tmp_path):
    def _write(name='in.3mf', **kwargs):
        path = tmp_path / name
        path.write_bytes(build_3mf(**kwargs))
        return str(path)
    return _write
