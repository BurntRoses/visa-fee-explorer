#!/usr/bin/env python3
"""Make the Pages reading copies inert. Canonical Release archives stay intact."""
import hashlib
import json
from pathlib import Path
import re
import sys

MARKER = b'<!-- visa-pages: read-only snapshot -->'
POLICY = (b'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
          b'style-src \'unsafe-inline\'; img-src data:; form-action \'none\'; base-uri \'none\'">')
DOCTYPE = re.compile(rb'<!doctype\s+html\b[^>]*>', re.I)
EARLY_RESOURCE = re.compile(rb'<(?:script|link|iframe|body)\b', re.I)
HEAD = re.compile(rb'<head\b[^>]*>', re.I)
REFRESH = re.compile(rb'<meta\b(?:"[^"]*"|\'[^\']*\'|[^\'">])*>', re.I)
REFRESH_ATTRIBUTE = re.compile(rb'\bhttp-equiv\s*=\s*(?:"\s*refresh\s*"|\'\s*refresh\s*\'|refresh(?=\s|/?>))', re.I)

def freeze(site):
    catalog = json.loads((site / 'source-archives.json').read_bytes())
    copies = {}
    for entry in catalog['files']:
        relative = entry['path']
        target = site / relative
        if not target.is_file() or target.suffix.lower() not in {'.html', '.htm'}:
            continue
        data = target.read_bytes()
        if MARKER in data:
            served = data
        else:
            if hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError(f'Original checksum mismatch: {relative}')
            head = HEAD.search(data)
            if not head:
                # One source contains a JSON API response in a file named .html.
                json.loads(data)
                if b'<' in data:
                    raise ValueError(f'Unexpected markup in JSON snapshot: {relative}')
                continue
            prefix = data[:head.end()]
            if EARLY_RESOURCE.search(prefix):
                doctype = DOCTYPE.search(prefix)
                if not doctype or EARLY_RESOURCE.search(prefix[doctype.start():]):
                    raise ValueError(f'Unsafe markup before the document head: {relative}')
                prefix = prefix[doctype.start():]
            served = prefix + MARKER + POLICY + data[head.end():]
            served = REFRESH.sub(lambda m: b'' if REFRESH_ATTRIBUTE.search(m[0]) else m[0], served)
            target.write_bytes(served)
        copies[relative] = {'sha256': hashlib.sha256(served).hexdigest(), 'bytes': len(served)}
    (site / 'source-pages-snapshots.json').write_text(json.dumps(
        {'version': catalog['version'], 'files': copies}, ensure_ascii=False, indent=2) + '\n')
    return len(copies)

if __name__ == '__main__':
    print(f'{freeze(Path(sys.argv[1]))} read-only web snapshots')
