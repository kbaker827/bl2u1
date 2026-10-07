"""Bambu Lab .3mf -> Snapmaker U1 conversion logic (no Flask dependencies).

Filament numbering is never changed: slot N in the output is slot N in the
input. Object extruder assignments (model_settings.config) and painted regions
(3D/Objects/*.model) refer to filaments by number, so renumbering them would
make painted areas print in the wrong colour.
"""

import copy
import json
import logging
import posixpath
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET

from defusedxml.ElementTree import fromstring as safe_fromstring

from utils import remove_quietly

logger = logging.getLogger(__name__)

SLICE_INFO       = 'Metadata/slice_info.config'
PROJECT_SETTINGS = 'Metadata/project_settings.config'

TARGET_FILAMENTS_MIN     = 4     # pad to at least 4 slots (one per U1 toolhead)
DEFAULT_FILAMENT_PROFILE = 'Snapmaker PLA SnapSpeed @U1'
PAD_COLOR                = '#FFFFFFFF'
PAD_TYPE                 = 'PLA'

# Zip-bomb guards. Declared sizes are trustworthy upper bounds: zipfile stops
# reading an entry once its declared size is reached.
MAX_ENTRIES            = 10_000
MAX_UNCOMPRESSED_TOTAL = 1024 ** 3        # 1 GiB
MAX_CONFIG_BYTES       = 32 * 1024 ** 2   # config files are read into memory
COPY_CHUNK             = 1024 ** 2

FALLBACK_FILAMENTS = (
    {'type': 'PLA',  'settings_id': DEFAULT_FILAMENT_PROFILE},
    {'type': 'PETG', 'settings_id': 'Snapmaker PETG HF'},
    {'type': 'ABS',  'settings_id': 'Generic ABS'},
    {'type': 'TPU',  'settings_id': 'Generic TPU'},
)

# Materials with no U1 profile of their own, mapped to the closest one.
TYPE_ALIASES = {'ASA': 'ABS', 'PCTG': 'PETG'}

# Process settings carried over when the user changed them from the Bambu
# system preset. Speeds, temperatures and accelerations are machine-specific
# and deliberately excluded. enable_support is handled by template choice.
CARRY_OVER_KEYS = frozenset({
    'layer_height', 'initial_layer_print_height',
    'wall_loops', 'top_shell_layers', 'bottom_shell_layers',
    'sparse_infill_density', 'sparse_infill_pattern',
    'top_surface_pattern', 'bottom_surface_pattern', 'only_one_wall_top',
    'brim_type', 'brim_width',
    'support_type', 'support_style', 'support_threshold_angle',
    'support_on_build_plate_only',
    'seam_position', 'ironing_type', 'fuzzy_skin', 'print_sequence',
})
LAYER_HEIGHT_KEYS = frozenset({'layer_height', 'initial_layer_print_height'})
MIN_LAYER_HEIGHT  = 0.04
MAX_LAYER_HEIGHT  = 0.32   # 80% of the U1's 0.4 mm nozzle

_COLOR_RE    = re.compile(r'^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$')
_PRINTER_RE  = re.compile(r'(key="printer_model_id"\s+value=")[^"]*(")')
U1_MODEL_ID  = 'Snapmaker U1'


class ConversionError(Exception):
    """A conversion problem whose message is safe to show to the user."""


# ---------------------------------------------------------------------------
# Startup loading
# ---------------------------------------------------------------------------
def load_filament_profiles(path: str) -> list[dict]:
    """Read the U1 filament profiles from the reference .3mf, with fallbacks."""
    try:
        with zipfile.ZipFile(path, 'r') as z:
            settings = json.loads(z.read(PROJECT_SETTINGS).decode('utf-8'))
        profiles = [
            {'type': t, 'settings_id': sid}
            for t, sid in zip(settings.get('filament_type', []),
                              settings.get('filament_settings_id', []))
        ]
        if profiles:
            logger.info("Loaded %d filament profiles", len(profiles))
            return profiles
        logger.warning("No filament profiles in %s -- using fallback defaults", path)
    except Exception as e:
        logger.warning("Could not load filament profiles (%s) -- using fallback defaults", e)
    return [dict(p) for p in FALLBACK_FILAMENTS]


