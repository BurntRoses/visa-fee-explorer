#!/usr/bin/env python3
"""Rebuild the US research package from archived source text/PDFs (offline).

Usage: python scripts/research_us.py
Dependencies: pdfplumber (only for the two OMB receipts tables).
Web PDF snapshots preserve every original line plus 1-based PDF pages.
"""
from pathlib import Path
from collections import defaultdict
import csv, hashlib, json, re, unicodedata

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT/'data/raw/us', ROOT/'data/research/us'
DATE='2026-11-15'
OUT.mkdir(parents=True,exist_ok=True)

def dump(name, rows):
    (OUT/(name+'.json')).write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n')
    if rows and isinstance(rows,list) and isinstance(rows[0],dict):
        keys=list(dict.fromkeys(k for r in rows for k in r))
        with (OUT/(name+'.csv')).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
            w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)

def slug(s):
    return re.sub(r'[^a-z0-9]+','_',unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()).strip('_')

def web_lines(name):
    result=[]
    for l in (RAW/name).read_text().splitlines():
        m=re.match(r'L(\d+)(?:@P(\d+)(?:-\d+)?)?: (.*)',l)
        if m:result.append((int(m[1]),int(m[2])+1 if m[2] else None,m[3]))
    return result

def source(sid,url,title,files,quality='official_original'):
    return dict(source_id=sid,url=url,institution='U.S. Department of State' if 'state.gov' in url else 'U.S. Government',title=title,retrieved_at=DATE,
                publication_date=None,source_quality=quality,files=[dict(path=str((RAW/f).relative_to(ROOT)),sha256=hashlib.sha256((RAW/f).read_bytes()).hexdigest()) for f in files])

