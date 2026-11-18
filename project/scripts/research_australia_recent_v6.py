#!/usr/bin/env python3
"""Offline2025–26VAC revenue/cash update and complete-FY visitor throughput.

Revenue is recognised accounting income, not the cash-flow leaf. Both leaves
are retained. Calendar2025 bridge uses two completeFYs at fixed50/50, with
seasonality left an assumption. No money is allocated by consular location.
"""
from __future__ import annotations

import calendar
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

from pypdf import PdfReader
from entity_names import canonical_name, JURISDICTION_NOTE
from build_dataset import entity

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/australia_recent_v6'
OUT = ROOT / 'data/research/australia_recent_v6'
CUT = '2026-11-17'
URLS = {
    'annual-reports-index.html': 'https://www.homeaffairs.gov.au/reports-and-publications/reports/annual-reports',
    'home-affairs-annual-report-2025-26.pdf': 'https://www.homeaffairs.gov.au/reports-and-pubs/Annualreports/home-affairs-annual-report-2025-26.pdf',
    'annual-2024-25-comparison.pdf': 'https://www.homeaffairs.gov.au/reports-and-pubs/Annualreports/home-affairs-annual-report-2024-25.pdf',
    'visitor-june-2026.pdf': 'https://www.homeaffairs.gov.au/research-and-stats/files/visitor-visa-june-2026.pdf',
    'visitor-june-2025-comparison.pdf': 'https://www.homeaffairs.gov.au/research-and-stats/files/visitor-visa-june-2025.pdf',
}
GROUP_TO_SUBCLASS = {'ETA Tourist': '601', 'ETA Business': '601', 'eVisitor Tourist': '651',
                     'eVisitor Business': '651', 'Tourist Visitor': '600', 'Business Visitor': '600',
                     'Sponsored Tourist': '600', 'Total': 'all_visitor'}


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = list(dict.fromkeys(k for r in obj for k in r))
        with (OUT / name.replace('.json', '.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, keys); writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in r.items()} for r in obj)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources, obs, checks, revisions = [], [], [], []
    sids = {}
    for filename, url in URLS.items():
        path = RAW / filename
        if filename.endswith('.pdf'):
            assert path.read_bytes().startswith(b'%PDF'), filename
        sid = 'aur6_' + {'annual-reports-index.html': 'annual_index',
                         'home-affairs-annual-report-2025-26.pdf': 'annual_2026',
                         'annual-2024-25-comparison.pdf': 'annual_2025_comparison',
                         'visitor-june-2026.pdf': 'visitor_2026_06',
                         'visitor-june-2025-comparison.pdf': 'visitor_2025_06_comparison'}[filename]
        sids[filename] = sid
        sources.append(dict(source_id=sid, title=filename, publisher='Australia Department of Home Affairs',
                            institution='Australia Department of Home Affairs', url=url,
                            local_path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            bytes=path.stat().st_size, retrieved_at=CUT, source_quality='official_primary',
                            capture_method='http_download_original' if filename in ['annual-reports-index.html','home-affairs-annual-report-2025-26.pdf'] else 'reuse_frozen_official_original',
                            archive_status='original_archived'))
    annual = PdfReader(RAW / 'home-affairs-annual-report-2025-26.pdf')
    notes = annual.pages[168].extract_text(extraction_mode='layout')
    income = annual.pages[154].extract_text(extraction_mode='layout')
    cash = annual.pages[157].extract_text(extraction_mode='layout')
    policy = annual.pages[169].extract_text(extraction_mode='layout')
    for n, text in [(155,income),(158,cash),(169,notes),(170,policy)]:
        (OUT / f'annual2026-p{n}.txt').write_text(text)
    def pair(text, label):
        line = next(line for line in text.splitlines() if label.lower() in line.lower())
        vals = re.findall(r'\d[\d,]+', line)
        return [int(v.replace(',','')) * 1000 for v in vals[:2]]
    revenue_2026, revenue_2025 = pair(notes, 'Visa Application Charges')
    cash_2026, cash_2025 = pair(cash, 'Visa Application Charges')
    checks += [dict(check='actual_348page_report_original_obtained', passed=len(annual.pages)==348,
                    pages=len(annual.pages), pdf_title=annual.metadata.title),
               dict(check='vac_note_matches_independent_income_schedule', passed=pair(income,'Visa Application Charges') == [revenue_2026,revenue_2025]),
               dict(check='vac_leaf_excludes_citizenship_and_total_taxation', passed='Immigration fees' in notes and 'Total taxation revenue' in notes and revenue_2026==4659562000),
               dict(check='recognition_policy_matched_to_lodged_application', passed='not\n recognised as revenue until matched with a lodged visa application' in policy or 'recognised as revenue until matched with a lodged visa application' in policy,
                    policy_text='Payments received before overseas lodgement are not recognised until matched with a lodged application.'),
               dict(check='revenue_and_cash_retained_separately', passed=(revenue_2026,cash_2026,revenue_2025,cash_2025)==(4659562000,4653412000,4154314000,4192178000))]
    revenue_sid = sids['home-affairs-annual-report-2025-26.pdf']
    for metric, amounts, locator, pageno in [
        ('visa_application_charge_revenue', {2025:revenue_2025,2026:revenue_2026}, 'Note2.1A Taxation revenue, Visa Application Charges',169),
        ('visa_application_charge_cash_received', {2025:cash_2025,2026:cash_2026}, 'Administered cash flow statement, Operating activities / Cash received / Visa Application Charges',158)]:
        for y, value in amounts.items():
            obs.append(dict(observation_id=f'aur6_au_vac_{"revenue" if "revenue" in metric else "cash"}_fy{y}',
                            destination='AUS', reporting_country='AUS', origin='WORLD', nationality='WORLD',
                            basis='government_accounting', origin_basis='government_accounting',
                            visa_group='unclassified', visa_type='all_visa_and_migration', metric=metric,
                            original_metric='Visa Application Charges', value=value, unit='AUD', currency='AUD',
                            original_value=value//1000, original_unit='AUD thousands',
                            period_start=f'{y-1}-07-01', period_end=f'{y}-06-30', period_type='financial_year',
                            year_type='financial', year=y, period_label=f'{y-1}-{str(y)[-2:]}',
                            source_id=revenue_sid, source_ids=[revenue_sid],
                            source_locator=f'PDF{pageno} / printed{pageno-14}, {locator}, {y}column',
                            calculation_type='official_accounting', aggregation_role='total',
                            observation_domain='visa_fee_revenue' if 'revenue' in metric else 'visa_fee_cash_flow',
                            accounting_basis='recognised_administered_revenue' if 'revenue' in metric else 'administered_cash_received',
                            context_only='cash' in metric, eligible_money_ledger='revenue' in metric,
                            notes='VAC签证与移民申请收费叶科目；不含citizenship Immigration fees、旅客离境费、进口费或全部税收。收入与现金分列，不相加。' + ('本条为前期比较数。' if y==2025 else '')))
    baseline = json.loads((RAW / 'baseline_inputs.json').read_text())
    oldrev = next(r for r in baseline['selected_prior_observations'] if r['metric']=='visa_application_charge_revenue')
    for metric, prior, newer, oldlocator in [
        ('visa_application_charge_revenue',oldrev['value'],revenue_2025,'2024–25report PDF165/printed151, Note2.1A; originalpage visually verified'),
        ('visa_application_charge_cash_received',4192178000,cash_2025,'2024–25report PDF154/printed140, cash received; originalpage visually verified')]:
        revisions.append(dict(metric=metric, year=2025, prior_report_value_AUD=prior,
                              new_report_comparative_AUD=newer, revision_AUD=newer-prior,
                              prior_source_id=sids['annual-2024-25-comparison.pdf'], prior_locator=oldlocator,
                              current_source_id=revenue_sid, status='unchanged' if newer==prior else 'revised'))
    checks.append(dict(check='fy2025_revenue_and_cash_comparatives_not_revised',passed=all(x['revision_AUD']==0 for x in revisions),comparisons=revisions))

    visitor = PdfReader(RAW / 'visitor-june-2026.pdf')
    v_sid = sids['visitor-june-2026.pdf']
    quantities = []
    for n, metric, table in [(12,'applications_lodged','1.02'),(20,'visas_granted','2.02')]:
        txt=visitor.pages[n-1].extract_text(extraction_mode='layout');(OUT/f'visitor2026-p{n}.txt').write_text(txt)
        parsed=[]
        for li, line in enumerate(txt.splitlines(),1):
            m=re.match(r'^\s*([A-Za-z].*?)\s{2,}([\d,]+)\s{2,}([\d,]+)\s+',line)
            if not m or m[1] not in GROUP_TO_SUBCLASS:continue
            label=m[1]
            for y,text in [(2025,m[2]),(2026,m[3])]:
                value=int(text.replace(',',''))
                row=dict(observation_id=f'aur6_visitor_{metric}_{y}_{label.replace(" ","_")}',
                         destination='AUS', reporting_country='AUS', origin='WORLD', nationality='WORLD',
                         basis='nationality', origin_basis='all_citizenships_total', visa_type=GROUP_TO_SUBCLASS[label],
                         visa_group=label, metric=metric, value=value,
                         unit='applications' if metric=='applications_lodged' else 'visa_issuance_events',
                         period_start=f'{y-1}-07-01',period_end=f'{y}-06-30',period_type='financial_year',
                         year_type='financial',year=y,period_label=f'{y-1}-{str(y)[-2:]}',
                         source_id=v_sid,source_ids=[v_sid],source_locator=f'PDF{n}/printed{n-4},Table{table},row{label},FY{y-1}/{str(y)[-2:]}',
                         calculation_type='published_statistical_series',observation_domain='visa_activity',
                         context_only=True,eligible_money_ledger=False,aggregation_role='total' if label=='Total' else 'component',
                         source_status='provisional' if y==2026 else None,
                         notes='Lodged是递交事件，Granted含primary和review grants；二者跨队列，不视为批准概率、收费事件或独立人数。FY2025/26当前年度数据按报告定义保留provisional。')
                quantities.append(row);parsed.append(row)
        for y in [2025,2026]:
            rr=[r for r in parsed if r['year']==y]
            total=next(r['value'] for r in rr if r['aggregation_role']=='total')
            checks.append(dict(check=f'visitor_{metric}_{y}_seven_groups_sum_total',
                               passed=sum(r['value'] for r in rr if r['aggregation_role']=='component')==total,
                               total=total,groups=len(rr)-1))
    obs.extend(quantities)
    throughput={}
    for y in [2025,2026]:
        selected=[r for r in quantities if r['year']==y and r['visa_type']=='600']
        lodged=sum(r['value'] for r in selected if r['metric']=='applications_lodged')
        granted=sum(r['value'] for r in selected if r['metric']=='visas_granted')
        throughput[y]=dict(year=y, applications=lodged,grants=granted,ratio=granted/lodged,
                           source_status='provisional' if y==2026 else None,
                           observation_ids=[r['observation_id'] for r in selected])
    old_lodged=sum(r['value'] for r in baseline['selected_prior_observations'] if r['metric']=='applications_lodged' and r['visa_type']=='600')
    old_granted=sum(r['value'] for r in baseline['selected_prior_observations'] if r['metric']=='visas_granted' and r['visa_type']=='600' and r['year_type']=='financial')
    checks.append(dict(check='visitor_fy2025_comparatives_match_frozen_model_inputs',passed=(old_lodged,old_granted)==(throughput[2025]['applications'],throughput[2025]['grants']),old_lodged=old_lodged,old_granted=old_granted))
    provisional=visitor.pages[4].extract_text(extraction_mode='layout')
    checks.append(dict(check='current_visitor_fy2026_provisional_status_preserved',passed='current financial year should always be considered' in provisional and 'provisional' in provisional))
    # Published monthly totals are independent activity context; not subclass600.
    for n, metric, table in [(11,'applications_lodged','1.01'),(19,'visas_granted','2.01')]:
        txt=visitor.pages[n-1].extract_text(extraction_mode='layout');(OUT/f'visitor2026-p{n}.txt').write_text(txt)
        for li,line in enumerate(txt.splitlines(),1):
            m=re.match(r'^(202\d-\d\d)\s+([\d,].*)$',line)
            if not m:continue
            values=re.findall(r'\d[\d,]*',m[2]);assert len(values)==12
            fy=int(m[1][:4])+1
            for j,v in enumerate(values):
                year=fy-1 if j<6 else fy;month=(j+6)%12+1
                obs.append(dict(observation_id=f'aur6_visitor_{metric}_{year}_{month:02d}_monthly_total',
                    destination='AUS',reporting_country='AUS',origin='WORLD',origin_label='全部国籍',origin_basis='all_citizenships_total',
                    visa_group='unclassified',visa_type='all_visitor',metric=metric,value=int(v.replace(',','')),
                    unit='applications' if metric=='applications_lodged' else 'visa_issuance_events',year=year,
                    period_start=f'{year}-{month:02d}-01',period_end=f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}',
                    period_type='calendar_month',source_id=v_sid,source_ids=[v_sid],
                    source_locator=f'PDF{n}/printed{n-4},Table{table},FY{m[1]},monthcolumn{j+1}',
                    calculation_type='published_statistical_series',observation_domain='visa_activity',context_only=True,
                    eligible_money_ledger=False,aggregation_role='total',flow_direction='inbound',
                    series_id='aus_all_visitor_'+metric+'_monthly',series_label='澳大利亚访客签证 · '+('递交' if metric=='applications_lodged' else '签发')+' · 月度',
                    scope='visitor_subclasses_600_601_651_all_locations',source_status='provisional' if fy==2026 else None,
                    notes='全访客600/601/651的发布月总数，不是600单独数量。多期总量不与财政年或类别分项相加。'))
    # TwoFY arithmetic mean is requested to parallel the existing2024 method.
    ratio=(throughput[2025]['ratio']+throughput[2026]['ratio'])/2
    bridge=(revenue_2025+revenue_2026)/2
    cash_bridge=(cash_2025+cash_2026)/2
    flows=baseline['selected_prior_flows']
    visitor_rows=[r for r in flows if r['visa_group']=='visitor']
    scale=throughput[2025]['ratio']/ratio
    new_visitor=sum(r['amount'] for r in visitor_rows)*scale
    old_china=sum(r['amount'] for r in visitor_rows if r['payer']=='CHN')
    plan=dict(method_id='au_vac_calendar_2025_complete_adjacent_fy',year=2025,
              baseline_total_revenue_AUD=oldrev['value'],
              calendar_revenue_AUD=dict(center=bridge,lower=bridge,upper=bridge),
              calendar_cash_received_AUD=cash_bridge,
              revenue_cash_difference_AUD=cash_bridge-bridge,
              calendar_bridge='0.5*FY2024/25 + 0.5*FY2025/26',
              calendar_period_start='2025-01-01',calendar_period_end='2025-12-31',
              calculation_type='calendar_year_model',accounting_basis='recognised_administered_VAC_revenue',
              income_observation_ids=['aur6_au_vac_revenue_fy2025','aur6_au_vac_revenue_fy2026'],
              cash_observation_ids=['aur6_au_vac_cash_fy2025','aur6_au_vac_cash_fy2026'],
              total_change_AUD=bridge-oldrev['value'],total_change_fraction=bridge/oldrev['value']-1,
              throughput=throughput,calendar_throughput=dict(center=ratio,lower=ratio*.9,upper=min(1,ratio*1.1),
                  formula='arithmetic mean of FY2024/25 and FY2025/26 grants/lodgements ratios',
                  interpretation='throughput proxy, not cohort grant probability',fy2026_status='provisional'),
              allocation_effect=dict(visitor_scale=scale,old_known_visitor_AUD=sum(r['amount'] for r in visitor_rows),
                  new_known_visitor_AUD=new_visitor,new_unknown_other_AUD=bridge-new_visitor,
                  old_china_mainland_visitor_AUD=old_china,new_china_mainland_visitor_AUD=old_china*scale,
                  china_mainland_visitor_change_AUD=old_china*(scale-1)),
              constraints=['Calendar total fixed at50/50 adjacent completeFY recognisedVAC revenue.',
                  'Receipt seasonality withinFYs is an unmeasured bridge assumption; this is not observedCY2025 revenue.',
                  'No20percent missing-nextFY scenario remains.',
                  'Cash received is stored separately and never added to recognisedrevenue.',
                  'Keep600offshore marginal allocation uncertainty negatively correlated withUNKNOWNother remainder.',
                  'No student/work/family/onshore600 nationality allocation is inferred.'],
              unchanged_2024_flows_sha256=baseline['unchanged_baselines']['aus_2024_flows_sha256'])
    checks += [dict(check='cy2025_uses_two_complete_fy_revenue_half_each',passed=bridge==4406938000),
               dict(check='cy2025_total_fixed_not_missing_fy20percent',passed=plan['calendar_revenue_AUD']['lower']==bridge==plan['calendar_revenue_AUD']['upper']),
               dict(check='visitor_new_ratio_and_old_fy_comparison_expected',passed=abs(ratio-0.7815917366440226)<1e-14),
               dict(check='all_observation_ids_unique',passed=len({r['observation_id'] for r in obs})==len(obs)),
               dict(check='income_cash_not_added_together',passed=plan['calendar_revenue_AUD']['center']!=cash_bridge and plan['accounting_basis']=='recognised_administered_VAC_revenue')]
    policies=[dict(policy_id='aur6_vac_revenue_recognition',source_id=revenue_sid,
                   source_locator='PDF170/printed156,VACandImmigrationfeesrecognition',
                   policy='签证与移民申请费受MigrationAct1958及VisaApplicationChargeAct1997约束；一般收取即确认，境外未递交申请的预收款需匹配递交后才确认。citizenship费另列Immigrationfees。',
                   accounting_basis='recognised_administered_revenue',distinct_cash_flow=True)]
    coverage=[dict(code='AUS',year=2026,status='complete_fy_revenue_and_visitor_context',
                   period_start='2025-07-01',period_end='2026-06-30',
                   actual_revenue_known=True,actual_revenue_AUD=revenue_2026,cash_received_AUD=cash_2026,
                   visitor_source_status='provisional',source_ids=[revenue_sid,v_sid],
                   notes='FY不是自然年；2025自然年以相邻完整FY各半桥接。VAC叶科目全国籍未分，不按访客国籍覆盖其余类别。')]
    archives=[dict(local_path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,
                   archive_kind='frozen_local_model_input_snapshot' if p.name=='baseline_inputs.json' else 'official_original')
              for p in sorted(RAW.iterdir()) if p.is_file()]
    report=dict(package='australia_recent_v6',sources=len(sources),observations=len(obs),checks=len(checks),
                checks_passed=all(r['passed'] for r in checks),fiscal_revenue_AUD={2025:revenue_2025,2026:revenue_2026},
                fiscal_cash_AUD={2025:cash_2025,2026:cash_2026},revisions=revisions,
                bridge=plan['calendar_revenue_AUD'],new_known_visitor_AUD=new_visitor,
                new_unknown_other_AUD=bridge-new_visitor,
                china_mainland_visitor_change_AUD=old_china*(scale-1),archived_bytes=sum(r['bytes'] for r in archives))
    for name,value in [('sources.json',sources),('observations.json',obs),('revisions.json',revisions),
                       ('calendar_2025_update_plan.json',plan),('policies.json',policies),('coverage.json',coverage),
                       ('archive_manifest.json',archives),('checks.json',checks),('report.json',report)]:dump(name,value)
    (OUT/'README.md').write_text('''# 澳大利亚2025–26完整财年更新\n\n官方2025–26年报PDF真实原件已归档，348页，创建于2026-10-19、最后修改2026-10-27。关键财务页已渲染并人工核对：PDF169/印155为Note2.1A、PDF155/印141为独立收入表、PDF158/印144为现金流、PDF170/印156为确认政策。\n\n- **VAC收入**FY2024/25=4,154,314,000AUD，FY2025/26=4,659,562,000AUD。前期比较数与上一年报告PDF165/印151一致，无修订。\n- **VAC现金收到**FY2024/25=4,192,178,000AUD，FY2025/26=4,653,412,000AUD。前期比较数与上一年报告PDF154/印140一致，无修订。收入与现金分别保留，不相加。年报将收入按确认政策入账：一般收取确认，但境外申请的预收款需匹配递交才确认。\n- 仅用VAC叶科目，排除citizenship Immigrationfees、旅客离境费、进口费、全部税收与部门总收入。没有人数可供用全部VAC收入推算人均收费。\n- CY2025固定50%FY2024/25+50%FY2025/26收入=**4,406,938,000AUD**，较旧最近FY运行率提高252,624,000AUD（约6.08%）。它是自然年模型，仍依赖半年季节性假设，非官方自然年实收；下一FY已完整，删除原缺FY±20%场景。现金桥接值4,422,795,000AUD单列旁证。\n- VisitorJune2026官方报告Table1.02/2.02可以更新600吞吐：FY25递交2,225,431、签发1,745,780；FY26递交2,296,353、签发1,788,205。对两FY的签发/递交比取算术均值0.7815917366440226，保留FY26provisional。它不是同队列批准率。只用于原有600境外月度国籍分配，其他VAC继续UNK。\n- 已有216个国籍访客分配按新吞吐调整；访客边际范围与UNK剩余范围负相关，目的地联合范围保持固定VAC桥接控制。CY2024flows维持原样。\n\n离线复算：`.research-venv/bin/python scripts/research_australia_recent_v6.py`。`calendar_2025_update_plan.json`记录新值、公式、China大陆归属变化；`revisions.json`记录收入/现金前期对照。`baseline_inputs.json`是已验证旧模型的选定快照，保留上游哈希，不冒充官方原始数据。原件和派生数据均只放在本包目录；全局注册由主任务处理。\n\n''' + JURISDICTION_NOTE+'\n')
    print(json.dumps(report,ensure_ascii=False))
    assert report['checks_passed'],[r for r in checks if not r['passed']]


if __name__=='__main__':main()