def load_templates(paths: dict[bool, str]) -> dict[bool, dict]:
    """Load template project settings keyed by "has supports"."""
    templates: dict[bool, dict] = {}
    for has_support, path in paths.items():
        try:
            with zipfile.ZipFile(path, 'r') as z:
                templates[has_support] = json.loads(z.read(PROJECT_SETTINGS).decode('utf-8'))
        except Exception as e:
            logger.error("Could not load template %s: %s", path, e)
    return templates


# ---------------------------------------------------------------------------
# Archive inspection
# ---------------------------------------------------------------------------
def check_archive(path: str) -> None:
    """Reject files that are not ZIP archives or would unpack to something huge."""
    try:
        with zipfile.ZipFile(path, 'r') as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, OSError) as e:
        raise ConversionError('Uploaded file is not a valid 3MF/ZIP archive') from e
    if len(infos) > MAX_ENTRIES:
        raise ConversionError('The 3MF archive contains too many files')
    if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_TOTAL:
        raise ConversionError('The 3MF archive is too large once uncompressed')


def _read_text(z: zipfile.ZipFile, name: str) -> str | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_CONFIG_BYTES:
        raise ConversionError(f'{name} is too large')
    return z.read(info).decode('utf-8')


def _read_settings(z: zipfile.ZipFile) -> dict | None:
    text = _read_text(z, PROJECT_SETTINGS)
    if text is None:
        return None
    try:
        settings = json.loads(text)
    except ValueError as e:
        raise ConversionError('Could not read the project settings in this file') from e
    if not isinstance(settings, dict):
        raise ConversionError('Could not read the project settings in this file')
    return settings


def _parse_xml(text: str) -> ET.Element | None:
    try:
        return safe_fromstring(text)
    except (ET.ParseError, ValueError) as e:   # defusedxml errors subclass ValueError
        logger.warning("Could not parse slice info: %s", e)
        return None


def _printer_model_id(path: str) -> str | None:
    try:
        with zipfile.ZipFile(path, 'r') as z:
            xml_str = _read_text(z, SLICE_INFO)
    except (zipfile.BadZipFile, OSError, ConversionError):
        return None
    if xml_str is None:
        return None
    match = re.search(r'key="printer_model_id"\s+value="([^"]*)"', xml_str)
    return match.group(1) if match else None


def detect_printer(path: str) -> str:
    """Return the source printer model id, or 'Unknown'."""
    return _printer_model_id(path) or 'Unknown'


def is_u1_format(path: str) -> bool:
    """Return True if the .3mf already targets Snapmaker U1."""
    model = _printer_model_id(path)
    return model is not None and U1_MODEL_ID in model


# ---------------------------------------------------------------------------
# Filaments
# ---------------------------------------------------------------------------
def normalize_color(color: str) -> str:
    """Return '#RRGGBB' (upper case), dropping any alpha; '#000000' if invalid."""
    if not color or not isinstance(color, str):
        return '#000000'
    c = color.lstrip('#')
    if len(c) == 8:
        c = c[:6]
    if len(c) != 6:
        return '#000000'
    try:
        int(c, 16)
    except ValueError:
        return '#000000'
    return f'#{c.upper()}'


def _canonical(material: str) -> str:
    return material.upper().replace('-HF', '').replace('-', '').replace(' ', '')


def auto_map_filament_type(original: str, profiles: list[dict]) -> str:
    """Map a source filament type to the closest available U1 type.

    Exact match first, then alias, then the longest U1 type contained in the
    source type (so the result never depends on profile order).
    """
    types = [p['type'] for p in profiles]
    if not types:
        return PAD_TYPE
    if not original or not isinstance(original, str):
        return types[0]

    up = original.strip().upper()
    for t in types:
        if t.upper() == up:
            return t

    source = _canonical(up)
    source = _canonical(TYPE_ALIASES.get(source, source))
    by_canonical = {_canonical(t): t for t in types}
    if source in by_canonical:
        return by_canonical[source]

    contained = [c for c in by_canonical if c and c in source]
    if contained:
        return by_canonical[max(contained, key=len)]
    return types[0]


def _used_filament_ids(root: ET.Element | None) -> set[str] | None:
    """Filament ids listed on any plate of a sliced project, or None if unknown."""
    if root is None:
        return None
    ids = {node.get('id') for node in root.iter('filament') if node.get('id')}
    return ids or None


