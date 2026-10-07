import os
import zipfile

import pytest

import converter
from converter import ConversionError
from conftest import (BLUE, FOUR_COLORS, GREEN, MODEL_SETTINGS, PAINTED_MODEL, RED,
                      build_3mf, plate, read_entry, read_settings)


def _convert(src, out, profiles, templates, colors=None, **kwargs):
    converter.convert(src, out, colors or {}, profiles=profiles, templates=templates, **kwargs)
    return out


# ---------------------------------------------------------------------------
# parse_filaments
# ---------------------------------------------------------------------------
def test_parse_reads_every_slot_from_project_settings(write_3mf, profiles):
    path = write_3mf(slice_info=None)

    filaments = converter.parse_filaments(path, profiles)

    assert [f['id'] for f in filaments] == ['1', '2', '3', '4']
    assert [f['color'] for f in filaments] == ['#FF0000', '#00FF00', '#0000FF', '#FFFF00']
    assert all(f['used'] is None for f in filaments)


def test_parse_lists_shared_filament_once_across_plates(write_3mf, profiles):
    path = write_3mf(slice_info=plate([1, 2]) + plate([1, 3]))

    filaments = converter.parse_filaments(path, profiles)

    assert [f['id'] for f in filaments] == ['1', '2', '3', '4']
    assert [f['used'] for f in filaments] == [True, True, True, False]


def test_parse_falls_back_to_slice_info_without_colours(write_3mf, profiles):
    path = write_3mf(colors=[], slice_info=plate([2, 1]) + plate([2]))

    filaments = converter.parse_filaments(path, profiles)

    assert [f['id'] for f in filaments] == ['1', '2']
    assert filaments[1]['color'] == '#00FF00'


def test_parse_ignores_unreadable_slice_info(tmp_path, profiles):
    path = tmp_path / 'bad.3mf'
    path.write_bytes(build_3mf(slice_info='<plate><unclosed>'))

    filaments = converter.parse_filaments(str(path), profiles)

    assert len(filaments) == 4
    assert filaments[0]['used'] is None


def test_parse_rejects_corrupt_project_settings(tmp_path, profiles):
    path = tmp_path / 'bad.3mf'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(converter.PROJECT_SETTINGS, '{not json')

    with pytest.raises(ConversionError):
        converter.parse_filaments(str(path), profiles)


# ---------------------------------------------------------------------------
# Regression tests for the bugs found in review
# ---------------------------------------------------------------------------
def test_convert_works_without_slice_info(write_3mf, profiles, templates, tmp_path):
    out = _convert(write_3mf(slice_info=None), str(tmp_path / 'out.3mf'), profiles, templates)

    assert read_settings(open(out, 'rb').read())['filament_colour'] == FOUR_COLORS


def test_convert_multi_plate_keeps_colours_in_slot_order(write_3mf, profiles, templates, tmp_path):
    src = write_3mf(slice_info=plate([1, 2]) + plate([1, 3]))

    out = _convert(src, str(tmp_path / 'out.3mf'), profiles, templates)

    # Slot 3 must stay blue: object 2 is assigned to extruder 3.
    assert read_settings(open(out, 'rb').read())['filament_colour'] == FOUR_COLORS


def test_convert_never_renumbers_filaments(write_3mf, profiles, templates, tmp_path):
    src = write_3mf(slice_info=plate([1, 3]))

    out = open(_convert(src, str(tmp_path / 'out.3mf'), profiles, templates), 'rb').read()

    assert read_settings(out)['filament_colour'][2] == BLUE
    assert read_entry(out, 'Metadata/model_settings.config').decode() == MODEL_SETTINGS
    assert read_entry(out, '3D/Objects/object_1.model').decode() == PAINTED_MODEL


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------
def test_convert_pads_to_four_filaments(write_3mf, profiles, templates, tmp_path):
    src = write_3mf(colors=[RED, GREEN], slice_info=None)

    settings = read_settings(open(_convert(src, str(tmp_path / 'o.3mf'), profiles, templates), 'rb').read())

    assert settings['filament_colour'] == [RED, GREEN, '#FFFFFFFF', '#FFFFFFFF']
    assert len(settings['filament_settings_id']) == 4


def test_convert_keeps_more_than_four_filaments(write_3mf, profiles, templates, tmp_path):
    src = write_3mf(colors=FOUR_COLORS + [RED, GREEN], slice_info=None)

    settings = read_settings(open(_convert(src, str(tmp_path / 'o.3mf'), profiles, templates), 'rb').read())

    assert len(settings['filament_colour']) == 6
    assert all(len(v) == 6 for k, v in settings.items()
               if k.startswith('filament_') and isinstance(v, list))


