import os
import re
import tempfile
import time
import uuid
import zipfile
import logging
from threading import Timer, Lock
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

import converter
import db
import library
from converter import ConversionError
from utils import filename_stem, remove_quietly, safe_join, sanitize_download_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER    = os.environ.get('BL2U1_UPLOAD_DIR', os.path.join(BASE_DIR, 'uploads'))
INVENTORY_FOLDER = os.environ.get('BL2U1_INVENTORY_DIR', os.path.join(BASE_DIR, 'inventory'))
MAX_UPLOAD_MB    = 200
MAX_FILE_AGE_HOURS       = 8
CLEANUP_INTERVAL_SECONDS = 3600
MAX_BATCH                = 50

TEMPLATE_PATHS = {
    False: os.path.join(BASE_DIR, 'u1_template.3mf'),
    True:  os.path.join(BASE_DIR, 'u1_template_supports.3mf'),
}
FILAMENT_PROFILES_FILE = os.path.join(BASE_DIR, 'filament_types.3mf')


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ('1', 'true', 'yes', 'on')


app = Flask(__name__)
app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    INVENTORY_FOLDER=INVENTORY_FOLDER,
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    FILAMENT_PROFILES=converter.load_filament_profiles(FILAMENT_PROFILES_FILE),
    U1_TEMPLATES=converter.load_templates(TEMPLATE_PATHS),
    ADMIN_TOKEN=os.environ.get('ADMIN_TOKEN', '').strip(),
    LIBRARY_ENABLED=_env_flag('LIBRARY_ENABLED', True),
    MAX_BATCH=MAX_BATCH,
)

try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(INVENTORY_FOLDER, exist_ok=True)
except OSError as e:
    raise RuntimeError(f"Cannot create directories: {e}") from e

db.init_db(os.path.join(INVENTORY_FOLDER, 'inventory.db'))
app.register_blueprint(library.bp)

if app.config['LIBRARY_ENABLED'] and not app.config['ADMIN_TOKEN']:
    logger.warning("ADMIN_TOKEN is not set: anyone who can reach this server can "
                   "view, edit and delete Library items.")

_SESSION_RE = re.compile(r'^[0-9a-f]{32}$')

# Maps session_id -> original filename stem (for download naming).
# Kept in memory, so the server must run as a single process (see Dockerfile).
_session_names: dict[str, str] = {}
_session_names_lock = Lock()


def _upload_path(filename: str) -> str | None:
    return safe_join(UPLOAD_FOLDER, filename)


def _session_name(session_id: str) -> str:
    with _session_names_lock:
        return _session_names.get(session_id, 'converted')


# ---------------------------------------------------------------------------
# Background cleanup (every hour instead of on every request)
# ---------------------------------------------------------------------------
def cleanup_old_files() -> None:
    now    = time.time()
    cutoff = MAX_FILE_AGE_HOURS * 3600
    try:
        for name in os.listdir(UPLOAD_FOLDER):
            path = os.path.join(UPLOAD_FOLDER, name)
            if os.path.isfile(path) and (now - os.path.getmtime(path)) > cutoff:
                os.remove(path)
                logger.debug("Deleted old upload: %s", name)
    except Exception as e:
        logger.error("Cleanup error: %s", e)

    with _session_names_lock:
        for sid in list(_session_names):
            p = _upload_path(f'{sid}_input.3mf')
            if p is None or not os.path.exists(p):
                _session_names.pop(sid, None)


def _schedule_cleanup(interval: int = CLEANUP_INTERVAL_SECONDS) -> None:
    cleanup_old_files()
    t = Timer(interval, _schedule_cleanup, [interval])
    t.daemon = True          # don't prevent process exit
    t.start()


_schedule_cleanup()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_e):
    return jsonify({'error': f'File is too large. Maximum size is {MAX_UPLOAD_MB} MB.'}), 413


@app.route('/')
def index():
    return render_template(
        'index.html',
        library_enabled=app.config['LIBRARY_ENABLED'],
        max_batch=app.config['MAX_BATCH'],
    )


@app.route('/healthz')
def healthz():
    return jsonify({'ok': True})


@app.route('/filament-types')
def get_filament_types():
    return jsonify(app.config['FILAMENT_PROFILES'])


@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    if not file.filename.lower().endswith('.3mf'):
        return jsonify({'error': 'Only .3mf files are accepted'}), 400

    session_id = uuid.uuid4().hex          # 32 hex chars, full 128-bit entropy
    filepath   = _upload_path(f'{session_id}_input.3mf')
    if filepath is None:
        return jsonify({'error': 'Internal path error'}), 500

    file.save(filepath)
    try:
        converter.check_archive(filepath)
        filaments = converter.parse_filaments(filepath, app.config['FILAMENT_PROFILES'])
        if not filaments:
            raise ConversionError('Could not find any filaments in this file')
    except ConversionError as e:
        remove_quietly(filepath)
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error("Analyze error: %s", e, exc_info=True)
        remove_quietly(filepath)
        return jsonify({'error': 'Could not read this file.'}), 400

    with _session_names_lock:
        _session_names[session_id] = sanitize_download_name(filename_stem(file.filename))
    return jsonify({'session_id': session_id, 'filaments': filaments})


