#!/usr/bin/env python3
"""Focused browser checks for the r11 primary-statistics expansion.

Run after the final data/UI build. Reuses the country-context browser harness;
every export is a real browser download checked against native observations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

from verify_country_context_browser import CHROMIUM, ROOT, Run


class ExpansionRun(Run):
    def series(self, page, code, native):
        matches = [s for s in self.context(page, code)['series'] if s.get('native_series_id') == native]
        assert len(matches) == 1, (code, native, [s['id'] for s in matches])
        return matches[0]

    @staticmethod
    def partner(series, code):
        return next(p for p in series['partners'] if p['code'] == code)

    def exercise(self, page, code, series, partner, label, years=None, export=True):
        self.pick(page, series, partner)
        points = self.points(partner)
        selected = [p for p in points if not years or p['year'] in years]
        assert selected, (code, label, years)
        self.check(label + ' shows source-basis caption and selected partner',
                   partner['name'] in page.locator('.context-overview').inner_text() and
                   (partner['code'] == 'WORLD' or series['origin_basis_label'] in page.locator('.context-overview').inner_text()))
        for point in selected:
            self.check(label + ' selects original period ' + point['period_end'],
                       self.select_point(page, series, partner, point))
        self.plot(page, series, partner, label)
        if export:
            rows = self.export(page, code, series, partner, label)
            self.check(label + ' CSV retains original origin basis',
                       all(r.get('origin_basis') == series['origin_basis'] for r in rows), series['origin_basis'])
        return points

    def usa(self, page):
        self.open(page, 'USA', 2024)
        series = self.series(page, 'USA', 'core_us_issued_B1/B2')
        world = self.partner(series, 'WORLD')
        points = self.points(world)
        self.check('US B1/B2 has FY2020–24 world counts and exact fiscal boundaries',
                   [p['year'] for p in points] == list(range(2020, 2025)) and
                   all(p['period_start'] == f"{p['year']-1}-10-01" and
                       p['period_end'] == f"{p['year']}-09-30" for p in points) and
                   points[-1]['observation_id'] == 'us_2024_grand_total_b1_b2_visas_issued',
                   dict(years=[p['year'] for p in points], values=[p['value'] for p in points]))
        self.exercise(page, 'USA', series, world, 'usa-b1b2-world')
        for code, value in [('CHN', 645977), ('IND', 898754)]:
            partner = self.partner(series, code)
            self.check('US B1/B2 FY2024 nationality ' + code + ' equals source',
                       len(partner['points']) == 1 and partner['points'][0]['value'] == value and series['origin_basis'] == 'nationality')
            self.exercise(page, 'USA', series, partner, 'usa-b1b2-' + code.lower())
        self.shot(page, 'desktop-us-b1b2-nationality')
        self.sources(page, series, 'US B1/B2')

    def japan(self, page):
        self.open(page, 'JPN')
        series = self.series(page, 'JPN', 'core_jp_nationality_all_issued')
        world = self.partner(series, 'WORLD')
        points = self.points(world)
        self.check('Japan all-category world series spans every year 2011–25',
                   [p['year'] for p in points] == list(range(2011, 2026)) and
                   points[-1]['value'] == 7862060 and series['origin_basis'] == 'nationality_region_or_document_as_published',
                   dict(years=[p['year'] for p in points], latest=points[-1]['value']))
        self.exercise(page, 'JPN', series, world, 'japan-all-world', [2011, 2020, 2024, 2025])
        self.exercise(page, 'JPN', series, self.partner(series, 'CHN'), 'japan-china-mainland', [2011, 2025])
        for code, value in [('HKG', 3115), ('HKG:JP:china_hongkong_document', 12), ('MAC', 169)]:
            partner = self.partner(series, code)
            point = next(p for p in partner['points'] if p['year'] == 2025)
            self.check('Japan 2025 document row remains independent ' + code,
                       point['value'] == value and ('中国香港' if code.startswith('HKG') else '中国澳门') in partner['name'],
                       dict(partner=partner['name'], value=point['value']))
            self.exercise(page, 'JPN', series, partner, 'japan-' + code.lower().replace(':', '-'), [2025])
        for prefix in ['HKG:JP:DI', 'HKG:JP:british_document', 'MAC:JP:travel_document']:
            self.check('Japan preserves historical document partner ' + prefix,
                       any(p['code'] == prefix for p in series['partners']))
        self.shot(page, 'desktop-japan-documents')
        self.sources(page, series, 'Japan all-category history')

    def britain(self, page):
        self.open(page, 'GBR')
        for metric in ['Applications', 'Issued']:
            series = self.series(page, 'GBR', 'core_uk_Visitor_' + metric)
            for code in ['CHN', 'IND']:
                partner = self.partner(series, code)
                self.check('UK visitor ' + metric + ' ' + code + ' retains distinct 2024/25 annual points',
                           [p['year'] for p in self.points(partner)] == [2024, 2025] and series['origin_basis'] == 'nationality')
                self.exercise(page, 'GBR', series, partner, 'uk-visitor-' + metric.lower() + '-' + code.lower())
        self.shot(page, 'desktop-uk-visitor')
        self.sources(page, series, 'UK visitor applications and issuance')

    def canada(self, page):
        self.open(page, 'CAN')
        series = self.series(page, 'CAN', 'core_ca_Visitor V-1_Approved')
        self.check('Canada approvals preserve source-country basis',
                   series['origin_basis'] == 'source_country_as_published' and '来源国' in series['origin_basis_label'],
                   series['origin_basis_label'])
        for code, values in [('CHN', [254375, 195115]), ('IND', [506075, 303075])]:
            partner = self.partner(series, code)
            points = self.points(partner)
            self.check('Canada visitor approvals ' + code + ' equals native 2024/25 totals',
                       [p['year'] for p in points] == [2024, 2025] and [p['value'] for p in points] == values)
            self.exercise(page, 'CAN', series, partner, 'canada-visitor-approved-' + code.lower())
        self.shot(page, 'desktop-canada-source-country')
        self.sources(page, series, 'Canada source-country approvals')

    def armenia(self, page):
        self.open(page, 'ARM', 2024)
        selected = page.get_by_label('选择背景指标', exact=True).input_value()
        default = next(s for s in self.context(page, 'ARM')['series'] if s['id'] == selected)
        self.check('Armenia default excludes conflicting government-draft series', default.get('context_selection_default') is not False)
        old, old_partner, old_point = self.find_point(page, 'ARM', 'mev7_ARM_2023_national_short_stay_visas_issued')
        new, new_partner, new_point = self.find_point(page, 'ARM', 'mev7_ARM_2024_national_short_stay_visas_issued')
        self.check('Armenia definition break stays in separate original series',
                   old['id'] != new['id'] and old_point['value'] == 38121 and new_point['value'] == 146001 and
                   len(old_partner['points']) == len(new_partner['points']) == 1,
                   dict(old=old['label'], new=new['label']))
        self.exercise(page, 'ARM', old, old_partner, 'armenia-short-2023-definition')
        self.exercise(page, 'ARM', new, new_partner, 'armenia-short-2024-definition')
        for code in ['IND', 'PHL']:
            series, partner, point = self.find_point(page, 'ARM', 'mev7_ARM_2024_national_short_stay_visas_issued_by_citizenship_' + code)
            self.exercise(page, 'ARM', series, partner, 'armenia-short-nationality-' + code.lower())
        series, partner, point = self.find_point(page, 'ARM', 'mev7_arm_ind_2023')
        self.exercise(page, 'ARM', series, partner, 'armenia-government-draft-conflict', [2022, 2023])
        page.locator('.context-evidence summary').click()
        self.check('Armenia source conflict is nondefault and readable in the actual evidence panel',
                   series.get('context_selection_default') is False and point.get('quality_issue') and
                   '口径或来源冲突' in page.locator('.context-evidence').inner_text())
        self.shot(page, 'desktop-armenia-definition-conflict')
        self.sources(page, series, 'Armenia government-draft original')

    def moldova(self, page):
        self.open(page, 'MDA', 2024)
        series, partner, point = self.find_point(page, 'MDA', 'mev7_MDA_2024_national_short_stay_visas_issued')
        points = self.points(partner)
        self.check('Moldova short-stay sequence preserves 2021–24 published values',
                   [p['year'] for p in points] == [2021, 2022, 2023, 2024] and
                   [p['value'] for p in points] == [1093, 4873, 2790, 2149])
        self.exercise(page, 'MDA', series, partner, 'moldova-short-stay')
        for code in ['CHN', 'IND']:
            s, p, point = self.find_point(page, 'MDA', 'mev7_MDA_2024_national_short_stay_visas_issued_by_citizenship_' + code)
            self.exercise(page, 'MDA', s, p, 'moldova-nationality-' + code.lower())
        self.shot(page, 'desktop-moldova-nationality')
        self.pick(page, series, partner)
        self.sources(page, series, 'Moldova short-stay factsheet history')

    def oman(self, page):
        self.open(page, 'OMN')
        series, partner, point = self.find_point(page, 'OMN', 'mev7_omn_2025_tourism_visa_entries')
        points = self.points(partner)
        self.check('Oman 2016–25 remains border-entry events rather than visa grants',
                   series['domain'] == 'mobility' and series['unit'] == 'border_entry_events' and
                   series['metric'] == 'inbound_entries_using_tourism_visa' and
                   [p['year'] for p in points] == list(range(2016, 2026)))
        self.exercise(page, 'OMN', series, partner, 'oman-tourism-visa-border-entries', [2016, 2020, 2024, 2025])
        for year, status, label in [(2024, 'provisional', '暂定值'), (2025, 'preliminary', '初步值')]:
            point = next(p for p in points if p['year'] == year)
            self.select_point(page, series, partner, point)
            evidence = page.locator('.context-evidence')
            if not evidence.get_attribute('open') == '':
                evidence.locator('summary').click()
            self.check('Oman ' + str(year) + ' source status and precision survive UI and archived point',
                       point.get('source_status') == status and point.get('source_status_label') == label and
                       point.get('source_rounding_unit') == 100 and point.get('source_rounding_half_unit') == 50 and
                       point.get('original_value') * 1000 == point['value'] and
                       label in evidence.inner_text() and '100' in evidence.inner_text() and 'thousand visitors/entry events' in evidence.inner_text())
            original = self.source_rows[point['observation_id']]
            self.check('Oman ' + str(year) + ' context preserves original precision/status fields',
                       all(point.get(k) == original.get(k) for k in ['original_value', 'original_unit', 'source_rounding_unit', 'source_rounding_half_unit', 'source_status', 'source_status_label']))
        self.shot(page, 'desktop-oman-precision-status')
        self.sources(page, series, 'Oman tourism-visa border entries')

    def philippines(self, page):
        self.open(page, 'PHL', 2024)
        series = self.series(page, 'PHL', 'phl_bi_non_board_within_six_days_quarterly')
        partner = series['partners'][0]
        points = self.points(partner)
        self.check('Philippines six-day processing series keeps its narrow transaction scope',
                   series['metric'] == 'non_board_action_transactions_within_six_days' and
                   series['unit'] == 'transaction_events' and '无需Board Action' in series['label'] and
                   '六日内办结' in series['label'] and '签发' not in series['label'])
        self.exercise(page, 'PHL', series, partner, 'philippines-non-board-six-day-quarterly', [points[0]['year'], points[-1]['year']])
        point = next(p for p in points if p['period_start'] == '2020-04-01')
        self.check('Philippines specific 2020 Q2 point can be selected directly in plot',
                   point['value'] == 160 and self.select_point(page, series, partner, point, method='plot'))
        self.shot(page, 'desktop-philippines-narrow-processing')
        self.sources(page, series, 'Philippines narrow processing series')

    def nepal(self, page):
        self.open(page, 'NPL')
        doi = [s for s in self.context(page, 'NPL')['series'] if s.get('native_series_id', '').startswith('sv7_npl_doi_')]
        self.check('Nepal DOI exposes 18 distinct metrics and 218 independent source partners',
                   len({s['native_series_id'] for s in doi}) == 18 and
                   len({p['code'] for s in doi for p in s['partners']}) == 218)
        series, partner, point = self.find_point(page, 'NPL', 'sv7_npl_es_2025_consular_gratis')
        self.check('Nepal published global consular-gratis count remains an independent free category',
                   point['value'] == 754 and '免费' in series['label'] and partner['code'] == 'WORLD')
        self.exercise(page, 'NPL', series, partner, 'nepal-economic-survey-consular-gratis', [2025])
        self.sources(page, series, 'Nepal economic-survey free category')
        self.open(page, 'NPL')
        for category, value, label in [('consular_gratis', 60, '免费'), ('non_tourist_other', 39, '非旅游')]:
            series, partner, point = self.find_point(page, 'NPL', 'sv7_npl_doi2025_r40_' + category)
            self.check('Nepal CHN ' + category + ' preserves the original category count',
                       point['value'] == value and partner['code'] == 'CHN' and partner['name'] == '中国大陆' and
                       label in series['label'] and series['origin_basis'] == 'nationality')
            self.exercise(page, 'NPL', series, partner, 'nepal-china-' + category, [2025])
        series, partner, point = self.find_point(page, 'NPL', 'sv7_npl_doi2025_r40_all')
        self.exercise(page, 'NPL', series, partner, 'nepal-china-published-total', [2025])
        self.check('Nepal CHN 2025 retains the published total without replacing it by category sum',
                   point['value'] == 101234 and point['source_id'] == 'sv7_npl_doi2026' and
                   all(text in point.get('quality_issue', '') for text in ['100915', '319', '863684', '592']))
        self.shot(page, 'desktop-nepal-china-published-total')
        page.locator('.context-evidence summary').click()
        page.locator('.context-records summary').click()
        self.check('Nepal actual evidence and table show 2025 original count and source arithmetic issue',
                   point['quality_issue'] in page.locator('.context-evidence').inner_text() and
                   'sv7_npl_doi2025_r40_all' in page.locator('.context-evidence').inner_text() and
                   '101,234' in page.locator('.context-records').inner_text() and
                   '来源版本存在差异' in page.locator('.context-keyfigure').inner_text())
        page.locator('.context-evidence').scroll_into_view_if_needed()
        self.shot(page, 'desktop-nepal-china-original-quality')
        for code, name in [('HKG', '中国香港'), ('MAC', '中国澳门'), ('TWN', '中国台湾')]:
            self.check('Nepal DOI jurisdiction partner has the full China display name ' + code,
                       self.partner(series, code)['name'] == name)
        duplicates = sorted([p for p in series['partners'] if p['code'].startswith('LAO:')], key=lambda p: p['code'])
        self.check('Nepal repeated source-country ISO rows keep distinct identifiers and native totals',
                   len(duplicates) == 2 and len({p['code'] for p in duplicates}) == 2 and
                   sorted(p['points'][0]['value'] for p in duplicates) == [215, 494] and
                   len({p['name'] for p in duplicates}) == 2,
                   [dict(code=p['code'], name=p['name'], value=p['points'][0]['value']) for p in duplicates])
        for i, duplicate in enumerate(duplicates, 1):
            self.exercise(page, 'NPL', series, duplicate, 'nepal-lao-original-row-' + str(i), [2025])
        self.pick(page, series, partner)
        self.sources(page, series, 'Nepal DOI independent country/category source rows')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18765/app/')
    countries = dict(USA='usa', JPN='japan', GBR='britain', CAN='canada', ARM='armenia', MDA='moldova', OMN='oman', PHL='philippines', NPL='nepal')
    parser.add_argument('--country', nargs='+', choices=countries, help='Run only selected new country cases; preserve other reports.')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    args.report = args.report or ROOT / 'docs/validation' / ('r11-' + '-'.join(c.lower() for c in args.country) + '-context-browser.json' if args.country else 'r11-expansion-context-browser.json')
    run = ExpansionRun(args)
    observations = json.loads((ROOT / 'data/processed/observations.json').read_text())
    run.source_rows = {r['observation_id']: r for r in observations}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROMIUM) if CHROMIUM.is_file() else None, headless=True)
        context = browser.new_context(accept_downloads=True, reduced_motion='reduce', viewport=dict(width=1440, height=1000))
        page = context.new_page()
        page.set_default_timeout(12000)
        run.watch(page, 'r11-expansion')
        page.goto(args.url, wait_until='load')
        run.ready(page)
        run.data_base = page.evaluate('document.baseURI')
        run.index = page.evaluate('VISA_WORKBENCH.index')
        for name in [countries[c] for c in (args.country or list(countries))]:
            run.case(name, lambda name=name: getattr(run, name)(page), page)
        run.check('expanded country-context cases emit no browser errors', not run.errors, run.errors)
        browser.close()
    report = dict(passed=all(c['passed'] for c in run.checks), url=args.url,
                  version=run.index['meta']['version'], ui_version=run.index['meta'].get('ui_version'),
                  elapsed_seconds=round(time.time() - run.started, 1), checks=run.checks,
                  downloads=run.downloads, screenshots=run.screenshots, errors=run.errors,
                  selected_countries=args.country or list(countries),
                  validation_boundary='Selected new primary-statistics series, real country/partner/period selection, exact source panels and native CSV downloads. Fee-flow visual acceptance is outside this focused check.')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], checks=len(run.checks), downloads=len(run.downloads), report=str(args.report)), ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
