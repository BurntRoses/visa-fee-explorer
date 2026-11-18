#!/usr/bin/env python3
"""Rebuild APAC official observations from archived originals (offline by default).

Requires openpyxl and pypdf. Does not author or modify official workbooks.
Outputs native, provenance-rich JSON and CSV for the main pipeline.
"""
from __future__ import annotations
import argparse, collections, csv, datetime, hashlib, json, re, ssl, urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from openpyxl import load_workbook
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/research/asia_pacific'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
RESEARCH_CUTOFF = '2026-11-15'

def dump(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{name}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    if rows:
        keys = list(dict.fromkeys(k for row in rows for k in row))
        with (OUT / f'{name}.csv').open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
            for row in rows:
                w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})

def oid(*parts):
    return '_'.join(re.sub(r'[^a-zA-Z0-9]+','-',str(p)).strip('-') for p in parts)

JP_TYPES = {'C':'all','D':'multiple_entry_subset','E':'travel_document','F':'diplomatic','G':'official','H':'transit',
    'I':'short_stay','J':'online_subset','K':'medical_stay','L':'highly_skilled','M':'startup',
    'N':'employment_total','AE':'general_total','AG':'student','AI':'dependent','AJ':'designated_total'}
JP_COUNTRIES = {'中国':'China','フィリピン':'Philippines','ベトナム':'Vietnam','インド':'India','インドネシア':'Indonesia',
    'ロシア':'Russia','ネパール':'Nepal','ミャンマー':'Myanmar','モンゴル':'Mongolia','大韓民国':'South Korea',
    '米国':'United States','アメリカ':'United States','英国':'United Kingdom','カナダ':'Canada','オーストラリア':'Australia',
    'ニュージーランド':'New Zealand','タイ':'Thailand','シンガポール':'Singapore','マレーシア':'Malaysia',
    'ドイツ':'Germany','フランス':'France','イタリア':'Italy','スペイン':'Spain','スイス':'Switzerland',
    'ブラジル':'Brazil','ナイジェリア':'Nigeria','南アフリカ':'South Africa','サウジアラビア':'Saudi Arabia',
    'パキスタン':'Pakistan','バングラデシュ':'Bangladesh','スリランカ':'Sri Lanka','エジプト':'Egypt',
    'トルコ':'Turkey','アラブ首長国連邦':'United Arab Emirates','台湾':'Taiwan','香港':'Hong Kong','合計':'WORLD'}

def japan():
    obs=[]; checks=[]
    for year in (2024,2025):
        wb=load_workbook(ROOT/f'data/raw/japan/visa-{year}.xlsx',data_only=True,read_only=True)
        for sheet in wb:
            basis='nationality' if sheet.title=='国籍別' else 'issuing_mission'
            headers={}; sheetrows=[]
            for rn,row in enumerate(sheet,1):
                if rn==3:
                    headers={c.column_letter:str(c.value).replace('\n',' ') for c in row if c.value is not None}
                if rn<4: continue
                origin=row[1].value if len(row)>1 else None
                if not origin: continue
                for c in row[2:46]:
                    if not isinstance(c.value,(int,float)): continue
                    col=c.column_letter
                    metric='visas_issued'
                    subset=col in ['D','J']
                    group_total=col in ['C','N','AE','AJ']
                    visa=JP_TYPES.get(col,'purpose_'+col)
                    obs.append(dict(observation_id=f'jp_{year}_{basis}_{rn}_{col}',destination='Japan',
                        nationality=JP_COUNTRIES.get(str(origin),str(origin)) if basis=='nationality' else None,
                        nationality_original=str(origin) if basis=='nationality' else None,
                        issuing_mission=str(origin) if basis=='issuing_mission' else None,
                        basis=basis,visa_type=visa,visa_type_original=headers.get(col,{'C':'発給数','N':'就業','AE':'一般','AJ':'特定'}.get(col,col)),
                        metric=metric,original_metric='査証発給数',value=int(c.value),unit='visas',
                        period_start=f'{year}-01-01',period_end=f'{year}-12-31',year_type='calendar',year=year,
                        source_id=f'jp_{year}_workbook',source_locator=f'{sheet.title}!{c.coordinate}',
                        calculation='direct_observation',source_quality='official_primary',
                        aggregation_role='subset' if subset else 'total' if group_total else 'leaf',
                        missing_reason=None))
                if basis=='nationality':sheetrows.append(row)
            if basis=='nationality':
                total=next(r for r in sheetrows if r[1].value=='合計')
                parts=[r for r in sheetrows if r[1].value!='合計']
                for ci in range(2,46):
                    value=total[ci].value
                    if isinstance(value,(int,float)):
                        s=sum(r[ci].value or 0 for r in parts if isinstance(r[ci].value,(int,float)))
                        assert s==value,(year,ci,s,value)
                # Employment and general-purpose groups include their own leaves.
                checks.append({'check':f'jp_{year}_nationality_columns_sum_to_world','result':'pass','nationality_rows':len(parts),
                    'total':total[2].value,'multiple':total[3].value,'short_stay':total[8].value})
    return obs,checks

