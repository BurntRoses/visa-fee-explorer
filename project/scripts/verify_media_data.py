#!/usr/bin/env python3
"""Check locked media claims against the final local data; never render or call a network.

Run once to create/update media/evidence/data-consistency.json and claims_snapshot.json.
Later input drift stops rendering. Use --refresh-baseline only after reviewing a change;
the locked numeric and scope assertions still apply when refreshing.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = 'media/evidence/data-consistency.json'
CLAIM_METRICS = {
    'fee_us_b_2024': ['bill_us_visitor_2024'],
    'fee_jp_issue_only': [],
    'bill_uk_student_2024_one_year': ['bill_uk_student_2024'],
    'fin_us_fy2024': ['us_2024_world_all_mrv_including_bcc_mrv_receipts_actual'],
    'policy_tha_2024': ['bill_THA_waiver_2024'],
    'policy_sgp_2024': ['bill_SGP_waiver_2024'],
    'waiver_sgp_reuse_demo': [f'waiver_SGP_2024_reuse{n}' for n in (1, 2, 4)],
}


class MediaDataError(RuntimeError):
    """A locked number, scope, source or reviewed input has changed."""


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def renderer_lock(root=ROOT):
    """Read a literal data declaration without importing the rendering dependencies."""
    tree = ast.parse((root / 'scripts/render_media.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == 'MEDIA_CLAIM_LOCK' for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise MediaDataError('render_media.py has no literal MEDIA_CLAIM_LOCK')


def verify_media_data(root=ROOT, media_lock=None, *, require_baseline=False,
                      refresh_baseline=False):
    root = Path(root)
    media_lock = renderer_lock(root) if media_lock is None else media_lock
    checks, inputs, file_hashes = [], {}, {}

    def load(rel):
        path = root / rel
        raw = path.read_bytes()
        file_hashes[rel] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    def check(name, actual, expected):
        if actual != expected:
            raise MediaDataError(f'{name}: expected {expected!r}, got {actual!r}')
        checks.append({'check': name, 'status': 'pass', 'value': actual})

    def number(name, actual, expected):
        check(name, str(Decimal(str(actual)).normalize()),
              str(Decimal(str(expected)).normalize()))

    def select(rows, key, value, bucket):
        matches = [r for r in rows if r.get(key) == value]
        if len(matches) != 1:
            raise MediaDataError(f'{bucket}/{value}: expected one record, got {len(matches)}')
        inputs.setdefault(bucket, {})[value] = matches[0]
        return matches[0]

    claims = load('data/processed/claims.json')
    sources = load('data/processed/sources.json')
    bills = load('data/processed/bills.json')
    fees = load('data/processed/fee_rules.json')
    ledger = load('data/processed/financial_ledger.json')
    observations = load('data/processed/observations.json')
    estimates = load('data/processed/estimates.json')
    # This is the exact FX input consumed by build_dataset.py; no processed FX file exists.
    fx = load('data/research/schengen_fx/fx.json')
    check('media claim ID set', sorted(media_lock), sorted(CLAIM_METRICS))
    snapshot = {}
    for cid, locked in media_lock.items():
        master = select(claims, 'claim_id', cid, 'claims')
        check(f'{cid}: metric links', master['metric_ids'], CLAIM_METRICS[cid])
        source_ids = list(dict.fromkeys(master['source_ids'] + locked['supporting_source_ids']))
        registered = []
        for sid in source_ids:
            source = select(sources, 'source_id', sid, 'sources')
            archives = {}
            if source.get('local_path'):
                archives[source['local_path']] = source.get('sha256')
            for item in source.get('files', []):
                archives[item['path']] = item.get('sha256') or archives.get(item['path'])
            if not archives:
                raise MediaDataError(f'{cid}/{sid}: missing registered local evidence')
            for rel, expected_hash in archives.items():
                path = root / rel
                if not path.is_file():
                    raise MediaDataError(f'{cid}/{sid}: local evidence not found: {rel}')
                actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                if expected_hash and actual_hash != expected_hash:
                    raise MediaDataError(f'{sid}: registered archive hash changed: {rel}')
                inputs.setdefault('source_archives', {})[rel] = actual_hash
            registered.append(source)
        snapshot[cid] = dict(locked, source_ids=source_ids,
                             master_claim=master, sources=registered)

    us = select(bills, 'id', 'bill_us_visitor_2024', 'bills')
    check('US standard bill scope', [us['destination'], us['year']], ['USA', 2024])
    check('US fee currency', us['components'][0]['currency'], 'USD')
    number('US standard B fee', us['components'][0]['amount'], 185)
    check('US application fee refundable', us['components'][0]['refundable'], False)
    cny = select(fx, 'fx_id', 'fed_2024_CNY', 'fx')
    number('2024 CNY per USD', cny['raw_rate'], '7.1957')
    check('FX direction/year', [cny['raw_direction'], cny['year']], ['currency_per_USD', 2024])
    number('US185 to CNY', Decimal(str(us['components'][0]['amount'])) *
           Decimal(str(cny['raw_rate'])), '1331.2045')

    jp = select(fees, 'id', 'jp_standard_single_pre202607', 'fees')
    check('Japan fee timing', jp['payment_trigger'], 'issuance_only')
    check('Japan no issuance rule', jp['refund_rule'], 'no_government_fee_if_not_issued')

    uk = select(bills, 'id', 'bill_uk_student_2024', 'bills')
    check('UK bill scope', [uk['destination'], uk['year']], ['GBR', 2024])
    check('UK bill currencies', [c['currency'] for c in uk['components']], ['GBP', 'GBP'])
    number('UK application fee', uk['components'][0]['amount'], 490)
    number('UK one-year student IHS', uk['components'][1]['amount'], 776)
    number('UK one-billing-year total', sum(c['amount'] for c in uk['components']), 1266)
    check('UK IHS example qualifier', '一个' in uk['label'] and '计费年' in uk['label'], True)
    ihs = select(fees, 'id', 'fee_f20d03e878c84127', 'fees')
    number('UK IHS structured rate', ihs['amount'], 776)
    check('UK IHS effective date', ihs['effective_from'], '2024-02-06')

    mid = CLAIM_METRICS['fin_us_fy2024'][0]
    raw_mrv = select(observations, 'observation_id', mid, 'observations')
    number('MRV raw million USD', raw_mrv['value'], 2561)
    check('MRV raw unit', raw_mrv['unit'], 'million_USD')
    check('MRV includes BCC', raw_mrv['visa_type'], 'ALL_MRV_INCLUDING_BCC')
    mrv = select(ledger, 'id', mid, 'financial_ledger')
    number('MRV 2561 million equals 2.561 billion USD', mrv['amount'], '2561000000')
    number('MRV raw-to-ledger conversion', Decimal(str(raw_mrv['value'])) * 1000000, mrv['amount'])
    check('MRV currency and period', [mrv['currency'], mrv['period_start'], mrv['period_end']],
          ['USD', '2023-10-01', '2024-09-30'])
    check('MRV income not profit qualifier', 'not government profit' in mrv['scope'], True)
    number('MRV annual-FX CNY', mrv['amount_cny'],
           Decimal(str(mrv['amount'])) * Decimal(str(cny['raw_rate'])))
    number('MRV on-screen billion CNY rounding',
           round(Decimal(str(mrv['amount_cny'])) / Decimal('100000000'), 1), '184.3')

    sg = select(fees, 'id', 'sg_processing', 'fees')
    number('SGD reference processing fee', sg['amount'], 30)
    check('SGD reference currency', sg['currency'], 'SGD')
    for n, expected in [(1, 30), (2, 15), (4, 7.5)]:
        est = select(estimates, 'estimate_id', f'waiver_SGP_2024_reuse{n}', 'estimates')
        number(f'SGD reuse{n}: reference fee', est['parameters']['reference_fee'], 30)
        number(f'SGD reuse{n}: trips per visa', est['parameters']['trips_per_visa'], n)
        number(f'SGD reuse{n}: per-trip allocation',
               Decimal(str(est['parameters']['reference_fee'])) / n, expected)
        check(f'SGD reuse{n}: scenario-only', est['permitted_use'], 'scenario_only')
    for dest, fee_id in [('THA', 'th_waiver_chinese_2024'), ('SGP', 'sg_waiver_chinese')]:
        bill = select(bills, 'id', f'bill_{dest}_waiver_2024', 'bills')
        number(f'{dest}: eligible waiver bill government fee',
               sum(c['amount'] for c in bill['components']), 0)
        rule = select(fees, 'id', fee_id, 'fees')
        number(f'{dest}: waiver structured government fee', rule['amount'], 0)
        if dest == 'SGP':
            check('SGP waiver start', rule['effective_from'], '2024-02-09')

    # Reject a master narrative that disagrees with its own structured media inputs.
    for cid, tokens in {
        'fee_us_b_2024': ['185', '1331', '不退'],
        'fee_jp_issue_only': ['未签发', '手续费'],
        'bill_uk_student_2024_one_year': ['490', '776', '1266', '计费年'],
        'fin_us_fy2024': ['25.61', '184.3'],
        'waiver_sgp_reuse_demo': ['30', '15', '7.5', '情景'],
    }.items():
        check(f'{cid}: master text agrees with locked facts',
              all(t in inputs['claims'][cid]['text'] for t in tokens), True)

    inputs['media_claim_lock'] = media_lock
    fingerprint = digest(inputs)
    baseline_path = root / REPORT
    if baseline_path.exists() and not refresh_baseline:
        baseline = json.loads(baseline_path.read_text())
        check('reviewed media input fingerprint', fingerprint, baseline['input_fingerprint_sha256'])
    elif require_baseline:
        raise MediaDataError('No reviewed media baseline. Run scripts/verify_media_data.py first.')
    report = {
        'status': 'pass', 'checked_at': datetime.now(timezone.utc).isoformat(),
        'input_fingerprint_sha256': fingerprint, 'claim_ids': list(media_lock),
        'source_ids': sorted(inputs['sources']), 'check_count': len(checks), 'checks': checks,
        'selected_input_records': inputs, 'input_file_sha256': file_hashes,
        'media_rendered': False,
        'drift_rule': 'Rendering compares selected master records, registered source archives and '
                      'the locked narrative to this fingerprint. Any change stops generation. '
                      'After review, --refresh-baseline may update provenance; numeric locks still apply.',
    }
    return report, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-baseline', action='store_true')
    args = parser.parse_args()
    try:
        report, snapshot = verify_media_data(refresh_baseline=args.refresh_baseline)
    except (MediaDataError, OSError, KeyError, ValueError) as error:
        parser.exit(1, f'Media/data consistency failed; no media rendered: {error}\n')
    (ROOT / REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'media/evidence/claims_snapshot.json').write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'checks': report['check_count'],
                      'claims': len(snapshot), 'sources': len(report['source_ids']),
                      'input_fingerprint_sha256': report['input_fingerprint_sha256'],
                      'media_rendered': False, 'report': REPORT}, ensure_ascii=False))


if __name__ == '__main__':
    main()
