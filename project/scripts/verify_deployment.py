#!/usr/bin/env python3
"""Smoke-test a published static workbench at any URL subpath.

Checks public artifact identity, lazy evidence, five diagrams and actual exports.
Uses the deployment staging tree as the expected release; never uploads data.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
import hashlib
import json
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EXE = (Path.home() / 'Library/Caches/ms-playwright/chromium-1254/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')
VIEWS = {'chord': '环形', 'single': '单国', 'sankey': '桑基', 'compare': '比较', 'heatmap': '热图'}
COUNTRIES = ['CHN', 'USA', 'GBR', 'SCH', 'JPN', 'CAN', 'AUS', 'IND']


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Published root, including its project subpath.')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--site', type=Path, default=ROOT / 'deploy/github-pages/site')
    parser.add_argument('--browser', type=Path, default=EXE)
    parser.add_argument('--changed-since', help='Also compare every added or modified staged site file since this Git revision.')
    args = parser.parse_args()
    base = args.url.rstrip('/') + '/'
    site = args.site.resolve()
    checks, errors, downloads, screenshots, http_samples = [], [], [], [], []
    started = time.monotonic()

    def check(name, passed, detail=None):
        row = {'check': name, 'passed': bool(passed)}
        if detail is not None:
            row['detail'] = detail
        checks.append(row)
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)

    def artifact(relative, binary_gzip=False):
        address = urljoin(base, relative)
        with tempfile.TemporaryDirectory(prefix='visa-artifact-') as temporary:
            body, headers = Path(temporary) / 'body', Path(temporary) / 'headers'
            response = subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location', '--retry', '1', '--max-time', '300', '-H', 'Accept-Encoding: identity', '--dump-header', str(headers), '--output', str(body), '--write-out', '%{http_code}', address], check=True, capture_output=True, text=True)
            raw, status = body.read_bytes(), int(response.stdout)
            encoding = next((line.split(':', 1)[1].strip() for line in headers.read_text().splitlines() if line.lower().startswith('content-encoding:')), '')
        expected = (site / relative).read_bytes()
        detail = {'url': address, 'status': status, 'bytes': len(raw), 'sha256': sha(raw), 'expected_sha256': sha(expected), 'content_encoding': encoding}
        http_samples.append(detail)
        check(relative + ' matches the staged release', status == 200 and raw == expected, detail)
        if binary_gzip:
            valid = raw.startswith(b'\x1f\x8b') and encoding.lower() not in ('gzip', 'x-gzip')
            check(relative + ' remains a binary gzip file for client decompression', valid, {'gzip_magic': raw[:2].hex(), 'content_encoding': encoding})
            if valid:
                json.loads(gzip.decompress(raw))
        return raw

    def ready(page):
        page.wait_for_function('!!window.VISA_WORKBENCH', timeout=120000)
        page.wait_for_selector('.chart-stage .viz-main-svg', timeout=15000)

    def reset(page):
        page.evaluate("VISA_WORKBENCH.update({countries: %s,focusCountry:'CHN',year:2024,flowScope:'internal',view:'chord',singleMode:'radial',playing:false,motionMode:'analysis'})" % json.dumps(COUNTRIES))
        page.wait_for_function("VISA_WORKBENCH.state.view==='chord'&&VISA_WORKBENCH.state.year===2024")

    def view(page, key):
        page.get_by_role('group', name='图形', exact=True).get_by_role('button', name=VIEWS[key], exact=True).click()
        page.wait_for_function('(v)=>VISA_WORKBENCH.state.view===v', arg=key)
        page.wait_for_timeout(80)

    def close(page):
        page.get_by_role('button', name='关闭面板', exact=True).click()
        page.wait_for_selector('dialog', state='detached')

    def fetch_download(page, label, directory):
        button = page.locator('.export-options>button').filter(has_text=label)
        with page.expect_download(timeout=300000) as event:
            button.click()
        downloaded = event.value
        destination = directory / downloaded.suggested_filename
        downloaded.save_as(destination)
        check(label + ' downloads a nonempty file', destination.stat().st_size > 100, {'filename': downloaded.suggested_filename, 'bytes': destination.stat().st_size})
        downloads.append({'format': label, 'filename': downloaded.suggested_filename, 'bytes': destination.stat().st_size, 'retained': False})
        return destination

    try:
        deployed = json.loads(artifact('deployment.json'))
        artifact('index.html')
        artifact('app/index.html')
        index = json.loads(artifact('app/data/index.json'))
        check('public deployment manifest identifies the current data', deployed['version'] == index['meta']['version'] and deployed['index_sha256'] == sha((site/'app/data/index.json').read_bytes()), deployed)
        artifact('app/data/full-data.json.gz', binary_gzip=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=str(args.browser))
            context = browser.new_context(accept_downloads=True, reduced_motion='reduce', viewport={'width': 1440, 'height': 900})
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append({'kind': 'runtime', 'error': str(error)}))
            page.on('console', lambda msg: errors.append({'kind': 'console', 'error': msg.text}) if msg.type == 'error' else None)
            page.on('requestfailed', lambda request: errors.append({'kind': 'request', 'url': request.url, 'error': request.failure}))
            page.on('response', lambda response: errors.append({'kind': 'http', 'url': response.url, 'status': response.status}) if response.status >= 400 else None)
            seen_chunks = []
            page.on('request', lambda request: seen_chunks.append(request.url) if '/chunks/' in request.url and request.url.endswith('.json.gz') else None)
            response = page.goto(base, wait_until='load', timeout=120000)
            ready(page)
            expected_base = urljoin(base, 'app/')
            actual_base = page.evaluate('document.baseURI')
            check('root entry resolves app assets under the project subpath', response.status == 200 and actual_base == expected_base, {'baseURI': actual_base, 'expected': expected_base})
            check('browser runs the published release', page.evaluate('VISA_WORKBENCH.index.meta.version') == deployed['version'])
            reset(page)

            years = page.evaluate('[...new Set(VISA_WORKBENCH.index.records.map(r=>r[0]))].sort((a,b)=>a-b)')
            rail = page.get_by_role('group', name='年份', exact=True)
            expected_years = sorted(index['meta']['years'])
            check('timeline contains every modeled year from the published index', years == expected_years and rail.get_by_role('button').count() == len(expected_years), years)
            rail.get_by_role('button', name=str(expected_years[0]), exact=True).click()
            page.wait_for_function('(year)=>VISA_WORKBENCH.state.year===year', arg=expected_years[0])
            historical = page.evaluate('({total:VISA_WORKBENCH.analysis.total,rows:VISA_WORKBENCH.analysis.totals.rowCount})')
            check('published historical selection computes real flows', historical['total'] > 0 and historical['rows'] > 0, historical)
            reset(page)

            for width, height in [(1440, 900), (390, 844)]:
                page.set_viewport_size({'width': width, 'height': height})
                for key in VIEWS:
                    view(page, key)
                    geometry = page.evaluate("({width:innerWidth,documentWidth:document.documentElement.scrollWidth,marks:document.querySelectorAll('.chart-stage .viz-main-svg [data-chart-interactive]').length})")
                    check(f'{width}px {key} renders without horizontal overflow', geometry['documentWidth'] <= width + 1 and geometry['marks'] > 0, geometry)
                view(page, 'chord')
                image_path = args.report.resolve().with_name(args.report.stem + f'-{width}.png')
                image_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(image_path))
                screenshots.append(str(image_path))
            page.set_viewport_size({'width': 1440, 'height': 900})
            reset(page)
            page.locator('.viz-chord-link').first.focus()
            page.keyboard.press('Enter')
            page.wait_for_selector('dialog .evidence-card', timeout=30000)
            check('published route loads real gzip evidence', bool(seen_chunks) and page.locator('dialog .evidence-card').count() > 0, {'chunks': seen_chunks})
            chunk_url = seen_chunks[0]
            relative_chunk = unquote(urlparse(chunk_url).path).removeprefix(unquote(urlparse(base).path))
            artifact(relative_chunk, binary_gzip=True)
            first = page.locator('.evidence-card').first
            first.locator(':scope>summary').click()
            check('route exposes original currency and quantity', all(t in first.inner_text() for t in ('原币金额', '数量与口径', '统计期间')))
            first.get_by_role('button', name='查看分项来源', exact=True).click()
            page.wait_for_selector('.source-items article')
            links = page.locator('.source-items a').filter(has_text='本地归档').evaluate_all('(links)=>links.map(a=>a.href)')
            source = None
            base_path = unquote(urlparse(base).path)
            for href in links:
                relative = unquote(urlparse(href).path).removeprefix(base_path)
                candidate = site / relative
                if candidate.is_file() and candidate.stat().st_size < 2_000_000:
                    source = relative
                    break
            check('route source links resolve within the deployment project', source is not None, {'links': links, 'sample': source})
            if source:
                artifact(source)
            close(page)

            reset(page)
            page.locator('.export-button').click()
            with tempfile.TemporaryDirectory(prefix='visa-deployment-') as temp:
                directory = Path(temp)
                png = fetch_download(page, '图形 PNG', directory)
                raw = png.read_bytes()
                dimensions = struct.unpack('>II', raw[16:24])
                check('published PNG is a valid raster', raw.startswith(b'\x89PNG\r\n\x1a\n') and dimensions[0] > 1000 and dimensions[1] > 500, {'width': dimensions[0], 'height': dimensions[1]})
                svg = fetch_download(page, '图形 SVG', directory)
                xml = ET.fromstring(svg.read_text())
                metadata = json.loads(xml.find('{http://www.w3.org/2000/svg}metadata').text)
                check('published SVG preserves current state and version', metadata['version'] == deployed['version'] and metadata['state']['countries'] == COUNTRIES)
                selected = fetch_download(page, '当前筛选 CSV', directory)
                with selected.open(encoding='utf-8-sig', newline='') as f:
                    rows = list(csv.DictReader(f))
                count = page.evaluate('VISA_WORKBENCH.analysis.totals.rowCount')
                check('published CSV contains every selected row', len(rows) == count and all(int(r['year']) == 2024 for r in rows), {'exported': len(rows), 'expected': count})
                complete = fetch_download(page, '完整数据 JSON', directory)
                complete_data = json.loads(complete.read_text())
                check('published complete JSON contains the full evidence corpus', complete_data['meta']['version'] == deployed['version'] and len(complete_data['flows']) == index['meta']['flow_count'] and bool(complete_data.get('observations')), {'flow_count': len(complete_data['flows']), 'observation_count': len(complete_data.get('observations', []))})
                complete.unlink()
            close(page)
            check('published browser has no runtime or network errors', not errors, errors)
            context.close()
            browser.close()
        if args.changed_since:
            changed = subprocess.run(['git', '-C', str(site.parent), 'diff', '--no-renames', '--name-only', '-z', '--diff-filter=AM', args.changed_since, 'HEAD', '--', 'site/'], check=True, capture_output=True).stdout.decode().split('\0')
            verified = {sample['url'] for sample in http_samples}
            relatives = [p.removeprefix('site/') for p in changed if p.startswith('site/') and urljoin(base, p.removeprefix('site/')) not in verified]
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(artifact, relatives))
    except Exception as exc:
        check('deployment smoke test completed', False, {'type': type(exc).__name__, 'error': str(exc)[:2000]})

    result = {'url': base, 'timestamp': datetime.now(timezone.utc).isoformat(), 'passed': all(c['passed'] for c in checks), 'elapsed_seconds': round(time.monotonic()-started, 2), 'checks': checks, 'errors': errors, 'http_samples': http_samples, 'downloads': downloads, 'screenshots': screenshots, 'changed_since': args.changed_since, 'scope': 'Published artifact identity, five diagrams at two widths, actual years, lazy route, source archive, actual exports; optional identity checks for all new or changed release files.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': result['passed'], 'checks': len(checks), 'failed': [c['check'] for c in checks if not c['passed']], 'report': str(args.report)}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
