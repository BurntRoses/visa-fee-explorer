#!/usr/bin/env python3
"""Rebuild the Turkey/Russia/Saudi evidence package from archived local sources.

Offline by default.  No inferred revenue is exported as an observed receipt.
Use --refresh only to refresh registered original documents, not the web snapshots.
PDF text archives were extracted with pdfplumber; --extract-pdfs regenerates them.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/turkey_russia_saudi'
OUT = ROOT / 'data/research/turkey_russia_saudi'
DATE = '2026-11-15'

# Raw endpoints and actual successful retrieval routes are both retained.
SOURCES = [
 ('ru_evisa_metadata','ru_evisa_meta_good.html','https://www.kdmid.ru/opendata/7704206201-electronic-visas/','official_primary','?download=1'),
 ('ru_evisa_latest_csv','ru_evisa_alt.csv','https://www.kdmid.ru/opendata/7704206201-electronic-visas/data-20261103-structure-20231008.csv','official_primary','?download=1'),
 ('ru_consular_annual','ru_visa_csv_good.csv','https://www.kdmid.ru/opendata/7704206201-visa/data-20260327-structure-20200514.csv','official_primary','?download=1'),
 ('ru_consular_by_post','ru_country_csv_good.csv','https://www.kdmid.ru/opendata/7704206201-country-visas/data-20260715-structure-20260715.csv','official_primary','?download=1'),
 ('ru_evisa_instructions','ru_evisa_instructions.html','https://evisa.kdmid.ru/Home/Instruction?culture=en-US','official_primary',''),
 ('ru_evisa_faq','ru_evisa_faq.html','https://electronic-visa.kdmid.ru/faq_en.html','official_primary',''),
 ('ru_evisa_fee_law','ru_fee_law.html','https://www.consultant.ru/document/cons_doc_LAW_364400/716fdfd2dd9e9f5fe40f1bf89bd757cb3131340f/','reliable_legal_reproduction',''),
 ('ru_waiver_original','ru_waiver_original.html','https://www.garant.ru/products/ipo/prime/doc/413070681/','reliable_legal_reproduction',''),
 ('ru_waiver_extension','ru_waiver_extended.html','https://www.garant.ru/hotlaw/federal/2172596/','reliable_legal_reproduction',''),
 ('ru_waiver_extension_embassy','ru_china_embassy_extension.html','https://ru.china-embassy.gov.cn/rus/dshd/202608/t20260831_12013102.htm','official_primary',''),
 ('tr_annual_2024','tr_2024_nw.pdf','https://www.mfa.gov.tr/data/BAKANLIK/disisleri-bakanligi-2024-yili-idare-faaliyet-raporu.pdf','official_primary','https://mfa.gov.tr/data/BAKANLIK/disisleri-bakanligi-2024-yili-idare-faaliyet-raporu.pdf'),
 ('tr_annual_2025','tr_report_2025.pdf','https://www.mfa.gov.tr/data/BAKANLIK/disisleri-bakanligi-2025-yili-idare-faaliyet-raporu.pdf','official_primary','https://mfa.gov.tr/data/BAKANLIK/disisleri-bakanligi-2025-yili-idare-faaliyet-raporu.pdf'),
 ('tr_prc_policy_2024','tr_beijing_2024.html','https://beijing-emb.mfa.gov.tr/Mission/ShowAnnouncement/411691','official_primary',''),
 ('tr_prc_fee_2015','tr_fee_historic.html','https://www.jingan.gov.cn/2020gdlm/009001/009001007/009001007004/20150521/f6bccb7a-c388-43c1-bfe6-888280d09ed6.html','official_secondary_historical',''),
 ('tr_prc_fee_2025_secondary','tr_fee_wise2025.html','https://wise.com/zh-cn/blog/visa-for-turkey','industry_secondary',''),
 ('sa_tourist_regulations','sa_tourist_regulations.pdf','https://cdn.mt.gov.sa/mtportal/mt-fe-production/content/policies-regulations/documents/tourism-regulations/Tourist-Visa-Regulations-En-V012.pdf','official_primary',''),
 ('sa_expat_guide_2024','sa_expat_services.pdf','https://www.hrsd.gov.sa/sites/default/files/2024-08/Guide%20to%20Services%20Provided%20for%20Expatriates.pdf','official_primary',''),
 ('sa_umrah_report_2025','sa_umrah_2025.html','https://spa.gov.sa/en/N2512740','official_primary',''),
]

SNAPSHOT_SOURCES = [
 ('ru_evisa_annual_web','ru_tables_snapshot.json','https://www.kdmid.ru/opendata/7704206201-electronic-visas/doc/view.php','official_primary'),
 ('ru_evisa_annual_web_part2','ru_evisa_snapshot.json','https://www.kdmid.ru/opendata/7704206201-electronic-visas/doc/view.php','official_primary'),
 ('ru_evisa_annual_web_part3','ru_evisa_total_snapshot.json','https://www.kdmid.ru/opendata/7704206201-electronic-visas/doc/view.php','official_primary'),
 ('ru_evisa_checkout_web','trs_policies_snapshot.json','https://warsaw.kdmid.ru/ru/consular-functions/vizovye-voprosy/Electron%20visa/','official_primary'),
 ('tr_prc_waiver_web','trs_policies_snapshot.json','https://www.iletisim.gov.tr/turkce/dis_basinda_turkiye/detay/turkiye-cin-vatandaslarina-vize-muafiyeti-uygulanacagini-acikladi-xinhua','official_secondary'),
 ('sa_sama_peg_web','sa_official_counts_fx_snapshot.json','https://sama.gov.sa/en-US/MediaCenter/News/Pages/news-557.aspx','official_primary'),
]

MONTHS = {v:i+1 for i,v in enumerate(['ЯНВАРЬ','ФЕВРАЛЬ','МАРТ','АПРЕЛЬ','МАЙ','ИЮНЬ','ИЮЛЬ','АВГУСТ','СЕНТЯБРЬ','ОКТЯБРЬ','НОЯБРЬ','ДЕКАБРЬ'])}
CHECKS = []

def write_json(name, obj):
    (OUT / (name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def write_rows(name, rows):
    write_json(name,rows)
    if not rows: return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with (OUT/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)

def check(name, ok, **details):
    CHECKS.append(dict(check=name,passed=bool(ok),**details))
    if not ok and details.get('severity') != 'source_discrepancy':
        raise AssertionError((name,details))

def number(x):
    return int(re.sub(r'[\s\u00a0.]','',x))

def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def source_fields(source_id):
    return dict(source_id=source_id,source_quality='official_primary',calculation_type='direct_observation')

def manifest():
    result=[]
    for sid,file,url,quality,retrieval in SOURCES:
        p=RAW/file
        if not p.exists(): continue
        result.append(dict(source_id=sid,url=url,retrieval_url=(url+retrieval if retrieval.startswith('?') else retrieval or url),path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,retrieved_at=DATE,source_quality=quality,archive_kind='original_document_sanitized' if sid=='sa_umrah_report_2025' else 'original_document',sanitization='public embedded access-token field redacted; article content unchanged' if sid=='sa_umrah_report_2025' else None))
    for sid,file,url,quality in SNAPSHOT_SOURCES:
        p=RAW/file
        result.append(dict(source_id=sid,url=url,path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,retrieved_at=DATE,source_quality=quality,archive_kind='indexed_official_page_extract',note='Search-tool page extract, not original HTML; line labels preserved.'))
    for p in sorted((RAW/'ru_evisa_archive').glob('*.csv')):
        url='https://www.kdmid.ru/opendata/7704206201-electronic-visas/'+p.name
        result.append(dict(source_id='ru_evisa_'+p.stem,path=str(p.relative_to(ROOT)),url=url,retrieval_url=url+'?download=1',sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,retrieved_at=DATE,source_quality='official_primary',archive_kind='original_csv'))
    write_json('sources',result)
    return result

def refresh():
    for sid,file,url,quality,retrieval in SOURCES:
        endpoint=url+retrieval if retrieval.startswith('?') else retrieval or url
        req=urllib.request.Request(endpoint,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=45) as r: data=r.read()
        if file.endswith('.pdf') and not data.startswith(b'%PDF'): raise ValueError('Not PDF: '+sid)
        if file.endswith('.csv') and b'year' not in data[:80]: raise ValueError('Not CSV: '+sid)
        if sid=='sa_umrah_report_2025':
            data=re.sub(rb'("gcloudToken"\s*:\s*)"[^"\\]*(?:\\.[^"\\]*)*"',rb'\1"[REDACTED_PUBLIC_EMBEDDED_TOKEN]"',data)
        p=RAW/file;tmp=p.with_suffix(p.suffix+'.part');tmp.write_bytes(data);tmp.replace(p)

def extract_pdfs():
    import pdfplumber
    for raw_name,out_name in [('tr_2024_nw.pdf','tr_report_2024.txt'),('tr_report_2025.pdf','tr_report_2025.txt'),('sa_expat_services.pdf','sa_expat_services.txt'),('sa_tourist_regulations.pdf','sa_tourist_regulations.txt')]:
        with pdfplumber.open(RAW/raw_name) as pdf:
            text='\n\n'.join('PAGE '+str(i+1)+'\n'+(p.extract_text() or '') for i,p in enumerate(pdf.pages))
        (OUT/out_name).write_text(text)

def russia():
    # The published CSV currently contains only the latest month. Its archive
    # contains 2024 Jun-Dec and all 12 months of 2025. Do not label Jun-Dec a year.
    monthly=[]
    for p in sorted((RAW/'ru_evisa_archive').glob('*.csv')):
        for r in rows(p):
            monthly.append(dict(destination='RUS',year=int(r['year']),month=MONTHS[r['month'].strip()],origin_as_published=r['country'].strip(),origin_basis='citizenship',visa_group='unified_evisa',issued=int(r['issued']),entered=int(r['entered']),source_id='ru_evisa_'+p.stem,source_quality='official_primary',calculation_type='direct_observation'))
    write_rows('russia_evisa_monthly_observations',monthly)

    # Recover the complete annual official table from archived indexed excerpts.
    # Deduplicate overlapping page viewports by citizenship; require 64 + WORLD.
    found={}
    for file in ['ru_tables_snapshot.json','ru_evisa_snapshot.json','ru_evisa_total_snapshot.json']:
        doc=json.loads((RAW/file).read_text())
        for c in doc.get('content',[]):
            text=c.get('text','')
            if '7704206201-electronic-visas/doc/view.php' not in text: continue
            for line in text.splitlines():
                m=re.match(r'L(\d+):\s*(.*)',line)
                if not m or not 918<=int(m[1])<=982: continue
                a=[v.strip() for v in m[2].split('|')]
                if len(a)==29 and all(re.fullmatch(r'\d+',v) for v in a[1:]): found[a[0]]=a
    check('evisa_annual_citizenship_rows',len(found)==65,rows=len(found))
    annual=[]
    for country,a in sorted(found.items()):
        for year,offset in [(2023,1),(2024,3),(2025,5)]:
            annual.append(dict(destination='RUS',year=year,period_start=f'{year}-01-01' if year!=2023 else '2023-08-01',period_end=f'{year}-12-31',origin='WORLD' if country=='Итого' else 'CHN' if country=='КИТАЙ' else None,origin_as_published=country,origin_basis='citizenship',visa_group='unified_evisa',issued=int(a[offset]),entered=int(a[offset+1]),source_locator=f'citizenship={country}; annual columns {year} Оформлено/Въезд',**source_fields('ru_evisa_annual_web')))
    for y in [2023,2024,2025]:
        world=next(r for r in annual if r['origin']=='WORLD' and r['year']==y)
        for metric in ['issued','entered']:
            s=sum(r[metric] for r in annual if r['origin']!='WORLD' and r['year']==y)
            check(f'evisa_annual_country_sum_{y}_{metric}',s==world[metric],sum=s,published_world=world[metric])
    for a in [r for r in annual if r['year']==2025]:
        mm=[r for r in monthly if r['year']==2025 and (a['origin']=='WORLD' or r['origin_as_published']==a['origin_as_published'])]
        for metric in ['issued','entered']:
            check(f'evisa_2025_monthly_sum_{a["origin_as_published"]}_{metric}',sum(r[metric] for r in mm)==a[metric])
    write_rows('russia_evisa_annual',annual)

    consular=[]
    for r in rows(RAW/'ru_visa_csv_good.csv'):
        consular.append(dict(destination='RUS',year=int(r['year']),origin='WORLD',origin_basis='all_consular_posts_abroad',visa_group='consular_visa_all_categories',**{k:number(r[k]) for k in ['total','business','private','tourist','other']},**source_fields('ru_consular_annual')))
    for r in consular: check(f'consular_categories_sum_{r["year"]}',r['total']==sum(r[k] for k in ['business','private','tourist','other']))
    write_rows('russia_consular_annual',consular)
    posts=[]
    for r in rows(RAW/'ru_country_csv_good.csv'):
        posts.append(dict(destination='RUS',year=int(r['year']),issuing_country_as_published=r['country'],issuing_city_as_published=r['city'],origin_basis='issuing_post_location_not_citizenship',visa_group='consular_visa_all_categories',**{k:number(r[k]) for k in ['total','diplomatic','service','common','transit']},**source_fields('ru_consular_by_post')))
    write_rows('russia_consular_by_post',posts)
    aggs={}
    for r in posts:
        k=(r['year'],r['issuing_country_as_published'])
        a=aggs.setdefault(k,dict(destination='RUS',year=k[0],issuing_country_as_published=k[1],origin_basis='issuing_post_location_not_citizenship',visa_group='consular_visa_all_categories',total=0,diplomatic=0,service=0,common=0,transit=0,source_id='ru_consular_by_post',source_quality='official_primary',calculation_type='deterministic_sum'))
        for metric in ['total','diplomatic','service','common','transit']:a[metric]+=r[metric]
    write_rows('russia_consular_country_annual',list(aggs.values()))
    cn=[]
    for year in [2024,2025]:
        for hk in [True,False]:
            selected=[r for r in posts if r['year']==year and r['issuing_country_as_published']=='Китай' and (hk or r['issuing_city_as_published']!='ГОНКОНГ')]
            cn.append(dict(destination='RUS',year=year,issuing_area='China_all_posts_including_Hong_Kong' if hk else 'China_mainland_posts',origin_basis='issuing_post_location_not_citizenship',**{k:sum(r[k] for r in selected) for k in ['total','diplomatic','service','common','transit']},post_count=len(selected),source_id='ru_consular_by_post',source_quality='official_primary',calculation_type='deterministic_sum'))
        a=next(r for r in consular if r['year']==year)
        b=sum(r['total'] for r in posts if r['year']==year)
        check(f'consular_country_vs_global_{year}',b==a['total'],severity='source_discrepancy',by_post_sum=b,published_annual_total=a['total'],difference=a['total']-b,note='Preserve both datasets. Do not force country rows to match published global total.')
    write_rows('russia_china_issuing_post_annual',cn)
    return annual

def turkey():
    annual=[];quarters=[]
    for year,page,printed in [(2024,109,108),(2025,119,113)]:
        text=(OUT/f'tr_report_{year}.txt').read_text()
        page_text=text.split(f'PAGE {page}\n',1)[1].split('\n\nPAGE ',1)[0]
        match=re.search(r'5 Sayı (\d{4}) ((?:[\d.]+\s+){9})',page_text)
        if not match:raise ValueError(f'Cannot locate evisa row: {year}')
        nums=[number(v) for v in match[2].split()]
        # Previous observation, target, revised expectation, Q1-Q4, annual, %.
        check(f'turkey_{year}_quarters_sum',sum(nums[3:7])==nums[7],quarter_sum=sum(nums[3:7]),annual=nums[7])
        sid=f'tr_annual_{year}'
        annual.append(dict(destination='TUR',year=year,origin='WORLD',origin_basis='all_nationalities',visa_group='evisa',metric='issued',value=nums[7],period_start=f'{year}-01-01',period_end=f'{year}-12-31',source_locator=f'PDF p{page}; printed p{printed}; E-Vize sistemi üzerinden ita edilen vize sayısı; Yıl Sonu Değeri',**source_fields(sid)))
        for q,v in enumerate(nums[3:7],1):quarters.append(dict(destination='TUR',year=year,quarter=q,origin='WORLD',visa_group='evisa',metric='issued',value=v,source_locator=f'PDF p{page}; printed p{printed}; quarter={q}',**source_fields(sid)))
    text=(OUT/'tr_report_2024.txt').read_text()
    m=re.search(r'2024 yılında ([\d.]+) adet e-vize, ([\d.]+) adet etiket vize olmak üzere toplamda\s+([\d.]+) adet vize ita edilmiştir',text)
    check('turkey_2024_all_channel_paragraph',bool(m))
    e,sticker,total=map(number,m.groups());check('turkey_2024_channels_sum',e+sticker==total)
    for group,v in [('sticker_visa',sticker),('all_visa_channels',total)]:annual.append(dict(destination='TUR',year=2024,origin='WORLD',origin_basis='all_nationalities',visa_group=group,metric='issued',value=v,source_locator='PDF p94; printed p93; section 1.10 GÖÇ VE VİZE FAALİYETLERİ',**source_fields('tr_annual_2024')))
    write_rows('turkey_annual',annual);write_rows('turkey_quarterly',quarters)

def fees_policies():
    fees=[
      dict(rule_id='RUS-evisa-adult-government',destination='RUS',origin='eligible_citizenships',visa_group='unified_evisa',component='government_consular_fee',amount=40,currency='USD',payer='applicant',effective_start='2023-08-01',effective_end=None,age_condition='age >=6',refund_on_refusal=False,source_id='ru_evisa_fee_law',source_quality='reliable_legal_reproduction',calculation_type='direct_observation',source_locator='Government Decree1601, 2020-10-05; adds paragraph7 to consular tariff; current instruction confirms non-refundable application payment.'),
      dict(rule_id='RUS-evisa-under6-government',destination='RUS',origin='eligible_citizenships',visa_group='unified_evisa',component='government_consular_fee',amount=0,currency='USD',age_condition='age <6',source_id='ru_evisa_fee_law',source_quality='reliable_legal_reproduction',calculation_type='direct_observation'),
      dict(rule_id='RUS-evisa-checkout-current',destination='RUS',origin='eligible_citizenships',visa_group='unified_evisa',component='applicant_total_approximate',amount=52,currency='USD',as_of=DATE,effective_start=None,source_id='ru_evisa_checkout_web',source_quality='official_primary',calculation_type='direct_observation',note='Consular fee + bank commission + payment-system transaction costs + document precheck; floating FX. Not government revenue and not proven historical 2024/2025 checkout price.'),
      dict(rule_id='RUS-evisa-under6-checkout-current',destination='RUS',origin='eligible_citizenships',visa_group='unified_evisa',component='payment_transaction_cost_approximate',amount=2,currency='USD',age_condition='age <6',as_of=DATE,source_id='ru_evisa_checkout_web',source_quality='official_primary',calculation_type='direct_observation'),
      dict(rule_id='TUR-CHN-evisa-historical-fee',destination='TUR',origin='CHN',visa_group='evisa',component='government_fee_reported',amount=60,currency='USD',as_of='2015-05-21',historical_2024_2025_status='provisional_corroboration_only',source_id='tr_prc_fee_2015',corroborating_source_id='tr_prc_fee_2025_secondary',source_quality='official_secondary_historical',calculation_type='direct_observation',note='Shanghai Jing’an government historical article reports USD60 +0.70 payment cost. Wise 2025-04-11 also reports USD60 but incorrectly describes multiple entry. Historical 2024/2025 primary tariff not recovered; do not multiply Turkey global evisa count by China tariff.'),
      dict(rule_id='TUR-CHN-short-visit-waiver',destination='TUR',origin='CHN',visa_group='tourism_transit',component='government_visa_fee',amount=0,currency='USD',effective_start='2026-01-02',source_id='tr_prc_waiver_web',source_quality='official_secondary',calculation_type='direct_observation',note='Ordinary PRC passports; tourism/transit; 90days in any180. Not retroactive to2024/2025.'),
      dict(rule_id='SAU-tourist-government-base',destination='SAU',origin='eligible_applicants',visa_group='tourist',component='government_visa_base_fee',amount=300,currency='SAR',source_id='sa_tourist_regulations',source_quality='official_primary',calculation_type='direct_observation',source_locator='Tourist Visa Regulations Article9; PDF p6',note='Mandatory approved medical insurance is separate (Article5). This tariff must not be applied to Umrah/Hajj/work visas.'),
      dict(rule_id='SAU-tourist-service-guide-2024',destination='SAU',origin='eligible_applicants',visa_group='tourist_evisa',component='service_fee_as_published_total_not_decomposed',amount=463.44,currency='SAR',as_of='2024',source_id='sa_expat_guide_2024',source_quality='official_primary',calculation_type='direct_observation',source_locator='PDF p438 / printed p439; Issuing a tourist visa',note='Guide describes insurance-company selection and policy issuance. Does not identify exact tax/platform/insurance breakdown or prove one universal price. SAR395/440/535 must not be treated as universal government fee.'),
    ]
    write_rows('fee_rules',fees)
    policies=[
      dict(destination='RUS',origin='CHN',policy='individual_ordinary_passport_visa_waiver',effective_start='2025-12-01',original_end='2026-09-14',current_end='2027-12-31',stay_days=30,amendment_date='2026-07-20',source_id='ru_waiver_original',extension_source_id='ru_waiver_extension',official_corroboration='ru_waiver_extension_embassy',note='Decree872 of2025-12-01; amended by Decree499 of2026-07-20. Guest/business/tourism/events/transit; employment, study, residence and specified work activities excluded. Earlier group waiver also existed; no all-China-visitors×fee counterfactual.'),
      dict(destination='RUS',policy='unified_evisa_validity_change',effective_start='2025-08-23',old_validity_days=60,new_validity_days=120,old_stay_days=16,new_stay_days=30,source_id='ru_evisa_checkout_web',note='Applies by submission date; single entry remains.'),
      dict(destination='TUR',origin='CHN',policy='ordinary_passport_tourism_transit_visa_waiver',effective_start='2026-01-02',stay_days=90,rolling_window_days=180,source_id='tr_prc_waiver_web'),
      dict(destination='TUR',origin='CHN',policy='evisa_historical_entry_rule',as_of='2024-09-26',stay_days=30,entries=1,source_id='tr_prc_policy_2024',note='Official Beijing embassy notice confirms 30-day SINGLE entry for ordinary PRC passports for tourism/business. Wise multiple-entry description is not adopted.'),
      dict(destination='RUS',policy='unified_evisa_payment_before_processing',source_id='ru_evisa_instructions',refund_on_refusal=False,note='Only applications for which consular fee paid accepted for processing. Fees not refunded regardless of processing result. Issued is not paid-application denominator.'),
    ]
    write_rows('policy_rules',policies)
    write_rows('exchange_rate_rules',[dict(base_currency='USD',quote_currency='SAR',quote_per_base=3.75,rate_kind='official_currency_peg',source_id='sa_sama_peg_web',source_date='2020-05-04',source_quality='official_primary',calculation_type='direct_observation',note='SAMA affirms official3.75 riyals per USD. This is an official peg statement, not an annual-average market table.')])

def saudi():
    html=(RAW/'sa_umrah_2025.html').read_text()
    m=re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',html,re.S)
    a=json.loads(m[1])['props']['pageProps']['newsDetails']
    check('saudi_umrah_published_claim','more than 12.4 million Umrah visas' in a['content'])
    write_rows('saudi_observations',[dict(destination='SAU',year_label=2025,period_basis='2025_achievements_report_exact_counting_period_not_explicit',origin='WORLD',visa_group='umrah_Masar_Nusuk',metric='issued',value=12400000,value_relation='greater_than',precision='rounded_0.1_million',calendar_year_comparability='not_confirmed',source_date='2026-02-15',source_locator='SPA N2512740; article paragraph5; Ministry of Hajj and Umrah 2025 achievements',**source_fields('sa_umrah_report_2025'),note='Separate religious visa category. Not tourist evisa, not pilgrim arrivals, not all Saudi visas. Article mixes report-year and Hijri-season achievements; no calendar-year revenue calculation.' )])
    write_json('sa_umrah_news',{k:a[k] for k in ['uuid','published_at','title','content','locale']})

def scenarios(annual):
    output=[]
    for a in annual:
        if a['year'] not in [2024,2025] or a['origin'] not in ['CHN','WORLD']:continue
        for child_share in [0,0.02,0.05,0.10]:
            output.append(dict(destination='RUS',origin=a['origin'],year=a['year'],visa_group='unified_evisa',issued=a['issued'],government_adult_tariff=40,currency='USD',assumed_under6_share=child_share,value=round(a['issued']*(1-child_share)*40,2),calculation_type='scenario_assumption',source_quality='official_inputs_plus_explicit_assumption',model='issued_evisa_count * (1 - assumed_under6_share) * USD40',interpretation='government_tariff_value_for_issued_visas_under_age_scenario_not_actual_revenue',source_ids=['ru_evisa_annual_web','ru_evisa_fee_law'],note='Age-share sensitivities are illustrative, not fitted estimates. Unsuccessful paid applications excluded; no actual revenue interval follows. Payment/precheck/insurance charges excluded. Do not describe this as minimum revenue because under6 visas are free.'))
    write_rows('russia_tariff_scenarios',output)

def gaps():
    write_rows('remaining_gaps',[
      dict(destination='TUR',item='Chinese annual visa quantities',status='not_located_in_retrieved_official_report',impact='No Chinese fee-flow estimate. Tourist arrivals cannot replace visa issues.'),
      dict(destination='TUR',item='2025 sticker/all-channel total',status='not_located_in_retrieved_official_report',impact='2025 evisa total is observed; other channels remain missing.'),
      dict(destination='TUR',item='2024/2025 nationality-specific primary tariffs and receipt revenue',status='not_recovered',impact='USD60 for China retains historical/secondary support only. Global fees vary by nationality and channel.'),
      dict(destination='RUS',item='Paid applications/refusals and under6 share',status='not_published_in_retrieved_tables',impact='Issued×USD40 is adult tariff benchmark, not actual revenue.'),
      dict(destination='RUS',item='Consular country table vs annual global table',status='published_source_discrepancy',impact='Country/post sums below published global annual totals; both preserved, no residual allocated to countries.'),
      dict(destination='SAU',item='2024/2025 tourist visa issues; Chinese quantities; actual tourist visa revenue',status='not_located_in_retrieved_sources',impact='SAR300 base tariff known; cannot multiply tourism arrivals or Umrah visas by it.'),
      dict(destination='SAU',item='Historical channel-specific insurance/tax/platform composition',status='partially_identified',impact='2024 service guide quotes SAR463.44; other quoted checkout totals are not universal government fee.'),
    ])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--refresh',action='store_true');parser.add_argument('--extract-pdfs',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.refresh:refresh()
    if args.extract_pdfs:extract_pdfs()
    sources=manifest();annual=russia();turkey();fees_policies();saudi();scenarios(annual);gaps()
    write_json('extraction_checks',CHECKS)
    report=dict(built_at=DATE,source_records=len(sources),checks=len(CHECKS),source_discrepancies=[c for c in CHECKS if not c['passed']],outputs=sorted(p.name for p in OUT.glob('*.csv')))
    write_json('build-output',report);print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
