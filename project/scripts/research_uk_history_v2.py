#!/usr/bin/env python3
"""Rebuild UK2013–2018 nationality/quarter visitor and study fee estimates offline.

Original application events remain distinct from unique people. Actual tariff dates,
visitor-duration mixes, short-study durations and legacy-route proxies are explicit.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import warnings

from bs4 import BeautifulSoup
import openpyxl
from pypdf import PdfReader
from research_history import code, quarter_bounds

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/uk_history_v2'
OUT=ROOT/'data/research/uk_history_v2'
EST=ROOT/'data/estimates/uk_history_v2_flows.json'
YEARS=range(2013,2019)
CHINA_START=date(2016,1,11)
# Effective start, visitor(6m/2y/5y/10y), Tier4, short study(6m/11m).
SCHEDULE=[
 (date(2012,4,6),(78,270,496,716),289,(78,140)),
 (date(2013,4,6),(80,278,511,737),298,(80,144)),
 (date(2014,4,6),(83,300,544,737),310,(83,150)),
 (date(2015,4,6),(85,324,588,737),322,(85,162)),
 (date(2016,3,18),(87,330,600,752),328,(89,170)),
 (date(2017,4,6),(89,337,612,767),335,(93,179)),
 (date(2018,4,6),(93,350,636,798),348,(97,186)),
]
# Annual original legislation, number, publication (made) date, relevant pages.
SPECS={
 'fees2012':(2012,971,'2012-03-27',[1,11]),
 'fees2012cost':(2012,813,'2012-03-13',[1,8]),
 'fees2013':(2013,749,'2013-03-26',[1,10,11]),
 'fees2013cost':(2013,617,'2013-03-14',[1,5]),
 'fees2014':(2014,922,'2014-04-02',[1,12,13]),
 'fees2014cost':(2014,581,'2014-03-11',[1,5]),
 'fees2015':(2015,768,'2015-03-18',[1,7,8,9]),
 'fees2016':(2016,226,'2016-02-23',[1,10,11]),
 'fees2017':(2017,515,'2017-03-30',[1,9,10]),
}
POLICY_URL='https://www.gov.uk/government/news/the-home-office-launches-new-two-year-chinese-visa-pilot'
CONTROLS={2013:{'Visitor':2205709,'Study':328987},2014:{'Visitor':2120560,'Study':320818},2015:{'Visitor':2222006,'Study':295556},2016:{'Visitor':2246991,'Study':320837},2017:{'Visitor':2385868,'Study':350806},2018:{'Visitor':2566351,'Study':373294}}


def read(p):return json.loads(p.read_text())
def dump(p,obj):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def stable(*parts):return 'ukh_flow_'+hashlib.sha256(json.dumps(parts,ensure_ascii=False).encode()).hexdigest()[:20]
def display_nationality(label,payer):
 return {'HKG':'中国香港','MAC':'中国澳门','TWN':'中国台湾'}.get(payer,label)


class Research:
 def __init__(self):
  self.sources=[];self.obs=[];self.fx=[];self.rules=[];self.cover=[];self.flows=[];self.models=[];self.ranges=[];self.checks=[];self.pages={}
 def check(self,name,passed,**details):
  self.checks.append(dict(check=name,passed=bool(passed),**details));assert passed,(name,details)
 def source(self,sid,path,url,title,published=None,notes=''):
  p=ROOT/path;self.check('original_exists_'+sid,p.is_file() and p.stat().st_size>0)
  self.sources.append(dict(source_id=sid,url=url,publisher='UK Home Office / UK Government',title=title,publication_date=published,
   local_path=path,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,retrieved_at=datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(),archive_status='archived',source_quality='official_primary',notes=notes))
 def archive(self):
  registry={s['source_id']:s for pkg in ['history','time_space'] for s in read(ROOT/f'data/research/{pkg}/sources.json')}
  for sid in ['history_uk_applications','history_uk_fee2018']:
   self.sources.append(registry[sid]);self.check('shared_original_hash_'+sid,hashlib.sha256((ROOT/registry[sid]['local_path']).read_bytes()).hexdigest()==registry[sid]['sha256'])
  for name,(y,n,pub,pages) in SPECS.items():
   self.source('ukh_'+name,f'data/raw/uk_history_v2/{name}.pdf',f'https://www.legislation.gov.uk/uksi/{y}/{n}/pdfs/uksi_{y}{n:04d}_en.pdf',f'Immigration and Nationality ({"Cost Recovery " if name.endswith("cost") else ""}Fees) Regulations {y}',pub,
    'Original contents identify SI2013/617; legacy downloads_extra.json has an incorrect /807 link for this local file.' if name=='fees2013cost' else '')
   d=PdfReader(RAW/f'{name}.pdf');texts=[]
   for page in pages:
    t=d.pages[page-1].extract_text() or '';self.pages[name,page]=t;texts.append(f'\n--- PDF page {page} ---\n'+t)
   (OUT/f'{name}_evidence.txt').write_text(''.join(texts)+'\n')
   self.check('original_instrument_identity_'+name,re.search(rf'{y}\s+No\.\s*{n}\b',self.pages[name,1]) is not None)
  d=PdfReader(ROOT/'data/raw/history/uk_fees2018base.pdf')
  for page in [1,10,11]:self.pages['fees2018',page]=d.pages[page-1].extract_text() or ''
  (OUT/'fees2018_evidence.txt').write_text(''.join(f'\n--- PDF page {p} ---\n'+self.pages['fees2018',p] for p in [1,10,11])+'\n')
  self.source('ukh_china_two_year2016','data/raw/uk_history_v2/china_two_year2016.html',POLICY_URL,'Home Office launches new two-year Chinese visa pilot','2016-01-06')
  t=BeautifulSoup((RAW/'china_two_year2016.html').read_text(),'html.parser').get_text(' ',strip=True)
  self.check('china_policy_start_and_initial_fee',all(s in t for s in ['11 January','£85','tourism, business']))
  self.check('china_scheme_mainland_qualification',all(s in self.pages['fees2016',10] for s in ['mainland China','Chinese national','£87']))
  for row in SCHEDULE:
   y=row[0].year;start=row[0]
   head=self.pages['fees'+str(y),1]
   self.check('tariff_commencement_'+str(y),('18th March 2016' if y==2016 else f'6th April {y}') in re.sub(r'\s+',' ',head))
  # Check every fee vector against its precise UK schedule pages, excluding Isle of Man/Channel Islands tables.
  fee_pages={2012:{'visitor': [('fees2012cost',8),('fees2012',11)],'study':[('fees2012cost',8)]},2013:{'visitor':[('fees2013cost',5),('fees2013',11)],'study':[('fees2013cost',5),('fees2013',10),('fees2013',11)]},2014:{'visitor':[('fees2014cost',5),('fees2014',12)],'study':[('fees2014cost',5),('fees2014',12),('fees2014',13)]},2015:{'visitor':[('fees2015',7),('fees2015',8)],'study':[('fees2015',8),('fees2015',9)]},2016:{'visitor':[('fees2016',10)],'study':[('fees2016',10),('fees2016',11)]},2017:{'visitor':[('fees2017',9)],'study':[('fees2017',9),('fees2017',10)]},2018:{'visitor':[('fees2018',10)],'study':[('fees2018',10),('fees2018',11)]}}
  self.fee_pages=fee_pages
  for start,visit,tier,short in SCHEDULE:
   y=start.year
   for group,values in [('visitor',visit),('study',(tier,*short))]:
    text=' '.join(self.pages[k] for k in fee_pages[y][group])
    for val in set(values):self.check(f'fee_document_{y}_{group}_{val}',bool(re.search(rf'£\s*{val}(?![\d,])',text)),pages=fee_pages[y][group])
 def fee_rules(self):
  for i,(start,vis,tier,short) in enumerate(SCHEDULE):
   end=(SCHEDULE[i+1][0]-timedelta(days=1)).isoformat() if i+1<len(SCHEDULE) else '2018-12-31'
   for kind,group,value in [(f'visitor_{term}','visitor',v) for term,v in zip(['6months','2years','5years','10years'],vis)]+[('tier4_entry','study',tier),('short_study_6months','study',short[0]),('short_study_11months','study',short[1])]:
    sids=self.tariff_sources(start.year,group)
    self.rules.append(dict(fee_id=f'ukh_{start.year}_{kind}',destination='GBR',visa_type=kind,visa_group=group,amount=value,currency='GBP',effective_from=start.isoformat(),effective_to=end,fee_component='government_application_fee',payment_trigger='application',source_ids=sids,
     source_locator='; '.join(f'{a}.pdf PDFp{p}' for a,p in self.fee_pages[start.year][group]),
     notes='2012–2013六个月学生访客按当期Part2普通短期访客费映射；11个月语言学习单独费率。' if kind=='short_study_6months' and start.year<2014 else 'UK entry clearance schedules only; no Isle of Man/Channel Islands fees'))
   if start.year>=2016:
    self.rules.append(dict(fee_id=f'ukh_{start.year}_china_2years',destination='GBR',visa_type='visitor_china_2years',visa_group='visitor',amount=vis[0],currency='GBP',effective_from=start.isoformat(),effective_to=end,fee_component='government_application_fee',payment_trigger='application',source_ids=self.tariff_sources(start.year,'visitor')+['ukh_china_two_year2016'],source_locator='UK Schedule1 Table1 item1.1.8; footnote(b)',notes='中国籍且从中国内地申请并符合方案要求；国籍数据不包含申请地点和资格'))
  self.rules.append(dict(fee_id='ukh_china_2016_launch',destination='GBR',visa_type='visitor_china_2years',visa_group='visitor',amount=85,currency='GBP',effective_from='2016-01-11',effective_to='2016-03-17',fee_component='government_application_fee',payment_trigger='application',source_ids=['ukh_china_two_year2016'],source_locator='Home Office launch announcement, published2016-01-06',notes='中国两年访客试行起始费；符合方案资格，不扩展至所有国籍或所有长期签'))
 def tariff_sources(self,y,group):
  if y==2018:return ['history_uk_fee2018']
  if y<2015:return ['ukh_fees'+str(y),'ukh_fees'+str(y)+'cost']
  return ['ukh_fees'+str(y)]
 @lru_cache(None)
 def unit_prices(self,y,quarter,group,subtype,payer):
  start,end=quarter_bounds(y,quarter);day=start;center=[];lower=[];upper=[];source_ids=set();segments=Counter()
  while day<end:
   d,vis,tier,short=next(row for row in reversed(SCHEDULE) if row[0]<=day);source_ids.update(self.tariff_sources(d.year,group.lower()))
   if group=='Visitor':
    # Duration centre remains90%6m +10%equally2/5/10y. Eligibility in the2y component is unknown.
    eligible_share=.5 if payer=='CHN' and day>=CHINA_START else 0
    v2=(1-eligible_share)*vis[1]+eligible_share*vis[0]
    v=.9*vis[0]+.1*(v2+vis[2]+vis[3])/3;lo=vis[0];hi=.75*vis[0]+.25*vis[3]
    if eligible_share:source_ids.add('ukh_china_two_year2016')
   elif subtype.startswith('Short-term'):
    lo,hi=short;v=(lo+hi)/2
   elif subtype=='Student - legacy route':
    # The workbook's legacy statistical label does not identify a fee-regulation item.
    # Preserve events with a clearly inferred Tier4 proxy; zero-to-proxy range does not claim observed waivers.
    v=tier;lo=0;hi=tier
   else:v=lo=hi=tier
   center.append(v);lower.append(lo);upper.append(hi);segments[(d.isoformat(),vis,tier,short)]+=1;day+=timedelta(days=1)
  return dict(center=sum(center)/len(center),lower=min(lower),upper=max(upper),source_ids=sorted(source_ids),segments=[dict(start=k[0],days=days,visitor=list(k[1]),tier4=k[2],short_study=list(k[3])) for k,days in segments.items()])
 def applications(self):
  w=openpyxl.load_workbook(ROOT/'data/raw/uk/entry-clearance-jun2026.xlsx',read_only=True,data_only=True)
  groups=defaultdict(lambda:dict(q=0,v=0.,lo=0.,hi=0.,oids=[],sids=set(),quarters=[]));totals=Counter();excluded=Counter();seen=set();unmapped=Counter();subtypes=Counter()
  validstudy={'Tier 4 - General Student','Tier 4 - Child Student','Short-term study (previously Student Visitor)','Student - legacy route'}
  for i,r in enumerate(w['Data_Vis_D01'].iter_rows(min_row=5,values_only=True),5):
   if str(r[0]) not in {str(y) for y in YEARS}:continue
   y=int(r[0]);group=r[4];q=r[8] or 0
   assert isinstance(q,(int,float)) and q>=0 and int(q)==q,(i,q)
   if group not in {'Visitor','Study'}:excluded[y,group]+=q;continue
   quarter=int(str(r[1])[-1]);subtype=r[6];applicant=r[7];key=(y,quarter,r[2],group,subtype,applicant)
   assert key not in seen,('duplicate source dimensions',i,key)
   seen.add(key);assert group=='Visitor' or subtype in validstudy,subtype
   payer={'Montserrat (British)':'MSR','Bermuda (British)':'BMU','Turks and Caicos Islands (British)':'TCA'}.get(r[2]) or code(r[2]);assert payer!='GBR',(i,r)
   if payer=='UNK':unmapped[r[2]]+=q
   start,end=quarter_bounds(y,quarter);oid=f'ukh_Vis_D01_r{i}';totals[y,group]+=q;subtypes[y,subtype]+=q
   self.obs.append(dict(observation_id=oid,source_id='history_uk_applications',source_locator=f"'Data_Vis_D01'!A{i}:I{i}",destination='GBR',nationality=display_nationality(r[2],payer),nationality_raw=r[2],payer=payer,year=y,quarter=quarter,origin_basis='nationality',visa_type=subtype,visa_group=group.lower(),applicant_type=applicant,metric='applications',raw_metric='Applications',value=q,unit='applications',quantity_basis='applications',period_start=start.isoformat(),period_end=(end-timedelta(days=1)).isoformat(),period_type='quarter',calculation_type='observed',notes='原表国籍、季度和主/附申请独立事件；数量不是独立申请人数；原始国籍标签见nationality_raw'))
   if not q:continue
   prices=self.unit_prices(y,quarter,group,subtype,payer);g=groups[y,payer,group,subtype]
   g['q']+=q;g['oids'].append(oid);g['sids'].update(prices['source_ids']);g['sids'].add('history_uk_applications')
   for field,scenario in [('v','center'),('lo','lower'),('hi','upper')]:g[field]+=q*prices[scenario]
   g['quarters'].append(dict(quarter=quarter,applicant_type=applicant,applications=q,**prices))
  w.close()
  self.check('source_unique_quarter_nationality_subtype_applicant_dimensions',len(seen)==len(self.obs),rows=len(self.obs))
  self.check('source_unknown_labels_explicit',set(unmapped)<= {'British overseas citizens','Other and unknown','Refugee','Stateless','Unknown','British Overseas citizens','Former Yugoslavia','Cyprus (Northern part of)'},labels=dict(unmapped))
  for (y,payer,group,subtype),g in sorted(groups.items()):
   legacy=subtype=='Student - legacy route';is_short=subtype.startswith('Short-term')
   note='真实季度国籍申请事件×当期英国境外申请费，主/附申请逐人计费；中心在季度内按日均匀分布，低/高按该季度可行费率日期。'
   if group=='Visitor':note+='访客期限为情景：中心90%六个月、10%等分两/五/十年；低全六个月，高75%六个月+25%十年。2016-01-11起中国两年部分中心假设50%从中国内地申请且符合优惠资格，资格未观测；五/十年维持普通价。'
   elif is_short:note+='短期学习原表合并六/十一月：中心各50%，低全六个月、高全十一月；2012/2013六个月学生访客按当期短访客费映射。'
   elif legacy:note+='Student旧路径无法与当期收费条目唯一对应，金额中心以Tier4代理，范围0至Tier4；这是路径映射敏感性，不是已观察到的减免。'
   else:note+='Tier4一般/儿童及附属申请按当期Tier4申请费。'
   params=dict(quarter_timing='uniform daily centre; feasible within-quarter date endpoint scenarios',quarter_observations=g['quarters'],quantity_meaning='application events, not unique people',excluded_charges=['IHS','priority','separately charged biometrics','outsourced service fees'],legacy_route_tariff_proxy=legacy,legacy_proxy_lower_zero_reason='unidentified fee item; mapping uncertainty, not observed waiver' if legacy else None)
   if group=='Visitor':params.update(visitor_duration_center={'6months':.9,'2years':.1/3,'5years':.1/3,'10years':.1/3},visitor_duration_lower={'6months':1},visitor_duration_upper={'6months':.75,'10years':.25},china_2year_scheme_start='2016-01-11',china_2year_eligibility_center=.5 if payer=='CHN' and y>=2016 else 0,china_2year_eligibility_range=[0,1] if payer=='CHN' and y>=2016 else [0,0],china_scope='Chinese nationals applying from mainland China; qualifying scheme conditions; nationality alone is insufficient')
   if is_short:params.update(short_study_duration_center={'6months':.5,'11months':.5},short_study_duration_range='all6month to all11month',short_study_2012_2013_mapping='StudentVisitor under Part2 mapped to ordinary6month visitor fee; explicit11month language concession separately documented')
   self.flows.append(dict(id=stable(y,payer,group,subtype),payer=payer,receiver='GBR',year=y,visa_group=group.lower(),visa_type=subtype,visa_label='英国访客' if group=='Visitor' else '英国短期学习' if is_short else '英国旧学习路径（代理）' if legacy else '英国Tier4学习',quantity=g['q'],quantity_basis='applications',amount=g['v'],lower=g['lo'],upper=g['hi'],currency='GBP',source_ids=sorted(g['sids']),observation_ids=g['oids'],method_id='ukh_quarter_nationality_applications_actual_tariff',model_status='modeled_estimate',calculation_type='application_count_times_historical_tariff_scenario',origin_basis='nationality',period_start=f'{y}-01-01',period_end=f'{y}-12-31',period_type='calendar_year_model',period_label=f'{y}自然年模型',notes=note,parameters=params))
  for y in YEARS:
   ff=[f for f in self.flows if f['year']==y];sids=sorted({s for f in ff for s in f['source_ids']})
   self.ranges.append(dict(receiver='GBR',year=y,amount=sum(f['amount'] for f in ff),lower=sum(f['lower'] for f in ff),upper=sum(f['upper'] for f in ff),currency='GBP',range_method='共同访客期限/季度收费日、短期学习六或十一月情景；旧Student路径代理映射范围，不是统计置信区间'))
   self.models.append(dict(model_id=f'ukh_uk_{y}',destination='GBR',year=y,source_ids=sids,quality='真实国籍季度申请×当期法规费率；期限与中国优惠资格、旧路径映射显式估算',included_visa_groups=['visitor','study'],missing='工作、家庭和其他类别；实际期限、免收退款和IHS/附加服务费；旧Student映射仅代理',parameters=dict(visitor_long_share_center=.1,visitor_long_share_range=[0,.25],short_study_11month_share_center=.5,short_study_11month_share_range=[0,1],china_scheme_eligible_share_center=.5,quantity='application events, not unique people')))
   self.cover.append(dict(receiver='GBR',destination='GBR',year=y,issuing_receiver_count=1,applications=sum(totals[y,g] for g in ['Visitor','Study']),included_groups={g:totals[y,g] for g in ['Visitor','Study']},excluded_groups={g:n for (yy,g),n in excluded.items() if yy==y},study_subtypes={s:n for (yy,s),n in subtypes.items() if yy==y and s!='Visitor'},coverage_status='partial_visa_types',source_ids=sids,scope='访客和学习；国籍与季度实际申请，工作/家庭/其他路径未计入',notes='各数量均为申请事件；旧Student中心采用Tier4代理，非全签种实收总额'))
   for group in ['Visitor','Study']:
    value=sum(f['quantity'] for f in ff if f['visa_group']==group.lower());self.check(f'quantity_reconciliation_{y}_{group}',value==totals[y,group]==CONTROLS[y][group],source_total=totals[y,group],flow_total=value,recorded_source_control=CONTROLS[y][group])
 def exchange(self):
  registry={s['source_id']:s for pkg in ['history','time_space'] for s in read(ROOT/f'data/research/{pkg}/sources.json')};ids=set()
  for pkg in ['time_space','history']:
   for row in read(ROOT/f'data/research/{pkg}/fx.json'):
    if row['currency']=='GBP' and row['year'] in YEARS:self.fx.append(row);ids.add(row['source_id'])
  for sid in sorted(ids):
   self.sources.append(registry[sid]);self.check('fx_source_hash_'+sid,hashlib.sha256((ROOT/registry[sid]['local_path']).read_bytes()).hexdigest()==registry[sid]['sha256'])
  self.check('fx_complete_historical_years',{r['year'] for r in self.fx}==set(YEARS) and len(self.fx)==6)
 def validate(self):
  sids={s['source_id'] for s in self.sources};oids={o['observation_id'] for o in self.obs}
  self.check('unique_ids',len(sids)==len(self.sources) and len(oids)==len(self.obs) and len({f['id'] for f in self.flows})==len(self.flows))
  self.check('flow_bounds_nonnegative_and_references',all(0<=f['lower']<=f['amount']<=f['upper'] and set(f['source_ids'])<=sids and set(f['observation_ids'])<=oids for f in self.flows))
  self.check('rule_sources_resolve',all(set(r['source_ids'])<=sids for r in self.rules))
  self.check('observation_allocation_once',len([oid for f in self.flows for oid in f['observation_ids']])==len({oid for f in self.flows for oid in f['observation_ids']}))
  self.check('positive_observations_all_used',{o['observation_id'] for o in self.obs if o['value']>0}=={oid for f in self.flows for oid in f['observation_ids']})
  self.check('area_nationality_display',all(o['nationality']=={'HKG':'中国香港','MAC':'中国澳门','TWN':'中国台湾'}[o['payer']] for o in self.obs if o['payer'] in {'HKG','MAC','TWN'}))
  self.check('no_existing_receiver_year_overlap',not any(f['receiver']=='GBR' and f['year'] in YEARS for p in (ROOT/'data/estimates').glob('*_flows.json') if p!=EST for f in read(p).get('flows',[])))
  for r in self.ranges:
   ff=[f for f in self.flows if f['year']==r['year']];self.check('annual_amount_reconcile_'+str(r['year']),all(math.isclose(sum(f[k] for f in ff),r[k],abs_tol=.00001) for k in ['amount','lower','upper']))
  # Specific regression checks catch using visitor tariffs for six-month study and incorrect commencement timing.
  self.check('2016_short_study_distinct_from_visitor',self.unit_prices(2016,2,'Study','Short-term study (previously Student Visitor)','IND')['lower']==89 and self.unit_prices(2016,2,'Visitor','Visitor','IND')['lower']==87)
  self.check('2017_short_study_distinct_from_visitor',self.unit_prices(2017,3,'Study','Short-term study (previously Student Visitor)','IND')['lower']==93 and self.unit_prices(2017,3,'Visitor','Visitor','IND')['lower']==89)
  self.check('2016_q1_tariff_change_segments',[s['days'] for s in self.unit_prices(2016,1,'Study','Tier 4 - General Student','IND')['segments']]==[77,14])
  self.check('china_scheme_not_backcast',self.unit_prices(2015,4,'Visitor','Visitor','CHN')['center']==self.unit_prices(2015,4,'Visitor','Visitor','IND')['center'])
  self.check('china_scheme_partial_qualification',self.unit_prices(2016,2,'Visitor','Visitor','CHN')['center']<self.unit_prices(2016,2,'Visitor','Visitor','IND')['center'] and self.unit_prices(2016,2,'Visitor','Visitor','CHN')['center']>87)
 def write(self):
  for n,obj in [('sources',self.sources),('observations',self.obs),('fee_rules',self.rules),('fx',self.fx),('coverage',self.cover),('checks',self.checks)]:dump(OUT/f'{n}.json',obj)
  dump(EST,dict(flows=self.flows,models=self.models,destination_ranges=self.ranges))
  annual=[dict(year=r['year'],applications=next(c['applications'] for c in self.cover if c['year']==r['year']),amount_GBP=r['amount'],lower_GBP=r['lower'],upper_GBP=r['upper']) for r in self.ranges]
  report=['# 英国2013–2018历史国籍申请与费率扩展','',f'{len(self.flows):,}条流，{len(self.obs):,}条季度原始数量观察，{len(self.sources)}个官方来源，{len(self.checks)}项检查通过。','',
   '新增六年访客和学习申请事件，按原表国籍/季度/主附申请保留来源行。数量不是独立申请人数；工作、家庭和其他类别的排除数量见coverage.json。',
   '', '2013–2015、2017–2018收费4月6日变更；2016为3月18日。2013年第一季度使用2012原法规。2016/2017短期学习六个月费为£89/£93，分别区别于访客£87/£89。2012/2013六个月学生访客按当期普通短期访客费映射，11个月英语课程按独立收费条目。',
   '', '访客期限中心90%六个月，10%等分两/五/十年；低全六个月，高75%六个月+25%十年。2016-01-11中国两年方案先£85，2016-03-18起随年度短访客费变更。法规要求中国籍、在中国内地申请并满足资格；国籍统计未包含申请地。中心对两年部分假设50%符合方案，敏感性0–100%；五/十年保持普通费。',
   '', '短期学习六与十一月未细分：中心各半、上下界各取一种期限。原表旧Student路径共764次申请，无法唯一匹配法规项目，中心用Tier4代理、范围0至Tier4并逐流标记推断。该范围是映射敏感性，不表示实际免收或统计置信区间。',
   '', '季度中心按日均匀分布；端点允许当季度全部申请发生于可行的低/高费率日期。没有把年度总数直接乘年末费率。金额为政府申请费场景；IHS、优先服务、单独生物识别与外包服务不计入。',
   '', '中国香港、中国澳门、中国台湾统一作为中文展示名，nationality_raw仅保留原始证据标签。汇率复用已归档美联储逐年英镑/美元年均值；源文件和SHA-256在sources.json。',
   '', '| 年 | 申请事件 | 中心GBP | 低GBP | 高GBP |','|---|---:|---:|---:|---:|']
  report += [f"| {a['year']} | {a['applications']:,} | {a['amount_GBP']:,.2f} | {a['lower_GBP']:,.2f} | {a['upper_GBP']:,.2f} |" for a in annual]
  report += ['', '重建：`.research-venv/bin/python scripts/research_uk_history_v2.py`。原文关键页提取附于本目录。', '', '源清单纠正：旧downloads_extra.json将fees2013cost.pdf写作SI2013/807，原文件首页为SI2013/617。本包source URL按真实617登记；不改写原始文件。']
  (OUT/'README.md').write_text('\n'.join(report)+'\n')
  print(json.dumps(dict(flows=len(self.flows),models=len(self.models),observations=len(self.obs),sources=len(self.sources),fee_rules=len(self.rules),fx=len(self.fx),checks=len(self.checks),checks_passed=all(c['passed'] for c in self.checks),annual=annual),ensure_ascii=False))


def main():
 logging.disable(logging.WARNING);warnings.filterwarnings('ignore',message='Cannot parse header or footer')
 OUT.mkdir(parents=True,exist_ok=True)
 r=Research();r.archive();r.fee_rules();r.applications();r.exchange();r.validate();r.write()

if __name__=='__main__':main()
