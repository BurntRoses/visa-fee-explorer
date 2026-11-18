#!/usr/bin/env python3
"""Build a compact rendering index, global coverage inventory and lazy evidence chunks.
No network. Global regions are extracted from frozen UN M49; monetary truth is flows.
"""
from pathlib import Path
import json,gzip,collections,gettext,io,hashlib,math,re
import pycountry,pandas as pd
from entity_names import canonical_name,JURISDICTION_NOTE
from country_profiles import build_country_profiles
from country_context import build_country_context
from observation_domains import has_visa_quantity, has_mobility_context, observation_domain
from research_packages import EXTENSION_PACKAGES, REFINEMENT_PACKAGES
from release_config import UI_VERSION
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'app/workbench/public/data'
GROUPS=['visitor','student','work','family','other','unclassified']
REGIONS={'Africa':'非洲','Americas':'美洲','Asia':'亚洲','Europe':'欧洲','Oceania':'大洋洲','Antarctica':'南极洲'}
tr=gettext.translation('iso3166-1',pycountry.LOCALES_DIR,languages=['zh_CN'],fallback=True).gettext

def js(obj):return json.dumps(obj,ensure_ascii=False,separators=(',',':'))
def load(path,default=None):
 p=ROOT/path
 return json.loads(p.read_text()) if p.exists() else ([] if default is None else default)
def group_of(r):
 if r.get('category_detail_status')=='unclassified':return 'unclassified'
 g=r.get('visa_group','other')
 if g=='other' and (r.get('receiver') in ['CHN','IND','TUR','AUS'] or any(x in str(r.get('visa_type','')).lower() for x in ['all_visa','all visa','all-category','全部签证','全类签证'])):return 'unclassified'
 return g if g in GROUPS else 'unclassified'
def category_groups(r):
 explicit=r.get('visa_group')
 if explicit in GROUPS:return {explicit}
 t=str(r.get('visa_type','')).lower()
 # Multi-class US MRV schedules are explicitly split by the named visa classes.
 if r.get('destination')=='USA':
  tokens=re.split(r'[/ ,_]+',t)
  found=set()
  if any(re.fullmatch(r'b[12]?|bbbcc|bbbcv|c1|d',x) for x in tokens):found.add('visitor')
  if any(re.fullmatch(r'f[12]?|m[12]?',x) for x in tokens):found.add('student')
  if any(re.fullmatch(r'h[0-9a-z]*|l[12]?|o[123]?|p[123]?|q[12]?|r[12]?|tn|td|e[123]?',x) for x in tokens):found.add('work')
  if any(re.fullmatch(r'k[123]?',x) for x in tokens):found.add('family')
  if any(re.fullmatch(r'a[123]?|g[1-5]?|j[12]?|nato|c2|c3|i|s|t|u',x) for x in tokens):found.add('other')
  if found:return found
 if any(x in t for x in ['visitor','touris','short_stay','short_visit','short stay','schengen','airport_transit','transit','600','ads_china']):return {'visitor'}
 if any(x in t for x in ['student','study','500']):return {'student'}
 if any(x in t for x in ['worker','work','employment','aewv','talent','business']):return {'work'}
 if any(x in t for x in ['family','partner','spouse','depend','joining','reunion']):return {'family'}
 if t in ['other','other temporary visas','diplomatic','official','medical','religious']:return {'other'}
 return {'unclassified'}
def active_fee(r,year):
 if r.get('validity_status')=='retrieval_date_rule_historical_continuity_unverified':return False
 start=str(r.get('effective_from') or '')[:10];end=str(r.get('effective_to') or '')[:10]
 if start and start>f'{year}-12-31':return False
 if end and end<f'{year}-01-01':return False
 snapshot=str(r.get('snapshot_date') or '')[:10]
 if not start:return False
 comp=str(r.get('component','')).lower()
 return not any(x in comp for x in ['service','biometric','sevis','health','ihs','authorisation','authorization','evus','levy','insurance','transaction','employer','uscis','asylum','surcharge'])
