#!/usr/bin/env python3
"""Allocate MRV account receipts across all FY2024 nationality/visa classes.

Offline model. Run with .research-venv/bin/python scripts/model_us.py.
Only data/estimates/us_flows.json is written. Raw observations are unchanged.
"""
from __future__ import annotations
from collections import defaultdict
from itertools import product
from pathlib import Path
import hashlib
import json
import math
import re
import unicodedata

# Import the shared entity resolver without running its assembly entry point.
from build_dataset import entity

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/research/us'
OUT=ROOT/'data/estimates/us_flows.json'
METHOD='us_mrv_all_class_account_calibrated_allocation_v1'
FREE_PREFIXES=('A','G','NATO')
B_CLASSES={'B1','B1/B2','B2'}
BCC_CLASSES={'BBBCC','BBBCV'}
UNKNOWN_PAYER='UNK_USA'

def load(name):
    return json.loads((RAW/name).read_text())

def slug(s):
    return re.sub(r'[^a-z0-9]+','_',unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()).strip('_')

def payer(s):
    """Preserve raw/no-nationality jurisdictions via the owning resolver."""
    return entity(s)

def rate_key(s):
    # Stable nationality correspondence without treating the non-nationality
    # refusal aggregate as if it were a country-specific observation.
    normalized=re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower())
    if normalized in {'chinamainland','china'}:return 'CHN'
    if normalized=='palestinianauthoritytraveldocument':return 'PAL_TRAVEL_DOC'
    if normalized=='kosovo':return 'XKX'
    code=entity(s)
    if code.startswith('RAW_'):
        code=entity(s.title())
    return normalized if code.startswith('RAW_') else code

def is_free(typ):
    return typ.startswith(FREE_PREFIXES) or typ in {'C2','C3'}

def tariff(typ,bcc_child_share=.1,j_exempt_share=.1):
    if is_free(typ):return 0.0
    if typ in BCC_CLASSES:return (1-bcc_child_share)*185+bcc_child_share*15
    if typ.startswith('J'):return 185*(1-j_exempt_share)
    if typ.startswith(('H','L','O','P','Q','R')):return 205.0
    if typ.startswith('E'):return 315.0
    if typ.startswith('K'):return 265.0
    return 185.0

def visa_group(typ):
    if typ in B_CLASSES|BCC_CLASSES:return 'visitor'
    if typ.startswith(('F','M')):return 'student'
    if typ.startswith('K'):return 'family'
    if typ.startswith(('H','L','O','P','Q','R','E','CW')) or typ in {'TN','TD'}:return 'work'
    return 'other'


