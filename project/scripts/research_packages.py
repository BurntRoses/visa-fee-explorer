"""Shared registration of offline evidence packages and money-model inputs."""
CORE_EVIDENCE_PACKAGES = [
    'schengen_fx', 'us', 'uk_canada', 'asia_pacific', 'china_seasia', 'india_korea', 'turkey_russia_saudi',
]
EXTENSION_PACKAGES = [
    'global_americas_africa', 'global_asia_me_europe', 'history', 'spatial_extension', 'time_space',
    'history_expansion', 'spatial_expansion_v2', 'temporal_expansion_v2', 'uk_history_v2',
    'africa_expansion_v3', 'asia_expansion_v3', 'mobility_context_v4', 'europe_expansion_v4',
    'americas_expansion_v4', 'asia_mobility_expansion_v4', 'africa_fiscal_expansion_v4', 'canada_history_v4',
    'global_recent_mobility_v4', 'china_visa_context_v4', 'us_history_v4',
    'africa_visa_issuance_v5', 'newzealand_history_v5', 'thailand_history_v5',
    'americas_expansion_v6', 'africa_expansion_v6', 'asia_expansion_v6', 'australia_recent_v6', 'europe_fiscal_v6', 'us_recent_v6',
    'middleeast_europe_v7', 'philippines_expansion_v7',
    'south_asia_expansion_v7', 'india_recent_v7', 'r12_public_statistics', 'r12_fiscal',
]
REFINEMENT_PACKAGES = ['evidence_refinement/schengen', 'evidence_refinement/uk_canada', 'evidence_refinement/korea_vietnam']
DATA_PACKAGES = CORE_EVIDENCE_PACKAGES + EXTENSION_PACKAGES + ['demographic_context'] + REFINEMENT_PACKAGES
CONTEXT_PACKAGES = {'mobility_context_v4', 'global_recent_mobility_v4', 'china_visa_context_v4', 'newzealand_history_v5', 'americas_expansion_v6', 'australia_recent_v6', 'us_recent_v6', 'middleeast_europe_v7', 'philippines_expansion_v7', 'india_recent_v7', 'r12_public_statistics'}
MONEY_EXTENSION_PACKAGES = [p for p in EXTENSION_PACKAGES if p not in CONTEXT_PACKAGES]
MONEY_PACKAGES = ['core', 'us', 'uk_canada', 'asia'] + MONEY_EXTENSION_PACKAGES


def active_money_inputs(root):
    """Apply explicit evidence replacements before adding disjoint fee scopes."""
    import json
    packages = {p: json.loads((root/f'data/estimates/{p}_flows.json').read_text())
                for p in MONEY_PACKAGES if (root/f'data/estimates/{p}_flows.json').exists()}
    for replacement in list(packages.values()):
        for rule in replacement.get('replaces', []):
            target = packages[rule['package']]
            removed = set(rule['flow_ids'])
            actual = {r['id'] for r in target['flows'] if r['id'] in removed}
            assert actual == removed, ('replacement input changed', rule, actual)
            target['flows'] = [r for r in target['flows'] if r['id'] not in removed]
            target['models'] = [r for r in target['models'] if r.get('model_id') not in rule.get('model_ids', [])]
            scopes = {(r['receiver'], r['year']) for r in rule.get('range_scopes', [])}
            target['destination_ranges'] = [r for r in target.get('destination_ranges', [])
                                            if (r['receiver'], r['year']) not in scopes]
    return packages
