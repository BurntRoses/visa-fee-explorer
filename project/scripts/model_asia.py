#!/usr/bin/env python3
"""Local working models for JPN/NZL/AUS/RUS fee flows in calendar 2024/2025.

Centers are explicit working parameters, not published national receipts. Outputs
contain native-currency amounts and parameter sensitivity envelopes, not CIs.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
from build_dataset import entity

ROOT = Path(__file__).resolve().parents[1]
AP = ROOT / 'data/research/asia_pacific'
RU = ROOT / 'data/research/turkey_russia_saudi'
OUTPUT = ROOT / 'data/estimates/asia_flows.json'
GROUP_NAMES = {'visitor': '短期访问', 'student': '学生', 'work': '工作',
               'family': '家族', 'other': '其他／未分配类别'}


def read(path):
    return json.loads(path.read_text())


def unique(items):
    return list(dict.fromkeys(x for x in items if x))


def row_id(prefix, year, payer, group):
    return f'{prefix}_{year}_{payer}_{group}'


class Model:
    def __init__(self):
        self.observations = read(AP / 'observations.json')
        self.rules = {f['fee_rule_id']: f for f in read(AP / 'fee_rules.json')}
        self.flows, self.models = [], []

    def add(self, prefix, payer, receiver, year, group, amount, lower, upper,
            currency, quantity, quantity_basis, sources, observations, notes, parameters,
            visa_type=None):
        if payer in ('WORLD', receiver):
            return
        if not (0 <= lower <= amount <= upper):
            raise ValueError((prefix, payer, year, group, lower, amount, upper))
        self.flows.append({
            'id': row_id(prefix, year, payer, group), 'payer': payer, 'receiver': receiver,
            'year': year, 'visa_group': group, 'visa_type': visa_type or group,
            'visa_label': GROUP_NAMES[group], 'amount': amount, 'currency': currency,
            'lower': lower, 'upper': upper, 'quantity': quantity,
            'quantity_basis': quantity_basis, 'source_ids': unique(sources),
            'observation_ids': unique(observations), 'method_id': prefix,
            'model_status': 'modeled_estimate', 'calculation_type': 'modeled_estimate',
            'period_start': f'{year}-01-01', 'period_end': f'{year}-12-31',
            'period_label': str(year), 'period_type': 'calendar_year_model',
            'origin_basis': 'modeled_nationality', 'notes': notes, 'parameters': parameters,
        })

    def japan(self):
        source = defaultdict(dict)
        for r in self.observations:
            if r['destination'] == 'Japan' and r.get('basis') == 'nationality':
                source[r['year'], r['nationality']][r['visa_type']] = r
        for (year, nationality), rr in sorted(source.items()):
            payer = entity(nationality)
            if payer == 'WORLD':
                continue
            q = lambda k: rr[k]['value']
            total, multiple = q('all'), q('multiple_entry_subset')
            counts = {
                'visitor': q('short_stay'), 'student': q('student'),
                'work': q('employment_total') + q('highly_skilled') + q('startup') +
                        q('purpose_AM') + q('purpose_AR') + q('purpose_AS'),
                'family': q('dependent') + q('purpose_AO') + q('purpose_AP'),
            }
            counts['other'] = total - sum(counts.values())
            if counts['other'] < 0:
                raise ValueError(('Negative disjoint Japanese remainder', year, nationality))
            # Select a feasible intersection midpoint, then allocate the remaining
            # multiple visas by sequential feasible midpoints. No independence assumption.
            remaining_total, remaining_multiple = total, multiple
            allocated = {}
            marginal = {}
            for group, count in counts.items():
                lo, hi = max(0, count + multiple - total), min(count, multiple)
                marginal[group] = (lo, hi)
                conditional_lo = max(0, remaining_multiple - (remaining_total - count))
                conditional_hi = min(count, remaining_multiple)
                selected = (conditional_lo + conditional_hi) / 2
                allocated[group] = selected
                remaining_total -= count
                remaining_multiple -= selected
            if abs(remaining_multiple) > 1e-8:
                raise ValueError('Japanese multiple-entry allocation did not reconcile')
            for group, count in counts.items():
                if count == 0:
                    continue
                lo, hi = marginal[group]
                sel = allocated[group]
                params = {
                    'nationality_original': nationality, 'total_issued': total,
                    'multiple_issued': multiple, 'group_count': count,
                    'multiple_group_frechet_lower': lo, 'multiple_group_frechet_upper': hi,
                    'multiple_group_center': sel,
                    'multiple_allocation': 'visitor Frechet midpoint; remaining groups sequential feasible midpoints in student/work/family/other order',
                    'unknown_other_exemption_share': {'center': .10, 'lower': 0, 'upper': .20},
                    'single_JPY': 3000, 'multiple_JPY': 6000,
                    'unobserved_double_entry_treated_as_single': True,
                    'group_counts': counts,
                    'group_partition': 'work includes employment/highly-skilled/startup/WH/future-talent/digital-nomad (some accompanying spouses stay in source purpose); family includes dependants/Japanese/permanent-resident spouse',
                }
                base, low_base, high_base = 3000 * (count + sel), 3000 * (count + lo), 3000 * (count + hi)
                if group == 'other':
                    free = q('diplomatic') + q('official')
                    transit = q('transit')
                    normal = count - free - transit
                    if normal < 0:
                        raise ValueError(('Other-count cannot contain known free and transit', year, nationality))
                    free_m = (max(0, sel - (count - free)) + min(free, sel)) / 2
                    rem_m = sel - free_m
                    transit_m = (max(0, rem_m - normal) + min(transit, rem_m)) / 2
                    normal_m = rem_m - transit_m
                    base = 3000 * (normal + normal_m) + 700 * transit
                    low_base = 3000 * (normal + max(0, lo - free - transit)) + 700 * transit
                    high_base = 3000 * (normal + min(normal, hi)) + 700 * transit
                    params.update(known_diplomatic_and_official_free=free, transit_count=transit,
                                  transit_JPY=700, other_normal_multiple_center=normal_m,
                                  diplomatic_official_zero_is_model_treatment=True)
                amount, lower, upper = base * .9, low_base * .8, high_base
                sids = [rr['all']['source_id'], 'jp_fee_old']
                if payer == 'PHL' and group == 'visitor':
                    amount = lower = upper = 0
                    sids.append('jp_fee_ph_gratis')
                    params.update(philippine_temporary_visitor_gratis=True,
                                  historical_continuity_assumption='2026 official page says remains gratis; apply unchanged to 2024/25 as a working historical assumption, not observed historical waiver counts')
                ids = [r['observation_id'] for r in rr.values() if r['visa_type'] in (
                    'all', 'multiple_entry_subset', 'short_stay', 'student', 'employment_total',
                    'highly_skilled', 'startup', 'dependent', 'diplomatic', 'official', 'transit',
                    'purpose_AM', 'purpose_AO', 'purpose_AP', 'purpose_AR', 'purpose_AS')]
                self.add('jp_frechet_exemptions', payer, 'JPN', year, group, amount, lower, upper,
                         'JPY', count, 'visas_issued', sids, ids,
                         '互斥目的组；短期×数次交叉用Fréchet可行中点，不假设独立。外交／公用按免费处理；菲律宾短期依现有官方gratis说明作历史持续假设。其余未知减免中心10%、敏感性0–20%；非官方收入。各组边界为边际敏感性包络，不能当同时可达的联合情景。', params)
        self.models.append({
            'model_id': 'jp_frechet_exemptions', 'destination': 'JPN', 'years': [2024, 2025],
            'status': 'working_estimate_not_official_receipts',
            'formula': 'JPY3000*(nonexempt single-equivalent count + allocated multiple count), transit JPY700; unknown exemptions center10%, range0–20%',
            'source_files': ['data/research/asia_pacific/observations.json', 'data/research/asia_pacific/fee_rules.json'],
            'limitations': ['Purpose and nationality exceptions beyond known treatments remain a parameter.',
                            'Nominal JPY differs from mission-local collection and is not actual cash receipts.',
                            'Philippine short-visit gratis is backcast from a 2026 remains-gratis statement.',
                            'Marginal Frechet bounds of different groups are not independent confidence limits.'],
        })

    def new_zealand(self):
        source = {}
        for r in self.observations:
            if r['destination'] == 'New Zealand' and r['metric'] == 'applications_decided':
                source[r['nationality'], r['visa_type'], r['year']] = r
        history = ROOT / 'data/research/newzealand_history_v5'
        reused = read(history / 'reused_observations.json')
        legacy_keys = {}
        corrected_payers = {}
        for r in reused:
            if r['metric'] != 'applications_decided':
                continue
            key = (r['visa_type'], r['raw_origin_label'])
            legacy = r['legacy_nationality_label']
            if key in legacy_keys and legacy_keys[key] != legacy:
                raise ValueError(('NZ legacy nationality key changed between FYs', key))
            legacy_keys[key] = legacy
            # The original 2024 amounts and IDs remain reproducible. For the
            # updated 2025 model, recover actual country codes from wrapped
            # labels; historical/organisation/unknown source buckets retain
            # their existing payer identifiers.
            if r['aggregation_role'] == 'country_component':
                corrected_payers[legacy, r['visa_type']] = entity('Kosovo' if r['origin'] == 'XKX' else r['origin'])
        next_fy = [r for r in read(history / 'observations.json')
                   if r['metric'] == 'applications_decided' and r['period_label'] == '2025/26']
        for r in next_fy:
            if (r['period_start'], r['period_end'], r['source_status']) != (
                    '2025-07-01', '2026-06-30', 'complete_fiscal_year'):
                raise ValueError(('NZ complete FY2025/26 required', r['observation_id']))
            legacy = legacy_keys[r['visa_type'], r['raw_origin_label']]
            source[legacy, r['visa_type'], 2026] = r
        for group in ('visitor', 'student', 'work'):
            rr = [r for r in next_fy if r['visa_type'] == group]
            world = next(r['value'] for r in rr if r['origin'] == 'WORLD')
            parts = sum(r['value'] for r in rr if r['origin'] != 'WORLD')
            if parts != world:
                raise ValueError(('NZ FY2025/26 nationality total', group, parts, world))
        pairs = sorted({(n, typ) for n, typ, y in source if n != 'WORLD'})
        work_mix = {'working_holiday': .15, 'AEWV': .35, 'other_work': .20,
                    'post_study_work': .15, 'partnership_work': .15}
        for year in (2024, 2025):
            fy_pairs = [(2024, .5), (2025, .5)] if year == 2024 else [(2025, .5), (2026, .5)]
            old_weight = (date(2024, 10, 1) - date(2024, 1, 1)).days / 366 if year == 2024 else 0
            for nationality, group in pairs:
                payer = entity(nationality) if year == 2024 else corrected_payers.get((nationality, group), entity(nationality))
                rr = [source[nationality, group, fy] for fy, w in fy_pairs if (nationality, group, fy) in source]
                if len(rr) != len(fy_pairs):
                    raise ValueError(('NZ required FY nationality row missing; missing is not zero', year, nationality, group))
                count = sum(source.get((nationality, group, fy), {}).get('value', 0) * w for fy, w in fy_pairs)
                if not count:
                    continue
                types = work_mix if group == 'work' else {group: 1.}
                rates, fee_ids, sids = {}, [], []
                for product, weight in types.items():
                    before = self.rules[f'nz_{product}_application_fee_pre202410']
                    after = self.rules[f'nz_{product}_application_fee_202410']
                    rates[product] = before['amount'] * old_weight + after['amount'] * (1 - old_weight)
                    fee_ids.extend([before['fee_rule_id'], after['fee_rule_id']])
                    sids.extend([before['source_id'], after['source_id']])
                fee_center = sum(types[k] * rates[k] for k in rates)
                lower, amount, upper = count * min(rates.values()) * .8, count * fee_center, count * max(rates.values()) * 1.2
                self.add('nz_fy_calendar_fee_events', payer, 'NZL', year, group,
                         amount, lower, upper, 'NZD', count, 'modeled_calendar_decided_applications',
                         [r['source_id'] for r in rr] + sids,
                         [r['observation_id'] for r in rr],
                         '相邻两个完整财政年决定件各占一半桥接日历年；2024用FY2023/24及FY2024/25，2025用FY2024/25及FY2025/26。政府application fee单列，不含IVL、immigration levy或NZeTA。缴费事件／决定比中心1，敏感性0.8–1.2；工作细类组合为显式模型参数。决定件含原文指定撤回，不是实收或独立申请人数。',
                         {'nationality_original': nationality, 'fiscal_year_weights': fy_pairs,
                          'calendar_bridge': '0.5*FY2023/24 + 0.5*FY2024/25' if year == 2024 else '0.5*FY2024/25 + 0.5*FY2025/26',
                          'fiscal_decided_inputs': [{'financial_year': r.get('period_label', f'{r["year"]-1}/{str(r["year"])[-2:]}'),
                                                     'decided': r['value'], 'weight': weight,
                                                     'observation_id': r['observation_id'], 'source_id': r['source_id']}
                                                    for r, (fy, weight) in zip(rr, fy_pairs)],
                          'calendar_2025_missing_next_FY': False,
                          'normalized_nationality_2025': payer if year == 2025 else None,
                          'nationality_label_restored_from_pdf': year == 2025 and payer != entity(nationality),
                          'paid_applications_per_decision': {'center': 1, 'lower': .8, 'upper': 1.2},
                          'pre_202410_rate_weight': old_weight, 'rate_timing_assumption': 'uniform payment within calendar year',
                          'fee_products_mix': types, 'weighted_product_rates_NZD': rates,
                          'work_mix_is_unobserved_working_parameter': group == 'work',
                          'fee_rule_ids': fee_ids, 'charge_scope': 'Band C government application_fee only',
                          'excluded_components': ['immigration_levy', 'international_visitor_levy', 'NZeTA'],
                          'missing_nationality_FY_rows_assumed_zero': len(rr) < len(fy_pairs)})
        self.models.append({
            'model_id': 'nz_fy_calendar_fee_events', 'destination': 'NZL', 'years': [2024, 2025],
            'status': 'working_estimate_not_official_receipts',
            'formula': 'FY decided bridge * paid/decided parameter * calendar-time product fee mix (application_fee only)',
            'parameters': {'calendar_fiscal_year_weights': {'2024': {'2023/24': .5, '2024/25': .5},
                                                           '2025': {'2024/25': .5, '2025/26': .5}},
                           'paid_per_decided': [0.8, 1, 1.2], 'work_product_mix': work_mix},
            'source_files': ['data/research/asia_pacific/observations.json',
                             'data/research/newzealand_history_v5/observations.json',
                             'data/research/newzealand_history_v5/reused_observations.json',
                             'data/research/asia_pacific/fee_rules.json'],
            'source_file_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in [history / 'observations.json', history / 'reused_observations.json']},
            'limitations': ['Band C is a pricing benchmark; actual concessions, Pacific bands, family/group billing and application location are not observed.',
                            'Work product mix is assumed, with the full source-product fee range used for sensitivity.',
                            'Equal-weight adjacent complete financial years approximate calendar-year timing; monthly application/payment seasonality is not identified.',
                            'Decisions include specified withdrawals and count applications, not people or current-period fee payments.',
                            'Decisions and payments occur in different periods; 0.8–1.2 is a working sensitivity, not fitted evidence.'],
        })

    def australia(self):
        observations = [r for r in self.observations if r['destination'] == 'Australia']
        recent = read(ROOT / 'data/research/australia_recent_v6/observations.json')
        observations += [r for r in recent if r.get('year') == 2026 and
                         r.get('period_type') == 'financial_year']
        monthly = read(AP / 'australia_monthly_grants.json')
        revenues = {r['year']: r for r in observations if r['metric'] == 'visa_application_charge_revenue'}
        throughput = {}
        for fy in (2024, 2025, 2026):
            applications = [r for r in observations if r['metric'] == 'applications_lodged' and
                            r['year'] == fy and r['visa_type'] == '600' and r['nationality'] == 'WORLD']
            grants = [r for r in observations if r['metric'] == 'visas_granted' and
                      r['year'] == fy and r['year_type'] == 'financial' and
                      r['visa_type'] == '600' and r['nationality'] == 'WORLD']
            throughput[fy] = {'ratio': sum(r['value'] for r in grants) / sum(r['value'] for r in applications),
                              'applications': sum(r['value'] for r in applications),
                              'grants': sum(r['value'] for r in grants),
                              'observation_ids': [r['observation_id'] for r in applications + grants]}
            if fy == 2026:
                if any((r['period_start'], r['period_end']) != ('2025-07-01', '2026-06-30')
                       for r in applications + grants):
                    raise ValueError('AU requires complete FY2025/26 visitor inputs')
                throughput[fy]['source_status'] = 'provisional'
        for year in (2024, 2025):
            fiscal_pair = (2024, 2025) if year == 2024 else (2025, 2026)
            selected_throughput = {fy: throughput[fy] for fy in fiscal_pair}
            ratio = (throughput[fiscal_pair[0]]['ratio'] + throughput[fiscal_pair[1]]['ratio']) / 2
            ratio_low, ratio_high = ratio * .9, min(1, ratio * 1.1)
            native_total = (revenues[fiscal_pair[0]]['value'] + revenues[fiscal_pair[1]]['value']) / 2
            target_low, target_high = native_total, native_total
            country_rows = defaultdict(list)
            for r in monthly:
                if int(r['year_month'][:4]) == year and r['visa_subclass'].startswith('600') and r['client_location'] == 'Outside Australia':
                    country_rows[r['nationality']].append(r)
            added = []
            for nationality, rr in sorted(country_rows.items()):
                payer = entity(nationality)
                if payer in ('WORLD', 'AUS'):
                    continue
                counts = defaultdict(int)
                fees_used = {}
                for r in rr:
                    fee_id = f'au_visitor_{year}0101' if year == 2024 and int(r['year_month'][5:]) <= 6 else (
                        'au_visitor_20240701' if r['year_month'] <= '2025-06' else 'au_visitor_20250701')
                    fee = self.rules[fee_id]
                    counts[fee_id] += r['value']
                    fees_used[fee_id] = fee
                weighted_granted = sum(counts[k] * fees_used[k]['amount'] for k in counts)
                center, low, high = weighted_granted / ratio, weighted_granted / ratio_high, weighted_granted / ratio_low
                annual_obs = [r for r in observations if r['metric'] == 'visas_granted' and r['year'] == year and
                              r['year_type'] == 'calendar' and r['nationality'] == nationality and
                              r['visa_type'] == '600' and r.get('client_location') == 'Outside Australia']
                self.add('au_600_fee_events', payer, 'AUS', year, 'visitor', center, low, high, 'AUD',
                         sum(r['value'] for r in rr) / ratio, 'modeled_paid_600_applications',
                         ['au_visitor_grants_pivot', 'au_visitor_2025_06'] +
                         (['aur6_visitor_2026_06'] if year == 2025 else []) + [f['source_id'] for f in fees_used.values()],
                         [r['observation_id'] for r in annual_obs] +
                         unique(i for fy in fiscal_pair for i in throughput[fy]['observation_ids']),
                         '仅对子类600境外记录使用有来源的offshore费；月度签发除以全球600批准／递交吞吐比估收费事件。该比率不是队列批准概率，国籍费率减免与跨期误差留在模型范围。其他签证和境内600不按访客份额分国籍。',
                         {'nationality_original': nationality, 'grants_by_tariff_period': dict(counts),
                          'government_tariff_AUD': {k: f['amount'] for k, f in fees_used.items()},
                          'grant_lodgement_throughput_proxy': {'center': ratio, 'lower': ratio_low, 'upper': ratio_high},
                          'throughput_inputs': selected_throughput, 'throughput_is_not_cohort_approval_rate': True,
                          'scope': '600 offshore only; all unallocated VAC remains UNKNOWN other',
                          'calendar_month_records': len(rr)}, visa_type='600_offshore')
                added.append(self.flows[-1])
            visitor_center = sum(r['amount'] for r in added)
            visitor_low, visitor_high = sum(r['lower'] for r in added), sum(r['upper'] for r in added)
            remainder = native_total - visitor_center
            if remainder < 0 or target_low < visitor_high:
                raise ValueError('AU visitor allocation exceeds VAC control')
            revenue_parameters = {
                'calendar_revenue_target_AUD': {'center': native_total, 'lower': target_low, 'upper': target_high},
                'fiscal_revenue_AUD': {str(y): revenues[y]['value'] for y in fiscal_pair},
                'calendar_bridge': '0.5*FY2024/25 + 0.5*FY2025/26',
                'accounting_basis': 'recognised_administered_VAC_revenue',
                'cash_received_is_separate_not_added': True,
                'seasonality_assumption': 'equal half-year shares of complete FY revenue; monthly VAC receipt timing not observed',
                'known_visitor_allocation_AUD': visitor_center,
                'remainder_identity': 'calendar revenue target minus known offshore600 allocation',
                'source_unallocated': True, 'contains_unidentified_visa_groups': True,
                'interval_dependency': 'remainder decreases when allocated visitor estimate rises'}
            self.add('au_vac_unallocated_remainder', 'UNKNOWN', 'AUS', year, 'other', remainder,
                     max(0, target_low - visitor_high), target_high - visitor_low, 'AUD', None,
                     'unallocated_actual_account_remainder', ['au_annual_2025'] + (['aur6_annual_2026'] if year == 2025 else []),
                     [revenues[y]['observation_id'] for y in fiscal_pair],
                     'VAC会计控制先按50/50桥接自然年；只减去已单独模型化的境外600部分，剩余留UNKNOWN来源／其他类别，绝不全部按访客国籍分配。2025缺下一FY，以最近会计运行率为中心±20%。边际范围与访客分配负相关，不能当独立误差。',
                     {'calendar_receipts_target_AUD': {'center': native_total, 'lower': target_low, 'upper': target_high},
                      'fiscal_receipts_AUD': {str(y): revenues[y]['value'] for y in (2024, 2025)},
                      'calendar_bridge': '0.5*FY2023/24 + 0.5*FY2024/25' if year == 2024 else 'latest FY2024/25 annual run rate; unavailable next FY assumed unchanged',
                      'known_visitor_allocation_AUD': visitor_center,
                      'remainder_identity': 'calendar target minus known offshore600 allocation',
                      'source_unallocated': True, 'contains_unidentified_visa_groups': True,
                      'interval_dependency': 'remainder decreases when allocated visitor estimate rises'} if year == 2024 else revenue_parameters)
            if year == 2025:
                self.flows[-1]['notes'] = (
                    'VAC签证申请费收入按FY2024/25与FY2025/26各半桥接自然年，固定收入控制，不再使用缺FY±20%场景。'
                    '这是按收入确认政策记录的会计收入，与现金流收款分列；半年季节性为模型假设。'
                    '只减去单独模型化的境外600，剩余留UNKNOWN来源／未识别类别。访客与剩余边际范围负相关。')
            self.models.append({
                'model_id': f'au_vac_calendar_{year}', 'destination': 'AUS', 'year': year,
                'status': 'official_FY_recognised_revenue_plus_calendar_bridge_and_partial_nationality_allocation',
                'center_AUD': native_total, 'lower_AUD': target_low, 'upper_AUD': target_high,
                'allocated_visitor_AUD': visitor_center, 'unknown_other_AUD': remainder,
                'center_reconciles_to_control': abs(visitor_center + remainder - native_total) < .01,
                'source_ids': ['au_annual_2025', 'au_visitor_grants_pivot', 'au_visitor_2025_06'] +
                              (['aur6_annual_2026', 'aur6_visitor_2026_06'] if year == 2025 else []),
                'accounting_basis': 'recognised_administered_VAC_revenue',
                'cash_received_not_revenue': True,
                'calendar_bridge': '0.5*FY2023/24 + 0.5*FY2024/25' if year == 2024 else '0.5*FY2024/25 + 0.5*FY2025/26',
                'throughput_source_status': 'FY2025/26 provisional' if year == 2025 else 'existing FY2023/24 and FY2024/25',
                'limitations': ['VAC total covers visa and migration categories wider than the visitor observations.',
                                'Calendar bridge is modeled with fixed equal half-year seasonality; neither FY is relabeled an observed calendar-year total.',
                                'Recognised administered VAC revenue is distinct from the administered cash-received leaf.',
                                'Nationalities of student/work/family and onshore600 receipts are unallocated.',
                                'Visitor and remainder marginal bounds are correlated; summing their marginal endpoints overstates total uncertainty.'],
            })

    def russia(self):
        rules = read(RU / 'fee_rules.json')
        adult = next(r for r in rules if r['rule_id'] == 'RUS-evisa-adult-government')
        for r in read(RU / 'russia_evisa_annual.json'):
            year = r['year']
            if year not in (2024, 2025):
                continue
            payer = entity(r.get('origin') or r['origin_as_published'])
            if payer == 'WORLD':
                continue
            quantity = r['issued']
            self.add('ru_evisa_age_mix', payer, 'RUS', year, 'visitor',
                     quantity * adult['amount'] * .95, quantity * adult['amount'] * .9,
                     quantity * adult['amount'], 'USD', quantity, 'evisas_issued',
                     [r['source_id'], adult['source_id']],
                     [f'ext_russia_evisa_annual_{i}_issued' for i, x in enumerate(read(RU / 'russia_evisa_annual.json')) if x == r],
                     '统一电子签USD40政府费；未满6岁免费份额中心5%、敏感性0–10%。按国籍签发数建模，不含支付附加费。失败申请付款数量未识别，纸签另外留金额缺口。',
                     {'nationality_original': r['origin_as_published'], 'issued': quantity,
                      'under6_share': {'center': .05, 'lower': 0, 'upper': .10},
                      'adult_government_fee_USD': adult['amount'], 'checkout_additional_costs_excluded': True,
                      'unissued_paid_application_events_not_observed': True}, visa_type='unified_evisa')
        paper = [r for r in read(RU / 'russia_consular_annual.json') if r['year'] in (2024, 2025)]
        self.models.append({
            'model_id': 'ru_evisa_age_mix', 'destination': 'RUS', 'years': [2024, 2025],
            'status': 'working_evisa_estimate_with_unquantified_paper_gap',
            'formula': 'nationality evisas issued * USD40 * (1-under6 share)',
            'parameters': {'under6_share': {'center': .05, 'lower': 0, 'upper': .10}},
            'paper_visa_gap': [{'year': r['year'], 'issued': r['total'], 'amount': None,
                                'source_id': r['source_id']} for r in paper],
            'paper_treatment': 'No applicable paper tariff in frozen fee_rules. Issuing-post location is not nationality. No paper amount edge invented; no USD40 evisa price assigned to paper visas.',
            'limitations': ['Age composition is an unfitted model parameter.',
                            'Unsuccessful fee-paying evisa applications are not counted.',
                            'Paper visas have counts but no amount estimate; Russia total remains incomplete.'],
        })


def main():
    model = Model()
    model.japan()
    model.new_zealand()
    model.australia()
    model.russia()
    # Japan publishes both 中国（香港） and 香港SAR as distinct source rows.
    # They share the HKG jurisdiction node but keep separate source parameters;
    # special DI/travel-document rows retain their independent RAW source codes.
    combined = {}
    for row in model.flows:
        if row['id'] not in combined:
            combined[row['id']] = row
            continue
        previous = combined[row['id']]
        if 'source_components' not in previous['parameters']:
            previous['parameters'] = {'source_components': [previous['parameters']],
                                      'aggregation': 'distinct source-label rows sharing one normalized payer jurisdiction; no DI/passport-category relabeling'}
        previous['parameters']['source_components'].append(row['parameters'])
        for key in ('amount', 'lower', 'upper', 'quantity'):
            previous[key] += row[key]
        previous['source_ids'] = unique(previous['source_ids'] + row['source_ids'])
        previous['observation_ids'] = unique(previous['observation_ids'] + row['observation_ids'])
    model.flows = list(combined.values())
    model.flows.sort(key=lambda r: (r['receiver'], r['year'], r['payer'], r['visa_group']))
    ids = [r['id'] for r in model.flows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate model edge identifiers after entity normalization')
    subtotals = []
    for destination in ('JPN', 'NZL', 'AUS', 'RUS'):
        for year in (2024, 2025):
            rr = [r for r in model.flows if r['receiver'] == destination and r['year'] == year]
            subtotals.append({'destination': destination, 'year': year, 'currency': rr[0]['currency'],
                              'amount': sum(r['amount'] for r in rr),
                              'lower': sum(r['lower'] for r in rr), 'upper': sum(r['upper'] for r in rr),
                              'edge_count': len(rr)})
    # Destination totals use joint parameter scenarios rather than adding
    # mutually incompatible purpose-level Frechet bounds or correlated residuals.
    japanese_source = defaultdict(dict)
    for row in model.observations:
        if row['destination'] == 'Japan' and row.get('basis') == 'nationality':
            japanese_source[row['year'], row['nationality']][row['visa_type']] = row['value']
    destination_ranges = []
    for subtotal in subtotals:
        destination, year = subtotal['destination'], subtotal['year']
        lower, upper = subtotal['lower'], subtotal['upper']
        if destination == 'JPN':
            lower = upper = 0
            for (source_year, nationality), values in japanese_source.items():
                if source_year != year or entity(nationality) in ('WORLD', 'JPN'):
                    continue
                total, multiple = values['all'], values['multiple_entry_subset']
                free = values['diplomatic'] + values['official']
                if entity(nationality) == 'PHL':
                    free += values['short_stay']
                transit = values['transit']
                normal = total - free - transit
                multiple_low = max(0, multiple - free - transit)
                multiple_high = min(normal, multiple)
                lower += .8 * (3000 * (normal + multiple_low) + 700 * transit)
                upper += 3000 * (normal + multiple_high) + 700 * transit
            method = ('joint by source nationality: F=diplomatic+official+PHL short-stay; '
                      'H=transit; N=all-F-H; normal multiple=[max(0,M-F-H),min(N,M)]; '
                      'low=.8*(3000*(N+Mlow)+700*H), high=3000*(N+Mhigh)+700*H. '
                      'All nationalities jointly use unknown exemptions20%/0%; center retains feasible purpose allocation.')
        elif destination == 'AUS':
            control = next(r for r in model.models if r.get('model_id') == f'au_vac_calendar_{year}')
            lower, upper = control['lower_AUD'], control['upper_AUD']
            method = ('calendar VAC total control; offshore600 and UNKNOWN remainder are negatively '
                      'correlated allocations and are not independently summed at marginal endpoints; '
                      'fixed50/50 bridge of adjacent complete FY recognised VAC revenue; '
                      'CY2024 uses FY2023/24+FY2024/25, CY2025 uses FY2024/25+FY2025/26. '
                      'Equal half-year seasonality is assumed; cash received is a separate accounting leaf.')
        elif destination == 'NZL':
            method = ('joint common paid/decided=.8/1.2 across all nationalities; work mix jointly '
                      '100% minimum/maximum calendar-weighted source product rate (WH/partnership); '
                      'visitor/student tariff products and fiscal bridge held fixed. Sum native edge amounts.')
        else:
            method = ('joint evisa under6 share10%/0% across all nationalities; USD40 adult government '
                      'tariff held fixed. Paper-visa monetary gap is outside this range.')
        destination_ranges.append({'receiver': destination, 'year': year,
                                   'amount': subtotal['amount'], 'lower': lower, 'upper': upper,
                                   'currency': subtotal['currency'], 'range_method': method})
    result = {'version': '2026.11.15-r2', 'flows': model.flows, 'models': model.models,
              'subtotals': subtotals, 'destination_ranges': destination_ranges,
              'interval_interpretation': 'Working-parameter sensitivity envelopes, not confidence intervals. Correlated/marginal endpoints do not define simultaneous joint outcomes.',
              'inputs': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [
                  AP / 'observations.json', AP / 'fee_rules.json', AP / 'australia_monthly_grants.json',
                  RU / 'russia_evisa_annual.json', RU / 'russia_consular_annual.json', RU / 'fee_rules.json',
                  ROOT / 'data/research/newzealand_history_v5/observations.json',
                  ROOT / 'data/research/newzealand_history_v5/reused_observations.json',
                  ROOT / 'data/research/australia_recent_v6/observations.json',
                  ROOT / 'data/research/australia_recent_v6/sources.json',
                  ROOT / 'data/entity_aliases.json']}}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print(json.dumps({'status': 'pass', 'flows': len(model.flows), 'models': len(model.models),
                      'subtotals': subtotals}, ensure_ascii=False))


if __name__ == '__main__':
    main()
