#!/usr/bin/env python3
"""Offline expansion: Eurostat residence permits and IRCC revised monthly intake."""
from calendar import month_name, monthrange
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
import pycountry

ROOT = Path(__file__).resolve().parents[1]
PKG = 'r12_public_statistics'
RAW = ROOT / 'data/raw' / PKG
OUT = ROOT / 'data/research' / PKG
EU = 'https://ec.europa.eu/eurostat/api/dissemination/'
CA = 'https://www.ircc.canada.ca/opendata-donneesouvertes/data/Open%20Data%20-%20OPS%20'
ORIGINALS = [
    ('r12_eurostat_first_permits', 'eurostat-migr_resfirst.tsv.gz',
     EU+'sdmx/2.1/data/migr_resfirst?format=TSV&compressed=true', 'Eurostat',
     'First permits by reason, length of validity and citizenship (migr_resfirst)',
     'd840d06a24a9b835701817f8ed6a1bda0dac6c481a9185cd59ca8659d4d72490'),
    ('r12_eurostat_first_permits_control', 'eurostat-migr_resfirst-totals.json',
     EU+'statistics/1.0/data/migr_resfirst?lang=en&freq=A&unit=PER&duration=TOTAL&reason=TOTAL&sinceTimePeriod=2011&untilTimePeriod=2025',
     'Eurostat','First residence permits: independent API query for total reason and duration',
     '7683aa836cfccf8fb169a89cd77e2fa750cbcdee216cd714149120ca703e49c0'),
    ('r12_ircc_received_sep2026', 'ircc-temporary-residents-received-to-sep-2026.xlsx',
     CA+'TRV%20Intake%20en.xlsx','Immigration, Refugees and Citizenship Canada',
     'Temporary resident applications received, including extensions (persons), through September 2026',
     '4ba0e367200a717107fe43c48787003d34d2810b6d09e4a64ff28fbf3a9e4384'),
    ('r12_ircc_processed_sep2026', 'ircc-temporary-residents-processed-to-sep-2026.xlsx',
     CA+'TR%20Processed%20en.xlsx','Immigration, Refugees and Citizenship Canada',
     'Temporary resident applications processed, including extensions (persons), through September 2026',
     '786c285012518fdac839c5521dc4ceb60fb8c245057cf6978a82d95266045630'),
]
REASONS = {'TOTAL':('全部用途','unclassified'), 'EDUC':('学习','student'),
           'EMP':('工作','work'), 'FAM':('家庭','family'), 'OTH':('其他用途','other')}
EU_SPECIAL = {'TOTAL':('WORLD','全部国籍（原表总计）'), 'XK':('XKX','科索沃'),
              'EL':('GRC','希腊'), 'UK':('GBR','英国'), 'UK_OCT':('UNK:EUROSTAT:UK_OCT','英国海外国家及领地（原表组）'),
              'STLS':('UNK:EUROSTAT:STATELESS','无国籍'), 'UNK':('UNK:EUROSTAT:UNKNOWN','国籍未知'),
              'RNC':('UNK:EUROSTAT:RNC','获承认的非公民（原表组）')}
EU_FLAGS = {'d':'定义不同', 'b':'序列中断', 'u':'可靠性较低', 'p':'初步', 'e':'估算', 'm':'数据不可用'}
CA_SPECIAL = {
    'Total':('WORLD','原表总计'), 'Other*':('UNK:IRCC:OTHER','其他（含未知、缺失或无效）'),
    'Stateless':('UNK:IRCC:STATELESS','无国籍'), 'Kosovo, Republic of':('XKX','科索沃'),
    'Macedonia':('MKD','北马其顿'), 'Turkey':('TUR','土耳其'),
    'The Netherlands Antilles':('UNK:IRCC:ANTILLES','荷属安的列斯（历史地理分项）'),
    'United Kingdom and Overseas Territories':('UNK:IRCC:UKOT','英国及海外领地（原表合并）'),
}
MONTHS = {name:i for i,name in enumerate(month_name) if name}


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, separators=(',',':'))+'\n')


def official(sid, filename, url, agency, title, pin):
    p = RAW / filename
    assert hashlib.sha256(p.read_bytes()).hexdigest() == pin, filename
    return dict(source_id=sid, title=title, publisher=agency, url=url,
                local_path=str(p.relative_to(ROOT)), sha256=pin, bytes=p.stat().st_size,
                retrieved_at='2026-11-18', archive_kind='original_document',
                source_quality='official_primary', archive_status='original_archived')