sources=[
 source('us_detail2024','https://travel.state.gov/content/dam/visas/Statistics/Non-Immigrant-Statistics/NIVDetailTables/FY24NIVDetailTable.pdf','FY 2024 Nonimmigrant Visas Issued, by Nationality and Visa Classification',['detail2024.web.merged.txt'],'official_original_web_text_snapshot'),
 source('us_workload2024','https://travel.state.gov/content/dam/visas/Statistics/Non-Immigrant-Statistics/NIVWorkload/FY%202024NIVWorkloadbyVisaCategory.pdf','Worldwide NIV Workload by Visa Category FY 2024',['us_workload2024.web.txt'],'official_original_web_text_snapshot'),
 source('us_classes2020_2024','https://travel.state.gov/content/dam/visas/Statistics/AnnualReports/FY2024AnnualReport/Table%20XVB.pdf','Table XV(B): Nonimmigrant Visas Issued by Classification, Fiscal Years 2020–2024',['us_classes2020_2024.web.txt'],'official_original_web_text_snapshot'),
 source('us_refusal2024','https://travel.state.gov/content/dam/visas/Statistics/Non-Immigrant-Statistics/RefusalRates/FY24.pdf','FY2024 NIV B Adjusted Refusals by Nationality',['us_refusal2024.web.txt'],'official_original_web_text_snapshot'),
 source('us_refusal2025','https://travel.state.gov/content/dam/visas/Statistics/Non-Immigrant-Statistics/RefusalRates/FY25.pdf','FY2025 NIV B Adjusted Refusals by Nationality',['us_refusal2025.web.txt'],'official_original_web_text_snapshot'),
 source('us_refusal_method','https://travel.state.gov/content/travel/en/legal/visa-law0/visa-statistics/nonimmigrant-visa-statistics/nonimmigrant-b-visa-adjusted-refusal-rates-by-nationality.html','Calculation of the Adjusted Visa Refusal Rate',['us_refusal_method.web.txt'],'official_original_web_text_snapshot'),
 source('us_omb2026','https://www.govinfo.gov/content/pkg/BUDGET-2026-APP/pdf/BUDGET-2026-APP-2-16.pdf','Budget FY2026 Appendix: Department of State; FY2024 actual receipts',['budget2026_state.pdf']),
 source('us_omb2027','https://www.govinfo.gov/content/pkg/BUDGET-2027-APP/pdf/BUDGET-2027-APP-2-15.pdf','Budget FY2027 Appendix: Department of State; FY2025 actual receipts',['budget2027_state_correct.pdf']),
 source('us_fee_schedule','https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/fees/fees-visa-services.html','Fees for Visa Services',['us_fee_schedule.web.txt'],'official_original_web_text_snapshot'),
 source('us_fees2024_cfr','https://www.govinfo.gov/content/pkg/CFR-2024-title22-vol1/pdf/CFR-2024-title22-vol1-part22.pdf','22 CFR Part 22, January 1, 2024 edition: Schedule of Fees',['us_fees2024_cfr.pdf']),
 source('us_mrv2023_notice','https://travel.state.gov/content/travel/en/News/visas-news/niv-fee-increases-to-take-effect-june-17-2023.html','Nonimmigrant Visa Fee Increases to Take Effect June 17, 2023',['us_mrv2023_notice.web.txt'],'official_original_web_text_snapshot'),
 source('us_china_reciprocity','https://travel.state.gov/content/travel/en/us-visas/Visa-Reciprocity-and-Civil-Documents-by-Country/China.html','China reciprocity table (retrieval-date snapshot; historical validity not established)',['us_china_reciprocity.web.txt'],'official_original_web_text_snapshot'),
 source('us_sevis2019','https://www.govinfo.gov/content/pkg/FR-2019-05-23/pdf/2019-10884.pdf','Adjusting Program Fees for the Student and Exchange Visitor Program, 84 FR 23930',['us_sevis2019.pdf']),
 source('us_sevis2024cfr','https://www.govinfo.gov/content/pkg/CFR-2024-title8-vol1/pdf/CFR-2024-title8-vol1-part103-subpartA.pdf','8 CFR 103.7 (2024): SEVIS fees',['us_sevis2024cfr.pdf']),
 source('us_uscis2024_rule','https://www.govinfo.gov/content/pkg/FR-2024-01-31/html/2024-01427.htm','USCIS Fee Schedule Final Rule, effective April 1, 2024',['us_uscis2024_fee_rule.html']),
 source('us_monthly_method','https://travel.state.gov/content/travel/en/legal/visa-law0/visa-statistics/nonimmigrant-visa-statistics/monthly-nonimmigrant-visa-issuances.html','Monthly NIV issuance methodology and preliminary-data warning',['us_monthly_method.web.txt'],'official_original_web_text_snapshot'),
 source('us_statistics_index','https://travel.state.gov/content/travel/en/legal/visa-law0/visa-statistics/nonimmigrant-visa-statistics.html','NIV statistics index (FY2024 latest annual issuance/workload tables)',['us_statistics_index.web.txt'],'official_original_web_text_snapshot'),
 source('us_evus2025','https://www.govinfo.gov/content/pkg/FR-2025-08-28/html/2025-16453.htm','CBP Immigration Fees Required by HR-1 for FY2025',['us_evus2025.web.txt'],'official_original_web_text_snapshot'),
 source('us_evus2026','https://www.govinfo.gov/content/pkg/FR-2025-11-19/html/2025-20304.htm','Certain DHS Immigration Fees Required by HR-1: FY2026 inflation adjustment',['us_evus2026.web.txt'],'official_original_web_text_snapshot'),
 source('us_evus2027','https://www.govinfo.gov/content/pkg/FR-2026-10-01/html/2026-20185.htm','Certain DHS Immigration-Related Fees Required by HR-1: FY2027 inflation adjustment',['us_evus2027.web.txt'],'official_original_web_text_snapshot'),
]

