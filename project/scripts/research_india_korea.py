#!/usr/bin/env python3
"""Offline India/Korea evidence rebuild. Requires pdfplumber, openpyxl, beautifulsoup4.

Visa issues, approval certificates, arrivals, fee rules and actual receipts are
kept as different metrics. This script performs no network requests.
"""
from pathlib import Path
from collections import defaultdict
import csv, hashlib, json, re, zipfile
import pdfplumber, openpyxl
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw'; OUT=ROOT/'data/research/india_korea'; OUT.mkdir(parents=True,exist_ok=True)
DATE='2026-11-15'

def dump(name,rows):
    (OUT/(name+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    if isinstance(rows,list) and rows:
        keys=list(dict.fromkeys(k for r in rows for k in r))
        with (OUT/(name+'.csv')).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
            w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)

def source(sid,url,title,publisher,files,notes=''):
    return dict(source_id=sid,url=url,title=title,publisher=publisher,retrieved_at=DATE,source_quality='official_original',
        files=[dict(path=str((RAW/f).relative_to(ROOT)),sha256=hashlib.sha256((RAW/f).read_bytes()).hexdigest()) for f in files],notes=notes)

sources=[
    source('in_mea2024','https://www.mea.gov.in/images/CPV/140725MEAAnnualReport2024English.pdf','MEA Annual Report 2024, Finance & Budget p307','India Ministry of External Affairs',['india/mea2024_lower.pdf'],'Fiscal receipts through FY2023-24; lowercase images URL returns original PDF.'),
    source('in_medical2024','https://sansad.in/getFile/annex/267/AU403_yunES4.pdf?source=pqars','Rajya Sabha Q403, Issuance of Medical Visa, 6 February 2025','India Ministry of External Affairs / Parliament',['india/medical_question2025.pdf','india/rs403_20250206_lower.pdf'],'The small MEA annex begins printed p2; complete Sansad PDF establishes medical-only scope.'),
    source('in_beijing2026_fees','https://www.eoibeijing.gov.in/page/visa-fees-and-charges/','Beijing visa fees and charges, effective 1 April 2026','Embassy of India, Beijing',['india/beijing_fees.html'],'Current rule only. Do not backdate RMB exchange conversion to 2024.'),
    source('in_etourist_current','https://www.indianvisaonline.gov.in/evisa/images/Etourist_fee_final.pdf','Country/Territory Wise e-Tourist Visa Fee','India Bureau of Immigration',['india/etourist_fees.pdf'],'Table dated 8 September 2026 has 5-year standard USD200, not older USD80; do not backdate to 2024.'),
    source('kr_yearbook2024','https://www.moj.go.kr/bbs/immigration/228/596464/artclView.do','2024 Immigration and Foreign Policy Statistical Yearbook','Korea Ministry of Justice',['korea/yearbook2024_index.html','korea/yearbook2024_excel.zip'],'Visa table is approval certificates, not total visa issues.'),
    source('kr_yearbook2025','https://www.immigration.go.kr/bbs/immigration/228/607939/artclView.do','2025 Immigration and Foreign Policy Statistical Yearbook','Korea Ministry of Justice',['korea/yearbook2025_index.html','korea/yearbook2025_excel.zip'],'Published 30 June 2026. Visa table is approval certificates.'),
    source('kr_chicago2024_fees','https://www.mofa.go.kr/us-chicago-en/brd/m_26753/view.do?page=1&seq=15','VISA Fee, dated 23 February 2024','Korea Consulate General, Chicago',['korea/visa_fee_chicago.html'],'Historical nationality-dependent fee schedule in USD.'),
    source('kr_visa_portal_fees','https://www.visa.go.kr/openPage.do?MENU_ID=10103','Visa application fees and non-refundability','Korea Ministry of Justice Visa Portal',['korea/visa_portal_fees.html'],'Current rule corroborates general fee types; reciprocity/exemptions and group-tour waivers matter.'),
    source('kr_moj2024_accounts','https://www.moj.go.kr/bbs/moj/172/601359/artclView.do','FY2024 Ministry of Justice settlement overview','Korea Ministry of Justice',['korea/moj2024_accounts_index.html','korea/moj2024_accounts.hwp','korea/moj2024_accounts.txt'],'Official accounts separate broad licence/fees and alien-registration fees, but do not isolate visa receipts; excluded from visa revenue.'),
    source('kr_nabo2024_mofa','https://nabo.go.kr/board/file/bulkDown.do?bid=19&idx=8825','Analysis of FY2024 Settlement: Foreign Affairs Committee','Korea National Assembly Budget Office',['korea/nabo2024_mofa.pdf'],'Budget/parliament alternative route examined; total ministry receipts do not isolate visas.'),
]

# 1. Actual visa receipts; passport and other income are separate context rows.
with pdfplumber.open(RAW/'india/mea2024_lower.pdf') as d:
    t=d.pages[307].extract_text()
assert '1396.91' in t and '2023-24' in t
receipts=[]
for fy,passport,visa,other,total in [('2019-20',2522.71,1792.11,856.16,5170.98),('2020-21',583.56,24.85,149.73,758.14),('2021-22',2332.50,316.93,874.18,3523.61),('2022-23',3360.03,1440.10,937.89,5738.02),('2023-24',3543.66,1396.91,881.59,5822.16)]:
    assert round(passport+visa+other,2)==total
    for metric,v in [('visa_fee_receipts',visa),('passport_receipts_excluded',passport),('other_receipts_excluded',other),('ministry_total_excluded',total)]:
        receipts.append(dict(id=f'in_{metric}_{fy}',destination='IND',year=int(fy[:4])+1,period_start=fy[:4]+'-04-01',period_end=str(int(fy[:4])+1)+'-03-31',period_type='fiscal_year',period_label='FY'+fy,metric=metric,value=v,unit='crore INR',amount=round(v*10000000),currency='INR',calculation_type='official_actual_receipts',eligible_visa_revenue=metric=='visa_fee_receipts',source_id='in_mea2024',pdf_page=308,printed_page=307,notes='MEA receipts; visa fees separate from passports and other receipts; source rounded to 0.01 crore.'))

# 2. Medical visas: complete 2019-24 nationality × ordinary/electronic table.
medical=[]; grand=None; serials=[]; original_total_errors=[]
with pdfplumber.open(RAW/'india/rs403_20250206_lower.pdf') as d:
    for pg,p in enumerate(d.pages,1):
        for table in p.extract_tables():
            for row in table:
                if len(row)!=15:continue
                if row[1]=='GrandTotal':grand=[int(re.sub(r'\s','',x)) for x in row[2:]];continue
                if not re.fullmatch(r'\d+\.',row[0] or ''):continue
                serial=int(row[0][:-1]);serials.append(serial)
                nat=re.sub(r'\s+',' ',row[1]).strip()
                vals=[int(re.sub(r'\s','',x)) for x in row[2:]]
                if sum(vals[:12])!=vals[12]:original_total_errors.append(dict(serial=serial,nationality=nat,total=vals[12],sum=sum(vals[:12])))
                for yi,year in enumerate(range(2019,2025)):
                    for ci,channel in enumerate(['ordinary','electronic']):
                        medical.append(dict(id=f'in_med_{serial}_{year}_{channel}',destination='IND',nationality=nat,year=year,period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year',visa_type='medical',channel=channel,metric='visas_issued',value=vals[yi*2+ci],unit='visas',source_id='in_medical2024',annex_pdf_page=pg,complete_pdf_page=pg+1,serial=serial,eligible_all_visa_total=False,notes='Medical-only; not all visa classes, applications, refusals or entries.'))
assert serials==list(range(1,211)),(len(serials),serials[-1])
medical_checks=[]
for yi,year in enumerate(range(2019,2025)):
    for ci,channel in enumerate(['ordinary','electronic']):
        s=sum(r['value'] for r in medical if r['year']==year and r['channel']==channel)
        medical_checks.append(dict(year=year,channel=channel,nationality_sum=s,official_total=grand[yi*2+ci],residual=s-grand[yi*2+ci]))
assert all(x['residual']==0 for x in medical_checks),medical_checks
assert sum(r['value'] for r in medical if r['year']==2024 and r['channel']=='electronic')==35175

# 3. Korea approval certificates, totals only; no inference of paid visa events.
certificates=[];certificate_checks=[]
for year in [2024,2025]:
    folder=RAW/f'korea/yearbook{year}_excel'
    if not folder.exists():zipfile.ZipFile(RAW/f'korea/yearbook{year}_excel.zip').extractall(folder)
    f=next(folder.glob('*사증발급인정서*'));ws=openpyxl.load_workbook(f,data_only=True).active
    rows=list(ws.values);headers=rows[0]
    national=[];official_grand=rows[1][3]
    for rn,row in enumerate(rows[1:],2):
        if row[2]!='총계':continue
        is_nat=bool(row[1]);name=row[1] or row[0]
        scope='nationality' if is_nat else ('grand_total' if name=='총합계' else 'continent_total')
        if is_nat:national.append(row)
        if name=='기타 총계':scope='unspecified_nationality';name='Other/unspecified'
        for ci in range(3,len(headers)):
            v=row[ci] or 0
            certificates.append(dict(id=f'kr_cert_{year}_{rn}_{ci}',destination='KOR',year=year,period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year',nationality=name,geography_scope=scope,visa_type='ALL' if ci==3 else headers[ci],metric='certificate_of_visa_issuance_approval',value=v,unit='certificates',source_id=f'kr_yearbook{year}',file=str(f.relative_to(ROOT)),sheet=ws.title,row=rn,column=ci+1,eligible_visa_fee_events=False,notes='사증발급인정서; preliminary approval certificate, not all visas issued.'))
        assert sum((x or 0) for x in row[4:])==row[3],(year,rn,name)
    unknown=sum(r['value'] for r in certificates if r['year']==year and r['geography_scope']=='unspecified_nationality' and r['visa_type']=='ALL')
    s=sum(r[3] for r in national)+unknown
    assert s==official_grand,(year,s,official_grand)
    certificate_checks.append(dict(year=year,official_total=official_grand,nationality_rows=len(national),unspecified=unknown,nationality_sum=s,residual=s-official_grand))

# 4. Fee rules. Dated 2024 Korea table vs retrieval-date India rules stay separate.
fees=[]
def fee(id,destination,typ,amount,currency,sid,valid_from=None,valid_to=None,**extra):
    fees.append(dict(id=id,destination=destination,visa_type=typ,amount=amount,currency=currency,source_id=sid,effective_from=valid_from,effective_to=valid_to,**extra))
ktxt=BeautifulSoup((RAW/'korea/visa_fee_chicago.html').read_text(),'html.parser').get_text(' ',strip=True)
assert '2024-02-23' in ktxt and 'China $40 $70 $90 $60 $70 $90' in ktxt
for typ,v in [('single_le90',40),('single_gt90',60),('double',70),('multiple',90)]:
    fee('kr_cn_2024_'+typ,'KOR',typ,v,'USD','kr_chicago2024_fees',nationality='CHN',historical_snapshot_date='2024-02-23',component='government_application_fee',mandatory=True,refundable=False,notes='Chinese nationals; group-tour fee waivers and diplomatic exemptions excluded. Exact underlying effective date not printed; 2024 dated official snapshot.')
ptxt=BeautifulSoup((RAW/'korea/visa_portal_fees.html').read_text(),'html.parser').get_text(' ',strip=True)
assert '40 달러' in ptxt and '반환되지 않습니다' in ptxt
for typ,v in [('single_le90',40),('single_gt90',60),('double',70),('multiple',90),('chinese_group_standard_before_waivers',15)]:
    fee('kr_current_'+typ,'KOR',typ,v,'USD','kr_visa_portal_fees',component='government_application_fee',refundable=False,validity_status='retrieval_date_rule',notes='Reciprocity and international agreements may change rates; group standard does not override temporary waivers.')
btxt=BeautifulSoup((RAW/'india/beijing_fees.html').read_text(),'html.parser').get_text(' ',strip=True)
assert '01.04.2026' in btxt and '695 21 716' in btxt
for typ,usd,rmb in [('tourist_le1yr',100,695),('tourist_1to5yr',200,1390),('business_le1yr',120,834),('business_1to5yr',250,1738),('student',80,556),('medical_le6mo',80,556),('medical_6to12mo',120,834),('employment_le6mo',120,834),('employment_6to12mo',200,1390),('employment_1to5yr',300,2085),('transit',20,139)]:
    fee('in_beijing_2026_'+typ,'IND',typ,rmb,'CNY','in_beijing2026_fees','2026-04-01',component='government_visa_fee',nationality='CHN',usd_schedule_amount=usd,notes='General schedule, China not listed as a reciprocal exception; ICWF RMB21 and contractor/payment service charges separate. Not a 2024 rule.')
fee('in_beijing_2026_icwf','IND','all',21,'CNY','in_beijing2026_fees','2026-04-01',component='government_welfare_surcharge',nationality='CHN',notes='ICWF; separate from base visa fee and service provider fee.')
etourist_serials=[]
with pdfplumber.open(RAW/'india/etourist_fees.pdf') as d:
    assert '08-September-2026' in d.pages[-1].extract_text()
    for pg,p in enumerate(d.pages,1):
        for table in p.extract_tables():
            for row in table:
                row=[x for x in row if x is not None]
                if len(row)!=6 or not re.fullmatch(r'\d+',row[0] or ''):continue
                etourist_serials.append(int(row[0]))
                for ci,typ in enumerate(['etourist_30d_apr_jun','etourist_30d_jul_mar','etourist_1yr','etourist_5yr'],2):
                    v=int(re.sub(r'\s','',row[ci]))
                    fee(f'in_etourist_current_{row[0]}_{typ}','IND',typ,v,'USD','in_etourist_current',nationality=row[1],component='government_evisa_fee',validity_status='official_snapshot_dated_2026_09_08',snapshot_date='2026-09-08',pdf_page=pg,notes='Table dated 8 September 2026; do not apply to 2024. Additional 3% bank charge. No China row in this e-tourist table.')

assert etourist_serials==list(range(1,176)),etourist_serials

gaps=[
 dict(destination='IND',metric='all_visas_issued_2024_2025_by_nationality',status='not_obtained',attempts=['MEA annual report original (CPV chapter has no all-visa nationality table)','MHA annual-report 2024-25 index and file route (original fetch SSL EOF; web file exceeds 20MB)','MEA dashboard official direct HTTPS/HTTP/www (TLS EOF/timeouts)','Parliament RS403 complete answer and annex (medical-only, excluded from all-class total)','Secondary MapsDaily annual regular/evisa totals identified but not substituted for official original'],next_path='MEA/BoI RTI or dashboard original exported series; then compare regular/eVisa counts by nationality and purpose.',estimation_path='Keep all-class China→India quantity null. Medical13 is separate fine class. Never multiply tourist entries or media June2024 approx2000 by annual tariff.'),
 dict(destination='IND',metric='visa_receipts_FY2024_25',status='not_obtained',attempts=['MEA Annual Report2024 actuals finish FY2023-24','Parliament external-affairs demands FY2025-26 table reports FY2024-25 through Sep2024 only and budget/revised estimates','MEA Accounts at Glance latest linked edition2016-17'],next_path='Newer MEA finance annual actuals/Union Finance Accounts detailed0070-60-117.',estimation_path='Display FY2023-24 actual INR13.9691bn with precise period; no annualisation of Sep partial or budget estimates.'),
 dict(destination='KOR',metric='all_visas_issued_applications_refusals_2024_2025',status='not_obtained',attempts=['MOJ2024 and2025 full Excel yearbook inventories','KOSIS certificate table lead','MOFA/data.go.kr nationality visa issuance searches','Official Visa Portal fee and application guidance'],next_path='MOJ/MOFA overseas consular-issuance statistics or information-disclosure request, separating visa issues and recognition certificates.',estimation_path='Approval certificates192752/200437 and China6434/5128 remain context, excluded from fee-flow. Entries not used as visa issues.'),
 dict(destination='KOR',metric='visa_fee_actual_receipts_2024_2025',status='not_separately_identified',attempts=['MOJ2024 settlement HWP original decoded: license/fees KRW23.925bn and alien-registration/revenue-replacement fees KRW19.342bn have broader/nonvisa scope','NABO FY2024 Foreign Affairs settlement308-page PDF searched; no isolated visa-fee line','MOFA consular fee guidance separates country-specific tariffs'],next_path='Detailed MOFA/MOJ revenue-account breakdown and overseas missions consular collections.',estimation_path='No whole-country visa revenue produced. No tariff × certificate or arrival proxy. Group and nationality waivers require actual fee-event denominator.'),
]

observations=[]
for r in receipts:
    observations.append(dict(observation_id=r['id'],destination='IND',metric=r['metric'],value=r['amount'],unit='INR',period_start=r['period_start'],period_end=r['period_end'],period_type=r['period_type'],source_id=r['source_id'],calculation_type=r['calculation_type'],page=308))
for r in medical+certificates:
    observations.append(dict(observation_id=r['id'],destination=r['destination'],nationality=r['nationality'],metric=r['metric'],visa_type=r['visa_type'],channel=r.get('channel'),value=r['value'],unit=r['unit'],period_start=r['period_start'],period_end=r['period_end'],period_type=r['period_type'],source_id=r['source_id'],eligible_all_visa_fee_events=False))

for name,rows in [('sources',sources),('actual_receipts',receipts),('medical_visas',medical),('korea_approval_certificates',certificates),('fee_rules',fees),('observations',observations),('coverage_gaps',gaps)]:dump(name,rows)
dump('validation',dict(as_of=DATE,medical_country_count=len(serials),medical_row_count=len(medical),medical_published_grand_residuals=medical_checks,medical_original_row_total_errors=original_total_errors,korea_certificates=certificate_checks,source_count=len(sources),observation_count=len(observations),fee_rule_count=len(fees),etourist_country_count=len(etourist_serials),excluded=['India ordinary/evisa all-class total not inferred','Korea approval certificate not counted as visa issuance','India current fees not backdated','Passport/OCI/residence and total ministry receipts not visa revenue']))
print(json.dumps(dict(sources=len(sources),observations=len(observations),medical=len(medical),korea_certificates=len(certificates),fees=len(fees),medical_original_row_total_errors=original_total_errors),ensure_ascii=False))
