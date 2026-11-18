#!/usr/bin/env python3
"""Verify published source assets against the local upload plan and downloads."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    response = subprocess.run(['gh', 'api', f'repos/{plan["repository"]}/releases/tags/{plan["tag"]}'],
                              check=True, capture_output=True, text=True)
    release = json.loads(response.stdout)
    actual = {a['name']: a for a in release['assets']}
    started = time.monotonic()

    def verify(expected):
        name = expected['name']
        asset = actual.get(name, {})
        row = dict(asset=name, expected_bytes=expected['bytes'], expected_sha256=expected['sha256'],
                   api_bytes=asset.get('size'), api_digest=asset.get('digest'))
        try:
            assert asset.get('size') == expected['bytes'], 'Release asset size differs'
            assert asset.get('digest') == 'sha256:' + expected['sha256'], 'Release asset digest differs'
            with tempfile.TemporaryDirectory(prefix='visa-source-download-') as tmp:
                path = Path(tmp) / name
                subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location',
                                '--retry', '2', '--max-time', '300', '-H', 'Accept-Encoding: identity',
                                '--output', str(path), asset['browser_download_url']],
                               check=True, capture_output=True, text=True)
                digest = hashlib.sha256()
                with path.open('rb') as handle:
                    for block in iter(lambda: handle.read(1024*1024), b''):
                        digest.update(block)
                row.update(download_bytes=path.stat().st_size, download_sha256=digest.hexdigest())
            assert row['download_bytes'] == expected['bytes'], 'Downloaded size differs'
            assert row['download_sha256'] == expected['sha256'], 'Downloaded SHA-256 differs'
            row['passed'] = True
        except Exception as error:
            row.update(passed=False, error=str(error)[:1800])
        print(('PASS ' if row['passed'] else 'FAIL ') + name, flush=True)
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(verify, plan['assets']))
    result = dict(version=plan['version'], tag=plan['tag'], release_url=release['html_url'],
                  passed=all(r['passed'] for r in checks), checks=checks,
                  seconds=round(time.monotonic()-started, 2),
                  downloaded_bytes=sum(r.get('download_bytes', 0) for r in checks))
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k!='checks'}, ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
