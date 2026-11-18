#!/usr/bin/env python3
"""Build the React/D3 workbench and self-contained offline distribution."""
from pathlib import Path
import base64,gzip,hashlib,json,os,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];A=ROOT/'app';W=A/'workbench';D=A/'dist'
subprocess.run([sys.executable,str(ROOT/'scripts/build_workbench_data.py')],cwd=ROOT,check=True)
node_dir=(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin')
env={**os.environ,'PATH':str(node_dir)+os.pathsep+os.environ.get('PATH','')}
node=shutil.which('node',path=env['PATH'])
if not node:raise SystemExit('Node.js is required to rebuild the frontend. The offline HTML needs no runtime.')
for cli,args in [('typescript/bin/tsc',['--noEmit']),('vite/bin/vite.js',['build'])]:
 path=W/'node_modules'/cli
 if not path.exists():raise SystemExit('Install locked frontend dependencies once: cd app/workbench && pnpm install --frozen-lockfile')
 subprocess.run([node,str(path),*args],cwd=W,env=env,check=True)
B=W/'build';html=(B/'index.html').read_text()
legacy=A/'legacy-r2'
if (A/'app.js').exists() and not legacy.exists():
 legacy.mkdir()
 for name in ['index.html','app.js','styles.css']:
  if (A/name).exists():shutil.copyfile(A/name,legacy/name)
 (legacy/'README.md').write_text('r2 历史界面源文件。现行产品入口为 ../index.html；重建与完整数据使用当前工作台流程。\n')
for target in [A,D]:
 target.mkdir(exist_ok=True)
 for directory in ['assets','data']:
  dest=target/directory
  if dest.exists():shutil.rmtree(dest)
  shutil.copytree(B/directory,dest)
 (target/'index.html').write_text(html if target==A else html.replace('<head>','<head><base href="../">'))
index=(B/'data/index.json').read_text()
chunks={p.name.removesuffix('.json.gz'):base64.b64encode(p.read_bytes()).decode() for p in sorted((B/'data/chunks').glob('*.json.gz'))}
contexts={p.name.removesuffix('.json.gz'):base64.b64encode(p.read_bytes()).decode() for p in sorted((B/'data/context').glob('*.json.gz'))}
full=base64.b64encode((B/'data/full-data.json.gz').read_bytes()).decode()
standalone=html
for match in list(re.finditer(r'<link[^>]+href="(\./assets/[^"]+\.css)"[^>]*>',standalone)):
 standalone=standalone.replace(match.group(0),'<style>'+(B/match.group(1)).read_text()+'</style>')
for match in list(re.finditer(r'<script[^>]+src="(\./assets/[^"]+\.js)"[^>]*></script>',standalone)):
 # One inline module has no imports; it can execute under file://.
 script=(B/match.group(1)).read_text().replace('</script','<\\/script')
 standalone=standalone.replace(match.group(0),'')
 standalone=standalone.replace('</body>','<script type="module">'+script+'</script></body>')
embedded='<script id="visa-index" type="application/json">'+index.replace('</','<\\/')+'</script><script>window.__VISA_CHUNKS__='+json.dumps(chunks,separators=(',',':'))+';window.__VISA_CONTEXT__='+json.dumps(contexts,separators=(',',':'))+';window.__VISA_FULL__="'+full+'";</script>'
standalone=standalone.replace('<div id="root">',embedded+'<div id="root">')
filename='签证这笔钱-离线版.html';p=A/filename;p.write_text(standalone)
(D/filename).write_text(standalone.replace('<head>','<head><base href="../">'))
# The large master is downloadable without entering the rendering path.
shutil.copyfile(A/'data.json',D/'data.json')
meta=json.loads(index)['meta']
manifest={'data_version':meta['version'],'ui_version':meta['ui_version'],'offline_entry':filename,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'index_bytes':len(index.encode()),'network_dependencies':[],'build':'React 19 / D3 7 / Vite 6; bundled JS/CSS, lazy compressed evidence'}
(A/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps(manifest,ensure_ascii=False))
