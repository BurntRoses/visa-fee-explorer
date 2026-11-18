#!/usr/bin/env python3
"""Archive (optional) and extract DG HOME workbooks + Fed annual FX.

Run with bundled Python or a Python environment with openpyxl and pandas.
Offline: python scripts/research_schengen_fx.py
Refresh originals: python scripts/research_schengen_fx.py --download
"""
import argparse
import csv
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/research/schengen_fx'
SOURCES = [
    ('sch_landing', 'schengen/statistics-landing.html', 'https://home-affairs.ec.europa.eu/policies/schengen/visa-policy/short-stay-visas-issued-schengen-countries_en', 'European Commission DG HOME', 'Short-stay visas issued by Schengen countries', '2026-05-28'),
    ('sch_2024', 'schengen/2024-consulates.xlsx', 'https://home-affairs.ec.europa.eu/document/download/6552447c-1d75-4f7c-bed6-1bd17a5d59f8_en?filename=2024-schengen-visa-statistics-consulates_en.xlsx', 'European Commission DG HOME', '2024 Schengen visa statistics — consulates', None),
    ('sch_2025', 'schengen/2025-consulates.xlsx', 'https://home-affairs.ec.europa.eu/document/download/56816949-e59f-442b-9091-5d03360bf860_en', 'European Commission DG HOME', '2025 Schengen visa statistics — consulates', '2026-05-28'),
    ('sch_metadata', 'schengen/metadata.pdf', 'https://home-affairs.ec.europa.eu/document/download/b4626219-fa37-4650-8216-0c2bda466c74_en?filename=visa_statistics_-_quality_and_metadata_reporting.pdf', 'European Commission DG HOME', 'Visa statistics — quality and metadata reporting', '2026-11-09'),
    ('sch_fee_2024', 'schengen/fee-change-2024.html', 'https://home-affairs.ec.europa.eu/news/schengen-visa-fee-increased-11-june-2024-2024-06-13_en', 'European Commission DG HOME', 'Schengen Visa Fee increased as of 11 June 2024', '2024-06-13'),
    ('sch_visa_code', 'schengen/visa-code-20240611.html', 'https://eur-lex.europa.eu/eli/reg/2009/810/2024-06-11/eng', 'European Union', 'Visa Code consolidated 11 June 2024', '2024-06-11'),
    ('sch_faq', 'schengen/FAQs.pdf', 'https://home-affairs.ec.europa.eu/document/download/dae5e071-1564-4a5d-9714-2147f7641781_en?filename=FAQs.pdf', 'European Commission DG HOME', 'Frequently Asked Questions — Schengen visas', None),
    ('sch_applying', 'schengen/applying.html', 'https://home-affairs.ec.europa.eu/policies/schengen/visa-policy/applying-schengen-visa_en', 'European Commission DG HOME', 'Applying for a Schengen visa', '2025-12-02'),
    ('fr_senate_visa_2024', 'france/senate-visa-report-20250924.html', 'https://www.senat.fr/rap/r24-904/r24-904_mono.html', 'Sénat, Commission des finances', 'Sur la délivrance des visas — rapport 904', '2025-09-24'),
    ('fx_fed_g5a_20260105', 'fx/fed-g5a-20260105.html', 'https://www.federalreserve.gov/releases/g5a/20260105/', 'Board of Governors of the Federal Reserve System', 'G.5A Annual — 2025 with 2024 comparisons', '2026-01-05'),
    ('cn_nbs_2024', 'china/nbs-2024.html', 'https://www.stats.gov.cn/sj/zxfb/202502/t20250228_1958817.html', '国家统计局', '2024年国民经济和社会发展统计公报', '2025-02-28'),
    ('cn_nbs_2025', 'china/nbs-2025.html', 'https://www.stats.gov.cn/sj/zxfb/202602/t20260228_1962662.html', '国家统计局', '2025年国民经济和社会发展统计公报', '2026-02-28'),
]

def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

