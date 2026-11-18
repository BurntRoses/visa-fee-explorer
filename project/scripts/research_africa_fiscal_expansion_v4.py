#!/usr/bin/env python3
"""Rebuild visa-specific African fiscal evidence from frozen official sources.

Tanzania: HQ business-visa actual receipts, July–June fiscal bridges.
Ghana: missions Visa Fees budget collections, explicitly a budget scenario.
Liberia: visa-specific airport/travel leaf accounts, historical/outturn rows.
The package never treats a comparison column, tourism count or mixed immigration
account as an observed visa-fee cash receipt.
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

from pypdf import PdfReader

sys.dont_write_bytecode = True
logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/africa_fiscal_expansion_v4'
OUT = ROOT / 'data/research/africa_fiscal_expansion_v4'
EST = ROOT / 'data/estimates/africa_fiscal_expansion_v4_flows.json'
ASOF = '2026-11-17'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
NAMES = {'TZA': '坦桑尼亚', 'GHA': '加纳', 'LBR': '利比里亚'}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class Research:
    def __init__(self):
        self.sources, self.obs, self.fx = [], [], []
        self.flows, self.models, self.ranges, self.excluded = [], [], [], []

    def source(self, slug, filename, url, publisher, title, notes):
        path = RAW / filename
        assert path.exists() and path.stat().st_size > 100
        sid = 'afv4_' + slug
        self.sources.append(dict(source_id=sid, url=url, publisher=publisher,
                                 title=title, notes=notes, retrieved_at=ASOF,
                                 source_quality='official_original',
                                 local_path=str(path.relative_to(ROOT)),
                                 path=str(path.relative_to(ROOT)),
                                 bytes=path.stat().st_size,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                 archive_kind='original_document'))
        return sid

    def reuse_source(self, package, sid):
        candidates = json.loads((ROOT / f'data/research/{package}/sources.json').read_text())
        record = next(s for s in candidates if s['source_id'] == sid)
        path = ROOT / record['local_path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
        self.sources.append(record)
        return sid

    def observation(self, slug, code, year, value, currency, sid, locator, **extra):
        oid = 'afv4_' + slug
        self.obs.append(dict(observation_id=oid, destination=code, year=year,
                             metric=extra.pop('metric', 'visa_fee_actual_revenue'),
                             raw_metric=extra.pop('raw_metric', 'Visa Fees'),
                             value=value, unit=currency, source_id=sid,
                             source_ids=[sid], source_locator=locator,
                             nationality='UNK', origin_basis='unallocated',
                             visa_group=extra.pop('visa_group', 'other'),
                             visa_type=extra.pop('visa_type', 'visa_fee_receipts'),
                             eligible_money_ledger=False,
                             period_start=extra.pop('period_start', f'{year}-01-01'),
                             period_end=extra.pop('period_end', f'{year}-12-31'),
                             period_type=extra.pop('period_type', 'calendar_year'),
                             calculation_type=extra.pop('calculation_type', 'direct_observation'), **extra))
        return oid

    def flow(self, code, year, typ, label, group, amount, lower, upper,
             currency, sources, observations, method, status, notes, parameters):
        assert 0 <= lower <= amount <= upper
        self.flows.append(dict(id=f'afv4_{code.lower()}_{year}_{typ}', payer='UNK',
                               receiver=code, year=year, visa_group=group,
                               visa_type=typ, visa_label=label,
                               category_detail_status='classified' if group == 'visitor' else 'unclassified',
                               amount=amount, lower=lower, upper=upper, currency=currency,
                               quantity=None, quantity_basis='no_matching_paid_application_denominator',
                               source_ids=list(dict.fromkeys(sources)),
                               observation_ids=list(dict.fromkeys(observations)),
                               method_id=method, model_status=status,
                               calculation_type='conditional_scenario', origin_basis='unallocated',
                               period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                               period_type='calendar_year_model', period_label=str(year),
                               notes=notes, parameters=parameters))
        found = next((r for r in self.ranges if (r['receiver'], r['year']) == (code, year)), None)
        if found:
            assert found['currency'] == currency
            for key, value in [('amount', amount), ('lower', lower), ('upper', upper)]:
                found[key] += value
        else:
            self.ranges.append(dict(receiver=code, year=year, amount=amount, lower=lower,
                                    upper=upper, currency=currency,
                                    range_method=parameters['range_method']))

    def tanzania(self):
        entries = [
            (2020, 'tza_2022_revenuebook.pdf', 212, 19539441162,
             'https://www.mof.go.tz/uploads/documents/en-1646136424-VOLUME I Financial Statement & Revenue Estimates for the year from 1 July 2021- to 30th June 2022.pdf',
             'FY2021/22 Financial Statement and Revenue Estimates, Volume I', '2019/2020'),
            (2021, 'tza_2023_revenuebook.pdf', 178, 9151651318,
             'https://www.mof.go.tz/uploads/documents/en-1667821187-VOLUME I REVENUE_ESTIMATES_2022_23 AS PASSED BY THE PARLIAMENT.pdf',
             'FY2022/23 Revenue Estimates, Volume I, as passed by Parliament', '2020/2021'),
            (2022, 'tza_2024_revenuebook.pdf', 180, 22413620489,
             'https://www.mof.go.tz/uploads/documents/en-1696325053-VOLUME I REVENUE ESTIMATES AS PASSED 2023-24.pdf',
             'FY2023/24 Revenue Estimates, Volume I, as passed by Parliament', '2021/2022'),
        ]
        annual, oids = {}, {}
        for fy, filename, page, amount, url, title, period in entries:
            sid = self.source(f'tza_budget{fy+2}', filename, url, 'Tanzania Ministry of Finance', title,
                              f'PDF p{page+1}, Vote093, Subvote2002 Immigration Head Quarter, '
                              f'item14220240 Receipts from Business Visa, {period} Actual Collection. '
                              'Adjacent approved estimates and estimates are excluded. HQ account subset; '
                              'do not assume Zanzibar has been merged into this line.')
            text = PdfReader(RAW / filename).pages[page].extract_text(extraction_mode='layout')
            row = next(line for line in text.splitlines() if '14220240' in line and 'Business Visa' in line)
            amounts = [int(x.replace(',', '')) for x in re.findall(r'\b\d{1,3}(?:,\d{3})+\b', row)]
            assert amounts[0] == amount, (fy, row)
            assert period in text and 'Actual' in text and 'Collection' in text
            assert 'HEAD QUARTER' in text or fy == 2020  # header starts on previous page in this edition
            (OUT / f'tza_fy{fy}_hq_visa_table.txt').write_text(text)
            annual[fy] = (amount, sid)
            oids[fy] = self.observation(f'tza_fy{fy}_hq_business_visa_actual', 'TZA', fy, amount, 'TZS', sid,
                                        f'PDF p{page+1}; Vote093; Subvote2002; item14220240; {period} Actual Collection',
                                        raw_metric='Receipts from Business Visa / Immigration Head Quarter2002',
                                        visa_group='visitor', visa_type='business_visa_hq_actual',
                                        period_start=f'{fy-1}-07-01', period_end=f'{fy}-06-30',
                                        period_type='fiscal_year', account_scope='Vote093 Subvote2002 HQ only',
                                        notes='官方实际收款列，保留原财年；不是邻列预算，不含Business Pass或其他移民许可。')
        sid = self.reuse_source('global_americas_africa', 'gaa_tz_revenue2025')
        source_path = ROOT / next(s for s in self.sources if s['source_id'] == sid)['local_path']
        text = PdfReader(source_path).pages[183].extract_text(extraction_mode='layout')
        row = next(line for line in text.splitlines() if '14220240' in line and 'Business Visa' in line)
        assert '28,321,612,500' in row and '2022/2023' in text and 'Actual' in text
        (OUT / 'tza_fy2023_hq_visa_table.txt').write_text(text)
        annual[2023] = (28321612500, sid)
        oids[2023] = self.observation('tza_fy2023_hq_business_visa_actual', 'TZA', 2023, 28321612500,
                                      'TZS', sid, 'PDF p184 / printed172; Vote093; Subvote2002; item14220240;2022/2023 Actual Collection',
                                      raw_metric='Receipts from Business Visa / Immigration Head Quarter2002',
                                      visa_group='visitor', visa_type='business_visa_hq_actual',
                                      period_start='2022-07-01', period_end='2023-06-30', period_type='fiscal_year',
                                      account_scope='Vote093 Subvote2002 HQ only',
                                      notes='复用同一官方原件的历史实际列；原件中2024/25预算已由旧模型使用，历史实际不与预算叠加。')
        # Zanzibar is a different subvote. No matching FY2020/21 observation was
        # found, so this single-year actual remains evidence, not a CY ledger edge.
        sid20 = annual[2020][1]
        text = PdfReader(RAW / 'tza_2022_revenuebook.pdf').pages[211].extract_text(extraction_mode='layout')
        assert '678,632,488' in text and 'IMMIGRATION ZANZIBAR' in text
        (OUT / 'tza_fy2020_zanzibar_visa_table.txt').write_text(text)
        self.observation('tza_fy2020_zanzibar_business_visa_actual', 'TZA', 2020, 678632488, 'TZS', sid20,
                         'PDF p212 / printed200; Vote093; Subvote2001; item14220240;2019/2020 Actual Collection',
                         raw_metric='Receipts from Business Visa / Immigration Zanzibar2001', visa_group='visitor',
                         visa_type='business_visa_zanzibar_actual', period_start='2019-07-01',
                         period_end='2020-06-30', period_type='fiscal_year',
                         account_scope='Subvote2001 Zanzibar only; disjoint from HQ2002',
                         notes='与HQ分开的实际科目；缺相邻财年对应子科目，未填补或合入HQ自然年桥接。')
        for year in (2020, 2021, 2022):
            a, b = annual[year][0], annual[year+1][0]
            params = dict(actual_fiscal_receipts_observed=True, calendar_receipts_observed=False,
                          account_code='14220240', collecting_subvote='2002 Immigration Head Quarter',
                          account_scope='HQ Business Visa only; Zanzibar2001 excluded',
                          fiscal_receipts_TZS=a, next_fiscal_receipts_TZS=b,
                          calendar_weights=[.5, .5], each_fiscal_half_weight_range=[.35, .65],
                          nationality_allocation='none',
                          excluded=['Business Pass', 'Visitors Pass', 'residence permits', 'passport fees', 'Zanzibar2001'],
                          range_method='相邻7月至6月财年实收各取1/2；每个半财年35%—65%分配为明确条件情景，非置信区间')
            self.flow('TZA', year, 'hq_business_visa_calendar_bridge', '移民总部商务签证实收的自然年桥接',
                      'visitor', .5*(a+b), .35*(a+b), .65*(a+b), 'TZS',
                      [annual[year][1], annual[year+1][1]], [oids[year], oids[year+1]],
                      'afv4_tza_hq_business_visa_calendar_bridge', 'observed_receipts_calendar_bridge_estimate',
                      '坦桑尼亚移民总部2002子科目商务签证实收，依相邻7月至6月财年各取一半桥接自然年。'
                      '只覆盖该HQ账户，不含单独列示的桑给巴尔2001、商务通行证或居留许可；未推断付款国籍或申请件数。', params)
        self.models.append(dict(model_id='afv4_tza_hq_business_visa_calendar_bridge', destination='TZA',
                                years=[2020, 2021, 2022], status='observed_fiscal_receipts_calendar_bridge_subset',
                                formula='0.5*HQ_BusinessVisa_FY[y]+0.5*HQ_BusinessVisa_FY[y+1]',
                                limitations=['只覆盖Vote093/Subvote2002/14220240商务签证科目，不等同全国全部签证费。',
                                             'FY2019/20桑给巴尔2001另存，未假设后续并入HQ。',
                                             '财年实际可核查；自然年是均匀时间分配模型。',
                                             '35%—65%半财年分配是工作情景，不是实测上下界或置信区间。',
                                             '付款国籍和付费申请次数未知；保持UNK和空分母。']))

    def ghana(self):
        sid = self.source('gha_budget2025', 'gha_2025_mfari_budget.pdf',
                          'https://www.mofep.gov.gh/sites/default/files/pbb-estimates/2025/2025-PBB-MFARI.pdf',
                          'Ghana Ministry of Finance / Ministry of Foreign Affairs',
                          '2025 Programme Based Budget Estimates, Ministry of Foreign Affairs',
                          'PDF p19: 2025 NON-TAX REVENUE PROJECTIONS—CAPPING, MISSIONS Visa Fees. '
                          '2025 COLLECTIONS(B) GH₵9,746,707.58 is a projection, not actual. '
                          'Retention(C) and Consolidated Fund(D) split the same collections. '
                          '2024(A) is only a prior-year comparator; A is a column letter, not proof of actual status.')
        text = PdfReader(RAW / 'gha_2025_mfari_budget.pdf').pages[18].extract_text(extraction_mode='layout')
        assert '2025 NON-' in text and 'PROJECTIONS' in text and 'COLLECTIONS' in text and '(GH₵)' in text
        row = next(line for line in text.splitlines() if 'Visa Fees' in line)
        amounts = re.findall(r'\d{1,3}(?:,\d{3})*\.\d{2}', row)
        assert amounts[:3] == ['13,839,516.75', '9,746,707.58', '6,432,827.00'], row
        (OUT / 'gha_2025_missions_visa_budget_table.txt').write_text(text)
        oid = self.observation('gha_2025_missions_visa_budget', 'GHA', 2025, 9746707.58, 'GHS', sid,
                               'PDF p19;2025 NON-TAX REVENUE PROJECTIONS—CAPPING; MISSIONS Visa Fees; COLLECTIONS(B)',
                               metric='visa_fee_budget_collections', raw_metric='Missions Visa Fees /2025 COLLECTIONS(B)',
                               visa_type='missions_visa_fee_budget', budget_not_actual=True,
                               notes='明确预算收款预测，非2025实收；只包括Visa Fees，不含护照、认证、其他收入或AICC租金。')
        self.observation('gha_2024_missions_visa_comparator', 'GHA', 2024, 13839516.75, 'GHS', sid,
                         'PDF p19; MISSIONS Visa Fees;2024(A) comparator',
                         metric='visa_fee_prior_year_comparator_status_unidentified',
                         raw_metric='Missions Visa Fees /2024(A)', actual_or_budget_status='not_identified',
                         notes='A是列字母；报告未在该列明确实际或预算身份，未进入金额总账。')
        self.observation('gha_2025_missions_visa_budget_retention', 'GHA', 2025, 6432827, 'GHS', sid,
                         'PDF p19; MISSIONS Visa Fees;2025 RETENTION(C)', metric='visa_fee_budget_retention_component',
                         raw_metric='Missions Visa Fees /RETENTION(C)', budget_not_actual=True,
                         parent_observation_id=oid,
                         notes='总收款的留存分项，不是额外收费；不与COLLECTIONS重复加总。')
        params = dict(actual_receipts_observed=False, budget_collections_GHS=9746707.58,
                      budget_realization_center=1.0, budget_realization_scenario=[.7, 1.3],
                      account_scope='Foreign Affairs missions Visa Fees only',
                      retention_is_component_not_extra=True, consolidated_fund_is_component_not_extra=True,
                      nationality_allocation='none',
                      excluded=['Passport Fees', 'Authentication Fees', 'Other income', 'AICC rentals'],
                      range_method='2025官方签证收款预算×执行率1.0；0.7—1.3为工作情景，非实收或置信区间')
        self.flow('GHA', 2025, 'missions_visa_budget_run_rate', '驻外使团签证收费预算运行率', 'other',
                  9746707.58, 9746707.58*.7, 9746707.58*1.3, 'GHS', [sid], [oid],
                  'afv4_gha_missions_visa_budget_run_rate', 'official_budget_run_rate_estimate',
                  '加纳2025驻外使团Visa Fees独立预算收款预测，以100%预算执行率为中心，70%—130%为条件情景。'
                  '预算不是已核实的实际收款；留存和缴入统一基金的分账不再重复加入，付款国籍及付费次数未知。', params)
        self.models.append(dict(model_id='afv4_gha_missions_visa_budget_run_rate', destination='GHA', years=[2025],
                                status='official_budget_projection_run_rate', formula='2025 Missions Visa Fees COLLECTIONS(B)*budget_realization',
                                limitations=['2025预算收款预测，未识别同期实际实收；执行率70%—130%是条件情景。',
                                             '只含驻外使团Visa Fees，不等同所有国内移民机关收入。',
                                             '2024比较列身份未明，未当作实际或预算边。',
                                             'Retention及缴库分项属于同一总收款，不能再次相加。',
                                             '未把visas and permits混合数量当作签证申请分母。']))

    def exchange_rates(self):
        sid = self.reuse_source('africa_expansion_v3', 'afx_wb_exchange_rates')
        source = next(s for s in self.sources if s['source_id'] == sid)
        z = zipfile.ZipFile(ROOT / source['local_path'])
        name = next(n for n in z.namelist() if n.startswith('API_'))
        rows = list(csv.reader(io.StringIO(z.read(name).decode('utf-8-sig'))))
        by_country = {r[1]: dict(zip(rows[4], r)) for r in rows[5:] if len(r) > 1}
        for country, year, currency in sorted({(f['receiver'], f['year'], f['currency']) for f in self.flows if f['currency'] != 'USD'}):
            value = float(by_country[country][str(year)])
            assert value > 0
            self.fx.append(dict(fx_id=f'afv4_wb_{country.lower()}_{year}', year=year, currency=currency,
                                raw_rate=value, raw_direction='currency_per_USD', usd_per_unit=1/value,
                                source_id=sid, source_ids=[sid],
                                source_locator=f'{name};CountryCode={country};year={year};PA.NUS.FCRF',
                                method='World Bank / IMF annual official exchange rate, period average'))

    def liberia(self):
        sid = self.source('lbr_revenue_details2024', 'lbr_revenue-budget-details-fy2024-doc-927.pdf',
                          'https://mfdp.gov.lr/edocman/file_65f9836add5b8_Revenue%20Details.pdf',
                          'Liberia Ministry of Finance and Development Planning, Department of Fiscal Affairs, Revenue Tax Policy Division',
                          'FY2024 Draft Revenue Budget: Revenue Budget Details, detailed historical revenue trend',
                          'PDF p146:2022 ACTUAL /2023 OUTTURN /2024 BUDGET, Jan–Dec. PDF p157 labels detailed historical revenue trend; '
                          'p167:2012–2023 Jan–Dec columns plus2024 Budget. Only Airport Visas142182-BIN and Visa To Travel To Liberia142185-BIN used. '
                          'Historical2012–2021 columns do not certify audited status. Scale1000USD established by exact parent BIN2022=4686.91 '
                          'matching FY2022 financial statements p25 explicitly US$000, plus overall revenue total and document USD executive summary. '
                          'Historical table does not repeat the monetary unit on each page; this scale determination is retained as a calculation, not a claimed printed unit.')
        unit_sid = self.source('lbr_financial2022_unit_control', 'lbr_consolidated-financial-statement-fy2022-doc-877.pdf',
                               'https://mfdp.gov.lr/edocman/Annual%20Consolidated%20Financial%20Statements%20FY2022%20-.pdf',
                               'Liberia Ministry of Finance and Development Planning, Comptroller and Accountant General Department',
                               'Annual Consolidated Financial Statements for the year ended31December2022',
                               'PDF p25 Note5 Administrative Fees, LIS2022 Actual4686.91, explicitly US$000. '
                               'PDF p14 total receipts808832.4 with p11 narrative US$808.83million. Independent denomination and parent-account control only; '
                               'not extra visa receipts, no allocation of all LIS receipts to visas.')
        reader = PdfReader(RAW / 'lbr_revenue-budget-details-fy2024-doc-927.pdf')
        historical = reader.pages[166].extract_text()
        actual = reader.pages[145].extract_text()
        parent = reader.pages[165].extract_text()
        summary = reader.pages[158].extract_text()
        controls = PdfReader(RAW / 'lbr_consolidated-financial-statement-fy2022-doc-877.pdf')
        unit_text = controls.pages[24].extract_text()
        total_text = controls.pages[13].extract_text()
        assert "US$'000'" in unit_text and '4,686.91' in unit_text and 'LIS' in unit_text
        assert '4,686.91' in next(line for line in parent.splitlines() if line.startswith('14217 '))
        assert '808,832.4' in total_text and '808,832' in summary
        assert '2022' in actual and 'ACTUAL' in actual and 'OUTTURN' in actual
        assert 'APPENDIX-DETAILED HISTORICAL REVENUE TREND' in reader.pages[156].extract_text()
        assert 'Jan-Dec.' in historical and 'FY-2024' in historical and 'BUDGET' in historical
        for filename, text in [('lbr_visa_historical_table.txt', historical),
                               ('lbr_visa_actual_outturn_table.txt', actual),
                               ('lbr_parent_historical_unit_control.txt', parent),
                               ('lbr_financial2022_explicit_unit_control.txt', unit_text)]:
            (OUT / filename).write_text(text)
        control_oid = self.observation('lbr_2022_lis_parent_unit_control', 'LBR', 2022, 4686910, 'USD', unit_sid,
                                       "PDF p25 Note5 Administrative Fees; LIS;2022 Actual;US$'000'",
                                       metric='mixed_lis_revenue_unit_control', raw_metric='LIS administrative fees total',
                                       reported_value=4686.91, reported_unit='thousand USD',
                                       notes='仅验证历史表同一LIS母账户单位1000USD；此混合移民服务总项不作为签证收入。')
        specs = [
            ('142182-BIN', 'Airport Visas', 'airport_visa_receipts', '机场签证收费',
             ['4', '136', '169', '72', '1', '129.37', '262.35', '196.85', '124.58', '184.72', '365.10', '209.36', '197']),
            ('142185-BIN', 'Visa To Travel To Liberia', 'travel_visa_receipts', '赴利比里亚签证收费',
             ['-', '0', '0', '-', '-', '0.30', '-', '-', '0.34', '0.35', '-', '0.03', '1']),
        ]
        for code, raw_label, typ, label, expected in specs:
            row = next(line for line in historical.splitlines() if line.startswith(code))
            values = row.split(raw_label, 1)[1].split()
            assert values == expected, (code, values)
            for year, token in zip(range(2012, 2024), values[:-1]):
                if token == '-':
                    self.excluded.append(dict(destination='LBR', year=year, candidate=code,
                                              reason='Published dash retained as missing/not separately reported, never coerced to zero.'))
                    continue
                value = float(token.replace(',', ''))
                amount = value * 1000
                precision = 1000 if '.' not in token else 10
                lower, upper = max(0, amount-precision/2), amount+precision/2
                if year == 2022:
                    status = 'published_actual_receipts_partial'
                    status_cn = '2022明确Actual实际列'
                    assert code != '142182-BIN' or '365' in next(line for line in actual.splitlines() if line.startswith(code))
                elif year == 2023:
                    status = 'published_outturn_receipts_partial'
                    status_cn = '2023明确Outturn执行结果列，未称已审计实收'
                else:
                    status = 'published_historical_receipts_partial'
                    status_cn = '详细历史收入趋势中的自然年金额，原列未标审计身份'
                oid = self.observation(f'lbr_{year}_{typ}', 'LBR', year, amount, 'USD', sid,
                                       f'PDF p167;{code};{raw_label};{year} Jan–Dec; scale1000 verified by LIS2022 parent and financial statements p25',
                                       metric='visa_fee_reported_outturn' if year == 2023 else 'visa_fee_actual_revenue' if year == 2022 else 'visa_fee_published_historical_receipts',
                                       raw_metric=code + ' ' + raw_label,
                                       visa_type=typ, reported_value=value, reported_token=token,
                                       reported_scale=1000, scale_status='established_by_exact_parent_account_and_document_total_reconciliation',
                                       printed_unit_on_leaf_page=False, published_precision_USD=precision,
                                       receipt_status=status, published_dash_is_not_zero=True,
                                       notes=status_cn+'；只取此签证叶科目，不含领事费、居留、重入许可、护照、册费或归化。')
                params = dict(account_code=code, account_scope='LIS/BIN named visa fee leaf only',
                              actual_receipts_observed=(year == 2022), published_receipt_status=status,
                              calendar_period_explicit='Jan–Dec, including historical pre-fiscal-transition years',
                              reported_value=value, reported_scale_to_USD=1000,
                              unit_control_source_id=unit_sid, unit_control_observation_id=control_oid,
                              unit_control='LIS2022 parent4686.91 equals financial statements p25 explicitly US$000; total receipts808832.4 vs revenue table808832',
                              published_precision_USD=precision,
                              excluded=['Consulate fees142107-MFA', 'residence permits', 're-entry permits', 'booklet fees', 'naturalization', 'all-LIS total'],
                              nationality_allocation='none',
                              range_method='两个互斥签证叶科目报告精度的半单位取整区间；历史金额、2022Actual及2023Outturn身份分别保留，非置信区间')
                self.flow('LBR', year, typ, label, 'other', amount, lower, upper, 'USD', [sid, unit_sid],
                          [oid, control_oid], 'afv4_lbr_visa_leaf_published_receipts', status,
                          '利比里亚LIS/BIN独立签证叶科目。'+status_cn+'；历史表逐年明确Jan–Dec，无需财政年桥接。'
                          '历史表叶页未重印单位，按2022相同LIS母账户与财报明确千美元值及总收入量级对账确定×1000。'
                          '缺号不作0，未混入广义领事费、居留、重入许可、册费、归化或护照。付款国籍及申请次数未知。', params)
                self.flows[-1].update(calculation_type='direct_observation', period_type='calendar_year')
        self.models.append(dict(model_id='afv4_lbr_visa_leaf_published_receipts', destination='LBR',
                                years=list(range(2012, 2024)), status='published_historical_actual_outturn_visa_leaf_receipts',
                                formula='Published142182-BIN Airport Visas and142185-BIN Visa To Travel To Liberia values*1000USD; dash omitted',
                                actual_labeled_years=[2022], outturn_labeled_years=[2023],
                                historical_columns_without_audited_status=list(range(2012, 2022)),
                                limitations=['只含两个明确签证收费叶科目；外交部混合Consulate fees不加入。',
                                             '2012—2021来自详细历史收入表，未把历史身份说成已审计实际。2022列明确Actual，2023列明确Outturn。',
                                             '2012—2023各列均明确Jan—Dec；不按旧7月至6月财政年再次桥接。',
                                             '叶页未重印单位；以相同LIS2022母项4686.91与财报US$000对应及总收入对账，确立千美元比例。',
                                             '2012—2016精度千美元，2017—2023精度10美元；零表示取整零，缺号保留缺失。',
                                             '付款国籍及付费事件数未披露；不从机场到达人数或国籍旅游份额分摊。']))

    def finish(self):
        sids = {s['source_id'] for s in self.sources}
        oids = {o['observation_id'] for o in self.obs}
        assert len(sids) == len(self.sources) and len(oids) == len(self.obs)
        assert len({f['id'] for f in self.flows}) == len(self.flows)
        for f in self.flows:
            assert set(f['source_ids']) <= sids and set(f['observation_ids']) <= oids
            assert f['payer'] == 'UNK' and f['quantity'] is None
        assert all(o['eligible_money_ledger'] is False for o in self.obs)
        for r in self.ranges:
            ff = [f for f in self.flows if (f['receiver'], f['year']) == (r['receiver'], r['year'])]
            for key in ('amount', 'lower', 'upper'):
                assert abs(sum(f[key] for f in ff)-r[key]) < .01
        assert {(f['year'], f['currency']) for f in self.flows if f['currency'] != 'USD'} <= {(f['year'], f['currency']) for f in self.fx}
        scopes = {(f['receiver'], f['year']) for f in self.flows}
        overlap, checked = [], []
        for p in sorted(EST.parent.glob('*_flows.json')):
            if p == EST:
                continue
            checked.append(str(p.relative_to(ROOT)))
            for f in json.loads(p.read_text()).get('flows', []):
                if (f.get('receiver'), f.get('year')) in scopes:
                    overlap.append((p.name, f.get('id')))
        assert not overlap, overlap
        coverage = []
        for code in NAMES:
            for year in sorted({f['year'] for f in self.flows if f['receiver'] == code}):
                for group in GROUPS:
                    ff = [f for f in self.flows if (f['receiver'], f['year'], f['visa_group']) == (code, year, group)]
                    modeled = bool(ff) and code != 'LBR'
                    known = bool(ff) and code == 'LBR'
                    coverage.append(dict(code=code, destination=code, name=NAMES[code], region='非洲', year=year,
                                         visa_group=group, status='amount_modeled' if modeled else 'amount_known' if known else 'not_found',
                                         fee_known=False, fee_current_snapshot_known=False, quantity_known=False,
                                         quantity_context_known=False, arrival_context_known=False,
                                         amount_known=known, amount_modeled=modeled, nationality_known=False,
                                         category_detail_status='classified_subset' if ff and group == 'visitor' else 'unclassified_aggregate' if ff else 'no_classified_observation',
                                         notes=ff[0]['notes'] if ff else '未取得本用途单独金额；不从其他移民服务总项臆拆。',
                                         source_ids=list(dict.fromkeys(s for f in ff for s in f['source_ids'])), searched_as_of=ASOF))
        totals_native = {f"{r['receiver']}_{r['year']}_{r['currency']}": r['amount'] for r in self.ranges}
        assert totals_native['LBR_2013_USD'] == 136000
        assert totals_native['LBR_2020_USD'] == 124920
        assert totals_native['LBR_2023_USD'] == 209390
        checks = dict(as_of=ASOF, sources=len(sids), observations=len(oids), fees=0, fx=len(self.fx),
                      flows=len(self.flows), models=len(self.models), coverage_rows=len(coverage),
                      receivers=sorted({f['receiver'] for f in self.flows}),
                      years=sorted({f['year'] for f in self.flows}),
                      totals_native=totals_native,
                      all_payers_unknown=True, no_claimed_application_denominators=True,
                      no_arrival_times_fee_model=True, all_cash_edges_visa_specific=True,
                      mixed_parent_unit_control_observation_not_cash_edge=True,
                      fiscal_raw_rows_not_extra_calendar_edges=True,
                      budget_not_labeled_actual=True, ghana_retention_not_added_twice=True,
                      liberia_actual_2022_outturn_2023_history_not_audited=True,
                      liberia_thousand_USD_unit_control_verified=True,
                      liberia_dashes_not_zero_and_explicit_JanDec_years=True,
                      tanzania_zanzibar_not_merged_with_hq=True,
                      no_duplicate_existing_receiver_year=True, overlap_checked_packages=checked)
        package = dict(package='africa_fiscal_expansion_v4', as_of=ASOF, flows=self.flows,
                       models=self.models, destination_ranges=self.ranges, subtotals=[],
                       coverage_rows=len(coverage),
                       scope='Tanzania HQ-only Business Visa FYactual2019/20–2022/23 calendar bridges2020–22; Ghana missions Visa Fees2025 budget run-rate, not actual; Liberia two visa leaf accounts2012–2023 calendar historical/Actual/Outturn, status preserved')
        self.excluded.extend([
            dict(destination='GHA', candidate='2024(A) Visa Fees comparator', reason='ColumnA does not establish actual status; retained as context only.'),
            dict(destination='GHA', candidate='2019–2027 series in2024 Missions Revenue Projection', reason='Historical columns do not identify actual/budget status; not treated as cash observations.'),
            dict(destination='GHA', candidate='2024 visas/permits counts in Interior budget', reason='Different tables have conflicting values and visas-and-permits scope; no paid application denominator.'),
            dict(destination='TZA', candidate='Zanzibar2001 FY2019/20 actual', reason='Separate account; no matching adjacent-year same-subvote observation, so not added to HQ calendar bridge.'),
        ])
        for filename, obj in [('sources.json', self.sources), ('observations.json', self.obs),
                              ('fee_rules.json', []), ('fx.json', self.fx), ('coverage.json', coverage),
                              ('checks.json', checks), ('excluded_candidates.json', self.excluded)]:
            dump(OUT / filename, obj)
        dump(EST, package)
        (OUT / 'README.md').write_text('''# 非洲财政签证证据扩展 v4

冻结原件可离线复算。运行`.research-venv/bin/python scripts/research_africa_fiscal_expansion_v4.py`。

- 坦桑尼亚：移民总部Vote093/Subvote2002/14220240 Business Visa实收，FY2019/20—2022/23。只用实际列，相邻7月至6月财年各取一半桥接2020—2022；每半财年35%—65%是条件情景。HQ与Zanzibar2001保持分开。
- 加纳：2025驻外使团Visa Fees的COLLECTIONS(B)预算GH₵9,746,707.58。中心为100%执行、情景70%—130%，不能称实收。2024(A)比较列身份未明，仅存背景。留存与缴库是分账，不能重复增加收款。
- 利比里亚：142182-BIN机场签证和142185-BIN赴利比里亚签证两个叶科目，2012—2023各列明确Jan—Dec。2012—2021历史收入未标审计身份；2022明确Actual，2023明确Outturn。千美元比例通过2022同一LIS母项4686.91与财报p25明确US$000、以及总收入对账确定，未假称叶页重印单位。缺号不作0；取整零仍按原报告精度保留范围。广义Consulate fees和移民许可均排除。
- 所有付款国籍保留UNK，未把游客、visa-and-permits或居留许可当作付费签证申请数；每申请人分母留空。
- 金额使用同年World Bank/IMF年均汇率；外汇归档和Tanzania2024/25预算书复用已有相同来源记录与哈希。

核查结果见`checks.json`；表格摘录及原件页码见观察。原始财年记录不会作为额外自然年边重复相加。
''')
        print(json.dumps(checks, ensure_ascii=False))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    r = Research()
    r.tanzania()
    r.ghana()
    r.liberia()
    r.exchange_rates()
    r.finish()


if __name__ == '__main__':
    main()
