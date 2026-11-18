#!/usr/bin/env python3
"""Rebuild Fiji visa-revenue bridges and Georgian issued-visa tariff values.

Offline originals are authoritative. Fiscal actuals, calendar bridges, standard
tariff values, and quantities which cannot yet be monetized remain distinct.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import logging
from pathlib import Path
import re

from bs4 import BeautifulSoup
from pypdf import PdfReader

logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/asia_expansion_v3'
OUT = ROOT / 'data/research/asia_expansion_v3'
EST = ROOT / 'data/estimates/asia_expansion_v3_flows.json'
ASOF = '2026-11-16'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
NAMES = {'FJI': '斐济', 'GEO': '格鲁吉亚'}


def compact(t):
    return re.sub(r'\s+', '', t)


def html(filename):
    return BeautifulSoup((RAW / filename).read_bytes(), 'html.parser').get_text(' ', strip=True)


class Research:
    def __init__(self):
        self.sources, self.obs, self.fees, self.fx = [], [], [], []
        self.flows, self.models, self.ranges = [], [], []

    def source(self, slug, filename, url, publisher, title, notes=''):
        path = RAW / filename
        assert path.exists() and path.stat().st_size > 1000, filename
        if filename.endswith('.pdf'):
            assert path.read_bytes().startswith(b'%PDF'), filename
        sid = 'asx_' + slug
        self.sources.append(dict(source_id=sid, url=url, publisher=publisher, title=title,
                                 retrieved_at=ASOF, source_quality='official_original',
                                 local_path=str(path.relative_to(ROOT)), path=str(path.relative_to(ROOT)),
                                 bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                 archive_kind='original_document', notes=notes))
        return sid

    def observation(self, slug, destination, year, metric, value, unit, sid, locator, **extra):
        oid = 'asx_' + slug
        nationality = extra.pop('nationality', 'UNK')
        self.obs.append(dict(observation_id=oid, destination=destination, year=year,
                             metric=metric, raw_metric=extra.pop('raw_metric', metric), value=value,
                             unit=unit, source_id=sid, source_ids=[sid], source_locator=locator,
                             nationality=nationality,
                             origin_basis='observed_nationality' if nationality != 'UNK' else 'unallocated',
                             visa_type=extra.pop('visa_type', 'unclassified'), visa_group='other',
                             period_start=extra.pop('period_start', f'{year}-01-01'),
                             period_end=extra.pop('period_end', f'{year}-12-31'),
                             period_type=extra.pop('period_type', 'calendar_year'),
                             calculation_type=extra.pop('calculation_type', 'direct_observation'), **extra))
        return oid

    def flow(self, payer, receiver, year, typ, amount, lower, upper, currency, sources,
             observations, quantity, quantity_basis, notes, params, method, status, calculation):
        assert 0 <= lower <= amount <= upper
        self.flows.append(dict(id=f'asx_{receiver.lower()}_{year}_{payer.lower()}_{typ}',
                               payer=payer, receiver=receiver, year=year, visa_group='other',
                               visa_type=typ, visa_label='独立签证费收入科目' if receiver == 'FJI' else '已签发签证标准费值',
                               category_detail_status='unclassified', amount=amount, lower=lower,
                               upper=upper, currency=currency, quantity=quantity, quantity_basis=quantity_basis,
                               source_ids=list(dict.fromkeys(sources)), observation_ids=list(dict.fromkeys(observations)),
                               method_id=method, model_status=status, calculation_type=calculation,
                               origin_basis='unallocated' if payer == 'UNK' else 'observed_nationality',
                               period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                               period_type='calendar_year_model', period_label=str(year), notes=notes,
                               parameters=params))

    def fiji(self):
        sb = self.source('fji_budget_process', 'fiji_budget_process.html',
                         'https://www.finance.gov.fj/budget-process/',
                         'Ministry of Finance, Republic of Fiji', 'National budget process and fiscal-year definition',
                         'Financial year begins1August and ends31July; budget distinguishes actual collected prior-year revenue from projections and estimates.')
        assert 'begins on 1 August' in html('fiji_budget_process.html')
        assert 'ends on 31 July' in html('fiji_budget_process.html')
        budgets = [
            (2021, '2022_23', 313, 312, 39.7, 'https://www.finance.gov.fj/wp-content/uploads/2023/09/2022-2023_Budget_Estimates_-_As_Approved_by_Parliament.pdf'),
            (2022, '2023_24', 341, 340, 137.2, 'https://www.finance.gov.fj/wp-content/uploads/2023/12/budget-2023.pdf'),
            (2023, '2024_25', 323, 322, 410.7, 'https://www.finance.gov.fj/wp-content/uploads/2024/07/Final-Budget_2024-v2-3.pdf'),
            (2024, '2025_26', 339, 338, 341.8, 'https://www.finance.gov.fj/wp-content/uploads/2025/06/2025-2026-Budget-Estimates.pdf'),
            (2025, '2026_27', 349, 348, 453.4, 'https://www.finance.gov.fj/wp-content/uploads/2026/08/Budget-Estimates-2026-2027.pdf'),
        ]
        actuals, oids, sids = {}, {}, {}
        for end, edition, page, printed, thousands, url in budgets:
            filename = f'fiji_budget{edition}.pdf'
            sid = self.source(f'fji_budget{edition}', filename, url,
                              'Ministry of Finance, Republic of Fiji', f'Budget Estimates {edition.replace("_", "–")}: Actual Visa Fees',
                              f'PDF p{page}, printed p{printed}; first numeric column Actual FY{end-1}–{end}. Units FJD thousands. Immigration Fees, Permit Fees and Citizenship Fees are separate and excluded.')
            text = PdfReader(RAW / filename).pages[page-1].extract_text()
            assert 'Actual' in text and f'{end-1}-{end}' in text and '($000)' in text
            line = next(x for x in text.splitlines() if re.search(r'\bVisa Fees\b', x))
            values = re.findall(r'\d[\d,]*\.\d+', line.split('Visa Fees', 1)[1])
            assert len(values) == 6 and float(values[0].replace(',', '')) == thousands, (filename, line)
            assert ('Immigration Fees' in text or 'Passport Fees' in text) and 'Permit Fees' in text and 'Citizenship Fees' in text
            (OUT / f'fji_actual_{end-1}_{end}.txt').write_text(text)
            actuals[end] = thousands * 1000
            sids[end] = sid
            oids[end] = self.observation(f'fji_fy{end-1}_{end}_visa_revenue', 'FJI', end,
                                         'visa_fees_reported_actual_revenue', thousands*1000, 'FJD', sid,
                                         f'PDF p{page}, printed p{printed}: Visa Fees, first numeric column Actual {end-1}-{end}, ($000)',
                                         raw_metric='Visa Fees, Actual ($000)', raw_value=thousands, raw_unit='FJD_thousands',
                                         period_start=f'{end-1}-08-01', period_end=f'{end}-07-31', period_type='fiscal_year',
                                         reporting_precision_FJD=100, revenue_column='Actual',
                                         visa_type='government_visa_fee_revenue_unclassified',
                                         notes='政府预算原件的独立签证费Actual收入科目，按原表千斐济元换算；不含较宽的护照及签证Immigration Fees、Permit Fees、公民身份费。无申请量或付款国籍。')
        sf = self.source('fji_fx_wdi', 'fiji_fx_wdi_2011_2025.json',
                         'https://api.worldbank.org/v2/country/FJI/indicator/PA.NUS.FCRF?format=json&per_page=100',
                         'World Bank WDI / IMF International Financial Statistics',
                         'PA.NUS.FCRF: Fiji official exchange rate, annual average LCU per USD')
        rawfx = json.loads((RAW / 'fiji_fx_wdi_2011_2025.json').read_text())
        rates = {int(r['date']): r['value'] for r in rawfx[1] if r['value'] is not None}
        for year in range(2021, 2026):
            rate = rates[year]
            assert 1 < rate < 4
            self.fx.append(dict(fx_id=f'asx_fjd_{year}_wdi', year=year, currency='FJD', raw_rate=rate,
                                raw_direction='currency_per_USD', usd_per_unit=1/rate,
                                source_id=sf, source_ids=[sf], source_locator=f'PA.NUS.FCRF FJI {year}',
                                method='World Bank annual-average FJD per USD inverted to USD per FJD'))
        for year in range(2021, 2026):
            scenario = year == 2025
            if scenario:
                amount = actuals[2025]
                lower, upper = amount*.75-50, amount*1.25+50
                sources, observations = [sids[2025], sb], [oids[2025]]
                params = dict(anchor_fiscal_year='2024-2025', anchor_actual_revenue_FJD=amount,
                              annual_runrate_multiplier=1, annual_runrate_multiplier_range=[.75,1.25],
                              observed_calendar_year_revenue=False, observed_application_quantity=False,
                              fiscal_receipts_rounding_half_width_FJD=50,
                              range_method='最新2024/25财年Actual收入的全年运行率±25%工作情景，加原表±50斐济元舍入；非2025自然年实收或置信区间')
            else:
                a, b = actuals[year], actuals[year+1]
                weight = 7/12
                amount = a*weight + b*(1-weight)
                candidates = [a*w+b*(1-w) for w in [weight-.1, weight+.1]]
                lower, upper = min(candidates)-50, max(candidates)+50
                sources, observations = [sids[year], sids[year+1], sb], [oids[year], oids[year+1]]
                params = dict(first_fiscal_year=f'{year-1}-{year}', second_fiscal_year=f'{year}-{year+1}',
                              first_fiscal_actual_revenue_FJD=a, second_fiscal_actual_revenue_FJD=b,
                              first_fiscal_calendar_share=weight, second_fiscal_calendar_share=1-weight,
                              fiscal_timing_weight_range=[weight-.1,weight+.1],
                              fiscal_receipts_rounding_half_width_FJD=50,
                              observed_calendar_year_revenue=False, observed_application_quantity=False,
                              range_method='两个相邻财年Actual签证费按7/12和5/12桥接；同一互补分配权重±0.10为时点敏感性情景，加原表±50斐济元舍入，非置信区间')
            self.flow('UNK', 'FJI', year, 'visa_revenue_runrate' if scenario else 'visa_revenue_calendar_bridge',
                      amount, lower, upper, 'FJD', sources, observations, None,
                      'fiscal_revenue_only_no_observed_application_denominator',
                      ('2025按最新2024/25财年Actual签证费运行率估算，±25%工作情景；未把预算Estimate当成实收。' if scenario else
                       '自然年中心为相邻两个财年Actual签证费的7/12+5/12桥接；不是原始自然年披露。') +
                      '只计独立Visa Fees科目；排除护照、许可、公民身份及广义移民收入。国籍及申请量未披露，付款方保留UNK，不推算每申请人花费。',
                      params, 'asx_fji_actual_calendar_bridge',
                      'fiscal_actual_runrate_scenario' if scenario else 'reported_actual_revenue_calendar_bridge_estimate',
                      'conditional_scenario' if scenario else 'fiscal_to_calendar_bridge')
            self.ranges.append(dict(receiver='FJI',year=year,amount=amount,lower=lower,upper=upper,currency='FJD',range_method=params['range_method']))
        self.models.append(dict(model_id='asx_fji_actual_calendar_bridge', destination='FJI', years=list(range(2021,2026)),
                                status='fiscal_actuals_calendar_bridge_and_2025_runrate',
                                formula='CY y = 7/12 Actual(FY y-1/y) + 5/12 Actual(FY y/y+1); CY2025 = Actual(FY2024/25) run-rate',
                                limitations=['原始收入为8月到次年7月财年；自然年金额为模型桥接。',
                                             '独立Visa Fees科目只构成部分国家签证收入覆盖；未将较宽移民/护照/许可收入替代签证收入。',
                                             '±0.10时间权重和2025±25%运行率是工作情景，不是统计置信区间。',
                                             '无付款国籍或申请数量，均不按旅游入境量分配。']))

    def georgia(self):
        sp = self.source('geo_migration2021', 'georgia_profile2021.pdf',
                         'https://migration.commission.ge/files/mmp21_eng_web3c.pdf',
                         'State Commission on Migration Issues, Georgia / Ministry of Foreign Affairs / Ministry of Internal Affairs',
                         '2021 Migration Profile of Georgia: Georgian Visas, 2016–2020',
                         'PDF/printed p29: category totals and MFA C-category nationalities. Category totals include MIA border visas; nationality table MFA totals are slightly smaller. p30 D quantities; 2019 D country table2103 vs category total2106 retained.')
        sl = self.source('geo_consular_law2018', 'georgia_consular_fee_law2018.pdf',
                         'https://www.matsne.gov.ge/en/document/download/1042331/6/en/pdf',
                         'Legislative Herald of Georgia / Parliament of Georgia',
                         'Law of Georgia on Consular Fees, consolidated publication6 (26December2018)',
                         'Article4(1)(b) USD20 visa review; Article4 latest listed amendment17July2015. Article5 exemptions and Article2 reciprocity retained. Publication6 valid until26June2025; tariff continuity from2016 is identified by unchanged Article4 amendment history, not a2026snapshot.')
        se = self.source('geo_emn2024', 'georgia_emn2024.pdf',
                         'https://home-affairs.ec.europa.eu/document/download/46fac166-7756-4709-9885-a1b12193abd1_en?filename=2024_EMN-ESTAT_GE_countryfactsheet.pdf',
                         'European Migration Network / European Commission, relevant Georgian national authority',
                         'EMN Observer Country Factsheet Georgia2024: Borders and Visas, 2021–2024',
                         'PDF p10. Short-stay visas2021–24;2024 citizenship top3 counts. Percentages explicitly share of all visas, not share of short-stay subtotal; use counts only, no percentage-derived nationalities.')
        p = PdfReader(RAW / 'georgia_profile2021.pdf')
        t, td = p.pages[28].extract_text(), p.pages[29].extract_text()
        e = PdfReader(RAW / 'georgia_emn2024.pdf').pages[9].extract_text()
        law = '\n'.join(p.extract_text() for p in PdfReader(RAW / 'georgia_consular_fee_law2018.pdf').pages)
        assert 'issuanceofaGeorgianvisa-USD20' in compact(law)
        assert 'diplomaticandspecialGeorgianvisas' in compact(law)
        assert '17 July 2015' in law and 'Law of Georgia No 4059' in law
        assert '26,343' in t and '45,576' in t and '6,977' in t
        crow = next(line for line in t.splitlines() if line.startswith('C ') and '26,343' in line)
        drow = next(line for line in t.splitlines() if line.startswith('D ') and '1,747' in line)
        assert [int(v.replace(',','')) for v in re.findall(r'\d[\d,]*',crow)] == [26343,27819,31932,45576,6977,138647]
        assert [int(v.replace(',','')) for v in re.findall(r'\d[\d,]*',drow)] == [1747,2535,2185,2106,503,9076]
        assert '7539(63.8%)' in compact(e) and '45151(80.4%)' in compact(e)
        assert 'shareofallvisasissued' in compact(e)
        for filename, text in [('geo_category_and_nationality2016_2020.txt',t),('geo_immigration2016_2020.txt',td),
                               ('geo_short_stay2021_2024.txt',e),('geo_consular_fee_law2018.txt',law)]:
            (OUT / filename).write_text(text)
        self.fees.append(dict(id='asx_geo_visa_review20',fee_rule_id='asx_geo_visa_review20',destination='GEO',
                              visa_type='visa_review_standard_tariff',visa_group='other',amount=20,currency='USD',
                              component='government_visa_fee',source_id=sl,source_ids=[sl],
                              source_locator='Law on Consular Fees Article4(1)(b), Article2 and Article5',
                              effective_from=None,effective_to='2025-06-25', historical_snapshot_year=2018,
                              validity_status='2018_consolidation_article4_amendment_history_through2015',
                              modeled_years=list(range(2016,2025)),payment_trigger='visa_application_review',
                              exemptions=['diplomatic_and_special_visas','foreign_family_of_Georgian_citizens',
                                          'official_delegations','humanitarian_and_charity_duty','treaty_and_discretionary_exemptions'],
                              notes='20美元为法定一般审理费；本文仅输出已签发普通C/短期签证的标准费值。未观测减免或互惠调整，故不将标准费值解释为实际支付；A/B外交特殊签证和D移民签证均未进入金额。无服务费。'))
        totals = {2016:26343,2017:27819,2018:31932,2019:45576,2020:6977,
                  2021:7539,2022:15054,2023:43856,2024:45151}
        cc = {
            2016:{'IND':10406,'CHN':8274,'EGY':2992,'IRN':1434,'PHL':590},
            2017:{'CHN':12136,'IND':9451,'EGY':2957,'PHL':846,'IDN':433},
            2018:{'CHN':21009,'IND':4993,'EGY':1468,'PHL':1006,'IDN':504},
            2019:{'CHN':30811,'IND':8161,'EGY':2017,'PHL':1597,'IDN':577},
            2020:{'CHN':3635,'IND':1660,'PHL':504,'EGY':452,'MKD':192},
            2021:{},2022:{},2023:{},2024:{'IND':34287,'EGY':3449,'PHL':1705}}
        country_totals = {2016:26271,2017:27756,2018:31863,2019:45536,2020:6963}
        d_totals = {2016:1747,2017:2535,2018:2185,2019:2106,2020:503}
        for year, total in d_totals.items():
            assert f'{total:,}' in t
            self.observation(f'geo_{year}_d_issued', 'GEO',year,'immigration_D_visas_issued',total,'visas',sp,
                             'PDF p29 category D row',visa_type='immigration_D',eligible_money_ledger=False,
                             notes='D类移民签证，仅作数量证据；未取得分类用途及家庭减免匹配，不输出金额。')
        self.observation('geo_2019_d_citizenship_table_total','GEO',2019,'immigration_D_visas_citizenship_table_total',2103,'visas',sp,
                         'PDF p30 nationality table TOTAL2019',visa_type='immigration_D',eligible_money_ledger=False,
                         conflict_group='geo2019_D_total',notes='国籍表2103与p29类别总量2106相差3；保留原文差异。D类不进入金额。')
        for year, total in totals.items():
            sid = sp if year <= 2020 else se
            text = t if year <= 2020 else e
            token = f'{total:,}' if year <= 2020 else f'{total:,}'.replace(',','')
            assert token in (text if year <= 2020 else compact(text)),(year,total)
            typ = 'ordinary_C' if year <= 2020 else 'short_stay'
            locator = 'PDF p29 category C row (MFA+MIA)' if year <= 2020 else 'PDF p10 short-stay visas issued chart'
            oid = self.observation(f'geo_{year}_{typ}_issued','GEO',year,f'{typ}_visas_issued',total,'visas',sid,
                                   locator,visa_type=typ,
                                   notes='普通C类签发量含MFA与MIA边境签证；不是唯一人数或含拒签的申请量。' if year<=2020 else
                                   '原文短期签发量；不是付费申请总量。百分比分母是全部签证，未据比例分摊。')
            extra_obs = []
            if year <= 2020:
                extra_obs.append(self.observation(f'geo_{year}_c_nationality_total','GEO',year,
                                                  'ordinary_C_MFA_citizenship_table_total',country_totals[year],'visas',sp,
                                                  'PDF p29 C-category citizenship table TOTAL',visa_type=typ,
                                                  national_category_total=total,unallocated_border_difference=total-country_totals[year],
                                                  notes='MFA国籍表小计小于含MIA边境签证的类别总量；差额不按国籍分配，留在UNK。'))
            national_obs = {}
            for payer, qty in cc[year].items():
                assert (f'{qty:,}' in t if year<=2020 else str(qty) in compact(e)),(year,payer,qty)
                national_obs[payer] = self.observation(f'geo_{year}_{payer.lower()}_{typ}_issued','GEO',year,
                                                      f'{typ}_visas_issued',qty,'visas',sid,
                                                      'PDF p29 C-category citizenship table' if year<=2020 else 'PDF p10 short-term citizenship top3 counts',
                                                      nationality=payer,visa_type=typ,
                                                      notes='中国大陆国籍的真实签发数量。' if payer=='CHN' else
                                                      '使用原文国籍数量；2024百分比基于全部签证，未将其误作短期签证占比。' if year==2024 else '原文国籍签发量。')
            counts = {**cc[year], 'UNK': total-sum(cc[year].values())}
            assert counts['UNK'] >= 0 and sum(counts.values()) == total
            for payer, qty in counts.items():
                amount = qty * 20
                params = dict(issued_visas=qty,aggregate_issued_total=total,standard_review_fee_USD=20,
                              actual_receipts_observed=False,actual_paid_applications_observed=False,
                              fee_value_basis='unadjusted_standard_tariff_equivalent_of_issued_cohort',
                              exemption_adjustment_observed=False,reciprocal_tariff_adjustment_observed=False,
                              charged_share_range=[0,1],charged_share_observed=False,
                              central_value_basis='full_statutory_standard_value_not_actual_revenue_point_estimate',
                              interval_scope='issued_C_or_short_stay_cohort_only_not_refused_paid_applications',
                              refused_paid_applications_excluded=True,services_excluded=True,
                              nationality_allocation='published nationality counts only; residual+unallocated border visas UNK',
                              range_method='中心为已签发队列全额20美元法定标准费值，不是实际收入点估计；收费比例未观测，下/上情景取0%/100%标准收费值。此识别/工作情景不覆盖未签发的付费申请，也不是财政实收置信区间')
                obsids = [oid,*extra_obs] + ([national_obs[payer]] if payer in national_obs else [])
                self.flow(payer,'GEO',year,'issued_standard_fee_equivalent',amount,0,amount,'USD',[sid,sl],
                          obsids,qty,'observed_visas_issued_not_unique_people_or_paid_applications',
                          ('C类普通签证；排除A/B外交特殊签证及D类移民签证。' if year<=2020 else '官方短期签发数量。')+
                          '中心为签发数量×20美元全额法定标准费值，不是实际收入点估计；减免比例未观测，下/上情景为该已签发队列0%/100%标准收费值。未覆盖未签发付费申请、互惠费率或退款，不能视为财政实收或申请人的实际支出。'+
                          ('MFA国籍表与含MIA边境的类别总量差额保留UNK。' if year<=2020 else
                           '2024国籍百分比分母为全部签证，只采用公开数量，余量UNK。' if year==2024 else '未公开匹配国籍数量，全部保留UNK。'),
                          params,'asx_geo_issued_standard_tariff','issued_standard_tariff_value_partial_estimate',
                          'deterministic_tariff_value')
            self.ranges.append(dict(receiver='GEO',year=year,amount=total*20,lower=0,upper=total*20,
                                    currency='USD',range_method='中心为已签发队列全额20美元标准费值；0–100%收费比例识别/工作情景，非实际收入点估计或实收置信区间，不覆盖未签发付费申请'))
        self.models.append(dict(model_id='asx_geo_issued_standard_tariff',destination='GEO',years=list(totals),
                                status='observed_issuances_unadjusted_standard_tariff_equivalent',
                                formula='published ordinary C (2016–2020) / short-stay (2021–2024) issuances * USD20 standard review fee',
                                limitations=['这是签发群体的一般标准费值，不是实际支付、财政实收或含拒签的付费申请量。',
                                             '外交特殊A/B类及D移民类未进入金额；法定减免、互惠费率及退款未观测，未虚构付费比例。',
                                             '中心是全额法定标准值而非实际收入点估计；下/上情景按已签发队列0%/100%收费比例，未覆盖未签发付费申请。',
                                             '2018合并法第4条最近所列修订为2015年7月；据此沿用到2016—2024，不以当前网页反推历史。',
                                             '2016—2020国籍表仅MFA，类别总量含MIA边境；差额保留UNK。',
                                             '2024原图国籍百分比以全部签证为分母；只用数量，不据百分比推算。',
                                             '2019D类表2103与类别总量2106差3，原始冲突保留且不影响金额。']))

    def finish(self):
        sids={s['source_id'] for s in self.sources};oids={o['observation_id'] for o in self.obs}
        assert len(sids)==len(self.sources) and len(oids)==len(self.obs)
        assert len({f['id'] for f in self.flows})==len(self.flows)
        for f in self.flows:
            assert set(f['source_ids'])<=sids and set(f['observation_ids'])<=oids
            assert f['payer'] not in ('WORLD',f['receiver'])
            if f['receiver']=='FJI':
                assert f['payer']=='UNK' and f['quantity'] is None
            else:
                assert f['amount']==f['quantity']*20 and f['lower']==0 and f['upper']==f['amount']
                assert f['parameters']['actual_receipts_observed'] is False
                assert f['parameters']['charged_share_range']==[0,1]
                assert f['parameters']['charged_share_observed'] is False
        for obs in self.obs:
            assert set(obs['source_ids'])<=sids
        for fx in self.fx:
            assert abs(fx['usd_per_unit']*fx['raw_rate']-1)<1e-12
        for r in self.ranges:
            ff=[f for f in self.flows if f['receiver']==r['receiver'] and f['year']==r['year']]
            for key in ('amount','lower','upper'):
                assert abs(sum(f[key] for f in ff)-r[key])<.01
            if r['receiver']=='GEO':
                assert sum(f['quantity'] for f in ff)==r['amount']/20
        scopes={(f['receiver'],f['year']) for f in self.flows}
        packages,overlap=[],[]
        for path in sorted(EST.parent.glob('*_flows.json')):
            if path==EST: continue
            packages.append(str(path.relative_to(ROOT)))
            for f in json.loads(path.read_text()).get('flows',[]):
                if (f.get('receiver'),f.get('year')) in scopes:overlap.append((str(path),f.get('id')))
        assert not overlap,overlap
        coverage=[]
        for code,years in {'FJI':range(2021,2026),'GEO':range(2016,2025)}.items():
            ss=[s['source_id'] for s in self.sources if s['source_id'].startswith('asx_'+code.lower())]
            for year in years:
                for group in GROUPS:
                    aggregate=group=='other'
                    ff=[f for f in self.flows if f['receiver']==code and f['year']==year and aggregate]
                    context=aggregate and any(o['destination']==code and o['year']==year for o in self.obs)
                    note=('2021—2024相邻财年Actual独立Visa Fees科目桥接；2025为2024/25财年实际运行率±25%情景。未取得国籍或申请量。' if code=='FJI' else
                          '普通C类/短期签证真实签发量与20美元一般标准费值；不是实收或实际支出，未虚构减免率。D类另存数量。')
                    coverage.append(dict(code=code,destination=code,name=NAMES[code],region='大洋洲' if code=='FJI' else '亚洲',
                                         year=year,visa_group=group,status='amount_modeled' if ff else 'not_found',
                                         fee_known=aggregate and code=='GEO',fee_current_snapshot_known=aggregate and code=='GEO',
                                         quantity_known=aggregate and code=='GEO',quantity_context_known=context and code=='GEO',
                                         category_detail_status='unclassified_aggregate' if aggregate else 'no_classified_observation',
                                         arrival_context_known=False,amount_known=False,amount_modeled=bool(ff),
                                         fiscal_amount_known=aggregate and code=='FJI',
                                         nationality_known=aggregate and code=='GEO' and (year<=2020 or year==2024),
                                         notes=note if aggregate else '本类别尚未单独拆分；'+note,source_ids=ss,searched_as_of=ASOF))
        totals=defaultdict(float)
        for f in self.flows:totals[f"{f['receiver']}_{f['year']}_{f['currency']}"]+=f['amount']
        checks=dict(as_of=ASOF,sources=len(sids),observations=len(oids),fees=len(self.fees),fx=len(self.fx),
                    flows=len(self.flows),receivers=sorted(NAMES),years=sorted({f['year'] for f in self.flows}),
                    receiver_years=len(scopes),coverage_rows=len(coverage),totals_native=dict(totals),
                    no_duplicate_existing_receiver_year=True,overlap_checked_packages=packages,
                    source_archives='official originals, bytes and SHA256 registered; table values asserted at exact PDF pages',
                    fiji_actual_column_not_estimate=True,fiji_fiscal_year_and_currency_units_asserted=True,
                    fiji_no_fabricated_applicant_denominator=True,
                    georgia_no_diplomatic_special_or_D_visa_fee_value=True,
                    georgia_issued_fee_value_not_claimed_as_actual_cash=True,
                    georgia_center_full_statutory_value_not_revenue_point_estimate=True,
                    georgia_unobserved_waiver_range_zero_to_full_issued_cohort_value=True,
                    georgia_range_excludes_unissued_paid_applications=True,
                    georgia_country_plus_UNK_equals_category_total=True,
                    georgia_MFA_MIA_total_scope_difference_retained=True,
                    georgia2024_percent_denominator_not_used_for_allocation=True,
                    georgia2019_D_total_conflict_retained=True,
                    fx_direction_reciprocal_checked=True,
                    china_hongkong_macao_taiwan_naming='CHN labeled中国大陆; no new Hong Kong/Macao/Taiwan nodes introduced')
        package=dict(package='asia_expansion_v3',as_of=ASOF,flows=self.flows,models=self.models,destination_ranges=self.ranges,
                     subtotals=[],coverage_rows=len(coverage),
                     scope='Fiji2021–2024fiscal-actual visa-fee calendar bridges and2025runrate; Georgia2016–2024ordinary-C/short-stay issued standard tariff values; D quantities only')
        for name,obj in [('sources.json',self.sources),('observations.json',self.obs),('fee_rules.json',self.fees),
                         ('fx.json',self.fx),('coverage.json',coverage),('checks.json',checks),
                         ('search_log.json',[
                             dict(destination='FJI',result='2022/23–2026/27 official budget actual Visa Fees; early budgets broad Immigration Fees not used; official fiscal calendar and WDI FX',searched_at=ASOF),
                             dict(destination='GEO',result='2021 migration profile2016–20C/D quantities; EMN2024factsheet2021–24short stays;2018consolidated consular law20USD tariff and exemptions; ordinaryC/shortstay standard values only',searched_at=ASOF),
                             dict(destination='ARM',result='Official2023/2024MFA annual reports archived as research candidates; no isolated verified visa amount or issuance cohort extracted; not registered as supporting monetary sources',searched_at=ASOF)])]:
            (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
        EST.write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n')
        (OUT/'README.md').write_text('''# 亚洲及太平洋数据扩展 v3

运行：`.research-venv/bin/python scripts/research_asia_expansion_v3.py`。脚本离线读取冻结原件，核对原表数量、Actual列、币种单位、国籍残差、来源哈希及现有金额包重叠；输出金额包、观测、费率、汇率、覆盖及检查结果。

斐济新增2020/21—2024/25五个实际财年独立Visa Fees收入科目，分别39,700、137,200、410,700、341,800、453,400斐济元。只计独立签证费，不把包含护照的Immigration Fees、Permit Fees或Citizenship Fees算入。2021—2024自然年中心按相邻财年7/12与5/12桥接，分配权重±0.10作为时点敏感性工作情景；2025按最新实际财年运行率±25%情景。原表精度为100斐济元；区间加±50元舍入。未把预算估计当实收，未推算申请人或国籍。WDI汇率保留原方向并取倒数。

格鲁吉亚新增2016—2020普通C类、2021—2024短期签证真实签发量；2016—2020前五国籍及2024前三国籍直接使用原文数量，余量保留UNK。中心是数量×法定20美元的全额标准费值，不是实际收入点估计，不能解释为财政收入、实际支付或含拒签的付费申请总量。减免比例未观测，下/上情景取该已签发队列0%/100%标准收费比例，因此下端为0、上端为完整标准费值；这是识别/工作情景，不是统计置信区间，也不覆盖未签发的付费申请。2018合并法第4条列出的最近修订为2015年7月；2016—2024按这一条文连续费率换算。法定减免、互惠差异和退款未观测，未虚构一个实际付费比例；外交/特殊A/B和移民D类没有进入金额。互惠加收差异未纳入该标准收费情景。

原始差异完整保留：2016—2020MFA国籍小计小于含MIA边境签证的C类别总量，差额仅入UNK。2019D类国籍表2103与类别表2106差3，两个原值均保存。2024EMN国籍百分比按全部签证为分母，只用其公开数量，未按百分比分配短期总量。

中国国籍以中国大陆标注；本包没有新增港澳台节点。签发数量为事件数，不是去重人数。未以游客入境量乘费率。
''')
        manifest={s['local_path'].split('/')[-1]:s['url'] for s in self.sources}
        (RAW/'registered_sources_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(checks,ensure_ascii=False))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    r=Research();r.fiji();r.georgia();r.finish()


if __name__=='__main__':main()
