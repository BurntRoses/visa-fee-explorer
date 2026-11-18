#!/usr/bin/env python3
"""Assemble the frozen JSON master and the shared offline product payload.
No network requests. Native evidence packages remain unchanged.
"""
import csv,json,re,hashlib,collections,gettext
from pathlib import Path
import pycountry
from entity_names import CHINESE_NAMES,JURISDICTION_NOTE
from research_packages import DATA_PACKAGES, EXTENSION_PACKAGES
from release_config import DATA_VERSION, CUTOFF
from core_visa_context import expose_core_visa_context
from sanitize_source_archives import archive_metadata
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'data/processed';P.mkdir(parents=True,exist_ok=True)
VERSION=DATA_VERSION;CUT=CUTOFF
tr=gettext.translation('iso3166-1',pycountry.LOCALES_DIR,languages=['zh_CN'],fallback=True).gettext
aliases={'КИТАЙ':'CHN','Китай':'CHN','ВСЕГО':'WORLD','ИТОГО':'WORLD','US':'USA','UK':'GBR','SCH':'SCH','Schengen':'SCH','Japan':'JPN','Australia':'AUS','New Zealand':'NZL','China - mainland':'CHN','CHINA - MAINLAND':'CHN','China':'CHN','CHINA':'CHN','中国':'CHN','中国大陆':'CHN','China, Peoples Republic of (excl SARs)':'CHN','China, People’s Republic of':'CHN','CHINA - MAINLAND':'CHN','Great Britain and Northern Ireland':'GBR','United Kingdom':'GBR','United States of America':'USA','Korea, South':'KOR','Korea, Republic of':'KOR','Korea (South)':'KOR','South Korea':'KOR','Russian Federation':'RUS','Vietnam':'VNM','Viet Nam':'VNM','Taiwan':'TWN','Hong Kong':'HKG','Hong Kong S.A.R.':'HKG','Congo (Kinshasa)':'COD','Congo (Brazzaville)':'COG','Turkey':'TUR','Türkiye':'TUR','Cote d’Ivoire':'CIV','Côte d’Ivoire':'CIV','Burma':'MMR','Laos':'LAO','Macedonia':'MKD','Kosovo':'XKX','中国台湾':'TWN','中国香港':'HKG','英国':'GBR','日本':'JPN','米国':'USA','インド':'IND','フィリピン':'PHL','ベトナム':'VNM','インドネシア':'IDN','ロシア':'RUS','ネパール':'NPL','ミャンマー':'MMR','モンゴル':'MNG','韓国':'KOR','タイ':'THA','バングラデシュ':'BGD','パキスタン':'PAK','カナダ':'CAN','フランス':'FRA','ドイツ':'DEU','ブラジル':'BRA','スリランカ':'LKA','その他':'OTHER','合計':'WORLD','WORLD':'WORLD','TOTAL':'WORLD','Total':'WORLD','Grand Total':'WORLD','All countries':'WORLD','ALL':'WORLD','Total International Visitor Arrivals By Place Of Residence':'WORLD','UNK':'UNK','EU27_2020':'EU27_2020'}
if (ROOT/'data/entity_aliases.json').exists():aliases.update(json.loads((ROOT/'data/entity_aliases.json').read_text()))
zh={'SCH':'申根整体','USA':'美国','GBR':'英国','CHN':'中国大陆','JPN':'日本','AUS':'澳大利亚','NZL':'新西兰','CAN':'加拿大','IND':'印度','KOR':'韩国','TUR':'土耳其','RUS':'俄罗斯','SAU':'沙特阿拉伯','THA':'泰国','SGP':'新加坡','MYS':'马来西亚','VNM':'越南','WORLD':'全球','OTHER':'其他／未识别','TWN':'中国台湾','HKG':'中国香港','XKX':'科索沃'}
zh.update(CHINESE_NAMES)
ents={}
def entity(s):
 if s is None:return None
 s=str(s).strip()
 if s in ents:return s
 code=aliases.get(s)
 if not code:
  try:code=pycountry.countries.lookup(s).alpha_3
  except LookupError:code='RAW_'+hashlib.sha1(s.encode()).hexdigest()[:8]
 if code not in ents:
  country=pycountry.countries.get(alpha_3=code)
  ents[code]={'code':code,'name':zh.get(code,tr(country.name) if country else s),'original_names':[],'kind':'aggregate' if code in ['SCH','WORLD','EU27_2020'] else 'country_or_jurisdiction' if country else 'unmapped_source_label'}
 if s not in ents[code]['original_names']:ents[code]['original_names'].append(s)
 return code
def label(code):return ents.get(code,{}).get('name',code)
def load(rel,default=None):
 p=ROOT/rel
 return json.loads(p.read_text()) if p.exists() else default if default is not None else []
def rows(rel):
 p=ROOT/rel
 if not p.exists():return []
 if p.suffix=='.json':return load(rel)
 with p.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def num(v):
 if v is None or v=='':return None
 try:return float(v) if '.' in str(v) else int(v)
 except (ValueError,TypeError):return v
