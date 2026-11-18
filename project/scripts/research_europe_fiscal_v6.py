#!/usr/bin/env python3
"""Cyprus 2018–2025 MFA visa-revenue account from archived indexed facts.

The government originals return403. Every source is an explicit fact_excerpt;
no local PDF and no audited-original archive identity is claimed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/europe_fiscal_v6'
OUT=ROOT/'data/research/europe_fiscal_v6'
ASOF='2026-11-17'
HASHES={
 2019:'f0800fb7725edc48cac98fd95e2f12ea66bab1237a7d883f019371fe80458d9f',
 2020:'f8bbbe4ebe8299d0254202e799588656fdd869800301a187d7759fcc90ec5749',
 2021:'71376931a6023597b1f8bd6693c49e5dbf461d38bf3221b8e0c9184ebae5fe45',
 2022:'6f82204422c128cc8854dcf07cbae294b963456f629703dea76a18fc58e91d33',
 2024:'238cd4507f1eea9b2c275eb0f3175ef5190e4ef4a0e3f90e816ba133bddf9ede',
 2025:'3e279e0e32c9829c7a6885f80e46525277ba0ef546e593779a263860af055dc0',
}
EXPECTED={2018:2300468,2019:2121980,2020:576683,2021:1037430,
          2022:1630231,2023:7074013,2024:7164042,2025:9127170}


def write(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    if isinstance(value,list) and value and isinstance(value[0],dict):
        fields=list(dict.fromkeys(k for row in value for k in row))
        with (OUT/name.replace('.json','.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fields);w.writeheader()
            w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
                         for k,v in row.items()} for row in value)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sources,observations,controls,candidates,checks,coverage,excluded=[],[],[],[],[],[],[]
    def check(name,ok,**extra):
        checks.append(dict(check=name,passed=bool(ok),**extra))
        assert ok,(name,extra)
    for year,digest in HASHES.items():
        path=RAW/f'cyp{year}_indexed_excerpt.json'
        raw=path.read_bytes();h=hashlib.sha256(raw).hexdigest();doc=json.loads(raw)
        sid=f'ev6_cyp_revenue{year}_indexed'
        check(f'{year}_frozen_excerpt',h==digest,sha256=h,bytes=len(raw))
        check(f'{year}_archive_identity',doc['archive_kind']=='fact_excerpt'
              and doc['capture_method']=='search_service_indexed_excerpt' and doc['original_downloaded'] is False)
        check(f'{year}_official_domain',doc['source_url'].startswith('https://www.gov.cy/'))
        check(f'{year}_report_year',doc['document_year']==year and f'REVENUES {year}' in doc['source_excerpt'])
        facts=doc['normalized_facts'];quote=doc['source_excerpt']
        check(f'{year}_account_and_department','01373' in quote and 'Visas' in quote and '1701' in quote and '170100' in quote)
        check(f'{year}_currency',facts['currency']=='EUR' and ('€' in quote or 'EUR' in quote))
        check(f'{year}_column_order',facts['columns']==[f'{year-1} Actual Revenues EUR',f'{year} Actual Revenues EUR',f'{year} Budget EUR','Variance EUR'])
        actual_previous,actual,budget,variance=facts['values']
        check(f'{year}_actual_budget_variance',actual-budget==variance,actual=actual,budget=budget,published_variance=variance)
        for value in facts['values']:
            token=f'{abs(value):,}'.replace(',','.')
            check(f'{year}_number_{value}',token in quote,needle=token)
        sources.append(dict(source_id=sid,url=doc['source_url'],publisher='塞浦路斯共和国国库／财政部',
           title=f'Detailed Table of Revenues {year}, Table{doc["table"]}, MFA01373 Visas (indexed fact excerpt)',
           retrieved_at=ASOF,document_year=year,publication_date=None,
           source_quality='official_indexed_excerpt',archive_kind='fact_excerpt',
           capture_method='search_service_indexed_excerpt',original_downloaded=False,
           local_path=str(path.relative_to(ROOT)),path=str(path.relative_to(ROOT)),sha256=h,bytes=len(raw),
           source_locator=f'Table{doc["table"]}; Head17 > Department1701 > Office170100 > Revenue01373',
           search_reference=doc['search_reference'],
           notes='政府PDF直链返回403；归档的是官方PDF搜索索引事实摘录，未取得原始PDF。目录2026是迁站上传路径，统计年由表题和Actual Revenues列头确定。'))
        for y,amount,col in [(year-1,actual_previous,'previous_year_actual'),(year,actual,'current_year_actual')]:
            observations.append(dict(observation_id=f'ev6_cyp_{y}_01373_in_report{year}',
              source_id=sid,source_ids=[sid],destination='CYP',destination_display_name='塞浦路斯',
              origin='UNK',nationality='UNK',origin_basis='unallocated',
              year=y,period_start=f'{y}-01-01',period_end=f'{y}-12-31',period_type='calendar_year',
              metric='visa_fee_actual_revenue',raw_metric='Θεωρήσεις Εισόδου - Visas',
              account_code='01373',department_code='1701',office_code='170100',
              value=amount,unit='EUR',currency='EUR',quantity=None,
              source_locator=f'Table{doc["table"]}; 1701/170100; 01373; {y} Actual Revenues EUR',
              source_quote=quote,column_role=col,document_year=year,
              source_status='published_actual_revenue_indexed_excerpt',
              calculation_type='direct_observation',observation_domain='government_visa_receipts',
              visa_group='unclassified',category_detail_status='unclassified_aggregate',
              archive_kind='fact_excerpt',capture_method='search_service_indexed_excerpt',
              selected_annual_control=False,eligible_money_ledger=False,context_only=True,
              notes='外交部总部会计叶科目签证实收，未识别用途、国籍及匹配付费事件分母；未纳入领事、移民许可或其他收入。'))
        excluded.append(dict(document_year=year,account_code='01605',label='Consular Fees',
            previous_year=year-1,previous_year_value=facts['excluded_consular_values'][0],
            current_year=year,current_year_value=facts['excluded_consular_values'][1],
            currency='EUR',source_id=sid,eligible_money_ledger=False,
            reason='与01373 Visas分别列示，领事收入不相加。1701/170100父级收入也不相加。'))
    grouped=defaultdict(list)
    for o in observations:grouped[o['year']].append(o)
    for y,rows in sorted(grouped.items()):
        check(f'{y}_cross_vintage_agreement',{r['value'] for r in rows}=={EXPECTED[y]},
              values=[r['value'] for r in rows],reports=[r['document_year'] for r in rows])
        chosen=max(rows,key=lambda r:r['document_year'])
        chosen.update(selected_annual_control=True,context_only=False,
                      aggregation_role='selected_visa_receipt_leaf')
        for r in rows:
            if r is not chosen:r['aggregation_role']='non_additive_cross_vintage_check'
        amount=chosen['value']
        controls.append(dict(year=y,receiver='CYP',currency='EUR',amount=amount,
             account_code='01373',department_code='1701',office_code='170100',
             source_id=chosen['source_id'],observation_id=chosen['observation_id'],
             scope='MFA_170100_01373_visa_receipts',archive_kind='fact_excerpt',
             source_quality='official_indexed_excerpt',payer='UNK',visa_group='unclassified',
             nationality_known=False,matching_paid_quantity=None))
        candidates.append(dict(id=f'ev6_cyp_{y}_01373_UNK',payer='UNK',receiver='CYP',year=y,
          amount=amount,lower=amount,upper=amount,currency='EUR',quantity=None,
          quantity_basis='no_matching_paid_application_denominator',visa_group='unclassified',
          visa_type='MFA_01373_visa_receipts',visa_label='签证实收（用途未细分）',
          category_detail_status='unclassified_aggregate',source_ids=[chosen['source_id']],
          observation_ids=[chosen['observation_id']],method_id='ev6_cyp_MFA_visa_receipts',
          model_status='published_receipts_indexed_excerpt_scope_partial',
          calculation_type='direct_observation',origin_basis='unallocated',
          period_start=f'{y}-01-01',period_end=f'{y}-12-31',period_type='calendar_year',
          notes='外交部01373 Visas叶科目实收；来自官方PDF搜索索引摘录，无本地PDF原件。国籍和用途未知；未加01605领事、1701/170100父级或其他移民收费。',
          parameters=dict(account_code='01373',accounting_scope='MFA headquarters account170100',
            range_kind='published_account_amount_not_total_coverage_confidence',
            original_downloaded=False,archive_kind='fact_excerpt')))
        for group in ['visitor','student','work','family','other','unclassified']:
            coverage.append(dict(code='CYP',destination='CYP',name='塞浦路斯',region='欧洲',
             year=y,visa_group=group,status='fiscal_leaf_account' if group=='unclassified' else 'category_amount_not_identified',
             amount_known=group=='unclassified',fiscal_amount_known=True,
             quantity_known=False,quantity_context_known=False,nationality_known=False,
             category_detail_status='unclassified_aggregate' if group=='unclassified' else 'no_classified_observation',
             source_ids=list(dict.fromkeys(r['source_id'] for r in rows)),searched_as_of=ASOF,
             notes='外交部01373签证实收可用，官方PDF仅取得索引摘录；国籍、用途及匹配付费申请数量未识别。'
                   +(' 此类别未从签证账户合计拆分。' if group!='unclassified' else '')))
    check('continuous_eight_years',sorted(grouped)==list(range(2018,2026)))
    check('single_selected_leaf_per_year',all(v==1 for v in Counter(o['year'] for o in observations if o['selected_annual_control']).values()))
    check('no_budget_or_consular_addition',all(c['amount']==EXPECTED[c['year']] for c in candidates))
    check('unknown_payers_and_quantity',all(c['payer']=='UNK' and c['quantity'] is None for c in candidates))
    check('unique_ids',len({o['observation_id'] for o in observations})==len(observations))
    check('fact_excerpt_identity_all',all(s['archive_kind']=='fact_excerpt' and not s['original_downloaded'] for s in sources))
    write('sources.json',sources);write('observations.json',observations);write('annual_cash_controls.json',controls)
    write('model_candidates.json',candidates);write('coverage.json',coverage);write('excluded_consular_rows.json',excluded)
    write('checks.json',checks);write('fx.json',[])
    report=dict(package='europe_fiscal_v6',asof=ASOF,frozen=True,integration_status='independent_candidate_not_registered',
       source_count=len(sources),original_document_count=0,fact_excerpt_count=len(sources),
       observation_count=len(observations),selected_annual_control_count=len(controls),candidate_flow_count=len(candidates),
       coverage_rows=len(coverage),years=sorted(grouped),checks=len(checks),passed=sum(c['passed'] for c in checks),
       annual_controls=controls,duplicate_vintage_years=[y for y,rows in sorted(grouped.items()) if len(rows)>1],
       scope='Cyprus MFA1701/170100 account01373 Visas; excludes01605 and parent totals',
       nationality_identified=False,paid_application_denominator_identified=False,
       original_downloads='403; blocked HTML responses are excluded from sources',
       amount_2024_eur=EXPECTED[2024],amount_2025_eur=EXPECTED[2025],
       change_2025_eur=EXPECTED[2025]-EXPECTED[2024],
       notes='未把2026上传目录当作统计年；无双边国籍分配，未改共享注册、模型和UI。')
    write('report.json',report)
    table='\n'.join(f'| {c["year"]} | {c["amount"]:,} | {c["source_id"]} |' for c in controls)
    (OUT/'README.md').write_text(f'''# 塞浦路斯签证财政收入2018–2025（独立v6）

财政部／国库Detailed Table of Revenues中的外交部`17 > 1701 > 170100`叶科目`01373 Θεωρήσεις Εισόδου - Visas`。8年连续金额如下，货币EUR。

| 年份 | 签证实收EUR | 来源 |
|---|---:|---|
{table}

六份年表同时列上年Actual Revenues、本年Actual Revenues、本年Budget和Variance。12个实收单元格形成8个唯一年度值；2019、2020、2021、2024的跨报表比较列完全一致，控制每年只选最近一份报告。预算与差额用于列顺序复核，不加到收入中。2025比2024增加1,963,128 EUR。

**来源身份：6份官方搜索索引事实摘录，0份本地PDF原件。** gov.cy原始PDF直链返回403，源内容由search_service索引返回。每份档案写明`archive_kind=fact_excerpt`、`capture_method=search_service_indexed_excerpt`、`original_downloaded=false`，保留政府URL、搜索引用、原始表题与列名、01373行和排除的01605领事行。`2026/02`或`2026/03`是迁站上传目录；数据年度只按表题／列名识别。下载403响应与失败日志不计作有效来源。

金额是上述外交部账户实际收入；用途和付款国籍未披露，全部保留UNK，匹配付费申请数量为null，不生成每申请人均价。01605 Consular Fees单列排除；1701、170100及01父级不与01373重复合计。未据领馆位置、游客来源或当代份额猜分国籍。年度lower=upper表示该发布账户金额自身的记录值，不表示全渠道覆盖完整或原件已查验。

离线运行：`.research-venv/bin/python scripts/research_europe_fiscal_v6.py`。{len(checks)}项来源哈希、档案身份、年度列、官方域名、原文数字、预算差额、跨版本一致、连续年度及候选去重检查通过。`model_candidates.json`是8条候选；没有修改共享注册、金额总账或界面。全局接入可复用已有同年EUR／人民币汇率。

文件：`sources.json`、`observations.json/.csv`、`annual_cash_controls.json/.csv`、`model_candidates.json/.csv`、`coverage.json`、`excluded_consular_rows.json`、`report.json`、`checks.json`。
''')
    print(json.dumps({k:v for k,v in report.items() if k!='annual_controls'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