def _do_convert(session_id, user_colors, keep_settings: bool = True) -> tuple[dict, int]:
    """Convert a single session's .3mf file. Returns (result_dict, http_status)."""
    if not isinstance(session_id, str) or not _SESSION_RE.fullmatch(session_id):
        return {'error': 'Invalid session ID'}, 400

    input_path  = _upload_path(f'{session_id}_input.3mf')
    output_path = _upload_path(f'{session_id}_U1_Ready.3mf')
    if input_path is None or output_path is None:
        return {'error': 'Internal path error'}, 500
    if not os.path.exists(input_path):
        return {'error': 'Session expired or file not found. Please re-upload.'}, 404

    try:
        converter.convert(
            input_path, output_path, user_colors,
            profiles=app.config['FILAMENT_PROFILES'],
            templates=app.config['U1_TEMPLATES'],
            keep_settings=keep_settings,
        )
    except ConversionError as e:
        return {'error': str(e)}, 400
    except Exception as e:
        logger.error("Conversion error [%s]: %s", session_id, e, exc_info=True)
        return {'error': 'Conversion failed. Please check your file and try again.'}, 500

    return {
        'download_url':  f'/download/{session_id}_U1_Ready.3mf',
        'download_name': f'{_session_name(session_id)}-U1.3mf',
    }, 200


def _keep_settings_flag(data: dict) -> bool:
    value = data.get('keep_settings', True)
    return value if isinstance(value, bool) else True


@app.route('/convert', methods=['POST'])
def convert():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    result, status = _do_convert(
        data.get('session_id', ''), data.get('colors', {}), _keep_settings_flag(data))
    return jsonify(result), status


@app.route('/convert-batch', methods=['POST'])
def convert_batch():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    sessions = data.get('sessions', {})
    if not isinstance(sessions, dict) or not sessions:
        return jsonify({'error': '"sessions" must be a non-empty object'}), 400
    if len(sessions) > MAX_BATCH:
        return jsonify({'error': f'At most {MAX_BATCH} files can be converted at once'}), 400

    keep_settings = _keep_settings_flag(data)
    results, errors = [], []
    for sid, conf in sessions.items():
        colors = conf.get('colors', {}) if isinstance(conf, dict) else {}
        result, status = _do_convert(sid, colors, keep_settings)
        (results if status == 200 else errors).append({**result, 'session_id': sid})

    return jsonify({'results': results, 'errors': errors}), 200 if results else 500


@app.route('/download-zip', methods=['POST'])
def download_zip():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    session_ids = data.get('session_ids', [])
    if not isinstance(session_ids, list) or not session_ids or len(session_ids) > MAX_BATCH:
        return jsonify({'error': f'"session_ids" must be a list of 1 to {MAX_BATCH} IDs'}), 400
    if not all(isinstance(sid, str) and _SESSION_RE.fullmatch(sid) for sid in session_ids):
        return jsonify({'error': 'Invalid session ID'}), 400

    # An anonymous temp file is deleted by the OS as soon as the response closes it,
    # so bundles never pile up on disk.
    bundle = tempfile.TemporaryFile(dir=UPLOAD_FOLDER)
    try:
        written = _write_bundle(bundle, session_ids)
        if not written:
            bundle.close()
            return jsonify({'error': 'No converted files found'}), 404
        bundle.seek(0)
        return send_file(bundle, mimetype='application/zip', as_attachment=True,
                         download_name='converted_files.zip')
    except Exception as e:
        logger.error("Bundle ZIP error: %s", e, exc_info=True)
        bundle.close()
        return jsonify({'error': 'Failed to create ZIP bundle'}), 500


def _write_bundle(bundle, session_ids: list[str]) -> int:
    """Write converted files into a ZIP with friendly, de-duplicated names."""
    used_names: dict[str, int] = {}
    written = 0
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        for sid in session_ids:
            src = _upload_path(f'{sid}_U1_Ready.3mf')
            if src is None or not os.path.exists(src):
                continue
            friendly = f'{_session_name(sid)}-U1.3mf'
            if friendly in used_names:
                used_names[friendly] += 1
                base, ext = friendly.rsplit('.', 1)
                friendly = f'{base} ({used_names[friendly]}).{ext}'
            else:
                used_names[friendly] = 1
            zout.write(src, friendly)
            written += 1
    return written


@app.route('/download/<filename>')
def download_file(filename: str):
    # Strict allowlist: only session-prefixed output files
    if not re.fullmatch(r'[0-9a-f]{32}_U1_Ready\.3mf', filename):
        return jsonify({'error': 'Invalid filename'}), 400
    filepath = _upload_path(filename)
    if filepath is None or not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    return send_file(filepath, as_attachment=True,
                     download_name=f'{_session_name(filename[:32])}-U1.3mf')


if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug, port=8080)
