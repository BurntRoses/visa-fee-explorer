#!/usr/bin/env python3
"""Offline MFA-scope Thai visa-fee history from a published individual study.

The publication quotes administrative collections, not audited financial accounts.
Only the visa leaf is bridged from October–September fiscal years to calendar years.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import sys
import zipfile

from pypdf import PdfReader

sys.dont_write_bytecode = True
logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/thailand_history_v5'
OUT = ROOT / 'data/research/thailand_history_v5'
EST = ROOT / 'data/estimates/thailand_history_v5_flows.json'
ASOF = '2026-11-17'
SID = 'thv5_mfa_consular_fund_study2024'
MID = 'thv5_mfa_visa_receipts_calendar_bridge'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
EXPECTED = {
    2019: [2173290505, 7455321978, 189190124, 807221, 9818609829],
    2020: [1280273324, 2831587131, 187396425, 1171712, 4300428592],
    2021: [528286256, 303270002, 134306608, 1140429, 967005295],
    2022: [2201347824, 1051027353, 159729157, 1585916, 3413690249],
    2023: [3910993620, 3668640332, 219803010, 1743082, 7801180044],
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = RAW / 'consular-fund-study-2023.pdf'
    pdf = PdfReader(path)
    assert len(pdf.pages) == 64
    first = pdf.pages[0].extract_text()
    assert 'Individual Study' in first and '2567' in first
    table = pdf.pages[47].extract_text(extraction_mode='layout')
    scope = pdf.pages[46].extract_text(extraction_mode='layout')
    unit_context = pdf.pages[42].extract_text(extraction_mode='layout')
    assert 'ค่าธรรมเนียม' in table and 'การตรวจลงตรา' in table
    assert '16 สิงหาคม 2567' in table and 'สำนักบริหารการคลัง' in table
    assert 'บาท' in unit_context and '353,097,720.50' in unit_context
    assert '30' in scope and 'หนังสือเดินทาง' in scope
    # Preserve authoritative text; the downloaded filename does not date the study.
    for filename, text in [('table2-source-text.txt', table), ('mfa-scope-retention-source-text.txt', scope),
                           ('currency-context-source-text.txt', unit_context), ('publication-title-text.txt', first)]:
        (OUT / filename).write_text(text)
    sources = [dict(source_id=SID,
                    url='https://image.mfa.go.th/mfa/0/yZ0EO327fd/%E0%B9%80%E0%B8%AD%E0%B8%81%E0%B8%AA%E0%B8%B2%E0%B8%A3/nbt/nbt15/IS/15020.pdf',
                    publisher='Thailand Ministry of Foreign Affairs / Devawongse Varopakarn Institute of Foreign Affairs',
                    title='Individual Study: feasibility of a fund for Thai nationals overseas in emergencies; diplomatic executive course15,2024',
                    author_original='นายศรัณยู อัมพาตระการ', publication_year=2024,
                    administrative_data_as_of='2024-08-16', retrieved_at=ASOF,
                    source_quality='official_publication_quoting_administrative_data',
                    archive_kind='original_document', local_path=str(path.relative_to(ROOT)),
                    path=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    notes='MFA-hosted individual training study,not an audit report. PDFp48/printed39/Table2 quotes Bureau of Financial Administration data as of16August2024. '
                          'Visa-fee leaf only;passport/legalisation/ID/total and30%retention allocations excluded. '
                          'FY2019–2023 is BuddhistEra2562–2566. THB identified from same-document fiscal-currency context;table does not reprint unit or scale. '
                          'Source total-minus-components residuals FY2019:+1,FY2021:+2000,FY2022:-1 retained without altering visa leaf.')]
    extracted, obs, annual, oidmap = [], [], {}, {}
    labels = ['passport_fees', 'visa_fees', 'legalisation_fees', 'national_ID_card_fees', 'reported_total']
    for line in table.splitlines():
        if not re.match(r'\s*256[2-6]\s', line):
            continue
        numbers = [int(x.replace(',', '')) for x in re.findall(r'\d[\d,]*', line)]
        assert len(numbers) == 6
        be, values = numbers[0], numbers[1:]
        year = be - 543
        assert values == EXPECTED[year], (year, values)
        residual = values[-1] - sum(values[:4])
        extracted.append(dict(fiscal_year_end=year, fiscal_year_BuddhistEra=be,
                              period_start=f'{year-1}-10-01', period_end=f'{year}-09-30',
                              **dict(zip(labels, values)), sum_four_fee_components=sum(values[:4]),
                              reported_total_minus_components=residual, currency='THB',
                              printed_unit_on_table=False, scale_applied=1,
                              currency_identification='same-document Thai fiscal-currency context;table unit omitted',
                              raw_line=line.strip(), source_id=SID,
                              source_locator=f'PDFp48/printed39/Table2;rowBE{be}'))
        amount = values[1]
        oid = f'thv5_mfa_visa_fy{year}_reported_collections'
        obs.append(dict(observation_id=oid, destination='THA', nationality='UNK', origin_basis='unallocated',
                        year=year, metric='visa_fee_published_administrative_collections',
                        raw_metric='ค่าธรรมเนียมการตรวจลงตรา', value=amount, unit='THB',
                        visa_group='other', visa_type='mfa_visa_fee_collections',
                        period_start=f'{year-1}-10-01', period_end=f'{year}-09-30', period_type='fiscal_year',
                        source_id=SID, source_ids=[SID], source_locator=f'PDFp48/printed39/Table2;BE{be};visa-fee column',
                        calculation_type='direct_observation', eligible_money_ledger=False,
                        receipt_status='published_administrative_collection_statistics',
                        audited_status='not_established_by_individual_study',
                        account_scope='MFA-collected visa fees only;not Ministry of Interior VOA',
                        printed_unit_on_table=False, unit_identification='THB from same-document fiscal context;not printed table header',
                        source_table_total_minus_components=residual,
                        notes='官方发布个人研究转引财政管理局2024-08-16行政收费统计，非审计报告；只取签证费叶列。'
                              '原财年保留，不作为额外自然年边。表页未重印单位，按同文稿泰铢财政语境识别。'))
        annual[year], oidmap[year] = amount, oid
    assert sorted(annual) == list(range(2019, 2024))
    assert {r['fiscal_year_end']:r['reported_total_minus_components'] for r in extracted} == {2019:1, 2020:0, 2021:2000, 2022:-1, 2023:0}
    obs.append(dict(observation_id='thv5_same_document_fiscal_currency_context', destination='THA',
                    nationality='UNK', origin_basis='unallocated', year=2024,
                    metric='same_document_fund_amount_currency_context', raw_metric='Fund amount denominated inบาท',
                    value=353097720.50, unit='THB', visa_group='other', visa_type='context_not_visa_receipts',
                    source_id=SID, source_ids=[SID], source_locator='PDFp43/printed34;353097720.50บาท',
                    period_type='document_context', calculation_type='direct_observation',
                    eligible_money_ledger=False, context_only=True,
                    notes='同文稿基金财政金额明确บาท，仅用于货币语境；不是签证收费，不是表2单位的直接复印。'))
    flows, ranges = [], []
    for year in range(2019, 2023):
        current, following = annual[year], annual[year+1]
        scenario = {str(w):w*current+(1-w)*following for w in [.6, .75, .9]}
        amount, lower, upper = scenario['0.75'], min(scenario.values()), max(scenario.values())
        notes = ('泰国外交部收取签证费的已发布行政统计，非审计报告。'
                 '以本年结束财年75%加下一财年25%桥接自然年；共同权重60%—90%是时间分配情景，非实测区间。'
                 '疫情期间季节分布可超出该情景范围。只覆盖外交部收费，不含内政部落地签、护照、认证、身份证或全部领事费。'
                 '原表三处总计与分项不合已保留，未调整签证费叶值；30%留存分账不重复增加收入。'
                 '付款国籍、用途细分及付费申请数未知。')
        flows.append(dict(id=f'thv5_tha_{year}_mfa_visa_calendar_bridge', payer='UNK', receiver='THA',
                          year=year, visa_group='other', visa_type='mfa_visa_fee_calendar_bridge',
                          visa_label='外交部签证收费行政统计的自然年桥接', category_detail_status='unclassified',
                          amount=amount, lower=lower, upper=upper, currency='THB', quantity=None,
                          quantity_basis='no_matching_paid_application_denominator',
                          source_ids=[SID], observation_ids=[oidmap[year], oidmap[year+1]],
                          method_id=MID, model_status='published_administrative_receipts_calendar_bridge_estimate',
                          calculation_type='conditional_scenario', origin_basis='unallocated',
                          period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                          period_type='calendar_year_model', period_label=str(year), notes=notes,
                          parameters=dict(account_scope='MFA-collected visa fee leaf only;Interior VOA excluded',
                                          fiscal_year_start_month=10, fiscal_year_end_month=9,
                                          fiscal_currency='THB', current_fiscal_receipts_THB=current,
                                          next_fiscal_receipts_THB=following,
                                          calendar_year_formula='w*FY[y]+(1-w)*FY[y+1]',
                                          calendar_weight_central=.75, calendar_weight_range=[.6,.9],
                                          shared_parameter='same w for all calendar-year bridges',
                                          scenario_amounts_THB=scenario,
                                          published_administrative_collections=True, audited_receipts=False,
                                          calendar_receipts_observed=False, nationality_allocation='none',
                                          printed_unit_on_table=False,
                                          unit_identification='THB from same-document fiscal-currency context',
                                          range_method='同一FY时间分配参数w=0.6/0.75/0.9；每年取相应情景最小最大，非置信区间',
                                          excluded=['passport fees','legalisation fees','national ID fees','all-consular-fee total','30%retention allocations','Ministry of Interior VOA'])))
        ranges.append(dict(receiver='THA', year=year, currency='THB', amount=amount, lower=lower, upper=upper,
                           range_method='Conditional FY timing scenarios w=.6/.75/.9;not confidence interval.'))
    wb = next(s for s in json.loads((ROOT/'data/research/africa_expansion_v3/sources.json').read_text()) if s['source_id']=='afx_wb_exchange_rates')
    wbpath = ROOT / wb['local_path']
    assert hashlib.sha256(wbpath.read_bytes()).hexdigest() == wb['sha256']
    sources.append(wb)
    z = zipfile.ZipFile(wbpath)
    fn = next(n for n in z.namelist() if n.startswith('API_') and n.endswith('.csv'))
    rows = list(csv.reader(io.StringIO(z.read(fn).decode('utf-8-sig'))))
    row = dict(zip(rows[4], next(r for r in rows[5:] if len(r)>1 and r[1]=='THA')))
    fx = []
    for year in range(2019, 2023):
        rate = float(row[str(year)])
        assert rate > 0
        fx.append(dict(fx_id=f'thv5_wb_tha_{year}', year=year, currency='THB', raw_rate=rate,
                       raw_direction='currency_per_USD', usd_per_unit=1/rate,
                       source_id=wb['source_id'], source_ids=[wb['source_id']],
                       source_locator=f'{fn};THA;{year};PA.NUS.FCRF', method='World Bank/IMF annual official exchange rate,period average'))
    coverage = []
    for year in range(2019, 2023):
        for group in GROUPS:
            available = group == 'other'
            coverage.append(dict(code='THA', destination='THA', name='泰国', region='亚洲', year=year,
                                 visa_group=group, status='amount_modeled' if available else 'not_found',
                                 fee_known=False, fee_current_snapshot_known=False, quantity_known=False,
                                 quantity_context_known=False, arrival_context_known=False,
                                 amount_known=False, amount_modeled=available, nationality_known=False,
                                 category_detail_status='unclassified_aggregate' if available else 'no_classified_observation',
                                 notes=next(f['notes'] for f in flows if f['year']==year) if available else '未取得独立用途收费，不臆拆外交部签证费总叶列。',
                                 source_ids=[SID] if available else [], searched_as_of=ASOF))
    overlap, checked = [], []
    for p in sorted(EST.parent.glob('*_flows.json')):
        if p == EST:
            continue
        checked.append(str(p.relative_to(ROOT)))
        for f in json.loads(p.read_text()).get('flows', []):
            if f.get('receiver')=='THA' and f.get('year') in range(2019, 2023) and (f.get('amount') or 0)>0:
                overlap.append((p.name, f.get('id')))
    assert not overlap, overlap
    assert len({o['observation_id'] for o in obs}) == len(obs)
    sids, oids = {s['source_id'] for s in sources}, {o['observation_id'] for o in obs}
    assert all(set(f['source_ids'])<=sids and set(f['observation_ids'])<=oids for f in flows)
    assert all(f['payer']=='UNK' and f['quantity'] is None and 0<=f['lower']<=f['amount']<=f['upper'] for f in flows)
    checks = dict(as_of=ASOF, sources=len(sources), observations=len(obs), fees=0, fx=len(fx),
                  flows=len(flows), models=1, coverage_rows=len(coverage), receivers=['THA'], years=list(range(2019,2023)),
                  raw_fiscal_years=list(annual), raw_fiscal_visa_receipts_THB=annual,
                  totals_native={f"THA_{r['year']}_THB":r['amount'] for r in ranges},
                  table_total_minus_four_components_THB={r['fiscal_year_end']:r['reported_total_minus_components'] for r in extracted},
                  all_five_amount_columns_preserved=True, table_visually_verified=True,
                  printed_unit_on_table=False, currency_identified_from_document_context=True,
                  source_not_claimed_audit=True, fiscal_raw_rows_not_extra_calendar_edges=True,
                  mfa_scope_only_interior_voa_excluded=True, retention_not_added_twice=True,
                  all_payers_unknown=True, no_claimed_application_denominators=True,
                  no_arrival_times_fee_model=True, no2023_2025_backfill=True,
                  no_duplicate_existing_receiver_year=True, overlap_checked_packages=checked)
    model = dict(model_id=MID, destination='THA', years=list(range(2019,2023)),
                 status='published_administrative_fiscal_collections_calendar_bridge_subset',
                 formula='0.75*MFA_visa_fiscal_receipts[y]+0.25*MFA_visa_fiscal_receipts[y+1]',
                 limitations=['外交部培训个人研究引用行政统计，非审计报告。',
                              '仅MFA签证收费，不包括内政部落地签或其他领事费。',
                              '自然年是Oct—Sep财年时间桥接，疫情季节分布可能超出情景权重。',
                              '同一个w参数跨年共享，跨年边际低高不能直接相加作为联合区间。',
                              '表页未重印单位，THB依据同文稿泰国财政货币语境识别。',
                              '原表三处总计与分项差异完整保留，签证叶值不以总计倒推。',
                              'FY2023只有原财年观察，缺FY2024，不回填CY2023—2025。',
                              '国籍、用途、申请次数未知，全部UNK和空分母。'])
    package = dict(package='thailand_history_v5', as_of=ASOF, flows=flows, models=[model],
                   destination_ranges=ranges, subtotals=[], coverage_rows=len(coverage),
                   scope='MFA-only visa-fee administrative collections FY2019–2023 quoted in official individual study;CY2019–2022 timing bridges;not audited nationwide accounts')
    excluded = [dict(destination='THA', candidate=x, reason=y) for x,y in [
        ('Passport/legalisation/nationalID/total columns','Control extraction only;not visa money edges.'),
        ('30%consular retention and30%passport production allocations','Allocations of existing collections,not new receipts.'),
        ('Ministry of Interior visa on arrival','Not covered by this MFA administrative table.'),
        ('CY2023–2025 backfill','FY2024 matched administrative collection missing;no extrapolation.'),
    ]]
    for filename, obj in [('sources.json',sources),('observations.json',obs),('fee_rules.json',[]),
                          ('coverage.json',coverage),('fx.json',fx),('checks.json',checks),
                          ('table2_extracted_rows.json',extracted),('excluded_candidates.json',excluded)]:
        dump(OUT/filename,obj)
    dump(EST,package)
    (OUT/'README.md').write_text('''# 泰国外交部签证收费历史 v5

离线复算：`.research-venv/bin/python scripts/research_thailand_history_v5.py`。

官方MFA网站冻结PDF，2024年外交培训个人研究，非审计报告。PDF48/印刷39表2引用财政管理局2024-08-16行政统计。原文件名不代表文稿年度。

FY2019—2023签证叶列为THB7,455,321,978／2,831,587,131／303,270,002／1,051,027,353／3,668,640,332。泰国财年为上年10月1日至当年9月30日。只取签证列，不含护照、认证、身份证和全部领事费，也不包括内政部落地签。留存30%及护照生产30%是已有收入分账，不重复相加。

CY2019—2022中心为0.75FY[y]+0.25FY[y+1]；共同时间权重w=0.6／0.75／0.9为条件情景，非置信区间。疫情期间季节分布可能超出此范围。跨年使用同一个w，跨年边际上下界不直接相加。FY2023保留原观察，缺FY2024，不回填CY2023—2025。

完整五金额列、四项和及残差保留在`table2_extracted_rows.json`。原表总计减四项和：FY2019+1、FY2021+2000、FY2022−1THB，其余0；未修改原值或以总计倒推签证列。表页未单独印货币/比例单位，按同文稿明确บาท的财政语境识别THB，原整数×1，不假称表头明示。

付款国籍和申请次数未知，4条边全部UNK、quantity=null。4条同年年均THB/USD汇率复用已冻结World Bank/IMF CSV及原source_id/hash。`checks.json`保留来源、期间、分类、引用、重复边和金额范围检查。
''')
    print(json.dumps(checks,ensure_ascii=False))


if __name__ == '__main__':
    main()
