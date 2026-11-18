#!/usr/bin/env python3
"""Rebuild Colombia nationality and Dominican visa-issuance evidence offline.

This package does not create money flows. Colombia's nationality is the passport
nationality. Dominican Republic's consulate is an issuing office, never a payer
nationality. Missing months and mixed application/issuance reports stay explicit.
"""
from __future__ import annotations

import calendar
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import gettext
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

import openpyxl
import pycountry
from pypdf import PdfReader
from entity_names import canonical_name, JURISDICTION_NOTE

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/americas_expansion_v6'
OUT = ROOT / 'data/research/americas_expansion_v6'
CUT = '2026-11-17'
CO_META = 'https://www.datos.gov.co/api/views/mgr2-njqc.json'
DO_INDEX = 'https://mirex.gob.do/transparencia/estadisticas/estadisticas-de-visados/'
MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
          'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
MANUAL_ISO = {
    'ARABIA SAUDITA': 'SAU', 'ARGELIA': 'DZA', 'BAHREIN': 'BHR', 'BANGLADESH': 'BGD',
    'BOLIVIA': 'BOL', 'BURKINA FASO': 'BFA', 'CONGO, REPUBLICA DEMOCRATICA DE': 'COD',
    'CURA€AO': 'CUW', 'ESPA¥A': 'ESP', 'ESPA�A': 'ESP', 'FEDERACION DE RUSIA': 'RUS',
    'FIJI': 'FJI', 'GUINEA-BISSAU': 'GNB', 'GUYANA FRANCESA': 'GUF', 'ISLAS COMOROS': 'COM',
    'KOSOVO': 'XKX', 'LAO, REPUBLIC DEMOCRATICA POPULAR DE': 'LAO', 'LESOTHO': 'LSO',
    'MACAO RAE RPC': 'MAC', 'MACEDONIA, EX REPUBLICA YUGOSLAVA DE': 'MKD', 'MALAWI': 'MWI',
    'MALDIVAS': 'MDV', 'MOLDOVA, REPUBLICA DE': 'MDA', 'MYANMAR': 'MMR', 'PALAU': 'PLW',
    'PALESTINA': 'PSE', 'QATAR': 'QAT', 'REPUBLICA ARABE SIRIA': 'SYR',
    'REPUBLICA CHECA': 'CZE', 'SAINT KITTS Y NEVIS': 'KNA', 'SIN NACIONALIDAD': 'UNK',
    'SIRIA': 'SYR', 'ST. MAARTEN': 'SXM', 'SUAZILANDIA': 'SWZ',
    'TERRITORIO PALESTINO, OCUPADO': 'PSE', 'VENEZUELA': 'VEN', 'ZIMBABWE': 'ZWE',
}
DO_SELECTED = {
    12403: (2021, [4, 5, 6], 'matrix_code'),
    12405: (2021, [7, 8, 9], 'matrix_code'),
    14643: (2022, [1, 2, 3], 'matrix_code'),
    14906: (2022, [4, 5, 6], 'matrix_name'),
    15046: (2022, [7, 8, 9], 'matrix_name'),
    15216: (2022, [10, 11, 12], 'matrix_name'),
    17485: (2024, [1, 2, 3], 'vertical'),
    17880: (2024, [4, 5, 6], 'vertical'),
    18180: (2024, [7, 8, 9], 'vertical'),
    18571: (2024, [10, 11, 12], 'vertical'),
    18996: (2025, [1, 2, 3], 'vertical'),
    19323: (2025, [4, 5, 6], 'vertical'),
    19542: (2025, [7, 8, 9], 'vertical'),
    19713: (2025, [10, 11, 12], 'vertical'),
    20013: (2026, [1, 2, 3], 'vertical'),
    20071: (2026, [5, 6], 'vertical'),
    20187: (2026, [7, 8, 9], 'vertical'),
}


def norm(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text).upper())
                   if unicodedata.category(c) != 'Mn').strip()


def write(name, obj, *, csv_copy=True):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    if csv_copy and isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = list(dict.fromkeys(k for r in obj for k in r))
        with (OUT / name.replace('.json', '.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, keys)
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()} for row in obj)


def month_period(y, m):
    return f'{y}-{m:02d}-01', f'{y}-{m:02d}-{calendar.monthrange(y, m)[1]}'


