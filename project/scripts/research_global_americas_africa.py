#!/usr/bin/env python3
"""Rebuild the Americas/Africa evidence package and conservative fee models.

Offline by default. Original archives are kept in data/raw/global_americas_africa.
--download attempts a refresh of known originals; --extract refreshes PDF/HTML text.
Birth country, issuing-post country, nationality, fiscal years and budgets remain
distinct. No arrival count is used as a visa count. Unidentified payer stays UNK.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/global_americas_africa'
OUT = ROOT / 'data/research/global_americas_africa'
EST = ROOT / 'data/estimates/global_americas_africa_flows.json'
CUTOFF = '2026-11-15'
GROUPS = ['visitor', 'student', 'work', 'family']


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def sid(filename):
    return 'gaa_' + Path(filename).stem


SOURCE_INFO = {
    'br_mre_index.html': ('BRA', 'Brazil Ministry of Justice / OBMigra', 'MRE visa microdata download index'),
    'br_microdata2021_2025.zip': ('BRA', 'Brazil MRE / OBMigra', 'SCI visa microdata: January 2021 through April 2025, despite index 2021–2025 label'),
    'br_consolidated2026.html': ('BRA', 'Brazil Ministry of Justice / OBMigra', '2026 publication index of 2025 immigration consolidated data'),
    'br_consolidated2025.pdf': ('BRA', 'Brazil Ministry of Justice / MRE / OBMigra', 'Dados Consolidados da Imigração no Brasil 2025 (published 2026)'),
    'br_fees2025_legal.html': ('BRA', 'Brazil MRE; reproduced by LegisWeb', 'Portaria MRE 602 of 8 May 2025: consular tariff'),
    'br_usd_indexed_excerpt.txt': ('BRA', 'Brazil MRE, US consular posts', 'Indexed official US-post tariff excerpts; original retrieval blocked'),
    'mx_report2025.pdf': ('MEX', 'Secretaría de Relaciones Exteriores, Mexico', 'Primer Informe de Labores 2024–2025'),
    'mx_sre_report_index.html': ('MEX', 'Secretaría de Relaciones Exteriores, Mexico', 'Original report download page'),
    'mx_fees2024.pdf': ('MEX', 'Secretaría de Relaciones Exteriores, Mexico', 'Extracto de la Ley Federal de Derechos para 2024'),
    'mx_fees2025.pdf': ('MEX', 'Secretaría de Relaciones Exteriores, Mexico', 'Extracto de la Ley Federal de Derechos para 2025'),
    'ar_tourist.html': ('ARG', 'Ministerio de Relaciones Exteriores, Argentina', 'Visa para Turismo'),
    'ar_work.html': ('ARG', 'Ministerio de Relaciones Exteriores, Argentina', 'Visa para trabajo'),
    'ar_student.html': ('ARG', 'Ministerio de Relaciones Exteriores, Argentina', 'Student visa, official education; MERCOSUR exemptions'),
    'cl_visa.html': ('CHL', 'Ministerio de Relaciones Exteriores, Chile', 'Autorización previa o visa; differentiated nationality requirements'),
    'cl_fee_index.html': ('CHL', 'Ministerio de Relaciones Exteriores, Chile', 'Cuadro de visas y aranceles'),
    'cl_tariff2026.pdf': ('CHL', 'Ministerio de Relaciones Exteriores, Chile', 'Visa tariff table corrected 6 March 2026; not a 2024/25 tariff'),
    'co_2025_indexed_excerpt.txt': ('COL', 'Colombia MRE, Consulate Santiago', 'September–December 2025 visa tariff indexed excerpt; original blocked'),
    'do_fees.html': ('DOM', 'Ministerio de Relaciones Exteriores, Dominican Republic', 'Official consular tariff: visitor, student, work, dependant and resident visas'),
    'pe_tariff.pdf': ('PER', 'Ministerio de Relaciones Exteriores, Peru', 'Tarifa de derechos consulares: resident/student tariffs and specific exemptions'),
    'pe_tourist.html': ('PER', 'Consulado General del Perú en Santiago', 'Tourist visa requirements and 30 consular-sol fee'),
    'eg_faq.html': ('EGY', 'Ministry of Interior, Egypt', 'Official e-Visa FAQ; current 2026 prices 30/65 USD, not 2024/25 prices'),
    'ma_formalities.html': ('MAR', 'Moroccan National Tourism Office', 'Travel formalities; official Accès Maroc eVisa / AEVM link'),
    'ma_guide_indexed_excerpt.txt': ('MAR', 'Accès Maroc / Morocco Ministry of Foreign Affairs', 'eVisa guide fee indexed excerpt; original retrieval failed'),
    'ke_eta.html': ('KEN', 'Directorate of Immigration Services, Kenya', 'Official eTA FAQ; travel authorisation excluded from visa money'),
    'et_tourist.html': ('ETH', 'Immigration and Citizenship Service, Ethiopia', 'Official tourist visa SPA entry point'),
    'et_js.js': ('ETH', 'Immigration and Citizenship Service, Ethiopia', 'Official eVisa application bundle containing tourist USD62/152 fee table'),
    'ng_2025_indexed_excerpt.txt': ('NGA', 'Nigeria Immigration Service', 'Service Level Agreement August 2025; indexed extract, original blocked'),
    'tz_guidelines.html': ('TZA', 'Tanzania Immigration Services', 'Official visa types, tariff and requirements'),
    'tz_revenue2025.pdf': ('TZA', 'Tanzania Ministry of Finance', 'FY2024/25 Revenue Book Volume I, as passed by Parliament'),
    'tz_mof.html': ('TZA', 'Tanzania Ministry of Finance', 'Budget-book original download index'),
    'ug_abstract2024.pdf': ('UGA', 'Uganda Ministry of Internal Affairs / DCIC', 'Approved Annual Statistical Abstract FY2023/24'),
    'ug_fees2021.pdf': ('UGA', 'Uganda Government; legal reproduction by ULII / Laws.Africa', 'Citizenship and Immigration Control (Fees) Regulations 2021, SI12'),
    'ug_visa_fees.html': ('UGA', 'Uganda Directorate of Citizenship and Immigration Control', '12 October 2023 official anti-fraud notice containing full visa fee table'),
    'za_annual2025.pdf': ('ZAF', 'Department of Home Affairs, South Africa', 'Annual Report FY2024/25'),
    'za_tariff2005.pdf': ('ZAF', 'South African Government Gazette', 'Notice 122/2005: Immigration Regulations prescribed fees'),
    'fx_wb_tza.json': ('TZA', 'World Bank / IMF International Financial Statistics', 'PA.NUS.FCRF annual official exchange rate, Tanzania 2024/25'),
    'fx_wb_zaf.json': ('ZAF', 'World Bank / IMF International Financial Statistics', 'PA.NUS.FCRF annual official exchange rate, South Africa 2024/25'),
}

URL_DEFAULTS = {
    'br_mre_index.html': 'https://www.gov.br/mj/pt-br/assuntos/seus-direitos/migracoes/portal-de-imigracao-laboral/obmigra-1/microdados/mre/MRE',
    'tz_revenue2025.pdf': 'https://www.mof.go.tz/uploads/documents/en-1729687079-volume%20I%202024-25%20as%20passed%20by%20Parliament.pdf',
    'za_annual2025.pdf': 'https://www.gov.za/sites/default/files/gcis_document/202510/dha-annual-report-2024-25.pdf',
    'br_usd_indexed_excerpt.txt': 'https://www.gov.br/mre/pt-br/consulado-sao-francisco/servicos-consulares-e-informacoes-uteis/visto-para-o-brasil',
    'co_2025_indexed_excerpt.txt': 'https://santiagodechile.consulado.gov.co/sites/default/files/FOTOS2025/TABLA%20TARIFAS%20PESOS%20CHILENOS%20VISAS%20%28SEP-DIC%29%202025.pdf',
    'ma_guide_indexed_excerpt.txt': 'https://www.acces-maroc.ma/assets/docs/Guide%20eVisa.pdf',
    'ng_2025_indexed_excerpt.txt': 'https://immigration.gov.ng/wp-content/uploads/2025/10/SERVICE_LEVEL_AGREEMENT_2025_.pdf',
}


def archive_sources(download=False, extract=False):
    urls = dict(URL_DEFAULTS)
    # The successful final report PDF URL takes precedence over failed mirrors.
    for path in sorted(OUT.glob('download_urls*.json')):
        urls.update(json.loads(path.read_text()))
    urls.update(URL_DEFAULTS)
    urls['mx_report2025.pdf'] = 'https://www.gob.mx/cms/uploads/attachment/file/1019639/1er_Informe_SRE_2025_vweb.pdf'
    urls['fx_wb_zaf.json'] = 'https://api.worldbank.org/v2/country/ZAF/indicator/PA.NUS.FCRF?format=json&date=2024:2025'
    logs = []
    if download:
        import requests
        for name in SOURCE_INFO:
            if name.endswith('_excerpt.txt'):
                continue
            url = urls[name]
            try:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                if name.endswith('.pdf') and not response.content.startswith(b'%PDF'):
                    raise ValueError('Expected PDF, received a different response type')
                (RAW / name).write_bytes(response.content)
            except Exception as error:
                logs.append({'url': url, 'result': 'refresh_failed_preserved_prior_archive', 'error': str(error), 'research_cutoff': CUTOFF})
    sources = []
    for name, (dest, institution, title) in SOURCE_INFO.items():
        p = RAW / name
        if not p.exists():
            logs.append({'url': urls.get(name), 'result': 'original_not_archived', 'filename': name, 'research_cutoff': CUTOFF})
            continue
        content = p.read_bytes()
        if p.suffix == '.pdf':
            assert content.startswith(b'%PDF'), f'Not a PDF archive: {p}'
        excerpt = name.endswith('_excerpt.txt')
        quality = 'official_indexed_excerpt' if excerpt else 'legal_reproduction' if name in ['ug_fees2021.pdf', 'br_fees2025_legal.html'] else 'official_primary'
        r = dict(source_id=sid(name), url=urls[name], final_url=urls[name], local_path=str(p.relative_to(ROOT)), sha256=hashlib.sha256(content).hexdigest(), bytes=len(content), content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream', institution=institution, publisher=institution, title=title, destination=dest, retrieved_at=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(), research_cutoff=CUTOFF, source_quality=quality, capture_method='search_service_indexed_excerpt' if excerpt else 'http_download_original', archive_status='excerpt_only_original_blocked' if excerpt else 'legal_reproduction_archived' if quality == 'legal_reproduction' else 'original_archived')
        txt = p.with_suffix('.txt')
        if extract and p.suffix in ['.html', '.pdf']:
            if p.suffix == '.pdf':
                from pdfminer.high_level import extract_text
                txt.write_text(extract_text(p))
            else:
                from bs4 import BeautifulSoup
                txt.write_text(BeautifulSoup(p.read_text(), 'html.parser').get_text('\n', strip=True))
        if txt.exists() and txt != p:
            r['extracted_path'] = str(txt.relative_to(ROOT))
        sources.append(r)
    for name, url in urls.items():
        if not (RAW / name).exists() and name not in SOURCE_INFO:
            logs.append({'url': url, 'filename': name, 'result': 'download_failed_or_replaced', 'research_cutoff': CUTOFF})
    logs += [
        {'destination': 'BRA', 'result': 'period_and_origin_correction', 'detail': 'Microdata ZIP actually ends April 2025; pais_nasc means birth country. Neither issuing mission nor birth country is used as payer nationality.'},
        {'destination': 'UGA', 'result': 'internal_source_discrepancy', 'detail': 'FY2023/24 work permits: narrative 12,970; Table 3.7 issued column total 13,488; received narrative/table 15,040 or 15,046. Work money not built from contradictory count.'},
        {'destination': 'UGA', 'result': 'excluded_regional_shared_visa', 'detail': '13,917 East African Tourist Visas issued by Uganda. Regional revenue retention/redistribution not resolved; excluded from money, retained as quantity.'},
        {'destination': 'TZA', 'result': 'budget_not_actual', 'detail': 'Business visa row FY2022/23 actual 28,321,612,500 TZS, FY2023/24 approved budget 34,063,575,000, FY2024/25 budget 36,000,000,000. Budgets only support an explicitly named budget-run-rate scenario.'},
        {'destination': 'EGY', 'result': 'historical_tariff_not_backdated', 'detail': 'Official portal archive now says USD30/65 (2026). Older indexed USD25/60 values are not silently replaced in 2024/25 models; no amount model built.'},
        {'destination': 'KEN', 'result': 'travel_authorisation_excluded', 'detail': 'Official eTA starting USD30 is separate from government visa fees; no eTA amount enters main visa ledger.'},
    ]
    dump(OUT / 'sources.json', sources)
    dump(OUT / 'search_log.json', logs)
    return sources


def text_source(stem):
    return (RAW / (stem + '.txt')).read_text()


def build_observations():
    obs = []
    def add(dest, year, kind, value, source, locator, origin='WORLD', basis='unallocated', metric='visas_issued', unit='visas', start=None, end=None, notes='', **extra):
        ident = re.sub(r'[^a-zA-Z0-9_]+', '_', f'gaa_{dest}_{year}_{kind}_{origin}_{metric}')
        period_start=start or f'{year}-01-01'
        period_end=end or f'{year}-12-31'
        days=(datetime.fromisoformat(period_end)-datetime.fromisoformat(period_start)).days+1
        period='calendar' if period_start[5:]=='01-01' and period_end[5:]=='12-31' else 'fiscal' if days in [365,366] else 'partial'
        r = dict(observation_id=ident, destination=dest, year=year, visa_type=kind, metric=metric, value=value, unit=unit, origin=origin, nationality=origin if basis == 'nationality' else None, origin_basis=basis, basis=basis, source_id=sid(source), source_locator=locator, period_start=period_start, period_end=period_end, year_type=period, period_type={'calendar':'calendar_year','fiscal':'fiscal_year','partial':'partial_reporting_period'}[period], calculation='direct_observation', source_quality='official_primary', notes=notes, **extra)
        obs.append(r)
        return r
    # Recompute all monthly and birth-country/type cells from the original ZIP.
    totals = collections.Counter()
    birth = collections.Counter()
    months = collections.Counter()
    with zipfile.ZipFile(RAW / 'br_microdata2021_2025.zip') as archive:
        with archive.open('Base_Tratada_MRE_jan21_abr25.csv') as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding='utf-8')):
                year = int(r['ano'])
                if year not in [2024, 2025]:
                    continue
                q = int(r['qtd'])
                totals[year, r['tipovisto_tab']] += q
                birth[year, r['pais_nasc'], r['tipovisto_tab']] += q
                months[year, int(r['mes'])] += q
    assert sum(q for (y, _), q in totals.items() if y == 2024) == 196053
    assert max(m for (y, m) in months if y == 2025) == 4
    for (y, typ), q in sorted(totals.items()):
        r = add('BRA', y, typ, q, 'br_microdata2021_2025.zip', f'Base_Tratada_MRE_jan21_abr25.csv; SUM(qtd) WHERE ano={y} AND tipovisto_tab={typ!r}', end=f'{y}-12-31' if y == 2024 else '2025-04-30', notes='CSV categories; pais_nasc and pais_posto do not establish payer nationality.')
        if y == 2025:
            r.update(year_type='partial', period_type='partial_year')
    dump(OUT / 'brazil_birth_country_type_cells.json', [dict(year=y, birth_country=country, visa_type=typ, quantity=q, origin_basis='country_of_birth_not_nationality', period_end='2024-12-31' if y == 2024 else '2025-04-30', source_id='gaa_br_microdata2021_2025', source_locator=f'Base_Tratada_MRE_jan21_abr25.csv; ano={y}, pais_nasc={country!r}, tipovisto_tab={typ!r}; sum(qtd)') for (y, country, typ), q in sorted(birth.items())])
    dump(OUT / 'brazil_monthly_totals.json', [dict(year=y, month=m, quantity=q) for (y, m), q in sorted(months.items())])
    # Table 1 is an embedded image, visually transcribed from archived PDF page 9.
    br2025 = {'Visita': 510195, 'Acolhida humanitária': 1457, 'Estudo': 13003, 'Trabalho': 25479, 'Reunião familiar': 13067, 'Demais Temporários': 2794, 'Diplomático': 1355, 'Oficial': 4938, 'Cortesia': 1949, 'Outros': 938}
    assert sum(br2025.values()) == 575175
    for typ, q in br2025.items():
        r = add('BRA', 2025, typ + '_annual', q, 'br_consolidated2025.pdf', f'PDF page 9, Table 1, TOTAL row, {typ} column', notes='Full 2025 total transcribed from raster table; country columns are explicitly birthplace, not nationality.')
        r['calculation'] = 'manual_transcription_from_archived_table'
    # Mexico is a nine-month consular output, not a full calendar year or nationality table.
    assert '156,766' in text_source('mx_report2025')
    add('MEX', 2025, 'all', 156766, 'mx_report2025.pdf', 'Printed page 21, Red consular en el mundo, Visas row', start='2024-10-01', end='2025-06-30', notes='Nine-month total across all overseas representations; no nationality/type distribution. Visa issuance, not number of applications.')
    ugtext = text_source('ug_abstract2024')
    assert '266,537' in ugtext and '246,445' in ugtext and '6,737' in ugtext
    ugvisa = {'ordinary_tourist': 246445, 'east_african_tourist': 13917, 'multiple_entry': 1637, 'transit': 2317, 'diplomatic_official': 2221}
    assert sum(ugvisa.values()) == 266537
    for typ, q in ugvisa.items():
        add('UGA', 2024, typ, q, 'ug_abstract2024.pdf', f'Printed page 19, Table 3.9, {typ} row', start='2023-07-01', end='2024-06-30')
    family = {'IND': (686,224,2120), 'USA': (418,8,147), 'PAK': (148,25,233), 'GBR': (203,17,77), 'CHN': (56,21,197), 'KEN': (66,30,125), 'SDN': (71,9,37), 'CAN': (87,6,21), 'DEU': (66,3,40), 'UNK': (730,71,795)}
    assert [sum(v[i] for v in family.values()) for i in range(3)] == [2531,414,3792]
    for org, vals in family.items():
        for typ, q in zip(['dependant_child','dependant_other','dependant_spouse'], vals):
            add('UGA', 2024, typ, q, 'ug_abstract2024.pdf', f'Printed page 14, Table 3.6; {org if org != "UNK" else "Others"} row; {typ} column', origin=org, basis='nationality' if org != 'UNK' else 'unallocated', metric='passes_issued', unit='passes', start='2023-07-01', end='2024-06-30', notes='Dependants are separately charged immigration authorisations; counts exclude student, work and tourist cohorts.')
    students = {'IND':3122, 'SOM':2132, 'SDN':1085, 'COD':869, 'TZA':823, 'KEN':691, 'NGA':661, 'PAK':466, 'SSD':436, 'UNK':3443}
    assert sum(students.values()) == 13728
    for org, q in students.items():
        r = add('UGA', 2024, 'student_pass', q, 'ug_abstract2024.pdf', f'Printed page 18, Figure 3.14, {org if org != "UNK" else "Others"} bar; total reconciles to Table 3.8 issued row', origin=org, basis='nationality' if org != 'UNK' else 'unallocated', metric='passes_issued', unit='passes', start='2023-07-01', end='2024-06-30', notes='Visual transcription from archived chart; EAC student fee exemption stated in definitions page. Somalia fee eligibility timing unresolved.')
        r['calculation'] = 'manual_transcription_from_archived_chart'
    for kind, q, loc in [('work_permit_narrative',12970,'Printed pages 15–16, sections 3.6.1/3.6.3'),('work_permit_table',13488,'Printed page 16, Table 3.7, Issued total')]:
        add('UGA', 2024, kind, q, 'ug_abstract2024.pdf', loc, metric='permits_issued', unit='permits', start='2023-07-01', end='2024-06-30', notes='Source internal inconsistency: competing count retained; excluded from amount model.', data_conflict=True)
    for y, q, metric in [(2023,28321612500,'government_fee_receipts'),(2024,34063575000,'approved_revenue_budget'),(2025,36000000000,'revenue_budget')]:
        add('TZA', y, 'business_visa', q, 'tz_revenue2025.pdf', f'Printed page 172, Vote 093, item 14220240 Receipts from Business Visa; column {"2022/2023 Actual Collection" if y == 2023 else "2023/2024 Approved Estimates" if y == 2024 else "2024/2025 Estimates"}', metric=metric, unit='TZS', start=f'{y-1}-07-01', end=f'{y}-06-30', notes='Budget columns are planned collection, not actual receipts.')
    for typ, q in [('critical_skills',1794),('general_work',780),('business',95)]:
        add('ZAF', 2025, typ, q, 'za_annual2025.pdf', f'Printed pages 14–15, Minister performance summary; {typ} adjudication denominator (repeated in service standards)', metric='applications_adjudicated_in_country_cohort', unit='applications', start='2024-04-01', end='2025-03-31', notes='In-country service-performance cohort only, not complete national applications or grants. Processing decisions and fee payment may fall in different periods.')
    dump(OUT / 'observations.json', obs)
    return obs


def build_rules():
    rules = []
    def add(code, dest, typ, group, amount, currency, source, locator, valid=None, notes='', component='government_visa_application_fee', quality=None, **extra):
        rules.append(dict(fee_rule_id='gaa_' + code, destination=dest, visa_type=typ, visa_group=group, fee_component=component, amount=amount, currency=currency, valid_from=valid, valid_to=None, source_id=sid(source), source_locator=locator, calculation='direct_observation', source_quality=quality or ('official_indexed_excerpt' if source.endswith('_excerpt.txt') else 'legal_reproduction' if source in ['ug_fees2021.pdf','br_fees2025_legal.html'] else 'official_primary'), unit='per_application_or_authorisation', payer='foreign applicant', mandatory=True, government_or_service='government', payment_stage='application_or_issue_as_specified', refusal_refund='not_identified', research_cutoff=CUTOFF, applicability=notes, **extra))
    for y, price in [(2024,53),(2025,54)]:
        for g in GROUPS:
            add(f'mx_{y}_{g}', 'MEX', 'ordinary_' + g, g, price, 'USD', f'mx_fees{y}.pdf', 'Printed page 4, Article 22 III(d); exemptions on following page', f'{y}-01-01', 'Ordinary foreign-passport visa: reception, study and, if appropriate, issuance; same processing fee across study/work/family. Reciprocity and humanitarian exemptions; resident-card charges excluded.', refusal_policy='Fee charged for processing regardless of grant; fee exemptions remain relevant.')
        add(f'mx_{y}_long_visitor', 'MEX','long_duration_visitor','visitor',price-1,'USD',f'mx_fees{y}.pdf','Printed page 4, Article 22 III(f)',f'{y}-01-01')
    for typ, g, fee, code in [('VIVIS_electronic','visitor',80,'220.11'),('VITEM_IV','student',100,'230.4'),('VITEM_V','work',100,'230.5'),('VITEM_XI','family',100,'230.11')]:
        add('br_'+typ,'BRA',typ,g,fee,'USD','br_fees2025_legal.html',f'Annex, tariff code {code}','2025-05-12','Original unit R$-ouro, not ordinary BRL. US consular tariff gives USD equivalence; nationality reciprocity and exemption apply. 2024 continuity is a model assumption, not established by this legal act.', original_currency='BRL_gold_consular_unit', original_amount=fee, usd_equivalence_source_id='gaa_br_usd_indexed_excerpt')
    for typ, g, fee, code in [('VIVIS_USA_paper','visitor',185,'220.5'),('VIVIS_CHN_paper','visitor',115,'220.6'),('VITEM_IV_USA','student',85,'230.12'),('VITEM_IV_GBR','student',465,'230.15'),('VITEM_V_USA','work',290,'230.14'),('VITEM_XI_USA','family',290,'230.14'),('VITEM_XI_humanitarian_dependant','family',0,'230.112')]:
        add('br_'+typ,'BRA',typ,g,fee,'USD','br_fees2025_legal.html',f'Annex, tariff code {code}','2025-05-12','Reciprocity/waiver subcase; not universal fee. Government eVisa USD80 differs from paper VIVIS US185.',original_currency='BRL_gold_consular_unit', original_amount=fee)
    for typ, g, fee in [('ordinary_tourist','visitor',50),('transit','visitor',50),('east_african_tourist','visitor',100),('multiple_6_12_month','visitor',100),('multiple_24_month','visitor',150),('diplomatic_official','other',0)]:
        add('ug_'+typ,'UGA',typ,g,fee,'USD','ug_visa_fees.html','Official fees table, notice dated 12 October 2023','2023-10-12','East African Tourist Visa is regional: issuing-country cash receipt is not all retained revenue.')
    add('ug_multi36','UGA','multiple_36_month','visitor',200,'USD','ug_fees2021.pdf','Schedule Part I item 2(c), printed page 3','2021-02-22')
    for typ, g, fee in [('student_pass','student',100),('dependant_spouse','family',350),('dependant_child','family',200),('dependant_other','family',1000)]:
        add('ug_'+typ,'UGA',typ,g,fee,'USD','ug_fees2021.pdf','Schedule Part I item 4, printed pages 3–4','2021-02-22','Government study/dependant authorisation; excludes permanent-residence certificates, identity cards and private service. Student passes for EAC citizens are fee exempt (statistical abstract definitions).')
    add('ug_student_eac','UGA','student_pass_eac','student',0,'USD','ug_abstract2024.pdf','Definitions: Student pass; EAC students exempt from payment',notes='Membership/implementation timing for Somalia unresolved. Do not assign a charged amount to its FY2023/24 cohort.')
    for typ, g, fee in [('visitor','visitor',425),('study','student',425),('work','work',1520),('business','work',1520),('relative','family',425)]:
        add('za_'+typ,'ZAF',typ,g,fee,'ZAR','za_tariff2005.pdf','Notice 122/2005, prescribed-fees table, '+typ+' row',notes='Historical statutory tariff; nationality waivers and current fee/payment timing require separate parameters. VFS service charge is excluded.')
    for typ, g, fee in [('ordinary','visitor',50),('multiple','visitor',100),('business','visitor',250),('transit','visitor',30),('student_short','student',50),('student_long','student',250),('student_extended','student',550)]:
        add('tz_'+typ,'TZA',typ,g,fee,'USD','tz_guidelines.html','Sections 11–12, visa type requirements / VISA FEES table',notes='Current official snapshot; historical tariff start not identified. Business visa is a short stay authorisation and must not replace a residence/work permit beyond 90 days.')
    for typ, g, fee in [('tourism_single','visitor',100),('tourism_multiple','visitor',150),('student','student',100),('dependant','family',150),('work_NM1','work',200),('temporary_worker','work',95),('resident','other',200)]:
        add('do_'+typ,'DOM',typ,g,fee,'USD','do_fees.html','Tasas de visas, '+typ+' row',notes='Current official tariff; historical 2024/25 effective date and issuance volumes not identified. Tourism-card tax is excluded.')
    for typ, g, fee, source in [('tourism','visitor',150,'ar_tourist.html'),('work','work',250,'ar_work.html'),('student','student',250,'ar_student.html')]:
        add('ar_'+typ,'ARG',typ,g,fee,'USD',source,'Arancel consular paragraph',notes='USD or EUR depending on processing mission; paid in local currency. USD here is one mission currency option, not universal conversion. Student MERCOSUR founding-member exemption; migration fees additional and not merged. Current snapshot, historical effective date unconfirmed.')
    add('pe_tourism','PER','tourism','visitor',30,'consular_sol','pe_tourist.html','Costo paragraph',notes='Consular sol is a consular accounting unit, not ordinary PEN; no PEN FX substitution. Historical 2024/25 effective date unconfirmed.')
    for typ, g, fee, locator in [('student_resident','student',15,'66(b)'),('student_temporary','student',15,'67(d)'),('worker_temporary','work',25,'67(g)'),('resident','other',80,'66(a)'),('refugee_resident','other',0,'66(d)')]:
        add('pe_'+typ,'PER',typ,g,fee,'consular_sol','pe_tariff.pdf','Tarifa de derechos consulares, item '+locator,notes='Resident/student/worker rates are distinct. Only named exemption subcases are free; general resident/student visas are not zero. No historical revenue inferred; consular-sol accounting unit not PEN.')
    for typ, g, study, issue in [('tourism','visitor',54,82),('academic','student',16,51),('worker','work',54,270),('spouse_colombian','family',54,270)]:
        for component, amount in [('application_study',study),('issuance_including_stamp',issue)]:
            add('co_'+typ+'_'+component,'COL',typ,g,amount,'USD','co_2025_indexed_excerpt.txt','01/Sep/2025–31/Dec/2025 table USD columns','2025-09-01','Fee-only indexed official evidence; original PDF download blocked. Issuance component includes stated stamp tax and is paid after authorisation; never add it to refused applications.',component=component)
    for typ, fee in [('single',30),('multiple',65)]:
        add('eg_current_'+typ,'EGY',typ,'visitor',fee,'USD','eg_faq.html','Types of visa and fees table',notes='2026 current price: not backdated into 2024/25. Historical USD25/60 tariff lacks archived original in this package.')
    for typ, fee in [('standard',770),('express',1100)]:
        add('ma_'+typ,'MAR','evisa_'+typ,'visitor',fee,'MAD','ma_guide_indexed_excerpt.txt','Guide, payment screen, p5',notes='Indexed excerpt only. No 2024/25 historical effective date or quantity match; not modeled.')
    for days, fee in [(30,62),(90,152)]:
        add('et_tourist_'+str(days),'ETH','tourist_'+str(days)+'_days','visitor',fee,'USD','et_js.js',f'Tourist Visa-VT component; Entry Type / Maximum Duration / Visa Fee table, Single Entry {days} Days',notes='Current official application bundle, not a proven 2024/25 tariff.')
    add('ke_eta','KEN','eTA','visitor',30,'USD','ke_eta.html','How much does the ETA cost?',notes='Starting price for current standard travel authorisation. eTA is excluded from main government visa fees.',component='travel_authorisation',main_money_eligible=False)
    add('cl_nationality_schedule','CHL','prior_visa','visitor',None,'USD','cl_tariff2026.pdf','Nationality table, current 6 March 2026 revision',notes='Nationality-specific visa fees and exemptions; no single rate. Current 2026 table not used for historical 2024/25 money.')
    add('ng_nationality_schedule','NGA','nationality_dependent','other',None,'USD','ng_2025_indexed_excerpt.txt','August 2025 SLA fee appendices',notes='Original table retrieval blocked; no fee guessed. Student/work/dependant and short-visit classes documented; full nationality-by-class tariff remains missing.')
    dump(OUT / 'fee_rules.json', rules)
    return rules


def build_models(obs):
    flows, models, ranges = [], [], []
    lookup = {(r['destination'],r['year'],r['visa_type'],r['origin']):r for r in obs}
    def get(d,y,t,o='WORLD'):
        return lookup[d,y,t,o]
    def add(mid, receiver, year, group, typ, payer, amount, lower, upper, currency, quantity, observations, sources, notes, parameters):
        assert 0 <= lower <= amount <= upper
        flows.append(dict(id=f'{mid}_{payer}_{typ}', payer=payer, receiver=receiver, year=year, visa_group=group, visa_type=typ, visa_label={'visitor':'访问','student':'学生','work':'工作','family':'家属','other':'类别未分配'}[group], amount=amount, lower=lower, upper=upper, currency=currency, quantity=quantity, quantity_basis='modeled_calendar_events_from_explicit_source_period', source_ids=list(dict.fromkeys(sources + [r['source_id'] for r in observations])), observation_ids=[r['observation_id'] for r in observations], method_id=mid, model_status='modeled_estimate', calculation_type='modeled_estimate', period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year_model', period_label=f'{year}自然年模型', origin_basis='unallocated' if payer == 'UNK' else 'modeled_nationality', notes=notes, parameters=parameters))
    for y in [2024,2025]:
        mid=f'gaa_bra_{y}'
        typmap={'visitor':'Visita','student':'Estudo','work':'Trabalho','family':'Reunião familiar','other':'Demais Temporários'}
        for group,typ in typmap.items():
            source=get('BRA',y,typ+('_annual' if y == 2025 else ''))
            q=source['value']
            # Published group totals, unknown nationality mix and fee waivers.
            fee={'visitor':80,'student':100,'work':100,'family':100,'other':100}[group]
            paid={'visitor':.95,'student':.8,'work':.9,'family':.5,'other':.75}[group]
            lowfee={'visitor':40,'student':30,'work':50,'family':0,'other':0}[group]
            highfee={'visitor':185,'student':465,'work':290,'family':290,'other':290}[group]
            add(mid,'BRA',y,group,group,'UNK',q*fee*paid,q*lowfee,q*highfee,'USD',q,[source],['gaa_br_fees2025_legal','gaa_br_usd_indexed_excerpt'],'官方全年分类型签发×政府费率组合情景；付款国籍未识别。出生国、领馆国未转成国籍。免收、互惠、纸签/电子签结构未观测；2024费率延续为工作假设，非实收。',dict(fee_USD=fee, paid_share_center=paid, effective_fee_lower=lowfee,effective_fee_upper=highfee,tariff_original_unit='R$-ouro; USD consular equivalence, not BRL FX',historical_tariff_continuity_assumed=(y==2024),payer_nationality='unidentified',counts_basis='full_calendar_year_issued'))
        models.append(dict(model_id=mid,destination='BRA',year=y,target='按官方分类型签发的政府费用工作模型',formula='issued_by_type × effective_government_fee',source_ids=['gaa_br_microdata2021_2025' if y==2024 else 'gaa_br_consolidated2025','gaa_br_fees2025_legal','gaa_br_usd_indexed_excerpt'],quality='actual annual quantity; unresolved fee/nationality mix; no official receipts',missing='拒签收费、完整国籍交叉表、免收及互惠收费实付；humanitarian/diplomatic/official/courtesy and unclassified Outros not monetized',coverage='partial'))
        # Nine-month publication is explicitly annualised; categories are not invented.
        src=get('MEX',2025,'all');q=src['value']*12/9
        fee=53 if y==2024 else 54
        central=q*(fee-.1)*.95/.9
        lower=q*.75*(fee-1)*.8
        upper=q*1.25*fee/.75
        mid=f'gaa_mex_{y}'
        add(mid,'MEX',y,'other','all_ordinary_visas','UNK',central,lower,upper,'USD',q,[src],[f'gaa_mx_fees{y}'],'2024-10至2025-06官方签发156,766件按12/9外推全年运行率；2024与2025均为该运行率情景。领馆地点未转为付款国籍，未把类别未知分配为旅游。申请费含拒签，申请/签发比与免收是显式参数。',dict(source_period=['2024-10-01','2025-06-30'],source_issued=156766,annualization=12/9,throughput_center=q,throughput_multiplier_range=[.75,1.25],approval_share={'center':.9,'lower':.75,'upper':1},paid_share={'center':.95,'lower':.8,'upper':1},long_duration_share_center=.1,ordinary_fee_USD=fee,source_year_not_same_as_model_year=True))
        flows[-1]['category_detail_status']='unclassified'
        models.append(dict(model_id=mid,destination='MEX',year=y,target='驻外普通签证申请费运行率模型',formula='156766 × 12/9 × (ordinary_fee - long_duration_share) × paid_share / approval_share',quality='official partial-period quantity; annualisation and fees-paid parameters',source_ids=['gaa_mx_report2025',f'gaa_mx_fees{y}'],missing='完整自然年申请、免收、申请国籍及旅游/学生/工作/家属分类',coverage='partial'))
        mid=f'gaa_uga_{y}'
        driftlo,drifthi=(.8,1.2) if y==2024 else (.65,1.35)
        for typ,fee,lofee,hifee in [('ordinary_tourist',50,50,50),('transit',50,50,50),('multiple_entry',125,100,200)]:
            src=get('UGA',2024,typ);q=src['value']
            add(mid,'UGA',y,'visitor',typ,'UNK',q*fee,q*driftlo*lofee,q*drifthi*hifee,'USD',q,[src],['gaa_ug_visa_fees','gaa_ug_fees2021'],'FY2023/24官方签发队列按最近财年运行率桥接自然年；普通/过境USD50，多次签期限组合USD100–200。尚无签证付款国籍，保留未知；东非共签未计入。',dict(fiscal_anchor='2023-07-01/2024-06-30',calendar_bridge='same annual throughput; explicit sensitivity',throughput_multiplier_range=[driftlo,drifthi],fee_USD={'center':fee,'lower':lofee,'upper':hifee},scope='issued_cohort; refused applications excluded'))
        for src in [r for r in obs if r['destination']=='UGA' and r['visa_type'].startswith('dependant_')]:
            fee={'dependant_child':200,'dependant_spouse':350,'dependant_other':1000}[src['visa_type']];q=src['value']
            add(mid,'UGA',y,'family',src['visa_type'],src['origin'],q*fee,q*fee*driftlo*.8,q*fee*drifthi,'USD',q,[src],['gaa_ug_fees2021'],'官方国籍×家属类别签发与各类别法定费用逐格匹配；FY2023/24桥接自然年，保留其他国家为未知。金额为已签发队列的收费模型，含免收/付款时点和年度运行率敏感性。',dict(fiscal_anchor='2023-07-01/2024-06-30',government_fee_USD=fee,observed_nationality=True,throughput_multiplier_range=[driftlo,drifthi],paid_share_range=[.8,1],scope='dependant authorisations, not residence-card/citizenship fees'))
        # Explicit free EAC cohorts are retained as zero amounts; Somalia is unresolved.
        for src in [r for r in obs if r['destination']=='UGA' and r['visa_type']=='student_pass']:
            org=src['origin'];q=src['value']
            if org=='SOM':
                continue
            exempt=org in ['COD','TZA','KEN','SSD']
            share=0 if exempt else .5 if org=='UNK' else 1
            lowshare=0 if exempt or org=='UNK' else .8
            highshare=0 if exempt else 1
            add(mid,'UGA',y,'student','student_pass',org,q*100*share,q*100*lowshare*driftlo,q*100*highshare*drifthi,'USD',q,[src],['gaa_ug_fees2021','gaa_ug_abstract2024'],'官方学生许可国籍柱图数量×法定USD100；EAC学生免收，已识别EAC国家对应0金额。索马里FY2023/24免收实施时点未明，数量保留但不编造金额；其他国籍付费比例情景0–100%。',dict(fiscal_anchor='2023-07-01/2024-06-30',government_fee_USD=100,eac_fee_exempt=exempt,unknown_paid_share={'center':share,'lower':lowshare,'upper':highshare},throughput_multiplier_range=[driftlo,drifthi],scope='study authorisation; no university tuition'))
        models.append(dict(model_id=mid,destination='UGA',year=y,target='普通/过境/多次签、学生及家属政府许可费',formula='sum(official FY2023/24 nationality/type issued × class fee × fee eligibility); calendar run-rate sensitivity',source_ids=['gaa_ug_abstract2024','gaa_ug_visa_fees','gaa_ug_fees2021'],quality='official issued counts; genuine nationality for family/student; fiscal-year bridge',missing='完整工作签费用（源数量矛盾）、索马里学生免收时点、东非共签收入分成、拒签收费及后续财年实际',coverage='partial'))
        # Budget scenario only: the latest actual is separately retained as 2022/23.
        a=get('TZA',2024,'business_visa');b=get('TZA',2025,'business_visa')
        native=(a['value']+b['value'])/2 if y==2024 else b['value']
        fxrow=next(r for r in json.loads((RAW/'fx_wb_tza.json').read_text())[1] if r['date']=='2024')
        rate=fxrow['value'];assert rate and rate>0
        mid=f'gaa_tza_{y}'
        lo,hi=(.6,1.4) if y==2024 else (.55,1.5)
        add(mid,'TZA',y,'visitor','business_visa_budget_run_rate','UNK',native/rate,native*lo/(rate*1.15),native*hi/(rate*.85),'USD',None,[a,b],['gaa_fx_wb_tza'],'政府商业短期签证收费预算运行率情景；预算不是实收。2024按相邻FY2023/24与2024/25预算等权桥接；2025延续FY2024/25预算。未知国籍保留未知。2025 TZS年均汇率缺，显式采用2024汇率并给±15%转换敏感性。',dict(original_amount=native,original_currency='TZS',budget_not_actual=True,actual_control_FY2022_23_TZS=28321612500,calendar_bridge='equal FY budget interpolation' if y==2024 else 'latest FY budget carried forward',budget_realisation_multiplier_range=[lo,hi],TZS_per_USD=rate,fx_observation_year=2024,fx_period='annual_average_2024',fx_multiplier_range=[.85,1.15]))
        models.append(dict(model_id=mid,destination='TZA',year=y,target='商业签证收入预算运行率情景',formula='FY revenue budget bridge / 2024 official TZS-per-USD; budget-realisation and FX sensitivity',source_ids=['gaa_tz_revenue2025','gaa_fx_wb_tza'],quality='budget-based scenario, not observed collection',missing='ordinary/student/family/work full scopes; actual FY2023/24 or later collections; payer nationality; 2025 official annual FX',coverage='budget_scenario_partial'))
        mid=f'gaa_zaf_{y}'
        for typ in ['critical_skills','general_work','business']:
            src=get('ZAF',2025,typ);q=src['value']
            dlo,dhi=(.75,1.25) if y==2024 else (.65,1.35)
            add(mid,'ZAF',y,'work',typ,'UNK',q*1520*.85,q*1520*dlo*.5,q*1520*dhi,'ZAR',q,[src],['gaa_za_tariff2005'],'仅国内受理工作/关键技能/商业签证服务绩效队列，非全国签证收入。FY2024/25年报处理队列按运行率桥接自然年；政府费ZAR1520，未识别国籍免收比例及申请收费时点；不含VFS服务费。',dict(fiscal_anchor='2024-04-01/2025-03-31',government_fee_ZAR=1520,paid_share={'center':.85,'lower':.5,'upper':1},throughput_multiplier_range=[dlo,dhi],coverage='domestic service-performance cohorts only; not national applications',tariff_source='Notice 122/2005, historical statutory tariff'))
        models.append(dict(model_id=mid,destination='ZAF',year=y,target='国内工作签证绩效队列的政府费用模型',formula='adjudication cohort × ZAR1520 × paid share; fiscal run-rate bridge',source_ids=['gaa_za_annual2025','gaa_za_tariff2005'],quality='partial administrative cohort; timing and fee-exemption model',missing='national visitor/student/family totals, complete work applications, fee nationality, actual visa receipts',coverage='partial'))
    for model in models:
        rr=[r for r in flows if r['method_id']==model['model_id']]
        currency=rr[0]['currency'];assert all(r['currency']==currency for r in rr)
        totals={key:sum(r[key] for r in rr) for key in ['amount','lower','upper']}
        model.update(central_native=totals['amount'],lower_native=totals['lower'],upper_native=totals['upper'],currency=currency)
        ranges.append(dict(receiver=model['destination'],year=model['year'],currency=currency,**totals,range_method='同一目的地工作参数端点；仅含明示建模队列，不表示未识别类别为零'))
    dump(EST, dict(models=models,flows=flows,destination_ranges=ranges))
    dump(OUT/'estimates.json',[dict(estimate_id=m['model_id'],destination=m['destination'],year=m['year'],target=m['target'],value=m['central_native'],lower=m['lower_native'],upper=m['upper_native'],currency=m['currency'],source_ids=m['source_ids'],calculation_type='modeled_estimate',model_scope=m['coverage'],formula=m['formula'],notes=m['quality']+'; '+m['missing']) for m in models])
    return models,flows


def build_coverage(rules,models,obs):
    countries={'MEX':('Mexico','Americas'),'BRA':('Brazil','Americas'),'ARG':('Argentina','Americas'),'CHL':('Chile','Americas'),'COL':('Colombia','Americas'),'PER':('Peru','Americas'),'DOM':('Dominican Republic','Americas'),'EGY':('Egypt','Africa'),'MAR':('Morocco','Africa'),'ZAF':('South Africa','Africa'),'KEN':('Kenya','Africa'),'TZA':('Tanzania','Africa'),'ETH':('Ethiopia','Africa'),'NGA':('Nigeria','Africa'),'UGA':('Uganda','Africa')}
    rows=[]
    for dest,(name,region) in countries.items():
        for y in [2024,2025]:
            for g in GROUPS:
                rr=[r for r in rules if r['destination']==dest and r['visa_group']==g]
                model=next((m for m in models if m['destination']==dest and m['year']==y),None)
                quantified=bool(model and ((dest=='BRA') or (dest=='UGA' and g in ['visitor','student','family']) or (dest=='ZAF' and g=='work') or (dest=='TZA' and g=='visitor')))
                if quantified:status='modeled_partial' if dest!='TZA' else 'budget_scenario_partial'
                elif dest=='MEX':status='modeled_total_category_unallocated'
                elif dest=='KEN' and g=='visitor':status='travel_authorisation_excluded'
                elif dest=='UGA' and g=='work':status='quantity_conflict_no_amount'
                elif rr:status='fee_rules_only_no_matched_quantity'
                elif dest=='NGA':status='official_index_identified_original_blocked'
                else:status='searched_not_quantified'
                missing={
                    'BRA':'国籍×类型实付、互惠与免费、拒签申请量；出生国不等于国籍',
                    'MEX':'九个月签发只有全国合计；无完整自然年和国籍×旅游/学生/工作/家属',
                    'UGA':'后续财年实际、收费/签发时点；工作表内矛盾；东非共签分成；索马里学生免收时点',
                    'ZAF':'全国签证按国籍×类别申请、访客/学生/家属总量、免收；模型只覆盖国内工作绩效队列',
                    'TZA':'实际全年收入（现有最新实际FY2022/23）、普通/学生/家属签完整覆盖、付款国籍',
                    'KEN':'eTA为旅行授权，不纳入签证；长期学生/工作/家属签证收费与申请量未匹配',
                    'EGY':'2024/2025历史费率原件及签证申请/签发；当前30/65美元不得回填历史',
                    'CHL':'当前表为2026，2024/2025费率与国籍×签证类别数量未匹配',
                    'NGA':'2025 SLA原始PDF被403拦截；国籍收费表及完整申请/签发未归档',
                    'COL':'2025费率仅官方索引摘录，原始PDF403；申请/签发和免收量未匹配',
                    'MAR':'eVisa收费指南原件下载失败，摘录仅作规则线索；历史费率和申请/签发未匹配',
                    'ARG':'处理领馆的USD/EUR选项、历史有效日期、国籍×类别收费申请量未匹配',
                    'PER':'领事sol非PEN；按类别免收与历史数量未匹配',
                    'DOM':'历史生效日、按国籍×签证类别收费申请量未匹配；未以入境人数乘收费',
                    'ETH':'当前官网JS有费率，2024/25历史有效日和签发/申请数量未匹配',
                }[dest]
                rows.append(dict(destination=dest,country=dest,country_name=name,region=region,year=y,visa_group=g,status=status,coverage_status=status,amount_available=quantified,total_amount_available=bool(model),amount=None,amount_reference='see native model flows; not an official receipt' if quantified else None,model_id=model['model_id'] if model else None,fee_rule_ids=[r['fee_rule_id'] for r in rr],source_ids=list(dict.fromkeys([r['source_id'] for r in rr]+([s for s in model['source_ids']] if model else []))),missing_reason=missing,research_cutoff=CUTOFF))
    dump(OUT/'coverage.json',rows)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download',action='store_true')
    parser.add_argument('--extract',action='store_true')
    args=parser.parse_args()
    sources=archive_sources(args.download,args.extract)
    observations=build_observations()
    rules=build_rules()
    # ZAR has observed annual rates for both model years. TZS2025 is missing and
    # intentionally not synthesized into a registry of observed exchange rates.
    fx=[]
    for file,cur in [('fx_wb_zaf.json','ZAR'),('fx_wb_tza.json','TZS')]:
        for r in json.loads((RAW/file).read_text())[1]:
            if r['value']:
                fx.append(dict(fx_id=f'gaa_wb_{r["date"]}_{cur}',year=int(r['date']),currency=cur,raw_rate=r['value'],raw_direction='currency_per_USD',usd_per_unit=1/r['value'],source_id=sid(file),source_locator=f'PA.NUS.FCRF; {r["countryiso3code"]}; date={r["date"]}',method='World Bank / IMF annual official exchange rate, period average'))
    dump(OUT/'fx.json',fx)
    models,flows=build_models(observations)
    coverage=build_coverage(rules,models,observations)
    sids={r['source_id'] for r in sources};oids={r['observation_id'] for r in observations}
    assert len(oids)==len(observations)
    assert len({r['id'] for r in flows})==len(flows)
    for r in flows:
        assert set(r['source_ids'])<=sids,(r['id'],set(r['source_ids'])-sids)
        assert set(r['observation_ids'])<=oids
        assert r['payer'] not in ['WORLD',r['receiver']]
        assert 0<=r['lower']<=r['amount']<=r['upper']
        assert not (r['receiver']=='KEN' and r['visa_type']=='eTA')
    for r in rules:assert r['source_id'] in sids,r['source_id']
    validation=dict(source_count=len(sources),archived_originals=sum(r['archive_status']=='original_archived' for r in sources),indexed_excerpt_only_sources=[r['source_id'] for r in sources if r['archive_status']=='excerpt_only_original_blocked'],observations=len(observations),fee_rules=len(rules),models=len(models),flows=len(flows),receivers=sorted({r['receiver'] for r in flows}),coverage_country_year_group_cells=len(coverage),observed_fx_records=len(fx),checks={'observation_ids_unique':True,'flow_ids_unique':True,'source_references_resolve':True,'bounds_ordered':True,'birth_country_never_used_as_nationality':True,'budget_actual_distinction_preserved':True,'eTA_excluded_from_visa_money':True,'unknown_payer_retained':True,'uganda_family_categories_reconcile':True,'uganda_student_nationalities_reconcile':True,'brazil_full_year_separated_from_april_microdata':True})
    dump(OUT/'validation.json',validation)
    (OUT/'README.md').write_text('''# Americas and Africa evidence package

Rebuild offline with `.research-venv/bin/python scripts/research_global_americas_africa.py`.
Use `--extract` only to refresh archived PDF/HTML text and `--download` to attempt original refreshes.

Sources preserve SHA-256 and archive status. Four indexed excerpts are labelled excerpt-only because original downloads were blocked; the Brazil fee legal text and Uganda 2021 law are archived legal reproductions. There is no claim that blocked originals were downloaded.

Money models cover Brazil, Mexico, Uganda, South Africa and Tanzania. Every model is a fee estimate rather than published fee receipts. Mexico uses an explicit nine-month annualisation. Uganda uses FY2023/24 quantities and preserves real student/family nationality; 2025 is a carry-forward scenario. South Africa is only the domestic work-service cohort. Tanzania is an explicit budget-run-rate scenario and retains the older actual separately.

Brazil's 34 MB original microdata ZIP ends April 2025. Country field `pais_nasc` means birth country; it is retained in a separate research table and never substituted for nationality. The archived 2025 report supplies full-year group totals. Birth-country and issuing-post fields do not create bilateral money edges.

Uganda work-permit source counts conflict (12,970 narrative versus 13,488 issued table total), so no work-money model is built. East African Tourist Visa regional revenue distribution and Somalia student exemption timing are unresolved and are excluded from money. Named EAC student exemptions retain genuine zero fee rows. Work/student/dependant authorisations are distinguished from permanent-residence certificates, cards, citizenship and tuition.

`coverage.json` records 15 countries × 2 years × 4 visa groups, including fee-only, conflicting, excluded and missing cells. No arrivals were multiplied by a fee. Current 2026 prices are never silently backdated. All limitations and model assumptions live at their corresponding records.
''')
    print(json.dumps(validation,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