def australia_pivot():
    path=ROOT/'data/raw/australia/visitor-granted-pivot.xlsx'
    z=zipfile.ZipFile(path)
    root=ET.fromstring(z.read('xl/pivotCache/pivotCacheDefinition1.xml'))
    fields=[];names=[]
    for f in root.find('s:cacheFields',NS):
        names.append(f.attrib['name']);shared=f.find('s:sharedItems',NS)
        fields.append([x.attrib.get('v') for x in shared] if shared is not None else [])
    raw=[];groups=collections.defaultdict(int);world=collections.defaultdict(int)
    records=ET.fromstring(z.read('xl/pivotCache/pivotCacheRecords1.xml'))
    for ri,record in enumerate(records,1):
        vals=[]
        for fi,v in enumerate(record):
            vals.append(fields[fi][int(v.attrib['v'])] if v.tag.endswith('}x') else v.attrib.get('v'))
        fy,qtr,month,subclass,visatype,group,location,country,count=vals
        if fy not in ('2023-24','2024-25','2025-26'): continue
        fy_start=int(fy[:4]);mi=int(month[:2]);calmonth=(mi+5)%12+1;calyear=fy_start if mi<=6 else fy_start+1
        if calyear not in (2024,2025) and fy not in ('2023-24','2024-25'):continue
        n=int(float(count)); m=f'{calyear}-{calmonth:02d}'
        raw.append(dict(year_month=m,financial_year=fy,visa_subclass=subclass,visa_type=visatype,visa_group=group,
            client_location=location,nationality=country,value=n,source_id='au_visitor_grants_pivot',
            source_locator=f'xl/pivotCache/pivotCacheRecords1.xml row {ri}'))
        for period,ystart,yend,ytype,yr in [(fy,f'{fy_start}-07-01',f'{fy_start+1}-06-30','financial',fy_start+1),
                                         (str(calyear),f'{calyear}-01-01',f'{calyear}-12-31','calendar',calyear)]:
            if (ytype=='calendar' and yr not in (2024,2025)) or (ytype=='financial' and fy not in ('2023-24','2024-25')):continue
            groups[(period,ystart,yend,ytype,yr,country,subclass,visatype,group,location)]+=n
            world[(period,ystart,yend,ytype,yr,subclass)]+=n
    dump('australia_monthly_grants',raw)
    obs=[]
    for key,n in sorted(groups.items()):
        period,st,en,yt,yr,country,subclass,visatype,group,location=key
        obs.append(dict(observation_id='au_grants_'+hashlib.sha1('|'.join(map(str,key)).encode()).hexdigest()[:16],
            destination='Australia',nationality=country,basis='nationality',visa_type=subclass.split(' ')[0],
            visa_type_original=subclass,visa_purpose=visatype,visa_group=group,client_location=location,
            metric='visas_granted',original_metric='Sum of Total / Visas Granted',value=n,unit='visas',
            period_start=st,period_end=en,year_type=yt,year=yr,period_label=period,
            source_id='au_visitor_grants_pivot',source_locator=f'pivot cache; FY/Month/Citizenship/Subclass/Group/Location filter; {period}',
            calculation='deterministic_aggregation',source_quality='official_primary',aggregation_role='leaf'))
    for key,n in sorted(world.items()):
        period,st,en,yt,yr,subclass=key
        obs.append(dict(observation_id=oid('au','world',period,subclass.split(' ')[0]),destination='Australia',nationality='WORLD',
            basis='nationality',visa_type=subclass.split(' ')[0],visa_type_original=subclass,
            metric='visas_granted',original_metric='Sum of Total / Visas Granted',value=n,unit='visas',
            period_start=st,period_end=en,year_type=yt,year=yr,period_label=period,
            source_id='au_visitor_grants_pivot',source_locator=f'pivot cache; all citizenships/locations/groups; {period}/{subclass}',
            calculation='deterministic_aggregation',source_quality='official_primary',aggregation_role='total'))
    return obs,[{'check':'au_pivot_records_decoded','result':'pass','all_cache_records':len(records),'selected_monthly_records':len(raw),'all_fields':names}]

