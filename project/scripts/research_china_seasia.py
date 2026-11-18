#!/usr/bin/env python3
"""Offline extraction of China / southeast Asia evidence; optional --download refresh."""
import json,csv,hashlib,re,calendar,argparse,subprocess
from pathlib import Path
from datetime import datetime,timezone
from bs4 import BeautifulSoup
import pdfplumber
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'data/research/china_seasia';OUT.mkdir(parents=True,exist_ok=True)
def write(name,data):
 (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 if isinstance(data,list) and data and isinstance(data[0],dict):
  keys=list(dict.fromkeys(k for r in data for k in r))
  with (OUT/name.replace('.json','.csv')).open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,keys);w.writeheader();w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in data)
def text(rel):return BeautifulSoup((ROOT/'data/raw'/rel).read_bytes(),'html.parser').get_text(' ',strip=True)
def main(download=False):
 src=json.loads((OUT/'download-manifest.json').read_text())
 for r in src:
  p=ROOT/r['local_path'] if r.get('local_path') else None
  if download and p:subprocess.run(['curl','-fsSL','--max-time','40',r['url'],'-o',str(p)],check=True)
  if p and p.exists():
   r.update(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),retrieved_at=datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(),source_quality='official_primary')
   if p.stat().st_size<300:r['archive_status']='challenge_or_empty_not_used'
  else:r['archive_status']='download_failed; web-text snapshot when available'
 for r in src:
  if r['source_id'] in ['sg_fee','th_waiver_mutual','th_fee']:
   r.update(local_path='data/raw/root-fee-web-snapshot.txt',archive_status='official_web_text_snapshot; HTTP original failed or challenge; not original HTML',sha256=hashlib.sha256((ROOT/'data/raw/root-fee-web-snapshot.txt').read_bytes()).hexdigest(),retrieved_at='2026-11-15',capture_method='web_tool_text_snapshot',source_quality='official_primary',title={'sg_fee':'ICA Visa processing fee','th_waiver_mutual':'中泰互免签证协定2024-03-01生效','th_fee':'Thailand official reference visa fees'}[r['source_id']])
 src.append(dict(source_id='root_fee_web',url=None,publisher='ICA / Thailand PRD / China MCT',title='Official fee/policy web text snapshots',local_path='data/raw/root-fee-web-snapshot.txt',source_quality='official_primary',retrieved_at='2026-11-15',source_locator='L21 ICA fee; L77 Thailand fee; L58 Thailand policy'))
 write('sources.json',src)
 obs=[]
 def add(oid,sid,year,value,metric,dest,origin=None,basis=None,locator=None,notes=None):
  obs.append(dict(observation_id=oid,source_id=sid,source_locator=locator,period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year',value=value,unit='events',metric=metric,destination=dest,origin=origin,origin_basis=basis,quantity_basis=metric,calculation_type='observed',notes=notes))
 for year,n,free in [(2024,2597000,20115000),(2025,2020000,30080000)]:
  txt=text(f'china/nia-{year}.html');assert ('259.7' if year==2024 else '202万') in txt
  add(f'cn_{year}_documents',f'cn_nia_{year}',year,n,'foreign_visa_and_residence_documents','CHN',locator='发布会主要数据段',notes='境内移民管理机构签证证件；含居留等，不是驻外签证总量')
  add(f'cn_{year}_waiver_entries',f'cn_nia_{year}',year,free,'visa_free_entries','CHN',locator='发布会主要数据段',notes='入境人次；不等于办证数或独立人数')
 txt=text('china/india-visa-issuance-2024.html');assert '280,000' in txt
 add('cn_indian_2024_issued','cn_india_2024',2024,280000,'issued','CHN','IND','nationality','Ambassador interview: 2024 visas for Indian citizens','驻印度使领馆；原文28万为报道精度，免费和类型结构未发布')
 j=json.loads((ROOT/'data/raw/singapore/visitor-arrivals-M550001.json').read_text())['Data']
 for row in j['row']:
  for year in (2024,2025):
   vals=[(c['key'],int(c['value'].replace(',',''))) for c in row['columns'] if c['key'].startswith(str(year)) and re.fullmatch(r'[\d,]+',c['value'])]
   if len(vals)!=12:continue
   add(f'sg_arrivals_{year}_{row["seriesNo"]}','sg_arrivals',year,sum(v for _,v in vals),'visitor_arrivals','SGP',row['rowText'],'place_of_residence',f'Data.row seriesNo={row["seriesNo"]}; 12 month columns',f'API metadata adjustmentType={j["adjustmentType"]}; preserve label; not visa counts')
   if row['rowText']=='China':
    for month,v in vals:
     rec=dict(obs[-1],observation_id=f'sg_arrivals_{month.replace(" ","_")}_China',value=v,source_locator=f'Data.row seriesNo=1.2.1; {month}',period_type='calendar_month')
     m=list(calendar.month_abbr).index(month.split()[1]);rec.update(period_start=f'{year}-{m:02d}-01',period_end=f'{year}-{m:02d}-{calendar.monthrange(year,m)[1]:02d}');obs.append(rec)
 with pdfplumber.open(ROOT/'data/raw/thailand/arrivals-2024.pdf') as pdf:txt='\n'.join(p.extract_text() or '' for p in pdf.pages)
 line=next(x for x in txt.splitlines() if '6,733,162' in x);assert 'China' in line
 add('th_chinese_2024_arrivals','th_arrivals_2024',2024,6733162,'tourist_arrivals','THA','CHN','nationality','Table17.3 PDF p1 China row', 'Tourist arrival events; not visas; all-purpose exceptions remain')
 write('observations.json',obs)
 fees=[]
 def fee(fid,dest,typ,amount,cur,start,end,sid,scope,trigger,refund,notes):
  fees.append(dict(fee_id=fid,destination=dest,visa_type=typ,amount=amount,currency=cur,effective_from=start,effective_to=end,source_id=sid,source_locator=scope,nationality_scope=scope,payment_trigger=trigger,refund_rule=refund,fee_component='government_fee',charge_basis='per_visa' if amount else 'qualifying_entry',notes=notes))
 txt=text('china/mumbai-fee-2024.html')
 for typ,amt in [('single_entry',2900),('double_entry',4400),('multiple_6_months',5900),('multiple_year_plus',8800)]:
  assert str(amt) in txt
  fee(f'cn_indian_{typ}_2024','CHN',typ,amt,'INR','2023-12-11','2025-12-31','cn_india_fee','Indian citizens; consulate section（五）','issuance','issuance-based; service fee separately','2024 notice; 2025 continuation notice; excludes centre fee / urgent fee')
 fee('cn_us_standard_2024','CHN','visa',140,'USD','2023-12-11','2024-12-31','cn_us_fee','US citizens normal visa; fee notice','issuance','consular rules','Historical fee; special J class and later policies separately')
 fee('sg_waiver_chinese','SGP','short_visit_waiver',0,'SGD','2024-02-09',None,'sg_waiver','Chinese ordinary passport; qualifying <=30-day visit','entry','not_applicable','Work/study/long residence require appropriate pass')
 fee('sg_processing','SGP','visa',30,'SGD',None,None,'root_fee_web','ICA fee snapshot L21; visa-required applicants','application','non-refundable','Reference fee; not charged to qualifying visa-free Chinese short visits')
 fee('th_waiver_chinese_2024','THA','short_visit_waiver',0,'THB','2023-09-25',None,'th_waiver_temporary','Chinese ordinary passport; temporary waiver then bilateral from 2024-03-01','entry','not_applicable','Short-visit conditions; work/study excluded; current stay limits require live check')
 fee('th_tourist_reference','THA','single_tourist',1000,'THB',None,None,'root_fee_web','PRD historical reference fee L77','application','not separately established here','THB benchmark; local consular prices may differ; not VOA THB2000')
 fee('my_waiver_chinese_2025','MYS','short_visit_waiver',0,'MYR','2025-07-17',None,'my_waiver','Chinese ordinary passport; <=30 days per visit, <=90/180 days','entry','not_applicable','Replaces earlier unilateral waiver; work/study exceptions')
 write('fee_rules.json',fees)
 estimates=[]
 fx=json.loads((ROOT/'data/research/schengen_fx/fx.json').read_text());rates={(r['year'],r['currency']):r['usd_per_unit'] for r in fx}
 for dest,oid,feeid,cur,unitfee in [('THA','th_chinese_2024_arrivals','th_tourist_reference','THB',1000),('SGP','sg_arrivals_2024_1.2.1','sg_processing','SGD',30)]:
  count=next(x['value'] for x in obs if x['observation_id']==oid)
  # Singapore February 9 cannot be partitioned exactly from monthly counts.
  if dest=='SGP':
   months=[x for x in obs if x['observation_id'].startswith('sg_arrivals_2024_') and x['period_type']=='calendar_month'];a=sum(x['value'] for x in months if x['period_start']>='2024-03-01');b=a+sum(x['value'] for x in months if x['period_start']=='2024-02-01')
  else:a=b=count
  for reuse in [1,2,4]:
   estimates.append(dict(estimate_id=f'waiver_{dest}_2024_reuse{reuse}',destination=dest,origin='CHN',year=2024,input_ids=[oid,feeid,f'fed_2024_{cur}','fed_2024_CNY'],method_id='fixed_travel_mechanical_counterfactual',formula='qualifying_arrivals * needs_new_visa_share / trips_per_visa * reference_fee',parameters={'trips_per_visa':reuse,'needs_new_visa_share':1,'reference_fee':unitfee,'arrival_lower':a,'arrival_upper':b},lower=a/reuse*unitfee,upper=b/reuse*unitfee,currency=cur,lower_cny=a/reuse*unitfee*rates[2024,cur]/rates[2024,'CNY'],upper_cny=b/reuse*unitfee*rates[2024,cur]/rates[2024,'CNY'],central=None,interval_type='conditional_scenario_not_confidence_interval',calculation_type='scenario',assumptions='Hold arrivals fixed; all counted arrivals treated as eligible; no existing valid visa except reuse parameter; no refused/non-travelling applications; no demand response',limitations='Residence vs citizenship mismatch for Singapore; not actual savings; not a mathematical upper bound on total foregone revenue; Singapore February bounds include eligibility uncertainty',permitted_use='scenario_only'))
 for price in [2900,4400,5900,8800]:
  estimates.append(dict(estimate_id=f'cn_indian_2024_rate{price}',destination='CHN',origin='IND',year=2024,input_ids=['cn_indian_2024_issued','cn_india_fee'],method_id='unknown_visa_mix',formula='280000 * standard_fee',parameters={'standard_fee':price,'paid_share':1},central=280000*price,currency='INR',calculation_type='scenario',interval_type=None,limitations='No observed mix or free-share; issuance-based reference only; 28万 rounded; not receipts or strict bounds',permitted_use='scenario_only'))
 write('estimates.json',estimates)
 write('checks.json',[{'check':'sg_full_year_months','passed':all(next(o['value'] for o in obs if o['observation_id']==f'sg_arrivals_{y}_1.2.1')==v for y,v in [(2024,3080054),(2025,3100156)])},{'check':'th_pdf_china_row','passed':'6,733,162' in line},{'check':'cn_india_issuance_text','passed':'280,000' in text('china/india-visa-issuance-2024.html')}])
 print(json.dumps({'sources':len(src),'observations':len(obs),'fees':len(fees),'estimates':len(estimates)},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--download',action='store_true');main(p.parse_args().download)
