#!/usr/bin/env python3
"""Check displayed context against frozen observations and fee-ledger boundaries."""
from pathlib import Path
from collections import defaultdict
from datetime import date
import gzip, hashlib, json, math
from observation_domains import observation_domain

ROOT = Path(__file__).resolve().parents[1]


def main():
    index = json.loads((ROOT / 'app/data/index.json').read_text())
    observations = json.loads((ROOT / 'data/processed/observations.json').read_text())
    by_id = {r['observation_id']: r for r in observations}
    sources = {r['source_id']: r for r in index['sources']}
    checks = []

    def check(name, errors, count):
        checks.append(dict(check=name, passed=not errors, checked=count, errors=errors[:12]))
        print(('PASS ' if not errors else 'FAIL ') + name, flush=True)

    bad, source_errors, point_count = [], [], 0
    contexts = {}
    for code, manifest in index['countryContext'].items():
        context = json.loads(gzip.decompress((ROOT / 'app/data' / manifest['file']).read_bytes()))
        contexts[code] = context
        if context['code'] != code:
            bad.append([code, 'country identity mismatch'])
        if len(context['series']) != manifest['series_count']:
            bad.append([code, 'series count mismatch'])
        for series in context['series']:
            for sid in series['source_ids']:
                if sid not in sources:
                    source_errors.append([code, sid])
            for partner in series['partners']:
                seen = set()
                for point in partner['points']:
                    point_count += 1
                    oid = point['observation_id']
                    row = by_id.get(oid)
                    if not row:
                        bad.append([code, oid, 'missing source observation'])
                        continue
                    for key in ['value', 'period_start', 'period_end', 'source_id', 'lower', 'upper', 'bound_type', 'lower_inclusive', 'source_status', 'source_status_label']:
                        if point.get(key) != row.get(key):
                            bad.append([code, oid, key, 'source value/period changed'])
                    if row['destination'] != code:
                        bad.append([code, oid, 'country context changed reporting geography'])
                    if row.get('unit') != series['unit']:
                        bad.append([code, oid, 'unit changed'])
                    if point['source_id'] not in sources:
                        source_errors.append([code, oid, point['source_id']])
                    key = point['period_start'], point['period_end']
                    if key in seen:
                        bad.append([code, oid, 'duplicate partner/period'])
                    seen.add(key)
                    if point['value'] is None or not math.isfinite(point['value']):
                        bad.append([code, oid, 'nonfinite display value'])
    check('every displayed context value, unit, period and source matches its observation', bad, point_count)
    check('all context sources resolve to archived source registry', source_errors, len(sources))

    # Concrete examples cross the critical semantic boundaries; they do not
    # recreate the classifier's keyword rules.
    coverage = index['coverage']
    gha2019 = [r for r in coverage if r['code'] == 'GHA' and r['year'] == 2015]
    check('Ghana historical tourist arrivals do not establish visa-application quantities',
          [] if gha2019 and all(not r['quantity_known'] for r in gha2019) and any(r.get('mobility_context_known') for r in gha2019) else ['arrival-only evidence labelled visa quantity'], len(gha2019))
    euro = [s for c in contexts.values() for s in c['series'] if s['metric'] == 'border_entry_refusals']
    check('Eurostat uses rounded persons and stays outside visa-application indicators',
          [] if euro and all(s['domain'] == 'mobility' and s['unit_label'] == '人（原表按5人取整）' for s in euro) else ['border-refusal domain/unit mismatch'], len(euro))
    check('EU27 is not silently displayed as Schengen or counted as a country',
          [] if 'EU27_2020' not in contexts and not any(e['code'] == 'EU27_2020' for e in index['entities']) else ['EU aggregate inserted into country context'], len(contexts))
    historical = [p for c in contexts.values() for s in c['series'] if s['native_series_id'].startswith('wdi_') for partner in s['partners'] for p in partner['points']]
    check('historical WDI context retains actual observation years rather than query end year',
          [] if historical and max(p['year'] for p in historical) == 2020 and all(p['year'] == int(by_id[p['observation_id']]['period_end'][:4]) for p in historical) else ['historical year shifted or imputed'], len(historical))
    ind = contexts.get('IND', {}).get('series', [])
    ind_errors = []
    for series in ind:
        if series['native_series_id'] == 'india_fta_nationality':
            labels = [p['name'] for p in series['partners']]
            if len(labels) != len(set(labels)):
                ind_errors.append('ambiguous duplicate India partner labels')
        if series['flow_direction'] == 'outbound' and not any(x in (series['origin_basis'] or '') for x in ['destination','usual_residence']):
            ind_errors.append('outbound partner basis missing')
    check('India source residuals remain separate and outbound partners retain destination basis', ind_errors, len(ind))
    flows = json.loads((ROOT / 'data/processed/flows.json').read_text())
    new_mobility_ids = {r['observation_id'] for r in observations if observation_domain(r) in ('mobility','rate','document_activity') and r.get('eligible_money_ledger') is False}
    accidental_money = [r['id'] for r in flows if set(r.get('observation_ids', [])) & new_mobility_ids]
    check('new tourism and border observations are not substituted for fee-payment quantities', accidental_money, len(flows))
    china_points = [p for s in contexts.get('CHN', {}).get('series', []) for partner in s['partners'] for p in partner['points']]
    floor = next((p for p in china_points if p['observation_id'] == 'cvc_cn_ind_2025_ytd_0922'), None)
    check('China latest India issuance remains a dated strict lower floor rather than annual actual',
          [] if floor and floor['value'] == 265000 and floor['period_end'] == '2025-09-22' and floor.get('lower_inclusive') is False and floor.get('source_status') == 'strict_lower_floor' else ['source lower floor lost'], len(china_points))
    recent = [p for c in contexts.values() for s in c['series'] if s['native_series_id'].startswith(('oecd_', 'eurostat_')) for partner in s['partners'] for p in partner['points'] if p['source_id'].startswith('recent_')]
    check('recent OECD and Eurostat context reaches published 2026 periods without annualization',
          [] if len(recent) == 11826 and max(p['period_end'] for p in recent) == '2026-09-30' else ['recent context missing or period shifted'], len(recent))
    package = json.loads((ROOT / 'data/estimates/europe_expansion_v4_flows.json').read_text())
    d_ids = {r['id'] for r in package['flows'] if r['receiver'] == 'DEU'}
    d_rows = [r for r in flows if r['id'] in d_ids]
    check('national D fee values retain processed cohorts, unknown payer and explicit standard-price status',
          [] if len(d_rows) == 84 and all(r['payer'] == 'UNK' and r['model_status'] == 'processed_cohort_full_standard_fee_benchmark' and r['lower_cny'] == 0 and math.isclose(r['amount_cny'], r['upper_cny']) for r in d_rows) else ['D fee-value scope changed'], len(d_rows))
    # r9 is frozen before staging r10. Only evidenced Indonesia replacement and
    # Australia2025 income/throughput, Nepal national receipts and India's
    # newly observed FY2024/25 receipts may alter an existing fee row.
    baseline_path = ROOT / 'docs/validation/r9-fee-baseline.json.gz'
    if baseline_path.exists():
        baseline = json.loads(gzip.decompress(baseline_path.read_bytes()))
        current = {r['id']:r for r in flows}
        allowed = {e['code'] for e in index['entities']}
        normal = lambda code: code if code in allowed else 'UNK'
        changed = []
        removed_idn = {f'game_idn_voa_model_{y}_UNK_visitor' for y in (2024,2025)}
        removed_npl = {r['id'] for r in baseline['flows'] if r['receiver']=='NPL' and r['amount_cny']>0}
        for old in baseline['flows']:
            row = current.get(old['id'])
            if old['id'] in removed_idn | removed_npl:
                if row is not None:changed.append([old['id'],'superseded positive fee edge retained'])
                continue
            if old['receiver']=='AUS' and old['year']==2025:
                if row is None:changed.append([old['id'],'allocation disappeared'])
                continue
            if old['receiver']=='IND' and old['year'] in (2024,2025):
                if row is None:changed.append([old['id'],'India receipt bridge disappeared'])
                continue
            if row is None or any(row.get(k)!=old.get(k) for k in ['year','amount_cny','lower_cny','upper_cny','quantity','quantity_basis']) or any(normal(row[k])!=normal(old[k]) for k in ['payer','receiver']):
                changed.append(old['id'])
        check('r9 fee rows preserved outside evidenced IDN,NPL,IND receipt and AUS2025 revisions', changed, len(baseline['flows']))

    americas = [r for r in observations if r.get('native_file')=='data/research/americas_expansion_v6/observations.json']
    americas_ids = {o['observation_id'] for o in americas}
    check('Colombia and Dominican issuance stays outside fee-event inputs',
          [r['id'] for r in flows if set(r.get('observation_ids', [])) & americas_ids], len(americas))
    co = next(s for s in contexts['COL']['series'] if s['native_series_id']=='col_visa_total_monthly')
    co_points = next(p['points'] for p in co['partners'] if p['code']=='WORLD')
    check('Colombia preserves 107 published months and never fills the 2025-2026 gaps',
          [] if len(co_points)==107 and len([p for p in co_points if p['year']==2025])==10 and len([p for p in co_points if p['year']==2026])==1 and co_points[-1]['period_end']=='2026-09-30' else ['month coverage changed'],len(co_points))
    dom = next(s for s in contexts['DOM']['series'] if s['native_series_id']=='dom_visa_total_annual')
    dom_points = dom['partners'][0]['points']
    p2024 = next(p for p in dom_points if p['year']==2024)
    check('Dominican2024 leaf sum retains published version discrepancy and all component sources',
          [] if p2024['value']==23736 and p2024.get('quality_issue') and len(dom['source_ids'])>=12 and '2026' not in {str(p['year']) for p in dom_points} else ['version, source or partial-year boundary lost'],len(dom_points))

    usa = [s for s in contexts['USA']['series'] if s['native_series_id'].startswith('usa_gao_')]
    location = next(s for s in usa if s['native_series_id']=='usa_gao_niv_applications_consular_location_fiscal')
    us_errors=[]
    if {p['code'] for p in location['partners']}!={'CHN','IND','BRA','MEX'}:
        us_errors.append('four consular locations merged or missing')
    for partner in location['partners']:
        for point in partner['points']:
            row=by_id[point['observation_id']]
            if row['origin']!='UNK' or row.get('context_partner_code')!=partner['code']:
                us_errors.append([point['observation_id'],'consular location changed payer nationality'])
        if partner['code']=='CHN' and '中国香港' not in partner['name']:
            us_errors.append('China location Hong Kong scope qualifier missing')
    for series in usa:
        for partner in series['partners']:
            for point in partner['points']:
                row=by_id[point['observation_id']]
                for key in ('original_value','original_unit','source_rounding_unit','source_rounding_half_unit'):
                    if point.get(key)!=row.get(key):us_errors.append([point['observation_id'],key,'source precision lost'])
                if not row.get('context_only') or row.get('eligible_money_ledger') is not False:
                    us_errors.append([point['observation_id'],'activity treated as fee input'])
    check('US official estimates, fiscal periods, precision and consular-location scope survive rendering',us_errors,sum(len(p['points']) for s in usa for p in s['partners']))

    japanese = next(s for s in contexts['JPN']['series'] if s['native_series_id']=='core_jp_nationality_all_issued')
    china_jp = next(p for p in japanese['partners'] if p['code']=='CHN')['points']
    check('Japan nationality history spans15 actual years and separates Hong Kong document rows',
          [] if [p['year'] for p in china_jp]==list(range(2011,2026)) and china_jp[-1]['value']==5709706
          and len([p for p in japanese['partners'] if p['code'].startswith('HKG')])>=3
          else ['Japan history or original document identity lost'], len(china_jp))
    new_activity={o['observation_id'] for o in observations if o.get('native_file') in
                  ['data/research/middleeast_europe_v7/observations.json','data/research/philippines_expansion_v7/observations.json']}
    check('new eastern Europe and Philippines activity never becomes a fee edge',
          [r['id'] for r in flows if set(r.get('observation_ids',[])) & new_activity],len(new_activity))
    oman=next(s for s in contexts['OMN']['series'] if s['metric']=='inbound_entries_using_tourism_visa')
    oman_points=[p for partner in oman['partners'] for p in partner['points']]
    check('Oman visa entries retain border-event unit,100-event precision and preliminary2025 status',
          [] if oman['domain']=='mobility' and oman['unit']=='border_entry_events' and len(oman_points)==10
          and all(p.get('source_rounding_unit')==100 for p in oman_points)
          and any(p['year']==2025 and p.get('source_status')=='preliminary' for p in oman_points)
          else ['Oman entry status or precision lost'], len(oman_points))
    nepal=json.loads((ROOT/'data/research/south_asia_expansion_v7/annual_cash_controls.json').read_text())
    fiscal={r['year']:r for r in nepal}
    npl_rows=[r for r in flows if r['receiver']=='NPL' and r['amount_cny']>0]
    npl_errors=[]
    for row in npl_rows:
        y=row['year'];expected=0
        for term in row['parameters'].get('day_weight_terms', []):
            control=fiscal[term['fiscal_year_end']]
            a,b=date.fromisoformat(control['period_start']),date.fromisoformat(control['period_end'])
            days=(b-a).days+1;overlap=(min(b,date(y,12,31))-max(a,date(y,1,1))).days+1
            expected+=control['amount']*overlap/days
        if y==2025:expected=fiscal[2025]['amount']
        if y<2023:expected=(fiscal[y]['amount']+fiscal[y+1]['amount'])/2
        if not math.isclose(expected,row['amount'],rel_tol=1e-12) or row['payer']!='UNK' or row['quantity'] is not None:
            npl_errors.append(row['id'])
    if {r['year'] for r in npl_rows}!=set(range(2019,2026)):npl_errors.append('wrong calendar years')
    if len([r for r in flows if r['receiver']=='NPL' and r['amount_cny']==0 and r['payer'] in ('CHN','IND')])!=4:
        npl_errors.append('explicit China/India free-policy scope changed')
    check('Nepal national cash controls bridge by actual dates,replace old positives and preserve free policies',npl_errors,len(npl_rows))

    report = dict(version=index['meta']['version'], ui_version=index['meta']['ui_version'],
                  passed=all(c['passed'] for c in checks), countries=len(contexts), context_points=point_count, checks=checks)
    (ROOT / 'docs/validation/country-context-data.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'checks'}, ensure_ascii=False))
    assert report['passed'], [c for c in checks if not c['passed']]


if __name__ == '__main__':
    main()