def number(x):
    x=x.replace(',','').strip()
    return int(x) if x.isdigit() else None

def australia_pdf():
    """Top citizenship and global application counts. Do not use all-visitor fee x count."""
    obs=[];checks=[]
    # Use June 2025 for internally consistent complete two-year comparison.
    r=PdfReader(ROOT/'data/raw/australia/visitor-june-2025.pdf')
    for pi in [11,12]:
        txt=r.pages[pi].extract_text(extraction_mode='layout')
        table='1.02' if pi==11 else '1.03'
        for line in txt.splitlines():
            m=re.match(r'^\s*([A-Za-z].*?)\s{2,}([\d,]+)\s{2,}([\d,]+)\s+',line)
            if not m:continue
            label,v1,v2=m.groups()
            if label in ['Visa Group','Citizenship Country']:continue
            for fy,v in [('2023-24',v1),('2024-25',v2)]:
                st=int(fy[:4]);visa={'ETA Tourist':'601','ETA Business':'601','eVisitor Tourist':'651','eVisitor Business':'651',
                    'Tourist Visitor':'600','Business Visitor':'600','Sponsored Tourist':'600','Total':'all_visitor'}
                country=label if pi==12 else 'WORLD'
                if label=='Total':country='WORLD'
                obs.append(dict(observation_id=oid('au_lodged',fy,table,label),destination='Australia',nationality=country,
                    basis='nationality',visa_type=visa.get(label,'all_visitor') if pi==11 else 'all_visitor',
                    visa_group=label if pi==11 else None,metric='applications_lodged',original_metric='Number of Visitor visa applications lodged',
                    value=number(v),unit='applications',period_start=f'{st}-07-01',period_end=f'{st+1}-06-30',
                    year_type='financial',year=st+1,period_label=fy,source_id='au_visitor_2025_06',
                    source_locator=f'PDF page {pi+1}, report page {pi-3}, Table {table}, row {label}, column {fy}',
                    calculation='direct_observation',source_quality='official_primary',
                    aggregation_role='total' if label=='Total' else 'leaf'))
    return obs,checks

