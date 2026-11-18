#!/usr/bin/env python3
"""Offline Gambia visa-fee receipts and budget evidence.

Run with .research-venv/bin/python. PDFium handles embedded table fonts whose
character mapping pypdf misses. The native annual receipt series and conflicts
are rebuilt from frozen primary PDFs, not transcribed search snippets.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import sys
import zipfile

import pypdfium2 as pdfium

sys.dont_write_bytecode = True
logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/africa_expansion_v6'
OUT = ROOT / 'data/research/africa_expansion_v6'
ASOF = '2026-11-17'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
PREFIX = 'af6_'

# URL identity was checked against original downloaded bytes. Changes require
# explicit evidence review, rather than silently accepting a replaced PDF.
DOCUMENTS = [
 ('gmb_budget2022', 'gmb_budget2022.pdf',
  'https://mofea.gov.gm/wp-content/uploads/2024/09/2022-approved-budget.pdf',
  'Gambia Ministry of Finance and Economic Affairs', '2022 Approved Budget',
  '359ff55f4a4bc5c24110b2793e2db8c50fea68c1b1ba1d013500cc841d3dcfe0',
  'p32 summary GMD000; pp35-36 agency detail GMD; 2020 Actual. Positive receipt sign is the absolute accounting credit.'),
 ('gmb_budget2023', 'gmb_budget2023.pdf',
  'https://mofea.gov.gm/wp-content/uploads/2024/09/ESTIMATES-OF-REVENUE-AND-EXPENDITURE-2023.pdf',
  'Gambia Ministry of Finance and Economic Affairs', '2023 Estimates of Revenue and Expenditure',
  '54132ea9f95f2e462ce82385e871db5ed792224a59b18fee625a17e06d17f85f',
  'p37 summary GMD000; pp40-41 detail GMD; 2021 Actual.'),
 ('gmb_budget2024', 'gmb_budget2024.pdf',
  'https://mofea.gov.gm/wp-content/uploads/2024/09/Estimates-of-Revenue-and-expenditure-2024.pdf',
  'Gambia Ministry of Finance and Economic Affairs', '2024 Estimates of Revenue and Expenditure',
  '46f43c01fa9d29351681998b91f5f9208b3a5c3c5db4a5600c4097480b129881',
  'p44 summary and pp47-48 agency detail contain anomalous 2022 Actual; superseded for ledger by 2022 public-account trial balance.'),
 ('gmb_budget2025', 'gmb_budget2025.pdf',
  'https://mofea.gov.gm/wp-content/uploads/2025/01/2025_Approved_Budget-Final.pdf',
  'Gambia Ministry of Finance and Economic Affairs', '2025 Approved Budget - Final',
  'b655267bad30a83c045692d35decf8a0f25fc09c66bceea7248e4319d304c299',
  'p48 summary GMD000; pp51-52 agency detail GMD; 2023 Actual and 2025 Estimate. Footer identifies Approved Estimates / adopted Budget Law.'),
 ('gmb_budget2026', 'gmb_budget2026_full_proposal.pdf',
  'https://mofea.gov.gm/wp-content/uploads/2025/11/FY2026-Budget-Estimates-Executive-Budget-Proposals-31.10.25.pdf',
  'Gambia Ministry of Finance and Economic Affairs', 'FY2026 Executive Budget Proposals, 31 October 2025',
  'd2652c44d92f0124efc1d23e136c7b3d921f39cb835234cdc051da61e925c05b',
  'p50 summary GMD000; p54 detail GMD; 2024 Actual differs slightly from 2024 audit trial balance; 2025 Approved confirms the prior budget, not actual 2025 receipts. 2026 Estimate is retained only as budget context.'),
 ('gmb_accounts2022', 'gmb_publicaccounts2022.pdf',
  'https://nao.gm/wp-content/uploads/2025/09/GoTG-2022-Financial-Statements-Audit-Report-and-AG-Certificate-1.pdf',
  'National Audit Office of The Gambia / Government of The Gambia', '2022 Government Financial Statements, Audit Report and Auditor General Certificate',
  'f89f223d65bbf0bbea6f1360e4f1ae04ec9a6a98cc9b587966c48c8ea01431ab',
  'p152 code1422177 Visa Fees CR22,827,551.80. p151 trial balance heading and p54 reporting period explicitly establish 2022; recurring footer saying 2021 is stale. p54 amounts expressed in GMD. Overall audit opinion p3 is adverse, not a clean opinion.'),
 ('gmb_accounts2024', 'gmb_publicaccounts2024.pdf',
  'https://nao.gm/wp-content/uploads/2025/12/AGs-Report_2024_091225-Final-Report-24-1.pdf',
  'National Audit Office of The Gambia / Government of The Gambia', '2024 Government Financial Statements and Auditor General Report',
  'd5c8c255f8ddcda8178b5a8abe4d960b5b928e35f861b277ec00c44b154f3c09',
  'p139 code1422177 Visa Fees CR22,982,402.82. p138 trial balance dated31December2024; p40 amounts expressed in GMD and Jan-Dec2024. Overall audit opinion p3 adverse. PDF metadata title2011 is stale; internal document controls establish2024.'),
]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class Research:
    def __init__(self):
        self.sources, self.observations, self.flows, self.fx = [], [], [], []
        self.models, self.ranges, self.conflicts, self.excluded = [], [], [], []
        self.docs = {}
        self.actual_oids, self.budget_oids = {}, {}
        self.actual_values, self.budget_values = {}, {}

    def load_sources(self):
        for slug, filename, url, publisher, title, expected_hash, notes in DOCUMENTS:
            p = RAW / filename
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            assert digest == expected_hash, (filename, digest)
            self.sources.append(dict(source_id=PREFIX+slug, url=url, publisher=publisher,
                                     title=title, retrieved_at=ASOF,
                                     source_quality='official_original', local_path=str(p.relative_to(ROOT)),
                                     path=str(p.relative_to(ROOT)), bytes=p.stat().st_size,
                                     sha256=digest, archive_kind='original_document', notes=notes))
            self.docs[slug] = pdfium.PdfDocument(p)

    def page(self, slug, pageno):
        t = self.docs[slug][pageno-1].get_textpage().get_text_range().replace('\r\n', '\n')
        (OUT / f'{slug}_p{pageno}_pdfium.txt').write_text(t)
        return t

    @staticmethod
    def visa_row(text, occurrence=0):
        rows = [line for line in text.splitlines() if re.search(r'\b1422177\b', line) and 'Visa Fees' in line]
        assert len(rows) > occurrence, rows
        row = rows[occurrence]
        nums = re.findall(r'(?<!\d)[(]?\d[\d,]*(?:\.\d+)?[)]?', row.split('Visa Fees', 1)[1])
        values = [float(s.strip('()').replace(',', '')) for s in nums]
        return row, values

    def observe(self, slug, year, value, sid, page, metric, raw_metric, **extra):
        oid = PREFIX+slug
        self.observations.append(dict(observation_id=oid, destination='GMB', year=year,
                                      metric=metric, raw_metric=raw_metric, value=value, unit='GMD',
                                      source_id=PREFIX+sid, source_ids=[PREFIX+sid],
                                      source_locator=f'PDF p{page}; code1422177 Visa Fees; '+extra.pop('locator', ''),
                                      nationality='UNK', origin_basis='unallocated', visa_group='other',
                                      visa_type='visa_fee_receipts', eligible_money_ledger=False,
                                      period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                                      period_type='calendar_year', calculation_type=extra.pop('calculation_type', 'direct_observation'),
                                      **extra))
        return oid

    def agency_table(self, doc, actual_year, pages, actual_values, summary_page, rounded_total,
                     budget_year=None, budget_values=None):
        total = 0
        actual_oids, budget_oids = [], []
        for agency, page, actual, index in zip(('interior08', 'foreign_affairs10'), pages, actual_values, (0, 0 if pages[0] != pages[1] else 1)):
            t = self.page(doc, page)
            assert 'Dalasi' in t and 'Actual' in t and str(actual_year) in t
            assert 'MINISTRY OF INTERIOR' in t if agency=='interior08' else 'MINISTRY OF FOREIGN AFFAIRS' in t
            row, values = self.visa_row(t, index)
            assert values[0] == actual, (doc, row, values, actual)
            total += actual
            actual_oids.append(self.observe(f'gmb_{actual_year}_{agency}_reported_actual', actual_year,
                                           actual, doc, page, 'visa_fee_reported_actual_revenue',
                                           f'1422177 Visa Fees / {agency} / Actual',
                                           account_scope=agency, reported_precision_GMD=1,
                                           receipt_status='reported_actual_in_budget_comparator',
                                           accounting_credit_shown_in_parentheses=True,
                                           selected_for_money_flow=actual_year not in (2022, 2024),
                                           notes='机构签证费实收历史列；括号为收入贷方展示，流入取正值；未混入护照、移民综合或领事服务。'))
            if budget_year is not None:
                amount = budget_values[0 if agency=='interior08' else 1]
                assert values[2] == amount, (doc, row, amount)
                budget_oids.append(self.observe(f'gmb_{budget_year}_{agency}_budget_{doc}', budget_year,
                                               amount, doc, page, 'visa_fee_budget_estimate',
                                               f'1422177 Visa Fees / {agency} / Estimate',
                                               account_scope=agency, budget_not_actual=True,
                                               selected_for_money_flow=budget_year==2025,
                                               reported_precision_GMD=1,
                                               notes='独立签证预算科目；不是同期实际收款。'))
        summary = self.page(doc, summary_page)
        assert "('000s)" in summary or "(’000s)" in summary
        _, rounded = self.visa_row(summary)
        assert rounded[0] == rounded_total
        assert round(total/1000) == rounded_total, (doc, total, rounded_total)
        summary_oid = self.observe(f'gmb_{actual_year}_summary_thousand_control', actual_year,
                                   rounded_total*1000, doc, summary_page,
                                   'visa_fee_summary_rounding_control_not_extra_revenue',
                                   '1422177 Visa Fees / economic-classification summary',
                                   reported_value=rounded_total, reported_scale=1000,
                                   reported_precision_GMD=1000, selected_for_money_flow=False,
                                   agency_detail_total_GMD=total,
                                   notes='千达拉西汇总用于核对两机构互斥明细，不再作为额外流量。')
        self.actual_oids[actual_year] = actual_oids+[summary_oid]
        self.actual_values[actual_year] = total
        if budget_year:
            self.budget_oids[budget_year] = budget_oids
            self.budget_values[budget_year] = sum(budget_values)
        return total

    def budget_receipts(self):
        self.agency_table('gmb_budget2022', 2020, [35, 36], [2414500, 11147396], 32, 13562)
        self.agency_table('gmb_budget2023', 2021, [40, 41], [4042250, 21714694], 37, 25757)
        self.agency_table('gmb_budget2024', 2022, [47, 48], [2780150, 528858772], 44, 531639)
        self.agency_table('gmb_budget2025', 2023, [51, 52], [4472000, 16445303], 48, 20917,
                          budget_year=2025, budget_values=[6140556, 11770268])
        # Two disjoint collecting-agency rows share this page in FY2026 book.
        self.agency_table('gmb_budget2026', 2024, [54, 54], [5885000, 17292085], 50, 23177,
                          budget_year=2026, budget_values=[9243648, 18933028])
        t = self.page('gmb_budget2026', 54)
        for index, agency, amount in [(0, 'interior08', 6140556), (1, 'foreign_affairs10', 11770268)]:
            _, values = self.visa_row(t, index)
            assert values[1] == amount
            self.observe(f'gmb_2025_{agency}_confirmed_approved', 2025, amount, 'gmb_budget2026', 54,
                         'visa_fee_prior_year_approved_budget_control',
                         f'1422177 Visa Fees / {agency} / 2025 Approved',
                         budget_not_actual=True, selected_for_money_flow=False,
                         notes='2026预算书确认2025已批预算，作为预算身份控制，不重复加入2025流量。')

    def audit_receipts(self):
        for year, page, title_page, policy_page, expected in [(2022,152,151,54,22827551.80), (2024,139,138,40,22982402.82)]:
            doc = f'gmb_accounts{year}'
            title = self.page(doc, title_page)
            policy = self.page(doc, policy_page)
            opinion = self.page(doc, 3)
            t = self.page(doc, page)
            assert 'TRIAL BALANCE' in title and str(year) in title
            assert 'expressed in GMD' in policy and str(year) in policy and '31' in policy and 'January' in policy
            assert 'Adverse Opinion' in opinion
            row, values = self.visa_row(t)
            assert values == [expected], row
            oid = self.observe(f'gmb_{year}_trial_balance_visa_reported_receipts', year, expected,
                               doc, page, 'visa_fee_reported_actual_revenue',
                               '1422177 Visa Fees / consolidated trial balance / CR',
                               account_scope='consolidated_government_visa_fee_leaf1422177',
                               selected_for_money_flow=True, reported_precision_GMD=.01,
                               overall_audit_opinion='adverse', clean_audit_opinion=False,
                               period_control_locator=f'PDF p{title_page} trial balance heading; p{policy_page} reporting currency and period',
                               notes='官方合并试算表签证收入贷方；金额按报告记录。整体财报审计为否定意见，不称无保留核实实收。'+
                                     ('部分页脚残留2021，年度按试算表标题与会计政策明确2022确定。' if year==2022 else 'PDF元数据标题残留2011，年度按正文和试算表标题明确2024确定。'))
            previous = self.actual_values[year]
            self.conflicts.append(dict(destination='GMB', year=year, metric='visa_fee_reported_actual_revenue',
                                       selected_source_id=PREFIX+doc, selected_observation_id=oid,
                                       selected_amount_GMD=expected,
                                       alternative_source_id=PREFIX+f'gmb_budget{year+2}',
                                       alternative_observation_ids=self.actual_oids[year],
                                       alternative_amount_GMD=previous,
                                       alternative_minus_selected_GMD=round(previous-expected,2),
                                       resolution='Use later published government-account consolidated visa-fee leaf; retain budget comparator as conflicting evidence; do not average or add.',
                                       audit_opinion_preserved='adverse'))
            self.actual_values[year] = expected
            self.actual_oids[year] = [oid]

    def flows_and_models(self):
        for year in range(2020, 2026):
            budget = year==2025
            amount = self.budget_values[year] if budget else self.actual_values[year]
            oids = self.budget_oids[year] if budget else self.actual_oids[year]
            observations = [o for o in self.observations if o['observation_id'] in oids]
            sids = list(dict.fromkeys(s for o in observations for s in o['source_ids']))
            typ = 'government_visa_budget_run_rate' if budget else 'government_visa_reported_receipts'
            method = PREFIX+'gmb_'+typ
            precision = 1 if year in (2020,2021,2023) else .005
            lower, upper = (amount*.7, amount*1.3) if budget else (amount-precision, amount+precision)
            range_method = ('2025官方已批签证预算×100%执行率为中心，70%—130%为条件情景，非实收、置信区间或经验上下界。' if budget else
                            '仅表示原表公布精度的半单位取整区间；非财报真实性或完整性的不确定性区间。')
            notes = ('冈比亚内政部08和外交部10签证叶科目1422177的2025已批预算之和；执行率100%为中心、70%—130%情景。' if budget else
                     f'冈比亚{year}年1422177签证费报告实际收入。'+
                     ('采用合并政府账户试算表；整体财报审计为否定意见。' if year in (2022,2024) else '采用随后预算书明确Actual的两机构明细之和，并与千达拉西汇总对账。'))
            notes += '不含护照、综合移民费、工作及居留许可、其他领事服务、Securiport或银行余额；付款国籍和付费申请数未知。'
            params = dict(account_code='1422177', account_scope='government reported Visa Fees only',
                          nationality_allocation='none', paid_application_denominator=None,
                          budget_not_actual=budget, range_method=range_method,
                          summary_is_control_not_extra_edge=True,
                          excluded=['Passport Fees','Immigration fees','Work permit fees','Other Consular Services','Securiport Fees','VISA FEE bank-account asset balance'])
            if budget:
                params.update(approved_budget_GMD=amount, budget_realization_center=1,
                              budget_realization_scenario=[.7,1.3], actual_receipts_observed=False)
            else:
                params.update(published_precision_half_unit_GMD=precision,
                              published_reported_receipts_GMD=amount, actual_column_reported=True,
                              overall_audit_opinion='adverse' if year in (2022,2024) else 'not_claimed_from_budget_actual_column')
            flow = dict(id=PREFIX+f'gmb_{year}_{typ}', payer='UNK', receiver='GMB', year=year,
                        visa_group='other', visa_type=typ,
                        visa_label='政府签证费预算执行估计' if budget else '政府报告的签证费收入',
                        category_detail_status='unclassified', amount=amount, lower=lower, upper=upper,
                        currency='GMD', quantity=None, quantity_basis='no_matching_paid_application_denominator',
                        source_ids=sids, observation_ids=oids, method_id=method,
                        model_status='official_budget_run_rate_estimate' if budget else 'official_reported_actual_receipts',
                        calculation_type='conditional_scenario' if budget else 'direct_observation',
                        origin_basis='unallocated', period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                        period_type='calendar_year_model' if budget else 'calendar_year',
                        period_label=str(year), notes=notes, parameters=params)
            self.flows.append(flow)
            self.ranges.append(dict(receiver='GMB', year=year, amount=amount, lower=lower,
                                    upper=upper,currency='GMD',range_method=range_method))
        self.models = [dict(model_id=PREFIX+'gmb_government_visa_reported_receipts', destination='GMB',
                            years=list(range(2020,2025)), status='reported_visa_receipt_leaf_series',
                            formula='Two disjoint agency1422177 Actual rows summed for2020,2021,2023; later consolidated government-account1422177 CR for2022,2024',
                            limitations=['2022及2024整体审计否定意见随记录保留，不能称clean audited actual。',
                                         '公布精度范围不量化账户错误、漏报或财报完整性。',
                                         '2022预算书异常与2024较小版本差异保留于source_conflicts.json，不重复加总。',
                                         '付款国籍及付费申请事件数未知，不按游客人数分摊。']),
                       dict(model_id=PREFIX+'gmb_government_visa_budget_run_rate', destination='GMB',years=[2025],
                            status='approved_budget_run_rate_scenario',formula='(6140556+11770268)GMD*execution_rate',
                            limitations=['2025中心为已批预算，不是实际收款；0.7—1.3为条件情景。',
                                         '2026预算书2025 Approved只用于身份核对，不成为额外收费或实际2025观察。',
                                         '2026提案金额仅存预算背景，未加入当前金额序列。'])]

    def exchange_rates(self):
        srcs=json.loads((ROOT/'data/research/africa_expansion_v3/sources.json').read_text())
        s=next(s for s in srcs if s['source_id']=='afx_wb_exchange_rates')
        p=ROOT/s['local_path']
        assert hashlib.sha256(p.read_bytes()).hexdigest()==s['sha256']
        self.sources.append(s)
        z=zipfile.ZipFile(p)
        name=next(n for n in z.namelist() if n.startswith('API_'))
        rows=list(csv.reader(io.StringIO(z.read(name).decode('utf-8-sig'))))
        row=next(r for r in rows[5:] if len(r)>1 and r[1]=='GMB')
        values=dict(zip(rows[4],row))
        for year in sorted({f['year'] for f in self.flows}):
            value=float(values[str(year)])
            assert value>0
            self.fx.append(dict(fx_id=PREFIX+f'wb_gmb_{year}',year=year,currency='GMD',raw_rate=value,
                                raw_direction='currency_per_USD',usd_per_unit=1/value,
                                source_id=s['source_id'],source_ids=[s['source_id']],
                                source_locator=f'{name};CountryCode=GMB;year={year};PA.NUS.FCRF',
                                method='World Bank / IMF annual official exchange rate, period average'))

    def finish(self):
        sids={s['source_id'] for s in self.sources}
        oids={o['observation_id'] for o in self.observations}
        assert len(sids)==len(self.sources) and len(oids)==len(self.observations)
        assert len({f['id'] for f in self.flows})==len(self.flows)==6
        expected={2020:13561896,2021:25756944,2022:22827551.8,2023:20917303,2024:22982402.82,2025:17910824}
        for f in self.flows:
            assert f['amount']==expected[f['year']]
            assert f['payer']=='UNK' and f['quantity'] is None
            assert set(f['source_ids'])<=sids and set(f['observation_ids'])<=oids
            assert f['lower']<=f['amount']<=f['upper']
        assert all(not o['eligible_money_ledger'] for o in self.observations)
        overlap, checked = [], []
        scopes={(f['receiver'],f['year']) for f in self.flows}
        for p in sorted((ROOT/'data/estimates').glob('*_flows.json')):
            if p.name=='africa_expansion_v6_flows.json':continue
            checked.append(str(p.relative_to(ROOT)))
            for f in json.loads(p.read_text()).get('flows',[]):
                if (f.get('receiver'),f.get('year')) in scopes and f.get('amount',0)>0:
                    overlap.append([p.name,f.get('id')])
        assert not overlap,overlap
        coverage=[]
        for f in self.flows:
            for group in GROUPS:
                active=group=='other'
                modeled=active and f['year']==2025
                known=active and f['year']!=2025
                coverage.append(dict(code='GMB',destination='GMB',name='冈比亚',region='非洲',year=f['year'],
                                     visa_group=group,status='amount_modeled' if modeled else 'amount_known' if known else 'not_found',
                                     fee_known=False,fee_current_snapshot_known=False,quantity_known=False,
                                     quantity_context_known=False,arrival_context_known=False,
                                     amount_known=known,amount_modeled=modeled,nationality_known=False,
                                     category_detail_status='unclassified_aggregate' if active else 'no_classified_observation',
                                     notes=f['notes'] if active else '未取得该用途单列收入，不从签证费总项臆拆。',
                                     source_ids=f['source_ids'] if active else [],searched_as_of=ASOF))
        self.excluded=[
            dict(destination='GMB',candidate='2022 budget comparator GMD531,638,922',reason='Conflicts with later government-account visa-fee CR22,827,551.80; keep as conflicting evidence, not selected edge.'),
            dict(destination='GMB',candidate='2024 FY2026-proposal comparator GMD23,177,085',reason='Differs from later published audit trial balance22,982,402.82; no averaging or addition.'),
            dict(destination='GMB',candidate='2026 proposed Visa Fees GMD28,176,676',reason='Budget proposal context only; not current actual receipts or additional2025 flow.'),
            dict(destination='GMB',candidate='VISA FEE Account / code3211184',reason='Year-end bank asset balance, not annual1422177 visa-fee revenue.'),
            dict(destination='GMB',candidate='2023 Government Public Accounts PDF p160',url='https://nao.gm/wp-content/uploads/2025/09/GoTG-2023-Financial-Statements-Audit-Report-and-AG-Certificate-2.pdf',reason='Visa-fee trial-balance continuation page160 is blank in archived original; no number inferred.2023 uses explicit Actual in later approved budget.'),
            dict(destination='CMR',candidate='eVisa cumulative April2023-to-2026 revenue',reason='Only cross-year cumulative narrative established in candidate sources; no invented annual allocation.'),
            dict(destination='SWZ',candidate='Treasury visa-fee annual account',reason='Candidate lead not verified from retrievable original in this package; no money edge added.'),
        ]
        checks=dict(as_of=ASOF,sources=len(sids),observations=len(oids),fees=0,fx=len(self.fx),flows=len(self.flows),
                    models=len(self.models),coverage_rows=len(coverage),receivers=['GMB'],years=list(range(2020,2026)),
                    totals_native={f'GMB_{y}_GMD':v for y,v in expected.items()},
                    source_hashes_verified=True,pdfium_original_text_rebuilt=True,agency_detail_and_thousand_summary_reconciled=True,
                    all_payers_unknown=True,no_claimed_application_denominators=True,no_arrival_times_fee_model=True,
                    only1422177_visa_leaf=True,audit_adverse_opinion_preserved=True,
                    stale_pdf_metadata_and_footer_not_used_as_year=True,
                    source_conflicts_retained=len(self.conflicts),conflicting_amounts_not_summed=True,
                    budget2025_not_actual=True,budget2026_not_money_edge=True,
                    no_duplicate_existing_receiver_year=True,overlap_checked_packages=checked)
        package=dict(package='africa_expansion_v6',as_of=ASOF,flows=self.flows,models=self.models,
                     destination_ranges=self.ranges,subtotals=[],coverage_rows=len(coverage),
                     scope='Gambia1422177 reported actual receipt leaf2020-2024; approved2025 budget execution scenario; unknown payer, no invented application denominator; source conflicts and adverse audit opinion retained')
        for filename,obj in [('sources.json',self.sources),('observations.json',self.observations),
                             ('fee_rules.json',[]),('fx.json',self.fx),('coverage.json',coverage),
                             ('checks.json',checks),('source_conflicts.json',self.conflicts),
                             ('excluded_candidates.json',self.excluded),('flows.json',package)]:dump(OUT/filename,obj)
        dump(ROOT/'data/estimates/africa_expansion_v6_flows.json',package)
        (OUT/'README.md').write_text('''# 非洲签证收入扩展 v6：冈比亚

运行 `.research-venv/bin/python scripts/research_africa_expansion_v6.py` 可从冻结原件离线重建研究包及 `data/estimates/africa_expansion_v6_flows.json`。已注册进入统一费用总账；`flows.json` 保留原币金额与控制范围。

| 年度 | 选用金额 GMD | 口径 |
|---|---:|---|
| 2020 | 13,561,896 | 2022已批预算书明确2020 Actual，内政08与外交10两个互斥1422177叶项之和 |
| 2021 | 25,756,944 | 2023预算书明确2021 Actual，同上 |
| 2022 | 22,827,551.80 | 2022政府合并试算表1422177贷方 |
| 2023 | 20,917,303 | 2025已批预算书明确2023 Actual，同上 |
| 2024 | 22,982,402.82 | 2024政府合并试算表1422177贷方 |
| 2025 | 17,910,824 | 官方已批预算之和，100%执行中心；70%—130%条件情景 |

2022和2024政府财报整体审计意见均为否定意见（adverse），这里记录官方报告金额，不称无保留核实实收。2020、2021、2023是后续预算书的Actual历史列，不冒充审计结论。实际金额范围只表示公布精度，不量化错报、漏报或财报完整性；2025范围是执行率情景，不是置信区间。

所有金额只取1422177 Visa Fees。机构明细用GMD，经济分类汇总用GMD千元；汇总只作对账，不再增加流量。护照、综合移民费、工作或居留许可、其他领事服务、Securiport机场安全费均分开。`VISA FEE Account`是银行资产余额，也不当作年度收入。

2022预算书Actual合计531,638,922与审计试算表22,827,551.80冲突；2026提案的2024比较列23,177,085也与2024审计22,982,402.82有差异。采用后发布的政府账户签证叶项，保留原始冲突，详见`source_conflicts.json`。2022试算表及政策明确2022，反复页脚2021是模板残留；2024元数据标题2011也是残留。2023审计原件p160空白，不填造该页金额。

2025已批预算由2026书的2025 Approved列再次确认。2026提案28,176,676只存预算背景。付款国籍保持UNK，申请件数为空；不按到达游客份额拆出双边边或人均申请支出。同年World Bank/IMF年均汇率复用已归档原件和哈希。

相关原页已渲染核对；PDFium可恢复pypdf遗漏的嵌入字体表格内容。完整来源、页码、哈希、单位、观察身份、冲突和查重结果分别见JSON与`*_pdfium.txt`。原始资料目录另存候选文档；未验证的候选不计入有效新增覆盖。
''')
        print(json.dumps(checks,ensure_ascii=False))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    r=Research()
    r.load_sources()
    r.budget_receipts()
    r.audit_receipts()
    r.flows_and_models()
    r.exchange_rates()
    r.finish()


if __name__=='__main__':main()
