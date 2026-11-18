#!/usr/bin/env python3
"""Offline Azerbaijan/Namibia ledger extension plus Mongolia quantity evidence.

Issued eVisas, government cash, arrival counts and visa permissions are distinct.
Only published nationalities are allocated. A 2025 carry-forward is an explicit
scenario. Rebuild exclusively from frozen originals; no online step is required.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import json
import logging
from pathlib import Path
import re

from bs4 import BeautifulSoup
from pypdf import PdfReader

logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/spatial_expansion_v2'
OUT = ROOT / 'data/research/spatial_expansion_v2'
EST = ROOT / 'data/estimates/spatial_expansion_v2_flows.json'
ASOF = '2026-11-16'
NAMES = {'AZE': '阿塞拜疆', 'NAM': '纳米比亚', 'MNG': '蒙古国'}
GROUPS = ('visitor', 'student', 'work', 'family', 'other')


def html(name):
    return BeautifulSoup((RAW / name).read_text(), 'html.parser').get_text(' ', strip=True)


def compact(text):
    return re.sub(r'\s+', '', text)


class Research:
    def __init__(self):
        self.sources, self.obs, self.fees, self.fx = [], [], [], []
        self.flows, self.models, self.ranges = [], [], []

    def source(self, slug, filename, url, publisher, title, notes='', quality='official_original'):
        path = RAW / filename
        assert path.exists() and path.stat().st_size > 100, filename
        sid = 'spv2_' + slug
        self.sources.append(dict(source_id=sid, url=url, publisher=publisher, title=title,
                                 retrieved_at=ASOF, source_quality=quality,
                                 local_path=str(path.relative_to(ROOT)), path=str(path.relative_to(ROOT)),
                                 bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                 archive_kind='original_document', notes=notes))
        return sid

    def observation(self, slug, destination, year, metric, value, unit, sid, locator, **extra):
        oid = 'spv2_' + slug
        nationality = extra.pop('nationality', 'UNK')
        self.obs.append(dict(observation_id=oid, destination=destination, year=year,
                             metric=metric, raw_metric=extra.pop('raw_metric', metric), value=value,
                             unit=unit, source_id=sid, source_ids=[sid], source_locator=locator,
                             nationality=nationality, origin_basis='observed_nationality' if nationality != 'UNK' else 'unallocated',
                             visa_type=extra.pop('visa_type', 'evisa'), visa_group='other',
                             period_start=extra.pop('period_start', f'{year}-01-01'),
                             period_end=extra.pop('period_end', f'{year}-12-31'),
                             period_type=extra.pop('period_type', 'calendar_year'),
                             calculation_type=extra.pop('calculation_type', 'direct_observation'), **extra))
        return oid

    def flow(self, payer, receiver, year, typ, amount, lower, upper, currency, sources,
             observations, quantity, quantity_basis, notes, params, method, status):
        assert 0 <= lower <= amount <= upper
        self.flows.append(dict(id=f'spv2_{receiver.lower()}_{year}_{payer.lower()}_{typ}',
                               payer=payer, receiver=receiver, year=year, visa_group='other',
                               visa_type=typ, visa_label='电子签证国家费' if receiver == 'AZE' else '落地签证计划收入',
                               category_detail_status='unclassified', amount=amount, lower=lower,
                               upper=upper, currency=currency, quantity=quantity, quantity_basis=quantity_basis,
                               source_ids=list(dict.fromkeys(sources)), observation_ids=list(dict.fromkeys(observations)),
                               method_id=method, model_status=status,
                               calculation_type='conditional_scenario' if year == 2025 else 'deterministic_tariff_value',
                               origin_basis=('unallocated' if payer == 'UNK' else 'modeled_prior_year_nationality' if year == 2025 else 'observed_nationality'),
                               period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                               period_type='calendar_year_model', period_label=str(year), notes=notes,
                               parameters=params))

    def azerbaijan(self):
        s24 = self.source('aze_tourism2024', 'aze_tourism2024.pdf',
                          'https://tourism.gov.az/uploads/documents/2024_statistika/statrep_2024_pages.pdf',
                          'State Tourism Agency of the Republic of Azerbaijan / ASAN',
                          'Annual Tourism Statistics 2024, Table A3: e-Visas issued',
                          'PDF p15 table A3 records eVisa issuances, despite reused Total arrivals column heading. 2023 total revised to 613818 from 613805. p16 shows purposes differ; do not classify all as visitor visas.')
        s23 = self.source('aze_tourism2023', 'aze_tourism2023.pdf',
                          'https://tourism.gov.az/uploads/documents/2023_statistika/%2Bannual_tourism_statistics_2023_f%C4%B0nal.pdf',
                          'State Tourism Agency of the Republic of Azerbaijan / ASAN',
                          'Annual Tourism Statistics 2023, Table A3: e-Visas issued',
                          'PDF p15 table A3, 2022/2023. Its 2023 total 613805 is superseded by 613818 in 2024 report; overlapping country values agree.')
        sf = self.source('aze_state_fee', 'aze_state_fee.html',
                         'https://www.migration.gov.az/en/page_detail/937',
                         'State Migration Service of the Republic of Azerbaijan', 'Electronic visa: state fee USD20',
                         'Government fee USD20, separate from online service/urgent charges. Official page last updated 2025-11-06.')
        sh = self.source('aze_historical_fee2019', 'aze_evisa_mfa_2017_greece.pdf',
                         'https://agora.mfa.gr/infofiles/Visa%20Information%20Azerbaijan%20az.pdf',
                         'EU-Azerbaijan Business Forum 2019; archived by Greek Ministry of Foreign Affairs',
                         'EU-Azerbaijan Business Forum 2019: Visa Information',
                         'Contemporaneous 2019 official-hosted document: USD20 visa plus USD3 service, system since 10 January2017. Used with 2025 official state-fee snapshot as historical-rate evidence; no intervening tariff change identified.',
                         'official_hosted_contemporaneous_document')
        t24 = PdfReader(RAW / 'aze_tourism2024.pdf').pages[14].extract_text()
        t23 = PdfReader(RAW / 'aze_tourism2023.pdf').pages[14].extract_text()
        assert all(x in compact(t24) for x in ['831899', '613818', '270327', '139617', '13641', '7216'])
        assert all(x in compact(t23) for x in ['613805', '521407', '22135', '3285'])
        assert 'state fee is 20 USD' in html('aze_state_fee.html')
        assert '20USD+3USDservicefee' in compact(PdfReader(RAW / 'aze_evisa_mfa_2017_greece.pdf').pages[0].extract_text())
        (OUT / 'aze_tableA3_2024.txt').write_text(t24)
        (OUT / 'aze_tableA3_2023.txt').write_text(t23)
        self.fees.append(dict(id='spv2_aze_evisa_state20', fee_rule_id='spv2_aze_evisa_state20', destination='AZE',
                              visa_type='evisa_state_fee', visa_group='other', amount=20, currency='USD',
                              component='government_visa_fee', source_id=sf, source_ids=[sf, sh],
                              source_locator='Migration Service eVisa paragraph; 2019 Business Forum visa document p1',
                              effective_from=None, effective_to=None, historical_snapshot_year=2019,
                              current_snapshot_date='2025-11-06', validity_status='historical_and_current_snapshots_no_intervening_change_identified',
                              payment_trigger='application_submission',
                              notes='20美元国家费，2019与2025快照相符；2022—2024沿用此费率计算签发收费值。未将3/5美元服务费或加急差额算入国家费，也不把签发收费值称为实收。'))
        old23 = {'IND':139617,'SAU':81401,'PAK':71188,'KWT':29525,'ISR':29158,'CHN':22135,
                 'ARE':20027,'OMN':17086,'GBR':17020,'USA':15566,'DEU':14025}
        counts = {
            2022: {'IND':75022,'SAU':96648,'PAK':70872,'KWT':22626,'ISR':23898,'CHN':3285,
                   'ARE':41241,'OMN':18700,'GBR':13125,'USA':11193,'DEU':10417},
            2023: {**old23,'IRN':13742,'KOR':7216},
            2024: {'IND':270327,'PAK':105594,'SAU':97949,'KWT':30990,'ISR':28610,'OMN':23925,
                   'GBR':20603,'USA':19224,'DEU':16565,'IRN':15282,'KOR':13641}}
        totals = {2022:521407,2023:613818,2024:831899}
        total_oids, country_oids = {}, {}
        self.observation('aze_2023_total_superseded', 'AZE', 2023, 'evisas_issued_superseded_total',
                         613805, 'visas', s23, 'PDF p15 table A3 total',
                         eligible_money_ledger=False, conflict_group='aze_2023_evisa_total',
                         notes='旧报告613805；新报告修订为613818，多13件。模型仅使用新总量，旧值留作修订记录。')
        for year, cc in counts.items():
            sid = s23 if year == 2022 else s24
            total_oids[year] = self.observation(f'aze_{year}_total', 'AZE', year, 'evisas_issued', totals[year],
                                               'visas', sid, 'PDF p15 Table A3 total',
                                               notes='电子签证签发人数；不是游客入境总数，也不等于含拒签的付费申请量。')
            for payer, qty in cc.items():
                csid = s23 if year == 2022 or year == 2023 and payer in ('CHN','ARE') else s24
                assert str(qty) in compact(t23 if csid == s23 else t24), (year,payer,qty)
                country_oids[(year,payer)] = self.observation(f'aze_{year}_{payer.lower()}_issued', 'AZE', year,
                                                            'evisas_issued', qty, 'visas', csid,
                                                            'PDF p15 table A3 nationality row', nationality=payer)
            cc['UNK'] = totals[year] - sum(cc.values())
            assert cc['UNK'] >= 0
        for year in (2022,2023,2024,2025):
            anchor = min(year,2024)
            scenario = year == 2025
            for payer, qty in counts[anchor].items():
                oid = total_oids[anchor] if payer == 'UNK' else country_oids[(anchor,payer)]
                amount = qty * 20
                params = dict(issued_anchor_year=anchor, issued_in_anchor=qty, state_fee_USD=20,
                              quantity_multiplier=1, quantity_multiplier_range=[.75,1.25] if scenario else [1,1],
                              actual_receipts_observed=False, refused_paid_applications_excluded=True,
                              nationality_allocation='published nationality only; residual UNK',
                              fee_evidence='2019 contemporaneous USD20 + separate service fee; official2025 USD20 state fee; historical rate continuity assumed',
                              range_method='2024签发量不变的2025运行率情景，数量±25%工作敏感性；非2025实测' if scenario else '真实签发量×20美元国家费；确定性收费值，非财政实收区间')
                self.flow(payer,'AZE',year,'evisa_state_fee_tariff_value',amount,amount * (.75 if scenario else 1),
                          amount * (1.25 if scenario else 1),'USD',[s23,s24,sf,sh],[oid,total_oids[anchor]],
                          qty if not scenario else None,
                          'observed_evisas_issued_not_paid_applications' if not scenario else '2024_issued_runrate_scenario_not_observed_2025_applications',
                          ('2025沿用2024已签发量和公开国籍结构；数量±25%是工作情景。' if scenario else '') +
                          '阿塞拜疆电子签证签发量×20美元国家费。排除服务费及加急附加费，未补入拒签付款、纸签或减免差异；只将原表明确国籍分配到付款方，余量保留未分配。用途未细分。',
                          params,'spv2_aze_issued_state_fee',
                          'prior_year_runrate_scenario' if scenario else 'issued_tariff_value_partial_estimate')
            total = totals[anchor] * 20
            self.ranges.append(dict(receiver='AZE',year=year,amount=total,lower=total*(.75 if scenario else 1),
                                    upper=total*(1.25 if scenario else 1),currency='USD',
                                    range_method='2024运行率数量±25%工作敏感性' if scenario else '已签发电子签20美元国家费值'))
        self.models.append(dict(model_id='spv2_aze_issued_state_fee',destination='AZE',years=[2022,2023,2024,2025],
                                status='observed_issuance_tariff_value_and_explicit_2025_runrate',
                                formula='published eVisas issued * USD20 government state fee; 2025 = 2024 count * quantity multiplier',
                                limitations=['签发收费值不等于财政实收；未包括拒签付款、服务费和纸签。',
                                             '2019和2025费率快照均20美元，中间年份沿用同费率。',
                                             '2023总量采用2024报告修订613818；2023报告613805仅留冲突记录。',
                                             '2025不是观测结果，±25%只是运行率工作情景。',
                                             '公开的国籍之外仅记UNK；未将未知国籍归给中国或其他付款方。']))

    def namibia(self):
        sj = self.source('nam_president2025', 'nam_june2025.pdf',
                         'https://namibiaembassyusa.org/wp-content/uploads/2025/07/Statement-by-Her-Excellency-Dr.-Netumbo-Nandi-Ndaitwah-President-of-the-Republic-of-Namibia-on-the-Occasion-of-The-Launch-of-the-6th-National-Development-Plan-DR-Netumbo-Nandi-.pdf',
                         'President of the Republic of Namibia / Embassy of Namibia in the USA',
                         'Launch of Sixth National Development Plan: presidential statement',
                         'PDF p31: policy implemented1April2025, as of30June2025 115857 visas and NAD171million revenue.')
        sn = self.source('nam_nampa2026', 'nam_nbc2026.html','https://nbcnews.na/node/115544',
                         'Namibian Broadcasting Corporation / NAMPA, quoting Minister of Home Affairs',
                         'Visa-on-arrival generates N$413 million in under a year',
                         'Exact ministerial report period03March2025–31January2026: 289510 visas and NAD413356900 revenue. Distinct from passport/document income.',
                         'official_agency_report_of_minister')
        sf = self.source('nam_fee2025', 'nam_fee2025.html','https://embassyofnamibia.fr/fees-and-requirements.php',
                         'Embassy of the Republic of Namibia in France','Visa Fees and Exemptions',
                         'Dated policy effective01April2025, listed reciprocity countries NAD1600. Do not apply this tariff to every nationality or reconstruct receipts from visa counts.')
        sp = self.source('nam_currency_peg', 'nam_central_bank_peg.html','https://www.bon.com.na/Bank/Monetary-Policy.aspx',
                         'Bank of Namibia','Monetary Policy: one-to-one Namibia Dollar / South Africa Rand parity')
        j = compact(PdfReader(RAW/'nam_june2025.pdf').pages[30].extract_text())
        assert '115,857' in j and '171million' in j and '30June2025' in j
        n = html('nam_nbc2026.html')
        assert all(x in n for x in ['03 March 2025 to 31 January 2026','289,510','413,356,900'])
        assert '01 April 2025' in html('nam_fee2025.html') and 'N$1600.00' in html('nam_fee2025.html')
        assert 'one-to-one parity between the Namibia Dollar and the South Africa Rand' in html('nam_central_bank_peg.html')
        o1 = self.observation('nam_2025_june_voa_revenue','NAM',2025,'visa_on_arrival_actual_revenue',171000000,'NAD',sj,
                              'PDF p31, tourism paragraph',period_start='2025-04-01',period_end='2025-06-30',
                              period_type='partial_calendar_year',visa_type='visa_on_arrival',
                              notes='总统原文171million，精度为百万；不是2025全年收入。')
        self.observation('nam_2025_june_voa_issued','NAM',2025,'visa_on_arrival_issued',115857,'visas',sj,
                         'PDF p31, tourism paragraph',period_start='2025-04-01',period_end='2025-06-30',
                         period_type='partial_calendar_year',visa_type='visa_on_arrival')
        o2 = self.observation('nam_2025_2026_voa_revenue','NAM',2025,'visa_on_arrival_actual_revenue',413356900,'NAD',sn,
                              'Minister quote beginning From03March2025',period_start='2025-03-03',period_end='2026-01-31',
                              period_type='cross_calendar_year_observation',visa_type='visa_on_arrival',
                              notes='跨年累计实收；不能原样标成2025全年。')
        self.observation('nam_2025_2026_voa_issued','NAM',2025,'visa_on_arrival_issued',289510,'visas',sn,
                         'same Minister quote',period_start='2025-03-03',period_end='2026-01-31',
                         period_type='cross_calendar_year_observation',visa_type='visa_on_arrival')
        total_days = (date(2026,1,31)-date(2025,3,3)).days + 1
        days25 = (date(2025,12,31)-date(2025,3,3)).days + 1
        assert (total_days,days25)==(335,304)
        amount = 413356900 * days25 / total_days
        params = dict(cross_year_observed_revenue_NAD=413356900, cross_year_days=335,
                      days_in_2025=304, calendar_bridge_weight=304/335,
                      reported_partial_2025_revenue_NAD=171000000,
                      nonnegative_receipts_assumption=True, uniform_daily_receipts_is_scenario=True,
                      whole_country_all_visa_revenue=False, nationality_allocation='none',
                      range_method='2025部分实收171m为下情景，跨年累计413.3569m为上情景；中心按304/335天平摊，非置信区间')
        self.flow('UNK','NAM',2025,'voa_receipts_calendar_bridge',amount,171000000,413356900,'NAD',
                  [sj,sn],[o1,o2],None,'calendar_revenue_bridge_no_observed_full_year_application_denominator',
                  '纳米比亚新落地签证计划2025自然年收入桥接：2025年3月3日至2026年1月31日实收4.133569亿纳元，中心按304/335天分配到2025；6月底披露1.71亿为下情景，跨年总额为上情景。政策4月生效、平台3月开放分开保存。只计该计划，国籍未知。',
                  params,'spv2_nam_calendar_receipts_bridge','observed_receipts_calendar_bridge_estimate')
        self.ranges.append(dict(receiver='NAM',year=2025,amount=amount,lower=171000000,upper=413356900,
                                currency='NAD',range_method=params['range_method']))
        self.models.append(dict(model_id='spv2_nam_calendar_receipts_bridge',destination='NAM',years=[2025],
                                status='actual_receipt_observations_calendar_allocation_scenario',
                                formula='NAD413356900 * 304/335; scenarios NAD171000000..413356900',
                                limitations=['中心是均匀日收入的自然年分配情景，未观察2025年逐月收入。',
                                             '上下来自两段官方披露并假设非负收入；171m原文取整，非精确统计界限。',
                                             '只覆盖落地签证计划，非全部纳米比亚签证收入。',
                                             '289510为跨年签发量，不用作2025自然年每申请人分母。',
                                             '未取得国籍，全部保留UNK；不以1600纳元乘所有签发件数。']))
        self.fees.append(dict(id='spv2_nam_reciprocity_2025',fee_rule_id='spv2_nam_reciprocity_2025',destination='NAM',
                              visa_type='visa_on_arrival_reciprocity_list',visa_group='visitor',amount=1600,currency='NAD',
                              component='government_visa_fee',source_id=sf,source_ids=[sf],effective_from='2025-04-01',
                              effective_to=None,validity_status='dated_historical_rule',
                              notes='仅使馆列明互惠政策对象；其他国籍、未成年人减免及不同通道不能统一套用。金额模型用实收，未用此费率乘总件数。'))
        fx_sources = json.loads((ROOT/'data/research/global_americas_africa/sources.json').read_text())
        fxs = next(s for s in fx_sources if s['source_id']=='gaa_fx_wb_zaf')
        assert hashlib.sha256((ROOT/fxs['local_path']).read_bytes()).hexdigest()==fxs['sha256']
        self.sources.append(fxs)
        fx = next(f for f in json.loads((ROOT/'data/research/global_americas_africa/fx.json').read_text()) if f['year']==2025 and f['currency']=='ZAR')
        self.fx.append(dict(fx_id='spv2_nad_2025_peg_zar',year=2025,currency='NAD',raw_rate=fx['raw_rate'],
                            raw_direction='currency_per_USD',usd_per_unit=fx['usd_per_unit'],source_id=sp,
                            source_ids=[sp,fx['source_id']],source_locator='Bank of Namibia monetary-policy parity; WDI PA.NUS.FCRF ZAF2025',
                            method='NAD=ZAR 1:1 peg; use existing World Bank2025 annual-average ZAR/USD rate'))

    def mongolia(self):
        entries = [
            ('mng2023','mng_2023.html','https://immigration.gov.mn/mn/articles/423/','eVisa development since2021; 2023 full year and 2024 first11months'),
            ('mng2024','mng_2024.html','https://immigration.gov.mn/mn/articles/426/','2024 immigration agency annual activity:92427eVisas'),
            ('mng2024_conflict','mng_2024_conflict.html','https://immigration.gov.mn/mn/articles/428/','2024 visa and visa-permission approval:92927eVisas'),
            ('mng2024_china','mng_2024_nationality.html','https://immigration.gov.mn/en/articles/445/','2024 eVisas granted to87423 Chinese nationals'),
            ('mng2025','mng_2025_ikon.html','https://ikon.mn/n/3kj4','2025:85690eVisas,124945visas and permissions; quoted Immigration Agency')]
        sids = {}
        for slug,filename,url,title in entries:
            sids[slug] = self.source(slug,filename,url,
                                     'Immigration Agency of Mongolia' if slug!='mng2025' else 'iKon.mn, quoting Immigration Agency of Mongolia',
                                     title,'量值保留；未取得足够历史国籍互惠费率，未进入金额总账。',
                                     'official_original' if slug!='mng2025' else 'news_report_of_official_agency')
        for slug,year,qty,token in [('mng2023',2023,31242,'31242'),('mng2024',2024,92427,'92427'),
                                   ('mng2024_conflict',2024,92927,'92,927'),('mng2025',2025,85690,'85,690')]:
            filename=next(e[1] for e in entries if e[0]==slug)
            assert token in html(filename)
            self.observation(f'{slug}_issued','MNG',year,'evisas_issued_conflicting_official_total' if 'conflict' in slug else 'evisas_issued',
                             qty,'visas',sids[slug],'article body eVisa sentence',eligible_money_ledger=False,
                             conflict_group='mng_2024_evisa_total' if year==2024 else None,
                             notes='2024同机构92427与92927相差500，保留两数；未自行消解，未算签证权限为签证。' if year==2024 else '真实签发量；不等于含拒签付款的申请量。')
        assert '87423' in html('mng_2024_nationality.html')
        self.observation('mng_2024_china_evisas','MNG',2024,'evisas_issued',87423,'visas',sids['mng2024_china'],
                         'article body 2024 China paragraph',nationality='CHN',eligible_money_ledger=False,
                         notes='官方披露中国国籍电子签证87423；尚未取得匹配历史费率与减免，未用统一50美元强行计算。')
        self.observation('mng_2024_visa_permissions','MNG',2024,'visa_permissions_not_visas',48844,'permissions',sids['mng2024'],
                         'annual activity first paragraph',visa_type='visa_permission',eligible_money_ledger=False,
                         notes='签证许可，不是签证，不与电子签签发重复相加为付费申请总量。')
        self.observation('mng_2024_ordinary_visas','MNG',2024,'ordinary_visas_issued',12898,'visas',sids['mng2024'],
                         'annual activity first paragraph',visa_type='ordinary_visa',eligible_money_ledger=False)

    def finish(self):
        self.source('khm_2024_treasury_context', 'khm_financial2024.pdf',
                    'https://www.treasury.gov.kh/media/documents/FS_2024.pdf',
                    'Cambodia General Department of National Treasury',
                    'Financial Statements 2024',
                    'Aggregate non-tax revenue mentions visa receipts among many sources, but does not isolate visa amount. Archived as excluded context, never substituted for visa receipts.')
        sids={s['source_id'] for s in self.sources};oids={o['observation_id'] for o in self.obs}
        assert len(sids)==len(self.sources) and len(oids)==len(self.obs)
        assert len({f['id'] for f in self.flows})==len(self.flows)
        for f in self.flows:
            assert set(f['source_ids'])<=sids and set(f['observation_ids'])<=oids
            assert f['payer']!='WORLD' and f['payer']!=f['receiver']
            assert not (f['year']==2025 and f['quantity'] is not None), '2025 quantities must not masquerade as observations'
        for r in self.ranges:
            ff=[f for f in self.flows if f['receiver']==r['receiver'] and f['year']==r['year']]
            for k in ('amount','lower','upper'):
                assert abs(sum(f[k] for f in ff)-r[k])<.01
        scopes={(f['receiver'],f['year']) for f in self.flows}
        packages,overlap=[],[]
        for path in sorted(EST.parent.glob('*_flows.json')):
            if path==EST: continue
            packages.append(str(path.relative_to(ROOT)))
            for f in json.loads(path.read_text()).get('flows',[]):
                if (f.get('receiver'),f.get('year')) in scopes: overlap.append((str(path),f.get('id')))
        assert not overlap, overlap
        coverage=[]
        for code,years in {'AZE':[2022,2023,2024,2025],'NAM':[2025],'MNG':[2023,2024,2025]}.items():
            ss=[s['source_id'] for s in self.sources if s['source_id'].startswith('spv2_'+code.lower())]
            for year in years:
                for group in GROUPS:
                    unclassified=group=='other'
                    ff=[f for f in self.flows if f['receiver']==code and f['year']==year and unclassified]
                    context=unclassified and any(o['destination']==code and o['year']==year for o in self.obs)
                    note={'AZE':'2022—2024真实电子签签发与公开国籍；金额为20美元国家费值。2025是2024运行率±25%情景；不是2025观测。',
                          'NAM':'2025新落地签计划部分实收与跨年实收桥接；自然年中心按天平摊，国籍未知。',
                          'MNG':'取得2023—2025电子签数量和2024中国国籍数量；2024官方总数相差500。国籍互惠费率未匹配，金额留缺。'}[code]
                    coverage.append(dict(code=code,destination=code,name=NAMES[code],region='非洲' if code=='NAM' else '亚洲',
                                         year=year,visa_group=group,status='amount_modeled' if ff else 'quantity_context_only' if context else 'not_found',
                                         fee_known=unclassified and code=='AZE',fee_current_snapshot_known=(unclassified and code=='AZE') or code=='NAM' and group=='visitor',
                                         quantity_known=unclassified and code in ('AZE','MNG') and not(code=='AZE' and year==2025),
                                         quantity_context_known=context,category_detail_status='unclassified_aggregate' if unclassified else 'no_classified_observation',
                                         arrival_context_known=False,amount_known=False,amount_modeled=bool(ff),
                                         nationality_known=unclassified and (code=='AZE' and year<2025 or code=='MNG' and year==2024),
                                         notes=note if unclassified else '本类别尚未单独拆分；'+note,source_ids=ss,searched_as_of=ASOF))
        totals=defaultdict(float)
        for f in self.flows: totals[f"{f['receiver']}_{f['year']}_{f['currency']}"]+=f['amount']
        checks=dict(as_of=ASOF,sources=len(sids),observations=len(oids),fees=len(self.fees),flows=len(self.flows),
                    receivers=sorted({f['receiver'] for f in self.flows}),quantity_destinations=sorted(NAMES),
                    years=sorted({f['year'] for f in self.flows}),coverage_rows=len(coverage),totals_native=dict(totals),
                    no_duplicate_existing_receiver_year=True,overlap_checked_packages=packages,
                    provenance='all sources/observations resolve; source quantities and tariffs asserted in frozen originals; destination ranges reconcile to allocated+UNK edges',
                    actual_cash_flows=False,all_2025_full_year_quantities_are_unobserved=True,
                    china_hongkong_macao_taiwan_naming='no additional Hong Kong/Macao/Taiwan nodes introduced; China bilateral quantity labeled China')
        package=dict(package='spatial_expansion_v2',as_of=ASOF,flows=self.flows,models=self.models,destination_ranges=self.ranges,
                     subtotals=[],scope='Azerbaijan2022–24observed-eVisa state-fee values plus2025runrate; Namibia2025actual-receipts calendar bridge; Mongolia quantities only',
                     coverage_rows=len(coverage))
        for name,obj in [('sources.json',self.sources),('observations.json',self.obs),('fee_rules.json',self.fees),('fx.json',self.fx),
                         ('coverage.json',coverage),('checks.json',checks),('search_log.json',[
                             dict(destination='AZE',result='Official2023/2024reportA3;2019and2025fee snapshots;2025reportnotlocated',searched_at=ASOF),
                             dict(destination='NAM',result='President2025PDF,NBC/NAMPA2026ministerquote,embassydatedfees,centralbankpeg;annualreportportalblocked',searched_at=ASOF),
                             dict(destination='MNG',result='Official2023/24/China2024quantities;2025mediaagencyquote;2024countconflictretained;feereciprocityunresolved',searched_at=ASOF),
                             dict(destination='KHM',result='Official2024Treasuryfinancialstatementsarchived;aggregatenontaxincomenotisolatedvisaincome;excluded',searched_at=ASOF)])]:
            (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
        EST.write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(checks,ensure_ascii=False))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    r=Research();r.azerbaijan();r.namibia();r.mongolia();r.finish()


if __name__=='__main__': main()
