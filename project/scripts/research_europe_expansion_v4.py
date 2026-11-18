#!/usr/bin/env python3
"""Rebuild European historical receipts and visa-activity context offline.

Ireland's Justice cash account includes entry and re-entry receipts.  The
nationality/monthly entry-visa event tables are context, never allocation keys
or revenue denominators.  Suppression and partial reporting remain explicit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import calendar
import csv
import gettext
import hashlib
import json
import logging
from pathlib import Path
import re

from bs4 import BeautifulSoup
from pypdf import PdfReader
import pycountry

from entity_names import canonical_name, JURISDICTION_NOTE

logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/europe_expansion_v4'
OUT = ROOT / 'data/research/europe_expansion_v4'
EST = ROOT / 'data/estimates/europe_expansion_v4_flows.json'
ASOF = '2026-11-17'
MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
# The12 official purpose columns are disjoint.  The final Gesamt column is not
# an additional purpose; all detailed consular rows sum to the worldwide row.
DEU_PURPOSES = [
    ('spouse_reunification', '配偶团聚', 'Ehegattennachzug', 'family'),
    ('parent_reunification', '父母团聚', 'Elternnachzug', 'family'),
    ('child_reunification', '子女团聚', 'Kindernachzug', 'family'),
    ('other_family_reunification', '其他家庭团聚', 'Sonstiger Familiennachzug', 'family'),
    ('study_preparation', '学习及升学准备', 'Studium (einschl. studienvorbereitende Maßnahmen und Studienbewerbung)', 'student'),
    ('language_school', '语言课程及学校', 'Sprachkurs/Schulbesuch', 'student'),
    ('employment', '工作、研究及实践', 'Erwerbstätigkeit (einschl. Wissenschaftler, Hochqualifizierte, Praktika, Au-Pair, Freiwilligendienste)', 'work'),
    ('jewish_immigration', '犹太移民', 'Jüdische Zuwanderung', 'other'),
    ('late_repatriates', '德裔后期迁入', 'Spätaussiedler', 'other'),
    ('humanitarian_resettlement', '人道接收及安置', 'Humanitäre Aufnahme / Resettlement', 'other'),
    ('other_purposes', '其他居留目的', 'Sonstige Aufenthaltszwecke', 'other'),
    ('unassigned_purposes', '用途未分配', 'Nicht zugeordnet', 'other'),
]
TR = gettext.translation('iso3166-1', pycountry.LOCALES_DIR, languages=['zh_CN'], fallback=True).gettext
ALIASES = {
    '*Other': 'UNK', 'Ceuta': 'UNK', 'Melilla': 'UNK', 'Kosovo': 'XKX',
    'Turkiye': 'TUR', 'Bolivia (Plurinational State of)': 'BOL',
    'Congo (the Democratic Republic of the)': 'COD',
    'Falkland Islands (the) [Malvinas]': 'FLK', 'Iran (Islamic Republic of)': 'IRN',
    "Korea (the Democratic People's Republic of) North Korea": 'PRK',
    'Micronesia (Federated States of)': 'FSM', 'Moldova (the Republic of)': 'MDA',
    'Tanzania, the United Republic of': 'TZA', 'Venezuela (Bolivarian Republic of)': 'VEN',
    'Virgin Islands (British)': 'VGB', 'Virgin Islands (U.S.)': 'VIR',
}


def country(raw):
    if raw in ALIASES:
        return ALIASES[raw]
    return pycountry.countries.lookup(re.sub(r' \(the\)', '', raw)).alpha_3


def name(code):
    c = pycountry.countries.get(alpha_3=code)
    return canonical_name(code, TR(c.name) if c else {'UNK': '来源未分配', 'XKX': '科索沃','WORLD':'全球'}.get(code, code))


def write(filename, obj):
    (OUT / filename).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def cell(raw):
    """A suppressed event count is unknown in [1,5], never an exact three."""
    raw = raw.strip()
    if raw == '*':
        return dict(value=None, lower=1, upper=5, suppressed=True, raw_value=raw)
    if raw == '':
        return dict(value=None, lower=None, upper=None, suppressed=False, missing=True, raw_value=raw)
    value = int(raw)
    assert value >= 0
    return dict(value=value, lower=value, upper=value, suppressed=False, raw_value=raw)


def aggregate(cells):
    assert cells and all(c['lower'] is not None for c in cells)
    lo = sum(c['lower'] for c in cells)
    hi = sum(c['upper'] for c in cells)
    return dict(value=lo if lo == hi else None, lower=lo, upper=hi,
                unsuppressed_total=sum(c['value'] or 0 for c in cells),
                suppressed_cells=sum(c['suppressed'] for c in cells),
                suppressed=lo != hi)


class Research:
    def __init__(self):
        self.sources, self.obs, self.fx = [], [], []
        self.flows, self.models, self.ranges = [], [], []
        self.native_country, self.reconciliations, self.country_mapping = [], [], []
        self.fees, self.germany_checks, self.deu_scenarios = [], [], []
        self.check_details = []

    def source(self, slug, filename, url, publisher, title, notes=''):
        path = RAW / filename
        assert path.exists() and path.stat().st_size > 1000, filename
        if filename.endswith('.pdf'):
            assert path.read_bytes().startswith(b'%PDF'), filename
        sid = 'evx_' + slug
        self.sources.append(dict(source_id=sid, url=url, publisher=publisher, title=title,
                                 retrieved_at=ASOF, source_quality='official_original',
                                 local_path=str(path.relative_to(ROOT)), path=str(path.relative_to(ROOT)),
                                 bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                 archive_kind='original_document', notes=notes))
        return sid

    def observation(self, slug, year, metric, unit, sid, locator, **extra):
        code = extra.pop('nationality', 'UNK')
        origin = extra.pop('origin', code)
        oid = 'evx_' + slug
        self.obs.append(dict(observation_id=oid, destination=extra.pop('destination', 'IRL'),
                             year=year, metric=metric, raw_metric=extra.pop('raw_metric', metric),
                             unit=unit, source_id=sid, source_ids=[sid], source_locator=locator,
                             nationality=code, origin=origin,
                             origin_display_name=extra.pop('origin_display_name',name(origin)),
                             origin_basis=extra.pop('origin_basis', 'observed_nationality' if code != 'UNK' else 'unallocated'),
                             visa_type=extra.pop('visa_type', 'unclassified'), visa_group=extra.pop('visa_group', 'other'),
                             period_start=extra.pop('period_start', f'{year}-01-01'),
                             period_end=extra.pop('period_end', f'{year}-12-31'),
                             period_type=extra.pop('period_type', 'calendar_year'),
                             calculation_type=extra.pop('calculation_type', 'direct_observation'),
                             eligible_money_ledger=extra.pop('eligible_money_ledger', False), **extra))
        return oid

    def ireland_cash(self):
        manifest = json.loads((RAW / 'downloads_accounts.json').read_text())
        urls = {int(re.search(r'account(\d{4})', r['filename'])[1]): r['url']
                for r in manifest if re.search(r'account(\d{4})', r['filename'])}
        pages = {2017: 23, 2019: 29, 2020: 26, 2021: 32, 2022: 31, 2023: 29}
        sids, texts = {}, {}
        for edition, page in pages.items():
            sid = self.source(f'irl_account{edition}', f'irl_account{edition}.pdf', urls[edition],
                              'Ireland Comptroller and Auditor General / Department of Justice',
                              f'Appropriation Account {edition}, Vote 24 Justice, Visa fees realised',
                              f'PDF p{page}, note4.1 Appropriations-in-aid: realised visa fees, EUR thousands; previous-year realised is a comparative, not an extra receipt. Registration, citizenship, passport, accrued and deferred balances excluded. 2023 explanatory note includes Atypical Working Scheme, so 2023 is context only.')
            reader = PdfReader(RAW / f'irl_account{edition}.pdf')
            text = reader.pages[page - 1].extract_text(extraction_mode='layout')
            assert 'Visa fees' in text and 'Realised' in text and '€000' in text
            texts[edition] = text
            sids[edition] = sid
            (OUT / f'irl_account{edition}_p{page}_layout.txt').write_text(text)
            explanatory = {2017: 24, 2019: 30, 2020: 26, 2021: 32, 2022: 32, 2023: 30}[edition]
            explanation = reader.pages[explanatory - 1].extract_text()
            (OUT / f'irl_account{edition}_p{explanatory}_scope.txt').write_text(explanation)
        # Current and comparative columns independently confirm every repeated year.
        pattern_values = {
            2017: ['4,000', '8,300', '8,741'], 2019: ['10,000', '9,847', '9,552'],
            2020: ['3,200', '3,082', '9,847'], 2021: ['2,700', '3,019', '3,082'],
            2022: ['6,600', '7,913', '3,019'], 2023: ['9,254', '11,544', '7,913'],
        }
        for edition, values in pattern_values.items():
            text = texts[edition]
            segment = text.split('Visa fees', 1)[1].split('Dormant accounts', 1)[0]
            assert all(v in segment for v in values), (edition, segment)
        scope17 = (OUT / 'irl_account2017_p24_scope.txt').read_text()
        assert 'entry and re-' in scope17 or 'entry and re‐' in scope17 or 'entry and re–' in scope17
        scope20 = (OUT / 'irl_account2020_p26_scope.txt').read_text()
        scope23 = (OUT / 'irl_account2023_p30_scope.txt').read_text()
        assert 'Atypical Worker Scheme' in scope20 and 'Miscellaneous receipts' in scope20
        assert 'Atypical' in scope23 and 'Working Scheme' in scope23
        controls = [(2016, 8741, 2017, 'comparative 2016'), (2017, 8300, 2017, '2017'),
                    (2018, 9552, 2019, 'comparative 2018'), (2019, 9847, 2019, '2019'),
                    (2020, 3082, 2020, '2020'), (2021, 3019, 2021, '2021'),
                    (2022, 7913, 2022, '2022'), (2023, 11544, 2023, '2023')]
        for year, thousands, edition, column in controls:
            mixed = year == 2023
            amount = thousands * 1000
            notes = ('该年科目解释同时涉及Atypical Working Scheme，未单独披露金额，因此仅作财务背景，不进入签证费总账。' if mixed else
                     'Vote24 Justice独立Visa fees实收科目，包括入境及再入境签证。不是所有海外使领馆留存费的完整普查。国籍、用途与匹配付费申请件数未披露。')
            oid = self.observation(f'irl_{year}_justice_cash', year,
                                   'mixed_visa_and_atypical_working_scheme_receipts' if mixed else 'government_visa_fee_receipts',
                                   'EUR', sids[edition], f'PDF p{pages[edition]}, note4.1 Visa fees / {column} Realised column; unit €000',
                                   value=amount, lower=amount-500, upper=amount+500,
                                   reported_value=thousands, reported_unit='EUR_thousands', rounding_unit_EUR=1000,
                                   observation_domain='finance_context' if mixed else 'visa_finance',
                                   context_only=mixed, aggregation_role='country_total',
                                   series_id='irl_justice_mixed_cash' if mixed else 'irl_justice_visa_cash',
                                   series_label='司法部签证与AWS混合实收' if mixed else '司法部签证费实收',
                                   eligible_money_ledger=not mixed, account_scope='Vote24 Justice cash receipts',
                                   visa_type='justice_visa_cash', notes=notes)
            if mixed:
                continue
            params = dict(actual_receipts_observed=True, government_scope='Vote24 Justice',
                          fee_scope='entry_and_reentry_visa_receipts', payer_nationality='unallocated',
                          quantity_denominator=None, range_method='官方千欧元实收的±500欧元取整区间；不是置信区间',
                          excludes=['registration', 'citizenship', 'passports', 'accrued_and_deferred_balances', 'mixed_2023_AWS'])
            self.flows.append(dict(id=f'evx_irl_{year}_justice_visa_cash', payer='UNK', receiver='IRL', year=year,
                                   visa_group='other', visa_type='justice_visa_fee_receipts', visa_label='司法部签证费实收',
                                   category_detail_status='unclassified', amount=amount, lower=amount-500, upper=amount+500,
                                   currency='EUR', quantity=None,
                                   quantity_basis='cash_receipts_entry_and_reentry_without_matching_event_denominator',
                                   source_ids=[sids[edition]], observation_ids=[oid], method_id='evx_irl_justice_actual_cash',
                                   model_status='observed_receipts_partial', calculation_type='direct_observation',
                                   origin_basis='unallocated', period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                                   period_type='calendar_year', period_label=str(year), notes=notes, parameters=params))
            self.ranges.append(dict(receiver='IRL', year=year, amount=amount, lower=amount-500, upper=amount+500,
                                    currency='EUR', range_method=params['range_method']))
        self.models.append(dict(model_id='evx_irl_justice_actual_cash', destination='IRL', years=list(range(2016, 2023)),
                                status='observed_vote24_visa_receipts', formula='Realised Visa fees (€000) × 1000',
                                limitations=['包括入境及再入境签证，没有匹配分母；不按仅入境国籍申请表分配。',
                                             'Vote24收款账户，未证明覆盖所有海外使领馆保留费。',
                                             '2023解释含Atypical Working Scheme，仅保留背景。',
                                             '原币区间仅为千欧元取整，不是模型置信区间。']))

    def ireland_activity(self):
        # Identical frozen original already registered by the r7 package.
        source = next(s for s in json.loads((ROOT / 'data/research/global_asia_me_europe/sources.json').read_text())
                      if s['source_id'] == 'game_irl_nationalities')
        assert hashlib.sha256((RAW / 'irl_nationality.csv').read_bytes()).hexdigest() == source['sha256']
        self.sources.append(source)
        sid = source['source_id']
        meta = self.source('irl_nationality_metadata', 'irl_nationality_resource.html',
                           'https://data.gov.ie/en_GB/dataset/6c903e63-69d8-40b9-a74e-172785f0bc27/resource/f4477ebf-7f24-4f2e-b222-fd661d2fbd42',
                           'Ireland Department of Justice / data.gov.ie', 'Visa nationality resource metadata and suppression definitions',
                           'Current description: suppression1–5; older embedded Notes/Description:1–3. Current1–5 adopted; conflict preserved. Received means payment completed; Granted combines first-instance and appeal grants; Refused first-instance. Annual event series are not a closed cohort.')
        sm = self.source('irl_monthly_activity', 'irl_month.csv',
                         'https://assets.gov.ie/static/documents/ab681bf6/visa_applications_and_decisions_-_year_and_month.csv',
                         'Ireland Department of Justice / Immigration Service Delivery', 'Visa applications and decisions — year and month, 2017–September2026',
                         'CP1252 CSV;60 rows;2 duration groups ×3 status groups ×10 years. 2026 Jan–Sep; Oct–Dec empty and not zero. Suppressed monthly cells retain1–5.')
        smm = self.source('irl_monthly_metadata', 'irl_month_resource.html',
                          'https://data.gov.ie/dataset/visa-applications-and-decisions-year-and-month/resource/89031928-75af-4a47-9a1b-1448f9e78a8a',
                          'Ireland Department of Justice / data.gov.ie', 'Visa monthly activity metadata',
                          'Received payment completed; granted first instance or appeal; refused first instance.1–5 suppressed; events not unique people; as-of snapshot subject to revision.')
        mt = BeautifulSoup((RAW / 'irl_nationality_resource.html').read_bytes(), 'html.parser').get_text(' ', strip=True)
        assert 'Values in the range 1 to 5' in mt and 'Values in the range 1 to 3' in mt
        assert 'payment completed' in mt and 'Appeal Granted' in mt and '1st instance' in mt
        monthly_text = BeautifulSoup((RAW / 'irl_month_resource.html').read_bytes(), 'html.parser').get_text(' ', strip=True)
        assert '1 to 5' in monthly_text and 'payment completed' in monthly_text
        rows = list(csv.DictReader((RAW / 'irl_nationality.csv').open(encoding='cp1252')))
        mrows = list(csv.DictReader((RAW / 'irl_month.csv').open(encoding='cp1252')))
        assert len(rows) == 1038 and len(mrows) == 60
        assert {r['Last Updated'] for r in rows + mrows} == {'30/09/2026'}
        assert Counter(r['Status'] for r in rows) == {'Received': 346, 'Granted': 346, 'Refused': 346}
        quantities = defaultdict(list)
        country_counts = Counter()
        for ix, row in enumerate(rows):
            code = country(row['Nationality'])
            country_counts[(row['Nationality'], code)] += 1
            duration = 'short_term' if row['Type'].startswith('short') else 'long_term'
            status = row['Status'].lower()
            for year in range(2017, 2027):
                c = cell(row[str(year)])
                assert not c.get('missing'), (ix, year)
                quantities[(year, duration, status)].append(c)
                native = dict(csv_row=ix+2, year=year, original_nationality=row['Nationality'], nationality=code,
                              name=name(code), duration_group=duration, status=status, **c)
                self.native_country.append(native)
                # The legacy2024/25 observations preserve the source cell but
                # lose its short/long duration in the unified context layer.
                # Re-transform those cells for this duration-aware series;
                # this creates no money edge or additional event to sum.
                bucket = code == 'UNK'
                source_bucket = 'SOURCE:irl_' + hashlib.sha256(row['Nationality'].encode()).hexdigest()[:12]
                bucket_fields = dict(origin=source_bucket, origin_name=row['Nationality'],
                                     raw_origin_label=row['Nationality'], origin_display_name=row['Nationality']) if bucket else {}
                self.observation(f'irl_activity_{year}_{ix}', year, 'visa_applications_' + status, 'application_events', sid,
                                 f'CSV row{ix+2}; Type={row["Type"]}; Status={row["Status"]}; Nationality={row["Nationality"]}; column{year}',
                                 nationality=code, visa_type=duration, original_nationality=row['Nationality'],
                                 duration_group=duration, status=status, **c,
                                 reused_source_observation_ids=[f'game_irl_{year}_{ix}'] if year in (2024,2025) else [],
                                 contextual_transformation='duration_preserving_source_cell',
                                 metadata_source_id=meta, observation_domain='visa_activity', context_only=True,
                                 series_id=f'irl_visa_{duration}_{status}_nationality',
                                 series_label=('短期' if duration == 'short_term' else '长期') + {'received':'签证申请受理','granted':'签证获批','refused':'签证拒签'}[status] + '（国籍）',
                                 aggregation_role='source_bucket_component' if bucket else 'nationality_part',
                                 **bucket_fields,
                                 period_end=f'{year}-09-30' if year == 2026 else f'{year}-12-31',
                                 period_type='partial_calendar_year' if year == 2026 else 'calendar_year',
                                 is_partial=year == 2026, as_of='2026-09-30',
                                 notes='入境签证事件；Received为完成付款后的受理，Granted含上诉获批，Refused为初审拒签；各状态年度不构成同一封闭申请队列。*保留1–5区间，不作0或精确3。与入境及再入境混合收款不匹配，不计算每申请人费用。')
        self.country_mapping = [dict(original_nationality=raw, nationality=code, name=name(code), source_rows=count,
                                     mapping_note='原表剩余项或非ISO属地；原称保留，不分给其他国家' if code == 'UNK' else 'source nationality mapped to statistical code')
                                for (raw, code), count in sorted(country_counts.items())]
        annual_months = defaultdict(list)
        for ix, row in enumerate(mrows):
            year = int(row['year'])
            duration = 'short_term' if row['Type'].startswith('short') else 'long_term'
            status = row['Status'].lower()
            cells = []
            for month, label in enumerate(MONTHS, 1):
                c = cell(row[label])
                if c.get('missing'):
                    assert year == 2026 and month >= 10
                    continue
                cells.append(c)
                self.observation(f'irl_month_{year}_{duration}_{status}_{month:02d}', year,
                                 'visa_applications_' + status, 'application_events', sm,
                                 f'CSV row{ix+2}; Type={row["Type"]}; Status={row["Status"]}; year={year}; column{label}',
                                 **c, visa_type=duration, duration_group=duration, status=status,
                                 period_start=f'{year}-{month:02d}-01',
                                 period_end=f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}',
                                 period_type='calendar_month', is_partial=False, as_of='2026-09-30',
                                 metadata_source_id=smm, observation_domain='visa_activity', context_only=True,
                                 origin_basis='all_nationalities', aggregation_role='country_total',
                                 series_id=f'irl_visa_{duration}_{status}_monthly',
                                 series_label=('短期' if duration == 'short_term' else '长期') + {'received':'签证申请受理','granted':'签证获批','refused':'签证拒签'}[status] + '（月度）',
                                 notes='真实月度入境签证事件；无国籍拆分。状态年度不是同一封闭申请队列，不能把当年拒签／受理当拒签概率。2026仅有1–9月，后续空白保留缺失。')
            assert len(cells) == (9 if year == 2026 else 12)
            a = aggregate(cells)
            annual_months[(year, status)].extend(cells)
            nat = aggregate(quantities[year, duration, status])
            reconciles = a['lower'] <= nat['upper'] and a['upper'] >= nat['lower']
            self.reconciliations.append(dict(year=year, duration_group=duration, status=status,
                                              monthly_sum=a, nationality_sum=nat,
                                              intervals_intersect=reconciles,
                                              difference_monthly_minus_unsuppressed_nationalities=a['unsuppressed_total']-nat['unsuppressed_total'],
                                              action='preserve original cells and intervals; do not force to totals'))
            assert reconciles, self.reconciliations[-1]
            self.observation(f'irl_annual_{year}_{duration}_{status}', year, 'visa_applications_' + status,
                             'application_events', sm, f'CSV row{ix+2}; sum of nonempty Jan–Dec columns ({len(cells)} months)',
                             **a, visa_type=duration, duration_group=duration, status=status,
                             period_end=f'{year}-09-30' if year == 2026 else f'{year}-12-31',
                             period_type='partial_calendar_year' if year == 2026 else 'calendar_year',
                             is_partial=year == 2026, months_observed=len(cells), as_of='2026-09-30',
                             calculation_type='sum_published_monthly_events', metadata_source_id=smm,
                             observation_domain='visa_activity', context_only=True,
                             origin_basis='all_nationalities', aggregation_role='country_total',
                             series_id=f'irl_visa_{duration}_{status}_annual',
                             series_label=('短期' if duration == 'short_term' else '长期') + {'received':'签证申请受理','granted':'签证获批','refused':'签证拒签'}[status] + '（年度）',
                             notes='各月原数相加；受抑制月则保留区间。短长期为并列互斥持续期，短期不能等同旅游，长期不能等同工作或学习。2026为1–9月；未年化。')
        for (year, status), cells in sorted(annual_months.items()):
            a = aggregate(cells)
            self.observation(f'irl_all_duration_{year}_{status}', year, 'visa_applications_' + status,
                             'application_events', sm, f'CSV year={year}, Status={status}; sum short-term and long-term nonempty month cells',
                             **a, visa_type='all_entry_visas', status=status, duration_group='all',
                             period_end=f'{year}-09-30' if year == 2026 else f'{year}-12-31',
                             period_type='partial_calendar_year' if year == 2026 else 'calendar_year',
                             is_partial=year == 2026, months_observed=9 if year == 2026 else 12,
                             calculation_type='sum_disjoint_published_duration_month_cells', metadata_source_id=smm,
                             observation_domain='visa_activity', context_only=True,
                             origin_basis='all_nationalities', aggregation_role='country_total',
                             series_id=f'irl_visa_all_{status}_annual',
                             series_label={'received':'签证申请受理','granted':'签证获批','refused':'签证拒签'}[status] + '（全部入境签证）',
                             notes='短长期入境签证事件合计，可作年度规模及疫情前后参照；含各月重复旅行／申请事件。不是独立申请人数或再入境签证件数，不能作为司法部实收的匹配分母。')

    def germany_national(self):
        manifest = json.loads((RAW / 'downloads_germany.json').read_text())
        urls = {int(re.search(r'national(\d{4})', r['filename'])[1]): r['url'] for r in manifest}
        landing = self.source('deu_statistics_landing', 'deu_statistics_landing.html',
                              'https://www.auswaertiges-amt.de/de/service/visa-und-aufenthalt/2231558-2231558',
                              'Auswärtiges Amt, Germany', 'Statistics of processed Schengen and national visas,2019–2025',
                              'National D series and Schengen C/airport-transit series are separate downloadable original tables. Only national D is added by this package. Current original PDFs say Bearbeitete (processed), not issued.')
        historical = self.source('deu_fee_effective2017', 'deu_fee_effective2017.pdf',
                                 'https://phnom-penh.diplo.de/resource/blob/1275764/9ab7be08eba031cab9bead68d9c9a3e0/visagebuehren-dt-data.pdf',
                                 'German Foreign Office / Embassy Phnom Penh',
                                 'Visumgebühren, dated26July2017: national D75EUR from1September2017; minors37.50EUR',
                                 'Dated historical official original. National D adult75EUR effective1September2017; minors half,37.50EUR. Publicly funded scholarship families, diplomatic staff and eligible German/EU/EEA families may be exempt. Schengen child discounts are a separate rule, not applied to national D.')
        law = self.source('deu_residence_ordinance', 'deu_residence_ordinance.html',
                          'https://www.gesetze-im-internet.de/aufenthv/BJNR294510004.html',
                          'German Federal Ministry of Justice / Federal Office of Justice',
                          'Aufenthaltsverordnung: §§46,49,50,52–54 visa fees and exemptions',
                          'Current consolidated law cross-check: §46(2)(1) national visa75EUR; §50 minors half; §52 exemptions, §53 discretionary reductions, §54 international agreements. Historical application is anchored by the dated2017 official fee sheet and2022 parliamentary answer.')
        parliamentary = self.source('deu_fee2022_parliament', 'deu_national_fee2022.pdf',
                                    'https://dserver.bundestag.de/btd/20/034/2003429.pdf',
                                    'Deutscher Bundestag / Federal Government',
                                    'Drucksache20/3429,2022: national visa application75EUR under§46(2)(1)',
                                    'Federal Government answer separates expedited skilled-worker procedure411EUR from national visa75EUR. Only visa fee used;411EUR, translations and private services excluded.')
        current = self.source('deu_fee_current', 'deu_visa_fee_exemptions.html',
                              'https://www.auswaertiges-amt.de/de/service/visa-und-aufenthalt/visabestimmungen-allgemein',
                              'Auswärtiges Amt, Germany', 'General visa fee rules: national75EUR, minors37.50EUR and exemptions',
                              'Current official cross-check, not a historical census of waiver incidence; no observed age or paid/exempt share attached to processed-purpose statistics.')
        hist_text = '\n'.join(p.extract_text() for p in PdfReader(RAW / 'deu_fee_effective2017.pdf').pages)
        assert '26.07.2017' in hist_text and '01.09.2017' in hist_text and '75 Euro' in hist_text
        assert '37,50' in hist_text and 'für nationale Visa' in hist_text and 'Stipendium' in hist_text
        law_text = BeautifulSoup((RAW / 'deu_residence_ordinance.html').read_bytes(), 'html.parser').get_text(' ', strip=True)
        assert 'für die Erteilung eines nationalen Visums' in law_text and '75 Euro' in law_text
        assert 'Minderjähriger' in law_text and 'Befreiungen und Ermäßigungen' in law_text
        parliament_text = '\n'.join(p.extract_text() for p in PdfReader(RAW / 'deu_national_fee2022.pdf').pages)
        assert '75 Euro' in parliament_text and '411 Euro' in parliament_text
        current_text = BeautifulSoup((RAW / 'deu_visa_fee_exemptions.html').read_bytes(), 'html.parser').get_text(' ', strip=True)
        assert '37,50 Euro' in current_text and '75 Euro' in current_text
        for typ, amount, age, condition in [
            ('national_d_adult', 75, 'adult18plus', 'Standard national D fee; statutory exemptions and international agreements override'),
            ('national_d_minor', 37.5, 'minor_under18', 'Half standard national D fee; statutory exemptions override'),
            ('national_d_exempt', 0, 'eligible_categories', 'Public scholarship/diplomatic/eligible German-EU-EEA family and treaty exemptions; share unobserved'),
        ]:
            self.fees.append(dict(fee_id='evx_deu_' + typ, destination='DEU', visa_type=typ,
                                  visa_group='other', amount=amount, currency='EUR', effective_from='2017-09-01',
                                  effective_to=None, age_scope=age, charge_basis='national_D_visa_application',
                                  source_id=historical, source_ids=[historical, law, parliamentary, current],
                                  source_locator='Dated26July2017 fee sheet pp1–2; AufenthV§46(2)(1),§50,§52–54; Bundestag20/3429',
                                  mandatory=True, government_fee=True, fee_condition=condition,
                                  historical_validity='dated2017 effective rule with2022 andcurrent corroboration',
                                  notes='历史费率锚定2017年9月1日；每年减免发生率未观测。此费率并不证明所有处理事件收取全额。'))
        de = gettext.translation('iso3166-1', pycountry.LOCALES_DIR, languages=['de'], fallback=True).gettext
        host_codes = {de(getattr(c, k)): c.alpha_3 for c in pycountry.countries
                      for k in ('name', 'official_name', 'common_name') if getattr(c, k, None)}
        host_codes.update({'Côte d’Ivoire':'CIV', 'Großbritannien':'GBR', 'Korea':'KOR', 'Korea, DVR':'PRK',
                           'Kosovo':'XKX', 'Palästinensische Gebiete':'PSE', 'USA':'USA', 'VAE':'ARE',
                           'VR China':'CHN', 'Weißrussland':'BLR'})
        expected = {2019:384829, 2020:231020, 2021:349689, 2022:444154, 2023:452102, 2024:485022, 2025:480864}
        for year in range(2019, 2026):
            sid = self.source(f'deu_national{year}', f'deu_national{year}.pdf', urls[year],
                              'Auswärtiges Amt, Germany', f'Bearbeitete nationale Visa{year},12residence purposes by consular mission',
                              'Official processed national D visa events, not grants, received applications or paid applicants. Land/Gebiet is mission location, not payer nationality. All12purpose columns are disjoint; Gesamt is their total. National D excludes Schengen C/airport transit.2022 printed date13.01.2022 is inconsistent with a completed2022 reporting year; retained as source error.')
            reader = PdfReader(RAW / f'deu_national{year}.pdf')
            details, total = [], None
            for pi, page in enumerate(reader.pages, 1):
                text = page.extract_text(extraction_mode='layout')
                assert f'Bearbeitete nationale Visa {year}' in text
                (OUT / f'deu_national{year}_p{pi}_layout.txt').write_text(text)
                for li, line in enumerate(text.splitlines(), 1):
                    cols = re.split(r'\s{2,}', line.strip())
                    nums = []
                    while cols and re.fullmatch(r'[\d.]+', cols[-1]):
                        nums.insert(0, int(cols.pop().replace('.', '')))
                    if not nums:
                        continue
                    assert len(nums) == 13 and sum(nums[:-1]) == nums[-1], (year, pi, line)
                    row = dict(page=pi, line=li, labels=cols, values=nums)
                    if cols[0].startswith('Gesamt'):
                        assert total is None
                        total = row
                    else:
                        assert len(cols) == 2, (year, row)
                        details.append(row)
            assert total is not None and total['values'][-1] == expected[year]
            assert all(sum(r['values'][j] for r in details) == total['values'][j] for j in range(13))
            for ri, row in enumerate(details):
                raw_host, mission = row['labels']
                host = host_codes[raw_host]
                if host == 'CHN' and mission == 'Hongkong':
                    host = 'HKG'
                if raw_host == 'Kongo' and mission == 'Kinshasa':
                    host = 'COD'
                post_code = 'POST:' + hashlib.sha256((raw_host+'|'+mission).encode()).hexdigest()[:12]
                post_label = name(host) + ' · ' + mission
                for j, (typ, label, raw_label, group) in enumerate(DEU_PURPOSES + [('all_national_d','全部长期签证','Gesamt','other')]):
                    self.observation(f'deu_d_{year}_post{ri}_{typ}', year, 'national_visa_applications_processed',
                                     'processed_visa_events', sid,
                                     f'PDF p{row["page"]}; table row Land/Gebiet={raw_host}; Auslandsvertretung={mission}; column{j+1}:{raw_label}',
                                     destination='DEU', value=row['values'][j], lower=row['values'][j], upper=row['values'][j],
                                     nationality='UNK', origin=post_code, origin_name=post_label,
                                     origin_display_name=post_label, raw_origin_label=raw_host+' · '+mission,
                                     origin_basis='consular_post_location', source_bucket_parent=host,
                                     consulate_country=host, original_consulate_country=raw_host, consular_post=mission,
                                     visa_type='national_d_' + typ, visa_group=group, raw_metric='Bearbeitete nationale Visa / ' + raw_label,
                                     observation_domain='visa_activity', context_only=True,
                                     aggregation_role='consular_post_component',
                                     series_id=f'deu_national_d_{typ}_consular', series_label='长期签证已处理 · ' + label + '（使领馆）',
                                     application_stage='processed', visa_regime='national_D',
                                     notes='领事处理地口径；不是付款国籍或普通国民出境量。Bearbeitete是已处理事件，不等同签发、当年受理或已付款申请。逐行12用途合计与总栏、所有使领馆合计与全球栏均精确对账。')
            purpose_oids = []
            for j, (typ, label, raw_label, group) in enumerate(DEU_PURPOSES + [('all_national_d','全部长期签证','Gesamt','other')]):
                quantity = total['values'][j]
                oid = self.observation(f'deu_d_{year}_world_{typ}', year, 'national_visa_applications_processed',
                                       'processed_visa_events', sid,
                                       f'PDF p{total["page"]}; Gesamt weltweit row; column{j+1}:{raw_label}',
                                       destination='DEU', value=quantity, lower=quantity, upper=quantity,
                                       nationality='UNK', origin='WORLD', origin_basis='all_consular_posts',
                                       visa_type='national_d_' + typ, visa_group=group,
                                       raw_metric='Bearbeitete nationale Visa / ' + raw_label,
                                       observation_domain='visa_activity', context_only=True,
                                       aggregation_role='country_total', series_id=f'deu_national_d_{typ}_annual',
                                       series_label='长期签证已处理 · ' + label,
                                       application_stage='processed', visa_regime='national_D',
                                       notes='国家长期D签证处理队列；与既有申根C/机场过境短期签证互斥。年份是处理年份，不是付款年份；全球合计不作国籍分配。')
                if typ == 'all_national_d':
                    continue
                purpose_oids.append(oid)
                benchmark = quantity * 75
                params = dict(benchmark_only=True, actual_receipts_observed=False,
                              paid_quantity_observed=False, observed_application_quantity=False,
                              processed_event_count=quantity, full_adult_standard_fee_EUR=75,
                              legal_minor_fee_EUR=37.5, fee_effective_from='2017-09-01',
                              effective_fee_multiplier_center=1, effective_fee_multiplier_range=[0,1],
                              waiver_minor_composition_observed=False, nationality_allocation='none',
                              count_metric='national_visa_applications_processed', visa_regime='national_D',
                              excludes=['Schengen_C', 'airport_transit_A', '411EUR_accelerated_skilled_worker_procedure',
                                        'residence_permit_after_entry', 'private_services'],
                              range_method='同年处理队列×成人全额75欧元标价基准；未知儿童、免收及其他减费令有效费乘数保留0–100%；共同乘数情景，非当年现金收入范围或置信区间')
                note = ('德国国家长期D签证已处理队列×全额成人75欧元的标准费规模基准；含12个互斥用途，'+label+
                        '为该行。未按未成年人37.50欧元及免收发生率修正，中心不是预期实收。0–100%乘数表示这些结构未知；处理年不是付款年。使领馆地不能当国籍，付款方保留UNK。与申根C及机场过境A独立。')
                self.flows.append(dict(id=f'evx_deu_{year}_national_d_{typ}_standard_value', payer='UNK', receiver='DEU', year=year,
                                       visa_group=group, visa_type='national_d_' + typ,
                                       visa_label='长期D · ' + label + ' · 全额标准费值',
                                       category_detail_status='unclassified' if typ == 'unassigned_purposes' else 'classified',
                                       amount=benchmark, lower=0, upper=benchmark, currency='EUR', quantity=quantity,
                                       quantity_basis='observed_processed_national_visa_cohort_standard_fee_benchmark',
                                       source_ids=[sid,historical,law,parliamentary,current], observation_ids=[oid],
                                       method_id='evx_deu_national_d_processed_cohort_standard_fee',
                                       model_status='processed_cohort_full_standard_fee_benchmark',
                                       calculation_type='conditional_standard_tariff_value', origin_basis='unallocated',
                                       period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year_cohort',
                                       period_label=f'{year}处理队列', notes=note, parameters=params))
            full = expected[year] * 75
            self.ranges.append(dict(receiver='DEU', year=year, amount=full, lower=0, upper=full, currency='EUR',
                                    visa_scope='national_D_only', component_method_id='evx_deu_national_d_processed_cohort_standard_fee',
                                    range_method='长期D处理队列全额成人标价基准；所有用途同一有效费乘数0–1；与Schengen C/ATV费用控制分别作为互斥分项相加'))
            children = total['values'][2]
            self.deu_scenarios.append(dict(destination='DEU',year=year, currency='EUR',
                                           baseline_full_adult_standard_fee_value=full,
                                           known_child_reunification_events=children,
                                           child_reunification_at_half_fee_no_other_adjustment=full-children*37.5,
                                           scenario_only=True, included_in_main_money_ledger=False,
                                           formula='total_processed*75 - child_reunification_processed*(75-37.5)',
                                           limitations='仅把已知子女团聚列按儿童半价，其余全部仍用成人全价；其他类别儿童、法定或人道免收未知。这是单因素情景，不是更窄的实收区间。',
                                           source_ids=[sid,historical,law]))
            self.germany_checks.append(dict(year=year,consular_rows=len(details),purpose_columns=12,
                                             all_row_sums_equal_total=True,all_column_sums_equal_worldwide=True,
                                             worldwide_processed=expected[year],full_standard_fee_value_EUR=full,
                                             exact_metric='Bearbeitete nationale Visa',
                                             printed_date_conflict='13.01.2022 printed for completed2022 table; date not used as period' if year==2022 else None))
        self.models.append(dict(model_id='evx_deu_national_d_processed_cohort_standard_fee',destination='DEU',
                                years=list(range(2019,2026)),status='processed_cohort_full_adult_standard_fee_benchmark',
                                formula='12 mutually exclusive national D processed-purpose counts ×75EUR; joint effective-fee factor0–1',
                                target='processed-cohort full-adult standard-fee value, not expected government cash revenue',
                                limitations=['处理年队列，不是当年受理、签发或实际已付费人数。',
                                             '75欧元为成人全价参照；未成年人37.50欧元、法定与个案免收份额未知。',
                                             '中心等于全额成人标价基准，不是对实收的无偏估计或预期；0–100%为条件情景。',
                                             '分列使领馆为处理地点，不代表付款国籍；全部费用边保留UNK。',
                                             '长期D范围与已有申根C／机场过境签证互斥；411欧元加急工作程序和入境后许可费排除。']))

    def exchange_rates(self):
        fx = json.loads((ROOT / 'data/research/history/fx.json').read_text())
        self.fx = [r for r in fx if r['currency'] == 'EUR' and r['year'] in range(2016, 2024)]
        fx_current = json.loads((ROOT / 'data/research/schengen_fx/fx.json').read_text())
        self.fx += [r for r in fx_current if r['currency'] == 'EUR' and r['year'] in (2024,2025)]
        source_ids = {r['source_id'] for r in self.fx}
        sources = json.loads((ROOT / 'data/research/history/sources.json').read_text())
        sources += json.loads((ROOT / 'data/research/schengen_fx/sources.json').read_text())
        self.sources.extend(s for s in sources if s['source_id'] in source_ids)
        assert len(self.fx) == 10 and {r['source_id'] for r in self.fx} <= {s['source_id'] for s in self.sources}

    def finish(self):
        sids = {s['source_id'] for s in self.sources}
        oids = {o['observation_id'] for o in self.obs}
        assert len(sids) == len(self.sources) and len(oids) == len(self.obs)
        assert len({f['id'] for f in self.flows}) == len(self.flows)
        assert all(f['payer'] == 'UNK' for f in self.flows)
        assert all(f['quantity'] is None for f in self.flows if f['receiver'] == 'IRL')
        assert all(f['quantity_basis'] == 'observed_processed_national_visa_cohort_standard_fee_benchmark'
                   and f['visa_type'].startswith('national_d_') and f['parameters']['benchmark_only']
                   for f in self.flows if f['receiver'] == 'DEU')
        for f in self.flows:
            assert set(f['source_ids']) <= sids and set(f['observation_ids']) <= oids
            assert f['lower'] <= f['amount'] <= f['upper']
        assert all(o['source_id'] in sids for o in self.obs)
        assert not any(f['year'] == 2023 and f['receiver'] == 'IRL' for f in self.flows)
        assert len(self.native_country) == 10380
        assert sum(o['period_type'] == 'calendar_month' for o in self.obs) == 702
        assert all(o.get('eligible_money_ledger') is False for o in self.obs if o.get('observation_domain') == 'visa_activity')
        assert all(o.get('is_partial') and o['period_end'] == '2026-09-30'
                   for o in self.obs if o['year'] == 2026 and o['period_type'] != 'calendar_month')
        scopes = {(f['receiver'], f['year']) for f in self.flows}
        overlap, checked, disjoint_existing = [], [], []
        for path in sorted(EST.parent.glob('*_flows.json')):
            if path == EST:
                continue
            checked.append(str(path.relative_to(ROOT)))
            for f in json.loads(path.read_text()).get('flows', []):
                if (f.get('receiver'), f.get('year')) in scopes:
                    is_schengen = ('sch' in f.get('method_id', '').lower()
                                   or '申根' in f.get('visa_type', '')
                                   or 'schengen' in f.get('visa_type', '').lower())
                    if f.get('receiver') == 'DEU' and f.get('visa_group') == 'visitor' and is_schengen:
                        disjoint_existing.append((path.name, f.get('id')))
                    else:
                        overlap.append((path.name, f.get('id')))
        assert not overlap, overlap
        coverage = []
        for year in range(2016, 2027):
            for group in GROUPS:
                ff = [f for f in self.flows if f['receiver'] == 'IRL' and f['year'] == year and f['visa_group'] == group]
                act = year >= 2017 and group == 'other'
                coverage.append(dict(code='IRL', destination='IRL', name='爱尔兰', region='欧洲', year=year,
                                     visa_group=group, status='amount_known' if ff else 'quantity_context' if act else 'not_found',
                                     fee_known=False, quantity_known=False, quantity_context_known=act,
                                     amount_known=bool(ff), amount_modeled=False, nationality_known=act,
                                     category_detail_status='unclassified_aggregate' if ff or act else 'no_classified_observation',
                                     source_ids=list(dict.fromkeys(s for f in ff for s in f['source_ids'])) +
                                                (['game_irl_nationalities', 'evx_irl_monthly_activity'] if act else []),
                                     notes='原始司法部签证收款包括再入境，事件表仅作入境签证背景；2023收款含AWS未计账，2024/25费用由既有包覆盖，2026仅1–9月。' if group == 'other' else
                                           '短长期不是本用途拆分；未按时长臆分旅游、学习、工作或家属。',
                                     searched_as_of=ASOF))
        for year in range(2019,2026):
            for group in GROUPS:
                ff = [f for f in self.flows if f['receiver'] == 'DEU' and f['year'] == year and f['visa_group'] == group]
                coverage.append(dict(code='DEU',destination='DEU',name='德国',region='欧洲',year=year,
                                     visa_group=group,status='amount_modeled' if ff else 'not_applicable',
                                     fee_known=bool(ff),quantity_known=bool(ff),quantity_context_known=bool(ff),
                                     amount_known=False,amount_modeled=bool(ff),nationality_known=False,
                                     category_detail_status='classified_aggregate' if ff else 'no_classified_observation',
                                     source_ids=list(dict.fromkeys(s for f in ff for s in f['source_ids'])),
                                     notes='长期D处理队列全额成人标价基准；不是当年收款或已缴费申请量。儿童及免收结构未知，0–100%共同乘数情景。逐使领馆活动背景不作国籍分配。' if ff else
                                           '本包只补国家长期D；短期申根C/机场过境由既有包覆盖，不重复。',
                                     searched_as_of=ASOF))
        counts = Counter(o['observation_domain'] for o in self.obs)
        checks = dict(as_of=ASOF, sources=len(self.sources), observations=len(self.obs), fees=len(self.fees), fx=len(self.fx),
                      flows=len(self.flows), models=len(self.models), coverage_rows=len(coverage),
                      monetary_receivers=['DEU','IRL'], money_years=sorted({f['year'] for f in self.flows}),
                      ireland_actual_receipts_EUR=sum(f['amount'] for f in self.flows if f['receiver']=='IRL'),
                      germany_full_standard_fee_values_EUR={str(y):sum(f['amount'] for f in self.flows if f['receiver']=='DEU' and f['year']==y) for y in range(2019,2026)},
                      germany_processed_national_d_reconciliations=self.germany_checks,
                      observation_domains=dict(counts), nationality_native_cells=len(self.native_country),
                      nationality_new_observations=sum(o.get('aggregation_role') in ('nationality_part','source_bucket_component') for o in self.obs),
                      nationality_source_buckets_preserved=sum(o.get('aggregation_role')=='source_bucket_component' for o in self.obs),
                      monthly_observations=702, monthly_nationality_reconciliations=len(self.reconciliations),
                      all_reconciliation_intervals_overlap=all(r['intervals_intersect'] for r in self.reconciliations),
                      suppression_current_range=[1,5], older_metadata_range=[1,3], suppression_conflict_preserved=True,
                      partial_period_2026='2026-01-01/2026-09-30', no_partial_annualization=True,
                      no_country_allocation_from_entry_only_counts=True, no_claimed_cash_application_denominator=True,
                      mixed_2023_aws_excluded=True, current_comparative_columns_asserted=True,
                      no_duplicate_existing_fee_scope=True, overlap_checked_packages=checked,
                      disjoint_existing_deu_schengen_edges=len(disjoint_existing),
                      germany_processed_not_issued_or_paid=True, german_D_never_allocated_by_post_nationality=True,
                      germany_fee_2017_effective_document_verified=True, germany_current_law_and2022_fee_corroborate=True,
                      no_claimed_germany_actual_receipts=True,
                      all_source_and_observation_ids_resolve=True, one_china_names_canonical=True,
                      zero_events_do_not_mean_zero_fees=True)
        for filename, obj in [('sources.json', self.sources), ('observations.json', self.obs),
                              ('fee_rules.json', self.fees), ('fx.json', self.fx), ('coverage.json', coverage),
                              ('checks.json', checks), ('ireland_nationality_cells.json', self.native_country),
                              ('ireland_monthly_nationality_reconciliation.json', self.reconciliations),
                              ('ireland_nationality_mapping.json', self.country_mapping),
                              ('germany_national_d_reconciliation.json',self.germany_checks),
                              ('germany_national_d_separate_scenarios.json',self.deu_scenarios),
                              ('search_log.json',[
                                  dict(destination='IRL',result='2016–22 Visa fees realised;2023AWS mixture context only;2017–Sep2026 nationality/monthly activity retained with suppression',searched_at=ASOF),
                                  dict(destination='DEU',result='2019–25 official national D processed-purpose tables; dated2017 effective75/37.5 fee and exemptions; processed-cohort standard-fee benchmark distinct from actual receipts and SchengenC/ATV',searched_at=ASOF),
                                  dict(destination='DEU',result='Official2019 WD3-113-19 short paper swaps25and75 in issuance/extension prose. Conflicts with dated2017AA sheet,2022government answer and current law; not used for tariff. Frozen original retained in raw.',searched_at=ASOF),
                                  dict(destination='BIH',result='2022/23/24 migration-profile PDF links located; old routes now redirect to new homepage or404 and direct host times out. No PDF original retrieved, no historical tables or fees imported from search snippets.',searched_at=ASOF),
                              ])]:
            write(filename, obj)
        EST.write_text(json.dumps(dict(package='europe_expansion_v4', as_of=ASOF, flows=self.flows,
                                       models=self.models, destination_ranges=self.ranges, subtotals=[],
                                       scope='Ireland Vote24 Justice realised visa receipts2016–22; entry-visa activity2017–Sep2026 context;2023AWS excluded; Germany national D processed-cohort full-adult standard-fee benchmarks2019–25, disjoint from SchengenC/ATV'),
                                   ensure_ascii=False, indent=2) + '\n')
        (OUT / 'README.md').write_text(f'''# 欧洲历史收款、长期签证及活动扩展

更新{ASOF}。离线运行 `.research-venv/bin/python scripts/research_europe_expansion_v4.py`，从冻结原件重新提取。

本包登记{len(self.sources)}个来源（包括复用的同一CSV和历史汇率原件）、{len(self.obs):,}条新观察、{len(self.flows)}条费用分项、2个模型。爱尔兰2016—2022司法部签证费实收共€{sum(f['amount'] for f in self.flows if f['receiver']=='IRL')/1e6:.3f}百万；德国2019—2025长期D签证另按全额标准费计规模基准。付款来源未知，费用边均保留UNK。原报告千欧元精度的上下半单位为±€500，表示取整范围。

## 实收与事件

2016/2017/2018/2019/2020/2021/2022 Visa fees Realised分别为€8.741/8.300/9.552/9.847/3.082/3.019/7.913百万。每个原件实际列及前期比较列均核对；预算列、登记、公民身份、护照、递延和应计余额未计入。Vote24是司法部收款账户，尚未证明覆盖所有海外使领馆留存款。

2017解释明确包含入境及再入境签证。国籍数据是入境签证事件，因此不把它作为整笔收款的国籍分配键或每申请人费用分母。2020的Atypical Worker Scheme在Miscellaneous receipts解释；2023 Visa fees解释又包含Atypical Working Scheme，€11.544百万留财务背景、没有计入主费用总账。

国籍原表2017—2026共10,380格全部保存在`ireland_nationality_cells.json`，并转为保留短／长期持续期的活动观察。2024/25的2,076格与既有费用研究共享同一原始单元格，`reused_source_observation_ids`关联旧观察；这是活动上下文的重新表达，没有新建费用边或重复相加的事件。月度2017—2026年9月共702格；另有60条短长期年度合计及30条全部入境签证年度合计。2026全部年度观察止于9月30日，不年化、未到月份不作0。

Received指完成付款后受理；Granted含初审或上诉获批；Refused是初审拒签。三者为各年发生的事件，不能用当年拒签／受理解释同一批申请的拒签概率；事件也不是独立人数。短期／长期不能直接等同旅游／工作／学习。

## 抑制与对账

当前资源描述将`*`定义为1—5，旧嵌入Notes写1—3，两种原文均归档。本包按当前1—5保留lower/upper，value为空，不把抑制格改成0或精确3。全部60个持续期×状态×年度的月度合计区间与国籍合计区间相交；原始格不为贴合总数而调整。对账表单独保存。

## 德国长期D签证

2019—2025原件全部明确`Bearbeitete nationale Visa`，即已处理国家长期D签证事件，依次384,829／231,020／349,689／444,154／452,102／485,022／480,864。每年12个用途列互斥；逐使领馆行之和与全球总栏、每行用途之和与总数完全相等。2022原件将日期写成13.01.2022，与完整2022报告年冲突，原字保留，处理期间仍为表标题的2022年。

用途保留配偶／父母／子女／其他家庭团聚、学习准备、语言学校、工作研究实践、犹太移民、德裔迁入、人道安置、其他目的、未分配12列，并映射家属／学习／工作／其他。使领馆所在地只表示处理地点，不能解释为付款国籍；中国香港和中国台湾处理地按产品标准名显示。

2017年7月26日外交部原件明确成人D签证自2017年9月1日起€75、未成年人€37.50，以及公费奖学金、外交人员、合资格德国／欧盟／欧洲经济区家庭等免收。2022政府答复及现行《居留条例》交叉印证。2019年议会研究简报把25和75欧元的签发／延期文字对调，该简报未用作费率；原件留raw可追踪。

主模型中心是**处理队列×成人全额€75的标价规模基准**，每年分12个用途共84条，中心不是预期实收。未知儿童及减免结构对应0—100%共同有效费乘数；这是条件情景，不是统计置信区间或当年现金收入范围。独立情景文件只展示把已知子女团聚列按半价的影响，未再次计入总账。申请缴费与处理可跨年；本模型只为同年处理队列标价，没有把处理数称付费申请人数。

国家长期D与既有申根C／机场过境范围互斥。€411加急工作程序、入境后居留许可、翻译及私人服务未计。2024和2025的全额标准费值分别为€36.377百万、€36.065百万。

{JURISDICTION_NOTE}
''')
        print(json.dumps(checks, ensure_ascii=False))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    r = Research()
    r.ireland_cash()
    r.ireland_activity()
    r.germany_national()
    r.exchange_rates()
    r.finish()


if __name__ == '__main__':
    main()