# 1. Complete nationality × class table, including explicit zero cells.
regions={'Africa','Asia','Europe','North America','Oceania','South America','Unknown'}
lines=web_lines('detail2024.web.merged.txt')
assert len(lines)==2450,'Incomplete archived PDF text'
pages=defaultdict(list)
for ln,pg,txt in lines:pages[pg].append((ln,txt))
detail=[]
for pg,content in sorted(pages.items()):
    if pg<=7:
        header=next(t for _,t in content if t.startswith('Fiscal Year 2024'))
        columns=header.split()[3:]
        for ln,t in content:
            m=re.fullmatch(r'(.+?) ((?:[\d,]+ ){12}[\d,]+)',t)
            if not m:continue
            nat=m[1];values=[int(x.replace(',','')) for x in m[2].split()]
            for c,v in zip(columns,values):detail.append(dict(nationality=nat,visa_type=c,value=v,page=pg,line=ln))
    else:
        ci=next(i for i,(_,t) in enumerate(content) if re.match(r'^(C4/D3|G3 |K2 |NATO7 |T5 )',t))
        header=content[ci][1].replace('Grand Total','ALL_NIV')
        columns=header.split()
        names=[(ln,t) for ln,t in content[:ci] if t not in regions and not t.startswith('Fiscal Year') and not t.startswith('Page ')]
        nums=[]
        for ln,t in content[ci+1:]:
            if re.fullmatch(r'[\d,]+(?: [\d,]+)*',t):nums.append((ln,[int(x.replace(',','')) for x in t.split()]))
        assert len(names)==len(nums),(pg,len(names),len(nums))
        for (name_ln,nat),(ln,vals) in zip(names,nums):
            assert len(vals)==len(columns),(pg,nat,len(vals),len(columns))
            for c,v in zip(columns,vals):detail.append(dict(nationality=nat,visa_type=c,value=v,page=pg,line=ln,label_line=name_ln))
by_nat=defaultdict(dict)
for r in detail:
    assert r['visa_type'] not in by_nat[r['nationality']],r
    by_nat[r['nationality']][r['visa_type']]=r['value']
classes=set(by_nat['Grand Total'])-{'ALL_NIV'}
for n,vs in by_nat.items():
    assert set(vs)==classes|{'ALL_NIV'},(n,len(vs))
    assert sum(v for c,v in vs.items() if c!='ALL_NIV')==vs['ALL_NIV'],(n,'row sum mismatch')
nations=[n for n in by_nat if not n.startswith('Totals for ') and n!='Grand Total']
for c in classes|{'ALL_NIV'}:assert sum(by_nat[n][c] for n in nations)==by_nat['Grand Total'][c],c
assert by_nat['Grand Total']['ALL_NIV']==10969936

obs=[]
def observation(nat,typ,metric,val,unit,sid,locator,year=2024,**extra):
    return dict(observation_id=f'us_{year}_{slug(nat)}_{slug(typ)}_{metric}',destination='US',nationality=nat,visa_type=typ,metric=metric,raw_metric_name=metric,value=val,unit=unit,period_start=f'{year-1}-10-01',period_end=f'{year}-09-30',period_type='US_fiscal_year',period_label=f'FY{year}',source_id=sid,locator=locator,calculation_type='direct_observation',**extra)
for r in detail:
    aggregate=r['nationality'].startswith('Totals for ') or r['nationality']=='Grand Total'
    obs.append(observation(r['nationality'],r['visa_type'],'visas_issued',r['value'],'visas','us_detail2024',f'PDF page {r["page"]}; archived line L{r["line"]}',is_aggregate=aggregate))
dump('nationality_class_2024',detail)

# 2. Category-level workload; preserve the published applications column.
work=[]
for ln,pg,t in web_lines('us_workload2024.web.txt'):
    m=re.match(r'^([A-Z][A-Z0-9/]*|Grand Total) ([\d,]+) ([\d,]+) ([\d,]+)',t)
    if not m:continue
    typ=m[1];iss,ref,app=[int(x.replace(',','')) for x in m.groups()[1:]]
    work.append(dict(visa_type=typ,issued=iss,refused=ref,applications=app,identity_residual=app-iss-ref,page=pg,line=ln))
    for metric,v in [('visas_issued',iss),('refused_at_fiscal_year_end',ref),('total_applications_published',app)]:
        o=observation('WORLD',typ,metric,v,'applications' if metric!='visas_issued' else 'visas','us_workload2024',f'PDF page {pg}; archived line L{ln}',is_aggregate=True)
        if metric=='visas_issued':o['observation_id']+='_workload'
        obs.append(o)
assert next(w for w in work if w['visa_type']=='Grand Total')['applications']==14245969
dump('workload2024',work)

