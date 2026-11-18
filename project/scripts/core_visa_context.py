"""Expose existing primary visa statistics without duplicating observations.

Only series metadata is added. Native values, periods, sources and fee-model
eligibility remain intact; totals and components are independently selectable.
"""
from collections import defaultdict
import hashlib
import unicodedata

US_CLASSES = {'B1/B2': 'B1/B2访客', 'F1': 'F1学生', 'J1': 'J1交流',
              'H1B': 'H1B工作', 'L1': 'L1调派', 'ALL_NIV': '全类别', 'Grand Total': '全类别'}
UK_TYPES = {'Visitor': '访客', 'Study': '学习', 'Work': '工作',
            'Family': '家庭', 'Other': '其他类别'}
UK_METRICS = {'Applications': '申请', 'Issued': '签发', 'Refused': '拒签', 'Withdrawn': '撤回'}
CA_TYPES = {'Visitor V-1': 'V-1访客', 'New study permit': '新学习许可',
            'All temporary residents incl extensions': '临时居民（含延期）'}
CA_METRICS = {'Applications': '受理', 'Approved': '批准', 'Processed': '处理'}
RU_CLASSES = {'total': '全类别', 'diplomatic': '外交', 'service': '公务',
              'common': '普通', 'transit': '过境', 'business': '商务',
              'private': '私人', 'tourist': '旅游', 'other': '其他'}


def expose_core_visa_context(rows):
    for row in rows:
        source, native = row.get('source_id'), row.get('native_file', '')
        code, kind, metric = row.get('destination'), row.get('visa_type'), row.get('metric')
        identifier = label = None
        if code == 'USA' and kind in US_CLASSES:
            if source in ('us_detail2024', 'us_classes2020_2024') and metric == 'visas_issued':
                # The nationality table already supplies FY2024's world total.
                if source == 'us_classes2020_2024' and row.get('period_end') == '2024-09-30':
                    continue
                identifier = 'core_us_issued_' + kind
                label = '美国非移民签证 · ' + US_CLASSES[kind] + '签发'
            elif source == 'us_workload2024' and metric in ('refused_at_fiscal_year_end', 'total_applications_published'):
                identifier = 'core_us_workload_' + kind + '_' + metric
                label = '美国非移民签证 · ' + US_CLASSES[kind] + ('财年末仍拒签' if metric.startswith('refused') else '原表申请工作量')
        elif code == 'JPN' and kind == 'all' and metric == 'visas_issued':
            if native == 'data/research/history_expansion/observations.json' or native == 'data/research/asia_pacific/observations.json' and row.get('origin_basis') == 'nationality':
                identifier, label = 'core_jp_nationality_all_issued', '日本 · 全类别签证签发（国籍／地区）'
                # Both native tables use the same nationality/region/document
                # heading; this preserves that broader scope across editions.
                row['origin_basis'] = 'nationality_region_or_document_as_published'
                row['period_type'] = 'calendar_year'
                raw = unicodedata.normalize('NFKC', row.get('origin_original') or '')
                if raw == '中国(香港)':
                    row['context_partner_code'] = 'HKG:JP:china_hongkong_document'
                    row['context_partner_label'] = '中国香港（原表“中国（香港）”证件分项）'
                    row['notes'] = (row.get('notes') or '') + ' 原表“中国（香港）”与“香港SAR”各列独立证件分项；国籍代码归同一辖区，背景选择保留这两行，未重复合计。'
                elif row.get('origin') == 'HKG' and 'DI' in raw:
                    row.update(context_partner_code='HKG:JP:DI', context_partner_label='中国香港（DI证件分项）')
                elif row.get('origin') == 'HKG' and '英国' in raw:
                    row.update(context_partner_code='HKG:JP:british_document', context_partner_label='中国香港（原表“香港（英国）”证件分项）')
                elif row.get('origin') == 'MAC' and '旅行証' in raw:
                    row.update(context_partner_code='MAC:JP:travel_document', context_partner_label='中国澳门（旅行证分项）')
                elif row.get('origin') == 'COD' and raw == 'ザイール':
                    row.update(context_partner_code='COD:JP:ZAIRE', context_partner_label='刚果民主共和国（原表“扎伊尔”历史分项）')
                elif row.get('origin') == 'UNK':
                    row.update(context_partner_code='UNK:JP:' + hashlib.sha1(raw.encode()).hexdigest()[:10], context_partner_label='未归属（原表“' + raw + '”）')
        elif code == 'GBR' and native.endswith('/uk_annual_summary.json') and kind in UK_TYPES and metric in UK_METRICS:
            identifier = 'core_uk_' + kind + '_' + metric
            label = '英国 · ' + UK_TYPES[kind] + UK_METRICS[metric]
        elif code == 'CAN' and native.endswith('/canada_annual_summary.json') and kind in CA_TYPES and metric in CA_METRICS:
            identifier = 'core_ca_' + kind + '_' + metric
            label = '加拿大 · ' + CA_TYPES[kind] + CA_METRICS[metric]
        elif code == 'RUS' and native.endswith('/russia_evisa_annual.json') and metric in ('issued', 'entered'):
            identifier = 'core_ru_evisa_' + metric
            label = '俄罗斯 · 统一电子签' + ('签发（国籍）' if metric == 'issued' else '入境人次（国籍）')
        elif code == 'RUS' and native.endswith('/russia_consular_annual.json') and metric in RU_CLASSES:
            identifier = 'core_ru_paper_global_' + metric
            label = '俄罗斯 · 驻外纸质签证' + RU_CLASSES[metric] + '签发总量'
        elif code == 'RUS' and native.endswith('/russia_consular_country_annual.json') and metric in RU_CLASSES:
            identifier = 'core_ru_paper_by_post_' + metric
            label = '俄罗斯 · 驻外纸质签证' + RU_CLASSES[metric] + '签发（机构所在地）'
        elif code == 'TUR' and native.endswith('/turkey_annual.json') and metric == 'issued':
            identifier = 'core_tur_issued_' + str(kind)
            label = '土耳其 · ' + {'evisa': '电子签', 'sticker_visa': '贴纸签', 'all_visa_channels': '全渠道'}.get(kind, str(kind)) + '签发'
        if identifier:
            row.update(series_id=identifier, series_label=label,
                       observation_domain='visa_activity', flow_direction='inbound')
            if code == 'RUS' and metric == 'entered':
                row['observation_domain'] = 'mobility'
            if code == 'USA':
                row['notes'] = (row.get('notes') or '') + ' 财年口径；签发、财年末仍拒签与原表申请工作量分别统计，不是同一申请队列，不能据此直接计算通过概率。'
    # Identically labelled original rows do not establish a unique annual point.
    # Keep both original observations, and leave that plotted period missing.
    groups = defaultdict(list)
    for row in rows:
        if row.get('series_id') == 'core_jp_nationality_all_issued':
            groups[row.get('context_partner_code') or row.get('origin'), row.get('period_start'), row.get('period_end')].append(row)
    for members in groups.values():
        if len(members) > 1:
            for row in members:
                row.pop('series_id')
                row.pop('series_label')
