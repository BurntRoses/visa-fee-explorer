#!/usr/bin/env python3
"""Actual Chromium media playback: time progression, rendered frames, end events."""
from pathlib import Path
import json,time
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'media/evidence';OUT.mkdir(exist_ok=True)
files=['flagship_vertical','flagship_horizontal','cut_refund','cut_uk_bill','cut_waiver']
with sync_playwright() as pw:
 paths=sorted((Path.home()/'Library/Caches/ms-playwright').glob('chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'),reverse=True)
 exe=pw.chromium.executable_path
 if not Path(exe).exists():exe=str(paths[0])
 b=pw.chromium.launch(headless=True,executable_path=exe,args=['--autoplay-policy=no-user-gesture-required'])
 pages=[]
 for name in files:
  p=b.new_page(viewport={'width':960,'height':800})
  p.goto((ROOT/f'media/exports/{name}.mp4').as_uri())
  p.locator('video').evaluate('(v)=>{v.muted=true;return v.play()}');pages.append((name,p))
 print('Five media players started at 1× speed.',flush=True)
 deadline=time.monotonic()+100
 while time.monotonic()<deadline:
  states=[p.locator('video').evaluate('(v)=>({t:v.currentTime,d:v.duration,ended:v.ended,error:v.error?.message||null,ready:v.readyState,frames:v.getVideoPlaybackQuality().totalVideoFrames})') for _,p in pages]
  if any(s['error'] for s in states):raise RuntimeError(states)
  if all(s['ended'] for s in states):break
  time.sleep(1)
 results=[]
 for (name,p),s in zip(pages,states):
  s.update(file=f'media/exports/{name}.mp4',playback_rate=p.locator('video').evaluate('(v)=>v.playbackRate'),actual_browser=b.version,method='HTMLVideoElement playback in real headless Chromium; muted playback checks rendering/decoding, audio technical checks separate')
  assert s['ended'] and s['frames']>100 and s['t']>=s['d']-.15,s
  # seek inside final encoded file for a visual inspection frame after full playback
  p.locator('video').evaluate('async (v)=>{await new Promise(r=>{v.addEventListener("seeked",r,{once:true});v.currentTime=Math.min(v.duration/2,35)});v.pause();}')
  p.screenshot(path=str(OUT/f'{name}_browser_playback.png'))
  results.append(s)
 b.close()
(OUT/'browser-playback.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps(results,ensure_ascii=False,indent=2),flush=True)
