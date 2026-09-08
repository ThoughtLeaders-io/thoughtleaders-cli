"""Public bundle boundaries and canonical-reference drift checks (no network)."""

import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_mcp_plugin', ROOT / 'scripts/build_mcp_plugin.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.fixture
def isolated_repo(tmp_path):
    for path in (builder.PLUGIN, Path('.agents/plugins')):
        shutil.copytree(ROOT / path, tmp_path / path)
    source = tmp_path / builder.SOURCE
    source.parent.mkdir(parents=True)
    source.write_bytes((ROOT / builder.SOURCE).read_bytes())
    return tmp_path


def test_checked_in_plugin_is_current():
    builder.validate(ROOT)


def test_canonical_change_requires_regeneration(isolated_repo):
    source = isolated_repo / builder.SOURCE
    source.write_text(source.read_text().replace('ergonomic keyboard review', 'standing desk review'))
    with pytest.raises(ValueError, match='drifted'):
        builder.validate(isolated_repo)
    (isolated_repo / builder.PLUGIN / builder.GENERATED).write_text(builder.render_examples(source.read_text()))
    builder.validate(isolated_repo)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'wrapper'])
def test_unknown_source_shape_fails_closed(mutation):
    source = (ROOT / builder.SOURCE).read_text()
    marker = '### ' + builder.HEADINGS[0] + '\n'
    if mutation == 'missing':
        source = source.replace(marker, '### Renamed\n')
    elif mutation == 'duplicate':
        source += '\n' + marker
    else:
        source = source.replace("tl db es '{", "tl db es --new-flag '{")
    with pytest.raises(ValueError):
        builder.render_examples(source)


def test_zip_is_reproducible_and_allowlisted(isolated_repo, tmp_path):
    plugin = isolated_repo / builder.PLUGIN
    (plugin / 'private.txt').write_text('must not ship')
    first, second = tmp_path / 'first.zip', tmp_path / 'second.zip'
    assert builder.build_zip(isolated_repo, first) == builder.build_zip(isolated_repo, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == set(builder.FILES)
        for name in builder.FILES:
            assert archive.read(name) == (plugin / name).read_bytes()
            assert archive.getinfo(name).external_attr >> 16 == 0o100644


def test_missing_reference_prevents_upload(isolated_repo, tmp_path):
    guide = isolated_repo / builder.PLUGIN / 'skills/tl-mcp/references/tool-selection.md'
    guide.unlink()
    with pytest.raises(ValueError, match='Missing'):
        builder.build_zip(isolated_repo, tmp_path / 'bad.zip')


def test_external_symlink_prevents_upload(isolated_repo, tmp_path):
    guide = isolated_repo / builder.PLUGIN / 'skills/tl-mcp/references/tool-selection.md'
    guide.unlink()
    guide.symlink_to(ROOT / builder.SOURCE)
    with pytest.raises(ValueError, match='unsafe'):
        builder.build_zip(isolated_repo, tmp_path / 'bad.zip')


def test_unbundled_link_prevents_upload(isolated_repo):
    guide = isolated_repo / builder.PLUGIN / 'skills/tl-mcp/references/tool-selection.md'
    guide.write_text(guide.read_text() + '\n[private](../../../../skills/tl/SKILL.md)\n')
    with pytest.raises(ValueError, match='Unpackaged'):
        builder.validate(isolated_repo)


def test_skill_names_and_routing_are_isolated():
    # Static contract only: actual automatic selection depends on the host/model.
    skill = (ROOT / builder.PLUGIN / 'skills/tl-mcp/SKILL.md').read_text()
    description = skill.split('---', 2)[1]
    assert 'name: tl-mcp\n' in description
    assert 'explicitly requests the ThoughtLeaders CLI' in description
    assert 'use the CLI skill instead' in description
    assert not (ROOT / 'skills/tl-mcp').exists()
    assert (ROOT / 'skills/tl/SKILL.md').read_text().startswith('---\nname: tl\n')
    mcp = json.loads((ROOT / builder.PLUGIN / '.mcp.json').read_text())
    assert 'command' not in mcp['mcpServers']['thoughtleaders']