# 3. B adjusted refusal rates are unique-applicant/last-action statistics.
rates=[]
for y in [2024,2025]:
    for ln,pg,t in web_lines(f'us_refusal{y}.web.txt'):
        m=re.fullmatch(r'(.+?) (\d+\.\d+)%',t)
        if not m:continue
        n,v=m[1],float(m[2]);rates.append(dict(year=y,nationality=n,adjusted_refusal_rate_percent=v,page=pg,line=ln))
        obs.append(observation(n,'B_ALL','adjusted_refusal_rate',v,'percent',f'us_refusal{y}',f'PDF page {pg}; archived line L{ln}',year=y,definition='Unique applicant counted once with last fiscal-year action; (refusals-overcomes)/(issuances+refusals-overcomes). Not a paid application-event refusal rate. Zero can also mean no adjudications.'))
assert len(rates)==398,(len(rates),'Expected 199 nationality labels each year')
dump('adjusted_refusal_rates',rates)

# 4. Final official class totals for historical trends; no monthly aggregation.
known_codes=classes|{'B1/B2/BCC','B1/B2/BCV','D3','F3','K4','M3','S5','S6','S7'}
trend=[];pending=None
for ln,pg,t in web_lines('us_classes2020_2024.web.txt'):
    first=t.split()[0] if t.split() else ''
    if pending is None and first in known_codes:pending=first
    if t.startswith('Grand Total'):pending='ALL_NIV'
    m=re.search(r'(?<!\S)([\d,]+|-) ([\d,]+|-) ([\d,]+|-) ([\d,]+|-) ([\d,]+|-)$',t)
    if m and pending:
        for year,v in zip(range(2020,2025),m.groups()):
            if v=='-':continue
            v=int(v.replace(',',''));trend.append(dict(year=year,visa_type=pending,value=v,page=pg,line=ln))
            obs.append(observation('WORLD',pending,'visas_issued',v,'visas','us_classes2020_2024',f'Table XV(B), PDF page {pg}, archived line L{ln}, FY{year} column',year=year,is_aggregate=True,revision_series='FY2024_annual_report'))
        pending=None
assert len([x for x in trend if x['visa_type']=='ALL_NIV'])==5
dump('class_trends_2020_2024',trend)

# 5. OMB actual receipts (millions USD); observe the precision of the budget.
import pdfplumber
receipts=[]
for year,name,sid,pageno in [(2024,'budget2026_state.pdf','us_omb2026',673),(2025,'budget2027_state_correct.pdf','us_omb2027',783)]:
    page=pdfplumber.open(RAW/name).pages[2]
    # Left column is the Special and Trust Fund Receipts table; crop prevents
    # same-line values from the separate Program and Financing table at right.
    txt=page.crop((0,0,float(page.width)/2,float(page.height))).extract_text(x_tolerance=1)
    (OUT/f'omb_{year}_receipts_column.txt').write_text(txt+'\n')
    assert 'actual' in txt and 'Machine-Readable' in txt
    val=2561 if year==2024 else 2487
    assert f'{val:,}' in txt
    actual_line=next(t for t in txt.splitlines() if re.search(rf'\b{val:,}\b',t))
    o=observation('WORLD','ALL_MRV_INCLUDING_BCC','mrv_receipts_actual',val,'million_USD',sid,f'Special and Trust Fund Receipts, identification code 019–5713–0–2–153, row 1130 Machine-Readable Visa Fee; printed page {pageno}, PDF page 3, FY{year} actual column',year=year,is_aggregate=True,precision='nearest million USD',raw_metric_name_original='Machine-Readable Visa Fee, Consular and Border Security Programs',scope='MRV fee receipts including border-crossing cards; not all immigration fees; not government profit',excludes=['SEVIS','USCIS petition fees','passport fees','reciprocity issuance fees not separately identified here'])
    receipts.append(o);obs.append(o)
dump('actual_receipts',receipts)

fees=[]
def fee(fid,typ,component,value,source_ids,valid_from=None,valid_to=None,**extra):
    return dict(dict(fee_rule_id=fid,destination='US',nationality='ALL',visa_type=typ,component=component,value=value,currency='USD',valid_from=valid_from,valid_to=valid_to,source_ids=source_ids,mandatory=True,payer='applicant',billing_unit='per_application',included_in_government_visa_account=component in ['MRV','reciprocity']),**extra)
