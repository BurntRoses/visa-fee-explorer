#!/usr/bin/env python3
"""Extract the archived UK/Canada evidence; offline by default.

Run with the project Python containing openpyxl and beautifulsoup4.
--download refreshes registered public sources, writing atomically to avoid
leaving a partial XLSX in the evidence archive. No currency conversion here.
"""
from __future__ import annotations
import argparse, calendar, csv, hashlib, json, re, urllib.request, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import openpyxl
from openpyxl.utils import get_column_letter
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/research/uk_canada'
STAMP = '2026-11-15'
UK_URL = 'https://assets.publishing.service.gov.uk/media/6a85c3741b45e4e555421eda/entry-clearance-visa-outcomes-datasets-jun-2026.xlsx'
V1_URL = 'https://www.ircc.canada.ca/opendata-donneesouvertes/data/Open%20Data%20-%20OPS%20TRV%20V-1%20Approved%20en.xlsx'

def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

def csvout(name, rows):
    if not rows: return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})

def stable(prefix, *args):
    return prefix + '_' + hashlib.sha256(json.dumps(args, ensure_ascii=False).encode()).hexdigest()[:16]

def sources():
    urls = json.loads((OUT / 'download_urls.json').read_text())
    urls.update({'uk_entry_clearance_jun2026':['uk',UK_URL], 'ca_visitor_v1':['canada',V1_URL],
                 'uk_statistics_index':['uk','https://www.gov.uk/government/statistical-data-sets/immigration-system-statistics-data-tables']})
    special = {'uk_entry_clearance_jun2026':'entry-clearance-jun2026.xlsx','ca_visitor_v1':'ircc-v1.xlsx',
               'uk_statistics_index':'data-tables.html'}
    result=[]
    for sid,(country,url) in urls.items():
        name = special.get(sid, sid+'.pdf' if '.pdf' in url else sid+'.html')
        if sid in ['ca_study-processed','ca_tr-intake','ca_tr-approved','ca_tr-processed']:
            name=sid[3:]+'.xlsx'
        p=ROOT/'data/raw'/country/name
        if not p.exists(): continue
        content=p.read_bytes()
        if p.suffix == '.html':
            soup=BeautifulSoup(content,'html.parser')
            title=soup.title.get_text(' ',strip=True) if soup.title else sid
        elif p.suffix=='.xlsx':
            title='UK Entry Clearance Visas: Applications and Outcomes, YE June 2026' if country=='uk' else openpyxl.load_workbook(p,read_only=True,data_only=True)['Page']['A3'].value
        else: title=sid.replace('_',' ')
        result.append(dict(source_id=sid,url=url,agency='UK Home Office' if country=='uk' else 'Immigration, Refugees and Citizenship Canada',
                           title=title,retrieved_at=STAMP,local_path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(content).hexdigest(),
                           bytes=len(content),source_quality='official_primary',
                           data_version='Published 27 August 2026; data through 2026 Q2' if sid=='uk_entry_clearance_jun2026' else
                           'MBR as of September 1, 2026; through August 2026' if p.suffix=='.xlsx' else 'Archived on retrieval date'))
    dump('sources.json',result)
    return result

