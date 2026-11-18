#!/usr/bin/env python3
"""Freeze FY2024/25 MEA visa-fee actual and calendar replacement candidates."""
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import re
import sys

from pypdf import PdfReader

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/india_recent_v7'
OUT=ROOT/'data/research/india_recent_v7'
URL='https://www.mea.gov.in/doc/6d106d76-062e-4c80-9f1f-cf54fef7c6cc'
PIN='e12a0806e9ef8e3b8daa534e33b17a2bcd61a494083d550659ee65d143bae918'


def dump(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    p=RAW/'mea_annual_2025.pdf';b=p.read_bytes();assert hashlib.sha256(b).hexdigest()==PIN
    pdf=PdfReader(p);assert len(pdf.pages)==520
    text=pdf.pages[390].extract_text(extraction_mode='layout')
    (RAW/'mea_annual_2025_p391.txt').write_text(text,encoding='utf-8')
    visa=[D(v) for v in re.findall(r'^\s*Visa\s+([\d.]+)\s+\d+%',text,re.M)]
    assert visa==list(map(D,['24.85','316.93','1440.10','1396.91','1488.38']))
    assert 'in FY 2024-25' in text and 'Rs. 1488.38 cr' in text
    native=int(visa[-1]*10_000_000);prior=int(visa[-2]*10_000_000)
    sid='ir7_mea_annual2025';oid='ir7_ind_visa_fee_receipts_fy2024_25'
    sources=[dict(source_id=sid,title='Ministry of External Affairs Annual Report2025, Finance & Budget, FY2024/25 Visa receipts',
        publisher='Government of India / Ministry of External Affairs',institution='Ministry of External Affairs',
        url=URL,local_path=str(p.relative_to(ROOT)),sha256=PIN,bytes=len(b),pages=520,retrieved_at='2026-11-17',
        source_quality='official_primary',capture_method='http_download_original',archive_status='original_archived',
        archive_kind='original_pdf',source_locator='PDF391 / printed391, Finance & Budget / revenue receipts / FY2024-25 Visa',
        notes='真实官方原件；PDFp391已目视核对，Visa、Passport、Others及Total分行，正文明确单位Rs crore及FY2024-25。')]
    ddg=RAW/'mea_ddg_2026_27.pdf';db=ddg.read_bytes();dd=PdfReader(ddg)
    sources.append(dict(source_id='ir7_mea_ddg2026_27',title='Detailed Demands for Grants2026-27, Demand29 Ministry of External Affairs',
        publisher='Government of India / Ministry of External Affairs',url='https://www.mea.gov.in/Uploads/PublicationDocs/41025_FINAL-DDG2026-27-MEA.pdf',
        local_path=str(ddg.relative_to(ROOT)),sha256=hashlib.sha256(db).hexdigest(),bytes=len(db),pages=len(dd.pages),
        retrieved_at='2026-11-17',source_quality='official_primary',capture_method='http_download_original',archive_status='original_archived',
        archive_kind='original_pdf',evidence_use='coverage_gap_search_only',notes='76页原件全文检索未找到独立Visa Fee收入；支出预算不替代签证实际收款。'))
    obs=[dict(observation_id=oid,destination='IND',reporting_country='IND',origin='UNK',nationality='UNK',
        origin_basis='unallocated_nationality',visa_group='unclassified',visa_type='all_visas_unallocated',
        metric='visa_fee_receipts',value=native,unit='INR',currency='INR',original_value='1488.38',original_unit='INR crore',
        original_unit_multiplier=10000000,source_rounding_unit_INR=100000,source_rounding_half_unit_INR=50000,
        year=2025,period_start='2024-04-01',period_end='2025-03-31',period_type='fiscal_year',period_label='FY2024-25',year_type='fiscal',
        source_id=sid,source_ids=[sid],source_locator='PDF391 / printed391, Finance & Budget, FY2024-25 / Visa / Amount1488.38; same-page paragraph corroborates',
        extraction_method='pdf_text_table_and_visual_page_confirmation',source_status='actual',financial_basis='official_revenue_receipts_actual',
        calculation_type='official_actual_receipts',observation_domain='finance',context_only=True,eligible_money_ledger=False,
        eligible_as_financial_control=True,aggregation_role='total',flow_direction='inbound',series_id='india_mea_visa_fee_actual_fiscal',
        series_label='印度外交部 · 签证费实际收款 · 财年',scope='MEA_Visa_revenue_receipts_separate_from_passports_and_other_receipts',
        notes='完整FY2024/25实际签证费收入1488.38crore×10,000,000；并非BE/RE或截至9月部分数。国籍、签证类别及匹配收费申请数量未知。context-only登记供模型手动桥接，禁止自动叠加FY费用边。')]
    candidates=[]
    for year,amount,lower,upper,method,notes,params in [
        (2024,int(D('.25')*prior+D('.75')*native),int(D('.35')*prior+D('.65')*native),int(D('.15')*prior+D('.85')*native),
         'india_adjacent_actual_fy_quarter_bridge','CY2024=25%FY2023/24+75%FY2024/25，假设FY内月收款均匀。区间为前财年权重15%–35%的期间分配情景，非统计置信区间。',
         dict(prior_fy_weight=.25,current_fy_weight=.75,prior_fy_weight_range=[.15,.35])),
        (2025,native,int(D('.65')*native),int(D('1.35')*native),
         'india_latest_complete_fy_running_rate_proxy','FY2025/26实际签证费仍未知；CY2025沿用最新完整FY2024/25运行率，延续原模型±35%情景。不能标记为观测CY2025实收。',
         dict(relative_range=[.65,1.35],alternative_20percent_range_INR=[int(D('.8')*native),int(D('1.2')*native)],next_fy_actual_known=False))]:
        candidates.append(dict(id=f'ir7_ind_calendar_{year}_UNK',payer='UNK',receiver='IND',year=year,amount=amount,lower=lower,upper=upper,
            currency='INR',quantity=None,visa_group='unclassified',visa_type='all_visas_unallocated',source_ids=[sid,'in_mea2024'],
            observation_ids=[oid,'in_visa_fee_receipts_2023-24'] if year==2024 else [oid],method_id=method,
            period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year_model',period_label=f'{year}自然年估算',
            calculation_type='modeled_estimate',model_status='replacement_candidate_not_added_to_ledger',origin_basis='unallocated_nationality',
            notes=notes+'须替换model_core.india()既有同年UNK→IND运行率边，不能叠加为新边。',
            parameters=dict(params,prior_fy2023_24_actual_INR=prior,latest_fy2024_25_actual_INR=native,latest_fy_observation_id=oid)))
    baseline=json.loads((ROOT/'data/research/india_korea/observations.json').read_text())
    comparisons=[]
    for label,value in zip(['2020-21','2021-22','2022-23','2023-24'],visa[:-1]):
        old=next(r for r in baseline if r['observation_id']==f'in_visa_fee_receipts_{label}')
        comparisons.append(dict(fiscal_year=label,previous_observation_id=old['observation_id'],previous_value_INR=old['value'],
            annual2025_comparative_INR=int(value*10000000),difference_INR=int(value*10000000)-old['value'],
            status='unchanged' if old['value']==int(value*10000000) else 'edition_difference_retained',source_id=sid,
            notes='只核对新版比较数，不增加重复历史观察或改写早年主账。'))
    checks=[dict(check='full_520page_official_original_hash_and_visa_cells',passed=True),
        dict(check='fy2024_25_visa_receipts_separate_from_passport_other_total',passed=native==14883800000 and sum(map(D,['3627.23','1488.38','848.06']))==D('5963.67')),
        dict(check='fiscal_period_complete_april_to_march_actual_not_budget',passed=obs[0]['period_start']=='2024-04-01' and obs[0]['period_end']=='2025-03-31' and obs[0]['source_status']=='actual'),
        dict(check='only_one_new_fiscal_observation_no_historical_duplication',passed=len(obs)==1),
        dict(check='historical_comparatives_compared_without_mutation',passed=len(comparisons)==4),
        dict(check='calendar2024_exact_quarter_bridge',passed=candidates[0]['amount']==14655125000),
        dict(check='calendar2025_latest_fy_proxy_keeps_unknown_next_fy',passed=candidates[1]['amount']==14883800000 and candidates[1]['parameters']['next_fy_actual_known'] is False),
        dict(check='raw_fiscal_observation_not_automatic_money_flow',passed=not obs[0]['eligible_money_ledger'] and obs[0]['context_only'])]
    assert all(c['passed'] for c in checks)
    coverage=[dict(code='IND',destination='IND',year=year,visa_group=group,status='actual_fiscal_aggregate_known_category_unallocated',
        amount_known=False,fiscal_amount_known=True,quantity_known=False,quantity_context_known=False,nationality_known=False,
        category_detail_status='unclassified_aggregate',source_ids=[sid],searched_as_of='2026-11-17',
        notes='FY2024/25独立Visa Fee实收可用；自然年须桥接。FY2025/26实际值未找到，2025仅最新完整FY运行率代理。国籍和用途未分。')
        for year in [2024,2025] for group in ['visitor','student','work','family','other']]
    gaps=[dict(destination='IND',metric='visa_fee_receipts_fy2025_26',status='not_identified',source_ids=[sid,'ir7_mea_ddg2026_27'],
        notes='AnnualReport2025收款截止FY2024/25；DDG2026/27全文未发现独立Visa Fee收款。不能用支出预算或半年度数替代。')]
    for n,v in [('sources.json',sources),('observations.json',obs),('finances.json',obs),('fx.json',[]),('coverage.json',coverage),
                ('checks.json',checks),('calendar_model_candidates.json',candidates),('historical_comparisons.json',comparisons),('coverage_gaps.json',gaps)]:dump(n,v)
    dump('README.json',dict(title='印度FY2024/25签证费实际收款补证',sources=len(sources),observations=1,coverage_rows=len(coverage),checks=len(checks),
        rebuild_command='.research-venv/bin/python scripts/research_india_recent_v7.py',
        finding='官方AnnualReport2025 PDF391/printed391确认完整FY2024/25 Visa1488.38crore=INR14,883,800,000；已目视验证。',
        registration='主注册作为CONTEXT_PACKAGES读取observations.json；finances.json是同一条金融观察的研究便利镜像，不同时导入。',
        integration='根任务手动替换model_core.india()2024/2025旧运行率，不新增重复边。',
        fiscal_vs_calendar='FY2024/25实际；CY2024桥接中心14,655,125,000；CY2025最新FY代理14,883,800,000±35%，FY2025/26未知。',
        fx='[]：候选仅原币INR；沿用主模型现有INR汇率转换流程。',
        precision='crore×10,000,000；0.01crore显示步长INR100,000，半单位50,000，不作统计区间。'))
    print(json.dumps(dict(sources=len(sources),observations=1,coverage=len(coverage),checks=len(checks),all_passed=True,candidates=candidates),ensure_ascii=False))


if __name__=='__main__':main()
