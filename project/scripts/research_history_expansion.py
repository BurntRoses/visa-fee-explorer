#!/usr/bin/env python3
"""Rebuild Japan 2011–2023 and Korea 2020–2023 from frozen official evidence.

Japanese purpose totals are disjoint; multiple-entry is a subset, not another
visa. Historical nominal tariffs are benchmarks, with dated reciprocity and
waiver evidence. Output intervals are parameter scenarios, not confidence bands.
"""
from __future__ import annotations

import gettext
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import openpyxl
import pycountry
from bs4 import BeautifulSoup
from pypdf import PdfReader

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/history_expansion'
OUT = ROOT / 'data/research/history_expansion'
EST = ROOT / 'data/estimates/history_expansion_flows.json'
YEARS = list(range(2011, 2024))
ASOF = '2026-11-16'
GROUPS = ('visitor', 'student', 'work', 'family', 'other')
LABELS = dict(visitor='短期访问', student='学生', work='工作', family='家族', other='其他签证')
MODEL_JP = 'hxp_jpn_issued_historical_tariff'
MODEL_KR = 'hxp_kr_historical_fee_scenario'


def norm(v):
    return re.sub(r'[\s()（）・,，.\-－]', '', unicodedata.normalize('NFKC', str(v or '')))


def read(path):
    return json.loads(path.read_text())


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def leaf_text(node):
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return ''.join(leaf_text(x) for x in node)
    if isinstance(node, dict):
        return leaf_text(node.get('children', []))
    return ''


def japanese_codes():
    translate = gettext.translation('iso3166-1', pycountry.LOCALES_DIR, languages=['ja']).gettext
    aliases = {}
    for country in pycountry.countries:
        for key in ('name', 'official_name', 'common_name'):
            label = getattr(country, key, None)
            if label:
                aliases[norm(translate(label))] = country.alpha_3
    extra = {
        'その他': 'UNK', 'エリトリア': 'ERI', 'オーストラリア': 'AUS',
        'カーボベルデ共和国': 'CPV', 'キルギス': 'KGZ', 'コソボ': 'XKX',
        'コンゴー': 'COG', 'ザイール': 'COD', 'ジブティ': 'DJI', 'ジョージア': 'GEO',
        'スロべニア': 'SVN', 'スワジランド': 'SWZ',
        'セントクリストファー・ネイビス': 'KNA', 'セントクリストファー・ネービス': 'KNA',
        'セントビンセント': 'VCT', 'セント・ヴィンセント': 'VCT', 'ソロモン': 'SLB',
        'バチカン': 'VAT', 'ブルネイ': 'BRN', 'ボスニア・ヘルツェゴヴナ': 'BIH',
        'マカオ旅行証': 'MAC', 'マケドニア旧ユーゴスラビア共和国': 'MKD',
        'マーシャル': 'MHL', 'ミクロネシア': 'FSM', 'モンゴル': 'MNG',
        'ユーゴスラビア社会主義連邦共和国': 'UNK', 'ロシア': 'RUS',
        '中国（台湾）': 'TWN', '中国（香港）': 'HKG', '中央アフリカ': 'CAF',
        '大韓民国': 'KOR', '東チモール民主共和国': 'TLS',
        '英国保護領': 'UNK', '英国属領': 'UNK', '英国直轄領': 'UNK', '英国（その他）': 'UNK',
        '香港DI': 'HKG', '香港ＤＩ': 'HKG', '香港ＳＡＲ': 'HKG', '香港（英国）': 'HKG',
    }
    aliases.update({norm(k): v for k, v in extra.items()})
    return aliases


def subset_extreme(capacities, coefficients, multiple, maximum=False):
    """Exact linear optimum with one shared observed multiple-entry constraint."""
    remaining = multiple
    result = 0.
    for i in sorted(range(len(capacities)), key=lambda i: coefficients[i], reverse=maximum):
        allocated = min(remaining, capacities[i])
        result += allocated * coefficients[i]
        remaining -= allocated
    assert abs(remaining) < 1e-7
    return result


def feasible_center(capacities, multiple):
    result = []
    remaining, capacity = multiple, sum(capacities)
    for count in capacities:
        lo, hi = max(0, remaining - (capacity - count)), min(count, remaining)
        selected = (lo + hi) / 2
        result.append(selected)
        remaining -= selected
        capacity -= count
    assert abs(remaining) < 1e-7
    return result


