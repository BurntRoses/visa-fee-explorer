#!/usr/bin/env python3
"""Restore NZ application-decision history from the frozen 8 October 2026 PDFs.

Only application tables are read, never the near-identical people tables.
Existing FY2023/24 and FY2024/25 IDs are reused in a separate metadata adapter;
observations.json contributes only the other nine financial years. No money
edge, current-fee historical extrapolation or calendar-year bridge is produced.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re

from pypdf import PdfReader
import pycountry

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/newzealand_history_v5'
OUT = ROOT / 'data/research/newzealand_history_v5'
ASOF = '2026-11-17'
YEARS = list(range(2016, 2027))
DECISIONS = ('approved', 'declined', 'decided')
TYPE_ZH = {'visitor': '访客', 'student': '学生', 'work': '工作'}
DECISION_ZH = {'approved': '批准申请', 'declined': '拒绝或撤回申请', 'decided': '已处理申请'}
SPECS = {
    'visitor': dict(pages=list(range(12,22)), first_columns=29, next_columns=5,
                    sha256='745b6ad1fcc98d11d5c4107f25f345e8764519d9fa875f0ae8f3e75dc59c7cd4',
                    expected_rows=223, title='Visitors Visas decided (applications)'),
    'student': dict(pages=list(range(8,13)), first_columns=34,
                    sha256='a6da7f863f541075c6ee6a57dbb16c84ad31b89964b9501fbf1b51c87128d6e1',
                    expected_rows=199, title='Student Visas decided (applications)'),
    'work': dict(pages=list(range(21,31)), first_columns=27, next_columns=7,
                 sha256='09654e354f799083b90a0e7c2eba5a8fa240f3e679607f538b8218711a6833ae',
                 expected_rows=206, title='Work Visas decided (applications)'),
}
ALIASES = {
    'Antigua & Barbuda':'ATG', 'Bosnia & Herzegovina':'BIH', 'Cape Verde':'CPV',
    'Democratic Republic of Congo':'COD', 'East Timor':'TLS', 'Equitorial Guinea':'GNQ',
    'Great Britain':'GBR', 'Guinea - Bissau':'GNB', 'Ivory Coast':'CIV',
    'Kosovo - Republic of':'XKX', 'Macau':'MAC', 'Macedonia':'MKD',
    'Palestine':'PSE', 'Pitcairn Islands':'PCN', 'Reunion':'REU', 'Russia':'RUS',
    'Sao Tome & Principe':'STP', 'Sint Maarten':'SXM', 'St Kitts - Nevis':'KNA',
    'St Lucia':'LCA', 'St Vincent and the Grenadines':'VCT',
    'Sth Georgia & Sandwich Islands':'SGS', 'Swaziland':'SWZ', 'Timor Leste':'TLS',
    'Turkey':'TUR', 'US Outlying Islands':'UMI', 'Vatican City':'VAT',
    'Virgin Islands, USA':'VIR',
}
SPECIAL = {
    'East Timor':('HIST:East_Timor_name_variant','东帝汶（原表旧称分列）','historical_source_bucket'),
    'European Commission':('SOURCE:European_Commission','欧盟委员会（原表证件类别）','source_document_bucket'),
    'Kosovo - UN Mission in':('SOURCE:UNMIK','联合国科索沃任务团（原表证件类别）','source_document_bucket'),
    'Pacific Island Trust Territory':('HIST:Pacific_Island_Trust_Territory','原太平洋群岛托管地（原表标签）','historical_source_bucket'),
    'South Pacific commission':('SOURCE:South_Pacific_Commission','南太平洋委员会（原表证件类别）','source_document_bucket'),
    'Soviet Union':('HIST:Soviet_Union','原苏联（原表标签）','historical_source_bucket'),
    'Yugoslavia':('HIST:Yugoslavia','原南斯拉夫（原表标签）','historical_source_bucket'),
    'Stateless':('UNK:stateless','无国籍（原表分列）','residual_component'),
    'United Nations':('SOURCE:United_Nations','联合国（原表证件类别）','source_document_bucket'),
    'Unknown':('UNK:unknown','国籍未披露（原表分列）','residual_component'),
    'Total':('WORLD','全部国籍','country_total'),
}
ZH = {'CHN':'中国大陆','HKG':'中国香港','MAC':'中国澳门','TWN':'中国台湾',
      'GBR':'英国','USA':'美国','IND':'印度','NZL':'新西兰','XKX':'科索沃',
      'TLS':'东帝汶'}
ROW_RE = re.compile(r'^\s*([A-Za-z][A-Za-z ,\'().&/\-]*?)\s{2,}([\d,].*)$')
DEF_NOTE = ('统计单位为申请件，并非申请人数或独立人数；一件可含多人，同一人可多次申请。'
            'Declined含未满足政策条件及原文所列撤回情形：申请人要求撤回、由新申请替代、或因后续申请批准而撤回。'
            'Decided不含未成功递交或拒绝受理的申请；不等于当期新递交或付费申请。')


def oid(*parts):
    return '_'.join(re.sub(r'[^a-zA-Z0-9]+','-',str(p)).strip('-') for p in parts)


def classify(name):
    if name in SPECIAL:
        return SPECIAL[name]
    code = ALIASES.get(name)
    if not code:
        code = pycountry.countries.lookup(name).alpha_3
    return code, ZH.get(code, name), 'country_component'


def write(name, obj, csv_too=False):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')
    if csv_too and isinstance(obj,list) and obj:
        keys=list(dict.fromkeys(k for r in obj for k in r))
        with (OUT/name.replace('.json','.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,keys);w.writeheader()
            w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
                         for k,v in r.items()} for r in obj)


class Research:
    def __init__(self):
        self.checks, self.rows, self.sources, self.new, self.reused = [], [], [], [], []
        self.existing = {r['observation_id']:r for r in json.loads(
            (ROOT/'data/research/asia_pacific/observations.json').read_text())
            if r.get('source_id','').startswith('nz_') and r.get('visa_type') in TYPE_ZH}
        self.hit_existing=set()
        self.metadata=[]

    def check(self,name,condition,**evidence):
        assert condition,(name,evidence)
        self.checks.append(dict(check=name,passed=True,**evidence))

    def page(self,reader,typ,pageno):
        text=reader.pages[pageno-1].extract_text(extraction_mode='layout')
        (OUT/f'{typ}_pdf_p{pageno}_layout.txt').write_text(text)
        return text

    def parse_page(self,text,typ,pageno,count):
        rows=[]
        active=False
        for line_no,line in enumerate(text.splitlines(),1):
            if line.lstrip().startswith('Nationality Country'):
                active=True
                continue
            if not active or not line.strip():
                continue
            m=ROW_RE.match(line)
            if m:
                name=m[1].strip()
                tokens=re.findall(r'\d[\d,]*',m[2])
                assert len(tokens)==count,(typ,pageno,line_no,name,len(tokens),count)
                rows.append(dict(first_label=name,name=name,page=pageno,line=line_no,
                                 values=[int(n.replace(',','')) for n in tokens],
                                 raw_line=line.rstrip(),continuations=[]))
            elif re.match(r'^\s{0,15}[A-Za-z]',line):
                # Printed labels wrap on the immediately following line, e.g.
                # Democratic / Republic of Congo. Preserve all pieces and rows.
                assert rows,(typ,pageno,line_no,line)
                addition=line.strip()
                assert not re.search(r'\d',addition),(typ,pageno,line_no,addition)
                rows[-1]['name']+=' '+addition
                rows[-1]['continuations'].append(dict(line=line_no,text=addition))
            else:
                # Footer page numbers and timestamps are not data rows.
                assert re.match(r'^\s*(?:\d[\d :/,A-Za-z-]*|Page.*)\s*$',line),(typ,pageno,line_no,line)
        assert active and rows,(typ,pageno)
        return rows

    def extract(self,typ,spec):
        path=ROOT/f'data/raw/newzealand/{typ}-decisions.pdf'
        data=path.read_bytes()
        digest=hashlib.sha256(data).hexdigest()
        self.check(f'{typ}_frozen_official_original',digest==spec['sha256'],sha256=digest,bytes=len(data))
        source_id=f'nz_{typ}_decisions'
        registry=json.loads((ROOT/'data/research/asia_pacific/sources.json').read_text())
        source=next(s for s in registry if s['source_id']==source_id)
        self.check(f'{typ}_reused_source_hash',source['sha256']==digest,source_id=source_id)
        self.sources.append(dict(source_id=source_id,local_path=str(path.relative_to(ROOT)),
            url=source['url'],sha256=digest,bytes=len(data),publication_date='2026-10-08',
            source_quality='official_original',registered_in='data/research/asia_pacific/sources.json',
            retrieval_date=source.get('retrieved_at'),role='existing_official_original_reused'))
        reader=PdfReader(path)
        definition=self.page(reader,typ,1)
        self.check(f'{typ}_application_definitions',
            'Many applications can have more than one applicant' in definition and
            'withdrawn' in definition and 'Nationality:' in definition,
            locator='PDF p1, Definitions',definition_note=DEF_NOTE)
        pages={}
        for pageno in spec['pages']:
            text=self.page(reader,typ,pageno)
            is_first=typ=='student' or pageno%2==(0 if typ=='visitor' else 1)
            # Explicit branching avoids merging the two halves at the wrong FY.
            if typ=='student':
                is_first=True
                expected_years=[f'{y}/{str(y+1)[-2:]}' for y in YEARS]
            elif is_first:
                expected_years=[f'{y}/{str(y+1)[-2:]}' for y in YEARS[:9]]
                if typ=='visitor': expected_years+=['2025/26']
            else:
                expected_years=['2025/26','2026/27']
            visible_years=re.findall(r'\b20\d\d/\d\d\b',text)
            self.check(f'{typ}_p{pageno}_headers',visible_years==expected_years,
                       years=visible_years,applications_table=True)
            if pageno==spec['pages'][0]:
                self.check(f'{typ}_application_scope_and_actual_date_window',
                    spec['title'] in text and
                    'Date of decision between 31 July 2016 and 30 September 2026' in text,
                    period_start='2016-07-31',period_end='2026-09-30')
            count=spec['first_columns'] if is_first else spec['next_columns']
            pages[pageno]=self.parse_page(text,typ,pageno,count)
        combined=[]
        if typ=='student':
            for pageno,rows in pages.items():
                for row in rows:
                    row.update(source_id=source_id,visa_type=typ,
                        years={str(y):row['values'][i*3:i*3+3] for i,y in enumerate(YEARS)},
                        published_all_years_total=row['values'][-1],
                        source_pages=[pageno],second_half=None)
                    combined.append(row)
        else:
            for pageno in spec['pages'][::2]:
                left,right=pages[pageno],pages[pageno+1]
                self.check(f'{typ}_paired_pages_{pageno}_{pageno+1}',
                    [r['name'] for r in left]==[r['name'] for r in right],rows=len(left))
                for a,b in zip(left,right):
                    years={str(y):a['values'][i*3:i*3+3] for i,y in enumerate(YEARS[:9])}
                    tail=a['values'][27:29]+b['values'][:4] if typ=='visitor' else b['values'][:6]
                    assert len(tail)==6
                    years.update({str(y):tail[i*3:i*3+3] for i,y in enumerate(YEARS[9:])})
                    a.update(source_id=source_id,visa_type=typ,years=years,
                        published_all_years_total=b['values'][-1],
                        source_pages=[pageno,pageno+1],second_half=b)
                    combined.append(a)
        names=[r['name'] for r in combined]
        self.check(f'{typ}_all_rows_including_total',len(names)==spec['expected_rows'] and len(set(names))==len(names),
                   rows=len(names),nationality_components=len(names)-1)
        self.check(f'{typ}_all_annual_decision_identities',
            all(v[0]+v[1]==v[2] for r in combined for v in r['years'].values()),
            compared_triples=len(combined)*len(YEARS))
        self.check(f'{typ}_all_row_lifetime_totals',
            all(sum(v[2] for v in r['years'].values())==r['published_all_years_total'] for r in combined),
            compared_row_totals=len(combined))
        world=next(r for r in combined if r['name']=='Total')
        leaves=[r for r in combined if r['name']!='Total']
        for year in YEARS:
            fy=f'{year}/{str(year+1)[-2:]}'
            for i,decision in enumerate(DECISIONS):
                total=world['years'][str(year)][i]
                summed=sum(r['years'][str(year)][i] for r in leaves)
                self.check(f'{typ}_{fy}_{decision}_nationality_additivity',summed==total,
                    world_total=total,nationality_sum=summed,residual=total-summed,
                    country_rows=len(leaves))
        self.check(f'{typ}_all_years_total_nationality_additivity',
            sum(r['published_all_years_total'] for r in leaves)==world['published_all_years_total'],
            world_total=world['published_all_years_total'],
            nationality_sum=sum(r['published_all_years_total'] for r in leaves))
        self.rows.extend(combined)
        for row in combined:
            self.observations(typ,row)

    def observations(self,typ,row):
        code,name,role=classify(row['name'])
        row.update(origin=code,origin_display_name=name,aggregation_role=role)
        for y in YEARS:
            fy=f'{y}/{str(y+1)[-2:]}'
            start='2016-07-31' if y==2016 else f'{y}-07-01'
            end='2026-09-30' if y==2026 else f'{y+1}-06-30'
            partial=y in (2016,2026)
            actual_note=('首期原表实际范围2016-07-31至2017-06-30，缺少财年开始30天。' if y==2016 else
                         '最新财年仅2026-07-01至2026-09-30，不能当作完整财年同比。' if y==2026 else '')
            # Locate the printed cell. Visitor2025/26 total is on the second
            # half page whereas approved/declined are on the first half page.
            for i,decision in enumerate(DECISIONS):
                point=row
                if typ!='student' and (y==2026 or y==2025 and (typ=='work' or decision=='decided')):
                    point=row['second_half']
                pageno,line_no=point['page'],point['line']
                value=row['years'][str(y)][i]
                new_id=f'nzh_{typ}_{oid(code)}_{y}_{decision}'
                old_name=row['first_label']
                old_name={'United States of':'United States of America',
                          'Democratic Republic of':'Democratic Republic of Congo',
                          'Pacific Island Trust':'Pacific Island Trust Territory',
                          'South Pacific':'South Pacific commission'}.get(old_name,old_name)
                existing_id=oid('nz',typ,old_name,fy,decision)
                reused=y in (2023,2024)
                rec=dict(observation_id=existing_id if reused else new_id,
                    source_id=row['source_id'],source_ids=[row['source_id']],
                    source_locator=f'PDF p{pageno}; nationality applications table, row {row["name"]}, FY{fy}, {decision.title()}, layout line {line_no}',
                    source_pages=row['source_pages'],source_text_line=line_no,
                    destination='NZL',reporting_country='NZL',origin=code,
                    origin_display_name=name,origin_label=name,
                    raw_origin_label=row['name'],origin_raw_code=code,
                    origin_basis='nationality',visa_type=typ,visa_group=typ,
                    metric='applications_'+decision,raw_metric='Applications '+decision.title(),
                    value=value,unit='applications',year=y+1,period_label=fy,
                    period_start=start,period_end=end,period_type='financial_year',
                    source_status='partial_fiscal_year' if partial else 'complete_fiscal_year',
                    fiscal_year_start=f'{y}-07-01',fiscal_year_end=f'{y+1}-06-30',
                    period_complete=not partial,
                    calculation_type='published_official_application_count',
                    observation_domain='visa_activity',context_only=True,eligible_money_ledger=False,
                    aggregation_role=role,scope='applications_by_passport_issuing_country',
                    series_id=f'nz_{typ}_nationality_applications_{decision}',
                    series_label=f'新西兰{TYPE_ZH[typ]}签证{DECISION_ZH[decision]}（财年）',
                    time_grain='financial_year',period_key=fy,
                    notes=actual_note+DEF_NOTE)
                if row['name']=='East Timor':
                    rec.update(source_bucket_parent='TLS',
                        notes=rec['notes']+' 原表同时另列Timor Leste；此旧称分项单独保留，避免静默合并或覆盖。')
                if partial:
                    rec['quality_issue']='partial_fiscal_year_start' if y==2016 else 'partial_latest_fiscal_year'
                if reused:
                    old=self.existing.get(existing_id)
                    assert old,(typ,row['name'],old_name,existing_id)
                    assert (old['value'],old['period_start'],old['period_end'],old['source_id'])==(value,start,end,row['source_id']),existing_id
                    self.hit_existing.add(existing_id)
                    rec.update(reused_source_observation_ids=[existing_id],
                        legacy_nationality_label=old['nationality'],
                        legacy_source_locator=old['source_locator'])
                    self.reused.append(rec)
                else:
                    self.new.append(rec)

    def finish(self):
        all_obs=self.new+self.reused
        self.check('existing_3768_observations_reused_without_value_period_source_changes',
            len(self.reused)==3768 and self.hit_existing==set(self.existing),
            existing=len(self.existing),reused=len(self.reused),values_modified=0)
        ids=[r['observation_id'] for r in all_obs]
        self.check('all_observation_ids_unique',len(ids)==len(set(ids)),observations=len(ids))
        self.check('only_new_nine_fiscal_years_in_main_observations',
            all(r['period_label'] not in ('2023/24','2024/25') for r in self.new),
            new_observations=len(self.new))
        self.check('partial_endpoints_retain_exact_actual_source_periods',
            all(r['period_start']=='2016-07-31' for r in all_obs if r['period_label']=='2016/17') and
            all(r['period_end']=='2026-09-30' for r in all_obs if r['period_label']=='2026/27'),
            initial_period_start='2016-07-31',latest_period_end='2026-09-30')
        self.check('no_money_ledger_eligible_rows',
            all(r['context_only'] and r['eligible_money_ledger'] is False for r in all_obs))
        # Aliases sometimes coexist (East Timor/Timor Leste, Kosovo documents).
        # A canonical code must not collapse two source cells in the same period.
        keys=[(r['series_id'],r['origin'],r['period_start'],r['period_end']) for r in all_obs]
        self.check('no_canonical_partner_period_collisions',len(keys)==len(set(keys)))
        mapping={r['name']:{k:r[k] for k in ('origin','origin_display_name','aggregation_role')}
                 for r in self.rows}
        write('country_mapping.json',mapping)
        write('sources.json',[])
        write('external_source_references.json',self.sources)
        write('observations.json',self.new,csv_too=True)
        write('reused_observations.json',self.reused,csv_too=True)
        write('parsed_application_rows.json',self.rows)
        write('checks.json',self.checks)
        by_type={typ:dict(source_rows=spec['expected_rows'],
                         nationality_components=spec['expected_rows']-1,
                         new_observations=sum(r['visa_type']==typ for r in self.new),
                         reused_observations=sum(r['visa_type']==typ for r in self.reused))
                 for typ,spec in SPECS.items()}
        coverage=dict(package='newzealand_history_v5',as_of=ASOF,destination='NZL',
            source_published_at='2026-10-08',source_period_start='2016-07-31',source_period_end='2026-09-30',
            financial_years=[f'{y}/{str(y+1)[-2:]}' for y in YEARS],
            new_sources=0,reused_official_sources=3,new_observations=len(self.new),
            reused_observations=len(self.reused),all_observations=len(all_obs),
            canonical_partners=len({r['origin'] for r in all_obs}),
            by_visa_type=by_type,unit='applications',observation_domain='visa_activity',
            monetary_flows_generated=0,
            partial_periods=[dict(label='2016/17',actual_start='2016-07-31',actual_end='2017-06-30',
                                  reason='source window starts30days after financial year begins'),
                             dict(label='2026/27',actual_start='2026-07-01',actual_end='2026-09-30',
                                  reason='source cutoff is first quarter of financial year')],
            gaps=['不含拒绝受理或未成功递交申请。','Declined含原文指定撤回；不能全部解释为政策拒签。',
                  '一件申请可包括多人；未生成申请人均费用。','未按现行收费表回填历史费用；未将申请审理量当收费事件。',
                  '未提取同文件的人数表或按量重新排序的重复表，避免重复累计。'])
        write('coverage_summary.json',coverage)
        write('coverage.json',[dict(code='NZL',year=year,visa_group=typ,status='quantity_only',
              quantity_context_known=True,source_ids=[f'nz_{typ}_decisions'],
              notes='原始财年签证申请处理件数；首末期不完整，精确期间和结果定义随观察保存。')
              for year in range(2016,2027) for typ in ('visitor','student','work')])
        write('report.json',dict(**coverage,checks=len(self.checks),passed=True,
            integration=dict(data_package='newzealand_history_v5',
                command='.research-venv/bin/python scripts/research_newzealand_history_v5.py',
                main_observations='observations.json contains only the9additional financial years.',
                reused_adapter='reused_observations.json replaces semantic metadata for the3768 existing IDs; do not append duplicate IDs.',
                source_registry='sources.json is empty: all3source IDs are registered by asia_pacific; external_source_references.json preserves hashes and paths.')))
        write('world_annual_summary.json',[
            {k:r[k] for k in ('observation_id','source_id','visa_type','metric','value','period_label',
                              'period_start','period_end','source_status','source_locator')}
            for r in sorted(all_obs,key=lambda r:(r['visa_type'],r['period_start'],r['metric'])) if r['origin']=='WORLD'],csv_too=True)
        (OUT/'README.md').write_text('''# 新西兰签证申请处理历史与近期数据 v5

离线重建：`.research-venv/bin/python scripts/research_newzealand_history_v5.py`。

复用2026年10月8日发布的访客、学生、工作签证3份官方PDF原件，恢复2016/17至2026/27共11财年，按护照签发国家/地区、批准、拒绝或撤回、处理合计保存申请件数。只提取 applications 表，不叠加同文档 people 表或重新排序的重复表。

## 接入

- `observations.json` 仅含旧FY2023/24、FY2024/25之外的9财年。注册包名 `newzealand_history_v5`。
- `reused_observations.json` 逐条复用旧2财年3768个 observation_id，value、起止期间与source_id完全不变，供主构建器按ID覆盖语义元数据。不要追加相同ID。它修复跨行国家名称，补齐国籍代码、series_id、中文系列名和定义。
- 3个source_id为 `nz_visitor_decisions`、`nz_student_decisions`、`nz_work_decisions`，已在 `asia_pacific` 注册，本包 `sources.json=[]` 避免重复注册，来源路径、哈希、发布日期在 `external_source_references.json`。
- 两类文件合并后，国家上下文可用9条系列：3签证类×3处理结果，按相同series_id连续显示。

## 实际期间与定义

- FY2016/17实际仅 **2016-07-31至2017-06-30**，缺财年开始30天。
- FY2026/27实际仅 **2026-07-01至2026-09-30**，是最新财年第一季度。
- 两期均保留实际起止、`source_status=partial_fiscal_year`和`period_complete=false`。不当作完整财年同比，也不年化。
- 国籍按原文定义为签发护照的国家/地区；原表国际组织、历史国家和未知类别分列，不强行合并到现代国家。中国相关显示名统一为中国大陆、中国香港、中国澳门、中国台湾。
- 单位是申请件，并非人数：一件可含多人，一人可申请多次。Declined包括条件不符及指定撤回情形。Decided不含未成功递交或拒绝受理的申请。

## 校验与边界

重建完整国家名称及跨页年份；每行每年核对 approved+declined=decided，每行11年处理量核对原表历年合计，每财年3项核对全部国籍分项加总等于世界总计。复用的旧记录逐条与原包核对ID、值、期间、来源。

所有观察均 `context_only=true`、`eligible_money_ledger=false`。不生成金额，不套用现行收费表估历史收入，不把审理量当本期付费事件。原件SHA-256、PDF页码、版面文本行、完整解析行均保留。
''')
        (RAW/'reused_originals_manifest.json').write_text(json.dumps(self.sources,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(package='newzealand_history_v5',new_observations=len(self.new),
            reused_observations=len(self.reused),checks=len(self.checks),passed=True),ensure_ascii=False))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    RAW.mkdir(parents=True,exist_ok=True)
    r=Research()
    for typ,spec in SPECS.items():
        r.extract(typ,spec)
    r.finish()


if __name__=='__main__':
    main()
