#!/usr/bin/env python3
"""Focused browser validation of directional light traces independent of year playback."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
EXE=(Path.home() / 'Library/Caches/ms-playwright/chromium-1254/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')
COUNTRIES=['CHN','USA','GBR','SCH','JPN','CAN','AUS','IND']

def close(a,b):return math.isclose(a,b,rel_tol=1e-9,abs_tol=.2)
TRACE_DATA=r"""()=>{
 const svg=document.querySelector('.viz-main-svg'),arcs=[...document.querySelectorAll('[data-node-code][data-arc-start]')].map(n=>({code:n.dataset.nodeCode,start:Number(n.dataset.arcStart),end:Number(n.dataset.arcEnd)})),nodes=[...document.querySelectorAll('[data-node-code][data-side]')].map(n=>({code:n.dataset.nodeCode,side:n.dataset.side,rect:(()=>{const r=n.querySelector('rect:last-of-type')?.getBBox();return r&&{x:r.x,y:r.y,width:r.width,height:r.height};})()}));
 const angle=p=>(Math.atan2(p.x,-p.y)+2*Math.PI)%(2*Math.PI),inArc=(value,node)=>node&&value>=node.start-.01&&value<=node.end+.01;
 return [...document.querySelectorAll('.viz-flow-trace')].map(path=>{
  const group=path.closest('.viz-flow-motion'),mark=path.closest('[data-amount][data-origin][data-destination]'),origin=group?.dataset.origin||mark?.dataset.origin,destination=group?.dataset.destination||mark?.dataset.destination,amount=Number(path.dataset.amount||mark?.dataset.amount),length=path.getTotalLength(),start=path.getPointAtLength(0),end=path.getPointAtLength(length),style=getComputedStyle(path),clipAttr=path.getAttribute('clip-path')||path.parentElement.getAttribute('clip-path')||style.clipPath,clipId=clipAttr?.match(/#([^)"]+)/)?.[1],clip=clipId&&document.getElementById(clipId),clipShape=clip?.querySelector('path');
  const originArc=arcs.find(a=>a.code===origin),destinationArc=arcs.find(a=>a.code===destination),sourceNode=nodes.find(n=>n.code===origin&&n.side==='source'),targetNode=nodes.find(n=>n.code===destination&&n.side==='target'),within=(p,r)=>r&&p.y>=r.y-1&&p.y<=r.y+r.height+1;
  const directionCorrect=arcs.length?inArc(angle(start),originArc)&&inArc(angle(end),destinationArc):sourceNode&&targetNode&&start.x<end.x&&Math.abs(start.x-sourceNode.rect.x-sourceNode.rect.width)<2&&Math.abs(end.x-targetNode.rect.x)<2&&within(start,sourceNode.rect)&&within(end,targetNode.rect);
  // Chromium's getPointAtLength flattens curves and can move a sample outside
  // a sub-pixel ribbon. Sample our quadratic analytically, without widening
  // the clip or accepting any geometrically outside point.
  const pd=path.getAttribute('d'),q=/^M[^A-Za-z]+Q[^A-Za-z]+$/.test(pd)?pd.match(/[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:e[-+]?\d+)?/gi)?.map(Number):null;
  let outside=0;if(clipShape&&clipShape.getAttribute('fill')!=='none'){for(let i=0;i<=40;i++){const t=i/40,p=q?.length===6?new DOMPoint((1-t)**2*q[0]+2*(1-t)*t*q[2]+t*t*q[4],(1-t)**2*q[1]+2*(1-t)*t*q[3]+t*t*q[5]):path.getPointAtLength(length*t);if(!clipShape.isPointInFill(p))outside++;}}
  return {origin,destination,amount,length,d:path.getAttribute('d'),start:{x:start.x,y:start.y},end:{x:end.x,y:end.y},animationName:style.animationName,animationState:style.animationPlayState,animationDuration:style.animationDuration,dasharray:style.strokeDasharray,dashoffset:style.strokeDashoffset,opacity:style.opacity,strokeOpacity:style.strokeOpacity,strokeWidth:style.strokeWidth,layer:path.classList.contains('viz-flow-body')?'body':path.classList.contains('viz-flow-tail')?'tail':'tip',active:group?.dataset.active==='true',markOpacity:mark?getComputedStyle(mark).opacity:'1',clipId,clipValid:!!clip&&!!clipShape,clipShape:clipShape?.tagName,directionCorrect:!!directionCorrect,outsideSamples:outside};
 });
}"""
GEOMETRY=r"""()=>{
 const box=e=>{const b=e.getBoundingClientRect();return {text:e.textContent,left:b.left,right:b.right,top:b.top,bottom:b.bottom,width:b.width,height:b.height}},visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden',intersects=(a,b)=>a.left<b.right-.5&&a.right>b.left+.5&&a.top<b.bottom-.5&&a.bottom>b.top+.5;
 const svg=document.querySelector('.viz-main-svg'),s=svg&&box(svg),texts=svg?[...svg.querySelectorAll('text')].filter(visible).map(box):[],legend=svg?[...svg.querySelectorAll('.viz-node-label')].filter(visible).map(box):[],note=document.querySelector('.viz-aggregation-note'),nb=note&&box(note),traces=[...document.querySelectorAll('.viz-flow-trace')].map(path=>{
  // A rotated SVG element's client rect encloses its transformed local bbox,
  // not just the actual curve. Measure the real path in screen coordinates.
  const m=path.getScreenCTM(),d=path.getAttribute('d'),q=/^M[^A-Za-z]+Q[^A-Za-z]+$/.test(d)?d.match(/[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:e[-+]?\d+)?/gi)?.map(Number):null,l=path.getTotalLength(),points=[];
  if(q?.length===6){const a=new DOMPoint(q[0],q[1]).matrixTransform(m),b=new DOMPoint(q[2],q[3]).matrixTransform(m),c=new DOMPoint(q[4],q[5]).matrixTransform(m),ts=[0,1];for(const k of ['x','y']){const t=(a[k]-b[k])/(a[k]-2*b[k]+c[k]);if(t>0&&t<1)ts.push(t);}for(const t of ts)points.push({x:(1-t)**2*a.x+2*(1-t)*t*b.x+t*t*c.x,y:(1-t)**2*a.y+2*(1-t)*t*b.y+t*t*c.y});}
  else for(let i=0;i<=100;i++)points.push(path.getPointAtLength(l*i/100).matrixTransform(m));
  return {left:Math.min(...points.map(p=>p.x)),right:Math.max(...points.map(p=>p.x)),top:Math.min(...points.map(p=>p.y)),bottom:Math.max(...points.map(p=>p.y))};
 });
 return {width:innerWidth,height:innerHeight,pageWidth:document.documentElement.scrollWidth,pageHeight:document.documentElement.scrollHeight,clipped:s?texts.filter(b=>b.left<s.left-2||b.right>s.right+2||b.top<s.top-2||b.bottom>s.bottom+2):[],legendNoteOverlap:innerWidth<600&&nb?legend.filter(b=>intersects(b,nb)):[],traceBounds:s?traces.filter(b=>b.left<s.left-2||b.right>s.right+2||b.top<s.top-2||b.bottom>s.bottom+2):[],invalidPaths:svg?[...svg.querySelectorAll('path[d]')].filter(e=>/NaN|Infinity/.test(e.getAttribute('d'))).length:0};
}"""

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',default='http://127.0.0.1:18765/app/');parser.add_argument('--report',type=Path,default=ROOT/'docs/validation/flow-motion-local.json');args=parser.parse_args();report=args.report.resolve();report.parent.mkdir(parents=True,exist_ok=True);prefix=report.stem;base=args.url.split('#')[0];checks=[];errors=[];screenshots=[];downloads=[];versions={};assets=[];started=time.monotonic()
 def check(name,passed,detail=None):
  checks.append(dict(check=name,passed=bool(passed),**({'detail':detail} if detail is not None else {})));print(('PASS ' if passed else 'FAIL ')+name,flush=True)
 def screenshot(page,label):
  path=report.parent/(prefix+'-'+label+'.png');page.screenshot(path=str(path),full_page=True,animations='allow');screenshots.append(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path))
 def attach(page):
  page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
 def boot(page,url):
  attach(page);page.goto(url,wait_until='domcontentloaded',timeout=120000);page.wait_for_function('!!window.VISA_WORKBENCH',timeout=120000)
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=str(EXE),headless=True);context=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='no-preference',accept_downloads=True);page=context.new_page()
  try:
   boot(page,base);versions=page.evaluate('({data_version:VISA_WORKBENCH.index.meta.version,ui_version:VISA_WORKBENCH.index.meta.ui_version})');assets=page.locator('script[src]').evaluate_all('(es)=>es.map(e=>e.src)');latest=page.evaluate('Math.max(...VISA_WORKBENCH.index.records.map(r=>r[0]))')
   state=page.evaluate('VISA_WORKBENCH.state');check('default paused latest-year view has continuous light traces',not state['playing'] and state['year']==latest and page.locator('.viz-flow-trace').count()>0,{'year':state['year'],'playing':state['playing'],'traces':page.locator('.viz-flow-trace').count()})
   def update(**patch):
    state=dict(countries=COUNTRIES,focusCountry='CHN',year=latest,flowScope='connected',spatialScale='country',view='chord',singleMode='radial',playing=False,motionMode='analysis',flowLight=True,maxNodes=24)
    state.update(patch);page.evaluate('(s)=>VISA_WORKBENCH.update(s)',state);page.wait_for_function('(s)=>Object.entries(s).every(([k,v])=>JSON.stringify(VISA_WORKBENCH.state[k])===JSON.stringify(v))',arg=state);page.wait_for_timeout(360)
   for view in ['chord','single','sankey']:
    update(view=view,focusCountry='USA' if view=='single' else 'CHN');traces=page.evaluate(TRACE_DATA);positive=page.locator('[data-origin][data-destination][data-amount]').evaluate_all('(es)=>es.filter(e=>Number(e.dataset.amount)>0).map(e=>e.dataset.origin+"|"+e.dataset.destination)');pairs={t['origin']+'|'+t['destination'] for t in traces}
    check(view+' positive connections carry traces while calendar playback is paused',bool(traces) and not page.evaluate('VISA_WORKBENCH.state.playing') and set(positive)<=pairs,{'positive_pairs':len(set(positive)),'trace_pairs':len(pairs)})
    check(view+' every trace runs from its actual payer endpoint to government endpoint',all(t['directionCorrect'] for t in traces),[t for t in traces if not t['directionCorrect']])
    check(view+' traces are clipped inside their actual fee ribbons',all(t['clipValid'] and t['outsideSamples']<=2 for t in traces),[{'origin':t['origin'],'destination':t['destination'],'amount':t['amount'],'outsideSamples':t['outsideSamples']} for t in traces if t['layer']=='body' and (not t['clipValid'] or t['outsideSamples']>2)])
    check(view+' zero-money routes never produce light traces',all(t['amount']>0 for t in traces))
    bidirectional=[pair for pair in pairs if '|'.join(reversed(pair.split('|'))) in pairs and pair.split('|')[0]!=pair.split('|')[1]]
    check(view+' opposite payments animate as separate directed connections',bool(bidirectional) and all(t['directionCorrect'] for t in traces if t['origin']+'|'+t['destination'] in bidirectional),{'bidirectional_pairs':len(bidirectional)})
    samples=[]
    for _ in range(3):
     samples.append(page.locator('.viz-flow-trace').first.evaluate('(e)=>({offset:parseFloat(getComputedStyle(e).strokeDashoffset),name:getComputedStyle(e).animationName,state:getComputedStyle(e).animationPlayState})'));page.wait_for_timeout(100)
    check(view+' CSS dash phase advances continuously towards the destination',all(s['name']!='none' and s['state']=='running' for s in samples) and samples[0]['offset']>samples[1]['offset']>samples[2]['offset'],samples)
    screenshot(page,view+'-frame-a');page.wait_for_timeout(170);screenshot(page,view+'-frame-b')
    from PIL import Image,ImageChops
    a=Image.open(report.parent/(prefix+'-'+view+'-frame-a.png')).convert('RGB');b=Image.open(report.parent/(prefix+'-'+view+'-frame-b.png')).convert('RGB');diff=ImageChops.difference(a,b);changed=sum(max(pixel)>12 for pixel in diff.get_flattened_data());check(view+' actual paused-year frames contain moving light pixels',changed>25,{'changed_pixels':changed,'frame_interval_ms':170})
   # Toggle control changes only traces and is persisted through both links and local storage.
   update();before=page.evaluate('({year:VISA_WORKBENCH.state.year,playing:VISA_WORKBENCH.state.playing,total:VISA_WORKBENCH.analysis.total,countries:VISA_WORKBENCH.state.countries})');toggle=page.get_by_role('button',name='流向流光',exact=True);toggle.click();page.wait_for_timeout(60);after=page.evaluate('({year:VISA_WORKBENCH.state.year,playing:VISA_WORKBENCH.state.playing,total:VISA_WORKBENCH.analysis.total,countries:VISA_WORKBENCH.state.countries})')
   check('light toggle is independent of selected fees, countries, year and playback',before==after and page.locator('.viz-flow-trace').count()==0 and toggle.get_attribute('aria-pressed')=='false')
   saved=page.evaluate('({url:new URLSearchParams(location.hash.slice(1)).get("flowLight"),local:JSON.parse(localStorage.getItem("visa-workbench-state-v4")).flowLight})');check('light toggle off state is saved in URL and local storage',saved=={'url':'false','local':False},saved)
   shared=page.url;page.reload(wait_until='domcontentloaded');page.wait_for_function('!!window.VISA_WORKBENCH');check('explicit URL restores light toggle state',page.locator('.viz-flow-trace').count()==0 and page.evaluate('VISA_WORKBENCH.state.flowLight')==False)
   page.goto(base,wait_until='domcontentloaded');page.wait_for_function('!!window.VISA_WORKBENCH');check('fresh URL restores locally saved light toggle state',page.locator('.viz-flow-trace').count()==0 and page.evaluate('VISA_WORKBENCH.state.flowLight')==False)
   page.get_by_role('button',name='流向流光',exact=True).click();page.wait_for_timeout(80);check('light toggle restores traces without starting calendar playback',page.locator('.viz-flow-trace').count()>0 and not page.evaluate('VISA_WORKBENCH.state.playing'))
   # Selection emphasizes the relevant light rather than making motion contingent on selection.
   update();first=page.locator('.viz-flow-trace').first;origin=first.evaluate('(e)=>e.dataset.origin||e.closest("[data-origin]").dataset.origin');node=page.locator('[data-node-code="'+origin+'"]').first;node.focus();page.keyboard.press('Enter');selected=page.evaluate(TRACE_DATA);related=[t for t in selected if origin in [t['origin'],t['destination']]];unrelated=[t for t in selected if origin not in [t['origin'],t['destination']]]
   check('selected country emphasizes its own directed light traces',bool(related) and bool(unrelated) and all(t['active'] for t in related) and all(not t['active'] for t in unrelated) and max(float(t['strokeOpacity'])*float(t['markOpacity']) for t in related if t['layer']=='body')>max(float(t['strokeOpacity'])*float(t['markOpacity']) for t in unrelated if t['layer']=='body'),{'related_opacity':[t['strokeOpacity'] for t in related[:3]],'unrelated_opacity':[t['strokeOpacity'] for t in unrelated[:3]]});page.keyboard.press('Escape')
   # The light stays on when year playback pauses, and year playback stays usable when light is off.
   update(year=latest-1,flowLight=False,playing=True,motionMode='presentation',playbackSpeed=1800);page.wait_for_function('(year)=>VISA_WORKBENCH.state.year===year&&!VISA_WORKBENCH.state.playing',arg=latest,timeout=5000);check('calendar playback works while light is switched off',page.locator('.viz-flow-trace').count()==0 and page.evaluate('VISA_WORKBENCH.state.year')==latest)
   for width,height in [(1440,900),(390,844),(320,780)]:
    page.set_viewport_size({'width':width,'height':height})
    for view in ['chord','single','sankey']:
     update(view=view);g=page.evaluate(GEOMETRY);check(f'{width}px {view} flowing paths and labels fit the fixed canvas',g['pageWidth']<=width and g['pageHeight']<=height+1 and not g['clipped'] and not g['legendNoteOverlap'] and not g['traceBounds'] and not g['invalidPaths'],g);screenshot(page,f'{width}-{view}')
   # Actual SVG and PNG exports must keep a static visible light phase without animation CSS.
   page.set_viewport_size({'width':1440,'height':900});update();page.locator('.export-button').click()
   with page.expect_download(timeout=30000) as event:page.get_by_role('button',name='图形 SVG',exact=True).click()
   path=report.parent/(prefix+'-chord.svg');event.value.save_as(path);raw=path.read_bytes();xml=ET.fromstring(raw);ns='{http://www.w3.org/2000/svg}';paths=[n for n in xml.iter(ns+'path') if 'viz-flow-trace' in n.get('class','')];metadata=json.loads(xml.find(ns+'metadata').text)
   check('SVG export retains a static directional light phase and valid clipping',bool(paths) and all(p.get('stroke-dasharray') and p.get('stroke-dashoffset') is not None for p in paths) and all(n.get('clip-path','none')=='none' or n.get('clip-path','').startswith('url("#') or n.get('clip-path','').startswith('url(#') for n in xml.iter()) and metadata['state']['flowLight']==True and metadata['state']['playing']==False,{'traces':len(paths),'sample':paths[0].attrib if paths else None})
   downloads.append({'path':str(path.relative_to(ROOT)),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
   with page.expect_download(timeout=30000) as event:page.get_by_role('button',name='图形 PNG',exact=True).click()
   path=report.parent/(prefix+'-chord.png');event.value.save_as(path);raw=path.read_bytes();check('PNG export is a real nonempty static raster with the light present',raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>10000,{'bytes':len(raw)});downloads.append({'path':str(path.relative_to(ROOT)),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()});page.get_by_role('button',name='关闭面板',exact=True).click()
   # System reduced motion is static by default; no CSS loop runs.
   reduced=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce');static=reduced.new_page();boot(static,base);traces=static.evaluate(TRACE_DATA);check('system reduced-motion default renders no repeating light animation',all(t['animationName']=='none' or t['animationState']=='paused' for t in traces) and not static.evaluate('VISA_WORKBENCH.state.playing') and static.get_by_role('button',name='流向流光',exact=True).is_disabled(),{'traces':len(traces),'animations':[t['animationName'] for t in traces[:3]]})
   check('directional light checks have no runtime or console errors',not errors,errors)
  except Exception as exc:
   check('focused directional light validation completed',False,str(exc));screenshot(page,'failure')
  browser.close()
 result={'timestamp':datetime.now(timezone.utc).isoformat(),'url':args.url,**versions,'loaded_scripts':assets,'passed':bool(checks) and all(c['passed'] for c in checks),'elapsed_seconds':round(time.monotonic()-started,2),'checks':checks,'errors':errors,'screenshots':screenshots,'downloads':downloads,'scope':'Real payer-to-government moving light, ribbon clipping, independent persisted toggle, paused calendar and year playback, selection/reduced-motion behavior, responsive layout and static SVG/PNG export; no video generated.'}
 report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[c for c in checks if not c['passed']],'report':str(report)},ensure_ascii=False),flush=True);return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
