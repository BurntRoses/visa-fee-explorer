#!/usr/bin/env python3
"""Offline Morocco e-visa issuance and statutory-fee-value research package.

Issuance counts times statutory fees are modeled fee values, never actual receipts.
No arrival counts, cross-year nationality shares or cumulative duplicate edges.
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

from bs4 import BeautifulSoup
from pypdf import PdfReader

sys.dont_write_bytecode = True
logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/africa_visa_issuance_v5'
OUT = ROOT / 'data/research/africa_visa_issuance_v5'
EST = ROOT / 'data/estimates/africa_visa_issuance_v5_flows.json'
ASOF = '2026-11-17'
PREFIX = 'aiv5_'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class Research:
    def __init__(self):
        self.sources, self.obs, self.fees, self.fx = [], [], [], []
        self.flows, self.models, self.ranges, self.excluded = [], [], [], []

    def source(self, slug, filename, url, publisher, title, notes,
               quality='official_original', kind='original_document'):
        path = RAW / filename
        assert path.exists() and path.stat().st_size > 100
        sid = PREFIX + slug
        self.sources.append(dict(source_id=sid, url=url, publisher=publisher, title=title,
                                 notes=notes, retrieved_at=ASOF, source_quality=quality,
                                 local_path=str(path.relative_to(ROOT)), path=str(path.relative_to(ROOT)),
                                 bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                 archive_kind=kind))
        return sid

    def observation(self, slug, year, value, metric, sid, locator, **extra):
        oid = PREFIX + slug
        self.obs.append(dict(observation_id=oid, destination='MAR', year=year, value=value,
                             unit=extra.pop('unit', 'evisas_issued'), metric=metric,
                             raw_metric=extra.pop('raw_metric', metric), source_id=sid,
                             source_ids=extra.pop('source_ids', [sid]), source_locator=locator,
                             nationality=extra.pop('nationality', 'UNK'),
                             origin_basis=extra.pop('origin_basis', 'unallocated'),
                             visa_group='visitor', visa_type='electronic_tourism_business_visa',
                             period_start=extra.pop('period_start', f'{year}-01-01'),
                             period_end=extra.pop('period_end', f'{year}-12-31'),
                             period_type=extra.pop('period_type', 'calendar_year'),
                             calculation_type=extra.pop('calculation_type', 'direct_observation'),
                             eligible_money_ledger=False, **extra))
        return oid

    def evidence(self):
        legal = self.source('mar_bo7106', 'mar_bo7106_fr.pdf',
                            'https://www.sgg.gov.ma/BO/FR/2873/2022/BO_7106_Fr.pdf',
                            'Morocco Secrétariat Général du Gouvernement',
                            'Bulletin Officiel7106,7 July2022; joint orders1658-22 and1659-22',
                            'Order1658-22,p849,article26: normal700/express1000 MAD chancellerie. '
                            'Order1659-22,p853,chapterII,items9–10: government service remuneration70/100 MAD. '
                            'Both tables visually verified from rendered original pages; sums770/1100, not two additive ledger edges.')
        pdf = PdfReader(RAW / 'mar_bo7106_fr.pdf')
        duty, service = pdf.pages[68].extract_text(), pdf.pages[72].extract_text()
        assert 'Visa électronique normal' in duty and re.search(r'normal\s+700', duty)
        assert re.search(r'express\s+1000', duty)
        assert re.search(r'normal\s+70', service) and re.search(r'express\s+100', service)
        assert '1659-22' in service
        for filename, text in [('mar_bo7106_p849.txt', duty), ('mar_bo7106_p853.txt', service)]:
            (OUT / filename).write_text(text)
        for typ, fee, extra_fee in [('normal', 700, 70), ('express', 1000, 100)]:
            for component, amount, locator in [('chancellerie', fee, 'PDFp69 / printed849;order1658-22;article26'),
                                                ('government_service_remuneration', extra_fee, 'PDFp73 / printed853;order1659-22;chapterII;items9–10')]:
                self.fees.append(dict(fee_rule_id=PREFIX+f'mar_evisa_{typ}_{component}', destination='MAR',
                                       visa_type=f'evisa_{typ}', visa_group='visitor', fee_component=component,
                                       amount=amount, currency='MAD', valid_from='2022-07-10', valid_to=None,
                                       legal_publication_date='2022-06-27', french_publication_date='2022-07-07',
                                       applicability='Applied from electronic-visa service launch; continuity through2025 is a model assumption, not a new legal commencement date.',
                                       source_id=legal, source_locator=locator, calculation='direct_observation',
                                       source_quality='official_original', unit='per_evisa', government_or_service='government',
                                       mandatory=True, payment_stage='application', refusal_refund='not_identified'))
        official = self.source('mar_portal2024', 'mar_portal2024.html',
                               'https://www.maroc.ma/fr/actualites/visa-electronique-des-resultats-positifs-sur-le-tourisme-marocain',
                               'Morocco government portal / Ministry of Tourism / MAP',
                               'Visa électronique:des résultats positifs sur le tourisme marocain,17 January2025',
                               '385738 is cumulative July2022–December2024, not2024 annual. India36690 is2024 annual. '
                               'Official November2024 peak16900 conflicts with media2026 peak16207; peaks excluded from all models.')
        text = BeautifulSoup((RAW / 'mar_portal2024.html').read_text(), 'html.parser').get_text(' ', strip=True)
        assert all(s in text for s in ['385.738', '36.690', '2024', '95%', '16.900'])
        cumulative = self.observation('mar_cumulative2022_2024', 2024, 385738, 'evisas_issued_cumulative', official,
                                      'Communiqué paragraphs2–3;July2022 to end2024', period_start='2022-07-10',
                                      period_type='cumulative_multi_year', notes='跨年度累计；不作为2024年度数量或额外收费边。')
        india = self.observation('mar_india2024_issued', 2024, 36690, 'evisas_issued', official,
                                 'India paragraph:36690 e-visas,up52% compared with2023', nationality='IND',
                                 origin_basis='nationality', notes='印度国籍2024年度签发量；不等同申请人数或已核实付费件数。')
        self.observation('mar_cumulative_tourism_share2022_2024', 2024, .95, 'tourism_share_of_issued_evisas',
                         official, 'Cumulative385738 paragraph;95% tourist', unit='share',
                         period_start='2022-07-10', period_type='cumulative_multi_year', notes='累计用途份额，不下放到单年或国籍。')
        self.observation('mar2024_annual_growth_rounded', 2024, .06, 'annual_evisa_issuance_growth_rounded',
                         official, '2024 growth6% compared with2023', unit='growth_rate',
                         rounding_interval=[.055, .065], notes='整数百分比增长；仅作跨源残差一致性检查。')
        self.observation('mar2024_nationalities', 2024, 111, 'distinct_evisa_nationalities',
                         official, '2024 visitors of111 nationalities', unit='nationalities')
        self.observation('mar2024_nov_peak_official', 2024, 16900, 'evisas_issued_monthly_peak_disputed',
                         official, 'November2024 peak16900', period_start='2024-11-01', period_end='2024-11-30',
                         period_type='calendar_month', quality_issue='Conflicts with later media16207;not used in fee models.')
        media23 = self.source('mar_interview2023', 'mar_interview2023_browser_capture.txt',
                              'https://medias24.com/2023/12/09/tourisme-209-000-visas-electroniques-ont-ete-delivres-depuis-juillet-2022-f-z-ammor/',
                              'Médias24 / interview with Minister of Tourism Fatim-Zahra Ammor',
                              'Tourisme:209000 visas électroniques depuis juillet2022,9 December2023',
                              'Direct minister interview, not an official-original release. Direct HTML returned403; '
                              'frozen provider browser article text is archived, not original HTML. '
                              '70347 July–December2022;138728 January–November2023;209075 cumulative. '
                              'Cumulative nationality shares are excluded from annual bilateral allocation.',
                              quality='minister_interview_media_report', kind='provider_browser_text_capture')
        text23 = (RAW / 'mar_interview2023_browser_capture.txt').read_text()
        assert all(s in text23 for s in ['70.347', '138.728', '209.075', 'novembre 2023'])
        y22 = self.observation('mar2022_launch_issued', 2022, 70347, 'evisas_issued', media23,
                               'Les visas électroniques en chiffres;Minister quote70347 July–December2022',
                               period_start='2022-07-10', period_type='service_launch_to_year_end',
                               notes='电子签证自2022年7月启动，保留启动日至年末期间；未把半年签发量倍增成年。')
        partial23 = self.observation('mar2023_jan_nov_issued', 2023, 138728, 'evisas_issued_partial_year', media23,
                                     'Minister quote138728 January–November2023', period_end='2023-11-30',
                                     period_type='partial_calendar_year', notes='11个月签发量，不当作已观测全年。')
        self.observation('mar2022_2023nov_cumulative_issued', 2023, 209075, 'evisas_issued_cumulative', media23,
                         'Minister quoteJuly2022–November2023 cumulative209075', period_start='2022-07-10',
                         period_end='2023-11-30', period_type='cumulative_multi_year')
        media26 = self.source('mar_report2026', 'mar_media2026_browser_capture.txt',
                              'https://medias24.com/2026/02/18/tourisme-e-visa-accelere-la-percee-du-maroc-en-asie-et-en-afrique-1630363/',
                              'Médias24 / figures attributed to Ministry of Tourism',
                              'Tourisme:l’e-visa accélère la percée du Maroc en Asie et Afrique,18 February2026',
                              '162409 annual2024;157560 first10months2025. Media report citing ministry, not official-original dataset. '
                              'Direct HTML403;provider browser full article text archived. November2024 peak16207 conflicts '
                              'with official16900; no monthly peak enters a model.',
                              quality='media_report_attributing_ministry_data', kind='provider_browser_text_capture')
        text26 = (RAW / 'mar_media2026_browser_capture.txt').read_text()
        assert all(s in text26 for s in ['162.409', '157.560', '10 premiers mois de 2025', '16.207'])
        y24 = self.observation('mar2024_issued_media', 2024, 162409, 'evisas_issued', media26,
                               'Une montée en puissance continue depuis2022;162409 issued in2024',
                               notes='媒体转述旅游部的全年签发量；未称官方原件或实收。')
        partial25 = self.observation('mar2025_jan_oct_issued_media', 2025, 157560, 'evisas_issued_partial_year', media26,
                                     'First10months2025:157560 e-visas', period_end='2025-10-31',
                                     period_type='partial_calendar_year', notes='2025年1—10月，未称全年实测。')
        self.observation('mar2024_tourism_share_media', 2024, .93, 'tourism_share_of_issued_evisas', media26,
                         '2024:93% tourism,7% business', unit='share', notes='两类均属访客；不据此生成留学、工作或家庭签证。')
        self.observation('mar2024_nov_peak_media', 2024, 16207, 'evisas_issued_monthly_peak_disputed', media26,
                         'November2024 peak16207', period_start='2024-11-01', period_end='2024-11-30',
                         period_type='calendar_month', quality_issue='Conflicts with official16900;not used in fee models.')
        # A residual is explicitly derived, not called an observed annual total.
        count23 = 385738 - 70347 - 162409
        assert count23 == 152982 and count23 >= 138728
        assert .055 <= 162409 / count23 - 1 < .065
        derived23 = self.observation('mar2023_annual_cross_source_residual', 2023, count23,
                                     'evisas_issued_annual_cross_source_residual', official,
                                     '385738 cumulative2022–2024 minus70347 launch2022 minus162409 annual2024',
                                     source_ids=[official, media23, media26], calculation_type='derived_cross_source_residual',
                                     reused_source_observation_ids=[cumulative, y22, y24],
                                     notes='跨源可比性条件下的年度残差152982，非单独发布全年实测；与2023前11月138728及官方2024增6%相容。')
        self.excluded.extend([
            dict(destination='MAR', candidate='385738 as2024 annual', reason='Official scope is cumulativeJuly2022–end2024.'),
            dict(destination='MAR', candidate='Cumulative nationality shares', reason='Not identified for individual calendar years;never distributed across annual flows.'),
            dict(destination='MAR', candidate='2024 November peaks16900 versus16207', reason='Conflicting official and later media values;both context observations,neither modeled.'),
            dict(destination='MAR', candidate='All tourist arrivals times visa fee', reason='No arrival-based fee model;arrivals include exempt travelers and repeated trips.'),
            dict(destination='RWA', candidate='Rwanda immigration/passport/visa mixed receipts and tourist arrivals', reason='No separate visa-only receipt or matched issuance denominator verified;no money edge added.'),
        ])
        return legal, official, media23, media26, y22, partial23, derived23, india, y24, partial25

    def model(self, evidence):
        legal, official, media23, media26, y22, partial23, derived23, india, y24, partial25 = evidence
        model_id = PREFIX + 'mar_evisa_statutory_fee_value'
        for year, payer, count, low_count, high_count, oids, sids, status in [
            (2022, 'UNK', 70347, 70347, 70347, [y22], [legal, media23], 'issued_evisa_statutory_fee_value'),
            (2023, 'UNK', 152982, 152982, 152982, [derived23, partial23], [legal, official, media23, media26], 'cross_source_residual_statutory_fee_value'),
            (2024, 'IND', 36690, 36690, 36690, [india], [legal, official], 'nationality_issued_evisa_statutory_fee_value'),
            (2024, 'UNK', 125719, 125719, 125719, [y24, india], [legal, official, media26], 'annual_total_less_known_nationality_statutory_fee_value'),
            (2025, 'UNK', 189072, 157560, 204828, [partial25], [legal, media26], 'partial_year_annualized_statutory_fee_value_scenario'),
        ]:
            amount, lower, upper = count * 935, low_count * 770, high_count * 1100
            basis = 'issued_evisas_not_paid_applications'
            if year == 2023:
                basis = 'annual_issuance_cross_source_residual_not_observed_paid_applications'
            elif year == 2025:
                basis = 'annualized_partial_year_issuance_scenario_not_observed_paid_applications'
            notes = ('摩洛哥旅游/商务电子签证签发量对应的标准费值情景，非政府已核实实收。'
                     '普通700+70=770 MAD、加急1000+100=1100 MAD；加急份额未披露，中心取区间中点50%，情景0%—100%。'
                     '假定所列签发件按标准费支付且2022费率持续适用，不计拒签付款、退款、减免或其他纸质签证。')
            if year == 2023:
                notes += '全年数量为跨源累计减2022与2024的残差152982，并非单独发布全年实测。'
            if year == 2025:
                notes += '原始只有1—10月157560；中心末两月延续前十月月均，情景为该月均0—1.5倍。'
            if year == 2024 and payer == 'UNK':
                notes += '从全年162409中扣除印度36690，剩余125719国籍待分配；不把全年总量与印度重复相加。'
            self.flows.append(dict(id=PREFIX+f'mar_{year}_{payer.lower()}_evisa_fee_value', payer=payer,
                                   receiver='MAR', year=year, visa_group='visitor',
                                   visa_type='evisa_tourism_business_statutory_fee_value',
                                   visa_label='旅游/商务电子签证标准费值情景', category_detail_status='classified',
                                   amount=amount, lower=lower, upper=upper, currency='MAD',
                                   quantity=count, quantity_basis=basis, quantity_label='电子签发件数/模型数量',
                                   application_denominator_known=False, actual_receipts_observed=False,
                                   source_ids=sids, observation_ids=oids, method_id=model_id,
                                   model_status=status, calculation_type='conditional_scenario',
                                   origin_basis='nationality' if payer == 'IND' else 'unallocated',
                                   period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                                   period_type='calendar_year_model', period_label=str(year), notes=notes,
                                   parameters=dict(issued_evisa_count=count, issued_count_lower=low_count,
                                                   issued_count_upper=high_count,
                                                   normal_fee_MAD=770, express_fee_MAD=1100,
                                                   government_chancellerie_normal_express_MAD=[700, 1000],
                                                   government_service_normal_express_MAD=[70, 100],
                                                   express_share_central=.5, express_share_range=[0, 1],
                                                   express_share_evidence='not_observed;central_is_midpoint_scenario',
                                                   shared_parameter='express_share_common_within_destination_year',
                                                   issuance_equals_standard_fee_events_assumed=True,
                                                   tariff_continuity_2022_2025_assumed=True,
                                                   actual_receipts_observed=False,
                                                   late2025_monthly_volume_multiplier_central=1 if year == 2025 else None,
                                                   late2025_monthly_volume_multiplier_range=[0, 1.5] if year == 2025 else None,
                                                   range_method='共同加急份额0%—100%的标准费情景；2025另以末两月月均0—1.5倍情景，非置信区间或实收上下界')))
        for year in range(2022, 2026):
            ff = [f for f in self.flows if f['year'] == year]
            self.ranges.append(dict(receiver='MAR', year=year, currency='MAD',
                                    **{k: sum(f[k] for f in ff) for k in ['amount', 'lower', 'upper']},
                                    range_method='Same express-share parameter for all nationalities;2025 same late-year volume scenario. Conditional statutory fee values,not receipts.'))
        self.models.append(dict(model_id=model_id, destination='MAR', years=[2022, 2023, 2024, 2025],
                                status='issued_evisa_statutory_fee_value_conditional_scenario',
                                formula='issued_evisas*(770+330*express_share);2023 count=385738-70347-162409;2025=157560*(1+0.2*late_month_multiplier)',
                                limitations=['不是财政实收；签发件不等同申请人或付费申请数。',
                                             '2022为启动后签发；2023为跨源年度残差；2024全年来自媒体引用旅游部，印度数来自官方通报。',
                                             '2025原始仅前十个月，全年是明确时间情景。',
                                             '未知普通/加急组成，中心50%只是费区间中点；低高不是统计置信区间。',
                                             '假定签发件按标准费支付、2022费率持续；未估拒签付款、退款、减免和纸质签证。',
                                             '除印度2024外付款国籍未知，保持UNK；不分摊累计国籍份额。']))

    def exchange_rates(self):
        records = json.loads((ROOT / 'data/research/africa_expansion_v3/sources.json').read_text())
        s = next(r for r in records if r['source_id'] == 'afx_wb_exchange_rates')
        path = ROOT / s['local_path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == s['sha256']
        self.sources.append(s)
        z = zipfile.ZipFile(path)
        filename = next(n for n in z.namelist() if n.startswith('API_') and n.endswith('.csv'))
        rows = list(csv.reader(io.StringIO(z.read(filename).decode('utf-8-sig'))))
        header = rows[4]
        mar = dict(zip(header, next(r for r in rows[5:] if len(r) > 1 and r[1] == 'MAR')))
        for year in range(2022, 2026):
            rate = float(mar[str(year)])
            assert rate > 0
            self.fx.append(dict(fx_id=PREFIX+f'wb_mar_{year}', year=year, currency='MAD', raw_rate=rate,
                                raw_direction='currency_per_USD', usd_per_unit=1/rate,
                                source_id=s['source_id'], source_ids=[s['source_id']],
                                source_locator=f'{filename};MAR;{year};PA.NUS.FCRF',
                                method='World Bank / IMF annual official exchange rate,period average'))

    def finish(self):
        sids = {s['source_id'] for s in self.sources}
        oids = {o['observation_id'] for o in self.obs}
        assert len(sids) == len(self.sources) and len(oids) == len(self.obs)
        assert len({f['id'] for f in self.flows}) == len(self.flows)
        assert all(set(f['source_ids']) <= sids and set(f['observation_ids']) <= oids for f in self.flows)
        assert all(0 <= f['lower'] <= f['amount'] <= f['upper'] for f in self.flows)
        assert all(f['actual_receipts_observed'] is False and f['application_denominator_known'] is False for f in self.flows)
        assert sum(f['quantity'] for f in self.flows if f['year'] == 2024) == 162409
        assert sum(f['quantity'] for f in self.flows if f['year'] <= 2024) == 385738
        assert all(o['eligible_money_ledger'] is False for o in self.obs)
        for row in self.ranges:
            ff = [f for f in self.flows if f['year'] == row['year']]
            for key in ['amount', 'lower', 'upper']:
                assert sum(f[key] for f in ff) == row[key]
        overlap, checked = [], []
        for path in sorted(EST.parent.glob('*_flows.json')):
            if path == EST:
                continue
            checked.append(str(path.relative_to(ROOT)))
            for f in json.loads(path.read_text()).get('flows', []):
                if f.get('receiver') == 'MAR' and f.get('year') in range(2022, 2026):
                    overlap.append((path.name, f.get('id')))
        assert not overlap, overlap
        coverage = []
        for year in range(2022, 2026):
            for group in GROUPS:
                available = group == 'visitor'
                ff = [f for f in self.flows if f['year'] == year] if available else []
                coverage.append(dict(code='MAR', destination='MAR', name='摩洛哥', region='非洲', year=year,
                                     visa_group=group, status='amount_modeled' if available else 'not_found',
                                     fee_known=available, fee_current_snapshot_known=available,
                                     quantity_known=available and year in [2022, 2024], quantity_context_known=available,
                                     quantity_scope='issued_evisas_not_paid_applications' if available else None,
                                     arrival_context_known=False, amount_known=False, amount_modeled=available,
                                     nationality_known=available and year == 2024,
                                     category_detail_status='classified_subset' if available else 'no_classified_observation',
                                     notes=ff[0]['notes'] if available else '未取得该用途独立签发或实收；不从旅游/商务电子签证推断。',
                                     source_ids=list(dict.fromkeys(s for f in ff for s in f['source_ids'])),
                                     searched_as_of=ASOF))
        checks = dict(as_of=ASOF, sources=len(sids), observations=len(oids), fees=len(self.fees),
                      fx=len(self.fx), flows=len(self.flows), models=len(self.models), coverage_rows=len(coverage),
                      receivers=['MAR'], years=list(range(2022, 2026)),
                      annual_quantities={str(y):sum(f['quantity'] for f in self.flows if f['year'] == y) for y in range(2022, 2026)},
                      totals_native={f"MAR_{r['year']}_MAD":r['amount'] for r in self.ranges},
                      official_cumulative_not_annual_and_not_duplicate_edge=True,
                      india2024_deducted_from_unknown_residual=True,
                      no_cumulative_nationality_allocation=True,
                      media_browser_captures_not_claimed_original_html=True,
                      annual2023_cross_source_residual_not_claimed_observed=True,
                      annual2023_residual_agrees_with_rounded_official_growth=True,
                      annual2025_not_claimed_observed=True,
                      statutory_fee_value_not_claimed_actual_receipts=True,
                      no_claimed_paid_application_denominator=True,
                      two_government_fee_components_combined_once=True,
                      fee_tables_visually_verified=True,
                      conflicting_monthly_peaks_excluded_from_models=True,
                      no_arrival_times_fee_model=True, no_duplicate_existing_receiver_year=True,
                      overlap_checked_packages=checked)
        package = dict(package='africa_visa_issuance_v5', as_of=ASOF, flows=self.flows, models=self.models,
                       destination_ranges=self.ranges, subtotals=[], coverage_rows=len(coverage),
                       scope='Morocco electronic tourism/business visa statutory-fee-value scenarios2022–2025;2024 India nationality retained;not actual receipts;2023 cross-source residual;2025 partial-year annualization')
        for name, obj in [('sources.json', self.sources), ('observations.json', self.obs),
                          ('fee_rules.json', self.fees), ('fx.json', self.fx), ('coverage.json', coverage),
                          ('excluded_candidates.json', self.excluded), ('checks.json', checks)]:
            dump(OUT / name, obj)
        dump(EST, package)
        (OUT / 'README.md').write_text('''# 摩洛哥电子签证签发与标准费值扩展 v5

离线复算：`.research-venv/bin/python scripts/research_africa_visa_issuance_v5.py`。

- 2022年启动后70,347件，来自部长直接采访的媒体全文捕获，不是官方原件。
- 官方截至2024末累计385,738件，不能写成2024全年。2024全年162,409件来自媒体引用旅游部；2023以累计减2022、2024得152,982件，明确跨源残差，并与官方2024增长6%相容。2023前11月138,728单独保留。
- 印度2024年36,690件来自政府通报；从全年总量扣除后国籍待分配125,719件，避免总数与分项重复。其他年份不套累计国籍份额。
- 2025只观测到前10月157,560件。全年中心189,072；末两月各为前10月月均0—1.5倍时，全年157,560—204,828，是明确情景。
- 2022年BO7106第849页政府签证费700/1000 MAD，加第853页政府服务收费70/100 MAD，普通770、加急1100。两页已渲染目视核对。50%加急中心仅为费区间中点，0%—100%为共同参数情景，没有实测占比依据。费率持续至2025是明确模型假设。
- 所有金额是签发量对应的标准费值，非已核实实收；未估拒签支付、退款、减免或纸质签证，不能作为每申请人实际花费。签发件数不是独立申请人。
- 官方2024年11月峰值16,900与2026媒体16,207冲突，均作背景观察、均不进入模型。
- 直接HTML访问媒体页为403，冻结的是可读取浏览器文章全文，来源质量与归档类型明确；未冒称下载到原始HTML。官方公报和政府通报为原件。
- World Bank/IMF同年年均MAD/USD归档复用已有来源和哈希，2022—2025齐备。
- 卢旺达未取得可分离签证收入或匹配签发分母，不以游客量乘费率补边。

`checks.json`含计数与守恒检查。原始累计、部分年度和费用分项不是额外收费边。
''')
        print(json.dumps(checks, ensure_ascii=False))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    r = Research()
    evidence = r.evidence()
    r.model(evidence)
    r.exchange_rates()
    r.finish()


if __name__ == '__main__':
    main()