def main():
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'chunks').mkdir(exist_ok=True)
 data=load('app/data.json',{});flows=data['flows'];names={e['code']:e['name'] for e in data['entities'] if not e['code'].startswith('RAW_')}
 regions={};raw=ROOT/'data/raw/world_inventory/un_m49.html'
 if raw.exists():
  table=pd.read_html(io.StringIO(raw.read_text()))[0]
  for r in table.to_dict('records'):
   c=r.get('ISO-alpha3 Code');reg=r.get('Region Name')
   if isinstance(c,str):regions[c]={'region':REGIONS.get(reg,'其他地区'),'subregion':str(r.get('Sub-region Name','')),'m49':str(r.get('M49 Code',''))}
 entities=[]
 for c in pycountry.countries:
  entities.append({'code':c.alpha_3,'name':canonical_name(c.alpha_3,names.get(c.alpha_3,tr(c.name))), 'kind':'country_or_jurisdiction',**regions.get(c.alpha_3,{'region':'其他地区'})})
 codes={x['code'] for x in entities}
 for c in sorted({x['payer'] for x in flows}|{x['receiver'] for x in flows}):
  if c not in codes and not c.startswith(('RAW_','UNK','OTHER','WORLD')):entities.append({'code':c,'name':names.get(c,c),'region':'其他地区','kind':'country_or_jurisdiction'});codes.add(c)
 entities.extend([{'code':'SCH','name':'申根整体','region':'欧洲','kind':'aggregate'},{'code':'UNK','name':'付款国籍未分配','region':'未分配','kind':'unallocated'}])
 entities.sort(key=lambda x:x['name']);ei={x['code']:i for i,x in enumerate(entities)}
 for r in flows:
  for key in ['payer','receiver']:
   if r[key] not in ei:
    r[key]='UNK'
 cells=collections.defaultdict(lambda:[0.0,0,0]);chunks=collections.defaultdict(list)
 covflow=collections.defaultdict(list)
 for r in flows:
  g=group_of(r);r['category_detail_status']='unclassified' if g=='unclassified' else 'classified';r['display_group']=g
  key=(r['year'],ei[r['payer']],ei[r['receiver']],GROUPS.index(g));cells[key][0]+=r['amount_cny'];cells[key][1]+=1;cells[key][2]+=int(r['amount_cny']==0)
  chunks[f'{r["receiver"]}-{r["year"]}'].append(r);covflow[r['receiver'],r['year'],g].append(r)
 records=[[*k,round(v[0],6),v[1],v[2]] for k,v in sorted(cells.items())]
 fees=data.get('fees',[]);obs=load('data/processed/observations.json');extra_cov=[]
 for pkg in EXTENSION_PACKAGES+REFINEMENT_PACKAGES:
  extra_cov+=load(f'data/research/{pkg}/coverage.json')
 extby=collections.defaultdict(list)
 for r in extra_cov:extby[r.get('code',r.get('destination'))].append(r)
 feedest=collections.defaultdict(list)
 for r in fees:feedest[r.get('destination')].append(r)
 # The common Schengen short-stay tariff applies to each member, without inventing long-stay rates.
 for c in data['flow_meta']['schengen_members']:feedest[c]+=feedest['SCH']
 obsdest=collections.defaultdict(list)
 for r in obs:obsdest[r.get('destination')].append(r)
 coverage=[]
 for e in entities:
  if e['kind']!='country_or_jurisdiction':continue
  c=e['code']
  for y in sorted({r['year'] for r in flows}):
   for g in GROUPS:
    ff=covflow[c,y,g];fr=[r for r in feedest[c] if g in category_groups(r) and active_fee(r,y)];oo=[o for o in obsdest[c] if str(o.get('period_start','')).startswith(str(y)) and g in category_groups(o)];ex=[r for r in extby[c] if r.get('year',y)==y and (r.get('visa_group',g)==g or (g=='unclassified' and r.get('category_detail_status')=='unclassified_aggregate'))];currentfr=[r for r in feedest[c] if g in category_groups(r)]
    feeknown=bool(fr);qknown=any(has_visa_quantity(o) for o in oo);mknown=any(has_mobility_context(o) for o in oo)
    source_ids=sorted({s for r in ff for s in r.get('source_ids',[])}|{s for r in fr for s in r.get('source_ids',[]) if s}|{o['source_id'] for o in oo if o.get('source_id')}|{ss for r in currentfr for ss in r.get('source_ids',[]) if ss}|{ss for r in ex for ss in r.get('source_ids',[]) if ss})
    if ff:status='modeled_nationality' if any(r['payer']!='UNK' and r['amount_cny']>0 for r in ff) else 'modeled_total'
    elif feeknown:status='fee_only'
    elif qknown:status='quantity_only'
    elif currentfr:status='current_fee_only'
    elif mknown:status='mobility_context_only'
    elif ex:status='researched_gap'
    else:status='not_researched'
    # An explicit native annual-quantity gap takes precedence over a modeled
    # count or a half-year observation. Partial counts remain useful context.
    quantity_flags=[r['quantity_known'] for r in ex if isinstance(r.get('quantity_known'),bool)]
    quantity_known=all(quantity_flags) if quantity_flags else qknown or any(r.get('quantity') is not None for r in ff)
    quantity_context_known=qknown or any(observation_domain(o)=='document_activity' for o in oo) or any(r.get('quantity_context_known') for r in ex)
    notes='；'.join(dict.fromkeys(str(r.get('notes',r.get('missing_reason',r.get('gaps',r.get('status',''))))) for r in ex))[:800]
    coverage.append(dict(code=c,name=e['name'],region=e.get('region','其他地区'),year=y,visa_group=g,status=status,fee_known=feeknown,fee_current_snapshot_known=bool(currentfr),quantity_known=quantity_known,quantity_context_known=quantity_context_known,mobility_context_known=mknown or any(r.get('mobility_context_known') for r in ex),amount_known=bool(ff),nationality_known=any(r['payer']!='UNK' and r['amount_cny']>0 for r in ff),source_ids=source_ids,notes=notes or ('已建模费用分项，原始统计与估算方法见明细。' if ff else '该类别金额尚未识别。' if status!='not_researched' else '尚无本项目已归档的可用数量或金额模型。')))
 chunkmap={}
 for stale in (OUT/'chunks').glob('*.json.gz'):stale.unlink()
 for key,rr in chunks.items():
  filename=f'chunks/{key}.json.gz';(OUT/filename).write_bytes(gzip.compress(js(rr).encode(),mtime=0));chunkmap[key]=filename
 yearCoverage=[dict(year=y,receivers=sorted({r['receiver'] for r in flows if r['year']==y}),model_ids=sorted({r.get('method_id','') for r in flows if r['year']==y})) for y in sorted({r['year'] for r in flows})]
 meta={**data['meta'],'years':sorted({r['year'] for r in flows}), 'year_coverage':yearCoverage,'ui_version':UI_VERSION,'jurisdiction_note':JURISDICTION_NOTE,'index_schema':'visa-index-1','index_record_count':len(records),'entity_count':len([e for e in entities if e['kind']=='country_or_jurisdiction']),'group_names':dict(zip(GROUPS,['访客','学生','工作','家庭','其他类别','类别未细分'])),'world_inventory_source':'https://unstats.un.org/unsd/methodology/m49/overview/'}
 profiles=build_country_profiles(flows,entities,data['flow_meta']['schengen_members'],load('data/research/demographic_context/population.json'))
 context_manifest,context_report=build_country_context(obs,entities,OUT)
 index=dict(countryContext=context_manifest,countryProfiles=profiles,meta=meta,entities=entities,groups=GROUPS,records=records,schengenMembers=data['flow_meta']['schengen_members'],coverage=coverage,annualRanges=data['flow_meta']['annual_ranges'],chunks=chunkmap,sources=data['sources'],models=data.get('flow_models',[]),feeRules=fees,bills=data.get('bills',[]),finances=data.get('finances',[]))
 # The heavy observation corpus stays in evidence downloads, not the first rendering path.
 (OUT/'index.json').write_text(js(index))
 full={**data,'observations':obs,'world_inventory':entities,'coverage_inventory':coverage,'country_profiles':profiles,'country_context':context_manifest,'jurisdiction_note':JURISDICTION_NOTE}
 (OUT/'full-data.json.gz').write_bytes(gzip.compress(js(full).encode(),mtime=0))
 (ROOT/'data/processed/country_profiles.json').write_text(js(profiles))
 (ROOT/'data/processed/world_inventory.json').write_text(js(entities))
 (ROOT/'data/processed/coverage_inventory.json').write_text(js(coverage))
 report={'context':context_report,'version':meta['version'],'entities':meta['entity_count'],'render_records':len(records),'raw_model_rows':len(flows),'chunks':len(chunkmap),'index_bytes':(OUT/'index.json').stat().st_size,'index_gzip_bytes':len(gzip.compress(js(index).encode())),'by_region':{region:{'jurisdictions':len({r['code'] for r in coverage if r['region']==region}),'amount_destinations':len({r['code'] for r in coverage if r['region']==region and r['amount_known']}),'fee_destinations':len({r['code'] for r in coverage if r['region']==region and r['fee_known']})} for region in sorted({r['region'] for r in coverage})}}
 (ROOT/'docs/validation/workbench-data-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(js(report))
if __name__=='__main__':main()