def csv_write(name, rows):
    if not rows:
        return
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def acquire(download):
    manifest = []
    for sid, rel, url, publisher, title, published in SOURCES:
        p = ROOT / 'data/raw' / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if download and not p.exists():
            subprocess.run(['curl', '-sSL', '--fail', '--retry', '1', '--max-time', '45', url, '-o', str(p)], check=True)
        if not p.exists():
            continue
        manifest.append(dict(source_id=sid, url=url, publisher=publisher, title=title,
                             publication_date=published,
                             retrieved_at=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                             local_path=str(p.relative_to(ROOT)) if p.stat().st_size else None, sha256=hashlib.sha256(p.read_bytes()).hexdigest() if p.stat().st_size else None,
                             archive_status='archived' if p.stat().st_size else 'empty_remote_response; EU anti-bot challenge; legal citation retained; fee rules additionally backed by DG HOME FAQ',
                             source_quality='official_primary'))
    return manifest

def extract():
    observations, consulates, countries, states, checks = [], [], [], [], []
    metric_cols = {'atv_applications': 4, 'atv_issued': 5, 'atv_not_issued': 7,
                   'applications': 9, 'uniform_issued': 10, 'multiple_entry_issued': 11,
                   'ltv_issued': 13, 'not_issued': 14}
    for year in (2024, 2025):
        wb = openpyxl.load_workbook(ROOT / f'data/raw/schengen/{year}-consulates.xlsx', data_only=True, read_only=True)
        ws = wb['Data for consulates']
        headers = [c.value for c in next(ws.iter_rows())]
        records = []
        for row in ws.iter_rows(min_row=2):
            if not all(row[c].value for c in (0, 1, 2)):
                continue
            base = dict(year=year, issuing_state=row[0].value, consulate_country=row[1].value,
                        consulate=row[2].value, source_id=f'sch_{year}',
                        source_locator=f"'Data for consulates'!A{row[0].row}:S{row[0].row}",
                        origin_basis='consulate_country')
            rec = {**base, **{k: row[col-1].value for k, col in metric_cols.items()}}
            records.append(rec)
            for metric, col in metric_cols.items():
                cell = row[col-1]
                if cell.value is None:
                    continue
                observations.append(dict(observation_id=f'sch_{year}_consulate_r{cell.row}_{cell.column_letter}',
                    source_id=f'sch_{year}', source_locator=f"'Data for consulates'!{cell.coordinate}",
                    raw_metric=headers[col-1], metric=metric, value=cell.value, unit='applications_or_decisions',
                    destination=row[0].value, consulate_country=row[1].value, nationality=None,
                    consulate=row[2].value, visa_type='airport_transit' if metric.startswith('atv') else 'schengen_short_stay',
                    period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
                    quantity_basis=metric, calculation_type='observed',
                    notes='not_issued includes refusals and discontinued examinations; counts are events, not unique people'))
        consulates.extend(records)
        for sheet, first, name_col, cols, dest in [
            ('Totals - third country', 3, 2, dict(applications=3, uniform_issued=4, multiple_entry_issued=5, ltv_issued=6, not_issued=7), countries),
            ('Totals - Schengen State', 5, 1, dict(applications=2, uniform_issued=3, multiple_entry_issued=4, ltv_issued=5, not_issued=6), states)]:
            for row in wb[sheet].iter_rows(min_row=first):
                name = row[name_col-1].value
                if not name:
                    continue
                rec = dict(year=year, entity=name, origin_basis='consulate_country' if dest is countries else 'issuing_state',
                           source_id=f'sch_{year}', source_locator=f"'{sheet}'!{row[name_col-1].coordinate}",
                           **{k: row[c-1].value for k, c in cols.items()})
                dest.append(rec)
                if name == 'Grand Total':
                    for k in cols:
                        summed = sum(r[k] or 0 for r in records)
                        checks.append(dict(year=year, check=f'detail_vs_{sheet}_{k}', detail_sum=summed, reported=rec[k], passed=summed==rec[k]))
        for row in ws.iter_rows():
            if row[2].value == f'Total worldwide {year}':
                for metric, col in metric_cols.items():
                    summed = sum(r[metric] or 0 for r in records)
                    cached = row[col-1].value
                    checks.append(dict(year=year, check=f'cached_main_total_{metric}', source_locator=f"'Data for consulates'!{row[col-1].coordinate}", detail_sum=summed, reported=cached, passed=summed==cached,
                                       resolution='Use detail sum reconciled to both pivot tables; preserve stale source total separately' if summed!=cached else 'matched'))
    dump('observations.json', observations)
    for name, rows in [('consulates.csv', consulates), ('origin_totals.csv', countries), ('destination_totals.csv', states)]:
        csv_write(name, rows)
    dump('checks.json', checks)
    dump('aggregates.json', dict(origin_totals=countries, destination_totals=states))
    return observations, checks

