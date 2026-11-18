#!/usr/bin/env python3
"""Check published Sources links and real GitHub Release download routing.

Reads the staged Pages index, public source manifest and upload plan. This
focused check opens only Sources and two rewritten archive links; the separate
verify_source_release.py owns full downloads and SHA-256 verification of assets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, quote, urljoin, urlparse

from playwright.sync_api import sync_playwright

from verify_country_context_browser import CHROMIUM, ROOT


class SourceRouterRun:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.checks, self.errors, self.downloads, self.screenshots = [], [], [], []
        self.browser_downloads = []
        self.art = args.report.parent / (args.report.stem + '-evidence')
        self.art.mkdir(parents=True, exist_ok=True)
        self.index = json.loads((args.site / 'app/data/index.json').read_text())
        self.manifest = json.loads((args.site / 'source-archives.json').read_text())
        self.plan_path = args.plan or ROOT / 'deliverables' / ('source-archives-' + self.index['meta']['version']) / 'upload-plan.json'
        self.plan = json.loads(self.plan_path.read_text())
        self.base = urljoin(args.url, '../')
        self.live_manifest = None

    def check(self, label, passed, detail=None):
        item = dict(check=label, passed=bool(passed))
        if detail is not None:
            item['detail'] = detail
        self.checks.append(item)
        print(('PASS ' if passed else 'FAIL ') + label, flush=True)

    def case(self, label, fn):
        try:
            fn()
        except Exception as error:
            self.check(label + ' completes', False, str(error)[:1800])

    def watch(self, page):
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('download', lambda download: self.browser_downloads.append(download))

    def shot(self, page, name):
        path = self.art / (name + '.png')
        page.screenshot(path=str(path), full_page=True)
        self.screenshots.append(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path))

    def selected_sources(self):
        files = {f['path']: f for f in self.manifest['files']}
        unique = {}
        for source in self.index['sources']:
            local = source.get('local_path') or ''
            if not local.startswith('source-archive.html?path='):
                continue
            original = parse_qs(urlparse(local).query).get('path', [None])[0]
            assert original in files, (source['source_id'], original)
            unique.setdefault(original, (source, files[original]))
        chosen = sorted(unique.values(), key=lambda pair: (pair[1]['bytes'], pair[1]['path']))[:2]
        assert len(chosen) == 2, 'Need two distinct rewritten local archives'
        return chosen

    def prepare(self, page):
        page.goto(self.args.url, wait_until='load')
        page.wait_for_function('!!window.VISA_WORKBENCH', timeout=45000)
        page.wait_for_selector('.chart-stage', timeout=20000)
        live_index = page.evaluate('VISA_WORKBENCH.index')
        self.live_sources = {s['source_id']: s for s in live_index['sources']}
        self.check('Published workbench matches staged source-release version',
                   live_index['meta']['version'] == self.index['meta']['version'] == self.manifest['version'] == self.plan['version'],
                   dict(live=live_index['meta']['version'], staged=self.index['meta']['version'], plan=self.plan['version']))
        response = page.request.get(urljoin(self.base, 'source-archives.json'), timeout=45000)
        assert response.ok, ('published manifest', response.status)
        self.live_manifest = response.json()
        self.check('Published source manifest matches release plan tag and repository',
                   self.live_manifest['version'] == self.plan['version'] and
                   self.live_manifest['tag'] == self.plan['tag'] and
                   self.live_manifest['repository'] == self.plan['repository'])
        page.get_by_role('button', name='打开资料菜单', exact=True).click()
        page.get_by_role('navigation', name='资料菜单', exact=True).get_by_role('button', name='来源', exact=True).click()
        page.wait_for_selector('.source-items article')

    def archive(self, page, context, source, file):
        sid = source['source_id']
        live = self.live_sources[sid]
        published = next(f for f in self.live_manifest['files'] if f['path'] == file['path'])
        asset = next(a for a in self.plan['assets'] if a['name'] == file['release_asset'])
        path_fields = ['path', 'bytes', 'sha256', 'release_asset', 'release_url', 'pack_asset', 'pack_url']
        self.check(sid + ' manifest preserves original path, byte size, hash and release assets',
                   all(published.get(k) == file.get(k) for k in path_fields) and
                   file['bytes'] == asset['bytes'] and file['sha256'] == asset['sha256'] and
                   source.get('local_archive_path') == file['path'] and
                   (source.get('bytes') is None or source['bytes'] == file['bytes']) and
                   (source.get('sha256') is None or source['sha256'] == file['sha256']),
                   dict(path=file['path'], bytes=file['bytes'], sha256=file['sha256'], release_asset=file['release_asset']))
        page.get_by_label('搜索来源', exact=True).fill(sid)
        article = page.locator('.source-items article').filter(has=page.get_by_text(sid, exact=True))
        assert article.count() == 1, (sid, article.count())
        link = article.locator('a[href*="source-archive.html?path="]')
        expected = urljoin(self.base, source['local_path'])
        actual = link.evaluate('(a)=>a.href')
        self.check(sid + ' Sources archive href retains the GitHub Pages project subpath',
                   live.get('local_path') == source['local_path'] and actual == expected and
                   urlparse(actual).path == urlparse(self.base).path + 'source-archive.html' and
                   parse_qs(urlparse(actual).query).get('path') == [file['path']] and
                   link.get_attribute('target') == '_blank',
                   dict(href=actual, expected=expected))
        self.shot(page, 'sources-' + re.sub(r'[^a-zA-Z0-9_-]', '-', sid))
        # HEAD follows the same signed Release redirect without downloading a
        # second copy. The browser click below exercises the real router/download.
        head = context.request.head(file['release_url'], timeout=60000)
        self.check(sid + ' GitHub Release original resolves to HTTP 200',
                   head.status == 200 and head.url.startswith('https://') and
                   urlparse(head.url).hostname in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com', 'github.com'),
                   dict(status=head.status, final_host=urlparse(head.url).hostname,
                        content_length=head.headers.get('content-length')))
        before = len(self.browser_downloads)
        with page.expect_popup(timeout=15000) as opened:
            link.click()
        popup = opened.value
        deadline = time.monotonic() + 60
        while len(self.browser_downloads) == before and time.monotonic() < deadline:
            page.wait_for_timeout(200)
        assert len(self.browser_downloads) > before, (sid, 'router did not create a browser download', popup.url)
        download = self.browser_downloads[before]
        error = download.failure()
        local = download.path() if not error else None
        size = Path(local).stat().st_size if local else 0
        seen = dict(source_id=sid, original_path=file['path'], router_url=actual,
                    expected_release_url=file['release_url'], download_url=download.url,
                    redirected_response_url=head.url, http_status=head.status,
                    suggested_filename=download.suggested_filename, downloaded_bytes=size,
                    expected_bytes=file['bytes'], error=error)
        self.downloads.append(seen)
        self.check(sid + ' real Sources click opens router and downloads a nonempty original',
                   not error and size > 0 and size == file['bytes'] and
                   download.suggested_filename == file['release_asset'] and
                   (download.url == file['release_url'] or urlparse(download.url).hostname in
                    ('release-assets.githubusercontent.com', 'objects.githubusercontent.com')),
                   {k: v for k, v in seen.items() if k not in ('redirected_response_url', 'download_url')})
        if not popup.is_closed():
            popup.close()

    def invalid(self, context, suffix, expected, name):
        page = context.new_page()
        before = len(self.browser_downloads)
        page.goto(urljoin(self.base, 'source-archive.html') + suffix, wait_until='load')
        page.wait_for_function('(v)=>document.getElementById("error")?.textContent===v', arg=expected)
        self.check(name + ' router shows the exact path error without a download link',
                   page.locator('#error').inner_text() == expected and
                   page.locator('#details').is_hidden() and page.locator('#original').is_hidden() and
                   len(self.browser_downloads) == before,
                   dict(url=page.url, error=page.locator('#error').inner_text()))
        self.shot(page, name)
        page.close()

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(CHROMIUM) if CHROMIUM.is_file() else None, headless=True)
            context = browser.new_context(accept_downloads=True, reduced_motion='reduce', viewport=dict(width=1440, height=1000))
            context.on('page', self.watch)
            page = context.new_page()
            page.set_default_timeout(15000)
            self.prepare(page)
            for source, file in self.selected_sources():
                self.case(source['source_id'], lambda source=source, file=file: self.archive(page, context, source, file))
            self.case('missing path', lambda: self.invalid(context, '', '缺少来源路径。', 'router-missing-path'))
            self.case('unknown path', lambda: self.invalid(context, '?path=' + quote('data/raw/__not_in_source_manifest__.pdf', safe=''),
                       '该来源未列入当前归档清单。', 'router-unknown-path'))
            self.check('Source router checks emit no browser script errors', not self.errors, self.errors)
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://burntroses.github.io/visa-fee-explorer/app/')
    parser.add_argument('--site', type=Path, default=ROOT / 'deploy/github-pages/site')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT / 'docs/validation/r11-source-router-browser.json')
    args = parser.parse_args()
    run = SourceRouterRun(args)
    run.case('source router browser run', run.run)
    report = dict(passed=bool(run.checks) and all(c['passed'] for c in run.checks), url=args.url,
                  version=run.index['meta']['version'], plan=str(run.plan_path),
                  seconds=round(time.monotonic() - run.started, 2), checks=run.checks,
                  downloads=run.downloads, screenshots=run.screenshots, errors=run.errors,
                  validation_boundary='Two distinct rewritten Sources links, project-subpath routing, Release HTTP 200 and real nonempty browser downloads; manifest original path/size/hash versus upload plan. Full asset download SHA-256 verification belongs to verify_source_release.py.')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], checks=len(run.checks), downloads=len(run.downloads), report=str(args.report)), ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
