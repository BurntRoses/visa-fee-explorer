#!/usr/bin/env python3
"""Rebuild the 2024/25 Korea and Vietnam extension from frozen evidence.

The observed metrics are not interchangeable: consular visa issuances, approval
certificates, entry-permit transactions and arrivals remain separate. Korea's
budget benchmark and Vietnam's issued-visa tariff values are scenarios, not
reported cash receipts. Saudi/UAE observations are retained without invented cash.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
from openpyxl import load_workbook
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/spatial_extension'
OUT = ROOT / 'data/research/spatial_extension'
EST = ROOT / 'data/estimates/spatial_extension_flows.json'
ASOF = '2026-11-16'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
NAMES = {'KOR': '韩国', 'VNM': '越南', 'ARE': '阿联酋', 'SAU': '沙特阿拉伯'}


def text(path):
    return BeautifulSoup((ROOT / path).read_text(), 'html.parser').get_text(' ', strip=True)


class Research:
    def __init__(self):
        self.sources, self.fees, self.obs = [], [], []
        self.flows, self.models, self.ranges, self.log = [], [], [], []

    def source(self, slug, path, url, publisher, title, notes='', quality='official_original'):
        p = ROOT / path
        assert p.exists(), path
        sid = 'spx_' + slug
        self.sources.append(dict(source_id=sid, url=url, publisher=publisher, title=title,
                                 retrieved_at=ASOF, source_quality=quality, local_path=path,
                                 path=path, bytes=p.stat().st_size,
                                 sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                 archive_kind='original_document', notes=notes))
        return sid

    def observation(self, slug, destination, year, metric, value, unit, sid, locator, **extra):
        oid = 'spx_' + slug
        self.obs.append(dict(observation_id=oid, destination=destination, year=year,
                             metric=metric, raw_metric=extra.pop('raw_metric', metric),
                             value=value, unit=unit, source_id=sid, source_ids=[sid],
                             source_locator=locator, nationality='UNK', origin_basis='unallocated',
                             visa_type=extra.pop('visa_type', 'all'), visa_group='other',
                             period_start=extra.pop('period_start', f'{year}-01-01'),
                             period_end=extra.pop('period_end', f'{year}-12-31'),
                             period_type=extra.pop('period_type', 'calendar_year'), **extra))
        return oid

    def flow(self, receiver, year, typ, amount, lower, upper, currency, sources, observations,
             quantity, basis, notes, parameters, method):
        assert 0 <= lower <= amount <= upper
        self.flows.append(dict(id=f'spx_{receiver.lower()}_{year}_{typ}', payer='UNK', receiver=receiver,
                               year=year, visa_group='other', visa_type=typ,
                               visa_label='类别未细分', category_detail_status='unclassified',
                               amount=amount, lower=lower, upper=upper, currency=currency,
                               quantity=quantity, quantity_basis=basis,
                               source_ids=list(dict.fromkeys(sources)), observation_ids=list(dict.fromkeys(observations)),
                               method_id=method, model_status='modeled_estimate',
                               calculation_type='conditional_scenario', origin_basis='unallocated',
                               period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                               period_type='calendar_year_model', period_label=str(year),
                               notes=notes, parameters=parameters))
        self.ranges.append(dict(receiver=receiver, year=year, amount=amount, lower=lower, upper=upper,
                                currency=currency, range_method=parameters['range_method']))

    def korea(self):
        s25 = self.source('kr_nabo2025', 'data/raw/spatial_extension/kr_nabo2025.pdf',
                          'https://www.nabo.go.kr/board/file/down.do?fid=33318495',
                          'Korea National Assembly Budget Office / Ministry of Foreign Affairs',
                          'Public Finance of the Republic of Korea 2025',
                          'PDF p580 / printed p562. Visa issuances are consular actual counts; visa-income amounts are expected/budget amounts, not settled receipts. The sentence calling the updated forecast 2024 has an internal year typo; the explicit 2024 comparison benchmark is retained, the ambiguous forecast is not used as actual cash.')
        s26 = self.source('kr_nabo2026', 'data/raw/spatial_extension/kr_nabo2026.pdf',
                          'https://nabo.go.kr/board/file/bulkDown.do?bid=19&idx=9183',
                          'Korea National Assembly Budget Office / Ministry of Foreign Affairs',
                          'Public Finance of the Republic of Korea 2026',
                          'PDF p632 / printed p614; actual overseas-mission visa issuance counts 2020–2025. Not Ministry of Justice approval certificates.')
        a = PdfReader(ROOT / self.sources[-2]['local_path']).pages[579].extract_text()
        b = PdfReader(ROOT / self.sources[-1]['local_path']).pages[631].extract_text()
        assert all(v in a for v in ['2,333,257', '1,362', '1,607', '수입금 예상액'])
        assert all(v in b for v in ['2,317,200', '2,333,257', '1,869,477'])
        ids = {}
        quantities = {2020: 383357, 2021: 309235, 2022: 676772, 2023: 1869477,
                      2024: 2333257, 2025: 2317200}
        for year, qty in quantities.items():
            ids[year] = self.observation(f'kr_{year}_consular_issued', 'KOR', year,
                                        'visas_issued_overseas_missions', qty, 'visas', s26,
                                        'PDF p632 / printed p614, 영사서비스 주요 통계(2020~2025년), 재외공관 사증발급',
                                        raw_metric='재외공관 사증발급', calculation_type='direct_observation',
                                        notes='真实驻外签证签发件数；不是入境次数，也不是法务部사증발급인정서认定书。拒签付款未包含在签发量中。')
        budget = 1362 * 100000000
        boid = self.observation('kr_2024_visa_revenue_budget_benchmark', 'KOR', 2024,
                               'visa_issuance_revenue_budget_benchmark', budget, 'KRW', s25,
                               'PDF p580 / printed p562, paragraph immediately above consular-statistics table',
                               raw_metric='2024년 1,362억원; 사증발급 수입금 예상액',
                               calculation_type='official_budget_benchmark',
                               account_scope='overseas-mission visa issuance income expectation; separate from passport services',
                               notes='2024预算／预期比较基准1362亿韩元，不是2024决算实收。相邻1607亿预期句有年份笔误，未把它当2025已收。')
        self.observation('kr_ambiguous_forecast_context', 'KOR', 2025,
                         'visa_issuance_revenue_forecast_ambiguous_year_excluded', 1607 * 100000000,
                         'KRW', s25, 'PDF p580 / printed p562, same paragraph',
                         calculation_type='official_forecast_context_only',
                         period_type='budget_forecast_year_ambiguous', eligible_money_ledger=False,
                         account_scope='visa issuance expected income; document sentence repeats 2024 although comparison is 2024 versus 2025-budget context',
                         notes='原件年份文字歧义；仅保存预期值，未替换实收，未用于金额中心或跨年增长。')
        for year in (2024, 2025):
            ratio = quantities[year] / quantities[2024]
            amount = budget * ratio
            params = dict(budget_anchor_2024_KRW=budget, anchor_is_actual_receipt=False,
                          issued_2024=quantities[2024], issued_in_year=quantities[year],
                          issuance_ratio=ratio, budget_realisation_multiplier=1,
                          budget_realisation_range=[0.7, 1.3],
                          multiplier_evidence='working sensitivity, not measured budget forecast error',
                          fee_mix_and_waivers='held constant in bridge; unobserved',
                          payment_clock='fee due on application; issued cases exclude rejected fee payments',
                          nationality_allocation='none',
                          range_method='2024官方预算基准×当年/2024驻外签发比×0.7–1.3工作敏感性；不是实收置信区间')
            self.flow('KOR', year, 'consular_budget_anchored_all_visas', amount, amount * .7,
                      amount * 1.3, 'KRW', [s25, s26], [boid, ids[2024], ids[year]],
                      quantities[year], 'observed_consular_visa_issuance_not_paid_applications',
                      '韩国驻外签证收入工作模型，以2024官方预算预期1362亿韩元为锚，2025按真实签发量比值桥接；减免、拒签付款、类型组合和预算兑现率未观察，±30%为工作敏感性。付款国籍及用途未拆分。',
                      params, 'spx_kr_budget_issuance_bridge')
        self.models.append(dict(model_id='spx_kr_budget_issuance_bridge', destination='KOR', years=[2024, 2025],
                                status='budget_anchored_scenario_unallocated',
                                formula='KRW136.2bn * overseas_mission_issued[year]/2333257 * budget_realisation_multiplier',
                                limitations=['中心来自官方预算预期，不是决算实收。',
                                             '2025保持单位签发对应收入不变；类型、减免、汇率和拒签付款结构变化未知。',
                                             '0.7–1.3是公开的敏感性参数，不是经回测的置信区间。',
                                             '国籍未知，金额只进入韩国收到，不归给中国等任何具体付款国。']))

    def vietnam(self):
        s24 = self.source('vn_2024h1_issued', 'data/raw/spatial_extension/vn_vna2024_original.html',
                          'https://vietnamnews.vn/society/1661049/viet-nam-makes-strides-in-immigration-services.html',
                          'Vietnam News Agency / Viet Nam News', 'Việt Nam makes strides in immigration services',
                          'Contemporaneous 2024 article quotes Immigration Department deputy director: nearly 1.5m e-visas in first six months 2024; 1.7m personnel applications and 8.9m arrivals are different metrics.',
                          'official_agency_report_of_department')
        s25 = self.source('vn_2025_issued', 'data/raw/spatial_extension/vn_vna2025.html',
                          'https://en.vietnamplus.vn/vietnam-steps-up-e-visa-rollout-to-protect-citizens-international-visitors-post349493.vnp',
                          'Vietnam News Agency / VietnamPlus', 'Vietnam steps up e-visa rollout to protect citizens, international visitors',
                          '26 July 2026. Quotes Immigration Department: more than 4m e-visas in 2025, up over 30%; nearly 2.5m in first half2026. Only 2025 e-visa count is modeled.',
                          'official_agency_report_of_department')
        sf = self.source('vn_government2025_fees', 'data/raw/vietnam/fees-official-2025.html',
                         'https://en.baochinhphu.vn/understanding-viet-nams-e-visa-111250218154519057.htm',
                         'Government of Viet Nam News', "Understanding Viet Nam's e-visa",
                         '19 February2025: USD25 single/USD50 multiple and no fee refund if not granted. Contemporary 2025 confirmation; historical applicability verified separately by the official 2024 consolidated regulation12/VBHN-BTC.')
        assert 'nearly 1.5 million e-visas' in text(self.sources[-3]['local_path'])
        assert 'more than four million e-visas' in text(self.sources[-2]['local_path'])
        assert 'US$25 for a single-entry visa' in text(self.sources[-1]['local_path'])
        historical = RAW / 'vn_mps_circular2023.html'
        fee_sids = [sf]
        if historical.exists() and '50 USD' in text(str(historical.relative_to(ROOT))):
            sh = self.source('vn_mps_circular2023', str(historical.relative_to(ROOT)),
                             'https://mps.gov.vn/chinh-sach-phap-luat/bai-viet/quy-dinh-moi-ve-thu-phi-linh-vuc-xuat-canh-nhap-canh-qua-canh-cu-tru-tai-viet-nam-d1-t1137',
                             'Viet Nam Ministry of Public Security', 'New immigration fee rules under Circular62/2023/TT-BTC',
                             'Contemporary official description of Circular62/2023. Multiple entry up to90days USD50.')
            fee_sids = [sh, sf]
        circular = RAW / 'vn_circular62_2023.pdf'
        if circular.exists():
            sc = self.source('vn_circular62_2023', str(circular.relative_to(ROOT)),
                             'https://www.vietnamtradeportal.gov.vn/kcfinder/upload/files/62_2023_TT-BTC_581457.pdf',
                             'Viet Nam Ministry of Finance / Viet Nam Trade Information Portal',
                             'Circular 62/2023/TT-BTC, signed 3 October 2023',
                             'Scanned original visually checked: PDF p2 Article1(2) changes multiple-entry tariff; p3 table USD50 up to90days; Article2 makes Article1(2) effective3October2023. 18November2023 applies to Article1(1) fee administration, not this tariff.')
            fee_sids = [sc] + fee_sids
        refinement = ROOT / 'data/research/evidence_refinement/korea_vietnam'
        consolidated = next(s for s in json.loads((refinement / 'sources.json').read_text())
                            if s['source_id'] == 'refine_vn_consolidated12_2024')
        archived = ROOT / consolidated['local_path']
        assert hashlib.sha256(archived.read_bytes()).hexdigest() == consolidated['sha256']
        self.sources.append(consolidated)
        historical_sid = consolidated['source_id']
        fee_sids = [historical_sid] + fee_sids
        for typ, fee in [('single_entry_evisa', 25), ('multiple_entry_evisa_up_to_90days', 50)]:
            multiple = typ.startswith('multiple')
            self.fees.append(dict(id='spx_vn_' + typ, fee_rule_id='spx_vn_' + typ, destination='VNM',
                                  visa_type=typ, visa_group='other', amount=fee, currency='USD',
                                  component='government_visa_fee', source_id=historical_sid,
                                  source_ids=fee_sids if multiple else [historical_sid, sf],
                                  source_locator='12/VBHN-BTC PDF p11 / gazette p57 sectionII row2a and footnote8; p8 / p54 footnote7; Circular62 PDF p3; 2025 GovernmentNews fee paragraph' if multiple else '12/VBHN-BTC PDF p11 / gazette p57 sectionII row1; p8 / p54 Article8(1); 2025 GovernmentNews fee paragraph',
                                  effective_from='2023-10-03' if multiple else '2021-05-22', effective_to=None,
                                  historical_snapshot_date='2024-04-04',
                                  validity_status='dated_historical_rule',
                                  payment_trigger='application_submission',
                                  refund_rule='not_refunded_if_visa_not_granted_or_applicant_declines_result',
                                  refund_source_locator='12/VBHN-BTC PDF p6 / gazette p52 Article6(3)',
                                  notes='电子签政府申请费；2024官方合并法核实历史单次25／多次不超过90天50美元。网上护照九折只针对本国护照，不适用外籍签证。签证用途未按访客／工作等分开；代理费、保险、服务费不计。'))
        o24 = self.observation('vn_2024_h1_evisa_issued', 'VNM', 2024, 'evisas_issued_approximate',
                               1500000, 'visas', s24, 'article paragraph beginning Việt Nam welcomed approximately8.9million',
                               period_end='2024-06-30', period_type='half_calendar_year',
                               raw_metric='issuing nearly 1.5 million e-visas',
                               calculation_type='rounded_reported_observation',
                               quantity_precision='nearly1.5million; representative1.5m, not exact',
                               notes='2024上半年近150万电子签；不是全年数字。未用游客数或170万其他申请数替换。')
        o25 = self.observation('vn_2025_evisa_issued_over4m', 'VNM', 2025, 'evisas_issued_reported_floor',
                               4000000, 'visas', s25, 'article paragraph Vietnam issued more than four million e-visas',
                               raw_metric='more than four million e-visas in2025, up over30%',
                               calculation_type='reported_rounded_floor', is_strict_count_floor=True,
                               notes='报道“超过400万”，400万保存为报道阈值，不是精确总数。不得用“增长超过30%”反解2024精确数。')
        scenarios = [(2024, 1500000 * 2, 1500000 * 1.6, 1500000 * 2.4, o24),
                     (2025, 4000000, 4000000, 4500000, o25)]
        for year, q, qlo, qhi, oid in scenarios:
            amount = q * 37.5
            params = dict(issued_benchmark=q, quantity_range=[qlo, qhi],
                          fee_single_USD=25, fee_multiple_USD=50, multiple_entry_share=.5,
                          multiple_entry_share_range=[0, 1], nationality_allocation='none',
                          payment_clock='fee is nonrefundable on application; rejected/abandoned paid applications absent from issuance count',
                          excluded=['paper visas', 'rejected paid applications', 'extensions', 'residence cards', 'service fees'],
                          fee_temporal_evidence='Official2024 consolidated regulation12/VBHN-BTC verifies USD25 single-entry effective2021-05-22 and USD50 multiple-entry<=90days effective2023-10-03; independently confirmed by2025 GovernmentNews',
                          quantity_method='H1 rounded1.5m * annualisation2, sensitivity1.6–2.4' if year == 2024 else 'reported over4m represented by4m; 4.5m is an explicit working upper scenario, not an observed upper bound',
                          range_method='已签发电子签收费值：数量情景×单次/多次25–50USD；拒签付款和纸签未估入')
            self.flow('VNM', year, 'issued_evisa_fee_value', amount, qlo * 25, qhi * 50,
                      'USD', list(dict.fromkeys([s24 if year == 2024 else s25] + fee_sids)), [oid], q,
                      'issued_evisa_benchmark_annual_model_not_all_paid_applications',
                      ('越南电子签签发收费值情景。2024以官方通讯社所报上半年近150万签发为基准，全年倍数2、敏感性1.6–2.4；' if year == 2024 else
                       '越南电子签签发收费值情景。2025报道超过400万，以400万作保守数量基准、450万作工作上情景；') +
                      '单次25／多次50美元，中心假设各半；真实组合、国籍、拒签付款和纸签缺失。不是全国签证实收。',
                      params, 'spx_vn_issued_evisa_tariff_mix')
        self.models.append(dict(model_id='spx_vn_issued_evisa_tariff_mix', destination='VNM', years=[2024, 2025],
                                status='issued_evisa_tariff_value_scenario',
                                formula='annual_issued_benchmark * (25*(1-multiple_share)+50*multiple_share)',
                                limitations=['只对应已签发电子签的费值，纸签、拒签与放弃申请者缴费未量化。',
                                             '2024由半年近似数桥接；2025的450万上情景没有被官方定义为真实上界。',
                                             '多次签比例中心50%为工作假设，敏感性0–100%。',
                                             '单次25美元和多次不超过90天50美元由2024官方合并法核实，分别自2021-05-22与2023-10-03生效；历史费率已知，实际单多次付费组合仍缺。',
                                             '用途和国籍未知，保留未细分类别和UNK付款国。']))

    def uae_saudi(self):
        for year, expected in ((2024, 14687542), (2025, 12116843)):
            path = f'data/raw/spatial_extension/ae_statistics{year}.xlsx'
            sid = self.source(f'ae_statistics{year}', path,
                              f'https://www.gdrfad.gov.ae/sites/default/files/gdrfa_tables/statistics/GDRFAD-Statistics{year}-en.xlsx',
                              'GDRFA Dubai', f'GDRFAD Statistics{year}',
                              'Original XLSX. Entry Permit Transactions is not an identified census of new paid tourist visa applications; only Dubai jurisdiction, not all UAE.')
            ws = load_workbook(ROOT / path, data_only=True).active
            rowno, row = next((i, row) for i, row in enumerate(ws.values, 1) if row[0] == 'Entry Permit Transactions')
            assert row[4] == expected
            self.observation(f'ae_{year}_entry_permit_transactions', 'ARE', year,
                             'dubai_entry_permit_transactions_context', expected, 'transactions', sid,
                             f'{ws.title}!E{rowno}', raw_metric='Entry Permit Transactions',
                             calculation_type='direct_observation', geography_scope='Dubai jurisdiction only',
                             eligible_money_ledger=False, notes='交易笔数，未拆新发／延期／取消、收费产品及国籍；不作为全国签证签发量，不直接乘旅游签费。')
        sid = self.source('ae_tourist_fee', 'data/raw/spatial_extension/ae_tourist_single.html',
                          'https://www.gdrfad.gov.ae/en/services/f9e586fe-0642-11ec-0320-0050569629e8',
                          'GDRFA Dubai', 'Issuance of a single-entry tourist visa',
                          'Retrieved2026-11-15; AED200/300 base tourist visa fee,5%VAT separate, in-country fees conditional. Current snapshot not backdated to2024/25.')
        assert '30-day tourist visa fee: AED 200' in text(self.sources[-1]['local_path'])
        for days, fee in [(30, 200), (60, 300)]:
            self.fees.append(dict(id=f'spx_ae_tourist_{days}d_current', destination='ARE', visa_type=f'tourist_single_{days}d',
                                  visa_group='visitor', amount=fee, currency='AED', component='government_visa_fee',
                                  source_id=sid, source_ids=[sid], effective_from=None, effective_to=None,
                                  historical_snapshot_date=ASOF, validity_status='retrieval_date_rule_historical_continuity_unverified',
                                  notes='迪拜旅游签基础费；VAT、境内变更、保险和旅游机构费分开。没有该产品收费笔数，不估金额。'))
        sid = self.source('sa_pep2025', 'data/raw/spatial_extension/sa_pep2025.html',
                          'https://pep.gov.sa/en/news/1011', 'Saudi Pilgrim Experience Program',
                          'PEP2025 Annual Report announcement:19.5m international pilgrims',
                          '3August2026 announcement reports15.03m visas issued,83%Umrah. Not15.03m tourist visas;19.5m pilgrims/18.03mUmrah performers are arrivals, not issuance counts.')
        assert '15.03 million visas' in text(self.sources[-1]['local_path'])
        self.observation('sa_2025_pep_visa_issued', 'SAU', 2025, 'pep_reported_visas_issued',
                         15030000, 'visas', sid, 'paragraph As part of the continued development of digital services',
                         raw_metric='15.03million visas including Umrah,visit and other categories;83%Umrah',
                         calculation_type='rounded_reported_observation', program_scope='PEP reported categories; not verified all Saudi visa products',
                         umrah_share=.83, eligible_money_ledger=False,
                         notes='83%为Umrah，类别政府费和减免未匹配，未把总数乘300SAR旅游基础费。')
        sid = self.source('sa_pep2024', 'data/raw/spatial_extension/sa_report2024.pdf',
                          'https://pep.gov.sa/sites/default/files/2025-07/التقرير السنوي لمنجزات البرنامج لعام 2024.pdf',
                          'Saudi Pilgrim Experience Program', 'Pilgrim Experience Program Annual Report2024',
                          'PDF pp54–56 describe KSA Visa platform and p56 lists3,000,000 issued2024,97,636 issued2023. Platform scope retained; not asserted as nationwide all-product visa issuance.')
        sa_text = PdfReader(ROOT / self.sources[-1]['local_path']).pages[55].extract_text()
        assert '3,000,000' in sa_text and '97,636' in sa_text
        self.observation('sa_2024_ksa_platform_issued', 'SAU', 2024,
                         'ksa_visa_platform_issued_context', 3000000, 'visas', sid,
                         'PDF pp54–56, KSA VISA platform; p56 number of entry visas in2024',
                         raw_metric='KSA VISA platform entry visas issued2024',
                         calculation_type='rounded_reported_observation', program_scope='KSA Visa platform only',
                         eligible_money_ledger=False,
                         notes='平台签发300万，未核实其与全国所有产品及2025PEP签发量的覆盖一致性；不直接计算跨年增长或金额。')

    def finish(self):
        OUT.mkdir(parents=True, exist_ok=True)
        coverage = []
        for code, name in NAMES.items():
            for year in (2024, 2025):
                for group in GROUPS:
                    ff = [r for r in self.flows if r['receiver'] == code and r['year'] == year and r['visa_group'] == group]
                    unclassified = group == 'other'
                    context = unclassified and any(o['destination'] == code and o['year'] == year for o in self.obs)
                    coverage.append(dict(code=code, destination=code, name=name,
                                         region='亚洲' if code in ('KOR', 'VNM') else '中东', year=year, visa_group=group,
                                         status='amount_modeled' if ff else 'quantity_context_only' if context else 'not_found',
                                         fee_known=code == 'VNM' and unclassified,
                                         fee_current_snapshot_known=(code == 'VNM' and unclassified) or (code == 'ARE' and group == 'visitor'),
                                         quantity_known=unclassified and (code == 'KOR' or code == 'VNM' and year == 2025),
                                         quantity_context_known=context, category_detail_status='unclassified_aggregate' if unclassified else 'no_classified_observation',
                                         arrival_context_known=False, amount_known=False, amount_modeled=bool(ff),
                                         nationality_known=False,
                                         notes=('本类别未取得单独数量或金额；' if not unclassified else '') + {'KOR': '驻外签发已取得；金额为预算锚定模型，国籍与用途未拆。法务部认定书另留且不代入。',
                                                'VNM': '电子签签发费用值模型；2024合并法核实单次25／多次不超过90天50美元历史费率。2024半年桥接，单多次组合未知；纸签与拒签付款缺。',
                                                'ARE': '取得迪拜原始交易量，非全国新发收费量；现行旅游基础费独列，不猜全年金额。',
                                                'SAU': '2024仅KSA Visa平台量，2025PEP签发含83%Umrah，两者范围不同；无匹配收费交叉，不以旅游费全量相乘。'}[code],
                                         source_ids=[s['source_id'] for s in self.sources if s['source_id'].startswith(tuple(prefix + {'KOR': 'kr_', 'VNM': 'vn_', 'ARE': 'ae_', 'SAU': 'sa_'}[code] for prefix in ('spx_', 'refine_')))],
                                         searched_as_of=ASOF))
        self.log = [dict(country=code, searched_at=ASOF, years=[2024, 2025], result=next(r['notes'] for r in coverage if r['code'] == code),
                         attempted_routes={'KOR': ['MOJ yearbook distinction confirmed', 'NABO2025/26originalPDF', 'MOFA whitepaper downloads interrupted after20MB', 'NABO2024MOFA settlement has no isolated visa line'],
                                           'VNM': ['VNA original2024/25reports', 'GovernmentNews2025fee snapshot', 'MPS2023fee circular', '12/VBHN-BTC official2024consolidation verifies historical25/50USD and separate effective dates', 'current portal returns JS application shell'],
                                           'ARE': ['GDRFA2024/25originalXLSX', 'GDRFAtourist service fee card', 'whole-ICPbudget mixes IDs/residence/other revenue; excluded'],
                                           'SAU': ['PEP2025officialannual announcement', 'PEP2024originalannualPDF', 'MOFAAPI/library TLS failure', 'old freeUmrah embassy pages conflict with current channel prices; excluded from cash estimate']}[code]) for code in NAMES]
        sids = {s['source_id'] for s in self.sources}
        oids = {o['observation_id'] for o in self.obs}
        assert len(sids) == len(self.sources) and len(oids) == len(self.obs)
        for f in self.flows:
            assert set(f['source_ids']) <= sids
            assert set(f['observation_ids']) <= oids
            assert f['payer'] == 'UNK' and f['category_detail_status'] == 'unclassified'
        scopes = {(f['receiver'], f['year']) for f in self.flows}
        checked_packages, overlapping = [], []
        for path in sorted(EST.parent.glob('*_flows.json')):
            if path == EST:
                continue
            checked_packages.append(str(path.relative_to(ROOT)))
            for other in json.loads(path.read_text()).get('flows', []):
                if (other.get('receiver'), other.get('year')) in scopes:
                    overlapping.append({'package': str(path.relative_to(ROOT)), 'flow_id': other.get('id')})
        assert not overlapping, overlapping
        fx_rows = json.loads((ROOT / 'data/research/schengen_fx/fx.json').read_text())
        reused_fx = [r for r in fx_rows if r['year'] in (2024, 2025) and r['currency'] in ('USD', 'KRW')]
        assert {(r['year'], r['currency']) for r in reused_fx} == {(y, c) for y in (2024, 2025) for c in ('USD', 'KRW')}
        package = dict(package='spatial_extension', as_of=ASOF, flows=self.flows, models=self.models,
                       destination_ranges=self.ranges, subtotals=[],
                       scope='2024/25KORbudget-anchored and VNMissued-eVisa tariff-value scenarios; no claimed actual receipts; unknown nationality retained',
                       coverage_rows=len(coverage))
        for fn, obj in [('sources.json', self.sources), ('fee_rules.json', self.fees), ('observations.json', self.obs),
                        ('coverage.json', coverage), ('search_log.json', self.log), ('fx.json', []),
                        ('validation.json', dict(as_of=ASOF, sources=len(sids), observations=len(oids), flows=len(self.flows),
                                                 receivers=sorted({f['receiver'] for f in self.flows}),
                                                 provenance='all flow source and observation IDs resolve; Korean PDF values, UAE XLSX cells and Saudi PDF values asserted; scanned Vietnamese circular p3 visually checked; official2024 consolidated Vietnamese tariff source SHA verified and offline refinement checks cover tariff, effective dates and refund rule',
                                                 no_duplicated_existing_receiver_year=not overlapping,
                                                 overlap_checked_packages=checked_packages,
                                                 reused_fx_keys=[{'year': r['year'], 'currency': r['currency']} for r in reused_fx],
                                                 all_sources_are_cash_receipts=False,
                                                 fx='KRW/USD2024/25 reuse existing Fed annual-average package; no new rates required'))]:
            (OUT / fn).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
        EST.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(dict(sources=len(sids), fees=len(self.fees), observations=len(oids), flows=len(self.flows),
                              receivers=sorted({f['receiver'] for f in self.flows}), coverage=len(coverage)), ensure_ascii=False))


def main():
    r = Research()
    r.korea()
    r.vietnam()
    r.uae_saudi()
    r.finish()


if __name__ == '__main__':
    main()
