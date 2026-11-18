#!/usr/bin/env python3
"""Rebuild the focused Korea/Vietnam evidence refinement package offline.

This package adds dated Vietnamese tariff evidence without adding monetary flows
or duplicating the issuance observations in spatial_extension. Korea's budget
anchor remains a budget scenario; arrivals are never substituted for paid visas.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/research/evidence_refinement/korea_vietnam'
RAW = ROOT / 'data/raw/evidence_refinement/korea_vietnam'
ASOF = '2026-11-16'
VN_ID = 'refine_vn_consolidated12_2024'
VN_FILE = RAW / 'vn_consolidated12_2024.pdf'
VN_SHA = '631286d020dbab85fd067f0cf30e0d67443e22c79d8eed9b5cdb5fc55ca46820'


def compact(text):
    return re.sub(r'\s+', ' ', text).strip().replace('k ể', 'kể').replace('n ăm', 'năm')


def dump(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, condition, **evidence):
        checks.append(dict(check=name, passed=bool(condition), **evidence))
        assert condition, name

    raw = VN_FILE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    check('archived_consolidated_regulation_sha256', sha == VN_SHA, sha256=sha)
    reader = PdfReader(VN_FILE)
    pages = [compact(p.extract_text()) for p in reader.pages]
    check('consolidated_document_has_13_pages', len(pages) == 13, page_count=len(pages))
    check('consolidation_number_and_date', '12/VBHN-BTC' in pages[8] and
          'ngày 04 tháng 4 năm 2024' in pages[8], locator='PDF p9 / gazette p55')
    check('single_entry_tariff_25_usd',
          'Cấp thị thực có giá trị một lần 25 USD/chiếc' in pages[10],
          locator='PDF p11 / gazette p57, section II row1')
    check('multiple_entry_upto90days_tariff_50_usd',
          'Loại có giá trị không quá 90 ngày 50 USD/chiếc' in pages[10],
          locator='PDF p11 / gazette p57, section II row2a')
    check('base_regulation_effective_2021_05_22',
          'kể từ ngày 22 tháng 5 năm 2021' in pages[7],
          locator='PDF p8 / gazette p54, Article8(1)')
    check('tariff_amendment_effective_2023_10_03',
          'Khoản 2 Điều 1 Thông tư này có hiệu lực từ ngày 03 tháng 10 năm 2023' in pages[7]
          and 'Mục này có hiệu lực thi hành từ ngày 03/10/2023' in pages[10],
          locator='PDF p8 footnote7 and p11 footnotes8/9; November18 applies to administration')
    check('visa_refusal_and_declining_results_no_refund',
          'không đủ điều kiện cấp thị thực' in pages[5]
          and 'không phải hoàn trả số tiền phí đã thu' in pages[5],
          locator='PDF p6 / gazette p52, Article6(3)')
    check('online_90percent_concession_is_passport_only',
          'cấp hộ chiếu theo hình thức trực tuyến' in pages[4]
          and 'điểm 1 Mục I' in pages[4],
          locator='PDF p5 / gazette p51, Article4(3); not sectionII visa fees')

    path = str(VN_FILE.relative_to(ROOT))
    sources = [dict(
        source_id=VN_ID,
        url='https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2024/4/41695/49739-1-2024555-55612-vbhn-btc.pdf',
        publisher='Viet Nam Ministry of Finance / Government Gazette',
        title='12/VBHN-BTC: consolidated immigration fee regulation, authenticated 4 April 2024',
        published_at='2024-04-26', document_date='2024-04-04', retrieved_at=ASOF,
        source_quality='official_original', local_path=path, path=path,
        bytes=len(raw), sha256=sha, archive_kind='original_document',
        notes='Consolidates 25/2021, 74/2022, 62/2023 and 63/2023. PDF p11/gazette p57: USD25 single, USD50 multiple <=90days. PDF p8/p54 separates tariff effective 2023-10-03 from administration effective 2023-11-18. The online 90% discount in Article4(3) concerns Vietnamese passports, not foreign visas. Domestic authorities including Immigration Department; no inference about overseas consular fee accounts.',
    )]
    fees = []
    for typ, amount, start, old, loc in [
        ('single_entry', 25, '2021-05-22', 'spx_vn_single_entry_evisa',
         'PDF p11 / gazette p57 sectionII row1; p8 / p54 Article8(1)'),
        ('multiple_entry_up_to_90days', 50, '2023-10-03',
         'spx_vn_multiple_entry_evisa_up_to_90days',
         'PDF p11 / gazette p57 sectionII row2a and footnote8; p8 / p54 footnote7'),
    ]:
        fid = 'refine_vn_' + typ + '_historical'
        fees.append(dict(
            id=fid, fee_rule_id=fid, destination='VNM', visa_type=typ,
            visa_group='other', amount=amount, currency='USD',
            component='government_visa_fee', source_id=VN_ID, source_ids=[VN_ID],
            source_locator=loc, effective_from=start, effective_to=None,
            historical_snapshot_date='2024-04-04', validity_status='dated_historical_rule',
            payment_trigger='application_submission',
            refund_rule='not_refunded_if_visa_not_granted_or_applicant_declines_result',
            refund_source_locator='PDF p6 / gazette p52, Article6(3)',
            exemptions='Article5: state guests, diplomats and families on reciprocity, treaties/reciprocity, humanitarian relief and specified indigent enforcement cases.',
            authority_scope='Vietnam-based authorities including Immigration Department; Article3',
            charge_basis='per_application', payer='applicant',
            related_existing_fee_rule_id=old,
            notes='2024官方合并法规直接核实历史法定费率；电子签适用性与2025政府说明相互印证。该规则不新增签发量或实收观察，不重复添加金额边。',
        ))

    coverage = []
    for code, name in [('KOR', '韩国'), ('VNM', '越南')]:
        for year in (2024, 2025):
            vn = code == 'VNM'
            coverage.append(dict(
                code=code, destination=code, name=name, region='亚洲', year=year,
                visa_group='other', status='amount_modeled',
                fee_known=vn, fee_current_snapshot_known=vn,
                quantity_known=True, quantity_context_known=True,
                category_detail_status='unclassified_aggregate', arrival_context_known=False,
                amount_known=False, amount_modeled=True, nationality_known=False,
                source_ids=[VN_ID, 'spx_vn_2024h1_issued' if year == 2024 else 'spx_vn_2025_issued']
                if vn else ['spx_kr_nabo2025', 'spx_kr_nabo2026'],
                searched_as_of=ASOF,
                notes=(
                    'USD25单次已由2024合并法核实，USD50多次<=90天自2023-10-03生效。'
                    + ('全年数量仍由上半年近150万桥接；未找到精确全年电子签签发量。' if year == 2024
                       else '全年报道为超过400万，保存下阈值；非精确件数。')
                    + '单多次组合、拒签付款、国籍与用途未拆；保持费值情景。'
                ) if vn else
                '驻外实际签发量已知；未取得签证专属决算实收或按国籍付费量。2024结算委员会报告只有外交部总账户，未升级原预算锚定模型。',
            ))

    updates = [dict(
        existing_fee_rule_id=fee['related_existing_fee_rule_id'],
        evidence_fee_rule_id=fee['fee_rule_id'],
        set=dict(source_id=VN_ID, append_source_ids=[VN_ID],
                 effective_from=fee['effective_from'],
                 historical_snapshot_date='2024-04-04',
                 validity_status='dated_historical_rule', source_locator=fee['source_locator']),
    ) for fee in fees]
    check('distinct_historical_rule_ids', len({f['fee_rule_id'] for f in fees}) == 2)
    check('no_duplicate_quantity_or_money_observations', True,
          observations_added=0, monetary_flows_added=0)
    dump('sources.json', sources)
    dump('fee_rules.json', fees)
    dump('observations.json', [])
    dump('coverage.json', coverage)
    dump('checks.json', checks)
    dump('integration_updates.json', updates)
    dump('research_log.json', dict(
        searched_as_of=ASOF,
        korea=dict(
            result='No isolated visa cash receipts or nationality-paid-visa breakdown found in this focused round.',
            reviewed=[
                dict(url='https://nabo.go.kr/board/file/down.do?fid=33318680',
                     locator='2024 settlement committee analysis, PDF p21 / printed p5',
                     finding='MOFA general-account receipts 368412 millionKRW; not visa-only. Web full-text search for 사증 found no match.'),
                dict(url='https://nabo.go.kr/board/file/down.do?fid=33318888',
                     locator='2026 budget committee analysis, PDF p21 / printed p5',
                     finding='MOFA aggregate revenue, not isolated visa income; no matching 사증 in web text.'),
                dict(url='https://nabo.go.kr/board/file/down.do?fid=33318873',
                     locator='2026 comprehensive budget analysis I, PDF p104 / printed p92',
                     finding='Visa-related rationale for 551억원 increase in consular fee budget; budget change only, no settled visa-only revenue.'),
            ],
            retrieval_note='Search-service PDF text reviewed. Direct original-PDF curl failed DNS for nabo.go.kr and www.nabo.go.kr. No local original or source record invented; retain existing frozen NABO2025/2026 originals.'),
        vietnam=dict(
            new_verified_evidence='12/VBHN-BTC dated2024-04-04 removes singleUSD25 2024 continuity assumption.',
            unresolved=['Exact2024 full-year eVisa count', 'Exact2025 eVisa count beyond reported >4m',
                        'Single/multiple-entry issuance mix', 'Paid refusals/abandonment',
                        'Nationality and visa-purpose fee breakdown', 'Settled government visa receipts'],
            excluded_substitutes=['Foreign arrivals', 'Daily application portal snapshot multiplied by365',
                                  'Back-solving2024 exact count from rounded growth >30%']),
    ))
    (OUT / 'README.md').write_text('''# 韩国／越南定向证据补包

2026-11-16冻结；默认离线重建：`.research-venv/bin/python scripts/research_refine_korea_vietnam.py`。

越南2024官方合并法规12/VBHN-BTC原件已经归档。单次USD25为25/2021规则（2021-05-22生效），多次不超过90天USD50修订2023-10-03生效。PDF p11／公报p57为价目表；p8／p54为生效日；p6／p52第6(3)条为拒签和放弃结果不退款。线上护照九折不适用于外籍签证。

## 统一包集成

新sources和两条历史fee_rules可并入研究证据。observations为空，防止重复签发数量或加入未经证实的金额。integration_updates.json列出两个已有spatial规则的精确字段更新：`spx_vn_single_entry_evisa`须移除`2025_official_snapshot_2024_continuity_assumption`并升级`dated_historical_rule`；两条旧规则均追加新source，保留旧source链。修改应落实在scripts/research_spatial_extension.py生成逻辑，避免离线重建恢复旧状态。

同时将该脚本params.fee_temporal_evidence和model.limitations中的“2024单次25连续性假设”改成2024合并法核实，并把新source加入越南flows.source_ids和coverage.source_ids。**金额中心及范围均不变**：仍为签发量×单多次组合的费值情景，国籍UNK，不升级为实收。

## 未补齐的数量与实收

越南2024全年精确电子签数量未取得；继续保留上半年近150万的年化情景。2025为报道超过400万阈值，单多次组合和拒签付款仍未知。不以入境旅客数、每日申请快照或四舍五入增长率替代。

韩国定向核查2024结算委员会报告及2026预算报告，未分离签证实收；只找到外交部总账户与预算增额，research_log.json保留可复查定位。直接下载NABO新报告遇DNS失败，没有把网页解析伪装成原始PDF归档，也未注册未下载的原件。现有NABO原件、真实驻外签发量及预算锚定情景继续沿用。
''')
    print(json.dumps(dict(package=str(OUT.relative_to(ROOT)), sources=len(sources),
                          fee_rules=len(fees), observations=0, coverage=len(coverage),
                          checks=len(checks), passed=all(c['passed'] for c in checks)),
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
