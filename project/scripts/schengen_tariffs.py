"""Dated adult Schengen tariffs, keyed by citizenship and collecting government.

No network or data build runs at import. The research_refine_schengen.py package
registers every source ID used here. Annual centres weight calendar days because
within-year application dates are unavailable; endpoints are tariff/timing
scenarios, not observed collected fees. Unknown citizenship always uses the
general tariff, never the submission country's concession.
"""
from __future__ import annotations

from datetime import date, timedelta
from copy import deepcopy
from functools import lru_cache


EU_RECEIVERS = tuple(sorted(set('AUT BEL BGR HRV CZE EST FIN FRA DEU GRC HUN ITA LVA LTU LUX MLT NLD POL PRT ROU SVK SVN ESP SWE'.split())))
ASSOCIATED_RECEIVERS = {'DNK', 'CHE', 'NOR', 'ISL', 'LIE'}
GENERAL_RATES = [
    {'rule_id': 'sch_general_pre2020', 'effective_from': '2015-01-01', 'amount': 60., 'source_ids': ['refine_sch_general2020']},
    {'rule_id': 'sch_general_2020', 'effective_from': '2020-02-02', 'amount': 80., 'source_ids': ['refine_sch_general2020']},
    {'rule_id': 'sch_general_2024', 'effective_from': '2024-06-11', 'amount': 90., 'source_ids': ['refine_sch_feechange2024']},
]


def _rule(nationality, receivers, start, end, amount, sources, *, multiplier=False):
    return dict(rule_id=f'sch_{nationality}_{receivers[0]}_{start}', nationality=nationality,
                receivers=list(receivers), effective_from=start, effective_to=end,
                amount=None if multiplier else float(amount), multiplier=float(amount) if multiplier else None,
                currency='EUR', age_scope='adult; child and waiver structures not observed',
                fee_component='government_application_fee', source_ids=sources,
                calculation_type='documented_tariff',
                basis='citizenship and collecting government; not consulate location')


FACILITATION_RULES = [
    _rule('ARM', EU_RECEIVERS, '2014-01-01', None, 35, ['refine_sch_eu_policy', 'refine_sch_review2024']),
    _rule('AZE', EU_RECEIVERS, '2014-09-01', None, 35, ['refine_sch_eu_policy', 'refine_sch_aze_guidelines2018']),
    _rule('BLR', EU_RECEIVERS, '2020-07-01', None, 35, ['refine_sch_belarus', 'refine_sch_review2024']),
    _rule('CPV', EU_RECEIVERS, '2022-07-01', None, .75, ['refine_sch_cv_amendment2021', 'refine_sch_cv_entry2022', 'refine_sch_review2024'], multiplier=True),
    _rule('GEO', EU_RECEIVERS, '2011-03-01', None, 35, ['refine_sch_georgia', 'refine_sch_eu_policy']),
    _rule('UKR', EU_RECEIVERS, '2008-01-01', None, 35, ['refine_sch_ukraine2015', 'refine_sch_eu_policy']),
    _rule('RUS', EU_RECEIVERS, '2007-06-01', '2022-09-11', 35, ['refine_sch_eu_russia', 'refine_sch_rus_guidelines2022']),
    _rule('ARM', ('DNK',), '2023-12-01', None, 35, ['refine_sch_dnk_agreements']),
    _rule('UKR', ('DNK',), '2009-03-01', None, 35, ['refine_sch_dnk_agreements']),
    # Denmark's own public list says 12 September; EC guidance says 16 September.
    # Retain the national-source centre and expose the conflict explicitly below.
    _rule('RUS', ('DNK',), '2009-10-01', '2022-09-11', 35, ['refine_sch_dnk_agreements', 'refine_sch_rus_guidelines2022']),
    _rule('AZE', ('NOR',), '2015-06-01', None, 35, ['refine_sch_nor_aze_treaty', 'refine_sch_aze_guidelines2018']),
    _rule('UKR', ('NOR',), '2011-09-01', None, 35, ['refine_sch_ukraine2015', 'refine_sch_nor_agreements']),
    _rule('RUS', ('NOR',), '2007-06-08', '2022-09-21', 35, ['refine_sch_rus_guidelines2022', 'refine_sch_nor_rus_suspension']),
    _rule('ARM', ('CHE',), '2016-08-01', None, 35, ['refine_sch_che_agreements', 'refine_sch_review2024']),
    _rule('AZE', ('CHE',), '2017-04-01', None, 35, ['refine_sch_che_aze_treaty', 'refine_sch_che_agreements']),
    _rule('GEO', ('CHE',), '2014-01-01', None, 35, ['refine_sch_che_agreements', 'refine_sch_georgia']),
    _rule('UKR', ('CHE',), '2019-03-01', None, 35, ['refine_sch_che_ukr_treaty', 'refine_sch_che_agreements']),
    _rule('RUS', ('CHE',), '2011-02-01', '2022-09-15', 35, ['refine_sch_che_agreements', 'refine_sch_che_rus_chronology']),
    # The archived EC guidance establishes the pre-suspension bilateral agreement.
    # The exact Icelandic suspension date was not archived: use standard centre in
    # 2022 with a 35--80 range rather than silently importing the EU's date.
    _rule('RUS', ('ISL',), '2015-01-01', '2021-12-31', 35, ['refine_sch_rus_guidelines2022', 'refine_sch_eu_russia']),
]