def main():
    detail=load('nationality_class_2024.json')
    workload={r['visa_type']:r for r in load('workload2024.json') if r['visa_type']!='Grand Total'}
    refusal={rate_key(r['nationality']):r for r in load('adjusted_refusal_rates.json') if r['year']==2024 and not r['nationality'].startswith('*')}
    receipts={r['period_label']:r for r in load('actual_receipts.json')}
    fy2024=receipts['FY2024']['value']*1e6
    fy2025=receipts['FY2025']['value']*1e6
    controls={2024:.75*fy2024+.25*fy2025,2025:fy2025}
    class_detail=defaultdict(list)
    for r in detail:
        if r['nationality']=='Grand Total' or r['nationality'].startswith('Totals for ') or r['visa_type']=='ALL_NIV':continue
        class_detail[r['visa_type']].append(r)
    assert all(sum(r['value'] for r in rr)==workload[typ]['issued'] for typ,rr in class_detail.items())
    assert sum(w['applications'] for w in workload.values())==14245969
    assert sum(w['issued'] for w in workload.values())==10969936

    allocation_rows=[]
    class_checks=[]
    fallback_b=[]
    unmapped_labels={}
    for typ,w in sorted(workload.items()):
        detail_rows=class_detail.get(typ,[])
        candidates=[]
        for r in detail_rows:
            if r['value']<=0:continue
            code=payer(r['nationality'])
            if code.startswith('RAW_'):unmapped_labels[code]=r['nationality']
            base=r['value']*w['applications']/w['issued'] if w['issued'] else 0
            rate=refusal.get(rate_key(r['nationality']))
            valid_rate=rate is not None and 0<=rate['adjusted_refusal_rate_percent']<100
            bridge=r['value']/(1-rate['adjusted_refusal_rate_percent']/100) if typ in B_CLASSES and valid_rate else base
            if typ in B_CLASSES and not valid_rate:fallback_b.append({'nationality':r['nationality'],'visa_type':typ,'reason':'no matching rate or 100% adjusted rate; use global class applications/issued ratio'})
            candidates.append(dict(payer=code,nationality=r['nationality'],visa_type=typ,issued=r['value'],q_base=base,q_bridge_raw=bridge,refusal=rate if typ in B_CLASSES and valid_rate else None,detail=r))
        if w['issued']==0 and w['applications']>0:
            # These classes have applications but no nationality issuance support.
            candidates.append(dict(payer=UNKNOWN_PAYER,nationality='Unknown nationality: zero global issuance',visa_type=typ,issued=0,q_base=float(w['applications']),q_bridge_raw=float(w['applications']),refusal=None,detail=None))
        raw_sum=sum(r['q_bridge_raw'] for r in candidates)
        for r in candidates:
            r['q']=r['q_bridge_raw']*w['applications']/raw_sum if raw_sum else 0
            allocation_rows.append(r)
        modeled=sum(r['q'] for r in candidates)
        assert math.isclose(modeled,w['applications'],abs_tol=1e-6),(typ,modeled,w)
        class_checks.append({'visa_type':typ,'global_issued':w['issued'],'global_applications':w['applications'],'allocated_applications':modeled,'residual':modeled-w['applications'],'free_category':is_free(typ),'nationality_cells':len(candidates),'allocation':'adjusted_B_refusal_bridge_then_class_normalized' if typ in B_CLASSES else 'issuance_share_times_global_class_applications' if w['issued'] else 'unknown_nationality_zero_issuance'})

    def weights(child_share,j_share,b_mode='bridge'):
        return [(r['q'] if b_mode=='bridge' else r['q_base'])*tariff(r['visa_type'],child_share,j_share) for r in allocation_rows]

    center_weights=weights(.1,.1)
    center_den=math.fsum(center_weights)
    center_shares=[v/center_den for v in center_weights]
    assert center_den>0 and math.isclose(math.fsum(center_shares),1,abs_tol=1e-12)
    # Each fee/bridge scenario is normalized separately to the same account.
    # Cellwise envelopes are alternatives, so their endpoints cannot be summed
    # to form a global confidence interval.
    scenarios=[]
    share_scenarios=[]
    for child,j,b_mode in product([0,.1,.2],[0,.1,.2],['bridge','global_class_ratio']):
        ww=weights(child,j,b_mode);den=math.fsum(ww);shares=[v/den for v in ww]
        share_scenarios.append(shares)
        scenarios.append({'bcc_child_share':child,'j_exempt_share':j,'b_allocation':b_mode,'nominal_weight_usd':den,'normalized_fy2024_usd':math.fsum(s*fy2024 for s in shares),'fy2024_residual_usd':math.fsum(s*fy2024 for s in shares)-fy2024})
    payer_shares=[]
    for shares in share_scenarios:
        pp=defaultdict(float)
        for r,s in zip(allocation_rows,shares):pp[r['payer']]+=s
        payer_shares.append(pp)

    flows=[]
    common_notes='国籍×类别分配是MRV会计总账校准模型，不是逐国实际收费事件；一般类别按签发份额分配全球同类申请，B1/B2/B1-B2用调整后拒签率桥接后再匹配全球同类申请。MRV实收含BCC，不含SEVIS、USCIS申请、护照及未单列互惠签发费。'
    for year in [2024,2025]:
        target=controls[year]
        timing_low,timing_high=(1.,1.) if year==2024 else (.85,1.15)
        for i,r in enumerate(allocation_rows):
            typ=r['visa_type'];w=workload[typ]
            center=center_shares[i]*target
            alternatives=[ss[i] for ss in share_scenarios]
            if year==2025:
                # One nationality's weight is tilted by +/-25%, and all shares
                # are renormalized to the same total. This is a redistribution,
                # rather than an extra +/-25% global revenue shock.
                alternatives=[ss[i]*factor/(1+(factor-1)*pp[r['payer']]) for ss,pp in zip(share_scenarios,payer_shares) for factor in [.75,1.,1.25]]
            lower=min(alternatives)*target*timing_low
            upper=max(alternatives)*target*timing_high
            assert lower-1e-6<=center<=upper+1e-6,(year,r,lower,center,upper)
            obs=[f'us_2024_world_{slug(typ)}_total_applications_published',receipts['FY2024']['observation_id'],receipts['FY2025']['observation_id']]
            source_ids=['us_workload2024','us_fees2024_cfr','us_fee_schedule','us_omb2026','us_omb2027']
            if r['detail'] is not None:
                obs.insert(0,f'us_2024_{slug(r["nationality"])}_{slug(typ)}_visas_issued');source_ids.insert(0,'us_detail2024')
            if r['refusal']:
                obs.append(f'us_2024_{slug(r["refusal"]["nationality"])}_b_all_adjusted_refusal_rate');source_ids+=['us_refusal2024','us_refusal_method']
            year_note='2024自然年总额＝FY2024实收×9/12＋FY2025实收×3/12，假定财年内均匀收款；两部分沿用FY2024国籍类别份额。' if year==2024 else '2025没有FY2026实际收款，故将FY2025实收平移作全年情景；期间敏感±15%，沿用FY2024分配份额并对单一国籍权重作±25%冲击后重归一化。'
            extra='官方免费类别按0纳入。' if is_free(typ) else 'BCC合资格儿童份额中心10%（0–20%），儿童USD15、其他USD185。' if typ in BCC_CLASSES else 'J类免收份额中心10%（0–20%）。' if typ.startswith('J') else ''
            if r['payer']==UNKNOWN_PAYER:extra+='全球申请大于0、签发为0，未强行指定国籍；保留未分配来源。'
            flows.append({'id':f'us_account_{year}_{slug(r["payer"])}_{slug(typ)}','payer':r['payer'],'receiver':'USA','year':year,'visa_group':visa_group(typ),'visa_type':typ,'visa_label':f'{typ} MRV'+('（官方免收）' if is_free(typ) else ''),'amount':center,'currency':'USD','lower':lower,'upper':upper,'quantity':r['q'],'quantity_basis':'FY2024 modeled application allocation; not observed paid events or calendar-year applications','period_start':f'{year}-01-01','period_end':f'{year}-12-31','period_label':f'{year}自然年费用分配情景','period_type':'calendar_year_modeled_bridge','origin_basis':'nationality_modelled_allocation','source_ids':list(dict.fromkeys(source_ids)),'observation_ids':obs,'method_id':METHOD,'model_status':'account_calibrated_allocation' if year==2024 else 'FY2025_flat_time_proxy_2024_shares','coverage_status':'all MRV classes including BCC; zero-issuance applications unallocated','notes':common_notes+year_note+extra,'parameters':{'nationality_original':r['nationality'],'fy2024_issued':r['issued'],'global_class_applications_fy2024':w['applications'],'global_class_issued_fy2024':w['issued'],'q_issuance_global_ratio':r['q_base'],'q_adjusted_bridge_before_class_normalization':r['q_bridge_raw'],'class_normalized_model_applications':r['q'],'adjusted_B_refusal_rate':r['refusal']['adjusted_refusal_rate_percent']/100 if r['refusal'] else None,'standard_tariff_usd':tariff(typ,0,0),'central_effective_tariff_usd':tariff(typ,.1,.1),'bcc_child_share':.1 if typ in BCC_CLASSES else None,'j_exempt_share':.1 if typ.startswith('J') else None,'normalized_account_share':center_shares[i],'calibrated_FY2024_amount_usd':center_shares[i]*fy2024,'calendar_control_usd':target,'fee_sensitivity_grid':'BCC child0/10/20%, J exempt0/10/20%, B bridge/global-class-ratio; every scenario account-normalized','timing_multiplier_range':[timing_low,timing_high],'allocation_tilt_2025':[.75,1.25] if year==2025 else None,'interval_kind':'pointwise_sensitivity_envelope_not_joint_or_statistical_confidence'}})

    assert len({r['id'] for r in flows})==len(flows),'Entity aliases unexpectedly collide in the nationality table'
    obs_ids={r['observation_id'] for r in load('observations.json')}
    unresolved=sorted({x for r in flows for x in r['observation_ids'] if x not in obs_ids})
    assert not unresolved,unresolved
    source_set={r['source_id'] for r in load('sources.json')}
    assert not {x for r in flows for x in r['source_ids'] if x not in source_set}
    annual_checks=[]
    for year,target in controls.items():
        rr=[r for r in flows if r['year']==year]
        total=math.fsum(r['amount'] for r in rr)
        assert math.isclose(total,target,abs_tol=1e-5),(year,total,target)
        annual_checks.append({'year':year,'amount_usd':total,'control_usd':target,'residual_usd':total-target,'paid_class_count':len({r['visa_type'] for r in rr if r['amount']>0}),'zero_fee_class_count':len({r['visa_type'] for r in rr if is_free(r['visa_type'])}),'payer_count':len({r['payer'] for r in rr}),'flow_count':len(rr),'unallocated_zero_issuance_amount_usd':math.fsum(r['amount'] for r in rr if r['payer']==UNKNOWN_PAYER),'china_usd':math.fsum(r['amount'] for r in rr if r['payer']=='CHN'),'mexico_usd':math.fsum(r['amount'] for r in rr if r['payer']=='MEX')})
    models=[{'model_id':METHOD,'title':'美国全部MRV类别国籍分配与实际账目校准','created_at':'2026-11-15','currency':'USD','scope':'MRV including BCC; 80 global workload classes; no regional/ALL_NIV double counting','control_accounts':[{'period':'FY2024','amount':fy2024,'source_id':'us_omb2026','observation_id':receipts['FY2024']['observation_id']},{'period':'FY2025','amount':fy2025,'source_id':'us_omb2027','observation_id':receipts['FY2025']['observation_id']}],'formulas':{'general_applications':'nationality_class_issued * global_class_applications / global_class_issued','B_applications':'raw national B-class weight=issued/(1-adjusted national B refusal rate); normalize within each B1/B2/B1-B2 class to published worldwide applications; fallback to worldwide class ratio when unavailable/100%','fee_weight':'modeled_class_applications * effective_tariff','account_allocation':'fee_weight / sum(all fee weights) * account_control','calendar2024':'0.75*FY2024_actual + 0.25*FY2025_actual','calendar2025':'FY2025_actual flat-time proxy; no FY2026 actual invented','nationality_sensitivity_2025':'multiply one payer weight by0.75/1.25; denominator=1+(factor-1)*payer_share; renormalize all payers to account control'},'calendar_controls':annual_checks,'free_classes':[c for c in workload if is_free(c)],'tariffs_usd':{'general':185,'H_L_O_P_Q_R':205,'E':315,'K':265,'BCC_regular':185,'BCC_qualifying_child':15,'A_G_NATO_C2_C3':0},'fee_mixture_parameters':{'bcc_child_share_center':.1,'bcc_child_share_grid':[0,.1,.2],'j_exempt_share_center':.1,'j_exempt_share_grid':[0,.1,.2]},'class_allocation_checks':class_checks,'sensitivity_scenarios':scenarios,'sensitivity_interpretation':'Every coherent fee/bridge allocation scenario is normalized to the same control. 2025 timing scenarios change the account control by ±15%. Individual flow lower/upper envelopes include alternative models and separate nationality shocks, cannot be summed into a joint global range, and are not statistical confidence intervals.','limitations':['Adjusted B refusal rates count unique applicants with last fiscal-year action and adjusted overcomes, not matched raw application or paid-fee events.','Global workload applications are published activity counts, not verified fee-payment events; fiscal timing and accounting timing can differ.','Fee-mixture/bridge weights allocate an observed MRV account; normalization does not prove each nationality paid that amount.','CY2024 assumes uniform within-fiscal-year receipts and stableFY2024 nationality/class shares.','CY2025 is a FY2025-total proxy with FY2024 allocation shares, not observed calendar2025 receipts or nationality issues.','Other specific waivers and refunds beyond A/G/NATO/C2/C3 and J/BCC mix are absorbed by account calibration; reciprocity, SEVIS and USCIS amounts are excluded.','No-issuance classes with published applications retain UNK_USA origin, and non-country nationality labels retain shared resolver RAW codes.','J exchange is grouped other rather than assumed student; all K dependants grouped family, work-dependent classes follow work family.'],'b_refusal_fallbacks':fallback_b,'unmapped_nationality_labels':unmapped_labels,'input_sha256':{f:hashlib.sha256((RAW/f).read_bytes()).hexdigest() for f in ['nationality_class_2024.json','workload2024.json','adjusted_refusal_rates.json','actual_receipts.json']},'source_ids':['us_detail2024','us_workload2024','us_refusal2024','us_refusal_method','us_fees2024_cfr','us_fee_schedule','us_omb2026','us_omb2027']}]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({'flows':flows,'models':models},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'file':str(OUT.relative_to(ROOT)),'flows':len(flows),'all_workload_classes':len(workload),'fee_weight_denominator_usd':center_den,'FY2024_normalization_factor':fy2024/center_den,'annual_controls':annual_checks,'unresolved_observation_ids':unresolved,'b_refusal_fallback_count':len(fallback_b),'unmapped_labels':unmapped_labels},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
