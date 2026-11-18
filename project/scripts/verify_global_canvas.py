#!/usr/bin/env python3
"""Focused browser acceptance for the fitted global visa-fee visualizations."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
EXE=(Path.home() / 'Library/Caches/ms-playwright/chromium-1254/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')

def close(a,b):return math.isclose(a,b,rel_tol=1e-9,abs_tol=.2)

GEOMETRY="""()=>{
 const svg=document.querySelector('.chart-stage .viz-main-svg'),s=svg?.getBoundingClientRect(),box=e=>{const b=e.getBoundingClientRect();return {text:e.textContent,left:b.left,right:b.right,top:b.top,bottom:b.bottom,width:b.width,height:b.height}},visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const text=svg?[...svg.querySelectorAll('text')].filter(visible).map(box):[];
 return {width:innerWidth,height:innerHeight,pageWidth:document.documentElement.scrollWidth,pageHeight:document.documentElement.scrollHeight,svg:s?.toJSON(),texts:text,clipped:s?text.filter(b=>b.left<s.left-2||b.right>s.right+2||b.top<s.top-2||b.bottom>s.bottom+2):[],invalidPaths:svg?[...svg.querySelectorAll('path[d]')].filter(e=>/NaN|Infinity/.test(e.getAttribute('d'))).length:0,arrows:svg?svg.querySelectorAll('[marker-end],[marker-start],marker').length:0};
}"""
REFERENCE="""()=>{const a=VISA_WORKBENCH.analysis,s=VISA_WORKBENCH.state,e=s.view==='single'?a.edges.filter(e=>s.singleMode==='origins'?e.destination===s.focusCountry:s.singleMode==='destinations'?e.origin===s.focusCountry:e.origin===s.focusCountry||e.destination===s.focusCountry):a.edges;return {total:e.reduce((t,e)=>t+e.amount,0),edges:e,entities:a.entities,year:s.year,view:s.view};}"""


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',default='http://127.0.0.1:18765/app/');parser.add_argument('--report',type=Path,default=ROOT/'docs/validation/global-canvas-local.json');args=parser.parse_args()
 report=args.report.resolve();report.parent.mkdir(parents=True,exist_ok=True);prefix=report.stem;checks=[];errors=[];screenshots=[];downloads=[];started=time.monotonic();versions={};assets=[]
 def check(name,passed,detail=None):
  checks.append(dict(check=name,passed=bool(passed),**({'detail':detail} if detail is not None else {})));print(('PASS ' if passed else 'FAIL ')+name,flush=True)
 def screenshot(page,label):
  p=report.parent/(prefix+'-'+label+'.png');page.screenshot(path=str(p),full_page=True);screenshots.append(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p))
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=str(EXE),headless=True);context=browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True,reduced_motion='reduce');page=context.new_page()
  page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
  try:
   page.goto(args.url,wait_until='domcontentloaded',timeout=120000);page.wait_for_function('!!window.VISA_WORKBENCH',timeout=120000)
   versions=page.evaluate('({data_version:VISA_WORKBENCH.index.meta.version,ui_version:VISA_WORKBENCH.index.meta.ui_version})');assets=page.locator('script[src]').evaluate_all('(es)=>es.map(e=>e.src)')
   codes=page.evaluate("VISA_WORKBENCH.index.entities.filter(e=>e.kind!=='unallocated').map(e=>e.code)")
   years=page.evaluate('[...new Set(VISA_WORKBENCH.index.records.map(r=>r[0]))].sort((a,b)=>a-b)');latest=max(years)
   def update(**patch):
    state=dict(countries=codes,focusCountry='USA',year=latest,flowScope='connected',spatialScale='country',view='chord',singleMode='radial',playing=False,motionMode='analysis',minAmount=0,showFree=True,maxNodes=24)
    state.update(patch);page.evaluate('(s)=>VISA_WORKBENCH.update(s)',state);page.wait_for_function('(s)=>Object.entries(s).every(([k,v])=>JSON.stringify(VISA_WORKBENCH.state[k])===JSON.stringify(v))',arg={k:v for k,v in state.items() if k!='countries'});page.wait_for_timeout(80)
   for width,height in [(1440,900),(390,844),(320,780)]:
    page.set_viewport_size({'width':width,'height':height})
    for view in ['chord','single','sankey','heatmap']:
     update(view=view);page.wait_for_selector('.viz-main-svg');ref=page.evaluate(REFERENCE);g=page.evaluate(GEOMETRY)
     check(f'{width}px global {view} fits viewport and all labels',g['pageWidth']<=width and g['pageHeight']<=height+1 and not g['clipped'],g)
     check(f'{width}px global {view} has finite geometry and no arrow markers',not g['invalidPaths'] and g['arrows']==0,{'invalidPaths':g['invalidPaths'],'arrows':g['arrows']})
     check(f'{width}px global {view} toolbar uses selected money',page.locator('.result-amount strong').inner_text()==page.evaluate('(v)=>{const f=new Intl.NumberFormat("zh-CN",{maximumFractionDigits:2});return Math.abs(v)>=1e8?f.format(v/1e8)+"亿元":Math.abs(v)>=1e4?f.format(v/1e4)+"万元":f.format(v)+"元"}',ref['total']))
     marks=page.locator('[data-origin][data-destination][data-amount]').evaluate_all('(es)=>es.map(e=>({origin:e.dataset.origin,destination:e.dataset.destination,amount:Number(e.dataset.amount)}))')
     positive=[m for m in marks if m['amount']>0]
     check(f'{width}px global {view} visualized amounts conserve selected fees',bool(positive) and close(sum(m['amount'] for m in positive),ref['total']),{'reference':ref['total'],'visualized':sum(m['amount'] for m in positive),'marks':len(positive)})
     if view in ['chord','single']:
      arcs=page.locator('[data-node-code][data-arc-start]').evaluate_all('(es)=>es.map(e=>({code:e.dataset.nodeCode,amount:Number(e.dataset.nodeWeight),start:Number(e.dataset.arcStart),end:Number(e.dataset.arcEnd)}))');shown={a['code'] for a in arcs};pairs={}
      for e in ref['edges']:
       k=(e['origin'] if e['origin'] in shown else '__OTHER__',e['destination'] if e['destination'] in shown else '__OTHER__');pairs[k]=pairs.get(k,0)+e['amount']
      money_weights={code:0. for code in shown};geo_weights={code:0. for code in shown};synthetic=max(ref['total']*.0005,1)
      for (origin,destination),amount in pairs.items():
       for code in [origin,destination]:money_weights[code]+=amount;geo_weights[code]+=amount or synthetic
      span=sum(a['end']-a['start'] for a in arcs);geo_total=sum(geo_weights.values())
      check(f'{width}px {view} circular allocations follow independent fee weights',bool(arcs) and all(close(a['amount'],money_weights[a['code']]) and abs((a['end']-a['start'])-span*geo_weights[a['code']]/geo_total)<1e-9 for a in arcs),{'nodes':len(arcs),'padding_radians':2*math.pi-span})
     if view in ['sankey','heatmap']:
      axes=page.evaluate('''()=>({sources:[...document.querySelectorAll('[data-side="source"],[data-axis="origin"]')].map(n=>({code:n.dataset.nodeCode,amount:Number(n.dataset.nodeAmount)})),targets:[...document.querySelectorAll('[data-side="target"],[data-axis="destination"]')].map(n=>({code:n.dataset.nodeCode,amount:Number(n.dataset.nodeAmount)}))})''')
      sources={n['code'] for n in axes['sources']};targets={n['code'] for n in axes['targets']};expected={}
      for e in ref['edges']:
       if e['amount']<=0:continue
       key=(e['origin'] if e['origin'] in sources else '__OTHER__',e['destination'] if e['destination'] in targets else '__OTHER__');expected[key]=expected.get(key,0)+e['amount']
      actual={(e['origin'],e['destination']):e['amount'] for e in positive}
      check(f'{width}px {view} independent directional aggregation matches every displayed edge',actual.keys()==expected.keys() and all(close(actual[k],v) for k,v in expected.items()),{'source_rows':len(sources),'target_columns':len(targets),'expected_pairs':len(expected),'displayed_pairs':len(actual)})
      check(f'{width}px {view} both axes retain the complete amount',close(sum(n['amount'] for n in axes['sources']),ref['total']) and close(sum(n['amount'] for n in axes['targets']),ref['total']))
     node=page.locator('[data-node-code]:not([data-node-code="__OTHER__"]):not([data-node-code="UNK"])').first
     if node.count():
      code=node.get_attribute('data-node-code');node.focus();page.keyboard.press('Enter');page.wait_for_timeout(30)
      selected=page.locator('[data-selected="true"]');check(f'{width}px {view} node keyboard selection stays in the current view',page.evaluate('VISA_WORKBENCH.state.view')==view and selected.count()>0 and selected.first.get_attribute('aria-pressed')=='true',{'code':code,'selected_marks':selected.count()})
      page.keyboard.press('Escape');page.wait_for_timeout(30);check(f'{width}px {view} Escape clears locked country selection',page.locator('[data-selected="true"]').count()==0)
      page.mouse.move(1,1);page.locator('body').click(position={'x':1,'y':1})
     if view=='heatmap':
      missing=page.locator('[data-missing="true"]').evaluate_all('(es)=>es.map(e=>({amount:e.getAttribute("data-amount"),label:e.textContent}))');free=page.locator('[data-free="true"]').evaluate_all('(es)=>es.map(e=>e.getAttribute("data-amount"))')
      check(f'{width}px heatmap distinguishes missing values from actual free fees',all(m['amount'] is None and '—' in m['label'] for m in missing) and all(float(v)==0 for v in free),{'missing':len(missing),'free':len(free)})
      check(f'{width}px heatmap preserves unknown payer separately',not any(e['origin']=='UNK' and e['amount']>0 for e in ref['edges']) or any(m['origin']=='UNK' for m in marks))
     svg=page.locator('.viz-main-svg');before=svg.locator(':scope > g').first.get_attribute('transform');r=svg.bounding_box();x=r['x']+r['width']-4;y=r['y']+4
     page.mouse.move(x,y);page.mouse.down();page.mouse.move(x-30,y+24,steps=3);page.mouse.up();page.mouse.wheel(0,80);page.wait_for_timeout(60);after=svg.locator(':scope > g').first.get_attribute('transform')
     check(f'{width}px {view} default canvas stays fitted when dragged or wheeled',before==after,{'before':before,'after':after})
     if width==1440 and view in ['sankey','heatmap']:
      other=page.locator('[data-node-code="__OTHER__"][data-side="source"],[data-node-code="__OTHER__"][data-axis="origin"]').first
      if other.count():
       members=[c for c in (other.get_attribute('data-members') or '').split(',') if c];other.focus();page.keyboard.press('Enter');panel=page.get_by_role('dialog',name='聚合国家成员',exact=True)
       check(f'{view} source aggregation opens the exact member list',panel.locator('.viz-member-list>button').count()==len(members) and 'UNK' not in members,{'expected_members':len(members),'displayed_members':panel.locator('.viz-member-list>button').count()})
       page.get_by_role('button',name='关闭国家成员',exact=True).click()
     screenshot(page,f'{width}-{view}')
   slider=page.get_by_role('slider',name='年份滑块',exact=True)
   check('phone timeline exposes the complete year range',slider.is_visible() and int(slider.get_attribute('min'))==0 and int(slider.get_attribute('max'))==len(years)-1,{'years':years})
   slider.focus();page.keyboard.press('Home');page.wait_for_timeout(50);check('phone year slider keyboard reaches the oldest actual year',page.evaluate('VISA_WORKBENCH.state.year')==min(years))
   page.keyboard.press('End');page.wait_for_timeout(50);check('phone year slider keyboard reaches the newest actual year',page.evaluate('VISA_WORKBENCH.state.year')==max(years))
   # Independent region aggregation must retain international fees within a region.
   saved_countries=page.evaluate('VISA_WORKBENCH.state.countries')
   for width,height in [(1440,900),(390,844)]:
    page.set_viewport_size({'width':width,'height':height})
    for view in ['chord','sankey','heatmap','compare']:
     update(view=view,spatialScale='region');ref=page.evaluate(REFERENCE);g=page.evaluate(GEOMETRY)
     check(f'{width}px regional {view} fits without invalid geometry',g['pageWidth']<=width and g['pageHeight']<=height+1 and not g['clipped'] and not g['invalidPaths'],g)
     check(f'{width}px regional {view} graph total equals original country fees',close(float(page.locator('[data-graph-total]').get_attribute('data-graph-total')),ref['total']))
     if view!='compare':
      region_index={'亚洲':0,'欧洲':1,'非洲':2,'美洲':3,'大洋洲':4,'其他地区':5};entities={e['code']:e for e in ref['entities']}
      def region_code(code):return 'UNK' if code=='UNK' else 'REG_'+str(region_index.get(entities.get(code,{}).get('region'),5))
      expected={}
      for e in ref['edges']:
       if e['amount']<=0:continue
       k=(region_code(e['origin']),region_code(e['destination']));expected[k]=expected.get(k,0)+e['amount']
      actual=page.locator('[data-origin][data-destination][data-amount]').evaluate_all('(es)=>es.map(e=>({origin:e.dataset.origin,destination:e.dataset.destination,amount:Number(e.dataset.amount)}))');positive={(e['origin'],e['destination']):e['amount'] for e in actual if e['amount']>0}
      check(f'{width}px regional {view} independently conserves every regional pair',positive.keys()==expected.keys() and all(close(positive[k],v) for k,v in expected.items()) and close(sum(positive.values()),ref['total']),{'expected_pairs':len(expected),'displayed_pairs':len(positive),'total':sum(positive.values())})
      domestic={k:v for k,v in expected.items() if k[0]==k[1]};check(f'{width}px regional {view} retains fees between countries of the same region',bool(domestic) and all(k in positive and close(positive[k],v) for k,v in domestic.items()),{'intra_region_pairs':len(domestic)})
      if width==1440:
       node=page.locator('[data-node-code^="REG_"]').first;node.focus();page.keyboard.press('Enter');panel=page.get_by_role('dialog',name='聚合国家成员',exact=True);labels=panel.locator('.viz-member-list>button>span').all_text_contents();check(f'{view} regional node opens actual country members',bool(labels) and not any('REG_' in label for label in labels) and page.locator('.evidence-card').count()==0,{'members':len(labels)})
       page.get_by_role('button',name='关闭国家成员',exact=True).click()
       route=page.locator('[data-origin^="REG_"][data-destination^="REG_"][data-amount]').first;route.focus();page.keyboard.press('Enter');panel=page.get_by_role('dialog',name='聚合国家成员',exact=True);check(f'{view} regional connection opens countries instead of an invalid route query',panel.locator('.viz-member-list>button').count()>0 and page.locator('.evidence-card').count()==0);page.get_by_role('button',name='关闭国家成员',exact=True).click()
     check(f'{width}px regional {view} preserves the country selection',page.evaluate('VISA_WORKBENCH.state.countries')==saved_countries)
     screenshot(page,f'{width}-regional-{view}')
   update(view='single',spatialScale='region');check('single-country view keeps actual countries when region scale is selected',page.locator('[data-node-code^="REG_"]').count()==0 and page.locator('[data-chart="single-chord"]').count()==1)
   # Use real country-picker controls and keyboard, not only the programmatic API.
   page.set_viewport_size({'width':1440,'height':900});update(countries=['CHN','USA','CAN'],view='chord')
   page.get_by_role('button',name='选择国家',exact=True).click();page.get_by_role('textbox',name='搜索国家',exact=True).fill('CHN')
   option=page.locator('.country-option').filter(has_text='CHN').first;check('country picker exposes selected state',option.get_attribute('aria-pressed')=='true' and 'selected' in option.get_attribute('class'))
   option.focus();page.keyboard.press('Enter');check('keyboard removes selected country',option.get_attribute('aria-pressed')=='false' and 'CHN' not in page.evaluate('VISA_WORKBENCH.state.countries'))
   page.keyboard.press('Enter');check('keyboard restores selected country',option.get_attribute('aria-pressed')=='true' and 'CHN' in page.evaluate('VISA_WORKBENCH.state.countries'))
   page.get_by_role('textbox',name='搜索国家',exact=True).fill('');page.get_by_role('button',name='仅看已选',exact=True).click();check('country picker selected-only filter shows precisely the selection',page.locator('.country-option').count()==3 and page.locator('.country-option[aria-pressed="false"]').count()==0)
   screenshot(page,'country-selection');page.get_by_role('button',name='关闭面板',exact=True).click()
   page.get_by_role('button',name='取消选择中国',exact=True).click();check('visible country chip removes only its own country','CHN' not in page.evaluate('VISA_WORKBENCH.state.countries') and set(page.evaluate('VISA_WORKBENCH.state.countries'))=={'USA','CAN'})
   # All real years remain individually navigable; oldest year must contain actual data.
   update(view='chord',year=min(years));reference=page.evaluate(REFERENCE);check('oldest selectable year uses actual nonempty evidence',reference['total']>0 and bool(reference['edges']),{'year':min(years),'edges':len(reference['edges']),'total':reference['total']})
   labels=page.locator('.year-rail button').evaluate_all('(es)=>es.map(e=>e.title)');check('timeline represents every actual data year',len(labels)==len(years) and all(any(str(y) in label for label in labels) for y in years),{'years':years,'labels':labels})
   # Current global heatmap SVG download must preserve metadata and actual view geometry.
   update(view='heatmap');ref=page.evaluate(REFERENCE);page.locator('.export-button').click()
   with page.expect_download(timeout=30000) as event:page.get_by_role('button',name='图形 SVG',exact=True).click()
   d=event.value;p=report.parent/(prefix+'-heatmap.svg');d.save_as(p);raw=p.read_bytes();xml=ET.fromstring(raw);ns='{http://www.w3.org/2000/svg}';meta=json.loads(xml.find(ns+'metadata').text)
   check('actual global heatmap SVG preserves selected amount and state',meta['state']['view']=='heatmap' and close(meta['amount_cny'],ref['total']) and len(raw)>1000,{'metadata_amount':meta['amount_cny'],'expected':ref['total'],'bytes':len(raw)})
   downloads.append({'path':str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()});page.get_by_role('button',name='关闭面板',exact=True).click()
   check('browser has no runtime or console errors',not errors,errors)
  except Exception as exc:
   check('focused validation completed',False,str(exc));screenshot(page,'failure')
  browser.close()
 result={'timestamp':datetime.now(timezone.utc).isoformat(),'url':args.url,**versions,'loaded_scripts':assets,'passed':bool(checks) and all(c['passed'] for c in checks),'elapsed_seconds':round(time.monotonic()-started,2),'checks':checks,'errors':errors,'screenshots':screenshots,'downloads':downloads,'scope':'Global graph amount conservation, arrow-free fitted canvas, real country/keyboard selection, actual timeline years and global SVG at desktop and two phone widths.'}
 report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[c for c in checks if not c['passed']],'report':str(report)},ensure_ascii=False),flush=True);return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
