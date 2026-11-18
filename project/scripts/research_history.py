#!/usr/bin/env python3
"""Rebuild archived 2015–2023 monetary-flow scenarios, entirely offline by default.

Schengen inputs are actual annual consulate applications (historical issuers),
not a current-membership backcast. UK inputs are 2019–2023 nationality applications;
only visitor and study routes with archived tariff evidence are included.

.research-venv/bin/python scripts/research_history.py [--download]
"""
from __future__ import annotations
import argparse, calendar, collections, hashlib, json, math, re, warnings
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import openpyxl
from bs4 import BeautifulSoup
from build_dataset import entity
from schengen_tariffs import annual_tariff, documented_urgent_tariff

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/history'
OUT=ROOT/'data/research/history'
YEARS=range(2015,2024)
SCH_URLS={
 2015:'806041fd-6870-43ac-a2a9-beac23c4f84b',2016:'1e25985b-8303-4ee5-a77e-188c9a562a47',
 2017:'498283c4-ed72-4a71-9ba6-5b726df1ee6c',2018:'d93dde94-f916-48d9-94ea-621e8a8f8bf2',
 2019:'f2681462-3c3d-487e-9627-9386e353396c',2020:'f9e61412-73b6-4415-a350-ab53e0300573',
 2021:'b4177e6c-90d3-4590-bca4-97c255542ae2',2022:'9c7b5dab-dde0-43dc-aa7e-71f653c3e4ca',
 2023:'87716634-be5e-4920-9358-495a95429759'}
SOURCES=[(f'history_sch_{y}',f'history/schengen_{y}.xlsx',f'https://home-affairs.ec.europa.eu/document/download/{uid}_en','European Commission DG HOME',f'{y} Schengen visa statistics — consulates',None) for y,uid in SCH_URLS.items()]+[
 ('history_sch_fee2020','history/eeas_fee2020.pdf','https://www.eeas.europa.eu/sites/default/files/qa_new_visa_rules_0.pdf','European Commission / EEAS','New EU visa rules — Questions and Answers','2020-01-31'),
 ('history_eu_policy','history/eu_visa_policy.html','https://home-affairs.ec.europa.eu/policies/schengen/visa-policy_en','European Commission DG HOME','Visa policy — facilitation agreements and entry dates',None),
 ('history_eu_eastern','history/eu_eastern_visa.html','https://home-affairs.ec.europa.eu/policies/international-affairs/engagement-partner-countries/eastern-partnership/visa-liberalisation-moldova-ukraine-georgia-and-armenia_en','European Commission DG HOME','Visa liberalisation with Moldova, Ukraine, Georgia and Armenia',None),
 ('history_eu_russia','history/eu_russia_measures.html','https://commission.europa.eu/topics/eu-solidarity-ukraine/eu-sanctions-against-russia-following-invasion-ukraine/visa-measures_en','European Commission','Visa measures — suspension with Russia from 12 September 2022',None),
 ('history_eu_georgia','history/eu_georgia_fee.pdf','https://www.eeas.europa.eu/sites/default/files/visa_rules2011_en.pdf','European Commission / EEAS','New rules of issuance of visas — Georgia','2011-03-01'),
 ('history_eu_ukraine','history/eu_ukraine_fee.html','https://www.legislation.gov.uk/eudn/2015/438/adopted/data.xht?view=snippet&wrap=true','Council of the European Union / legislation.gov.uk','Council Decision (EU) 2015/438 — Ukraine visa facilitation','2015-03-02'),
 ('history_eu_belarus','history/eu_belarus_fee.html','https://www.eeas.europa.eu/belarus/travel-study_en','European External Action Service','Travel & Study — Belarus; 35 euro fee from 1 July 2020',None),
 ('history_fed_20190102','history/fed_g5a_20190102.html','https://www.federalreserve.gov/releases/g5a/20190102/','Federal Reserve Board','G.5A annual exchange rates 2018 with 2015–2017 comparisons','2019-01-02'),
 ('history_fed_20220103','history/fed_g5a_20220103.html','https://www.federalreserve.gov/releases/g5a/20220103/','Federal Reserve Board','G.5A annual exchange rates 2021 with 2018–2020 comparisons','2022-01-03'),
 ('history_fed_20260105','fx/fed-g5a-20260105.html','https://www.federalreserve.gov/releases/g5a/20260105/','Federal Reserve Board','G.5A annual exchange rates 2025 with 2022–2024 comparisons','2026-01-05'),
 ('history_uk_applications','uk/entry-clearance-jun2026.xlsx','https://assets.publishing.service.gov.uk/media/6a85c3741b45e4e555421eda/entry-clearance-visa-outcomes-datasets-jun-2026.xlsx','UK Home Office','Entry clearance visa applications — Vis_D01 to June 2026',None),
 ('history_uk_fee2018','history/uk_fees2018base.pdf','https://www.legislation.gov.uk/uksi/2018/330/pdfs/uksi_20180330_en.pdf','UK Government / legislation.gov.uk','Immigration and Nationality (Fees) Regulations 2018','2018-03-16'),
 ('history_uk_fee2019','history/uk_fees2019reg.pdf','https://www.legislation.gov.uk/uksi/2019/475/pdfs/uksi_20190475_en.pdf','UK Government / legislation.gov.uk','Immigration and Nationality (Fees) (Refund, Waiver and Amendment) (EU Exit) Regulations 2019','2019-03-07'),
 ('history_uk_fee2020','history/uk_fees2020.html','https://www.gov.uk/government/publications/uk-points-based-immigration-system-further-details-statement/uk-points-based-immigration-system-further-details-statement','UK Home Office','UK points-based immigration system further details statement — fee table','2020-07-13'),
 ('history_uk_fee2022','history/uk_fees2022.pdf','https://www.legislation.gov.uk/uksi/2022/296/pdfs/uksi_20220296_en.pdf','UK Government / legislation.gov.uk','Immigration and Nationality and Immigration Services Commissioner (Fees) (Amendment) Regulations 2022','2022-03-15'),
 ('history_uk_fee2023','history/uk_fees2023.pdf','https://www.legislation.gov.uk/uksi/2023/1004/pdfs/uksi_20231004_en.pdf','UK Government / legislation.gov.uk','Immigration and Nationality (Fees) (Amendment) (No. 2) Regulations 2023','2023-09-14'),
 ('history_uk_fee2023_policy','history/uk_fees2023_news.html','https://www.gov.uk/government/news/new-visa-fees-set-to-come-into-effect-next-month','UK Home Office','New visa fees set to come into effect next month — charged-policy fees','2023-09-15'),
]

