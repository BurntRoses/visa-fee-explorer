#!/usr/bin/env python3
"""Offline UK/Canada visa-government-fee flow scenarios, calendar 2024/2025.

Run with .research-venv/bin/python scripts/model_uk_canada.py.
Only the named estimates JSON is written. No country total or programme account
is added to its constituent flows. Scenario limits are sensitivity cases, never
statistical confidence intervals or claimed empirical fee-duration shares.
"""
from __future__ import annotations
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from build_dataset import entity

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'data/research/uk_canada'
OUTPUT = ROOT / 'data/estimates/uk_canada_flows.json'
YEARS = (2024, 2025)
GROUP_ZH = {'Visitor':'访客', 'Study':'学习', 'Work':'工作', 'Family':'家庭', 'Other':'其他'}


def stable(prefix, *parts):
    payload = json.dumps(parts, ensure_ascii=False, separators=(',', ':'))
    return prefix + '_' + hashlib.sha256(payload.encode()).hexdigest()[:20]


def load(name):
    return json.loads((EVIDENCE / name).read_text())


def payer_code(name):
    # Non-country / unmapped nationality labels remain visible as unknown origins.
    special = {'British overseas citizens':'UNK', 'Cyprus (Northern part of)':'UNK',
               'Other and unknown':'UNK', 'Refugee':'UNK', 'Stateless':'UNK',
               'Other*':'UNK', 'Unknown':'UNK', 'Not stated':'UNK',
               'Commonwealth of the Northern Mariana Islands':'MNP',
               'Federated States of Micronesia':'FSM', 'Republic of Palau':'PLW'}
    code = special.get(name) or entity(name)
    return 'UNK' if not code or code.startswith('RAW_') or code in ('OTHER','WORLD') else code


# A tariff vector is (before 2024-04-10, from that date, from 2025-04-09).
# All amounts are GBP and are outside-UK government application fees.
TARIFF = {
 'zero':(0,0,0), 'visit_short':(115,115,127), 'visit_2y':(400,432,475),
 'visit_5y':(771,771,848), 'visit_10y':(963,963,1059),
 'study':(490,490,524), 'short_study':(200,200,214),
 'sw_short':(719,719,769), 'sw_long':(1420,1420,1519),
 'sw_salary_short':(551,551,590), 'sw_salary_long':(1084,1084,1160),
 'hc_short':(284,284,304), 'hc_long':(551,551,590),
 'temporary':(298,298,319), 'hpi':(822,822,880),
 'talent':(716,716,766), 'innovator':(1191,1191,1274),
 'startup':(435,435,465), 'investor':(1884,1884,2000),
 'family':(1846,1846,1938), 'adult_relative':(3250,3250,3413),
 'refugee_relative':(404,404,424), 'indefinite':(2885,2885,3029),
 'generic':(637,637,682), 'transit_air':(35,35,39), 'transit_land':(64,64,70),
 'bno_short':(180,180,193), 'bno_long':(250,250,268),
 'right_abode':(388,550,589),
}


def mix(**shares):
    assert math.isclose(sum(shares.values()), 1)
    return tuple(sum(TARIFF[k][i] * w for k,w in shares.items()) for i in range(3))


def rule(key, low, center=None, high=None, explanation='', **params):
    def vec(v): return TARIFF[v] if isinstance(v,str) else v
    center = low if center is None else center
    high = center if high is None else high
    return dict(key=key, low=vec(low), center=vec(center), high=vec(high),
                explanation=explanation, parameters=params)