# Only these frozen originals explicitly document a EUR70 expedited charge.
# Do not infer a double fee merely because an ordinary treaty fee is EUR35.
URGENT_RULES = [
    dict(rule_id='sch_UKR_EU_urgent70', nationality='UKR', receivers=list(EU_RECEIVERS),
         effective_from='2015-01-01', effective_to=None, amount=70., currency='EUR',
         source_ids=['refine_sch_ukraine2015'], source_locator='Guidelines Article6(3)',
         basis='Three-day decision requested and accepted, residence-distance conditions and treaty exceptions; 2015 is the modelling start, not the legal origin.'),
    dict(rule_id='sch_UKR_CHE_urgent70', nationality='UKR', receivers=['CHE'],
         effective_from='2019-03-01', effective_to=None, amount=70., currency='EUR',
         source_ids=['refine_sch_che_ukr_treaty'], source_locator='PDF p8, Article6(3)',
         basis='Three-day processing, residence-distance conditions and treaty exceptions; Swiss bilateral entry into force1 March2019.'),
]


def documented_urgent_tariff(nationality: str, receiver: str, year: int):
    """Return a supported expedited rule, or None; never infer an urgent fee."""
    start, end = f'{year}-01-01', f'{year}-12-31'
    rule = next((r for r in URGENT_RULES if r['nationality'] == nationality and receiver in r['receivers']
                 and r['effective_from'] <= end and (r['effective_to'] is None or r['effective_to'] >= start)), None)
    return deepcopy(rule) if rule else None


def _active(rule, day):
    return rule['effective_from'] <= day and (rule.get('effective_to') is None or day <= rule['effective_to'])


