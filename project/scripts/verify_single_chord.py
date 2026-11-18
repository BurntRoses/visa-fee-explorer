#!/usr/bin/env python3
"""Focused checks for the shared, weighted single-country chord diagrams."""
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
COUNTRIES=['CHN','USA','GBR','SCH','JPN','CAN','AUS','IND','KOR']
REFERENCE="""() => {
 const {state:s,analysis:a}=VISA_WORKBENCH, focus=s.focusCountry;
 const edges=a.edges.filter(e=>s.singleMode==='origins'?e.destination===focus:s.singleMode==='destinations'?e.origin===focus:e.origin===focus||e.destination===focus);
 const n=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}),money=v=>Math.abs(v)>=1e8?n.format(v/1e8)+'亿元':Math.abs(v)>=1e4?n.format(v/1e4)+'万元':n.format(v)+'元';
 return {focus,mode:s.singleMode,total:edges.reduce((v,e)=>v+e.amount,0),edges,formatted:money(edges.reduce((v,e)=>v+e.amount,0)),analysisTotal:a.total,unrelated:a.edges.filter(e=>e.origin!==focus&&e.destination!==focus).length,names:Object.fromEntries(a.entities.map(e=>[e.code,e.name]))};
}"""
MARKS="""() => ({chart:document.querySelector('[data-chart]')?.getAttribute('data-chart'),graph:Number(document.querySelector('[data-graph-total]')?.getAttribute('data-graph-total')),toolbar:document.querySelector('.result-amount strong')?.textContent,arcs:[...document.querySelectorAll('[data-node-code]')].map(e=>({code:e.dataset.nodeCode,weight:Number(e.dataset.nodeWeight),start:Number(e.dataset.arcStart),end:Number(e.dataset.arcEnd)})),ribbons:[...document.querySelectorAll('.viz-chord-link')].map(e=>({origin:e.dataset.origin,destination:e.dataset.destination,amount:Number(e.dataset.amount),d:e.querySelector('path')?.getAttribute('d')}))})"""
GEOMETRY="""() => {
 const box=e=>{const b=e.getBoundingClientRect();return {left:b.left,right:b.right,top:b.top,bottom:b.bottom,width:b.width,height:b.height};},svg=document.querySelector('.chart-stage .viz-main-svg'),r=svg&&box(svg),visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const clipped=svg?[...svg.querySelectorAll('text')].filter(visible).map(e=>({text:e.textContent,...box(e)})).filter(b=>b.left<r.left-2||b.right>r.right+2||b.top<r.top-2||b.bottom>r.bottom+2):[];
 return {width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,documentHeight:document.documentElement.scrollHeight,clipped,svg:r};
}"""

