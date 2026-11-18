#!/usr/bin/env python3
"""Offline historical receipt/revenue controls: Australia2011–2023, USA2021–22.

Only explicitly named visa fee accounts and actual columns enter fiscal controls.
Country/category allocations remain unknown and cash controls have no invented
quantity denominator. Calendar-year values and their ranges are timing models.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import unicodedata

from bs4 import BeautifulSoup
import openpyxl
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/temporal_expansion_v2'
OUT = ROOT / 'data/research/temporal_expansion_v2'
EST = ROOT / 'data/estimates/temporal_expansion_v2_flows.json'
ASOF = '2026-11-16'


def read(path):
    return json.loads(path.read_text())


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


class Research:
    def __init__(self):
        self.sources, self.obs, self.fx, self.coverage = [], [], [], []
        self.flows, self.models, self.ranges, self.checks, self.conflicts = [], [], [], [], []
        self.source_ids = set()

    def check(self, check, passed, **details):
        self.checks.append(dict(check=check, passed=bool(passed), **details))
        assert passed, (check, details)

    def source(self, slug, path, url, publisher, title, notes=''):
        sid = 'tmx_' + slug
        if sid in self.source_ids:
            return sid
        p = ROOT / path
        self.check('original_document_exists_' + slug, p.is_file(), path=path)
        self.sources.append(dict(source_id=sid, url=url, publisher=publisher, title=title,
                                 local_path=path, sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                 bytes=p.stat().st_size, retrieved_at=ASOF, source_quality='official_primary',
                                 archive_kind='original_document', notes=notes))
        self.source_ids.add(sid)
        return sid

    def fiscal(self, receiver, year, value, currency, metric, sid, locator, notes, **extra):
        oid = f'tmx_{receiver.lower()}_FY{year}_{metric}'
        start = f'{year-1}-07-01' if receiver == 'AUS' else f'{year-1}-10-01'
        end = f'{year}-06-30' if receiver == 'AUS' else f'{year}-09-30'
        self.obs.append(dict(observation_id=oid, destination=receiver, nationality='UNK', year=year,
                             metric=metric, raw_metric='Visa Application Charges / historical Visa application fees' if receiver == 'AUS' else 'Machine-Readable Visa Fee, Consular and Border Security Programs',
                             value=value, unit=currency, source_id=sid, source_ids=extra.pop('source_ids', [sid]),
                             source_locator=locator, visa_type='all_unallocated', visa_group='other',
                             category_detail_status='unclassified', origin_basis='unallocated_nationality',
                             period_start=start, period_end=end, period_type='fiscal_year', period_label=f'FY{year-1}/{str(year)[2:]}' if receiver == 'AUS' else f'FY{year}',
                             calculation_type='official_recognised_revenue' if receiver == 'AUS' else 'official_cash_receipt',
                             notes=notes, **extra))
        return oid

    def calendar(self, receiver, year, a, b, share, sensitivity, currency, method):
        amount = (1-share)*a['amount'] + share*b['amount']
        alternatives = [(1-w)*a['amount']+w*b['amount'] for w in sensitivity]
        rounding = (1-share)*a['rounding']+share*b['rounding']
        lower, upper = max(0, min(alternatives)-rounding), max(alternatives)+rounding
        isau = receiver == 'AUS'
        timing = '次财年1–6月' if isau else '次财年10–12月'
        note = ('澳大利亚官方签证申请费已确认收入，含境内、境外及适用移民申请；明确排除另列的公民、签证证据、其他移民费、旅客离境税和其他税项。' if isau else '美国MRV实际现金账户，含边境通行卡；其他领事收入、SEVIS和USCIS不在此账户。')
        note += f'自然年由相邻两个财政年真实金额桥接，假设财年内均匀收款／确认；{timing}权重中心{share:.0%}、范围{sensitivity[0]:.0%}–{sensitivity[-1]:.0%}。付款国籍和用途未分配，quantity为空。'
        parameters = dict(fiscal_amounts={str(year):a['amount'],str(year+1):b['amount']},
                          fiscal_source_locators={str(year):a['locators'],str(year+1):b['locators']},
                          next_fiscal_year_share_center=share, next_fiscal_year_share_range=sensitivity,
                          period_assumption='uniform receipts/revenue recognition within each fiscal year',
                          rounding_native_currency=rounding, nationality_allocation='none', category_allocation='none',
                          quantity_is_null_for_account_control=True,
                          account_scope='all VAC recognised revenue including onshore/offshore applicable migration applications; not net of a matched refund series' if isau else 'MRV fee offsetting cash receipts, account571350; all actual sublines as reconciled')
        sids = sorted(set(a['sids']+b['sids']))
        self.flows.append(dict(id=f'tmx_{receiver.lower()}_{year}_fiscal_bridge', payer='UNK', receiver=receiver, year=year,
                               visa_group='other', visa_type='historical_VAC_all_unallocated' if isau else 'historical_MRV_all_unallocated',
                               visa_label='签证申请费（类别未细分）' if isau else 'MRV（类别未细分）', category_detail_status='unclassified',
                               amount=amount, lower=lower, upper=upper, currency=currency, quantity=None,
                               quantity_basis='official_fiscal_revenue_control_without_event_count',
                               source_ids=sids, observation_ids=[a['oid'],b['oid']], method_id=method,
                               model_status='actual_revenue_control_calendar_bridge' if isau else 'actual_cash_control_calendar_bridge',
                               calculation_type='fiscal_actual_calendar_bridge', origin_basis='unallocated_nationality',
                               period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year_model',
                               period_label=f'{year}自然年模型', notes=note, parameters=parameters))
        range_method = f'相邻财年实际签证科目；{timing}权重{sensitivity[0]:.0%}–{sensitivity[-1]:.0%}及原表取整，国籍分配保持未知'
        self.ranges.append(dict(receiver=receiver, year=year, amount=amount, lower=lower, upper=upper, currency=currency, range_method=range_method))
        self.coverage.append(dict(receiver=receiver, destination=receiver, year=year,
                                  coverage_status='fiscal_actual_calendar_bridge_unallocated', source_ids=sids,
                                  scope='澳大利亚全部VAC已确认收入；含境内和境外适用移民申请' if isau else '美国全部MRV现金账户；包含BCC，不含其他领事／移民收费',
                                  notes=note, fiscal_years=[year,year+1], category_detail_status='unclassified',
                                  quantity_status='not_available_for_financial_control'))

    def australia(self):
        # Explicit source page, units and column values. Each pair is an original
        # financial-note actual/comparative column, never an audit headline/budget.
        specs = [
            ('au_diac2011_12.pdf', 411, 'Note19A: Fees and fines; Visa application fees', {2012:1029223,2011:927721}),
            ('au_diac2012_13.pdf', 405, 'Note19A: Fees and fines; Visa application fees', {2013:1163109,2012:1029223}),
            ('au_dibp2014_15.pdf', 307, 'Note19A: Fees and fines; Visa application fees', {2015:1818674,2014:1594387}),
            ('au_dibp2015_16.pdf', 208, 'Note2.1A: Taxation Revenue; Visa Application Charges', {2016:1913947,2015:1818674}),
            ('au_dibp2016_17.pdf', 163, 'Note2.1A: Taxation revenue; Visa Application Charges', {2017:2045503,2016:1913947}),
            ('au_annual2017_18.pdf', 131, 'Note2.1A: Taxation revenue; Visa Application Charges', {2018:2026328,2017:2045503}),
            ('au_annual2018_19.pdf', 124, 'Note2.1A: Taxation revenue; Visa Application Charges', {2019:2330427,2018:2026328}),
            ('au_annual2019_20.pdf', 149, 'Note2.1A: Indirect tax; Visa Application Charges', {2020:2157168,2019:2330427}),
            ('au_annual2020_21.pdf', 209, 'Note2.1A: Taxation revenue; Visa Application Charges', {2021:1632989,2020:2157168}),
            ('au_annual2021_22.pdf', 208, 'Note2.1A: Taxation revenue; Visa Application Charges', {2022:1981971,2021:1632989}),
            ('au_annual2022_23.pdf', 138, 'Note2.1A: Taxation revenue; Visa Application Charges', {2023:3155729,2022:1981971}),
            ('data/raw/australia/annual-2023-24.pdf', 119, 'Note2.1A: Taxation revenue; Visa Application Charges', {2024:3384970,2023:3155729}),
        ]
        urls = {r['name']:r['url'] for r in read(RAW/'download_manifest.json') if r.get('archived')}
        urls['au_dibp2016_17.pdf'] = 'https://www.homeaffairs.gov.au/reports-and-pubs/Annualreports/2016-17/Complete.pdf'
        urls['data/raw/australia/annual-2023-24.pdf'] = 'https://www.homeaffairs.gov.au/reports-and-pubs/Annualreports/home-affairs-annual-report-2023-24.pdf'
        seen = defaultdict(list)
        for name, page, label, amounts in specs:
            path = name if name.startswith('data/') else str((RAW/name).relative_to(ROOT))
            sid = self.source(Path(name).stem, path, urls[name], 'Australian Department of Immigration and Citizenship / Immigration and Border Protection / Home Affairs',
                              f'Australian immigration annual financial statements {min(amounts)}–{str(max(amounts))[2:]}; visa application fee actual revenue',
                              'Original audited financial statements; actual and comparative columns in AUD thousand. Separate taxation receivables, total taxes and immigration/citizenship fees are excluded.')
            doc = PdfReader(ROOT/path)
            text = doc.pages[page-1].extract_text() or ''
            compact = re.sub(r'[^A-Za-z0-9]', '', unicodedata.normalize('NFKC',text))
            self.check('au_original_page_explicit_visa_fee_' + Path(name).stem,
                       ('Visaapplicationfees' in compact or 'VisaApplicationCharges' in compact) and all(str(v) in compact for v in amounts.values()),
                       page=page, fiscal_actuals_thousand_AUD=amounts)
            (OUT/f'{Path(name).stem}_p{page}.txt').write_text(text+'\n')
            if name == 'au_dibp2015_16.pdf':
                reclass = doc.pages[190].extract_text()
                self.check('au_2015_reclassification_explicit_not_new_revenue', 'reclassified from non-taxation revenue' in reclass and '1,819m' in reclass)
                (OUT/'au_2015_reclassification_p191.txt').write_text(reclass+'\n')
            for year, value in amounts.items():
                locator = f'PDFp{page}; {label}; {year} actual/comparative column; AUD thousand'
                seen[year].append(dict(amount=value*1000,sid=sid,locator=locator))
        fiscal = {}
        for year, rows in sorted(seen.items()):
            self.check('au_same_fiscal_actual_across_originals', len({r['amount'] for r in rows})==1,
                       year=year, observed_values=[r['amount'] for r in rows], sources=[r['sid'] for r in rows])
            value = rows[0]['amount']
            oid = self.fiscal('AUS',year,value,'AUD','visa_application_fee_revenue_actual',rows[0]['sid'], '; '.join(r['locator'] for r in rows),
                              '官方签证申请费已确认收入；原表AUD千元转全元。2015/16起从非税重分类到税收，2015比较值完全一致，未把重分类算成新增收费。包含境内／境外适用签证和移民申请；公民、签证证据、其他移民服务费及旅客离境税另列。',
                              source_ids=sorted({r['sid'] for r in rows}), original_value_thousand=value/1000,
                              original_unit='AUD thousand', original_locations=[r['locator'] for r in rows])
            fiscal[year] = dict(amount=value,sids=sorted({r['sid'] for r in rows}),oid=oid,rounding=500,locators=[r['locator'] for r in rows])
        self.check('au_two_adjacent_fiscal_actuals_every_calendar_year', sorted(fiscal)==list(range(2011,2025)))
        method = 'tmx_au_vac_actual_calendar_bridge'
        for year in range(2011,2024):
            self.calendar('AUS',year,fiscal[year],fiscal[year+1],.5,[.4,.5,.6],'AUD',method)
        self.models.append(dict(model_id=method,destination='AUS',years=list(range(2011,2024)),
                                status='audited_revenue_control_calendar_bridge',source_ids=sorted({s for r in fiscal.values() for s in r['sids']}),
                                formula='CY[y] = 0.5*actual_VAC_FYendingJune[y] + 0.5*actual_VAC_FYendingJune[y+1]',
                                parameters=dict(next_fiscal_year_weight=[.4,.5,.6],source_rounding_AUD=500),
                                limitations=['自然年是财年内均匀确认假设下的桥接；40–60%是共同期间情景，不是统计置信区间。',
                                             '官方VAC含境内与境外适用签证及移民申请，保留完整科目范围；它与境外签发量不共用申请分母。',
                                             '国籍、具体用途和匹配退款序列未分配；全部保留UNK/未细分，数量为空。',
                                             '2015/16行政分类改为税收，使用同一签证申请费叶科目跨年对照，公民/证据/其他移民费未加入。']))

    def us_mrv(self):
        values = defaultdict(list)
        for release, actual_end in [(2024,2022),(2025,2023)]:
            filename=f'usa_db{release}_outlays.xlsx'
            sid=self.source(f'usa_db{release}_outlays',str((RAW/filename).relative_to(ROOT)),
                            f'https://www.govinfo.gov/content/pkg/BUDGET-{release}-DB/xls/BUDGET-{release}-DB-2.xlsx',
                            'U.S. Office of Management and Budget / Government Publishing Office',
                            f'Public Budget Database FY{release}, Outlays and offsetting receipts; MRV account571350')
            guide_sid=self.source(f'usa_db{release}_guide',str((RAW/f'usa_db{release}_guide.pdf').relative_to(ROOT)),
                                  f'https://www.govinfo.gov/content/pkg/BUDGET-{release}-DB/pdf/BUDGET-{release}-DB-4.pdf',
                                  'U.S. Office of Management and Budget / Government Publishing Office',
                                  f'Public Budget Database FY{release} user guide: fiscal periods, units, actual/estimate boundary')
            guide='\n'.join(p.extract_text() or '' for p in PdfReader(RAW/f'usa_db{release}_guide.pdf').pages[:10])
            self.check('us_database_actual_units_and_sign_documented', 'thousands of dollars' in guide and 'Offsetting receipts' in guide and str(actual_end) in guide,
                       release=release,actual_through=actual_end)
            workbook=openpyxl.load_workbook(RAW/filename,read_only=True,data_only=True);sheet=workbook.worksheets[0]
            rows=list(sheet.iter_rows(values_only=True));header=list(rows[0]);matches=[]
            for rownum,row in enumerate(rows[1:],2):
                if str(row[4])=='571350' and row[5]=='Machine-Readable Visa Fee, Consular and Border Security Programs':
                    matches.append((rownum,row))
            self.check('us_mrv_account_name_code_unique',len(matches)==1,release=release,matching_rows=[r[0] for r in matches])
            rownum,row=matches[0]
            self.check('us_mrv_state_discretionary_receipt_identity',row[1]=='Department of State' and str(row[6])=='19' and row[9]=='Discretionary',release=release)
            for year in range(2019,actual_end+1):
                column=header.index(str(year));raw=row[column]
                self.check('us_mrv_actual_negative_offsetting_receipt',isinstance(raw,(float,int)) and raw<0,release=release,year=year,value=raw)
                locator=f"'{sheet.title}'!{openpyxl.utils.get_column_letter(column+1)}{rownum}; account571350; {year} actual; USD thousand negative offsetting receipt"
                values[year].append(dict(amount=-raw*1000,sid=sid,guide_sid=guide_sid,locator=locator,raw=raw))
            workbook.close()
        expected={2019:1847000000,2020:896000000,2021:826000000,2022:1644000000,2023:2220000000}
        fiscal={}
        for year,rows in sorted(values.items()):
            self.check('us_cash_cross_release_and_existing_pdf_reconciliation',{r['amount'] for r in rows}=={expected[year]},year=year,amounts=[r['amount'] for r in rows])
            value=rows[0]['amount'];sids=sorted({r[k] for r in rows for k in ['sid','guide_sid']})
            oid=self.fiscal('USA',year,value,'USD','mrv_cash_receipts_actual',rows[0]['sid'],'; '.join(r['locator'] for r in rows),
                            '明确MRV账户571350；原值负数为offsetting receipts，按官方指南单位千美元，转为正向政府收入。仅使用预算发布年前两年及以前的actual列；后续预测列不入账。FY2019/2020/2021/2023与既有原PDF实际收款控制一致。',
                            source_ids=sids,original_signed_values_thousand=[r['raw'] for r in rows],original_unit='USD thousand',
                            actual_source_locations=[r['locator'] for r in rows])
            fiscal[year]=dict(amount=value,sids=sids,oid=oid,rounding=500000,locators=[r['locator'] for r in rows])
        method='tmx_us_mrv_actual_gap_bridge'
        for year in (2021,2022):self.calendar('USA',year,fiscal[year],fiscal[year+1],.25,[.15,.25,.35],'USD',method)
        self.models.append(dict(model_id=method,destination='USA',years=[2021,2022],status='official_cash_gap_identified_calendar_bridge',
                                source_ids=sorted({s for r in fiscal.values() for s in r['sids']}),
                                formula='CY[y] = 0.75*MRV_actual_FY[y] + 0.25*MRV_actual_FY[y+1]',
                                parameters=dict(next_fiscal_year_weight=[.15,.25,.35],source_rounding_USD=500000),
                                limitations=['FY2022旧预算PDF使用泛称offsetting receipts；本包通过官方数据库明确MRV账户名与编号独立识别1644百万美元。',
                                             '2024数据库的FY2023为预测1883百万，未使用；FY2023实际2220百万来自2025数据库，匹配既有PDF。',
                                             'FY2019之前该账户在重组结构中为0；0未解释为签证免费，未由此回填历史收入。',
                                             '自然年期间权重15–35%是共同情景；国籍和用途未知，数量为空。']))

    def exchange_rates(self):
        selected={}
        releases={2013:'20130102',2016:'20160104',2019:'20190102',2022:'20220103',2026:'20260105'}
        # Exact previously archived official originals, newly registered with
        # package-local source IDs; no new network dependency during rebuild.
        for year,stamp in releases.items():
            path=ROOT/f'data/raw/history_expansion/fx_{year}.html'
            sid=self.source('fed_g5a_'+stamp,str(path.relative_to(ROOT)),f'https://www.federalreserve.gov/releases/g5a/{stamp}/',
                            'Board of Governors of the Federal Reserve System',f'G.5A annual FX release{stamp}; historical AUD/USD')
            soup=BeautifulSoup(path.read_text(),'html.parser')
            header=next(r for r in soup.select('table tr') if 'COUNTRY' in r.get_text() and 'CURRENCY' in r.get_text())
            years=[int(v) for v in re.findall(r'\b20\d{2}\b',header.get_text(' ',strip=True))]
            row=next(r for r in soup.select('table tr') if r.find(['th','td']) and r.find(['th','td']).get_text(' ',strip=True).replace('*','')=='AUSTRALIA')
            cells=[c.get_text(' ',strip=True) for c in row.find_all(['th','td'])]
            rates=[float(v.replace(',','')) for v in cells[2:]]
            for y,rate in zip(years,rates):
                if y in range(2011,2024):selected[y]=dict(fx_id=f'tmx_fed_{y}_AUD',year=y,currency='AUD',raw_rate=rate,
                                                        raw_direction='USD_per_currency',usd_per_unit=rate,source_id=sid,
                                                        source_locator=f'G.5A annual table; *AUSTRALIA DOLLAR; {y}',
                                                        method='year-specific Federal Reserve annual average, direct USD per AUD')
        self.check('all_australian_calendar_years_have_historical_AUD_FX',sorted(selected)==list(range(2011,2024)))
        self.fx.extend(selected[y] for y in sorted(selected))
        for year in (2021,2022):
            self.fx.append(dict(fx_id=f'tmx_identity_{year}_USD',year=year,currency='USD',usd_per_unit=1,
                                source_id=selected[year]['source_id'],source_locator='USD numeraire identity',method='USD identity'))

    def validate(self):
        self.check('unique_flow_ids',len(self.flows)==len({r['id'] for r in self.flows}))
        self.check('unique_observation_ids',len(self.obs)==len({r['observation_id'] for r in self.obs}))
        self.check('fifteen_new_receiver_years',len(self.flows)==15 and len(self.ranges)==15)
        self.check('all_sources_are_registered_originals',all(s['source_id'].startswith('tmx_') and (ROOT/s['local_path']).is_file() for s in self.sources))
        oids={r['observation_id'] for r in self.obs};fx={(r['currency'],r['year']) for r in self.fx}
        for row in self.flows:
            self.check('flow_bounds_references_and_no_fake_quantities',0<=row['lower']<=row['amount']<=row['upper'] and row['quantity'] is None and row['payer']=='UNK' and row['visa_group']=='other' and row['category_detail_status']=='unclassified' and set(row['source_ids'])<=self.source_ids and set(row['observation_ids'])<=oids,
                       receiver=row['receiver'],year=row['year'])
            self.check('flow_has_year_matched_FX',(row['currency'],row['year']) in fx,receiver=row['receiver'],year=row['year'])
        self.check('all_fx_source_ids_resolve',all(r['source_id'] in self.source_ids for r in self.fx))
        existing={}
        for path in (ROOT/'data/estimates').glob('*flows.json'):
            if path==EST:continue
            obj=read(path);rows=obj if isinstance(obj,list) else obj.get('flows',[])
            for row in rows:
                receiver=row.get('receiver',row.get('destination'))
                existing.setdefault((receiver,row.get('year')),[]).append(path.name)
        overlap=[dict(receiver=r['receiver'],year=r['year'],existing=sorted(set(existing[r['receiver'],r['year']]))) for r in self.flows if (r['receiver'],r['year']) in existing]
        self.check('no_receiver_year_overlap_existing_models',not overlap,overlap=overlap)
        for row in self.ranges:
            amount=sum(f['amount'] for f in self.flows if (f['receiver'],f['year'])==(row['receiver'],row['year']))
            self.check('destination_joint_amount_matches_edges',math.isclose(amount,row['amount'],abs_tol=.001),receiver=row['receiver'],year=row['year'])

    def write(self):
        for name,obj in [('sources',self.sources),('observations',self.obs),('fee_rules',[]),('fx',self.fx),('coverage',self.coverage),('checks',self.checks),('source_conflicts',self.conflicts)]:dump(OUT/(name+'.json'),obj)
        dump(EST,dict(flows=self.flows,models=self.models,destination_ranges=self.ranges))
        report=['# 历史财务扩展二：澳大利亚2011—2023、美国2021—2022','',
                '复算：`.research-venv/bin/python scripts/research_temporal_expansion_v2.py`。离线读取已归档官方原件，不联网。',
                '',f'新增{len(self.flows)}条费用分项、{len(self.models)}个模型、{len(self.obs)}条财年观察、{len(self.sources)}条来源登记、{len(self.fx)}条同年汇率，覆盖15个此前没有费用模型的收款方年度。所有费用边付款来源UNK、用途other/unclassified、quantity=null。',
                '', '## 澳大利亚','',
                '2011—2024财政年真实签证申请费收入取自DIAC/DIBP/HomeAffairs经审计财务报表原始叶科目。2011—2015称Visa application fees，2015/16后重分类为税收Visa Application Charges；2015比较值1,818,674千澳元在两种分类的相邻原件完全一致。其他移民服务、公民、签证证据费、旅客离境税和其他税项独立排除。包含境内、境外及适用移民申请，原件政策写明已收且匹配已递交申请时确认收入；这里只称实际已确认收入，不将整个财务科目等同境外签发量。',
                '', '每个自然年中心=前半年所属财年实收/确认值50%+后半年所属次财年值50%。次财年权重40%—60%与千元原表±500澳元构成共同期间情景。财政年原值、准确PDF页和列标签完整保留。未借用2024国籍或类别份额回填历史。',
                '', '## 美国MRV','',
                'GovInfo公开预算数据库2024/2025的Outlays工作簿明确标识账户571350和Machine-Readable Visa Fee, Consular and Border Security Programs名称。官方指南规定单位千美元、offsetting receipts记负数，2024版2022及以前、2025版2023及以前为actual。FY2019/20/21/22/23对应1847/896/826/1644/2220百万美元；2019/20/21/23与现有预算PDF控制一致。',
                '', '此前FY2022旧PDF表只显示泛称offsetting receipts，无法单独识别；本轮用明确账户数据库补证。CY2021=0.75×826m+0.25×1644m=1030.5m美元，CY2022=0.75×1644m+0.25×2220m=1788m美元。次财年权重15%—35%，并保留原表百万美元精度。2024数据库的FY2023=1883m属于预测，未入实际控制；以2025数据库实际2220m替代。',
                '', 'FY2019前该重组账户的0保留为来源结构信息，未据此推导历史真实签证收入为0，也未填入这些年度。MRV含边境通行卡；护照、移民签附加、抽签、担保、SEVIS和USCIS科目均排除。',
                '', '## 证据与期间','',
                '模型范围为期间分配情景，不是置信区间。实收/收入账户没有可配对的逐年付款事件数，不计算每申请人均额。原币金额换算使用相应自然年的Fed G.5A年均汇率；AUD方向是美元/澳元，USD为计价单位恒等。source_ids在包内全部注册，来源含原件路径、SHA和字节数。fee_rules为空，因为模型取财政叶科目实际金额，并未以标准价代替实收。',
                '', '| 收款方 | 自然年 | 中心原币 | 期间情景下界 | 期间情景上界 | 币种 |','|---|---|---:|---:|---:|---|']
        report.extend(f"| {r['receiver']} | {r['year']} | {r['amount']:,.0f} | {r['lower']:,.0f} | {r['upper']:,.0f} | {r['currency']} |" for r in self.ranges)
        (OUT/'README.md').write_text('\n'.join(report)+'\n')
        print(json.dumps(dict(flows=len(self.flows),models=len(self.models),observations=len(self.obs),sources=len(self.sources),fx=len(self.fx),coverage=len(self.coverage),checks=len(self.checks),passed=all(c['passed'] for c in self.checks)),ensure_ascii=False))


def main():
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    OUT.mkdir(parents=True,exist_ok=True)
    r=Research();r.australia();r.us_mrv();r.exchange_rates();r.validate();r.write()


if __name__=='__main__':main()
