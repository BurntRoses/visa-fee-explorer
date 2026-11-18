#!/usr/bin/env python3
"""Focused real-browser QA for CountryContext, downloads and offline embedding.

Run after the final data/UI build:
  .research-venv/bin/python scripts/verify_country_context_browser.py \
      --url http://127.0.0.1:18765/app/ \
      --report docs/validation/r10-context-browser.json

This checks the new country-context surface only. It intentionally does not
repeat unrelated chord, heatmap, motion or complete-workbench acceptance tests.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROMIUM = (Path.home() / 'Library/Caches/ms-playwright/chromium-1254/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')
FLOOR_ID = 'cvc_cn_ind_2025_ytd_0922'
APPROX_ID = 'cvc_cn_ind_2023_annual'


class Run:
    def __init__(self, args):
        self.args = args
        self.art = args.report.parent / (args.report.stem + '-evidence')
        self.art.mkdir(parents=True, exist_ok=True)
        self.checks, self.errors, self.downloads, self.screenshots, self.requests = [], [], [], [], []
        self.contexts, self.index, self.source_rows = {}, {}, {}
        self.started = time.time()

    def check(self, name, passed, detail=None):
        row = dict(check=name, passed=bool(passed))
        if detail is not None:
            row['detail'] = detail
        self.checks.append(row)
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)

    def case(self, name, fn, page=None):
        try:
            fn()
        except Exception as exc:
            self.check(name + ' completes', False, str(exc)[:1800])
            if page and not page.is_closed():
                self.shot(page, 'failure-' + re.sub(r'[^a-z0-9-]', '-', name.lower()))

    def watch(self, page, scope):
        page.on('pageerror', lambda error: self.errors.append(dict(scope=scope, error=str(error))))
        page.on('console', lambda message: self.errors.append(dict(scope=scope, error=message.text))
                if message.type == 'error' else None)
        page.on('request', lambda request: self.requests.append(dict(scope=scope, url=request.url,
                                                                    type=request.resource_type)))

    def ready(self, page):
        page.wait_for_function('!!window.VISA_WORKBENCH', timeout=30000)
        page.wait_for_selector('.chart-stage', timeout=15000)

    def context(self, page, code):
        if code not in self.contexts:
            manifest = self.index['countryContext'][code]
            url = urljoin(self.data_base, 'data/' + manifest['file'])
            response = page.request.get(url)
            assert response.ok, (code, response.status, url)
            self.contexts[code] = json.loads(gzip.decompress(response.body()))
        return self.contexts[code]

    def close(self, page):
        button = page.locator('dialog').get_by_role('button', name='关闭面板', exact=True)
        if button.count():
            button.click()
            page.wait_for_selector('dialog', state='detached')

    def open(self, page, code, year=2025):
        self.close(page)
        page.evaluate('(p)=>VISA_WORKBENCH.update(p)', dict(countries=[code], focusCountry=code,
                      year=year, view='single', flowScope='connected', singleMode='radial',
                      spatialScale='country', motionMode='analysis', playing=False))
        page.wait_for_function('(p)=>VISA_WORKBENCH.state.focusCountry===p.code&&VISA_WORKBENCH.state.year===p.year&&VISA_WORKBENCH.state.view==="single"',
                               arg=dict(code=code, year=year))
        page.locator('[data-testid="country-summary"] button').click()
        page.locator('.profile-tabs').get_by_role('button', name='签证与出入境', exact=True).click()
        page.wait_for_function('!document.querySelector(".context-state[role=status]")')
        page.wait_for_selector('.country-context,.context-state,.context-member-view')

    def pick(self, page, series, partner):
        page.get_by_label('选择背景指标', exact=True).select_option(series['id'])
        page.get_by_label('选择背景来源', exact=True).select_option(partner['code'])
        page.wait_for_function('(p)=>document.querySelector(".context-overview h3")?.textContent===p', arg=series['label'])
        page.wait_for_timeout(100)

    @staticmethod
    def points(partner):
        return sorted(partner['points'], key=lambda p: (p['period_end'], p['period_start']))

    def find_point(self, page, code, oid):
        data = self.context(page, code)
        for series in data['series']:
            for partner in series['partners']:
                for point in partner['points']:
                    if point['observation_id'] == oid:
                        return series, partner, point
        raise AssertionError(f'missing context observation {oid}')

    def select_point(self, page, series, partner, point, method='slider'):
        points = self.points(partner)
        position = next(i for i, p in enumerate(points) if p['observation_id'] == point['observation_id'])
        if method == 'plot' or len(points)==1:
            page.locator('.context-plot-point').nth(position).locator('circle').click(force=True)
        else:
            slider = page.get_by_role('slider', name='选择背景数据期间', exact=True)
            slider.focus()
            # Moving both endpoints also selects the first observation when a
            # missing main year leaves the slider at0 without an active point.
            slider.press('End')
            slider.press('Home')
            for _ in range(position):
                slider.press('ArrowRight')
        page.wait_for_function('(v)=>document.querySelector(".context-period-picker input")?.value===String(v)', arg=position)
        return self.display_matches(page, series, point)

    def display_matches(self, page, series, point):
        expected = page.evaluate('({p,s})=>{const n=new Intl.NumberFormat("zh-CN",{maximumFractionDigits:2});const exact=new Intl.NumberFormat("zh-CN",{maximumFractionDigits:s.domain==="rate"?2:1});return s.domain==="rate"||p.value<10000?exact.format(p.value):p.value>=1e8?n.format(p.value/1e8)+"亿":n.format(p.value/10000)+"万";}',
                                 dict(p=point, s=series))
        strong = page.locator('.context-keyfigure strong').inner_text()
        period = page.locator('.context-keyfigure>div>span').first.inner_text()
        correct_period = point['period_start'][:7] in period if 'month' in series['period_type'] else str(point['year']) in period
        active = page.locator('.context-plot-point.active title').text_content()
        return expected in strong and correct_period and bool(active)

    def plot(self, page, series, partner, label):
        expected = len(partner['points'])
        geometry = page.locator('.context-trend>svg[role="img"]').evaluate('''svg=>{
          const points=[...svg.querySelectorAll('.context-plot-point circle')].map(c=>({x:Number(c.getAttribute('cx')),y:Number(c.getAttribute('cy'))}));
          const paths=[...svg.querySelectorAll('path[stroke]')].map(p=>p.getAttribute('d'));
          return {label:svg.getAttribute('aria-label'),points,paths,viewBox:svg.viewBox.baseVal.width};
        }''')
        self.check(label + ' renders real finite trend geometry for every archived point',
                   len(geometry['points']) == expected and expected > 0 and
                   all(math.isfinite(p['x']) and math.isfinite(p['y']) for p in geometry['points']) and
                   bool(geometry['paths']) and all(path and 'NaN' not in path for path in geometry['paths']) and
                   series['label'] in geometry['label'],
                   dict(points=expected, paths=len(geometry['paths']), aria_label=geometry['label']))
        return geometry

    def shot(self, page, name):
        path = self.art / (name + '.png')
        page.screenshot(path=str(path), full_page=True)
        self.screenshots.append(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path))

    def export(self, page, code, series, partner, name):
        with page.expect_download(timeout=10000) as download:
            page.locator('.context-actions').get_by_role('button', name=re.compile('导出这条序列|已导出 CSV')).click()
        item = download.value
        path = self.art / (name + '.csv')
        item.save_as(str(path))
        raw = path.read_bytes()
        rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        points = self.points(partner)
        errors = []
        if len(rows) != len(points):
            errors.append(dict(reason='row count', expected=len(points), actual=len(rows)))
        for row, point in zip(rows, points):
            expected = dict(country=code, series=series['label'], metric=series['metric'], domain=series['domain'],
                            partner=partner['code'], partner_name=partner['name'], unit=series['unit'], **point)
            for key, value in expected.items():
                if isinstance(value, (dict, list)):
                    try:
                        actual = json.loads(row.get(key, ''))
                    except (TypeError, ValueError):
                        errors.append(dict(oid=point['observation_id'], key=key,
                                           reason='structured CSV field is not valid JSON', actual=row.get(key)))
                        continue
                    if actual != value:
                        errors.append(dict(oid=point['observation_id'], key=key, expected=value, actual=actual))
                    continue
                if isinstance(value, bool):
                    value = str(value).lower()
                if value is not None and str(value) != row.get(key):
                    # JS exports integer-valued numbers without Python's .0.
                    if isinstance(value, (int,float)) and row.get(key) and float(row[key]) == value:
                        continue
                    errors.append(dict(oid=point['observation_id'], key=key, expected=value, actual=row.get(key)))
            original = self.source_rows.get(point['observation_id'])
            if original is None:
                errors.append(dict(oid=point['observation_id'], reason='missing original observation'))
            else:
                for key in ('value','period_start','period_end','source_id','lower','upper','bound_type',
                            'lower_inclusive','source_status','source_total_discrepancy'):
                    if point.get(key) != original.get(key):
                        errors.append(dict(oid=point['observation_id'], key=key, reason='differs from source observation'))
                quality = original.get('quality_issue') or (original.get('source_total_discrepancy') or {}).get('interpretation')
                if point.get('quality_issue') != quality:
                    errors.append(dict(oid=point['observation_id'], key='quality_issue', reason='differs from source quality flag'))
        self.check(name + ' CSV equals selected series and original source values, periods and bounds', not errors,
                   dict(rows=len(rows), filename=item.suggested_filename, errors=errors[:8]))
        self.downloads.append(dict(path=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                                   suggested_filename=item.suggested_filename, rows=len(rows), bytes=len(raw),
                                   sha256=hashlib.sha256(raw).hexdigest()))
        return rows

    def gaps(self, geometry, points, label):
        """Compare rendered stroke segments with actual missing-period breaks."""
        expected = []
        for i, point in enumerate(points):
            gap = i and (date.fromisoformat(point['period_end']) -
                         date.fromisoformat(points[i-1]['period_end'])).days > 45
            if i == 0 or gap:
                expected.append([])
            expected[-1].append(geometry['points'][i])
        actual = [[dict(x=float(x), y=float(y)) for x, y in
                   re.findall(r'[ML](-?[\d.eE+]+),(-?[\d.eE+]+)', path)]
                  for path in geometry['paths']]
        matches = len(actual) == len(expected) and all(
            len(a) == len(e) and all(math.isclose(p['x'], q['x'], abs_tol=1e-6) and
                                    math.isclose(p['y'], q['y'], abs_tol=1e-6)
                                    for p, q in zip(a, e)) for a, e in zip(actual, expected))
        self.check(label + ' stroke stops at missing-month gaps instead of joining them',
                   matches and len(expected) > 1,
                   dict(expected_segment_lengths=[len(s) for s in expected],
                        rendered_segment_lengths=[len(s) for s in actual]))

    def sources(self, page, series, label):
        page.locator('.context-actions').get_by_role('button', name='查看来源', exact=True).click()
        page.wait_for_selector('.source-items article')
        ids = page.locator('.source-items article code').all_text_contents()
        expected = set(series['source_ids'])
        links = page.locator('.source-items article').evaluate_all('''items=>items.map(a=>({id:a.querySelector('code')?.textContent,url:a.querySelector('a')?.getAttribute('href'),target:a.querySelector('a')?.getAttribute('target')}))''')
        registry = {s['source_id']:s for s in self.index['sources']}
        self.check(label + ' source panel opens exactly the selected metric sources and original URLs',
                   set(ids) == expected and all(r['url'] == registry[r['id']]['url'] and r['target']=='_blank' for r in links),
                   dict(source_ids=ids, links=links))

    def china(self, page):
        self.open(page, 'CHN')
        self.check('single-country summary opens a real context tab with independent counts',
                   page.locator('.country-context').count() == 1 and
                   '背景序列独立于费用账' in page.locator('.context-definition').inner_text())
        selected = page.get_by_label('选择背景指标', exact=True).input_value()
        default = next(s for s in self.context(page,'CHN')['series'] if s['id']==selected)
        self.check('China default avoids conflict and unidentified-period alternatives',
                   default.get('context_selection_default') is not False and '冲突' not in default['label'])
        series, partner, point = self.find_point(page, 'CHN', FLOOR_ID)
        self.pick(page,series,partner)
        self.check('China 265000 is a strict dated floor rather than an annual actual',
                   point['value']==265000 and point['period_end']=='2025-09-22' and point.get('lower_inclusive') is False and
                   self.select_point(page,series,partner,point) and
                   page.locator('.context-keyfigure strong').inner_text().startswith('> ') and
                   '截止 2025-09-22' in page.locator('.context-keyfigure').inner_text())
        self.plot(page,series,partner,'China floor')
        axis_labels = page.locator('.context-trend svg>text').all_text_contents()
        self.check('China year-to-date axis distinguishes March and September endpoints', '2025-03' in axis_labels and '2025-09' in axis_labels, axis_labels)
        page.locator('.context-evidence summary').click()
        self.check('China floor evidence shows original status, exact dates and observation identity',
                   all(x in page.locator('.context-evidence').inner_text() for x in [FLOOR_ID,'原文累计下限','2025-09-22']))
        self.export(page,'CHN',series,partner,'china-dated-floor')
        self.shot(page,'desktop-china-floor')
        self.sources(page,series,'China floor')
        self.open(page,'CHN')
        series,partner,point = self.find_point(page,'CHN',APPROX_ID)
        self.pick(page,series,partner)
        self.check('China approximate historical count visibly retains its approximate sign',
                   self.select_point(page,series,partner,point) and page.locator('.context-keyfigure strong').inner_text().startswith('≈ '))
        page.locator('.context-records summary').click()
        row = page.locator('.context-records tbody tr').filter(has_text='2023年')
        self.check('data table preserves approximation rather than presenting a false exact count',
                   row.count()==1 and '≈ 180,000' in row.inner_text())

    def india(self, page):
        self.open(page,'IND',2025)
        data = self.context(page,'IND')
        inbound = next(s for s in data['series'] if s.get('native_series_id')=='india_fta_nationality')
        partner = next(p for p in inbound['partners'] if p['code']=='CHN')
        self.pick(page,inbound,partner)
        self.check('India2025 retains no-record state while the historical trend remains visible',
                   '无记录' in page.locator('.context-keyfigure strong').inner_text() and page.locator('.context-plot-point').count()>1)
        page.locator('.context-keyfigure').get_by_role('button', name=re.compile('查看最新')).click()
        latest = self.points(partner)[-1]
        self.check('latest-period action opens the real 2024 source and can return to missing2025',
                   latest['year']==2024 and self.display_matches(page,inbound,latest))
        geometry1 = self.plot(page,inbound,partner,'India inbound')
        self.export(page,'IND',inbound,partner,'india-inbound-china')
        page.locator('.context-keyfigure').get_by_role('button', name='返回主图 2025 年', exact=True).click()
        self.check('return-to-main-year preserves missing data instead of zero filling',
                   page.locator('.context-keyfigure strong').inner_text()=='无记录')
        other = next(p for p in inbound['partners'] if p['code']=='USA')
        page.get_by_label('选择背景来源',exact=True).select_option(other['code'])
        geometry2 = self.plot(page,inbound,other,'India second nationality')
        self.check('partner selection changes the actual plotted values and source caption',
                   geometry1['paths']!=geometry2['paths'] and other['name'] in page.locator('.context-overview p').inner_text())
        outbound = next(s for s in data['series'] if s.get('native_series_id')=='india_national_departures_destination')
        destination = next(p for p in outbound['partners'] if p['code']=='USA')
        self.pick(page,outbound,destination)
        self.check('outbound metric changes partner meaning to destination',
                   '目的地' in page.locator('.context-selectors label').nth(1).inner_text() and
                   page.locator('.context-overview h3').inner_text()==outbound['label'])
        self.export(page,'IND',outbound,destination,'india-outbound-usa')
        self.shot(page,'desktop-india-partners')

    def recent(self, page, screenshot=True):
        # Montenegro is independently selectable in the existing country UI;
        # Schengen member contexts are exercised through the member selector.
        code='MNE'
        data=self.context(page,code)
        series=next(s for s in data['series'] if 'month' in s['period_type'] and
                    any(p['period_end']=='2026-09-30' for a in s['partners'] for p in a['points']))
        partner=next(a for a in series['partners'] if any(p['period_end']=='2026-09-30' for p in a['points']))
        self.open(page,code,2025)
        self.pick(page,series,partner)
        points=self.points(partner)
        main = next(p for p in reversed(points) if p['year']==2025)
        self.check('monthly context initially matches the main2025 year without hiding2026 data',
                   self.display_matches(page,series,main) and points[-1]['period_end']=='2026-09-30')
        self.plot(page,series,partner,'Recent monthly context')
        slider=page.get_by_role('slider',name='选择背景数据期间',exact=True)
        slider.focus();slider.press('End')
        self.check('monthly slider selects published September2026 without annualizing its value',
                   self.display_matches(page,series,points[-1]) and '2026-09' in page.locator('.context-keyfigure').inner_text() and
                   page.evaluate('VISA_WORKBENCH.state.year')==2025)
        page.get_by_role('button',name='前一期背景数据',exact=True).click()
        self.check('previous-month control updates the selected point and value',self.display_matches(page,series,points[-2]))
        page.get_by_role('button',name='后一期背景数据',exact=True).click()
        self.check('next-month control restores the latest observation and disables at endpoint',
                   self.display_matches(page,series,points[-1]) and page.get_by_role('button',name='后一期背景数据',exact=True).is_disabled())
        self.check('clicking a plotted point selects its original historical observation',
                   self.select_point(page,series,partner,points[0],method='plot'))
        self.export(page,code,series,partner,'recent-montenegro-monthly')
        slider.focus();slider.press('End')
        if screenshot:self.shot(page,'desktop-latest-monthly')
        return code,series,partner

    def americas(self, page):
        self.open(page,'COL',2025)
        data=self.context(page,'COL')
        total=next(s for s in data['series'] if s.get('native_series_id')=='col_visa_total_monthly')
        world=next(p for p in total['partners'] if p['code']=='WORLD')
        points=self.points(world)
        by_year={year:sorted(p['period_start'][5:7] for p in points if p['year']==year)
                 for year in (2025,2026)}
        self.pick(page,total,world)
        self.check('Colombia monthly total preserves107 periods, Jan-Oct2025 and only September2026',
                   len(points)==107 and by_year=={2025:[f'{m:02d}' for m in range(1,11)],2026:['09']} and
                   page.locator('.context-series-count small').inner_text()=='107 期',
                   dict(periods=len(points),months=by_year))
        october=next(p for p in points if p['period_start']=='2025-10-01')
        september=points[-1]
        self.check('Colombia initial2025 selection uses October and shows Chinese issuance units',
                   self.display_matches(page,total,october) and total['unit']=='visa_issuance_events' and
                   total['unit_label']=='次签发' and page.locator('.context-keyfigure small').inner_text()=='次签发')
        geometry=self.plot(page,total,world,'Colombia published monthly total')
        self.gaps(geometry,points,'Colombia monthly total')
        self.check('Colombia September2026 point remains1996 published issuances without zero-filled months',
                   september['period_start']=='2026-09-01' and september['value']==1996 and
                   self.select_point(page,total,world,september,method='plot'))
        self.export(page,'COL',total,world,'colombia-monthly-total')
        nationality=[s for s in data['series'] if s.get('origin_basis')=='passport_nationality' and
                     'month' in s['period_type']]
        codes={p['code'] for s in nationality for p in s['partners']}
        permanent=next(s for s in nationality if s.get('native_series_id')=='col_visa_nationality_permanent_monthly')
        china=next(p for p in permanent['partners'] if p['code']=='CHN')
        self.pick(page,permanent,china)
        national_geometry=self.plot(page,permanent,china,'Colombia China passport nationality')
        self.check('Colombia passport-nationality catalogue has198 distinct codes and CHN changes real values',
                   len(codes)==198 and china['name']=='中国大陆' and len(china['points'])==107 and
                   permanent['origin_basis_label']=='护照国籍' and
                   '护照国籍 · 中国大陆' in page.locator('.context-overview p').inner_text() and
                   geometry['paths']!=national_geometry['paths'],
                   dict(distinct_nationality_codes=len(codes),series_partner_counts={s['native_series_id']:len(s['partners']) for s in nationality}))
        self.export(page,'COL',permanent,china,'colombia-china-passport-monthly')
        self.shot(page,'desktop-colombia-passport-monthly')

        self.open(page,'DOM',2024)
        annual,unknown,point=self.find_point(page,'DOM','amx6_dom_total_2024_annual')
        self.pick(page,annual,unknown)
        self.check('Dominican2024 annual value23736 visibly retains its source-version badge',
                   point['value']==23736 and self.display_matches(page,annual,point) and
                   '来源版本存在差异' in page.locator('.context-keyfigure').inner_text() and
                   unknown['code']=='UNK' and unknown['name']=='申请人国籍未公开' and
                   annual['unit_label']=='次签发')
        page.locator('.context-evidence summary').click()
        evidence=page.locator('.context-evidence').inner_text()
        self.check('Dominican expanded evidence explains6255 leaf sum,6254 printed and6256 later PDF',
                   all(text in evidence for text in ('6255','6254','6256','版本差异')) and
                   point.get('source_total_discrepancy',{}).get('xlsx_leaf_sum')==6255 and
                   point.get('source_total_discrepancy',{}).get('xlsx_printed_total')==6254 and
                   point.get('source_total_discrepancy',{}).get('pdf_printed_total')==6256,
                   dict(evidence=evidence))
        rows=self.export(page,'DOM',annual,unknown,'dominican-annual-version-difference')
        exported=next(r for r in rows if r['observation_id']==point['observation_id'])
        self.check('Dominican annual CSV retains parsed discrepancy JSON and original quality interpretation',
                   json.loads(exported['source_total_discrepancy'])==point['source_total_discrepancy'] and
                   exported.get('quality_issue')==point['source_total_discrepancy']['interpretation'],
                   dict(csv_quality_issue=exported.get('quality_issue')))
        quarters={'amx6_do_17485','amx6_do_17880','amx6_do_18180','amx6_do_18571'}
        self.check('Dominican annual source catalogue includes all four2024 quarter originals',
                   quarters.issubset(annual['source_ids']),dict(required=sorted(quarters),actual=annual['source_ids']))
        self.shot(page,'desktop-dominican-annual-version-difference')
        self.sources(page,annual,'Dominican annual')
        self.open(page,'DOM',2025)
        monthly=next(s for s in self.context(page,'DOM')['series'] if s.get('native_series_id')=='dom_visa_total_monthly')
        unknown=next(p for p in monthly['partners'] if p['code']=='UNK')
        points=self.points(unknown)
        self.pick(page,monthly,unknown)
        months=[p['period_start'][5:7] for p in points if p['year']==2026]
        geometry=self.plot(page,monthly,unknown,'Dominican published monthly total')
        self.check('Dominican2026 contains eight published months and no invented April zero',
                   months==['01','02','03','05','06','07','08','09'] and
                   not any(p['period_start']=='2026-04-01' for p in points),dict(months2026=months))
        self.gaps(geometry,points,'Dominican monthly total')
        self.export(page,'DOM',monthly,unknown,'dominican-monthly-missing-april')

    def americas_mobile(self,page):
        width=320
        page.set_viewport_size(dict(width=width,height=844))
        try:
            self.open(page,'DOM',2024)
            series,partner,point=self.find_point(page,'DOM','amx6_dom_total_2024_annual')
            self.pick(page,series,partner)
            page.locator('.context-evidence summary').click()
            page.locator('.context-records summary').click()
            geometry=page.evaluate('''()=>{const d=document.querySelector('dialog'),r=e=>{const b=e.getBoundingClientRect();return {left:b.left,right:b.right,width:b.width,scrollWidth:e.scrollWidth,clientWidth:e.clientWidth,text:e.textContent?.slice(0,140)};};return {document:document.documentElement.scrollWidth,dialog:r(d),text:[...d.querySelectorAll('.context-evidence,.context-evidence p,.context-evidence dd,.context-keyfigure,.context-actions')].map(r),controls:[...d.querySelectorAll('.context-selectors select,.context-actions button,.context-period-picker input')].map(r)};}''')
            clipped=[g for g in geometry['text']+geometry['controls'] if g['left'] < -1 or
                     g['right'] > width+1 or g['scrollWidth'] > g['clientWidth']+1]
            self.check('320px Dominican long version explanation and controls wrap inside the viewport',
                       geometry['document']<=width+1 and geometry['dialog']['width']<=width+1 and not clipped,
                       dict(geometry=geometry,clipped=clipped))
            self.check('320px Dominican expanded version explanation remains readable with all three values',
                       self.display_matches(page,series,point) and
                       all(v in page.locator('.context-evidence').inner_text() for v in ('6255','6254','6256')))
            page.locator('dialog .drawer-inner').evaluate('e=>e.scrollTop=0')
            self.shot(page,'mobile-320-dominican-version-difference')
            page.locator('.context-evidence').scroll_into_view_if_needed()
            self.shot(page,'mobile-320-dominican-version-evidence')
        finally:
            page.set_viewport_size(dict(width=1440,height=1000))

    def schengen(self,page):
        self.open(page,'SCH')
        selector=page.get_by_label('选择申根成员背景',exact=True)
        members=[o.get_attribute('value') for o in selector.locator('option').all()]
        expected=set(self.index['schengenMembers'])&set(self.index['countryContext'])
        self.check('Schengen uses actual member context rather than displaying an EU aggregate',
                   set(members)==expected and '欧盟总计与申根范围分别识别' in page.locator('.context-member-view').inner_text())
        for code in ('DEU','FRA'):
            selector.select_option(code)
            data=self.context(page,code)
            page.wait_for_function('(n)=>document.querySelectorAll(".country-context select[aria-label=选择背景指标] option").length===n',arg=len(data['series']))
            options=page.get_by_label('选择背景指标',exact=True).locator('option').all_text_contents()
            self.check('Schengen member '+code+' loads its own metric catalogue and finite graph',
                       len(options)==len(data['series']) and page.locator('.context-plot-point').count()>0,
                       dict(series=len(options),selected_member=selector.input_value()))
        self.shot(page,'desktop-schengen-member')

    def usa(self,page):
        self.open(page,'USA')
        series,partner,point=self.find_point(page,'USA','usr6_niv_estimated_applications_fy2025')
        self.pick(page,series,partner)
        self.check('US applications visibly retain official estimate label and exact fiscal dates',
                   '申请估算' in page.locator('.context-overview h3').inner_text() and
                   '2024-10-01' in page.locator('.context-keyfigure').inner_text() and
                   '2025-09-30' in page.locator('.context-keyfigure').inner_text())
        self.plot(page,series,partner,'US fiscal estimates')
        page.locator('.context-evidence summary').click()
        self.check('US estimate source evidence exposes original displayed precision',
                   all(t in page.locator('.context-evidence').inner_text() for t in ['来源显示精度','10,000','13.54','million']))
        self.export(page,'USA',series,partner,'usa-fiscal-estimates')
        series,partner,point=self.find_point(page,'USA','usr6_niv_applications_location_CHN_fy2025')
        self.pick(page,series,partner)
        self.check('US consular locations can switch independently without claiming payer nationality',
                   len(series['partners'])==4 and '受理领事所在地' in page.locator('.context-overview').inner_text() and
                   '中国香港' in page.get_by_label('选择背景来源',exact=True).locator('option:checked').inner_text())
        self.export(page,'USA',series,partner,'usa-china-location')
        self.shot(page,'desktop-usa-consular-location')

    def empty(self,page):
        candidates=[e['code'] for e in self.index['entities'] if e.get('kind')=='country_or_jurisdiction' and e['code'] not in self.index['countryContext']]
        code='LBR' if 'LBR' in candidates else candidates[0]
        self.open(page,code)
        self.check('country without context shows an explicit empty state and no invented graph',
                   '当前尚未归档' in page.locator('.context-state').inner_text() and
                   '费用收付和人口折算' in page.locator('.context-state').inner_text() and
                   page.locator('.country-context,.context-trend').count()==0,dict(code=code))

    def mobile(self,page):
        for width in (390,320):
            page.set_viewport_size(dict(width=width,height=844))
            self.open(page,'CHN')
            series,partner,point=self.find_point(page,'CHN',FLOOR_ID)
            self.pick(page,series,partner)
            self.select_point(page,series,partner,point)
            page.locator('.context-evidence summary').click()
            page.locator('.context-records summary').click()
            geometry=page.evaluate('''()=>{const d=document.querySelector('dialog'),svg=document.querySelector('.context-trend svg'),r=e=>{const b=e.getBoundingClientRect();return {left:b.left,right:b.right,width:b.width,scrollWidth:e.scrollWidth,clientWidth:e.clientWidth};};return {viewport:innerWidth,document:document.documentElement.scrollWidth,dialog:r(d),svg:r(svg),controls:[...d.querySelectorAll('.context-selectors select,.context-actions button,.context-keyfigure strong,.context-period-picker input')].map(r),texts:[...svg.querySelectorAll('text')].map(e=>({...r(e),text:e.textContent}))};}''')
            clipped=[g for g in geometry['controls']+geometry['texts'] if g['left'] < -1 or g['right'] > width+1]
            self.check(f'{width}px context controls, values and chart labels fit the viewport',
                       geometry['document']<=width+1 and geometry['dialog']['width']<=width+1 and
                       geometry['svg']['width']>200 and not clipped,
                       dict(geometry=geometry,clipped=clipped))
            self.check(f'{width}px mobile keeps the floor evidence and usable period controls',
                       '2025-09-22' in page.locator('.context-evidence').inner_text() and
                       page.get_by_role('slider',name='选择背景数据期间',exact=True).is_visible())
            page.locator('dialog .drawer-inner').evaluate('e=>e.scrollTop=0')
            self.shot(page,f'mobile-{width}-china-context')
        page.set_viewport_size(dict(width=1440,height=1000))

    def offline(self,browser):
        context=browser.new_context(accept_downloads=True,reduced_motion='reduce',viewport=dict(width=1440,height=1000))
        context.set_offline(True)
        page=context.new_page();self.watch(page,'offline')
        page.goto(self.args.offline_file.resolve().as_uri(),wait_until='load')
        self.ready(page)
        embedded=page.evaluate('({version:VISA_WORKBENCH.index.meta.version,codes:Object.keys(window.__VISA_CONTEXT__||{}),manifest:Object.keys(VISA_WORKBENCH.index.countryContext||{})})')
        self.check('file offline embeds every context chunk and the final index revision',
                   page.url.startswith('file:') and embedded['version']==self.index['meta']['version'] and
                   set(embedded['codes'])==set(embedded['manifest'])==set(self.index['countryContext']),
                   dict(version=embedded['version'],embedded_countries=len(embedded['codes'])))
        self.open(page,'CHN')
        series,partner,point=self.find_point(page,'CHN',FLOOR_ID)
        self.pick(page,series,partner)
        self.check('file offline decompresses China context and retains dated strict-floor semantics',
                   self.select_point(page,series,partner,point) and page.locator('.context-keyfigure strong').inner_text().startswith('> '))
        self.export(page,'CHN',series,partner,'offline-china-floor')
        self.sources(page,series,'Offline China')
        self.recent(page,screenshot=False)
        self.shot(page,'offline-latest-monthly')
        remote=[r for r in self.requests if r['scope']=='offline' and r['url'].startswith(('http:','https:'))]
        self.check('file context interaction, source panel and CSV exports make zero HTTP requests',not remote,dict(http_requests=remote))
        context.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:18765/app/')
    parser.add_argument('--report',type=Path,default=ROOT/'docs/validation/r10-context-browser.json')
    parser.add_argument('--offline-file',type=Path,default=ROOT/'app/签证这笔钱-离线版.html')
    args=parser.parse_args()
    args.url=args.url.rstrip('/')+'/'
    args.report=args.report.resolve()
    run=Run(args)
    # Compare real downloaded CSV rows to the source observation registry, not
    # merely to the same rendered text that produced the download.
    observations=json.loads((ROOT/'data/processed/observations.json').read_text())
    run.source_rows={r['observation_id']:r for r in observations}
    del observations
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=str(CHROMIUM) if CHROMIUM.is_file() else None,headless=True)
        context=browser.new_context(accept_downloads=True,reduced_motion='reduce',viewport=dict(width=1440,height=1000))
        page=context.new_page();page.set_default_timeout(12000);run.watch(page,'online')
        page.goto(args.url,wait_until='load');run.ready(page)
        run.data_base=page.evaluate('document.baseURI')
        run.index=page.evaluate('VISA_WORKBENCH.index')
        for name,fn in [('china',run.china),('india',run.india),('recent',run.recent),
                        ('americas',run.americas),('usa',run.usa),('schengen',run.schengen),('empty',run.empty),
                        ('mobile',run.mobile),('americas-mobile',run.americas_mobile)]:
            run.case(name,lambda fn=fn:fn(page),page)
        run.case('offline',lambda:run.offline(browser))
        run.check('focused context scenarios produce no browser runtime or console errors',not run.errors,run.errors)
        browser.close()
    report=dict(passed=all(c['passed'] for c in run.checks),url=args.url,
                version=run.index['meta']['version'],ui_version=run.index['meta'].get('ui_version'),
                elapsed_seconds=round(time.time()-run.started,1),checks=run.checks,
                downloads=run.downloads,screenshots=run.screenshots,errors=run.errors,
                offline_file=str(args.offline_file.resolve()),
                validation_boundary='Real Chromium CountryContext interactions, raw-source-matched CSV and network-disabled file operation. Existing global visualization tests are not repeated.')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('checks','downloads','screenshots','errors')},ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