def uk_rule(group, subtype, applicant, payer):
    """Complete deterministic mapping of each mutually exclusive original leaf."""
    s = subtype
    if group == 'Visitor':
        if payer == 'CHN':
            return rule('visitor_china', 'visit_short', 'visit_short',
                        mix(visit_short=.75,visit_10y=.25),
                        '中国中心情景按短期费（中国两年访客方案）；国籍并不能确认居住地或资格。高情景25%按十年价。',
                        long_duration_share_center=0, long_duration_share_range=[0,.25],
                        china_two_year_scheme_applicability='assumed for central case; residence/eligibility unavailable',
                        higher_duration_mix='upper: 25% ten-year; unobserved five/ten-year shares')
        return rule('visitor_duration', 'visit_short',
                    mix(visit_short=.9,visit_2y=1/30,visit_5y=1/30,visit_10y=1/30),
                    mix(visit_short=.75,visit_10y=.25),
                    '访客期限情景：中心90%短期、其余10%在2/5/10年间各占三分之一；低全短期，高25%十年。期限比例是工作情景。',
                    long_duration_share_center=.1, long_duration_share_range=[0,.25],
                    central_long_duration_weights={'2_year':1/3,'5_year':1/3,'10_year':1/3},
                    duration_shares_status='scenario assumptions, not empirical estimates')
    if group == 'Study':
        return rule('short_study' if s.startswith('Short-term') else 'study',
                    'short_study' if s.startswith('Short-term') else 'study',
                    explanation='历史海外申请费；主申请与附属申请各计一份申请费。')
    if group == 'Family':
        if s == 'Refugee Family Reunion':
            return rule('free_refugee_reunion', 'zero', 'zero', 'family',
                        '难民家庭团聚中心按免费政策分类；本地费表没有该路径的零费行，故高情景保留普通家庭价作为分类敏感性。',
                        zero_fee_evidence_status='policy classification assumption; archived tariff lacks an explicit zero-fee line')
        if s.startswith('Family: Other'):
            return rule('family_other', 'family', 'adult_relative', 'adult_relative',
                        '其他家庭申请暂以成年受抚养亲属价为中心；低情景为普通家庭价；实际关系/豁免未知。')
        if 'immediate settlement' in s:
            return rule('family_immediate', 'family', 'family', 'indefinite',
                        '立即定居细项与费表无法一一对应：中心采用1846/1938，定居价为高情景。')
        return rule('family_standard','family', explanation='普通家庭路径历史申请费；未建模费用减免比例。')
    if group == 'Work':
        if s in ('Frontier Worker','ECAA Businessperson','Other permit free employment'):
            return rule('work_free_policy','zero','zero','generic',
                        '中心按免费/免许可路径分类；原始费表未列零费行，高情景用Other visa价标示未证实的分类敏感性。',
                        zero_fee_evidence_status='policy/source-label classification assumption, not explicit in archived fee table')
        if s == 'Health and Care Worker':
            return rule('health_duration','hc_short',mix(hc_short=.75,hc_long=.25),'hc_long',
                        '中心75%不超过三年、25%超过三年；期限比例是工作情景。',
                        long_duration_share_center=.25, long_duration_share_range=[0,1])
        if s in ('Skilled Worker','Tier 2 - General','Tier 2 - Dependant'):
            return rule('skilled_duration_salary','sw_salary_short',
                        mix(sw_short=.6,sw_long=.25,sw_salary_short=.1,sw_salary_long=.05),'sw_long',
                        '中心普通短期60%、普通长期25%、工资清单短期10%、清单长期5%；这些是工作情景。',
                        central_fee_mix={'ordinary_le3y':.6,'ordinary_gt3y':.25,'salary_list_le3y':.1,'salary_list_gt3y':.05},
                        fee_mix_status='scenario assumption, not observed')
        if s in ('Senior or Specialist Worker (Global Business Mobility)','Dependant - Global Business Mobility'):
            return rule('gbm_duration','temporary' if s.startswith('Dependant') else 'sw_short',
                        mix(sw_short=.75,sw_long=.25),'sw_long',
                        '中心按高级/专才75%不超过三年、25%超过三年；GBM附属申请的低情景允许临时调派费。',
                        long_duration_share_center=.25,long_duration_share_range=[0,1])
        if s == 'International Sportsperson':
            return rule('sport_duration','temporary',mix(temporary=.5,sw_short=.5),'sw_short',
                        '中心一年内/一年以上各半；工作情景，非已观测期限结构。')
        if s.startswith('Minister of Religion'):
            return rule('minister','sw_short')
        if 'Global Talent' in s or 'Exceptional Talent' in s:
            return rule('global_talent','talent', explanation='政府审批信和签证费合计716/766；不重复增加审批费，不含私人背书服务。')
        if s == 'Innovator Founder' or s == 'Tier 1 - Entrepreneur':
            return rule('innovator','innovator', explanation='政府申请费；私人背书费和会面费排除。')
        if s == 'Start-up': return rule('startup','startup')
        if s.startswith('Investor'): return rule('investor','investor')
        if s in ('High Potential Individual','Scale-up Worker'): return rule('hpi_scaleup','hpi')
        if s in ('UK Ancestry','Overseas Domestic Worker'):
            return rule('work_other_visa','generic', explanation='海外表Other visa条款作为祖籍/海外家政申请的代表价；细分收费行未单列。')
        if any(x in s for x in ('Seasonal','Youth Mobility','Creative','Government Authorised','Charity','Religious','International Agreement','Graduate Trainee','UK Expansion','Service Supplier','Secondment','Dependant - Temporary')):
            return rule('temporary_work','temporary')
        # Historic closed routes remain present as small original leaf counts.
        return rule('legacy_work','generic','sw_short','investor',
                    '遗留Tier1/Work Permit细项不能从当前表准确识别：中心普通工作价，范围Other visa至投资者价。',
                    mapping_status='representative tariff scenario for legacy category')
    if group == 'Other':
        if any(x in s for x in ('EU Settlement Scheme','EEA Family Permit','Ukraine')):
            return rule('free_other_policy','zero','zero','generic',
                        '中心按EUSS/EEA家庭许可/乌克兰免费政策分类；归档费表未列零费行，高情景保留分类敏感性。',
                        zero_fee_evidence_status='policy classification assumption; archived fee table lacks explicit zero-fee line')
        if s == 'BN(O) route':
            return rule('bno_duration','bno_short',mix(bno_short=.5,bno_long=.5),'bno_long',
                        '中心30个月/5年各半，期限比例为工作情景。')
        if s == 'Transit':
            return rule('transit_type','transit_air',mix(transit_air=.5,transit_land=.5),'transit_land',
                        '未区分空侧/陆侧过境：中心各半，低空侧，高陆侧。')
        if s == 'Certificate of entitlement to right of abode': return rule('right_abode','right_abode')
        if s == 'Other settlement (indefinite leave)':
            return rule('other_settlement','generic','family','indefinite',
                        '其他定居的收费条款未知：中心普通定居申请价，范围Other visa至无限期入境价。')
        if s.startswith('Joining or accompanying'):
            return rule('joining_dependant','generic','family','adult_relative',
                        '未识别附属申请所依附的主路径：中心家庭价，范围Other visa至成年亲属价。')
        if s == 'Other temporary visas':
            return rule('other_temporary','zero','generic','family',
                        '混合的其他临时签证：中心Other visa，范围零至家庭路径价；不把该中心称为实收。')
    raise ValueError(('Unmapped UK leaf',group,subtype,applicant))