def nz_decisions():
    obs=[];checks=[];issues=[]
    # Only application tables, not the near-identical people tables or repeated sorted versions.
    page_sets={'visitor':[12,14,16,18,20],'student':[8,9,10,11,12],'work':[21,23,25,27,29]}
    for typ,pages in page_sets.items():
        r=PdfReader(ROOT/f'data/raw/newzealand/{typ}-decisions.pdf');countries=[]; totals={}
        for pageno in pages:
            txt=r.pages[pageno-1].extract_text(extraction_mode='layout')
            for li,line in enumerate(txt.splitlines(),1):
                m=re.match(r'^\s*([A-Za-z][A-Za-z ,\'().&/\-]*?)\s{2,}([\d,].*)$',line)
                if not m:continue
                country,nums=m.groups();nums=re.findall(r'\d[\d,]*',nums)
                expected={'visitor':29,'student':34,'work':27}[typ]
                if len(nums)!=expected:
                    issues.append({'type':typ,'page':pageno,'line':li,'country':country,'number_count':len(nums),'expected':expected});continue
                country=country.strip()
                if country=='United States of':country='United States of America'
                if country=='Democratic Republic of':country='Democratic Republic of Congo'
                if country=='Pacific Island Trust':country='Pacific Island Trust Territory'
                if country=='South Pacific':country='South Pacific commission'
                countries.append(country)
                for yi in [7,8]:
                    fy=f'{2016+yi}/{str(2017+yi)[-2:]}'
                    vals=[int(s.replace(',','')) for s in nums[yi*3:yi*3+3]]
                    assert vals[0]+vals[1]==vals[2],(typ,pageno,country,fy,vals)
                    for decision,value in zip(['approved','declined','decided'],vals):
                        obs.append(dict(observation_id=oid('nz',typ,country,fy,decision),destination='New Zealand',
                            nationality='WORLD' if country=='Total' else country,basis='nationality',visa_type=typ,
                            metric='applications_'+decision,original_metric=f'Applications {decision.title()}',value=value,unit='applications',
                            period_start=f'{2016+yi}-07-01',period_end=f'{2017+yi}-06-30',year_type='financial',year=2017+yi,
                            period_label=fy,source_id=f'nz_{typ}_decisions',source_locator=f'PDF page {pageno}, row {country}, FY {fy}, {decision}',
                            calculation='direct_observation',source_quality='official_primary',aggregation_role='total' if country=='Total' else 'leaf',
                            definition_note='Declined includes specified withdrawals; decided excludes failed lodgements/refused-to-consider; application not people.'))
        subset=[x for x in obs if x['visa_type']==typ]
        for fy in ['2023/24','2024/25']:
            for metric in ['applications_approved','applications_declined','applications_decided']:
                rows=[x for x in subset if x['period_label']==fy and x['metric']==metric]
                w=next((x['value'] for x in rows if x['nationality']=='WORLD'),None)
                s=sum(x['value'] for x in rows if x['nationality']!='WORLD')
                checks.append({'check':f'nz_{typ}_{fy}_{metric}_nationalities_sum','result':'pass' if s==w else 'incomplete',
                    'parts_sum':s,'world_total':w,'difference':None if w is None else w-s,'country_rows':len(rows)-1})
    dump('nz_parser_issues',issues)
    return obs,checks

def accounting():
    """Actual administered revenue; original annual-report financial statement, not volume x fee."""
    rows=[]
    for year,value in [(2024,3384970000),(2025,4154314000)]:
        rows.append(dict(observation_id=f'au_vac_revenue_fy{year}',destination='Australia',nationality='WORLD',
            basis='government_accounting',visa_type='all_visa_and_migration',metric='visa_application_charge_revenue',
            original_metric='Visa application charges',value=value,unit='AUD',currency='AUD',
            original_value=value//1000,original_unit='AUD thousands',period_start=f'{year-1}-07-01',
            period_end=f'{year}-06-30',year_type='financial',year=year,period_label=f'{year-1}-{str(year)[-2:]}',
            source_id='au_annual_2025',source_locator=f'PDF page 165 / printed page 151, Note 2.1A Taxation revenue, {year} column; visually verified archived PNG',
            supporting_source_id='au_annual_2024' if year==2024 else None,
            supporting_source_locator='FY2023/24 annual report PDF page 119 / printed page 105, Note 2.1A' if year==2024 else None,
            calculation='direct_observation',source_quality='official_primary',aggregation_role='total',
            scope_note='Administered visa and migration application fees. Separately reported citizenship Immigration fees and miscellaneous visitor/working-holiday revenue are excluded. Not a profit measure.',
            accounting_note='Note 2.1A policy PDF166 / printed152: generally non-refundable except prescribed circumstances; recognized when collected; overseas advance payments recognized only after matching a lodged application.'))
    return rows,[{'check':'au_vac_revenue_unit_conversion','result':'pass','fy2024_AUD':3384970000,'fy2025_AUD':4154314000}]