def test_convert_applies_user_choices(write_3mf, profiles, templates, tmp_path):
    src = write_3mf(slice_info=plate([1, 2]))
    petg = next(p for p in profiles if 'PETG' in p['type'])

    out = open(_convert(src, str(tmp_path / 'o.3mf'), profiles, templates,
                        colors={'2': {'color': '#123456', 'type': petg['type']}}), 'rb').read()

    settings = read_settings(out)
    assert settings['filament_colour'][1] == '#123456FF'
    assert settings['filament_settings_id'][1] == petg['settings_id']
    slice_info = read_entry(out, converter.SLICE_INFO).decode()
    assert 'value="Snapmaker U1"' in slice_info
    assert 'color="#123456"' in slice_info


@pytest.mark.parametrize('colors, message', [
    ({'9': {'color': '#000000', 'type': 'PLA'}}, 'Unknown filament ID'),
    ({'1': {'color': 'red', 'type': 'PLA'}}, 'Invalid color'),
    ({'1': {'color': '#000000', 'type': 'NYLON'}}, 'Invalid filament type'),
    ({'1': 'PLA'}, 'must be a JSON object'),
    (['1'], 'must be a JSON object'),
])
def test_convert_rejects_bad_choices(write_3mf, profiles, templates, tmp_path, colors, message):
    with pytest.raises(ConversionError, match=message):
        converter.convert(write_3mf(), str(tmp_path / 'o.3mf'), colors,
                          profiles=profiles, templates=templates)


def test_convert_uses_supports_template_when_enabled(write_3mf, profiles, templates, tmp_path):
    src = write_3mf(settings_extra={'enable_support': '1'})

    settings = read_settings(open(_convert(src, str(tmp_path / 'o.3mf'), profiles, templates), 'rb').read())

    assert settings['enable_support'] == '1'


def test_support_flag_beats_stale_diff_entry():
    orig = {'enable_support': '0', 'different_settings_to_system': ['enable_support', '']}
    assert converter._support_enabled(orig) is False


def test_support_falls_back_to_diff_when_flag_missing():
    orig = {'different_settings_to_system': ['wall_loops;enable_support', '']}
    assert converter._support_enabled(orig) is True


def test_convert_without_project_settings_fails(tmp_path, profiles, templates):
    src = tmp_path / 'in.3mf'
    src.write_bytes(build_3mf(colors=[], include_settings=False, slice_info=plate([1])))

    with pytest.raises(ConversionError, match='no project settings'):
        converter.convert(str(src), str(tmp_path / 'o.3mf'), {},
                          profiles=profiles, templates=templates)
    assert not os.path.exists(tmp_path / 'o.3mf')


def test_convert_without_filaments_fails(tmp_path, profiles, templates):
    src = tmp_path / 'in.3mf'
    src.write_bytes(build_3mf(colors=[], slice_info=None))

    with pytest.raises(ConversionError, match='any filaments'):
        converter.convert(str(src), str(tmp_path / 'o.3mf'), {},
                          profiles=profiles, templates=templates)


def test_convert_with_missing_template_fails(write_3mf, profiles, tmp_path):
    with pytest.raises(ConversionError, match='template missing'):
        converter.convert(write_3mf(), str(tmp_path / 'o.3mf'), {}, profiles=profiles, templates={})


def test_convert_streams_other_entries_and_skips_unsafe_ones(write_3mf, profiles, templates, tmp_path):
    blob = os.urandom(3 * converter.COPY_CHUNK)
    src = write_3mf(extra_entries={'3D/big.bin': blob, '../evil.txt': b'x', 'Metadata/': b''})

    out = _convert(src, str(tmp_path / 'o.3mf'), profiles, templates)

    with zipfile.ZipFile(out) as z:
        assert z.read('3D/big.bin') == blob
        assert '../evil.txt' not in z.namelist()


def test_unreadable_slice_info_fails_conversion(tmp_path, profiles, templates):
    src = tmp_path / 'in.3mf'
    src.write_bytes(build_3mf(slice_info='<plate><unclosed>'))

    with pytest.raises(ConversionError, match='slice info'):
        converter.convert(str(src), str(tmp_path / 'o.3mf'), {},
                          profiles=profiles, templates=templates)


# ---------------------------------------------------------------------------
# Carrying over print settings
# ---------------------------------------------------------------------------
def _settings_with(extra, profiles, templates, tmp_path, keep=True):
    src = tmp_path / 'in.3mf'
    src.write_bytes(build_3mf(settings_extra=extra))
    out = _convert(str(src), str(tmp_path / 'o.3mf'), profiles, templates, keep_settings=keep)
    return read_settings(open(out, 'rb').read())


def test_changed_settings_are_carried_over(profiles, templates, tmp_path):
    extra = {'layer_height': '0.12', 'wall_loops': '4', 'outer_wall_speed': '999',
             'sparse_infill_density': '40%',
             'different_settings_to_system': ['layer_height;wall_loops;outer_wall_speed', '']}

    settings = _settings_with(extra, profiles, templates, tmp_path)

    assert settings['layer_height'] == '0.12'
    assert settings['wall_loops'] == '4'
    assert settings['outer_wall_speed'] != '999'          # speeds are machine-specific
    assert settings['sparse_infill_density'] == '15%'     # not changed by the user
    assert settings['different_settings_to_system'][0] == 'layer_height;wall_loops'