def quarter_price(vector, year, quarter, scenario):
    if year == 2024:
        if quarter == 1: return vector[0]
        if quarter == 2:
            return min(vector[:2]) if scenario=='low' else max(vector[:2]) if scenario=='high' else (9*vector[0]+82*vector[1])/91
        return vector[1]
    if quarter == 1: return vector[1]
    if quarter == 2:
        return min(vector[1:]) if scenario=='low' else max(vector[1:]) if scenario=='high' else (8*vector[1]+83*vector[2])/91
    return vector[2]


def uk_model():
    with (EVIDENCE/'uk_quarterly_observations.csv').open(encoding='utf-8-sig') as f:
        rows = [r for r in csv.DictReader(f) if r['metric']=='Applications' and int(r['year']) in YEARS]
    assert len({r['observation_id'] for r in rows}) == len(rows)
    buckets = defaultdict(list)
    for r in rows:
        assert r['origin_name'] != 'WORLD'
        buckets[payer_code(r['origin_name']),int(r['year']),r['visa_type_group'],r['visa_type_subgroup'],r['applicant_type']].append(r)
    models = [{
      'method_id':'uk_quarterly_application_tariff_v1',
      'receiver':'GBR','currency':'GBP','period_basis':'calendar_year',
      'description':'互斥国籍×季度×签证细项申请量乘海外政府费率的情景模型；不是财政实收，也不以宽口径账目倒推。',
      'quantity_scope':'All application leaf rows in Data_Vis_D01, calendar 2024 and 2025; no decision rows or annual totals.',
      'application_count_timing':'biometric enrolment; payment may precede it',
      'quarter_timing':{'2024Q2':'9 days before 2024-04-10, 82 after; uniform submission working case',
                        '2025Q2':'8 days before 2025-04-09, 83 after; uniform submission working case',
                        'sensitivity':'all quarter applications at the lower/higher applicable rate'},
      'exclusions':['IHS','priority/super-priority services','private application centre/endorsement services','employer sponsorship/skills charges','ETA'],
      'unmodelled':['fee waivers','individual refunds/cancellations','payment versus biometric date','residence eligibility for China two-year scheme'],
      'range_meaning':'sensitivity across stated duration, fee-category and quarter-date scenarios; not confidence limits or a guaranteed bound on receipts',
      'source_ids':['uk_entry_clearance_jun2026','uk_fees_apr2024','uk_fees_apr2025'],
      'input_leaf_count':len(rows),'input_applications':sum(int(r['value']) for r in rows),
      'scenario_shares_status':'All mixture shares are openly selected working scenarios, not empirically estimated proportions.'
    }]
    rules = {}
    flows = []
    for (payer,year,group,subtype,applicant),rr in sorted(buckets.items()):
        r = uk_rule(group,subtype,applicant,payer)
        key = r['key']
        method_id = 'uk_fee_' + key + '_v1'
        if key not in rules:
            rules[key] = {'method_id':method_id, 'parent_method_id':'uk_quarterly_application_tariff_v1',
                          'receiver':'GBR','currency':'GBP','description':r['explanation'],
                          'tariff_dates':['before 2024-04-10','2024-04-10 to 2025-04-08','from 2025-04-09'],
                          'low_tariffs':r['low'],'central_tariffs':r['center'],'high_tariffs':r['high'],
                          'parameters':r['parameters'], 'source_ids':['uk_fees_apr2024','uk_fees_apr2025'],
                          'range_meaning':'scenario sensitivity, not an empirical confidence interval'}
        sums = {k:sum(int(x['value'])*quarter_price(r[v],year,int(x['quarter']),k) for x in rr)
                for k,v in [('low','low'),('center','center'),('high','high')]}
        flows.append({'id':stable('uk_fee',payer,year,group,subtype,applicant),
          'payer':payer,'receiver':'GBR','year':year,'visa_group':group,
          'visa_type':subtype+' | '+applicant,
          'label':GROUP_ZH[group]+' · '+subtype+' · '+applicant,
          'amount':round(sums['center'],6),'currency':'GBP','quantity':sum(int(x['value']) for x in rr),
          'quantity_basis':'applications_by_biometric_enrolment_date',
          'source_ids':['uk_entry_clearance_jun2026','uk_fees_apr2024','uk_fees_apr2025'],
          'observation_ids':[x['observation_id'] for x in rr], 'method_id':method_id,
          'notes':'按国籍；海外申请政府费情景，非实收。'+r['explanation'],
          'parameters':{'parent_method_id':'uk_quarterly_application_tariff_v1',
                        'origin_basis':'nationality','original_names':sorted({x['origin_name'] for x in rr}),
                        'applicant_type':applicant,
                        'quarter_applications':dict(sorted((x['quarter'],sum(int(y['value']) for y in rr if y['quarter']==x['quarter'])) for x in rr)),
                        'scenario_status':'working scenario, not observed revenue'},
          'lower':round(sums['low'],6),'upper':round(sums['high'],6)})
    models.extend(rules.values())
    assert sum(f['quantity'] for f in flows) == sum(int(r['value']) for r in rows)
    assert sum(len(f['observation_ids']) for f in flows) == len(rows)
    return flows, models