def fee_rules_and_policies():
    """Manual transcription of identified original tables, kept separate from quantity observations."""
    fees=[]
    def add(fid,dest,visa,component,amount,currency,start,end,source,locator,**kw):
        fees.append(dict(fee_rule_id=fid,destination=dest,visa_type=visa,fee_component=component,
            amount=amount,currency=currency,valid_from=start,valid_to=end,source_id=source,source_locator=locator,
            calculation='direct_observation',source_quality='official_primary',unit='per application',
            payer='applicant',mandatory='conditional_on_scope',government_or_service='government',
            payment_stage='application',refusal_refund='normally_no',research_cutoff=RESEARCH_CUTOFF,**kw))
    for entry,amt in [('single',3000),('double_or_multiple',6000),('transit',700)]:
        add(f'jp_standard_{entry}_pre202607','Japan',entry,'visa_issuance_fee',amt,'JPY','2024-01-01','2026-06-30','jp_fee_old','main body paragraphs 1–3',
            applicability='Standard nominal yen amount; fees collected in mission local currency; purpose/nationality exceptions; observation window start is not legal commencement.',
            fee_stage_override='issuance_only',refusal_refund_override='no_government_fee_if_not_issued')
    for entry,amt in [('single',15000),('multiple',30000)]:
        add(f'jp_standard_{entry}_202607','Japan',entry,'visa_issuance_fee',amt,'JPY','2026-07-01',None,'jp_fee_july2026','main body paragraphs 1–4',
            applicability='Approximate yen equivalent; applications accepted at overseas missions on/after 1 July; nationality/purpose exceptions.',fee_stage_override='issuance_only')
    for entry,amt in [('single',145),('double_or_multiple',285),('transit',35)]:
        add(f'jp_sh_{entry}_202504','Japan',entry,'visa_issuance_fee',amt,'CNY','2025-04-01','2026-06-30','jp_sh_fee_2025','fee table',
            applicability='Shanghai mission-local fee; not a fee for all Chinese nationals applying anywhere.',fee_stage_override='issuance_only')
    for entry,amt in [('single',715),('double_or_multiple',1430)]:
        add(f'jp_cn_{entry}_202607','Japan',entry,'visa_issuance_fee',amt,'CNY','2026-07-01',None,'jp_cn_fee_july2026','fee table',
            applicability='Japan Embassy in China local fee; not total agency quote. Indian nationality exception recorded separately.',fee_stage_override='issuance_only')
    add('jp_cn_india_202607','Japan','single_or_multiple','visa_issuance_fee',40,'CNY','2026-07-01',None,'jp_cn_fee_july2026','Indian-applicant exception table',
        applicability='Indian national applying at mission in China.',fee_stage_override='issuance_only')
    add('jp_ph_temporary_visitor_gratis_observed2026','Japan','short_stay','visa_issuance_fee',0,'JPY',None,None,'jp_fee_ph_gratis','Important Notice',
        applicability='Philippine nationals, temporary visitor up to 90 days; official June2026 page says remains gratis. No automatic retroactive deduction for every visa category.',fee_stage_override='issuance_only',rule_status='observed_current_2026_historical_start_not_identified')
    for visa,values,ref,loc in [
        ('600_offshore_standard',[190,195,200,250],'visitor','Schedule1 item181 (2024), item190 (2025); Schedule3 item58 paragraph1236 (2026)'),
        ('500_student_standard',[710,1600,2000,2500],'student','Schedule1 item160 (2024), item167 (2025); Schedule3 item42 paragraph1222 (2026)')]:
        periods=[('2024-01-01','2024-06-30',2024),('2024-07-01','2025-06-30',2024),('2025-07-01','2026-06-30',2025),('2026-07-01',None,2026)]
        for i,(start,end,sy) in enumerate(periods):
            add(f'au_{ref}_{start.replace("-","")}', 'Australia',visa,'visa_application_charge',values[i],'AUD',start,end,f'au_fee_legislation_{sy}',loc,
                applicability='Base primary applicant only; special passport/stream/nationality exemptions and additional applicant charges excluded. 2026 standard offshore visitor applies to non-Pacific passports; student concessional bands differ.',
                original_value_role='amount_replaced_in_amending_instrument' if i==0 else 'new_amount_in_amending_instrument')
    # Band C applies to ordinary applicants outside NZ/Pacific; unit differs by product.
    products=[('visitor',190,21,300,41),('ADS_China_group',35,55,55,85),('other_group_visitor',55,55,86,85),
        ('student',300,95,485,265),('post_study_work',490,210,320,1350),('partnership_work',650,210,570,1060),
        ('working_holiday',210,210,215,455),('AEWV',540,210,480,1060),('other_work',490,210,295,1060)]
    for visa,oldfee,oldlevy,newfee,newlevy in products:
        for label,start,end,fee,levy,src,loc in [
            ('pre202410','2024-01-01','2024-09-30',oldfee,oldlevy,'nz_fee_cost_review_2024','PDF page55, Annex6 CURRENT charges, BandC / levy; visually verified'),
            ('202410','2024-10-01',None,newfee,newlevy,'nz_fees_oct2024','PDF page2, product row, BandC / New Immigration Levy')]:
            for comp,amt in [('application_fee',fee),('immigration_levy',levy)]:
                add(f'nz_{visa}_{comp}_{label}','New Zealand',visa,comp,amt,'NZD',start,end,src,loc,
                    applicability='Band C rest-of-world tariff; concessions/waivers and family/group billing require applicable rules. IVL not included.',
                    unit_scope_note='Source schedule lists product rates; group/ADS billing unit must be checked before mapping to people. A visitor application can cover eligible family members.')
    for label,start,end,amt,src in [('pre202410','2024-01-01','2024-09-30',35,'nz_ivl_change_2024'),('202410','2024-10-01',None,100,'nz_ivl_change_2024')]:
        add(f'nz_ivl_{label}','New Zealand','eligible_visa_or_NZeTA','international_visitor_levy',amt,'NZD',start,end,src,'IVL section',
            unit_override='per eligible person per visa application or NZeTA request',applicability='Most ordinary tourist/fee-paying student/working-holiday applicants; exclusions include partner/dependent categories, transit, resident and business categories; not each entry.',
            main_visa_fee_scope=False,applicant_bill_scope=True)
    for channel,amt in [('website',23),('mobile_app',17)]:
        add(f'nz_NZeTA_{channel}','New Zealand','NZeTA','electronic_authorisation_request_fee',amt,'NZD','2024-01-01',None,'nz_fees_oct2024','PDF page3, NZeTA rows; unchanged old rates also shown in fee review PDF55',
            applicability=f'{channel}; qualifying passports only; IVL separate.',main_visa_fee_scope=False,applicant_bill_scope=True)
    # Normalize overriding semantic fields while retaining a common schema.
    for f in fees:
        for key in ['payment_stage','refusal_refund','unit']:
            override={'payment_stage':'fee_stage_override','refusal_refund':'refusal_refund_override','unit':'unit_override'}[key]
            if override in f:f[key]=f.pop(override)
        if f['destination']=='Japan':f['refusal_refund']='no_government_fee_if_not_issued'
    policies=[
        dict(policy_id='jp_no_issuance_no_gov_fee',destination='Japan',policy_type='fee_timing_and_agency',source_id='jp_fee_old',source_locator='main body paragraphs2–3',
            rule='Visa government fee is due for issuance; an unissued visa incurs no government visa fee. Designated agency handling is an additional charge whose amount is not uniform in the official notice.'),
        dict(policy_id='jp_china_historical_regional_waiver',destination='Japan',policy_type='fee_waiver',source_id='jp_cn_historical_waiver',source_locator='签证手续费 footnotes1–2',
            rule='Historical2019 official tourist-visa page specifies Okinawa/three Tohoku prefecture fee exemptions. Old CNY200/400 rates on the same page are superseded.',use_status='historical_evidence_only; no2024/25 exempt count or fee deduction inferred'),
        dict(policy_id='au_refused_no_normal_refund',destination='Australia',policy_type='refund',source_id='au_refund',source_locator='Refund eligibility main text',
            rule='An unsuccessful/refused application or a change of mind does not normally trigger a fee refund. Prescribed exceptions and separate refund programs remain.'),
        dict(policy_id='au_vac_recognition',destination='Australia',policy_type='accounting',source_id='au_annual_2025',source_locator='PDF166 / printed152, Note2.1A accounting policy',
            rule='Visa and migration fees normally not refundable except prescribed circumstances; generally recognized when collected; overseas advance payment recognized when matched with a lodged application.'),
        dict(policy_id='nz_refused_no_normal_refund',destination='New Zealand',policy_type='refund',source_id='nz_refund',source_locator='When you cannot get a refund',
            rule='A processed/declined application, change of mind or post-lodgement withdrawal normally does not receive a fee refund; listed other circumstances can qualify.'),
        dict(policy_id='nz_ivl_scope_and_no_refund',destination='New Zealand',policy_type='IVL',source_id='nz_ivl_scope',source_locator='Who must pay / who does not / when to pay',
            rule='IVL applies per eligible person at visa application or NZeTA request; it is not refunded on decline. Many residency, nationality, dependent, transit and business exceptions apply.'),
        dict(policy_id='nz_decision_definitions',destination='New Zealand',policy_type='statistical_definition',source_id='nz_visitor_decisions',source_locator='PDF1 definitions',
            rule='Nationality is passport-issuing country. Decided means approved/declined applications accepted for processing, excluding failed lodgements/refused-to-consider. Declined includes specified withdrawals; application counts can include multiple people.'),
        dict(policy_id='nz_family_fee_unit',destination='New Zealand',policy_type='billing_unit',source_id='nz_fee_cost_review_2024',source_locator='PDF37 Table9 visitors commentary',
            rule='One fee is charged for visitor applications including eligible family members, so multiplying a per-application rate by visitor-person counts is incorrect.'),
        dict(policy_id='au_pivot_cache_privacy_scope',destination='Australia',policy_type='statistical_definition',source_id='au_visitor_grants_pivot',source_locator='Notes worksheet and OOXML cache',
            rule='Official pivot display suppresses1–4 as<5. This extraction uses integer cached aggregates by month/subclass/citizenship/group/location, never individual records. Data are revised dynamically; all outputs frozen to archived September2026 release.')]
    return fees,policies