def int_count(value):
    if isinstance(value, (int, float)):
        assert value >= 0 and int(value) == value, value
        return int(value)
    text = str(value).strip()
    assert re.fullmatch(r'[0-9]+', text), value
    return int(text)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources, obs, checks, exclusions, details, discrepancies = [], [], [], [], [], []
    manifest = json.loads((RAW / 'do_download_manifest.json').read_text())
    co_queries = json.loads((RAW / 'co_query_manifest.json').read_text())
    query_urls = {r['name']: r['url'] for r in co_queries}

    def source(sid, filename, url, publisher, title, **extra):
        path = RAW / filename
        sources.append(dict(source_id=sid, title=title, publisher=publisher, url=url,
                            local_path=str(path.relative_to(ROOT)), retrieved_at=CUT,
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size,
                            source_quality='official_primary', archive_status='original_archived',
                            archive_kind='original_api_response' if filename.endswith('.json') else 'original_document',
                            **extra))
        return sid

    co_meta = json.loads((RAW / 'co_mgr2-njqc_metadata.json').read_text())
    meta_sid = source('amx6_co_metadata', 'co_mgr2-njqc_metadata.json', CO_META,
                      'Colombia Ministerio de Relaciones Exteriores', co_meta['name'])
    co_sid = source('amx6_co_nationality_month', 'co_visa_nationality_month_vocation.json',
                    query_urls['co_visa_nationality_month_vocation.json'],
                    'Colombia Ministerio de Relaciones Exteriores',
                    'Visas expedidas por mes, nacionalidad de pasaporte y vocación de permanencia, 2017–2026',
                    query_limit=100000, result_rows=20055, metadata_source_id=meta_sid,
                    source_data_updated=datetime.fromtimestamp(co_meta['rowsUpdatedAt'], timezone.utc).isoformat())
    for key, title in [('co_visa_month_controls.json', 'Independent monthly visa and raw-cell controls'),
                       ('co_visa_rows_count.json', 'Independent total visa and raw-cell controls'),
                       ('co_visa_nationality_annual.json', 'Independent annual nationality controls')]:
        source('amx6_' + Path(key).stem, key, query_urls[key],
               'Colombia Ministerio de Relaciones Exteriores', title)

    es = gettext.translation('iso3166-1', pycountry.LOCALES_DIR, languages=['es'])
    zh = gettext.translation('iso3166-1', pycountry.LOCALES_DIR, languages=['zh_CN'])
    translations = {norm(es.gettext(c.name)): c.alpha_3 for c in pycountry.countries}
    manual = {norm(k): v for k, v in MANUAL_ISO.items()}
    raw_cells = json.loads((RAW / 'co_visa_nationality_month_vocation.json').read_text())
    mapping = []
    for label in sorted({r['nacionalidad'] for r in raw_cells}):
        code = manual.get(norm(label), translations.get(norm(label)))
        assert code, ('unresolved nationality', label)
        country = pycountry.countries.get(alpha_3=code)
        name = canonical_name(code, zh.gettext(country.name) if country else {'UNK': '无国籍（原表）', 'XKX': '科索沃'}[code])
        mapping.append(dict(raw_label=label, code=code, display_name=name,
                            basis='passport_nationality', method='explicit_alias' if norm(label) in manual else 'ISO_3166_Spanish_name'))
    mapping_by_label = {r['raw_label']: r for r in mapping}
    group = defaultdict(lambda: {'value': 0, 'raw_labels': set(), 'indices': []})
    month_sums, annual_nat_sums, annual_sums = Counter(), Counter(), Counter()
    for i, r in enumerate(raw_cells):
        y, m, value = int(r['anio']), int(r['mes']), int_count(r['visas'])
        code = mapping_by_label[r['nacionalidad']]['code']
        key = y, m, code, r['tipo_documento']
        group[key]['value'] += value
        group[key]['raw_labels'].add(r['nacionalidad'])
        group[key]['indices'].append(i)
        month_sums[y, m] += value
        annual_nat_sums[y, code] += value
        annual_sums[y] += value
    controls = json.loads((RAW / 'co_visa_month_controls.json').read_text())
    monthly_control = {(int(r['anio']), int(r['mes'])): int_count(r['visas']) for r in controls}
    all_control = json.loads((RAW / 'co_visa_rows_count.json').read_text())[0]
    checks.extend([
        dict(check='co_complete_group_query_below_limit', passed=len(raw_cells) < 100000, rows=len(raw_cells), limit=100000),
        dict(check='co_107_monthly_controls_reconcile', passed=month_sums == monthly_control, months=len(controls)),
        dict(check='co_total_539157_reconciles', passed=sum(month_sums.values()) == int(all_control['visas']) == 539157,
             raw_cells=int(all_control['raw_cells']), visas=int(all_control['visas'])),
        dict(check='co_raw_cell_count_independent_sum', passed=sum(int(r['raw_cells']) for r in controls) == int(all_control['raw_cells'])),
    ])
    independent_annual = Counter()
    for r in json.loads((RAW / 'co_visa_nationality_annual.json').read_text()):
        independent_annual[int(r['anio']), mapping_by_label[r['nacionalidad']]['code']] += int_count(r['visas'])
    checks.append(dict(check='co_independent_annual_nationality_reconciles', passed=annual_nat_sums == independent_annual,
                       nationality_year_cells=len(independent_annual)))
    column_defs = {r['fieldName']: r.get('description', '') for r in co_meta['columns']}
    checks.append(dict(check='co_metadata_defines_issuance_and_passport_nationality',
                       passed='expide' in column_defs['anio'] and 'pasaporte' in column_defs['nacionalidad']
                       and 'Visas' in column_defs['cantidad'], definitions=column_defs))
    co_year_months = defaultdict(set)
    for y, m in month_sums:
        co_year_months[y].add(m)
    complete_co = {y for y, months in co_year_months.items() if months == set(range(1, 13))}
    annual_vocation = defaultdict(lambda: {'value': 0, 'ids': []})
    for (y, m, code, vocation), value in sorted(group.items()):
        name = next(r['display_name'] for r in mapping if r['code'] == code)
        start, end = month_period(y, m)
        suffix = 'permanent' if vocation == 'PERMANENTE' else 'temporary'
        oid = f'amx6_co_{y}_{m:02d}_{code}_{suffix}'
        row = dict(observation_id=oid, source_id=co_sid, source_ids=[co_sid, meta_sid],
                   source_locator='grouped JSON indices ' + ','.join(map(str, value['indices'])),
                   destination='COL', reporting_country='COL', origin=code, origin_basis='passport_nationality',
                   origin_label=name, origin_display_name=name, raw_origin_labels=sorted(value['raw_labels']),
                   visa_group='unclassified', visa_type='col_vocation_' + suffix, raw_visa_type=vocation,
                   metric='visas_issued', raw_metric='Número de Visas / Año y Mes Expedición', value=value['value'],
                   unit='visa_issuance_events', period_start=start, period_end=end, period_type='calendar_month', year=y,
                   calculation_type='published_statistical_series', observation_domain='visa_activity', context_only=True,
                   eligible_money_ledger=False, aggregation_role='component', flow_direction='inbound',
                   series_id='col_visa_nationality_' + suffix + '_monthly',
                   series_label='哥伦比亚已签发签证 · ' + ('永久' if suffix == 'permanent' else '临时') + ' · 月度',
                   scope='passport_nationality_by_vocation', coverage_status='published_month',
                   notes='原表按停留意向仅分PERMANENTE/TEMPORAL；未改标旅游、学习或工作。计数是签发事件，非申请量、收费事件或独立人数。')
        obs.append(row)
        if y in complete_co:
            key = y, code, vocation
            annual_vocation[key]['value'] += value['value']
            annual_vocation[key]['ids'].append(oid)
    for (y, code, vocation), v in sorted(annual_vocation.items()):
        suffix = 'permanent' if vocation == 'PERMANENTE' else 'temporary'
        name = next(r['display_name'] for r in mapping if r['code'] == code)
        obs.append(dict(observation_id=f'amx6_co_{y}_{code}_{suffix}_annual', source_id=co_sid,
                        source_ids=[co_sid, meta_sid], source_locator=f'12 published months of {y}, passport={code}, vocation={vocation}',
                        destination='COL', reporting_country='COL', origin=code, origin_basis='passport_nationality',
                        origin_label=name, origin_display_name=name, visa_group='unclassified',
                        visa_type='col_vocation_' + suffix, raw_visa_type=vocation, metric='visas_issued',
                        value=v['value'], unit='visa_issuance_events', period_start=f'{y}-01-01', period_end=f'{y}-12-31',
                        period_type='calendar_year', year=y, calculation_type='sum_of_12_published_months',
                        observation_domain='visa_activity', context_only=True, eligible_money_ledger=False,
                        aggregation_role='component', flow_direction='inbound',
                        series_id='col_visa_nationality_' + suffix + '_annual',
                        series_label='哥伦比亚已签发签证 · ' + ('永久' if suffix == 'permanent' else '临时') + ' · 年度',
                        scope='passport_nationality_by_vocation', coverage_status='complete_calendar_year',
                        derived_from_observation_ids=v['ids'], notes='仅对具备12个发布月份的年度求和；原表无某国籍的单元未补零。'))
    # All-nationality totals are separate controls/series, not added to components.
    for (y, m), value in sorted(month_sums.items()):
        start, end = month_period(y, m)
        obs.append(dict(observation_id=f'amx6_co_total_{y}_{m:02d}', source_id='amx6_co_visa_month_controls',
                        source_ids=['amx6_co_visa_month_controls', meta_sid], source_locator=f'anio={y},mes={m:02d}',
                        destination='COL', reporting_country='COL', origin='WORLD', origin_label='全部国籍',
                        origin_basis='all_nationalities_total', metric='visas_issued', value=value,
                        unit='visa_issuance_events', period_start=start, period_end=end, period_type='calendar_month', year=y,
                        visa_group='unclassified', visa_type='all', calculation_type='published_statistical_series',
                        observation_domain='visa_activity', context_only=True, eligible_money_ledger=False,
                        aggregation_role='total', flow_direction='inbound', series_id='col_visa_total_monthly',
                        series_label='哥伦比亚已签发签证 · 全部国籍 · 月度', scope='all_passport_nationalities_all_vocations',
                        notes='独立月度API控制总数；不与国籍/永久临时分项相加。2025仅1–10月，2026仅9月。'))

    # Dominican originals: preserve office-level cells but aggregate display only
    # to unknown-nationality monthly/type components. Never geocode an office into payer.
    do_lookup = {r['id']: r for r in manifest}
    do_type_month = defaultdict(lambda: {'value': 0, 'ids': [], 'sources': set()})
    do_month = Counter()
    do_files = []
    for fid, (y, expected_months, style) in DO_SELECTED.items():
        file = do_lookup[fid]
        path = RAW / file['name']
        assert path.read_bytes().startswith(b'PK'), path
        sid = source('amx6_do_' + str(fid), file['name'], file['url'],
                     'Dominican Republic Ministerio de Relaciones Exteriores (MIREX)', file['title'],
                     statistical_period_start=month_period(y, min(expected_months))[0],
                     statistical_period_end=month_period(y, max(expected_months))[1])
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = book.worksheets[0]
        rows = list(sheet.iter_rows(values_only=True))
        selected, control, row_controls = [], None, []
        if style == 'vertical':
            header_index = next(i for i, r in enumerate(rows) if 'CANTIDAD' in r and 'CONSULADOS' in r)
            header = rows[header_index]
            col = {label: header.index(label) for label in ['CONSULADOS', 'AÑO', 'MES', 'TIPO DE VISADOS', 'CANTIDAD']}
            office, year, month, visa_type = None, None, None, None
            for ri, r in enumerate(rows[header_index+1:], header_index+2):
                if str(r[col['CONSULADOS']]).strip().lower() == 'total':
                    control = int_count(r[col['CANTIDAD']]); break
                if r[col['CONSULADOS']] not in (None, ''):
                    office, month, visa_type = str(r[col['CONSULADOS']]).strip(), None, None
                if r[col['AÑO']] not in (None, ''):
                    year = int_count(r[col['AÑO']])
                if r[col['MES']] not in (None, ''):
                    month = MONTHS.index(str(r[col['MES']]).strip().lower()) + 1
                if r[col['TIPO DE VISADOS']] not in (None, ''):
                    visa_type = str(r[col['TIPO DE VISADOS']]).strip()
                q = r[col['CANTIDAD']]
                if q in (None, ''):
                    continue
                assert office and year == y and month in expected_months and visa_type, (fid, ri, r)
                selected.append((ri, office, year, month, visa_type, int_count(q), col['CANTIDAD']+1))
        elif style == 'matrix_code':
            # Page headers may repeat. Code cells are stable B, month cells C:E;
            # the2022Q1 final total is shifted one column left in the export.
            office = None
            codes = {'CM', 'CS', 'DM', 'DPM', 'E', 'NM', 'NM1', 'NS', 'OM', 'RS', 'TM', 'TS'}
            for ri, r in enumerate(rows, 1):
                if str(r[0]).strip().lower() == 'total general':
                    values = [v for v in r[1:] if isinstance(v, (int, float))]
                    control = int_count(values[-1]); row_controls = list(map(int_count, values[:3])); break
                if len(r) < 5 or r[1] not in codes:
                    continue
                if r[0] and str(r[0]).strip():
                    office = str(r[0]).strip()
                assert office, (fid, ri)
                for j, month in enumerate(expected_months, 2):
                    if r[j] is not None:
                        selected.append((ri, office, y, month, str(r[1]), int_count(r[j]), j+1))
        else:
            office = None
            for ri, r in enumerate(rows, 1):
                label = str(r[0] or '').strip()
                if label.lower() == 'total general':
                    control = int_count(r[4]); row_controls = [int_count(v) for v in r[1:4]]; break
                if not re.match(r'^(VISA|VISADO|RENOVACION)\b', label):
                    if label and any(isinstance(x, (int, float)) for x in r[1:4]):
                        office = label
                    continue
                assert office, (fid, ri)
                for j, month in enumerate(expected_months, 1):
                    if r[j] is not None:
                        selected.append((ri, office, y, month, label, int_count(r[j]), j+1))
        total = sum(r[5] for r in selected)
        assert control is not None, ('missing published total', fid)
        if fid == 17880:
            # The official open table is internally off by1, and its companion
            # PDF is a later snapshot. Preserve every value; do not rebalance.
            pdf_file = do_lookup[17881]
            pdf_sid = source('amx6_do_17881', pdf_file['name'], pdf_file['url'],
                             'Dominican Republic Ministerio de Relaciones Exteriores (MIREX)', pdf_file['title'],
                             notes='Later report snapshot; published total6256 differs fromXLSX printed6254 and leaf sum6255.')
            pdf_text = '\n\n'.join(f'PDF PAGE {i+1}\n{p.extract_text()}'
                                   for i, p in enumerate(PdfReader(RAW / pdf_file['name']).pages))
            (OUT / 'do_2024_q2_companion_pdf.txt').write_text(pdf_text)
            discrepancy = dict(destination='DOM', year=2024, months=[4,5,6],
                               source_id=sid, comparison_source_id=pdf_sid,
                               xlsx_leaf_sum=total, xlsx_printed_total=control, pdf_printed_total=6256,
                               xlsx_generated_at='2024-10-09T15:07:45', pdf_generated_at='2024-10-18T09:53:04',
                               difference_leaf_minus_xlsx_total=total-control,
                               interpretation='开放表内部差1张；稍后生成PDF另有6256。仅保留各版本和计算口径，未判定哪一版为最终。月度按开放表逐格求和，全年合计亦保留此标记。')
            discrepancies.append(discrepancy)
            checks.append(dict(check='do_2024q2_known_source_discrepancy_preserved',
                               passed=total == 6255 and control == 6254 and '6256' in pdf_text.split('PDF PAGE 19')[-1]
                               and '18-Oct-2024' in pdf_text,
                               **discrepancy))
        else:
            checks.append(dict(check=f'do_{fid}_leaf_cells_match_published_total', passed=total == control,
                               value=total, published_total=control, source_id=sid, cells=len(selected),
                               sheet=sheet.title, selected_months=expected_months))
        actual_months = sorted({r[3] for r in selected})
        checks.append(dict(check=f'do_{fid}_actual_month_scope', passed=actual_months == expected_months,
                           actual_months=actual_months, title=file['title']))
        if row_controls:
            month_values = [sum(r[5] for r in selected if r[3] == month) for month in expected_months]
            checks.append(dict(check=f'do_{fid}_monthly_controls_reconcile', passed=month_values == row_controls,
                               calculated=month_values, published=row_controls))
        for ri, office, year, month, visa_type, value, col in selected:
            code_match = re.search(r'\(([^)]+)\)', visa_type)
            code = code_match.group(1) if code_match else visa_type
            cell_id = f'amx6_do_{fid}_r{ri}_c{col}'
            office_display = ('台北，中国台湾' if re.search(r'TAIPEI|TAIWAN|TAIWÁN', office, re.I) else
                              '中国香港' if re.search(r'HONG KONG', office, re.I) else office)
            details.append(dict(cell_id=cell_id, source_id=sid, source_locator=f"'{sheet.title}'!{openpyxl.utils.get_column_letter(col)}{ri}",
                                collecting_office_original=office, collecting_office_display=office_display,
                                payer='UNK', origin_basis='not_published', destination='DOM', year=year, month=month,
                                raw_visa_type=visa_type, visa_code=code, value=value, unit='visa_issuance_events'))
            box = do_type_month[year, month, visa_type]
            box['value'] += value; box['ids'].append(cell_id); box['sources'].add(sid)
            do_month[year, month] += value
        do_files.append(dict(source_id=sid, file_id=fid, year=y, months=expected_months,
                             published_total=control, parsed_total=total, leaf_cells=len(selected),
                             reconciled=total == control,
                             period_note='原文件标题为4–6月，原表内明示5–6月；4月未发布，不补零。' if fid == 20071 else ''))
    # Three separately published CSVs corroborate2026xlsx leaf values and period.
    for fid, xlsx_id in [(20011, 20013), (20070, 20071), (20188, 20187)]:
        file = do_lookup[fid]
        sid = source('amx6_do_' + str(fid), file['name'], file['url'],
                     'Dominican Republic Ministerio de Relaciones Exteriores (MIREX)', file['title'])
        csv_rows = list(csv.reader((RAW / file['name']).open(encoding='cp1252'), delimiter=';'))
        header_i = next(i for i, r in enumerate(csv_rows) if 'CANTIDAD' in r and 'CONSULADOS' in r)
        header = csv_rows[header_i]; qty = header.index('CANTIDAD'); off = header.index('CONSULADOS')
        vals, control = [], None
        for r in csv_rows[header_i+1:]:
            if str(r[off]).strip().lower() == 'total':
                control = int_count(r[qty]); break
            if r[qty].strip():
                vals.append(int_count(r[qty]))
        xlsx_values = [r['value'] for r in details if r['source_id'] == 'amx6_do_' + str(xlsx_id)]
        checks.append(dict(check=f'do_csv_{fid}_independent_format_matches_xlsx_{xlsx_id}',
                           passed=vals == xlsx_values and sum(vals) == control,
                           csv_source_id=sid, count=len(vals), total=control))
    source('amx6_do_visa_statistics_portal', 'do_visas_index.html', DO_INDEX,
           'Dominican Republic Ministerio de Relaciones Exteriores (MIREX)',
           'Estadísticas de Visados: public original-file index2016–2026',
           notes='Public WP File Download index; annualAPI directory responses and65originals preserved inarchive_manifest.')
    policy_url = 'https://mirex.gob.do/canciller-roberto-alvarez-reprocha-se-difundan-datos-falsos-sobre-las-visas-en-haiti-de-manera-irresponsable/'
    policy_sid = source('amx6_do_haiti_2024_scope', 'do_2024_haiti_policy.html', policy_url,
                        'Dominican Republic Ministerio de Relaciones Exteriores (MIREX)',
                        'Canciller Roberto Álvarez: visas emitidas en Haití,3October2024',
                        publication_date='2024-10-03',
                        notes='2024YTD102humanitarian trade visas in Haiti consulates, plus25issued byCancillería. Limited geography and purposes, not aDominican national total or nationality series. No numerical observation added.')

    for (y, m, visa_type), box in sorted(do_type_month.items()):
        start, end = month_period(y, m)
        slug = hashlib.sha256(visa_type.encode()).hexdigest()[:10]
        obs.append(dict(observation_id=f'amx6_do_{y}_{m:02d}_{slug}', source_id=sorted(box['sources'])[0],
                        source_ids=sorted(box['sources']), source_locator=f'office leaf cells, month={m}, type={visa_type}',
                        destination='DOM', reporting_country='DOM', origin='UNK', origin_label='申请人国籍未公开',
                        origin_basis='not_published', raw_visa_type=visa_type, visa_group='unclassified',
                        visa_type='do_' + slug, metric='visas_issued', value=box['value'], unit='visa_issuance_events',
                        period_start=start, period_end=end, period_type='calendar_month', year=y,
                        calculation_type='sum_published_office_cells', observation_domain='visa_activity',
                        context_only=True, eligible_money_ledger=False, aggregation_role='component', flow_direction='inbound',
                        series_id='dom_visa_type_' + slug + '_monthly', series_label='多米尼加已签发签证 · ' + visa_type + ' · 月度',
                        scope='published_consular_issuance_including_renewals_and_official_categories',
                        component_cell_ids=box['ids'],
                        source_total_discrepancy=discrepancies[0] if y==2024 and m in [4,5,6] else None,
                        notes='领馆是办理机构，不代表申请人国籍；全部保留UNK。含续签、外交、公务、礼遇等原类别，不视为全体缴费签证。' + ('2024Q2开放表细格6255、打印总数6254、后发PDF6256，保留差异。' if y==2024 and m in [4,5,6] else '')))
    for (y, m), value in sorted(do_month.items()):
        start, end = month_period(y, m)
        sids = sorted({sid for (yy, mm, _), b in do_type_month.items() if yy == y and mm == m for sid in b['sources']})
        obs.append(dict(observation_id=f'amx6_do_total_{y}_{m:02d}', source_id=sids[0], source_ids=sids,
                        source_locator=f'sum office/type leaf cells, month={m}', destination='DOM', reporting_country='DOM',
                        origin='UNK', origin_label='申请人国籍未公开', origin_basis='not_published', metric='visas_issued',
                        value=value, unit='visa_issuance_events', period_start=start, period_end=end,
                        period_type='calendar_month', year=y, visa_group='unclassified', visa_type='all',
                        calculation_type='sum_published_office_cells', observation_domain='visa_activity',
                        context_only=True, eligible_money_ledger=False, aggregation_role='total', flow_direction='inbound',
                        series_id='dom_visa_total_monthly', series_label='多米尼加已签发签证 · 月度',
                        scope='published_consular_issuance_including_renewals_and_official_categories',
                        source_total_discrepancy=discrepancies[0] if y==2024 and m in [4,5,6] else None,
                        notes='按原表领馆×类别分项求月总数，与类别分项不相加。2026年4月未见数据。跨年办理系统及范围变化保持原样。' + ('2024Q2开放表细格6255、打印总数6254、后发PDF6256，保留差异。' if y==2024 and m in [4,5,6] else '')))

    # Complete-year aggregate totals aid country summaries without annualization.
    for dest, totals in [('COL', month_sums), ('DOM', do_month)]:
        by_year = defaultdict(dict)
        for (y, m), value in totals.items():
            by_year[y][m] = value
        for y, months in sorted(by_year.items()):
            if set(months) != set(range(1, 13)):
                continue
            monthly = [r for r in obs if r['destination'] == dest and r['year'] == y
                       and r['aggregation_role'] == 'total' and r['period_type'] == 'calendar_month']
            sids = sorted({s for r in monthly for s in r['source_ids']})
            obs.append(dict(observation_id=f'amx6_{dest.lower()}_total_{y}_annual', source_id=sids[0], source_ids=sids,
                            source_locator='sum of12 published monthly totals', destination=dest, reporting_country=dest,
                            origin='WORLD' if dest == 'COL' else 'UNK', origin_label='全部国籍' if dest == 'COL' else '申请人国籍未公开',
                            origin_basis='all_nationalities_total' if dest == 'COL' else 'not_published',
                            visa_group='unclassified', visa_type='all', metric='visas_issued', value=sum(months.values()),
                            unit='visa_issuance_events', period_start=f'{y}-01-01', period_end=f'{y}-12-31',
                            period_type='calendar_year', year=y, calculation_type='sum_of_12_published_months',
                            observation_domain='visa_activity', context_only=True, eligible_money_ledger=False,
                            aggregation_role='total', flow_direction='inbound', series_id=dest.lower() + '_visa_total_annual',
                            series_label=('哥伦比亚' if dest == 'COL' else '多米尼加') + '已签发签证 · 年度',
                            scope='all_passport_nationalities_all_vocations' if dest == 'COL' else 'published_consular_issuance_including_renewals_and_official_categories',
                            derived_from_observation_ids=[r['observation_id'] for r in monthly],
                            source_total_discrepancy=discrepancies[0] if dest=='DOM' and y==2024 else None,
                            notes='完整12个月之和；签发事件含原表相应类别，不等于付费人数。' + ('2024年度23736为开放表细格和；Q2开放表细格6255、打印总数6254、后发PDF6256，版本差异保留。' if dest=='DOM' and y==2024 else '')))

    coverage = []
    for dest, totals in [('COL', month_sums), ('DOM', do_month)]:
        for y in sorted({y for y, m in totals}):
            months = sorted(m for yy, m in totals if yy == y)
            missing = sorted(set(range(1, 13)) - set(months))
            coverage.append(dict(code=dest, year=y, visa_group='unclassified', status='visa_issuance_context_only',
                                 observed_months=months, missing_months=missing, complete_calendar_year=not missing,
                                 observed_total=sum(v for (yy, m), v in totals.items() if yy == y),
                                 nationality_known=dest == 'COL', actual_revenue_known=False,
                                 eligible_money_ledger=False,
                                 source_total_discrepancy=discrepancies[0] if dest=='DOM' and y==2024 else None,
                                 source_ids=sorted({s for r in obs if r['destination'] == dest and r['year'] == y for s in r['source_ids']}),
                                 notes='签发数量背景；国籍为护照国籍。' if dest == 'COL' else '签发数量背景；未公开付款国籍。2023混合申请/签发系统未并入，2021只抽取4–9月。'))
    exclusions.extend([
        dict(candidate='Colombia co_mgr2-njqc_rows.json and co_yj6h-yjbu_rows.json',
             reason='Exploratory first50000-row captures are incomplete. No values from either capture enter observations. The separate Venezuela dataset includes country_of_birth, not passport nationality.'),
        dict(candidate='Mexico datos.gob.mx and SRE Visas2017–2026 download attempts',
             reason='Blocked or HTML replacement responses, renamed .blocked.html. Not valid CSV, not evidence of visa quantity.'),
        dict(candidate='Dominican Republic2016–2020PDFs and2021Q1/Q4',
             reason='Originals archived for later work, no observations added.2016report contains DENEGADA rows;2021Q4XLSX has lost thousands separators in typed numeric cells.'),
        dict(candidate='Dominican Republic2023all quarters',
             reason='Originals mix SGM, SGC and CORREO systems. Some worksheet headings say solicitudes/Fecha de Entrada and include duplicate-looking subtotals; no pooled issuance series or fee model created.'),
        dict(candidate='Dominican Republic2026Q2 title',
             reason='Portal title says abril-junio, but the originalXLSX,CSV,PDF all state01-May-2026–30-Jun-2026 and have only May/June; April remains missing.'),
        dict(candidate='Dominican Republic2024Q2 competing total values',
             reason='XLSX leaf6255, printed total6254, laterPDF6256. No proportional balancing or choice of final official value. Source-specific monthly leaf sums retained with discrepancy metadata.'),
        dict(candidate='Colombia2017–2026 fee conversion / Dominican tariff multiplication',
             reason='No period-matched historical rates, exemptions, paid applications or country-specific fee events assembled. Issuance count is retained as context, no money inferred.'),
    ])
    archived = []
    used_paths = {s['local_path'] for s in sources}
    for p in sorted(RAW.rglob('*')):
        if p.is_file():
            archived.append(dict(local_path=str(p.relative_to(ROOT)), sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                 bytes=p.stat().st_size, used_in_sources=str(p.relative_to(ROOT)) in used_paths))
    checks.extend([
        dict(check='all_observation_ids_unique', passed=len(obs) == len({r['observation_id'] for r in obs})),
        dict(check='all_source_ids_unique', passed=len(sources) == len({r['source_id'] for r in sources})),
        dict(check='observation_sources_resolve', passed=all(set(r['source_ids']) <= {s['source_id'] for s in sources} for r in obs)),
        dict(check='all_visa_context_excluded_from_money_ledger', passed=all(r['context_only'] and r['eligible_money_ledger'] is False and r['observation_domain'] == 'visa_activity' for r in obs)),
        dict(check='dominican_office_never_used_as_nationality', passed=all(r['origin'] == 'UNK' and r['origin_basis'] == 'not_published' for r in obs if r['destination'] == 'DOM')),
        dict(check='china_names_canonical', passed=all(r['origin_display_name'] == canonical_name(r['origin'], '') for r in obs if r['origin'] in {'CHN','HKG','MAC','TWN'})),
        dict(check='co_2025_2026_not_annualized', passed=not any(r['year'] in [2025,2026] and r['period_type'] == 'calendar_year' for r in obs if r['destination']=='COL')),
        dict(check='dom_2026_april_absent_not_zero_filled', passed=(2026,4) not in do_month and len([k for k in do_month if k[0]==2026])==8),
        dict(check='no_dominican2023_application_records_used', passed=not any(r['year']==2023 for r in obs if r['destination']=='DOM')),
        dict(check='no_amounts_or_fee_denominators_created', passed=all(not any(k in r for k in ['amount','amount_cny','fee_events','fee_rate']) for r in obs)),
    ])
    report = dict(package='americas_expansion_v6', sources=len(sources), observations=len(obs),
                  reporting_countries=['COL','DOM'], money_flows_added=0,
                  observations_by_destination=dict(Counter(r['destination'] for r in obs)),
                  periods_by_destination={d: dict(first=min(r['period_start'] for r in obs if r['destination']==d),
                                                    last=max(r['period_end'] for r in obs if r['destination']==d)) for d in ['COL','DOM']},
                  colombia=dict(raw_group_rows=len(raw_cells), canonical_month_nationality_vocation_cells=len(group),
                                raw_nationality_labels=len(mapping), nationality_codes=len({r['code'] for r in mapping}),
                                months=len(month_sums), visas=sum(month_sums.values()),
                                complete_years=sorted(complete_co), annual_published_sums=dict(sorted(annual_sums.items()))),
                  dominican=dict(parsed_xlsx_files=len(DO_SELECTED), months=len(do_month), raw_leaf_cells=len(details),
                                 visa_events=sum(do_month.values()), files=do_files),
                  source_discrepancies=discrepancies,
                  archived_files=len(archived), archived_bytes=sum(x['bytes'] for x in archived),
                  checks=len(checks), checks_passed=all(r['passed'] for r in checks))
    for name, obj in [('sources.json', sources), ('observations.json', obs), ('coverage.json', coverage),
                      ('co_nationality_mapping.json', mapping), ('do_office_type_month_cells.json', details),
                      ('source_discrepancies.json', discrepancies),
                      ('excluded_candidates.json', exclusions), ('archive_manifest.json', archived),
                      ('checks.json', checks), ('report.json', report)]:
        write(name, obj)
    (OUT / 'README.md').write_text('''# 美洲签证签发扩展 v6\n\n本包仅写入独立研究目录，不修改r9、全局注册、产品或金额总账。\n\n## 已完成的实质扩展\n\n- **哥伦比亚**：外交部在官方datos.gov.co发布的mgr2-njqc，完整取得“年月×护照国籍×永久/临时”分组，不使用探索阶段前50000行截断文件。元数据明确Año/Mes为签发时间、Número为签证数量、国籍对应护照；标题中的solicitudes不改解释成申请总量。2017–2024每年12个月，2025仅1–10月，2026仅9月。官方最近更新时间保留在sources.json。最新月份仅1996张，覆盖有断档，不能解释为全年签发趋势暴跌。\n- 哥伦比亚对四份独立API结果对账：年月国籍永久临时分项、年月总数及原始行数、全表总数及原始行数、年度国籍分项。总签发539157、原始细格283600。国籍编码别名与乱码在mapping中保留原称、明确归并；永久/临时表示原表停留意向，不推断旅游/学习/工作。\n- **多米尼加**：MIREX官方门户年度目录、65份原始CSV/XLSX/PDF已归档。抽取2021年4–9月、2022全年、2024–2025全年、2026年1–3月及5–9月。每份XLSX逐领馆/类别/月细格与官方合计核对：16份完全一致，2024Q2开放表细格6255、打印总数6254、后发PDF6256，三个值及生成时间在source_discrepancies中保留，不调平。2024年度23736是开放表细格和，带同一差异标记。2026三份独立CSV与XLSX数量逐行对照。2026所谓第二季度原文件明确只含5–6月，4月仍缺失。\n- 多米尼加领馆是签发机构，没有公布申请人国籍，所有付款来源保留UNK。类别含续签、外交、公务、礼遇等，不转换成全额缴费签证人数。逐领馆原始细格单独保存，产品候选观测只用月度类别与总数。\n- 2016旧报告含DENEGADA；2023工作表混有申请名册、SGM/SGC/CORREO来源，未合并进签发层。2021Q4开放表把9.440等千位数转成9.44，未擅自恢复。原件保留供后续核验。墨西哥下载被替换为HTML，明确排除并改名blocked.html。\n\n## 文件与复算\n\n`observations.json/csv`为独立签证活动背景；`do_office_type_month_cells.json/csv`为可溯源的底层单元，**不得与已汇总观测再次相加**。年度值、月度值、国籍/类别分项和总量属于不同层级，也不相加。`coverage.json`列出实际发布月份和缺月；`sources.json`及`archive_manifest.json`记录官方链接、原件路径和SHA256。\n\n运行：`.research-venv/bin/python scripts/research_americas_expansion_v6.py`。复算全程离线，直接使用归档原件。所有观测`context_only=true`、`eligible_money_ledger=false`；未取得匹配历史收费/豁免和实际收费事件，新增金额流为0。\n\n''' + JURISDICTION_NOTE + '\n')
    print(json.dumps(report, ensure_ascii=False))
    assert report['checks_passed'], [r for r in checks if not r['passed']]


if __name__ == '__main__':
    main()