fees += [
 fee('us_mrv_nonpetition_2023','B/F/J/M/C1/D/I/TN/TD/S/T/U','MRV',185,['us_mrv2023_notice','us_fee_schedule'],'2023-06-17',refund_policy='non_refundable',exemptions='Government-sponsored J; diplomatic/charitable/replacement and other fee exemptions apply; not all issued cases necessarily paid standard fee.'),
 fee('us_mrv_petition_2023','H/L/O/P/Q/R','MRV',205,['us_mrv2023_notice','us_fee_schedule'],'2023-06-17',refund_policy='non_refundable'),
 fee('us_mrv_e_2023','E','MRV',315,['us_mrv2023_notice','us_fee_schedule'],'2023-06-17',refund_policy='non_refundable'),
 fee('us_mrv_k','K','MRV',265,['us_fee_schedule','us_fees2024_cfr'],refund_policy='non_refundable',validity_note='Verified in January 1, 2024 CFR edition and retrieval-date fee schedule; original effective date not established.'),
 fee('us_mrv_official_free','A/G/C2/C3/NATO','MRV',0,['us_fee_schedule'],validity_note='Official/diplomatic categories; some other personal exemptions also apply.'),
 fee('us_bcc_regular','BBBCC/BBBCV','MRV',185,['us_fee_schedule'],'2023-06-17',refund_policy='non_refundable',conditions='age 15+ or not qualifying for reduced child price'),
 fee('us_bcc_child','BBBCC/BBBCV','MRV',15,['us_fee_schedule'],refund_policy='non_refundable',conditions='Mexican citizen under 15; parent/guardian has or is applying for BCC; limited validity. Age mix not published.'),
 fee('us_sevis_fm_2019','F1/M1','SEVIS',350,['us_sevis2019','us_sevis2024cfr'],'2019-06-24',billing_unit='per_initial_SEVIS_record',refund_policy='Generally non_refundable; fee transfer/reapplication exceptions exist.',conditions='Initial F/M applicants; dependants F2/M2 do not pay separately; renewals/continuing SEVIS record do not automatically repay.'),
 fee('us_sevis_j_standard_2019','J1','SEVIS',220,['us_sevis2019','us_sevis2024cfr'],'2019-06-24',billing_unit='per_initial_SEVIS_record',conditions='Most J1; J2 exempt; government-sponsored G1/G2/G3/G7 programmes exempt.'),
 fee('us_sevis_j_special_2019','J1','SEVIS',35,['us_sevis2019','us_sevis2024cfr'],'2019-06-24',billing_unit='per_initial_SEVIS_record',conditions='Au pair, camp counselor, summer work/travel.'),
 fee('us_l_blanket_fraud','L1','blanket_L_fraud_prevention',500,['us_fee_schedule'],conditions='Principal applicant covered by blanket L petition only; not every L1 applicant.'),
 fee('us_l_blanket_employer_surcharge','L1','blanket_L_employer_surcharge',4500,['us_fee_schedule'],conditions='Principal blanket L applicant; employer >=50 US employees and >50% H1B/L1.'),
 fee('us_cn_b_reciprocity_current','B1/B2','reciprocity',0,['us_china_reciprocity'],nationality='China - mainland',validity_months=120,billing_unit='per_issuance',validity_note='Observed 2026-11-15; historical effective date not established. Special validity exceptions exist.'),
 fee('us_cn_l_reciprocity_current','L1/L2','reciprocity',105,['us_china_reciprocity'],nationality='China - mainland',validity_months=24,billing_unit='per_issuance',validity_note='Observed 2026-11-15; historical effective date not established.'),
 fee('us_evus_2025','B_10YEAR_CHINA','EVUS',30,['us_evus2025'],'2025-09-30','2025-12-31',nationality='China - mainland',billing_unit='per_enrollment',included_in_government_visa_account=False,conditions='Separate electronic update enrollment, not a new visa fee. Existing valid enrollment not immediately charged again.'),
 fee('us_evus_2026','B_10YEAR_CHINA','EVUS',30.75,['us_evus2026'],'2026-01-01','2026-10-15',nationality='China - mainland',billing_unit='per_enrollment',included_in_government_visa_account=False),
 fee('us_evus_2027','B_10YEAR_CHINA','EVUS',31.75,['us_evus2027'],'2026-10-16',nationality='China - mainland',billing_unit='per_enrollment',included_in_government_visa_account=False),
]
for code,regular,small in [('H1B/H1B1',780,460),('H2A_NAMED_1_25',1090,545),('H2A_UNNAMED',530,460),('H2B_NAMED_1_25',1080,540),('H2B_UNNAMED',580,460),('L',1385,695),('O_1_25',1055,530),('E/H3/P/Q/R/TN_1_25',1015,510)]:
    for band,value in [('regular',regular),('small_or_nonprofit',small)]:
        fees.append(fee(f'us_uscis129_2024_{slug(code)}_{band}',code,'USCIS_I129',value,['us_uscis2024_rule'],'2024-04-01','2024-12-31',payer='employer_petitioner',billing_unit='per_petition',included_in_government_visa_account=False,conditions=f'{band}; small employer means <=25 full-time-equivalent US employees. One petition may cover multiple beneficiaries; not a visa-issuance charge. End date is analytical historical window, not claimed repeal date.',locator='89 FR 6386–6387, 8 CFR 106.2(a)(3)'))
