#!/usr/bin/env python3
"""Replace Nepal's arrival-priced subset with national visa-receipt controls."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    research = ROOT / 'data/research/south_asia_expansion_v7'
    flows = json.loads((research / 'calendar_model_candidates.json').read_text())
    old = json.loads((ROOT / 'data/estimates/global_asia_me_europe_flows.json').read_text())
    replaced = [r['id'] for r in old['flows'] if r['receiver'] == 'NPL' and r['amount'] > 0]
    kept = [r for r in old['flows'] if r['receiver'] == 'NPL' and r['amount'] == 0]
    assert len(replaced) == 26
    assert len(kept) == 4 and {r['payer'] for r in kept} == {'CHN', 'IND'}
    ranges = []
    for row in flows:
        assert row['payer'] == 'UNK' and row['quantity'] is None
        assert row['currency'] == 'NPR' and row['year'] in (2023, 2024, 2025)
        row['visa_group'] = 'other'
        row['category_detail_status'] = 'unclassified'
        for key in ('amount_cny', 'lower_cny', 'upper_cny'):
            row.pop(key, None)
        row['notes'] += ' 主账保留CHN旅游免费和IND无需签证两项明确零费政策；旧正额游客费用模型已全部移除。'
        ranges.append(dict(receiver='NPL', year=row['year'], currency='NPR',
                           amount=row['amount'], lower=row['lower'], upper=row['upper'],
                           range_method='全国14228财政实际签证费基准；2023/24为均匀日率自然年桥接，2025为最近FY水平±15%时间情景'))
    bundle = dict(package='south_asia_expansion_v7', flows=flows, destination_ranges=ranges,
                  models=[dict(model_id='sv7_npl_national_receipts_calendar_bridge', destination='NPL',
                               years=sorted(r['year'] for r in flows),
                               status='national_cash_leaf_fiscal_to_calendar_estimate',
                               formula='2023/24=sum(fiscal_actual_receipts * overlap_days / fiscal_days); 2025=latest FY2024/25 level',
                               source_ids=sorted({s for r in flows for s in r['source_ids']}),
                               limitations=['财政年实际收入与自然年估算分别保存。',
                                            '全国14228签证费只取Collection，Utilization和部门子账不再相加。',
                                            '用途与付款国籍未知，保持UNK；没有匹配付费事件分母。',
                                            '旧游客国籍份额不转作财政份额；中国旅游免费与印度无需签证零费政策独立保留。']),
                          dict(model_id='game_npl_tourist_single_entry', destination='NPL', years=[2024, 2025],
                               status='explicit_free_policy_edges_only',
                               formula='CHN eligible tourist visas=0; IND ordinary travel requires no visa=0',
                               limitations=['仅保留有政策来源的四条明确零额边；游客数量不表示付费申请次数。',
                                            '原正额游客费情景已由全国14228财政基准替换。'])],
                  replaces=[dict(package='global_asia_me_europe', flow_ids=replaced,
                                 model_ids=['game_npl_tourist_single_entry'],
                                 range_scopes=[dict(receiver='NPL', year=y) for y in (2024, 2025)],
                                 reason='National 14228 receipt scope supersedes the positive tourist subset; explicit free-policy edges remain zero.')])
    out = ROOT / 'data/estimates/south_asia_expansion_v7_flows.json'
    out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(json.dumps(dict(flows=len(flows), replaced=len(replaced), explicit_free_kept=len(kept))))


if __name__ == '__main__':
    main()