def parse_filaments(path: str, profiles: list[dict]) -> list[dict]:
    """Return one entry per filament slot, in slot order.

    project_settings.config is the source of truth: position N is filament N,
    across every plate. slice_info.config (only present in full for sliced
    projects) is used to flag which filaments are actually used.
    """
    with zipfile.ZipFile(path, 'r') as z:
        settings  = _read_settings(z) or {}
        slice_xml = _read_text(z, SLICE_INFO)

    root = _parse_xml(slice_xml) if slice_xml else None
    used = _used_filament_ids(root)

    colors = settings.get('filament_colour')
    types  = settings.get('filament_type')
    colors = colors if isinstance(colors, list) else []
    types  = types if isinstance(types, list) else []

    if colors:
        slots = [
            (str(i + 1), color, types[i] if i < len(types) else '')
            for i, color in enumerate(colors)
        ]
    else:
        slots = _slots_from_slice_info(root)

    return [
        {
            'id':          fid,
            'color':       normalize_color(color),
            'type':        ftype if isinstance(ftype, str) and ftype else 'PLA',
            'mapped_type': auto_map_filament_type(ftype, profiles),
            'used':        (fid in used) if used is not None else None,
        }
        for fid, color, ftype in slots
    ]


def _slots_from_slice_info(root: ET.Element | None) -> list[tuple[str, str, str]]:
    """Fallback for files without filament_colour: unique ids across all plates."""
    if root is None:
        return []
    seen: dict[str, tuple[str, str, str]] = {}
    for node in root.iter('filament'):
        fid = node.get('id', '')
        if fid.isdigit() and fid not in seen:
            seen[fid] = (fid, node.get('color', ''), node.get('type', ''))
    return [seen[k] for k in sorted(seen, key=int)]


def _resolve_choices(filaments: list[dict], user_colors: dict,
                     profiles: list[dict]) -> list[dict]:
    """Validate the user's choices and return {'color','type'} per slot."""
    if not isinstance(user_colors, dict):
        raise ConversionError('"colors" must be a JSON object')

    valid_ids   = {f['id'] for f in filaments}
    valid_types = {p['type'] for p in profiles}
    for fid, conf in user_colors.items():
        if fid not in valid_ids:
            raise ConversionError(f'Unknown filament ID: {fid}')
        if not isinstance(conf, dict):
            raise ConversionError('Each filament entry must be a JSON object')
        color = conf.get('color', '')
        if not isinstance(color, str) or not _COLOR_RE.match(color):
            raise ConversionError(f'Invalid color: {color}')
        if conf.get('type', '') not in valid_types:
            raise ConversionError(f"Invalid filament type: {conf.get('type', '')}")

    return [
        {
            'color': user_colors[f['id']]['color'] if f['id'] in user_colors else f['color'],
            'type':  user_colors[f['id']]['type'] if f['id'] in user_colors else f['mapped_type'],
        }
        for f in filaments
    ]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def _support_enabled(orig: dict) -> bool:
    value = orig.get('enable_support')
    if isinstance(value, str):
        return value.strip() == '1'
    diff = orig.get('different_settings_to_system', [])
    return any(
        isinstance(s, str) and 'enable_support' in s.split(';')
        for s in (diff if isinstance(diff, list) else [])
    )


def _with_alpha(color: str) -> str:
    return (color + 'FF').upper() if len(color) == 7 else color.upper()


def _fit_list(value: list, count: int) -> list:
    if len(value) < count:
        return value + [value[-1]] * (count - len(value))
    return value[:count]


def _valid_layer_height(value: str) -> bool:
    try:
        return MIN_LAYER_HEIGHT <= float(value) <= MAX_LAYER_HEIGHT
    except ValueError:
        return False


def _changed_process_keys(orig: dict) -> set[str]:
    diff = orig.get('different_settings_to_system')
    if isinstance(diff, list) and diff and isinstance(diff[0], str):
        return {k for k in diff[0].split(';') if k}
    return set()


def _carried_settings(template: dict, orig: dict) -> dict[str, str]:
    """User-changed, whitelisted, sane process settings from the source file."""
    carried = {}
    for key in sorted(_changed_process_keys(orig) & CARRY_OVER_KEYS):
        value = orig.get(key)
        if not isinstance(value, str) or not isinstance(template.get(key), str):
            continue
        if key in LAYER_HEIGHT_KEYS and not _valid_layer_height(value):
            continue
        carried[key] = value
    return carried


def _mark_changed(diff, keys: list[str], filament_count: int) -> list[str]:
    """Add keys to the process entry of different_settings_to_system."""
    if isinstance(diff, list) and diff and isinstance(diff[0], str):
        existing, rest = [k for k in diff[0].split(';') if k], list(diff[1:])
    else:
        existing, rest = [], [''] * (filament_count + 1)
    return [';'.join(sorted(set(existing) | set(keys)))] + rest