def dump(name,obj):
 (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def stable(prefix,*parts):
 return prefix+'_'+hashlib.sha256(json.dumps(parts,ensure_ascii=False).encode()).hexdigest()[:20]

def archive(download=False):
 if download:import requests
 manifest=[]
 for sid,rel,url,publisher,title,published in SOURCES:
  p=ROOT/'data/raw'/rel
  if download and (not p.exists() or not p.stat().st_size):
   p.parent.mkdir(parents=True,exist_ok=True)
   r=requests.get(url,timeout=60);r.raise_for_status();p.write_bytes(r.content)
  if not p.exists() or not p.stat().st_size:raise FileNotFoundError(f'Missing archived original: {p}; use --download')
  manifest.append(dict(source_id=sid,url=url,publisher=publisher,title=title,publication_date=published,
   retrieved_at=datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(),local_path=str(p.relative_to(ROOT)),
   sha256=hashlib.sha256(p.read_bytes()).hexdigest(),archive_status='archived',source_quality='official_primary'))
 # Shared tariff sources are archived and registered by the Schengen refinement
 # package. Keep them in this package as well so its standalone self-check and
 # source references remain complete without relying on merge order downstream.
 from research_refine_schengen import archive_sources
 manifest.extend(s for s in archive_sources(download) if not s['source_id'].startswith('refine_sch_workbook_'))
 return manifest

ALIASES={'FORMER YUGOSLAV REPUBLIC OF MACEDONIA':'MKD','FORMER YUGOSLAV MACEDONIA':'MKD','KOSOVO':'XKX','HOLY SEE':'VAT','CONGO, REPUB. DEMOC.':'COD','COTE IVOIRE':'CIV','GUINEA BISSAU':'GNB','RUMANIA':'ROU','TANZANIA,UND REPUBLIC':'TZA','British overseas citizens':'UNK','Other and unknown':'UNK','Refugee':'UNK','Stateless':'UNK','Unknown':'UNK','Not stated':'UNK','Other*':'UNK','Cyprus (Northern part of)':'UNK','Commonwealth of the Northern Mariana Islands':'MNP','Federated States of Micronesia':'FSM','Republic of Palau':'PLW'}
def code(s):
 c=ALIASES.get(s) or entity(s)
 return 'UNK' if not c or c.startswith('RAW_') or c in {'WORLD','OTHER'} else c

# These consulate locations are unallocated because local citizenship cannot be
# inferred for visa-exempt or transition-year populations. This is not a backcast
# claiming that today's visa exemptions already applied in 2015.
UNKNOWN_LOCATIONS=set('ALB AND ARG AUS AUT BEL BGR BHS BRB BIH BRA BRN CAN CHE CHL COL CRI CYP CZE DEU DMA DNK ESP EST FIN FRA GBR GRC GRD GTM HKG HND HRV HUN IRL ISL ISR ITA JPN KIR KNA KOR LCA LIE LTU LUX LVA MAC MCO MDA MEX MHL MKD MLT MNE MUS MYS FSM NLD NOR NZL NIC PAN PER PLW POL PRT PRY ROU SLV SMR SRB SVK SVN SWE SYC SGP SLB TWN TLS TON TTO TUV ARE USA URY VUT VAT VEN VCT WSM'.split())

def local_share(c,y):
 if c in {'GEO','UKR'}:return .95 if y<2017 else 0
 return 0 if c in UNKNOWN_LOCATIONS or c=='UNK' else .95

# (central, low, high) adult fees. Application timing is not observed within a year.
def sch_fee(c,y,receiver):
 tariff=annual_tariff(c,receiver,y)
 return tariff['center'],tariff['lower'],tariff['upper']


def flow(payer,receiver,y,kind,group,q,v,lo,hi,currency,sids,oids,method,notes,params,origin):
 return dict(id=stable('history_flow',payer,receiver,y,kind),payer=payer,receiver=receiver,year=y,visa_group=group,
  visa_type=kind,visa_label='申根短期' if group=='visitor' and receiver!='GBR' else '英国访客' if group=='visitor' else '英国学习',
  amount=v,lower=max(0,min(v,lo)),upper=max(v,hi),currency=currency,quantity=q,quantity_basis='applications',
  source_ids=sorted(set(sids)),observation_ids=oids,method_id=method,model_status='modeled_estimate',
  period_start=f'{y}-01-01',period_end=f'{y}-12-31',period_label=f'{y}自然年模型',period_type='calendar_year_model',
  origin_basis=origin,notes=notes,parameters=params)


def schengen():
 observations=[];checks=[];flows=[];models=[];ranges=[];cover=[]
 for y in YEARS:
  w=openpyxl.load_workbook(RAW/f'schengen_{y}.xlsx',read_only=True,data_only=True)
  ws=w['Data for consulates'];total=0;groups=collections.defaultdict(lambda:[0,[]]);raw_origins=set();members=set()
  for i,r in enumerate(ws.iter_rows(min_row=2,values_only=True),2):
   if not all(r[c] for c in (0,1,2)):continue
   raw_q=r[8];q=raw_q if raw_q is not None else 0
   if not isinstance(q,(int,float)):raise ValueError((y,i,q))
   total+=q;dst=code(r[0]);origin=code(r[1]);members.add(dst);raw_origins.add(r[1])
   oid=f'history_sch_{y}_r{i}_I'
   observations.append(dict(observation_id=oid,source_id=f'history_sch_{y}',source_locator=f"'Data for consulates'!I{i}",
    destination=r[0],consulate_country=r[1],consulate=r[2],nationality=None,origin_basis='consulate_country',metric='applications',
    raw_metric='Uniform visas applied for',value=raw_q,unit='applications',visa_type='schengen_short_stay',visa_group='visitor',
    period_start=f'{y}-01-01',period_end=f'{y}-12-31',period_type='calendar_year',quantity_basis='applications',calculation_type='observed' if raw_q is not None else 'missing_source_cell',
    notes='空白原表数量保留null且不产生费用；逐领馆统一短期签申请；不含机场过境签、长期签和边检口岸签；递交地不等于付款国籍'))
   groups[(origin,dst)][0]+=q;groups[(origin,dst)][1].append(oid)
  reported=None
  for r in w['Totals - Schengen State'].iter_rows(values_only=True):
   if r[0]=='Grand Total':reported=r[1]
  checks.append(dict(check='schengen_detail_vs_state_summary',year=y,detail=total,reported=reported,passed=total==reported))
  bydst=collections.defaultdict(lambda:[0.,0.,0.])
  sids=[f'history_sch_{y}','history_sch_fee2020','history_eu_policy','history_eu_eastern','history_eu_russia','history_eu_georgia','history_eu_ukraine','history_eu_belarus']
  model_sids=set(sids)
  for (origin,dst),(q,oids) in sorted(groups.items()):
   if not q:continue
   share=local_share(origin,y);tariff=annual_tariff(origin,dst,y);unknown=annual_tariff('UNK',dst,y)
   fee,fl,fh=tariff['center'],tariff['lower'],tariff['upper'];adult,al,ah=unknown['center'],unknown['lower'],unknown['upper']
   urgent=documented_urgent_tariff(origin,dst,y)
   # An unidentified applicant may have the documented Ukrainian urgent fee;
   # its centre still uses the general tariff, and no local treaty is inherited.
   unknown_urgent=documented_urgent_tariff('UKR',dst,y)
   urgent_high=max(fh,urgent['amount'] if urgent else fh)
   unknown_high=max(ah,unknown_urgent['amount'] if unknown_urgent else ah)
   urgent_sources=(urgent['source_ids'] if urgent else [])+(unknown_urgent['source_ids'] if unknown_urgent else [])
   route_sids=sorted(set(sids+tariff['source_ids']+unknown['source_ids']+urgent_sources));model_sids.update(route_sids)
   params={'submission_country':origin,'national_share':share,'national_share_sensitivity':[.8,1] if share else [0,0],
    'effective_fee_fraction':.9,'effective_fee_sensitivity':[.8,1],'adult_tariff_center':fee,
    'adult_tariff_timing_range':[fl,fh],'fee_time_weight':'equal calendar days; annual application dates unavailable',
    'fee_facilitation_scope':tariff['basis'],'adult_tariff_sources':tariff['source_ids'],'adult_tariff_uncertainty':tariff['uncertainty'],
    'adult_tariff_segments':[{k:s[k] for k in ('start','end','days','amount')} for s in tariff['segments']],
    'unknown_nationality_tariff':adult,'unknown_nationality_tariff_sources':unknown['source_ids'],
    'unknown_nationality_rule':'ordinary adult tariff centre; no concession inherited from submission country',
    'documented_urgent_tariff':urgent,'unknown_high_tariff':unknown_high,
    'unknown_high_urgent_scenario':unknown_urgent,
    'history_scope':'actual annual issuers; uniform short-stay applications only'}
   if share:
    v=q*.95*fee*.9;lo=q*.8*fl*.8;hi=q*urgent_high
    flows.append(flow(origin,dst,y,'申根短期','visitor',q*.95,v,lo,hi,'EUR',route_sids,oids,'history_schengen_consulate_nationality_tariff',
     '逐年官方申请数×国籍、收款政府与日期对应费率。领馆所在地按95%本国国籍分配（80—100%情景）；儿童与免收取有效成人费90%（80—100%情景）。双边优惠无当期依据时一般费中心、优惠至一般费范围；2017起格鲁吉亚、乌克兰递交地保留未知。',params,'modeled_nationality'))
   unknown_q=q*(1-share);v=unknown_q*adult*.9
   # Residual citizenship is not assigned the local country's treaty tariff.
   lo=0 if share else unknown_q*35*.8
   hi=q*.2*unknown_high if share else q*unknown_high
   flows.append(flow('UNK',dst,y,'申根短期_递交地_'+origin,'visitor',unknown_q,v,lo,hi,'EUR',route_sids,oids,'history_schengen_consulate_nationality_tariff',
    '递交地无法证明国籍的部分保留未知；免签或政策过渡递交地不分配本国公民。未知国籍中心按普通成人费、低情景含35欧便利化；不把未知国籍按旅游份额摊给国家。',params,'unallocated_nationality'))
   bydst[dst][0]+=q*(share*fee+(1-share)*adult)*.9
   # Common sensitivity scenarios; payer-allocation edge bounds are not summed.
   bydst[dst][1]+=q*.8*(.8*fl+.2*35) if share else q*35*.8
   # Citizenship shares and the discounted fee change the same receipt total.
   # Use the common 80--100% allocation endpoints instead of independently
   # putting the entire population at the largest of the two citizenship fees.
   bydst[dst][2]+=q*max(.8*urgent_high+.2*unknown_high,urgent_high) if share else q*unknown_high
  for dst,(v,lo,hi) in sorted(bydst.items()):
   ranges.append(dict(receiver=dst,year=y,amount=v,lower=min(lo,v),upper=max(v,hi),currency='EUR',range_method='国籍×收款政府×日期成人费率；共同有效收费与国籍分配情景，逐付款方边际端点不相加；未知国籍中心为一般费，保留未证实双边优惠与急件范围'))
  models.append(dict(model_id=f'history_schengen_{y}',destination='SCH',year=y,issuing_members=sorted(members),members=sorted(members|{'LIE'}),
   source_ids=sorted(model_sids),quality='官方逐领馆申请数；国籍×收款政府×日期历史费率和显式收费/国籍转换情景，非官方实收',
   missing='长期签、ATV、真实申请人国籍、儿童/免收费结构、各国急件；未证实双边优惠和冰岛俄罗斯暂停日保留范围，丹麦日期冲突显式；过渡递交地保留未知',
   parameters={'local_share':.95,'effective_adult_fee_fraction':.9,'membership':'annual source workbook, not current members'}))
  cover.append(dict(year=y,receiver='SCH',issuing_receiver_count=len(members),issuing_members=sorted(members),applications=total,
   origin_location_count=len(raw_origins),scope='统一短期签证申请；历史成员收款方；列支敦士登无独立签发统计',coverage_status='partial_visa_types',source_ids=[f'history_sch_{y}']))
  w.close()
 return observations,checks,flows,models,ranges,cover


def quarter_bounds(y,q):
 m=(q-1)*3+1;start=date(y,m,1);end=date(y,m+3,1) if q<4 else date(y+1,1,1)
 return start,end

# Historical visitor fee vector (short, 2 year, 5 year, 10 year); China scheme
# qualification is not observed, so the higher-duration alternative is retained.
UK_SCHEDULE=[(date(2018,4,6),(93,350,636,798),348,186),
 (date(2019,3,29),(95,361,655,822),348,186),
 (date(2022,4,6),(100,376,670,837),363,200),
 (date(2023,10,4),(115,400,771,963),490,200)]

def uk_price(y,q,group,subtype,payer,scenario):
 start,end=quarter_bounds(y,q);current=start;values=[]
 while current<end:
  _,visit,study,short=next(row for row in reversed(UK_SCHEDULE) if row[0]<=current)
  if group=='Visitor':
   v=visit[0] if scenario=='lower' or (payer=='CHN' and scenario=='center') else visit[0]*.9+sum(visit[1:])*.1/3 if scenario=='center' else visit[0]*.75+visit[3]*.25
  elif subtype.startswith('Short-term'):
   # Old six-month and 11-month labels are pooled in Vis_D01. Through 2020
   # the old £97 option is retained; later short-term language route uses £186/200.
   low=97 if y<=2020 else short
   v=low if scenario=='lower' else (low+short)/2 if scenario=='center' else short
  else:
   # From Oct 2023 the Home Office charged-policy announcement says £490.
   # Preserve £363 in the lower case because the instrument amended the wrong
   # legacy fee item (1.3.11 rather than the Student 1.3.11A item).
   v=363 if scenario=='lower' and current>=date(2023,10,4) else study
  values.append(v);current+=timedelta(days=1)
 # Quarter application dates are unknown: uniform-day center and all-at-low/high
 # dates for the two endpoint scenarios. Duration shares are scenarios, not observed.
 return sum(values)/len(values) if scenario=='center' else min(values) if scenario=='lower' else max(values)


def uk():
 w=openpyxl.load_workbook(ROOT/'data/raw/uk/entry-clearance-jun2026.xlsx',read_only=True,data_only=True)
 observations=[];totals=collections.Counter();excluded=collections.Counter();groups=collections.defaultdict(lambda:dict(q=0,v=0.,lo=0.,hi=0.,oids=[]))
 for i,r in enumerate(w['Data_Vis_D01'].iter_rows(min_row=5,values_only=True),5):
  if str(r[0]) not in {'2019','2020','2021','2022','2023'}:continue
  y=int(r[0]);group=r[4];qnum=int(r[8] or 0)
  if group not in {'Visitor','Study'}:excluded[(y,group)]+=qnum;continue
  payer=code(r[2]);quarter=int(str(r[1])[-1]);start,end=quarter_bounds(y,quarter)
  oid=f'history_uk_Vis_D01_r{i}';totals[(y,group)]+=qnum
  observations.append(dict(observation_id=oid,source_id='history_uk_applications',source_locator=f"'Data_Vis_D01'!A{i}:I{i}",destination='GBR',
   nationality=r[2],origin_basis='nationality',visa_group=group.lower(),visa_type=r[6],applicant_type=r[7],metric='applications',raw_metric='Applications',
   value=qnum,unit='applications',period_start=start.isoformat(),period_end=(end-timedelta(days=1)).isoformat(),period_type='quarter',
   quantity_basis='applications',calculation_type='observed',notes='真实国籍申请数，非签发量；主申请和附属申请为不同原始行'))
  g=groups[(y,payer,group,r[6])];g['q']+=qnum;g['oids'].append(oid)
  for field,scenario in [('v','center'),('lo','lower'),('hi','upper')]:g[field]+=qnum*uk_price(y,quarter,group,r[6],payer,scenario)
 w.close()
 sids=['history_uk_applications','history_uk_fee2018','history_uk_fee2019','history_uk_fee2020','history_uk_fee2022','history_uk_fee2023','history_uk_fee2023_policy']
 flows=[];models=[];ranges=[];cover=[]
 for (y,payer,group,subtype),g in sorted(groups.items()):
  if not g['q']:continue
  flows.append(flow(payer,'GBR',y,subtype,group.lower(),g['q'],g['v'],g['lo'],g['hi'],'GBP',sids,g['oids'],'history_uk_quarter_applications_tariff',
   '逐季度国籍申请×有年代依据的申请费。访客期限中心90%短期、10%均分2/5/10年，低全短期、高25%十年；中国中心按两年优惠方案短期价、适用资格未观测。学习主附申请逐人计费，2023十月按Home Office公布收费490英镑，低情景保留363。仅含访客与学习，工作、家庭、其他路径未扩展。',
   {'visitor_duration_share_status':'working scenario, not observed','visitor_long_share_center':0 if payer=='CHN' else .1,'visitor_long_share_range':[0,.25],
    'fee_change_2022':'2022-04-06 (Schedule 1 fee increases); 11 April commencement applies to separate route wording',
    'quarter_timing':'uniform daily center; low/high allocation to tariff dates','charged_policy_student_from_2023_10_04':490,
    'student_legislative_item_uncertainty_lower':363,'excluded_charges':['IHS','biometrics where separate','priority','outsourced service fees']},'nationality'))
 for y in range(2019,2024):
  f=[r for r in flows if r['year']==y]
  ranges.append(dict(receiver='GBR',year=y,amount=sum(r['amount'] for r in f),lower=sum(r['lower'] for r in f),upper=sum(r['upper'] for r in f),currency='GBP',range_method='访客期限和季度收费日期共同情景；2023学生按公布收费中心/原条目低情景；只涵盖访客与学习'))
  models.append(dict(model_id=f'history_uk_{y}',destination='GBR',year=y,source_ids=sids,quality='真实国籍申请×历史费率；期限混合为情景，非实收',
   included_visa_groups=['visitor','study'],missing='工作、家庭、其他类别；真实期限混合、减免和退款、IHS与附加服务费'))
  cover.append(dict(year=y,receiver='GBR',issuing_receiver_count=1,applications=sum(totals[y,g] for g in ['Visitor','Study']),
   included_groups={g:totals[y,g] for g in ['Visitor','Study']},excluded_groups={g:n for (yy,g),n in excluded.items() if yy==y},
   coverage_status='partial_visa_types',scope='仅访客与学习路径；全部真实原表国籍，不宣称全类收入',source_ids=['history_uk_applications']))
 return observations,flows,models,ranges,cover


def fx():
 rows={}
 for sid,filename in [('history_fed_20190102','data/raw/history/fed_g5a_20190102.html'),('history_fed_20220103','data/raw/history/fed_g5a_20220103.html'),('history_fed_20260105','data/raw/fx/fed-g5a-20260105.html')]:
  s=BeautifulSoup((ROOT/filename).read_text(),'html.parser');years=[]
  for tr in s.find_all('tr'):
   cells=[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'],recursive=False)]
   if cells and cells[0]=='COUNTRY':years=[int(x) for x in cells[2:] if re.fullmatch(r'20\d\d',x)];continue
   if not years or len(cells)!=2+len(years):continue
   country=re.sub(r'[^A-Z]','',cells[0]);cur={'CHINAPR':'CNY','EMUMEMBERS':'EUR','UNITEDKINGDOM':'GBP'}.get(country)
   if not cur:continue
   for y,value in zip(years,cells[2:]):
    if y not in YEARS:continue
    value=float(value.replace(',','').replace(' ',''));direct=cur!='CNY'
    rows[y,cur]=dict(fx_id=f'history_fed_{y}_{cur}',year=y,currency=cur,raw_rate=value,raw_direction='USD_per_currency' if direct else 'currency_per_USD',usd_per_unit=value if direct else 1/value,
     source_id=sid,source_locator=f'G.5A annual table; {cells[0]}; {y}',method='Federal Reserve annual average New York noon buying rates; historical year, not current rate')
 for y in YEARS:rows[y,'USD']=dict(fx_id=f'history_usd_{y}',year=y,currency='USD',raw_rate=1,raw_direction='USD_per_USD',usd_per_unit=1,source_id=rows[y,'CNY']['source_id'],source_locator='USD numeraire',method='identity')
 assert len(rows)==36,sorted(rows)
 return [v for k,v in sorted(rows.items())]


def fee_rules():
 rules=[]
 def add(key,dst,group,amount,cur,start,end,sids,locator,notes=''):
  rules.append(dict(fee_id='history_'+key,destination=dst,visa_group=group,visa_type=group,amount=amount,currency=cur,effective_from=start,effective_to=end,
   fee_component='government_application_fee',payment_trigger='application',source_ids=sids,source_locator=locator,notes=notes))
 from research_refine_schengen import fee_rules as refined_fee_rules
 for rule in refined_fee_rules():
  if rule['effective_from']>'2023-12-31':continue
  historical=dict(rule,fee_id='history_'+rule['fee_id'])
  historical['effective_to']=min(rule.get('effective_to') or '2023-12-31','2023-12-31')
  rules.append(historical)
 for i,(start,visit,study,short) in enumerate(UK_SCHEDULE):
  if start.year>2023:continue
  end=(UK_SCHEDULE[i+1][0]-timedelta(days=1)).isoformat() if i+1<len(UK_SCHEDULE) else '2023-12-31'
  ss=['history_uk_fee2018' if i==0 else 'history_uk_fee2019' if i==1 else 'history_uk_fee2022' if i==2 else 'history_uk_fee2023']
  for term,amount in zip(['visit_short','visit_2y','visit_5y','visit_10y'],visit):
   add('uk_'+term+'_'+str(start),'GBR','visitor',amount,'GBP',start.isoformat(),end,ss,'Schedule 1, Table 1, items 1.1.1–1.1.4')
   rules[-1]['visa_type']=term
  add('uk_study_'+str(start),'GBR','study',study,'GBP',start.isoformat(),end,ss+(['history_uk_fee2023_policy'] if i==3 else []),'Student/Tier 4 outside-UK fee; 2023 charged-policy announcement','2023十月的490是Home Office公布收费；学生条款修订编号存在疑义，低情景保留363')
  rules[-1]['visa_type']='sponsored_study'
  add('uk_shortstudy_'+str(start),'GBR','study',short,'GBP',start.isoformat(),end,ss,'Schedule 1, item 1.2.2','六个月内旧短期学习£97在2019–2020低情景保留；不误用访客学术/医疗£190')
  rules[-1]['visa_type']='short_term_study'
 return rules


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--download',action='store_true');args=parser.parse_args()
 OUT.mkdir(parents=True,exist_ok=True);warnings.filterwarnings('ignore',message='Cannot parse header or footer')
 sources=archive(args.download);so,checks,sf,sm,sr,sc=schengen();uo,uf,um,ur,uc=uk();rates=fx()
 observations=so+uo;flows=sf+uf;models=sm+um;ranges=sr+ur;coverage=sc+uc
 valid_sids={s['source_id'] for s in sources};valid_oids={o['observation_id'] for o in observations};fxkeys={(r['year'],r['currency']) for r in rates}
 assert len(valid_oids)==len(observations)
 assert len({f['id'] for f in flows})==len(flows)
 for f in flows:
  assert 2015<=f['year']<=2023 and 0<=f['lower']<=f['amount']<=f['upper'],f['id']
  assert set(f['source_ids'])<=valid_sids,(f['id'],f['source_ids'])
  assert set(f['observation_ids'])<=valid_oids,f['id']
  assert (f['year'],f['currency']) in fxkeys
  assert f['payer']!=f['receiver'],f['id']
 for r in ranges:
  summed=sum(f['amount'] for f in flows if f['receiver']==r['receiver'] and f['year']==r['year'])
  assert math.isclose(summed,r['amount'],abs_tol=.001),(r,summed)
 assert all(c['passed'] for c in checks)
 checks.extend([dict(check='flow_references_ranges_fx_and_uniqueness',passed=True,flows=len(flows),observations=len(observations)),dict(check='historical_membership',passed=all(('HRV' in c['issuing_members'])==(c['year']==2023) for c in sc)),dict(check='history_does_not_replace_2024_2025',passed=all(f['year']<2024 for f in flows))])
 annual=[]
 for y in YEARS:
  ff=[f for f in flows if f['year']==y];receivers=sorted({f['receiver'] for f in ff})
  annual.append(dict(year=y,receiver_count=len(receivers),receivers=receivers,flows=len(ff),payer_count=len({f['payer'] for f in ff if f['payer']!='UNK'}),coverage='2015–2018申根短期；2019–2023另含英国访客与学习；随年代覆盖变化，不代表全球总额'))
 for name,obj in [('sources.json',sources),('fee_rules.json',fee_rules()),('observations.json',observations),('fx.json',rates),('coverage.json',coverage),('annual_coverage.json',annual),('checks.json',checks)]:dump(name,obj)
 output=ROOT/'data/estimates/history_flows.json';output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(dict(flows=flows,models=models,destination_ranges=ranges),ensure_ascii=False,indent=2)+'\n')
 report=['# 历史数据扩展：2015–2023','',f'共 {len(flows):,} 条费用流情景、{len(observations):,} 条原始数量观察、{len(sources)} 个官方原始来源。','',
  '申根：九年逐领馆统一短期签申请均与各年度成员国汇总完全核对。2015–2022有25个独立签发收款政府，2023有26个；按原表年度成员处理，未把2025成员回填。列支敦士登没有独立签发行。',
  '', '英国：2019–2023的访客与学习真实国籍申请，按季度匹配2018/2019/2022/2023历史价目。2022费用涨价适用4月6日（附表1），不是11日的部分路线文字修订。2023年学生前三季度按363英镑；第四季度中心按10月1–3日363英镑、10月4日–12月31日490英镑逐日加权，再乘各季度真实申请数汇总全年，低情景保留363英镑。工作、家庭、其他路径尚未计入历史金额，coverage.json保存排除数量。',
  '', '金额为申请数与历史费率的模型。申根费用按国籍、收款政府及日期匹配；EU便利化不自动覆盖丹麦或关联国。挪威阿塞拜疆从2015-06-01、瑞士阿塞拜疆从2017-04-01、佛得角75%成人费从2022-07-01；俄罗斯暂停按各收款政府证据处理。瑞士乌克兰2019年前缺少当期优惠依据时保留一般费中心和35至一般费范围，丹麦暂停日冲突及冰岛日期缺口显式记录。领馆递交地仍保留95%国籍情景和一般费未知残差；儿童、免收、急件及英国期限结构为情景。',
  '', '汇率：美联储G.5A对应自然年的人民币、欧元、英镑年均汇率和美元单位基准，保留原始报价方向与来源；没有用2024/2025汇率回填历史。',
  '', '时间序列覆盖会变化：2015–2018只有申根短期；2019起再含英国访客与学习。新增历史年份缺少的收款国没有补零，不能把范围变化解释为全球收支变化。','',
  '| 年份 | 实际独立收款方 | 费用流条数 | 已分配付款国家/地区 |','|---|---:|---:|---:|']
 report.extend(f"| {r['year']} | {r['receiver_count']} | {r['flows']} | {r['payer_count']} |" for r in annual)
 report.extend(['','重建：`.research-venv/bin/python scripts/research_history.py`。原始文件SHA-256位于`sources.json`；原表定位保留在`observations.json`。'])
 (OUT/'REPORT.md').write_text('\n'.join(report)+'\n')
 print(json.dumps(dict(flows=len(flows),observations=len(observations),sources=len(sources),fx=len(rates),years=annual,checks_passed=all(c['passed'] for c in checks)),ensure_ascii=False))

if __name__=='__main__':main()
