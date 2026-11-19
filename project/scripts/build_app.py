#!/usr/bin/env python3
"""Build the React/D3 workbench and self-contained offline distribution."""
from pathlib import Path
import argparse,base64,gzip,hashlib,json,re,shutil,subprocess,sys
from workbench_payloads import workbench_payloads
ROOT=Path(__file__).resolve().parents[1];A=ROOT/'app';W=A/'workbench';D=A/'dist'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--published',action='store_true',help='Use the sibling GitHub Pages data snapshot in place of research intermediates.')
args=parser.parse_args()
published=ROOT.parent/'site/app/data'
if args.published:
 if not (published/'index.json').is_file():parser.error('--published requires the GitHub checkout with site/app/data/')
else:
 subprocess.run([sys.executable,str(ROOT/'scripts/build_workbench_data.py')],cwd=ROOT,check=True)
node=shutil.which('node')
if not node:raise SystemExit('Node.js is required to rebuild the frontend. The offline HTML needs no runtime.')
for cli,options in [('typescript/bin/tsc',['--noEmit']),('vite/bin/vite.js',['build'])]:
 path=W/'node_modules'/cli
 if not path.exists():raise SystemExit('Install locked frontend dependencies once: cd app/workbench && pnpm install --frozen-lockfile')
 subprocess.run([node,str(path),*options],cwd=W,check=True)
B=W/'build';html=(B/'index.html').read_text()
if args.published:
 shutil.copytree(published,B/'data',dirs_exist_ok=True)
index_text=(B/'data/index.json').read_text()
index=json.loads(index_text)
if args.published and index['meta']['ui_version']!=json.loads((W/'package.json').read_text())['version']:
 parser.error('package.json and the published snapshot must have the same UI version')
preload=f'<link rel="preload" href="./data/boot-{index["meta"]["ui_version"]}.json.gz" as="fetch" crossorigin>'
html=html.replace('</head>',preload+'</head>',1)
html=html.replace('<link rel="stylesheet" crossorigin', '<link id="workspace-style" rel="stylesheet" media="print" onload="this.media=\'all\'" crossorigin',1)
parts=workbench_payloads(index)
for name,payload in parts.items():(B/'data'/name).write_bytes(payload)
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
standalone=html.replace(preload,'')
for match in list(re.finditer(r'<link[^>]+href="(\./assets/[^"]+\.css)"[^>]*>',standalone)):
 standalone=standalone.replace(match.group(0),'<style>'+(B/match.group(1)).read_text()+'</style>')
for match in list(re.finditer(r'<script[^>]+src="(\./assets/[^"]+\.js)"[^>]*></script>',standalone)):
 # One inline module has no imports; it can execute under file://.
 script=(B/match.group(1)).read_text().replace('</script','<\\/script')
 standalone=standalone.replace(match.group(0),'')
 standalone=re.sub(r'(?m)^[ \t]+\n','',standalone)
 standalone=standalone.replace('</body>','<script type="module">'+script+'</script></body>')
# Non-executable data blocks do not create a huge JS object at startup.
blocks=[]
for name in parts:
 blocks.append((name.removesuffix(f'-{index["meta"]["ui_version"]}.json.gz'),B/'data'/name))
for kind,folder in [('chunk','chunks'),('context','context')]:
 for p in sorted((B/'data'/folder).glob('*.json.gz')):
  blocks.append((kind+'-'+p.name.removesuffix('.json.gz'),p))
blocks.append(('full',B/'data/full-data.json.gz'))
embedded=''.join(f'<script type="application/octet-stream" id="visa-{key}">{base64.b64encode(p.read_bytes()).decode()}</script>' for key,p in blocks)
standalone=standalone.replace('</body>',embedded+'</body>')
filename='签证这笔钱-离线版.html';p=A/filename;p.write_text(standalone)
(D/filename).write_text(standalone.replace('<head>','<head><base href="../">'))
# The large master is downloadable without entering the rendering path.
if not args.published:shutil.copyfile(A/'data.json',D/'data.json')
meta=index['meta']
manifest={'data_version':meta['version'],'ui_version':meta['ui_version'],'offline_entry':filename,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'index_bytes':len(index_text.encode()),'network_dependencies':[],'build':'React 19 / D3 7 / Vite 6; bundled JS/CSS, lazy compressed evidence'}
(A/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps(manifest,ensure_ascii=False))