def estimates(observations):
    """Transparent nominal fee-value scenarios; no re-labelling as cash income."""
    estimates=[];derived=[]
    for year in [2024,2025]:
        nat=[x for x in observations if x['destination']=='Japan' and x['year']==year and x.get('basis')=='nationality']
        by=collections.defaultdict(dict)
        for x in nat:by[x['nationality']][x['visa_type']]=x
        for country,records in by.items():
            n=records['all'];m=records['multiple_entry_subset'];short=records['short_stay']
            country_id=hashlib.sha1(country.encode()).hexdigest()[:12]
            estimates.append(dict(estimate_id=f'jp_standard_nominal_{year}_{country_id}',destination='Japan',nationality=country,year=year,
                period_start=n['period_start'],period_end=n['period_end'],year_type='calendar',visa_type='all',
                target='issued_cohort_standard_nominal_fee_value',value=3000*(n['value']+m['value']),currency='JPY',
                method='scenario',formula='3000*(all_issued+multiple_issued)',input_observation_ids=[n['observation_id'],m['observation_id']],
                fee_rule_ids=['jp_standard_single_pre202607','jp_standard_double_or_multiple_pre202607'],
                assumptions='Multiple-entry subset charged6000; every remaining visa charged3000. Unobserved double-entry visas treated as single; waivers/transit/diplomatic/special nationality tariffs ignored; mission currency conversion ignored.',
                interpretation='Standard-tariff counterfactual for issued cohort. Not official revenue, not an unconditional upper bound across nationality-specific tariffs.',
                uncertainty='Structural tariff exceptions and currency collection, not sampling error.',use_status='scenario_only'))
            # Unknown overlap has exact Fréchet limits; these bound nominal short-stay fee value, not real receipts.
            lower=max(0,short['value']+m['value']-n['value']);upper=min(short['value'],m['value'])
            estimates.append(dict(estimate_id=f'jp_shortstay_multiple_overlap_{year}_{country_id}',destination='Japan',nationality=country,year=year,
                period_start=n['period_start'],period_end=n['period_end'],year_type='calendar',visa_type='short_stay',
                target='short_stay_standard_nominal_fee_value',lower=3000*(short['value']+lower),upper=3000*(short['value']+upper),currency='JPY',
                interval_type='partial_identification_of_standard_tariff_scenario',method='Frechet_bounds',
                formula='multiple_in_short=[max(0,short+multiple-total),min(short,multiple)]; fee=3000*(short+multiple_in_short)',
                input_observation_ids=[n['observation_id'],m['observation_id'],short['observation_id']],
                fee_rule_ids=['jp_standard_single_pre202607','jp_standard_double_or_multiple_pre202607'],
                assumptions='Only overlap unknown; tariff scenario assumes all short-stay single/multiple paid standard prices, no waivers/special prices; double-entry classification not observed.',
                interpretation='Does not assume short-stay and multiple-entry independence. Interval is not a confidence interval or actual revenue interval.',use_status='scenario_only'))
    # Directly calculable decision shares; not application-cohort success probability.
    nz=collections.defaultdict(dict)
    for x in observations:
        if x['destination']=='New Zealand' and x['metric'].startswith('applications_'):
            nz[(x['year'],x['visa_type'],x['nationality'])][x['metric']]=x
    for (year,visa,country),records in nz.items():
        dec=records['applications_decided'];approved=records['applications_approved'];declined=records['applications_declined']
        if not dec['value']:continue
        derived.append(dict(derived_metric_id=oid('nz_decision_share',year,visa,country),destination='New Zealand',nationality=country,visa_type=visa,
            year=year,year_type='financial',period_start=dec['period_start'],period_end=dec['period_end'],
            approved_decision_share=approved['value']/dec['value'],declined_decision_share=declined['value']/dec['value'],
            input_observation_ids=[approved['observation_id'],declined['observation_id'],dec['observation_id']],
            formula='approved/decided; declined/decided',calculation='deterministic_calculation',
            interpretation='Fiscal-year decided-application share; declined includes specified withdrawals; not a lodged-cohort approval probability.'))
    # Concrete ordinary single-person applicant bills, independent of quantity cohorts.
    for visa,oldfee,oldlevy,newfee,newlevy in [('visitor',190,21,300,41),('student',300,95,485,265),('working_holiday',210,210,215,455)]:
        for label,fee,levy,ivl in [('pre202410',oldfee,oldlevy,35),('202410',newfee,newlevy,100)]:
            derived.append(dict(derived_metric_id=f'nz_bill_{visa}_{label}',destination='New Zealand',nationality='China',visa_type=visa,
                metric='ordinary_single_person_applicant_bill',value=fee+levy+ivl,currency='NZD',application_fee=fee,immigration_levy=levy,IVL=ivl,
                formula='application_fee + immigration_levy + IVL',fee_rule_ids=[f'nz_{visa}_application_fee_{label}',f'nz_{visa}_immigration_levy_{label}',f'nz_ivl_{label}'],
                calculation='deterministic_calculation',interpretation='One eligible BandC applicant, no concession, no agency/translation/medical costs. IVL separate from core visa fee.'))
    return estimates,derived