# Canada: mutually exclusive published revenue accounts from three fiscal years.
# The Public Accounts use the ledger label "Multiple entry" for the main TRV
# account. Do not invent a separate single-entry residual or add programme totals.
CA_COMPONENTS = {
 'trv_multiple':(100,'Visitor','TRV multiple-entry revenue account','访客签证 Multiple entry 收入科目'),
 'trv_family':(500,'Visitor','TRV family maximum fee','家庭访客签证封顶费'),
 'study':(150,'Study','Study permit including extensions','学习许可（含续签）'),
 'work':(155,'Work','Work permit including extensions','工作许可（含续签）'),
 'work_artists':(465,'Work','Performing artists group maximum fee','表演团体工作许可封顶费'),
 'open_work':(100,'Work','Open work permit holder additional fee','开放工作许可附加费'),
}
CA_REFINED_EVIDENCE = ROOT / 'data/research/evidence_refinement/uk_canada'


def country_weights(rows, year, visa_type):
    """Normalize source-country cells, retaining suppression and rounding limits."""
    cells = [r for r in rows if r['year']==year and r['visa_type']==visa_type and r['origin_name']!='WORLD']
    b = defaultdict(lambda:dict(q=0.,low=0.,high=0.,ids=[],names=[]))
    for r in cells:
        if r['value'] is None:
            assert r.get('lower') is not None and r.get('upper') is not None, r
            lo,hi=float(r['lower']),float(r['upper']); q=(lo+hi)/2
        else:
            q=float(r['value']);lo=max(0,q-2.5) if q else 0.;hi=q+2.5 if q else 0.
        d=b[payer_code(r['origin_name'])]
        d['q']+=q;d['low']+=lo;d['high']+=hi;d['ids'].append(r['observation_id']);d['names'].append(r['origin_name'])
    tq=sum(x['q'] for x in b.values());tl=sum(x['low'] for x in b.values());th=sum(x['high'] for x in b.values())
    assert tq > 0
    for d in b.values():
        d['weight']=d['q']/tq
        d['weight_low']=d['low']/(d['low']+th-d['high']) if d['low'] else 0
        d['weight_high']=d['high']/(d['high']+tl-d['low']) if d['high'] else 0
    return b, tq


