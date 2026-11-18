#!/usr/bin/env python3
"""Recent official travel context, offline by default; never a fee model.

OECD SDMX arrivals/departures retain visitor and source distinctions. Eurostat
accommodation arrivals retain their establishment/residence scope, distinct
from border arrivals. No nights, revenue, visa counts or unique people inferred.
"""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import date
import argparse, calendar, csv, hashlib, json, math, re
import xml.etree.ElementTree as ET
import pycountry
from entity_names import canonical_name

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/global_recent_mobility_v4'
OUT = ROOT / 'data/research/global_recent_mobility_v4'
CUT = '2026-11-17'
URLS = {
    'oecd_inbound_data.xml': 'https://sdmx.oecd.org/public/rest/v1/data/OECD.CFE.TOU,DSD_TOURISM_INTER@DF_INBOUND,1.1/all?startPeriod=2021&endPeriod=2025',
    'oecd_outbound_data.xml': 'https://sdmx.oecd.org/public/rest/v1/data/OECD.CFE.TOU,DSD_TOURISM_INTER@DF_OUTBOUND,1.1/all?startPeriod=2021&endPeriod=2025',
    'oecd_inbound_structure.xml': 'https://sdmx.oecd.org/public/rest/v1/dataflow/OECD.CFE.TOU/DSD_TOURISM_INTER@DF_INBOUND/1.1?references=all',
    'eurostat_accommodation_2021_2025.json': 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tour_occ_arnraw?lang=en&freq=A&unit=NR&nace_r2=I551-I553&sinceTimePeriod=2021&untilTimePeriod=2025',
    'eurostat_accommodation_residency_2021_2025.json': 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tour_occ_arnat?lang=en&freq=A&unit=NR&nace_r2=I551-I553&sinceTimePeriod=2021&untilTimePeriod=2025',
    'eurostat_nonresident_accommodation_monthly_2024_2026.json': 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tour_occ_arm?lang=en&freq=M&c_resid=FOR&unit=NR&nace_r2=I551-I553&sinceTimePeriod=2024-01&untilTimePeriod=2026-12',
    'eurostat_tourism_metadata.html': 'https://ec.europa.eu/eurostat/cache/metadata/en/tour_occ_esms.htm',
}
NS = {'g': 'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic'}
VISITOR = {'_T': '全部访客', 'OVERNIGHT': '过夜游客', 'SAME_DAY': '当日访客'}
OECD_SOURCE = {'TDS': '需求侧调查', 'TSS': '供给侧调查', '_Z': '原表未分采集渠道'}
CN_NAMES = {'CHN': '中国大陆', 'HKG': '中国香港', 'MAC': '中国澳门', 'TWN': '中国台湾'}


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = list(dict.fromkeys(k for r in obj for k in r))
        with (OUT / name.replace('.json', '.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, keys)
            w.writeheader()
            w.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in obj)


def english(e):
    return next((x.text for x in e if x.tag.endswith('Name') and x.attrib.get('{http://www.w3.org/XML/1998/namespace}lang') == 'en'), None)


def iso2(code):
    if code in {'EL': 'GRC', 'UK': 'GBR', 'XK': 'XKX'}:
        return {'EL': 'GRC', 'UK': 'GBR', 'XK': 'XKX'}[code]
    c = pycountry.countries.get(alpha_2=code)
    return c.alpha_3 if c else None


def period(value):
    if re.fullmatch(r'\d{4}', value):
        return value + '-01-01', value + '-12-31', 'calendar_year'
    if re.fullmatch(r'\d{4}-\d{2}', value):
        y, m = map(int, value.split('-'))
        return value + '-01', value + '-' + str(calendar.monthrange(y, m)[1]), 'calendar_month'
    raise ValueError(('unhandled statistical period', value))


def jsonstat_cells(j):
    dims, sizes = j['id'], j['size']
    cats = {d: {v: k for k, v in j['dimension'][d]['category']['index'].items()} for d in dims}
    for index, value in sorted(j['value'].items(), key=lambda kv: int(kv[0])):
        n, coord = int(index), {}
        for d, size in reversed(list(zip(dims, sizes))):
            coord[d] = cats[d][n % size]
            n //= size
        assert n == 0
        yield index, coord, value, j.get('status', {}).get(index)


def main(download=False):
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if download:
        import requests
        for filename, url in URLS.items():
            r = requests.get(url, timeout=90)
            r.raise_for_status()
            if filename.endswith('.json'):
                assert r.json().get('class') == 'dataset'
            elif filename.endswith('.xml'):
                ET.fromstring(r.content)
            (RAW / filename).write_bytes(r.content)
    sources, observations, missing, excluded, checks = [], [], [], [], []

    def source(sid, filename, publisher, title, notes):
        p = RAW / filename
        sources.append(dict(source_id=sid, title=title, publisher=publisher, url=URLS[filename],
                            local_path=str(p.relative_to(ROOT)), retrieved_at=CUT,
                            sha256=hashlib.sha256(p.read_bytes()).hexdigest(), bytes=p.stat().st_size,
                            source_quality='official_primary', archive_kind='original_api_response' if filename.endswith(('.xml', '.json')) else 'original_document',
                            notes=notes))
        return sid

    meta_sid = source('recent_oecd_tourism_structure', 'oecd_inbound_structure.xml', 'OECD',
                      'International tourism SDMX data structure, code lists and dataflow definitions',
                      'Includes the shared DSD_TOURSIM_INTER structure and English definitions for visitor, accommodation, survey source, unit and status flags. OECD SDMX source spelling TOURSIM retained.')
    structure = ET.fromstring((RAW / 'oecd_inbound_structure.xml').read_bytes())
    labels = {}
    for cl in structure.iter():
        if cl.tag.endswith('Codelist'):
            labels[(cl.attrib.get('agencyID'), cl.attrib.get('id'))] = {x.attrib['id']: english(x) for x in cl if x.tag.endswith('Code')}
    region_labels = labels['OECD', 'CL_REGIONAL']
    measure_labels = labels['OECD.CFE.TOU', 'CL_MEASURE']
    status_labels = labels['SDMX', 'CL_OBS_STATUS']
    oecd_counts = {}
    for direction in ['inbound', 'outbound']:
        filename = f'oecd_{direction}_data.xml'
        sid = source('recent_oecd_' + direction, filename, 'OECD Tourism Statistics / national reporting authorities',
                     f'{direction.title()} tourism, annual 2021–2025, SDMX original',
                     'Only arrivals/departures and origin/destination-market series are used. Nights are excluded. All-visitors, overnight and same-day series stay separate. Supply/demand survey series stay separate. National statistical coverage varies; not visa or unique-person counts.')
        tree = ET.fromstring((RAW / filename).read_bytes())
        nn, selected, nulls = 0, 0, 0
        for si, series in enumerate(tree.findall('.//g:Series', NS)):
            key = {v.attrib['id']: v.attrib['value'] for v in series.findall('./g:SeriesKey/g:Value', NS)}
            attributes = {v.attrib['id']: v.attrib['value'] for v in series.findall('./g:Attributes/g:Value', NS)}
            if key['MEASURE'] not in ('ARRIVALS', 'TOP_MKT', 'DEPARTURES', 'TOP_DES'):
                excluded.append(dict(source_id=sid, series_index=si, key=key, reason='bed_nights_are_not_arrival_events'))
                continue
            reporting = key['REF_AREA']
            if not pycountry.countries.get(alpha_3=reporting):
                excluded.append(dict(source_id=sid, series_index=si, key=key, reason='subnational_reference_area_not_promoted_to_country'))
                continue
            cp = key['COUNTERPART_AREA']
            if cp == '_Z':
                partner, partner_name = 'WORLD', '全部来源' if direction == 'inbound' else '全部目的地'
            elif pycountry.countries.get(alpha_3=cp):
                partner, partner_name = cp, CN_NAMES.get(cp, canonical_name(cp, region_labels.get(cp, cp)))
            else:
                partner, partner_name = 'SOURCE:OECD:' + cp, (region_labels.get(cp) or cp) + '（原表合并来源）'
            visitor = key['VISITOR_TYPE']
            assert visitor in VISITOR
            assert key['UNIT_MEASURE'] == 'PS'
            mult = int(attributes.get('UNIT_MULT', '0'))
            source_code = key['SOURCE']
            series_id = 'oecd_' + direction + '_' + visitor.lower().strip('_') + '_' + key['ACCOMMODATION_TYPE'].lower().strip('_') + '_' + source_code.lower().strip('_')
            title = ('入境' if direction == 'inbound' else '出境') + VISITOR[visitor] + ('到达' if direction == 'inbound' else '出发') + '（OECD · ' + OECD_SOURCE.get(source_code, source_code) + '）'
            for oi, o in enumerate(series.findall('./g:Obs', NS)):
                time = o.find('./g:ObsDimension', NS).attrib['value']
                exact = period(time)
                cell = o.find('./g:ObsValue', NS)
                obs_attributes = {v.attrib['id']: v.attrib['value'] for v in o.findall('./g:Attributes/g:Value', NS)}
                locator = f'SDMX Series[{si}]/Obs[{oi}]; ' + '; '.join(f'{k}={v}' for k, v in key.items()) + '; TIME_PERIOD=' + time
                if cell is None or cell.attrib.get('value') in (None, ''):
                    missing.append(dict(source_id=sid, source_locator=locator, key=key, time_period=time, source_status=obs_attributes, value=None))
                    nulls += 1
                    continue
                nn += 1
                raw_value = float(cell.attrib['value'])
                value = raw_value * 10 ** mult
                assert value >= 0 and math.isfinite(value)
                status = obs_attributes.get('OBS_STATUS')
                selected += 1
                observations.append(dict(observation_id='recent_' + series_id + '_' + reporting + '_' + cp + '_' + time,
                    source_id=sid, source_ids=[sid, meta_sid], metadata_source_id=meta_sid, source_locator=locator,
                    destination=reporting, reporting_country=reporting, origin=partner, origin_name=partner,
                    origin_display_name=partner_name, raw_origin_label=region_labels.get(cp, cp), origin_raw_code=cp,
                    origin_label=partner_name, origin_basis='source_country_unqualified' if direction == 'inbound' else 'reporting_country_outbound_and_destination',
                    metric='international_visitor_arrivals' if direction == 'inbound' else 'international_visitor_departures',
                    raw_metric=measure_labels[key['MEASURE']], value=int(value) if value.is_integer() else value,
                    raw_value=cell.attrib['value'], original_unit_code=key['UNIT_MEASURE'], original_unit_multiplier=mult,
                    unit='arrival_events' if direction == 'inbound' else 'departure_events',
                    period_start=exact[0], period_end=exact[1], period_type=exact[2], year=int(time[:4]),
                    calculation_type='official_estimate' if status == 'E' else 'published_statistical_series',
                    observation_domain='mobility', context_only=True, eligible_money_ledger=False,
                    aggregation_role='country_total' if cp == '_Z' else 'country_component' if pycountry.countries.get(alpha_3=cp) else 'source_bucket_component',
                    flow_direction=direction, series_id=series_id, series_label=title,
                    scope=f"{direction};visitor_type={visitor};accommodation_type={key['ACCOMMODATION_TYPE']};source={source_code}",
                    visitor_type=visitor, accommodation_type=key['ACCOMMODATION_TYPE'], survey_source=source_code,
                    source_status=status, source_status_label=status_labels.get(status, status), source_attributes=obs_attributes,
                    notes='原表PS计量的是旅行统计数量，保留小数估计；不视为独立人数或签证申请。全部访客含过夜与当日访客；过夜/当日分别建序列。供给侧与需求侧调查分别保留。来源市场口径按报告国原始定义，不转为付款国籍。TOP市场分项不穷尽全体，且不与总量重复相加。'))
        oecd_counts[direction] = dict(nonnull_country_arrival_departure_cells=nn, selected_observations=selected, missing_cells=nulls)
        checks.append(dict(check='oecd_' + direction + '_non_null_events_preserved', passed=nn == selected, **oecd_counts[direction]))

    emeta_sid = source('recent_eurostat_tourism_metadata', 'eurostat_tourism_metadata.html', 'Eurostat',
                      'Occupancy of tourist accommodation establishments — reference metadata',
                      'Scope is NACE55.1,55.2,55.3: hotels/similar, holiday/short-stay and campsites. Arrival means arriving/checking into a tourist accommodation establishment, not crossing a border. Usual residence is distinct from nationality. National size/threshold coverage and revisions remain in source metadata.')
    euro_files = [
        ('eurostat_accommodation_2021_2025.json', 'recent_eurostat_accommodation_origin', 'Arrivals at tourist accommodation establishments by country of origin of the tourist', 'partner'),
        ('eurostat_accommodation_residency_2021_2025.json', 'recent_eurostat_accommodation_residency', 'Arrivals at tourist accommodation establishments by residence status', 'annual_total'),
        ('eurostat_nonresident_accommodation_monthly_2024_2026.json', 'recent_eurostat_accommodation_monthly', 'Monthly non-resident arrivals at tourist accommodation establishments', 'monthly_total'),
    ]
    euro_counts, annual_totals, bilateral = {}, {}, defaultdict(dict)
    for filename, sid, title, role in euro_files:
        sid = source(sid, filename, 'Eurostat / national statistical institutes', title,
                     'Original JSON-stat, reporting countries only in display. Nonresident annual totals are read directly from FOR in tour_occ_arnat; country residence components from tour_occ_arnraw do not imply exhaustive coverage. Regional aggregates, domestic rows and overlapping totals are kept only in frozen original/exclusions. No values are inferred from overnight stays.')
        j = json.loads((RAW / filename).read_text())
        selected, nulls, reasons = 0, 0, Counter()
        for index, coord, value, flag in jsonstat_cells(j):
            reporting = iso2(coord['geo'])
            residence = coord['c_resid']
            locator = 'JSON-stat value[' + index + ']; ' + '; '.join(f'{d}={coord[d]}' for d in j['id'])
            assert coord['nace_r2'] == 'I551-I553' and coord['unit'] == 'NR'
            if not reporting:
                reasons['reporting_region_aggregate_not_country'] += 1
                continue
            if role == 'partner':
                partner = iso2(residence)
                if not partner or partner == reporting:
                    reason = 'domestic_or_overlapping_regional_residence_bucket'
                    reasons[reason] += 1
                    continue
                partner_name = CN_NAMES.get(partner, canonical_name(partner, j['dimension']['c_resid']['category']['label'][residence]))
                aggregation_role = 'country_component'
            else:
                if residence != 'FOR':
                    reasons['domestic_and_all_resident_totals_not_foreign_arrivals'] += 1
                    continue
                partner, partner_name, aggregation_role = 'WORLD', '全部非居民来源', 'country_total'
            time = coord['time']
            exact = period(time)
            if value is None:
                nulls += 1
                missing.append(dict(source_id=sid, source_locator=locator, key=coord, time_period=time, value=None, source_status=flag))
                continue
            assert isinstance(value, (int, float)) and value >= 0 and math.isfinite(value)
            selected += 1
            series_id = 'eurostat_nonresident_accommodation_arrivals' + ('_monthly' if role == 'monthly_total' else '')
            observations.append(dict(observation_id=f'recent_estat_accommodation_{coord["geo"]}_{residence}_{time}',
                source_id=sid, source_ids=[sid, emeta_sid], metadata_source_id=emeta_sid, source_locator=locator,
                destination=reporting, reporting_country=reporting, origin=partner, origin_name=partner,
                origin_label=partner_name, origin_display_name=partner_name, raw_origin_label=j['dimension']['c_resid']['category']['label'][residence], origin_raw_code=residence,
                origin_basis='place_of_residence', metric='nonresident_accommodation_arrivals', raw_metric=j['label'],
                value=value, unit='arrival_events', period_start=exact[0], period_end=exact[1], period_type=exact[2], year=int(time[:4]),
                calculation_type='official_estimate' if flag and 'e' in flag else 'published_statistical_series',
                observation_domain='mobility', context_only=True, eligible_money_ledger=False,
                aggregation_role=aggregation_role, flow_direction='inbound', series_id=series_id,
                series_label='非居民住宿设施到达（Eurostat' + (' · 月度' if role == 'monthly_total' else '') + '）',
                scope='nonresident_arrivals_at_NACE_55.1_55.2_55.3_tourist_accommodation_establishments',
                source_status=flag, source_data_updated=j.get('updated'),
                notes='住宿设施到达次数，非口岸入境。旅客换住多家设施可能重复计次；居住地不等于国籍。NACE55.1酒店、55.2度假及短住、55.3露营设施；各国门槛/采集范围见元数据。原表统计符号保留；非居民总计直接取FOR，来源国分项不穷尽全体且不与总计相加。'))
            if role == 'annual_total':
                annual_totals[reporting, time] = value
            elif role == 'partner':
                bilateral[reporting, time][partner] = value
        euro_counts[role] = dict(nonnull_selected=selected, missing_selected=nulls, excluded_cell_counts=dict(reasons), raw_data_updated=j.get('updated'))
        excluded.append(dict(source_id=sid, reason='cell_filter_summary', counts=dict(reasons)))
        checks.append(dict(check='eurostat_' + role + '_selected_scope', passed=selected > 0, **euro_counts[role]))
    # Every component is an independently published residence-country leaf.
    # The set is not exhaustive and is never balanced to the foreign total.
    exceed = [(c, y, partner, value, annual_totals[c, y]) for (c, y), parts in bilateral.items() if (c, y) in annual_totals for partner, value in parts.items() if value > annual_totals[c, y]]
    checks.append(dict(check='individual_foreign_residence_components_do_not_exceed_same_scope_foreign_total', passed=not exceed, examples=exceed[:10], totals_checked=len(annual_totals)))
    annual_foreign, monthly_foreign = {}, defaultdict(list)
    for row in observations:
        if row['metric'] == 'nonresident_accommodation_arrivals' and row['origin'] == 'WORLD':
            key = row['destination'], row['year']
            if row['period_type'] == 'calendar_year':
                annual_foreign[key] = row
            else:
                monthly_foreign[key].append(row)
    annual_monthly_comparisons = []
    for key, rows in sorted(monthly_foreign.items()):
        if len(rows) != 12 or key not in annual_foreign:
            continue
        annual = annual_foreign[key]
        total = sum(r['value'] for r in rows)
        annual_monthly_comparisons.append(dict(code=key[0], year=key[1], annual_value=annual['value'],
            sum_12_published_months=total, difference=total-annual['value'],
            relative_difference=(total-annual['value'])/annual['value'] if annual['value'] else None,
            annual_observation_id=annual['observation_id'],
            monthly_observation_ids=[r['observation_id'] for r in sorted(rows, key=lambda r:r['period_start'])],
            interpretation='年度与月度为独立发布的原表。差异可能来自覆盖范围或更新，不强制对账、不以月度替换年度；本包未识别逐国差异的唯一原因。'))
    ids = Counter(r['observation_id'] for r in observations)
    checks.append(dict(check='observation_ids_unique', passed=all(n == 1 for n in ids.values()), observations=len(observations)))
    display_keys = Counter((r['destination'], r['series_id'], r['origin'], r['period_start'], r['period_end']) for r in observations)
    checks.append(dict(check='country_series_partner_period_unique', passed=all(n == 1 for n in display_keys.values()), examples=[str(k) for k, n in display_keys.items() if n > 1][:10]))
    checks.append(dict(check='all_mobility_context_excluded_from_fee_model', passed=all(r['observation_domain'] == 'mobility' and r['context_only'] and r['eligible_money_ledger'] is False for r in observations)))
    checks.append(dict(check='no_nights_or_revenue_substituted_for_arrivals', passed=all(r['unit'] in ['arrival_events', 'departure_events'] and 'NIGHTS' not in str(r['raw_metric']).upper() for r in observations)))
    checks.append(dict(check='china_product_names_canonical', passed=all(r['origin_label'] == CN_NAMES[r['origin']] for r in observations if r['origin'] in CN_NAMES)))
    checks.append(dict(check='missing_cells_preserved_outside_numeric_display_not_zero_filled', passed=bool(missing) and all(r['value'] is None for r in missing), missing_cells=len(missing)))
    # Source-specific reference checks make the selected XML/JSON transformations
    # reviewable without assuming a changing external headline is an oracle.
    sample = {r['observation_id']: r for r in observations}
    reference = [('recent_oecd_inbound_t_z_tds_JPN__Z_2025', 42683837),
                 ('recent_oecd_inbound_t_z_tds_JPN__Z_2024', 36870148)]
    for oid, value in reference:
        checks.append(dict(check='source_reference_' + oid, passed=sample.get(oid, {}).get('value') == value, expected=value, actual=sample.get(oid, {}).get('value')))
    cov = defaultdict(lambda: {'source_ids': set(), 'series': set()})
    for r in observations:
        box = cov[r['destination'], r['year']]
        box['source_ids'].update(r['source_ids'])
        box['series'].add(r['series_id'])
    coverage = [dict(code=c, year=y, visa_group='unclassified', status='mobility_context_only',
                     mobility_context_known=True, source_ids=sorted(v['source_ids']),
                     notes='已归档近期旅行／住宿活动原表，独立于签证申请量和费用；' + str(len(v['series'])) + '条原口径序列。') for (c, y), v in sorted(cov.items())]
    report = dict(package='global_recent_mobility_v4', sources=len(sources), observations=len(observations),
                  reporting_countries=len({r['destination'] for r in observations}),
                  origin_destination_country_codes=len({r['origin'] for r in observations if pycountry.countries.get(alpha_3=r['origin'])}),
                  years=sorted({r['year'] for r in observations}),
                  annual_observations=sum(r['period_type'] == 'calendar_year' for r in observations),
                  monthly_observations=sum(r['period_type'] == 'calendar_month' for r in observations),
                  monthly_last_period=max(r['period_end'] for r in observations if r['period_type'] == 'calendar_month'),
                  by_metric=dict(Counter(r['metric'] for r in observations)),
                  oecd=oecd_counts, eurostat=euro_counts, missing_cells=len(missing),
                  annual_monthly_comparisons=len(annual_monthly_comparisons),
                  annual_monthly_differences=sum(r['difference'] != 0 for r in annual_monthly_comparisons),
                  money_flows_added=0, checks_passed=all(r['passed'] for r in checks))
    for name, obj in [('sources.json', sources), ('observations.json', observations), ('coverage.json', coverage),
                      ('missing_cells.json', missing), ('excluded_candidates.json', excluded),
                      ('annual_monthly_comparison.json', annual_monthly_comparisons), ('checks.json', checks), ('report.json', report)]:
        write(name, obj)
    (OUT / 'README.md').write_text('''# 近期全球旅行与住宿活动背景\n\n本包将OECD国际旅游统计的2021–2025年度到达/出发及主要市场，与Eurostat2021–2025住宿设施到达和2024–2026月度非居民到达接入独立背景层。\n\n- OECD全部访客、过夜游客、当日访客分别保留；供给侧与需求侧调查分开。原单位PS仍按旅行统计原指标展示，并不表示独立人数。主要市场不穷尽全体。\n- Eurostat指标是到达酒店/短住/露营设施，不是跨境入境。来源是通常居住地，不是国籍。非居民总计直接取FOR；仅保留可识别外国居住地的分项，不加总重叠地区或制造残差。月度发布至2026年9月，未加成2026全年。\n- 原始null/无值单元、估计/初步/断点符号保留；数值展示不把缺失变0。缺失与排除明细独立导出。原表中已包含的真实0保持0。\n- 数据来源为下载时的OECD/Eurostat版本，国家间采集范围与方法不同；不把住宿/边境/调查系列拼成同口径长趋势。\n- 中国大陆、中国香港、中国澳门、中国台湾按原表统计范围标示，遵循一个中国原则。\n- 所有记录均context_only=true、eligible_money_ledger=false，不建任何费用流。\n\n复算：`.research-venv/bin/python scripts/research_global_recent_mobility_v4.py`；只有显式`--download`才联网刷新原件。\n''')
    print(json.dumps(report, ensure_ascii=False))
    assert report['checks_passed'], [c for c in checks if not c['passed']]


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--download', action='store_true')
    main(p.parse_args().download)
