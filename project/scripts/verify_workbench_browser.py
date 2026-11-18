#!/usr/bin/env python3
"""Exercise the workbench UI, exports and network-disabled standalone file.

Use --phase preflight --url http://127.0.0.1:18767/ while final data is building.
The default final run requires the real 2011–2025 history and checks file:// too.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import struct
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/validation'
ART = OUT / 'workbench-browser-evidence'
EXE = (Path.home() / 'Library/Caches/ms-playwright/chromium-1254/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')
LABELS = {'chord': '环形', 'single': '单国', 'sankey': '桑基', 'compare': '比较', 'heatmap': '热图'}
GROUPS = ['visitor', 'student', 'work', 'family', 'other', 'unclassified']
DEFAULT = {'countries': ['CHN', 'USA', 'GBR', 'SCH', 'JPN', 'CAN', 'AUS', 'IND'],
           'focusCountry': 'CHN', 'year': 2024, 'visaGroups': GROUPS,
           'flowScope': 'internal', 'spatialScale':'country', 'regionMode': 'aggregate', 'view': 'chord',
           'singleMode': 'radial', 'direction': 'both', 'motionMode': 'analysis',
           'playing': False, 'playbackSpeed': 3500, 'showFree': True, 'maxNodes': 24, 'minAmount': 0}
EXPECTED_YEARS = list(range(2011, 2026))
GEOMETRY = """() => {
 const w=innerWidth,h=innerHeight,r=e=>{const b=e.getBoundingClientRect();return {left:b.left,top:b.top,right:b.right,bottom:b.bottom,width:b.width,height:b.height};};
 const stage=document.querySelector('.chart-stage'),svg=stage?.querySelector('.viz-main-svg');
 const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&getComputedStyle(e).display!=='none';
 const outside=[...document.querySelectorAll('.app-header,.primary-controls,.result-toolbar,.chart-stage,.timeline,.canvas-footer')].filter(visible).map(e=>({tag:e.className,...r(e)})).filter(e=>e.left< -1||e.right>w+1||e.top< -1||e.bottom>h+1);
 const clippedText=svg?[...svg.querySelectorAll('text')].filter(visible).map(e=>({text:e.textContent,...r(e)})).filter(e=>e.left<r(svg).left-2||e.right>r(svg).right+2||e.top<r(svg).top-2||e.bottom>r(svg).bottom+2).slice(0,10):[];
 return {width:w,height:h,documentWidth:document.documentElement.scrollWidth,documentHeight:document.documentElement.scrollHeight,scrollY,stage:stage&&r(stage),svg:svg&&r(svg),marks:svg?.querySelectorAll('[data-chart-interactive]').length||0,outside,clippedText};
}"""


class Run:
    def __init__(self, args):
        self.args = args
        self.checks, self.errors, self.downloads, self.screenshots, self.requests = [], [], [], [], []
        self.version, self.years, self.history_pending = None, [], False

    def check(self, name, passed, detail=None):
        row = {'check': name, 'passed': bool(passed)}
        if detail is not None:
            row['detail'] = detail
        self.checks.append(row)
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)

    def case(self, name, fn, page=None):
        try:
            fn()
            self.check(name + ' completed', True)
        except Exception as exc:
            self.check(name + ' completed', False, str(exc)[:1800])
            if page and not page.is_closed():
                self.screenshot(page, 'failure-' + name.replace(' ', '-'))
                if page.locator('dialog[open]').count():
                    page.keyboard.press('Escape')

    def watch(self, page, scope):
        page.on('pageerror', lambda error: self.errors.append({'scope': scope, 'error': str(error)}))
        page.on('console', lambda msg: self.errors.append({'scope': scope, 'error': msg.text}) if msg.type == 'error' else None)
        page.on('request', lambda request: self.requests.append({'scope': scope, 'url': request.url, 'type': request.resource_type}))

    def ready(self, page):
        page.wait_for_function('!!window.VISA_WORKBENCH', timeout=30000)
        page.wait_for_selector('.chart-stage .viz-main-svg', timeout=10000)
        self.version = page.evaluate('VISA_WORKBENCH.index.meta.version')
        self.years = page.evaluate('[...new Set(VISA_WORKBENCH.index.records.map(r=>r[0]))].sort((a,b)=>a-b)')

    def reset(self, page, **patch):
        state = {**DEFAULT, **patch}
        page.evaluate('(s)=>VISA_WORKBENCH.update(s)', state)
        page.wait_for_function('(s)=>VISA_WORKBENCH.state.view===s.view&&VISA_WORKBENCH.state.countries.join()===s.countries.join()', arg=state)
        page.wait_for_timeout(170)

    def choose_view(self, page, view):
        page.get_by_role('group', name='图形', exact=True).get_by_role('button', name=LABELS[view], exact=True).click()
        page.wait_for_function('(view)=>VISA_WORKBENCH.state.view===view', arg=view)
        page.wait_for_timeout(180)

    def close(self, page):
        page.locator('dialog').get_by_role('button', name='关闭面板', exact=True).click()
        page.wait_for_selector('dialog', state='detached')

    def menu(self, page, label):
        page.get_by_role('button', name='打开资料菜单', exact=True).click()
        page.get_by_role('navigation', name='资料菜单').get_by_role('button', name=label, exact=True).click()

    def download(self, page, button, key, timeout=30000):
        started = time.monotonic()
        with page.expect_download(timeout=timeout) as event:
            button.click()
        d = event.value
        path = ART / (key + Path(d.suggested_filename).suffix)
        d.save_as(path)
        raw = path.read_bytes()
        self.downloads.append({'key': key, 'suggested_filename': d.suggested_filename,
                               'path': str(path.relative_to(ROOT)), 'bytes': len(raw),
                               'elapsed_seconds': round(time.monotonic() - started, 2),
                               'sha256': hashlib.sha256(raw).hexdigest()})
        self.check(key + ' download produces a nonempty file', len(raw) > 100, {'bytes': len(raw), 'filename': d.suggested_filename})
        return path

    def screenshot(self, page, key):
        p = ART / (key + '.png')
        page.screenshot(path=str(p), full_page=True)
        self.screenshots.append(str(p.relative_to(ROOT)))

    def countries(self, page):
        self.reset(page)
        page.locator('.countries-trigger').click()
        dialog = page.locator('dialog')
        search = dialog.get_by_role('textbox', name='搜索国家', exact=True)
        dialog.get_by_role('button', name='清空', exact=True).click()
        self.check('country picker clears the entire selection', page.evaluate('VISA_WORKBENCH.state.countries.length===0'))
        for code in ('CHN', 'JPN', 'IDN'):
            search.fill(code)
            result = dialog.locator('.country-option')
            self.check('country search ' + code + ' narrows real results', result.count() == 1 and code in result.inner_text())
            result.click()
            self.check('country selection ' + code + ' updates its own surface', result.get_attribute('aria-pressed') == 'true')
        self.check('country picker preserves N simultaneous selections', page.evaluate("VISA_WORKBENCH.state.countries.join(',')==='CHN,JPN,IDN'"))
        dialog.get_by_role('button', name='查看 3 个国家／地区', exact=True).click()
        self.check('country selection updates the trigger and visible chart', '已选 3 项' in page.locator('.countries-trigger').inner_text() and page.locator('.viz-main-svg').count() == 1)
        page.locator('.countries-trigger').click()
        search.fill('IDN')
        dialog.locator('.country-option').click()
        self.check('country option toggles out of the selected set', page.evaluate("!VISA_WORKBENCH.state.countries.includes('IDN')&&VISA_WORKBENCH.state.countries.length===2"))
        search.fill('')
        dialog.locator('[aria-label="国家地区"]').select_option('亚洲')
        codes = dialog.locator('.country-option code').all_text_contents()
        expected = page.evaluate("VISA_WORKBENCH.index.entities.filter(e=>e.kind!=='unallocated'&&!VISA_WORKBENCH.index.schengenMembers.includes(e.code)&&e.region==='亚洲').map(e=>e.code)")
        self.check('region filter shows the real Asian country list', sorted(codes) == sorted(expected) and len(codes) > 10, {'visible_countries': len(codes)})
        dialog.get_by_role('button', name='选中当前结果', exact=True).click()
        self.check('select current results applies the region as a multi-country set', sorted(page.evaluate('VISA_WORKBENCH.state.countries')) == sorted(expected))
        dialog.locator('.preset-list').get_by_role('button', name='欧洲', exact=True).click()
        self.check('Europe preset combines Schengen without duplicate members', page.evaluate("VISA_WORKBENCH.state.countries.includes('SCH')&&!VISA_WORKBENCH.state.countries.some(c=>VISA_WORKBENCH.index.schengenMembers.includes(c))"))
        dialog.locator('.preset-list').get_by_role('button', name='全球', exact=True).click()
        self.check('global preset selects the country base and one Schengen aggregate', page.evaluate("VISA_WORKBENCH.state.countries.length>100&&VISA_WORKBENCH.state.countries.includes('SCH')&&!VISA_WORKBENCH.state.countries.some(c=>VISA_WORKBENCH.index.schengenMembers.includes(c))"))
        dialog.locator('.preset-list').get_by_role('button', name='主要往来', exact=True).click()
        dialog.get_by_role('button', name='查看 8 个国家／地区', exact=True).click()
        page.get_by_role('group', name='往来范围', exact=True).get_by_role('button', name='全球往来', exact=True).click()
        self.check('scope control changes the real included flow set', page.evaluate("VISA_WORKBENCH.state.flowScope==='connected'&&VISA_WORKBENCH.analysis.edges.some(e=>!VISA_WORKBENCH.state.countries.includes(e.origin)||!VISA_WORKBENCH.state.countries.includes(e.destination))"))
        self.reset(page)
        self.check('page has no video elements or video navigation', page.locator('video,a[href$=".mp4"],a[href*="video"]').count() == 0)

    def views(self, page, prefix='online'):
        self.reset(page)
        for view in LABELS:
            self.choose_view(page, view)
            svg = page.locator('.chart-stage .viz-main-svg')
            active = page.get_by_role('group', name='图形', exact=True).get_by_role('button', name=LABELS[view], exact=True)
            self.check(prefix + ' ' + view + ' uses a selectable data diagram', svg.count() == 1 and svg.locator('[data-chart-interactive]').count() > 0 and active.get_attribute('data-state') == 'active', {'marks': svg.locator('[data-chart-interactive]').count()})
            if view == 'single':
                modes = page.get_by_role('group', name='单国图形', exact=True)
                for mode, label in [('radial', '流向'), ('origins', '来源'), ('destinations', '去向')]:
                    modes.get_by_role('button', name=label, exact=True).click()
                    self.check(prefix + ' single ' + mode + ' changes computed diagram', page.evaluate('(m)=>VISA_WORKBENCH.state.singleMode===m', mode) and svg.locator('[data-chart-interactive]').count() > 0, {'title': svg.get_attribute('aria-label')})
                self.check(prefix + ' single modes have exactly three choices', modes.get_by_role('button').count() == 3)
                page.select_option('[aria-label="焦点国家"]', 'USA')
                self.check(prefix + ' focus country updates its analysis', page.evaluate("VISA_WORKBENCH.state.focusCountry==='USA'") and '美国' in svg.get_attribute('aria-label'))
            if view == 'compare':
                order = page.get_by_role('group', name='国家对照排序', exact=True)
                order.get_by_role('button', name='收到', exact=True).click()
                self.check(prefix + ' compare sort has an active surface', order.get_by_role('button', name='收到', exact=True).get_attribute('aria-pressed') == 'true')
        nav = page.get_by_role('group', name='图形', exact=True)
        nav.get_by_role('button', name='热图', exact=True).focus()
        page.keyboard.press('Home')
        self.check(prefix + ' view keyboard Home activates chord', page.evaluate("VISA_WORKBENCH.state.view==='chord'"))
        page.keyboard.press('End')
        self.check(prefix + ' view keyboard End activates heatmap', page.evaluate("VISA_WORKBENCH.state.view==='heatmap'"))
        focus_style = page.evaluate('({outline:getComputedStyle(document.activeElement).outlineStyle,shadow:getComputedStyle(document.activeElement).boxShadow})')
        self.check(prefix + ' keyboard focus adds no exterior outline or ring', focus_style['outline'] == 'none' and focus_style['shadow'] == 'none', focus_style)

    def evidence(self, page):
        self.reset(page)
        page.get_by_role('button', name='打开资料菜单', exact=True).click()
        page.get_by_role('navigation', name='资料菜单').get_by_role('button', name='费用明细', exact=True).wait_for(state='visible')
        page.wait_for_function("document.querySelector('.utility-menu')?.contains(document.activeElement)")
        page.keyboard.press('End')
        self.check('utility menu End focuses its final action', page.evaluate("document.activeElement.textContent.includes('复制链接')"))
        page.keyboard.press('Home')
        self.check('utility menu Home focuses its first action', page.evaluate("document.activeElement.textContent.includes('费用明细')"))
        page.keyboard.press('Escape')
        self.check('utility menu Escape returns focus to trigger', page.locator('.utility-menu').count() == 0 and page.evaluate("document.activeElement.id==='utility-trigger'"))
        before = len(self.requests)
        page.locator('.viz-chord-link').first.focus()
        page.keyboard.press('Enter')
        page.wait_for_selector('dialog .evidence-card')
        route = page.locator('dialog h2').inner_text()
        chunks = [r['url'] for r in self.requests[before:] if '/chunks/' in r['url'] or r['url'].endswith('.json.gz')]
        self.check('keyboard ribbon opens lazy bilateral evidence', bool(chunks) and 0 < page.locator('.evidence-card').count() <= 12, {'route': route, 'chunks': chunks})
        first = page.locator('.evidence-card').first
        first.locator(':scope>summary').click()
        self.check('route item exposes original currency quantity and period', first.locator('dl').is_visible() and all(s in first.inner_text() for s in ('原币金额', '数量与口径', '统计期间')))
        first.locator('.parameter-details>summary').click()
        self.check('route parameters contain actual model JSON', first.locator('.parameter-details pre').is_visible() and len(first.locator('.parameter-details pre').inner_text()) > 10)
        first.get_by_role('button', name='查看分项来源', exact=True).click()
        page.wait_for_selector('.source-items article')
        self.check('route sources include the original and local archive', page.locator('.source-items a').filter(has_text='原始页面').count() > 0 and page.locator('.source-items a').filter(has_text='本地归档').count() > 0)
        before = len(self.requests)
        page.get_by_role('button', name='返回 ' + route + ' 的费用明细', exact=True).click()
        page.wait_for_selector('.evidence-card')
        self.check('source return restores route and cached evidence', page.locator('dialog h2').inner_text() == route and not any(r['url'].endswith('.json.gz') for r in self.requests[before:]))
        route_csv = self.download(page, page.get_by_role('button', name='完整路线 CSV', exact=True), 'r4-online-route')
        with route_csv.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        self.check('route CSV preserves payer receiver sources and parameters', rows and all(k in rows[0] for k in ('payer', 'receiver', 'source_ids', 'parameters', 'year')))
        self.close(page)
        self.menu(page, '费用明细')
        page.wait_for_selector('.data-records>button')
        page.get_by_role('textbox', name='搜索费用记录', exact=True).fill('中国大陆')
        page.wait_for_function("document.querySelector('.data-records')?.textContent.includes('中国大陆')")
        visible_rows=page.locator('.data-records>button').all_text_contents()
        self.check('menu data search filters actual records', bool(visible_rows) and all('中国大陆' in text for text in visible_rows),visible_rows[:3])
        self.close(page)
        self.coverage(page)
        self.menu(page, '读图')
        self.check('reading guide opens within the utility menu', page.locator('.help-content').is_visible())
        self.close(page)

    def coverage(self, page):
        self.menu(page, '数据覆盖')
        page.wait_for_selector('.coverage-table>div')
        page.get_by_role('textbox', name='搜索覆盖国家', exact=True).fill('中国')
        page.get_by_role('textbox', name='搜索覆盖国家', exact=True).fill('')
        base_count = page.evaluate("VISA_WORKBENCH.index.entities.filter(e=>e.kind==='country_or_jurisdiction').length")
        page.wait_for_function('(n)=>document.querySelectorAll(".coverage-table>div").length===n', arg=base_count)
        self.check('coverage menu opens the global data base', page.locator('.coverage-table>div').count() == base_count and page.locator('.coverage-summary').is_visible(), {'countries': base_count})
        self.close(page)

    def exports(self, page, prefix):
        self.reset(page)
        page.locator('.export-button').click()
        buttons = page.locator('.export-options>button')
        self.check(prefix + ' export menu has five formats', buttons.count() == 5)
        svg_path = self.download(page, buttons.filter(has_text='图形 SVG'), prefix + '-chart')
        xml = ET.fromstring(svg_path.read_text())
        metadata = json.loads(xml.find('{http://www.w3.org/2000/svg}metadata').text)
        self.check(prefix + ' SVG carries the current state amount and title', metadata['state']['countries'] == DEFAULT['countries'] and metadata['state']['view'] == 'chord' and metadata['state']['visaGroups'] == GROUPS and metadata['state']['regionMode'] == 'aggregate' and metadata['amount_cny'] == page.evaluate('VISA_WORKBENCH.analysis.total') and xml.find('{http://www.w3.org/2000/svg}title') is not None)
        png_path = self.download(page, buttons.filter(has_text='图形 PNG'), prefix + '-chart-raster')
        raw = png_path.read_bytes()
        width, height = struct.unpack('>II', raw[16:24])
        dimensions = page.locator('.chart-stage').bounding_box()
        self.check(prefix + ' PNG contains a valid double-resolution raster', raw.startswith(b'\x89PNG\r\n\x1a\n') and width == round(dimensions['width']) * 2 and height == (round(dimensions['height']) + 72) * 2, {'width': width, 'height': height})
        selected = self.download(page, buttons.filter(has_text='当前筛选 CSV'), prefix + '-selection')
        with selected.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        expected = page.evaluate('VISA_WORKBENCH.analysis.totals.rowCount')
        self.check(prefix + ' selection CSV includes every filtered model row', len(rows) == expected and all(int(r['year']) == DEFAULT['year'] for r in rows), {'export_rows': len(rows), 'index_rows': expected})
        state_path = self.download(page, buttons.filter(has_text='分析状态 JSON'), prefix + '-analysis')
        state = json.loads(state_path.read_text())
        self.check(prefix + ' state JSON reproduces countries view and edges', state['state']['countries'] == DEFAULT['countries'] and state['state']['view'] == 'chord' and len(state['analysis']['edges']) > 0)
        full_path = self.download(page, buttons.filter(has_text='完整数据 JSON'), prefix + '-complete', timeout=60000)
        with gzip.open(ROOT / 'app/data/full-data.json.gz', 'rb') as expected_file:
            expected_hash = hashlib.file_digest(expected_file, 'sha256').hexdigest()
        self.check(prefix + ' complete JSON exactly preserves the frozen corpus bytes', self.downloads[-1]['sha256'] == expected_hash, {'expected_sha256': expected_hash, 'download_sha256': self.downloads[-1]['sha256']})
        full = json.loads(full_path.read_text())
        self.check(prefix + ' complete JSON contains flows sources rules and observations', isinstance(full, dict) and any(k in full for k in ('flows', 'fee_flows')) and bool(full.get('sources')) and any(k in full for k in ('observations', 'observation_index')), {'keys': list(full)})
        full_path.unlink()
        self.downloads[-1]['retained'] = False
        page.wait_for_function("[...document.querySelectorAll('.export-options .action-status')].every(e=>e.textContent==='已导出')")
        self.check(prefix + ' export results stay in the original buttons', all(text == '已导出' for text in page.locator('.export-options .action-status').all_text_contents()))
        self.close(page)

    def timeline(self, page):
        self.reset(page)
        rail = page.get_by_role('group', name='年份', exact=True)
        years = self.years
        self.history_pending = years != EXPECTED_YEARS
        if self.args.phase == 'final':
            self.check('timeline contains all fifteen real years 2011 through 2025', years == EXPECTED_YEARS and rail.get_by_role('button').count() == len(EXPECTED_YEARS), years)
        else:
            self.check('preflight timeline shows every currently built year', rail.get_by_role('button').count() == len(years) and len(years) >= 2, years)
        observations = page.evaluate("[...new Set(VISA_WORKBENCH.index.records.map(r=>r[0]))].sort((a,b)=>a-b).map(year=>{const a=VISA_WORKBENCH.analyzeSelection({...VISA_WORKBENCH.state,year});return {year,total:a.total,rows:a.totals.rowCount,receivers:new Set(a.edges.map(e=>e.destination)).size};})")
        maximum = max(o['total'] for o in observations)
        actual = []
        for observation in observations:
            button = rail.get_by_role('button', name=str(observation['year']), exact=True)
            button.click()
            page.wait_for_function('(y)=>VISA_WORKBENCH.state.year===y', arg=observation['year'])
            actual.append(page.evaluate('({year:VISA_WORKBENCH.state.year,total:VISA_WORKBENCH.analysis.total,rows:VISA_WORKBENCH.analysis.totals.rowCount})'))
            bar = float(button.locator('.year-bar').evaluate('e=>parseFloat(e.style.height)'))
            expected_bar = max(2, observation['total'] / maximum * 24)
            self.check('timeline year ' + str(observation['year']) + ' uses its real flow result', math.isclose(actual[-1]['total'],observation['total'],abs_tol=.01) and actual[-1]['rows'] == observation['rows'] and observation['rows'] > 0 and abs(bar - expected_bar) < .01 and f"当前筛选{observation['receivers']}个" in button.get_attribute('title'), observation)
        self.check('historical selection changes real totals and row counts', len({o['total'] for o in actual}) > 1 and len({o['rows'] for o in actual}) > 1)
        rail.get_by_role('button', name=str(years[-1]), exact=True).focus()
        page.keyboard.press('Home')
        self.check('year rail Home selects the first available year', page.evaluate('VISA_WORKBENCH.state.year') == years[0])
        page.keyboard.press('End')
        self.check('year rail End selects the final available year', page.evaluate('VISA_WORKBENCH.state.year') == years[-1])
        self.reset(page)
        page.get_by_role('button', name='播放速度', exact=True).click()
        self.check('speed button changes the real playback interval', page.evaluate('VISA_WORKBENCH.state.playbackSpeed===1800') and page.get_by_role('button', name='播放速度', exact=True).inner_text() == '2×')
        page.reload(wait_until='load')
        self.ready(page)
        self.check('saved URL reload restores numeric speed and paused playback', page.evaluate("typeof VISA_WORKBENCH.state.playbackSpeed==='number'&&VISA_WORKBENCH.state.playbackSpeed===1800&&!VISA_WORKBENCH.state.playing"))
        self.reset(page,year=years[-3])
        start = page.evaluate('VISA_WORKBENCH.state.year')
        next_year = years[(years.index(start) + 1) % len(years)]
        page.get_by_role('button', name='播放时间变化', exact=True).click()
        page.wait_for_function('(y)=>VISA_WORKBENCH.state.year===y', arg=next_year, timeout=4000)
        self.check('play advances to the next available year and draws flow cues', page.evaluate('VISA_WORKBENCH.state.playing') and page.locator('.viz-flow-trace').count() > 0)
        page.get_by_role('button', name='暂停播放', exact=True).click()
        paused = page.evaluate('VISA_WORKBENCH.state.year')
        page.wait_for_timeout(1950)
        self.check('pause holds the year and the independent flow light continues', page.evaluate('VISA_WORKBENCH.state.year') == paused and page.locator('.viz-flow-trace').count() > 0)
        page.get_by_role('button', name='播放时间变化', exact=True).click()
        page.emulate_media(reduced_motion='reduce')
        page.wait_for_function("!VISA_WORKBENCH.state.playing&&document.querySelector('.visa-visualization')?.classList.contains('reduce-motion')", timeout=3000)
        self.check('live reduced-motion change stops playback without a reload', page.get_by_role('button', name='播放时间变化', exact=True).is_disabled() and page.locator('.viz-flow-trace').count() == 0)
        page.evaluate('VISA_WORKBENCH.update({playing:true})')
        page.wait_for_function('VISA_WORKBENCH.state.playing===false')
        self.check('reduced motion refuses programmatic playback too', page.locator('.viz-flow-trace').count() == 0)
        page.emulate_media(reduced_motion='no-preference')
        page.wait_for_function("!document.querySelector('[aria-label=播放时间变化]').disabled")
        self.check('live motion preference restoration reenables play', not page.get_by_role('button', name='播放时间变化', exact=True).is_disabled())
        self.reset(page)

    def hydration(self, browser):
        fixtures = [('legacy-url', None, '#countries=CHN,FRA,DEU&focusCountry=CHN&year=2024&visaGroups=student&regionMode=members&singleMode=categories&view=single&minAmount=999999&showFree=false'),
                    ('legacy-storage-v4', 'visa-workbench-state-v4', ''),
                    ('legacy-storage-v3', 'visa-workbench-state-v3', '')]
        for label, key, suffix in fixtures:
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            if key:
                fixture = {**DEFAULT, 'countries': ['CAN', 'ESP', 'ITA'], 'focusCountry': 'CAN', 'visaGroups': ['student'], 'regionMode': 'members', 'singleMode': 'categories', 'showFree': False, 'minAmount': 999999, 'playbackSpeed': '1800'}
                context.add_init_script('localStorage.clear();localStorage.setItem(' + json.dumps(key) + ',' + json.dumps(json.dumps(fixture)) + ');')
            page = context.new_page()
            self.watch(page, label)
            page.goto(self.args.url.split('#')[0] + suffix, wait_until='load')
            self.ready(page)
            state = page.evaluate('VISA_WORKBENCH.state')
            members = page.evaluate('VISA_WORKBENCH.index.schengenMembers')
            self.check(label + ' enforces one Schengen aggregate and all visa categories', state['regionMode'] == 'aggregate' and state['visaGroups'] == GROUPS and 'SCH' in state['countries'] and not set(state['countries']).intersection(members) and state['minAmount'] == 0 and state['showFree'] is True and state['singleMode'] == 'radial', {'countries': state['countries'], 'groups': state['visaGroups'], 'regionMode': state['regionMode']})
            self.check(label + ' strips hidden filter fields from the saved URL', all(field + '=' not in page.url for field in ('visaGroups', 'regionMode', 'showFree', 'minAmount')))
            context.close()

    def layouts(self, page):
        for width in self.args.width or (1440, 1024, 768, 390, 320):
            page.set_viewport_size({'width': width, 'height': 900 if width >= 768 else 844})
            self.reset(page)
            for view in self.args.view or LABELS:
                self.choose_view(page, view)
                page.wait_for_timeout(150)
                geometry = page.evaluate(GEOMETRY)
                good = geometry['documentWidth'] <= width + 1 and geometry['documentHeight'] <= geometry['height'] + 1 and geometry['scrollY'] == 0 and not geometry['outside'] and geometry['svg'] and geometry['stage']['height'] >= 220 and geometry['marks'] > 0
                self.check(f'layout {width}px {view} keeps a fixed canvas without overflow', good, geometry)
                self.check(f'layout {width}px {view} keeps labels inside the canvas', not geometry['clippedText'], geometry['clippedText'])
                if not good or geometry['clippedText']:
                    self.screenshot(page, f'r4-failure-layout-{width}-{view}')
                elif self.args.phase == 'final' and width in (1440, 390) and view == 'chord':
                    self.screenshot(page, f'r4-layout-{width}-chord')
                if width < 500 and view == 'heatmap':
                    cells = page.locator('.viz-main-svg g[data-chart-interactive][aria-label$="点击查看费用与来源"]')
                    target = next(cells.nth(i) for i in range(cells.count()) if '其余' not in cells.nth(i).get_attribute('aria-label'))
                    accessible = target.get_attribute('aria-label')
                    target.focus()
                    page.wait_for_selector('.viz-tooltip.visible b')
                    amount = page.locator('.viz-tooltip b').inner_text()
                    font = page.locator('.viz-tooltip b').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')
                    self.check(f'layout {width}px narrow heatmap exposes a readable exact amount', amount in accessible and font >= 12 and amount.endswith('元'), {'amount': amount, 'font_px': font})
                    page.keyboard.press('Enter')
                    page.wait_for_selector('dialog .evidence-card')
                    self.check(f'layout {width}px heatmap opens evidence with the same amount', page.locator('.detail-total strong').inner_text() == amount, {'diagram_amount': amount, 'detail_amount': page.locator('.detail-total strong').inner_text()})
                    self.close(page)
            page.locator('.countries-trigger').click()
            dialog_geometry = page.locator('dialog').evaluate('e=>({width:e.getBoundingClientRect().width,scroll:e.scrollWidth})')
            self.check(f'layout {width}px country chooser fits its viewport', dialog_geometry['width'] <= width + 1 and dialog_geometry['scroll'] <= width + 1 and page.locator('dialog [aria-label="搜索国家"]').is_visible(), dialog_geometry)
            self.close(page)
        page.set_viewport_size({'width': 1440, 'height': 900})
        self.reset(page)

    def offline(self, browser):
        context = browser.new_context(accept_downloads=True, reduced_motion='reduce', viewport={'width': 1440, 'height': 900})
        page = context.new_page()
        self.watch(page, 'offline')
        start = len(self.requests)
        context.set_offline(True)
        page.goto(self.args.offline_file.resolve().as_uri(), wait_until='load')
        self.ready(page)
        self.check('offline file boots with browser networking disabled', page.url.startswith('file:') and page.locator('.viz-main-svg').count() == 1)
        self.check('offline file embeds all fifteen real historical years', self.years == EXPECTED_YEARS, self.years)
        self.views(page, 'offline')
        self.reset(page)
        page.locator('.viz-chord-link').first.focus()
        page.keyboard.press('Enter')
        page.wait_for_selector('.evidence-card')
        first = page.locator('.evidence-card').first
        first.locator(':scope>summary').click()
        first.get_by_role('button', name='查看分项来源', exact=True).click()
        page.wait_for_selector('.source-items article')
        self.check('offline route decompresses evidence and opens the source registry', page.locator('.source-items article').count() > 0)
        archive = page.locator('.source-items a').filter(has_text='本地归档').first.get_attribute('href')
        archive_path = Path(unquote(urlparse(urljoin(page.url.split('#')[0], archive)).path)) if archive else None
        self.check('offline source archive resolves to an existing original', bool(archive_path and archive_path.is_file() and archive_path.stat().st_size > 0), str(archive_path))
        self.close(page)
        self.exports(page, self.version.rsplit('-',1)[-1]+'-offline')
        self.screenshot(page, self.version.rsplit('-',1)[-1]+'-offline-file-chord')
        remote = [r for r in self.requests[start:] if r['url'].startswith(('http:', 'https:'))]
        self.check('offline routes sources and all exports make zero HTTP requests', not remote, {'http_requests': remote, 'file_blob_requests': len(self.requests[start:])})
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', choices=['all', 'ui', 'coverage', 'layouts', 'offline', 'exports', 'motion', 'hydration'], default='all')
    parser.add_argument('--phase', choices=['preflight', 'final'], default='final')
    parser.add_argument('--url', default='http://127.0.0.1:18765/app/')
    parser.add_argument('--offline-file', type=Path, default=ROOT / 'app/签证这笔钱-离线版.html')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--reuse-report', type=Path, help='Replace matching check results in this same-version report after a targeted repair.')
    parser.add_argument('--width', type=int, action='append', help='Limit layout verification to this viewport width; repeat as needed.')
    parser.add_argument('--view', choices=list(LABELS), action='append', help='Limit layout verification to this view; repeat as needed.')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    run = Run(args)
    started = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(EXE))
        if args.scope != 'offline':
            context = browser.new_context(accept_downloads=True, reduced_motion='no-preference', viewport={'width': 1440, 'height': 900})
            page = context.new_page()
            run.watch(page, 'online')
            page.goto(args.url, wait_until='load')
            run.ready(page)
            if args.scope in ('all', 'ui'):
                run.case('country selection', lambda: run.countries(page), page)
                run.case('five views and three single modes', lambda: run.views(page), page)
                run.case('menu and route evidence', lambda: run.evidence(page), page)
            if args.scope == 'coverage':
                run.case('coverage menu', lambda: run.coverage(page), page)
            if args.scope in ('all', 'motion'):
                run.case('timeline and motion', lambda: run.timeline(page), page)
            if args.scope in ('all', 'exports'):
                run.case('online exports', lambda: run.exports(page, 'r4-online'), page)
            if args.scope in ('all', 'layouts'):
                run.case('responsive layouts', lambda: run.layouts(page), page)
            if args.scope in ('all', 'hydration'):
                run.case('legacy URL and storage', lambda: run.hydration(browser))
            context.close()
        if args.scope == 'offline' or args.scope == 'all' and args.phase == 'final':
            run.case('offline file', lambda: run.offline(browser))
        run.check('no runtime or console errors', not run.errors, run.errors)
        browser.close()
    result = {'version': run.version, 'phase': args.phase, 'scope': args.scope, 'url': args.url,
              'passed': all(c['passed'] for c in run.checks), 'elapsed_seconds': round(time.time() - started, 2),
              'checks': run.checks, 'errors': run.errors, 'downloads': run.downloads, 'screenshots': run.screenshots,
              'historical_year_expectation': {'expected': EXPECTED_YEARS, 'observed': run.years, 'pending_final_build': run.history_pending if args.phase == 'preflight' else False},
              'reused_visual_evidence': [str(p.relative_to(ROOT)) for p in sorted(OUT.glob('workbench-charts-soft-*.png'))],
              'validation_boundary': 'Real Chromium UI, actual downloads and network-disabled file:// operation. Data arithmetic is checked by the data/query validators.'}
    suffix = '' if args.phase == 'final' and args.scope == 'all' else '-' + args.phase + '-' + args.scope
    path = args.report or args.reuse_report or OUT / ('workbench-browser-checks' + suffix + '.json')
    if args.reuse_report:
        previous = json.loads(args.reuse_report.read_text())
        if previous.get('version') != result['version'] or previous.get('phase') != result['phase']:
            raise ValueError('Reused browser evidence must match the current data version and validation phase.')
        replaced = {c['check'] for c in result['checks']}
        retained = [c for c in previous.get('checks', []) if c['check'] not in replaced]
        result['checks'] = retained + result['checks']
        result['errors'] = previous.get('errors', []) + result['errors']
        replaced_downloads = {d['key'] for d in result['downloads']}
        result['downloads'] = [d for d in previous.get('downloads', []) if d['key'] not in replaced_downloads] + result['downloads']
        result['screenshots'] = list(dict.fromkeys([s for s in previous.get('screenshots', []) if 'failure-' not in s] + result['screenshots']))
        result['passed'] = all(c['passed'] for c in result['checks']) and not result['errors']
        result['incremental_validation'] = previous.get('incremental_validation', []) + [{'scope': args.scope, 'widths': args.width, 'views': args.view, 'reused_checks': len(retained), 'replaced_checks': len(run.checks), 'superseded_failures': [c['check'] for c in previous.get('checks', []) if not c['passed'] and c['check'] in replaced]}]
        result['scope'] = previous.get('scope', args.scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'checks': len(result['checks']), 'failed': [c for c in result['checks'] if not c['passed']], 'errors': result['errors'], 'report': str(path)}, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