def canada_model():
    """Three fiscal anchors; coherent calendar weights and source-country proxies.

    Each flow retains a marginal payer-share sensitivity envelope. Destination
    ranges instead evaluate the same time weight across all fee components;
    changing country shares cannot change total Canadian government revenue.
    """
    actual_rows=json.loads((CA_REFINED_EVIDENCE/'observations.json').read_text())
    actual={(int(r['period_start'][:4]),r['component']):r for r in actual_rows
            if r['scope_in_model']=='selected_core_fee'}
    assert set(actual)=={(y,k) for y in (2023,2024,2025) for k in CA_COMPONENTS}
    annual=load('canada_annual_summary.json')
    weights_grid=(.15,.25,.35)
    source_ids=sorted({sid for r in actual.values() for sid in r['source_ids']})
    models=[{
      'method_id':'ca_pa_fiscal_calendar_bridge_v2','receiver':'CAN','currency':'CAD',
      'description':'三财年Public Accounts互斥细项实际收入按季度权重桥接自然年；日历金额与国别分配均为模型，财年科目金额为观测。',
      'fiscal_periods':[['2023-04-01','2024-03-31'],['2024-04-01','2025-03-31'],['2025-04-01','2026-03-31']],
      'formula':'calendar_revenue_y = w * actual_FY_ending_March_y + (1-w) * actual_FY_ending_March_(y+1)',
      'central_weight':.25,'sensitivity_weights':list(weights_grid),
      'central_assumptions':'各财年内收入均匀确认；自然年Jan-Mar取前一财年25%，Apr-Dec取后一财年75%。没有声称观察到季度实际收款。',
      'sensitivity':'所有费用科目共用w=0.15/0.25/0.35与互补1-w；取完整情景端点包络，不是统计置信区间。',
      'scope':'Six disjoint fiscal revenue accounts. Study/work include inland applications and extensions. Payers are applicants, not country governments.',
      'accounting_basis':'Reported fiscal revenue, not independently measured cash receipts in each calendar year.',
      'excluded_fee_lines':['eTA','temporary resident permit','restoration of status','employer compliance','International Experience Canada participation fees','biometrics','permanent residence','citizenship','passport'],
      'not_added':['Temporary Residence programme total','deferred revenue accounts','remissions','old tariff-times-applications TRV scenario'],
      'trv_scope':'Use the exact published Multiple entry account plus separate family maximum account. Single-entry revenue is not separately labelled; do not infer a missing residual or assume a separate zero.',
      'reconciliation':'Published Public Accounts Temporary Residence leaf accounts, including excluded eTA/IEC/etc, sum exactly to Fees Report programme revenue in FY2024-25 and FY2025-26. The programme is a check, not an extra flow.',
      'source_ids':source_ids,
    },{
      'method_id':'ca_source_country_allocation_v1','receiver':'CAN','currency':'CAD',
      'description':'按V-1获批或新学签结案的来源国份额分配实际科目桥接金额；这不是付费申请人的实测国籍分布。',
      'visitor_proxy':'Calendar-year Visitor V-1 approved persons, including family-cap allocation; refusals are not estimated by country.',
      'study_proxy':'Calendar-year New study permit processed persons, applied to revenue including extensions; extension distribution may differ.',
      'suppression':'Published -- means 1–4; central 2.5, sensitivity 1–4. Published multiples of 5 vary ±2.5 in share sensitivity.',
      'rounding':'Normalize sum of country cells instead of forcing rounded published WORLD to equal the country sum.',
      'unknown_origin':'Work permit, group and open-work accounts remain entirely UNK because a matching payer-country distribution is absent.',
      'range_scope':'Individual country envelopes are marginal, not jointly additive. Country-share uncertainty redistributes a fixed destination amount.',
      'source_ids':['ca_visitor_v1','ca_study-processed'],
    }]
    revenues={}
    for key,(fee,group,subtype,label) in CA_COMPONENTS.items():
        revenues[key]={}
        for year in YEARS:
            prev,current=actual[year-1,key],actual[year,key]
            scenario={str(w):w*prev['value']+(1-w)*current['value'] for w in weights_grid}
            revenues[key][year]={'center':scenario['0.25'],'low':min(scenario.values()),'high':max(scenario.values()),'scenario_amounts':scenario}
        models.append({
          'method_id':'ca_pa_'+key+'_calendar_bridge_v2','parent_method_id':'ca_pa_fiscal_calendar_bridge_v2',
          'receiver':'CAN','currency':'CAD','fee_component':subtype,
          'actual_fiscal_revenues':[{'period_start':r['period_start'],'period_end':r['period_end'],
                                    'amount':r['value'],'observation_id':r['observation_id'],
                                    'source_ids':r['source_ids'],'locator':r['locator']}
                                   for r in [actual[y,key] for y in (2023,2024,2025)]],
          'calendar_scenarios':revenues[key],
          'source_ids':source_ids,
          'notes':'费用细项为互斥收入科目。开放工作许可附加费与工作许可处理费是两笔不同付款，可由同一人支付，不把付款笔数当人数。'})
    flows=[]
    allocated=defaultdict(float)
    for year in YEARS:
        for key,(fee,group,subtype,label) in CA_COMPONENTS.items():
            amt=revenues[key][year]
            anchors=[actual[year-1,key],actual[year,key]]
            proxy=key in ('trv_multiple','trv_family','study')
            if proxy:
                typ='New study permit' if key=='study' else 'Visitor V-1'
                weights,denominator=country_weights(annual,year,typ)
            else:
                weights={'UNK':dict(q=amt['center']/fee,weight=1,weight_low=1,weight_high=1,ids=[],names=['No matching payer-country distribution for retained work-fee account'])}
                denominator=None
            sources=sorted({sid for r in anchors for sid in r['source_ids']})
            if proxy:sources.append('ca_study-processed' if key=='study' else 'ca_visitor_v1')
            for payer,w in sorted(weights.items()):
                amount=amt['center']*w['weight']
                flows.append({
                  'id':stable('ca_pa_fee',payer,year,key),'payer':payer,'receiver':'CAN','year':year,
                  'visa_group':group,'visa_type':subtype,'label':label,'amount':round(amount,6),'currency':'CAD',
                  'quantity':w['q'],'quantity_basis':'source_country_distribution_proxy' if proxy else 'modelled_fee_equivalent_events',
                  'source_ids':sources,'observation_ids':[r['observation_id'] for r in anchors]+w['ids'],
                  'method_id':'ca_pa_'+key+'_calendar_bridge_v2',
                  'model_status':'modeled_estimate','origin_basis':'source_country_proxy' if proxy else 'unknown',
                  'notes':'自然年财年插值模型；原始实际收入逐项保留。'+('国别按V-1获批或新学签结案份额代理；家庭结构/续签结构未知。' if proxy else '缺少工作许可付款人来源国分布，全部保留UNK。')+('原账目名为Multiple entry；未另行识别single-entry科目。' if key=='trv_multiple' else ''),
                  'parameters':{'allocation_method_id':'ca_source_country_allocation_v1' if proxy else 'unknown_origin',
                                'origin_basis':'source_country_proxy' if proxy else 'unknown',
                                'original_names':sorted(set(w['names'])),'allocation_weight':w['weight'],
                                'allocation_denominator':denominator,'calendar_bridge_weight':.25,
                                'anchor_fiscal_revenues':[{'value':r['value'],'period_start':r['period_start'],'period_end':r['period_end'],'observation_id':r['observation_id']} for r in anchors],
                                'unit_fee_for_equivalent_events':None if proxy else fee,
                                'scenario_status':'modelled calendar allocation from observed fiscal accounts'},
                  'lower':round(amt['low']*w['weight_low'],6),'upper':round(amt['high']*w['weight_high'],6)})
                allocated[key,year]+=amount
            assert math.isclose(allocated[key,year],amt['center'],abs_tol=.01)
    destination_ranges=[]
    for year in YEARS:
        totals={str(w):sum(revenues[k][year]['scenario_amounts'][str(w)] for k in CA_COMPONENTS) for w in weights_grid}
        destination_ranges.append({
          'receiver':'CAN','year':year,'currency':'CAD','amount':totals['0.25'],
          'lower':min(totals.values()),'upper':max(totals.values()),
          'range_method':'六项实际财年收入共同使用前财年权重w=0.15/0.25/0.35与互补1-w的完整情景端点；来源国代理份额仅重新分配，不改变加拿大政府总额，不累加各国边际范围。',
          'calendar_weight_scenario_totals':totals,
          'source_ids':source_ids,'method_id':'ca_pa_fiscal_calendar_bridge_v2'})
        assert math.isclose(sum(f['amount'] for f in flows if f['year']==year),totals['0.25'],abs_tol=.01)
    return flows,models,destination_ranges