def fx():
    table = next(t for t in pd.read_html(str(ROOT / 'data/raw/fx/fed-g5a-20260105.html')) if 'COUNTRY' in t.columns)
    code_map = {'AUSTRALIA':'AUD','CANADA':'CAD','CHINA, P.R.':'CNY','EMU MEMBERS':'EUR','INDIA':'INR','JAPAN':'JPY',
                'MALAYSIA':'MYR','NEW ZEALAND':'NZD','SINGAPORE':'SGD','SOUTH KOREA':'KRW','THAILAND':'THB','UNITED KINGDOM':'GBP'}
    rows=[]
    for _, r in table.iterrows():
        raw=str(r['COUNTRY']); clean=raw.lstrip('*').strip()
        if clean not in code_map:
            continue
        for year in (2024, 2025):
            rate=float(r[str(year)])
            rows.append(dict(fx_id=f'fed_{year}_{code_map[clean]}', year=year, currency=code_map[clean], raw_rate=rate,
                             raw_direction='USD_per_currency' if raw.startswith('*') else 'currency_per_USD',
                             usd_per_unit=rate if raw.startswith('*') else 1/rate,
                             source_id='fx_fed_g5a_20260105', source_locator=f'annual table; {raw}; {year}',
                             method='New York daily noon buying rates annual average'))
    for y in (2024,2025):
        rows.append(dict(fx_id=f'fed_{y}_USD',year=y,currency='USD',raw_rate=1,raw_direction='USD_per_currency',usd_per_unit=1,
                         source_id='fx_fed_g5a_20260105',source_locator='numeraire',method='USD numeraire'))
    dump('fx.json', rows)
    csv_write('fx.csv', rows)

def fees():
    rows=[]
    for start,end,adult,child in [('2020-02-02','2024-06-10',80,40),('2024-06-11',None,90,45)]:
        for age,amount in [('12_and_over',adult),('6_to_under_12',child),('under_6',0)]:
            rows.append(dict(fee_id=f'sch_{start}_{age}',destination='SCH',visa_type='schengen_short_stay',fee_component='government_application_fee',amount=amount,currency='EUR',
                effective_from=start,effective_to=end,age_scope=age,nationality_scope='standard rate; facilitation agreements and restrictive measures require separate rules',
                payment_trigger='application',refund_rule='normally non-refundable on refusal; incompetent consulate/inadmissibility exceptions in Articles 18/19',
                exemptions='Article 16(4)-(6): age, studies, researchers, nonprofit meetings and individual waivers; EU free-movement family rules separately',payer='applicant',mandatory=True,charge_basis='per_application',
                source_id='sch_fee_2024' if age!='under_6' else 'sch_faq',source_locator='fee-change notice; FAQ question 10, PDF p4; Visa Code Article 16',calculation_type='observed'))
    rows.append(dict(fee_id='sch_service_standard_cap_20240611',destination='SCH',visa_type='schengen_short_stay',fee_component='external_provider_service_fee_standard_cap',amount=45,currency='EUR',effective_from='2024-06-11',effective_to=None,age_scope='all',nationality_scope='Article 17(4) ordinary ceiling; exceptional Article 17(4a)/(4b) ceilings differ',payment_trigger='application_via_external_provider',refund_rule='provider terms',exemptions='does not mean every applicant pays EUR45',payer='applicant',mandatory='channel_dependent',charge_basis='per_application',source_id='sch_visa_code',source_locator='Article 17(4), (4a), (4b)',calculation_type='observed'))
    dump('fee_rules.json',rows)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--download',action='store_true');args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    dump('sources.json',acquire(args.download))
    obs,checks=extract();fx();fees()
    print(json.dumps(dict(observations=len(obs),checks=len(checks),source_discrepancies=[c for c in checks if not c['passed']]),ensure_ascii=False))
