#!/usr/bin/env python3
"""Build one fee-edge ledger and derive equal payer/receiver country views.

Local frozen inputs only. Government financial accounts are controls, never added
to fee edges. Optional modeled_flow_inputs.json replaces explicitly scoped routes.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / 'data/processed'
SCHEMA_VERSION = 'flow-ledger-1'
VISA_GROUPS = {
    'B1/B2': 'visitor', 'Visitor': 'visitor', 'Visitor V-1': 'visitor',
    'short': 'visitor', 'short_stay': 'visitor', 'visitor': 'visitor',
    '600': 'visitor', '601': 'visitor', '651': 'visitor',
    'F1': 'student', 'Study': 'student', 'student': 'student',
    'New study permit': 'student', 'H1B': 'work', 'L1': 'work',
    'Work': 'work', 'work': 'work', 'Family': 'family',
    'family': 'family', 'all': 'all',
}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def amount_sum(values):
    """Use the serialized edge amount once on both sides, avoiding incremental drift."""
    return float(sum((Decimal(str(v)) for v in values), Decimal(0)))


def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    inputs = {}

    def load(name, optional=False):
        path = PROCESSED / name
        if optional and not path.exists():
            return None
        inputs[str(path.relative_to(ROOT))] = digest_file(path)
        return json.loads(path.read_text())

    routes = load('routes.json')
    finances = load('financial_ledger.json')
    entities = load('entities.json')
    bills = load('bills.json')
    modeled = load('modeled_flow_inputs.json', optional=True)
    entity_map = {e['code']: e for e in entities}

    def entity_name(code):
        return entity_map.get(code, {}).get('name', str(code))

    def unallocated(code):
        if code in (None, '', 'UNK', 'OTHER', 'UNKNOWN', 'UNALLOCATED') or str(code).startswith('UNK_'):
            return True
        if str(code).startswith(('RAW_', 'UNKNOWN_', 'UNALLOCATED_')):
            return True
        return False

    def aggregate_origin(route):
        code = route.get('origin')
        labels = [route.get('origin_name', ''), *entity_map.get(code, {}).get('original_names', [])]
        return code == 'WORLD' or any(str(s).casefold().startswith('totals for ') for s in labels)

    route_controls, skipped, flows = [], Counter(), []
    years = sorted({int(r['year']) for r in routes})
    for route in routes:
        if not finite(route.get('amount_cny')):
            skipped['amount_unidentified'] += 1
            continue
        if route.get('origin') == route.get('destination'):
            skipped['same_payer_receiver'] += 1
            continue
        if aggregate_origin(route):
            route_controls.append(route)
            skipped['aggregate_origin_control_only'] += 1
            continue
        payer, receiver = route['origin'], route['destination']
        if not payer or not receiver:
            skipped['missing_endpoint'] += 1
            continue
        unknown = unallocated(payer) or unallocated(receiver)
        amount = route['amount_cny']
        flows.append({
            'id': f'flow_{route["id"]}', 'route_id': route['id'],
            'payer': payer, 'receiver': receiver, 'origin': payer, 'destination': receiver,
            'payer_name': route.get('origin_name') or entity_name(payer),
            'receiver_name': route.get('destination_name') or entity_name(receiver),
            'origin_name': route.get('origin_name') or entity_name(payer),
            'destination_name': route.get('destination_name') or entity_name(receiver),
            'year': int(route['year']), 'period_start': route['period_start'],
            'period_end': route['period_end'], 'period_label': route['period_label'],
            'period_type': route['period_type'], 'visa_type': route['visa_type'],
            'visa_group': VISA_GROUPS.get(route['visa_type'], 'other'),
            'visa_label': route['visa_label'], 'quantity': route['quantity'],
            'quantity_basis': route['quantity_basis'], 'quantity_label': route['quantity_label'],
            'amount': route['amount'], 'currency': route['currency'],
            'amount_cny': amount, 'lower_cny': amount, 'upper_cny': amount,
            'calculation_type': route['calculation_type'],
            'model_status': 'standard_tariff_scenario', 'method_id': route['method_id'],
            'origin_basis': route['origin_basis'], 'source_ids': route['source_ids'],
            'observation_ids': route['observation_ids'],
            'coverage_status': 'source_unallocated_scenario' if unknown else 'covered_route_scenario',
            'unknown_unallocated': unknown, 'notes': route.get('notes', ''),
        })

    base_count = len(flows)
    model_meta = {'present': modeled is not None, 'replaced_base_edges': 0, 'modeled_edge_count': 0}
    # The optional input adapter is intentionally separate from base-route conversion.
    if modeled is not None:
        flows, model_meta = merge_modeled(flows, modeled, entity_name)
        years = sorted(set(years) | {f['year'] for f in flows})

    ids = [f['id'] for f in flows]
    if len(ids) != len(set(ids)):
        raise ValueError('Flow IDs must be unique')
    for flow in flows:
        if flow['payer'] == flow['receiver']:
            raise ValueError(f'Self-flow is not a cross-country edge: {flow["id"]}')
        if not all(finite(flow.get(k)) for k in ('amount_cny', 'lower_cny', 'upper_cny')):
            raise ValueError(f'Nonfinite modeled amount: {flow["id"]}')
        if not 0 <= flow['lower_cny'] <= flow['amount_cny'] <= flow['upper_cny']:
            raise ValueError(f'Invalid amount bounds: {flow["id"]}')
    flows.sort(key=lambda f: (f['year'], f['payer'], f['receiver'], f['visa_group'], f['id']))

    balances, matrices, annual_checks = [], [], []
    country_codes = {e['code'] for e in entities if e.get('kind') == 'country_or_jurisdiction'}
    country_codes.update(f['payer'] for f in flows)
    country_codes.update(f['receiver'] for f in flows)
    country_codes.update(f['destination'] for f in finances)
    country_codes.update(b['destination'] for b in bills)
    country_codes.discard('WORLD')
    for year in years:
        edges = [f for f in flows if f['year'] == year]
        incoming, outgoing, cells = defaultdict(list), defaultdict(list), defaultdict(list)
        for flow in edges:
            outgoing[flow['payer']].append(flow)
            incoming[flow['receiver']].append(flow)
            cells[flow['payer'], flow['receiver']].append(flow)
        for code in sorted(country_codes):
            ins, outs = incoming[code], outgoing[code]
            control = [f for f in finances if f['year'] == year and f['destination'] == code]
            inc = amount_sum(f['amount_cny'] for f in ins)
            out = amount_sum(f['amount_cny'] for f in outs)
            inc_low, inc_high = (amount_sum(f[k] for f in ins) for k in ('lower_cny', 'upper_cny'))
            out_low, out_high = (amount_sum(f[k] for f in outs) for k in ('lower_cny', 'upper_cny'))
            unknown_in = amount_sum(f['amount_cny'] for f in ins if unallocated(f['payer']))
            unknown_out = amount_sum(f['amount_cny'] for f in outs if unallocated(f['receiver']))
            used = ins + outs
            balances.append({
                'year': year, 'country': code, 'code': code, 'name': entity_name(code),
                'entity_kind': entity_map.get(code, {}).get('kind', 'model_node'),
                'inflow_cny': inc, 'outflow_cny': out, 'net_cny': amount_sum([inc, -out]),
                'inflow': inc, 'outflow': out, 'net': amount_sum([inc, -out]),
                'inflow_lower_cny': inc_low, 'inflow_upper_cny': inc_high,
                'outflow_lower_cny': out_low, 'outflow_upper_cny': out_high,
                'net_lower_cny': amount_sum([inc_low, -out_high]),
                'net_upper_cny': amount_sum([inc_high, -out_low]),
                'inflow_edge_count': len(ins), 'outflow_edge_count': len(outs),
                'edge_count': len(used), 'unknown_unallocated_cny': unknown_in,
                'unknown_unallocated': unknown_in,
                'unknown_receiver_outflow_cny': unknown_out,
                'unknown_unallocated_is_included_in_inflow': True,
                'coverage_status': 'modeled_and_covered_routes' if any(
                    f.get('model_status') != 'standard_tariff_scenario' for f in used
                ) else 'covered_routes_only' if used else 'no_amount_edges',
                'model_status': sorted({f['model_status'] for f in used}),
                'origin_bases': sorted({str(f.get('origin_basis')) for f in used}),
                'period_scopes': sorted({f'{f["period_start"]}/{f["period_end"]}' for f in used}),
                'control_accounts': control,
                'control_accounts_included_in_flows': False,
                'bill_ids': [b['id'] for b in bills if b['year'] == year and b['destination'] == code],
                'unquantified_missing_scope': True,
            })
        matrix_cells = []
        for (payer, receiver), rr in sorted(cells.items()):
            matrix_cells.append({
                'payer': payer, 'receiver': receiver, 'origin': payer, 'destination': receiver,
                'amount_cny': amount_sum(f['amount_cny'] for f in rr),
                'lower_cny': amount_sum(f['lower_cny'] for f in rr),
                'upper_cny': amount_sum(f['upper_cny'] for f in rr),
                'edge_count': len(rr), 'edge_ids': [f['id'] for f in rr],
                'visa_groups': sorted({f['visa_group'] for f in rr}),
            })
        annual = [b for b in balances if b['year'] == year]
        edge_total = amount_sum(f['amount_cny'] for f in edges)
        income_total = amount_sum(b['inflow_cny'] for b in annual)
        outgo_total = amount_sum(b['outflow_cny'] for b in annual)
        net_total = amount_sum(b['net_cny'] for b in annual)
        tolerance = max(.01, abs(edge_total) * 1e-12)
        if not (abs(income_total - edge_total) <= tolerance and
                abs(outgo_total - edge_total) <= tolerance and abs(net_total) <= tolerance):
            raise ValueError(f'Country sides do not conserve edge amounts in {year}')
        annual_checks.append({'year': year, 'edge_count': len(edges), 'edge_total_cny': edge_total,
                              'inflow_total_cny': income_total, 'outflow_total_cny': outgo_total,
                              'net_total_cny': net_total, 'conservation': 'pass'})
        matrices.append({
            'year': year, 'currency': 'CNY', 'format': 'sparse',
            'row_meaning': 'payer_outflow', 'column_meaning': 'receiver_inflow',
            'country_codes': sorted(country_codes), 'cells': matrix_cells,
            'row_totals': {b['code']: b['outflow_cny'] for b in annual},
            'column_totals': {b['code']: b['inflow_cny'] for b in annual},
            'total_cny': edge_total, 'missing_cell_meaning': 'no_modeled_or_covered_amount_edge',
        })

    meta = {
        'schema_version': SCHEMA_VERSION, 'years': years, 'currency': 'CNY',
        'input_sha256': inputs, 'route_input_count': len(routes), 'base_edge_count': base_count,
        'edge_count': len(flows), 'country_balance_count': len(balances),
        'skipped_routes': dict(skipped), 'model_input': model_meta,
        'annual_checks': annual_checks, 'route_control_totals': route_controls,
        'accounting_identity': 'Each edge is counted once as payer outflow and once as receiver inflow; net=inflow-outflow. Global inflow and outflow are the same money, not additive.',
        'unknown_unallocated_definition': 'UNKNOWN/OTHER/RAW payer edges remain explicit. A country unknown_unallocated_cny is already included in its inflow; never add it again. Unquantified missing scope remains separate.',
        'financial_control_rule': 'Financial records are never appended as additional flow edges. Explicit destination models may use scope-matched actual accounts for calibration or residuals; each such use and its period bridge is documented in modeled inputs.',
        'base_interval_rule': 'Base lower=point=upper fixes one tariff scenario; it is not a confidence interval or full actual-receipts bound.',
        'limitations': [
            'Base edges are existing tariff scenarios, not identified actual payments or complete government receipts.',
            'Original nationality, citizenship, residence, source-country and consulate-location bases remain distinct in origin_basis; aggregation does not harmonize them.',
            'Year groups retain exact native periods; fiscal-year and calendar-year edges may share a year label.',
            'SCH is a regional receiver, not an additional country to add to member-country receipts.',
            'Government accounts may include domestic services and wider fee scopes; their time and accounting basis are not forced to match route scenarios.',
            'No edge or missing matrix cell means no included amount, not proof that the real fee is zero. Explicit zero-valued routes remain edges.',
            'Bill archetypes remain reference details; they are not multiplied by annual counts or added to the network.',
        ],
    }
    for filename, data in [('flows.json', flows), ('country_balances.json', balances),
                           ('flow_matrix.json', matrices), ('flow_meta.json', meta)]:
        (PROCESSED / filename).write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'),
                                                     allow_nan=False) + '\n')
    print(json.dumps({'status': 'pass', 'edges': len(flows), 'balances': len(balances),
                      'modeled_edges': model_meta['modeled_edge_count'], 'years': annual_checks},
                     ensure_ascii=False))


def merge_modeled(base_flows, modeled, entity_name):
    """Explicit destination/year/category scopes replace their base amount edges."""
    scopes = modeled.get('replace_scopes', [])

    def in_scope(flow, scope):
        groups = scope.get('visa_groups', ['all'])
        return (flow['receiver'] == scope['destination'] and
                flow['year'] == int(scope['year']) and
                ('all' in groups or flow['visa_group'] in groups))

    replaced = [f for f in base_flows if any(in_scope(f, s) for s in scopes)]
    result = [f for f in base_flows if not any(in_scope(f, s) for s in scopes)]
    added = []
    for original in modeled.get('flows', []):
        flow = dict(original)
        payer, receiver = flow['payer'], flow['receiver']
        if payer == 'WORLD':
            raise ValueError('Model origins must be allocated country/source nodes, not WORLD totals')
        flow.update(origin=payer, destination=receiver, year=int(flow['year']))
        if not any(in_scope(flow, s) for s in scopes):
            raise ValueError(f'Modeled edge has no declared replacement scope: {flow["id"]}')
        flow.setdefault('payer_name', entity_name(payer))
        flow.setdefault('receiver_name', entity_name(receiver))
        flow.setdefault('origin_name', flow['payer_name'])
        flow.setdefault('destination_name', flow['receiver_name'])
        flow.setdefault('route_id', None)
        flow.setdefault('period_start', f'{flow["year"]}-01-01')
        flow.setdefault('period_end', flow.get('end', f'{flow["year"]}-12-31'))
        flow.setdefault('period_label', flow.get('label', str(flow['year'])))
        flow.setdefault('period_type', flow.get('type', 'calendar_year_model'))
        flow.setdefault('visa_type', flow['visa_group'])
        flow.setdefault('visa_label', flow['visa_group'])
        flow.setdefault('quantity', None)
        flow.setdefault('quantity_basis', 'modeled_fee_events')
        flow.setdefault('quantity_label', flow['quantity_basis'])
        flow.setdefault('calculation_type', 'modeled_estimate')
        flow.setdefault('model_status', 'modeled_estimate')
        flow.setdefault('origin_basis', 'modeled_nationality')
        flow.setdefault('source_ids', [])
        flow.setdefault('observation_ids', [])
        flow.setdefault('parameters', {})
        unknown = payer in ('UNK', 'OTHER', 'UNKNOWN', 'UNALLOCATED') or str(payer).startswith(
            ('RAW_', 'UNK_', 'UNKNOWN_', 'UNALLOCATED_'))
        flow.setdefault('unknown_unallocated', unknown)
        flow.setdefault('coverage_status', 'modeled_unallocated_source' if unknown else 'modeled_estimate')
        added.append(flow)
    return result + added, {
        'present': True, 'version': modeled.get('version'),
        'replaced_base_edges': len(replaced), 'modeled_edge_count': len(added),
        'replace_scopes': scopes, 'models': modeled.get('models', []),
        'additional_sources': modeled.get('sources', []), 'notes': modeled.get('notes', []),
    }


if __name__ == '__main__':
    main()
