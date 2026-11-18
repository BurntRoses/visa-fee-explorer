#!/usr/bin/env python3
"""Rebuild USA 2013–2018 MRV retained-collection calendar bridges offline.

GAO's fee-specific retained collections are one historical series. The FY2019
endpoint differs from OMB account571350; preserve that discontinuity explicitly
and never blend the GAO and OMB fiscal controls into a calendar-year flow.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/us_history_v4'
OUT = ROOT / 'data/research/us_history_v4'
EST = ROOT / 'data/estimates/us_history_v4_flows.json'
ASOF = '2026-11-17'
GAO_URL = 'https://www.gao.gov/assets/730/720119.pdf'
MODEL = 'uh4_us_mrv_retained_collection_calendar_bridge_series_break'


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = list(dict.fromkeys(k for row in obj for k in row))
        with path.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                              for k, v in row.items()} for row in obj)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources, observations, flows, fx, coverage, ranges, checks = [], [], [], [], [], [], []

    def check(name, passed, **detail):
        checks.append(dict(check=name, passed=bool(passed), **detail))
        assert passed, (name, detail)

    def source(slug, path, url, title, publisher, kind='original_document', notes=''):
        sid = 'uh4_' + slug
        p = ROOT / path
        check('archived_source_exists_' + slug, p.is_file() and p.stat().st_size > 1000, path=path)
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        sources.append(dict(source_id=sid, url=url, title=title, publisher=publisher,
                            local_path=path, sha256=digest, bytes=p.stat().st_size,
                            retrieved_at=ASOF, source_quality='official_original_web_text_snapshot'
                            if 'web_text' in kind else 'official_primary', archive_kind=kind,
                            files=[dict(path=path, sha256=digest)], notes=notes))
        return sid

    gao_sid = source('gao_22_104424', 'data/raw/us_history_v4/gao_full_report.web.txt',
                     GAO_URL, 'GAO-22-104424, April2022: actual MRV retained collections FY2013–2019',
                     'United States Government Accountability Office; Department of State source data',
                     'official_original_web_text_snapshot',
                     '原GAO无障碍PDF全文Web读取文本，保存全部5311行原行号及150页页号、32次读取原始响应与完整性清单。HTTP直接下载403；未把错误页伪装成PDF。文本层全文快照不等同原PDF字节副本。')
    text = (ROOT / sources[-1]['local_path']).read_text()
    lines = {}
    for line in text.splitlines():
        match = re.match(r'L(\d+)(?:@P(\d+)(?:-\d+)?)?: (.*)', line)
        if match:
            lines[int(match[1])] = (int(match[2]) + 1 if match[2] else None, match[3])
    check('complete_original_report_text_all5311_lines', sorted(lines)==list(range(5311)),
          first_line=min(lines), last_line=max(lines), captured_lines=len(lines), reported_pdf_pages=150)
    table_line = next(n for n, (page, value) in lines.items()
                      if page == 98 and value.startswith('Machine readable visa fee '))
    millions = [int(v.replace(',', '')) for v in lines[table_line][1].split()[4:]]
    check('seven_original_mrv_table7_values', millions == [1704, 1967, 2173, 2157, 2025, 1957, 1910],
          original_unit='USD million', source_line=table_line, values=millions)
    check('gao_defines_revenue_as_retained_collections',
          'but retained collections (revenues)' in text and 'only the consular fees retained by State' in text)
    check('gao_actual_financial_system_data_and_audit',
          'Global Financial Management System (GFMS)' in text and
          'generally accepted government auditing standards' in text and
          'using actual revenue information from fiscal years 2013' in text)
    check('nonimmigrant_fee_and_bcc_retained_scope_original',
          all(x in text for x in ['Nonimmigrant Visa Application and Border Crossing',
                                 'card – age 15 and over', 'Reciprocal Non-retained']))
    fiscal = {}
    for year, value in zip(range(2013, 2020), millions):
        # Figure4 independently repeats the same retained collection in USD bn.
        fig_line = next(n for n, (page, value) in lines.items()
                        if page == 29 and value.startswith(str(year) + ' '))
        fig_value = float(lines[fig_line][1].split()[1])
        check('table7_figure4_same_retained_collection', math.isclose(value / 1000, fig_value), year=year)
        oid = f'uh4_usa_FY{year}_mrv_retained_collection_actual'
        locator = f'Accessible PDFp98 / printedp89, Table7, Machine readable visa fee, FY{year}; original lineL{table_line}'
        fiscal[year] = dict(amount=value * 1000000, oid=oid, locator=locator)
        observations.append(dict(observation_id=oid, destination='USA', nationality='UNK', year=year,
                                 metric='mrv_retained_collections_actual', raw_metric='Machine readable visa fee',
                                 value=value * 1000000, unit='USD', source_id=gao_sid, source_ids=[gao_sid],
                                 source_locator=locator, original_value=value, original_unit='USD million',
                                 source_rounding_USD=500000, period_start=f'{year-1}-10-01',
                                 period_end=f'{year}-09-30', period_type='fiscal_year', period_label=f'FY{year}',
                                 visa_type='all_unallocated', visa_group='other', category_detail_status='unclassified',
                                 origin_basis='unallocated_nationality', calculation_type='official_retained_collection',
                                 financial_basis='retained_collections_from_fee_specific_GFMS_series',
                                 included_in_calendar_bridge=year in range(2013, 2020),
                                 notes='GAO基于国务院GFMS等系统的MRV留用收款，含非移民签证申请与BCC；不含护照、互惠签发费、其他独立领事收费及USCIS/SEVIS。FY2019仅作本系列CY2018端点，不新增2019费用边。'))

    omb_sid = source('omb2021_state', 'data/raw/us_history_v4/omb2021_state.html',
                     'https://www.govinfo.gov/content/pkg/BUDGET-2021-APP/html/BUDGET-2021-APP-1-17.htm',
                     'Budget FY2021 State Appendix: FY2019 actual MRV CBSP account571350 receipts',
                     'U.S. Office of Management and Budget / Government Publishing Office')
    soup = BeautifulSoup((RAW / 'omb2021_state.html').read_text(), 'html.parser')
    table = next(tab for tab in soup.find_all('table')
                 if 'Machine-Readable Visa Fee, Consular and Border Security Programs' in tab.get_text(' ', strip=True))
    rows = [[cell.get_text(' ', strip=True) for cell in row.find_all(['td', 'th'])]
            for row in table.find_all('tr')]
    mrv_rows = [row for row in rows if len(row) >= 5 and
                row[1] == 'Machine-Readable Visa Fee, Consular and Border Security Programs']
    check('omb_actual_column_and_explicit_mrv_cash_row',
          '2019 actual' in table.get_text(' ', strip=True) and len(mrv_rows) == 2 and mrv_rows[0][2] == '1,847' and
          not mrv_rows[1][2], rows=mrv_rows)
    check('omb_account_reorganisation_documented_not_zero_before2019',
          'account that began in FY 2019' in soup.get_text(' ', strip=True))
    omb_amount = int(mrv_rows[0][2].replace(',', '')) * 1000000
    observations.append(dict(observation_id='uh4_usa_FY2019_omb_mrv_receipt_comparison_only',
                             destination='USA', nationality='UNK', year=2019,
                             metric='mrv_cash_receipts_actual_comparison_only', value=omb_amount, unit='USD',
                             raw_metric='Machine-Readable Visa Fee, Consular and Border Security Programs',
                             source_id=omb_sid, source_ids=[omb_sid],
                             source_locator='Special and Trust Fund Receipts; identification019–5713–0–2–153; code1130, first MRV row; FY2019 actual column',
                             original_value=1847, original_unit='USD million',
                             period_start='2018-10-01', period_end='2019-09-30', period_type='fiscal_year',
                             period_label='FY2019', calculation_type='official_cash_receipt',
                             comparison_only=True, eligible_money_ledger=False,
                             notes='与GAO同财年留用收款1910百万存在63百万差异。保留两个原值；本包不将此值与GAO相邻年混合，且不重复新增既有2019边。'))
    conflicts = [dict(conflict_id='uh4_fy2019_gao_vs_omb_mrv', destination='USA', year=2019,
                      metric='MRV retained collections versus CBSP account571350 receipts',
                      values=[dict(source_id=gao_sid, amount=1910000000, currency='USD',
                                   financial_basis='GAO retained collection fee-specific series'),
                              dict(source_id=omb_sid, amount=omb_amount, currency='USD',
                                   financial_basis='OMB actual cash receipt account571350')],
                      absolute_difference_USD=1910000000-omb_amount,
                      relative_difference_to_OMB=(1910000000-omb_amount)/omb_amount,
                      resolution_status='scope_or_timing_difference_not_uniquely_identified',
                      treatment='Historical CY2013–2018 use only the homogeneous GAO series; no GAO/OMB fiscal bridge and no GAO2019 main flow. Later OMB series remains independent; time-series boundary is explicit.',
                      source_ids=[gao_sid, omb_sid])]
    check('fy2019_difference_preserved_without_reconciliation', conflicts[0]['absolute_difference_USD'] == 63000000)

    selected_fx = {}
    for release, stamp in [(2016, '20160104'), (2019, '20190102')]:
        path = f'data/raw/history_expansion/fx_{release}.html'
        sid = source('fed_g5a_' + stamp, path, f'https://www.federalreserve.gov/releases/g5a/{stamp}/',
                     f'Federal Reserve G.5A annual FX release {stamp}; historical CNY per USD',
                     'Board of Governors of the Federal Reserve System')
        soup = BeautifulSoup((ROOT / path).read_text(), 'html.parser')
        header = next(row for row in soup.select('table tr')
                      if 'COUNTRY' in row.get_text() and 'CURRENCY' in row.get_text())
        years = [int(v) for v in re.findall(r'\b20\d{2}\b', header.get_text(' ', strip=True))]
        row = next(row for row in soup.select('table tr') if row.get_text(' ', strip=True).startswith('CHINA,P.R.'))
        cells = [cell.get_text(' ', strip=True) for cell in row.find_all(['td', 'th'])]
        for year, value in zip(years, cells[2:]):
            if year in range(2013, 2019):
                rate = float(value)
                if year in selected_fx:
                    check('historical_FX_release_overlap_agrees', selected_fx[year]['cny_per_unit'] == rate, year=year)
                selected_fx[year] = dict(fx_id=f'uh4_fed_{year}_USD', year=year, currency='USD',
                                         usd_per_unit=1, cny_per_unit=rate, cny_per_usd=rate,
                                         raw_rate=rate, raw_direction='CNY_per_USD', source_id=sid,
                                         source_locator=f'G.5A annual table; CHINA,P.R. YUAN; {year}',
                                         method='USD numeraire identity; CNY conversion uses year-specific official annual average')
    fx = [selected_fx[y] for y in sorted(selected_fx)]
    check('all_six_calendar_years_have_original_historical_FX', sorted(selected_fx) == list(range(2013, 2019)))

    for year in range(2013, 2019):
        a, b = fiscal[year], fiscal[year+1]
        amount = .75*a['amount'] + .25*b['amount']
        candidates = [(1-w)*a['amount'] + w*b['amount'] for w in (.15,.25,.35)]
        lower, upper = min(candidates)-500000, max(candidates)+500000
        notes = ('美国MRV留用收款，含非移民签证申请与边境通行卡；付款国籍和具体用途未分配。'
                 '以GAO同一实际留用收款系列桥接，CY=75%本财年+25%次财年；次财年权重15%–35%加原表百万美元取整。'
                 '该历史系列与2019起OMB账户现金系列存在口径／期间断点，GAO的FY2019=1910百万与OMB=1847百万差额63百万未强行调平。')
        parameters = dict(fiscal_amounts={str(year):a['amount'], str(year+1):b['amount']},
                          fiscal_source_locators={str(year):a['locator'], str(year+1):b['locator']},
                          next_fiscal_year_share_center=.25, next_fiscal_year_share_range=[.15,.25,.35],
                          source_rounding_USD=500000, original_precision='USD million',
                          calendar_timing_assumption='uniform retained collections within each fiscal year; not an observed calendar total',
                          nationality_allocation='none', category_allocation='none',
                          account_scope='GAO homogeneous fee-specific retained-collection series; MRV including BCC',
                          series_discontinuity='FY2019 GAO1910m versus OMB account5713501847m; no cross-series fiscal blend',
                          fiscal_control_series='GAO_22_104424_Table7',
                          quantity_is_null_for_account_control=True)
        flows.append(dict(id=f'uh4_usa_{year}_mrv_retained_bridge', payer='UNK', receiver='USA', year=year,
                          visa_group='other', visa_type='historical_MRV_retained_all_unallocated',
                          visa_label='MRV留用收款（类别未细分）', category_detail_status='unclassified',
                          amount=amount, lower=lower, upper=upper, currency='USD', quantity=None,
                          quantity_basis='official_retained_collection_without_matched_fee_event_count',
                          source_ids=[gao_sid], observation_ids=[a['oid'],b['oid']], method_id=MODEL,
                          model_status='retained_collection_calendar_bridge',
                          calculation_type='fiscal_actual_calendar_bridge',
                          financial_basis='retained_collections_from_fee_specific_GFMS_series',
                          origin_basis='unallocated_nationality', period_start=f'{year}-01-01',
                          period_end=f'{year}-12-31', period_type='calendar_year_model',
                          period_label=f'{year}自然年留用收款模型', notes=notes, parameters=parameters))
        ranges.append(dict(receiver='USA', year=year, amount=amount, lower=lower, upper=upper, currency='USD',
                           range_method='同一GAO留用收款系列；次财年权重15%–35%与百万美元原表取整；保留GAO/OMB系列断点'))
        coverage.append(dict(receiver='USA', destination='USA', year=year,
                             coverage_status='retained_collection_calendar_bridge_unallocated',
                             scope='MRV retained collections including BCC, GAO homogeneous fiscal series',
                             source_ids=[gao_sid], fiscal_years=[year,year+1],
                             financial_basis='retained_collection', quantity_status='not_available_for_financial_control',
                             category_detail_status='unclassified', series_break_after_calendar_year=2018, notes=notes))

    models = [dict(model_id=MODEL, destination='USA', years=list(range(2013,2019)),
                   status='retained_collection_calendar_bridge', source_ids=[gao_sid],
                   title='美国MRV历史留用收款2013–2018（与后续OMB现金账户系列有断点）',
                   formula='CY[y]=0.75*GAO_MRV_retained_FY[y]+0.25*GAO_MRV_retained_FY[y+1]',
                   parameters=dict(next_fiscal_year_share=[.15,.25,.35], source_rounding_USD=500000),
                   limitations=['自然年是均匀收款假设的期间桥接；15%–35%是期间情景，不是统计置信区间。',
                                'MRV含BCC，排除互惠签发费、其他领事费、护照、SEVIS和USCIS；数量为空。',
                                'GAO原表为留用收款，保留其财务定义；不能直接等同OMB单一571350账户。',
                                'FY2019 GAO1910m与OMB1847m相差63m，未唯一解释；仅在GAO同系列内桥接2013–2018，2019以后主边沿用已有独立来源。',
                                '未用当前国籍、旅游人数、签发量或类别份额回填付款方和申请人数。'])]
    source_ids = {row['source_id'] for row in sources}
    observation_ids = {row['observation_id'] for row in observations}
    check('unique_identifiers', len(source_ids)==len(sources) and len(observation_ids)==len(observations) and
          len({row['id'] for row in flows})==len(flows))
    check('six_disjoint_pre2019_calendar_models', len(flows)==6 and [row['year'] for row in flows]==list(range(2013,2019)))
    check('no_gao_omb_fiscal_blend', all(row['source_ids']==[gao_sid] and
          all('mrv_retained_collection_actual' in oid for oid in row['observation_ids']) for row in flows))
    check('all_references_resolve_and_no_invented_payers_or_counts', all(
          set(row['source_ids'])<=source_ids and set(row['observation_ids'])<=observation_ids and
          row['payer']=='UNK' and row['quantity'] is None and row['visa_group']=='other' and
          row['lower']<=row['amount']<=row['upper'] for row in flows))
    existing = {}
    for path in (ROOT/'data/estimates').glob('*flows.json'):
        if path == EST:
            continue
        obj = json.loads(path.read_text())
        for row in obj if isinstance(obj,list) else obj.get('flows',[]):
            existing.setdefault((row.get('receiver',row.get('destination')),row.get('year')), []).append(path.name)
    overlap = [dict(year=row['year'], files=existing['USA',row['year']]) for row in flows if ('USA',row['year']) in existing]
    check('no_existing_USA_receiver_year_overlap', not overlap, overlap=overlap)
    check('all_FX_references_resolve', all(row['source_id'] in source_ids for row in fx))
    check('all_destination_controls_equal_edges', all(row['amount']==next(f['amount'] for f in flows if f['year']==row['year']) for row in ranges))

    report = dict(package='us_history_v4', as_of=ASOF, added_calendar_years=list(range(2013,2019)),
                  destination='USA', financial_definition='MRV retained collections, including BCC',
                  source_series='GAO-22-104424 Table7', source_count=len(sources),
                  fiscal_observations=len(observations), flows=len(flows), models=len(models),
                  fx_rows=len(fx), checks=len(checks), checks_passed=sum(row['passed'] for row in checks),
                  fiscal_actuals_USD_million=dict(zip(range(2013,2020),millions)),
                  source_conflicts=conflicts, annual_summary=ranges)
    for name, data in [('sources',sources),('observations',observations),('fee_rules',[]),('fx',fx),
                       ('coverage',coverage),('checks',checks),('source_conflicts',conflicts),('report',report)]:
        dump(OUT/(name+'.json'),data)
    dump(EST,dict(flows=flows,models=models,destination_ranges=ranges))
    paragraphs = ['# 美国MRV历史留用收款：2013—2018', '',
        '离线复算：`.research-venv/bin/python scripts/research_us_history_v4.py`。', '',
        f'新增6个美国收款方自然年、6条UNK付款来源费用边、1个模型、8条财年原值及6条同年汇率；{len(checks)}项检查通过。', '',
        'GAO-22-104424附录IV表7（无障碍PDF第98页、印刷页89）明确给出MRV留用收款，单位百万美元：FY2013—2019依次为1704、1967、2173、2157、2025、1957、1910。Figure4独立重复相同系列。GAO以国务院GFMS等系统实际数据进行绩效审计，明确其“revenues”指留用收款（retained collections），并非全部领事收费。MRV包含非移民签证申请费及BCC，不含互惠签发费、护照、其他领事费、USCIS、SEVIS。', '',
        '同系列内CY[y]=75%×FY[y]+25%×FY[y+1]。美国财年10月1日至次年9月30日；次财年10—12月权重15%—35%与原表±0.5百万美元取整形成期间情景。付款国籍、用途及相同口径付款事件数没有匹配分母，保留UNK、未细分和quantity=null。', '',
        'FY2019的GAO留用收款1910百万美元，与OMB预算附录实际MRV账户571350的1847百万相差63百万。差异在原件中未得到唯一解释，来源冲突完整保留。历史6个自然年仅使用GAO同系列；CY2018两端为GAO1957m/1910m，没有把GAO2018与OMB2019拼接。GAO2019不新增主费用边。与2019以后独立OMB现金系列比较时存在来源／财务口径断点。', '',
        'GAO直接HTTP下载返回403，因此归档Web工具从原官方150页PDF读取的全文文本层，完整覆盖L0—L5310全部5311行，保存原页号、行号、32次原始响应JSON及完整性清单；不是搜索摘要。文本层全文快照不等同原PDF字节副本；没有将错误响应保存为伪PDF。OMB附录保留原始HTML及SHA256，2019 actual列与两个同名MRV行分别验证。', '',
        'USD为原币和美元计价单位；人民币换算采用既有归档Fed G.5A对应年度CNY/USD均值，2015跨两份发布的值一致。', '',
        '| 自然年 | 中心 USD百万 | 下界 USD百万 | 上界 USD百万 | CNY/USD年均 |',
        '|---|---:|---:|---:|---:|']
    paragraphs.extend(f"| {row['year']} | {row['amount']/1e6:.2f} | {row['lower']/1e6:.2f} | {row['upper']/1e6:.2f} | {selected_fx[row['year']]['cny_per_usd']:.4f} |" for row in ranges)
    (OUT/'README.md').write_text('\n'.join(paragraphs)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
