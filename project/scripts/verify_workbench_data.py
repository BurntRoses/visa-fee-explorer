#!/usr/bin/env python3
"""Read-only validation of the final money ledger and workbench evidence index.

Writes only docs/validation/workbench-data-verification.{json,md}. It does not
rebuild, normalize, download, or repair product data. Fails with actionable row IDs.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

from research_packages import MONEY_PACKAGES, MONEY_EXTENSION_PACKAGES, CONTEXT_PACKAGES, active_money_inputs
ROOT=Path(__file__).resolve().parents[1]
PACKAGES=MONEY_PACKAGES
NEW=MONEY_EXTENSION_PACKAGES
REFINEMENTS=['evidence_refinement/schengen','evidence_refinement/uk_canada','evidence_refinement/korea_vietnam']
HISTORY_YEARS=tuple(range(2015,2024))


def load(path):
    return json.loads((ROOT/path).read_text())


def close(a,b,atol=.05):
    return math.isclose(a,b,rel_tol=1e-10,abs_tol=atol)


def fee_id(row):
    return row.get('fee_id',row.get('fee_rule_id',row.get('id',row.get('rule_id'))))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',default='app/data/index.json',help='Final built index path relative to workspace')
    args=parser.parse_args()
    index_path=ROOT/args.index
    idx=json.loads(index_path.read_text())
    flows=load('data/processed/flows.json')
    balances=load('data/processed/country_balances.json')
    meta=load('data/processed/flow_meta.json')
    sources=load('data/processed/sources.json')
    observations=load('data/processed/observations.json')
    source_by={r['source_id']:r for r in sources}
    obs_by={r['observation_id']:r for r in observations}
    flow_by={r['id']:r for r in flows}
    years=sorted({r['year'] for r in flows})
    errors=[];warnings=[];checks=[]
    def check(name,failures,count=None):
        failures=list(failures)
        checks.append(dict(check=name,status='fail' if failures else 'pass',checked=count,failure_count=len(failures),examples=failures[:20]))
        if failures:errors.append(dict(check=name,count=len(failures),examples=failures[:10]))
    check('unique_flow_ids',[k for k,n in collections.Counter(r['id'] for r in flows).items() if n>1],len(flows))
    check('unique_source_ids',[k for k,n in collections.Counter(r['source_id'] for r in sources).items() if n>1],len(sources))
    check('flow_source_references',[dict(flow=r['id'],source=s) for r in flows for s in r.get('source_ids',[]) if s not in source_by],len(flows))
    check('flow_observation_references',[dict(flow=r['id'],observation=o) for r in flows for o in r.get('observation_ids',[]) if o not in obs_by],len(flows))
    check('ordered_finite_money_ranges',[r['id'] for r in flows if not all(isinstance(r.get(k),(int,float)) and math.isfinite(r[k]) for k in ['amount_cny','lower_cny','upper_cny']) or not 0<=r['lower_cny']<=r['amount_cny']<=r['upper_cny']],len(flows))
    check('cross_border_no_world_or_self',[r['id'] for r in flows if r['payer']==r['receiver'] or r['payer']=='WORLD' or r['receiver'] in ['WORLD','UNK']],len(flows))
    check('calendar_model_period_labels',[r['id'] for r in flows if r.get('period_start')!=f'{r["year"]}-01-01' or r.get('period_end')!=f'{r["year"]}-12-31' or 'model' not in r.get('period_type','')],len(flows))
    year_errors=[]
    for label,actual in [('ledger metadata',meta.get('years')),('render metadata',idx['meta'].get('years'))]:
        if actual!=years:year_errors.append(dict(location=label,expected=years,actual=actual))
    check('dynamic_years_match_the_complete_ledger',year_errors,len(years))
    fx=[]
    for pkg in ['schengen_fx']+NEW:
        path=ROOT/f'data/research/{pkg}/fx.json'
        if path.exists():fx+=json.loads(path.read_text())
    rate={};fxconf=[]
    for r in fx:
        key=r['year'],r['currency']
        if key in rate and not close(rate[key],r['usd_per_unit'],1e-12):fxconf.append(dict(year=key[0],currency=key[1],first=rate[key],second=r['usd_per_unit']))
        rate[key]=r['usd_per_unit']
    check('fx_registry_no_conflicts',fxconf,len(fx))
    check('fx_source_references',[r['fx_id'] for r in fx if r.get('source_id') not in source_by],len(fx))
    history_fx=load('data/research/history/fx.json')
    historical_fx_errors=[]
    expected_history_fx={(y,c) for y in HISTORY_YEARS for c in ['CNY','EUR','GBP','USD']}
    actual_history_fx=collections.Counter((r['year'],r['currency']) for r in history_fx)
    for key in sorted(expected_history_fx|set(actual_history_fx)):
        expected=1 if key in expected_history_fx else 0
        if actual_history_fx[key]!=expected:historical_fx_errors.append(dict(year=key[0],currency=key[1],expected_records=expected,actual=actual_history_fx[key]))
    for r in history_fx:
        raw=r.get('raw_rate');direction=r.get('raw_direction')
        if not isinstance(raw,(int,float)) or not math.isfinite(raw) or raw<=0:
            historical_fx_errors.append(dict(fx=r['fx_id'],error='missing or invalid original historical quotation'));continue
        expected=1/raw if direction=='currency_per_USD' else raw if direction in ['USD_per_currency','USD_per_USD'] else None
        if expected is None or not close(expected,r['usd_per_unit'],1e-12):historical_fx_errors.append(dict(fx=r['fx_id'],error='historical quotation direction does not reproduce USD conversion'))
        if not r.get('source_locator') or not close(rate.get((r['year'],r['currency']),-1),r['usd_per_unit'],1e-12):historical_fx_errors.append(dict(fx=r['fx_id'],error='historical year FX or locator lost in shared registry'))
    check('historical_annual_FX_coverage_and_quote_directions',historical_fx_errors,len(history_fx))
    fxerr=[]
    for r in flows:
        c=r.get('currency');y=r['year']
        if c!='CNY' and ((y,c) not in rate or (y,'CNY') not in rate):
            fxerr.append(dict(flow=r['id'],error='missing FX',year=y,currency=c));continue
        for native,cny in [('amount','amount_cny'),('lower','lower_cny'),('upper','upper_cny')]:
            expected=r[native] if c=='CNY' else r[native]*rate[y,c]/rate[y,'CNY']
            if not close(expected,r[cny],2e-5):fxerr.append(dict(flow=r['id'],field=cny,expected=expected,actual=r[cny]))
    check('native_to_CNY_recomputation',fxerr,len(flows)*3)
    native=active_money_inputs(ROOT)
    provenance=[];native_ids=[]
    scopes=collections.defaultdict(set)
    for pkg,d in native.items():
        for r in d['flows']:
            native_ids.append(r['id']);scopes[r['receiver'],r['year']].add(pkg)
            target=flow_by.get(r['id'])
            if not target:
                provenance.append(dict(package=pkg,flow=r['id'],error='missing from final ledger'));continue
            for key in ['amount','lower','upper','currency','quantity','observation_ids','source_ids','parameters','notes']:
                if target.get(key)!=r.get(key):provenance.append(dict(package=pkg,flow=r['id'],field=key,error='native metadata changed or lost'))
    check('all_native_flows_integrated_and_parameters_preserved',provenance,len(native_ids))
    check('native_packages_have_no_duplicate_flow_ids',[k for k,n in collections.Counter(native_ids).items() if n>1],len(native_ids))
    # Disjoint visa categories may share a receiver/year (Germany national D
    # versus Schengen short stay). A category collision still requires review.
    category_scopes=collections.defaultdict(set)
    for pkg,d in native.items():
        for r in d['flows']:category_scopes[r['receiver'],r['year'],r['visa_group']].add(pkg)
    check('new_packages_do_not_overlap_receiver_year_category_scopes',[dict(receiver=k[0],year=k[1],visa_group=k[2],packages=sorted(v)) for k,v in category_scopes.items() if len(v)>1 and any(p in NEW for p in v)],len(category_scopes))
    native_model_errors=[]
    indexed_models=collections.defaultdict(list)
    for r in idx.get('models',[]):indexed_models[r.get('model_id',r.get('method_id'))].append(r)
    for pkg in NEW:
        for r in native[pkg]['models']:
            key=r.get('model_id',r.get('method_id'))
            if r not in indexed_models.get(key,[]):native_model_errors.append(dict(package=pkg,model=key,error='native model metadata changed or absent from product'))
    check('new_package_model_metadata_preserved',native_model_errors,sum(len(native[p]['models']) for p in NEW))
    archive_errors=[];source_count=0
    for pkg in NEW+REFINEMENTS+sorted(CONTEXT_PACKAGES):
        for r in load(f'data/research/{pkg}/sources.json'):
            p=r.get('local_path') or r.get('path')
            if not p:continue
            p=ROOT/p
            if not p.exists():archive_errors.append(dict(source=r['source_id'],error='archive missing',path=str(p)));continue
            source_count+=1
            expected=r.get('sha256')
            if expected and hashlib.sha256(p.read_bytes()).hexdigest()!=expected:archive_errors.append(dict(source=r['source_id'],error='SHA256 mismatch',path=str(p)))
            if r.get('archive_status')=='original_archived' and r.get('capture_method')=='search_service_indexed_excerpt':archive_errors.append(dict(source=r['source_id'],error='indexed excerpt mislabelled original'))
    check('new_source_archives_hash_and_capture_status',archive_errors,source_count)
    # Reuse the already completed raw-workbook reconciliation instead of opening
    # all nine workbooks during every product validation.
    cached_history=load('data/research/history/checks.json')
    reused_history_errors=[dict(check=r.get('check'),year=r.get('year'),error='archived historical evidence check failed') for r in cached_history if not r.get('passed')]
    reconciliations=[r for r in cached_history if r.get('check')=='schengen_detail_vs_state_summary']
    reconciliation_years=collections.Counter(r.get('year') for r in reconciliations)
    for y in HISTORY_YEARS:
        if reconciliation_years[y]!=1:reused_history_errors.append(dict(year=y,error='missing or duplicate completed workbook reconciliation'))
    for r in reconciliations:
        if r.get('detail')!=r.get('reported'):reused_history_errors.append(dict(year=r.get('year'),error='completed source reconciliation has nonzero residual'))
    check('historical_source_reconciliations_reused',reused_history_errors,len(cached_history))
    # Some French short-stay lines are moved intact into the French fiscal
    # constraint package. Validate the original historical inputs by ID.
    historical=load('data/estimates/history_flows.json')['flows']
    historic_models={m['year']:m for m in native['history']['models'] if m.get('destination')=='SCH'}
    historic_coverage={r['year']:r for r in load('data/research/history/annual_coverage.json')}
    member_errors=[]
    for y in HISTORY_YEARS:
        expected_count=26 if y==2023 else 25
        model=historic_models.get(y,{})
        issuing=set(model.get('issuing_members',[]))
        actual={r['receiver'] for r in historical if r['year']==y and r['receiver']!='GBR'}
        integrated={flow_by[r['id']]['receiver'] for r in historical if r['year']==y and r['receiver']!='GBR' and r['id'] in flow_by}
        if len(issuing)!=expected_count or actual!=issuing or integrated!=issuing:
            member_errors.append(dict(year=y,expected_issuers=expected_count,source_issuers=sorted(issuing),native_receivers=sorted(actual),final_receivers=sorted(integrated)))
        if ('HRV' in issuing)!=(y==2023) or issuing&{'BGR','ROU','LIE'}:
            member_errors.append(dict(year=y,error='current members backfilled or non-issuing Liechtenstein created'))
        expected_receivers=issuing|({'GBR'} if y>=2019 else set())
        cov=historic_coverage.get(y,{})
        if cov.get('receiver_count')!=len(expected_receivers) or set(cov.get('receivers',[]))!=expected_receivers:
            member_errors.append(dict(year=y,error='historical annual coverage differs from actual modeled receivers'))
    check('historical_members_and_actual_receiver_counts',member_errors,len(HISTORY_YEARS))
    french_actuals={2019:219_000_000,2020:61_000_000,2021:56_000_000,2024:261_000_000}
    r12_errors=[]
    for y,original in french_actuals.items():
        french=[r for r in flows if r['year']==y and r['receiver']=='FRA']
        other=[r for r in french if r['method_id']=='r12_fr_visa_receipts_unallocated_residual']
        if (len(other)!=1 or other[0]['payer']!='UNK' or other[0]['quantity'] is not None
            or not close(math.fsum(r['amount'] for r in french),original,.01)):
            r12_errors.append(dict(year=y,error='French receipt constraint or residual changed'))
    r12_context={r['observation_id'] for r in observations if r.get('native_file')=='data/research/r12_public_statistics/observations.json'}
    for r in flows:
        if r12_context.intersection(r.get('observation_ids',[])):
            r12_errors.append(dict(flow=r['id'],error='background statistics used in fee ledger'))
    check('r12_france_receipts_no_duplicate_and_background_outside_ledger',r12_errors,len(r12_context)+len(french_actuals))
    historic_fee_errors=[];uk_student_date_errors=[];uk_student_2023_rows=0
    for r in historical:
        target=flow_by.get(r['id'],{})
        if r['receiver']=='GBR':
            expected_group='student' if r['visa_group']=='study' else r['visa_group']
            if target.get('visa_group')!=expected_group:historic_fee_errors.append(dict(flow=r['id'],error='historical UK study/visitor classification lost',expected=expected_group,actual=target.get('visa_group')))
            if r['year']==2023 and r['visa_group']=='study' and not r['visa_type'].startswith('Short-term'):
                uk_student_2023_rows+=1
                inputs=[obs_by[o] for o in r.get('observation_ids',[]) if o in obs_by]
                expected_native=dict(amount=0.,lower=0.,upper=0.)
                for o in inputs:
                    # 2023 Q1–Q3: £363. In Q4, Oct 1–3 remain £363;
                    # Oct 4–Dec 31 (89 days) use the published £490 policy.
                    after=str(o.get('period_start',''))>='2023-10-01'
                    center=(3*363+89*490)/92 if after else 363
                    for field,price in [('amount',center),('lower',363),('upper',490 if after else 363)]:expected_native[field]+=o['value']*price
                for field,expected in expected_native.items():
                    if not close(target.get(field,-1),expected,.01):uk_student_date_errors.append(dict(flow=r['id'],field=field,expected=expected,actual=target.get(field),error='2023 student fee must change within Q4, not across the full year'))
            continue
        if r['payer']=='UNK':continue
        c=r['payer'];y=r['year'];expected=None
        # Associated governments use their own bilateral treaty dates. Their
        # corrected exceptions are checked against dated evidence below.
        if r['receiver'] in ['CHE','NOR','ISL','DNK']:continue
        if c in ['ARM','AZE'] or (c in ['GEO','UKR'] and y<2017) or (c=='RUS' and y<2022):expected=35
        elif c=='RUS':expected=(254*35+111*80)/365 if y==2022 else 80
        elif c=='BLR':expected=60 if y<=2019 else (32*60+150*80+184*35)/366 if y==2020 else 35
        elif c=='CPV' and y>=2022:expected=(181*80+184*60)/365 if y==2022 else 60
        elif c not in ['GEO','UKR']:expected=60 if y<=2019 else (32*60+334*80)/366 if y==2020 else 80
        if expected is not None and not close(target.get('parameters',{}).get('adult_tariff_center',-1),expected,1e-10):
            historic_fee_errors.append(dict(flow=r['id'],payer=c,year=y,expected_adult_fee=expected,error='historical tariff or fee transition changed'))
        if c in ['GEO','UKR'] and y>=2017:historic_fee_errors.append(dict(flow=r['id'],error='post-liberalisation submission country assigned to local citizenship'))
    check('historical_fee_transitions_and_UK_study_scope',historic_fee_errors,len(historical))
    if not uk_student_2023_rows:uk_student_date_errors.append(dict(error='no 2023 UK student model rows checked'))
    check('historical_UK_2023_student_fee_effective_dates',uk_student_date_errors,uk_student_2023_rows)
    refined_tariff_errors=[]
    # Fixed legal examples independently test integration of receiver-specific
    # agreements and prevent unknown-nationality residuals receiving discounts.
    examples=[('ARM','FRA',2025,35),('AZE','CHE',2016,60),
              ('AZE','NOR',2015,(151*60+214*35)/365),
              ('RUS','NOR',2022,(264*35+101*80)/365),
              ('RUS','CHE',2022,(258*35+107*80)/365)]
    for payer,receiver,y,expected in examples:
        matches=[r for r in native['core' if y>=2024 else 'history']['flows'] if r['payer']==payer and r['receiver']==receiver and r['year']==y]
        if not matches:refined_tariff_errors.append(dict(payer=payer,receiver=receiver,year=y,error='dated legal example absent'));continue
        for r in matches:
            actual=r['parameters'].get('adult_tariff_center',r['parameters'].get('adult_tariff'))
            if not close(actual,expected,1e-10):refined_tariff_errors.append(dict(flow=r['id'],expected=expected,actual=actual))
    residuals=[r for r in native['core']['flows'] if r['payer']=='UNK' and r['receiver']=='FRA' and r['year']==2025 and r['parameters'].get('submission_country')=='ARM']
    if not residuals or any(not close(r['parameters'].get('adult_tariff',-1),90,1e-10) for r in residuals):refined_tariff_errors.append(dict(error='Armenia submission residual must retain general adult tariff'))
    check('dated_bilateral_tariffs_and_unknown_payer_rule',refined_tariff_errors,len(examples)+len(residuals))
    sums=collections.defaultdict(lambda:collections.defaultdict(float))
    for r in flows:
        for field in ['amount','amount_cny','lower_cny','upper_cny']:sums[r['receiver'],r['year']][field]+=r[field]
    control_errors=[];controls=[]
    def control(label,actual,expected):
        controls.append(dict(control=label,actual=actual,expected=expected,residual=actual-expected,status='pass' if close(actual,expected,.1) else 'fail'))
        if not close(actual,expected,.1):control_errors.append(controls[-1])
    for m in native['us']['models']:
        for c in m.get('calendar_controls',[]):control(f'USA {c["year"]} MRV calendar account',sums['USA',c['year']]['amount'],c['control_usd'])
    for m in native['asia']['models']:
        if m.get('model_id','').startswith('au_vac_calendar_'):control(f'AUS {m["year"]} calendar VAC',sums['AUS',m['year']]['amount'],m['center_AUD'])
    for m in native['uk_canada']['models']:
        if m.get('actual_fiscal_revenues'):
            anchors={int(r['period_start'][:4]):r for r in m['actual_fiscal_revenues']}
            for fiscal in anchors.values():
                o=obs_by.get(fiscal['observation_id'],{})
                control(m['method_id']+' '+fiscal['period_start']+' actual source',fiscal['amount'],o.get('value',-1))
            for y in [2024,2025]:
                expected=.25*anchors[y-1]['amount']+.75*anchors[y]['amount']
                control(m['method_id']+f' CY{y} fiscal interpolation',sum(r['amount'] for r in flows if r['year']==y and r['method_id']==m['method_id']),expected)
            continue
        if 'actual_fiscal_revenue' not in m:continue
        ss=m['calendar_scenarios']
        control(m['method_id']+' FY2024/25 weighted bridge',.75*ss['2024']['center']+.25*ss['2025']['center'],m['actual_fiscal_revenue'])
    # Totals recomputed from six published Public Accounts rows, independently
    # of country weights, applicant counts and old fee-report scenarios.
    for y,expected in [(2024,688085364.75),(2025,567138716.25)]:
        control(f'CAN {y} six disjoint actual-account bridge',sums['CAN',y]['amount'],expected)
    ca=[r for r in native['uk_canada']['flows'] if r['receiver']=='CAN']
    ca_errors=[]
    for r in ca:
        if not r['method_id'].startswith('ca_pa_') or 'ca_trv_individual_tariff_scenario_v1' in str(r):ca_errors.append(dict(flow=r['id'],error='superseded tariff scenario still included'))
        if r['visa_group']=='Work' and r['payer']!='UNK':ca_errors.append(dict(flow=r['id'],error='work source country was inferred without evidence'))
        if r['payer']!='UNK' and r.get('origin_basis')!='source_country_proxy':ca_errors.append(dict(flow=r['id'],error='source-country proxy labelled observed nationality'))
    check('canada_replaces_old_scenario_and_preserves_origin_scope',ca_errors,len(ca))
    for y in sorted({r['year'] for r in native['global_asia_me_europe']['flows'] if r['receiver']=='LKA'}):
        rr=[r for r in native['global_asia_me_europe']['flows'] if r['receiver']=='LKA' and r['year']==y]
        expected=sum(obs_by[o]['value'] for r in rr for o in r.get('observation_ids',[]) if o in obs_by)
        # Older native schemas may express the 2025 actual in LKR millions.
        if expected and expected<sum(r['amount'] for r in rr)/1000:
            expected*=1000000
        control(f'LKA {y} visa-only receipts excluding ETA',sum(r['amount'] for r in rr),expected)
    for r in load('data/research/europe_fiscal_v6/annual_cash_controls.json'):
        control(f'CYP {r["year"]} 01373 actual visa leaf',sums['CYP',r['year']]['amount'],r['amount'])
    # Independent arithmetic uses the reported crore amounts, never the
    # replacement candidates that the core model consumes.
    control('IND2024 adjacent actual fiscal receipt bridge',sums['IND',2024]['amount'],(.25*1396.91+.75*1488.38)*1e7)
    control('IND2025 latest complete fiscal receipt proxy',sums['IND',2025]['amount'],1488.38*1e7)
    check('key_receipt_controls_and_fiscal_identities',control_errors,len(controls))
    india=[r for r in flows if r['receiver']=='IND' and r['year'] in (2024,2025)]
    india_errors=[]
    for r in india:
        if r['payer']!='UNK' or r.get('quantity') is not None or 'ir7_mea_annual2025' not in r['source_ids']:
            india_errors.append(r['id'])
        if r['year']==2025 and (r['parameters'].get('next_fy_actual_known') is not False or not close(r['lower'],r['amount']*.65,.1) or not close(r['upper'],r['amount']*1.35,.1)):
            india_errors.append(dict(id=r['id'],error='latest FY proxy lost its scope or range'))
    if len(india)!=2:india_errors.append('expected exactly one replacement edge per year')
    check('india_latest_actual_replaces_old_proxy_without_invented_payers_or_paid_counts',india_errors,len(india))
    cyprus_errors=[]
    cyprus=[r for r in flows if r['receiver']=='CYP']
    for r in cyprus:
        if r['payer']!='UNK' or r.get('quantity') is not None:
            cyprus_errors.append(dict(flow=r['id'],error='unidentified payer or paid quantity invented'))
        for sid in r['source_ids']:
            source=source_by[sid]
            if source.get('archive_kind')!='fact_excerpt' or source.get('original_downloaded') is not False:
                cyprus_errors.append(dict(flow=r['id'],source=sid,error='indexed fact excerpt lost source identity'))
    check('cyprus_indexed_receipt_scope_and_unknown_denominator_preserved',cyprus_errors,len(cyprus))
    annual_errors=[]
    annual_by={r['year']:r for r in meta['annual_ranges']}
    if len(annual_by)!=len(meta['annual_ranges']):annual_errors.append(dict(error='duplicate annual joint ranges'))
    if set(annual_by)!=set(years):annual_errors.append(dict(error='annual joint range years differ from ledger',expected=years,actual=sorted(annual_by)))
    destination_by={(r['receiver'],r['year']):r for r in meta['destination_ranges']}
    if len(destination_by)!=len(meta['destination_ranges']):annual_errors.append(dict(error='duplicate receiver/year joint ranges'))
    if set(destination_by)!=set(sums):annual_errors.append(dict(error='destination joint range scopes differ from ledger',missing=sorted(set(sums)-set(destination_by)),extra=sorted(set(destination_by)-set(sums))))
    for y in years:
        ff=[r for r in flows if r['year']==y];bb=[r for r in balances if r['year']==y]
        edge=math.fsum(r['amount_cny'] for r in ff)
        for label,v in [('inflow',math.fsum(r['inflow_cny'] for r in bb)),('outflow',math.fsum(r['outflow_cny'] for r in bb))]:
            if not close(edge,v,.1):annual_errors.append(dict(year=y,total=label,edges=edge,balances=v))
        if abs(math.fsum(r['net_cny'] for r in bb))>.1:annual_errors.append(dict(year=y,error='net does not sum to zero'))
        a=annual_by.get(y)
        if not a:continue
        if not close(a['amount_cny'],edge,.1):annual_errors.append(dict(year=y,error='annual center differs from edges'))
        if not a['lower_cny']<=a['amount_cny']<=a['upper_cny']:annual_errors.append(dict(year=y,error='annual bounds reversed'))
        joint=[r for r in meta['destination_ranges'] if r['year']==y]
        for field in ['lower_cny','upper_cny']:
            if not close(a[field],math.fsum(r[field] for r in joint),.1):annual_errors.append(dict(year=y,field=field,error='annual range differs from joint receiver controls'))
    for r in meta['destination_ranges']:
        if not close(r['amount_cny'],sums[r['receiver'],r['year']]['amount_cny'],.1):annual_errors.append(dict(receiver=r['receiver'],year=r['year'],error='destination center differs from edges'))
        if not 0<=r['lower_cny']<=r['amount_cny']<=r['upper_cny']:annual_errors.append(dict(receiver=r['receiver'],year=r['year'],error='destination bounds reversed'))
    check('single_ledger_conservation_and_joint_ranges',annual_errors,len(flows))
    range_metadata_errors=[]
    for pkg in NEW:
        for r in native[pkg].get('destination_ranges',[]):
            key=r['receiver'],r['year'];destination=destination_by.get(key)
            target=next((c for c in destination.get('components',[]) if c.get('package')==pkg),None) if destination else None
            if not target:range_metadata_errors.append(dict(package=pkg,receiver=key[0],year=key[1],error='native receiver range absent'));continue
            for field,native_field in [('amount_cny','amount'),('lower_cny','lower'),('upper_cny','upper')]:
                expected=r[native_field] if r['currency']=='CNY' else r[native_field]*rate[key[1],r['currency']]/rate[key[1],'CNY']
                if not close(target[field],expected,.1):range_metadata_errors.append(dict(package=pkg,receiver=key[0],year=key[1],field=field,error='native joint range changed'))
            for field in set(r)-{'amount','lower','upper','currency'}:
                if target.get(field)!=r[field]:range_metadata_errors.append(dict(package=pkg,receiver=key[0],year=key[1],field=field,error='native joint range metadata changed or lost'))
    check('new_package_joint_ranges_and_metadata_preserved',range_metadata_errors,sum(len(native[p].get('destination_ranges',[])) for p in NEW))
    # Compare every final evidence chunk and rendering record; no design acceptance
    # inference is made by this structural check.
    chunkrows=[];chunkerr=[]
    for key,rel in idx['chunks'].items():
        p=index_path.parent/rel
        if not p.exists():chunkerr.append(dict(chunk=key,error='missing file'));continue
        rr=json.loads(gzip.decompress(p.read_bytes()))
        for r in rr:
            if f'{r["receiver"]}-{r["year"]}'!=key:chunkerr.append(dict(chunk=key,flow=r['id'],error='wrong receiver/year partition'))
            base=flow_by.get(r['id'])
            if not base:chunkerr.append(dict(flow=r['id'],error='chunk row not in ledger'));continue
            for f in ['amount_cny','lower_cny','upper_cny','parameters','source_ids','observation_ids']:
                if r.get(f)!=base.get(f):chunkerr.append(dict(flow=r['id'],field=f,error='chunk differs from ledger'))
        chunkrows+=rr
    counts=collections.Counter(r['id'] for r in chunkrows)
    for fid in flow_by:
        if counts[fid]!=1:chunkerr.append(dict(flow=fid,chunk_occurrences=counts[fid]))
    check('lazy_chunks_exactly_cover_ledger_and_keep_evidence',chunkerr,len(chunkrows))
    entity={r['code']:i for i,r in enumerate(idx['entities'])}
    groups=idx['groups'];cell=collections.defaultdict(lambda:[0.0,0,0]);rendererr=[]
    for r in chunkrows:
        try:key=r['year'],entity[r['payer']],entity[r['receiver']],groups.index(r['display_group'])
        except (KeyError,ValueError):rendererr.append(dict(flow=r['id'],error='invalid index entity/group'));continue
        cell[key][0]+=r['amount_cny'];cell[key][1]+=1;cell[key][2]+=int(r['amount_cny']==0)
    for r in idx['records']:
        key=tuple(r[:4]);expected=cell.pop(key,None)
        if not expected or not close(r[4],expected[0],2e-5) or r[5:]!=expected[1:]:rendererr.append(dict(key=key,index=r[4:],expected=expected))
    for k,v in cell.items():rendererr.append(dict(key=k,error='missing compact record',expected=v))
    check('compact_render_index_conserves_every_money_row',rendererr,len(idx['records']))
    classify=[]
    for r in chunkrows:
        expected_unclassified=r.get('category_detail_status')=='unclassified' or (r['receiver'] in ['MEX','LKA','IRL'] and r['visa_group']=='other') or (r['receiver'] in ['CHN','IND','TUR','AUS'] and r['visa_group']=='other')
        if expected_unclassified and r.get('display_group')!='unclassified':classify.append(dict(flow=r['id'],receiver=r['receiver'],display_group=r.get('display_group'),error='quantity or receipts have no purpose split; must be unclassified'))
    check('unsplit_total_receipts_not_labelled_other_purpose',classify,len(chunkrows))
    cby={(r['code'],r['year'],r['visa_group']):r for r in idx['coverage']}
    check('coverage_source_references',[dict(country=r['code'],year=r['year'],group=r['visa_group'],source=s) for r in idx['coverage'] for s in r.get('source_ids',[]) if s not in source_by],len(idx['coverage']))
    product_year_errors=[]
    year_coverage={r['year']:r for r in idx['meta'].get('year_coverage',[])}
    if set(year_coverage)!=set(years):product_year_errors.append(dict(error='render year coverage does not cover every ledger year',expected=years,actual=sorted(year_coverage)))
    for y in years:
        expected={r['receiver'] for r in flows if r['year']==y}
        actual=set(year_coverage.get(y,{}).get('receivers',[]))
        if actual!=expected:product_year_errors.append(dict(year=y,error='render actual receiver coverage differs from ledger',expected=sorted(expected),actual=sorted(actual)))
    coverage_years={r['year'] for r in idx['coverage']}
    if coverage_years!=set(years):product_year_errors.append(dict(error='coverage inventory omits ledger years',expected=years,actual=sorted(coverage_years)))
    if idx.get('annualRanges')!=meta['annual_ranges']:product_year_errors.append(dict(error='render annual ranges or metadata differ from the final ledger'))
    check('product_year_receiver_coverage_and_annual_ranges',product_year_errors,len(years))
    # These packages explicitly state current-only/historical-unverified evidence.
    historical=[]
    for code in ['EGY','ETH','CHL','DOM','ARG','PER']:
        for y in [y for y in years if y>=2024]:
            r=cby.get((code,y,'visitor'))
            if r and r['fee_known']:
                historical.append(dict(country=code,year=y,source_ids=r['source_ids'],error='current snapshot or unverified historical fee incorrectly shown as historical known'))
    mar_rules={r['id']:r for r in idx['feeRules'] if r.get('destination')=='MAR' and r['id'].startswith('aiv5_mar_')}
    expected_mar={'aiv5_mar_evisa_normal_chancellerie':700,'aiv5_mar_evisa_express_chancellerie':1000,
                  'aiv5_mar_evisa_normal_government_service_remuneration':70,'aiv5_mar_evisa_express_government_service_remuneration':100}
    for fid,amount in expected_mar.items():
        r=mar_rules.get(fid,{})
        if r.get('amount')!=amount or r.get('effective_from')!='2022-07-10' or 'aiv5_mar_bo7106' not in r.get('source_ids',[]):
            historical.append(dict(fee_rule_id=fid,error='Morocco historical tariff must come from the dated 2022 original law, not current snapshot'))
    check('current_only_tariffs_not_backdated_and_new_Morocco_dated_law_preserved',historical,6*len([y for y in years if y>=2024])+len(expected_mar))
    vn=cby.get(('VNM',2024,'unclassified'),{})
    check('vietnam_half_year_count_not_marked_known_full_year',[] if vn.get('quantity_known') is False and vn.get('quantity_context_known') is True else [vn],1)
    vn_fees={r['id']:r for r in idx['feeRules'] if r.get('destination')=='VNM'}
    vn_errors=[]
    for fid,start in [('spx_vn_single_entry_evisa','2021-05-22'),('spx_vn_multiple_entry_evisa_up_to_90days','2023-10-03')]:
        f=vn_fees.get(fid,{})
        if f.get('validity_status')!='dated_historical_rule' or f.get('effective_from')!=start or 'refine_vn_consolidated12_2024' not in f.get('source_ids',[]):vn_errors.append(dict(fee_rule_id=fid,error='2024 consolidated-law evidence missing or stale'))
    check('vietnam_2024_historical_tariffs_verified',vn_errors,2)
    gapnotes=[]
    for pkg in NEW:
        for r in load(f'data/research/{pkg}/coverage.json'):
            reason=r.get('missing_reason')
            if not reason:continue
            key=r.get('code',r.get('destination')),r.get('year'),r.get('visa_group')
            target=cby.get(key)
            if target and reason not in target.get('notes',''):
                gapnotes.append(dict(country=key[0],year=key[1],group=key[2],error='native missing_reason absent from workbench evidence note'))
    check('native_coverage_gap_explanations_visible',gapnotes)
    # Narrow content assertions catch overlap/category mistakes that sums alone miss.
    gaa=native['global_americas_africa']['flows'];content=[]
    for r in gaa:
        if r['receiver']=='BRA' and r['payer']!='UNK':content.append(dict(flow=r['id'],error='birth country must not be nationality'))
        if r['receiver']=='TZA' and not r['parameters'].get('budget_not_actual'):content.append(dict(flow=r['id'],error='Tanzania budget claim lost'))
        if r['receiver']=='MEX' and r['visa_group']!='other':content.append(dict(flow=r['id'],error='Mexico unsplit quantity misclassified by purpose'))
        if r['receiver']=='UGA' and (r['visa_type']=='east_african_tourist' or r['visa_group']=='work'):content.append(dict(flow=r['id'],error='unresolved regional sharing or conflicting work quantity monetized'))
        if r['receiver'] in ['UGA','ZAF'] and not r['parameters'].get('fiscal_anchor'):content.append(dict(flow=r['id'],error='fiscal bridge provenance absent'))
    check('new_package_specific_scope_and_period_boundaries',content,len(gaa))
    expected_fee_ids={fee_id(r) for pkg in NEW if (ROOT/f'data/research/{pkg}/fee_rules.json').exists() for r in load(f'data/research/{pkg}/fee_rules.json')}
    actual_fee_ids={r.get('id') for r in idx['feeRules']}
    check('latest_native_fee_rules_in_product',[dict(fee_rule_id=f,error='product built before latest research package') for f in sorted(expected_fee_ids-actual_fee_ids,key=str)],len(expected_fee_ids))
    for pkg in NEW:
        for m in native[pkg]['models']:
            if any(x in str(m).lower() for x in ['budget','carry','unverified','partial','sensitivity','run-rate']):
                warnings.append(dict(model=m.get('model_id'),scope='Explicit working model / partial coverage; passing checks does not establish national actual receipts'))
    report=dict(timestamp=datetime.now(timezone.utc).isoformat(),version=idx['meta'].get('version'),index=args.index,status='fail' if errors else 'pass',flow_count=len(flows),source_count=len(sources),observation_count=len(observations),chunk_count=len(idx['chunks']),render_record_count=len(idx['records']),check_count=len(checks),failed_checks=len(errors),failures=errors,checks=checks,receipt_controls=controls,scope_notes=warnings,limitations=['Validation checks consistency, recomputation and evidence boundaries; visual quality and user acceptance require the rendered workbench.','Parameter scenario envelopes are not statistical confidence intervals; marginal edge ranges are not added to override joint destination controls.'])
    out=ROOT/'docs/validation';out.mkdir(parents=True,exist_ok=True)
    (out/'workbench-data-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=[f'# Workbench data verification — {report["status"].upper()}', '',f'Version {report["version"]}; {len(flows):,} flows; {len(checks)} checks; {len(errors)} failed checks.','', 'Checks:']
    lines += [f'- {r["status"].upper()}: {r["check"]} ({r["failure_count"]} failures)' for r in checks]
    if errors:
        lines+=['','Actionable failures:']+[f'- {e["check"]}: {json.dumps(e["examples"][:3],ensure_ascii=False)}' for e in errors]
    lines+=['','Receipt controls:']+[f'- {c["status"].upper()} {c["control"]}: {c["actual"]:,.6f}; expected {c["expected"]:,.6f}' for c in controls]
    lines+=['','Money estimates retain explicit source and model limits. These checks do not imply design acceptance or complete global actual receipts.']
    (out/'workbench-data-verification.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:report[k] for k in ['version','status','flow_count','source_count','chunk_count','check_count','failed_checks','failures']},ensure_ascii=False,indent=2))
    return 1 if errors else 0


if __name__=='__main__':
    sys.exit(main())
