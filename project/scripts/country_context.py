"""Compact, lazy country travel/visa context without changing any money edge."""
from collections import Counter, defaultdict
from pathlib import Path
import gzip, hashlib, json, math, re
from observation_domains import observation_domain

LABELS = {
    'visitor_arrivals': '国际访客到达', 'tourist_arrivals': '国际游客到达',
    'tourist_arrivals_total': '国际游客到达', 'tourist_arrivals_source_market': '游客到达（来源市场）',
    'visa_free_entries': '外国人免签入境', 'entered': '持统一电子签入境',
    'foreign_visa_and_residence_documents': '境内外国人签证及居留等证件',
    'border_entry_refusals': '外部边境拒绝入境',
}
UNIT_LABELS = {
    'percent': '%', '%': '%', 'percentage': '%', 'persons_rounded_border_refusals': '人（原表按5人取整）',
    'arrival_events': '人次', 'departure_events': '人次', 'entry_events': '人次',
    'border_crossing_events': '人次', 'events': '人次', 'count': '人次',
    'applications': '次申请', 'visas': '次签发', 'visa_events': '次', 'documents': '证次',
    'residence_permits': '份许可',
    'application_events': '次申请', 'service_actions': '次服务', 'processed_visa_events': '次处理',
    'visa_issuance_events': '次签发',
    'adjudication_events': '次审理',
    'decisions': '次决定', 'persons': '人（原表计数）', 'border_entry_events': '入境人次',
    'transaction_events': '次事务', 'visa_recipients_as_reported': '获签者（原表计数）',
}
BASIS_LABELS = {
    'nationality': '国籍', 'citizenship': '国籍', 'place_of_residence': '通常居住地',
    'country_of_residence': '通常居住地', 'residence': '通常居住地',
    'usual_residence_of_departing_traveller': '出境者通常居住地',
    'all_source_markets': '全部来源市场', 'statistical_population_scope': '原表人口统计范围',
    'source_market_not_verified_payer_nationality': '来源市场',
    'observed_nationality': '国籍', 'all_nationalities': '全部国籍',
    'passport_nationality': '护照国籍', 'not_published': '申请人国籍未公开',
    'indian_passport_and_reported_destination': '印度护照及报告目的地',
    'source_country_unqualified': '原表来源地', 'aggregate_control': '原表合计',
    'all_consular_posts': '全球使领馆合计', 'consular_post_location': '办理使领馆',
    'reporting_country_outbound_and_destination': '报告国出境及目的地',
    'all_locations_total': '全球合计',
    'consular_country_location_not_nationality': '受理领事所在地',
    'nationality_region_or_document_as_published': '国籍／地区／旅行证件',
    'source_country_as_published': '原表来源国',
    'visa_applicant_citizenship': '申请人国籍', 'not_reported': '国籍未披露',
    'unallocated_nationality': '国籍未披露',
    'all_consular_posts_abroad': '全球驻外机构合计',
    'issuing_post_location_not_citizenship': '签发机构所在地',
}
REGION_LABELS = {
    'NORTH AMERICA':'北美洲', 'CENTRAL AND SOUTH AMERICA':'中南美洲', 'WESTERN EUROPE':'西欧',
    'EASTERN EUROPE':'东欧', 'AFRICA':'非洲', 'WEST ASIA':'西亚', 'SOUTH ASIA':'南亚',
    'SOUTH EAST ASIA':'东南亚', 'EAST ASIA':'东亚', 'AUSTRALASIA':'澳大利西亚',
    'OCEANIA':'大洋洲', 'ASIA':'亚洲', 'EUROPE':'欧洲', 'OTHERS':'其他地区',
}


def context_eligible(row):
    d = observation_domain(row)
    return d == 'mobility' or d == 'document_activity' and row.get('metric') == 'foreign_visa_and_residence_documents' or bool(row.get('series_id')) and d in ('visa_activity', 'document_activity', 'rate')


