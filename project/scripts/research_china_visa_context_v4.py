#!/usr/bin/env python3
"""Rebuild China overseas visa-issuance context from frozen official pages.

Counts, approximate counts, strict floors, issuing-post locations and applicant
nationalities remain distinct. No amount or fee-ledger records are generated.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/china_visa_context_v4'
OUT = ROOT / 'data/research/china_visa_context_v4'
ASOF = '2026-11-17'

SOURCES = [
    ('cvc_india_2023_kolkata', 'india_2023_kolkata.html', '2024-04-08',
     '中国驻加尔各答总领事馆',
     'Remarks of Qin Yong at the launch of the Mastermind Entrepreneurs Forum',
     '6669aec825c85abab9bfc7ce389b50b473055870df81be75d5a2d2f84471d9f6',
     '中国驻印度使领馆全年合计；正文明确印度公民，不是加尔各答单馆。'),
    ('cvc_india_2024_mcci', 'india_2024_mcci.html', '2024-11-04',
     '中国驻印度大使馆', 'Speech by Ambassador Xu Feihong at the MCCI Event',
     '51017eb31d8a1e89c83593dbe37486ef6229e7fa4967cce10f4bbbd3df430844',
     '页面显示2024-11-04，URL路径含20241218；保留页面日期。统计截止日未给，不把文稿日期当作精确截止日。正文未在该句限定国籍。'),
    ('cvc_india_2025_apr21', 'india_2025_apr21.html', '2025-04-21',
     '中国驻印度大使馆', 'Ambassador Xu Feihong written interview to the Times of India',
     '0a0f82eebeffcd68df49fe8631e779f9222e0c7a66c1b4b812a62be6ad7a8f6a',
     '正文称采访发表于4月19日；8.5万为今年以来，未给精确统计截止日，也未在该句限定国籍。去年的28万指2024年。'),
    ('cvc_india_2025_q1_mfa', 'india_2025_q1_mfa.html', '2025-04-02',
     '中国外交部／中国驻印度大使馆', 'Remarks at the 75th anniversary of China-India diplomatic relations',
     '675385538ab3d21059553a651107095f93122f1742d3950cf1932549d446d617',
     '原页PubDate为2025-04-02，URL路径含20250407；原文明确第一季度和印度公民。'),
    ('cvc_india_2025_sep9_mfa', 'india_2025_sep9_mfa.html', '2025-09-09',
     '中国外交部／中国驻印度大使馆', 'Remarks at the seminar on the 80th anniversary of victory',
     '3776240f8f4f7f0b7375e9f475058f571ccc3308d749fcdf70716d34f5742cbf',
     '原页PubDate为2025-09-09，URL路径含20250912；今年以来超过24万，未给精确统计截止日。'),
    ('cvc_india_2025_sep22_mfa', 'india_2025_sep22_mfa.html', '2025-09-24',
     '中国外交部／中国驻印度大使馆', 'Remarks at the reception celebrating the 76th anniversary of the PRC',
     '4887d2e57e76d1862a491f041dace7c9048222e091aceea23abc05a25e934afd',
     '原页PubDate为2025-09-24，URL路径含20250928；原文明确截至9月22日及印度公民。'),
    ('cvc_saudi_2024_riyadh_mfa', 'saudi_2024_riyadh_mfa.html', '2024-08-26',
     '中国外交部／中国驻沙特阿拉伯大使馆', '驻沙特大使常华在利雅得中国签证申请服务中心开业仪式上的致辞',
     '9f497924b84503dc03ff3da7b2fe2064380fe6559d2e8a5e123baf456641b460',
     '使馆审发量不等于沙特国籍量；确切统计截止日未披露。'),
    ('cvc_saudi_2024_jeddah_mfa', 'saudi_2024_jeddah_mfa.html', '2024-08-28',
     '中国外交部／中国驻吉达总领事馆', '驻吉达代总领事张维康在吉达中国签证申请服务中心开业仪式上的致辞',
     'c53fa9b0435809cdc75401f3b727641485d1bb5fe0346a45e11bc16357752ca3',
     '吉达单馆；包括沙特公民及在沙合法居民，不能推断申请人国籍；确切统计截止日未披露。'),
    ('cvc_jordan_2024_reception', 'jordan_2024_reception.html', '2024-09-26',
     '中国驻约旦大使馆', 'Remarks at the reception celebrating the 75th anniversary of the PRC',
     'd823c8dee154598e39e6d0849c5c066c35a90e309f22577c6a988bdd1e31b0ca',
     '原文first nine months但文章发表于9月26日；不能当作完整1至9月已结束统计。使馆地点不等于国籍。'),
]


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        elif tag in ('p', 'div', 'br', 'td', 'tr', 'h1', 'h2', 'li') and not self.skip:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        elif tag in ('p', 'div', 'td', 'tr', 'h1', 'h2', 'li') and not self.skip:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def lines(self):
        return [re.sub(r'\s+', ' ', unescape(s)).strip()
                for s in ''.join(self.parts).splitlines() if s.strip()]


def write(name, rows):
    (OUT / name).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with (OUT / name.replace('.json', '.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, keys)
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in r.items()} for r in rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    urls = json.loads((RAW / 'acquisition_urls.json').read_text())
    sources, texts, checks, observations = [], {}, [], []
    for sid, filename, published, publisher, title, expected_hash, notes in SOURCES:
        path = RAW / filename
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == expected_hash, (sid, digest, expected_hash)
        assert len(data) > 1000 and b'<html' in data.lower(), sid
        parser = PageText()
        parser.feed(data.decode('utf-8'))
        lines = parser.lines()
        texts[sid] = lines
        (OUT / f'{sid}_text.txt').write_text('\n'.join(lines) + '\n')
        sources.append(dict(source_id=sid, url=urls[filename], local_path=str(path.relative_to(ROOT)),
                            publisher=publisher, title=title, publication_date=published,
                            retrieved_at=ASOF, source_quality='official_original',
                            archive_kind='original_document', sha256=digest, bytes=len(data), notes=notes))
        checks.append(dict(check=f'{sid}_frozen_original', passed=True, sha256=digest, bytes=len(data)))

    # A new context view reuses the existing registered source and original;
    # the source itself must not be duplicated in the shared source registry.
    existing_path = ROOT / 'data/raw/china/india-visa-issuance-2024.html'
    existing_hash = hashlib.sha256(existing_path.read_bytes()).hexdigest()
    assert existing_hash == 'fb2faaf702324c0c53722b411665f14cba2d7c2bb4768e768000d43d2efb2d4c'
    parser = PageText()
    parser.feed(existing_path.read_text())
    texts['cn_india_2024'] = parser.lines()
    (OUT / 'cn_india_2024_reused_text.txt').write_text('\n'.join(texts['cn_india_2024']) + '\n')
    write('external_source_references.json', [dict(source_id='cn_india_2024',
          local_path=str(existing_path.relative_to(ROOT)), sha256=existing_hash,
          registered_in='data/research/china_seasia/sources.json',
          source_observation_id='cn_indian_2024_issued',
          reason='Reuse existing official original; do not register a second copy of this source.')])

    def locate(sid, needle):
        hits = [(i, line) for i, line in enumerate(texts[sid], 1) if needle in line]
        assert hits, (sid, needle)
        lineno, line = hits[0]
        checks.append(dict(check=f'{sid}_quote_{len(checks)}', passed=True, needle=needle, text_line=lineno))
        return lineno, line

    def add(oid, sid, needle, value, year, *, nationality=False, location='IND',
            end=None, status='reported_count', metric='overseas_visas_issued',
            unit='visas', series='china_post_issuance', label='中国大陆驻外机构签发',
            raw_period='this year', notes='', **extra):
        line_no, line = locate(sid, needle)
        source = next((s for s in sources if s['source_id'] == sid), None)
        # For unspecified cutoff dates, the document date is an upper bound on
        # when a figure was available, never a fabricated measurement endpoint.
        observations.append(dict(
            observation_id=oid, source_id=sid, source_ids=[sid],
            source_locator=f'HTML normalized text line {line_no}; quote: {needle}',
            source_text_line=line_no, source_quote=needle, raw_line=line,
            destination='CHN', destination_display_name='中国大陆', reporting_country='CHN',
            origin='IND' if nationality else 'UNK',
            origin_display_name='印度' if nationality else f'国籍未披露（在{dict(IND="印度",SAU="沙特阿拉伯",JOR="约旦")[location]}办理）',
            origin_label='印度公民' if nationality else f'国籍未披露（{location}办理机构）',
            origin_basis='nationality' if nationality else 'consular_post_location',
            issuing_post_country=location, partner_country='IND' if nationality else None,
            metric=metric, raw_metric='visas issued' if unit == 'visas' else metric,
            value=value, raw_value=needle, unit=unit, year=year,
            period_start=f'{year}-01-01', period_end=end,
            period_type='calendar_year' if end == f'{year}-12-31' else
                        'year_to_date' if end else 'year_to_date_unspecified_cutoff',
            raw_period=raw_period, period_end_precision='exact' if end else 'not_published',
            published_at=source['publication_date'] if source else '2025-04-01',
            observation_available_not_later_than=source['publication_date'] if source else '2025-04-01',
            calculation_type='published_official_count' if unit == 'visas' else 'published_official_rate',
            observation_domain='visa_activity' if unit == 'visas' else 'rate',
            context_only=True, eligible_money_ledger=False,
            series_id=series, series_label=label,
            aggregation_role='bilateral_nationality_component' if nationality else 'issuing_post_statistic',
            scope='chinese_missions_in_india_indian_citizens' if nationality else 'issuing_post_location_not_nationality',
            source_status=status, context_selection_default=end is not None,
            notes=notes + ' 签发份数不等于独立申请人数、入境人次、付费申请或财政收入；不直接进入费用总账。',
            **extra))
        if status == 'strict_lower_floor':
            observations[-1].update(lower=value, upper=None, bound_type='strict_lower_floor',
                                    lower_inclusive=False, value_semantics='reported_floor_not_point_estimate')
        elif status == 'approximate_count':
            observations[-1].update(value_semantics='published_approximation_not_exact_count')

    add('cvc_cn_ind_2023_annual', 'cvc_india_2023_kolkata',
        'issued approximately 180,000 visas to Indian citizens', 180000, 2023,
        nationality=True, end='2023-12-31', status='approximate_count',
        series='china_issuance_indian_citizens_annual', label='中国大陆向印度公民全年签发',
        raw_period='In 2023', notes='保留approximately，不能当作超过18万或精确18万。')
    add('cvc_cn_ind_2024_annual_context', 'cn_india_2024',
        'issued 280,000 visas to Indian citizens in 2024', 280000, 2024,
        nationality=True, end='2024-12-31',
        series='china_issuance_indian_citizens_annual', label='中国大陆向印度公民全年签发',
        raw_period='in 2024', reused_source_observation_ids=['cn_indian_2024_issued'],
        notes='复用既有来源及观察的上下文视图，不是新增签发量，不与原观察相加。')
    add('cvc_cn_ind_2025_q1', 'cvc_india_2025_q1_mfa',
        'issued over 70,000 visas to Indian citizens', 70000, 2025,
        nationality=True, end='2025-03-31', status='strict_lower_floor',
        series='china_issuance_indian_citizens_ytd_floors', label='中国大陆向印度公民累计签发（下限）',
        raw_period='In the first quarter of this year', notes='原文为over，图中数值表示下限。')
    add('cvc_cn_ind_2025_q1_yoy', 'cvc_india_2025_q1_mfa',
        'year-on-year increase of approximately 15%', 15, 2025,
        nationality=True, end='2025-03-31', status='approximate_rate',
        metric='overseas_visas_issued_yoy_percent', unit='percent',
        series='china_issuance_indian_citizens_yoy', label='中国大陆向印度公民签发同比增幅',
        raw_period='In the first quarter of this year',
        notes='保留约15%的报道精度；不倒算未公布的2024第一季度精确签发量。')
    add('cvc_cn_ind_2025_ytd_0922', 'cvc_india_2025_sep22_mfa',
        'issued over 265,000 visas to Indian citizens', 265000, 2025,
        nationality=True, end='2025-09-22', status='strict_lower_floor',
        series='china_issuance_indian_citizens_ytd_floors', label='中国大陆向印度公民累计签发（下限）',
        raw_period='By September 22nd',
        notes='2025年截至9月22日超过26.5万；这是全年数量的保守下限，不能替代全年实绩或中心估算。')
    add('cvc_cn_ind_2025_ytd_sep_unspecified', 'cvc_india_2025_sep9_mfa',
        'issued over 240,000 visas to Indian citizens', 240000, 2025,
        nationality=True, status='strict_lower_floor',
        series='china_issuance_indian_citizens_ytd_unlocated', label='中国大陆向印度公民累计签发（截止日未披露）',
        raw_period='Since the beginning of this year',
        notes='9月9日文稿中的今年以来；精确累计截止日未披露，暂不绘制精确日期趋势。')
    add('cvc_cn_indpost_2025_ytd_apr_unspecified', 'cvc_india_2025_apr21',
        'over 85,000 visas so far this year', 85000, 2025,
        status='strict_lower_floor', series='china_missions_india_ytd_unlocated',
        label='中国大陆驻印度机构累计签发（国籍及截止日未限定）',
        raw_period='so far this year',
        notes='本句只有驻印度机构范围；不把办理地点替代申请人国籍，也不把4月21日或媒体转引的4月9日作为统计截止日。')
    add('cvc_cn_indpost_2024_ytd_mcci', 'cvc_india_2024_mcci',
        'issued over two hundred and forty thousand visas', 240000, 2024,
        status='strict_lower_floor', series='china_missions_india_ytd_unlocated',
        label='中国大陆驻印度机构累计签发（国籍及截止日未限定）',
        raw_period='This year', notes='保留24万以上的年内快照；不作全年统计，不与全年28万相加。')
    add('cvc_cn_indpost_2024_business_share', 'cvc_india_2024_mcci',
        '80% of which were business visas', 80, 2024,
        metric='business_share_of_visas_issued', unit='percent',
        series='china_missions_india_business_share', label='中国大陆驻印度机构商务签占比（同期签发）',
        raw_period='This year', notes='商务签约占同期驻印机构签发量80%；不是全年、印度公民或收费类型的精确分布。')
    add('cvc_cn_saupost_2024_riyadh_ytd', 'cvc_saudi_2024_riyadh_mfa',
        '今年以来，中国使馆签证审发量已超2万份', 20000, 2024,
        location='SAU', status='strict_lower_floor',
        series='china_mission_riyadh_ytd_unlocated', label='中国大陆驻沙特使馆签证审发（下限）',
        metric='overseas_visas_reviewed_and_issued', raw_period='今年以来',
        notes='原词为审发量；不另行等同于申请递交量。单使馆办理量，不等于沙特公民总量。')
    add('cvc_cn_saupost_2024_jeddah_ytd', 'cvc_saudi_2024_jeddah_mfa',
        '2024年至今，驻吉达总领馆已签发7000逾份赴华签证', 7000, 2024,
        location='SAU', status='strict_lower_floor',
        series='china_mission_jeddah_ytd_unlocated', label='中国大陆驻吉达总领馆累计签发（下限）',
        raw_period='2024年至今', notes='原文7000逾份按超过7000记录；不与利雅得不同截止期的快照相加。')
    add('cvc_cn_saupost_2024_jeddah_yoy', 'cvc_saudi_2024_jeddah_mfa',
        '较去年同期增长近40％', 40, 2024,
        location='SAU', status='approximate_rate',
        metric='overseas_visas_issued_yoy_percent', unit='percent',
        series='china_mission_jeddah_yoy_unlocated', label='中国大陆驻吉达总领馆签发同比增幅（近似）',
        raw_period='2024年至今', notes='近40%为近似增幅；不倒算未公布的基期签发量。')
    add('cvc_cn_jorpost_2024_partial', 'cvc_jordan_2024_reception',
        'issued nearly ten thousand visas in the first nine months', 10000, 2024,
        location='JOR', status='approximate_count',
        series='china_mission_jordan_partial', label='中国大陆驻约旦使馆签发（近似年内快照）',
        raw_period='in the first nine months',
        quality_issue='Article date 2024-09-26 precedes the end of the reported first-nine-month period; precise cutoff unresolved.',
        notes='near并非精确1万；9月26日文章提及前9个月，精确截止日待核，不冒充已结束的前三季度。')

    # Deterministic checks cover evidence semantics, not only schema shape.
    ids = [r['observation_id'] for r in observations]
    assert len(ids) == len(set(ids))
    registered = {s['source_id'] for s in sources} | {'cn_india_2024'}
    assert all(r['source_id'] in registered for r in observations)
    assert all(r['context_only'] and not r['eligible_money_ledger'] for r in observations)
    assert all(r['origin'] == 'UNK' for r in observations if r['origin_basis'] == 'consular_post_location')
    floors = [r for r in observations if r['source_status'] == 'strict_lower_floor']
    assert all(r['value'] == r['lower'] and r['upper'] is None and not r['lower_inclusive'] for r in floors)
    explicit = [r for r in observations if r['period_end']]
    assert len(explicit) == 5
    latest = next(r for r in observations if r['observation_id'] == 'cvc_cn_ind_2025_ytd_0922')
    assert latest['period_end'] == '2025-09-22' and latest['origin_basis'] == 'nationality'
    assert latest['value'] == 265000 and latest['value'] > 280000 * .7
    checks += [
        dict(check='unique_observation_ids', passed=True, observations=len(observations)),
        dict(check='references_resolve_in_package_or_existing_registry', passed=True),
        dict(check='context_only_no_money_records', passed=True),
        dict(check='post_location_not_relabelled_nationality', passed=True),
        dict(check='strict_floors_not_exact_point_estimates', passed=True, floors=len(floors)),
        dict(check='only_five_precise_period_observations', passed=True, observations=len(explicit)),
        dict(check='india_2025_floor_invalidates_old_196000_quantity_lower', passed=True,
             old_quantity_lower=196000, supported_conservative_lower=265000,
             strict_source_wording='over', not_full_year_actual=True),
    ]
    recommendation = dict(
        recommendation_id='cvc_china_india_2025_quantity_floor', destination='CHN', origin='IND', year=2025,
        source_id=latest['source_id'], observation_id=latest['observation_id'],
        conservative_numeric_lower=265000, actual_bound_is_strict=True, reported_floor=265000,
        observed_period_start=latest['period_start'], observed_period_end=latest['period_end'],
        proposed_core_action='Raise the 2025 annual issuance quantity lower to at least 265000; retain explicit annual estimation status.',
        central_annual_quantity=None, upper_annual_quantity=None,
        notes='This is an issuance floor, not a paid-application or revenue floor. Apply separate paid-share and fee-mix parameters; no new flow is generated here.')
    coverage = dict(package='china_visa_context_v4', as_of=ASOF,
        destinations=['CHN'], issuing_post_countries=['IND', 'SAU', 'JOR'],
        observed_nationalities=['IND'], years=[2023, 2024, 2025],
        new_sources=len(sources), reused_sources=1, observations=len(observations),
        precise_period_observations=len(explicit), unspecified_cutoff_observations=len(observations)-len(explicit),
        observations_by_domain=dict(Counter(r['observation_domain'] for r in observations)),
        full_year_india_observations=2, monetary_flows_generated=0,
        gaps=['中国大陆境外签证签发总量及全球国籍矩阵仍未找到可复核公开表。',
              '印度公民2025全年签发实绩未找到；截至9月22日超过26.5万仅为下限。',
              '费用减免、签证类型与收费签发占比未由这些总量资料识别。',
              '沙特、约旦及部分印度资料只有办理机构与未明确截止日的年内快照，未转成国籍边或精确日期点。'])
    write('sources.json', sources)
    write('observations.json', observations)
    write('model_recommendations.json', [recommendation])
    write('coverage_summary.json', coverage)
    write('coverage.json', [dict(code='CHN', year=year, visa_group='unclassified',
          status='quantity_only', quantity_context_known=True,
          source_ids=sorted({r['source_id'] for r in observations if r['year']==year}),
          notes='境外签发活动背景；年内累计下限及未明确截止日另列，不是付费人数或财政收入。')
          for year in sorted({r['year'] for r in observations})])
    write('checks.json', checks)
    write('report.json', dict(**coverage, checks=len(checks), passed=all(c['passed'] for c in checks),
        recommendation=recommendation,
        integration=dict(data_package='china_visa_context_v4',
                         command='python3 scripts/research_china_visa_context_v4.py',
                         existing_source_dependency='china_seasia:cn_india_2024',
                         exact_period_context_observation_ids=[r['observation_id'] for r in explicit],
                         uncertain_cutoffs='period_end=null; current country_context.py deliberately skips these rows.',
                         floor_display='Prefix > for strict_lower_floor or label value explicitly as a lower floor.')))
    (OUT / 'README.md').write_text('''# 中国大陆境外签证签发证据补充 v4

离线重建：`python3 scripts/research_china_visa_context_v4.py`。

9 个新官方原页、1 个复用来源、13 条签发量或占比观察。印度公民2023全年约18万、2024全年28万；2025第一季度超过7万，截至9月22日超过26.5万。第一季度同比约15%。年度、年内累计与占比均分别保存。

## 接入

- 数据包名：`china_visa_context_v4`。注册到 `DATA_PACKAGES` 与相应 `EXTENSION_PACKAGES` 后复用 `sources.json`、`observations.json`。
- `cn_india_2024` 已注册在 `china_seasia`，本包只引用，不重复注册来源。`cvc_cn_ind_2024_annual_context` 是原观察 `cn_indian_2024_issued` 的上下文视图。
- 5 条观察具有精确起止日期；8 条未披露确切累计截止日，保留 `period_end=null`。现有国家上下文构建器会跳过这8条，原始证据仍可检索。
- `strict_lower_floor` 的 `value` 是报道阈值，必须显示“超过”或“下限”，不能画成精确实绩。

## 模型建议

`cvc_cn_ind_2025_ytd_0922` / `cvc_india_2025_sep22_mfa` 明确印度国籍、2025年1月1日至9月22日累计超过265000。原年度数量下界196000已低于官方年内下限，保守数值下界可提高到265000。不能据此把265000设为全年实际或中心；费用减免和类型结构仍须另行建模。详见 `model_recommendations.json`。

## 口径

这些是境外签证签发或使领馆办理数据，均为 `context_only=true`、`eligible_money_ledger=false`。不是入境人次、境内停居留证件、独立人数、付费申请人数或财政收入。不生成任何金额边。办理机构设在印度、沙特或约旦，不能据此将所有申请人标为该国国籍。

原页、SHA-256、原文摘录和文本行定位齐备。网页元数据日期与URL路径日期不一致时，使用原页显示日期并保留差异。约旦“前九个月”与9月26日文稿日期的未完期问题保留为 `quality_issue`。

中国相关显示名统一为中国大陆、中国香港、中国澳门、中国台湾；原始来源文本保持原样。
''')
    print(json.dumps(dict(package='china_visa_context_v4', sources=len(sources),
                          observations=len(observations), precise_period_observations=len(explicit),
                          checks=len(checks), passed=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
