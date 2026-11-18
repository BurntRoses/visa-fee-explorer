#!/usr/bin/env python3
"""Frozen Indonesia visa cash-receipt evidence and r10 replacement candidates.

Writes only its own research directory. Audited LRA leaf accounts stay separate
from accrual LO, preliminary press totals, mixed services and unknown payers.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
from html import unescape
from html.parser import HTMLParser
import io
import json
import logging
from pathlib import Path
import re
import zipfile

from pypdf import PdfReader

logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/asia_expansion_v6'
OUT = ROOT / 'data/research/asia_expansion_v6'
ASOF = '2026-11-17'

SOURCES = [
 ('av6_idn_law2020', 'idn_2020_law_appendix_part3.pdf',
  'd260b77731a82b74901e5f5b9afafc96b3d290e19868808bfeb6e4230958e858',
  '印度尼西亚总统／中央政府／BPK法规数据库', 'UU3/2021 financial appendix part3, PDF185 / printed495',
  '2020现金实收与2019审计比较列；金额单位rupiah。'),
 ('av6_idn_lkpp2025', 'idn_lkpp_2025_audited.pdf',
  '3ae3242f1e0833a1476264ba39cd64b357dc83da7ccd804a2b9f30117fcfc888',
  '印度尼西亚政府／审计署 BPK', 'LKPP2025 Audited, Appendix2.A, PDF306 / L.11',
  '2025审计现金实收及2024审计比较列；金额单位rupiah。425212与425221为不同叶科目。'),
 ('av6_idn_law2023', 'idn_2023_law_appendix_part3.pdf',
  'e49dcb9f80d754e451cc74ee757077a4262c4ef57eec052d19555a729efa11e3',
  '印度尼西亚总统／中央政府／BPK法规数据库', 'UU60/2024 financial appendix, part3, PDF77–78 / printed486–487',
  '2023现金实收与2022比较列；财政执行LRA，不是预算或权责发生制LO。原PDF OCR字母数字混淆，已逐项查看页面图像。'),
 ('av6_idn_law2022', 'idn_2022_law_appendix_part3.pdf',
  'b0092cb86c2963179f66cdf84cfa77683105f2a84ccaf91b8fe05fe8aab4e4c7',
  '印度尼西亚总统／中央政府／BPK法规数据库', 'UU18/2023 financial appendix, part3, PDF66–67 / printed466–467',
  '2022现金实收与2021比较列；2022值与下一年中央报表复核一致。OCR错误保留，数值逐项查看原始页面图像。'),
 ('av6_idn_account_definitions', 'idn_account_definitions_2018.pdf',
  '853a8ecafa7d8ce0e9b05e2dfd3e51b6542e4103b9ddf4645b2688589a4e6524',
  '印度尼西亚财政部国库总局／国防部官方镜像', 'KEP211/PB/2018 national account codification, PDF121–122 and431',
  '425212包含访问签和有限居留签VITAS；425213为居留／再入境许可ITAS/ITAP；425214含罚金等。425224为混合贸易办事处服务，不能全部计为签证。'),
 ('av6_idn_mfa2023', 'idn_mfa_financial_2023.pdf',
  '982d50435d52d86bf2412ff7e937c14ba4d1d94a62a3b2290b7f7f003d81c235',
  '印度尼西亚外交部', 'MFA financial statements2023 Audited, LRA PDF64 and LO PDF163',
  '2023海外签证现金数与中央合并表一致；2022比较数高374520印尼盾，保留合并／版本差异。LO权责数不能代现金数。'),
 ('av6_idn_press2022nov', 'idn_2022_partial_receipts_jogja.html',
  'd6694e9b2f52e54f93300d3d7477112e51f067bc76754e9de4b4e4e026792b3f',
  '印度尼西亚移民总局／日惹移民局', '2022-12-01 PNBP release, OMSPAN2022-11-30 19:49',
  '正文一处01/11/2022与12月1日矛盾；金额明确截止11月30日19:49，采用该财务统计截止。'),
 ('av6_idn_press2022dec', 'idn_2022_dec28_receipts_jogja.html',
  '30906ffa93038728b6954ed7cb8a7b77fca676d589064254d64c111315872e18',
  '印度尼西亚移民总局／日惹移民局', '2022 year-end release, OMSPAN2022-12-28 15:05 WIB',
  '12月28日截点，不能作完整自然年；同页12月23日出入境人次不是签证数。'),
 ('av6_idn_press2023', 'idn_2023_receipts_bengkalis.html',
  'fc3e09ea287d818035a3dfa0c56ecee5e939eb2fca37d08741c260d5e2dbe1b4',
  '印度尼西亚移民总局／Bengkalis移民局', '2024-01-04 release: 2023 PNBP components',
  '初步新闻稿2023签证收入比后续法定中央账高1267130800印尼盾。年账控制选择审计合并表。'),
 ('av6_idn_press2026h1', 'idn_2026_h1_bengkalis.html',
  '5f59a5ae1fc33e6666b534d3d25f5c0fb6aabb5fe6d562649829a6c2b015ad69',
  '印度尼西亚移民总局／Bengkalis移民局', '2026-07-07 release: H1 visa receipts2025/2026',
  '实收明确；数量段同时出现C1为3829902与113323两个矛盾数，保留冲突不拿来估费用。游客国籍人次不能分配收费。'),
 ('av6_idn_press2026oct', 'idn_2026_oct_receipts_jogja.html',
  '8f971de9bc4f63035d53865e513e9a1192e89e935bdba38ca382220131f86f02',
  '印度尼西亚移民总局／日惹移民局', '2026-10-14 release, cash cutoff2026-10-12 07:30 WIB',
  '签证4.7万亿为报道精度；总移民收入8.68万亿、全年预测及护照等均不当签证收入。'),
]


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        elif tag in ('p', 'div', 'br', 'td', 'tr', 'h1', 'h2', 'li') and not self.skip:
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        elif tag in ('p', 'div', 'td', 'tr', 'h1', 'h2', 'li') and not self.skip:
            self.parts.append('\n')
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
    def lines(self):
        return [re.sub(r'\s+', ' ', unescape(x)).strip()
                for x in ''.join(self.parts).splitlines() if x.strip()]


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    if isinstance(value, list) and value and isinstance(value[0], dict):
        keys = list(dict.fromkeys(k for r in value for k in r))
        with (OUT / name.replace('.json', '.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, keys)
            w.writeheader()
            w.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                         for k, v in r.items()} for r in value)


def compact(s):
    return re.sub(r'\s+', '', s)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    urls = json.loads((RAW / 'acquisition_urls.json').read_text())
    sources, external, checks, observations, texts, readers = [], [], [], [], {}, {}
    def check(name, condition, **evidence):
        checks.append(dict(check=name, passed=bool(condition), **evidence))
        assert condition, (name, evidence)
    for sid, filename, digest, publisher, title, notes in SOURCES:
        path = RAW / filename
        data = path.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        check(sid + '_frozen_original', h == digest, sha256=h, bytes=len(data))
        check(sid + '_original_format', data.startswith(b'%PDF') if filename.endswith('.pdf') else b'<html' in data.lower())
        sources.append(dict(source_id=sid, url=urls[filename], local_path=str(path.relative_to(ROOT)),
                            path=str(path.relative_to(ROOT)), publisher=publisher, title=title,
                            retrieved_at=ASOF, source_quality='official_original',
                            archive_kind='original_document', sha256=h, bytes=len(data), notes=notes))
        if filename.endswith('.pdf'):
            readers[sid] = PdfReader(path)
        else:
            parser = PageText(); parser.feed(data.decode('utf-8'))
            texts[sid] = parser.lines()
            (OUT / f'{sid}_text.txt').write_text('\n'.join(texts[sid]) + '\n')
    def reuse(sid, filename, digest, registry, reason):
        p = ROOT / filename
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        check(sid + '_reused_original', h == digest, sha256=h)
        external.append(dict(source_id=sid, local_path=filename, sha256=h,
                             registered_in=registry, reason=reason))
        return p
    reuse('game_idn_2024', 'data/raw/global_asia_me_europe/idn_2024.html',
          'c48c4e0708d8708bf7a8d913c0cdb18a423208614605fd0f1b8eb5eea88499cb',
          'data/research/global_asia_me_europe/sources.json', '已登记原文，不再登记另一份导航更新副本。')
    reuse('game_idn_2025', 'data/raw/global_asia_me_europe/idn_2025.html',
          'c7d144eb4e530f5a64eb33a2d51c9dec9a4e37aaf91e7384bffc4aac4da823fe',
          'data/research/global_asia_me_europe/sources.json', '现有2025年7551371签发量及VOA模型证据引用。')
    pfx = reuse('afx_wb_exchange_rates', 'data/raw/africa_expansion_v3/wb_fx_dataset.zip',
          'a565ae178924699a3a254159b4a93e99f077270ffa7f7941c4bfb687883927ce',
          'data/research/africa_expansion_v3/sources.json', '重用同一世界银行完整汇率数据集，提取IDN2019–2025历史汇率。')
    reuse('history_fed_20220103', 'data/raw/history/fed_g5a_20220103.html',
          '0b2ae73b272c906fd98a361d1e1e38c794d071528dd3cd7be10f4f33be749960',
          'data/research/history/sources.json', '历史人民币／美元年均汇率2019–2021。')
    reuse('fx_fed_g5a_20260105', 'data/raw/fx/fed-g5a-20260105.html',
          '850ebe60416fbfe66c086a833a5b0df5fb41f0d7c252bb577ab89335911d698e',
          'data/research/schengen_fx/sources.json', '人民币／美元年均汇率2022–2025；同一原件重用不重复归档。')
    def page(sid, n):
        key=(sid,n)
        if key not in texts:
            texts[key]=readers[sid].pages[n-1].extract_text(extraction_mode='layout')
            (OUT / f'{sid}_pdf_p{n}_layout.txt').write_text(texts[key]+'\n')
        return texts[key]
    def locate(sid, needle, n=None):
        t=page(sid,n) if n else '\n'.join(texts[sid])
        check(f'{sid}_quote_{len(checks)}', compact(needle) in compact(t), needle=needle, pdf_page=n)
        return f'PDF p{n}' if n else f'HTML normalized text line {next(i for i,x in enumerate(texts[sid],1) if needle in x)}'
    defs = page('av6_idn_account_definitions',121) + page('av6_idn_account_definitions',122)
    for phrase in ['visa kunjungan dan visa tinggal terbatas', 'izin tinggal terbatas, dan izin tinggal tetap',
                   'biaya beban keimigrasian', 'meliputi pendapatan paspor, visa']:
        check('account_scope_'+phrase.split()[0]+'_'+str(len(checks)), compact(phrase) in compact(defs))
    def add(oid,sid,needle,value,year,*,n=None,account=None,metric='visa_fee_cash_receipts',
            unit='IDR',end=None,status='reported_actual',selected=False,**extra):
        locator=locate(sid,needle,n)
        observations.append(dict(observation_id=oid,source_id=sid,source_ids=[sid],source_locator=locator,
             source_quote=needle,destination='IDN',destination_display_name='印度尼西亚',
             origin='UNK',origin_basis='unallocated',nationality='UNK',year=year,
             metric=metric,value=value,unit=unit,account_code=account,
             period_start=f'{year}-01-01',period_end=end or f'{year}-12-31',
             period_type='calendar_year' if (end is None or end==f'{year}-12-31') else
                 'half_year' if end==f'{year}-06-30' else 'year_to_date',
             calculation_type='direct_observation',source_status=status,
             accounting_basis='LRA_cash' if account and metric=='visa_fee_cash_receipts' else None,
             selected_annual_control=selected,context_only=not selected,
             eligible_money_ledger=False,visa_group='unallocated',**extra))
        return observations[-1]

    # Digits on OCR-imperfect statutory pages were visually checked against the
    # original page renders. Keep exact OCR probes; never silently normalize them.
    annual = {
      2019: (406729595455,300888401352,'av6_idn_law2020',185,185,
             '406.729.595.455','300.888.401.352'),
      2020: (229088321928,75845274019,'av6_idn_law2020',185,185,
             '229.088.321.928','75.845.274.019'),
      2021: (392551045115,1676876718,'av6_idn_law2022',66,67,
             '392.551 .045.1 1 5','r .676.876.7r I'),
      2022: (2038546234250,12753575080,'av6_idn_law2023',77,78,
             '2.O38.546.234.250','12.753.575.080'),
      2023: (4065946561392,81174688340,'av6_idn_law2023',77,78,
             '4.065.946.561.392','81.174.688.340'),
      2024: (5037980507624,95301059797,'av6_idn_lkpp2025',306,306,
             '5.037.980.507.624','95.301.059.797'),
      2025: (5644764250000,58631160895,'av6_idn_lkpp2025',306,306,
             '5.644.764.250.000','58.631.160.895'),
    }
    annual_rows=[]
    for y,(dom,over,sid,pd,po,qd,qo) in annual.items():
        for account,val,p,q in [('425212',dom,pd,qd),('425221',over,po,qo)]:
            add(f'av6_idn_{y}_{account}_cash',sid,q,val,y,n=p,account=account,
                status='audited_consolidated_actual',selected=True,
                scope='identified_visa_leaf_accounts',
                notes='实收金额精确到印尼盾；签证用途与付款国籍未分配。两个叶科目以外的混合服务不在此控制范围。')
        annual_rows.append(dict(year=y,receiver='IDN',currency='IDR',
            immigration_visa_account_425212=dom,overseas_visa_account_425221=over,
            identified_visa_cash_total=dom+over,source_ids=[sid],
            scope='two_identified_visa_leaf_accounts_not_exhaustive_national_total',
            omitted_mixed_account='425224',payer='UNK',visa_group='unallocated'))
    # Independent budget, difference and year-on-year fields prove column order.
    validations=[
      (2019,2020,425212,-177641273527,-43.68),
      (2019,2020,425221,-225043127333,-74.79),
      (2021,2022,425212,1645995189135,419.31),
      (2021,2022,425221,11076698362,660.56),
      (2022,2023,425212,2027400327142,99.45),
      (2022,2023,425221,68421113260,536.49),
      (2024,2025,425212,606783742376,12.04),
      (2024,2025,425221,-36669898902,-38.48),
    ]
    for y0,y1,account,diff,pct in validations:
        idx=0 if account==425212 else 1
        a,b=annual[y0][idx],annual[y1][idx]
        check(f'account{account}_{y1}_difference',b-a==diff,earlier=a,later=b,published_difference=diff)
        check(f'account{account}_{y1}_growth',abs((b/a-1)*100-pct)<=0.0051,
              computed_percent=(b/a-1)*100,published_percent=pct)
    locate('av6_idn_law2022','2.038.546.234.250',66)
    locate('av6_idn_law2022','2.753.575.080',67)

    # The mixed office-service account exists in the audited table from2020.
    mixed={2019:50513757196,2020:36845959824,2021:22231380804,2022:50876661094,2023:63908911528,2024:60997221054,2025:66017240420}
    # This is an upper bound on the unidentified visa part inside ONE mixed
    # account, not an upper bound on all Indonesian visa collections.
    mixed_rows=[dict(year=y,account_code='425224',mixed_account_total_idr=v,
       visa_component_lower_idr=0,visa_component_upper_idr=v,
       eligible_money_ledger=False,aggregation_role='excluded_mixed_scope',
       notes='贸易和经济办事处服务含护照、签证、宣誓书、领事及其他服务，无法拆分。涉及中国台湾的办事处地点不等于申请人国籍。')
       for y,v in mixed.items()]

    # Preliminary fiscal vintages and within-year nodes stay non-additive.
    partials=[
       ('2022nov','av6_idn_press2022nov','Visa : 1,766,249,697,550',1766249697550,2022,'2022-11-30',
        [1209072500000,1766249697550,948364100000,106404500001],4030090797551),
       ('2022dec','av6_idn_press2022dec','2.001.570.010.750',2001570010750,2022,'2022-12-28',
        [1358793000000,2001570010750,1045221500000,121197000001],4526781510751),
       ('2023press','av6_idn_press2023','4.067.213.692.192',4067213692192,2023,'2023-12-31',
        [2107877400000,4067213692192,1284899700000,150206000003],7610196792195),
    ]
    for slug,sid,q,val,y,end,components,total in partials:
        add('av6_idn_'+slug+'_visa_cash',sid,q,val,y,end=end,account='425212',
            status='preliminary_release_superseded' if y==2023 else 'within_year_cash_snapshot',
            notes='移民局新闻发布快照；不与年账加总，也不自动外推。')
        check(slug+'_component_reconciliation',sum(components)==total,components=components,published_total=total)
    add('av6_idn_2025h1_visa_cash','av6_idn_press2026h1','2.645.712.900.000',2645712900000,2025,
        end='2025-06-30',account='425212',status='within_year_cash_snapshot')
    add('av6_idn_2026h1_visa_cash','av6_idn_press2026h1','2.815.639.500.000',2815639500000,2026,
        end='2026-06-30',account='425212',status='within_year_cash_snapshot')
    add('av6_idn_2026oct12_visa_cash','av6_idn_press2026oct','Rp4,7 triliun',4700000000000,2026,
        end='2026-10-12',account='425212',status='rounded_within_year_cash_snapshot',
        value_semantics='published_approximation_not_exact_count',reported_precision_idr=100000000000,
        notes='截止07:30WIB；4.7万亿为报道值，未发布精确数，未自动设置统计置信区间。')
    check('2022_partial_monotonic',1766249697550<2001570010750<annual[2022][0])
    check('2025_partial_below_annual',2645712900000<annual[2025][0])
    check('2026_h1_growth',round((2815639500000/2645712900000-1)*100,2)==6.42)
    check('2026_partial_monotonic',2815639500000<4700000000000)

    # Official source discrepancies: selected national cash is never blended
    # with source-vintage, accrual or internally conflicting quantity values.
    add('av6_idn_mfa2023_cash','av6_idn_mfa2023','81.174.688.340',81174688340,2023,n=64,
        account='425221',status='departmental_cash_crosscheck',duplicate_of='av6_idn_2023_425221_cash')
    add('av6_idn_mfa2022_cash_comparator','av6_idn_mfa2023','12.753.949.600',12753949600,2022,n=64,
        account='425221',status='departmental_cash_vintage_difference')
    add('av6_idn_mfa2023_accrual','av6_idn_mfa2023','83.146.635.359',83146635359,2023,n=163,
        account='425221',metric='visa_fee_accrual_revenue',status='accrual_excluded_from_cash_control',
        accounting_basis_override='LO_accrual')
    quantity_probes=[
      ('2026h1_all',2026,'3.924.500',3924500,'visas_issued_reported_total'),
      ('2025h1_all',2025,'4.209.465',4209465,'visas_issued_reported_total'),
      ('2026h1_voa',2026,'3.481.490',3481490,'visa_on_arrival_issued'),
      ('2026h1_c1_small',2026,'113.323',113323,'C1_issued_conflicting'),
      ('2026h1_c1_large',2026,'3.829.902',3829902,'C1_issued_conflicting'),
      ('2025h1_c1_large',2025,'3.726.855',3726855,'C1_issued_conflicting'),
      ('2026h1_c20',2026,'83.852',83852,'C20_issued'),
    ]
    for slug,y,q,v,m in quantity_probes:
        add('av6_idn_'+slug,'av6_idn_press2026h1',q,v,y,end=f'{y}-06-30',metric=m,unit='visas',
            status='internally_conflicting_quantity' if 'c1' in slug else 'reported_quantity_context',
            notes='保留原文数量；同页C1冲突且总量含BVK免签类别，全部不用于倒算收费或分配国籍。')
    conflicts=[
       dict(id='2023_preliminary_vs_audited',year=2023,preferred='av6_idn_2023_425212_cash',
            preferred_value_idr=annual[2023][0],other_value_idr=4067213692192,
            difference_idr=4067213692192-annual[2023][0],reason='后续审计合并财政执行账户优先于年初新闻快报。'),
       dict(id='2022_mfa_vs_consolidated',year=2022,preferred='av6_idn_2022_425221_cash',
            preferred_value_idr=annual[2022][1],other_value_idr=12753949600,
            difference_idr=12753949600-annual[2022][1],reason='全国同口径选择中央合并表；部门比较数差374520，未用平均值抹平。'),
       dict(id='2023_cash_vs_accrual',year=2023,preferred='av6_idn_2023_425221_cash',
            preferred_value_idr=annual[2023][1],other_value_idr=83146635359,
            difference_idr=83146635359-annual[2023][1],reason='LRA现金与LO权责发生制不是同一计量基础。'),
       dict(id='2026h1_C1_conflict',year=2026,preferred=None,values=[113323,3829902],
            reason='同一发布稿对C1给出两个矛盾数；无收费模型选择。'),
    ]

    z=zipfile.ZipFile(pfx)
    member=next(n for n in z.namelist() if n.startswith('API_') and n.endswith('.csv'))
    fxrows=list(csv.DictReader(z.read(member).decode('utf-8-sig').splitlines()[4:]))
    idn=next(r for r in fxrows if r['Country Code']=='IDN')
    cny={2019:6.9081,2020:6.9042,2021:6.4508,2022:6.729,2023:7.0809,2024:7.1957,2025:7.1875}
    fx=[dict(fx_id=f'av6_idn_fx_{y}',year=y,currency='IDR',raw_rate=float(idn[str(y)]),
         raw_direction='currency_per_USD',local_per_usd=float(idn[str(y)]),usd_per_unit=1/float(idn[str(y)]),
         cny_per_usd=cny[y],cny_per_idr=cny[y]/float(idn[str(y)]),
         source_id='afx_wb_exchange_rates',cny_source_id='history_fed_20220103' if y<=2021 else 'fx_fed_g5a_20260105',
         source_locator=f'{member}; Indonesia IDN; PA.NUS.FCRF; {y}',method='same_year_annual_average')
    for y in annual]
    expected_fx={2019:14147.6713605454,2020:14582.2034678177,2021:14308.1439011896,2022:14849.8539362104,2023:15236.8846620506,2024:15855.448286671,2025:16477.8651797835}
    for row in fx:
        check('fx_'+str(row['year']),row['local_per_usd']==expected_fx[row['year']])
    candidates=[]
    for o in observations:
        if not o['selected_annual_control']:
            continue
        y=o['year']; f=next(x for x in fx if x['year']==y)
        candidates.append(dict(id=o['observation_id']+'_UNK',payer='UNK',receiver='IDN',year=y,
          visa_group='unallocated',visa_type='identified_visa_cash_'+o['account_code'],
          visa_label='签证实收（用途未分配）',category_detail_status='unclassified',
          amount=o['value'],lower=o['value'],upper=o['value'],currency='IDR',
          amount_cny=o['value']*f['cny_per_idr'],quantity=None,quantity_basis='no_matching_paid_application_denominator',
          source_ids=[o['source_id'],'av6_idn_account_definitions'],observation_ids=[o['observation_id']],
          method_id='av6_idn_identified_cash_leaf_accounts',model_status='audited_receipts_scope_partial',
          calculation_type='direct_observation',origin_basis='unallocated',
          period_start=o['period_start'],period_end=o['period_end'],period_type='calendar_year',
          notes='候选替换旧VOA模型，不能叠加；只含425212或425221已识别现金账户，425224混合部分未计入。用途与国籍未知。',
          parameters=dict(account_code=o['account_code'],accounting_basis='LRA_cash',
             range_kind='observed_account_scope_exact_not_total_coverage_confidence',omitted_mixed_account='425224')))
    for y in annual:
        subset=[r for r in candidates if r['year']==y]
        check('candidate_accounts_disjoint_'+str(y),len(subset)==2 and len({r['parameters']['account_code'] for r in subset})==2)
        check('candidate_cash_conservation_'+str(y),sum(r['amount'] for r in subset)==sum(annual[y][:2]))
    check('all_candidate_payers_unknown',all(r['payer']=='UNK' and r['quantity'] is None for r in candidates))
    check('no_purpose_guess',all(r['visa_group']=='unallocated' for r in candidates))
    check('unique_observation_ids',len({r['observation_id'] for r in observations})==len(observations))
    check('single_selected_account_year',all(v==1 for v in Counter((r['year'],r['account_code']) for r in observations if r['selected_annual_control']).values()))

    # Freeze the existing r9 VOA baseline separately from live totals. This
    # package can then be rebuilt even after a future integration replaces it.
    baseline_path=OUT/'r9_indonesia_baseline.json'
    if not baseline_path.exists():
        ledger=json.loads((ROOT/'data/processed/flows.json').read_text())
        baseline=[r for r in ledger if r.get('receiver')=='IDN']
        check('baseline_is_expected_VOA_model',len(baseline)==2 and all(r['method_id']=='game_idn_voa_model' for r in baseline))
        baseline_path.write_text(json.dumps(baseline,ensure_ascii=False,indent=2)+'\n')
    baseline=json.loads(baseline_path.read_text())
    impacts=[]
    for y in [2024,2025]:
        b=[r for r in baseline if r['year']==y]
        old=sum(r['amount'] for r in b)
        new=sum(annual[y][:2]);f=next(x for x in fx if x['year']==y)
        check('baseline_no_known_payers_'+str(y),all(r['payer']=='UNK' for r in b))
        old_cny=sum(r['amount_cny'] for r in b)
        check('baseline_fx_consistency_'+str(y),abs(old_cny-old*f['cny_per_idr'])<0.01)
        impacts.append(dict(year=y,receiver='IDN',old_model_ids=[r['id'] for r in b],
           old_voa_model_idr=old,new_identified_cash_idr=new,replacement_delta_idr=new-old,
           old_voa_model_cny=old_cny,new_identified_cash_cny=new*f['cny_per_idr'],
           replacement_global_delta_cny=(new-old)*f['cny_per_idr'],
           china_allocated_outflow_delta_cny=0,china_actual_outflow='unidentified_not_zero',
           new_known_payer_count=0,unknown_payer_share=1,
           integration='replace_old_IDN_annual_edges_once_do_not_add_control_on_top',
           omitted_mixed_425224_idr=mixed[y]))
    exclusions=[
      dict(topic='425211/425222 passports',reason='本国护照收入，不是外国申请人签证费。'),
      dict(topic='425213 residence and re-entry permits',reason='ITK/ITAS/ITAP及再入境许可单独账户；本包不计为签证。'),
      dict(topic='425214 other immigration',reason='含移民负担／罚金、ABTC和宣誓书，不整体计为签证。'),
      dict(topic='425224 mixed trade/economic office services',reason='护照、签证、领事和其他服务混合；只保留0至账户总额的未识别签证部分范围，不进入总账。'),
      dict(topic='golden visa investment',reason='投资承诺／投资规模，不是政府签证收入。'),
      dict(topic='nationality tourist arrivals and free-entry BVK',reason='旅行或免签活动不等于付费签证申请，不能据此分配实收。'),
      dict(topic='2026 full-year projection',reason='2026仅H1及10月12日快照，不自动年化，不回填2025。'),
      dict(topic='2024 5.03tn press paragraph',reason='复用game_idn_2024；财政年收入段与12月15日签发段期间不同。5.03万亿与审计5.0379805万亿差异不强称四舍五入。'),
      dict(topic='2025 ministry issuance discrepancy',reason='2026-07-14部门网页索引显示9372856，现有快报7551371；本地原件下载超时，未登记为可用数据，审计实收无需依赖该签发数。'),
    ]
    write('sources.json',sources);write('external_source_references.json',external)
    write('observations.json',observations);write('annual_cash_controls.json',annual_rows)
    write('mixed_account_exclusions.json',mixed_rows);write('source_conflicts.json',conflicts)
    write('fx.json',fx);write('model_candidates.json',candidates)
    write('replacement_impact.json',impacts);write('exclusions.json',exclusions);write('checks.json',checks)
    coverage=dict(asof=ASOF,package='asia_expansion_v6',integration_status='independent_r10_candidate_not_registered',
       new_source_count=len(sources),reused_source_count=len(external),observation_count=len(observations),
       selected_annual_cash_observation_count=14,annual_years=list(annual),
       within_year_cash_nodes=5,latest_partial_end='2026-10-12',candidate_flow_count=len(candidates),
       checks=len(checks),passed=sum(c['passed'] for c in checks),
       cash_scope='425212+425221; excludes unidentified visa component in mixed425224',
       receiver_coverage=1,bilateral_nationality_coverage=0,unknown_payer_share=1)
    coverage_rows=[]
    for y in [*annual,2026]:
        sids=list(dict.fromkeys(o['source_id'] for o in observations if o['year']==y))
        for group in ['visitor','student','work','family','other','unclassified']:
            coverage_rows.append(dict(code='IDN',destination='IDN',name='印度尼西亚',region='亚洲',
               year=y,visa_group=group,category_detail_status='unclassified_aggregate' if group=='unclassified' else 'no_classified_observation',
               status='audited_cash_total_unknown_payers' if y in annual and group=='unclassified' else 'category_amount_not_identified',
               amount_known=y in annual and group=='unclassified',fiscal_amount_known=y in annual,
               quantity_known=False,quantity_context_known=y in [2025,2026],nationality_known=False,
               source_ids=sids,notes=('两个独立签证叶科目审计现金实收可用，未获付款国籍及匹配付费申请分母；混合科目425224内的签证部分未识别。'
                    if y in annual else '只有2026上半年和10月12日年内财政快照，完整年额未识别；C1数量冲突未用于收费模型。')
                    + (' 本类别未从账户合计拆分。' if group!='unclassified' else ''),searched_as_of=ASOF))
    write('coverage.json',coverage_rows)
    coverage['coverage_rows']=len(coverage_rows)
    write('report.json',{**coverage, 'frozen':True, 'annual_cash_controls':annual_rows,
        'replacement_impact':impacts,
        'reuse_game_idn_2024':dict(source_id='game_idn_2024',
             path='data/raw/global_asia_me_europe/idn_2024.html',
             sha256='c48c4e0708d8708bf7a8d913c0cdb18a423208614605fd0f1b8eb5eea88499cb',
             action='reuse_registered_original_only_no_new_source_registration'),
        'integration_contract':dict(replace_method_id='game_idn_voa_model',
             replace_flow_ids=['game_idn_voa_model_2024_UNK_visitor','game_idn_voa_model_2025_UNK_visitor'],
             candidates='data/research/asia_expansion_v6/model_candidates.json',
             receipt_basis='LRA_cash_actual',preserve_known_payer_edges=True,
             current_known_payer_edges=0,unallocated_only=True,additive_with_old_model=False,
             scope_gap='unidentified_visa_portion_inside_mixed_account425224'),
        'gaps':['No nationality-specific paid visa quantities or receipts.',
                '2026 cash snapshots do not establish a full year.',
                'Mixed425224 has no visa-only split.',
                'No matching paid-application denominator for per-applicant price.']})
    table='\n'.join(f'| {r["year"]} | {r["immigration_visa_account_425212"]:,} | {r["overseas_visa_account_425221"]:,} | {r["identified_visa_cash_total"]:,} |' for r in annual_rows)
    impact_text='\n'.join(f'- {r["year"]}：候选替换差额 {r["replacement_delta_idr"]:,.0f} IDR，按同年年均汇率约 {r["replacement_global_delta_cny"]/1e8:.4f} 亿元人民币。' for r in impacts)
    (OUT/'README.md').write_text(f'''# 印尼签证收入历史与近期节点（独立研究包v6）

冻结截至{ASOF}的官方原件，离线提取。新增{len(sources)}来源、{len(observations)}观察；14个审计年度叶科目观察构成2019–2025连续系列。2025/2026半年及2026-10-12另列，未外推全年。本包尚未注册入共享数据或线上r9；供r10接入。

## 可识别现金实收

单位：印尼盾IDR，金额按原表完整精度保存。

| 年份 | 425212签证 | 425221海外签证 | 两项可识别合计 |
|---|---:|---:|---:|
{table}

2019–2020取UU3/2021附表1.A；2021取UU18/2023附表的2021比较列；2022–2023取UU60/2024附表；2024–2025取LKPP2025 Audited附表2.A。PDF页与印刷页、OCR摘录、查看过的页面图像均留存。复算比较列差额及同比以检查列顺序；2022两份中央表值一致。2020附表中的网页识别值229084371928与原图不符，采用看图核对的229088321928。

425212的会计定义包括访问签与有限居留签VITAS，不能全标短期访问。425213的ITK/ITAS/ITAP及再入境许可、425214罚金和其他移民服务、护照均排除。425224贸易／经济办事处服务同时含护照、签证等，未能拆分。因此两项合计是**已识别签证账户范围**，不能称全部渠道无遗漏总额；其混合签证部分0至账户总额另存，不整体计为签证。涉及中国香港、中国澳门、中国台湾一律使用中国冠名；办事处位置不是申请人国籍。

## 旧模型替换影响

{impact_text}

应替换现有两条年度VOA估算边，不能将本控制额叠加到旧模型上。现有IDN边全部付款国籍未知；新增候选同样保留UNK，不凭旅游到达国籍分配。中国已分配支出变化为0，仅表示未新增可归属边，不表示中国申请人没有付款。`model_candidates.json`含两账户×七年共14条候选，未改全局总账。若要保留VOA访问签子类，它必须在425212控制内作为估算分配，不能再另加。

## 期间、冲突与精度

- 2022-11-30、12-28为年内现金快照，与完整年账逐步递增；2023新闻快报比审计425212高1,267,130,800 IDR，控制选择审计数。
- 外交部2022海外签证比较数比中央合并数高374,520 IDR；保留版本差异。2023海外现金81,174,688,340与权责收入83,146,635,359不同，费用现金系列选前者。
- 2026 H1签证现金2,815,639,500,000 IDR，同比2025 H1的2,645,712,900,000增长6.42%。同稿C1签发数有3,829,902与113,323冲突，单独标记，无费用推算。稿中旅游到达人次不分配签证收费。
- 2026-10-12 07:30WIB约4.7万亿IDR按原报道精度保存，不展示成精确实收，不自动年化。年度候选的lower=upper表示已识别科目自身精确，不表示渠道覆盖已完整。
- 全部收入没有匹配的付费申请事件分母，`quantity=null`；不拿签发数或到达人次生成每申请人均价。

## 复现与交付

运行 `.research-venv/bin/python scripts/research_asia_expansion_v6.py`。固定SHA256、原始格式、原文数字／OCR探针、叶科目非重叠、差额和同比、新闻组件求和、截点递增、候选金额守恒、未知付款人和旧模型汇率一致性共{len(checks)}项通过。复用已登记的世界银行汇率ZIP与美联储人民币年均汇率原件，未重复登记下载副本。

核心文件：`sources.json`、`observations.json/.csv`、`annual_cash_controls.json/.csv`、`source_conflicts.json`、`mixed_account_exclusions.json`、`model_candidates.json/.csv`、`replacement_impact.json/.csv`、`checks.json`。`r9_indonesia_baseline.json`冻结接入前两条模型，用于未来离线重建对比。探查失败、不含目标附表或非审计正文下载不列入有效来源数。
''')
    print(json.dumps(coverage,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
