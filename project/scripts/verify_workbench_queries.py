#!/usr/bin/env python3
"""Compare the workbench query engine with the full evidence rows, and time it."""
from pathlib import Path
import json,sys
from collections import defaultdict
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/validation'
EXE=str(Path.home() / 'Library/Caches/ms-playwright/chromium-1254/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')
index=json.loads((ROOT/'app/data/index.json').read_text());rows=[]
years=sorted({r[0] for r in index['records']})
import gzip
for path in index['chunks'].values():rows.extend(json.loads(gzip.decompress((ROOT/'app/data'/path).read_bytes())))
checks=[]
def ck(label,passed,detail=None):
 checks.append(dict(check=label,passed=bool(passed),detail=detail))
 if not passed:print('FAIL',label,detail)
def reference(s):
 selected=set(s['countries']);members=set(index['schengenMembers'])
 def normal(c):return 'UNK' if c.startswith(('UNK','RAW_','OTHER','WORLD','TOTAL','UNALLOCATED')) else 'SCH' if s['regionMode']=='aggregate' and c in members else c
 if s['regionMode']=='aggregate' and selected&members:selected=(selected-members)|{'SCH'}
 if s['regionMode']=='members' and 'SCH' in selected:selected=(selected-{'SCH'})|members
 t=defaultdict(float);edges=defaultdict(float);count=0
 for r in rows:
  if r['year']!=s['year'] or r['display_group'] not in s['visaGroups']:continue
  a,b=normal(r['payer']),normal(r['receiver']);v=r['amount_cny']
  if a==b:continue
  t['globalTotal']+=v;f=a in selected;to=b in selected
  if f and to:t['internal']+=v
  elif to and a!='UNK':t['externalIn']+=v
  elif f:t['externalOut']+=v
  if to and a=='UNK':t['unallocated']+=v
  if (f and to) if s['flowScope']=='internal' else (f or to):edges[a+'|'+b]+=v;count+=1
 return {**t,'total':sum(edges.values()),'edgeCount':len(edges),'rowCount':count,'edges':dict(edges)}
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,executable_path=EXE);page=b.new_page(viewport={'width':1440,'height':900});page.goto('http://127.0.0.1:18765/app/');page.wait_for_function('!!window.VISA_WORKBENCH')
 base=page.evaluate('VISA_WORKBENCH.state');codes=[e['code'] for e in index['entities'] if e.get('kind')=='country_or_jurisdiction' and e['code'] not in index['schengenMembers']]
 scenarios=[]
 for n in [1,2,8,24,80]:
  countries=base['countries'] if n==8 else (['CHN','USA'] if n==2 else ['CHN'] if n==1 else list(dict.fromkeys(base['countries']+codes))[:n])
  for scope in ['internal','connected']:
   for year in years:scenarios.append({**base,'countries':countries,'year':year,'flowScope':scope})
 scenarios.extend([{**base,'countries':['CHN','FRA','DEU','SCH'],'regionMode':mode,'flowScope':scope} for mode in ['aggregate','members'] for scope in ['internal','connected']])
 scenarios.extend([{**base,'visaGroups':[group],'flowScope':'connected'} for group in index['groups']])
 expanded_scopes=set()
 for package in ['temporal_expansion_v2','uk_history_v2','africa_expansion_v3','asia_expansion_v3','africa_expansion_v6','asia_expansion_v6','europe_fiscal_v6','south_asia_expansion_v7']:
  native=json.loads((ROOT/f'data/estimates/{package}_flows.json').read_text())
  expanded_scopes.update((r['receiver'],r['year']) for r in native['flows'])
 scenarios.extend({**base,'countries':[code],'year':year,'flowScope':'connected'} for code,year in sorted(expanded_scopes))
 for i,s in enumerate(scenarios):
  r=page.evaluate('(s)=>{const a=VISA_WORKBENCH.analyzeSelection(s);return {...a,edgeAmounts:Object.fromEntries(a.edges.map(e=>[e.id,e.amount]))}}',s);expected=reference(s)
  diffs={k:[r[k] if k in ['total','globalTotal'] else r['totals'][k],expected.get(k,0)] for k in ['total','globalTotal','internal','externalIn','externalOut','unallocated','edgeCount','rowCount'] if abs((r[k] if k in ['total','globalTotal'] else r['totals'][k])-expected.get(k,0))>0.2}
  badedges=[key for key in set(r['edgeAmounts'])|set(expected['edges']) if abs(r['edgeAmounts'].get(key,0)-expected['edges'].get(key,0))>.2]
  ck(f'evidence agrees query {i+1}: {len(s["countries"])} countries/{s["year"]}/{s["flowScope"]}/{s["regionMode"]}/{s["visaGroups"]}',not diffs and not badedges,{'differences':diffs,'bad_edges':badedges[:5]})
 # Lazy evidence retrieval must expose exactly the rows represented by the current index.
 for s in [scenarios[0],scenarios[3],scenarios[7],scenarios[15],scenarios[19],scenarios[22]]:
  v=page.evaluate('async(s)=>{const a=VISA_WORKBENCH.analyzeSelection(s),rr=await VISA_WORKBENCH.selectedRows(s);return {query:a.total,rows:rr.length,count:a.totals.rowCount,sum:rr.reduce((n,r)=>n+r.amount_cny,0)}}',s)
  ck('lazy evidence matches graph '+str(len(s['countries']))+s['flowScope']+s['regionMode'],v['count']==v['rows'] and abs(v['query']-v['sum'])<.2,v)
 for code in sorted({code for code,year in expanded_scopes}):
  year=max(y for c,y in expanded_scopes if c==code)
  s={**base,'countries':[code],'year':year,'flowScope':'connected'}
  v=page.evaluate('async(s)=>{const a=VISA_WORKBENCH.analyzeSelection(s),rr=await VISA_WORKBENCH.selectedRows(s);return {query:a.total,rows:rr.length,count:a.totals.rowCount,sum:rr.reduce((n,r)=>n+r.amount_cny,0)}}',s)
  ck(f'{code} {year} expanded country loads the exact dated evidence',v['rows']>0 and v['count']==v['rows'] and abs(v['query']-v['sum'])<.2,v)
 empty=page.evaluate('(s)=>VISA_WORKBENCH.analyzeSelection({...s,countries:[]})',base);ck('empty selection has no edges',not empty['edges'] and empty['total']==0)
 one=page.evaluate('(s)=>VISA_WORKBENCH.analyzeSelection({...s,countries:["CHN"],flowScope:"internal"})',base);ck('single internal scope empty while national totals retained',not one['edges'] and one['countryTotals'][0]['incoming']>1e9)
 missing=page.evaluate('(s)=>VISA_WORKBENCH.analyzeSelection({...s,countries:["SAU"],flowScope:"connected"}).countryTotals[0]',base);ck('quantity-only receiver remains unidentified in the money ledger',not missing['incomingKnown'] and missing['net'] is None,missing)
 for code in ['KOR','VNM']:
  for year in [2024,2025]:
   v=page.evaluate('(s)=>VISA_WORKBENCH.analyzeSelection(s)',{**base,'countries':[code],'year':year,'flowScope':'connected'})
   expected=reference({**base,'countries':[code],'year':year,'flowScope':'connected'})
   ck(f'{code} {year} unallocated payer is included once in receiver inflow',v['countryTotals'][0]['incomingKnown'] and v['countryTotals'][0]['incoming']>0 and abs(v['countryTotals'][0]['incoming']-expected['unallocated'])<.2,{'incoming':v['countryTotals'][0]['incoming'],'unallocated':v['totals']['unallocated'],'expected':expected['unallocated']})
 for i,year in enumerate(years):
  a=page.evaluate('(s)=>VISA_WORKBENCH.analyzeSelection(s)',{**base,'year':year})
  target=years[i-1] if i else years[1]
  ck(f'{year} comparison uses the adjacent actual year',a.get('comparisonYear')==target,{'actual':a.get('comparisonYear'),'expected':target})
 historical=page.evaluate('async(s)=>{const a=VISA_WORKBENCH.analyzeSelection(s),r=await VISA_WORKBENCH.selectedRows(s);return {total:a.total,count:a.totals.rowCount,years:[...new Set(r.map(x=>x.year))],sum:r.reduce((n,x)=>n+x.amount_cny,0),rows:r.length};}',{**base,'countries':['CHN','SCH'],'year':years[0],'flowScope':'connected'})
 ck('historical selection lazy-loads the corresponding dated flows',historical['total']>0 and historical['years']==[years[0]] and historical['count']==historical['rows'] and abs(historical['total']-historical['sum'])<.2,historical)
 zero=[r for r in rows if r['amount_cny']==0];ck('known zero records preserved',len(zero)>0,{'zero_rows':len(zero)})
 timings=[]
 for n in [8,80]:
  s={**base,'countries':list(dict.fromkeys(base['countries']+codes))[:n],'flowScope':'connected'}
  samples=page.evaluate('(s)=>{for(let i=0;i<3;i++)VISA_WORKBENCH.analyzeSelection(s);return Array.from({length:12},()=>{const t=performance.now();VISA_WORKBENCH.analyzeSelection(s);return performance.now()-t;});}',s)
  ordered=sorted(samples);p95=ordered[-1];timings.append({'countries':n,'median_ms':ordered[len(ordered)//2],'max_ms':p95,'samples_ms':samples});ck(f'query time {n} countries',p95<(100 if n==8 else 300),timings[-1])
 b.close()
result={'passed':all(r['passed'] for r in checks),'checks':checks,'timings':timings,'reference':'full lazy evidence rows; independent Python edge aggregation','version':index['meta']['version']};(OUT/'workbench-query-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({'passed':result['passed'],'checks':len(checks),'timings':timings},ensure_ascii=False));sys.exit(0 if result['passed'] else 1)
