#!/usr/bin/env python3
"""Focused browser checks for visible historical coverage and the latest-year shortcut."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
EXE=(Path.home() / 'Library/Caches/ms-playwright/chromium-1254/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')
REFERENCE="""()=>{const i=VISA_WORKBENCH.index,s=VISA_WORKBENCH.state,a=VISA_WORKBENCH.analysis,m=new Set(i.schengenMembers),receivers=[...new Set(i.records.filter(r=>r[0]===s.year).map(r=>m.has(i.entities[r[2]].code)?'SCH':i.entities[r[2]].code))];return {year:s.year,countries:s.countries,flowScope:s.flowScope,receivers:[...new Set(a.edges.map(e=>e.destination))],globalReceivers:receivers,total:a.total,playing:s.playing};}"""
GEOMETRY="""()=>{
 const box=e=>{const b=e.getBoundingClientRect();return {text:e.textContent,left:b.left,right:b.right,top:b.top,bottom:b.bottom,width:b.width,height:b.height}},visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden',intersects=(a,b)=>a.left<b.right-.5&&a.right>b.left+.5&&a.top<b.bottom-.5&&a.bottom>b.top+.5;
 const svg=document.querySelector('.viz-main-svg'),s=svg&&box(svg),strip=document.querySelector('.year-coverage'),coverage=strip&&box(strip),note=document.querySelector('.viz-aggregation-note'),noteBox=note&&box(note),texts=svg?[...svg.querySelectorAll('text')].filter(visible).map(box):[],legend=svg?[...svg.querySelectorAll('.viz-node-label')].filter(visible).map(box):[],arcs=svg?[...svg.querySelectorAll('[data-arc-start]')].map(box):[];
 const clipped=s?texts.filter(b=>b.left<s.left-2||b.right>s.right+2||b.top<s.top-2||b.bottom>s.bottom+2):[];
 const coverageClipped=strip?[...strip.querySelectorAll('strong,span,button')].filter(visible).map(box).filter(b=>b.left<coverage.left-1||b.right>coverage.right+1||b.top<coverage.top-1||b.bottom>coverage.bottom+1):[];
 const overlap=innerWidth<600&&document.querySelector('[data-chart="chord"]')?legend.flatMap((a,i)=>legend.slice(i+1).filter(b=>intersects(a,b)).map(b=>[a.text,b.text])):[];
 const legendNoteOverlap=innerWidth<600&&noteBox?legend.filter(b=>intersects(b,noteBox)):[];
 const arcBottom=arcs.length?Math.max(...arcs.map(b=>b.bottom)):null;
 return {width:innerWidth,height:innerHeight,pageWidth:document.documentElement.scrollWidth,pageHeight:document.documentElement.scrollHeight,coverage,coverageClipped,svg:s,clipped,legendOverlap:overlap,legendNoteOverlap,arcBottom,legendTop:legend.length?Math.min(...legend.map(b=>b.top)):null};
}"""

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',default='http://127.0.0.1:18765/app/');parser.add_argument('--report',type=Path,default=ROOT/'docs/validation/year-coverage-local.json');args=parser.parse_args();report=args.report.resolve();report.parent.mkdir(parents=True,exist_ok=True);base=args.url.split('#')[0];prefix=report.stem;checks=[];errors=[];screenshots=[];versions={};assets=[];started=time.monotonic()
 def check(name,passed,detail=None):
  checks.append(dict(check=name,passed=bool(passed),**({'detail':detail} if detail is not None else {})));print(('PASS ' if passed else 'FAIL ')+name,flush=True)
 def attach(page):
  page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
 def boot(page,url):
  attach(page);page.goto(url,wait_until='domcontentloaded',timeout=120000);page.wait_for_function('!!window.VISA_WORKBENCH',timeout=120000)
 def screenshot(page,label):
  p=report.parent/(prefix+'-'+label+'.png');page.screenshot(path=str(p),full_page=True);screenshots.append(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p))
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=str(EXE),headless=True);context=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce');page=context.new_page()
  try:
   boot(page,base);versions=page.evaluate('({data_version:VISA_WORKBENCH.index.meta.version,ui_version:VISA_WORKBENCH.index.meta.ui_version})');assets=page.locator('script[src]').evaluate_all('(es)=>es.map(e=>e.src)');years=page.evaluate('[...new Set(VISA_WORKBENCH.index.records.map(r=>r[0]))].sort((a,b)=>a-b)');latest=max(years)
   check('new visitor starts at the latest actual data year',page.evaluate('VISA_WORKBENCH.state.year')==latest,{'latest_year':latest,'actual_year':page.evaluate('VISA_WORKBENCH.state.year')})
   americas=page.evaluate("VISA_WORKBENCH.index.entities.filter(e=>e.kind!=='unallocated'&&e.region==='美洲').map(e=>e.code)")
   historical=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce');page=historical.new_page();url=base+'#'+urlencode({'countries':','.join(americas),'year':2016,'flowScope':'connected','spatialScale':'country','view':'chord','focusCountry':'USA','singleMode':'radial'});boot(page,url)
   ref=page.evaluate(REFERENCE);check('explicit historical share URL preserves its selected year',ref['year']==2016 and set(ref['countries'])==set(americas) and ref['flowScope']=='connected',ref)
   def update(**patch):
    state=dict(countries=americas,focusCountry='USA',year=2016,flowScope='connected',spatialScale='country',view='chord',playing=False,motionMode='analysis',maxNodes=24)
    state.update(patch)
    if state['focusCountry'] not in state['countries']:state['focusCountry']=state['countries'][0]
    page.evaluate('(s)=>VISA_WORKBENCH.update(s)',state);page.wait_for_function('(s)=>Object.entries(s).every(([k,v])=>JSON.stringify(VISA_WORKBENCH.state[k])===JSON.stringify(v))',arg=state);page.wait_for_timeout(60)
   for width,height in [(1440,900),(390,844),(320,780)]:
    page.set_viewport_size({'width':width,'height':height});update();ref=page.evaluate(REFERENCE);strip=page.get_by_test_id('year-coverage')
    check(f'{width}px Americas 2016 has only the documented Schengen receiver',ref['receivers']==['SCH'] and ref['globalReceivers']==['SCH'],ref)
    check(f'{width}px historical coverage explains why country changes still lead to Schengen',strip.is_visible() and strip.get_attribute('data-year')=='2016' and strip.get_attribute('data-receivers')=='1' and '仅有申根短期费用数据' in strip.inner_text() and '更换来源国' in strip.inner_text(),strip.inner_text())
    g=page.evaluate(GEOMETRY);check(f'{width}px historical coverage and chord fit without label or legend collisions',g['pageWidth']<=width and g['pageHeight']<=height+1 and not g['coverageClipped'] and not g['clipped'] and not g['legendOverlap'] and not g['legendNoteOverlap'] and (width>=600 or g['arcBottom'] is None or g['legendTop']>g['arcBottom']),g);screenshot(page,f'{width}-historical')
    update(countries=['CHN','JPN']);changed=page.evaluate(REFERENCE);check(f'{width}px changing payer countries retains the true historical scope',changed['receivers']==['SCH'] and changed['year']==2016 and '仅有申根' in strip.inner_text(),changed)
    update();before=page.evaluate(REFERENCE);page.get_by_role('button',name=re.compile(r'查看\s*'+str(latest)+r'\s*多国数据')).click();page.wait_for_function('(year)=>VISA_WORKBENCH.state.year===year',arg=latest);after=page.evaluate(REFERENCE)
    check(f'{width}px latest-year shortcut preserves Americas and connected scope',after['countries']==before['countries'] and after['flowScope']==before['flowScope'] and after['year']==latest,after)
    check(f'{width}px the same Americas selection reveals thirteen latest-year receivers',len(after['receivers'])==13 and len(after['receivers'])>len(before['receivers']),{'before':before['receivers'],'after':after['receivers']})
    check(f'{width}px latest coverage separates whole-data coverage from selected receivers',int(strip.get_attribute('data-receivers'))==len(after['globalReceivers']) and len(after['globalReceivers'])>len(after['receivers']) and str(latest) in strip.inner_text(),strip.inner_text())
    for view in ['chord','sankey','heatmap']:
     update(view=view,year=latest);g=page.evaluate(GEOMETRY)
     check(f'{width}px latest {view} fits with the added coverage row',g['pageWidth']<=width and g['pageHeight']<=height+1 and not g['coverageClipped'] and not g['clipped'] and not g['legendOverlap'] and not g['legendNoteOverlap'] and (view!='chord' or width>=600 or g['arcBottom'] is None or g['legendTop']>g['arcBottom']),g);screenshot(page,f'{width}-latest-{view}')
    if width==1440:
     expected=page.evaluate("""()=>{const i=VISA_WORKBENCH.index,m=new Set(i.schengenMembers),years=[...new Set(i.records.map(r=>r[0]))].sort((a,b)=>a-b);return years.map(year=>({year,count:new Set(i.records.filter(r=>r[0]===year).map(r=>m.has(i.entities[r[2]].code)?'SCH':i.entities[r[2]].code)).size}));}""")
     buttons=page.locator('.year-rail button').evaluate_all('(es)=>es.map(e=>({title:e.title,label:e.querySelector(".year-coverage-label")?.textContent}))');check('desktop timeline labels every year with its independent whole-data coverage',len(buttons)==len(expected) and all(('全库'+str(r['count'])+'个收款方') in buttons[i]['title'] and buttons[i]['label']==('仅申根' if r['count']==1 else str(r['count'])+'收款方') for i,r in enumerate(expected)),{'expected':expected,'buttons':buttons})
   page.set_viewport_size({'width':1440,'height':900});update(year=latest);page.locator('.year-rail button').filter(has=page.locator('.full-year',has_text='2016')).click();check('historical year remains manually selectable after the shortcut',page.evaluate('VISA_WORKBENCH.state.year')==2016 and '仅有申根' in page.get_by_test_id('year-coverage').inner_text())
   # Real playback controls with a virtual browser clock, rather than waiting wall time.
   playback=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='no-preference');play=playback.new_page();boot(play,base);play.clock.install();play.evaluate('(s)=>VISA_WORKBENCH.update(s)',dict(countries=americas,flowScope='connected',view='chord',year=years[-2],playing=False,motionMode='analysis',playbackSpeed=1800));play.get_by_role('button',name='播放时间变化',exact=True).click();play.wait_for_function('VISA_WORKBENCH.state.playing===true');play.clock.fast_forward(1900);play.wait_for_function('(latest)=>VISA_WORKBENCH.state.year===latest&&VISA_WORKBENCH.state.playing===false',arg=latest,timeout=5000)
   check('playback reaches the latest year and stops',play.evaluate('VISA_WORKBENCH.state.year')==latest and not play.evaluate('VISA_WORKBENCH.state.playing'));play.clock.fast_forward(12000);check('stopped playback never wraps to the oldest year',play.evaluate('VISA_WORKBENCH.state.year')==latest and not play.evaluate('VISA_WORKBENCH.state.playing'))
   play.get_by_role('button',name='播放时间变化',exact=True).click();play.wait_for_function('(year)=>VISA_WORKBENCH.state.year===year&&VISA_WORKBENCH.state.playing===true',arg=years[-2]);check('starting playback at the newest year begins only the last two years',play.evaluate('VISA_WORKBENCH.state.year')==years[-2]);play.clock.fast_forward(1900);play.wait_for_function('(latest)=>VISA_WORKBENCH.state.year===latest&&VISA_WORKBENCH.state.playing===false',arg=latest,timeout=5000);check('last-two-year playback stops again at the latest year',play.evaluate('VISA_WORKBENCH.state.year')==latest and not play.evaluate('VISA_WORKBENCH.state.playing'))
   check('focused historical coverage checks have no runtime or console errors',not errors,errors)
  except Exception as exc:
   check('focused year coverage validation completed',False,str(exc));screenshot(page,'failure')
  browser.close()
 result={'timestamp':datetime.now(timezone.utc).isoformat(),'url':args.url,**versions,'loaded_scripts':assets,'passed':bool(checks) and all(c['passed'] for c in checks),'elapsed_seconds':round(time.monotonic()-started,2),'checks':checks,'errors':errors,'screenshots':screenshots,'scope':'Historical-only Schengen explanation, Americas latest-year shortcut preserving selection, explicit URL versus new-visitor year, whole-data coverage labels, non-wrapping playback and affected layouts at three widths.'}
 report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[c for c in checks if not c['passed']],'report':str(report)},ensure_ascii=False),flush=True);return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
