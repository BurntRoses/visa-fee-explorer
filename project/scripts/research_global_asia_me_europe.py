#!/usr/bin/env python3
"""Build the frozen regional extension, without network access.

Actual receipts, observed quantities, current tariffs and working assumptions are
kept separate. Native-currency flows never convert tourist arrivals directly into
observed cash. Only files owned by this research package are written.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

import pycountry
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from pypdf import PdfReader

logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/global_asia_me_europe'
OUT = ROOT / 'data/research/global_asia_me_europe'
EST = ROOT / 'data/estimates/global_asia_me_europe_flows.json'
ASOF = '2026-11-15'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
NAMES = {'KOR': '韩国', 'VNM': '越南', 'IDN': '印度尼西亚', 'PHL': '菲律宾',
         'KHM': '柬埔寨', 'NPL': '尼泊尔', 'LKA': '斯里兰卡', 'PAK': '巴基斯坦',
         'UZB': '乌兹别克斯坦', 'SAU': '沙特阿拉伯', 'ARE': '阿联酋', 'QAT': '卡塔尔',
         'OMN': '阿曼', 'JOR': '约旦', 'IRN': '伊朗', 'IRL': '爱尔兰', 'CYP': '塞浦路斯',
         'SRB': '塞尔维亚', 'GEO': '格鲁吉亚', 'ARM': '亚美尼亚', 'FJI': '斐济', 'PNG': '巴布亚新几内亚'}
REGIONS = {c: ('欧洲' if c in ('IRL', 'CYP', 'SRB', 'GEO', 'ARM') else '大洋洲' if c in ('FJI', 'PNG') else '中东' if c in ('SAU', 'ARE', 'QAT', 'OMN', 'JOR', 'IRN') else '亚洲') for c in NAMES}
ALIASES = {'*Other': 'UNK', 'Others': 'UNK', 'U.S.A.': 'USA', 'U.K.': 'GBR',
           'Kosovo': 'XKX', 'Ceuta': 'UNK', 'Melilla': 'UNK', 'Turkiye': 'TUR',
           "Korea (the Democratic People's Republic of) North Korea": 'PRK',
           'Congo (the Democratic Republic of the)': 'COD', 'Congo (the)': 'COG',
           'Tanzania, the United Republic of': 'TZA', 'South Korea': 'KOR'}


def country(name):
    if name in ALIASES:
        return ALIASES[name]
    name = re.sub(r' \(the\)', '', name)
    try:
        return pycountry.countries.lookup(name).alpha_3
    except LookupError:
        return 'UNK'


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


class Research:
    def __init__(self):
        OUT.mkdir(parents=True, exist_ok=True)
        self.sources, self.fees, self.obs, self.flows, self.models = [], [], [], [], []
        self.ranges, self.fx, self.log = [], [], []

    def source(self, slug, fn, url, publisher, title, notes='', quality='official_original'):
        p = RAW / fn
        if not p.exists():
            raise FileNotFoundError(p)
        sid = 'game_' + slug
        self.sources.append({'source_id': sid, 'url': url, 'publisher': publisher,
                             'title': title, 'retrieved_at': ASOF, 'source_quality': quality,
                             'local_path': str(p.relative_to(ROOT)), 'path': str(p.relative_to(ROOT)),
                             'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                             'bytes': p.stat().st_size, 'archive_kind': 'original_document', 'notes': notes})
        return sid

    def fee(self, slug, receiver, typ, amount, currency, sid, start=None, end=None,
            group='visitor', notes='', payer='applicant', nationality=None, locator='', snapshot=None):
        self.fees.append({'id': 'game_' + slug, 'fee_rule_id': 'game_' + slug,
                          'destination': receiver, 'visa_type': typ, 'visa_group': group,
                          'amount': amount, 'currency': currency, 'effective_from': start,
                          'effective_to': end, 'component': 'government_visa_fee',
                          'source_id': sid, 'source_ids': [sid], 'source_locator': locator,
                          'payer': payer, 'mandatory': True, 'nationality_scope': nationality,
                          'historical_snapshot_date': snapshot,
                          'validity_status': 'dated_historical_rule' if start or snapshot and snapshot[:4] in ('2024', '2025') else 'retrieval_date_rule_historical_continuity_unverified',
                          'notes': notes})

    def observation(self, slug, receiver, year, metric, value, currency, sid,
                    nationality='UNK', group='other', locator='', lower=None, upper=None,
                    period_start=None, period_end=None, notes='', **extra):
        oid = 'game_' + slug
        self.obs.append({'observation_id': oid, 'destination': receiver, 'year': year,
                         'metric': metric, 'value': value, 'unit': currency, 'currency': currency if currency != 'count' else None,
                         'nationality': nationality, 'visa_type': group, 'visa_group': group,
                         'source_id': sid, 'source_ids': [sid], 'source_locator': locator,
                         'lower': lower, 'upper': upper, 'period_start': period_start or f'{year}-01-01',
                         'period_end': period_end or f'{year}-12-31', 'notes': notes, **extra})
        return oid

    def flow(self, slug, payer, receiver, year, group, amount, lower, upper, currency,
             sources, observations, quantity=None, basis=None, notes='', parameters=None,
             typ=None, status='modeled_estimate'):
        assert payer not in ('WORLD', receiver)
        assert 0 <= lower <= amount <= upper, (slug, amount, lower, upper)
        self.flows.append({'id': 'game_' + slug, 'payer': payer, 'receiver': receiver,
                           'year': year, 'visa_group': group, 'visa_type': typ or group,
                           'visa_label': {'visitor': '短期访问', 'student': '学生', 'work': '工作', 'family': '家族', 'other': '其他／未分配类别'}[group],
                           'category_detail_status': 'unclassified' if receiver in ('LKA', 'IRL') else 'classified',
                           'amount': amount, 'lower': lower, 'upper': upper, 'currency': currency,
                           'quantity': quantity, 'quantity_basis': basis,
                           'source_ids': list(dict.fromkeys(sources)), 'observation_ids': observations,
                           'method_id': 'game_' + slug.split('_20')[0], 'model_status': status,
                           'calculation_type': status, 'period_start': f'{year}-01-01',
                           'period_end': f'{year}-12-31', 'period_label': str(year),
                           'period_type': 'calendar_year_model',
                           'origin_basis': 'unallocated' if payer == 'UNK' else 'modeled_nationality',
                           'notes': notes, 'parameters': parameters or {}})

    def sri_lanka(self):
        s24 = self.source('lka_report2024', 'lka_2024.pdf', 'https://www.immigration.gov.lk/content/files/reports/2024_performance_report_e.pdf', 'Sri Lanka Department of Immigration and Emigration', 'Annual Performance Report 2024', 'PDF p79 / printed p73 has separately reported visa, eVisa and ETA receipts.')
        s25 = self.source('lka_report2025', 'lka_2025.pdf', 'https://www.immigration.gov.lk/content/files/reports/2025_performance/D_of%20Immigration_E_PR-2025.pdf', 'Sri Lanka Department of Immigration and Emigration', 'Performance Report 2025', 'PDF p45, Revenue Analysis 2019–2025; units LKR million. The 2024 trend combines eVisa and ETA; use the original detailed 2024 table instead.')
        t24 = PdfReader(RAW / 'lka_2024.pdf').pages[78].extract_text()
        t25 = PdfReader(RAW / 'lka_2025.pdf').pages[44].extract_text()
        assert all(x in t24 for x in ('8,556,781,520', '4,232,775,441', '9,536,162,398'))
        assert '2025 11,823 3,822 264 8,186 17,606 3,179 44,880' in t25
        for year, sid, typ, amount, rounding, page in [
            (2024, s24, 'visa_issuances_extensions', 8556781520, 0, 'PDF p79 / printed p73'),
            (2024, s24, 'evisa_receipts', 4232775441, 0, 'PDF p79 / printed p73'),
            (2025, s25, 'visa_issuances_extensions', 8186000000, 500000, 'PDF p45')]:
            oid = self.observation(f'lka_{year}_{typ}', 'LKA', year, 'government_visa_receipts', amount, 'LKR', sid, locator=page,
                                   notes='Actual reported visa receipts; nationality and purpose not published in this table. Visa issuances/extensions include extensions. ETA, passports, ports and citizenship excluded.')
            self.flow(f'lka_receipts_{year}_{typ}', 'UNK', 'LKA', year, 'other', amount, amount - rounding, amount + rounding, 'LKR', [sid], [oid],
                      notes='官方签证实收，付款国籍和用途尚未拆分；visa issuances/extensions包含延期。2024电子签另列且与ETA分开；2025按百万卢比表的舍入精度保留±50万。', typ=typ,
                      parameters={'official_receipts': True, 'nationality_allocation': 'none', 'rounding_LKR': rounding}, status='official_receipts_unallocated')
        # Keep excluded receipts inspectable without putting them into the visa ledger.
        for y, sid, amt in [(2024, s24, 9536162398), (2025, s25, 17606000000)]:
            self.observation(f'lka_{y}_eta_excluded', 'LKA', y, 'excluded_eta_receipts', amt, 'LKR', sid,
                             locator='PDF p79' if y == 2024 else 'PDF p45', ledger_scope='excluded_authorization_fee', notes='ETA is outside the main visa-fee ledger.')
        sf = self.source('lka_fx2025', 'lka_fx_2025.pdf', 'https://www.cbsl.gov.lk/sites/default/files/cbslweb_documents/publications/aer/2025/en/Full_Text.pdf', 'Central Bank of Sri Lanka', 'Annual Economic Review 2025, Table 1.18 Exchange Rate Movements')
        for year, rate in ((2024, 302.12), (2025, 300.95)):
            self.fx.append({'year': year, 'currency': 'LKR', 'usd_per_unit': 1 / rate, 'local_per_usd': rate, 'source_id': sf,
                            'source_locator': 'PDF p80 / printed p54; Table 1.18 annual average US dollar row', 'method': 'annual_average'})
        for year in (2024, 2025):
            fs = [f for f in self.flows if f['receiver'] == 'LKA' and f['year'] == year]
            self.ranges.append({'receiver': 'LKA', 'year': year, 'currency': 'LKR', 'amount': sum(f['amount'] for f in fs),
                                'lower': sum(f['lower'] for f in fs), 'upper': sum(f['upper'] for f in fs), 'range_method': 'official_receipts_plus_reported_rounding'})
        self.models.append({'model_id': 'game_lka_receipts', 'destination': 'LKA', 'years': [2024, 2025],
                            'status': 'actual_visa_receipts_unallocated', 'formula': '2024 visa issuances/extensions + separately reported eVisa; 2025 visa issuances/extensions only; ETA excluded',
                            'limitations': ['付款国籍、学生／工作／家庭用途未分配。', '包含签证延期；2025表格为百万卢比舍入。', '2025未独立列出eVisa，因此不能把未列值解释为0。']})

    def ireland(self):
        sid = self.source('irl_nationalities', 'irl_nationality.csv', 'https://assets.gov.ie/static/documents/bd11bc22/visa_applications_and_decisions_-_year_and_nationality.csv', 'Ireland Department of Justice / Immigration Service Delivery', 'Visa applications and decisions — year and nationality', 'Last updated 30 September 2026; 2024/25 full-year columns; Received/Granted/Refused × short/long; cells 1–5 are suppressed as *. Native CSV is CP1252.')
        sc = self.source('irl_accounts2024', 'irl_2024_accounts.pdf', 'https://www.audit.gov.ie/media/tdxfpzgs/24-vote-24-justice.pdf', 'Ireland Comptroller and Auditor General / Department of Justice', 'Appropriation Account 2024 Vote 24 Justice', 'PDF p33 note4.1 visa fees realised EUR10.595m, separate from immigration registration EUR78.488m. Cash control is Vote24 receipts, not a proven census of fees retained by every overseas mission.')
        sf = self.source('irl_tariff', 'irl_fees.html', 'https://www.irishimmigration.ie/preclearance-and-entry-visas-fees/', 'Ireland Immigration Service Delivery', 'Preclearance and entry visas fees', 'Current official tariff and exemptions. Historical continuity is a working allocation assumption, not a dated 2024 exemption census.')
        for typ, amt in [('single_entry', 60), ('multiple_entry', 100), ('transit', 25)]:
            self.fee('irl_' + typ, 'IRL', typ, amt, 'EUR', sf, notes='申请行政费，拒签／撤回不退；附加服务费另列。当前页面，历史持续性未单独核实。')
        rows = list(csv.DictReader((RAW / 'irl_nationality.csv').open(encoding='cp1252')))
        assert len(rows) == 1038
        # Parse all observations, keeping suppression intervals rather than treating * as 0.
        received = defaultdict(list)
        for ix, row in enumerate(rows):
            for year in (2024, 2025):
                v = row[str(year)].strip()
                lo, hi = (1, 5) if v == '*' else (int(v or 0), int(v or 0))
                mid = (lo + hi) / 2
                code = country(row['Nationality'])
                typ = 'short_term' if row['Type'].startswith('short') else 'long_term'
                oid = self.observation(f'irl_{year}_{ix}', 'IRL', year, 'applications_' + row['Status'].lower(), None if v == '*' else lo,
                                       'count', sid, nationality=code, locator=f'CSV row {ix+2}, {year}', lower=lo, upper=hi,
                                       notes='* means a suppressed count from 1 to 5, not zero.', original_nationality=row['Nationality'],
                                       duration_group=typ, status=row['Status'], basis='nationality')
                if row['Status'] == 'Received':
                    received[year].append({'payer': code, 'typ': typ, 'q': mid, 'lo': lo, 'hi': hi, 'oid': oid, 'original': row['Nationality']})
        control = 10595000
        oid_cash = self.observation('irl_2024_cash', 'IRL', 2024, 'government_visa_receipts', control, 'EUR', sc, locator='PDF p33 note4.1 item4 Visa fees / p34 explanatory note',
                                    notes='Vote24 Justice cash receipts only. No nationality or purpose breakdown in the account.')
        exemptions = set('BIH CIV ECU IDN JAM XKX KGZ MNE MAR MKD PER SRB LKA TUN UGA ZMB'.split())
        totals = {y: sum(r['q'] for r in received[y] if r['payer'] not in exemptions) for y in (2024, 2025)}
        for year in (2024, 2025):
            # Aggregate both durations into other. Short visas can include work/study;
            # long visas do not identify student/work/family in this CSV.
            rr = defaultdict(list)
            for row in received[year]:
                rr[row['payer']].append(row)
            total = control * totals[year] / totals[2024]
            tlo, thi = (control - 500, control + 500) if year == 2024 else (total * .75, total * 1.25)
            for payer, pp in sorted(rr.items()):
                count, lowq, highq = (sum(r[k] for r in pp) for k in ('q', 'lo', 'hi'))
                exempt = payer in exemptions
                amount = 0 if exempt else total * count / totals[year]
                # Relative per-application allocation weights 0.5–1.5, calibrated
                # jointly to the account. Marginal boundaries are not independent.
                low = 0 if exempt else tlo * (.5 * lowq) / (.5 * lowq + 1.5 * (totals[year] - lowq))
                high = 0 if exempt else thi * (1.5 * highq) / (1.5 * highq + .5 * max(0, totals[year] - highq))
                self.flow(f'irl_receipt_allocation_{year}_{payer}_other', payer, 'IRL', year, 'other', amount, low, high, 'EUR', [sid, sc, sf],
                          [r['oid'] for r in pp] + [oid_cash], quantity=count, basis='applications_received_with_suppression_midpoints',
                          notes='2024以Justice账户签证费实收校准，按非国籍豁免申请量作模型归属；不是官方国籍收入。2025保持2024有效均费并给总额±25%敏感性。短期／长期未拆分用途，均保留其他类别；当前国籍豁免表回推属显式假设。边际国籍上下界不可相加当联合总区间。',
                          parameters={'observed_receipt_control_EUR_2024': control, 'control_scope': 'Vote24 Justice cash receipt subset',
                                      'application_count_range': [lowq, highq], 'nationality_original': [r['original'] for r in pp],
                                      'short_term_count': sum(r['q'] for r in pp if r['typ'] == 'short_term'),
                                      'long_term_count': sum(r['q'] for r in pp if r['typ'] == 'long_term'),
                                      'nationality_exemption_historical_continuity_assumed': exempt,
                                      'relative_allocation_weight': {'center': 1, 'lower': .5, 'upper': 1.5},
                                      '2025_receipt_rate_stability_multiplier': {'center': 1, 'lower': .75, 'upper': 1.25},
                                      'bridge': {'observed_2024_cash_EUR': control, 'eligible_received_2024': totals[2024],
                                                 'eligible_received_2025': totals[2025],
                                                 'effective_EUR_per_eligible_received_2024': control / totals[2024],
                                                 '2025_formula': '2024_cash / eligible_received_2024 * eligible_received_2025',
                                                 'assumptions': ['same cash-account collection scope', 'same nominal fee and single/multiple mix', 'same exemption incidence apart from observed nationality counts', 'same payment/cash timing relationship'],
                                                 'not_observed_2025_receipts': True}},
                          status='official_control_with_modeled_allocation' if year == 2024 else 'modeled_estimate')
            self.ranges.append({'receiver': 'IRL', 'year': year, 'currency': 'EUR', 'amount': total, 'lower': tlo, 'upper': thi,
                                'range_method': 'joint_cash_control_not_sum_of_marginal_nationality_bounds' if year == 2024 else 'joint_effective_receipt_rate_sensitivity_25_percent'})
        self.models.append({'model_id': 'game_irl_receipt_allocation', 'destination': 'IRL', 'years': [2024, 2025],
                            'status': '2024_actual_cash_control_with_modeled_nationality_allocation_2025_rate_model',
                            'formula': '2024 EUR10.595m × eligible received-application share; 2025 applies the 2024 effective receipt per eligible application; 1–5 suppression midpoint3',
                            'limitations': ['Vote24现金可能不含海外使馆留存收费；不宣称爱尔兰所有政府机构完整收入。', '无国籍×单次／多次／家庭减免交叉；国籍归属是模型。', '2026当前国籍豁免名单回推2024/25为工作假设。', '短期不等于纯旅游，长期无学生／工作／家族拆分，因此不强拆用途。', '2025无已核实实收；±25%是费率稳定敏感性，不是置信区间。']})

    def indonesia(self):
        s24 = self.source('idn_2024', 'idn_2024.html', 'https://bengkalis.imigrasi.go.id/2025/01/02/imigrasi-kembali-cetak-rekor-di-2024-melaju-cepat-dalam-tubuh-yang-baru/', 'Indonesia Directorate General of Immigration / Bengkalis office', 'Imigrasi kembali cetak rekor di 2024', 'Visa issuance figures cover 1 January–15 December 2024, not the full calendar year. Broad immigration PNBP includes passports/residence and is excluded.')
        s25 = self.source('idn_2025', 'idn_2025.html', 'https://jakartapusat.imigrasi.go.id/berita/imigrasi-di-era-yuldi-yusman-rekor-pnbp-dan-penguatan-penegakan-hukum', 'Indonesia Immigration, Central Jakarta office', 'Imigrasi di era Yuldi Yusman: 2025 performance', '2025 visa issuance total7,551,371; no published VOA or nationality split in this release.')
        sf = self.source('idn_tariff', 'idn_fee_2024.html', 'https://ngurahrai.imigrasi.go.id/layanan-wna/', 'Indonesia Immigration, Ngurah Rai office', 'Layanan WNA — VOA IDR500,000', 'Official current page references 2024 tariff legislation; historical continuity of VOA rate is an explicit working assumption.')
        for filename, token in [('idn_2024.html', '4.635.858'), ('idn_2025.html', '7.551.371')]:
            text = BeautifulSoup((RAW / filename).read_text(), 'html.parser').get_text(' ', strip=True)
            assert token in text, (filename, token)
        self.fee('idn_voa', 'IDN', 'B1_visa_on_arrival', 500000, 'IDR', sf, notes='30日落地签／eVOA；不含续签、第三方服务费。当前页面用于2024/25需费率持续假设。')
        q24, all24, all25 = 4635858, 5162775, 7551371
        o24 = self.observation('idn_2024_voa_partial', 'IDN', 2024, 'visas_issued', q24, 'count', s24, group='visitor', period_end='2024-12-15',
                               notes='Observed VOA only, Jan1–Dec15; annual extrapolation is separate.', quantity_basis='visa_on_arrival_issued')
        oa24 = self.observation('idn_2024_all_partial', 'IDN', 2024, 'visas_issued', all24, 'count', s24, period_end='2024-12-15')
        o25 = self.observation('idn_2025_all_visas', 'IDN', 2025, 'visas_issued', all25, 'count', s25, notes='All visa categories; 2025 VOA share unobserved.')
        for y, q, lo, hi, obs, pars in [
            (2024, q24 * 366 / 350, q24, q24 * (1 + 2 * 16 / 350), [o24], {'observed_days': 350, 'unobserved_days': 16, 'unobserved_daily_rate_multiplier': {'center': 1, 'lower': 0, 'upper': 2}}),
            (2025, all25 * q24 / all24, all25 * .7, all25, [o24, oa24, o25], {'VOA_share': {'center': q24 / all24, 'lower': .7, 'upper': 1}, 'share_basis': '2024 Jan1–Dec15 observed composition, carried forward to2025'})]:
            self.flow(f'idn_voa_model_{y}_UNK_visitor', 'UNK', 'IDN', y, 'visitor', q * 500000, lo * 500000, hi * 500000, 'IDR', [s24, sf] + ([s25] if y == 2025 else []), obs,
                      quantity=q, basis='modeled_full_year_VOA_issued',
                      notes='名义政府落地签费模型，非官方实收。2024只观察至12月15日，余16天按日均外推；2025落地签份额以2024组成回推并给70%–100%敏感性。两年均未按游客国籍猜分，也未将全部移民PNBP当签证收入。', parameters={**pars, 'fee_IDR': 500000, 'historical_tariff_continuity_assumption': True})
            self.ranges.append({'receiver': 'IDN', 'year': y, 'currency': 'IDR', 'amount': q * 500000, 'lower': lo * 500000, 'upper': hi * 500000, 'range_method': 'partial_period_bridge' if y == 2024 else 'unobserved_VOA_share_sensitivity'})
        fxid = self.source('idn_fx_worldbank', 'idn_fx_worldbank.json', 'https://api.worldbank.org/v2/country/IDN/indicator/PA.NUS.FCRF?date=2024:2025&format=json', 'World Bank / IMF International Financial Statistics', 'Official exchange rate, LCU per USD period average, Indonesia')
        for r in json.loads((RAW / 'idn_fx_worldbank.json').read_text())[1]:
            self.fx.append({'year': int(r['date']), 'currency': 'IDR', 'usd_per_unit': 1 / r['value'], 'local_per_usd': r['value'], 'source_id': fxid, 'method': 'annual_average'})
        self.models.append({'model_id': 'game_idn_voa_model', 'destination': 'IDN', 'years': [2024, 2025], 'status': 'working_estimate_not_official_receipts',
                            'formula': '2024 observed VOA ×366/350×IDR500000; 2025 total visas ×2024 VOA share×IDR500000',
                            'limitations': ['只含落地签基础政府费，不含其他签证、延期和服务费。', '2024末16天未观察；2025落地签份额未观察。', '国籍未知保留UNK，不用旅游到访份额代替签证量。', '敏感性范围为建模参数，不是统计置信区间。']})

    def nepal(self):
        sq = self.source('npl_stats2025', 'npl_2025.xlsx', 'https://giwmscdnone.gov.np/media/files/Nepal%20Tourism%20Statistics%202025_mkmdltz.xlsx', 'Nepal Ministry of Culture, Tourism and Civil Aviation', 'Nepal Tourism Statistics 2025 — original Excel workbook', '49 sheets; nationality worksheet reports 2024 and2025 counts. Tourist arrivals are not visa application or payment events.')
        sf = self.source('npl_fees', 'npl_fees.html', 'https://immigration.gov.np/visa-fees-and-documents', 'Nepal Department of Immigration', 'Visa Fees and Documents', 'Current official tariff; policy-duration and re-entry mix not observed historically. TLS certificate validation failed on direct retrieval; original page retrieved without rewriting contents.')
        sg = self.source('npl_china_waiver', 'npl_china_policy.html', 'https://mofa.gov.np/content/1450/nepal-china/', 'Nepal Ministry of Foreign Affairs', 'Nepal–China bilateral relations', 'Chinese tourist visa fees waived effective1January2016.')
        se = self.source('npl_embassy_fees', 'npl_cn_fees.html', 'https://cn.nepalembassy.gov.np/pages/visa/', 'Embassy of Nepal, Beijing', 'Visa information and gratis rules', 'Chinese tourist gratis; Indian nationals need no visa; children under10 gratis except US passport; SAARC first30-day visa once a year gratis.')
        si = self.source('npl_india_waiver', 'npl_india_waiver_indexed.json', 'https://ccu.nepalconsulate.gov.np/pages/visa-5/',
                         'Consulate General of Nepal, Kolkata', 'Visa — Indian nationals require no visa',
                         'Indexed official page extract, line36: Visa not required for Indian Nationals; line75 describes first30-day SAARC gratis. Current confirmation, with historical continuity explicitly assumed.', quality='official_indexed_page_extract')
        self.sources[-1]['archive_kind'] = 'indexed_official_page_extract'
        for days, price in ((15, 30), (30, 50), (90, 125)):
            self.fee('npl_tourist_' + str(days), 'NPL', f'tourist_{days}_days', price, 'USD', sf,
                     notes='当前官方单次旅游费表，2024/25持续性为模型假设；国籍、儿童减免和重入境须另处理。')
        self.fee('npl_chinese_gratis', 'NPL', 'tourist_Chinese', 0, 'USD', sg, start='2016-01-01', nationality='CHN', notes='2016年1月1日起中国游客签证免签证费；不据此把学生／工作等签证也设为0。')
        for typ, price, group, note in [('study_degree_month', 30, 'student', '学位学习，每月；部分国籍优惠另列。'), ('study_nondegree_month', 75, 'student', '非学位学习，每月。'),
                                         ('work_government_month', 30, 'work', '政府关联工作每月。'), ('work_donor_month', 50, 'work', '捐助项目工作每月。'), ('work_other_month', 75, 'work', '其他机构工作每月。'),
                                         ('relative_direct_month', 10, 'family', '尼泊尔公民直系亲属每月。'), ('marriage_month', 15, 'family', '与尼泊尔公民结婚，每月；页面另列特例。')]:
            self.fee('npl_' + typ, 'NPL', typ, price, 'USD', sf, group=group, notes=note + '当前页面，非已核实2024/25历史费表；重入境收费另列。')
        w = load_workbook(RAW / 'npl_2025.xlsx', data_only=True, read_only=True)
        rows = [r for r in w['Tourist Arrival_Nationalities'].values if r[0] and r[0] not in ('%', 'Nationality') and isinstance(r[11], (int, float))]
        assert next(r for r in rows if r[0] == 'China')[11:13] == (101874, 95732)
        for year, col in ((2024, 11), (2025, 12)):
            reported_total = next(r[col] for r in rows if r[0] == 'Total')
            detail_sum = sum(r[col] for r in rows if r[0] != 'Total')
            if detail_sum != reported_total:
                self.log.append({'country': 'NPL', 'year': year, 'issue': 'official_workbook_detail_total_difference',
                                 'source_id': sq, 'worksheet': 'Tourist Arrival_Nationalities',
                                 'detail_sum': detail_sum, 'reported_total': reported_total,
                                 'difference': detail_sum - reported_total,
                                 'treatment': 'Keep published nationality cells unchanged; no rescaling or invented corrected total. Model is a partial selected-nationality subset.'})
            for ix, r in enumerate(rows):
                if r[0] == 'Total':
                    continue
                payer, q = country(r[0]), r[col]
                oid = self.observation(f'npl_{year}_{payer}_arrivals', 'NPL', year, 'tourist_arrivals', q, 'count', sq, nationality=payer, group='visitor',
                                       locator=f'Worksheet Tourist Arrival_Nationalities, {r[0]}, {year}', notes='Arrivals, not observed paid visas.', original_nationality=r[0], basis='nationality')
                # US five-year reciprocity visas and SAARC first-30-day waivers
                # have unobserved mixes; retain observations but no cash guess.
                if payer in ('USA', 'BGD', 'LKA', 'UNK'):
                    continue
                gratis = payer in ('CHN', 'IND')
                # A first single-entry visa model only, excluding extensions.
                # 50/40/10% duration mix gives USD47.5; 80% paid new-visa
                # events per arrival gives USD38. Zero to125 captures unobserved
                # existing visas, children and the permitted standard durations.
                amount = 0 if gratis else q * 47.5 * .8
                hi = 0 if gratis else q * 125
                self.flow(f'npl_tourist_single_entry_{year}_{payer}_visitor', payer, 'NPL', year, 'visitor', amount, 0, hi, 'USD', [sq, sf, se] + ([sg] if payer == 'CHN' else [si] if payer == 'IND' else []), [oid],
                          quantity=q, basis='tourist_arrivals_not_observed_paid_visa_events',
                          notes='旅游首次单次签证费模型；到访量不等于缴费签证数。工作中心假设15／30／90日占50%／40%／10%，每次到访新付费事件0.8；范围0至每到访125美元，保留儿童、已有签证和重入境未知。中国旅游免签证费，印度无需签证。美国长期互惠、SAARC和其他国籍混合未猜金额；学生工作家庭无量不造金额。',
                          parameters={'tariff_continuity_assumption': True, 'duration_mix': {'15_days': .5, '30_days': .4, '90_days': .1},
                                      'new_paid_events_per_arrival': {'center': 0 if gratis else .8, 'lower': 0, 'upper': 0 if gratis else 1},
                                      'standard_single_entry_fee_USD': {'center': 47.5, 'lower': 30, 'upper': 125}, 'gratis_policy': gratis,
                                      'scope': 'modeled new single-entry tourist visas only; extensions and US reciprocity product excluded'}, status='modeled_estimate')
            ff = [f for f in self.flows if f['receiver'] == 'NPL' and f['year'] == year]
            self.ranges.append({'receiver': 'NPL', 'year': year, 'currency': 'USD', 'amount': sum(f['amount'] for f in ff),
                                'lower': 0, 'upper': sum(f['upper'] for f in ff), 'range_method': 'working_single_entry_subset_not_national_total'})
        self.models.append({'model_id': 'game_npl_tourist_single_entry', 'destination': 'NPL', 'years': [2024, 2025], 'status': 'arrival_anchored_working_fee_model_partial_nationality_subset',
                            'formula': 'nonexempt selected nationalities: arrivals ×0.8×(0.5×30+0.4×50+0.1×125); China/India0; other/mixed-waiver/US excluded',
                            'limitations': ['官方数量为到访，不是签证缴费事件；新付费占比、停留费档组合是工作参数。', '仅选定已明确普通旅游费档国籍，不是全国收入。', '中国免签证费有2016起政策证据；标准收费2024/25持续性假设。', '不将登山、景区、护照、总旅游收入混入签证费。']})

    def qatar(self):
        sq = self.source('qat_report2025', 'qat_2025_report.pdf', 'https://www.qatartourism.com/content/dam/qatar-tourism/press-releases/2026/jan/2025-rapport/ACHIEVEMENTS-REPORT-2025.pdf', 'Qatar Tourism', 'Annual Tourism Performance Report 2025 / Achievements Report', 'PDF p9: Hayya processed nearly one million e-visa applications. No exact count, paid share, nationality or product split.')
        sf = self.source('qat_tariff', 'qat_fees.html', 'https://visitqatar.com/intl-en/plan-your-trip/visas', 'Visit Qatar / Qatar Tourism', 'Qatar visa and entry requirements', 'Tourist Hayya QAR100 is a product fee; do not apply it to every visa-exempt visitor or every Hayya event automatically.')
        self.fee('qat_hayya_tourist', 'QAT', 'Hayya_A1_tourist', 100, 'QAR', sf, notes='Hayya旅游签证产品费；免签者、其他Hayya产品和获批／支付比例须分别处理。当前页面，非2025收费量证明。')
        text = PdfReader(RAW / 'qat_2025_report.pdf').pages[8].extract_text()
        assert 'nearly one million e-visa applications' in text
        oid = self.observation('qat_2025_hayya_rounded', 'QAT', 2025, 'applications_processed_rounded_description', None, 'count', sq, group='visitor', locator='PDF p9',
                               notes='Source says nearly one million, not an exact count. Numeric approximation and paying-product share below are working parameters.', reported_text='nearly one million')
        self.flow('qat_hayya_scenario_2025_UNK_visitor', 'UNK', 'QAT', 2025, 'visitor', 950000 * .5 * 100, 0, 1000000 * 100, 'QAR', [sq, sf], [oid],
                  quantity=950000, basis='working_numeric_approximation_of_nearly_one_million',
                  notes='Hayya旅游收费敏感性模型，非官方收入。近100万仅为官方约数；中心95万和适用100里亚尔收费产品占50%均是工作假设，完整包络0–1亿里亚尔。未把免签访客统一收费，也未按入境国籍推签证国籍。',
                  parameters={'application_count': {'center': 950000, 'lower': 900000, 'upper': 1000000, 'status': 'working_interpretation_of_nearly_not_source_bound'},
                              'paid_QAR100_product_share': {'center': .5, 'lower': 0, 'upper': 1, 'status': 'unobserved_working_parameter'}, 'tariff_continuity_assumption': True})
        self.ranges.append({'receiver': 'QAT', 'year': 2025, 'currency': 'QAR', 'amount': 47500000, 'lower': 0, 'upper': 100000000, 'range_method': 'full_unobserved_paid_product_share_sensitivity'})
        sx = self.source('qat_fx_worldbank', 'qat_fx_worldbank.json', 'https://api.worldbank.org/v2/country/QAT/indicator/PA.NUS.FCRF?date=2024:2025&format=json', 'World Bank / IMF International Financial Statistics', 'Official exchange rate, LCU per USD period average, Qatar')
        for r in json.loads((RAW / 'qat_fx_worldbank.json').read_text())[1]:
            self.fx.append({'year': int(r['date']), 'currency': 'QAR', 'usd_per_unit': 1 / r['value'], 'local_per_usd': r['value'], 'source_id': sx, 'method': 'annual_average'})
        self.models.append({'model_id': 'game_qat_hayya_scenario', 'destination': 'QAT', 'years': [2025], 'status': 'wide_working_product_mix_sensitivity_not_observed_receipts',
                            'formula': 'nearly1m applications → working950k ×working50% applicable paid-product share×QAR100; sensitivity0–QAR100m',
                            'limitations': ['不是近100万全部收费的推断；收费产品、获批和支付比例未知。', '95万和50%中心为工作参数，不是官方值。', '2024数量未找到，未用跨年累计量填补。']})

    def regional_tariffs(self):
        defs = [
            ('srb_tariff2025', 'srb_fees.html', 'https://warsaw.mfa.gov.rs/gradjani/usluge/cenovnik-konzularnih-usluga', 'Serbia Ministry of Foreign Affairs / Embassy in Warsaw', 'Consular fees effective1January2025'),
            ('cyp_tariff2024', 'cyp_fees2024.html', 'https://cyprusinuk.com/visa-information/', 'Cyprus High Commission in the UK', 'Visa information — fee change11June2024'),
            ('geo_tariff', 'geo_fees.html', 'https://www.evisa.gov.ge/GeoVisa/en/Home/Faq/', 'Georgia Ministry of Foreign Affairs', 'eVisa frequently asked questions'),
            ('arm_tariff', 'arm_fees.html', 'https://www.mfa.am/en/fees', 'Armenia Ministry of Foreign Affairs', 'Visa consular fees'),
            ('uzb_tariff', 'uzb_fees.html', 'https://gov.uz/en/mfa/pages/o-zbekiston-respublikasi-vizasi', 'Uzbekistan Ministry of Foreign Affairs', 'Visa of the Republic of Uzbekistan'),
            ('phl_tariff', 'phl_fees.html', 'https://newyorkpcg.org/pcgny/consular-services/schedule-of-fees/', 'Philippines Consulate General New York', 'Schedule of consular fees'),
            ('omn_work_tariff', 'omn_fees.html', 'https://www.rop.gov.om/english/visas.aspx', 'Royal Oman Police', 'Visa types — work visa'),
            ('fji_tariff2025', 'fji_fees2025.pdf', 'https://www.immigration.gov.fj/wp-content/uploads/2025/08/new-fees-for-2025.pdf', 'Fiji Immigration Department', 'New Immigration Services Fees effective1August2025')]
        ss = {slug: self.source(slug, fn, url, pub, title) for slug, fn, url, pub, title in defs}
        for typ, amt, group, note in [('C_adult', 90, 'visitor', 'C类短期签证；华沙使馆公布欧元收费。'), ('C_under12', 45, 'visitor', '12岁以下儿童C签证。'), ('D', 50, 'other', 'D类临时停留；未按学习／工作／家庭拆分。')]:
            self.fee('srb_' + typ, 'SRB', typ, amt, 'EUR', ss['srb_tariff2025'], start='2025-01-01', group=group, notes=note + '另列签证贴纸€2，不将申诉费混入签证费。')
        self.fee('srb_sticker', 'SRB', 'visa_sticker', 2, 'EUR', ss['srb_tariff2025'], start='2025-01-01', group='other', notes='签证贴纸项目；不与基础签证费重复作为完整签证产品。')
        for typ, amt in [('adult', 90), ('child6_12', 45)]:
            self.fee('cyp_' + typ, 'CYP', 'short_stay_' + typ, amt, 'EUR', ss['cyp_tariff2024'], start='2024-06-11', notes='2024年6月11日起；页面此前€80标准未在本包回填逐日全年加权。')
        self.fee('geo_evisa', 'GEO', 'short_stay_evisa', 20, 'USD', ss['geo_tariff'], notes='政府签证费20美元；2%服务费另列排除。当前快照，不回填为已核实2024/25历史价。')
        for days, amt in [(21, 3000), (120, 15000)]:
            self.fee('arm_visitor_' + str(days), 'ARM', f'visitor_{days}_days', amt, 'AMD', ss['arm_tariff'], notes='保留亚美尼亚德拉姆本币；当前网页美元换算不倒推2024/25。')
        for typ, amt in [('single', 20), ('double', 35), ('multiple', 50)]:
            self.fee('uzb_evisa_' + typ, 'UZB', 'evisa_' + typ, amt, 'USD', ss['uzb_tariff'], notes='当前官方电子签收费；具体国籍免签、电子签资格与2024/25历史适用另核，不直接乘全部游客。')
        for typ, amt, group, nat in [('visitor_visa_free_nationality_single', 30, 'visitor', 'nationals of visa-free countries applying for visa'), ('visitor_visa_required_single', 40, 'visitor', 'visa-required countries except special rates'), ('visitor_Chinese_single', 25, 'visitor', 'CHN'), ('visitor_Chinese_multiple3m', 50, 'visitor', 'CHN'), ('visitor_Chinese_multiple6m', 100, 'visitor', 'CHN'), ('student9F', 250, 'student', None), ('employment9G', 400, 'work', None), ('nonquota_immigrant13A_13G', 150, 'other', None)]:
            self.fee('phl_' + typ, 'PHL', typ, amt, 'USD', ss['phl_tariff'], group=group, nationality=nat, notes='纽约领馆收费范围；对华单次$25不可被一般非免签国家$40覆盖。当前页面，2024/25历史持续性未单独核实。')
        self.fee('omn_work', 'OMN', 'work', 20, 'OMR', ss['omn_work_tariff'], group='work', payer='sponsoring_employer', notes='ROP页面work visa收费20里亚尔；由雇主申请并承担责任。未观察工作量；罚款和劳工许可费不计。当前费表历史有效性待核。')
        for typ, amt, group, note in [('single_entry', 93, 'visitor', '单次签证申请。'), ('multiple_entry', 185, 'visitor', '多次签证申请。'), ('student_application', 136, 'student', '学生许可申请费。'), ('student_issue', 185, 'student', '学生许可签发费，分开保留不得与申请费替换。'), ('work_application', 650.05, 'work', '工作许可申请费；雇主具体承担规则未观察。'), ('permit_issue', 185, 'other', '许可签发费，未分配用途；不是每种签证通用费。')]:
            self.fee('fji_' + typ, 'FJI', typ, amt, 'FJD', ss['fji_tariff2025'], start='2025-08-01', group=group, notes=note + '仅适用于2025年8月1日起支付的申请；不覆盖此前2024和2025年1–7月。', locator='PDF p1–2')

    def cambodia_quantity_context(self):
        sid = self.source('khm_report2024', 'khm_2024_statistics.pdf', 'https://asset.cambodia.gov.kh/tourism/2025/02/combinepdfconference.pdf',
                          'Cambodia Ministry of Tourism', 'Annual Report2024 and2025 Directions of the Ministry of Tourism',
                          '137-page bilingual conference report. PDF p81–82 / English printed p3–4 report actual2024 arrival totals and top10 source markets. These are arrival context, not paid visa quantities. China percentage is misprinted2.7%; use the published count848,952 without that percentage.')
        r = PdfReader(RAW / 'khm_2024_statistics.pdf')
        text = r.pages[81].extract_text()
        assert '848,952' in text and '2,146,674' in text
        for payer, qty in [('THA', 2146674), ('VNM', 1340587), ('CHN', 848952), ('LAO', 334448), ('USA', 214529), ('KOR', 192305), ('IDN', 166795), ('FRA', 131738), ('GBR', 115148), ('JPN', 112718)]:
            self.observation(f'khm_2024_{payer}_arrival_context', 'KHM', 2024, 'tourist_arrivals_source_market', qty, 'count', sid,
                             nationality=payer, group='visitor', locator='PDF p82 / English printed p4, top-ten markets',
                             notes='Official source-market arrival count, not a verified nationality × paid visa count. No monetary flow inferred.', basis='source_market_not_verified_payer_nationality')
        self.observation('khm_2024_total_arrival_context', 'KHM', 2024, 'tourist_arrivals_total', 6700125, 'count', sid,
                         group='visitor', locator='PDF p81 / English printed p3', notes='Arrival context only; not visa quantity or revenue.')

    def coverage(self):
        rows = []
        for code, name in NAMES.items():
            ff = [f for f in self.fees if f['destination'] == code]
            ss = list(dict.fromkeys(s for f in ff for s in f['source_ids']))
            of = [f for f in self.flows if f['receiver'] == code]
            for year in (2024, 2025):
                for group in GROUPS:
                    flows = [f for f in of if f['year'] == year and f['visa_group'] == group]
                    fees = [f for f in ff if f['visa_group'] == group]
                    obs = [o for o in self.obs if o['destination'] == code and o['year'] == year and o['visa_group'] == group and o['unit'] == 'count']
                    historical = [f for f in fees if f['effective_from'] and int(f['effective_from'][:4]) <= year]
                    status = 'amount_modeled' if flows else 'fee_only' if historical else 'current_fee_only' if fees else 'not_found'
                    note = ('包含实际总额但国籍未知。' if code == 'LKA' and group == 'other' else
                            '短期／长期申请可按国籍查，但未按用途分配；金额放其他类别。' if code == 'IRL' and group != 'other' else
                            '现有核心india_korea包已有韩国2024/25签发国籍量和费表，本区域扩展不重复建流。' if code == 'KOR' else
                            '现有turkey_russia_saudi包已有SAR300旅游基础政府费及2024服务指南；签证量和国籍金额未核实。' if code == 'SAU' else
                            '首次单次旅游签证的部分国籍模型；到访量不等于支付量，其他用途尚无金额。' if code == 'NPL' else
                            '收费量、免签／付费产品交叉、国籍金额未找到。')
                    rows.append({'code': code, 'destination': code, 'name': name, 'region': REGIONS[code], 'year': year, 'visa_group': group,
                                 'status': status, 'fee_known': bool(historical), 'fee_current_snapshot_known': bool(fees),
                                 'quantity_known': any(o['metric'] in ('visas_issued', 'applications_received') for o in obs),
                                 'arrival_context_known': any('arrival' in o['metric'] for o in obs),
                                 'amount_known': any(f['model_status'].startswith('official') for f in flows),
                                 'amount_modeled': bool(flows), 'nationality_known': any(f['payer'] != 'UNK' for f in flows),
                                 'source_ids': list(dict.fromkeys(ss + [s for f in flows for s in f['source_ids']])),
                                 'notes': note, 'searched_as_of': ASOF})
        write('coverage.json', rows)
        return rows

    def search_log(self):
        issues = {
            'KOR': '核心包已含官方2024/25签发量、2024芝加哥费表；本包不重复。',
            'VNM': '电子签收费与免签并行；未找到2024/25按国籍×付费签证产品数量或独立签证费实收，不以全部入境游客乘费。',
            'IDN': '取得Jan1–Dec15 2024落地签量及2025全部签证量。Bali旅游统计Table16月度VOA收入合计与年度数矛盾，且USD单位数值异常，未使用。',
            'PHL': '取得官方纽约领馆费表，含中国专属价、学生、工作和移民类别；未得到2024/25收费签证量。',
            'KHM': 'combinepdfreport.pdf当前75页原件与搜索缓存所称国别旅游表不一致，未据缓存建流。另取得137页官方会议年报PDF p81–82的2024到访总数及十大市场，只作到访背景，不冒充签证付费量。evisa.gov.kh两HTML为WAF拦截，不作已存正文。',
            'NPL': '取得官方2025原始49表XLSX和2024/25国籍到访量。中国2016起旅游免签证费。仅部分国籍建立首次单次签证敏感性模型；美国互惠、SAARC及其他未猜。',
            'LKA': '取得2024/25官方移民年报，独立签证实收可用；国籍及学生工作家庭拆分缺失，ETA明确排除。',
            'PAK': 'DGIP费用页请求超时；2024年8月126国旅游／商务免收费改革只覆盖特定范围和起点。未把全年所有类别设0。',
            'UZB': '取得官方电子签20/35/50美元和普通签表；当前页面含2026政策变化，不能整表当2024/25历史状态；付费量缺失。',
            'SAU': '核心包有官方旅游签基础300SAR，保险另列；入境旅游和Umrah到访不等于该产品付费签证，未做假精度金额。',
            'ARE': '2024 ICP服务指南URL返回500；GDRFA现行产品页不代表2024/25付费量；未用总入境或居留业务收入替代。',
            'QAT': '官方2025报告Hayya nearly1m申请是约数且产品／支付比例未知，生成0–100mQAR明确工作模型；2024未取累计量凑数。',
            'OMN': '取得ROP work visa20OMR官方页；其他产品历史表和2024/25付费量未核实；罚款劳工费不混入。',
            'JOR': '旅游部费用页请求超时。Jordan Pass免签证费有停留条件；未用游客总数×40JOD。',
            'IRN': '外交部签证类型站403；收费按国籍／使馆不同，未找到可核实2024/25量费交叉。',
            'IRL': '官方国籍×短／长×收到／准签／拒签CSV和2024Justice签证费实收均可用；2025收入为2024有效均费模型，未称已实收。',
            'CYP': '官方英国高专署11June2024费率90EUR和儿童45EUR；2024/25付费量、长期类别缺失。塞浦路斯2024/25非申根，不并入申根控制。',
            'SRB': '官方华沙使馆2025-01-01 C90EUR/儿童45/D50、贴纸2；2024历史价和收费量未核实。',
            'GEO': '官方FAQ政府费20USD和2%服务费可分；2024/25历史价、数量和长期签证缺失。',
            'ARM': '官方现行费表以AMD保存，不将2026美元换算倒填2024/25；历史价和数量未核实。',
            'FJI': '取得2025-08-01新收费官方PDF，含旅游、学生、工作；未把新价适用于2024和2025前7月，数量缺失。',
            'PNG': 'ICA2025官方签证手册URL被重定向后403。不能把免费政府访客MSF等于全申请免费；线上必收费与旧价待原件核实。'}
        for c, issue in issues.items():
            self.log.append({'country': c, 'name': NAMES[c], 'years': [2024, 2025], 'searched_at': ASOF,
                             'routes': ['official immigration/foreign affairs fee rules', 'official annual performance/accounts/statistics', 'nationality and product quantity cross-tab', 'budget/parliament alternative where available'],
                             'result': issue, 'next_gap': 'purpose × paying quantity × nationality or distinct visa receipts',
                             'source_ids': list(dict.fromkeys(s for o in self.obs if o['destination'] == c for s in o['source_ids']))})

    def finish(self):
        self.search_log()
        coverage = self.coverage()
        source_ids = {s['source_id'] for s in self.sources}
        obs_ids = {o['observation_id'] for o in self.obs}
        assert len(source_ids) == len(self.sources)
        assert len({f['id'] for f in self.flows}) == len(self.flows)
        for f in self.flows:
            assert set(f['source_ids']) <= source_ids
            assert set(f['observation_ids']) <= obs_ids
        write('sources.json', self.sources)
        write('fee_rules.json', self.fees)
        write('observations.json', self.obs)
        write('search_log.json', self.log)
        write('fx.json', self.fx)
        package = {'package': 'global_asia_me_europe', 'as_of': ASOF, 'flows': self.flows, 'models': self.models,
                   'destination_ranges': self.ranges, 'subtotals': [],
                   'scope': 'visa government fees only; official cash controls and modeled allocations distinguished; ETA excluded; model ranges are parameter sensitivities',
                   'coverage_rows': len(coverage)}
        EST.parent.mkdir(parents=True, exist_ok=True)
        EST.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'sources': len(self.sources), 'fees': len(self.fees), 'observations': len(self.obs),
                          'flows': len(self.flows), 'receivers': sorted({f['receiver'] for f in self.flows}),
                          'coverage': len(coverage), 'fx': len(self.fx)}, ensure_ascii=False))


def main():
    r = Research()
    r.sri_lanka()
    r.ireland()
    r.indonesia()
    r.nepal()
    r.qatar()
    r.regional_tariffs()
    r.cambodia_quantity_context()
    r.finish()


if __name__ == '__main__':
    main()
