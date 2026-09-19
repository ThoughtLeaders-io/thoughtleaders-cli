"""Generate shared MCP examples, check drift, and build a reproducible upload ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = Path('plugins/thoughtleaders-youtube-data')
SOURCE = Path('skills/tl/references/elasticsearch-schema.md')
GENERATED = Path('skills/tl-mcp/references/query-examples.md')
HEADINGS = (
    'Search videos by sponsored brand mention',
    'Count sponsored mentions for a brand (size:0 + track_total_hits)',
    'Full-text search on title/summary/transcript',
)
# Explicit public bundle boundary. New files require a reviewed allowlist change.
BASE_FILES = (
    '.codex-plugin/plugin.json',
    '.mcp.json',
    'skills/tl-mcp/SKILL.md',
    'skills/tl-mcp/references/tool-selection.md',
    GENERATED.as_posix(),
)


# Reviewed dependency manifest: canonical files are copied, never discovered by glob.
SKILLS = {
    'tl-keyword-research': {
        'scripts': ('build_report', 'expand_entities', 'fetch_context', 'probe',
                    'search_channels', 'search_videos', 'select_keywords'),
        'references': ('elasticsearch-content-search', 'help'),
        'agents': ('keyword-entity-resolver', 'keyword-relevance-validator',
                   'keyword-context-classifier'),
    },
    'tl-channel-authenticity': {
        'scripts': ('_io_utf8', 'analyze_channel', 'anomaly_detector',
                    'comment_analyzer', 'comment_scraper', 'engagement_ratios',
                    'peer_cohort', 'report', 'resolve_channel', 'score', 'tl_cli',
                    'video_integrity', 'view_curves'),
        'references': ('scoring', 'peer-cohort', 'comment-patterns', 'red-flags'),
        'agents': ('youtube-comment-classifier',),
    },
}
SHARED_SCRIPTS = ('tl_data', 'mcp_run')
RUNTIME = Path('skills/_shared/references/mcp-runtime.md')
TL_METHOD = Path('skills/tl-mcp/references/methodology.md')
FILES = BASE_FILES + (TL_METHOD.as_posix(),) + tuple(
    f'skills/{name}-mcp/{relative}'
    for name, spec in SKILLS.items()
    for relative in (
        'SKILL.md', 'references/methodology.md', 'references/mcp-runtime.md',
        *(f'scripts/{script}.py' for script in (*spec['scripts'], *SHARED_SCRIPTS)),
        *(f'references/{ref}.md' for ref in spec['references']),
        *(f'references/agents/{agent}.md' for agent in spec['agents']),
    )
)


def without_frontmatter(source: str) -> str:
    if not source.startswith('---\n') or '\n---\n' not in source[4:]:
        raise ValueError('Expected canonical Markdown frontmatter')
    return source.split('\n---\n', 1)[1].lstrip()


def section(source: str, heading: str) -> str:
    marker = f'## {heading}\n'
    if source.count(marker) != 1:
        raise ValueError(f'Expected one canonical section: {heading}')
    return source.split(marker, 1)[1].split('\n## ', 1)[0].strip()


def render_tl_methodology(source: str) -> str:
    # Deliberately public subset: no team network sizes, contact details, private
    # organization glossary, permission assumptions, or executable CLI workflows.
    terminology = section(source, 'Data Model & Terminology')
    selected = []
    for prefix in ('- **Channels**', '- **Brands**', '- **Uploads**',
                   '- **Snapshots**', '- **Reports**', '- **Comments**',
                   '- **`projected_views`**', '- **`views`**'):
        matches = [line for line in terminology.splitlines() if line.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f'Expected one public terminology entry: {prefix}')
        selected.append(matches[0])
    method = section(source, 'Methodology').split('\n\n', 1)[0]
    return ('# Shared research terminology and methodology\n\n'
            '<!-- Generated from selected public portions of skills/tl/SKILL.md. -->\n\n'
            + '\n'.join(selected) + '\n\n## Sponsorship matching\n\n' + method + '\n')


def generated_files(root: Path) -> dict[str, bytes]:
    result = {
        GENERATED.as_posix(): render_examples((root / SOURCE).read_text(encoding='utf-8')).encode(),
        TL_METHOD.as_posix(): render_tl_methodology(
            (root / 'skills/tl/SKILL.md').read_text(encoding='utf-8')).encode(),
    }
    for name, spec in SKILLS.items():
        dest = f'skills/{name}-mcp'
        source = root / 'skills' / name
        canonical = without_frontmatter((source / 'SKILL.md').read_text(encoding='utf-8'))
        preface = ('<!-- Generated verbatim from the canonical skill body; do not edit. -->\n\n'
                   '# Reading this workflow through MCP\n\n'
                   'Read [MCP runtime](mcp-runtime.md) first. Its execution instructions '
                   'govern this package. The canonical workflow below retains CLI examples '
                   'as script/argument notation and legacy agent names; do not execute '
                   'CLI commands or install/authenticate the CLI. Use the packaged Python '
                   'scripts through the MCP runner, and the bundled agent prompts. '
                   'Persistence and optional external integrations require separately '
                   'available tools. Canonical source: `skills/' + name + '/SKILL.md`.\n\n')
        result[f'{dest}/references/methodology.md'] = (preface + canonical).encode()
        result[f'{dest}/references/mcp-runtime.md'] = (root / RUNTIME).read_bytes()
        for script in spec['scripts']:
            result[f'{dest}/scripts/{script}.py'] = (source / 'scripts' / f'{script}.py').read_bytes()
        for script in SHARED_SCRIPTS:
            result[f'{dest}/scripts/{script}.py'] = (root / 'skills/_shared' / f'{script}.py').read_bytes()
        for ref in spec['references']:
            result[f'{dest}/references/{ref}.md'] = (source / 'references' / f'{ref}.md').read_bytes()
        for agent in spec['agents']:
            result[f'{dest}/references/agents/{agent}.md'] = without_frontmatter(
                (root / 'agents' / f'{agent}.md').read_text(encoding='utf-8')).encode()
    return result


def generate(root: Path) -> None:
    # CLI skill installers copy only standalone SKILL.md directories, not _shared.
    # Vendor from the same canonical helper so those installations remain complete.
    for skill in SKILLS:
        (root / 'skills' / skill / 'scripts/tl_data.py').write_bytes(
            (root / 'skills/_shared/tl_data.py').read_bytes())
    for name, content in generated_files(root).items():
        path = root / PLUGIN / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def render_examples(source: str) -> str:
    """Extract only JSON, never private prose or executable CLI instructions."""
    chunks = [
        '# ES query structure examples\n\n'
        '<!-- Generated by scripts/build_mcp_plugin.py; do not edit. -->\n\n'
        f'Source: `{SOURCE.as_posix()}` in the ThoughtLeaders CLI repository.\n'
        'Only the selected JSON examples are reused; no schema catalogue is bundled.\n'
        'These are illustrative `query` bodies for `tl_db_es`, not complete tool calls.\n'
        'Fetch `tl_schema_es` first; current schema and tool definitions take precedence.\n'
        'Replace example IDs, phrases and dates, keep results small, and select only\n'
        'needed identifying fields. These examples do not request transcript excerpts;\n'
        'use [the excerpt guide](tool-selection.md#transcript-excerpts) for quotations.\n'
    ]
    for heading in HEADINGS:
        marker = f'### {heading}\n'
        if source.count(marker) != 1:
            raise ValueError(f'Expected exactly one canonical heading: {heading}')
        section = re.split(r'\n#{1,3} ', source.split(marker, 1)[1], maxsplit=1)[0]
        blocks = re.findall(r"```bash\ntl db es '(.*?)'\n```", section, re.S)
        if len(blocks) != 1 or section.count('```') != 2:
            raise ValueError(f'Unrecognized canonical example wrapper: {heading}')
        query = json.loads(blocks[0])
        if not isinstance(query, dict) or 'query' not in query:
            raise ValueError(f'Expected an ES query object: {heading}')
        chunks.append(f'## {heading}\n\n```json\n{json.dumps(query, indent=2, ensure_ascii=False)}\n```\n')
    return '\n'.join(chunks)


def validate(root: Path) -> None:
    plugin = root / PLUGIN
    for name in FILES:
        path = plugin / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(plugin.resolve()):
            raise ValueError(f'Missing or unsafe plugin file: {name}')
    for skill in SKILLS:
        helper = root / 'skills' / skill / 'scripts/tl_data.py'
        if not helper.is_file() or helper.read_bytes() != (root / 'skills/_shared/tl_data.py').read_bytes():
            raise ValueError(f'Generated CLI helper drifted: {skill}; run python scripts/build_mcp_plugin.py --generate')
    for name, expected in generated_files(root).items():
        if (plugin / name).read_bytes() != expected:
            raise ValueError(f'Generated content drifted: {name}; run python scripts/build_mcp_plugin.py --generate')
    manifest = json.loads((plugin / FILES[0]).read_text())
    if manifest['name'] != plugin.name or manifest['skills'] != './skills/' or manifest['mcpServers'] != './.mcp.json':
        raise ValueError('Plugin name or component paths do not match bundle')
    connection = json.loads((plugin / '.mcp.json').read_text())
    if connection != {'mcpServers': {'thoughtleaders': {'type': 'http', 'url': 'https://app.thoughtleaders.io/mcp'}}}:
        raise ValueError('Unexpected MCP connection configuration')
    marketplace = json.loads((root / '.agents/plugins/marketplace.json').read_text())
    entries = [p for p in marketplace['plugins'] if p['name'] == manifest['name']]
    if len(entries) != 1 or entries[0]['source'] != {'source': 'local', 'path': f'./{PLUGIN.as_posix()}'}:
        raise ValueError('Marketplace does not resolve to this plugin')
    skill = (plugin / 'skills/tl-mcp/SKILL.md').read_text()
    if not skill.startswith('---\nname: tl-mcp\n'):
        raise ValueError('Expected distinct tl-mcp skill name')
    for name in SKILLS:
        mcp_name = name + '-mcp'
        entrypoint = (plugin / 'skills' / mcp_name / 'SKILL.md').read_text(encoding='utf-8')
        if not entrypoint.startswith(f'---\nname: {mcp_name}\n'):
            raise ValueError(f'Expected distinct skill name: {mcp_name}')
        if (root / 'skills' / mcp_name).exists():
            raise ValueError('MCP skill must not be in the CLI skill tree')
    if (root / 'skills/tl-mcp').exists():
        raise ValueError('MCP skill must not be in the CLI skill tree')
    for name in FILES:
        if not name.endswith('.md'):
            continue
        path = plugin / name
        for link in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if '://' in link:
                continue
            target = (path.parent / link.split('#')[0]).resolve()
            if not target.is_relative_to(plugin.resolve()) or target.relative_to(plugin.resolve()).as_posix() not in FILES:
                raise ValueError(f'Unpackaged reference in {name}: {link}')


def build_zip(root: Path, output: Path) -> str:
    validate(root)
    if output.resolve().is_relative_to((root / PLUGIN).resolve()):
        raise ValueError('Write upload artifacts outside the maintained plugin source')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(FILES):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (root / PLUGIN / name).read_bytes())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(f'{digest}  {output.name}\n')
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true', help='Refresh generated workflows, scripts and references from canonical skills')
    parser.add_argument('--output', type=Path, help='Write a deterministic upload ZIP after validation')
    args = parser.parse_args()
    if args.generate:
        generate(ROOT)
    validate(ROOT)
    if args.output:
        print(f'{build_zip(ROOT, args.output)}  {args.output}')
    else:
        print('MCP plugin references and generated content are current.')


if __name__ == '__main__':
    main()
