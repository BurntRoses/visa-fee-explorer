#!/usr/bin/env python3
"""Rebuild recent US NIV activity context from archived GAO originals.

Figures 3/4 are manually transcribed from explicit printed bar labels, with
their exact original bytes pinned. Table 3 is parsed from the accessible HTML.
These are activity observations only; none is a money-ledger input.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
from html import unescape
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/us_recent_v6'
OUT = ROOT / 'data/research/us_recent_v6'
CUT = '2026-11-17'
REPORT_URL = 'https://files.gao.gov/reports/GAO-26-107902/index.html'
IMAGE_BASE = 'https://files.gao.gov/reports/GAO-26-107902/d26107902_web_files/'
PINNED = {
    'gao_26_107902.html': '8fbfea701fdb4e1cb1db1d289e05a39b5f3e2da0a1210c413487abdd8f6bd7c7',
    'gao_26_107902_figure3_niv_applications.jpg': '914c4a1c3034fbe9dd5c51d65cce5419111e0da5de6cd28799d31d6ceefea77a',
    'gao_26_107902_figure4_niv_adjudications.jpg': '2b9c76428d1853ae80ac6b4072c0cec51c21f0f3f87d7d72c42429c4bae76e16',
}
# Exact labels on the frozen official graphs, in millions. Do not infer the
# underlying unrounded count from bar height or from an unrelated annual table.
FIGURE3 = {2019: '11.40', 2020: '5.49', 2021: '5.03', 2022: '10.07',
           2023: '13.00', 2024: '13.29', 2025: '13.54'}
FIGURE4 = {2019: '11.39', 2020: '5.18', 2021: '2.93', 2022: '7.77',
           2023: '12.55', 2024: '13.86', 2025: '14.08'}
COUNTRIES = {
    'Brazil': ('BRA', '巴西', 1141235),
    'China': ('CHN', '中国（报告含中国香港领事地）', 1206011),
    'India': ('IND', '印度', 1455255),
    'Mexico': ('MEX', '墨西哥', 2658627),
}


def dump(filename, value):
    (OUT / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def fiscal_fields(year):
    return dict(year=year, period_start=f'{year-1}-10-01',
                period_end=f'{year}-09-30', period_type='fiscal_year',
                year_type='fiscal', period_label=f'FY{year}')


def plain_html(fragment):
    return ' '.join(unescape(re.sub(r'<[^>]*>', ' ', fragment)).split())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources, observations, coverage, checks = [], [], [], []
    for filename, sid, title, url, kind in [
        ('gao_26_107902.html', 'usr6_gao_26_107902',
         'GAO-26-107902: Nonimmigrant Visas — global demand, adjudications and country-location applications',
         REPORT_URL, 'original_accessible_html'),
        ('gao_26_107902_figure3_niv_applications.jpg', 'usr6_gao_figure3_applications',
         'GAO-26-107902 Figure 3: Worldwide estimated NIV applications, FY2019–2025',
         IMAGE_BASE+'image003.jpg', 'original_figure_image'),
        ('gao_26_107902_figure4_niv_adjudications.jpg', 'usr6_gao_figure4_adjudications',
         'GAO-26-107902 Figure 4: Worldwide NIV adjudications, FY2019–2025',
         IMAGE_BASE+'image004.jpg', 'original_figure_image'),
    ]:
        path = RAW / filename
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == PINNED[filename], f'Original changed; recheck extraction: {filename}'
        assert data.startswith(b'\xff\xd8\xff') if filename.endswith('.jpg') else b'Table 3:' in data
        sources.append(dict(source_id=sid, title=title, publisher='U.S. Government Accountability Office',
                            institution='U.S. Government Accountability Office', url=url,
                            local_path=str(path.relative_to(ROOT)), sha256=digest, bytes=len(data),
                            retrieved_at=CUT, source_quality='official_primary',
                            capture_method='http_download_original', archive_kind=kind,
                            archive_status='original_archived',
                            notes='GAO analysis of Department of State data. 所有数值仅作签证活动背景；不回算收入或分配国籍付款边。'))
    html = (RAW / 'gao_26_107902.html').read_text(encoding='utf-8')
    text = plain_html(html)
    checks.append(dict(check='all_three_original_hashes_match_visual_transcription_inputs', passed=True))
    checks.append(dict(check='official_html_references_exact_figure_originals',
                       passed=all('src="d26107902_web_files/'+x+'"' in html
                                  for x in ['image003.jpg', 'image004.jpg'])))
    checks.append(dict(check='fiscal_application_method_is_fee_collections_divided_by_average_rate',
                       passed='dividing the total fee collections in a fiscal year by the average fee rate' in text,
                       notes='官方自身估算量，不能当逐份申请行政计数，也不能再乘费率充当新的独立收入证据。'))
    assert all(r['passed'] for r in checks)

    base = dict(destination='USA', reporting_country='USA', origin='WORLD', nationality='WORLD',
                origin_basis='all_locations_total', visa_type='all_niv', visa_group='unclassified',
                observation_domain='visa_activity', context_only=True, eligible_money_ledger=False,
                aggregation_role='total', flow_direction='inbound',
                source_status='published_rounded', source_ids=['usr6_gao_26_107902'])
    for metric, values, sid, label, fig in [
        ('estimated_applications', FIGURE3, 'usr6_gao_figure3_applications', '美国非移民签证 · 全球申请估算 · 财年', 3),
        ('visas_adjudicated', FIGURE4, 'usr6_gao_figure4_adjudications', '美国非移民签证 · 全球审理量 · 财年', 4),
    ]:
        for year, printed in values.items():
            row = dict(base)
            row.update(fiscal_fields(year))
            row.update(observation_id=f'usr6_niv_{metric}_fy{year}', metric=metric,
                       value=int(Decimal(printed)*1_000_000), unit='applications' if fig==3 else 'adjudication_events',
                       original_value=printed, original_unit='million', reported_decimal_places=2,
                       source_rounding_unit=10000, source_rounding_half_unit=5000,
                       source_id=sid, source_ids=['usr6_gao_26_107902', sid],
                       source_locator=f'Figure {fig}, FY{year} bar, explicit printed label {printed} million',
                       extraction_method='manual_visual_transcription_of_explicit_printed_bar_label',
                       calculation_type='official_application_estimate' if fig==3 else 'published_statistical_series',
                       series_id=f'usa_gao_niv_{metric}_fiscal', series_label=label,
                       scope='all_nonimmigrant_visa_types_worldwide',
                       notes=('国务院以财年MRV收款除以平均费率估算申请量；原图按百万保留两位，保留原显示精度。'
                              if fig==3 else '全年各NIV签发地所有类别的审理事件，含批准及拒绝；不等于签发量。原图按百万保留两位。')
                              +'财年为前一年10月1日至当年9月30日。申请与审理可跨财年队列，不以二者之比作批准概率或独立申请人数。')
            observations.append(row)

    # The official accessible table repeats once in the highlights. Select
    # precisely the Table 3 anchor in the body, then its following table.
    assert html.count('<a name="TOC_TABLE_2">') == 1
    section = html.split('<a name="TOC_TABLE_2">', 1)[1]
    table = re.search(r'<table\b.*?</table>', section, re.S).group(0)
    table_rows = [[plain_html(cell) for cell in re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', tr, re.S)]
                  for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table, re.S)]
    parsed_locations = {}
    for cells in table_rows:
        if not cells or cells[0].strip() not in COUNTRIES:
            continue
        raw_name = cells[0].strip()
        code, label, expected = COUNTRIES[raw_name]
        value = int(cells[1].replace(',', ''))
        assert value == expected
        parsed_locations[code] = value
        is_china = code == 'CHN'
        observations.append(dict(observation_id=f'usr6_niv_applications_location_{code}_fy2025',
            destination='USA', reporting_country='USA', origin='UNK', nationality='UNK',
            origin_basis='consular_country_location_not_nationality', basis='consular_location',
            consular_location_country=code, consular_location_name=label,
            context_partner_code=code, context_partner_label=label,
            consular_location_raw_label=raw_name, location_includes=['CHN','HKG'] if is_china else [code],
            visa_type='all_niv', visa_group='unclassified', metric='applications_by_consular_location',
            value=value, unit='applications', original_value=cells[1], original_unit='applications',
            **fiscal_fields(2025),
            source_id='usr6_gao_26_107902', source_ids=['usr6_gao_26_107902'],
            source_locator=f'Table 3, {raw_name} row, NIV applications column',
            extraction_method='accessible_html_table_cell', calculation_type='published_statistical_series',
            observation_domain='visa_activity', context_only=True, eligible_money_ledger=False,
            aggregation_role='selected_location_component', flow_direction='inbound',
            series_id='usa_gao_niv_applications_consular_location_fiscal',
            series_label='美国非移民签证 · 指定领事地申请量 · 财年',
            source_status='published', scope='selected_four_consular_country_locations_not_exhaustive',
            notes='数据是受理所在地汇总，不是申请人国籍或居住地，origin保持UNK。四地仅为报告选取的样本，不穷尽全球。'
                  +('GAO方法明确中国行包含中国香港领事地，不能作为中国内地申请人数量。' if is_china else '')))
    checks.append(dict(check='table3_exact_application_cells_parsed_four_locations',
                       passed=parsed_locations=={v[0]:v[2] for v in COUNTRIES.values()}, values=parsed_locations))
    checks.append(dict(check='china_location_explicitly_includes_china_hong_kong',
                       passed='We included Hong Kong in our calculations for China.' in text))
    checks.append(dict(check='country_location_not_misclassified_as_nationality',
                       passed=all(r['origin']=='UNK' and r['nationality']=='UNK'
                                  for r in observations if r['metric']=='applications_by_consular_location')))

    # Explicit figures in the report text, preserving the one-decimal precision.
    # This distinct B1/B2 series is not an additive component of the global NIV
    # series above, nor a total that may be inferred from rounded percentages.
    for year, printed, sentence in [
        (2019, '9.2', 'went from 9.2 million in FY 2019'),
        (2021, '1.5', 'a low of 1.5 million in FY 2021'),
        (2025, '11.7', 'reaching 11.7 million, 2.5 million more'),
    ]:
        assert sentence in text
        row = dict(base)
        row.update(fiscal_fields(year))
        row.update(observation_id=f'usr6_visitor_adjudications_fy{year}',
                   visa_type='B1_B2', visa_group='visitor', metric='visas_adjudicated',
                   value=int(Decimal(printed)*1_000_000), unit='adjudication_events',
                   original_value=printed, original_unit='million', reported_decimal_places=1,
                   source_rounding_unit=100000, source_rounding_half_unit=50000,
                   source_id='usr6_gao_26_107902', source_locator='Adjudications section, paragraph immediately before Figure 4',
                   extraction_method='explicit_report_text', calculation_type='published_statistical_series',
                   series_id='usa_gao_visitor_b1_b2_adjudications_fiscal',
                   series_label='美国访客签证B1/B2 · 全球审理量 · 财年',
                   scope='visitor_visa_B1_B2_worldwide', aggregation_role='category_component',
                   notes='报告将B1和B2统称visitor visas；这是审理事件，含批准与拒绝，不是签发量或收费人数。原文百万保留一位；不与全部NIV总量相加。')
        observations.append(row)

    for year in FIGURE3:
        ids=[r['observation_id'] for r in observations if r['year']==year]
        coverage.append(dict(code='USA', destination='USA', year=year,
            coverage_status='official_niv_activity_context', **{k:v for k,v in fiscal_fields(year).items() if k!='year'},
            source_ids=['usr6_gao_26_107902','usr6_gao_figure3_applications','usr6_gao_figure4_adjudications'],
            observation_ids=ids, context_only=True, eligible_money_ledger=False,
            quantity_status='official_application_estimate_and_rounded_adjudication_totals',
            series_ids=sorted({r['series_id'] for r in observations if r['year']==year}),
            notes='全NIV申请估算与全NIV审理量均覆盖完整财政年；访客子类仅有2019/2021/2025明确原文值。'
                  +('另有四个选定领事所在地申请量，国籍不详；中国行含中国香港领事地。' if year==2025 else '')))
    ids=[r['observation_id'] for r in observations]
    checks += [
        dict(check='unique_observation_ids', passed=len(ids)==len(set(ids))),
        dict(check='all_rows_context_only_no_money_ledger', passed=all(r['context_only'] and not r['eligible_money_ledger'] for r in observations)),
        dict(check='all_rows_precise_us_fiscal_periods', passed=all(r['period_start']==f"{r['year']-1}-10-01" and r['period_end']==f"{r['year']}-09-30" for r in observations)),
        dict(check='only_count_metrics_no_wait_time_or_staff_rows', passed=all(r['metric'] in {'estimated_applications','visas_adjudicated','applications_by_consular_location'} for r in observations)),
        dict(check='complete_global_2019_2025_series', passed=all(len([r for r in observations if r['series_id']==s])==7 for s in ['usa_gao_niv_estimated_applications_fiscal','usa_gao_niv_visas_adjudicated_fiscal'])),
        dict(check='all_series_have_chinese_labels', passed=all(re.search(r'[\u3400-\u9fff]',r['series_label']) for r in observations)),
    ]
    assert all(r['passed'] for r in checks), checks
    readme=dict(title='美国近期非移民签证活动背景（GAO-26-107902）',
        version='2026.11.17-us-recent-v6', sources=len(sources), observations=len(observations),
        coverage_rows=len(coverage), fiscal_years=list(FIGURE3),
        rebuild_command='python3 scripts/research_us_recent_v6.py',
        extraction='官方图3/4的明确数字标签人工逐项转录，附原图和SHA；Table3从可访问HTML表格解析。未使用OCR或柱高估计。',
        series=[dict(series_id=s, label=next(r['series_label'] for r in observations if r['series_id']==s),
                     observations=sum(r['series_id']==s for r in observations)) for s in dict.fromkeys(r['series_id'] for r in observations)],
        use='所有观察均为context_only=true、eligible_money_ledger=false。独立保留财年、类别、原始显示精度和领事地口径。',
        precision='图3/4百万两位，显示步长10,000、半单位5,000；正文B1/B2百万一位，步长100,000、半单位50,000。这是来源显示精度，不是统计置信区间。',
        methodology=['申请量是国务院用财年MRV收款除以平均费率所得的官方估算；不再以该估算乘费率产生独立收入证据。',
                    '审理量包含批准及拒绝且与申请跨财年队列，不能视为签发或通过概率。',
                    '四国表按领事所在地汇总，不转成国籍付款边。中国行按原报告含中国香港领事地，保持该范围。',
                    'FY2019是2018-10-01至2019-09-30；其后同例，不转换为自然年。'],
        excluded=[dict(candidate='Monthly NIV Issuances by Nationality and Visa Class, Jan2025–Feb2026',
                       status='not_obtained', reason='travel直连返回403；adoption同路径镜像重定向travel404再返回403。没有真xlsx，未纳入月度观察。FY2020后官方月报不得累加成年报。'),
                  dict(candidate='GAO wait-time tables and staffing figure',status='excluded_from_quantity_observations', reason='等待天数与人员是独立指标，本包只提供签证活动数量。'),
                  dict(candidate='Visitor adjudications for unreported intervening years',status='not_inferred', reason='没有明确数值，不由总量乘类别百分比、不插值。')],
        money_flows_added=0, fx='[]：没有货币观察，无汇率转换。')
    dump('sources.json',sources);dump('observations.json',observations)
    dump('coverage.json',coverage);dump('fx.json',[]);dump('checks.json',checks);dump('README.json',readme)
    print(json.dumps(dict(sources=len(sources), observations=len(observations), coverage=len(coverage),
                          checks=len(checks), all_passed=all(r['passed'] for r in checks)),ensure_ascii=False))


if __name__=='__main__':
    main()
