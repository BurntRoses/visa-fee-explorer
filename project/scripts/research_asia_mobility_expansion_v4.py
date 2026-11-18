#!/usr/bin/env python3
"""Asia travel context and India's historical visa-receipt calendar bridges.

Rebuilds only from frozen official originals. Travel events, source-specific
territorial buckets, fiscal receipts and calendar estimates stay distinct.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
import logging
from pathlib import Path
import re

import pycountry
from pypdf import PdfReader

logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/asia_mobility_expansion_v4'
OUT = ROOT / 'data/research/asia_mobility_expansion_v4'
EST = ROOT / 'data/estimates/asia_mobility_expansion_v4_flows.json'
ASOF = '2026-11-17'

ALIASES = {
    'U. S. A': 'USA', 'U.S.A': 'USA', 'U.K.': 'GBR', 'U.A.E.': 'ARE',
    'UAE': 'ARE', 'Utd Arab Emirates': 'ARE', 'Russian Fed.': 'RUS',
    'Czech Rep.': 'CZE', 'Rep. of Korea': 'KOR', 'Korea (ROK)': 'KOR',
    'Korea (DPRK)': 'PRK', 'Yemen Arab': 'YEM', 'Nether lands': 'NLD',
    'Switzer land': 'CHE', 'Hong Kong (China)': 'HKG', 'Macao (China)': 'MAC',
    'Taiwan (PR. of China)': 'TWN', 'Chinese Taipei': 'TWN', 'Turkiye': 'TUR',
    'Centr. African Rep.': 'CAF', "Cote d'lvoire": 'CIV',
    'Dem. Rep. Congo': 'COD', 'Reunion': 'REU', 'Sao Tome & Principe': 'STP',
    'Sao Tome &': 'STP', 'Antigua & Barbuda': 'ATG', 'Brit. Virgin Islands': 'VGB',
    'Dominican Rep.': 'DOM', 'St. Kitts & Nevis': 'KNA', 'St. Vincent & Gren.': 'VCT',
    'Trinidad & Tobago': 'TTO', 'Turks & Caicos': 'TCA', 'Micronesia FSM': 'FSM',
    'N. Mariana Islands': 'MNP', 'Brunei': 'BRN', 'Rep. Moldova': 'MDA',
    'Bosnia & Herzg.': 'BIH', 'Vatican City': 'VAT', 'Palestine': 'PSE',
    'Curacao': 'CUW', 'US Virgin Islands': 'VIR', 'Laos': 'LAO',
    'United States of': 'USA', 'United States of America': 'USA',
    'Turkey': 'TUR', 'South Korea': 'KOR', 'Uae': 'ARE', 'Russia': 'RUS',
}
REGIONS = {
    'Africa', 'North Africa', 'Sub-Saharan', 'Sub-Saharan Africa', 'Americas',
    'Caribbean', 'Central America', 'North America', 'South America',
    'Asia and the', 'North-East Asia', 'Oceania', 'South Asia', 'South-East Asia',
    'Europe', 'Central/Eastern', 'Northern Europe', 'Southern/Medit.',
    'Western Europe', 'Middle East', 'Asia Total', 'Europe Total',
}
OLD_REGIONS = {
    'NORTH AMERICA', 'CENTRAL AND SOUTH AMERICA', 'WESTERN EUROPE', 'EASTERN EUROPE',
    'AFRICA', 'MIDDLE EAST', 'SOUTH ASIA', 'SOUTH EAST ASIA', 'EAST ASIA', 'AUSTRALASIA',
}
ZH = {'CHN': '中国大陆', 'HKG': '中国香港', 'MAC': '中国澳门', 'TWN': '中国台湾',
      'CHN-XZ-SOURCE': '中国西藏（原表分列）', 'ANT-SOURCE': '原荷属安的列斯（原表标签）'}


def slug(x):
    return re.sub(r'[^a-z0-9]+', '_', x.lower()).strip('_')


def number(s):
    return None if s == '-' else int(s.replace(',', ''))


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = list(dict.fromkeys(k for r in obj for k in r))
        with (OUT / name.replace('.json', '.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, keys)
            w.writeheader()
            w.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                         for k, v in r.items()} for r in obj)


class Research:
    def __init__(self):
        self.sources, self.obs, self.checks, self.flows, self.fx = [], [], [], [], []
        self.models, self.ranges, self.revisions = [], [], []
        self.readers = {}

    def source(self, sid, filename, url, publisher, title, expected_hash=None, notes='', outside=False):
        path = ROOT / filename if outside else RAW / filename
        data = path.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        if expected_hash:
            assert h == expected_hash, (filename, h)
        assert len(data) > 100
        if path.suffix == '.pdf':
            assert data.startswith(b'%PDF')
            self.readers[sid] = PdfReader(path)
        self.sources.append(dict(source_id=sid, local_path=str(path.relative_to(ROOT)),
                                 path=str(path.relative_to(ROOT)), url=url, publisher=publisher,
                                 title=title, retrieved_at=ASOF, source_quality='official_original',
                                 archive_kind='original_api_response' if path.suffix == '.json' else 'original_document',
                                 sha256=h, bytes=len(data), notes=notes))
        return sid

    def page(self, sid, page):
        t = self.readers[sid].pages[page-1].extract_text(extraction_mode='layout')
        (OUT / f'{sid}_pdf_p{page}_layout.txt').write_text(t)
        return t

    def classify(self, name, region=''):
        if name == 'Grand Total':
            return 'WORLD', 'country_total'
        if name in REGIONS or name in {'Asia Total', 'Europe Total', 'Total'}:
            return 'REGION:' + slug(region if name == 'Total' else name), 'region_subtotal'
        if name.startswith(('Others Not', 'Not Classified', 'Not classified')):
            return 'UNK:unclassified', 'residual_component'
        if name.startswith(('Others', 'Negara-negara lain')):
            return 'UNK:' + slug(region), 'residual_component'
        if name == 'Tibet':
            return 'CHN-XZ-SOURCE', 'subnational_source_bucket'
        if name == 'Neth. Antilles':
            return 'ANT-SOURCE', 'historical_source_bucket'
        aliases = {k.casefold(): v for k, v in ALIASES.items()}
        if name.casefold() in aliases:
            return aliases[name.casefold()], 'country_component'
        try:
            return pycountry.countries.lookup(name).alpha_3, 'country_component'
        except LookupError:
            raise AssertionError(('unmapped source label', name))

    def rows(self, sid, pages, cols, start_marker=None):
        region = ''
        answer = []
        active = start_marker is None
        token = r'(?:\d[\d,]*|-)'
        pattern = re.compile(r'^\s*([A-Za-z][^0-9]*?)\s+(' + token +
                             (r'\s+' + token) * (cols-1) + r')(?=\s|$)')
        for page in pages:
            for line_no, line in enumerate(self.page(sid, page).splitlines(), 1):
                clean = re.sub(r'\s+', ' ', line).strip()
                if not active and start_marker in clean:
                    active = True
                if not active:
                    continue
                if clean in OLD_REGIONS:
                    region = clean
                    continue
                m = pattern.match(line)
                if not m:
                    continue
                name = re.sub(r'\s+', ' ', m[1]).strip()
                if name in {'Nationality', 'Country', 'Country of', 'Year'}:
                    continue
                raw_values = m[2].split()
                code, role = self.classify(name, region)
                if role == 'region_subtotal' and name != 'Total':
                    region = name
                answer.append(dict(name=name, code=code, role=role, region=region,
                                   values=[number(s) for s in raw_values], raw_values=raw_values,
                                   page=page, line=line_no, raw_line=line.rstrip()))
        assert active and answer, (sid, pages)
        return answer

    def context(self, sid, row, year, value, raw, direction, series, label, metric, table, **extra):
        code, role = row['code'], row['role']
        self.obs.append(dict(
            observation_id=f'amx_{series}_{year}_{slug(code)}_{slug(row["region"])}',
            source_id=sid, source_ids=[sid], source_locator=f'PDF p{row["page"]}, {table}, row {row["name"]}, column {year}, layout line {row["line"]}',
            destination='IND' if sid.startswith('amx_ind') else 'MYS',
            reporting_country='IND' if sid.startswith('amx_ind') else 'MYS',
            origin=code, partner_country=code, origin_name=ZH.get(code, row['name']),
            raw_origin_label=row['name'], original_name=row['name'], raw_region=row['region'],
            origin_basis='nationality' if direction == 'inbound' and sid.startswith('amx_ind') else
                         'indian_passport_and_reported_destination' if direction == 'outbound' else extra.pop('origin_basis', 'source_country_unqualified'),
            metric=metric, raw_metric=extra.pop('raw_metric', metric), value=value,
            raw_value=raw, unit='arrival_events' if direction == 'inbound' else 'departure_events',
            period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
            year=year, calculation_type='published_statistical_series', observation_domain='mobility',
            context_only=True, eligible_money_ledger=False, aggregation_role=role,
            flow_direction=direction, series_id=series, series_label=label,
            scope='reporting_country_all_markets' if role == 'country_total' else
                  'source_specific_statistical_bucket' if role in {'subnational_source_bucket', 'historical_source_bucket'} else 'bilateral_market_component',
            source_bucket_parent='CHN' if code == 'CHN-XZ-SOURCE' else None,
            raw_line=row['raw_line'], notes=extra.pop('notes', '') + ' 同一人多次旅行分别计次；不作为签证申请、付费或独立人数。',
            **extra))

    def balance(self, rows, years, series):
        totals = [r for r in rows if r['role'] == 'country_total']
        assert len(totals) == 1, (series, len(totals))
        parts = [r for r in rows if r['role'] not in {'country_total', 'region_subtotal'}]
        for i, year in enumerate(years):
            unknown = [r['name'] for r in parts if r['values'][i] is None]
            total = totals[0]['values'][i]
            summed = sum(r['values'][i] or 0 for r in parts)
            residual = total - summed
            expected = -4 if series == 'ind_new_inbound' and year == 2023 else 0
            assert residual == expected, (series, year, residual, expected)
            self.checks.append(dict(check=f'{series}_leaf_total_{year}', passed=residual == expected,
                                    year=year, published_total=total, sum_of_known_leaves=summed,
                                    residual=residual, source_missing_cells=unknown,
                                    reconciles_exactly=residual == 0, expected_source_residual=expected,
                                    interpretation='source arithmetic discrepancy retained' if residual else
                                    'known leaves reconcile; source dash remains missing' if unknown else 'exact reconciliation'))

    def india(self):
        old = self.source('amx_ind_comp2024', 'india_tourism_compendium_2024.pdf',
            'https://data.tourism.gov.in/mrd/Uploads/tourism_data/India%20Tourism%20Data%20Compendium%202024.pdf',
            'Ministry of Tourism / Bureau of Immigration, Government of India', 'India Tourism Data Compendium 2024',
            '4bfd2cb05314ef54efc70746de9ec84f93d93f1a2a1d329ad0048238b2a7a358',
            notes='Foreign tourist arrivals by passport nationality; Indian-national departures by destination; both count trips. PDF p176–177 definitions. Table3.2.3 title2021–2023 disagrees with actual column headings2019/2022/2023; columns govern extraction.')
        new = self.source('amx_ind_comp2025', 'india_tourism_compendium_2025.pdf',
            'https://data.tourism.gov.in/mrd/Uploads/tourism_data/India%20Tourism%20Data%20Compendium%202025_1.pdf',
            'Ministry of Tourism / Bureau of Immigration, Government of India', 'India Tourism Data Compendium 2025',
            'b7ac3e64394bf1b1a3b7afc7fbb39b4b8f83b31a229b85769aeb2b17e9012aa9',
            notes='Latest full country/territory tables2019/2023/2024; selected major inbound markets2001–2024. Source territorial labels preserved; China-related labels normalized for display. Historical table revisions preserved, not averaged.')
        self.page(old, 176)
        self.page(old, 177)
        old_in = self.rows(old, range(46,49), 5)
        old_out = self.rows(old, range(103,107), 3)
        new_in = self.rows(new, range(39,46), 3)
        new_out = self.rows(new, range(133,141), 3, start_marker='Table 3.1.5 :')
        for rows, years, label in [(old_in,list(range(2019,2024)),'ind_old_inbound'),
                                   (old_out,[2019,2022,2023],'ind_old_outbound'),
                                   (new_in,[2019,2023,2024],'ind_new_inbound'),
                                   (new_out,[2019,2023,2024],'ind_new_outbound')]:
            self.balance(rows,years,label)
        for rows, years, sid, direction, table in [
            (new_in,[2019,2023,2024],new,'inbound','Table2.1.5'),
            (new_out,[2019,2023,2024],new,'outbound','Table3.1.5'),
            (old_in,list(range(2019,2024)),old,'inbound','Table2.1.2'),
            (old_out,[2019,2022,2023],old,'outbound','Table3.2.3')]:
            for row in rows:
                for i, year in enumerate(years):
                    if sid == old and year in {2019,2023}:
                        continue
                    self.context(sid,row,year,row['values'][i],row['raw_values'][i],direction,
                                 'india_fta_nationality' if direction == 'inbound' else 'india_national_departures_destination',
                                 '印度外国游客到达（国籍）' if direction == 'inbound' else '印度公民出境（目的地）',
                                 'foreign_tourist_arrivals' if direction == 'inbound' else 'indian_nationals_departures',table,
                                 raw_metric='Foreign Tourist Arrivals (FTAs)' if direction == 'inbound' else 'Indian Nationals’ Departures (INDs)',
                                 source_edition=2025 if sid == new else 2024,
                                 notes='新版表包含源文件原有区域/辖区分类；区域总计与国家分项不相加。' if sid == new else '旧版用于补足新版未列的疫情期间年份。')
        # Fifteen major source markets have a continuous24-year series. Existing
        # country-year rows win; these rows fill genuine gaps only.
        seen={(r['series_id'],r['year'],r['origin']) for r in self.obs}
        for page,codes in [(46,['USA','BGD','GBR','AUS','CAN','MYS','LKA']),
                           (47,['DEU','FRA','SGP','NPL','JPN','RUS','ITA','THA'])]:
            hits=0
            for line_no,line in enumerate(self.page(new,page).splitlines(),1):
                tokens=line.split()
                if not tokens or not re.fullmatch(r'20\d{2}',tokens[0]): continue
                if len(tokens)!=len(codes)+1: continue
                year=int(tokens[0]); hits+=1
                for code, raw in zip(codes,tokens[1:]):
                    key=('india_fta_nationality',year,code)
                    if key in seen: continue
                    seen.add(key)
                    row=dict(code=code,role='country_component',name=pycountry.countries.get(alpha_3=code).name,
                             region='major_2024_source_markets',page=page,line=line_no,raw_line=line.rstrip())
                    self.context(new,row,year,number(raw),raw,'inbound','india_fta_nationality',
                                 '印度外国游客到达（国籍）','foreign_tourist_arrivals','Table2.1.6',source_edition=2025,
                                 notes='2024年前15大客源国历史连续序列，补足完整国籍面板未列年份；不是全世界总量。')
            assert hits==24,(page,hits)
        for direction,old_rows,new_rows,old_years in [('inbound',old_in,new_in,list(range(2019,2024))),
                                                     ('outbound',old_out,new_out,[2019,2022,2023])]:
            a={(r['code'],y):r['values'][i] for r in old_rows if r['role'] in {'country_component','country_total'}
               for i,y in enumerate(old_years) if y in {2019,2023}}
            b={(r['code'],y):r['values'][i] for r in new_rows if r['role'] in {'country_component','country_total'}
               for i,y in enumerate([2019,2023,2024]) if y in {2019,2023}}
            for key in sorted(a.keys()&b.keys()):
                if a[key]!=b[key]:
                    self.revisions.append(dict(reporting_country='IND',direction=direction,partner=key[0],year=key[1],
                                               edition2024_value=a[key],edition2025_value=b[key],difference=b[key]-a[key],
                                               selected_edition=2025,notes='保留新版披露和版本差异；不据此推断旅行行为变化。'))

    def malaysia(self):
        old=self.source('amx_mys_yearbook2024','malaysia_statistics_yearbook_2024.pdf',
            'https://www.dosm.gov.my/uploads/release-content/file_20260410164034.pdf',
            'Department of Statistics Malaysia / Tourism Malaysia','Statistics Yearbook Malaysia2024: Table15.1',
            '0cef6018734197fe420754b5440f4665d1405eb2012e3a393e3b3942b9ce135c',
            notes='PDFp252/printed170: visitors2019–24 split into tourists and excursionists;15 selected country rows plus other countries. Headline unit Number of persons is normalized to arrival events because this is an arrivals series, not unique people.')
        new=self.source('amx_mys_handbook2026','malaysia_statistical_handbook_2026.pdf',
            'https://www.dosm.gov.my/uploads/release-content/file_20260903105212.pdf',
            'Department of Statistics Malaysia / Malaysian Tourism Promotion Board','Malaysia Statistical Handbook2026: Table14.1 Tourist Arrivals by Country of Residence',
            'da20e447d4ad5c54c7c1f62ef802028f395e31255641db2727761ab012306b85',
            notes='PublishedSeptember2026. PDFp155/printed122:51 residence markets+other,2019/2024/2025. Source calls tableTourist but2019/2024 cells exactly equal older Visitor series inclusive of excursionists. Declared title and metric ambiguity are both retained;2025 not silently normalized to overnight tourist arrivals.')
        t=self.page(old,252)
        years=list(range(2019,2025))
        lines=t.splitlines()
        visitors=[]
        for line_no,line in enumerate(lines,1):
            if line.strip().startswith('A4.'):
                break
            m=re.match(r'^\s*(.*?)\s+(\d[\d,]*(?:\s+\d[\d,]*){5})\s*$',line)
            if not m:continue
            name=re.sub(r'\s+',' ',m[1]).strip(); values=m[2].split()
            if name in {'Tahun','Year'}:
                continue
            if name.startswith(('Visitor arrivals','A1.')):
                row=dict(name='Grand Total',code='WORLD',role='country_total',region='',page=252,line=line_no,raw_line=line.rstrip())
                metric='visitor_arrivals';series='malaysia_visitor_arrivals';label='马来西亚访客到达（含当日往返）'
            elif name.startswith(('Tourist arrivals','A2.')):
                row=dict(name='Grand Total',code='WORLD',role='country_total',region='',page=252,line=line_no,raw_line=line.rstrip())
                metric='overnight_tourist_arrivals';series='malaysia_overnight_tourist_arrivals';label='马来西亚过夜游客到达'
            elif name.startswith(('Excursionist arrivals','A3.')):
                row=dict(name='Grand Total',code='WORLD',role='country_total',region='',page=252,line=line_no,raw_line=line.rstrip())
                metric='same_day_visitor_arrivals';series='malaysia_excursionist_arrivals';label='马来西亚当日访客到达'
            elif name and not name.startswith(('Number','Bilangan','Domestik','Antarabangsa')) and not re.match(r'^\d',name):
                if name.startswith('Negara-negara lain'):code,role='UNK','residual_component'
                else:code,role=self.classify(name)
                row=dict(name=name,code=code,role=role,region='selected_source_markets',page=252,line=line_no,raw_line=line.rstrip())
                metric='visitor_arrivals';series='malaysia_visitor_arrivals';label='马来西亚访客到达（含当日往返）'
            else:continue
            if series=='malaysia_visitor_arrivals':visitors.append(dict(row,values=[number(v) for v in values]))
            for year,raw in zip(years,values):
                self.context(old,row,year,number(raw),raw,'inbound',series,label,metric,'Table15.1',
                             origin_basis='source_country_unqualified',raw_metric=name,
                             source_metric_ambiguity=False,
                             notes='A1访客=A2过夜游客+A3当日访客；旧版未明确国家归属是国籍还是居住地，保留未限定来源国口径。')
        self.balance(visitors,years,'mys_visitor2019_2024')
        for year in years:
            d={r['metric']:r['value'] for r in self.obs if r['destination']=='MYS' and r['year']==year and r['origin']=='WORLD'}
            assert d['visitor_arrivals']==d['overnight_tourist_arrivals']+d['same_day_visitor_arrivals'],d
            self.checks.append(dict(check=f'mys_visitors_equal_tourists_plus_excursionists_{year}',passed=True))
        t=self.page(new,155)
        market=[]
        for line_no,line in enumerate(t.splitlines(),1):
            m=re.match(r'^\s*(\d{1,2})\s+([A-Z][A-Z .]+?)\s+(\d[\d,]*)\s+(\d[\d,]*)\s+(\d[\d,]*)\s',line)
            if not m:continue
            name=m[2].strip().title();raws=list(m.group(3,4,5))
            if name=='U.S.A':name='U.S.A'
            code,role=self.classify(name)
            market.append(dict(code=code,name=name,role=role,region='all_reported_residence_markets',
                               page=155,line=line_no,raw_line=line.rstrip(),values=[number(v) for v in raws],raw_values=raws))
        assert len(market)==52,len(market)
        total_line=next((i,line) for i,line in enumerate(t.splitlines(),1) if re.search(r'42,196,893\s+37,961,485\s+35,045,625',line))
        market.append(dict(code='WORLD',name='Grand Total',role='country_total',region='',page=155,
                           line=total_line[0],raw_line=total_line[1],values=[42196893,37961485,35045625],
                           raw_values=['42,196,893','37,961,485','35,045,625']))
        self.balance(market,[2025,2024,2019],'mys_residence_arrivals2025')
        # Use only the new2025 column in the context series. Duplicate2019/2024
        # figures remain in the crosswalk rather than double counting the series.
        older={(r['origin'],r['year']):r['value'] for r in self.obs if r['series_id']=='malaysia_visitor_arrivals'}
        for row in market:
            for i,year in [(1,2024),(2,2019)]:
                if (row['code'],year) in older and row['role']!='residual_component':
                    assert older[(row['code'],year)]==row['values'][i],row
            self.context(new,row,2025,row['values'][0],row['raw_values'][0],'inbound',
                         'malaysia_reported_residence_arrivals','马来西亚按居住地到达（原表口径待统一）',
                         'reported_arrivals_by_residence','Table14.1',origin_basis='place_of_residence',
                         raw_metric='Tourist Arrivals by Country of Residence',source_metric_ambiguity=True,
                         harmonized_metric=None,
                         notes='原表标题称Tourist，2019/2024对照列却与旧版含当日访客的Visitor数完全相同。2025按原表到达量保存，不能解释为过夜游客或签证量。')

    def india_money(self):
        sid=self.source('amx_ind_mea2024','data/raw/india/mea2024_lower.pdf',
            'https://www.mea.gov.in/images/CPV/140725MEAAnnualReport2024English.pdf',
            'Ministry of External Affairs, Government of India','Annual Report2024: Finance & Budget, Visa receipts',
            '93831f1d7a8c53aa8ecba37a54e90d3da90fb4b00455eac641f53ce3dcf2d3e0',outside=True,
            notes='PDFp308/printed307. Visa separately disclosed from Passport and Others. Existing original reused, not re-downloaded. Amounts in croreINR;0.01crore source precision.')
        t=self.page(sid,308)
        values=[float(v.replace(',','')) for v in re.findall(r'\bVisa\s+(\d[\d,]*\.\d{2})',t)]
        assert values==[1792.11,24.85,316.93,1440.10,1396.91],values
        receipts={end:round(v*10_000_000) for end,v in zip(range(2020,2025),values)}
        oids={}
        for end,amount in receipts.items():
            oid=f'amx_ind_visa_actual_fy{end-1}_{end}';oids[end]=oid
            self.obs.append(dict(observation_id=oid,destination='IND',origin='UNK',origin_basis='unallocated',
                                 year=end,period_start=f'{end-1}-04-01',period_end=f'{end}-03-31',
                                 period_type='fiscal_year',period_label=f'FY{end-1}/{end}',
                                 metric='government_visa_fee_actual_receipts',raw_metric='Visa, Amount (In Rs cr)',
                                 value=amount,raw_value=values[end-2020],unit='INR',currency='INR',
                                 observation_domain='fiscal_receipts',context_only=False,eligible_money_ledger=True,
                                 source_id=sid,source_ids=[sid],source_locator=f'PDFp308/printed307, FY{end-1}-{str(end)[2:]}, Visa row',
                                 calculation_type='official_actual_receipts',aggregation_role='fiscal_control',
                                 notes='独立Visa实际收入；护照、其他收入均排除。金额精度0.01crore=100000INR，半舍入宽度50000INR。'))
        sf=self.source('amx_ind_fx_wdi','india_fx_wdi.json',
            'https://api.worldbank.org/v2/country/IND/indicator/PA.NUS.FCRF?format=json&per_page=100',
            'World Bank WDI / IMF International Financial Statistics','India annual average official exchange rate: PA.NUS.FCRF',
            '25ff812ff5e44d3f2a9c9480372aa090e130800fbbd7ac688cb8c564c3357e35')
        raw=json.loads((RAW/'india_fx_wdi.json').read_text());rates={int(r['date']):r['value'] for r in raw[1] if r['value'] is not None}
        for year in range(2020,2024):
            self.fx.append(dict(fx_id=f'amx_inr_{year}_wdi',year=year,currency='INR',raw_rate=rates[year],
                                raw_direction='currency_per_USD',usd_per_unit=1/rates[year],source_id=sf,
                                source_ids=[sf],source_locator=f'JSON countryiso3code=IND,indicator=PA.NUS.FCRF,date={year}',
                                method='WDI annual averageINR perUSD inverted'))
            first,second=receipts[year],receipts[year+1]
            center=.25*first+.75*second
            endpoints=[w*first+(1-w)*second for w in [.10,.40]]
            lower,upper=max(0,min(endpoints)-50_000),max(endpoints)+50_000
            params=dict(first_fiscal_period_start=f'{year-1}-04-01',first_fiscal_period_end=f'{year}-03-31',
                        second_fiscal_period_start=f'{year}-04-01',second_fiscal_period_end=f'{year+1}-03-31',
                        first_fiscal_actual_receipts_INR=first,second_fiscal_actual_receipts_INR=second,
                        first_fiscal_weight=.25,second_fiscal_weight=.75,first_weight_sensitivity=[.10,.40],
                        observed_calendar_revenue=False,observed_application_quantity=False,
                        source_rounding_half_width_INR=50_000,
                        range_method='相邻两个4月–次年3月财年按25%/75%桥接；第一财年权重10%–40%且第二权重互补，为时点工作情景；再加原表舍入，非统计置信区间。')
            self.flows.append(dict(id=f'amx_ind_{year}_visa_receipts_calendar_bridge',payer='UNK',receiver='IND',year=year,
                                   visa_group='other',visa_type='government_visa_fee_revenue_unclassified',
                                   visa_label='签证费实际收入的自然年桥接',category_detail_status='unclassified',
                                   amount=center,lower=lower,upper=upper,currency='INR',quantity=None,
                                   quantity_basis='fiscal_revenue_only_no_observed_application_denominator',origin_basis='unallocated',
                                   source_ids=[sid],observation_ids=[oids[year],oids[year+1]],
                                   method_id='amx_ind_actual_calendar_bridge',model_status='reported_actual_revenue_calendar_bridge_estimate',
                                   calculation_type='fiscal_to_calendar_bridge',period_start=f'{year}-01-01',period_end=f'{year}-12-31',
                                   period_type='calendar_year_model',period_label=str(year),parameters=params,
                                   notes='独立Visa实际收款的相邻财年25%+75%桥接，保留财政期和时点情景；不是自然年原始实收。没有收费申请量或国籍，付款方UNK，不按游客份额分配。'))
            self.ranges.append(dict(receiver='IND',year=year,amount=center,lower=lower,upper=upper,currency='INR',range_method=params['range_method']))
        self.models.append(dict(model_id='amx_ind_actual_calendar_bridge',destination='IND',years=list(range(2020,2024)),
                                formula='CYy=.25*Actual(FYy-1/y)+.75*Actual(FYy/y+1)',
                                limitations=['没有月度实际收入，25%/75%是假设财年内均匀收款的自然年中心。',
                                             '疫情期间收款高度不均，10%–40%时点权重仅为工作敏感性，不能当完整误差范围。',
                                             '原始财政收入与旅行背景分别保存；不估算每位游客或申请人的费用。']))

    def finish(self):
        ids=[r['observation_id'] for r in self.obs]
        assert len(ids)==len(set(ids)),[k for k,v in Counter(ids).items() if v>1]
        source_ids={r['source_id'] for r in self.sources}
        assert all(r['source_id'] in source_ids for r in self.obs)
        travel=[r for r in self.obs if r.get('observation_domain')=='mobility']
        assert all(r['context_only'] and not r['eligible_money_ledger'] and r['period_type']=='calendar_year' for r in travel)
        assert all(r['value'] is None or isinstance(r['value'],int) and r['value']>=0 for r in travel)
        assert {(r['receiver'],r['year']) for r in self.flows}=={('IND',y) for y in range(2020,2024)}
        # Source arithmetic discrepancies are evidence, not parser corrections.
        # Their exact residuals are exported for use in rendering/aggregation.
        quality=[c for c in self.checks if c.get('residual', 0) != 0]
        coverage=[]
        for country in ['IND','MYS']:
            rr=[r for r in travel if r['destination']==country and r['value'] is not None]
            for year in sorted({r['year'] for r in rr}):
                rows=[r for r in rr if r['year']==year]
                coverage.append(dict(code=country,year=year,visa_group='unclassified',status='mobility_context_only',
                                     mobility_context_known=True,source_ids=sorted({r['source_id'] for r in rows}),
                                     directions=sorted({r['flow_direction'] for r in rows}),
                                     rows=len(rows),notes='旅行背景可用；不代表签证申请或费用覆盖。'))
        for name,value in [('sources.json',self.sources),('observations.json',self.obs),('checks.json',self.checks),
                           ('fx.json',self.fx),('models.json',self.models),('destination_ranges.json',self.ranges),
                           ('edition_comparison.json',self.revisions),('coverage.json',coverage)]:write(name,value)
        EST.write_text(json.dumps(dict(flows=self.flows,models=self.models,destination_ranges=self.ranges),ensure_ascii=False,indent=2)+'\n')
        report=dict(package='asia_mobility_expansion_v4',asof=ASOF,sources=len(self.sources),
                    observations=len(self.obs),mobility_rows=len(travel),money_fiscal_controls=len(self.obs)-len(travel),
                    fee_flows=len(self.flows),fee_receiver_years=[dict(receiver='IND',year=y) for y in range(2020,2024)],
                    mobility_years=[min(r['year'] for r in travel),max(r['year'] for r in travel)],
                    reporting_countries=['IND','MYS'],series_counts=dict(Counter(r['series_id'] for r in travel)),
                    origin_bases=dict(Counter(r['origin_basis'] for r in travel)),
                    source_missing_values=sum(r['value'] is None for r in travel),
                    edition_differences=len(self.revisions),source_arithmetic_discrepancies=quality,
                    validation='source hashes, exact table extraction, names, uniqueness, units, fiscal bridge scopes and context-only separation passed; source arithmetic residuals retained')
        write('report.json',report)
        print(json.dumps({k:v for k,v in report.items() if k!='source_arithmetic_discrepancies'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    r=Research()
    r.india()
    r.malaysia()
    r.india_money()
    r.finish()
