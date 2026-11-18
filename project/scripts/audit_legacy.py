#!/usr/bin/env python3
from pathlib import Path
from bs4 import BeautifulSoup
import json,re,collections
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'data/research/legacy';out.mkdir(parents=True,exist_ok=True)
soup=BeautifulSoup((ROOT/'参考/白皮书快照.html').read_text(),'html.parser');tables=soup.find_all('table')
selected=[13,22,23,27,28,29,34,36];rows=[]
for i in selected:
 for n,tr in enumerate(tables[i].find_all('tr')):
  cells=[x.get_text(' ',strip=True) for x in tr.find_all(['td','th'])]
  route=next((x for x in cells[:2] if '→' in x),None)
  if not route or not tr.find_all('td'):continue
  m=re.match(r'(.+?)\s*→\s*([^\s·]+)',route)
  if not m:continue
  origin,dest=[x.strip() for x in m.groups()]
  rows.append(dict(table_index=i,row_index=n,origin=origin,destination=dest,pair_key=origin+'→'+dest,cells=cells))
by=collections.defaultdict(list)
for r in rows:by[r['pair_key']].append(r)
dups=[{'pair':k,'occurrences':v} for k,v in by.items() if len(v)>1]
result={'status':'legacy_214_coverage_withdrawn','table_indices':selected,'parsed_route_rows':len(rows),'distinct_pair_labels':len(by),'duplicate_pair_labels':dups,'rows':rows,'note':'Counts cover selected explicit route tables only; micro-flow prose and different measurement bases are not silently counted. A pair-label count is not a count of independent amount observations. Schengen aggregate and member destinations overlap.'}
(out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
(out/'tables-text.txt').write_text('\n\n'.join(f'TABLE {i}\n'+t.get_text(' ',strip=True) for i,t in enumerate(tables)))
print({k:v for k,v in result.items() if k not in ['rows','duplicate_pair_labels']});print('duplicates',[(x['pair'],len(x['occurrences'])) for x in dups])
