#!/usr/bin/env python3
"""Build the unified estimated payer -> recipient fee ledger, then product data.

Run after build_dataset.py; all source packages and model scripts are local.
"""
from pathlib import Path
from research_packages import EXTENSION_PACKAGES, active_money_inputs
from release_config import DATA_VERSION
import json,csv,subprocess,sys,collections,hashlib
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'data/processed'
def load(path):return json.loads((ROOT/path).read_text())
def dump_csv(name,rows):
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with (P/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,keys);w.writeheader()
  for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False,separators=(',',':')) if isinstance(v,(list,dict)) else v for k,v in row.items()})
def main():
 if '--reuse-models' not in sys.argv:
  for name in ['model_core.py','model_us.py','model_uk_canada.py','model_asia.py','model_indonesia.py','model_cyprus.py','model_nepal.py']:
   subprocess.run([sys.executable,str(ROOT/'scripts'/name)],cwd=ROOT,check=True)
  subprocess.run([sys.executable,str(ROOT/'scripts/model_r12_fiscal.py')],cwd=ROOT,check=True)
 fx=load('data/research/schengen_fx/fx.json')
 for pkg in EXTENSION_PACKAGES:
  fp=ROOT/f'data/research/{pkg}/fx.json'
  if fp.exists():fx+=load(str(fp.relative_to(ROOT)))
 rates={(r['year'],r['currency']):r['usd_per_unit'] for r in fx}
 sources=load('data/processed/sources.json');sids={r['source_id'] for r in sources}
 def to_cny(x,c,y):return x if c=='CNY' else x*rates[y,c]/rates[y,'CNY']
 out=[];models=[];native_ranges=[];component_ranges={}
 for package,data in active_money_inputs(ROOT).items():
  models+=data['models'];native_ranges.extend((package,r) for r in data.get('destination_ranges',[]))
  for f in data['flows']:
   r=dict(f);r['visa_label']=r.get('visa_label',r.get('label',r['visa_type']))
   r['visa_group']={'Visitor':'visitor','Study':'student','study':'student','Work':'work','Family':'family','Other':'other'}.get(r['visa_group'],r['visa_group'])
   if r['visa_group'] not in ['visitor','student','work','family','other']:r['visa_group']='other'
   for key,native in [('amount_cny','amount'),('lower_cny','lower'),('upper_cny','upper')]:r[key]=round(to_cny(r[native],r['currency'],r['year']),6)
   r['model_status']=r.get('model_status','modeled_estimate');r['origin_basis']=r.get('origin_basis','modeled_nationality')
   r['period_start']=f'{r["year"]}-01-01';r['period_end']=f'{r["year"]}-12-31';r['period_type']='calendar_year_model';r['period_label']=f'{r["year"]}自然年模型'
   r['source_ids']=list(dict.fromkeys(r.get('source_ids',[])))
   missing=[s for s in r['source_ids'] if s not in sids]
   assert not missing,(r['id'],missing)
   # Every row is a cross-border nationality-attributed payment; self rows are retained as unknown attribution.
   if r['payer']==r['receiver']:r['payer']='UNK'
   out.append(r)
   key=package,r['receiver'],r['year']
   component=component_ranges.setdefault(key,dict(package=package,receiver=r['receiver'],year=r['year'],amount_cny=0,lower_cny=0,upper_cny=0,range_method='共同费率／数量参数端点；未识别范围另列'))
   for field in ['amount_cny','lower_cny','upper_cny']:component[field]+=r[field]
 # A joint control governs its own package's disjoint scope. National D fees
 # and Schengen C fees can share a collecting government without sharing a fee.
 controlled=set()
 for package,r in native_ranges:
  key=package,r['receiver'],r['year'];assert key not in controlled,('duplicate joint control',key);controlled.add(key)
  target=component_ranges[key]
  converted={k:to_cny(r[native],r['currency'],r['year']) for k,native in [('amount_cny','amount'),('lower_cny','lower'),('upper_cny','upper')]}
  assert abs(target['amount_cny']-converted['amount_cny'])<.1,(package,r['receiver'],r['year'],'joint scope center mismatch')
  target.update({k:v for k,v in r.items() if k not in ['amount','lower','upper','currency']},**converted)
 scopes={(r['receiver'],r['year']) for r in out}|{('SCH',2024),('SCH',2025)}
 model={'version':DATA_VERSION,'flows':out,'replace_scopes':[{'destination':d,'year':y,'visa_groups':['all']} for d,y in sorted(scopes)],'models':models,'notes':['所有金额归入自然年模型，财年输入显式桥接。','国籍未识别部分保留UNK，已包含在目的地收入；未知不得重加。','参数情景范围不是置信区间，中心为透明工作假设；与实际收款分开。']}
 (P/'modeled_flow_inputs.json').write_text(json.dumps(model,ensure_ascii=False,separators=(',',':')))
 subprocess.run([sys.executable,str(ROOT/'scripts/build_flow_ledger.py')],cwd=ROOT,check=True)
 data=load('app/data.json')
 for k in ['flows','country_balances','flow_matrix','flow_meta']:data[k]=load(f'data/processed/{k}.json')
 data['meta']['version']=model['version'];data['meta']['notes']='付款国籍→收款政府的进出估算账；同一笔钱只合计一次。'
 data['meta']['flow_count']=len(data['flows']);data['flow_meta']['version']=model['version']
 data['meta']['flow_model_count']=len(models)
 data['meta']['destination_count']=len({r['receiver'] for r in data['flows']})
 members=next(x['members'] for x in models if x.get('destination')=='SCH')
 data['flow_meta']['schengen_members']=members
 data['fx']=fx
 data['flow_meta']['model_scope']={'government_visa_fees':True,'excluded':['IHS','SEVIS','biometrics','private_service','insurance','travel_authorizations'],'unquantified_destinations':[c for c in ['KOR','SAU','VNM'] if c not in {r['receiver'] for r in out}],'partial_destinations':['RUS','SGP','THA','MYS','ECU'],'missing_scope':'德国长期D签已纳入标准费值，其他申根成员长期签、俄纸签及未建模目的地仍缺；财政实收、队列费值与运行率按模型分别标记。'}
 data['flow_meta']['limitations']=['统一自然年费用估算；财年账目按已注明的平移／插值假设桥接。','来源按国籍建模；领馆所在地转换、未知来源及参数原样保留。','国家差额仅对应本账共同边集合；不代表政府利润或全部经济净收益。','边际情景范围并非联合概率区间，各边上下端不一定能够同时实现。','没有金额边表示未识别，不表示真实费用为0；有明确零额边才表示对应免费类别。']
 # Add disjoint controlled components after retaining each one's joint range.
 # Nationality-allocation envelopes never override fixed receipts.
 destination_ranges={}
 for r in component_ranges.values():
  key=r['receiver'],r['year']
  total=destination_ranges.setdefault(key,dict(receiver=key[0],year=key[1],amount_cny=0,lower_cny=0,upper_cny=0,range_method=r['range_method'],components=[]))
  for field in ['amount_cny','lower_cny','upper_cny']:total[field]+=r[field]
  total['components'].append(r)
 for total in destination_ranges.values():
  methods=list(dict.fromkeys(c['range_method'] for c in total['components']))
  total['range_method']='；'.join(methods) if len(total['components'])==1 else '独立费用范围相加：'+'；'.join(methods)
 for y in [2024,2025]:
  r=destination_ranges['USA',y];mult=.15 if y==2025 else 0
  r.update(lower_cny=r['amount_cny']*(1-mult),upper_cny=r['amount_cny']*(1+mult),range_method='2024财年插值实收控制；2025最近财年运行率±15%，国籍分配不改变总额')
  assert len(r['components'])==1,('US receipt scope requires one independent component',y)
  r['components'][0].update({k:r[k] for k in ['lower_cny','upper_cny','range_method']})
 data['flow_meta']['destination_ranges']=list(destination_ranges.values())
 annual=[]
 for y in sorted({r['year'] for r in data['flows']}):
  rr=[r for r in data['flows'] if r['year']==y]
  ranges=[r for r in destination_ranges.values() if r['year']==y]
  low=sum(r['lower_cny'] for r in ranges);high=sum(r['upper_cny'] for r in ranges)
  annual.append({'year':y,'amount_cny':sum(r['amount_cny'] for r in rr),'lower_cny':low,'upper_cny':high,'range_method':'目的地共同参数情景合计；固定总账校准项不累加国籍分配边际包络'})
 data['flow_meta']['annual_ranges']=annual
 for r in data['country_balances']:
  control=destination_ranges.get((r['country'],r['year']))
  if control:
   r['inflow_lower_cny']=control['lower_cny'];r['inflow_upper_cny']=control['upper_cny']
   r['net_lower_cny']=r['inflow_lower_cny']-r['outflow_upper_cny'];r['net_upper_cny']=r['inflow_upper_cny']-r['outflow_lower_cny']
   r['inflow_range_method']=control['range_method']
  r['inflow_available']=bool(r['inflow_edge_count']);r['outflow_available']=bool(r['outflow_edge_count'])
  r['zero_without_edges_meaning']='集合空和的记账0，不是该国真实免费或无收费；界面显示未识别'
 # Keep master files and product payload one generated version.
 (P/'country_balances.json').write_text(json.dumps(data['country_balances'],ensure_ascii=False,separators=(',',':')))
 (P/'flow_meta.json').write_text(json.dumps(data['flow_meta'],ensure_ascii=False,separators=(',',':')))
 for n in ['flows','country_balances']:dump_csv(n+'.csv',data[n])
 data['flow_models']=models
 data['claims']=[r for r in data.get('claims',[]) if r['claim_id']!='no_global_sum' and not r['claim_id'].startswith('modeled_global_')]
 for a in annual:
  data['claims'].append({'claim_id':f'modeled_global_{a["year"]}','title':f'{a["year"]}已建模签证费用流','text':f'{a["year"]}已建模费用流中心为{a["amount_cny"]/1e8:.2f}亿元人民币，每条费用边只合计一次。','source_ids':sorted({s for r in data['flows'] if r['year']==a['year'] for s in r.get('source_ids',[])}),'metric_ids':[f'flow_meta.annual_ranges.{a["year"]}'],'required_qualifier':'统一自然年工作模型；参数情景范围，非全世界实收；各年目的地与类别覆盖不同，年度总额不能直接解释为全球趋势；未知来源计入收到但未分配至各具体国付出。'})
 data['meta']['claim_count']=len(data['claims'])
 (P/'claims.json').write_text(json.dumps(data['claims'],ensure_ascii=False,separators=(',',':')))
 (P/'meta.json').write_text(json.dumps(data['meta'],ensure_ascii=False,separators=(',',':')))
 (ROOT/'app/data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
 (ROOT/'app/data.js').write_text('window.VISA_DATA='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n')
 print(json.dumps({'version':model['version'],'flows':len(data['flows']),'annual':annual,'china':[r for r in data['country_balances'] if r['country']=='CHN']},ensure_ascii=False)[:5000])
if __name__=='__main__':main()
