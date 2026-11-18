#!/usr/bin/env python3
"""Frozen travel/border context, independent of the government visa-fee ledger.

WDI supplies historical breadth; Eurostat supplies nationality and border detail.
Neither series is converted to visa applications, fee revenue or refusal rates.
Run offline by default. --download explicitly refreshes the frozen responses.
"""
from pathlib import Path
from collections import Counter
import argparse, csv, hashlib, json, math
import pycountry
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/mobility_context_v4'
OUT = ROOT / 'data/research/mobility_context_v4'
RETRIEVED = '2026-11-17'
URLS = {
    'wdi_arrivals.json': 'https://api.worldbank.org/v2/country/all/indicator/ST.INT.ARVL?date=2011:2025&format=json&per_page=20000',
    'wdi_departures.json': 'https://api.worldbank.org/v2/country/all/indicator/ST.INT.DPRT?date=2011:2025&format=json&per_page=20000',
    'wdi_arrivals_metadata.json': 'https://api.worldbank.org/v2/indicator/ST.INT.ARVL?format=json',
    'wdi_departures_metadata.json': 'https://api.worldbank.org/v2/indicator/ST.INT.DPRT?format=json',
    'eurostat_refused_entry.json': 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/migr_eirfs?lang=en&freq=A&unit=PER&border=TOTAL&reason=TOTAL&sinceTimePeriod=2011&untilTimePeriod=2025',
    'eurostat_metadata.html': 'https://ec.europa.eu/eurostat/cache/metadata/en/migr_eil_esms.htm',
    'nia_2019.html': 'https://www.nia.gov.cn/n741440/n741542/c1199336/content.html',
    'nia_2021.html': 'https://www.nia.gov.cn/n741435/n1194535/n1468227/index.html',
    'nia_2022.html': 'https://www.nia.gov.cn/n741435/n1194535/n1555230/index.html',
    'nia_2023.html': 'https://www.nia.gov.cn/n741435/n1194535/n1625663/index.html',
}


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = list(dict.fromkeys(k for r in obj for k in r))
        with (OUT / name.replace('.json', '.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, keys)
            w.writeheader()
            w.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in obj)


def iso2(code):
    special = {'EL': 'GRC', 'UK': 'GBR', 'XK': 'XKX', 'TOTAL': 'WORLD', 'UNK': 'UNK'}
    if code in special:
        return special[code]
    c = pycountry.countries.get(alpha_2=code)
    return c.alpha_3 if c else code


def main(download=False):
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if download:
        import requests
        for name, url in URLS.items():
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            if name.endswith('.json'):
                r.json()
            (RAW / name).write_bytes(r.content)
    sources, obs, checks = [], [], []

    def source(sid, name, publisher, title, notes):
        path = RAW / name
        sources.append(dict(source_id=sid, local_path=str(path.relative_to(ROOT)), url=URLS[name],
                            publisher=publisher, title=title, retrieved_at=RETRIEVED,
                            source_quality='official_primary', archive_kind='original_api_response' if name.endswith('.json') else 'original_document',
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size, notes=notes))
        return sid

    for direction, indicator, label in [('arrivals', 'ST.INT.ARVL', '国际旅游到达'), ('departures', 'ST.INT.DPRT', '国际旅游出境')]:
        sid = source('mobility_wdi_' + direction, 'wdi_' + direction + '.json', 'World Bank WDI / UN Tourism',
                     indicator + ' — ' + label + '，2011–2025查询快照',
                     '仅提取有数值的国家／地区，不提取地区和收入组总计；查询到2025不代表各年有数据。缺失保留缺失。旅游事件，非签证申请、付费或独立人数。')
        msid = source('mobility_wdi_' + direction + '_metadata', 'wdi_' + direction + '_metadata.json',
                      'World Bank WDI / UN Tourism', indicator + ' — definition and source metadata',
                      '到达的本国采集范围可能是边境、航空或住宿设施，部分国家用含一日游的访客数替代过夜游客。出境按通常居住地归属。')
        meta, records = json.loads((RAW / ('wdi_' + direction + '.json')).read_text())
        assert meta['pages'] == 1 and meta['total'] == len(records), meta
        for i, r in enumerate(records):
            code, value = r['countryiso3code'], r['value']
            if not pycountry.countries.get(alpha_3=code) or value is None:
                continue
            year = int(r['date'])
            assert isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
            obs.append(dict(observation_id=f'mobility_wdi_{direction}_{code}_{year}', source_id=sid,
                            source_locator=f'JSON [1][{i}]; indicator={indicator}; countryiso3code={code}; date={year}',
                            destination=code, origin='WORLD', origin_basis='all_source_markets' if direction == 'arrivals' else 'usual_residence_of_departing_traveller',
                            metric='international_tourist_' + direction, raw_metric=r['indicator']['value'],
                            value=value, unit='arrival_events' if direction == 'arrivals' else 'departure_events',
                            period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
                            calculation_type='official_estimate' if r.get('obs_status') == 'F' else 'published_statistical_series',
                            observation_domain='mobility', context_only=True, eligible_money_ledger=False,
                            aggregation_role='country_total', flow_direction='inbound' if direction == 'arrivals' else 'outbound',
                            series_id=f'wdi_{direction}', series_label=label + '（WDI／UN Tourism）',
                            scope='reporting_country_all_markets', source_status=r.get('obs_status') or None,
                            metadata_source_id=msid, notes='同一人多次旅行分别计次。各国采集范围见指标元数据；不用于费用／申请分母。'))
        rr = [r for r in obs if r['source_id'] == sid]
        checks.append(dict(check='wdi_' + direction + '_only_nonnull_country_rows', passed=len(rr) == sum(r['value'] is not None and bool(pycountry.countries.get(alpha_3=r['countryiso3code'])) for r in records),
                           rows=len(rr), countries=len({r['destination'] for r in rr}), first_year=min(r['period_start'][:4] for r in rr), last_year=max(r['period_start'][:4] for r in rr)))

    sid = source('mobility_eurostat_border_refusals', 'eurostat_refused_entry.json', 'Eurostat',
                 'migr_eirfs — Third country nationals refused entry at the external borders, 2011–2025',
                 'Annual rounded counts; all border types and all reasons. Preserve citizen, reporting geo, flags and missing cells. EU27 aggregate is retained separately and never added to member totals. Border refusal is different from a visa-application refusal.')
    msid = source('mobility_eurostat_border_metadata', 'eurostat_metadata.html', 'Eurostat',
                  'Immigration law enforcement — reference metadata',
                  'Regulation 862/2007 framework. Each person is counted once per reporting country and reference period; countries may overlap. Values are rounded to5; EU aggregate uses unrounded national inputs. No visa-refusal rate is inferred.')
    j = json.loads((RAW / 'eurostat_refused_entry.json').read_text())
    dims, sizes = j['id'], j['size']
    cats = {d: {v: k for k, v in j['dimension'][d]['category']['index'].items()} for d in dims}
    for raw_index, value in sorted(j['value'].items(), key=lambda item: int(item[0])):
        if value is None:
            continue
        n, coord = int(raw_index), {}
        for d, size in reversed(list(zip(dims, sizes))):
            coord[d] = cats[d][n % size]
            n //= size
        assert n == 0 and coord['freq'] == 'A' and coord['border'] == coord['reason'] == 'TOTAL'
        assert coord['unit'] == 'PER' and isinstance(value, (int, float)) and value >= 0
        geo, citizen, year = coord['geo'], coord['citizen'], int(coord['time'])
        status = j.get('status', {}).get(raw_index)
        obs.append(dict(observation_id=f'mobility_eurostat_refused_{geo}_{citizen}_{year}', source_id=sid,
                        source_locator=f'JSON-stat value[{raw_index}]; ' + '; '.join(d + '=' + coord[d] for d in dims),
                        destination=iso2(geo), origin=iso2(citizen), origin_basis='citizenship',
                        metric='border_entry_refusals', raw_metric=j['label'], value=value,
                        unit='persons_rounded_border_refusals', period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
                        calculation_type='official_estimate' if status and 'e' in status else 'published_rounded_observation',
                        observation_domain='mobility', context_only=True, eligible_money_ledger=False,
                        aggregation_role='region_total' if geo == 'EU27_2020' else 'country_total' if citizen == 'TOTAL' else 'citizenship_component',
                        flow_direction='inbound', series_id='eurostat_border_refusals', series_label='外部边境拒绝入境（Eurostat）',
                        scope='all_external_borders_all_reasons', source_status=status,
                        origin_raw_code=citizen, destination_raw_code=geo, metadata_source_id=msid,
                        origin_label={'TOTAL':'全部来源','UNK':'未知国籍','STLS':'无国籍','RNC':'认可非公民','ASI':'亚洲汇总','UK_OCT':'英国海外属地'}.get(citizen, j['dimension']['citizen']['category']['label'].get(citizen, citizen)),
                        notes='原表单位Persons：同一报告国、同一参考期内每人计一次，按5人取整；跨国可能重叠。边境拒绝入境与签证拒签分列。国籍分项与TOTAL不相加；EU27按未取整数计算且与申根范围不同，不并入成员合计。'))
    er = [r for r in obs if r['source_id'] == sid]
    checks += [dict(check='eurostat_nonnull_cells_preserved', passed=len(er) == sum(v is not None for v in j['value'].values()), rows=len(er), positive_rows=sum(r['value'] > 0 for r in er)),
               dict(check='no_missing_cell_imputed_as_zero', passed=all(r['value'] is not None for r in obs))]
    # China NIA: inbound+outbound crossing events are explicitly different from
    # one-way foreign entries and from visa/residence documents issued in China.
    existing = {s['source_id']: s for s in json.loads((ROOT / 'data/research/china_seasia/sources.json').read_text())}
    nia_sources = {}
    for year in (2019, 2021, 2022, 2023, 2024, 2025):
        if year >= 2024:
            sid = f'cn_nia_{year}'
            nia_sources[year] = (sid, ROOT / existing[sid]['local_path'])
        else:
            sid = source(f'mobility_cn_nia_{year}', f'nia_{year}.html', '国家移民管理局',
                         f'{year}年出入境／移民管理主要数据',
                         '保留发布精度；出入境是两方向查验人次，不能除以2冒充入境、出境或独立人数。')
            nia_sources[year] = (sid, RAW / f'nia_{year}.html')
    facts = {
        2019: [('border_crossings', 670000000, '6.7亿', '全部人员出入境查验', 'all_persons'),
               ('mainland_resident_border_crossings', 350000000, '3.5亿', '中国大陆居民出入境查验', 'mainland_residents'),
               ('foreign_border_crossings', 97675000, '9767.5万', '外国人出入境查验', 'foreign_nationals')],
        2021: [('border_crossings', 128000000, '1.28亿', '全部人员出入境查验', 'all_persons'),
               ('mainland_resident_border_crossings', 74234000, '7423.4万', '中国大陆居民出入境查验', 'mainland_residents'),
               ('hongkong_macao_taiwan_resident_border_crossings', 48973000, '4897.3万', '中国香港、澳门、台湾居民出入境查验', 'hongkong_macao_taiwan_residents'),
               ('foreign_border_crossings', 4531000, '453.1万', '外国人出入境查验', 'foreign_nationals')],
        2022: [('border_crossings', 115700000, '1.157亿', '全部人员出入境查验', 'all_persons'),
               ('mainland_resident_border_crossings', 64635000, '6463.5万', '中国大陆居民出入境查验', 'mainland_residents'),
               ('hongkong_macao_taiwan_resident_border_crossings', 46591000, '4659.1万', '中国香港、澳门、台湾居民出入境查验', 'hongkong_macao_taiwan_residents'),
               ('foreign_border_crossings', 4473000, '447.3万', '外国人出入境查验', 'foreign_nationals')],
        2023: [('border_crossings', 424000000, '4.24亿', '全部人员出入境查验', 'all_persons'),
               ('mainland_resident_border_crossings', 206000000, '2.06亿', '中国大陆居民出入境查验', 'mainland_residents'),
               ('hongkong_macao_taiwan_resident_border_crossings', 183000000, '1.83亿', '中国香港、澳门、台湾居民出入境查验', 'hongkong_macao_taiwan_residents'),
               ('foreign_border_crossings', 35478000, '3547.8万', '外国人出入境查验', 'foreign_nationals')],
        2024: [('border_crossings', 610000000, '6.1亿', '全部人员出入境查验', 'all_persons'),
               ('mainland_resident_border_crossings', 291000000, '2.91亿', '中国大陆居民出入境查验', 'mainland_residents'),
               ('hongkong_macao_taiwan_resident_border_crossings', 254000000, '2.54亿', '中国香港、澳门、台湾居民出入境查验', 'hongkong_macao_taiwan_residents'),
               ('foreign_border_crossings', 64882000, '6488.2万', '外国人出入境查验', 'foreign_nationals')],
        2025: [('border_crossings', 697000000, '6.97亿', '全部人员出入境查验', 'all_persons'),
               ('mainland_resident_border_crossings', 335000000, '3.35亿', '中国大陆居民出入境查验', 'mainland_residents'),
               ('hongkong_macao_taiwan_resident_border_crossings', 279000000, '2.79亿', '中国香港、澳门、台湾居民出入境查验', 'hongkong_macao_taiwan_residents'),
               ('foreign_border_crossings', 82035000, '8203.5万', '外国人出入境查验', 'foreign_nationals'),
               ('foreign_visa_free_entry_share', 73.1, '73.1%', '免签入境占外国人入境', 'foreign_entries')],
    }
    for year, rr in facts.items():
        sid, path = nia_sources[year]
        text = ''.join(BeautifulSoup(path.read_bytes(), 'html.parser').get_text(' ', strip=True).split())
        for metric, value, needle, label, scope in rr:
            assert needle in text, (year, needle)
            pos = text.index(needle)
            obs.append(dict(observation_id=f'mobility_cn_{metric}_{year}', source_id=sid,
                            source_locator=f'正文含“{text[max(0, pos-24):pos+len(needle)+28]}”',
                            destination='CHN', origin='WORLD', origin_basis='statistical_population_scope',
                            metric=metric, raw_metric=label, value=value, unit='percent' if metric.endswith('_share') else 'border_crossing_events',
                            period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
                            calculation_type='published_rounded_observation', observation_domain='rate' if metric.endswith('_share') else 'mobility',
                            context_only=True, eligible_money_ledger=False, aggregation_role='country_total',
                            flow_direction='inbound' if metric.endswith('_share') else 'both', series_id='nia_' + metric,
                            series_label=label + '（国家移民管理局）', scope=scope,
                            notes='按原文精度保存；出入境含两个方向。中国香港、中国澳门、中国台湾按居民统计口径合列；分项与总量不重复合计。'))
    checks += [dict(check='context_has_no_money_eligibility', passed=all(r['context_only'] and r['eligible_money_ledger'] is False for r in obs)),
               dict(check='observation_ids_unique', passed=len({r['observation_id'] for r in obs}) == len(obs))]
    by_country_year = {}
    for r in obs:
        if not pycountry.countries.get(alpha_3=r['destination']) and r['destination'] != 'XKX':
            continue
        key = r['destination'], int(r['period_start'][:4])
        item = by_country_year.setdefault(key, dict(code=key[0], year=key[1], visa_group='unclassified',
                            mobility_context_known=True, status='mobility_context_only', source_ids=set(),
                            notes='旅行／边境背景独立保存；不表示已知签证申请数量或费用。'))
        item['source_ids'].add(r['source_id'])
    coverage = [{**r, 'source_ids': sorted(r['source_ids'])} for r in by_country_year.values()]
    for name, obj in [('sources.json', sources), ('observations.json', obs), ('coverage.json', coverage), ('checks.json', checks)]:
        write(name, obj)
    report = dict(package='mobility_context_v4', sources=len(sources), observations=len(obs),
                  country_coverage=len({r['code'] for r in coverage}), coverage_rows=len(coverage),
                  counts_by_metric=dict(Counter(r['metric'] for r in obs)),
                  positive_observations=sum(r['value'] > 0 for r in obs), money_flows_added=0,
                  data_updated={'WDI': meta['lastupdated'], 'Eurostat': j['updated']},
                  checks_passed=all(r['passed'] for r in checks))
    write('report.json', report)
    assert report['checks_passed'], checks
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--download', action='store_true')
    main(p.parse_args().download)
