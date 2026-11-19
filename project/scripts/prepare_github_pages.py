#!/usr/bin/env python3
"""Stage the workbench and budgeted Pages/Release source archives; never upload."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import shutil

from build_github_source_archive import application_paths, copy_verified, prepare_sources, DEFAULT_REPO, MIB
from sanitize_source_archives import KEY
from freeze_pages_snapshots import freeze
from workbench_payloads import workbench_payloads

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy/github-pages'
SITE = DEPLOY / 'site'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-release-repo', default=DEFAULT_REPO)
    parser.add_argument('--source-release-tag')
    parser.add_argument('--source-assets-dir', type=Path)
    parser.add_argument('--site-budget-mib', type=int, default=850)
    parser.add_argument('--source-pack-mib', type=int, default=256)
    parser.add_argument('--preserve-source-placement', type=Path, help='Keep Pages and Release source placement for an unchanged data version.')
    args = parser.parse_args()
    index = json.loads((ROOT / 'app/data/index.json').read_text())
    manifest = json.loads((ROOT / 'app/build-manifest.json').read_text())
    SITE.mkdir(parents=True, exist_ok=True)
    paths = application_paths(ROOT)
    output = args.source_assets_dir or ROOT / 'deliverables' / ('source-archives-' + index['meta']['version'])
    archive = prepare_sources(index, ROOT, output,
                              base_site_bytes=sum((ROOT/p).stat().st_size for p in paths),
                              repo=args.source_release_repo, tag=args.source_release_tag,
                              budget_bytes=args.site_budget_mib*MIB,
                              pack_bytes=args.source_pack_mib*MIB,
                              placement_manifest=json.loads(args.preserve_source_placement.read_text()) if args.preserve_source_placement else None)
    # Keep the offline HTML and every canonical source record untouched. Only
    # the staged online index points large-file archive links at Release.
    source_paths = archive['source_paths']
    for relative in source_paths:
        source = ROOT / relative
        if source.suffix.lower() in {'.html', '.htm', '.js', '.txt', '.json', '.xml'} and KEY.search(source.read_bytes()):
            raise SystemExit(f'Embedded credential in public source archive: {relative}')
    paths.update(source_paths - archive['release_paths'])
    extras = archive['extra_site_files']
    online_index_gzip = gzip.compress(archive['index_bytes'], compresslevel=9, mtime=0)
    extras['app/data/index.json.gz'] = online_index_gzip
    extras.update({f'app/data/{name}': raw for name,raw in workbench_payloads(json.loads(archive['index_bytes'])).items()})
    expected = paths | set(extras) | {'index.html', '.nojekyll', 'deployment.json', 'source-pages-snapshots.json'}
    for previous in SITE.rglob('*'):
        if previous.is_file() and str(previous.relative_to(SITE)) not in expected:
            previous.unlink()
    for relative in sorted(paths):
        src, dest = ROOT / relative, SITE / relative
        assert src.resolve().is_relative_to(ROOT), relative
        assert src.stat().st_size < 100*MIB, (relative, 'GitHub regular repository file limit')
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy_verified(src, dest, archive['source_hashes'].get(relative))
    for relative, raw in extras.items():
        (SITE/relative).write_bytes(raw)
    freeze(SITE)
    (SITE/'app/data/index.json').write_bytes(archive['index_bytes'])
    html = (ROOT / 'app/index.html').read_text()
    (SITE / 'index.html').write_text(html.replace('<head>', '<head><base href="./app/">', 1))
    (SITE / '.nojekyll').touch()
    revision = {
        'version': index['meta']['version'],
        'ui_version': index['meta']['ui_version'],
        'offline_sha256': manifest['sha256'],
        'index_sha256': hashlib.sha256((SITE/'app/data/index.json').read_bytes()).hexdigest(),
        'index_bytes': (SITE/'app/data/index.json').stat().st_size,
        'index_gzip_sha256': hashlib.sha256((SITE/'app/data/index.json.gz').read_bytes()).hexdigest(),
        'index_gzip_bytes': (SITE/'app/data/index.json.gz').stat().st_size,
        'boot_bytes': (SITE/f'app/data/boot-{index["meta"]["ui_version"]}.json.gz').stat().st_size,
        'source_archives': len(source_paths),
        'pages_source_files': len(source_paths-archive['release_paths']),
        'release_source_files': len(archive['release_paths']),
        'release_assets': len(archive['assets']),
        'source_release_tag': archive['tag'],
        'source_archive_manifest_sha256': archive['release_manifest_sha256'],
        'source_archive_manifest': 'source-archives.json',
        'source_release_upload_plan': str(Path(archive['upload_plan']).relative_to(ROOT)),
        'site_budget_bytes': archive['budget_bytes'],
        'site_files': len(expected),
    }
    (SITE / 'deployment.json').write_text(json.dumps(revision, ensure_ascii=False, indent=2) + '\n')
    workflow = DEPLOY / '.github/workflows/pages.yml'
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text('''name: Publish visa fee explorer
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@v4
''')
    # README content belongs to the release owner, not the staging operation.
    files = [p for p in SITE.rglob('*') if p.is_file()]
    assert len(files) == revision['site_files'], (len(files), revision['site_files'])
    total = sum(p.stat().st_size for p in files)
    assert total <= archive['budget_bytes'], (total, archive['budget_bytes'])
    assert hashlib.sha256((SITE/'app/签证这笔钱-离线版.html').read_bytes()).hexdigest() == manifest['sha256']
    print(json.dumps({**revision, 'directory': str(DEPLOY), 'site_bytes': total,
                      'release_upload_plan': archive['upload_plan']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