for band,value in [('regular',600),('small',300),('nonprofit',0)]:
    fees.append(fee('us_asylum_2024_'+band,'I129/I129CW/I140','asylum_program_fee',value,['us_uscis2024_rule'],'2024-04-01','2024-12-31',payer='employer_petitioner',billing_unit='per_petition',included_in_government_visa_account=False,conditions=band+'; separate from base petition fee. Historical 2024 window.',locator='89 FR 6391, 8 CFR 106.2(c)(13)'))
fees.append(fee('us_i129f_2024','K1','USCIS_I129F',675,['us_uscis2024_rule'],'2024-04-01','2024-12-31',payer='US_citizen_petitioner',billing_unit='per_petition',included_in_government_visa_account=False,conditions='K3 spouse I129F petition is fee-exempt; historical 2024 window.',locator='89 FR 6387, 8 CFR 106.2(a)(5)'))
dump('fee_rules',fees)

# Standard tariff equivalents: deliberately not called actual receipts.
def nominal_rate(c):
    if c.startswith(('A','G','NATO')) or c in ['C2','C3']:return 0
    if c.startswith(('H','L','O','P','Q','R')):return 205
    if c.startswith('E'):return 315
    if c.startswith('K'):return 265
    if c in ['BBBCC','BBBCV','CW1','CW2','N8','N9','ALL_NIV']:return None
    return 185
derived=[]
for r in detail:
    if r['nationality'] not in nations:continue
    rate=nominal_rate(r['visa_type'])
    if rate is None:continue
    derived.append(dict(metric_id=f'us2024_{slug(r["nationality"])}_{slug(r["visa_type"])}_issuance_tariff_equivalent',nationality=r['nationality'],destination='US',visa_type=r['visa_type'],period_label='FY2024',quantity=r['value'],fee_usd=rate,value_usd=r['value']*rate,calculation_type='deterministic_calculation',measure='standard_tariff_equivalent_of_issued_visas',source_ids=['us_detail2024','us_fee_schedule','us_mrv2023_notice'],observation_ids=[f'us_2024_{slug(r["nationality"])}_{slug(r["visa_type"])}_visas_issued'],method='issued_count * standard_MRV_tariff',limitation='Not actual receipts; excludes refusals, BCC, CW/N unknown fee classes, reciprocity. Free/waived individual cases may occur. J includes unknown government-sponsored fee-exempt share. Fees may have been paid before fiscal year.'))
dump('tariff_equivalents_2024',derived)
dump('observations',obs)
dump('sources',sources)
checks=dict(archived_pdf_lines=len(lines),nationality_labels_including_unknown=len(nations),class_columns=len(classes),detail_cells=len(detail),raw_observations=len(obs),us2024_issued_total=by_nat['Grand Total']['ALL_NIV'],row_and_column_totals='PASS',workload_nonzero_identity_residuals=[w for w in work if w['identity_residual']],refusal_rate_rows=len(rates),latest_final_issuance_year_available_in_official_index=2024,actual_mrv_receipts_usd_millions={r['period_label']:r['value'] for r in receipts})
dump('validation',checks)
print(json.dumps(checks,ensure_ascii=False,indent=2))
