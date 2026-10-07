"""Library (inventory) API: stores converted models with title, description and tags.

When the ADMIN_TOKEN setting is non-empty, every Library request must send it in
the X-Admin-Token header. When LIBRARY_ENABLED is false, the API returns 404.
"""

import hmac
import logging
import os
import re
import shutil
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file

import converter
import db
from converter import ConversionError
from utils import filename_stem, remove_quietly, safe_join, sanitize_download_name

logger = logging.getLogger(__name__)

bp = Blueprint('library', __name__, url_prefix='/api/inventory')

TOKEN_HEADER    = 'X-Admin-Token'
MAX_TITLE       = 200
MAX_DESCRIPTION = 2000
MAX_TAG         = 50
MAX_TAGS        = 20

_ID_RE = re.compile(r'^[0-9a-f]{32}$')


@bp.before_request
def _guard():
    if not current_app.config['LIBRARY_ENABLED']:
        return jsonify({'error': 'The library is disabled on this server'}), 404
    token = current_app.config['ADMIN_TOKEN']
    if token:
        given = request.headers.get(TOKEN_HEADER, '')
        if not hmac.compare_digest(given.encode('utf-8'), token.encode('utf-8')):
            return jsonify({'error': 'Library password required', 'auth_required': True}), 401
    return None


def _inventory_path(filename: str) -> str | None:
    return safe_join(current_app.config['INVENTORY_FOLDER'], filename)


def _find_item(item_id: str):
    """Return (item, None) or (None, error_response)."""
    if not _ID_RE.fullmatch(item_id):
        return None, (jsonify({'error': 'Invalid ID'}), 400)
    item = db.get_item(item_id)
    if item is None:
        return None, (jsonify({'error': 'Item not found'}), 404)
    return item, None


@bp.route('')
def inventory_list():
    items = db.list_items(
        sort_by=request.args.get('sort', 'upload_date'),
        order=request.args.get('order', 'desc'),
        search=request.args.get('q', ''),
    )
    return jsonify(items)


@bp.route('/upload', methods=['POST'])
def inventory_upload():
    files = [f for f in request.files.getlist('files') if f.filename]
    if not files:
        return jsonify({'error': 'No files uploaded'}), 400
    max_batch = current_app.config['MAX_BATCH']
    if len(files) > max_batch:
        return jsonify({'error': f'At most {max_batch} files can be uploaded at once'}), 400

    items, errors = [], []
    for file in files:
        if not file.filename.lower().endswith('.3mf'):
            errors.append({'filename': file.filename, 'error': 'Not a .3mf file'})
            continue
        try:
            items.append(_add_file(file))
        except ConversionError as e:
            errors.append({'filename': file.filename, 'error': str(e)})
        except Exception as e:
            logger.error("Inventory upload error for %s: %s", file.filename, e, exc_info=True)
            errors.append({'filename': file.filename, 'error': 'Could not process this file'})

    return jsonify({'items': items, 'errors': errors}), 200 if items else 400


def _add_file(file) -> dict:
    """Store one uploaded file in the library, converting it to U1 if needed."""
    safe_name   = sanitize_download_name(filename_stem(file.filename))
    item_id     = uuid.uuid4().hex
    stored_name = f'{item_id}.3mf'
    temp_path   = safe_join(current_app.config['UPLOAD_FOLDER'], f'{item_id}_inv_temp.3mf')
    dest_path   = _inventory_path(stored_name)
    if temp_path is None or dest_path is None:
        raise RuntimeError('Internal path error')

    profiles = current_app.config['FILAMENT_PROFILES']
    try:
        file.save(temp_path)
        converter.check_archive(temp_path)
        filaments = converter.parse_filaments(temp_path, profiles)
        if not filaments:
            raise ConversionError('Could not find any filaments in this file')

        already_u1 = converter.is_u1_format(temp_path)
        if already_u1:
            shutil.move(temp_path, dest_path)
        else:
            converter.convert(temp_path, dest_path, {}, profiles=profiles,
                              templates=current_app.config['U1_TEMPLATES'])

        return db.add_item(
            item_id=item_id,
            original_name=f'{safe_name}.3mf',
            stored_name=stored_name,
            file_size=os.path.getsize(dest_path),
            filament_count=len(filaments),
            filament_colors=[f['color'] for f in filaments],
            filament_types=[f['type'] if already_u1 else f['mapped_type'] for f in filaments],
            was_converted=not already_u1,
            source_printer=converter.detect_printer(dest_path if already_u1 else temp_path),
            title=safe_name,
        )
    except BaseException:
        remove_quietly(dest_path)
        raise
    finally:
        remove_quietly(temp_path)


@bp.route('/<item_id>/download')
def inventory_download(item_id: str):
    item, error = _find_item(item_id)
    if error:
        return error
    filepath = _inventory_path(item['stored_name'])
    if filepath is None or not os.path.exists(filepath):
        return jsonify({'error': 'File not found on disk'}), 404
    return send_file(filepath, as_attachment=True, download_name=item['original_name'])


def _clean_tags(tags) -> list[str] | None:
    if isinstance(tags, str):
        tags = tags.split(',')
    if not isinstance(tags, list):
        return None
    cleaned = [str(t).strip()[:MAX_TAG] for t in tags]
    return [t for t in cleaned if t][:MAX_TAGS]


@bp.route('/<item_id>', methods=['PATCH'])
def inventory_update(item_id: str):
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400
    _item, error = _find_item(item_id)
    if error:
        return error

    updates = {}
    if 'title' in data:
        updates['title'] = str(data['title'])[:MAX_TITLE]
    if 'description' in data:
        updates['description'] = str(data['description'])[:MAX_DESCRIPTION]
    if 'tags' in data:
        tags = _clean_tags(data['tags'])
        if tags is not None:
            updates['tags'] = tags

    return jsonify(db.update_item(item_id, **updates))


@bp.route('/<item_id>', methods=['DELETE'])
def inventory_delete(item_id: str):
    item, error = _find_item(item_id)
    if error:
        return error

    filepath = _inventory_path(item['stored_name'])
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError as e:
            logger.error("Could not delete inventory file %s: %s", filepath, e)

    db.delete_item(item_id)
    return jsonify({'ok': True})