def extract_uk():
    w=openpyxl.load_workbook(ROOT/'data/raw/uk/entry-clearance-jun2026.xlsx',read_only=True,data_only=True)
    raw=[];summary=defaultdict(lambda:dict(value=0,input_ids=[],source_rows=[]));detail=defaultdict(lambda:dict(value=0,input_ids=[],source_rows=[]))
    for sheet,metric in [('Data_Vis_D01','Applications'),('Data_Vis_D02','Decisions')]:
        s=w[sheet]
        for rn,r in enumerate(s.iter_rows(min_row=5,values_only=True),5):
            if str(r[0]) not in ('2024','2025'):continue
            year=int(r[0]);q=int(str(r[1])[-1]);endmonth=q*3
            outcome=r[8] if metric=='Decisions' else 'Applications';value=r[-1]
            if not isinstance(value,(int,float)):raise ValueError((sheet,rn,r))
            locator=f'{sheet}!{get_column_letter(len(r))}{rn}'
            oid=stable('uk_obs',sheet,locator,*r[:-1]);source='uk_entry_clearance_jun2026'
            record=dict(observation_id=oid,destination='GBR',origin_name=r[2],jurisdiction_basis='nationality',year=year,quarter=q,
                        period_start=f'{year}-{endmonth-2:02d}-01',period_end=f'{year}-{endmonth:02d}-{calendar.monthrange(year,endmonth)[1]}',
                        period_type='calendar_quarter',visa_type_group=r[4],visa_type=r[5],visa_type_subgroup=r[6],applicant_type=r[7],
                        metric=outcome,value=value,unit='applications' if outcome=='Applications' else 'decisions',source_id=source,
                        locator=locator,source_row=rn,
                        calculation_kind='observed',source_quality='official_primary',
                        count_timing='biometric_enrolment_date' if outcome=='Applications' else 'decision_date')
            raw.append(record)
            for origin in [r[2],'WORLD']:
                key=(year,origin,r[4],outcome)
                summary[key]['value']+=value;summary[key]['input_ids'].append(oid);summary[key]['source_rows'].append(rn)
            key=(year,r[2],r[4],r[5],r[6],r[7],outcome)
            detail[key]['value']+=value;detail[key]['input_ids'].append(oid);detail[key]['source_rows'].append(rn)
    assert len({r['observation_id'] for r in raw})==len(raw)
    csvout('uk_quarterly_observations.csv',raw)
    annual=[]
    for (year,origin,group,outcome),v in sorted(summary.items()):
        annual.append(dict(observation_id=stable('uk_annual',year,origin,group,outcome),destination='GBR',origin_name=origin,
                           jurisdiction_basis='nationality',year=year,period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year',
                           visa_type_group=group,visa_type=group,metric=outcome,value=v['value'],unit='applications' if outcome=='Applications' else 'decisions',
                           source_id='uk_entry_clearance_jun2026',locator=f'{"Data_Vis_D01" if outcome=="Applications" else "Data_Vis_D02"}; Year={year}; Nationality={origin}; Visa type group={group}; Case outcome={outcome}; sum Q1-Q4',
                           input_ids=v['input_ids'],calculation_kind='deterministic_calculation',source_quality='official_primary',
                           count_timing='biometric_enrolment_date' if outcome=='Applications' else 'decision_date',
                           notes='Applications and decisions in the same year are different cohorts; grants/applications is not an approval rate.'))
    dump('uk_annual_summary.json',annual);csvout('uk_annual_summary.csv',annual)
    detailed=[]
    for (year,origin,group,typ,sub,applicant,outcome),v in sorted(detail.items()):
        detailed.append(dict(observation_id=stable('uk_detail',year,origin,group,typ,sub,applicant,outcome),destination='GBR',origin_name=origin,
                             jurisdiction_basis='nationality',year=year,visa_type_group=group,visa_type=typ,visa_type_subgroup=sub,applicant_type=applicant,
                             metric=outcome,value=v['value'],source_id='uk_entry_clearance_jun2026',input_ids=v['input_ids'],source_rows=v['source_rows']))
    csvout('uk_annual_detailed.csv',detailed)
    notes=[]
    for sn in ['Cover_Sheet','Notes','List_of_Fields']:
        notes.extend([sn+': '+' | '.join(str(x) for x in r if x is not None) for r in w[sn].iter_rows(values_only=True) if any(x is not None for x in r)])
    (OUT/'uk_workbook_notes.txt').write_text('\n'.join(notes)+'\n')
    return annual,len(raw)