def api_control(doc):
    assert doc['id'] == ['freq','reason','citizen','duration','unit','geo','time']
    dims = [list(sorted(doc['dimension'][k]['category']['index'],
                        key=doc['dimension'][k]['category']['index'].get)) for k in doc['id']]
    assert dims[0] == ['A'] and dims[1] == ['TOTAL'] and dims[3] == ['TOTAL'] and dims[4] == ['PER']
    status = doc.get('status',{})
    result = {}
    for idx, val in doc['value'].items():
        n = int(idx)
        yrs, geos = len(dims[-1]), len(dims[-2])
        result[dims[2][n//(yrs*geos)], dims[-2][(n//yrs)%geos], int(dims[-1][n%yrs])] = (val, status.get(idx,'').strip())
    return result


def eu_rows():
    meta = json.loads((RAW / ORIGINALS[1][1]).read_bytes())
    updated = meta['updated']
    control = api_control(meta)
    compared = set()
    summary, rows, missing = Counter(), [], Counter()

    def code(alpha):
        if alpha in EU_SPECIAL:
            return EU_SPECIAL[alpha]
        c = pycountry.countries.get(alpha_2=alpha)
        assert c is not None, alpha
        return c.alpha_3, c.name

    with gzip.open(RAW / ORIGINALS[0][1], 'rt', encoding='utf-8', newline='') as f:
        tsv = csv.reader(f, delimiter='\t')
        cols = next(tsv)
        assert cols[0] == r'freq,reason,citizen,duration,unit,geo\TIME_PERIOD'
        yrs = [int(y) for y in cols[1:]]
        for lineno, line in enumerate(tsv,2):
            freq, reason, citizen, duration, unit, geo = line[0].split(',')
            if freq!='A' or duration!='TOTAL' or unit!='PER':
                continue
            if reason!='TOTAL' and citizen!='TOTAL':
                continue
            # Reporting-country series cannot sum overlapping EU aggregates.
            if geo in {'EU27_2020','EU28'}:
                continue
            dest, _ = code(geo)
            partner, raw_name = code(citizen)
            label = meta['dimension']['citizen']['category']['label'].get(citizen, raw_name)
            reason_name, group = REASONS[reason]
            for col, (year, raw) in enumerate(zip(yrs,line[1:]),2):
                if year<2011: continue
                val,*flags = raw.split()
                if val==':':
                    missing[year] += 1
                    continue
                val = int(val)
                if reason=='TOTAL':
                    key = (citizen,geo,year)
                    assert key not in compared and control[key][0] == val, key
                    compared.add(key)
                assert set(flags) <= EU_FLAGS.keys(), flags
                summary[geo] += 1
                rows.append(dict(observation_id=f'r12_eu_permit_{geo}_{citizen}_{reason}_{year}',
                                 destination=dest, origin=partner, origin_raw_code=citizen,
                                 context_partner_code=partner, context_partner_label=raw_name,
                                 origin_label=label, origin_basis='citizenship',
                                 source_id=ORIGINALS[0][0], source_edition=updated,
                                 metadata_source_id=ORIGINALS[1][0],
                                 source_locator=f'migr_resfirst data row {lineno}, column {col}: {line[0]} / {year}',
                                 source_status=' '.join(flags) or 'published',
                                 source_status_label='、'.join(EU_FLAGS[k] for k in flags) or '来源公布值',
                                 value=val, unit='residence_permits', metric='first_residence_permits', visa_group=group,
                                 visa_type=f'first_residence_permits_{reason.lower()}',
                                 series_id=f'r12_eurostat_first_permits_{reason.lower()}',
                                 series_label=f'Eurostat · 首次居留许可（{reason_name}）',
                                 period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                                 period_type='calendar_year', observation_domain='document_activity',
                                 calculation_type='direct_observation', flow_direction='inbound',
                                 context_selection_default=False, context_only=True, eligible_money_ledger=False,
                                 aggregation_role='non_additive_published_total' if citizen=='TOTAL' else 'citizenship_component',
                                 notes='首次居留许可按报告地与国籍统计，原来源可能包含此前许可失效至少六个月后再办的许可。与签证签发、付费申请不同；保留公布零值，冒号缺失不补零。'))
    expected = {k for k in control if k[1] not in {'EU27_2020','EU28'}}
    assert compared == expected, (len(compared),len(expected))
    return rows, dict(geographies=len(summary), by_geography=dict(summary), independent_cells=len(compared),
                      missing_cells_by_year=dict(missing), edition=updated)


def ca_rows(entry, aliases, kind):
    sid, filename, *_ = entry
    wb = load_workbook(RAW/filename, read_only=True, data_only=True)
    sheet = wb.active
    src = list(sheet.values)
    assert sheet.title == 'Page' and 'September 2026' in src[2][0]
    assert 'October 6, 2026' in src[225][0] and 'suppressed' in src[227][0]
    assert 'Visitor Records' in src[222][0] and 'Study Permits Extensions' in src[222][0]
    rows, omitted = [], []
    columns = []
    year = None
    for i, (y, m) in enumerate(zip(src[4],src[5])):
        if isinstance(y,int):year=y
        if m and m.strip() in MONTHS:
            columns.append((i,year,MONTHS[m.strip()]))
    assert [(y,m) for _,y,m in columns] == [(y,m) for y in range(2023,2027) for m in range(1,10 if y==2026 else 13)]
    observed = []
    for row_num, row in enumerate(src[6:222],7):
        label = row[0]
        if label in CA_SPECIAL:
            partner, name = CA_SPECIAL[label]
        else:
            a = aliases.get(label)
            if not a: a=pycountry.countries.lookup(label).alpha_3
            partner, name = a, label
        for i,y,m in columns:
            val=row[i]
            cell=f'Page!{get_column_letter(i+1)}{row_num}'
            if not isinstance(val,int):
                assert val in (None,'–','—','-','--'), (cell,type(val).__name__)
                omitted.append(dict(cell=cell,origin=label,year=y,month=m,mark=val))
                continue
            assert val>=0 and val%5==0, cell
            if label=='Total':observed.append(val)
            rows.append(dict(observation_id=f'{sid}_row{row_num}_{y}_{m:02d}',destination='CAN',origin=partner,
                             context_partner_code=partner,context_partner_label=name,
                             origin_label=label,origin_basis='source_country_as_published',source_id=sid,
                             source_locator=cell, source_edition='2026-10-06',
                             source_status='published_rounded' if val not in (0,5) else 'published',
                             metric=f'temporary_resident_people_applications_{kind}',value=val,unit='persons',
                             visa_group='unclassified',visa_type='temporary_resident_including_extensions',
                             series_id=f'r12_ircc_tr_people_{kind}',series_label='IRCC · 临时居民含延期 · '+('受理' if kind=='received' else '处理')+'（月度，人数口径）',
                             calculation_type='direct_observation',observation_domain='visa_activity',
                             aggregation_role='non_additive_published_total' if label=='Total' else 'source_country_component',
                             period_start=f'{y}-{m:02d}-01',period_end=f'{y}-{m:02d}-{monthrange(y,m)[1]}',
                             period_type='calendar_month',flow_direction='inbound',context_selection_default=False,
                             context_only=True,eligible_money_ledger=False,
                             notes='原表人数口径，包含临时居民签证、访客记录、学习与工作许可及适用延期。1–4被隐匿；其他值通常按5取整。各国分项与总计不一定相加，业务数据可修订。'))
    assert len(observed)==45 and observed[-1]==({'received':314000,'processed':357850}[kind])
    wb.close()
    return rows, omitted


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = [official(*x) for x in ORIGINALS]
    aliases = json.loads((ROOT/'data/entity_aliases.json').read_text())
    europe, checks = eu_rows()
    received, rec_omitted = ca_rows(ORIGINALS[2],aliases,'received')
    processed, pro_omitted = ca_rows(ORIGINALS[3],aliases,'processed')
    data = europe+received+processed
    assert len({r['observation_id'] for r in data})==len(data)
    assert all(isinstance(r['value'],int) and r['value']>=0 for r in data)
    assert len({(r['destination'],r['series_id'],r['context_partner_code'],r['period_start']) for r in data})==len(data)
    dump('sources.json',sources)
    dump('observations.json',data)
    dump('ircc_suppressed_or_missing.json',{sources[2]['source_id']:rec_omitted,sources[3]['source_id']:pro_omitted})
    dump('checks.json',dict(eurostat=checks,europe_observations=len(europe),
                            ircc_received=len(received),ircc_processed=len(processed),
                            suppressed_or_missing=len(rec_omitted)+len(pro_omitted)))
    print(json.dumps(dict(europe=len(europe),geographies=checks['geographies'],
                          independ_cell_checks=checks['independent_cells'],canada=len(received)+len(processed)),
                     ensure_ascii=False))


if __name__=='__main__':
    main()
