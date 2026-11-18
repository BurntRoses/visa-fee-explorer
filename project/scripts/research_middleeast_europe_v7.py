#!/usr/bin/env python3
"""Rebuild official visa-activity evidence for Armenia and EMN observer countries.

All observations are context only. Visa counts are not application counts,
unique people, payments, or visa-fee receipts. Oman tourism-visa entries are
border events and are deliberately kept outside visa-issuance statistics.
"""
from __future__ import annotations

import csv
from collections import defaultdict
import hashlib
import json
import logging
from pathlib import Path
import re
import sys

from pypdf import PdfReader
from bs4 import BeautifulSoup

sys.dont_write_bytecode = True
logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/middleeast_europe_v7'
OUT = ROOT / 'data/research/middleeast_europe_v7'
CUT = '2026-11-17'
PDFS = {
    'emn23': ('emn_observers_2023.pdf', 'https://www.emn.at/sites/default/files/2024/03/emn-observer-country-statistical-annex-en.pdf',
              'European Migration Network, EMN Observer Country Statistical Annex 2023', '14'),
    'emn24': ('emn_observers_2024.pdf', 'https://www.emn.at/sites/default/files/publications/2024_EMN_Observer_Country_statistical_annex.pdf',
              'European Migration Network, EMN Observer Country Statistical Annex 2024', '17-18'),
    'arm24': ('arm_emn_2024.pdf', 'https://home-affairs.ec.europa.eu/document/download/b9da3d06-5999-416f-9625-d27d95153398_en?filename=2024_EMN-AM_countryfactsheet.pdf',
              'EMN Observer Country Factsheet: Armenia, December 2025', '11'),
    'mda24': ('mda_emn_2024.pdf', 'https://home-affairs.ec.europa.eu/document/download/755c9936-1819-4cf6-8fd8-19389a0a3f1d_en',
              'EMN Observer Country Factsheet: Republic of Moldova, December 2025', '11'),
    'srb24': ('srb_emn_2024.pdf', 'https://home-affairs.ec.europa.eu/document/download/14b0e643-d989-4306-8ad1-d0c8f8b08ff8_en?filename=2024_EMN-RS_countryfactsheet.pdf',
              'EMN Observer Country Factsheet: Serbia, December 2025', '10'),
    'ukr24': ('ukr_emn_2024.pdf', 'https://home-affairs.ec.europa.eu/document/download/2f512909-488c-463b-b512-edd179e2a548_en',
              'EMN Observer Country Factsheet: Ukraine, December 2025', '10'),
    'arm_law': ('arm_state_duty_2023_consolidated.html', 'https://www.arlis.am/en/acts/209221',
                'Armenia Law on State Duty, consolidated through 2023-12-08', 'Articles 8, 14, 15, 26'),
    'arm_india': ('arm_draft_6855_justification.html', 'https://e-draft.am/index.php/en/projects/6855/justification',
                  'Armenia Ministry of Internal Affairs draft justification 6855', 'paragraphs 41-46'),
    'oman26': ('omn_yearbook_2026.pdf', 'https://api.ncsi.gov.om/uploads/pdfs/statistical_year_book_2026___issue_54_1777963604.pdf',
               'Oman Statistical Year Book 2026, NCSI', 'printed p. 21-4 / PDF p. 335'),
}
COUNTRIES = {
    'ARM': ('Armenia', '亚美尼亚'), 'MDA': ('Republic of Moldova', '摩尔多瓦'),
    'MNE': ('Montenegro', '黑山'), 'MKD': ('North Macedonia', '北马其顿'),
    'SRB': ('Serbia', '塞尔维亚'), 'UKR': ('Ukraine', '乌克兰'),
}
NATIONALITIES = {
    'India': ('IND', '印度'), 'Philippines': ('PHL', '菲律宾'), 'Türkiye': ('TUR', '土耳其'),
    'Turkey': ('TUR', '土耳其'), 'Turkmenistan': ('TKM', '土库曼斯坦'),
    'Egypt': ('EGY', '埃及'), 'China': ('CHN', '中国大陆'), 'PR China': ('CHN', '中国大陆'),
    'Nepal': ('NPL', '尼泊尔'), 'Bangladesh': ('BGD', '孟加拉国'), 'USA': ('USA', '美国'), 'Great Britain': ('GBR', '英国'),
    'GB': ('GBR', '英国'), 'United States': ('USA', '美国'),
}
VISA_ROWS_2023 = {
    'ARM': (285737, 247616, 38121), 'MNE': (2672, 808, 1864), 'SRB': (29442, 20276, 9166),
}
VISA_ROWS_2024 = {
    'ARM': (158825, 12824, 146001), 'MDA': (11058, 1100, 2149),
    'MKD': (3678, 1376, 2302), 'SRB': (31513, 22798, 8715), 'UKR': (13770, 10127, 3643),
}
TOP_2024 = {
    'ARM': [('India', 49308, '31.0%'), ('Philippines', 26336, '16.6%'), ('Türkiye', 14325, '9.0%')],
    'MDA': [('China', 316, '2.9%'), ('India', 182, '1.6%'), ('Turkmenistan', 51, '0.5%')],
    'MKD': [('China', 360, '9.8%'), ('Nepal', 270, '7.3%'), ('Bangladesh', 292, '7.9%')],
    'SRB': [('PR China', 1697, '5.4%'), ('India', 756, '2.4%'), ('Egypt', 644, '2.0%')],
    'UKR': [('China', 1562, '11.34%'), ('USA', 1275, '9.26%'), ('Great Britain', 434, '3.15%')],
}
EXPECTED_HASHES = {
    'emn23': '3bb65b645c8cf4f166f19675330e33e526b0d7c39c2f0d235420ad4fcfc97627',
    'emn24': 'aa26c4e4a24f91093162295071f3a724afc3a651eeca653d32abd3452d776963',
    'arm24': '7ffb3d39675dbe0a32536125c29c0a119d98bad2b92a2114119fe24a2f222500',
    'mda24': '5e3a0bac758690ab03127850651fefe438c4396f9bcdb222b673ec90f0eb866e',
    'srb24': 'd3574d07dd14db1968f4aaa9e73a65b853e3995070d92c03a392bb305682e11d',
    'ukr24': '8a6dd965d7eda02b02b960b4fdaf61658c324c7e71e547e1b053474d65acf243',
    'arm_india': '989695450d38e12b335a280d92301d6f262f65c7bfca110f82b90f88f87c0963',
    'arm_law': 'dbd94a2b094e75596722b0c4487d00479e473fdf2c1e2db28715723dab80f578',
    'oman26': '93a4fc2ba4b508ab5b01a7ec5de041529ff284d8ba1b3eab6fe1b0463196f9df',
}


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        fields = list(dict.fromkeys(k for row in obj for k in row))
        with (OUT / name.replace('.json', '.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                         for k, v in row.items()} for row in obj)


def compact(text):
    return re.sub(r'\s+', ' ', text or '').replace('\u00ad', '')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources, observations, checks, exclusions = [], [], [], []
    texts = {}
    for key, (filename, url, title, locator) in PDFS.items():
        path = RAW / filename
        assert path.exists() and path.stat().st_size > 1000, filename
        raw = path.read_bytes()
        checks.append(dict(check=f'original_sha256_{key}', passed=hashlib.sha256(raw).hexdigest() == EXPECTED_HASHES[key]))
        if filename.endswith('.pdf'):
            reader = PdfReader(path)
            texts[key] = '\n'.join(page.extract_text() or '' for page in reader.pages)
            kind = 'original_document'
        else:
            texts[key] = BeautifulSoup(raw, 'html.parser').get_text(' ', strip=True)
            kind = 'official_original_web_page'
        sources.append(dict(source_id='mev7_' + key, title=title,
                            publisher='European Migration Network' if key.startswith(('emn', 'arm24', 'mda24', 'srb24', 'ukr24'))
                            else ('Armenia Ministry of Internal Affairs / e-draft' if key == 'arm_india' else 'Armenia ARLIS / National Assembly' if key.startswith('arm_') else 'Oman National Centre for Statistics and Information'),
                            url=url, local_path=str(path.relative_to(ROOT)), retrieved_at=CUT,
                            sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                            source_quality='official_primary_or_intergovernmental', archive_status='original_archived',
                            archive_kind=kind, source_locator=locator,
                            notes='EMN observer totals are submitted by relevant national authorities; do not interpret as applications, unique persons, or receipts.' if key.startswith('emn') else ''))

    emn23, emn24 = compact(texts['emn23']), compact(texts['emn24'])
    assert '285 737 247 616 38 121' in emn23
    assert '2 672 808 1 864' in emn23 and '29 442 20 276 9 166' in emn23
    assert '158 825 12 824 146 001' in emn24 and '11 058* 1 100 2 149' in emn24
    assert '3 678 1 376 2 302' in emn24 and '31 513 22 798 8 715' in emn24
    assert '13 770 10 127 3 643' in emn24 and 'Moldova note: Total visas also include type A visas' in emn24
    checks.append(dict(check='EMN_table_values_and_Moldova_scope_extracted', passed=True,
                       source_ids=['mev7_emn23', 'mev7_emn24']))

    def add(country, year, metric, value, unit, source_key, page, scope, **extra):
        native, zh = COUNTRIES[country]
        start, end = f'{year}-01-01', f'{year}-12-31'
        oid = f'mev7_{country}_{year}_{metric}'
        if extra.get('origin'):
            oid += '_' + extra['origin']
        row = dict(observation_id=oid, source_id='mev7_' + source_key,
            source_ids=['mev7_' + source_key], source_locator=f'PDF page {page}; Table 6.1/6.2 or cited source text',
            destination=country, reporting_country=country, origin='UNK', origin_basis='not_reported',
            origin_label='国籍未披露', origin_display_name='国籍未披露', metric=metric, value=value,
            unit=unit, period_start=start, period_end=end, period_type='calendar_year', year=year,
            calculation_type='published_statistic', observation_domain='visa_activity', context_only=True,
            eligible_money_ledger=False, aggregation_role=extra.pop('aggregation_role', 'control'),
            flow_direction='inbound', scope=scope, coverage_status='published_annual',
            display_destination=f'{native}（{zh}）', notes=extra.pop('notes', ''))
        row.update(extra)
        observations.append(row)
        return oid

    # National totals and mutually exclusive short/long stay categories.
    for code, values in VISA_ROWS_2023.items():
        total, long_stay, short_stay = values
        for metric, value, scope in [('visas_issued_total', total, 'all_national_visa_types'),
                                     ('national_long_stay_visas_issued', long_stay, 'national_long_stay'),
                                     ('national_short_stay_visas_issued', short_stay, 'national_short_stay')]:
            add(code, 2023, metric, value, 'visa_issuance_events', 'emn23', 14, scope,
                aggregation_role='control' if metric.endswith('_total') else 'component',
                definition_break_with_2024=(code == 'ARM'),
                notes='Armenia 2023 official EMN category totals are retained as published; the separate India-specific government series does not reconcile and is not a component of this row.' if code == 'ARM' else '')
    # Moldova and Ukraine totals were not reported in 2023; preserve only the observed short-stay value.
    add('MDA', 2023, 'national_short_stay_visas_issued', 2790, 'visa_issuance_events', 'mda24', 11,
        'national_short_stay', notes='2023 point appears in the 2021-2024 comparison in the 2024 factsheet. 2023 total/long-stay values are not published here.')
    add('UKR', 2023, 'national_short_stay_visas_issued', 3823, 'visa_issuance_events', 'ukr24', 10,
        'national_short_stay', notes='2023 point appears in the 2021-2024 comparison in the 2024 factsheet. 2023 total/long-stay values are not reported in the 2023 annex.')

    for code, values in VISA_ROWS_2024.items():
        total, long_stay, short_stay = values
        # The EMN annex explicitly includes Moldovan airport/transit A/B types in total.
        total_note = 'Moldova total includes A airport-transit and B transit visas; reported long/short components do not sum to total.' if code == 'MDA' else ''
        for metric, value, scope in [('visas_issued_total', total, 'all_national_visa_types'),
                                     ('national_long_stay_visas_issued', long_stay, 'national_long_stay'),
                                     ('national_short_stay_visas_issued', short_stay, 'national_short_stay')]:
            add(code, 2024, metric, value, 'visa_issuance_events', 'emn24', 17, scope,
                aggregation_role='control' if metric.endswith('_total') else 'component',
                definition_break_with_2023=(code == 'ARM'), notes=total_note)
    for code, rows in TOP_2024.items():
        total = VISA_ROWS_2024[code][0]
        for nationality, value, share in rows:
            iso, zh = NATIONALITIES[nationality]
            skey, page = ('ukr24', 10) if code == 'UKR' else ('emn24', 18)
            add(code, 2024, 'national_short_stay_visas_issued_by_citizenship', value,
                'visa_issuance_events', skey, page, 'short_stay_top3_citizenship', origin=iso,
                origin_basis='visa_applicant_citizenship', origin_label=zh, origin_display_name=zh,
                aggregation_role='top_nationality_component', denominator_value=total,
                denominator_scope='all visas issued', published_share=share,
                notes='仅为前三国籍之一，不能与全体短停签发量或其他成分相加；百分比按全部签证而非短停签证计算。' + ('中国冠名按中国大陆展示。' if iso == 'CHN' else ''))

    # Short-stay annual series reported in the factsheets.
    series = {
        'MDA': {2021: 1093, 2022: 4873, 2023: 2790, 2024: 2149},
        'SRB': {2023: 9166, 2024: 8715},
        'UKR': {2021: 21898, 2022: 3807, 2023: 3823, 2024: 3643},
    }
    for code, years in series.items():
        skey, page = {'MDA': ('mda24', 11), 'SRB': ('srb24', 10), 'UKR': ('ukr24', 10)}[code]
        for year, value in years.items():
            existing = next((o for o in observations if o['destination'] == code and o['year'] == year and o['metric'] == 'national_short_stay_visas_issued'), None)
            if existing:
                assert existing['value'] == value
                existing.update(series_id=code.lower() + '_short_stay_visa_issued',
                                series_label=COUNTRIES[code][1] + '短期签证签发量',
                                series_scope='all short-stay visas',
                                source_ids=list(dict.fromkeys(existing['source_ids'] + ['mev7_' + skey])))
                continue
            oid = f'mev7_{code}_{year}_short_stay_trend'
            native, zh = COUNTRIES[code]
            observations.append(dict(observation_id=oid, source_id='mev7_' + skey, source_ids=['mev7_' + skey],
                source_locator=f'PDF page {page}, 2021-2024 short-stay chart', destination=code, reporting_country=code,
                origin='UNK', origin_basis='not_reported', origin_label='国籍未披露', origin_display_name='国籍未披露',
                metric='national_short_stay_visas_issued', value=value, unit='visa_issuance_events',
                period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year', year=year,
                calculation_type='published_statistic', observation_domain='visa_activity', context_only=True,
                eligible_money_ledger=False, aggregation_role='control', flow_direction='inbound',
                series_id=code.lower()+'_short_stay_visa_issued', series_label=zh+'短期签证签发量', series_scope='all short-stay visas',
                scope='national_short_stay', coverage_status='published_annual', display_destination=f'{native}（{zh}）',
                notes='该年度短停签发量来自2024 factsheet中的历史比较图，不从四舍五入的百分比倒推全体签证数量。'))
    # Official Armenian MIA draft series is a separate visa label and conflicts with EMN 2023 categories.
    for year, value, period in [(2022, 25062, 'calendar_year'), (2023, 67609, 'calendar_year')]:
        s, e = (f'{year}-01-01', f'{year}-06-30') if period == '2024_first_half' else (f'{year}-01-01', f'{year}-12-31')
        observations.append(dict(observation_id=f'mev7_arm_ind_{year}', source_id='mev7_arm_india',
            source_ids=['mev7_arm_india'], source_locator='justification paragraph 41', destination='ARM',
            reporting_country='ARM', origin='IND', origin_basis='citizenship', origin_label='印度', origin_display_name='印度',
            metric='entry_visa_recipients_as_reported', value=value, unit='visa_recipients_as_reported',
            period_start=s, period_end=e, period_type='calendar_half' if period.endswith('half') else 'calendar_year', year=year,
            calculation_type='published_statistic', observation_domain='visa_activity', context_only=True,
            eligible_money_ledger=False, aggregation_role='separate_nonreconciling_series', flow_direction='inbound',
            scope='entry_visa_for_Indian_citizens', coverage_status='published_period',
            context_selection_default=False,
            quality_issue='口径或来源冲突：内政部草案所列2023年印度公民入境签证获签者67,609，高于EMN当年全体短期签证签发量38,121；保留独立序列，不合并、不用于趋势衔接。',
            notes='亚美尼亚政府拟议说明引述的签发印度公民入境签证数量。与EMN国家长/短停表不可合并；2023数67609大于EMN全体短停38121，存在定义或数据冲突，保留原始序列供辨析。'))

    # Armenia's 2024 fee scenario is a legal ceiling envelope, not collections or a ledger flow.
    arm_short = 146001
    low_fee, high_fee = 0, 40000
    law = compact(texts['arm_law'])
    assert 'The amount of base duty shall be set at AMD 1000' in law
    assert 'with the right to stay for a period of up to 120 days and with a validity period of up to one year: in the amount of 40-fold of the base duty' in law
    assert 'persons under the age of 18' in law and 'close relatives of the citizen of the Republic of Armenia' in law
    fees = [dict(candidate_id='mev7_arm_2024_shortstay_standard_fee_value', destination='ARM', year=2024,
        observation_id='mev7_ARM_2024_national_short_stay_visas_issued', quantity=arm_short,
        quantity_unit='visa_issuance_events', quantity_source_id='mev7_emn24', quantity_locator='PDF page 17, Table 6.1',
        legal_source_id='mev7_arm_law', legal_locator='Articles 8, 14(9), 15(3), 26', currency='AMD',
        fee_lower_per_visa=low_fee, fee_upper_per_visa=high_fee,
        value_lower=arm_short*low_fee, value_upper=arm_short*high_fee,
        calculation='issued_short_stay_visa_count x conditional legal visitor-visa tariff envelope',
        confidence='scenario_only', eligible_money_ledger=False, actual_receipt=False,
        status='research_candidate_not_model_input',
        notes='2024 state-duty schedule: AMD1,000 base; single visitor visa up to 120 days 15x, multiple up to120-day stay/1-year validity 40x. Lower zero allows exemptions (including under-18s and close relatives) and unobserved free/waived categories; upper assumes every short-stay visa incurred the 40x maximum visitor tariff. Visa subclasses, reciprocity, consular/e-visa channel, collection/refund, and exemption counts are unknown. This is an intentionally broad conditional legal envelope, not expected revenue, realized fees, or applicant cost.')]

    # Oman yearbook visitor entries with a tourism visa, in thousands of entries.
    om = compact(texts['oman26'])
    oman = {2016: 1374200, 2017: 1369200, 2018: 1769000, 2019: 2093000, 2020: 530700,
            2021: 363200, 2022: 1364000, 2023: 2385300, 2024: 2342200, 2025: 2445100}
    assert 'Inbound Visitors by Tourism Visa 530.7 2,093.0 1,769.0 1,369.2 1,374.2' in om
    assert 'Inbound Visitors by Tourism Visa 2,445.1 2,342.2 2,385.3 1,364.0 363.2' in om
    for year, value in oman.items():
        observations.append(dict(observation_id=f'mev7_omn_{year}_tourism_visa_entries', source_id='mev7_oman26',
            source_ids=['mev7_oman26'], source_locator='PDF page 335, inbound tourism indicators; 2016-2020 on PDF p.334',
            destination='OMN', reporting_country='OMN', origin='UNK', origin_basis='not_reported', origin_label='国籍未披露',
            origin_display_name='国籍未披露', metric='inbound_entries_using_tourism_visa', value=value,
            unit='border_entry_events', period_start=f'{year}-01-01', period_end=f'{year}-12-31',
            period_type='calendar_year', year=year, calculation_type='published_statistic_thousands_x_1000',
            observation_domain='mobility', context_only=True, eligible_money_ledger=False,
            aggregation_role='control', flow_direction='inbound', scope='inbound visitors entering on tourism visas',
            coverage_status='published_annual', raw_value_thousands=value/1000,
            raw_unit='thousand visitors/entry events', precision_in_events=100,
            original_value=value/1000, original_unit='thousand visitors/entry events',
            source_rounding_unit=100, source_rounding_half_unit=50,
            data_status='provisional' if year==2024 else 'preliminary' if year==2025 else 'published',
            source_status='provisional' if year==2024 else 'preliminary' if year==2025 else 'published',
            source_status_label='暂定值' if year==2024 else '初步值' if year==2025 else '已公布',
            notes='原表单位千人次，已乘1000；统计的是持旅游签入境的边境人次，不是签证签发量、申请量、独立人员或付费事件。2024暂定，2025初步。'))

    # Keep factual gaps and source-definition conflicts visible.
    exclusions = [
        dict(item='ARM 2023 citizenship short-stay top-3', reason='2023 Table 6.2 is consular issuing-country location; 2024 table is applicant citizenship. Do not join as a nationality time series.', status='excluded_from_nationality_series', source_ids=['mev7_emn23','mev7_emn24']),
        dict(item='ARM India-issued visa series vs EMN annual categories', reason='Government draft says 67,609 Indian citizen entry visas in 2023, exceeding EMN national short-stay total 38,121. Definitions differ or conflict; retain separate series, do not reconcile.', status='conflict_retained', source_ids=['mev7_arm_india','mev7_emn23']),
        dict(item='MNE 2024 visa issuance', reason='EMN table reports n/i for total, long-stay, short-stay and top citizenship.', status='not_reported', source_ids=['mev7_emn24']),
        dict(item='MDA 2023 total and long-stay visas', reason='EMN reports n/i; short-stay count alone is available.', status='not_reported', source_ids=['mev7_emn23']),
        dict(item='UKR 2023 total and long-stay visas', reason='EMN reports n/i; short-stay count alone is available.', status='not_reported', source_ids=['mev7_emn23']),
        dict(item='Oman visa issuance, applications, fee receipts', reason='NCSI Yearbook gives tourism-visa arrivals, not administrative visa grants, and does not provide fee receipts.', status='not_observed', source_ids=['mev7_oman26']),
        dict(item='Bahrain annual visa grant series', reason='OpenDataSoft catalog searches did not locate visa issuance series; a >10,000 Golden Residency cumulative threshold is only in 2024 media reproductions of a statement and is not admitted as annual amount.', status='not_admitted_without_primary_archive', source_ids=[]),
    ]

    # Verify source links and explicit non-overlap semantics before exporting.
    metric_labels = {
        'visas_issued_total': '签证签发总量',
        'national_long_stay_visas_issued': '长期签证签发量',
        'national_short_stay_visas_issued': '短期签证签发量',
        'national_short_stay_visas_issued_by_citizenship': '短期签证签发量 · 已披露国籍',
        'entry_visa_recipients_as_reported': '印度公民入境签证获签者 · 内政部口径',
        'inbound_entries_using_tourism_visa': '持旅游签证入境人次',
    }
    for o in observations:
        country = o['destination']
        zh = COUNTRIES.get(country,('', '阿曼'))[1]
        scope_slug = re.sub('[^a-z0-9]+', '_', o['scope'].lower()).strip('_')
        o['series_id'] = '_'.join(['mev7',country.lower(),o['metric'],scope_slug,o['period_type']])
        suffix = ''
        if country == 'ARM' and o['metric'] != 'entry_visa_recipients_as_reported':
            version = '2023_definition' if o['year'] < 2024 else '2024_definition'
            o['series_id'] += '_' + version
            suffix = ' · 2023年原口径' if o['year'] < 2024 else ' · 2024年新口径'
        o['series_label'] = zh + ' · ' + metric_labels[o['metric']] + suffix
        o['series_scope'] = o['scope']
    # The shared workbench accepts annual country/category coverage rows.
    # National visa classes do not identify visitor/student/work categories;
    # leave this category unclassified rather than assigning short stay to tourism.
    by_country_year = defaultdict(list)
    for o in observations:
        by_country_year[o['destination'], o['year']].append(o)
    coverage = []
    for (code, year), members in sorted(by_country_year.items()):
        mobility = code == 'OMN'
        visa = [o for o in members if o['observation_domain'] == 'visa_activity']
        coverage.append(dict(code=code, destination=code, year=year, visa_group='unclassified',
            category_detail_status='unclassified_aggregate',
            period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
            status='mobility_context_only' if mobility else 'quantity_only',
            context_only=True, eligible_money_ledger=False,
            amount_known=False, amount_modeled=False, fee_known=False,
            quantity_known=any(o['metric'] != 'entry_visa_recipients_as_reported' for o in visa),
            quantity_context_known=bool(visa), mobility_context_known=mobility,
            observation_count=len(members), visa_activity_observation_count=len(visa),
            mobility_observation_count=sum(o['observation_domain']=='mobility' for o in members),
            source_ids=sorted({s for o in members for s in o['source_ids']}),
            observation_ids=sorted(o['observation_id'] for o in members),
            series_ids=sorted({o['series_id'] for o in members}),
            notes='已归档持旅游签证入境人次，原表千人次转换并保留100人次显示精度；不作为签证签发量或费用。' if mobility else
                  '已归档原表签证数量，总量、长短停、前三国籍和冲突口径分别保留；类别未细分，不相加、不转换为费用。' +
                  ('亚美尼亚2023与2024存在定义断点；内政部印度公民序列有来源冲突，独立保存。' if code=='ARM' else '') +
                  ('总量包括A/B过境类型，长期与短期之和不等于总量。' if code=='MDA' and year==2024 else '')))
    ids = [o['observation_id'] for o in observations]
    source_ids = {s['source_id'] for s in sources}
    for year, table in [(2023,VISA_ROWS_2023),(2024,VISA_ROWS_2024)]:
        for code,(total,long_stay,short_stay) in table.items():
            checks.append(dict(check=f'{code}_{year}_visa_category_reconciliation',
                passed=(total==long_stay+short_stay) if code!='MDA' else total>long_stay+short_stay,
                total=total, long_stay=long_stay, short_stay=short_stay,
                residual_other_types=total-long_stay-short_stay,
                note='Moldova includes type A/B visas in total.' if code=='MDA' else ''))
    for code,rows in TOP_2024.items():
        checks.append(dict(check=f'{code}_2024_top3_below_short_stay_total',
            passed=sum(r[1] for r in rows)<=VISA_ROWS_2024[code][2],
            top3_sum=sum(r[1] for r in rows),short_stay_total=VISA_ROWS_2024[code][2]))
        for name,value,share in rows:
            decimals=len(share.rstrip('%').split('.')[1])
            checks.append(dict(check=f'{code}_2024_{name}_published_share_compatible_with_all_visas',
                passed=abs(value/VISA_ROWS_2024[code][0]*100-float(share.rstrip('%'))) <= .5*10**(-decimals)+.000001,
                actual_denominator_scope='all visas issued',published_share=share))
    checks.extend([
        dict(check='observation_ids_unique', passed=len(ids) == len(set(ids)), count=len(ids)),
        dict(check='all_observations_resolve_to_archived_source', passed=all(o['source_id'] in source_ids for o in observations)),
        dict(check='citizenship_values_preserve_one_china_display_name', passed=all(o['origin_label'] == '中国大陆' for o in observations if o.get('origin') == 'CHN')),
        dict(check='all_activity_observations_context_only', passed=all(o['context_only'] and not o['eligible_money_ledger'] for o in observations)),
        dict(check='oman_border_events_not_visa_grants', passed=all(o['metric'] == 'inbound_entries_using_tourism_visa' and o['unit'] == 'border_entry_events' for o in observations if o['destination'] == 'OMN'), count=sum(o['destination'] == 'OMN' for o in observations)),
        dict(check='arm_2024_fee_scenario_not_receipts_or_flows', passed=fees[0]['value_upper'] == 5840040000 and not fees[0]['actual_receipt'] and not fees[0]['eligible_money_ledger']),
        dict(check='annual_short_stay_no_duplicate_views', passed=len({(o['destination'],o['year']) for o in observations if o['metric'] == 'national_short_stay_visas_issued'}) == sum(o['metric'] == 'national_short_stay_visas_issued' for o in observations)),
        dict(check='every_observation_has_chinese_series_label',passed=all(o.get('series_id') and re.search('[\u4e00-\u9fff]',o.get('series_label','')) for o in observations)),
        dict(check='series_partner_period_unique',passed=len({(o['series_id'],o['origin'],o['period_start'],o['period_end'])for o in observations})==len(observations)),
        dict(check='oman_uses_mobility_domain',passed=all(o['observation_domain']=='mobility'for o in observations if o['destination']=='OMN')),
        dict(check='oman_preserves_original_thousands_and_100_event_precision', passed=all(o['original_value']*1000==o['value'] and o['source_rounding_unit']==100 and o['source_rounding_half_unit']==50 and o['original_unit']==o['raw_unit'] for o in observations if o['destination']=='OMN')),
        dict(check='oman_provisional_preliminary_status_preserved', passed=all(o['source_status']==o['data_status'] and o['source_status_label']==('暂定值' if o['year']==2024 else '初步值' if o['year']==2025 else '已公布') for o in observations if o['destination']=='OMN')),
        dict(check='arm_conflicting_series_not_default_and_has_chinese_quality_flag', passed=all(o['context_selection_default'] is False and '口径或来源冲突' in o['quality_issue'] for o in observations if o['metric']=='entry_visa_recipients_as_reported')),
        dict(check='coverage_is_standard_unique_country_year_category_rows', passed=all(isinstance(r,dict) and r.get('code') and r.get('year') and r.get('visa_group') for r in coverage) and len({(r['code'],r['year'],r['visa_group'])for r in coverage})==len(coverage), count=len(coverage)),
        dict(check='coverage_partitions_all_observations_once', passed=sum(r['observation_count']for r in coverage)==len(observations) and {oid for r in coverage for oid in r['observation_ids']}==set(ids)),
        dict(check='coverage_does_not_invent_money_or_merge_border_into_visa_counts', passed=all(not r['amount_known'] and not r['amount_modeled'] and not r['eligible_money_ledger'] and (not r['quantity_known'] and r['mobility_context_known'] if r['code']=='OMN' else r['quantity_context_known'] and not r['mobility_context_known'])for r in coverage)),
        dict(check='reported_visas_nonnegative_integer', passed=all(isinstance(o['value'], int) and o['value'] >= 0 for o in observations)),
    ])
    assert all(c['passed'] for c in checks), checks

    # The top-nationality components and visa category totals are separate views, not additional flows.
    write('sources.json', sources)
    write('observations.json', observations)
    write('fee_scenarios.json', fees)
    write('exclusions.json', exclusions)
    write('source_conflicts.json', [dict(conflict_id='arm_2023_visa_scope',
        source_ids=['mev7_emn23','mev7_arm_india','mev7_arm24'],
        observation_ids=['mev7_ARM_2023_national_short_stay_visas_issued','mev7_arm_ind_2023'],
        values=dict(emn_short_stay_total=38121,indian_entry_visa_recipients=67609),
        resolution='Retain as separate scopes; no trend stitching, residual allocation, or fee-model input. 2024 factsheet explicitly declares a definition change.',
        status='unresolved_scope_or_source_conflict')])
    write('legal_fee_rules.json', [dict(rule_id=f'mev7_arm_visitor_{coef}',source_id='mev7_arm_law',
        currency='AMD',base_duty=1000,coefficient=coef,amount=coef*1000,
        locator='Articles 8, 14(9), 15(3)',visa_scope=scope,
        applicability='Historical law with visa-fee article amendments through 2022, official consolidation headed 2023-12-08; not the current 2026 MFA fee page.',
        exemptions_locator='Article26: under18, close relatives, educational roles, humanitarian, diplomatic and other stated categories',
        model_status='conditional_tariff_only') for coef,scope in [(3,'single visitor up to21 days'),(15,'single visitor up to120 days'),
        (20,'multiple visitor up to60-day stay / six-month validity'),(40,'multiple visitor up to120-day stay / one-year validity')]])
    write('checks.json', checks)
    write('coverage.json', coverage)
    write('coverage_summary.json', dict(as_of=CUT, destination_country_count=len(COUNTRIES)+1,
        visa_destination_country_count=len(COUNTRIES),
        countries=sorted([*COUNTRIES,'OMN']), unique_observation_count=len(observations),
        visa_issuance_observation_count=sum(o['observation_domain']=='visa_activity' for o in observations),
        oman_border_context_count=sum(o['destination']=='OMN' for o in observations),
        fee_scenario_count=len(fees), money_flow_count=0,
        caveat='Counts include annual totals, category components, and top-nationality views; do not sum all rows.'))
    print(json.dumps({'sources': len(sources), 'observations': len(observations), 'fees': len(fees),
                      'checks': len(checks), 'all_passed': all(c['passed'] for c in checks)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