def extract_canada():
    definitions=[('ircc-v1','ca_visitor_v1','Visitor V-1','Approved'),
                 ('study-processed','ca_study-processed','New study permit','Processed'),
                 ('tr-intake','ca_tr-intake','All temporary residents incl extensions','Applications'),
                 ('tr-approved','ca_tr-approved','All temporary residents incl extensions','Approved'),
                 ('tr-processed','ca_tr-processed','All temporary residents incl extensions','Processed')]
    annual=[];monthly=[];notes=[]
    for name,sid,typ,metric in definitions:
        w=openpyxl.load_workbook(ROOT/f'data/raw/canada/{name}.xlsx',read_only=True,data_only=True);s=w['Page']
        rows=list(s.iter_rows(values_only=True));years=rows[4];months=rows[5]
        cy=None;columns=[]
        for ci,(y,m) in enumerate(zip(years,months),1):
            if isinstance(y,int):cy=y
            if cy not in [2024,2025]:continue
            columns.append((ci,cy,str(m).strip()))
        for rn,r in enumerate(rows[6:],7):
            if not r[0]:continue
            if not any(isinstance(x,(int,float)) or x=='--' for x in r[1:]):
                notes.append(name+f'!A{rn}: '+str(r[0]));continue
            origin='WORLD' if r[0]=='Total' else r[0]
            for ci,year,month in columns:
                val=r[ci-1];supp=val=='--'
                if not supp and not isinstance(val,(int,float)):continue
                annualrow=month=='Total'
                m=0 if annualrow else list(calendar.month_name).index(month)
                d=dict(observation_id=stable('ca_obs',name,year,origin,month),destination='CAN',origin_name=origin,jurisdiction_basis='source_country_as_published',
                       year=year,period_start=f'{year}-01-01' if annualrow else f'{year}-{m:02d}-01',
                       period_end=f'{year}-12-31' if annualrow else f'{year}-{m:02d}-{calendar.monthrange(year,m)[1]}',
                       period_type='calendar_year' if annualrow else 'calendar_month',visa_type_group=typ,visa_type=typ,metric=metric,
                       value=None if supp else val,raw_value=val,unit='persons',source_id=sid,locator=f'Page!{get_column_letter(ci)}{rn}',
                       calculation_kind='observed',source_quality='official_primary',missing_reason='privacy_suppression_1_to_4' if supp else None,
                       lower=1 if supp else None,upper=4 if supp else None,
                       notes='Annual printed total is retained; rounded monthly and country figures need not sum. Source-country definition is not relabelled nationality without a dictionary.')
                (annual if annualrow else monthly).append(d)
    dump('canada_annual_summary.json',annual);csvout('canada_annual_summary.csv',annual);csvout('canada_monthly_observations.csv',monthly)
    (OUT/'canada_workbook_notes.txt').write_text('\n'.join(notes)+'\n')
    return annual,len(monthly)

