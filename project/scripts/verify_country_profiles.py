#!/usr/bin/env python3
"""Check profile totals against chart records and event denominators against rows."""
from pathlib import Path
from collections import defaultdict
import json,math
ROOT=Path(__file__).resolve().parents[1]
def main():
 index=json.loads((ROOT/'app/data/index.json').read_text());data=json.loads((ROOT/'app/data.json').read_text());profiles=index['countryProfiles'];checks=[]
 def check(name,ok,detail=None):
  checks.append(dict(check=name,passed=bool(ok),detail=detail));print(('PASS ' if ok else 'FAIL ')+name)
 members=set(index['schengenMembers']);norm=lambda c:'SCH' if c in members else c;expected=defaultdict(lambda:[None,None]);sourceids={s['source_id'] for s in index['sources']};errors=[]
 for year,oi,di,gi,amount,count,zero in index['records']:
  a,b=norm(index['entities'][oi]['code']),norm(index['entities'][di]['code'])
  if a==b:continue
  expected[a,year][1]=(expected[a,year][1] or 0)+amount;expected[b,year][0]=(expected[b,year][0] or 0)+amount
 for code,years in profiles.items():
  for year,p in years.items():
   for i,key in enumerate(['incoming','outgoing']):
    actual=p[key]['amount_cny'];want=expected[code,int(year)][i]
    if (actual is None)!=(want is None) or actual is not None and not math.isclose(actual,want,rel_tol=1e-9,abs_tol=.05):errors.append([code,year,key,actual,want])
 check('all country-year amounts equal the chart index with identical Schengen scope',not errors,errors[:5])
 groups={'applications':{'applications','applications_by_biometric_enrolment_date','applications_received_with_suppression_midpoints'},'paid_events':{'modeled_paid_events','modeled_paid_600_applications'},'issued':{'observed_visa_issuances_in_documented_fee_exempt_category','observed_evisas_issued_not_paid_applications','visas_issued','evisas_issued','modeled_full_year_VOA_issued','observed_consular_visa_issuance_not_paid_applications','modeled_consular_visa_issuance_scenario','issued_evisa_benchmark_annual_model_not_all_paid_applications','observed_visas_issued_not_unique_people_or_paid_applications'},'processed_benchmark':{'observed_processed_national_visa_cohort_standard_fee_benchmark'},'decisions':{'modeled_calendar_decided_applications'},'modeled_events':{'modeled_calendar_events_from_explicit_source_period'}}
 # Independently pool native fee rows once, not the summary builder's function.
 metrics=defaultdict(lambda:[0.,0.,0])
 for r in data['flows']:
  a,b=norm(r['payer']),norm(r['receiver']);q=r.get('quantity')
  if a==b or not isinstance(q,(int,float)) or q<=0:continue
  group=next((g for g,allowed in groups.items() if r.get('quantity_basis') in allowed),None)
  if group is None:continue
  for code,side in [(a,'outgoing'),(b,'incoming')]:
   m=metrics[code,r['year'],side,group];m[0]+=q;m[1]+=r['amount_cny'];m[2]+=1
 bad=[];all_bench=[];popbad=[]
 for code,years in profiles.items():
  for y,p in years.items():
   population=p.get('population')
   if population and (population['year']!=int(y) or population['value']<=0 or population['source_id'] not in sourceids):popbad.append([code,y])
   for side in ['incoming','outgoing']:
    b=p[side].get('benchmark')
    if not b:continue
    all_bench.append(b);q,amount,rows=metrics[code,int(y),side,b['basis']]
    if not math.isclose(q,b['quantity'],rel_tol=1e-10) or not math.isclose(amount,b['amount_cny'],rel_tol=1e-10) or rows!=b['rows']:bad.append([code,y,side])
 check('every event denominator and matched amount is reconstructed from native fee rows',not bad,bad[:5])
 check('event mean and coverage share use the matched fee subset',all(math.isclose(b['amount_cny']/b['quantity'],b['fee_per_event_cny'],rel_tol=1e-10) and (b['amount_share'] is None or 0<=b['amount_share']<=1.0000001) for b in all_bench),{'benchmarks':len(all_bench)})
 check('arrival and country-allocation proxies are excluded from application means',profiles['CAN']['2025']['incoming']['benchmark'] is None and profiles['NPL']['2025']['incoming']['benchmark'] is None)
 check('all population denominators use same year, positive values and archived sources',not popbad,popbad[:5])
 pop=json.loads((ROOT/'data/research/demographic_context/population.json').read_text());popmap={(r['code'],r['year']):r['value'] for r in pop}
 check('Schengen population sums all same-year members without China scope overlap',all(math.isclose(p['population']['value'],sum(popmap[c,int(y)] for c in members),rel_tol=1e-12) for y,p in profiles['SCH'].items() if p['population']))
 check('Hong Kong Macao Taiwan and mainland product names are canonical',all(next(e['name'] for e in index['entities'] if e['code']==c)==n for c,n in [('CHN','中国大陆'),('HKG','中国香港'),('MAC','中国澳门'),('TWN','中国台湾')]))
 check('single China statistical principle is explicit in product data',all(x in index['meta']['jurisdiction_note'] for x in ['一个中国原则','中国香港','中国澳门','中国台湾','不代表独立国家']))
 check('summary sources all resolve to the unified registry',all(set(d['source_ids'])<=sourceids and (not d.get('benchmark') or set(d['benchmark']['source_ids'])<=sourceids) for years in profiles.values() for p in years.values() for d in [p['incoming'],p['outgoing']]))
 check('missing amounts remain null while explicit free amounts stay zero',all(p['incoming']['amount_cny'] is None for p in profiles.get('ATA',{}).values()) and any(p['incoming']['amount_cny']==0 for years in profiles.values() for p in years.values()))
 report=dict(passed=all(r['passed'] for r in checks),version=index['meta']['version'],ui_version=index['meta']['ui_version'],profiles=len(profiles),country_years=sum(len(v) for v in profiles.values()),checks=checks)
 (ROOT/'docs/validation/country-profile-data.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');assert report['passed']
if __name__=='__main__':main()
