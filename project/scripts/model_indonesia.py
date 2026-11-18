#!/usr/bin/env python3
"""Replace the VOA-only approximation with identified Indonesian visa cash leaves."""
from collections import defaultdict
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    research = ROOT/'data/research/asia_expansion_v6'
    flows = json.loads((research/'model_candidates.json').read_text())
    controls = json.loads((research/'annual_cash_controls.json').read_text())
    scopes = defaultdict(list)
    for row in flows:
        assert row['payer'] == 'UNK' and row['quantity'] is None
        assert row['amount'] == row['lower'] == row['upper']
        row['visa_group'] = 'other'
        row['category_detail_status'] = 'unclassified'
        row.pop('amount_cny', None)  # The shared FX registry owns conversion.
        row['notes'] = ('官方LRA现金签证叶科目；425212含访问及有限居留签，425221为海外签证。'
                        '两科目互斥，替换旧VOA估算；未含425224混合服务中无法分拆的签证部分。'
                        '付款国籍、用途及匹配收费事件数未公开。')
        scopes[row['year']].append(row)
    ranges = []
    for control in controls:
        year = control['year']
        amount = sum(r['amount'] for r in scopes[year])
        assert len(scopes[year]) == 2 and amount == control['identified_visa_cash_total']
        ranges.append(dict(receiver='IDN', year=year, currency='IDR', amount=amount,
                           lower=amount, upper=amount,
                           range_method='LRA两个已识别签证现金科目；相同端点为科目公布值，未涵盖混合账户遗漏或报表误差'))
    bundle = dict(package='asia_expansion_v6', flows=flows, destination_ranges=ranges,
                  models=[dict(model_id='av6_idn_identified_visa_cash', destination='IDN',
                               years=sorted(scopes), status='official_visa_cash_leaf_accounts_partial_scope',
                               formula='425212 Pendapatan Visa + 425221 Pendapatan Visa di Luar Negeri',
                               limitations=['425224贸易及经济办事处混合服务中的签证收入未能分拆，未计入。',
                                            '现金与权责收入各按原表记录；此系列使用LRA现金。',
                                            '来源国籍与付费申请数量未知；不按到达游客份额分配或计算申请人均值。'])],
                  replaces=[dict(package='global_asia_me_europe',
                                 flow_ids=[f'game_idn_voa_model_{y}_UNK_visitor' for y in (2024, 2025)],
                                 model_ids=['game_idn_voa_model'],
                                 range_scopes=[dict(receiver='IDN', year=y) for y in (2024, 2025)],
                                 reason='Audited visa cash leaves contain the previous VOA-only scope; replace once.')])
    out = ROOT/'data/estimates/asia_expansion_v6_flows.json'
    out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(',', ':'))+'\n')
    print(json.dumps(dict(flows=len(flows), years=sorted(scopes), replaced_flows=2), ensure_ascii=False))


if __name__ == '__main__':
    main()
