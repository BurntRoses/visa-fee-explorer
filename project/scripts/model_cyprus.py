#!/usr/bin/env python3
"""Integrate Cyprus's published visa-receipt leaf without inventing payers."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    research = ROOT / 'data/research/europe_fiscal_v6'
    flows = json.loads((research / 'model_candidates.json').read_text())
    controls = json.loads((research / 'annual_cash_controls.json').read_text())
    by_year = {r['year']: r for r in controls}
    ranges = []
    for row in flows:
        control = by_year[row['year']]
        assert row['payer'] == 'UNK' and row['quantity'] is None
        assert row['amount'] == row['lower'] == row['upper'] == control['amount']
        assert row['parameters']['archive_kind'] == 'fact_excerpt'
        row['visa_group'] = 'other'
        row['category_detail_status'] = 'unclassified'
        ranges.append(dict(receiver='CYP', year=row['year'], currency='EUR',
                           amount=row['amount'], lower=row['lower'], upper=row['upper'],
                           range_method='01373签证实收公布账户值；官方索引事实摘录，未取得PDF原件；同端点不表示全渠道覆盖或统计置信区间'))
    assert len(flows) == len(by_year) == len({r['year'] for r in flows})
    bundle = dict(package='europe_fiscal_v6', flows=flows, destination_ranges=ranges,
                  models=[dict(model_id='ev6_cyp_MFA_visa_receipts', destination='CYP',
                               years=sorted(by_year),
                               status='published_receipts_indexed_excerpt_scope_partial',
                               formula='MFA170100 account01373 Visas; one latest-report actual cell per calendar year',
                               source_ids=sorted({s for r in flows for s in r['source_ids']}),
                               limitations=['官方PDF直链403，来源是可追溯索引事实摘录；未归档或查验PDF原件。',
                                            '仅外交部01373签证叶科目，不含01605领事费用及其他移民收费。',
                                            '预算、差额、父级合计和跨年重复比较列均不加入金额。',
                                            '付款国籍、用途和付费申请数量未知，保留UNK与空分母。'])])
    out = ROOT / 'data/estimates/europe_fiscal_v6_flows.json'
    out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(json.dumps(dict(flows=len(flows), years=sorted(by_year), currency='EUR'), ensure_ascii=False))


if __name__ == '__main__':
    main()