def download_missing():
    """Restore frozen originals using manifest URLs; never replace an archived version silently."""
    sources=json.loads((OUT/'sources.json').read_text())
    ctx=ssl.create_default_context(cafile='/etc/ssl/cert.pem')
    for s in sources:
        if s.get('capture_method')!='http_download_original':continue
        path=ROOT/s['local_path']
        if path.exists():continue
        req=urllib.request.Request(s['url'],headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=90,context=ctx) as response:data=response.read()
        if hashlib.sha256(data).hexdigest()!=s['sha256']:
            raise ValueError(f"{s['source_id']}: current download differs from frozen original; inspect version before updating manifest")
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)

def provenance_checks(observations,fees,policies):
    sources=json.loads((OUT/'sources.json').read_text());ids={s['source_id'] for s in sources}
    missing={x['source_id'] for x in observations+fees+policies}-ids
    assert not missing,missing
    for s in sources:
        p=ROOT/s['local_path'];assert p.exists(),p
        assert hashlib.sha256(p.read_bytes()).hexdigest()==s['sha256'],s['source_id']
    return [{'check':'apac_source_references_and_archived_sha256','result':'pass','sources':len(sources)}]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download',action='store_true',help='Restore missing frozen originals from sources.json; existing files untouched')
    args=parser.parse_args()
    if args.download:download_missing()
    rows=[];checks=[]
    for fn in [japan,australia_pivot,australia_pdf,nz_decisions,accounting]:
        r,c=fn();rows.extend(r);checks.extend(c)
    ids=[r['observation_id'] for r in rows];assert len(ids)==len(set(ids)),'duplicate observation IDs'
    fees,policies=fee_rules_and_policies();est,derived=estimates(rows)
    for collection,key in [(fees,'fee_rule_id'),(policies,'policy_id'),(est,'estimate_id'),(derived,'derived_metric_id')]:
        values=[x[key] for x in collection];assert len(values)==len(set(values)),f'duplicate {key}'
    checks.extend(provenance_checks(rows,fees,policies))
    dump('fee_rules',fees);dump('policies',policies);dump('estimates',est);dump('derived_metrics',derived)
    dump('observations',rows);dump('validation',checks)
    print(json.dumps({'observations':len(rows),'fee_rules':len(fees),'policies':len(policies),'estimates':len(est),'derived_metrics':len(derived),'checks':checks},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