def _daily(nationality, receiver, day):
    general = next(r for r in reversed(GENERAL_RATES) if r['effective_from'] <= day)
    value = general['amount']; sources = set(general['source_ids']); lower = value
    matched = next((r for r in FACILITATION_RULES if r['nationality'] == nationality and receiver in r['receivers'] and _active(r, day)), None)
    uncertainty = []
    rule_id = general['rule_id']
    if matched:
        value = general['amount'] * matched['multiplier'] if matched['multiplier'] is not None else matched['amount']
        lower = value; sources.update(matched['source_ids']); rule_id = matched['rule_id']
    elif nationality != 'UNK' and receiver in ASSOCIATED_RECEIVERS and nationality in {'ARM', 'AZE', 'BLR', 'CPV', 'GEO', 'UKR', 'RUS'}:
        # A current EU treaty or a later bilateral treaty is not historical proof
        # of the actual fee in a different collecting jurisdiction.
        lower = .75 * value if nationality == 'CPV' else min(35., value)
        uncertainty.append('No applicable bilateral concession is established for this date; general tariff centre, concession-to-general range.')
        sources.add('refine_sch_aze_guidelines2018')
        if receiver == 'CHE': sources.add('refine_sch_che_agreements')
        if receiver == 'DNK': sources.add('refine_sch_dnk_agreements')
        if receiver == 'NOR': sources.add('refine_sch_nor_agreements')
        # Known full-suspension dates establish standard treatment thereafter.
        suspended = ((receiver == 'CHE' and nationality == 'RUS' and day >= '2022-09-16') or
                     (receiver == 'NOR' and nationality == 'RUS' and day >= '2022-09-22') or
                     (receiver == 'DNK' and nationality == 'RUS' and day >= '2022-09-16'))
        if suspended:
            lower = value; uncertainty = []
            sources.add({'CHE':'refine_sch_che_rus_chronology', 'NOR':'refine_sch_nor_rus_suspension', 'DNK':'refine_sch_dnk_agreements'}[receiver])
    if nationality == 'RUS' and receiver == 'DNK' and '2022-09-12' <= day <= '2022-09-15':
        lower = 35.; uncertainty = ['Denmark source says 12 September 2022; EC guidance says 16 September. National source supplies the centre.']
        sources.update(['refine_sch_dnk_agreements', 'refine_sch_rus_guidelines2022'])
    if nationality == 'RUS' and receiver == 'ISL' and day.startswith('2022'):
        lower = 35.; sources.add('refine_sch_rus_guidelines2022')
        uncertainty = ['Icelandic full-suspension date not established in the archived evidence; standard centre and 35--80 timing range for 2022.']
    return dict(amount=value, lower=lower, upper=value, source_ids=sorted(sources), rule_id=rule_id, uncertainty=uncertainty)


@lru_cache(maxsize=None)
def _annual_tariff(nationality: str, receiver: str, year: int) -> dict:
    """Return center/lower/upper EUR adult fee plus dated sources and segments.

    nationality and receiver are ISO3. Supported modelling years: 2015--2025.
    lower/upper cover application timing and documented evidence gaps only;
    children, exemptions, urgent prices and nationality shares are caller-level
    scenarios. The function never infers citizenship from consulate location.
    """
    if not 2015 <= year <= 2025: raise ValueError(f'Unsupported Schengen modelling year: {year}')
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    current = start; values = []; segments = []; sources = set(); uncertainty = set()
    while current < end:
        item = _daily(nationality, receiver, current.isoformat()); values.append(item)
        sources.update(item['source_ids']); uncertainty.update(item['uncertainty'])
        signature = (item['amount'], item['lower'], item['upper'], item['rule_id'], tuple(item['source_ids']), tuple(item['uncertainty']))
        if not segments or signature != segments[-1]['_signature']:
            segments.append(dict(start=current.isoformat(), end=current.isoformat(), days=1, **item, _signature=signature))
        else: segments[-1]['end'] = current.isoformat(); segments[-1]['days'] += 1
        current += timedelta(days=1)
    for segment in segments: del segment['_signature']
    return dict(center=sum(v['amount'] for v in values)/len(values),
                lower=min(v['lower'] for v in values), upper=max(v['upper'] for v in values),
                currency='EUR', nationality=nationality, receiver=receiver, year=year,
                source_ids=sorted(sources), segments=segments, uncertainty=sorted(uncertainty),
                basis='Adult tariff by citizenship, collecting government and effective date; equal-calendar-day centre because application dates are not observed.',
                unknown_nationality_rule='General adult tariff; no concession inherited from submission country.' if nationality == 'UNK' else None)


def annual_tariff(nationality: str, receiver: str, year: int) -> dict:
    """Return an independent, JSON-serializable dated fee result.

    Ordinary nationalities and EU collecting states share cached calculations;
    the returned citizenship/receiver always retain the caller's actual codes.
    """
    key_nationality = nationality if nationality in {'ARM','AZE','BLR','CPV','GEO','UKR','RUS'} else 'UNK'
    key_receiver = 'FRA' if receiver in EU_RECEIVERS or key_nationality == 'UNK' else receiver
    result = deepcopy(_annual_tariff(key_nationality, key_receiver, year))
    result.update(nationality=nationality, receiver=receiver)
    if nationality != 'UNK': result['unknown_nationality_rule'] = None
    return result