def close(a,b):return math.isclose(a,b,rel_tol=1e-10,abs_tol=.2)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:18765/app/');p.add_argument('--report',type=Path,default=ROOT/'docs/validation/single-chord-local.json');args=p.parse_args()
 report=args.report.resolve();report.parent.mkdir(parents=True,exist_ok=True);prefix=report.stem;checks=[];errors=[];screenshots=[];downloads=[];started=time.monotonic();version=ui=None;assets=[]
 def check(name,passed,detail=None):
  checks.append(dict(check=name,passed=bool(passed),**({'detail':detail} if detail is not None else {})));print(('PASS ' if passed else 'FAIL ')+name,flush=True)
 def screenshot(page,label):
  path=report.parent/(prefix+'-'+label+'.png');page.screenshot(path=str(path),full_page=True);screenshots.append(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path))
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=str(EXE),headless=True);context=browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True,reduced_motion='reduce');page=context.new_page()
  page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
  page.goto(args.url,wait_until='domcontentloaded',timeout=120000);page.wait_for_function('!!window.VISA_WORKBENCH',timeout=120000)
  version,ui=page.evaluate('[VISA_WORKBENCH.index.meta.version,VISA_WORKBENCH.index.meta.ui_version]');assets=page.locator('script[src]').evaluate_all('(es)=>es.map(e=>e.src)')
  def update(**patch):
   state=dict(countries=COUNTRIES,focusCountry='CHN',year=2024,flowScope='connected',regionMode='aggregate',view='single',singleMode='radial',direction='both',playing=False,motionMode='analysis',showFree=True,minAmount=0,maxNodes=12,**{})
   state.update(patch);page.evaluate('(s)=>VISA_WORKBENCH.update(s)',state);page.wait_for_function('(s)=>Object.entries(s).every(([k,v])=>JSON.stringify(VISA_WORKBENCH.state[k])===JSON.stringify(v))',arg=state);page.wait_for_timeout(60)
  def scenario(label,**patch):
   update(**patch);ref=page.evaluate(REFERENCE);m=page.evaluate(MARKS)
   if not ref['edges']:
    check(label+' empty direction draws no positive ribbon',not m['ribbons'] and page.locator('.viz-empty,.canvas-empty').count()>0,{'expected':ref['total'],'chart':m['chart']});check(label+' toolbar is zero',m['toolbar']==ref['formatted']);return ref,m
   page.wait_for_selector('[data-chart="single-chord"]');m=page.evaluate(MARKS)
   check(label+' reuses a chord in the single view',m['chart']=='single-chord' and bool(m['arcs']))
   check(label+' filtered graph, ribbons and toolbar match independent focus sum',close(m['graph'],ref['total']) and close(sum(e['amount'] for e in m['ribbons']),ref['total']) and m['toolbar']==ref['formatted'],{'reference':ref['total'],'graph':m['graph'],'ribbons':sum(e['amount'] for e in m['ribbons']),'toolbar':m['toolbar']})
   check(label+' every ribbon touches the focal country',all(ref['focus'] in (e['origin'],e['destination']) for e in m['ribbons']))
   check(label+' mode filters ribbon direction',all(e['destination']==ref['focus'] for e in m['ribbons']) if ref['mode']=='origins' else all(e['origin']==ref['focus'] for e in m['ribbons']) if ref['mode']=='destinations' else True)
   codes={a['code'] for a in m['arcs']};mapped={}
   for e in ref['edges']:
    key=(e['origin'] if e['origin'] in codes else '__OTHER__',e['destination'] if e['destination'] in codes else '__OTHER__');mapped[key]=mapped.get(key,0)+e['amount']
   actual={(e['origin'],e['destination']):e['amount'] for e in m['ribbons']};positive={k:v for k,v in mapped.items() if v>0}
   check(label+' aggregation retains all directed positive amounts',set(actual)==set(positive) and all(close(actual[k],v) for k,v in positive.items()))
   synthetic=max(ref['total']*.0005,1);weights={c:0. for c in codes};geometry_weights={c:0. for c in codes}
   for (a,b),value in mapped.items():
    weights[a]+=value;weights[b]+=value;geometry_weights[a]+=value or synthetic;geometry_weights[b]+=value or synthetic
   span=sum(a['end']-a['start'] for a in m['arcs']);geo_total=sum(geometry_weights.values())
   deviations=[{'code':a['code'],'actual':a['end']-a['start'],'expected':span*geometry_weights[a['code']]/geo_total} for a in m['arcs'] if abs((a['end']-a['start'])-span*geometry_weights[a['code']]/geo_total)>1e-9]
   check(label+' arc spans follow directed fee weights excluding equal padding',not deviations and all(close(a['weight'],weights[a['code']]) for a in m['arcs']),{'failures':deviations,'zero_route_geometry':synthetic,'angular_padding':2*math.pi-span})
   check(label+' focal node cannot be aggregated',ref['focus'] in codes)
   has_unknown=any(e['origin']=='UNK' or e['destination']=='UNK' for e in ref['edges']);check(label+' unknown payer stays separate from Other',not has_unknown or 'UNK' in codes)
   check(label+' all ribbon paths are finite filled areas',all(e['d'] and 'NaN' not in e['d'] and 'Infinity' not in e['d'] and e['d'].startswith('M') and e['d'].endswith('Z') for e in m['ribbons']))
   return ref,m
  try:
   for scope in ['internal','connected']:
    for mode in ['radial','origins','destinations']:scenario(f'CHN {scope} {mode}',flowScope=scope,singleMode=mode)
   both,_=scenario('radial old direction incoming',direction='incoming');out,_=scenario('radial old direction outgoing',direction='outgoing');check('flow mode remains bidirectional with legacy hidden direction state',close(both['total'],out['total']))
   for mode in ['radial','origins','destinations']:
    update(singleMode=mode)
    timeline=page.evaluate("""()=>{const s=VISA_WORKBENCH.state,years=[...new Set(VISA_WORKBENCH.index.records.map(r=>r[0]))].sort((a,b)=>a-b),fmt=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}),money=v=>Math.abs(v)>=1e8?fmt.format(v/1e8)+'亿元':Math.abs(v)>=1e4?fmt.format(v/1e4)+'万元':fmt.format(v)+'元';return years.map(year=>{const a=VISA_WORKBENCH.analyzeSelection({...s,year}),ee=a.edges.filter(e=>s.singleMode==='origins'?e.destination===s.focusCountry:s.singleMode==='destinations'?e.origin===s.focusCountry:e.origin===s.focusCountry||e.destination===s.focusCountry),total=ee.reduce((v,e)=>v+e.amount,0),button=[...document.querySelectorAll('.year-rail button')].find(e=>e.querySelector('.full-year')?.textContent===String(year)),bar=button?.querySelector('.year-bar');return {year,total,receivers:new Set(ee.map(e=>e.destination)).size,expectedText:money(total),title:button?.title,height:bar&&parseFloat(bar.style.height)};});}""")
    maximum=max(r['total'] for r in timeline)
    check(mode+' timeline uses focal amounts, recipient counts and relative bar weights',all(str(r['receivers'])+'个收款方' in r['title'] and r['expectedText'] in r['title'] and abs(r['height']-max(2,r['total']/max(maximum,1)*24))<.001 for r in timeline),timeline)
   ref,m=scenario('CHN aggregation',singleMode='radial');check('multi-country input contains excluded unrelated edges',ref['unrelated']>0 and not close(ref['analysisTotal'],ref['total']))
   if '__OTHER__' in {a['code'] for a in m['arcs']}:
    shown={a['code'] for a in m['arcs']};hidden={e['origin'] for e in ref['edges']}|{e['destination'] for e in ref['edges']};hidden-=shown
    page.locator('.viz-aggregation-note button').click();panel=page.get_by_role('dialog',name='聚合国家成员',exact=True);buttons=panel.locator('.viz-member-list>button')
    rows=buttons.evaluate_all('(es)=>es.map(e=>({name:e.querySelector("span")?.textContent?.trim(),values:[...e.querySelectorAll("b")].map(b=>b.textContent)}))')
    check('Other expands the exact hidden country membership',len(rows)==len(hidden) and {r['name'] for r in rows}=={ref['names'].get(c,c) for c in hidden} and 'UNK' not in hidden,{'hidden':sorted(hidden),'displayed_members':len(rows)})
    expected_members=page.evaluate('''(ref)=>{const f=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}),money=v=>Math.abs(v)>=1e8?f.format(v/1e8)+'亿元':Math.abs(v)>=1e4?f.format(v/1e4)+'万元':f.format(v)+'元';return Object.fromEntries([...new Set(ref.edges.flatMap(e=>[e.origin,e.destination]))].map(code=>{const incoming=ref.edges.filter(e=>e.destination===code),outgoing=ref.edges.filter(e=>e.origin===code);return [ref.names[code]||code,[incoming.length?money(incoming.reduce((s,e)=>s+e.amount,0)):'未识别',outgoing.length?money(outgoing.reduce((s,e)=>s+e.amount,0)):'未识别']]}))}''',ref)
    check('Other member amounts use only focus-relative fee edges',all(r['values']==expected_members[r['name']] for r in rows))
    panel.get_by_role('button',name='关闭国家成员',exact=True).click()
   screenshot(page,'desktop')
   # A real, unaggregated ribbon must open exactly the amount encoded on it.
   link=page.locator('.viz-chord-link:not([data-origin="__OTHER__"]):not([data-destination="__OTHER__"])').first
   route_amount=float(link.get_attribute('data-amount'));route_label=link.get_attribute('aria-label');link.focus();page.keyboard.press('Enter');page.wait_for_selector('.evidence-card',timeout=120000)
   expected_text=page.evaluate('(v)=>{const f=new Intl.NumberFormat("zh-CN",{maximumFractionDigits:2});return Math.abs(v)>=1e8?f.format(v/1e8)+"亿元":Math.abs(v)>=1e4?f.format(v/1e4)+"万元":f.format(v)+"元"}',route_amount)
   check('keyboard ribbon activation opens matching route evidence',page.locator('.detail-total strong').inner_text()==expected_text,{'route':route_label,'amount':route_amount,'drawer':page.locator('.detail-total strong').inner_text()});page.get_by_role('button',name='关闭面板',exact=True).click()
   # Actual SVG download: focal mode sum differs from the full selection amount.
   ref,m=scenario('CHN SVG origins',singleMode='origins');page.locator('.export-button').click()
   with page.expect_download(timeout=30000) as event:page.get_by_role('button',name='图形 SVG',exact=True).click()
   download=event.value;path=report.parent/(prefix+'-origins.svg');download.save_as(path);raw=path.read_bytes();xml=ET.fromstring(raw);ns='{http://www.w3.org/2000/svg}';meta=json.loads(xml.find(ns+'metadata').text)
   title=xml.find(ns+'title').text;check('SVG download carries focal mode, amount and title',meta['state']['view']=='single' and meta['state']['focusCountry']=='CHN' and meta['state']['singleMode']=='origins' and close(meta['amount_cny'],ref['total']) and '中国' in title and '来源' in title,{'metadata_amount':meta['amount_cny'],'expected':ref['total'],'title':title});downloads.append({'path':str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()});page.get_by_role('button',name='关闭面板',exact=True).click()
   for focus in ['KOR','SCH']:
    for mode in ['radial','origins','destinations']:scenario(f'{focus} connected {mode}',focusCountry=focus,singleMode=mode)
   scenario('KOR 2015 empty incoming',focusCountry='KOR',year=2015,singleMode='origins')
   update(countries=['CHN'],flowScope='internal');check('single country internal selection remains empty',page.locator('.canvas-empty').count()==1 and page.get_by_role('button',name='查看全球往来',exact=True).is_visible())
   first,_=scenario('year2024',singleMode='radial');old=page.locator('[data-node-code]').evaluate_all('(es)=>es.map(e=>[e.dataset.nodeCode,e.dataset.arcStart,e.dataset.arcEnd])');second,_=scenario('year2025',year=2025,singleMode='radial');new=page.locator('[data-node-code]').evaluate_all('(es)=>es.map(e=>[e.dataset.nodeCode,e.dataset.arcStart,e.dataset.arcEnd])');check('year change reallocates actual amounts and geometry',not close(first['total'],second['total']) and old!=new)
   page.emulate_media(reduced_motion='reduce');page.evaluate("VISA_WORKBENCH.update({playing:true,motionMode:'presentation'})");page.wait_for_function('VISA_WORKBENCH.state.playing===false');check('reduced motion stops playback and suppresses flow traces',page.locator('.visa-visualization.reduce-motion').count()==1 and page.locator('.viz-flow-trace').count()==0)
   for width,height in [(1440,900),(390,844),(320,780)]:
    page.set_viewport_size({'width':width,'height':height})
    for focus in ['CHN','SCH']:
     for mode in ['radial','origins','destinations']:
      scenario(f'{width}px {focus} {mode}',focusCountry=focus,singleMode=mode,maxNodes=12);g=page.evaluate(GEOMETRY);check(f'{width}px {focus} {mode} labels fit and page has no overflow',g['documentWidth']<=width and g['documentHeight']<=height+1 and not g['clipped'],g)
      if focus=='CHN' and mode=='radial' and width in [390,320]:screenshot(page,f'mobile-{width}')
   check('no runtime or console errors',not errors,errors)
  except Exception as exc:
   check('focused validation completed',False,str(exc));screenshot(page,'failure')
  browser.close()
 result={'timestamp':datetime.now(timezone.utc).isoformat(),'url':args.url,'data_version':version,'ui_version':ui,'loaded_scripts':assets,'passed':all(c['passed'] for c in checks),'elapsed_seconds':round(time.monotonic()-started,2),'checks':checks,'errors':errors,'screenshots':screenshots,'downloads':downloads,'scope':'Shared single-country chord weights, amount scopes, unknown/Other attribution, route evidence, SVG, year and reduced-motion behavior, desktop/mobile geometry.'}
 report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[c for c in checks if not c['passed']],'report':str(report)},ensure_ascii=False),flush=True);return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
