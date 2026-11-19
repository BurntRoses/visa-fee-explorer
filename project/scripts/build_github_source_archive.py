#!/usr/bin/env python3
"""Prepare GitHub Release source assets; no network writes or app-source changes.

Large original files get direct Release assets so Pages fits its budget. Every
referenced original also remains in deterministic ZIP source packs. The caller
rewrites only its staged online index; offline files keep their original paths.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path
import re
import shlex
import shutil
from urllib.parse import quote
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
DEFAULT_REPO = 'BurntRoses/visa-fee-explorer'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def copy_verified(source, destination, expected_sha256=None):
    """Stream and verify staged copies instead of platform fast-copy shortcuts."""
    temporary = destination.with_name(destination.name + '.copying')
    actual = hashlib.sha256()
    with source.open('rb') as src, temporary.open('wb') as dest:
        for block in iter(lambda: src.read(MIB), b''):
            actual.update(block)
            dest.write(block)
    result = actual.hexdigest()
    assert expected_sha256 is None or result == expected_sha256, (str(source), 'source changed during staging')
    assert digest(temporary) == result, (str(destination), 'staged copy hash mismatch')
    temporary.replace(destination)
    return result


def source_paths(index, root):
    refs = {}
    for source in index['sources']:
        for relative in [source.get('local_path')] + [row.get('path') for row in source.get('files', []) if isinstance(row, dict)]:
            if not relative:
                continue
            path = root / relative
            if not path.is_file():
                continue
            assert path.resolve().is_relative_to(root.resolve()), relative
            refs.setdefault(relative, set()).add(source['source_id'])
    return refs


def application_paths(root):
    paths = {'app/index.html', 'app/build-manifest.json', 'app/签证这笔钱-离线版.html'}
    for folder in ['app/assets', 'app/data']:
        paths.update(str(p.relative_to(root)) for p in (root / folder).rglob('*') if p.is_file())
    assert all((root / p).is_file() for p in paths)
    return paths


def make_pack(path, members, root, records):
    """Fixed timestamps and permissions make identical originals reproducible."""
    with zipfile.ZipFile(path, 'w', allowZip64=True) as archive:
        for relative in members:
            source = root / relative
            entry = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry._compresslevel = 6
            expected = records[relative]
            actual = hashlib.sha256()
            size = 0
            with source.open('rb') as src, archive.open(entry, 'w', force_zip64=True) as dest:
                for block in iter(lambda: src.read(MIB), b''):
                    size += len(block)
                    actual.update(block)
                    dest.write(block)
            assert size == expected['bytes'] and actual.hexdigest() == expected['sha256'], relative
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == members
        assert archive.testzip() is None


def router_html():
    return '''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>来源归档 · 签证费用</title>
<style>body{font:16px/1.7 system-ui,sans-serif;color:#203b3b;background:#f8faf8;margin:0}main{max-width:700px;margin:12vh auto;padding:28px}h1{font-size:24px;font-weight:550}code{overflow-wrap:anywhere;font-size:12px}a{color:#167268}dt{color:#70817b;font-size:13px}dd{margin:0 0 14px;overflow-wrap:anywhere}.links{display:flex;gap:24px;flex-wrap:wrap}#error{color:#8f503f}</style>
<main><h1 id="title">正在打开来源原件</h1><p id="status">归档由同版本 GitHub Release 提供。</p>
<dl id="details" hidden><dt>原始文件路径</dt><dd id="path"></dd><dt>归档原件 SHA-256</dt><dd><code id="hash"></code></dd><dt>大小</dt><dd id="size"></dd></dl>
<p class="links"><a id="original" hidden>打开原件</a><a id="pack" hidden>下载所在来源分卷</a></p><p id="error" role="status"></p>
<noscript>请启用 JavaScript，或在 <a href="source-archives.json">来源归档清单</a> 中按原始路径查找原件和 ZIP 分卷链接。</noscript></main>
<script>
(async()=>{try{
 const path=new URL(location.href).searchParams.get('path');
 if(!path)throw Error('缺少来源路径。');
 const response=await fetch(new URL('./source-archives.json',location.href));
 if(!response.ok)throw Error('来源归档清单载入失败 '+response.status);
 const manifest=await response.json(),file=manifest.files.find(row=>row.path===path);
 if(!file)throw Error('该来源未列入当前归档清单。');
 const destination=file.release_url||new URL(file.path,location.href).href;
 document.getElementById('title').textContent=path.split('/').pop();
 document.getElementById('status').textContent='正在打开 '+manifest.version+' 的原件。若浏览器未自动下载，可使用下方链接。';
 document.getElementById('path').textContent=path;document.getElementById('hash').textContent=file.sha256;
 document.getElementById('size').textContent=new Intl.NumberFormat('zh-CN').format(file.bytes)+' 字节';document.getElementById('details').hidden=false;
 for(const [id,url] of [['original',destination],['pack',file.pack_url]]){const link=document.getElementById(id);link.href=url;link.rel='noopener noreferrer';link.hidden=false;}
 location.replace(destination);
}catch(error){document.getElementById('title').textContent='来源归档';document.getElementById('error').textContent=error.message;}})();
</script></html>'''.encode()


def prepare_sources(index, root, output, *, base_site_bytes, repo=DEFAULT_REPO, tag=None,
                    budget_bytes=850*MIB, pack_bytes=256*MIB, placement_manifest=None):
    version = index['meta']['version']
    token = re.sub(r'[^A-Za-z0-9._-]', '-', version)
    tag = tag or 'source-archives-' + token
    assert re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), repo
    assert re.fullmatch(r'[A-Za-z0-9_.-]+', tag), tag
    assert budget_bytes > base_site_bytes + 2*MIB, 'Application alone exceeds the Pages budget'
    assert pack_bytes < 1900*MIB
    output.mkdir(parents=True, exist_ok=True)
    release_base = f'https://github.com/{repo}/releases/download/{quote(tag, safe="")}/'
    refs = source_paths(index, root)
    records = {relative: dict(path=relative, bytes=(root/relative).stat().st_size,
                             sha256=digest(root/relative), source_ids=sorted(ids))
               for relative, ids in sorted(refs.items())}
    release_paths = set()
    projected = base_site_bytes + sum(row['bytes'] for row in records.values()) + 2*MIB
    if placement_manifest:
        assert placement_manifest['version'] == version
        previous = {row['path']: row for row in placement_manifest['files']}
        assert {key: row['sha256'] for key,row in previous.items()} == {key: row['sha256'] for key,row in records.items()}
        release_paths = {key for key,row in previous.items() if row['location'] == 'github_release'}
        projected -= sum(records[key]['bytes'] for key in release_paths)
    else:
        for row in sorted(records.values(), key=lambda r: (-r['bytes'], r['path'])):
            # GitHub's regular repository-file limit is independent of Pages size.
            if projected > budget_bytes or row['bytes'] >= 100*MIB:
                release_paths.add(row['path'])
                projected -= row['bytes']
    assert projected <= budget_bytes
    asset_rows = []
    direct = {}
    for relative in sorted(release_paths):
        row = records[relative]
        suffix = ''.join(Path(relative).suffixes)[-20:]
        suffix = suffix if re.fullmatch(r'(?:\.[A-Za-z0-9_-]+)*', suffix) else '.bin'
        name = 'original-' + row['sha256'] + suffix
        row.update(location='github_release', release_asset=name, release_url=release_base+name)
        if name in direct:
            continue
        path = output / name
        if not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            temporary = path.with_suffix(path.suffix+'.tmp')
            copy_verified(root/relative, temporary, row['sha256'])
            assert digest(temporary) == row['sha256']
            temporary.replace(path)
        direct[name] = path
        asset_rows.append(dict(name=name, path=str(path.resolve()), bytes=row['bytes'], sha256=row['sha256'], role='original'))
    groups, current, total = [], [], 0
    for relative, row in records.items():
        if current and total+row['bytes'] > pack_bytes:
            groups.append(current)
            current, total = [], 0
        current.append(relative)
        total += row['bytes']
    if current:
        groups.append(current)
    bundles = []
    for number, members in enumerate(groups, 1):
        name = f'visa-sources-{token}-{number:03}.zip'
        path = output / name
        inputs = dict(members=[{k:records[p][k] for k in ['path','bytes','sha256']} for p in members])
        marker = output / (name+'.inputs.json')
        signature = hashlib.sha256(encoded(inputs)).hexdigest()
        previous = json.loads(marker.read_text()) if marker.is_file() else {}
        if previous.get('inputs_sha256') != signature or not path.is_file() or digest(path) != previous.get('sha256'):
            temporary = output / (name+'.tmp')
            make_pack(temporary, members, root, records)
            temporary.replace(path)
            write_json(marker, dict(inputs_sha256=signature, sha256=digest(path)))
        value = dict(name=name, bytes=path.stat().st_size, sha256=digest(path),
                     files=len(members), uncompressed_bytes=sum(records[p]['bytes'] for p in members),
                     url=release_base+name)
        assert value['bytes'] < 2*1024**3, (name, 'GitHub Release asset limit')
        bundles.append(value)
        asset_rows.append(dict(**{k:value[k] for k in ['name','bytes','sha256']},path=str(path.resolve()),role='source_pack'))
        for relative in members:
            records[relative].update(pack_asset=name, pack_url=value['url'])
            records[relative].setdefault('location','github_pages')
    public = dict(schema='visa-source-archives-v1', version=version, repository=repo, tag=tag,
                  release_url=f'https://github.com/{repo}/releases/tag/{quote(tag,safe="")}',
                  original_files=len(records), original_bytes=sum(r['bytes'] for r in records.values()),
                  release_original_files=len(release_paths), packs=bundles, files=list(records.values()),
                  extraction='ZIP entries retain original data/raw relative paths. Match each extracted file SHA-256 to this manifest.')
    manifest_path = output/'source-archives.json'
    manifest_path.write_bytes(encoded(public)+b'\n')
    asset_rows.append(dict(name=manifest_path.name,path=str(manifest_path.resolve()),bytes=manifest_path.stat().st_size,sha256=digest(manifest_path),role='manifest'))
    sums = output/'SHA256SUMS.txt'
    sums.write_text(''.join(f'{a["sha256"]}  {a["name"]}\n' for a in sorted(asset_rows,key=lambda a:a['name'])))
    asset_rows.append(dict(name=sums.name,path=str(sums.resolve()),bytes=sums.stat().st_size,sha256=digest(sums),role='checksums'))
    notes = output/'SOURCE-ASSET-NOTES.md'
    notes.write_text(f'''# 来源归档 {version}

本次归档包含{len(records)}份应用引用的来源文件，共{public['original_bytes']:,}字节。{len(bundles)}个ZIP分卷覆盖全部原件，解压后保留原始data/raw相对路径。source-archives.json列出每份原件的路径、大小、SHA-256、来源编号、所在分卷及在线位置；SHA256SUMS.txt核对本次资源下载。

Pages保留小原件，{len(release_paths)}份较大原件另外作为本Release的独立资源，来源面板可直接打开。离线完整交付仍包含全部原件。ZIP分卷与独立资源可能包含同一原件，这是下载方式的选择，不代表额外数据或收款记录。
''')
    paths = [a['path'] for a in asset_rows]
    create = ['gh','release','create',tag,'--repo',repo,'--target','<PUBLISHED_COMMIT_SHA>',
              '--title','来源归档 '+version,'--notes-file',str(notes.resolve()),*paths]
    upload = ['gh','release','upload',tag,'--repo',repo,*paths]
    upload_plan = dict(version=version, repository=repo, tag=tag, source_files=len(records),
                       source_bytes=public['original_bytes'], pages_budget_bytes=budget_bytes,
                       projected_pages_bytes_with_2MiB_reserve=projected,
                       release_original_files=len(release_paths), assets=asset_rows,
                       create_release_command=create, upload_to_existing_release_command=upload,
                       instructions='Replace <PUBLISHED_COMMIT_SHA> with the exact published commit. Publish and verify these assets before deploying the Pages index that references this tag. This preparation performs no remote mutation.')
    write_json(output/'upload-plan.json',upload_plan)
    (output/'upload-commands.txt').write_text(shlex.join(create)+'\n\n'+shlex.join(upload)+'\n')
    staged = deepcopy(index)
    for source in staged['sources']:
        relative = source.get('local_path')
        if relative in release_paths:
            source['local_archive_path'] = relative
            source['online_archive_url'] = records[relative]['release_url']
            source['local_path'] = 'source-archive.html?path='+quote(relative,safe='')
        for file in source.get('files',[]):
            if isinstance(file,dict) and file.get('path') in release_paths:
                relative=file['path']
                file['local_archive_path']=relative
                file['online_archive_url']=records[relative]['release_url']
                file['path']='source-archive.html?path='+quote(relative,safe='')
    staged['meta']['source_archives'] = dict(manifest='../source-archives.json', release_tag=tag,
                                             repository=repo, online_delivery='Pages and GitHub Release originals; complete ZIP source packs')
    return dict(release_paths=release_paths, source_paths=set(refs), assets=asset_rows,
                source_hashes={path:row['sha256'] for path,row in records.items()},
                index_bytes=encoded(staged), extra_site_files={
                    'source-archives.json':manifest_path.read_bytes(), 'source-archive.html':router_html()},
                upload_plan=str((output/'upload-plan.json').resolve()), tag=tag,
                projected_pages_bytes=projected, budget_bytes=budget_bytes,
                release_manifest_sha256=digest(manifest_path))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=Path,default=ROOT/'app/data/index.json')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--repo',default=DEFAULT_REPO)
    parser.add_argument('--tag')
    parser.add_argument('--site-budget-mib',type=int,default=850)
    parser.add_argument('--pack-mib',type=int,default=256)
    args=parser.parse_args()
    index=json.loads(args.index.read_text())
    output=args.output or ROOT/'deliverables'/('source-archives-'+index['meta']['version'])
    static=application_paths(ROOT)
    result=prepare_sources(index,ROOT,output,base_site_bytes=sum((ROOT/p).stat().st_size for p in static),
                           repo=args.repo,tag=args.tag,budget_bytes=args.site_budget_mib*MIB,pack_bytes=args.pack_mib*MIB)
    print(json.dumps({k:result[k] for k in ['tag','upload_plan','projected_pages_bytes','budget_bytes']},ensure_ascii=False))


if __name__=='__main__':main()