def html_tables():
    """Archive every fee-table row; curate applicability separately."""
    rows=[]
    for p in sorted((ROOT/'data/raw/uk').glob('uk_fees_*.html')):
        sid=p.stem;soup=BeautifulSoup(p.read_text(),'html.parser')
        for ti,t in enumerate(soup.find_all('table'),1):
            h=t.find_previous(['h2','h3']);section=h.get_text(' ',strip=True) if h else ''
            for ri,tr in enumerate(t.find_all('tr'),1):
                cells=[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'],recursive=False)]
                if len(cells)>=3 and ri>1:
                    rows.append(dict(fee_row_id=stable('uk_fee_row',sid,ti,ri),source_id=sid,locator=f'HTML table {ti}, row {ri}',section=section,
                                     original_fee_label=cells[0],previous_fee=cells[1],new_fee=cells[2],change=cells[3] if len(cells)>3 else '',currency='GBP'))
    csvout('uk_official_fee_table_rows.csv',rows)
    tables=[]
    for p in sorted((ROOT/'data/raw/canada').glob('ca_*.html')):
        soup=BeautifulSoup(p.read_text(),'html.parser')
        for ti,t in enumerate(soup.find_all('table'),1):
            tables.append(dict(source_id=p.stem,table_number=ti,caption=t.caption.get_text(' ',strip=True) if t.caption else '',
                               rows=[[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'],recursive=False)] for tr in t.find_all('tr')]))
    dump('canada_html_tables.json',tables)

def fee_rules():
    rules=[]
    def add(dest,typ,item,amount,start,end,source,locator,**extra):
        rule=dict(fee_rule_id=stable('fee',dest,typ,item,start),destination=dest,visa_type=typ,fee_item=item,amount=amount,
                          currency='GBP' if dest=='GBR' else 'CAD',effective_start=start,effective_end=end,source_id=source,locator=locator,
                          source_quality='official_primary',calculation_kind='observed',payer='applicant',mandatory='conditional',charge_basis='per_application',
                          )
        rule.update(extra);rules.append(rule)
        if dest=='GBR' and item=='government_application_fee':rule['additional_source_ids']=['uk_refund_policy']
    intervals=[('2024-01-01','2025-04-08','uk_fees_apr2024',115,490,719,1420,284,551,1846),
               ('2025-04-09','2026-04-07','uk_fees_apr2025',127,524,769,1519,304,590,1938),
               ('2026-04-08',None,'uk_fees_apr2026',135,558,819,1618,324,628,2064)]
    for start,end,sid,v,student,sw3,sw5,hc3,hc5,family in intervals:
        for typ,a,loc,notes in [
            ('Visitor short',v,'Visas and applications made outside the UK; Visit visa short up to 6 months','Chinese nationals applying in mainland China under the Chinese visa scheme can pay this fee for a 2-year visa; excludes other long-duration tariffs.'),
            ('Student',student,'Study applications outside the UK; Student main applicant and dependants','IHS separately charged where applicable; visa duration may exceed course duration.'),
            ('Skilled Worker up to 3 years',sw3,'Work applications outside UK; standard Skilled Worker up to 3 years','Other tariff applies for Immigration Salary List or Health and Care routes.'),
            ('Skilled Worker over 3 years',sw5,'Work applications outside UK; standard Skilled Worker over 3 years','Other tariff applies for Immigration Salary List or Health and Care routes.'),
            ('Health and Care Worker up to 3 years',hc3,'Work applications outside UK; Health and Care up to 3 years','Health and Care Worker and eligible dependants exempt from IHS.'),
            ('Health and Care Worker over 3 years',hc5,'Work applications outside UK; Health and Care over 3 years','Health and Care Worker and eligible dependants exempt from IHS.'),
            ('Family partner entry clearance',family,'Visas outside UK; Route to Settlement','Applicant may qualify for fee waiver; IHS separate where applicable.')]:
            add('GBR',typ,'government_application_fee',a,start,end,sid,loc,refund_on_refusal=False,notes=notes)
    for amount,start,end,sid in [(400,'2024-01-01','2024-04-09','uk_fees_apr2024'),(432,'2024-04-10','2025-04-08','uk_fees_apr2024'),(475,'2025-04-09','2026-04-07','uk_fees_apr2025'),(506,'2026-04-08',None,'uk_fees_apr2026')]:
        add('GBR','Visitor 2 years standard','government_application_fee',amount,start,end,sid,'Visas outside UK; Visit visa long up to 2 years; fee table footnote 1',refund_on_refusal=False,notes='Chinese visa scheme exception: short visit tariff for eligible Chinese nationals applying in mainland China.')
    for typ,fees in [('Visitor 5 years',[771,848,903]),('Visitor 10 years',[963,1059,1128])]:
        for (start,end,sid,*_),a in zip(intervals,fees):add('GBR',typ,'government_application_fee',a,start,end,sid,'Visas outside UK; Visit visa long',refund_on_refusal=False)
    for typ,old,new in [('IHS standard',624,1035),('IHS student / under18 / Youth Mobility',470,776)]:
        for start,end,a in [('2024-01-01','2024-02-05',old),('2024-02-06',None,new)]:
            add('GBR',typ,'immigration_health_surcharge',a,start,end,'uk_ihs_guidance','IHS costs and calculation; before/after 9am 6 February 2024',
                refund_on_refusal=True,annual_rate=True,charge_basis='per_year_paid_upfront',additional_source_ids=['uk_ihs_refunds'],notes='Annual rate; total visa duration charged upfront in half-year increments. Health and Care exempt. Outside-UK permission up to 6 months exempt. IHS is refunded if refused.')
    for typ,item,a,loc,notes in [
        ('Visitor','government_application_fee',100,'Temporary Resident visa','Per person; family of 5+ travelling together and applying together maximum CAD500; some exemptions.'),
        ('Visitor family','government_family_cap',500,'Temporary Resident visa - maximum fee for family','Family cap; do not add this to single-person tariff.'),
        ('Student','government_application_fee',150,'Study permit (includes extension)','Per person, including extensions; not just new overseas visas.'),
        ('Work permit','government_application_fee',155,'Work permit (includes extensions)','Per person; exemptions and special programs apply.'),
        ('Open work permit','open_work_permit_holder_fee',100,'Open Work Permit Holder','Additional to work permit processing where applicable; distinct refund rules.'),
        ('Biometrics single','biometrics',85,'Biometric','Conditional: most temporary residents age14-79; valid biometrics generally reusable 10 years, even after refusal.'),
        ('Biometrics family','biometrics_family_cap',170,'Biometric - maximum fee for family','Cap for eligible family applying together; do not multiply CAD85 universally.'),
        ('eTA','electronic_travel_authorisation',7,'Electronic Travel Authorization','Separate from visa flow account.'),
        ('Employer compliance','employer_compliance_fee',230,'Employer compliance fee','Employer-paid for applicable LMIA-exempt offers; not applicant outlay.')]:
        extra={'notes':notes}
        if item=='employer_compliance_fee':extra.update(payer='employer',charge_basis='per_job_offer')
        if 'cap' in item:extra.update(charge_basis='per_family_or_group')
        if item=='biometrics':extra.update(charge_basis='per_enrolment',additional_source_ids=['ca_biometrics','ca_bio_reuse'])
        if item=='open_work_permit_holder_fee':extra.update(refund_on_refusal=True,additional_source_ids=['ca_work_refunds'])
        if typ=='Visitor' and item=='government_application_fee':extra.update(refund_on_refusal=False,additional_source_ids=['ca_guide5256'])
        if typ=='Work permit' and item=='government_application_fee':extra.update(refund_on_refusal=False,additional_source_ids=['ca_work_refunds'])
        add('CAN',typ,item,a,'2024-01-01',None,'ca_fees_2024_25',f'Details on each fee; Fee: {loc}',**extra)
    dump('fee_rules.json',rules);csvout('fee_rules.csv',rules)
    return rules

def financial_observations():
    rows=[]
    def add(oid,dest,start,end,metric,value,currency,sid,loc,scope):
        rows.append(dict(observation_id=oid,destination=dest,origin_name='WORLD',period_start=start,period_end=end,period_type='fiscal_year',
                         metric=metric,value=value,unit=currency,source_id=sid,locator=loc,source_quality='official_primary',calculation_kind='deterministic_calculation' if dest=='GBR' else 'observed',scope=scope,
                         raw_value=value/1000 if dest=='GBR' else value,raw_unit=currency+'_thousands' if dest=='GBR' else currency,
                         normalization_formula='raw_value * 1000' if dest=='GBR' else 'identity'))
    for year,val,sid,page,printed in [(2023,2635103000,'uk_accounts_2024_25',256,248),(2024,2978355000,'uk_accounts_2024_25',256,248),(2025,3574088000,'uk_accounts_2025_26',283,278)]:
        add(f'uk_fin_visa_immigration_fy{year}','GBR',f'{year}-04-01',f'{year+1}-03-31','Visa and immigration income',val,'GBP',sid,
            f'PDF page {page}, printed page {printed}, Income note; £000 ×1000','Broad visa and immigration account, including in-country immigration services; not overseas short visitor visa income; IHS excluded. FY2024-25 accounting policy PDF pp242-244 (printed234-236): paid on application, income recognised on decision; deferred income exists, so not cash receipts in same period.')
    for year,val,sid,page,printed in [(2024,2420109000,'uk_accounts_2024_25',256,248),(2025,2318923000,'uk_accounts_2025_26',283,278)]:
        add(f'uk_fin_ihs_retained_fy{year}','GBR',f'{year}-04-01',f'{year+1}-03-31','Immigration Health Surcharge retained income',val,'GBP',sid,
            f'PDF page {page}, printed page {printed}, Income note; £000 ×1000','Retained income; separate £200.769m payable to Consolidated Fund in FY2024-25. Not total cash collected; not visa application fee.')
    # Read the actual labelled group totals rather than treating agency total as visa revenue.
    for fy,sid in [('2024-25','ca_fees_2024_25'),('2025-26','ca_fees_2025_26')]:
        p=ROOT/f'data/raw/canada/{sid}.html';soup=BeautifulSoup(p.read_text(),'html.parser')
        if fy=='2024-25':
            for ti,t in enumerate(soup.find_all('table'),1):
                cap=t.caption.get_text(' ',strip=True) if t.caption else ''
                if 'totals for' not in cap or ti==1:continue
                data=t.find_all('tr')[-1];cells=[c.get_text(' ',strip=True) for c in data.find_all(['th','td'],recursive=False)]
                if len(cells)<3:continue
                value=float(cells[0].replace(',',''));metric=cap.split(':')[0]
                add(stable('ca_fin',fy,metric),'CAN','2024-04-01','2025-03-31',metric+' revenue',value,'CAD',sid,f'HTML table {ti}, caption {cap}; revenue column',
                    'Program-level government fee revenue; Temporary Residence includes eTA, permits/extensions/restoration and employer compliance; Other Service includes biometrics. Not visitor-V1-only.')
        else:
            t=soup.find('table')
            for ri,tr in enumerate(t.find_all('tr')[1:],2):
                cells=[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'],recursive=False)]
                if len(cells)<2 or cells[0]=='Total':continue
                add(stable('ca_fin',fy,cells[0]),'CAN','2025-04-01','2026-03-31',cells[0]+' revenue',float(cells[1].replace(',','')),'CAD',sid,f'HTML table 1, row {ri}, Revenue column',
                    'Program-level government fee revenue; broader than entry visa fees. Do not add program-level rows to their component fees.')
    # Reported per-fee values FY2024-25, only where actual numeric revenue is published.
    soup=BeautifulSoup((ROOT/'data/raw/canada/ca_fees_2024_25.html').read_text(),'html.parser')
    for h in soup.find_all('h4'):
        label=h.get_text(' ',strip=True)
        if not any(k in label.lower() for k in ['temporary resident visa','biometric','study permit','work permit','electronic travel','open work']):continue
        parts=[]
        for sib in h.next_siblings:
            if getattr(sib,'name',None) in ['h3','h4']:break
            if hasattr(sib,'get_text'):parts.append(sib.get_text(' ',strip=True))
        text=' '.join(parts);m=re.search(r'2024–25 total fee revenue \(\$\)\s*:\s*([\d,]+)',text)
        if m:add(stable('ca_fin_fee',label),'CAN','2024-04-01','2025-03-31',label.replace('Fee: ','')+' revenue',int(m.group(1).replace(',','')),'CAD','ca_fees_2024_25',label+'; 2024–25 total fee revenue',
                 'Published per-fee revenue; overlaps program grouping and must not be summed again with that grouping.')
    dump('financial_observations.json',rows);csvout('financial_observations.csv',rows)
    return rows

def extra_canada_observations():
    """Full-year intake broken down by program, from the COW public brief."""
    soup=BeautifulSoup((ROOT/'data/raw/canada/ca_summary_2024_25.html').read_text(),'html.parser')
    tables=soup.find_all('table');table=tables[2];rows=[]
    # Table has one or two leading label cells because of HTML rowspan.
    for rn,tr in enumerate(table.find_all('tr'),1):
        cells=[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'],recursive=False)]
        if len(cells)<4:continue
        vals=cells[-3:]
        if not all(re.fullmatch(r'[\d,]+',x) for x in vals):continue
        labels=cells[:-3];label=' / '.join(labels)
        for yi,year in enumerate([2024,2025]):
            rows.append(dict(observation_id=stable('ca_cow_intake',label,year),destination='CAN',origin_name='WORLD',jurisdiction_basis='global',
                             year=year,period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year',
                             visa_type_group=label,visa_type=label,metric='Applications received',value=int(vals[yi].replace(',','')),unit='persons',
                             source_id='ca_summary_2024_25',locator=f'HTML table 3, row {rn}, {year} Full Year',calculation_kind='observed',
                             source_quality='official_primary',notes='Rounded to nearest 100. Program totals and their subgroups overlap; do not sum parent and child rows.'))
    # Direct official reported global TRV refusal rates, not rates inferred from V-1.
    for year,val in [(2024,54),(2025,51)]:
        rows.append(dict(observation_id=f'ca_trv_refusal_rate_{year}',destination='CAN',origin_name='WORLD',year=year,
                         period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year',visa_type_group='Temporary Resident Visa',
                         visa_type='Temporary Resident Visa',metric='Official global refusal rate',value=val,unit='percent',
                         source_id='ca_refusal_2025',locator='Key messages; global temporary resident visa refusal rate in 2025 compared to 2024',
                         calculation_kind='observed',source_quality='official_primary',notes='Rounded official rate; not V-1-only, not China-specific, not linked to same-year application cohort.'))
    dump('canada_program_intake_and_rates.json',rows);csvout('canada_program_intake_and_rates.csv',rows)
    return rows

def benchmark_models(uk,ca,extra):
    """Tariff scenarios, kept separate from estimates of actual receipts."""
    results=[]
    for r in uk:
        if r['visa_type_group']!='Visitor' or r['metric']!='Applications':continue
        year=r['year'];n=r['value'];base=115 if year==2024 else 127;maxfee=963 if year==2024 else 1059
        if year==2024:
            lo=hi=base*n;centre=lo
        else:
            # Annual extract alone supports the extremes; quarter inputs below narrow
            # the tariff timing scenario, without inventing monthly applications.
            # This cache is built once below, outside repeated source parsing.
            lo=n*115;hi=n*127;centre=None
        results.append(dict(estimate_id=stable('uk_visitor_tariff',year,r['origin_name']),method_id='uk_short_visitor_tariff_benchmark',
                            destination='GBR',origin_name=r['origin_name'],year=year,period_start=r['period_start'],period_end=r['period_end'],
                            target='Visitor application tariff-equivalent, all applications at short/Chinese-scheme tariff',currency='GBP',
                            quantity=n,input_observation_ids=[r['observation_id']],source_ids=['uk_entry_clearance_jun2026','uk_fees_apr2024' if year==2024 else 'uk_fees_apr2025'],
                            benchmark_lower=lo,benchmark_upper=hi,value=centre,interval_type='tariff_timing_scenario' if year==2025 else 'fixed_tariff_benchmark',
                            long_duration_all_max_tariff_value=n*maxfee,calculation_kind='scenario',result_use='scenario_only',
                            assumptions=['All counted applicants pay the standard tariff; fee exemptions/refunds/foreign-currency collection rates not observed.',
                                         'Visa duration mix is not observed. The maximum-tariff figure assigns every application to a 10-year visa; it is a stress scenario, not a plausible central estimate.',
                                         'UK application statistics count biometric enrolment date, which may follow fee payment. Tariff timing uses statistical date as a proxy.'],
                            formula='sum(quarterly applications * applicable short tariff); 2025Q2 has pre/post-9-April tariff uncertainty'))
    raw=list(csv.DictReader((OUT/'uk_quarterly_observations.csv').open(encoding='utf-8-sig')))
    quarter=defaultdict(lambda:defaultdict(int))
    for r in raw:
        if r['metric']=='Applications' and r['visa_type_group']=='Visitor':
            for origin in [r['origin_name'],'WORLD']:quarter[(int(r['year']),origin)][int(r['quarter'])]+=int(r['value'])
    for r in results:
        if r['year']!=2025:continue
        q=quarter[(2025,r['origin_name'])]
        unchanged=q[1]*115+(q[3]+q[4])*127
        r.update(benchmark_lower=unchanged+q[2]*115,benchmark_upper=unchanged+q[2]*127,
                 value=unchanged+q[2]*(8*115+83*127)/91,
                 within_quarter_assumption='Uniform distribution of application dates within 2025Q2; 8 days at GBP115, 83 days at GBP127.',quarterly_applications=dict(q))
    for r in results:
        if r['value'] is not None:
            r['long_duration_mix_sensitivity']=[dict(share_assigned_10_year_tariff=a,value=r['value']*(1-a)+r['long_duration_all_max_tariff_value']*a,
                                                    status='illustrative_parameter_not_observed') for a in [0,0.1,0.25,1]]
    # Canada: expose new full-year official intake × standard fee, instead of
    # substituting the much smaller V-1 issuance count for the application count.
    for r in extra:
        label=r['visa_type_group']
        if r['metric']!='Applications received':continue
        amount=None
        if label=='Temporary Resident Visa':amount=100
        elif label=='Overall Study Permit':amount=150
        elif label=='Overall Work Permit':amount=155
        if amount is None:continue
        n=r['value']
        results.append(dict(estimate_id=stable('ca_intake_tariff',r['year'],label),method_id='ca_program_intake_standard_tariff_benchmark',
                            destination='CAN',origin_name='WORLD',year=r['year'],period_start=r['period_start'],period_end=r['period_end'],
                            target=label+' application standard-tariff equivalent',currency='CAD',quantity=n,value=n*amount,
                            input_observation_ids=[r['observation_id']],source_ids=['ca_summary_2024_25','ca_fees_2024_25'],
                            formula=f'applications received × CAD{amount}',calculation_kind='scenario',result_use='scenario_only',
                            assumptions=['All received applications are standard individually paid applications; exemptions, refunds and family caps unknown.',
                                         'Fee payment and recorded intake dates may differ. Work/student permits must not also be counted as a second new visitor visa fee merely because a counterfoil is issued.'],
                            interval_type='not_a_probability_interval',fee_rule='Government application fee only; biometrics and open-permit/other fees excluded.'))
    dump('tariff_benchmarks.json',results);csvout('tariff_benchmarks.csv',results)
    return results

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.download:
        registry=json.loads((OUT/'sources.json').read_text())
        for s in registry:
            p=ROOT/s['local_path'];tmp=p.with_suffix(p.suffix+'.part')
            with urllib.request.urlopen(s['url'],timeout=180) as r:tmp.write_bytes(r.read())
            if p.suffix=='.xlsx':
                with zipfile.ZipFile(tmp) as z:
                    assert z.testzip() is None
            tmp.replace(p)
    src=sources();uk,nu=extract_uk();ca,nc=extract_canada();html_tables();fees=fee_rules();fin=financial_observations()
    extra=extra_canada_observations();models=benchmark_models(uk,ca,extra)
    checks={
        'uk_raw_rows':nu,'uk_annual_group_rows':len(uk),'canada_monthly_rows':nc,'canada_printed_annual_rows':len(ca),
        'source_count':len(src),'fee_rules':len(fees),'financial_rows':len(fin),'canada_extra_rows':len(extra),'tariff_scenarios':len(models),
        'uk_world_visitors':[{k:r[k] for k in ['year','metric','value','observation_id']} for r in uk if r['origin_name']=='WORLD' and r['visa_type_group']=='Visitor'],
        'uk_china_visitors':[{k:r[k] for k in ['year','metric','value','observation_id']} for r in uk if r['origin_name']=='China' and r['visa_type_group']=='Visitor'],
        'canada_v1_world_china':[{k:r[k] for k in ['origin_name','year','value','locator']} for r in ca if r['source_id']=='ca_visitor_v1' and r['origin_name'] in ['WORLD',"People's Republic of China"]],
    }
    assert len({r['observation_id'] for r in uk})==len(uk)
    assert len({r['observation_id'] for r in ca})==len(ca)
    assert all(r['value'] is None or r['value']>=0 for r in ca)
    for y in [2024,2025]:
        for metric in ['Applications','Issued','Refused','Withdrawn']:
            group=[r for r in uk if r['year']==y and r['visa_type_group']=='Visitor' and r['metric']==metric]
            world=[r for r in group if r['origin_name']=='WORLD']
            assert len(world)==1 and sum(r['value'] for r in group if r['origin_name']!='WORLD')==world[0]['value']
    dump('extraction_checks.json',checks);print(json.dumps(checks,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