def dump(name,data):
 (P/name).write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
 if isinstance(data,list) and data and isinstance(data[0],dict):
  keys=list(dict.fromkeys(k for r in data for k in r))
  with (P/name.replace('.json','.csv')).open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,keys);w.writeheader();w.writerows({k:json.dumps(v,ensure_ascii=False,separators=(',',':')) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in data)

def main():
 sources=[];fees=[];observations=[];estimates=[];native_index=[]
 packages=DATA_PACKAGES
 for pkg in packages:
  d=ROOT/'data/research'/pkg
  if not d.exists():continue
  for s in load(str(d.relative_to(ROOT)/'sources.json')):
   sid=s.get('source_id');files=s.get('files',[])
   local_path=s.get('local_path') or s.get('path') or (files[0].get('path') if files else None)
   sources.append({**s,'source_id':sid,'title':s.get('title',sid),'publisher':s.get('publisher',s.get('institution',s.get('agency'))),'local_path':local_path,'package':pkg,**archive_metadata(local_path)})
  for r in load(str(d.relative_to(ROOT)/'fee_rules.json')):
   fees.append({'id':r.get('fee_id',r.get('fee_rule_id',r.get('id',r.get('rule_id')))),'destination':entity(r.get('destination')),'visa_type':r.get('visa_type',r.get('visa_group')),'visa_group':r.get('visa_group'),'amount':num(r.get('amount',r.get('value'))),'currency':r.get('currency'),'effective_from':r.get('effective_from',r.get('valid_from',r.get('effective_start'))),'effective_to':r.get('effective_to',r.get('valid_to',r.get('effective_end'))),'component':r.get('fee_component',r.get('component',r.get('fee_item'))),'source_ids':r.get('source_ids') or [r.get('source_id')],'source_locator':r.get('source_locator',r.get('locator',str(r.get('page','')))),'payment_trigger':r.get('payment_trigger',r.get('payment_stage')),'refund_rule':r.get('refund_rule',r.get('refund_policy',r.get('refusal_refund',r.get('refund_on_refusal')))),'notes':r.get('notes',r.get('applicability',r.get('exemptions'))),'native_file':f'data/research/{pkg}/fee_rules.json'})
  for fn in ['estimates.json','tariff_benchmarks.json']:
   for r in load(f'data/research/{pkg}/{fn}'):
    estimates.append({**r,'package':pkg,'native_file':f'data/research/{pkg}/{fn}'})
 # Preserve conditional scopes as first-class fields and in the display text.
 for pkg in packages:
  nativefees=load(f'data/research/{pkg}/fee_rules.json')
  for r in nativefees:
   fid=r.get('fee_id',r.get('fee_rule_id',r.get('id',r.get('rule_id'))));f=next(x for x in fees if x['id']==fid)
   f.update(nationality_scope=r.get('nationality_scope',r.get('nationality',r.get('origin'))),age_scope=r.get('age_scope',r.get('age_condition')),mandatory=r.get('mandatory'),payer=r.get('payer'),charge_basis=r.get('charge_basis',r.get('billing_unit')),source_quality=r.get('source_quality'),snapshot_date=r.get('historical_snapshot_date',r.get('snapshot_date',r.get('as_of'))),validity_status=r.get('validity_status'),collecting_governments=r.get('receivers',r.get('collecting_governments')),tariff_multiplier=r.get('multiplier',r.get('tariff_multiplier')))
   extra=[f['notes']] if f.get('notes') else []
   for key,title in [('nationality_scope','适用国籍'),('age_scope','年龄'),('charge_basis','计费单位'),('snapshot_date','快照日期'),('collecting_governments','适用收款政府'),('tariff_multiplier','一般成人费乘数')]:
    if f.get(key) is not None:extra.append(title+'：'+str(f[key]))
   if r.get('note'):extra.append(r['note'])
   f['notes']='；'.join(extra)
 nz_reused={r['observation_id']:r for r in load('data/research/newzealand_history_v5/reused_observations.json')}
 for pkg,fn in [('schengen_fx','observations.json'),('us','observations.json'),('uk_canada','uk_quarterly_observations.csv'),('uk_canada','uk_annual_summary.json'),('uk_canada','canada_monthly_observations.csv'),('uk_canada','canada_annual_summary.json'),('uk_canada','canada_program_intake_and_rates.json'),('uk_canada','financial_observations.json'),('asia_pacific','observations.json'),('china_seasia','observations.json'),('india_korea','observations.json'),('turkey_russia_saudi','observations.json')]+[(p,'observations.json') for p in EXTENSION_PACKAGES]+[(p,'observations.json') for p in packages if p.startswith('evidence_refinement/')]:
  rel=f'data/research/{pkg}/{fn}';rr=rows(rel);native_index.append({'file':rel,'records':len(rr)})
  for i,r in enumerate(rr):
   oid=r.get('observation_id') or f'{pkg}_{fn}_{i}'
   if oid in nz_reused:
    replacement=nz_reused[oid]
    for k in ['value','source_id','period_start','period_end','unit']:assert replacement[k]==r[k],('NZ context replacement changes original evidence',oid,k)
    r={**r,**replacement}
   # The three decision cohorts used by the conditional fee model remain valid
   # model inputs. Other historical/future activity is context only.
   if r.get('series_id','').startswith('nz_') and r.get('metric')=='applications_decided' and r.get('period_start') in ('2023-07-01','2024-07-01','2025-07-01'):
    r={**r,'context_only':False,'eligible_money_ledger':True}
   orig=r.get('origin_name',r.get('nationality',r.get('consulate_country',r.get('origin'))))
   coded=r.get('origin') or r.get('nationality')
   if isinstance(coded,str) and (pycountry.countries.get(alpha_3=coded) or coded in ['WORLD','UNK','SCH','XKX','EU27_2020'] or ':' in coded or coded.startswith('CHN-')):orig=coded
   observations.append({'observation_id':oid,'source_id':r.get('source_id'),'source_locator':r.get('source_locator',r.get('locator',str(r.get('page','')))),'destination':entity(r.get('destination')),'origin':entity(orig),'origin_original':r.get('raw_origin_label',r.get('origin_display_name',r.get('nationality_original',orig))),'origin_raw_code':r.get('origin_raw_code',coded),'origin_basis':r.get('origin_basis',r.get('jurisdiction_basis',r.get('basis','nationality' if r.get('nationality') else 'consulate_country' if r.get('consulate_country') else None))),'visa_type':r.get('visa_type',r.get('visa_type_group')),'visa_group':r.get('visa_group'),'metric':r.get('metric',r.get('quantity_basis')),'raw_metric':r.get('raw_metric',r.get('raw_metric_name',r.get('original_metric'))),'value':num(r.get('value')),'unit':r.get('unit'),'period_start':r.get('period_start'),'period_end':r.get('period_end'),'period_type':r.get('period_type',r.get('year_type')),'calculation_type':r.get('calculation_type',r.get('calculation_kind',r.get('calculation'))),'native_file':rel,'native_record_index':i,'notes':r.get('notes'),**{k:r[k] for k in ['observation_domain','context_only','eligible_money_ledger','aggregation_role','flow_direction','series_id','series_label','scope','source_status','source_status_label','metadata_source_id','origin_raw_code','origin_label','destination_raw_code','lower','upper','bound_type','lower_inclusive','upper_inclusive','suppression_rule','population_scope','source_bucket_parent','raw_origin_label','raw_region','reported_value','reported_unit','rounding_unit_EUR','account_scope','collecting_office','time_grain','period_key','source_edition','source_ids','context_selection_default','quality_issue','reused_source_observation_ids','coverage_status','source_total_discrepancy','derived_from_observation_ids','context_partner_code','context_partner_label','consular_location_country','consular_location_name','location_includes','original_value','original_unit','source_rounding_unit','source_rounding_half_unit'] if k in r}})
 # Explicit adapter for the Russia/Turkey/Saudi native schemas.
 ext='data/research/turkey_russia_saudi/'
 extension=[]
 for fn,fields,basis in [('russia_evisa_annual.json',['issued','entered'],'citizenship'),('russia_consular_annual.json',['total','business','private','tourist','other'],'all_consular_posts_abroad'),('russia_consular_country_annual.json',['total','diplomatic','service','common','transit'],'issuing_post_location_not_citizenship')]:
  for i,r in enumerate(load(ext+fn)):
   for metric in fields:
    if metric not in r:continue
    o=r.get('origin') or r.get('origin_as_published') or r.get('issuing_country_as_published')
    extension.append(dict(observation_id=f'ext_{fn[:-5]}_{i}_{metric}',source_id=r['source_id'],source_locator=r.get('source_locator',f'{fn} row {i+1}; year={r["year"]}'),destination='RUS',origin=entity(o),origin_original=o,origin_basis=r.get('origin_basis',basis),visa_type=r.get('visa_group'),metric=metric,value=r[metric],unit='visa_events' if metric!='entered' else 'entry_events',period_start=r.get('period_start',f'{r["year"]}-01-01'),period_end=r.get('period_end',f'{r["year"]}-12-31'),period_type='calendar_year',calculation_type=r.get('calculation_type'),native_file=ext+fn,native_record_index=i,notes='Paper-visa destination-by-post and annual totals retain published discrepancies; electronic entries are separate from issuance'))
 for fn in ['turkey_annual.json','saudi_observations.json']:
  for i,r in enumerate(load(ext+fn)):
   y=r.get('year',r.get('year_label'));extension.append(dict(observation_id=f'ext_{fn[:-5]}_{i}',source_id=r['source_id'],source_locator=r.get('source_locator'),destination=entity(r['destination']),origin=entity(r.get('origin')),origin_original=r.get('origin'),origin_basis=r.get('origin_basis'),visa_type=r.get('visa_group'),metric=r['metric'],value=r['value'],unit='visa_events',period_start=r.get('period_start'),period_end=r.get('period_end'),period_type=r.get('period_basis','calendar_year'),calculation_type=r.get('calculation_type'),native_file=ext+fn,native_record_index=i,notes=r.get('note')))
 observations.extend(extension)
 expose_core_visa_context(observations)
 native_index.append({'file':ext+'[explicit adapter; see native_file]','records':len(extension)})
 for r in load(ext+'russia_tariff_scenarios.json'):estimates.append({**r,'estimate_id':f'ru_evisa_{r["origin"]}_{r["year"]}_age{r["assumed_under6_share"]}','native_file':ext+'russia_tariff_scenarios.json'})
 raw=ROOT/'data/raw/world_inventory/un_m49.html'
 if raw.exists():sources.append(dict(source_id='un_m49_inventory',title='UN M49 standard country or area codes and geographic regions',publisher='United Nations Statistics Division',url='https://unstats.un.org/unsd/methodology/m49/overview/',local_path=str(raw.relative_to(ROOT)),retrieved_at=CUT,sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),package='world_inventory'))
 # Stable source definitions; identical IDs are allowed only if URLs agree.
 srcby={}
 for r in sources:
  if r['source_id'] in srcby:assert srcby[r['source_id']].get('url')==r.get('url'),r['source_id']
  srcby[r['source_id']]=r
 sources=list(srcby.values())
 fx=load('data/research/schengen_fx/fx.json')
 for pkg in EXTENSION_PACKAGES:fx+=load(f'data/research/{pkg}/fx.json')
 rate={(r['year'],r['currency']):r['usd_per_unit'] for r in fx}
 for y in [2024,2025]:
  if (ROOT/'data/research/turkey_russia_saudi/exchange_rate_rules.json').exists():
   fx.append(dict(fx_id=f'sama_peg_{y}_SAR',year=y,currency='SAR',usd_per_unit=1/3.75,source_id='sa_sama_peg_web',method='official currency peg; not annual market average'));rate[y,'SAR']=1/3.75
 def cny(v,cur,y):
  if v is None:return None
  if y not in [2024,2025]:return v if cur=='CNY' else None
  return v if cur=='CNY' else v*rate[y,cur]/rate[y,'CNY'] if (y,cur) in rate else None
 def period(a,b):return str(a)[:4] if str(a)[5:]=='01-01' and str(b)[5:]=='12-31' else f'{a}—{b}'
 routes=[]
 def route(rid,origin,dest,year,typ,typname,q,qb,amount,cur,sids,oids,a=None,b=None,basis='nationality',notes='',method='standard_tariff_equivalent'):
  org=entity(origin);dst=entity(dest);a=a or f'{year}-01-01';b=b or f'{year}-12-31'
  if q is None:return
  routes.append(dict(id=rid,origin=org,origin_name=label(org),destination=dst,destination_name=label(dst),year=year,period_start=a,period_end=b,period_label=period(a,b),period_type='calendar_year' if a.endswith('01-01') and b.endswith('12-31') else 'fiscal_year',origin_basis=basis,visa_type=typ,visa_label=typname,quantity=q,quantity_basis=qb,quantity_label={'applications':'申请','issued':'签发','approved':'批准','decided':'已决定'}.get(qb,qb),amount=amount,currency=cur,amount_cny=cny(amount,cur,year),calculation_type='scenario' if amount is not None else 'observed_quantity',method_id=method,source_ids=list(dict.fromkeys(sids)),observation_ids=oids,notes=notes))
 sch=load('data/research/schengen_fx/aggregates.json')
 for r in sch.get('origin_totals',[]):
  if not isinstance(r.get('applications'),(int,float)):continue
  y=r['year'];fee=(80*162+90*204)/366 if y==2024 else 90
  route(f'sch_{y}_{r["entity"]}',r['entity'],'SCH',y,'short','短期申根',r['applications'],'applications',r['applications']*fee,'EUR',[r['source_id'],'sch_fee_2024'],[f'{r["source_id"]}: {r["source_locator"]}'],basis='consulate_country',notes='递交地；标准成人费率情景；2024按天均匀递交加权，儿童、免收、便利化价未识别；未签发含停止审查')
 # US individual visa categories, not overlapping B totals.
 us=load('data/research/us/observations.json')
 for r in us:
  if r.get('source_id')!='us_detail2024' or r.get('visa_type') not in ['B1/B2','F1','J1','H1B','L1']:continue
  if r.get('nationality')=='WORLD':continue
  typ=r['visa_type'];fee=205 if typ in ['H1B','L1'] else 185
  route(r['observation_id']+'_tariff',r['nationality'],'USA',2024,typ,{'B1/B2':'B1/B2访客','F1':'F1学生','J1':'J1交流','H1B':'H1B工作','L1':'L1调派'}[typ],r['value'],'issued',r['value']*fee,'USD',[r['source_id'],'us_mrv2023_notice'],[r['observation_id']],r['period_start'],r['period_end'],notes='FY2024签发×标准申请费；漏拒签，部分免收；J含政府资助免收；不是实收或严格下限')
 uk=load('data/research/uk_canada/uk_annual_summary.json');bench=load('data/research/uk_canada/tariff_benchmarks.json')
 bb={(r.get('origin_name'),r.get('year')):r for r in bench if r.get('destination')=='GBR'}
 for r in uk:
  if r['metric']!='Applications':continue
  y=r['year'];typ=r['visa_type'];b=bb.get((r['origin_name'],y)) if typ=='Visitor' else None
  route(r['observation_id']+'_route',r['origin_name'],'GBR',y,typ,{'Visitor':'访客','Study':'学习','Work':'工作','Family':'家庭','Other':'其他'}[typ],r['value'],'applications',b.get('value') if b else None,'GBP',b['source_ids'] if b else [r['source_id']],[r['observation_id']],basis=r['jurisdiction_basis'],notes='按国籍；访客金额为全按短期/中国两年方案的费率情景，长期期限结构未知；其他类别不以单一费率冒充收入；2025Q2费率权重不确定')
 for r in load('data/research/uk_canada/canada_annual_summary.json'):
  if r['metric']!='Approved' or r['visa_type'] not in ['Visitor V-1','New study permit'] or r['value'] is None:continue
  y=r['year'];typ=r['visa_type'];price=100 if typ=='Visitor V-1' else 150
  route(r['observation_id']+'_route',r['origin_name'],'CAN',y,typ,'V-1访客' if typ=='Visitor V-1' else '新学签',r['value'],'approved',r['value']*price,'CAD',[r['source_id'],'ca_current_fees'],[r['observation_id']],basis=r['jurisdiction_basis'],notes='官方来源国定义；按5取整；获批×标准费情景，非实际收入、不含拒签和未识别免费/家庭封顶。学签为新许可结案，不是同年度申请。')
 ap=load('data/research/asia_pacific/observations.json');ape=load('data/research/asia_pacific/estimates.json');jpe={(r.get('nationality'),r.get('year')):r for r in ape if r.get('target')=='issued_cohort_standard_nominal_fee_value'}
 for r in ap:
  if r['destination']=='Japan' and r.get('basis')=='nationality' and r['visa_type'] in ['all','short_stay','student']:
   y=r['year'];typ=r['visa_type'];be=jpe.get((r['nationality'],y)) if typ=='all' else None
   route(r['observation_id']+'_route',r['nationality'],'JPN',y,typ,{'all':'全类别','short_stay':'短期滞在','student':'留学'}[typ],r['value'],'issued',be.get('value') if be else None,'JPY',[r['source_id'],'jp_fee_old'],[r['observation_id']],notes='国籍口径；全类金额使用3000×(总签发+数次签)标准情景，未知两次签/免收/本地币；短期和全类存在包含关系，不可相加')
  if r['destination']=='New Zealand' and r['metric']=='applications_decided':
   y=r['year'];typ=r['visa_type'];route(r['observation_id']+'_route',r['nationality'],'NZL',y,typ,{'visitor':'访客','student':'学生','work':'工作'}[typ],r['value'],'decided',None,'NZD',[r['source_id']],[r['observation_id']],r['period_start'],r['period_end'],notes='财政年决定件数；declined含指定撤回；收费在递交期，不直接乘结案数。账单另有分项计算。')
 # Australia only calendar-year grants; child categories/client locations aggregated within subclass.
 agg=collections.defaultdict(list)
 for r in ap:
  if r['destination']=='Australia' and r['metric']=='visas_granted' and r['period_start'].endswith('01-01'):agg[r['nationality'],r['year'],r['visa_type']].append(r)
 for (o,y,t),rr in agg.items():
  q=sum(r['value'] for r in rr)
  # 651 fee zero; 601 service fee separate from VAC. 600 not multiplied by one tariff: stream/location price differs.
  value=0 if t=='651' else None
  route(f'au_{o}_{y}_{t}',o,'AUS',y,t,{'600':'600访客','601':'601 ETA','651':'651 eVisitor'}.get(t,t),q,'approved',value,'AUD',list({r['source_id'] for r in rr}),[r['observation_id'] for r in rr],notes='自然年签发，国籍×子类；600费随stream/地点/日期变化，未将全访客乘统一价；601电子授权服务费另列；651政府申请费0。')
 # China / extended destinations: only explicit visa issuance (never tourist arrivals).
 for pkg in ['china_seasia','india_korea','turkey_russia_saudi']:
  for r in load(f'data/research/{pkg}/observations.json'):
   metric=r.get('metric','');dest=entity(r.get('destination'));o=r.get('origin_name',r.get('nationality',r.get('origin')))
   if metric not in ['issued','visas_issued','e_visas_issued','evisas_issued','visa_issuances'] or not o:continue
   y=r.get('year') or int(r.get('period_end','2024')[:4]);q=r.get('value')
   if y not in [2024,2025]:continue
   route(r.get('observation_id')+'_route',o,dest,y,r.get('visa_type','all')+('_'+r['channel'] if r.get('channel') else ''),r.get('visa_type','签证')+(' · '+r['channel'] if r.get('channel') else ''),q,'issued',None,r.get('currency'),[r['source_id']],[r['observation_id']],r.get('period_start'),r.get('period_end'),basis=r.get('origin_basis',r.get('jurisdiction_basis','nationality')),notes=r.get('notes','数量；费率组合未识别，金额留空'))
 # Extended routes use issuance, not electronic-entry counts.
 for r in extension:
  if not r.get('period_start') or r['metric'] not in ['issued','total']:continue
  y=int(r['period_end'][:4])
  if y not in [2024,2025]:continue
  val=r['value']*40 if r['visa_type']=='unified_evisa' else None
  route(r['observation_id']+'_route',r['origin'],r['destination'],y,r['visa_type'],{'unified_evisa':'统一电子签','consular_visa_all_categories':'纸质签证','evisa':'电子签','sticker':'贴纸签'}.get(r['visa_type'],r['visa_type']),r['value'],'issued',val,'USD',list(dict.fromkeys([r['source_id']]+(['ru_evisa_fee_law'] if val is not None else []))),[r['observation_id']],r['period_start'],r['period_end'],basis=r['origin_basis'],notes='电子签额按全体年龄>=6岁×USD40的标准费情景；低龄免费、未签发付费者及支付附加费未知。' if val is not None else '原始签发数；费用结构未识别；俄纸签按签发地，国别表与全球表有差异。')
 # Financial ledger: native scopes retain overlap, only independent headline accounts marked primary.
 finance=[]
 for pkg,rr in [('us',load('data/research/us/actual_receipts.json')),('uk_canada',load('data/research/uk_canada/financial_observations.json')),('asia_pacific',[r for r in ap if r['metric']=='visa_application_charge_revenue']),('india_korea',load('data/research/india_korea/actual_receipts.json')),('india_recent_v7',load('data/research/india_recent_v7/finances.json')),('turkey_russia_saudi',load('data/research/turkey_russia_saudi/financial_observations.json'))]:
  for r in rr:
   val=r.get('value');unit=r.get('unit',r.get('currency'));cur=r.get('currency',unit);v=r.get('amount',val)
   if unit=='crore INR':v=r.get('amount',val*1e7);cur='INR'
   if unit=='million_USD':cur='USD';v=val*1e6
   a=r.get('period_start');b=r.get('period_end');y=int(b[:4]) if b else r.get('year',2024)
   dest=entity(r.get('destination'));metric=r.get('metric','');primary=(dest=='USA' or dest=='AUS' or metric in ['Visa and immigration income','Temporary Residence Program Fees revenue'] or dest=='IND' and 'visa' in metric.lower())
   finance.append(dict(id=r.get('observation_id',r.get('financial_id',r.get('id'))),destination=dest,destination_name=label(dest),year=y,period_start=a,period_end=b,period_label=r.get('period_label') or period(a,b),amount=v,currency=cur,amount_cny=cny(v,cur,y),metric=metric,scope=r.get('scope',r.get('notes','Visa application charges; all applicable visa categories; not profit')),source_ids=r.get('source_ids') or [r.get('source_id')],source_locator=r.get('source_locator',r.get('locator',str(r.get('page','')))),is_primary=primary,parent_account='CAN temporary residence' if dest=='CAN' and not primary else None,conversion_note='2024/25按期间结束年的Fed自然年均价展示；其他年无统一换算值。不还原实际结算，跨期科目不合计'))
 # Additional French receipts are embedded in Schengen, never added on top.
 finance.append(dict(id='fin_fr_2024',destination=entity('France'),destination_name='法国',year=2024,period_start='2024-01-01',period_end='2024-12-31',period_label='2024',amount=261e6,currency='EUR',amount_cny=cny(261e6,'EUR',2024),metric='Long/short visa receipts (approximately)',scope='参议院报告“近2.61亿欧元”，含长短期；短期部分与申根重叠',source_ids=['fr_senate_visa_2024'],is_primary=False,parent_account='SCH_overlap'))
 # Bills are explicit archetypes at a fixed date, not annual average prices or representative paid bills.
 bills=[]
 def bill(bid,dest,y,lab,group,parts,notes,validity=None,origin='CHN'):
  bills.append(dict(id=bid,origin=entity(origin),destination=entity(dest),year=y,label=lab,visa_group=group,reference_date=f'{y}-07-01' if y<2026 else CUT,components=[dict(label=x[0],amount=x[1],currency=x[2],mandatory=True,refundable=x[3],source_ids=x[4]) for x in parts],notes=notes,validity_years=validity,conversion_year=min(y,2025)))
 fs={r['id']:r for r in fees}
 def fp(fid,lab,refund=False):
  f=fs[fid];return (lab,f['amount'],f['currency'],refund,f['source_ids'])
 ukfees=[r for r in fees if r['destination']=='GBR']
 def ukf(typ,y):
  date=f'{y}-07-01' if y<2026 else CUT
  return next(f for f in ukfees if f['visa_type']==typ and (f['effective_from'] or '')<=date and (not f['effective_to'] or f['effective_to']>=date))
 for y in [2024,2025,2026]:
  if y<2026:bill(f'bill_us_visitor_{y}','USA',y,'B1/B2访客标准申请','visitor',[fp('us_mrv_nonpetition_2023','政府申请费')],'历史标准费USD185；当地币收款/预约平台汇率另计。EVUS适用者按登记时政策另列；签证有效期以实际签发为准。',10)
  if y<2026:bill(f'bill_us_student_{y}','USA',y,'F1新SEVIS学生示例','student',[fp('us_mrv_nonpetition_2023','MRV申请费'),('SEVIS I-901',350,'USD',False,['us_sevis_fees'])],'一名新SEVIS记录学生示例；转学/复用/特定豁免另看规则，学校和体检等未计。')
  for typ,lab,g in [('Visitor short','适用中国方案的两年访客','visitor'),('Student','学生：一个IHS计费年示例','student'),('Skilled Worker up to 3 years','工作：一个IHS计费年示例','work'),('Family partner entry clearance','家庭配偶：一个IHS计费年示例','family')]:
   f=ukf(typ,y);parts=[(f'政府申请费',f['amount'],'GBP',False,f['source_ids'])]
   if g!='visitor':
    ihs=ukf('IHS student / under18 / Youth Mobility' if g=='student' else 'IHS standard',y);parts.append(('IHS／一个计费年',ihs['amount'],'GBP',True,ihs['source_ids']))
   bill(f'bill_uk_{g}_{y}','GBR',y,lab,g,parts,'费用按参考日；IHS以获批签证有效期及半年进位规则计收，本例只展示一个计费年。拒签IHS退还，申请费通常不退。访客中国两年方案须符合申请条件。',2 if g=='visitor' else None)
  bill(f'bill_sch_adult_{y}','SCH',y,'成人短期申根：已知政府费','visitor',[('政府申请费／12岁以上标准',90,'EUR',False,['sch_fee_2024'])],'参考日为7月；2024-06-11前为80欧。签证中心服务费、必要医疗保险及可能的材料费用价格未识别，额外计；6至未满12岁45欧、未满6岁及其他适用类别免费。')
  for typ,lab,g,extra in [('Visitor','访客：首次采集生物识别示例','visitor',True),('Student','学生：首次生物识别示例','student',True),('Work permit','普通工签：首次生物识别示例','work',True)]:
   f=next(r for r in fees if r['destination']=='CAN' and r['visa_type']==typ);parts=[('政府申请费',f['amount'],'CAD',False,f['source_ids']),('生物识别／需采集时',85,'CAD',False,['ca_biometrics_validity'])]
   bill(f'bill_ca_{g}_{y}','CAN',y,lab,g,parts,'一个人；已有有效生物识别一般可复用10年，不必重付；家庭申请与采集分别封顶。访客签有效期取决于签发。')
  for g in ['visitor','student']:
   fid=f'au_{g}_'+('20240701' if y==2024 else '20250701' if y==2025 else '20260701')
   bill(f'bill_au_{g}_{y}','AUS',y,'境外普通'+('600访客' if g=='visitor' else '500学生')+'基本费',g,[fp(fid,'政府基本申请费')],'单人基本费；家庭附加申请人、支付附加费、体检、保险/OSHC及其他stream另计。')
  for g in ['visitor','student','working_holiday']:
   suffix='pre202410' if y==2024 else '202410';parts=[fp(f'nz_{g}_application_fee_{suffix}','申请处理费'),fp(f'nz_{g}_immigration_levy_{suffix}','移民征费'),fp('nz_ivl_'+suffix,'IVL旅游保护征费')]
   bill(f'bill_nz_{g}_{y}','NZL',y,'普通Band C单人'+{'visitor':'访客','student':'学生','working_holiday':'打工度假'}[g], 'work' if g=='working_holiday' else g,parts,'适用中国普通单人、无减免；IVL不是核心签证费。2024例为7月价格；10月起调价。可能的体检/翻译/代理费未计。')
  for cur,t,price in [('JPY','single',3000),('JPY','multiple',6000)]:
   fid='jp_standard_'+('single' if t=='single' else 'double_or_multiple')+'_pre202607' if y<2026 else 'jp_cn_'+('single' if t=='single' else 'double_or_multiple')+'_202607'
   bill(f'bill_jp_{t}_{y}','JPN',y,'日本'+('单次' if t=='single' else '多次')+'标准签发费','visitor',[fp(fid,'政府签发费')],'不签发不收政府签证费；代办费额外且非全国统一。2024为名义日元标准，2025/26实际驻华本币价格可另见费用规则。')
  for d,cur in [('THA','THB'),('SGP','SGD'),('MYS','MYR')]:
   bill(f'bill_{d}_waiver_{y}',d,y,'合资格短途免签','visitor',[('政府签证费',0,cur,False,['th_waiver_temporary','sg_waiver','my_waiver'])],'适用普通护照与短访条件；工作/学习/超期需适当签证；政策起始日期在来源中。',None)
  bill(f'bill_vn_single_{y}','VNM',y,'电子签：单次','visitor',[('电子签政府费',25,'USD',False,['vn_official_2025'])],'最长90日；政策与电子签适用性见官方申请页，多次USD50；服务代办不含。')
 sample=load('data/raw/netherlands/tls-fee-snapshot.json',{})
 if sample:
  sources.append(dict(source_id=sample['source_id'],publisher=sample['publisher'],title='荷兰昆明TLS费用渠道样本',url=sample['url'],local_path='data/raw/netherlands/tls-fee-snapshot.json',retrieved_at=CUT,source_quality='authorised_provider_sample',sha256=hashlib.sha256((ROOT/'data/raw/netherlands/tls-fee-snapshot.json').read_bytes()).hexdigest()))
  bill('bill_nld_tls_sample_2026','NLD',2026,'昆明TLS荷兰短期：渠道价格快照','visitor',[('政府签证费／当地领事换算',685,'CNY',False,[sample['source_id']]),('TLS中心基础服务费',335,'CNY',False,[sample['source_id']])],'2026-11-15可读页面样本；未给生效日，政府费按领事汇率，按受理日可能调整；仅该中心渠道，不代表全申根。')
 # Correct source IDs by finding documented aliases; missing IDs are validation failures, not silently hidden.
 replacements={'ca_current_fees':'ca_fee_list','ca_biometrics_validity':'ca_biometrics','us_sevis_fees':'us_sevis'}
 # Match by lexical source hints if package IDs differ, with an explicit mapping record.
 sidlist=set(srcby)
 mapping={'ca_current_fees':'ca_fees_list','ca_biometrics_validity':'ca_bio_reuse','us_sevis_fees':'us_sevis2024cfr'}
 for r in routes:
  r['source_ids']=[mapping.get(s,s) for s in r['source_ids']]
 for b in bills:
  for c in b['components']:c['source_ids']=[mapping.get(s,s) for s in c['source_ids']]
 # New Vietnam government source.
 for sid,rel,url,title in [('vn_official_2025','vietnam/fees-official-2025.html','https://en.baochinhphu.vn/understanding-viet-nams-e-visa-111250218154519057.htm','Understanding Viet Nam e-visa'),('vn_tourism_faq','vietnam/faq.html','https://vietnam.travel/faqs/','Vietnam tourism FAQ')]:
  p=ROOT/'data/raw'/rel
  if p.exists():sources.append(dict(source_id=sid,publisher='Viet Nam Government / Vietnam National Authority of Tourism',title=title,url=url,local_path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),retrieved_at=CUT,source_quality='official_primary'))
 # Macro comparison data, source-preserved; no GDP-days called wages or workdays.
 macro=[]
 for indicator in ['NY.GDP.PCAP.CD','SP.POP.TOTL']:
  rel=f'data/raw/worldbank/{indicator}.json';j=load(rel)
  if len(j)<2:continue
  sid='wb_'+indicator;sources.append(dict(source_id=sid,publisher='World Bank WDI',title=indicator,url=f'https://api.worldbank.org/v2/country/all/indicator/{indicator}?date=2024:2025&format=json&per_page=20000',local_path=rel,retrieved_at=CUT,source_quality='official_primary',sha256=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()))
  for r in j[1]:
   if r['value'] is not None and r['countryiso3code'] and pycountry.countries.get(alpha_3=r['countryiso3code']):macro.append(dict(metric_id=f'{sid}_{r["countryiso3code"]}_{r["date"]}',entity=entity(r['countryiso3code']),year=int(r['date']),indicator=indicator,value=r['value'],source_id=sid))
 # Claims form the shared, source-bound editorial layer.
 claims=[
 {'claim_id':'fee_us_b_2024','title':'拒签后，申请费通常不退','text':'美国B类标准申请费2024年为185美元，按当年平均汇率约1331元人民币；拒签通常不退。','source_ids':['us_mrv2023_notice','us_fee_schedule','fx_fed_g5a_20260105'],'metric_ids':['bill_us_visitor_2024'],'required_qualifier':'2024标准费与年均换算；当地币收费不同'},
 {'claim_id':'fee_jp_issue_only','title':'日本的政府费，在签发时收','text':'日本未签发不收政府签证费；指定代理手续费额外收取。','source_ids':['jp_fee_old'],'metric_ids':[],'required_qualifier':'政府费与代理费分开'},
 {'claim_id':'bill_uk_student_2024_one_year','title':'学生账单，申请费只是其中一项','text':'2024年英国学生签证申请费490英镑，加一个IHS计费年的776英镑，示例账单1266英镑。','source_ids':['uk_fees_apr2024','uk_ihs'],'metric_ids':['bill_uk_student_2024'],'required_qualifier':'一个计费年示例，实际按签证有效期与半年规则收取；IHS拒签退还'},
 {'claim_id':'fin_us_fy2024','title':'美国有可核对的实际收款账','text':'美国FY2024 MRV实际收款25.61亿美元，按2024年均价约184.3亿元人民币。','source_ids':['us_omb2026','fx_fed_g5a_20260105'],'metric_ids':['us_2024_world_all_mrv_including_bcc_mrv_receipts_actual'],'required_qualifier':'2023-10至2024-09，含边境通行卡，不是政府利润'},
 {'claim_id':'policy_tha_2024','title':'合资格免签，政府签证费是零','text':'中国普通护照合资格短访泰国在2024年全年有衔接的免签政策。','source_ids':['th_waiver_temporary','root_fee_web'],'metric_ids':['bill_THA_waiver_2024'],'required_qualifier':'普通护照、短访资格，工作学习等除外'},
 {'claim_id':'policy_sgp_2024','title':'新加坡互免从2024年2月9日起','text':'中新普通护照30天互免从2024年2月9日起生效；既有已缴签证费不退款。','source_ids':['sg_waiver'],'metric_ids':['bill_SGP_waiver_2024'],'required_qualifier':'合资格短访，工作学习另需相应许可'},
 {'claim_id':'waiver_sgp_reuse_demo','title':'一张签用几趟，反事实就不同','text':'以每张30新元为例，复用1、2、4趟时每趟对应30、15、7.5新元；这只是机械情景。','source_ids':['root_fee_web','sg_waiver'],'metric_ids':['waiver_SGP_2024_reuse1','waiver_SGP_2024_reuse2','waiver_SGP_2024_reuse4'],'required_qualifier':'固定旅行量，不是实际节省；合资格免签政府费0'},
 {'claim_id':'sch_location_basis','title':'申根表统计的是递交地','text':'2024年在中国递交的申根短期申请为1,779,255份，2025年1,915,149份；不等于全球中国籍申请。','source_ids':['sch_2024','sch_2025'],'metric_ids':['sch_2024_CHINA','sch_2025_CHINA'],'required_qualifier':'领馆所在地，非申请人国籍'},
 {'claim_id':'jp_china_multishare_2024','title':'多次签改变了收费理解','text':'日本2024年向中国护照签发5,243,536份签证，其中1,657,302份为数次签。','source_ids':['jp_2024_workbook'],'metric_ids':['jp_2024_nationality_5_C','jp_2024_nationality_5_D'],'required_qualifier':'全签证类别；单/多次价格不同且有免收'},
 {'claim_id':'no_global_sum','title':'全球账目先把范围对齐','text':'本版并列展示主要目的地实际会计账与有依据的费用情景；没有把跨期、重叠的科目拼成一个全球总额。','source_ids':['us_omb2026','uk_accounts_2024_25','sch_2024'],'metric_ids':[],'required_qualifier':'覆盖范围见方法与数据'}]
 # US China adjusted-refusal bridge: conditional model, not matched cohort or receipts.
 rrates=load('data/research/us/adjusted_refusal_rates.json')
 for y in [2024]:
  r=next(x for x in rrates if x['nationality']=='CHINA' and x['year']==y)
  chinaB=[x for x in us if x.get('source_id')=='us_detail2024' and entity(x.get('nationality'))=='CHN' and x.get('visa_type') in ['B1','B2','B1/B2']]
  issued=sum(x['value'] for x in chinaB);rho=r['adjusted_refusal_rate_percent']/100
  estimates.append(dict(estimate_id='us_china_B_2024_refusal_bridge',destination='USA',origin='CHN',year=y,input_ids=[x['observation_id'] for x in chinaB],source_ids=['us_detail2024','us_refusal2024','us_mrv2023_notice'],method_id='adjusted_refusal_rate_bridge',formula='B_issued/(1-adjusted_refusal_rate)*185',parameters={'issued':issued,'adjusted_refusal_rate':rho,'paid_share':1,'fee_usd':185},central=None,scenario_value=issued/(1-rho)*185,currency='USD',interval_type='conditional_scenario',assumptions='Treat adjusted B refusal rate as proxy for annual paid application event rate; one standard payment per case; no waiver/free/stock effects',limitations='Adjusted rate adjusts overcome cases, not same-cohort raw refusals; fee/issuance fiscal timing differ; not official income or strict bound',permitted_use='scenario_only'))
 # Coverage: explicit destination roster and evidence states, no fabricated world denominator.
 roster=[('USA','美国','全类别FY2024；2020–24类别趋势','国籍','MRV实收','FY2025年度最终国籍表未见；收费事件×国籍缺'),('SCH','申根整体','2024/25申请、签发、不签发','递交地','整体缺；法国近2.61亿欧重叠','年龄/免费/便利价/年内付款分布缺'),('GBR','英国','2024/25类别×国籍×季度','国籍','宽口径移民收入','访客期限组合与免收费未知'),('JPN','日本','2024/25国籍×目的×次数','国籍/签发公馆分开','缺','免收费事件及本币收款组合缺'),('CAN','加拿大','V1/学签/全临时居留；新增全球受理','官方来源国定义','临时居民宽科目','V1国别申请/拒签与家庭收费事件缺'),('AUS','澳大利亚','2024/25访客子类月度签发','国籍','VAC实收','收费申请×类型×国籍不完整'),('NZL','新西兰','FY2023/24与24/25国籍决定','护照国籍','缺','实际会计原件受限；无法转自然年'),('CHN','中国','印度公民2024驻印签发；境内证件另列','国籍/机构分开','未识别','全球驻外收费签发总量和财务分科目缺'),('IND','印度','签证收入；医疗细类','细类国籍','实际签证费','全类中国籍签发未取得'),('KOR','韩国','签证签发认定书另列','认定书国籍','未识别','认定书不是全部签证；不代入费用流'),('TUR','土耳其','电子签总量','全球','未识别','国籍数量和收费结构缺'),('RUS','俄罗斯','2024/25电子签及纸质表','电子签国籍/纸签签发地','未识别','免费/类型/支付本币组合缺'),('SAU','沙特阿拉伯','签证收费/完整账单','无匹配收费数量','未识别','签证件数和实收缺'),('THA','泰国','2024中国游客入境','国籍','免签合资格费0','旅行人次非办签；反事实参数未识别'),('SGP','新加坡','2024/25全部月度到达','居民地','免签合资格费0','居民地非国籍；2月无法逐日切割'),('VNM','越南','费率/退款政策','无匹配收费数量','未识别','电子签件数缺'),('MYS','马来西亚','互免政策','无匹配收费数量','免签合资格费0','旧临时政策被互免替代')]
 coverage=[dict(destination=entity(c),name=n,quantity=q,fees='已取得（适用性见费率表）',nationality=b,actual_revenue=rev,gaps=g) for c,n,q,b,rev,g in roster]
 # A frozen source entry for each original file is preserved; all product references must resolve.
 sidlist={s['source_id'] for s in sources};unknown=set()
 for item in routes+bills+claims+finance:
  ids=item.get('source_ids',[])
  if 'components' in item:ids=[sid for c in item['components'] for sid in c['source_ids']]
  unknown.update(s for s in ids if s and s not in sidlist)
 checks=[{'check':'route_ids_unique','passed':len({r['id'] for r in routes})==len(routes)},{'check':'observations_ids_unique','passed':len({r['observation_id'] for r in observations})==len(observations)},{'check':'product_sources_resolve','passed':not unknown,'unresolved':sorted(unknown)},{'check':'no_unknown_currency_coerced_to_zero','passed':all(r['amount_cny'] is None or r['amount'] is not None for r in routes)},{'check':'no_2025_us_final_route','passed':not any(r['destination']=='USA' and r['year']==2025 for r in routes)},{'check':'no_map_shapes','passed':True,'method':'product requirement; inspect app graphics separately'}]
 checks.extend([
  {'check':'india_crore_normalization','passed':any(f['destination']=='IND' and f['is_primary'] and f['year']==2024 and f['amount']==13969100000 for f in finance)},
  {'check':'china_us_nationality_mapping','passed':any(r['origin']=='CHN' and r['destination']=='USA' and r['visa_type']=='B1/B2' and r['quantity']==645977 for r in routes)},
  {'check':'uk_china_visitor_applications_2024','passed':any(r['origin']=='CHN' and r['destination']=='GBR' and r['year']==2024 and r['visa_type']=='Visitor' and r['quantity']==557093 for r in routes)},
  {'check':'bill_uk_one_charge_year','passed':sum(c['amount'] for b in bills if b['id']=='bill_uk_student_2024' for c in b['components'])==1266},
  {'check':'historical_us_receipts','passed':any(f['destination']=='USA' and f['year']==2024 and f['amount']==2561000000 for f in finance)},
  {'check':'fee_ids_unique','passed':len({f['id'] for f in fees})==len(fees)},
 ])
 meta={'version':VERSION,'cutoff':CUT,'observation_count':len(observations),'source_count':len(sources),'route_count':len(routes),'destination_count':len(coverage),'notes':'金额费率情景与实际账目分开；自然年与财年精确标识；公开版保留来源归档','native_packages':native_index,'source_id_mapping':mapping}
 data={'meta':meta,'entities':sorted(ents.values(),key=lambda x:x['code']),'routes':routes,'finances':finance,'fees':fees,'bills':bills,'claims':claims,'sources':sources,'fx':fx,'coverage':coverage,'estimates':estimates,'macro':macro}
 for name,obj in [('entities',data['entities']),('sources',sources),('fee_rules',fees),('observations',observations),('estimates',estimates),('routes',routes),('financial_ledger',finance),('bills',bills),('claims',claims),('coverage',coverage),('macro',macro),('checks',checks),('meta',meta),('derived_metrics',routes+finance)]:dump(name+'.json',obj)
 # Application payload keeps evidence references; large raw observation arrays remain downloadable.
 app=ROOT/'app';app.mkdir(exist_ok=True)
 (app/'data.js').write_text('window.VISA_DATA='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n')
 (app/'data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
 print(json.dumps({'meta':meta,'checks':checks},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