def test_out_of_range_layer_height_is_not_carried(profiles, templates, tmp_path):
    extra = {'layer_height': '0.4', 'different_settings_to_system': ['layer_height', '']}

    assert _settings_with(extra, profiles, templates, tmp_path)['layer_height'] == '0.2'


def test_keep_settings_false_uses_template(profiles, templates, tmp_path):
    extra = {'wall_loops': '4', 'different_settings_to_system': ['wall_loops', '']}

    assert _settings_with(extra, profiles, templates, tmp_path, keep=False)['wall_loops'] == '2'


def test_mark_changed_merges_with_existing_diff():
    assert converter._mark_changed(['enable_support', 'a', 'b'], ['wall_loops'], 4) == \
        ['enable_support;wall_loops', 'a', 'b']
    assert converter._mark_changed(None, ['wall_loops'], 4) == ['wall_loops'] + [''] * 5


# ---------------------------------------------------------------------------
# Filament type mapping and colours
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('source, expected', [
    ('PLA', 'PLA'),
    ('pla', 'PLA'),
    ('PETG', 'PETG-HF'),
    ('PETG-HF', 'PETG-HF'),
    ('PLA-CF', 'PLA'),
    ('ASA', 'ABS'),
    ('PCTG', 'PETG-HF'),
    ('TPU 95A', 'TPU'),
    ('NYLON', 'PLA'),
    ('', 'PLA'),
    (None, 'PLA'),
])
def test_auto_map_filament_type(source, expected, profiles):
    assert converter.auto_map_filament_type(source, profiles) == expected


def test_auto_map_prefers_longest_match_regardless_of_order():
    profiles = [{'type': 'PLA'}, {'type': 'PLA-CF'}]
    assert converter.auto_map_filament_type('PLA-CF', list(reversed(profiles))) == 'PLA-CF'
    assert converter.auto_map_filament_type('Matte PLA-CF', profiles) == 'PLA-CF'


def test_auto_map_with_no_profiles():
    assert converter.auto_map_filament_type('PLA', []) == 'PLA'


@pytest.mark.parametrize('raw, expected', [
    ('#ff0000', '#FF0000'), ('FF0000FF', '#FF0000'), ('#12', '#000000'),
    ('#GGGGGG', '#000000'), ('', '#000000'), (None, '#000000'),
])
def test_normalize_color(raw, expected):
    assert converter.normalize_color(raw) == expected


# ---------------------------------------------------------------------------
# Archive checks, printer detection, loaders
# ---------------------------------------------------------------------------
def test_check_archive_rejects_non_zip(tmp_path):
    path = tmp_path / 'x.3mf'
    path.write_bytes(b'not a zip')
    with pytest.raises(ConversionError, match='not a valid'):
        converter.check_archive(str(path))


def test_check_archive_rejects_too_many_entries(write_3mf, monkeypatch):
    monkeypatch.setattr(converter, 'MAX_ENTRIES', 2)
    with pytest.raises(ConversionError, match='too many files'):
        converter.check_archive(write_3mf())


def test_check_archive_rejects_huge_uncompressed_size(write_3mf, monkeypatch):
    monkeypatch.setattr(converter, 'MAX_UNCOMPRESSED_TOTAL', 100)
    with pytest.raises(ConversionError, match='too large'):
        converter.check_archive(write_3mf())


def test_oversized_config_entry_is_rejected(write_3mf, profiles, monkeypatch):
    monkeypatch.setattr(converter, 'MAX_CONFIG_BYTES', 10)
    with pytest.raises(ConversionError, match='too large'):
        converter.parse_filaments(write_3mf(), profiles)


def test_printer_detection(write_3mf, tmp_path):
    bambu = write_3mf('b.3mf', slice_info=plate([1]))
    u1 = write_3mf('u.3mf', slice_info=plate([1], printer='Snapmaker U1'))
    bare = write_3mf('n.3mf', slice_info=None)
    junk = tmp_path / 'junk.3mf'
    junk.write_bytes(b'junk')

    assert converter.detect_printer(bambu) == 'C11'
    assert converter.is_u1_format(bambu) is False
    assert converter.is_u1_format(u1) is True
    assert converter.detect_printer(bare) == 'Unknown'
    assert converter.detect_printer(str(junk)) == 'Unknown'


def test_load_filament_profiles_falls_back(tmp_path):
    empty = tmp_path / 'empty.3mf'
    with zipfile.ZipFile(empty, 'w') as z:
        z.writestr(converter.PROJECT_SETTINGS, '{}')

    assert converter.load_filament_profiles(str(tmp_path / 'missing.3mf'))[0]['type'] == 'PLA'
    assert converter.load_filament_profiles(str(empty))[0]['type'] == 'PLA'


def test_load_templates_skips_missing(tmp_path):
    assert converter.load_templates({False: str(tmp_path / 'missing.3mf')}) == {}
