#!/usr/bin/env python3
"""Reproduce Philippines context observations from frozen official scans.

Read explicit printed cells manually, pin original hashes in inputs.json, and
check the annual/quarter identities. This does not produce money-model flows.
"""
from __future__ import annotations

import calendar
from decimal import Decimal
import hashlib
import json
import logging
from pathlib import Path
import sys

from pypdf import PdfReader

sys.dont_write_bytecode = True
logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/philippines_expansion_v7'
OUT = ROOT / 'data/research/philippines_expansion_v7'
CUT = '2026-11-17'


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def period(year, quarter=None, half=None):
    if quarter:
        a,b=quarter*3-2,quarter*3
        return dict(year=year,period_start=f'{year}-{a:02d}-01',
                    period_end=f'{year}-{b:02d}-{calendar.monthrange(year,b)[1]}',
                    period_type='calendar_quarter', period_label=f'{year}Q{quarter}')
    if half:
        return dict(year=year,period_start=f'{year}-01-01',period_end=f'{year}-06-30',
                    period_type='calendar_half_year',period_label=f'{year}H1')
    return dict(year=year,period_start=f'{year}-01-01',period_end=f'{year}-12-31',
                period_type='calendar_year',period_label=str(year))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    inputs=json.loads((RAW/'inputs.json').read_text())
    sources=[];obs=[];checks=[];conflicts=[];coverage=[]
    for item in inputs['sources']:
        p=RAW/item['filename'];b=p.read_bytes();sha=hashlib.sha256(b).hexdigest()
        assert sha==item['sha256'], f'Changed original; re-read scan: {p.name}'
        pages=None
        if p.suffix=='.pdf':
            assert b.startswith(b'%PDF')
            pdf=PdfReader(p,strict=False);pages=len(pdf.pages)
            assert pages==1
            assert len(pdf.pages[0]['/Resources'].get('/XObject',{}))>0
        sources.append(dict(source_id=item['source_id'],title=item['title'],
            publisher='Philippines Bureau of Immigration',institution='Philippines Department of Justice / Bureau of Immigration',
            url=item['url'],local_path=str(p.relative_to(ROOT)),retrieved_at=CUT,
            sha256=sha,bytes=len(b),pages=pages,source_quality='official_primary',
            capture_method='http_download_original',archive_status='original_archived',
            archive_kind='original_scanned_pdf' if pages else 'original_official_index_html',
            evidence_use=item['evidence_use'],
            notes='扫描PDF由pypdf确认真实Page树及图片对象、pdfium实际渲染；没有把pdfplumber空文本/0页结果当作空白报告。' if pages else '发布机构的透明度报表索引，保留原始下载链接。'))
    checks.append(dict(check='all_registered_originals_hash_and_real_page_content_verified',passed=True,source_count=len(sources)))
    source_ids={s['source_id'] for s in sources}
    base=dict(destination='PHL',reporting_country='PHL',origin='UNK',nationality='UNK',
        origin_basis='unallocated_nationality',context_only=True,eligible_money_ledger=False,
        source_status='published_actual',calculation_type='published_statistical_series',
        extraction_method='manual_visual_transcription_of_explicit_scanned_table_cells',
        year_type='calendar',flow_direction='inbound')

    # FAR5 row is a mixed passport+visa account, not visa revenue alone.
    for yr, vals in inputs['passport_and_visa_fees'].items():
        year=int(yr);sid=f'ph7_far5_{year}'
        numbers=[Decimal(v) for v in vals['quarters']]
        total=Decimal(vals['total'])
        assert sum(numbers)==total
        checks.append(dict(check=f'far5_{year}_passport_visa_actual_quarters_sum_reported_total',passed=True,
                           total_PHP=str(total),quarters=len(numbers)))
        for q,value in enumerate(numbers,1):
            obs.append(dict(base,observation_id=f'ph7_passport_visa_collections_{year}_q{q}',
                **period(year,q),metric='passport_and_visa_fee_collections_mixed',
                value=int(value) if value==int(value) else float(value),unit='PHP',currency='PHP',
                original_value=vals['quarters'][q-1],original_unit='Philippine pesos',
                source_id=sid,source_ids=[sid],source_locator=f'FAR5 PDF1, A General Fund / Non-Tax / Passport and Visa Fees, UACS4-02-01-12000, actual collections Q{q}',
                visa_type='passport_and_visa_unseparated',visa_group='mixed',observation_domain='finance',
                financial_basis='actual_revenue_and_other_receipts_collections',
                aggregation_role='period_component',series_id='phl_bi_passport_visa_mixed_actual_quarterly',
                series_label='菲律宾移民局 · 护照及签证混合实收 · 季度',
                scope='Bureau_of_Immigration_General_Fund_Passport_and_Visa_Fees_UACS_4020112000',
                notes='护照及签证混合叶项实收，不是纯签证费；与年度/半年总额重叠。目标、国库缴款、处理费、ACR卡、快车道费、罚款及其他服务收入均未相加。未换汇或纳入费用账。'))
        half=year==2024
        obs.append(dict(base,observation_id=f'ph7_passport_visa_collections_{year}_{"h1" if half else "annual"}',
            **period(year,half=half),metric='passport_and_visa_fee_collections_mixed',
            value=int(total),unit='PHP',currency='PHP',original_value=vals['total'],original_unit='Philippine pesos',
            source_id=sid,source_ids=[sid],source_locator='FAR5 PDF1, Passport and Visa Fees / UACS4-02-01-12000 / actual collections TOTAL (column8)',
            visa_type='passport_and_visa_unseparated',visa_group='mixed',observation_domain='finance',
            financial_basis='actual_revenue_and_other_receipts_collections',aggregation_role='total',
            series_id='phl_bi_passport_visa_mixed_actual_halfyear' if half else 'phl_bi_passport_visa_mixed_actual_annual',
            series_label='菲律宾移民局 · 护照及签证混合实收 · '+('半年' if half else '年度'),
            scope='Bureau_of_Immigration_General_Fund_Passport_and_Visa_Fees_UACS_4020112000',
            notes='原表actual collections TOTAL列，护照/签证未分，仅作财政背景，不能作为菲律宾全部签证收入。'
                  +('只覆盖1月–6月，不乘2、不视为完整2024年。' if half else '与四个季度观察重叠，不相加。')))

    for yr, values in inputs['non_board_action'].items():
        year=int(yr);sid=f'ph7_bar1_{year}'
        for index,pair in enumerate(values['quarter_pairs']+[values['annual_pair']]):
            q=index+1 if index<4 else None
            pn,den=pair
            for component,value,metric,cn in [
                ('within_six_days',pn,'non_board_action_transactions_within_six_days','六日内办结'),
                ('indicator_denominator',den,'non_board_action_transactions_indicator_denominator','考核分母')]:
                conflict=year==2024 and (q==3 or q is None)
                obs.append(dict(base,observation_id=f'ph7_non_board_{component}_{year}_{"q"+str(q) if q else "annual"}',
                    **period(year,q),metric=metric,value=value,unit='transaction_events',
                    visa_type='non_board_action_unclassified',visa_group='unclassified',
                    observation_domain='visa_activity',source_id=sid,source_ids=[sid],
                    source_locator=f'BAR1 PDF1, Transactions Processed not Requiring Board Action (filing to implementation) within6days, Work Accomplished {"Q"+str(q) if q else "TOTAL"}, {"numerator" if component=="within_six_days" else "denominator"}',
                    original_value=f'{pn}/{den}',original_unit='visas' if values['explicit_visas_label'] else 'transactions (no unit label on this row)',
                    indicator_numerator=pn,indicator_denominator=den,
                    source_status='source_inconsistency_retained' if conflict else 'published_actual',
                    source_conflict_id='ph7_bar2024_q3_denominator' if conflict else None,
                    quality_issue=('2024年第3季度原表为3355/3335，同时标为100%；全年分母8964与季度分母合计8944相差20。保留原值，默认不选入展示汇总。' if conflict else None),
                    context_selection_default=not conflict,
                    aggregation_role='period_component' if q else 'total',
                    series_id=f'phl_bi_non_board_{component}_'+('quarterly' if q else 'annual'),
                    series_label=f'菲律宾移民局 · 无需Board Action事务{cn} · '+('季度' if q else '年度'),
                    scope='non_board_action_transactions_in_six_day_performance_indicator_only',
                    visa_scope_detail_status='visas_label_explicit' if values['explicit_visas_label'] else 'transaction_indicator_visa_scope_not_explicit_in_2024_row',
                    notes='官方绩效表分子/分母原始数量，分子是6日内完成，分母为该考核所涉事务；不等于全局签证签发或批准量，不区分新签证、延期与具体类别，不视为独立申请人数。年度与季度重叠。'
                          +('本年原表未标visas单位，仅保留事务指标口径。' if not values['explicit_visas_label'] else '该行在原表标有visas，但仍按指定处理事务解释。')
                          +('2024Q3原表3355/3335同时写100%；全年分母8964与季度合计8944不同，保留原数。' if conflict else '')))
        quarter_n=sum(p[0] for p in values['quarter_pairs']);quarter_d=sum(p[1] for p in values['quarter_pairs'])
        annual_n,annual_d=values['annual_pair']
        if year==2024:
            conflicts.append(dict(conflict_id='ph7_bar2024_q3_denominator',source_id=sid,
                source_locator='PDF1, non-Board Action six-day row, Q3 and TOTAL',
                reported_q3_numerator=3355,reported_q3_denominator=3335,reported_q3_percentage='100.00%',
                reported_annual_numerator=annual_n,reported_annual_denominator=annual_d,
                sum_quarter_numerators=quarter_n,sum_quarter_denominators=quarter_d,
                discrepancy_denominator=annual_d-quarter_d,resolution='retain_all_printed_values_no_repair_no_rate_inference',
                notes='已放大原始扫描复核，非OCR识别问题。不能把分母擅改3355，也不据此求处理成功率。'))
            checks.append(dict(check='bar2024_printed_inconsistency_retained_without_imputation',passed=(quarter_n,quarter_d,annual_n,annual_d)==(8964,8944,8964,8964)))
        else:
            checks.append(dict(check=f'bar1_{year}_quarter_pairs_sum_annual_pair',passed=(quarter_n,quarter_d)==(annual_n,annual_d),numerator=annual_n,denominator=annual_d))

    # Earlier reports explicitly combine immigration and registration; keep a
    # separate series instead of treating them as visas or connecting the break.
    for yr, values in inputs['immigration_registration'].items():
        year=int(yr);sid=f'ph7_bar1_{year}'
        assert sum(values['quarters'])==values['total']
        for i,value in enumerate(values['quarters']+[values['total']]):
            q=i+1 if i<4 else None
            obs.append(dict(base,observation_id=f'ph7_immigration_registration_{year}_{"q"+str(q) if q else "annual"}',
                **period(year,q),metric='immigration_and_registration_transactions_processed_mixed',value=value,
                unit='transaction_events',visa_type='immigration_and_registration_mixed',visa_group='mixed',
                observation_domain='document_activity',source_id=sid,source_ids=[sid],
                source_locator=f'BAR1 PDF1, PI Set2 Documents & Transactions / No.of Immigration & Registration Transactions Processed, Work Accomplished {"Q"+str(q) if q else "TOTAL"}',
                aggregation_role='period_component' if q else 'total',
                series_id='phl_bi_immigration_registration_processed_'+('quarterly' if q else 'annual'),
                series_label='菲律宾移民局 · 移民及登记混合事务处理 · '+('季度' if q else '年度'),
                scope='immigration_and_registration_transactions_mixed_not_visa_issuance',
                notes='移民及登记混合业务事件，不当作签证签发、延期或申请人数量。2016/2017原报表部分季度经调整，采用Q4报告中发布的全年回顾值；不与后来的non-Board Action窄口径连接。'))
        checks.append(dict(check=f'bar1_{year}_mixed_immigration_registration_quarters_sum_total',passed=True))

    for year in range(2016,2026):
        rows=[r for r in obs if r['year']==year]
        coverage.append(dict(code='PHL',destination='PHL',year=year,period_start=f'{year}-01-01',period_end=f'{year}-12-31',
            status='official_mixed_fiscal_and_processing_context',context_only=True,eligible_money_ledger=False,
            source_ids=sorted({s for r in rows for s in r['source_ids']}),
            observation_count=len(rows),series_ids=sorted({r['series_id'] for r in rows}),
            money_coverage='passport_and_visa_mixed_actual_only' if year<=2023 else 'passport_and_visa_mixed_2024H1_only' if year==2024 else 'none',
            quantity_coverage='non_board_action_six_day_indicator' if str(year) in inputs['non_board_action'] else 'mixed_immigration_registration' if str(year) in inputs['immigration_registration'] else 'percentages_only_no_counts',
            pure_visa_revenue_identified=False,visa_grants_identified=False,
            source_conflict_ids=['ph7_bar2024_q3_denominator'] if year==2024 else [],
            notes='护照及签证混合收款、窄口径办理绩效与移民登记事务分序列，不相加，不使用年度目标或缴库额替代实收。2024财政数据仅H1；业务表完整全年。'))
    ids=[r['observation_id'] for r in obs]
    checks.extend([
        dict(check='all_observation_ids_unique',passed=len(ids)==len(set(ids))),
        dict(check='all_observation_sources_registered',passed=all(s in source_ids for r in obs for s in r['source_ids'])),
        dict(check='all_observations_context_only_no_visa_money_ledger',passed=all(r['context_only'] and not r['eligible_money_ledger'] for r in obs)),
        dict(check='all_payers_unallocated_no_bilateral_inference',passed=all(r['origin']=='UNK' and r['nationality']=='UNK' for r in obs)),
        dict(check='2024_mixed_collections_not_annualised',passed=not any(r['year']==2024 and r['unit']=='PHP' and r['period_type']=='calendar_year' for r in obs)),
        dict(check='source_2019_bar_percentages_not_converted_to_counts',passed=not any(r['year']==2019 and r['unit']=='transaction_events' for r in obs)),
        dict(check='no_visa_grant_or_total_visa_revenue_claim',passed=not any(r['metric'] in {'visas_granted','visas_issued','visa_fee_revenue'} for r in obs)),
        dict(check='all_observation_domains_use_project_standard_enums',passed=all(r['observation_domain'] in {'visa_activity','document_activity','finance'} for r in obs)),
        dict(check='all_source_conflict_rows_explained_and_excluded_from_default_selection',passed=all(r.get('quality_issue') and r.get('context_selection_default') is False for r in obs if r.get('source_conflict_id'))),
    ])
    assert all(r['passed'] for r in checks),checks
    for name,obj in [('sources.json',sources),('observations.json',obs),('coverage.json',coverage),
                     ('fx.json',[]),('checks.json',checks),('source_conflicts.json',conflicts),('flows.json',[])]:dump(name,obj)
    readme=dict(title='菲律宾移民局财务与办理背景 v7',sources=len(sources),observations=len(obs),
        coverage_years=list(range(2016,2026)),checks=len(checks),money_flows_added=0,
        rebuild_command='.research-venv/bin/python scripts/research_philippines_expansion_v7.py',
        method='真实官方一页扫描PDF逐格人工读取，原件SHA冻结；pypdf确认Page树和XObject，pdfium实际渲染，未用OCR猜数。',
        fiscal_scope='2016–2023完整全年及2024H1的Passport and Visa Fees UACS4-02-01-12000实收叶项，护照及签证未分。只作PHP原币财政背景，不换汇、不入签证费用账。',
        quantity_scope='2018、2020–2025无需Board Action六日内办理指标分子和分母；2016/2017移民及登记混合事务。均不是签证签发总量，不区分新签证和延期。2019表只有百分比，未推算数量。',
        source_conflicts='2024Q3为3355/3335且写100%；全年8964/8964与季度分母和8944不符。保留全部原数和冲突，不修补。',
        annualisation='季度、半年、年度为重叠观察；H1不倍增，分子/分母不相加。',
        fx='[]：混合财政观察保持PHP；没有可入账的独立签证收费叶项。',
        evidence_files=['data/raw/philippines_expansion_v7/inputs.json','source_conflicts.json'],
        excluded=['全部移民局收入、Processing Fees、Other Service Income、Clearance/Certification、ACR卡、Express Lane及罚款不能全算签证收入。',
                  'FAR年度目标、累计缴库及实际收款分列，未把目标和缴库当成同一收入。',
                  'BAR业务绩效中比例或处理时限不转换成新签发量。'])
    dump('README.json',readme)
    (OUT/'README.md').write_text('# 菲律宾移民局财务与办理背景 v7\n\n'+readme['method']+'\n\n'+readme['fiscal_scope']+'\n\n'+readme['quantity_scope']+'\n\n'+readme['source_conflicts']+'\n\n重建：`'+readme['rebuild_command']+'`\n',encoding='utf-8')
    print(json.dumps(dict(sources=len(sources),observations=len(obs),coverage=len(coverage),checks=len(checks),all_passed=True,money_flows=0)))


if __name__=='__main__':main()
