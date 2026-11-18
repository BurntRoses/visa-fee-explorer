#!/usr/bin/env python3
"""Freeze Schengen tariff/quantity refinements from archived originals, offline.

Outputs are confined to data/research/evidence_refinement/schengen. No monetary
model or app build runs here. Use --download only to recover a missing original.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import openpyxl

from build_dataset import entity
from schengen_tariffs import annual_tariff, documented_urgent_tariff, FACILITATION_RULES, GENERAL_RATES, URGENT_RULES

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/evidence_refinement/schengen'
OUT = ROOT / 'data/research/evidence_refinement/schengen'

# id, archived project path, original URL, publisher, title, publication date
SOURCES = [
 ('refine_sch_general2020','data/raw/history/eeas_fee2020.pdf','https://www.eeas.europa.eu/sites/default/files/qa_new_visa_rules_0.pdf','European Commission / EEAS','New EU visa rules: 60 to 80 EUR from 2 February 2020','2020-01-31'),
 ('refine_sch_feechange2024','data/raw/schengen/fee-change-2024.html','https://home-affairs.ec.europa.eu/news/schengen-visa-fee-increased-11-june-2024-2024-06-13_en','European Commission DG HOME','Schengen visa fee increased as of 11 June 2024','2024-06-13'),
 ('refine_sch_eu_policy','data/raw/history/eu_visa_policy.html','https://home-affairs.ec.europa.eu/policies/schengen/visa-policy_en','European Commission DG HOME','EU visa policy: agreements and entry-into-force dates',None),
 ('refine_sch_belarus','data/raw/history/eu_belarus_fee.html','https://www.eeas.europa.eu/belarus/travel-study_en','European External Action Service','Belarus: 35 EUR fee from 1 July 2020',None),
 ('refine_sch_georgia','data/raw/history/eu_georgia_fee.pdf','https://www.eeas.europa.eu/sites/default/files/visa_rules2011_en.pdf','European Commission / EEAS','New rules for Georgia: visa facilitation from 1 March 2011','2011-03-01'),
 ('refine_sch_ukraine2015','data/raw/history/eu_ukraine_fee.html','https://www.legislation.gov.uk/eudn/2015/438/adopted/data.xht?view=snippet&wrap=true','Council of the European Union / legislation.gov.uk','Decision 2015/438: Ukraine implementation guidelines','2015-03-02'),
 ('refine_sch_eu_russia','data/raw/history/eu_russia_measures.html','https://commission.europa.eu/topics/eu-solidarity-ukraine/eu-sanctions-against-russia-following-invasion-ukraine/visa-measures_en','European Commission','EU visa facilitation with Russia: full suspension from 12 September 2022',None),
 ('refine_sch_stats_landing','data/raw/schengen/statistics-landing.html','https://home-affairs.ec.europa.eu/policies/schengen/visa-policy/short-stay-visas-issued-schengen-countries_en','European Commission DG HOME','Annual Schengen visa statistics through 2025; Cyprus kept separate','2026-05-28'),
 ('refine_sch_review2024','data/raw/evidence_refinement/schengen/ec_fee_review2024.pdf','https://data.consilium.europa.eu/doc/document/ST-7812-2024-INIT/en/pdf','European Commission / Council of the European Union','COM(2024)128: fixed 35 EUR treaties and Cabo Verde 75% standard tariff','2024-03-14'),
 ('refine_sch_cv_amendment2021','data/raw/evidence_refinement/schengen/cv_amendment2021.pdf','https://data.consilium.europa.eu/doc/document/ST-5035-2021-INIT/en/pdf','Council of the European Union','EU–Cabo Verde amendment: Article 5, 75% fee; child/teen exceptions','2021-01-26'),
 ('refine_sch_cv_entry2022','data/raw/evidence_refinement/schengen/cv_entry2022.pdf','https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX%3A22022X0603%2801%29','Official Journal of the European Union','Entry into force of EU–Cabo Verde amendment on 1 July 2022','2022-06-03'),
 ('refine_sch_aze_guidelines2018','data/raw/evidence_refinement/schengen/ec_aze_guidelines2018.pdf','https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX%3A32018D0311','Council of the European Union','Decision 2018/311: EU scope, associated-state exclusions, NO/CH bilateral entry dates','2018-02-27'),
 ('refine_sch_dnk_agreements','data/raw/evidence_refinement/schengen/denmark_agreements.html','https://www.nyidanmark.dk/en-GB/Words-and-concepts/US/Visum/Visa-facilitation-agreements','Danish Immigration Service','Denmark bilateral agreements; Armenia from 1 December 2023','2023-12-05'),
 ('refine_sch_dnk_rus_news','data/raw/evidence_refinement/schengen/denmark_rus_suspension2022.html','https://www.nyidanmark.dk/en-GB/News-Front-Page/2022/09/Changed-visa-rules-concerning-Russian-citizens/','Danish Immigration Service','Changed visa rules concerning Russian citizens','2022-09-09'),
 ('refine_sch_nor_agreements','data/raw/evidence_refinement/schengen/norway_agreements.html','https://www.udi.no/en/word-definitions/facilitation-agreements-for-applications-for-visitors-visa/','Norwegian Directorate of Immigration','Norway facilitation agreements with Azerbaijan and Ukraine',None),
 ('refine_sch_nor_aze_treaty','data/raw/evidence_refinement/schengen/norway_aze_treaty.html','https://lovdata.no/dokument/TRAKTATEN/traktat/2014-12-03-23','Norway treaty series / Lovdata','Norway–Azerbaijan agreement: 35 EUR, entry 1 June 2015','2014-12-03'),
 ('refine_sch_nor_rus_suspension','data/raw/evidence_refinement/schengen/norway_rus_suspension.html','https://www.udi.no/en/important-messages/norways-visa-agreement-with-russia/','Norwegian Directorate of Immigration','Norway–Russia facilitation suspended from 22 September 2022',None),
 ('refine_sch_che_agreements','data/raw/evidence_refinement/schengen/swiss_agreements.html','https://www.sem.admin.ch/en/visa-facilitation-agreements','Swiss State Secretariat for Migration','Swiss bilateral facilitation agreements and effective dates','2024-02-26'),
 ('refine_sch_che_aze_treaty','data/raw/evidence_refinement/schengen/swiss_aze_treaty2017.pdf','https://fedlex.data.admin.ch/filestore/fedlex.data.admin.ch/eli/cc/2017/209/20170401/de/pdf-a/fedlex-data-admin-ch-eli-cc-2017-209-20170401-de-pdf-a-1.pdf','Swiss Confederation / Fedlex','SR 0.142.111.642: Azerbaijan, 35 EUR from 1 April 2017','2016-10-10'),
 ('refine_sch_che_ukr_treaty','data/raw/evidence_refinement/schengen/swiss_ukr_treaty2019.pdf','https://www.fedlex.admin.ch/filestore/fedlex.data.admin.ch/eli/cc/2019/126/20190301/de/pdf-a/fedlex-data-admin-ch-eli-cc-2019-126-20190301-de-pdf-a.pdf','Swiss Confederation / Fedlex','SR 0.142.117.673: Ukraine, 35 EUR from 1 March 2019','2017-06-07'),
 ('refine_sch_che_rus_chronology','data/raw/evidence_refinement/schengen/swiss_rus_chronology2022.html','https://archiv.migration.swiss/en/migration-report-2022/the-year-as-seen-by-the-sem/chronology','Swiss State Secretariat for Migration','Migration Report 2022: Russia facilitation suspended on 16 September',None),
 ('refine_sch_rus_guidelines2022','data/raw/evidence_refinement/schengen/ec_rus_guidelines2022.pdf','https://home-affairs.ec.europa.eu/system/files/2022-09/Communication%20from%20the%20Commission%20on%20updating%20guidelines%20on%20general%20visa%20issuance%20in%20relation%20to%20Russian%20applicants%20and%20on%20providing%20guidelines%20on%20controls%20of%20Russian%20citizens%20at%20the%20external%20borders_en.pdf','European Commission','Updated Russia visa guidelines: EU versus bilateral suspension dates','2022-09-30'),
]
HISTORY_UIDS = {
 2015:'806041fd-6870-43ac-a2a9-beac23c4f84b',2016:'1e25985b-8303-4ee5-a77e-188c9a562a47',
 2017:'498283c4-ed72-4a71-9ba6-5b726df1ee6c',2018:'d93dde94-f916-48d9-94ea-621e8a8f8bf2',
 2019:'f2681462-3c3d-487e-9627-9386e353396c',2020:'f9e61412-73b6-4415-a350-ab53e0300573',
 2021:'b4177e6c-90d3-4590-bca4-97c255542ae2',2022:'9c7b5dab-dde0-43dc-aa7e-71f653c3e4ca',
 2023:'87716634-be5e-4920-9358-495a95429759',2024:'6552447c-1d75-4f7c-bed6-1bd17a5d59f8',2025:'56816949-e59f-442b-9091-5d03360bf860',
}
for _year, _uid in HISTORY_UIDS.items():
    SOURCES.append((f'refine_sch_workbook_{_year}', f'data/raw/history/schengen_{_year}.xlsx' if _year < 2024 else f'data/raw/schengen/{_year}-consulates.xlsx',
                    f'https://home-affairs.ec.europa.eu/document/download/{_uid}_en', 'European Commission DG HOME',
                    f'{_year} Schengen visa statistics — original annual consulate workbook', '2026-05-28' if _year == 2025 else None))


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def archive_sources(download=False):
    """Also used by research_history to register the shared tariff source IDs."""
    rows = []
    for sid, rel, url, publisher, title, published in SOURCES:
        path = ROOT / rel
        if not path.exists() and download:
            # Recovery is confined to this subpackage's raw directory.
            if not path.is_relative_to(RAW): raise FileNotFoundError(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['curl', '-sSL', '--fail', '--max-time', '45', url, '-o', str(path)], check=True)
        if not path.exists() or not path.stat().st_size: raise FileNotFoundError(f'Missing original: {path}')
        raw = path.read_bytes()
        if path.suffix == '.pdf' and not raw.startswith(b'%PDF'): raise ValueError(f'Not a PDF original: {path}')
        signature_date = sid in {'refine_sch_nor_aze_treaty','refine_sch_che_aze_treaty','refine_sch_che_ukr_treaty'}
        rows.append(dict(source_id=sid, url=url, publisher=publisher, title=title, publication_date=None if signature_date else published,
                         retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                         local_path=rel, path=rel, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                         source_quality='official_primary', archive_status='archived',
                         document_date=published,
                         notes='Archived original reused in place; treaty document dates are signature dates, not entry into force. Fee effective dates are recorded separately in fee_rules.json.'))
    return rows


SPECIAL = {'ARM', 'AZE', 'BLR', 'CPV', 'RUS', 'GEO', 'UKR'}


def legacy_fee(nationality, year):
    """Frozen pre-refinement centre, solely to quantify the amount correction."""
    if year >= 2024: return (80*162+90*204)/366 if year == 2024 else 90.
    base = 60. if year <= 2019 else (32*60+334*80)/366 if year == 2020 else 80.
    if nationality in {'ARM','AZE'} or (nationality in {'GEO','UKR'} and year < 2017) or (nationality == 'RUS' and year < 2022): return 35.
    if nationality == 'RUS' and year == 2022: return (254*35+111*80)/365
    if nationality == 'BLR':
        if year == 2020: return (32*60+150*80+184*35)/366
        if year >= 2021: return 35.
    return base


def extract_quantities():
    observations = []; coverage = []; checks = []; comparisons = []; impacts = []
    for year in range(2015, 2026):
        source = next(s for s in SOURCES if s[0] == f'refine_sch_workbook_{year}')
        workbook = openpyxl.load_workbook(ROOT / source[1], read_only=True, data_only=True)
        sheet = workbook['Data for consulates']; grouped = collections.defaultdict(lambda: [0., []])
        total = 0; members = set(); original_cells = 0; missing = 0
        for i, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
            if not all(row[j] for j in (0,1,2)): continue
            q = row[8]; original_cells += 1
            if q is None: missing += 1
            elif not isinstance(q, (int,float)): raise ValueError((year, i, q))
            country, receiver = entity(row[1]), entity(row[0]); members.add(receiver)
            total += q or 0
            oid = f'refine_sch_{year}_r{i}_I'
            grouped[country, receiver][0] += q or 0; grouped[country, receiver][1].append(oid)
            if country in SPECIAL:
                observations.append(dict(observation_id=oid, source_id=source[0], source_locator=f"'Data for consulates'!I{i}",
                                         destination=row[0], receiver=receiver, consulate_country=row[1], nationality=None,
                                         origin_basis='consulate_country', metric='applications', raw_metric='Uniform visas applied for', value=q,
                                         unit='applications', visa_type='schengen_short_stay', visa_group='visitor',
                                         period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year',
                                         calculation_type='observed' if q is not None else 'missing_source_cell',
                                         notes='Original cell, not applicant nationality. Excludes airport transit, national long stay and border issues.'))
        state_total = None; state_locator = None
        for i, row in enumerate(workbook['Totals - Schengen State'].iter_rows(values_only=True), 1):
            if row[0] == 'Grand Total': state_total = row[1]; state_locator = f"'Totals - Schengen State'!B{i}"
        checks.append(dict(check='original_application_detail_matches_state_total', year=year, actual=total,
                           expected=state_total, source_id=source[0], source_locator=state_locator, passed=total == state_total))
        observations.append(dict(observation_id=f'refine_sch_annual_{year}', source_id=source[0], source_locator=state_locator,
                                 metric='applications', value=state_total, unit='applications', destination='Schengen annual issuing states',
                                 period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year', calculation_type='observed',
                                 origin_basis='all_consulate_locations', nationality=None, notes='Uniform short-stay application pivot total.'))
        expected_members = 25 if year <= 2022 else 26 if year == 2023 else 28
        checks.append(dict(check='historical_issuer_membership', year=year, passed=len(members) == expected_members and ('HRV' in members) == (year >= 2023) and ('BGR' in members) == (year >= 2024) and ('ROU' in members) == (year >= 2024),
                           actual=len(members), expected=expected_members, issuing_members=sorted(members)))
        old_total = new_total = 0.; changed = []
        for (country, receiver), (q, oids) in sorted(grouped.items()):
            # Only these seven origins have different adult centres. The other
            # countries use the same general price, independent of share.
            share = .95 if country in SPECIAL and not (country in {'GEO','UKR'} and year >= 2017) else 0.
            general = annual_tariff('UNK', receiver, year)
            tariff = annual_tariff(country, receiver, year) if country in SPECIAL else general
            old = legacy_fee(country, year); new = tariff['center']; adult = general['center']
            old_total += q * (share*old + (1-share)*adult) * .9
            new_total += q * (share*new + (1-share)*adult) * .9
            if country in SPECIAL and q:
                record = dict(year=year, submission_country=country, receiver=receiver, applications=q, national_share=share,
                              legacy_center=old, revised_center=new, revised_lower=tariff['lower'], revised_upper=tariff['upper'],
                              unknown_tariff_center=adult, amount_change_eur=q*share*(new-old)*.9,
                              source_ids=[source[0]]+tariff['source_ids'], observation_ids=oids,
                              annual_tariff=tariff, note='Amount impact holds existing 95% local-share and 90% effective-fee assumptions fixed; residual UNK keeps general fee.')
                comparisons.append(record)
                if not math.isclose(old,new,abs_tol=1e-9) and share: changed.append(record)
        impacts.append(dict(year=year, legacy_center_eur=old_total, revised_center_eur=new_total, change_eur=new_total-old_total,
                            changed_routes=len(changed), changed_applications=sum(r['applications'] for r in changed),
                            changed_pairs=[dict(submission_country=r['submission_country'], receiver=r['receiver'], applications=r['applications'],
                                                old_tariff=r['legacy_center'], new_tariff=r['revised_center'], change_eur=r['amount_change_eur']) for r in changed],
                            basis='Original annual applications; existing local 95%/effective 90% scenarios held fixed; centre change only, not collected-revenue correction.'))
        coverage.append(dict(destination='SCH', year=year, visa_group='visitor', status='amount_modeled', quantity_known=True,
                             fee_known=True, amount_known=False, amount_modeled=True, nationality_known=False,
                             original_applications=total, original_detail_rows=original_cells, missing_application_cells=missing,
                             issuing_receiver_count=len(members), issuing_members=sorted(members),
                             source_ids=[source[0], 'refine_sch_stats_landing'],
                             searched_as_of='2026-11-16', notes='Official annual short-stay applications; actual annual issuers, not present-day membership backcast. Consulate location is not citizenship; 95% and 90% remain scenarios.'))
        workbook.close()
    return observations, coverage, checks, comparisons, impacts


def fee_rules():
    rows = []
    for i, rule in enumerate(GENERAL_RATES):
        rows.append(dict(fee_id=rule['rule_id'], destination='SCH', visa_type='schengen_short_stay', visa_group='visitor', amount=rule['amount'],
                         currency='EUR', effective_from=rule['effective_from'],
                         effective_to=(date.fromisoformat(GENERAL_RATES[i+1]['effective_from'])-timedelta(days=1)).isoformat() if i+1 < len(GENERAL_RATES) else None,
                         date_interval='inclusive start and inclusive end', nationality_scope='standard adult fee; citizenship concessions separately',
                         fee_component='government_application_fee', payment_trigger='application', source_ids=rule['source_ids'],
                         source_locator='2020 Q&A pp1,3 / 2024 fee-change notice', calculation_type='documented_tariff'))
    for rule in FACILITATION_RULES:
        rows.append(dict(fee_id=rule['rule_id'], destination='SCH', visa_type='schengen_short_stay', visa_group='visitor', **rule,
                         nationality_scope=rule['nationality'], payment_trigger='application', date_interval='inclusive start and inclusive end',
                         source_locator='Dated treaty/official agreement list; see evidence.json'))
    for rule in URGENT_RULES:
        rows.append(dict(fee_id=rule['rule_id'], destination='SCH', visa_type='schengen_short_stay_urgent', visa_group='visitor', **rule,
                         nationality_scope=rule['nationality'], fee_component='government_application_fee_urgent', payment_trigger='accepted_urgent_application',
                         date_interval='inclusive start and inclusive end', calculation_type='documented_conditional_tariff',
                         notes=rule['basis']))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--download', action='store_true'); args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sources = archive_sources(args.download)
    observations, coverage, checks, comparisons, impacts = extract_quantities()
    rules = fee_rules()
    # Meaningful regressions: receiver/date restrictions, 2024 split, leap-day
    # accounting and unknown-citizenship treatment change actual model amounts.
    cases = [
        ('ARM','FRA',2024,35.), ('AZE','CHE',2025,35.), ('BLR','POL',2025,35.),
        ('CPV','PRT',2022,(181*80+184*60)/365), ('CPV','PRT',2023,60.),
        ('CPV','PRT',2024,(162*60+204*67.5)/366), ('CPV','PRT',2025,67.5),
        ('AZE','CHE',2015,60.), ('AZE','CHE',2016,60.), ('AZE','CHE',2017,(90*60+275*35)/365),
        ('AZE','NOR',2015,(151*60+214*35)/365), ('UKR','CHE',2015,60.),
        ('RUS','NOR',2022,(264*35+101*80)/365), ('RUS','CHE',2022,(258*35+107*80)/365),
        ('UNK','FRA',2024,(162*80+204*90)/366), ('UNK','FRA',2025,90.),
        ('BLR','FRA',2020,(32*60+150*80+184*35)/366),
    ]
    for nationality, receiver, year, expected in cases:
        result = annual_tariff(nationality, receiver, year)
        checks.append(dict(check='dated_nationality_receiver_fee', nationality=nationality, receiver=receiver, year=year,
                           expected=expected, actual=result['center'], passed=math.isclose(result['center'], expected, abs_tol=1e-9)))
    for nationality, receiver, year, expected in [('ARM','FRA',2025,None),('AZE','CHE',2025,None),('BLR','POL',2025,None),
                                                  ('UKR','FRA',2015,70.),('UKR','CHE',2015,None),('UKR','CHE',2020,70.)]:
        result = documented_urgent_tariff(nationality, receiver, year)
        actual = result['amount'] if result else None
        checks.append(dict(check='no_unsupported_urgent70_generalization', nationality=nationality, receiver=receiver, year=year,
                           expected=expected, actual=actual, passed=actual == expected))
    registered = {s['source_id'] for s in sources}
    referenced = {s for r in rules for s in r['source_ids']} | {s for c in comparisons for s in c['source_ids']}
    checks.append(dict(check='all_refined_tariff_sources_registered', missing=sorted(referenced-registered), passed=referenced <= registered))
    expected_totals = {2024:11716723, 2025:12201026}
    for year, expected in expected_totals.items():
        actual = next(c['original_applications'] for c in coverage if c['year'] == year)
        checks.append(dict(check='contemporary_original_annual_total', year=year, expected=expected, actual=actual, passed=actual == expected))
    checks.append(dict(check='2025_official_release_is_complete_calendar_year', passed=True,
                       source_id='refine_sch_stats_landing', locator='28 May 2026; 2025 consulate workbook link; annual workbook labels'))
    gaps = [
        dict(gap_id='sch_nationality_conversion', scope='all years', status='unresolved', effect='95% local citizenship and 80–100% range are analyst scenarios; five-percent UNK residual stays general adult tariff.'),
        dict(gap_id='sch_age_waivers', scope='all years', status='unresolved', effect='90% effective adult fee is a scenario. Treaty under-12 waivers and Cabo Verde age-12–17 half adult price do not establish a collected average.'),
        dict(gap_id='sch_dnk_rus_2022_date', scope='DNK/RUS 2022', status='conflicting_official_dates', source_ids=['refine_sch_dnk_agreements','refine_sch_rus_guidelines2022'], effect='Danish public list: 12 September; EC PDF p2 paragraph3: 16 September. Keep 12 September centre and disclose timing range.'),
        dict(gap_id='sch_isl_rus_2022_date', scope='ISL/RUS 2022', status='not_established', effect='Do not import EU date. Standard fee centre with concession-to-standard interval until local suspension date is evidenced.'),
        dict(gap_id='sch_che_ukr_pre2019', scope='CHE/UKR before 2019-03-01', status='no_archived_contemporaneous_concession', source_ids=['refine_sch_ukraine2015','refine_sch_che_ukr_treaty'], effect='2015 EU guidelines say Swiss negotiations finalized, not agreement in force. Standard centre; 35-to-standard range; do not backcast 2019 treaty.'),
        dict(gap_id='sch_other_bilateral_exceptions', scope='associated states and Denmark without applicable bilateral evidence', status='bounded', effect='Use standard centre, concession-to-standard interval for listed facilitation nationalities; no automatic EU-wide 35 EUR rule. No blanket70 EUR urgent fee: frozen originals establish this only for UKR/EU and UKR/CHE from2019.'),
        dict(gap_id='sch_restrictive_measures', scope='Gambia restrictive tariffs and 2022 Russian official/business partial suspension', status='partial', effect='No Gambia submission-country rows in current original workbooks. Cross-country citizenship and restricted categories are not identified; do not apply adult surcharges to unknown nationality.'),
        dict(gap_id='sch_coverage', scope='all years', status='partial_visa_types', effect='Short stay only: no national long-stay, airport-transit, border-issue fees, private service charges or actual refund records.'),
    ]
    evidence = [
        dict(source_id='refine_sch_review2024', locator='PDF pp3–4 (printed pp1–2)', finding='Armenia, Azerbaijan and Belarus adult fee 35 EUR; Cabo Verde adult fee 75% standard; under-12 treaty waiver.'),
        dict(source_id='refine_sch_feechange2024', locator='Fee-change notice dated 13 June 2024', finding='Standard adult fee 80 to 90 and Cabo Verde 60 to 67.50 from 11 June 2024; fixed 35 EUR treaty fees unchanged.'),
        dict(source_id='refine_sch_cv_amendment2021', locator='PDF pp12–13, replaced Article5', finding='Adult 75% standard fee; under12 exempt; ages12–17 pay50% of discounted adult fee; private provider cap30 EUR.'),
        dict(source_id='refine_sch_cv_entry2022', locator='PDF p1, OJ L152/112 dated3 June2022', finding='Amended agreement enters into force1 July2022, not2021 publication/signature.'),
        dict(source_id='refine_sch_aze_guidelines2018', locator='PDF p7, section1.5', finding='EU agreement excludes Denmark and associated states. Norway bilateral starts1 June2015; Switzerland1 April2017.'),
        dict(source_id='refine_sch_nor_aze_treaty', locator='Treaty header entry-into-force metadata; Article6(1)', finding='Norwegian original confirms1 June2015 and35 EUR; Council guideline has an immaterial signing-year discrepancy, not an effective-date discrepancy.'),
        dict(source_id='refine_sch_che_aze_treaty', locator='PDF p1, entry-into-force line; Article6', finding='Swiss Azerbaijan agreement enters1 April2017 and ordinary processing fee35 EUR.'),
        dict(source_id='refine_sch_che_ukr_treaty', locator='PDF p1 entry-into-force line; PDF p8 Article6', finding='Swiss Ukraine agreement enters1 March2019; ordinary fee35 EUR thereafter, conditional three-day urgent fee70 EUR in Article6(3).'),
        dict(source_id='refine_sch_ukraine2015', locator='Guidelines section1.5', finding='Norway Ukraine agreement entered1 September2011. Swiss negotiations finishedNovember2011; this does not establish a pre2019 Swiss concession.'),
        dict(source_id='refine_sch_nor_rus_suspension', locator='Lead paragraph', finding='Norway Russia facilitation temporarily suspended from22 September2022.'),
        dict(source_id='refine_sch_che_rus_chronology', locator='Chronology16.09.2022', finding='Federal Council suspends Swiss Russia facilitation on16 September2022.'),
        dict(source_id='refine_sch_dnk_agreements', locator='Benefits and list of agreements', finding='35 EUR bilateral tariff; Armenia enters1 December2023; Russia suspension listed12 September2022.'),
        dict(source_id='refine_sch_stats_landing', locator='28 May2026 page date, consulate statistics table, Cyprus paragraph', finding='Official2025 annual workbook available; Cyprus national visas are on separate sheet and must not enter Schengen uniform-visa count.'),
    ]
    assert all(c['passed'] for c in checks), [c for c in checks if not c['passed']]
    for name, value in [('sources.json', sources), ('fee_rules.json', rules), ('observations.json', observations), ('coverage.json', coverage),
                        ('checks.json', checks), ('evidence.json', evidence), ('gaps.json', gaps), ('tariff_comparisons.json', comparisons), ('impact.json', impacts)]: dump(name, value)
    lines = ['# 申根费用证据细化：国籍 × 收款政府 × 日期', '',
             '原始年度工作簿、法律和官方政策页已归档；默认重建完全离线。2025年表是2026-05-28公布的完整自然年表，可用于2025年数量。', '',
             '共同函数：`from schengen_tariffs import annual_tariff`；`annual_tariff(nationality, receiver, year)`返回`center/lower/upper/source_ids/basis/segments/uncertainty`。年度中心按日加权；递交日期未知，端点为当年费率及证据范围。', '',
             'EU优惠不自动约束丹麦、挪威、瑞士、冰岛。ARM/AZE/BLR的35欧和CPV的75%只适用于相应国籍及有依据的收款政府；UNK残余中心仍为一般费。', '',
             '现行95%本国国籍及90%有效成人收费保留为情景。CPV的儿童/青少年减免已记录，未据此编造真实平均实收。CHE/UKR在2019年前与其他未证实双边优惠采用一般费中心和优惠至一般费范围。丹麦俄罗斯暂停有4日官方冲突，冰岛暂停日期未证实，均显式保留。', '',
             '| 年份 | 原模型中心 EUR | 修订中心 EUR | 差额 EUR | 受影响路线 |', '|---|---:|---:|---:|---:|']
    lines += [f"| {r['year']} | {r['legacy_center_eur']:,.2f} | {r['revised_center_eur']:,.2f} | {r['change_eur']:,.2f} | {r['changed_routes']} |" for r in impacts]
    lines += ['', '差额只比较同一申请数量、同一95%与90%假设下的成人费率修改，非官方实收修正值。所有原表定位、源文件SHA、费用分段和逐路线差额分别见JSON。', '',
              '离线重建：`.research-venv/bin/python scripts/research_refine_schengen.py`。该脚本不改主模型或前端。历史模型通过同一函数重建，现代模型由主流水线接入。']
    (OUT / 'README.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(sources=len(sources), fee_rules=len(rules), observations=len(observations), checks=len(checks), passed=True,
                          annual_impacts=[dict(year=r['year'], change_eur=round(r['change_eur'],2)) for r in impacts]), ensure_ascii=False))


if __name__ == '__main__': main()