def main():
    uk,um=uk_model();ca,cm,destination_ranges=canada_model();flows=uk+ca
    assert len({f['id'] for f in flows}) == len(flows)
    for f in flows:
        assert f['receiver'] in ('GBR','CAN') and f['year'] in YEARS
        assert len(f['payer']) == 3 and not f['payer'].startswith('RAW')
        assert 0 <= f['lower'] <= f['amount'] <= f['upper'], f
        assert all(math.isfinite(f[k]) for k in ('lower','amount','upper','quantity'))
        assert f['source_ids'] and f['observation_ids']
    model_ids={m['method_id'] for m in um+cm}
    assert all(f['method_id'] in model_ids for f in flows)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps({'flows':flows,'models':um+cm,'destination_ranges':destination_ranges},ensure_ascii=False,separators=(',',':'))+'\n')
    totals=defaultdict(lambda:defaultdict(float))
    for f in flows:
        totals[(f['receiver'],f['year'],f['currency'])][f['visa_group']]+=f['amount']
    print(json.dumps({'output':str(OUTPUT),'flows':len(flows),'models':len(um+cm),'destination_ranges':destination_ranges,
                      'subtotals':[{'receiver':k[0],'year':k[1],'currency':k[2],**dict(v),'total':sum(v.values())} for k,v in sorted(totals.items())]},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
