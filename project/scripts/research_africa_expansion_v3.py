#!/usr/bin/env python3
"""Offline African visa-receipt expansion, excluding ETA and mixed accounts.

Somalia: federal Visa Fees receipts, separately from passports/work permits.
Zambia: Foreign Affairs code123092 Visa Fees only; Immigration totals excluded.
Kenya: retained EATV government share only; onward transfers are excluded.
"""
from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import sys
import zipfile

from pypdf import PdfReader

sys.dont_write_bytecode = True
logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/africa_expansion_v3'
OUT = ROOT / 'data/research/africa_expansion_v3'
EST = ROOT / 'data/estimates/africa_expansion_v3_flows.json'
ASOF = '2026-11-16'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
NAMES = {'SOM':'索马里','ZMB':'赞比亚','KEN':'肯尼亚'}


def compact(text):
    return re.sub(r'\s+', '', text)


class Research:
    def __init__(self):
        self.sources, self.obs, self.fees, self.fx = [], [], [], []
        self.flows, self.models, self.ranges, self.excluded = [], [], [], []

    def source(self, slug, filename, url, publisher, title, notes='', quality='official_original'):
        p = RAW / filename
        assert p.exists() and p.stat().st_size > 100, filename
        sid = 'afx_' + slug
        self.sources.append(dict(source_id=sid,url=url,publisher=publisher,title=title,
                                 retrieved_at=ASOF,source_quality=quality,
                                 local_path=str(p.relative_to(ROOT)),path=str(p.relative_to(ROOT)),
                                 bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                 archive_kind='original_document',notes=notes))
        return sid

    def observation(self, slug, destination, year, amount, currency, sid, locator, **extra):
        oid = 'afx_' + slug
        self.obs.append(dict(observation_id=oid,destination=destination,year=year,
                             metric=extra.pop('metric','visa_fee_actual_revenue'),
                             raw_metric=extra.pop('raw_metric','Visa Fees'),value=amount,unit=currency,
                             source_id=sid,source_ids=[sid],source_locator=locator,
                             nationality='UNK',origin_basis='unallocated',visa_group=extra.pop('visa_group','other'),
                             visa_type=extra.pop('visa_type','visa_fee_receipts'),
                             period_start=extra.pop('period_start',f'{year}-01-01'),
                             period_end=extra.pop('period_end',f'{year}-12-31'),
                             period_type=extra.pop('period_type','calendar_year'),
                             calculation_type=extra.pop('calculation_type','direct_observation'),**extra))
        return oid

    def flow(self, receiver, year, typ, label, group, amount, lower, upper, currency, sources,
             observations, notes, parameters, method, modeled=False):
        assert 0 <= lower <= amount <= upper
        self.flows.append(dict(id=f'afx_{receiver.lower()}_{year}_{typ}',payer='UNK',receiver=receiver,
                               year=year,visa_group=group,visa_type=typ,visa_label=label,
                               category_detail_status='classified' if group=='visitor' else 'unclassified',
                               amount=amount,lower=lower,upper=upper,currency=currency,quantity=None,
                               quantity_basis='actual_revenue_no_matching_application_denominator',
                               source_ids=list(dict.fromkeys(sources)),observation_ids=list(dict.fromkeys(observations)),
                               method_id=method,model_status='observed_receipts_calendar_bridge_estimate' if modeled else 'observed_receipts_partial',
                               calculation_type='conditional_scenario' if modeled else 'direct_observation',
                               origin_basis='unallocated',period_start=f'{year}-01-01',period_end=f'{year}-12-31',
                               period_type='calendar_year_model' if modeled else 'calendar_year',period_label=str(year),
                               notes=notes,parameters=parameters))
        self.ranges.append(dict(receiver=receiver,year=year,amount=amount,lower=lower,upper=upper,
                                currency=currency,range_method=parameters['range_method']))

    def somalia(self):
        sf = self.source('som_framework2027','som_framework2027.pdf',
                         'https://mof.gov.so/storage/documents/2026/11/1gdq4q6m/Budget%20Policy%20Framework%20Paper%20for%20FY2027.pdf',
                         'Federal Government of Somalia, Ministry of Finance, Budget Directorate',
                         'FY2027 Budget Policy Framework, October2026, Table27 historical actual columns',
                         'PDF p35 Table27: 2021–2025 Actual, 2026–2027 Budget. Only historical actual columns used. Fiscal year January–December. Federal receipts, not a sum of all member-state/Somaliland collections.')
        s24 = self.source('som_budget2024','som_budget2024.pdf',
                          'https://mof.gov.so/sites/default/files/Publications/2024%20END%20YEAR%20BUDGET%20PERFORMANCE%20REPORT_0.pdf',
                          'Federal Government of Somalia, Ministry of Finance, Budget Directorate',
                          'FY2024 End-Year Budget Performance Report',
                          'PDF p7 paragraph19, p33 Annex1 Visa Fees: USD8.26m actual, USD7.72m budget; separate passport and work-permit rows. Narrative US-administration chronology is inconsistent; not used to explain annual trend.')
        s25 = self.source('som_budget2025','som_budget2025.pdf',
                          'https://www.mof.gov.so/sites/default/files/Publications/FGS%202025%20end-year%20budget%20performance%20report.%20.pdf',
                          'Federal Government of Somalia, Ministry of Finance, Budget Directorate',
                          'FY2025 End-Year Budget Performance Report, prepared1March2026',
                          'PDF p37 Annex1 code142201 Visa Fees: USD8.52m actual versus USD13.64m budget. Not immigration total, passport, work permit, passenger fee or OTA/ETA.')
        t = PdfReader(RAW/'som_framework2027.pdf').pages[34].extract_text()
        line = next(line for line in t.splitlines() if 'Visa Fees' in line)
        assert re.findall(r'\d+\.\d+',line)[:7] == ['3.9','7.5','8.7','8.3','8.5','8.9','9.1'],line
        (OUT/'som_framework_actual_table.txt').write_text(t)
        t24 = PdfReader(RAW/'som_budget2024.pdf').pages[32].extract_text()
        t25 = PdfReader(RAW/'som_budget2025.pdf').pages[36].extract_text()
        line24 = next(line for line in t24.splitlines() if 'Visa Fees' in line)
        line25 = next(line for line in t25.splitlines() if 'Visa Fees' in line)
        assert re.findall(r'\d+\.\d+',line24)[:6] == ['7.72','1.96','2.14','2.54','1.62','8.26'],line24
        assert re.findall(r'\d+\.\d+',line25)[:6] == ['13.64','1.82','1.99','1.89','2.81','8.52'],line25
        (OUT/'som_2024_visa_receipt_table.txt').write_text(t24)
        (OUT/'som_2025_visa_receipt_table.txt').write_text(t25)
        money = {2021:(3.9,.1,sf,'PDF p35 Table27:2021 Actual'),
                 2022:(7.5,.1,sf,'PDF p35 Table27:2022 Actual'),
                 2023:(8.7,.1,sf,'PDF p35 Table27:2023 Actual'),
                 2024:(8.26,.01,s24,'PDF p33 Annex1:Visa Fees; p7 paragraph19'),
                 2025:(8.52,.01,s25,'PDF p37 Annex1 code142201:Actual2025 Total')}
        for year,(million,unit,sid,locator) in money.items():
            amount=million*1000000
            oid=self.observation(f'som_{year}_actual_visa','SOM',year,amount,'USD',sid,locator,
                                 reported_value=million,reported_unit='million USD',rounding_unit_USD=unit*1000000,
                                 account_scope='Federal Government Visa Fees line only; not all federal member states or Somaliland',
                                 notes='真实联邦签证费收款；未把其他移民服务收入归为签证。报告金额以百万美元四舍五入。')
            params=dict(actual_receipts_observed=True,government_scope='Federal Government of Somalia',
                        account_code='142201' if year==2025 else 'Visa Fees',
                        published_precision_USD=unit*1000000,rounding_half_unit_USD=unit*500000,
                        excluded=['passport fees','work-permit taxes','airport/passenger fees','non-federal collections'],
                        nationality_allocation='none',range_method='中心为官方实收，区间仅表示原报告四舍五入半单位，不是估算置信区间')
            self.flow('SOM',year,'federal_visa_fee_receipts','联邦政府签证费实收','other',amount,
                      amount-unit*500000,amount+unit*500000,'USD',[sid],[oid],
                      '索马里联邦政府Visa Fees单列实收，按报告精度保留；未包括护照、工作许可或机场费，未声称覆盖所有地方政府及索马里兰。付款国籍与用途未拆，没有匹配申请人数。',
                      params,'afx_som_federal_actual_receipts')
        # Save quarterly actuals for a real subannual evidence layer, not extra ledger edges.
        for year,values,sid,page in [(2024,[1.96,2.14,2.54,1.62],s24,33),(2025,[1.82,1.99,1.89,2.81],s25,37)]:
            for q,value in enumerate(values,1):
                month=(q-1)*3+1;end=q*3
                endday=30 if end in (6,9) else 31
                self.observation(f'som_{year}_q{q}_actual_visa','SOM',year,value*1000000,'USD',sid,
                                 f'PDF p{page} Annex1 Visa Fees Q{q}',period_start=f'{year}-{month:02d}-01',
                                 period_end=f'{year}-{end:02d}-{endday}',period_type='calendar_quarter',
                                 reported_value=value,reported_unit='million USD',eligible_money_ledger=False,
                                 notes='真实季度收款；金额已由年度Visa Fees总行覆盖，不能与全年金额再相加。季度与年度独立取整可有1万美元差。')
        self.models.append(dict(model_id='afx_som_federal_actual_receipts',destination='SOM',years=list(money),
                                status='observed_annual_federal_visa_receipts',formula='Published federal Visa Fees actual; no arrivals or tariff multiplication',
                                limitations=['联邦政府账户覆盖，不等同所有地区或索马里兰收入。',
                                             '2021—2023精度0.1百万美元；2024—2025精度0.01百万美元。',
                                             '仅原始金额取整区间，不是置信区间。','没有国籍或匹配付费申请人数，保留UNK。']))

    def zambia(self):
        entries=[(2019,'zmb_full2021.pdf',27,
                  'https://www.cabri-sbo.org/uploads/bia/Zambia_2021_Approval_External_EnactedBudget_MinistryOfFinanceAndNationalPlanning_SADCCOMESA_English_9daf4d.pdf',17913423,'xxvii'),
                 (2020,'zmb_full2022.pdf',22,
                  'https://www.parliament.gov.zm/sites/default/files/images/publication_docs/2022%20YELLOW%20BOOK.pdf',4514463,'xvii'),
                 (2021,'zmb_full2023.pdf',24,
                  'https://www.parliament.gov.zm/sites/default/files/images/publication_docs/07%20Main%20Report%20Budget%202023%20%282%29.pdf',7535637,'xxv')]
        for year,filename,page,url,amount,printed in entries:
            sid=self.source(f'zmb_budget{year+2}',filename,url,
                            'Republic of Zambia, Ministry of Finance / National Assembly of Zambia',
                            f'{year+2} Yellow Book: Revenue, Grants and Financing, Head17 Visa Fees, {year} Actual',
                            f'PDF p{page+1}, printed{printed}, Head17 Foreign Affairs code123092 Visa Fees. Actual{year} column; following two columns are estimates. Foreign Affairs visa receipts only, separate from passport/TDI and broad Immigration Fees and Charges.',
                            'official_original' if year!=2019 else 'official_document_archived_by_CABRI')
            t=PdfReader(RAW/filename).pages[page].extract_text()
            assert str(amount) in compact(t).replace(',','') and '123092' in t and f'{year} Actual' in t,(year,amount)
            assert 'Visa Fees' in t
            (OUT/f'zmb_{year}_actual_visa_table.txt').write_text(PdfReader(RAW/filename).pages[page].extract_text(extraction_mode='layout'))
            oid=self.observation(f'zmb_{year}_mfa_actual_visa','ZMB',year,amount,'ZMW',sid,
                                 f'PDF p{page+1} / printed{printed}; Head17; code123092; {year} Actual',
                                 raw_metric='123092 Visa Fees / Head17 Ministry of Foreign Affairs',
                                 account_scope='Foreign Affairs collections only; excludes broad domestic Immigration Fees and Charges',
                                 notes='纯签证费实际列；不是相邻年度预算。仅外交部收款子集，不等同全国全部签证费。')
            params=dict(actual_receipts_observed=True,account_code='123092',collecting_department='Head17 Foreign Affairs',
                        government_scope='Foreign Affairs visa-fee account subset',
                        excluded=['123020 Passport Fees','123090 TDI(Foreign)','123018 Immigration Fees and Charges'],
                        nationality_allocation='none',range_method='独立Visa Fees实际收款，原币精确数；不扩为全国签证总额')
            self.flow('ZMB',year,'foreign_affairs_visa_fee_receipts','外交部签证费实收','other',amount,amount,amount,'ZMW',
                      [sid],[oid],'赞比亚预算黄皮书在外交部第17部门单列123092 Visa Fees实际收款；只覆盖该收款子集，移民机关广义许可与收费总项、护照及旅行证费用均未计入。付款国籍与用途未拆。',
                      params,'afx_zmb_mfa_actual_receipts')
        self.models.append(dict(model_id='afx_zmb_mfa_actual_receipts',destination='ZMB',years=[2019,2020,2021],
                                status='observed_foreign_affairs_visa_receipts_partial',
                                formula='Head17 code123092 Visa Fees / Actual column, in ZMW',
                                limitations=['外交部收款子集，不等同全国全部签证收款。','相邻两列预算完全排除。',
                                             '移民机关收费大项含许可和其他收费，未按比例臆拆为签证。','无付款国籍和申请件数。']))

    def kenya(self):
        # Retained Kenyan share, including Kenya entitlement from partner collections,
        # never gross stickers sold and never government-to-government payer edges.
        files=[('2022','ken_eatv2022.pdf',
                'https://libraryir.parliament.go.ke/server/api/core/bitstreams/6daa2162-46bc-4d13-81c9-29dcbe548373/content')]
        sources,readers,texts={},{},{}
        for year,filename,url in files:
            sid=self.source(f'ken_eatv_fy{year}',filename,url,
                            'Office of the Auditor-General of Kenya / National Treasury, archived by National Assembly',
                            f'East Africa Tourist Visa Fee Collection Account, year ended30June{year}',
                            'Cash-basis EATV account: receipts from stickers are before partner sharing; note13.4(or equivalent) is Kenyan retained40% plus Kenya entitlement received from Uganda/Rwanda. Do not count both gross and retained. Not ETA, passports, ordinary mixed consular services or immigration permits.')
            sources[int(year)]=sid
            readers[int(year)]=PdfReader(RAW/filename)
            texts[int(year)]=[page.extract_text() for page in readers[int(year)].pages]
        # Frozen report rows and page assertions. Add only annual observations that can
        # be traced to the actual National Treasury Receiver of Revenue transfer line.
        t22=texts[2022][39]
        assert '104,076,119.00' in t22 and '5,496,020.00' in t22 and 'Kenya Component' in t22
        annual={2021:(5496020,sources[2022],40),2022:(104076119,sources[2022],40)}
        oids={}
        for fy,(amount,sid,page) in sorted(annual.items()):
            oids[fy]=self.observation(f'ken_fy{fy}_retained_eatv','KEN',fy,amount,'KES',sid,
                                      f'PDF p{page}:Transfer of EATV revenue to National Treasury Receiver of Revenue, total Kenyan entitlement',
                                      metric='eatv_retained_kenyan_government_revenue',raw_metric='Kenyan40% share plus receipts from Uganda and Rwanda',
                                      visa_group='visitor',visa_type='east_africa_tourist_visa_retained_share',
                                      period_start=f'{fy-1}-07-01',period_end=f'{fy}-06-30',period_type='fiscal_year',
                                      eligible_money_ledger=False,
                                      notes='实际肯尼亚应留签证份额，伙伴国转来的是肯尼亚签证分账收入，不把政府当作申请国籍；财政年度先留原始观测，再桥接自然年。')
        for year in sorted(annual):
            if year+1 not in annual or year>2023:continue
            a,b=annual[year][0],annual[year+1][0]
            center=(a+b)/2
            # Independent half-FY placement sensitivities. This is intentionally not
            # a statistical confidence interval nor an identified calendar bound.
            lower=.35*(a+b);upper=.65*(a+b)
            params=dict(actual_fiscal_receipts_observed=True,calendar_receipts_observed=False,
                        fiscal_year_end_june30=year,fiscal_receipts_KES=a,next_fiscal_receipts_KES=b,
                        calendar_weights=[.5,.5],each_fiscal_half_weight_range=[.35,.65],
                        account_scope='Kenya retained EATV share only',partner_transfers_excluded=True,
                        government_to_government_transfers_are_not_applicant_nationality=True,
                        nationality_allocation='none',excluded=['gross sticker sales','Uganda/Rwanda entitlements','ETA','passport fees','mixed consular services'],
                        range_method='相邻7月至6月财年实收各取1/2桥接自然年；每个半财年35%—65%分配为工作情景，非置信区间')
            self.flow('KEN',year,'retained_eatv_calendar_bridge','东非旅游联签肯尼亚留存收入','visitor',
                      center,lower,upper,'KES',[annual[year][1],annual[year+1][1]],[oids[year],oids[year+1]],
                      '仅肯尼亚应留的东非旅游联签EATV份额：财政账户明确扣除转卢旺达及乌干达的份额，伙伴国交来的肯尼亚应得额保留。自然年由相邻7月至6月财年各取一半；上下为半财年分配情景，不是全年观测实收。未含ETA、普通签证或其他领事收费。付款国籍未知。',
                      params,'afx_ken_retained_eatv_calendar_bridge',True)
        self.models.append(dict(model_id='afx_ken_retained_eatv_calendar_bridge',destination='KEN',
                                years=sorted(f['year'] for f in self.flows if f['receiver']=='KEN'),
                                status='observed_fiscal_retained_visa_receipts_calendar_bridge',
                                formula='0.5 * retained_EATV_FY[year] + 0.5 * retained_EATV_FY[year+1]',
                                limitations=['只涵盖EATV肯尼亚留存，非肯尼亚全部签证费。','自然年为相邻财年均匀分配，不是逐月实收。',
                                             '35%—65%半财年分配是工作情景，不能称置信区间。',
                                             '转伙伴国的款不归肯尼亚；伙伴国转来款无申请国籍，不把Uganda/Rwanda误写为付款方。',
                                             '不含2024年实施的ETA，不用游客数乘签证费。']))

    def exchange_rates(self):
        sid=self.source('wb_exchange_rates','wb_fx_dataset.zip',
                         'https://api.worldbank.org/v2/en/indicator/PA.NUS.FCRF?downloadformat=csv',
                         'World Bank / IMF International Financial Statistics',
                         'WDI PA.NUS.FCRF official exchange rate, LCU per USD, period average',
                         'Full official CSV archive; individual JSON API blocked by WAF. Kenya KES, Zambia ZMW (not obsolete pre2013 ZMK). Use year-matched annual average rates.')
        z=zipfile.ZipFile(RAW/'wb_fx_dataset.zip')
        filename=next(n for n in z.namelist() if n.startswith('API_'))
        rows=list(csv.reader(io.StringIO(z.read(filename).decode('utf-8-sig'))))
        header=rows[4]
        by_country={r[1]:dict(zip(header,r)) for r in rows[5:] if len(r)>1}
        keys={(f['receiver'],f['year'],f['currency']) for f in self.flows if f['currency']!='USD'}
        for country,year,currency in sorted(keys):
            value=float(by_country[country][str(year)])
            assert value>0
            self.fx.append(dict(fx_id=f'afx_wb_{country.lower()}_{year}',year=year,currency=currency,
                                raw_rate=value,raw_direction='currency_per_USD',usd_per_unit=1/value,
                                source_id=sid,source_ids=[sid],source_locator=f'{filename}; CountryCode={country}; year={year}; PA.NUS.FCRF',
                                method='World Bank / IMF annual official exchange rate, period average'))

    def finish(self):
        sids={s['source_id'] for s in self.sources};oids={o['observation_id'] for o in self.obs}
        assert len(sids)==len(self.sources) and len(oids)==len(self.obs)
        assert len({f['id'] for f in self.flows})==len(self.flows)
        for f in self.flows:
            assert set(f['source_ids'])<=sids and set(f['observation_ids'])<=oids
            assert f['payer']=='UNK' and f['quantity'] is None
            assert f['visa_type'] not in ['eta','passport','immigration_fees_and_charges']
        assert all(o.get('eligible_money_ledger') is False for o in self.obs if o['period_type'] in ('calendar_quarter','fiscal_year'))
        for r in self.ranges:
            ff=[f for f in self.flows if f['receiver']==r['receiver'] and f['year']==r['year']]
            for key in ('amount','lower','upper'):assert abs(sum(f[key] for f in ff)-r[key])<.01
        fxkeys={(f['year'],f['currency']) for f in self.fx}
        assert {(f['year'],f['currency']) for f in self.flows if f['currency']!='USD'}<=fxkeys
        scopes={(f['receiver'],f['year']) for f in self.flows};overlap=[];checked=[]
        for p in sorted(EST.parent.glob('*_flows.json')):
            if p==EST:continue
            checked.append(str(p.relative_to(ROOT)))
            for f in json.loads(p.read_text()).get('flows',[]):
                if (f.get('receiver'),f.get('year')) in scopes:overlap.append((p.name,f.get('id')))
        assert not overlap,overlap
        coverage=[]
        for code in NAMES:
            years=sorted({f['year'] for f in self.flows if f['receiver']==code})
            for year in years:
                for group in GROUPS:
                    ff=[f for f in self.flows if f['receiver']==code and f['year']==year and f['visa_group']==group]
                    actual=bool(ff) and code!='KEN';modeled=bool(ff) and code=='KEN'
                    coverage.append(dict(code=code,destination=code,name=NAMES[code],region='非洲',year=year,visa_group=group,
                                         status='amount_modeled' if modeled else 'amount_known' if actual else 'not_found',
                                         fee_known=False,fee_current_snapshot_known=False,quantity_known=False,quantity_context_known=False,
                                         category_detail_status='classified_aggregate' if code=='KEN' and ff else 'unclassified_aggregate' if ff else 'no_classified_observation',
                                         arrival_context_known=False,amount_known=actual,amount_modeled=modeled,nationality_known=False,
                                         notes=ff[0]['notes'] if ff else '未取得本用途单独金额；只保留已有签证账户覆盖，不从宽口径移民费拆估。',
                                         source_ids=list(dict.fromkeys(s for f in ff for s in f['source_ids'])),searched_as_of=ASOF))
        totals={f"{f['receiver']}_{f['year']}_{f['currency']}":f['amount'] for f in self.flows}
        checks=dict(as_of=ASOF,sources=len(sids),observations=len(oids),fees=len(self.fees),fx=len(self.fx),flows=len(self.flows),
                    receivers=sorted({f['receiver'] for f in self.flows}),years=sorted({f['year'] for f in self.flows}),
                    coverage_rows=len(coverage),totals_native=totals,all_payers_unknown=True,
                    no_duplicate_existing_receiver_year=True,overlap_checked_packages=checked,
                    all_quarter_and_fiscal_observations_excluded_as_direct_edges=True,
                    all_cash_sources_are_visa_specific=True,eta_passport_work_permit_mixed_immigration_excluded=True,
                    no_arrival_times_fee_model=True,no_claimed_application_denominators=True,
                    provenance='frozen original document hashes; amount rows and actual-year headers asserted; FX data from official CSV archive; ranges reconcile; all source/observation IDs resolve')
        package=dict(package='africa_expansion_v3',as_of=ASOF,flows=self.flows,models=self.models,
                     destination_ranges=self.ranges,subtotals=[],coverage_rows=len(coverage),
                     scope='Somalia federal Visa Fees annual actual2021–25; Zambia MFA code123092 actual2019–21 subset; Kenya retained EATV fiscal cash calendar bridges; no ETA or mixed immigration totals')
        for filename,obj in [('sources.json',self.sources),('observations.json',self.obs),('fee_rules.json',self.fees),
                             ('fx.json',self.fx),('coverage.json',coverage),('checks.json',checks),('search_log.json',[
                                 dict(destination='SOM',result='Visa Fees separate from passports/work permits;2021–25 actual columns;2024/25 quarterly rows kept without annual double count',searched_at=ASOF),
                                 dict(destination='ZMB',result='Foreign Affairs Visa Fees actual code123092; broad Immigration Fees and Charges excluded; current2024/25 spending-only OBB not treated as actual receipt',searched_at=ASOF),
                                 dict(destination='KEN',result='EATV retained government share only; gross partner transfers excluded; ordinary visa+consular mix excluded; ETA excluded',searched_at=ASOF),
                                 dict(destination='MDG',result='OECD sales of goods/services includes visa stamps plus other items; excluded as non-isolated amount',searched_at=ASOF),
                                 dict(destination='RWA',result='Current waiver/fee rules found, but no reliable matching historical total; research-permit visas from NISR are not travel visa issuances',searched_at=ASOF),
                                 dict(destination='EGY',result='Tourist arrivals not a paid-visa quantity; no multiplication',searched_at=ASOF)])]:
            (OUT/filename).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
        EST.write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(checks,ensure_ascii=False))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    r=Research();r.somalia();r.zambia();r.kenya();r.exchange_rates();r.finish()


if __name__=='__main__':main()