def build_settings(template: dict, orig: dict, choices: list[dict],
                   profiles: list[dict], keep_settings: bool) -> dict:
    """Return new U1 project settings for the given filament choices."""
    count  = max(TARGET_FILAMENTS_MIN, len(choices))
    padding = count - len(choices)
    colors = [_with_alpha(c['color']) for c in choices] + [PAD_COLOR] * padding
    types  = [c['type'] for c in choices] + [PAD_TYPE] * padding

    profile_map     = {p['type']: p['settings_id'] for p in profiles}
    default_profile = profiles[0]['settings_id'] if profiles else DEFAULT_FILAMENT_PROFILE

    settings = {
        key: _fit_list(val, count)
        if key.startswith('filament_') and isinstance(val, list) and val else val
        for key, val in copy.deepcopy(template).items()
    }
    settings['filament_colour']      = colors
    settings['filament_type']        = types
    settings['filament_settings_id'] = [profile_map.get(t, default_profile) for t in types]

    if not keep_settings:
        return settings
    carried = _carried_settings(template, orig)
    if not carried:
        return settings
    return {
        **settings,
        **carried,
        'different_settings_to_system': _mark_changed(
            settings.get('different_settings_to_system'), list(carried), count),
    }


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------
def _rewrite_slice_info(xml_str: str, choices: list[dict]) -> bytes:
    xml_str = _PRINTER_RE.sub(rf'\g<1>{U1_MODEL_ID}\g<2>', xml_str)
    root = _parse_xml(xml_str)
    if root is None:
        raise ConversionError('Could not read the slice info in this file')
    for node in root.iter('filament'):
        fid = node.get('id', '')
        if fid.isdigit() and 1 <= int(fid) <= len(choices):
            choice = choices[int(fid) - 1]
            node.set('color', choice['color'].upper())
            node.set('type',  choice['type'])
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def _is_safe_member(name: str) -> bool:
    norm = posixpath.normpath(name)
    return not (name.startswith('/') or norm.startswith('..') or '\\' in name)


def _write_archive(zin: zipfile.ZipFile, output_path: str,
                   replacements: dict[str, bytes]) -> None:
    """Copy zin to output_path, streaming entries and swapping replaced ones."""
    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if not _is_safe_member(item.filename):
                logger.warning("Skipping suspicious ZIP entry: %s", item.filename)
                continue
            info = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = item.external_attr
            if item.filename in replacements:
                zout.writestr(info, replacements[item.filename])
            elif item.is_dir():
                zout.writestr(info, b'')
            else:
                force_zip64 = item.file_size > zipfile.ZIP64_LIMIT
                with zin.open(item) as src, zout.open(info, 'w', force_zip64=force_zip64) as dst:
                    shutil.copyfileobj(src, dst, COPY_CHUNK)


def convert(input_path: str, output_path: str, user_colors: dict, *,
            profiles: list[dict], templates: dict[bool, dict],
            keep_settings: bool = True) -> None:
    """Convert a Bambu .3mf to U1 format.

    user_colors maps filament id -> {'color': '#RRGGBB', 'type': <U1 type>};
    filaments not listed keep their colour and get an auto-mapped type.
    Raises ConversionError for problems the user can fix.
    """
    filaments = parse_filaments(input_path, profiles)
    if not filaments:
        raise ConversionError('Could not find any filaments in this file')
    choices = _resolve_choices(filaments, user_colors, profiles)

    try:
        with zipfile.ZipFile(input_path, 'r') as zin:
            orig = _read_settings(zin)
            if orig is None:
                raise ConversionError(
                    'This file has no project settings. Is it a Bambu Studio project?')
            template = templates.get(_support_enabled(orig))
            if template is None:
                raise ConversionError('Server template missing -- please contact the administrator')

            settings = build_settings(template, orig, choices, profiles, keep_settings)
            replacements = {
                PROJECT_SETTINGS: json.dumps(settings, indent=4, ensure_ascii=False).encode('utf-8'),
            }
            slice_xml = _read_text(zin, SLICE_INFO)
            if slice_xml is not None:
                replacements[SLICE_INFO] = _rewrite_slice_info(slice_xml, choices)

            _write_archive(zin, output_path, replacements)
    except BaseException:
        remove_quietly(output_path)
        raise
