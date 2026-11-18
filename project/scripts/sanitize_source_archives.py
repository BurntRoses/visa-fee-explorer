#!/usr/bin/env python3
"""Redact embedded Google browser credentials without changing source text."""
import argparse
import os
from pathlib import Path
import re

KEY = re.compile(rb"AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")
MARKER = b"<!-- visa-archive: credential redacted; active content disabled -->"
CSP = (b'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
       b'style-src \'unsafe-inline\'; img-src data:; form-action \'none\'; base-uri \'none\'">')
ROOT = Path(__file__).resolve().parents[1]


def clean(payload):
    if not KEY.search(payload):
        return payload
    output = KEY.sub(b"[REDACTED_GOOGLE_API_KEY]", payload)
    head = re.search(rb"<head\b[^>]*>", output, re.I)
    if head:
        at = head.end()
        output = output[:at] + MARKER + CSP + output[at:]
    return output


def archive_metadata(path):
    if path and (ROOT / path).suffix.lower() in (".htm", ".html") and (ROOT / path).is_file():
        with (ROOT / path).open("rb") as f:
            if MARKER in f.read():
                return dict(archive_kind="redacted_inert_web_snapshot",
                            archive_status="redacted_snapshot_archived",
                            archive_note="保留页面事实；已移除嵌入的第三方 Google API key，并禁用网页脚本和外部资源。")
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    affected = []
    for path in sorted((ROOT / "data/raw").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm", ".js", ".txt", ".json", ".xml"}:
            continue
        payload = path.read_bytes()
        sanitized = clean(payload)
        if sanitized == payload:
            continue
        affected.append(path.relative_to(ROOT))
        if args.apply:
            stat = path.stat()
            path.write_bytes(sanitized)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    for path in affected:
        print(path)
    if affected and not args.apply:
        raise SystemExit("Embedded Google API key in a source archive. Run sanitize_source_archives.py --apply.")


if __name__ == "__main__":
    main()