def build_country_context(observations, entities, outdir):
    """Preserve original periods/partners. Never sum country totals and parts.

    Native series_id is preferred. Legacy context is grouped only when metric,
    source, origin basis, visa type and frequency match. Annual source documents
    may explicitly share a series ID, with each point retaining its own source.
    """
    target = Path(outdir) / 'context'
    target.mkdir(exist_ok=True)
    for stale in target.glob('*.json.gz'):
        stale.unlink()
    names = {e['code']: e['name'] for e in entities}
    names.update(WORLD='全部来源', UNK='未分配／未知')
    country_codes = {e['code'] for e in entities if e.get('kind') == 'country_or_jurisdiction'} | {'SCH'}
    groups, exclusions = defaultdict(dict), Counter()
    accepted = 0
    for row in observations:
        code = row.get('destination')
        if not context_eligible(row) or code not in country_codes:
            continue
        value = row.get('value')
        if not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            continue
        start, end = row.get('period_start'), row.get('period_end')
        if not start or not end or not re.match(r'^\d{4}-\d{2}-\d{2}$', start) or not re.match(r'^\d{4}-\d{2}-\d{2}$', end):
            exclusions['missing_exact_period'] += 1
            continue
        metric, domain = row.get('metric') or '', observation_domain(row)
        origin = row.get('context_partner_code') or row.get('origin') or 'WORLD'
        # Explicit total labels with a legacy UNK placeholder retain the total
        # role. Nothing here changes the payer of a financial row.
        if metric == 'tourist_arrivals_total' or row.get('aggregation_role') == 'country_total' and origin in ('UNK', None):
            origin = 'WORLD'
        frequency = row.get('period_type') or ('calendar_year' if start[5:] == '01-01' and end[5:] == '12-31' else 'source_period')
        sid = row.get('series_id')
        if not sid:
            if metric in ('visa_free_entries', 'foreign_visa_and_residence_documents') and code == 'CHN':
                sid = 'nia_' + metric
            else:
                sid = metric + '__' + str(row.get('source_id'))
        # Prevent shared IDs from silently joining differing statistical scopes.
        identity = (sid, domain, row.get('unit'), row.get('origin_basis'), row.get('visa_type'), frequency, None if row.get('series_id') else row.get('scope'))
        key = hashlib.sha1(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:12]
        series = groups[code].setdefault(key, dict(id=key, native_series_id=sid,
                 label=row.get('series_label') or LABELS.get(metric, row.get('raw_metric') or metric),
                 domain=domain, metric=metric, unit=row.get('unit') or 'events',
                 unit_label=UNIT_LABELS.get(row.get('unit'), row.get('unit') or '次'),
                 origin_basis=row.get('origin_basis'), origin_basis_label=BASIS_LABELS.get(row.get('origin_basis'), row.get('origin_basis') or '原表总体'),
                 visa_type=row.get('visa_type'), scope=row.get('scope'), flow_direction=row.get('flow_direction'),
                 context_selection_default=row.get('context_selection_default', True), quality_issue=row.get('quality_issue'),
                 period_type=frequency, notes=set(), source_ids=set(), partners=defaultdict(list), _seen=set()))
        period_key = origin, start, end
        if period_key in series['_seen']:
            raise AssertionError(('duplicate_context_period', code, sid, period_key, row['observation_id']))
        series['_seen'].add(period_key)
        series['source_ids'].add(row['source_id'])
        series['source_ids'].update(row.get('source_ids') or [])
        if row.get('metadata_source_id'):
            series['source_ids'].add(row['metadata_source_id'])
        if row.get('notes'):
            series['notes'].add(row['notes'])
        series['partners'][origin].append({k: v for k, v in dict(year=int(end[:4]), period_start=start, period_end=end,
                  value=value, lower=row.get('lower'), upper=row.get('upper'), calculation_type=row.get('calculation_type'),
                  source_id=row['source_id'], observation_id=row['observation_id'], source_locator=row.get('source_locator'),
                  source_status=row.get('source_status'), source_status_label=row.get('source_status_label'), bound_type=row.get('bound_type'),
                  lower_inclusive=row.get('lower_inclusive'), upper_inclusive=row.get('upper_inclusive'),
                  aggregation_role=row.get('aggregation_role'),
                  coverage_status=row.get('coverage_status'), source_total_discrepancy=row.get('source_total_discrepancy'),
                  origin_original=row.get('origin_original'), raw_metric=row.get('raw_metric'), scope=row.get('scope'), source_bucket_parent=row.get('source_bucket_parent'),
                  quality_issue=row.get('quality_issue') or (row.get('source_total_discrepancy') or {}).get('interpretation'), context_selection_default=row.get('context_selection_default'),
                  original_value=row.get('original_value'), original_unit=row.get('original_unit'),
                  source_rounding_unit=row.get('source_rounding_unit'), source_rounding_half_unit=row.get('source_rounding_half_unit'),
                  raw_region=row.get('raw_region'), origin_raw_code=row.get('origin_raw_code')).items() if v is not None})
        if row.get('origin_label'):
            series['partners'][origin][-1]['origin_label'] = row['origin_label']
        if row.get('context_partner_label'):
            series['partners'][origin][-1]['origin_label'] = row['context_partner_label']
        accepted += 1
    manifest, point_counts = {}, Counter()
    for code, by_id in sorted(groups.items()):
        rows, years, source_ids = [], set(), set()
        for series in by_id.values():
            series.pop('_seen')
            series['source_ids'] = sorted(series['source_ids'])
            series['notes'] = ' '.join(sorted(series['notes']))
            partners = []
            for origin, points in sorted(series['partners'].items(), key=lambda kv: (kv[0] != 'WORLD', names.get(kv[0], kv[0]))):
                points.sort(key=lambda p: (p['period_start'], p['period_end']))
                source_name = next((p.get('origin_label') or p.get('origin_original') for p in points if p.get('origin_label') or p.get('origin_original')), origin)
                region = next((p.get('raw_region') for p in points if p.get('raw_region')), None)
                raw_code = str(next((p.get('origin_raw_code') for p in points if p.get('origin_raw_code')), ''))
                if origin not in names:
                    if raw_code == 'CHN-XZ-SOURCE':
                        source_name = '中国西藏（原表分列）'
                    elif raw_code.startswith('UNK:') and region:
                        source_name = REGION_LABELS.get(region.upper(), region) + '其他来源（原表分列）'
                    elif raw_code.startswith('REGION:'):
                        source_name = REGION_LABELS.get(str(region or source_name).upper(), region or source_name) + '汇总（原表分列）'
                partner_name = source_name if (origin == 'UNK' and series['origin_basis'] == 'not_published') or series['origin_basis'] == 'consular_country_location_not_nationality' else names.get(origin, source_name)
                partners.append(dict(code=origin, name=partner_name, points=points))
                years.update(p['year'] for p in points)
                point_counts[series['domain']] += len(points)
            series['partners'] = partners
            rows.append(series)
            source_ids.update(series['source_ids'])
        # Country totals and native recent data lead; legacy WDI remains easy to
        # select without crowding the default card with obsolete-year values.
        rows.sort(key=lambda s: (s['domain'] != 'mobility', s['native_series_id'].startswith('wdi_'),
                                not any(p['code'] == 'WORLD' for p in s['partners']), s['label']))
        payload = dict(schema='visa-country-context-1', code=code, name=names.get(code, code), series=rows)
        data = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        filename = f'context/{code}.json.gz'
        (Path(outdir) / filename).write_bytes(gzip.compress(data, mtime=0))
        manifest[code] = dict(file=filename, series_count=len(rows), years=sorted(years), source_ids=sorted(source_ids))
    return manifest, dict(countries=len(manifest), series=sum(m['series_count'] for m in manifest.values()),
                          points=accepted, by_domain=dict(point_counts), excluded=dict(exclusions),
                          context_gzip_bytes=sum(p.stat().st_size for p in target.glob('*.json.gz')))
