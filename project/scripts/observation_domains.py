"""One semantic boundary for visa activity, finance and travel context.

Coverage describes evidence, not a claim that all events incurred a fee. In
particular, border arrivals/refusals cannot establish visa-application volume.
"""
import re

MOBILITY_METRICS = {
    'entered', 'visitor_arrivals', 'tourist_arrivals', 'tourist_arrivals_total',
    'tourist_arrivals_source_market', 'visa_free_entries',
    'international_tourist_arrivals', 'international_tourist_departures',
    'border_entry_refusals', 'border_crossings', 'foreign_border_crossings',
    'resident_border_crossings', 'mainland_resident_border_crossings',
    'hongkong_macao_taiwan_resident_border_crossings', 'foreign_entries',
    'foreign_visa_free_entry_share', 'foreign_entries_derived_from_rounded_share',
}
DOCUMENT_METRICS = {
    'foreign_visa_and_residence_documents', 'passes_issued', 'permits_issued',
    'visa_permissions_not_visas', 'dubai_entry_permit_transactions_context',
    'ksa_visa_platform_issued_context',
}


def observation_domain(row):
    explicit = row.get('observation_domain')
    if explicit in ('mobility', 'visa_activity', 'document_activity', 'finance', 'rate'):
        return explicit
    metric = str(row.get('metric') or '').strip().lower()
    unit = str(row.get('unit') or '').lower()
    if metric in MOBILITY_METRICS or re.search(r'(?:^|_)(?:arrivals|departures|crossings|excursionists)(?:_|$)', metric):
        return 'mobility'
    if metric in DOCUMENT_METRICS:
        return 'document_activity'
    if any(x in metric for x in ('revenue', 'receipts', 'income', 'budget', 'forecast')) or unit.upper() in {'USD', 'EUR', 'GBP', 'CNY', 'INR', 'AUD', 'CAD'}:
        return 'finance'
    if any(x in metric for x in ('rate', 'share', 'percentage')) or unit in ('percent', 'percentage', '%'):
        return 'rate'
    if any(x in metric for x in ('superseded', 'conflicting')):
        return 'superseded'
    if any(x in metric for x in ('application', 'issued', 'granted', 'approved', 'approval', 'processed', 'decided', 'decision', 'not_issued', 'refused', 'withdrawn', 'lapsed')):
        return 'visa_activity'
    if unit in ('visa_events', 'visas', 'applications_or_decisions', 'applications'):
        return 'visa_activity'
    if metric in ('total', 'diplomatic', 'service', 'common', 'transit', 'business', 'private', 'tourist', 'other') and 'visa' in str(row.get('visa_type', '')).lower():
        return 'visa_activity'
    return 'other'


def has_visa_quantity(row):
    value = row.get('value')
    return isinstance(value, (int, float)) and value >= 0 and observation_domain(row) == 'visa_activity'


def has_mobility_context(row):
    value = row.get('value')
    return isinstance(value, (int, float)) and value >= 0 and observation_domain(row) == 'mobility'
