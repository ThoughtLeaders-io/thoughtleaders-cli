"""Public bundle boundaries and canonical-reference drift checks (no network)."""

import ast
import importlib.util
import sys
import sysconfig
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
    for name in ('tl', '_shared', *builder.SKILLS):
        shutil.copytree(ROOT / 'skills' / name, tmp_path / 'skills' / name)
    shutil.copytree(ROOT / 'agents', tmp_path / 'agents')
    return tmp_path


def test_checked_in_plugin_is_current():
    builder.validate(ROOT)


def test_canonical_change_requires_regeneration(isolated_repo):
    source = isolated_repo / builder.SOURCE
    source.write_text(source.read_text().replace('ergonomic keyboard review', 'standing desk review'))
    with pytest.raises(ValueError, match='drifted'):
        builder.validate(isolated_repo)
    builder.generate(isolated_repo)
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


@pytest.mark.parametrize('source', [
    'skills/tl-keyword-research/scripts/probe.py',
    'skills/tl-channel-authenticity/scripts/score.py',
    'skills/_shared/tl_data.py',
    'agents/youtube-comment-classifier.md',
    'skills/tl-keyword-research/SKILL.md',
])
def test_canonical_dependency_changes_require_generation(isolated_repo, source):
    path = isolated_repo / source
    path.write_text(path.read_text(encoding='utf-8') + '\n# Updated canonical source\n', encoding='utf-8')
    with pytest.raises(ValueError, match='drifted'):
        builder.validate(isolated_repo)
    builder.generate(isolated_repo)
    builder.validate(isolated_repo)


def test_full_workflows_and_prompts_are_shared():
    for name, spec in builder.SKILLS.items():
        package = ROOT / builder.PLUGIN / 'skills' / (name + '-mcp')
        canonical = builder.without_frontmatter((ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8'))
        assert (package / 'references/methodology.md').read_text(encoding='utf-8').endswith(canonical)
        for agent in spec['agents']:
            prompt = (package / 'references/agents' / (agent + '.md')).read_text(encoding='utf-8')
            assert prompt == builder.without_frontmatter((ROOT / 'agents' / (agent + '.md')).read_text(encoding='utf-8'))
            assert not prompt.startswith('---')
        for script in spec['scripts']:
            assert (package / 'scripts' / (script + '.py')).read_bytes() == (ROOT / 'skills' / name / 'scripts' / (script + '.py')).read_bytes()
        for script in builder.SHARED_SCRIPTS:
            assert (package / 'scripts' / (script + '.py')).read_bytes() == (ROOT / 'skills/_shared' / (script + '.py')).read_bytes()


def test_installed_packages_have_complete_python_dependencies(tmp_path):
    archive = tmp_path / 'plugin.zip'
    builder.build_zip(ROOT, archive)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(tmp_path / 'installed')
    # Every local import resolves inside the individual installed skill. The only
    # third-party runtime dependency is the explicitly documented yt-dlp scraper.
    for name in builder.SKILLS:
        scripts = tmp_path / 'installed/skills' / (name + '-mcp') / 'scripts'
        local = {path.stem for path in scripts.glob('*.py')}
        for path in scripts.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            compile(tree, str(path), 'exec')
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [alias.name.split('.')[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports = [node.module.split('.')[0]]
                else:
                    continue
                stdlib = set(getattr(sys, 'stdlib_module_names', ()))
                stdlib.update(sys.builtin_module_names)
                stdlib.update(p.stem for p in Path(sysconfig.get_path('stdlib')).iterdir()
                              if p.name not in {'site-packages', 'dist-packages'})
                stdlib.update(p.name.split('.')[0] for p in
                              (Path(sysconfig.get_path('stdlib')) / 'lib-dynload').glob('*'))
                assert set(imports) <= local | stdlib | {'yt_dlp'}, (path, imports)


def test_all_three_discoverable_skill_names():
    names = [Path(name).parts[1] for name in builder.FILES if name.endswith('/SKILL.md')]
    assert sorted(names) == ['tl-channel-authenticity-mcp', 'tl-keyword-research-mcp', 'tl-mcp']
    for name in names:
        body = (ROOT / builder.PLUGIN / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8')
        assert body.startswith('---\nname: ' + name + '\n')
        assert 'explicitly requests the ThoughtLeaders CLI' in body


def test_generated_files_have_no_private_schema_catalogue():
    names = set(builder.FILES)
    assert not any(name.endswith('postgres-schema.md') for name in names)
    assert not any(name.endswith('elasticsearch-schema.md') for name in names)
    public = (ROOT / builder.PLUGIN / builder.TL_METHOD).read_text(encoding='utf-8')
    assert '**Profiles**' not in public
    assert '**TPP**' not in public
    assert 'media_buying_network_join_date' not in public


@pytest.mark.parametrize('name', list(builder.SKILLS))
def test_cli_installed_skill_has_generated_shared_helper(name):
    assert (ROOT / 'skills' / name / 'scripts/tl_data.py').read_bytes() == (ROOT / 'skills/_shared/tl_data.py').read_bytes()