class Package:
    def __init__(self):
        self.sources, self.obs, self.fees, self.fx = [], [], [], []
        self.flows, self.models, self.ranges, self.coverage, self.checks = [], [], [], [], []
        self.conflicts = []
        self.aliases = japanese_codes()
        self.snapshots = [read(RAW / f'japan_detroit_fees{y}_facts.json') for y in (2011, 2015, 2023)]
        self.sids = {}

    def source(self, slug, filename, url, publisher, title, fact_capture=False, notes=''):
        path = ROOT / filename if filename.startswith('data/') else RAW / filename
        sid = 'hxp_' + slug
        if sid in self.sids:
            return sid
        assert path.exists()
        self.sources.append(dict(source_id=sid, url=url, publisher=publisher, title=title,
                                 local_path=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest(), retrieved_at=ASOF,
                                 source_quality='official_primary_factual_capture' if fact_capture else 'official_primary',
                                 archive_kind='structured_factual_capture' if fact_capture else 'original_document', notes=notes))
        self.sids[sid] = True
        return sid

    def check(self, name, passed, **details):
        self.checks.append(dict(check=name, passed=bool(passed), **details))
        assert passed, (name, details)

    def fees_japan(self):
        ids = []
        for year in (2011, 2015, 2023):
            capture = read(RAW / f'japan_detroit_fees{year}_facts.json')
            sid = self.source(f'jpn_detroit_fees{year}', f'japan_detroit_fees{year}_facts.json',
                              capture['url'], capture['publisher'], f'Japan visa fees and fee exemptions, Detroit {year}', True,
                              '官方同期收费表的结构化事实摘录；原始字节下载403，明确不声称此JSON为原PDF/HTML。')
            ids.append(sid)
            self.fees.append(dict(fee_rule_id=f'hxp_jpn_waiver_snapshot{year}', destination='JPN',
                                  component='government_visa_fee', amount=0, currency='JPY', source_id=sid,
                                  effective_from=capture['effective_from'], effective_to=capture['effective_to'],
                                  fee_exempt_iso3=capture['full_fee_exempt_iso3'],
                                  conditional_exemptions=capture['conditional_exemptions'],
                                  validity_status='dated_consular_snapshot',
                                  notes='适用已记录的领馆时段；中间年份连续性在模型中单独作为假设。中国香港仅指定BNO证件，不将整区一律免收；中国澳门2015/2023快照列明。'))
        continuity = read(RAW / 'japan_fee_continuity1978_facts.json')
        sc = self.source('jpn_nominal_continuity', 'japan_fee_continuity1978_facts.json', continuity['url'],
                         continuity['publisher'], 'MOFA press conference19June2026: prior nominal fee schedule established1978', True)
        schedule = read(RAW / 'japan_old_fee_schedule_facts.json')
        ss = self.source('jpn_prior_schedule', 'japan_old_fee_schedule_facts.json', schedule['url'],
                         schedule['publisher'], 'MOFA Visa Fees: pre-July2026 nominal fees and issuance-only payment trigger', True)
        law = read(RAW / 'japan_fee_law_2017.json')
        self.check('japan_cabinet_order_revision_precedes_history', law['revision_info']['amendment_enforcement_date'] == '2007-10-01')
        sl = self.source('jpn_fee_law2007', 'japan_fee_law_2017.json',
                         'https://laws.e-gov.go.jp/api/2/law_data/327CO0000000074?asof=2017-04-01',
                         'Japan e-Gov / Cabinet', 'Consular Fee Cabinet Order, historical revision effective2007-10-01')
        self.standard_sids = [sc, ss, sl] + ids
        for typ, amount in [('single', 3000), ('multiple', 6000), ('transit', 700)]:
            self.fees.append(dict(fee_rule_id='hxp_jpn_nominal_' + typ, destination='JPN', visa_type=typ,
                                  amount=amount, currency='JPY', component='government_visa_fee', source_id=ss,
                                  source_ids=[sc, ss, sl], effective_from='1978-05-01', effective_to='2026-06-30',
                                  payment_trigger='visa_issuance', validity_status='historical_nominal_benchmark',
                                  notes='约合日元的名义基准；实际按公馆当地货币收取。1978起连续性的依据为2026外务大臣说明，旧政令历史版本为交叉证据；本模型只扩展2011–2023。'))
        self.india_sid = []
        for year in (2017, 2020, 2023):
            sid = self.source(f'jpn_ministry_fee{year}', f'japan_fee_law_ministry{year}.json',
                              f'https://laws.e-gov.go.jp/api/2/law_data/327M50000020004?asof={year}-04-01',
                              'Japan e-Gov / Ministry of Foreign Affairs', f'Consular Fee Ordinance as of{year}-04-01; India reciprocity Appendix2')
            self.india_sid.append(sid)
        ir = read(RAW / 'japan_iran_fee_change2017_facts.json')
        self.iran_sid = self.source('jpn_iran_change2017', 'japan_iran_fee_change2017_facts.json', ir['url'],
                                    ir['publisher'], 'Contemporary2017-08-01 Iranian fee revision: comparison with general fees', True,
                                    '马来西亚同期新旧表和卡塔尔同期通知互证；伊朗费用从2017-08-01等于普通费。')
        self.fees.extend([
            dict(fee_rule_id='hxp_jpn_india_reciprocal_benchmark', destination='JPN', nationality='IND',
                 amount=832, multiple_amount=832, transit_amount=76, currency='JPY', component='government_visa_fee',
                 source_id=self.india_sid[-1], source_ids=self.india_sid + ids, validity_status='historical_benchmark_with_continuity_assumption',
                 documented_from='2011-04-01', documented_to='2024-03-31',
                 notes='2023法令日元收款列832/832/76；2011/2015同期当地美元表和2017/2020法令证明低费且单/多次同价。将832/76作为历史近似中心是显式假设，使用0.8–1.2币值敏感性，未称每年真实日元实收。'),
            dict(fee_rule_id='hxp_jpn_iran_pre201708_benchmark', destination='JPN', nationality='IRN',
                 amount=5000, multiple_amount=10000, transit_amount=5000, currency='JPY',
                 component='government_visa_fee', source_id=self.iran_sid, source_ids=[ids[0], ids[1], self.india_sid[0], self.iran_sid],
                 effective_to='2017-07-31', validity_status='approximate_historical_reciprocal_benchmark',
                 notes='由2011/2015领馆相对普通费的比率与2017历史省令推得5000/10000/5000日元近似基准；2017-08-01起普通标准，2017中心按日期均匀分配。'),
        ])

    def documented_free_share(self, iso, year, conditional=False):
        start, end = date(year, 1, 1), date(year + 1, 1, 1)
        intervals = []
        for snapshot in self.snapshots:
            eligible = iso in snapshot['full_fee_exempt_iso3']
            if conditional:
                eligible = any(r['iso3'] == iso for r in snapshot['conditional_exemptions'])
            if eligible:
                a, b = max(start, date.fromisoformat(snapshot['effective_from'])), min(end, date.fromisoformat(snapshot['effective_to']) + timedelta(days=1))
                if b > a:
                    intervals.append((a, b))
        return sum((b-a).days for a, b in intervals)/(end-start).days

    def profile(self, iso, original, year, group):
        single, increment, transit = 3000., 3000., 700.
        extra_ids, flags = [], []
        local_low, local_high = .9, 1.1
        if iso == 'IND':
            single, increment, transit = 832., 0., 76.
            local_low, local_high = .8, 1.2
            extra_ids += self.india_sid
            flags.append('印度832/832/76日元为跨期近似基准，非逐年实际当地费')
        if iso == 'IRN' and year <= 2017:
            old_share = 1 if year < 2017 else (date(2017, 8, 1)-date(2017, 1, 1)).days/365
            single = 3000 + 2000*old_share
            increment = single
            transit = 700 + 4300*old_share
            extra_ids.append(self.iran_sid)
            flags.append('伊朗特别费于2017-08-01改为普通费；2017按均匀日期分配')
        center_factor, low_factor, high_factor = .9, .8*local_low, local_high
        stable_free = any(iso in x['full_fee_exempt_iso3'] for x in self.snapshots)
        if stable_free and not (iso == 'MAC' and year < 2015):
            center_factor, low_factor = 0., 0.
            high_factor = (1-self.documented_free_share(iso, year))*local_high
            flags.append('同期快照免收；未观察日期的中心延续免收，范围允许该时段普通收费')
        if iso == 'PHL' and group == 'visitor':
            center_factor, low_factor = 0., 0.
            high_factor = (1-self.documented_free_share(iso, year, True))*local_high
            flags.append('菲律宾短期≤90天免收；未观察日期的免收费连续性为假设')
        if iso == 'HKG':
            if '英国' in original or 'BNO' in original:
                center_factor, low_factor = 0., 0.
                high_factor = (1-self.documented_free_share(iso, year, True))*local_high
                flags.append('中国香港明确英国/BNO类证件按BNO免收费；源证件类别保留')
            else:
                low_factor = 0.
                flags.append('中国香港其他证件不整体套用BNO免收；BNO组合未知范围允许免收')
        if iso == 'ROU':
            center_factor, low_factor, high_factor = .5, 0., local_high
            flags.append('罗马尼亚按目的部分免收/需咨询；付费占比中心50%、范围0–100%为工作参数')
        return dict(single=single, increment=increment, transit=transit, center=center_factor,
                    low=low_factor, high=high_factor, flags=flags, source_ids=extra_ids)

    def japan(self):
        manifest = read(RAW / 'download_manifest.json')
        aggregate = {}
        destination_amounts = defaultdict(lambda: [0., 0., 0.])
        for file in manifest:
            year = file['year']
            sid = self.source(f'jpn_issued{year}', file['name'], file['url'], 'MOFA Japan / Statistics Bureau e-Stat',
                              f'{year} Japanese visa issuances by nationality/region and purpose')
            workbook = openpyxl.load_workbook(RAW / file['name'], read_only=True, data_only=True)
            sheet = next(s for s in workbook.worksheets if s.title.startswith('国籍別'))
            rows = list(sheet.iter_rows(values_only=True))
            header = {norm(value): i for row in rows[1:3] for i, value in enumerate(row) if value is not None and norm(value) not in {'詳細', '報告'}}
            # Far-right stale helper columns in2017–19 contain old totals. Find the
            # first occurrence in the main block rather than relying on dict overwrite.
            for label in ('発給数', 'うち数次', '就業', '高度専門職'):
                positions = [i for row in rows[1:3] for i, value in enumerate(row) if norm(value) == label]
                if positions:
                    header[label] = min(positions)
            qcol = header['発給数']
            origin_col = qcol - 1
            primary_end = max(i for label, i in header.items() if label == 'その他')
            header = {label: i for label, i in header.items() if i <= primary_end}
            world = next(row for row in rows[3:] if norm(row[origin_col]) == '合計')
            world_total = int(world[qcol])
            detail = []
            for rownum, row in enumerate(rows[3:], 4):
                if norm(row[origin_col]) == '合計' or not isinstance(row[qcol], (int, float)):
                    continue
                original = str(row[origin_col]).strip()
                assert norm(original) in self.aliases, (year, original)
                iso = self.aliases[norm(original)]
                if iso == 'JPN':
                    iso = 'UNK'
                detail.append((rownum, row, original, iso))
            column_checks = []
            for i in sorted(set(header.values())):
                if isinstance(world[i], (int, float)):
                    count = sum(row[i] or 0 for _, row, _, _ in detail)
                    column_checks.append((i, count, world[i]))
            mismatches = [dict(column=openpyxl.utils.get_column_letter(i+1), detail=a, world=b) for i, a, b in column_checks if a != b]
            # The official2012 student column contains a small source conflict;
            # preserve nationality cells and the separate world control verbatim.
            allowed = [{'column':'AB','detail':58716,'world':58705}] if year==2012 else []
            self.check('japan_nationality_columns_reconcile_or_preserve_known_source_conflict', mismatches == allowed,
                       year=year, checked_numeric_columns=len(column_checks),
                       mismatches=mismatches, resolution='retain original nationality details and separate original world row; no calibration')
            if mismatches:
                self.conflicts.append(dict(year=year,source_id=sid,source_locator=f"'{sheet.title}'!AB4 and nationality cells AB5 onward",
                                           metric='student_visas_issued',detail=58716,reported_world=58705,difference=11,
                                           resolution='retain original nationality cells; no invented correction or scaling; total visa count independently reconciles'))
            purpose_total = defaultdict(int)
            for rownum, row, original, iso in detail:
                get = lambda label: int(row[header[norm(label)]] or 0) if norm(label) in header else 0
                total, multiple = get('発給数'), get('うち数次')
                counts = dict(visitor=get('短期滞在'), student=get('留学')+get('就学'),
                              work=get('就業')+get('高度人材')+get('高度専門職')+get('起業')+get('ﾜｰｷﾝｸﾞﾎﾘﾃﾞｰ')+get('未来創造人材')+get('技実１イ')+get('技実１ロ'),
                              family=get('家族滞在')+get('日本人の配偶者等')+get('永住者の配偶者等'))
                counts['other'] = total-sum(counts.values())
                free, transit = get('外交')+get('公用'), get('通過')
                assert min(counts.values()) >= 0 and counts['other'] >= free+transit, (year, original, counts)
                assert 0 <= multiple <= total
                for group, count in counts.items():
                    purpose_total[group] += count
                oid = f'hxp_jpn_{year}_r{rownum}'
                cells = {label: dict(cell=f'{openpyxl.utils.get_column_letter(i+1)}{rownum}', value=row[i] or 0)
                         for label, i in header.items() if isinstance(row[i], (int, float))}
                self.obs.append(dict(observation_id=oid, source_id=sid, source_locator=f"'{sheet.title}'!{openpyxl.utils.get_column_letter(qcol+1)}{rownum}",
                                     destination='JPN', nationality=iso, nationality_original=original, year=year,
                                     metric='visas_issued', raw_metric='発給数', value=total, unit='visas',
                                     visa_type='all', visa_group='other', basis='nationality', origin_basis='nationality_region_or_document_as_published',
                                     period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
                                     calculation_type='direct_observation', multiple_entry_subset=multiple,
                                     disjoint_group_counts=counts, source_cells=cells,
                                     notes='官方国籍/地区/证件类别原行；数量列均保留源单元格。数次为子集；渡航证明书另列，不加入签证总数。中文展示：中国香港、中国澳门、中国台湾；历史解体政体、英国不明属地和其他保留未知。'))
                if not total:
                    continue
                segments = [(g, counts[g], 'ordinary') for g in GROUPS[:-1]] + [
                    ('other', counts['other']-free-transit, 'ordinary'), ('other', transit, 'transit'), ('other', free, 'free')]
                capacities = [count for _, count, _ in segments]
                selected = feasible_center(capacities, multiple)
                profiles = {g: self.profile(iso, original, year, g) for g in GROUPS}
                base, extra = [], []
                for g, count, kind in segments:
                    profile = profiles[g]
                    base.append(count*(profile['single'] if kind == 'ordinary' else profile['transit'] if kind == 'transit' else 0))
                    extra.append(profile['increment'] if kind == 'ordinary' else 0.)
                amounts = {g: sum((base[i]+extra[i]*selected[i])*profiles[g]['center'] for i, (gg, _, _) in enumerate(segments) if gg == g) for g in GROUPS}
                joint = [sum(amounts.values())]
                for endpoint, maximize in [('low', False), ('high', True)]:
                    b = sum(base[i]*profiles[g][endpoint] for i, (g, _, _) in enumerate(segments))
                    coefficients = [extra[i]*profiles[g][endpoint] for i, (g, _, _) in enumerate(segments)]
                    joint.append(b+subset_extreme(capacities, coefficients, multiple, maximize))
                assert joint[1]-1e-6 <= joint[0] <= joint[2]+1e-6
                for i, value in enumerate(joint):
                    destination_amounts[year][i] += value
                for g in GROUPS:
                    if not counts[g]:
                        continue
                    p = profiles[g]
                    central = amounts[g]
                    bounds = []
                    for endpoint, maximize in [('low', False), ('high', True)]:
                        b = sum(base[i]*p[endpoint] for i, (gg, _, _) in enumerate(segments) if gg == g)
                        coefficients = [extra[i]*p[endpoint] if gg == g else 0. for i, (gg, _, _) in enumerate(segments)]
                        bounds.append(b+subset_extreme(capacities, coefficients, multiple, maximize))
                    key = (year, iso, g)
                    if key not in aggregate:
                        aggregate[key] = dict(amount=0., lower=0., upper=0., quantity=0, source_ids=set(), observation_ids=[], components=[])
                    dest = aggregate[key]
                    for field, value in [('amount', central), ('lower', bounds[0]), ('upper', bounds[1]), ('quantity', counts[g])]:
                        dest[field] += value
                    dest['source_ids'].update([sid]+self.standard_sids+p['source_ids'])
                    dest['observation_ids'].append(oid)
                    dest['components'].append(dict(nationality_original=original, total_issued=total, multiple_issued=multiple,
                                                   group_count=counts[g], group_multiple_center=sum(selected[i] for i, (gg, _, _) in enumerate(segments) if gg == g),
                                                   nominal_fee_JPY={k: p[k] for k in ('single', 'increment', 'transit')},
                                                   effective_factor={k: p[k] for k in ('center', 'low', 'high')}, assumptions=p['flags']))
            world_id = f'hxp_jpn_{year}_world'
            self.obs.append(dict(observation_id=world_id, source_id=sid, destination='JPN', nationality='WORLD', year=year,
                                 metric='visas_issued', raw_metric='発給数 合計', value=world_total, unit='visas', visa_type='all', visa_group='other',
                                 source_locator=f"'{sheet.title}'!{openpyxl.utils.get_column_letter(qcol+1)}4", calculation_type='direct_observation',
                                 period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year'))
            self.check('japan_disjoint_purposes_match_world', sum(purpose_total.values()) == world_total,
                       year=year, world=world_total, disjoint_purposes=dict(purpose_total))
            self.coverage.append(dict(receiver='JPN', destination='JPN', year=year, visas_issued=world_total,
                                      nationality_rows=len(detail), coverage_status='modeled_historical_five_groups', source_ids=[sid]+self.standard_sids,
                                      scope='官方完整年度签发、国籍/地区/证件类别与五组互斥用途；历史名义费率及同期减免证据支持费用估算',
                                      notes='签发≠申请人数；日本未发签不收政府签证费。日元金额为名义基准，实际公馆当地币结算、减免组合与多次用途交叉未逐件观察。'+('2012留学国籍明细58716较原世界总行58705多11，采用明细并保留冲突；签证总量独立核对一致。' if year==2012 else '')))
            workbook.close()
        for (year, iso, g), row in sorted(aggregate.items()):
            assert 0 <= row['lower'] <= row['amount']+1e-5 <= row['upper']+1e-5
            self.flows.append(dict(id=f'hxp_jpn_{year}_{iso}_{g}', payer=iso, receiver='JPN', year=year,
                                   visa_group=g, visa_type='historical_japan_'+g, visa_label=LABELS[g],
                                   amount=row['amount'], lower=row['lower'], upper=row['upper'], currency='JPY',
                                   quantity=row['quantity'], quantity_basis='visas_issued',
                                   source_ids=sorted(row['source_ids']), observation_ids=row['observation_ids'],
                                   method_id=MODEL_JP, model_status='modeled_estimate', calculation_type='modeled_estimate',
                                   origin_basis='nationality' if iso != 'UNK' else 'unallocated_nationality',
                                   period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year_model', period_label=f'{year}自然年模型',
                                   notes='官方签发×当期名义/互惠费率；五组用途互斥。数次签按可行交叉分配，不重复计算。免收费快照之外的连续性、其他减免与当地币结算为显式情景；费用范围不是置信区间。中国香港、中国澳门、中国台湾名称用于展示，源证件原称另存。'+('2012留学源国籍明细较世界行多11，保留明细，未按汇总强行缩放。' if year==2012 else ''),
                                   parameters=dict(raw_passport_components=row['components'], known_diplomatic_official_fee_treatment='free',
                                                   paid_ordinary_fraction={'center': .9, 'lower': .8, 'upper': 1},
                                                   nominal_local_currency_factor={'center': 1, 'lower': .9, 'upper': 1.1},
                                                   multiple_allocation='sequential feasible midpoints; extrema solve one shared observed multiple-entry constraint',
                                                   old_technical_trainee_group='work; separate old general-purpose trainee columns added only outside employment total',
                                                   excluded=['private_agency_fee', 'residence_renewal', 'landing_tax', 'travel_document_certificates'])))
        for year, (amount, lower, upper) in sorted(destination_amounts.items()):
            self.ranges.append(dict(receiver='JPN', year=year, amount=amount, lower=lower, upper=upper, currency='JPY',
                                    range_method='共同费率/减免端点；每个国籍/证件行共享唯一数次总约束求金额极值，不相加用途边际极端值'))
        self.models.append(dict(model_id=MODEL_JP, destination='JPN', years=YEARS,
                                status='historical_issuance_tariff_working_estimate',
                                formula='disjoint official nationality/purpose issuances × historical nominal fee, reciprocal exception and documented/assumed waiver × feasible multiple-entry intersection',
                                source_ids=sorted({s for f in self.flows if f['receiver'] == 'JPN' for s in f['source_ids']}),
                                limitations=['3000/6000/700日元是历史名义基准；公馆实际当地货币费和年均市场汇率存在偏离，±10%为情景参数。',
                                             '2011/2015/2023免收费快照只证明所列时段；其余日期中心延续免收，范围允许未观察时段付普通费。时段按均匀签发处理。',
                                             '印度832/832/76跨期近似并非逐年真实收费；使用±20%币值范围，依据同期低费表和法令。',
                                             '2017伊朗费用按日历日期均匀混合；实际月内申请和签发结构未观察。',
                                             '普通收费类别另有20%到0%减免、罗马尼亚50%付费中心等参数；不是拟合值或置信区间。',
                                             '多次签与用途未交叉公开，中心选可行中点，极值保持已知多次签合计；双次未单列部分按单次基准处理。']))

    def exchange_rates(self):
        dates = {2013: '20130102', 2016: '20160104', 2019: '20190102', 2022: '20220103', 2026: '20260105'}
        selected = {}
        for release, stamp in dates.items():
            path = RAW / f'fx_{release}.html'
            soup = BeautifulSoup(path.read_text(), 'html.parser')
            header = next(row for row in soup.select('table tr') if 'COUNTRY' in row.get_text() and 'CURRENCY' in row.get_text())
            years = [int(v) for v in re.findall(r'\b(?:19|20)\d{2}\b', header.get_text(' ', strip=True))]
            row = next(row for row in soup.select('table tr') if row.find(['td', 'th']) and row.find(['td', 'th']).get_text(' ', strip=True) == 'JAPAN')
            cells = [cell.get_text(' ', strip=True) for cell in row.find_all(['td', 'th'])]
            rates = [float(v.replace(',', '')) for v in cells[2:]]
            assert len(years) == len(rates)
            sid = self.source(f'fed_g5a_{stamp}', path.name, f'https://www.federalreserve.gov/releases/g5a/{stamp}/',
                              'Board of Governors of the Federal Reserve System', f'G.5A annual exchange rates, release {stamp}')
            for year, rate in zip(years, rates):
                if year in YEARS:
                    selected[year] = dict(fx_id=f'hxp_fed_{year}_JPY', year=year, currency='JPY', raw_rate=rate,
                                          raw_direction='currency_per_USD', usd_per_unit=1/rate, source_id=sid,
                                          source_locator=f'annual table; JAPAN YEN; {year}',
                                          method='Federal Reserve New York daily noon buying rates annual average; latest archived precision per year')
        self.check('JPY_fx_all_historical_years', sorted(selected) == YEARS)
        self.fx.extend(selected[year] for year in YEARS)

    def korea(self):
        sn = self.source('kr_nabo2026', 'data/raw/spatial_extension/kr_nabo2026.pdf',
                         'https://nabo.go.kr/board/file/bulkDown.do?bid=19&idx=9183',
                         'Korea National Assembly Budget Office / Ministry of Foreign Affairs',
                         'Public Finance Republic of Korea2026, actual overseas-mission issuances2020–2025')
        sf = self.source('kr_fee_law2022', 'korea_fee2022.pdf',
                         'https://www.law.go.kr/LSW/lsPdfPrint.do?ancYnChk=0&bylChaChk=N&efGubun=Y&efYd=20220504&joAllCheck=Y&joEfOutPutYn=on&lsiSeq=242093&mokChaChk=N',
                         'Korea Ministry of Government Legislation / Ministry of Justice',
                         'Immigration Act Enforcement Rule as of2022-05-04, Article71 fees, Article74 waivers')
        se = self.source('kr_fee_change2014', 'korea_fee2014.html',
                         'https://www.mofa.go.kr/us-seattle-en/brd/m_4809/view.do?seq=703570',
                         'Consulate-General Republic of Korea in Seattle / MOFA', 'Contemporary31December2013 notice: standard fee increase effective1January2014')
        text = '\n'.join(p.extract_text() for p in PdfReader(RAW/'korea_fee2022.pdf').pages)
        article = text[text.index('제71조(사증'):text.index('제72조(각종')]
        self.check('korean_historical_fees_verified', all(v in article for v in ('40불', '60불', '70불', '90불', '2013. 12. 23.')))
        source_page = PdfReader(ROOT/'data/raw/spatial_extension/kr_nabo2026.pdf').pages[631].extract_text()
        quantities = {2020:383357, 2021:309235, 2022:676772, 2023:1869477}
        self.check('korean_2020_2023_actual_issued_verified', all(f'{q:,}' in source_page for q in quantities.values()))
        for typ, fee in [('single_up_to90days',40), ('single_over90days',60), ('double',70), ('multiple',90)]:
            self.fees.append(dict(fee_rule_id='hxp_kr_'+typ, destination='KOR', visa_type=typ,
                                  amount=fee, currency='USD', component='government_visa_application_fee',
                                  source_id=sf, source_ids=[se,sf], source_locator='2022Rule Article71(1), PDFpp42–43; official2013notice fee table',
                                  effective_from='2014-01-01', documented_through='2022-05-04',
                                  validity_status='historical_dated_rule_with_2023_continuity_assumption',
                                  notes='2013同期通知规定2014-01-01起40/60/70/90美元，2022历史法令再次确认且费用条款注明2013最后修订。2023连续性为显式工作假设；国籍互惠、减免、实际类别和拒签付款未知。'))
        for year, q in quantities.items():
            oid = f'hxp_kr_{year}_consular_issued'
            self.obs.append(dict(observation_id=oid, source_id=sn, source_locator='PDFp632 / printedp614; 영사서비스 주요 통계(2020~2025년), 재외공관 사증발급',
                                 destination='KOR', nationality='UNK', year=year, metric='visas_issued_overseas_missions',
                                 raw_metric='재외공관 사증발급', value=q, unit='visas', visa_type='all', visa_group='other',
                                 category_detail_status='unclassified', calculation_type='direct_observation',
                                 period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
                                 notes='驻外公馆真实签发；不是入境或法务部认定书，付款事件与国籍未公开。'))
            amount, lower, upper = q*60*.8*1.05, q*40*.5, q*90*1.3
            parameters = dict(standard_fee_mix_USD={'center':60,'lower':40,'upper':90},
                              chargeable_share={'center':.8,'lower':.5,'upper':1},
                              paid_application_events_per_issued={'center':1.05,'lower':1,'upper':1.3},
                              parameters_are_unfitted_working_scenarios=True, nationality_allocation='none',
                              historical_fee_continuity_2023_assumed=year==2023,
                              range_method='官方签发×40–90美元费率组合×50–100%收费份额×1–1.3付款/签发；共同端点情景，非置信区间')
            self.flows.append(dict(id=f'hxp_kr_{year}_unclassified',payer='UNK',receiver='KOR',year=year,
                                   visa_group='other',visa_type='historical_consular_unclassified',visa_label='类别未细分',category_detail_status='unclassified',
                                   amount=amount,lower=lower,upper=upper,currency='USD',quantity=q,
                                   quantity_basis='observed_consular_visa_issuance_not_paid_applications',
                                   source_ids=[sn,sf,se],observation_ids=[oid],method_id=MODEL_KR,
                                   model_status='modeled_estimate',calculation_type='conditional_scenario',origin_basis='unallocated_nationality',
                                   period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year_model',period_label=f'{year}自然年模型',
                                   notes='韩国历史签证费用粗估：真实驻外签发×同期40/60/70/90美元标准组合；中心每签发60美元基准、80%收费、1.05付款/签发。国籍和用途不分配，减免及拒签付款以明确范围表达。不是官方收入实收。',parameters=parameters))
            self.ranges.append(dict(receiver='KOR',year=year,amount=amount,lower=lower,upper=upper,currency='USD',range_method=parameters['range_method']))
            self.coverage.append(dict(receiver='KOR',destination='KOR',year=year,visas_issued=q,
                                      coverage_status='historical_fee_scenario_unallocated',source_ids=[sn,sf,se],
                                      scope='官方年度驻外签发完整总量；国籍和用途未知，收入为标准费率与显式参数情景',
                                      notes='签发不是申请人数；包含拒签付款的付费事件未直接观察。与2024/25预算锚模型分开保留方法。'))
        self.models.append(dict(model_id=MODEL_KR,destination='KOR',years=sorted(quantities),status='historical_conditional_fee_scenario',
                                source_ids=[sn,sf,se],formula='official consular issued × standard fee mix × chargeable fraction × payment-events/issued',
                                limitations=['60美元组合、80%收费、1.05付款/签发均为公开的工作中心，不是调查或回归结果。',
                                             '40–90美元费率、50–100%收费及1–1.3付款/签发构成情景范围；互惠费率可能在范围外。',
                                             '2023费率连续性依据2022法令与2014生效标准作假设；不分配给任何付款国或用途。',
                                             'K-ETA、私人签证中心收费、居留续签和国内许可排除；不是财政决算实收。']))

    def validate(self):
        ids = [r['id'] for r in self.flows]
        sids = {r['source_id'] for r in self.sources}
        oids = {r['observation_id'] for r in self.obs}
        self.check('unique_flow_ids', len(ids)==len(set(ids)), flows=len(ids))
        self.check('unique_source_ids',len(sids)==len(self.sources),sources=len(sids))
        self.check('unique_observation_ids',len(oids)==len(self.obs),observations=len(oids))
        self.check('all_money_bounds_valid',all(0<=r['lower']<=r['amount']+1e-4<=r['upper']+1e-4 for r in self.flows))
        self.check('all_flow_sources_resolve',all(set(r['source_ids'])<=sids for r in self.flows))
        self.check('all_observation_sources_resolve',all(r['source_id'] in sids for r in self.obs))
        self.check('all_flow_observations_resolve',all(set(r['observation_ids'])<=oids for r in self.flows))
        for year in YEARS:
            rows=[r for r in self.flows if r['receiver']=='JPN' and r['year']==year]
            world=next(r['value'] for r in self.obs if r['observation_id']==f'hxp_jpn_{year}_world')
            self.check('japan_all_flow_quantities_counted_once',sum(r['quantity'] for r in rows)==world,year=year)
            total=next(r for r in self.ranges if r['receiver']=='JPN' and r['year']==year)
            self.check('japan_joint_range_center_equals_edges',abs(sum(r['amount'] for r in rows)-total['amount'])<.01,year=year)
        self.check('no_existing_receiver_year_overlap',not any(r['receiver']=='JPN' and r['year']>=2024 or r['receiver']=='KOR' and r['year']>=2024 for r in self.flows))

    def write(self):
        for name,value in [('sources',self.sources),('observations',self.obs),('fee_rules',self.fees),('fx',self.fx),('coverage',self.coverage),('checks',self.checks),('source_conflicts',self.conflicts)]:
            dump(OUT/(name+'.json'),value)
        dump(EST,dict(flows=self.flows,models=self.models,destination_ranges=self.ranges))
        (OUT/'README.md').write_text('''# 历史扩展：日本2011–2023、韩国2020–2023

重建：`.research-venv/bin/python scripts/research_history_expansion.py`。所有计算离线读取归档原件/事实摘录；`checks.json`记录源表各主列与世界总数、互斥用途、唯一数次约束和引用完整性。

日本13份e-Stat官方原始xlsx按各年真实表头解析。五组用途互斥；就业汇总之外的高度人才、创业、打工度假、未来人才及旧制技能实习列归工作。数次签是总量的子集，不再加一次。源列中渡航证明书不在签证总量内；2017–2019右侧旧版辅助汇总完全排除。每个原行的源单元格和原称保存在观察表。中国香港、中国澳门、中国台湾用于中文呈现；旧政体和不明英国属地保留未知，不强分现代国籍。

2012原件的留学国籍明细合计58716，原世界总行58705，相差11。`source_conflicts.json`保存原值、位置和处理方式；模型保留国籍明细，不对其缩放。该年签证总量1986539仍与国籍明细及五组互斥总量独立核对相等；其余12年的主数字列全部逐列核对相等。

名义费率连续性来自2026日本外务大臣关于1978旧标准的官方说明，以及2007生效的政令历史版本。2011/2015/2023同期领馆表支持互惠与免收费快照。快照间的连续性、印度832/832/76近似、当地币偏离及其他减免均在参数和范围里显式记录。2017-08-01伊朗从特别费改普通费有两个同期领馆通知互证。日本未发签不收政府签证费；不以拒签率制造额外付款。

日本目的×多次签未交叉公开。中心是保持唯一多次总数的可行中点；每条用途的边际范围和收款国联合范围均通过容量约束求极值。收款国范围不相加彼此不可同时实现的用途极端值。日元换美元使用Fed G.5A相应年份年均率，只新增2011–2023JPY。

韩国2020–2023使用NABO官方真实驻外签发和2014生效、2022法令再次确认的40/60/70/90美元标准。签发不等于付费申请；粗估用明确的费率组合、收费份额及付款/签发参数。未知国籍始终UNK，未知用途始终other/unclassified；不把总量包装为访客。2023费率连续性为说明过的假设。与现有2024/25预算锚方法不同，未称实收或同口径增长。

范围是可复现的参数情景，不是置信区间。签发件数也不是独立申请人数。JSON结构化事实摘录明确标识；未将下载被403拦截的官方页面冒充已归档原始PDF/HTML。美国2016–2018旧预算检查未找到足以独立标识的MRV实收栏，未按表格位置猜值或填入总账。
''')
        print(json.dumps(dict(flows=len(self.flows), observations=len(self.obs),sources=len(self.sources),fee_rules=len(self.fees),fx=len(self.fx),coverage=len(self.coverage),checks=len(self.checks),all_checks_passed=all(r['passed'] for r in self.checks)),ensure_ascii=False))


def main():
    package=Package()
    package.fees_japan()
    package.japan()
    package.exchange_rates()
    package.korea()
    package.validate()
    package.write()


if __name__=='__main__':
    main()
