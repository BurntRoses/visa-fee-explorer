#!/usr/bin/env python3
"""Nepal national visa cash accounts and visa context; frozen, offline rebuild.

Only this independent package is written. Fiscal observations, calendar bridges,
latest-fiscal-level proxies and administrative context remain distinct.
"""
from __future__ import annotations
from collections import Counter
import csv
from datetime import date
from decimal import Decimal
import hashlib
import json
import logging
from pathlib import Path
import re
import zipfile
import pycountry
from pypdf import PdfReader
from entity_names import canonical_name

logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/south_asia_expansion_v7'
OUT=ROOT/'data/research/south_asia_expansion_v7'
ASOF='2026-11-17'
SOURCES=[
 ('sv7_npl_cfs2020','npl_fcgo_cfs2020_cdn1.pdf','2bf6f5f7a4acc0316917fa838d03630a9b1f84fae5e5b72ae669f59373177ce5',
  'https://giwmscdnone.gov.np/media/pdf_upload/20210517185110_CFS_2019_2020%20final_mktdwf5.pdf',
  '尼泊尔财政总审计长办公室 FCGO','Consolidated Financial Statement 2019/20',
  'Annex4 PDF62提供2018/19、2019/20百万精度实际收入；PDF176提供2019/20精确签证费叶科目。'),
 ('sv7_npl_cfs2021','npl_fcgo_cfs2021_cdn1.pdf','9c3f1cda85a32f884d1c0a1e30ab27652efe4425c6a00d131f0058a5227a51d6',
  'https://giwmscdnone.gov.np/media/pdf_upload/20250127145826_2020-2021_xtybcb6.pdf',
  '尼泊尔财政总审计长办公室 FCGO','Consolidated Financial Statement 2020/21',
  'Annex3 PDF49和Annex4 PDF54均以NPR百万为单位；collection和utilization不是两笔收入。'),
 ('sv7_npl_cfs2022','npl_fcgo_cfs2022_cdn1.pdf','c2260b3a4fe8894454829d6deca5fb6fa086f959be15cba93cfabb7cc8d04b7a',
  'https://giwmscdnone.gov.np/media/pdf_upload/20250127145608_CFS%202021-2022_qetdf7b.pdf',
  '尼泊尔财政总审计长办公室 FCGO','Consolidated Financial Statement 2021/22',
  'Annex3 PDF54、Annex4 PDF61；NPR原币，2020/21比较值沿用整万精度。'),
 ('sv7_npl_cfs2023','npl_fcgo_cfs2023.pdf','e2a6059685d89c9e81b69f259fbc87941b437963f43d2fa4ede7889e71cfe5bf',
  'https://giwmscdnone.gov.np/media/pdf_upload/20240725124752_cfs2022-2023_q53t9je.pdf',
  '尼泊尔财政总审计长办公室 FCGO','Consolidated Financial Statement 2022/23',
  'Annex1.1 Collection PDF232、Annex1.2 Utilization PDF236；选全国联邦收入叶科目14228，不加父级。政策PDF16明确2022-07-17至2023-07-16。'),
 ('sv7_npl_cfs2024','npl_fcgo_cfs2024.pdf','e9ad963908680ed07ec9b3b1caccb612bc8e8b14a32c667b4dd6a97ce2f34d7f',
  'https://giwmscdnone.gov.np/media/pdf_upload/20250629144539_CFS%202023-2024_fmeywfy.pdf',
  '尼泊尔财政总审计长办公室 FCGO','Consolidated Financial Statement 2023/24',
  'Annex1.1 PDF244与Annex1.2 PDF248复核一致；政策PDF16明确2023-07-17至2024-07-15。'),
 ('sv7_npl_cfs2025','npl_fcgo_cfs2025.pdf','682d6e6d81ec7f2658266796256218b7782f112854ad881db85d8de437bc2ec7',
  'https://giwmscdnone.gov.np/media/pdf_upload/CFS_FY2024.25%20._5dndpkp.pdf',
  '尼泊尔财政总审计长办公室 FCGO','Consolidated Financial Statement 2024/25',
  '扫描PDF；PDF180/184原图人工转录14228，PDF16原图核对现金基础、NPR币种及精确财政期间。人工fixture不是独立来源。'),
 ('sv7_npl_doi2026','npl_doi_book2026.pdf','9c4642a540c14f9edf26c006829363da9907abca4737acca203819d329cb95cb',
  'https://immigration.gov.np/doi-notice-file/Notices-202608041537423010.pdf',
  '尼泊尔移民局 Department of Immigration','Immigration & Emigration Related Facts & Figures, Year6 Issue1 July2026',
  '2025国籍×签证类型原表；PDF82–89跨页存在相同文字的离页副本，按序号核对重复页并只取一次。印刷总数及类别合计有矛盾，原值留存。财政表仅部门及下属办公室，不加全国CFS。'),
 ('sv7_npl_es2026','npl_econsurvey2026_en.pdf','c3ac0207fdf301d519f20e900a55b4629bbc14e3db2101e1476899c797f0cddd',
  'https://giwmscdnone.gov.np/media/pdf_upload/Final%20Merged%20ES_5_15_7ym4ycg.pdf',
  '尼泊尔财政部 Ministry of Finance','Economic Survey2026, Annex12.1 Details of Visa',
  'PDF459印刷184，2019–2025共17类签证和已发布总数；2019和2023算术不一致，不能自动改数或当作匹配付费分母。'),
 ('sv7_npl_oag2026','npl_oag63_2026.pdf','b891feefb95476ac14f5d8143b17ffa9ce4a2f2a52c90e6965fa345591ac7745',
  'https://oag.gov.np/site_uploads/mahalkhaparakashhakaka-ou-varashhaka-paratavathana-1435411017.pdf',
  '尼泊尔审计长办公室 OAG','63rd Annual Report2026, Home Affairs, DoI paragraph15',
  'PDF298–299印刷266–267；2024/25电子门户签证费加罚金与RMIS入账差异，混合口径不替代14228签证费收入。'),
]
TYPES=[('tourist','Tourist','visitor'),('business','Business','visitor'),('transit','Transit','visitor'),
 ('marriage','Marriage','family'),('study','Study','student'),('residential','Residential','other'),
 ('nrn','NRN','other'),('relation','Relation','family'),('working','Working','work'),
 ('diplomatic','Diplomatic','other'),('official','Official','other'),('dependent','Dependent','family'),
 ('press','Press','other'),('reciprocity','Reciprocity','other'),('consular_gratis','ConsularGratis','other'),
 ('saarc_endorsement','SAARCTravelEndorsement','other'),('non_tourist_other','NonTouristVisa(Others)','other')]
TYPE_ZH={'tourist':'旅游签证','business':'商务签证','transit':'过境签证','marriage':'婚姻签证','study':'学习签证',
 'residential':'居民签证','nrn':'非居民尼泊尔人签证','relation':'亲属签证','working':'工作签证',
 'diplomatic':'外交签证','official':'公务签证','dependent':'家属签证','press':'记者签证','reciprocity':'互惠签证',
 'consular_gratis':'领事免费签证','saarc_endorsement':'南亚区域合作联盟旅行签注','non_tourist_other':'其他非旅游签证','all':'全部签证'}
ALIASES={'Aland Islands':'ALA','Cape Verde':'CPV',"Cote d'Ivoire":'CIV','Democratic Republic of the Congo':'COD',
 'European Union':'EU27_2020','Holy See (Vatican City)':'VAT',
 'Hong Kong (Chinese special administrative region)':'HKG','Macao Special Administrative Region of China':'MAC',
 'Kosovo':'XKX','Laos':'LAO','Libyan Arab Jamahiriya':'LBY','Micronesia, Federated States':'FSM',
 'North Korea':'PRK','North Sudan':'SDN','Occupied Palestinian Territory':'PSE','R_union':'REU',
 'Refugee and others':'UNK','Russia':'RUS','Saint Kitts and Neviss':'KNA','St.Kitts and Nevis':'KNA',
 'South Korea':'KOR','Swaziland':'SWZ','Taiwan(China)':'TWN','Macedonia':'MKD','Turkey':'TUR',
 'United Arab Emirates (UAE)':'ARE','United Nations (UN)':'UNK','United Republic of Tanzania':'TZA',
 'United States of America (USA)':'USA','United States Virgin Islands':'VIR','Wallis and Futuna Islands':'WLF'}


def write(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    if isinstance(obj,list) and obj and isinstance(obj[0],dict):
        keys=list(dict.fromkeys(k for r in obj for k in r))
        with (OUT/name.replace('.json','.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,keys);w.writeheader()
            w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in obj)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sources,checks,observations,controls,candidates,conflicts,coverage=[],[],[],[],[],[],[]
    readers={};text_cache={}
    def check(name,ok,**e):
        checks.append(dict(check=name,passed=bool(ok),**e))
        assert ok,(name,e)
    for sid,filename,digest,url,publisher,title,notes in SOURCES:
        p=RAW/filename;data=p.read_bytes();actual=hashlib.sha256(data).hexdigest()
        check(sid+'_original',actual==digest and data.startswith(b'%PDF'),sha256=actual,bytes=len(data))
        sources.append(dict(source_id=sid,url=url,local_path=str(p.relative_to(ROOT)),path=str(p.relative_to(ROOT)),
          publisher=publisher.replace('财政总审计长办公室','财政总会计长办公室'),title=title,retrieved_at=ASOF,source_quality='official_original',
          archive_kind='original_document',original_downloaded=True,sha256=actual,bytes=len(data),notes=notes))
        readers[sid]=PdfReader(p)
    for sid,filename,url,publisher,title in [
      ('sv7_npl_cfs_directory','npl_fcgo_english_index.html','https://fcgo.gov.np/category/consolidated-us',
       '尼泊尔财政总审计长办公室 FCGO','CFS official English directory establishing CDN provenance'),
      ('sv7_npl_doi_directory','npl_doi_publication_index.html','https://immigration.gov.np/publication',
       '尼泊尔移民局 Department of Immigration','Official immigration fact-book publication directory')]:
        p=RAW/filename;b=p.read_bytes()
        check(sid+'_html',b'<html' in b.lower())
        sources.append(dict(source_id=sid,url=url,local_path=str(p.relative_to(ROOT)),path=str(p.relative_to(ROOT)),
          publisher=publisher.replace('财政总审计长办公室','财政总会计长办公室'),title=title,retrieved_at=ASOF,source_quality='official_original',archive_kind='original_document',
          original_downloaded=True,sha256=hashlib.sha256(b).hexdigest(),bytes=len(b)))
    directory=(RAW/'npl_fcgo_english_index.html').read_text()
    for filename in ['CFS_FY2024.25','20250629144539_CFS','20240725124752_cfs','20250127145608_CFS','20250127145826_2020','20210517185110_CFS']:
        check('official_directory_'+filename,filename in directory)
    def page(sid,n,mode='layout'):
        key=(sid,n,mode)
        if key not in text_cache:
            text_cache[key]=readers[sid].pages[n-1].extract_text(extraction_mode=mode) or ''
            (OUT/f'{sid}_pdf_p{n}_{mode}.txt').write_text(text_cache[key]+'\n')
        return text_cache[key]
    def probe(sid,n,needle,mode='layout'):
        t=page(sid,n,mode)
        check(sid+'_p'+str(n)+'_probe_'+str(len(checks)),re.sub(r'\s+','',needle) in re.sub(r'\s+','',t),needle=needle)
        return f'PDF p{n}; {needle}'
    def amount_line(sid,n,amount,position=-1,scale=1):
        t=page(sid,n)
        lines=[l for l in t.splitlines() if '14228' in l and re.search(r'Visa',l,re.I)]
        check(sid+'_p'+str(n)+'_visa_leaf_line',len(lines)==1,line=lines)
        tokens=re.findall(r'(?<!\d)\d[\d,]*\.\d{2}(?!\d)',lines[0])
        check(sid+'_p'+str(n)+'_actual_column_'+str(len(checks)),Decimal(tokens[position].replace(',',''))*scale==Decimal(str(amount)),
              tokens=tokens,selected_column=position,scale=scale,expected=amount)
        return lines[0].strip()
    fixture=json.loads((RAW/'npl_cfs2025_visual_transcription.json').read_text())
    check('2025_manual_transcription_original_hash',fixture['original_sha256']==next(s['sha256'] for s in sources if s['source_id']=='sv7_npl_cfs2025'))
    check('2025_collection_utilization_agree',fixture['collection']['amount_npr']==fixture['utilization']['amount_npr']=='4725958738.12')
    check('2025_original_not_fact_excerpt',fixture['capture_method']=='manual_visual_transcription_from_archived_original')
    for r in [fixture['collection'],fixture['utilization']]:
        check('2025_render_p'+str(r['pdf_page']), (ROOT/r['rendered_page']).is_file())
    (OUT/'npl_cfs2025_manual_transcription.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n')
    # Exact dates are only assigned where the original reporting-policy page gives them.
    periods={2023:('2022-07-17','2023-07-16'),2024:('2023-07-17','2024-07-15'),2025:('2024-07-16','2025-07-16')}
    for y,startq,endq in [(2023,'July 17, 2022','July 16, 2023'),(2024,'July 17, 2023','July 15, 2024')]:
        probe(f'sv7_npl_cfs{y}',16,f'from {startq}, to {endq}')
        probe(f'sv7_npl_cfs{y}',16,'cash')
    probe('sv7_npl_cfs2020',15,'cash basis of accounting')
    probe('sv7_npl_cfs2021',13,'cash basis of accounting','plain')
    probe('sv7_npl_cfs2022',13,'cash basis of accounting')
    annual={2019:(2680400000,'sv7_npl_cfs2020',62,1,1000000,10000),
            2020:(2876232350.37,'sv7_npl_cfs2020',176,-1,1,.01),
            2021:(1091010000,'sv7_npl_cfs2021',49,-1,1000000,10000),
            2022:(2007400381.17,'sv7_npl_cfs2022',54,-1,1,.01),
            2023:(3585812680.51,'sv7_npl_cfs2023',232,-1,1,.01),
            2024:(4179267099.07,'sv7_npl_cfs2024',244,-1,1,.01),
            2025:(4725958738.12,'sv7_npl_cfs2025',180,-1,1,.01)}
    for y,(amount,sid,n,col,scale,precision) in annual.items():
        fy=f'{y-1}/{str(y)[2:]}'
        raw=fixture['collection']['raw_amount'] if y==2025 else amount_line(sid,n,amount,col,scale)
        if y==2019:probe(sid,n,'Rs. in million')
        if y==2021:probe(sid,n,'NPR. In Million')
        start,end=periods.get(y,(None,None));oid=f'sv7_npl_fy{y}_14228_cash'
        observations.append(dict(observation_id=oid,source_id=sid,source_ids=[sid],
          source_locator=f'PDF p{n}; revenue leaf14228; fiscal year{fy}; actual/revenue receipts column',
          source_quote=raw,destination='NPL',destination_display_name='尼泊尔',reporting_country='NPL',
          origin='UNK',nationality='UNK',origin_basis='unallocated',year=y,fiscal_year=fy,
          period_start=start,period_end=end,period_type='fiscal_year',period_label='FY'+fy,
          period_date_precision='exact_original_reporting_policy' if start else 'fiscal_year_label_only',
          metric='visa_fee_cash_receipts',raw_metric='14228 Visa Fee / Visa fees',value=amount,unit='NPR',currency='NPR',
          account_code='14228',accounting_basis='cash',accounting_scope='federal_government_national_account',
          published_amount_quantum_npr=precision,calculation_type='direct_observation',
          source_status='published_fiscal_cash_actual',observation_domain='government_visa_receipts',
          selected_annual_control=True,context_only=False,eligible_money_ledger=False,
          aggregation_role='selected_national_visa_revenue_leaf',visa_group='unclassified',
          quantity=None,quantity_basis='no_matching_paid_event_denominator',
          notes='全国联邦政府14228签证费现金科目；国籍、收费用途及匹配付费数量未知。财年不作自然年实际。'
                +(' 原表百万保留两位小数，量值精度为1万NPR。' if precision==10000 else '')
                +(' 数字从归档原始扫描PDF人工看图转录；collection与utilization仅计一次。' if y==2025 else '')))
        ctrl=dict(year=y,fiscal_year=fy,receiver='NPL',payer='UNK',amount=amount,currency='NPR',account_code='14228',
          period_start=start,period_end=end,period_type='fiscal_year',period_label='FY'+fy,
          date_precision='exact' if start else 'fiscal_year_label_only',published_amount_quantum_npr=precision,
          source_id=sid,observation_id=oid,scope='national_federal_visa_cash_receipts',matching_paid_quantity=None)
        controls.append(ctrl)
        candidates.append(dict(id=oid+'_UNK',payer='UNK',receiver='NPL',year=y,fiscal_year=fy,
          amount=amount,lower=amount,upper=amount,currency='NPR',quantity=None,
          quantity_basis='no_matching_paid_application_denominator',visa_group='unclassified',
          visa_type='national_14228_visa_receipts',visa_label='签证费实收（用途未细分）',category_detail_status='unclassified_aggregate',
          source_ids=[sid],observation_ids=[oid],method_id='sv7_npl_fiscal_cash_actual',
          model_status='published_fiscal_actual',calculation_type='direct_observation',origin_basis='unallocated',
          period_start=start,period_end=end,period_type='fiscal_year',period_label='FY'+fy,
          eligible_calendar_ledger=False,notes='财政年原币实收候选；必须保留FY期间，不可按year静默当作自然年。'
            '不与同一期间的游客×标准费情景、部门子账、collection/utilization重复相加。',
          parameters=dict(account_code='14228',accounting_basis='cash',payer_allocation='UNK',
                          published_amount_quantum_npr=precision,calendar_alignment='none')))
    # Independent comparative and utilization probes are checks, not additional control money.
    cross=[(2020,'sv7_npl_cfs2020',62,-1,1000000,2876230000),
           (2020,'sv7_npl_cfs2021',49,1,1000000,2876230000),
           (2021,'sv7_npl_cfs2021',54,-1,1000000,1091010000),
           (2021,'sv7_npl_cfs2022',54,1,1,1091010000),
           (2022,'sv7_npl_cfs2022',61,-1,1,2007400381.17),
           (2023,'sv7_npl_cfs2023',236,-1,1,3585812680.51),
           (2024,'sv7_npl_cfs2024',248,-1,1,4179267099.07)]
    crosschecks=[]
    for y,sid,n,col,scale,v in cross:
        raw=amount_line(sid,n,v,col,scale)
        preferred=annual[y][0]
        check('crosscheck_'+str(y)+'_'+sid+'_'+str(n),abs(v-preferred)<=5000,
              selected_value=preferred,comparison_value=v,difference=v-preferred)
        crosschecks.append(dict(year=y,source_id=sid,pdf_page=n,value=v,currency='NPR',selected_value=preferred,
          aggregation_role='non_additive_comparison_or_utilization',source_quote=raw))
    crosschecks.append(dict(year=2025,source_id='sv7_npl_cfs2025',pdf_page=184,value=4725958738.12,currency='NPR',
          aggregation_role='non_additive_utilization_counterpart',source_quote=fixture['utilization']['raw_amount']))
    # Annual visa context from the separate Economic Survey; preserve published arithmetic issues.
    es=page('sv7_npl_es2026',459)
    esrows={}
    for line in es.splitlines():
        m=re.match(r'^\s*(\d+)\s+(.+?)\s+((?:\d+\s+){6}\d+)\s*$',line)
        if m:esrows[int(m[1])]=(m[2].strip(),list(map(int,m[3].split())))
    check('es_seventeen_type_rows',sorted(esrows)==list(range(1,18)))
    total_line=next(l for l in es.splitlines() if 'Grand Total' in l)
    published=list(map(int,re.findall(r'\d+',total_line)))
    check('es_seven_years',len(published)==7)
    eschecks=[]
    for j,y in enumerate(range(2019,2026)):
        summed=sum(v[1][j] for v in esrows.values())
        residual=summed-published[j]
        check('es_known_arithmetic_'+str(y),residual=={2019:-90000,2023:1000}.get(y,0),
              type_sum=summed,published_total=published[j],residual=residual)
        eschecks.append(dict(year=y,type_sum=summed,published_total=published[j],type_sum_minus_published=residual,
          source_id='sv7_npl_es2026',source_locator='PDF459, Annex12.1',
          quality_status='internally_inconsistent_source' if residual else 'arithmetic_reconciled'))
        for k,(slug,label,group) in enumerate(TYPES,1):
            observations.append(dict(observation_id=f'sv7_npl_es_{y}_{slug}',source_id='sv7_npl_es2026',source_ids=['sv7_npl_es2026'],
              source_locator=f'PDF459 Annex12.1 row{k} {y}',source_label_raw=esrows[k][0],
              destination='NPL',reporting_country='NPL',origin='WORLD',origin_basis='published_global_total',
              year=y,period_start=f'{y}-01-01',period_end=f'{y}-12-31',period_type='calendar_year',
              metric='visas_issued',value=esrows[k][1][j],unit='visas',visa_type=slug,visa_group=group,
              series_id='sv7_npl_es_'+slug,series_label='尼泊尔 · '+TYPE_ZH[slug]+'签发（经济调查）',
              context_only=True,eligible_money_ledger=False,observation_domain='visa_activity',
              aggregation_role='visa_type_component',source_status='published_count_with_source_total_flags',
              source_year_total_arithmetic_residual=residual,
              quality_issue=(f'源表{y}年17类合计{summed}，已发布总数{published[j]}，类别合计减总数为{residual}；原值保留。' if residual else None),
              notes='签发件数包含收费和免费类别；不是付费申请人数、独立人数或收入。原表年份与总数保留，未修正源文矛盾。'))
        observations.append(dict(observation_id=f'sv7_npl_es_{y}_published_total',source_id='sv7_npl_es2026',source_ids=['sv7_npl_es2026'],
          source_locator=f'PDF459 Annex12.1 Grand Total {y}',destination='NPL',reporting_country='NPL',origin='WORLD',
          origin_basis='published_global_total',year=y,period_start=f'{y}-01-01',period_end=f'{y}-12-31',period_type='calendar_year',
          metric='visas_issued',value=published[j],unit='visas',visa_type='all',visa_group='all',
          series_id='sv7_npl_es_total',series_label='尼泊尔 · 全部签证签发（经济调查）',
          context_only=True,eligible_money_ledger=False,observation_domain='visa_activity',
          aggregation_role='non_additive_published_total',source_year_total_arithmetic_residual=residual,
          source_status='internally_inconsistent_source' if residual else 'published_count',
          quality_issue=(f'源表{y}年17类合计{summed}，已发布总数{published[j]}，类别合计减总数为{residual}；原值保留。' if residual else None),
          notes='总数与类别不重复加总；2019、2023存在源表算术差异，保留原值。'))
    # The book contains identical off-page spreads. Every source index is retained once.
    def parse_countries(n):
        rows={};duplicates=0
        for line in page('sv7_npl_doi2026',n,'plain').splitlines():
            m=re.match(r'^\s*(\d+)\s+(.+?)\s+((?:\d+\s+){17}\d+)\s*$',line)
            if m:
                row=(int(m[1]),m[2].strip(),list(map(int,m[3].split())))
                if row[0] in rows:
                    check('doi_same_page_duplicate_'+str(n)+'_'+str(row[0]),rows[row[0]]==row)
                    duplicates+=1
                else:rows[row[0]]=row
        check('doi_same_page_duplicate_count_'+str(n),duplicates==len(rows),duplicates=duplicates,unique_rows=len(rows))
        return [rows[i] for i in sorted(rows)]
    country_rows=[]
    for n in [82,84,86,88]:
        rows=parse_countries(n);other=parse_countries(n+1)
        check('doi_identical_offpage_spread_'+str(n),rows==other and bool(rows),rows=len(rows),counterpart=n+1)
        country_rows += [dict(index=i,name=name,values=values,pdf_page=n) for i,name,values in rows]
    check('doi_218_source_country_buckets',len(country_rows)==218 and sorted(r['index'] for r in country_rows)==list(range(1,219)))
    display_path=RAW/'country_display_names_frozen.json'
    if not display_path.exists():
        entities=json.loads((ROOT/'data/processed/entities.json').read_text())
        display_path.write_text(json.dumps({x['code']:x['name'] for x in entities},ensure_ascii=False,indent=2)+'\n')
    entity_names=json.loads(display_path.read_text())
    def country(raw):
        if raw in ALIASES:return ALIASES[raw]
        try:return pycountry.countries.lookup(raw).alpha_3
        except LookupError:raise ValueError(('unmapped_country',raw))
    mismatches=[];mapping=[]
    code_counts=Counter(country(r['name']) for r in country_rows)
    for r in country_rows:
        code=country(r['name']);display=canonical_name(code,entity_names.get(code) or r['name'])
        if code=='UNK':display='联合国（原表身份桶）' if 'United Nations' in r['name'] else '难民及其他（未分国籍）'
        if code=='EU27_2020':display='欧盟（原表区域桶）'
        partner_code=code+':'+hashlib.sha256(r['name'].encode()).hexdigest()[:10] if code_counts[code]>1 else code
        partner_label=display+'（原表：'+r['name']+'）' if code_counts[code]>1 and code!='UNK' else display
        vals=r['values'];residual=vals[-1]-sum(vals[:-1]);idx=r['index']
        mapping.append(dict(source_index=idx,source_label_raw=r['name'],code=code,display_name=display,
          context_partner_code=partner_code,context_partner_label=partner_label,
          scope='source_non_country_bucket' if code in ['UNK','EU27_2020'] else 'published_country_or_region_bucket'))
        if residual:mismatches.append(dict(source_index=idx,source_label_raw=r['name'],code=code,published_total=vals[-1],type_sum=sum(vals[:-1]),residual=residual))
        for k,(slug,label,group) in enumerate([*TYPES,('all','Total','all')]):
            observations.append(dict(observation_id=f'sv7_npl_doi2025_r{idx}_{slug}',source_id='sv7_npl_doi2026',source_ids=['sv7_npl_doi2026'],
              source_locator=f'PDF{r["pdf_page"]} (identical off-page counterpart{r["pdf_page"]+1}); country table10.1 row{idx}; {label}',
              source_row_index=idx,source_label_raw=r['name'],origin_label=display,origin_display_name=display,
              destination='NPL',destination_display_name='尼泊尔',reporting_country='NPL',origin=code,partner_country=code,
              context_partner_code=partner_code,context_partner_label=partner_label,
              origin_basis='source_country_bucket' if code in ['UNK','EU27_2020'] else 'nationality',
              year=2025,period_start='2025-01-01',period_end='2025-12-31',period_type='calendar_year',
              metric='visas_issued',value=vals[k],unit='visas',visa_type=slug,visa_group=group,
              series_id=f'sv7_npl_doi_{slug}',series_label='尼泊尔 · '+TYPE_ZH[slug]+'签发（移民局）',
              context_only=True,eligible_money_ledger=False,observation_domain='visa_activity',
              aggregation_role='non_additive_published_country_total' if slug=='all' else 'country_type_component',
              source_row_total_minus_types=residual,source_status='published_count_with_source_arithmetic_flags',
              quality_issue=(f'本源行已发布总数{vals[-1]}，17类合计{sum(vals[:-1])}，相差{residual}。' if residual else '本源行类别合计与行总数一致。')
                +'全表已发布总数863684、国家源行总数合计864276，相差592；Transit列已发布2115、国家叶项合计2215，相差100。原值保留。',
              notes='签发件数不等于付费事件、申请人或财政收入；免费和收费份数未分离。源表类别与总数存在差异；保留原值。'
                '同一标准代码可能有不同原始标签叶项，源行身份独立，不按代码直接去重。'))
    printed_total=[834213,4517,2115,1616,1028,17,3228,8416,2133,950,2202,1860,4,6,752,46,481,863684]
    leaf_sums=[sum(r['values'][j] for r in country_rows) for j in range(18)]
    check('doi_leaf_column_sums',leaf_sums==[834213,4517,2215,1616,1028,17,3228,8416,2133,950,2202,1860,4,6,752,46,481,864276],leaf_sums=leaf_sums)
    doi_obs=[r for r in observations if r['source_id']=='sv7_npl_doi2026']
    check('doi_exactly_eighteen_metric_choices',len({r['series_id'] for r in doi_obs})==18)
    check('doi_unique_metric_partner_period',len({(r['series_id'],r['context_partner_code'],r['period_end']) for r in doi_obs})==len(doi_obs))
    check('doi_row_total_source_discrepancy',len(mismatches)==35 and sum(r['residual'] for r in mismatches)==592,
          discrepant_rows=len(mismatches),residual=sum(r['residual'] for r in mismatches))
    total_probe='834213 4517 2115 1616 1028 17 3228 8416 2133 950 2202 1860 4 6 752 46 481 863684'
    probe('sv7_npl_doi2026',88,total_probe,'plain')
    doi_totals=dict(published_column_totals=printed_total,leaf_column_sums=leaf_sums,
       leaf_type_sum=sum(leaf_sums[:-1]),leaf_row_total_sum=leaf_sums[-1],
       published_grand_total=printed_total[-1],leaf_totals_minus_published=leaf_sums[-1]-printed_total[-1],
       row_total_minus_type_sum=leaf_sums[-1]-sum(leaf_sums[:-1]),
       transit_published=printed_total[2],transit_leaf_sum=leaf_sums[2],
       economic_survey2025_total=published[-1],source_status='internally_inconsistent_source_not_repaired',
       eligible_money_denominator=False)
    for code in ['CHN','HKG','MAC','TWN']:
        check('one_china_display_'+code,all(r['display_name']==canonical_name(code,'') for r in mapping if r['code']==code))
    # Department subset revenue is contextual; its missingFY2078/79 header is not fabricated.
    dept_years=[2020,2021,2023,2024,2025]
    dept_values=[577644120.64,602935324.09,891437097.93,947548567.56,1009254823.09]
    dept_rows=[]
    probe('sv7_npl_doi2026',92,'14228','plain')
    for y,v in zip(dept_years,dept_values):
        dept_rows.append(dict(year=y,fiscal_year=f'{y-1}/{str(y)[2:]}',source_id='sv7_npl_doi2026',source_locator='PDF92 printed80 Table12 14228',
          value=v,currency='NPR',aggregation_role='non_additive_department_subset',national_control=annual[y][0],
          eligible_money_ledger=False,context_only=True,
          notes='原表仅列2076/77、2077/78、2079/80、2080/81、2081/82，缺2078/79；不是连续五年，范围为移民局及下属办公室。'))
        check('department_subset_below_national_'+str(y),v<annual[y][0])
    # Mixed visa+fine audit differences remain independent from the visa-only leaf.
    audit=dict(source_id='sv7_npl_oag2026',source_locator='PDF298–299 printed266–267 Home Affairs DoI paragraph15',
      fiscal_year='2024/25',portal_visa_plus_fines_npr=5153372000,rmis_deposited_npr=4369488000,
      difference_npr=783884000,foreign_mission_visa_plus_fines_explanation_npr=777741000,
      unexplained_residual_npr=6143000,eligible_money_ledger=False,context_only=True,
      scope='visa_fees_plus_fines_mixed_portal_scope_not_account14228',
      notes='审计指出境外使领馆签证费与罚金因RMIS不支持外币导致入账差异；不把混合门户额替代或加到全国14228。')
    check('audit_portal_difference',audit['portal_visa_plus_fines_npr']-audit['rmis_deposited_npr']==audit['difference_npr'])
    check('audit_explanation_residual',audit['difference_npr']-audit['foreign_mission_visa_plus_fines_explanation_npr']==audit['unexplained_residual_npr'])
    probe('sv7_npl_oag2026',299,'७८ करोड ३८ लाख ८४ हजार')
    # Reuse the already-registered original FX dataset; no duplicate source registration.
    fxpath=ROOT/'data/raw/africa_expansion_v3/wb_fx_dataset.zip'
    check('fx_original_hash',hashlib.sha256(fxpath.read_bytes()).hexdigest()=='a565ae178924699a3a254159b4a93e99f077270ffa7f7941c4bfb687883927ce')
    z=zipfile.ZipFile(fxpath);member=next(n for n in z.namelist() if n.startswith('API_') and n.endswith('.csv'))
    fxrow=next(r for r in csv.DictReader(z.read(member).decode('utf-8-sig').splitlines()[4:]) if r['Country Code']=='NPL')
    cny={2023:7.0809,2024:7.1957,2025:7.1875}
    fx=[dict(fx_id=f'sv7_npl_fx_{y}',year=y,currency='NPR',local_per_usd=float(fxrow[str(y)]),usd_per_unit=1/float(fxrow[str(y)]),
      cny_per_usd=cny[y],cny_per_npr=cny[y]/float(fxrow[str(y)]),source_id='afx_wb_exchange_rates',
      cny_source_id='fx_fed_g5a_20260105',source_locator=f'{member}; NPL; PA.NUS.FCRF; {y}') for y in cny]
    external=[dict(source_id='afx_wb_exchange_rates',local_path=str(fxpath.relative_to(ROOT)),
      registered_in='data/research/africa_expansion_v3/sources.json',sha256=hashlib.sha256(fxpath.read_bytes()).hexdigest(),reason='Reuse original annual-average NPR/USD data.'),
      dict(source_id='fx_fed_g5a_20260105',local_path='data/raw/fx/fed-g5a-20260105.html',
      registered_in='data/research/schengen_fx/sources.json',sha256='850ebe60416fbfe66c086a833a5b0df5fb41f0d7c252bb577ab89335911d698e',
      reason='Reuse registered CNY/USD annual-average2023–2025.')]
    check('cny_original_hash',hashlib.sha256((ROOT/external[-1]['local_path']).read_bytes()).hexdigest()==external[-1]['sha256'])
    # This calendar model is optional and separate from the original fiscal candidate file.
    calendar_candidates=[]
    for y in [2023,2024,2025]:
        f=next(x for x in fx if x['year']==y)
        if y<2025:
            terms=[]
            for endyear in [y,y+1]:
                start,end=map(date.fromisoformat,periods[endyear]);fy_days=(end-start).days+1
                a=max(start,date(y,1,1));b=min(end,date(y,12,31));overlap=(b-a).days+1
                terms.append(dict(fiscal_year_end=endyear,amount_npr=annual[endyear][0],fiscal_period_days=fy_days,
                                  calendar_overlap_days=overlap,contribution_npr=annual[endyear][0]*overlap/fy_days))
            check('calendar_full_day_coverage_'+str(y),sum(t['calendar_overlap_days'] for t in terms)==(date(y+1,1,1)-date(y,1,1)).days,terms=terms)
            amount=sum(t['contribution_npr'] for t in terms)
            # A timing scenario bracket, not statistical confidence or published receipts.
            low=min(annual[y][0],annual[y+1][0]);high=max(annual[y][0],annual[y+1][0])
            model_status='day_weighted_fiscal_to_calendar_model';method='sv7_npl_fiscal_day_weighted_bridge'
            note='两个相邻财政实际年度按原件精确期间假设日收入均匀后桥接；自然年数是估算。范围为相邻FY总额的时间分配情景，非置信区间。'
            inputs=[y,y+1]
        else:
            amount=annual[y][0];low=amount*.85;high=amount*1.15;terms=[];inputs=[y]
            model_status='latest_fiscal_level_calendar_proxy';method='sv7_npl_latest_fiscal_level_proxy'
            note='仅FY2024/25实际已发布；将该FY年度水平作为CY2025代理，±15%仅为时间敏感情景；不是CY2025实际或2025/26实际。'
        calendar_candidates.append(dict(id=f'sv7_npl_calendar_{y}_UNK',payer='UNK',receiver='NPL',year=y,
          amount=amount,lower=low,upper=high,currency='NPR',amount_cny=amount*f['cny_per_npr'],
          lower_cny=low*f['cny_per_npr'],upper_cny=high*f['cny_per_npr'],quantity=None,
          quantity_basis='no_matching_paid_application_denominator',visa_group='unclassified',
          visa_type='national_14228_visa_receipts',visa_label='签证费实收基准（自然年估算）',
          category_detail_status='unclassified_aggregate',source_ids=[annual[i][1] for i in inputs]+['afx_wb_exchange_rates','fx_fed_g5a_20260105'],
          observation_ids=[f'sv7_npl_fy{i}_14228_cash' for i in inputs],method_id=method,
          model_status=model_status,calculation_type='modeled_estimate',origin_basis='unallocated',
          period_start=f'{y}-01-01',period_end=f'{y}-12-31',period_type='calendar_year_model',period_label=f'{y}自然年估算',
          notes=note+' 国籍与用途未知，不能按签发或游客份额分配。接入必须替换旧Nepal游客×标准费模型，不可叠加。',
          parameters=dict(account_code='14228',fiscal_actual_inputs=inputs,day_weight_terms=terms,
              range_kind='timing_sensitivity_not_statistical_confidence',fx_id=f['fx_id'],
              proxy_timing_multiplier_range=[.85,1.15] if y==2025 else None)))
    baseline_path=OUT/'pre_v7_nepal_baseline.json'
    if not baseline_path.exists():
        rows=json.loads((ROOT/'data/processed/flows.json').read_text())
        baseline=[r for r in rows if r.get('receiver')=='NPL']
        check('baseline_old_tourist_model',len(baseline)==30 and all(r['method_id']=='game_npl_tourist_single_entry' for r in baseline))
        baseline_path.write_text(json.dumps(baseline,ensure_ascii=False,indent=2)+'\n')
    baseline=json.loads(baseline_path.read_text())
    impacts=[]
    for y in [2024,2025]:
        old=[r for r in baseline if r['year']==y];new=next(c for c in calendar_candidates if c['year']==y)
        impacts.append(dict(year=y,old_model_ids=[r['id'] for r in old],
          preserve_zero_fee_ids=[r['id'] for r in old if r['payer'] in ['CHN','IND'] and r['amount']==0],
          replace_old_model_ids=[r['id'] for r in old if r['amount']>0],
          old_tourist_model_cny=sum(r['amount_cny'] for r in old),
          new_national_calendar_model_cny=new['amount_cny'],delta_cny=new['amount_cny']-sum(r['amount_cny'] for r in old),
          replacement='replace_all_old_NPL_game_npl_tourist_single_entry_edges_once',unknown_payer_share=1,
          nationality_allocation='no_supported_cash_allocation',new_payer='UNK'))
    check('continuous_seven_fiscal_controls',[r['year'] for r in controls]==list(range(2019,2026)))
    check('single_selected_leaf_per_fiscal_year',all(v==1 for v in Counter(r['year'] for r in observations if r.get('selected_annual_control')).values()))
    check('unknown_payer_all_candidates',all(r['payer']=='UNK' and r['quantity'] is None for r in candidates+calendar_candidates))
    check('fiscal_candidates_never_silent_calendar',all(r['period_type']=='fiscal_year' and not r['eligible_calendar_ledger'] for r in candidates))
    check('unique_observation_ids',len({r['observation_id'] for r in observations})==len(observations))
    check('context_never_money_denominator',all(not r['eligible_money_ledger'] for r in observations))
    check('observation_source_resolves',all(r['source_id'] in {s['source_id'] for s in sources} for r in observations))
    for y in range(2019,2026):
        for group in ['visitor','student','work','family','other','unclassified']:
            coverage.append(dict(code='NPL',destination='NPL',name='尼泊尔',region='亚洲',year=y,visa_group=group,
              period_type='fiscal_year',fiscal_year=f'{y-1}/{str(y)[2:]}',
              status='national_fiscal_visa_cash_actual' if group=='unclassified' else 'category_amount_not_identified',
              amount_known=group=='unclassified',fiscal_amount_known=True,amount_modeled=False,
              quantity_known=False,quantity_context_known=True,nationality_known=False,nationality_context_known=y==2025,
              source_ids=[annual[y][1],'sv7_npl_es2026']+(['sv7_npl_doi2026'] if y==2025 else []),
              category_detail_status='unclassified_aggregate' if group=='unclassified' else 'no_classified_cash_observation',
              notes='14228全国签证费实收为财政年；签发数量背景为自然年，二者没有匹配付费分母。国籍签发背景不分配财政收入。',searched_as_of=ASOF))
    outputs={'sources.json':sources,'external_source_references.json':external,'observations.json':observations,
      'annual_cash_controls.json':controls,'fiscal_controls.json':controls,'non_additive_fiscal_crosschecks.json':crosschecks,
      'model_candidates.json':candidates,'calendar_model_candidates.json':calendar_candidates,'fx.json':fx,
      'economic_survey_arithmetic.json':eschecks,'doi2025_country_mapping.json':mapping,
      'doi2025_country_rows.json':country_rows,'doi2025_row_arithmetic_issues.json':mismatches,
      'doi2025_source_total_conflicts.json':doi_totals,'department_subset_fiscal_context.json':dept_rows,
      'audit_portal_reconciliation.json':audit,'replacement_impact.json':impacts,'coverage.json':coverage,'checks.json':checks}
    for filename,obj in outputs.items():write(filename,obj)
    report=dict(package='south_asia_expansion_v7',asof=ASOF,frozen=True,integration_status='independent_ready_for_root_integration',
      source_count=len(sources),official_original_pdf_count=len(SOURCES),observation_count=len(observations),
      selected_fiscal_actuals=len(controls),fiscal_years=[r['fiscal_year'] for r in controls],
      fiscal_candidate_count=len(candidates),optional_calendar_candidate_count=len(calendar_candidates),
      visa_context_years=list(range(2019,2026)),visa_2025_country_source_buckets=len(country_rows),
      visa_2025_unique_standard_codes=len({r['code'] for r in mapping}),checks=len(checks),passed=sum(r['passed'] for r in checks),
      latest_fiscal_actual_npr=annual[2025][0],latest_actual_period=periods[2025],
      integration_contract=dict(replace_method_id='game_npl_tourist_single_entry',replace_receiver='NPL',
        replace_calendar_years=[2024,2025],preserve_explicit_CHN_IND_free_tourist_edges=True,
        preserve_flow_ids=[f'game_npl_tourist_single_entry_{y}_{c}_visitor' for y in [2024,2025] for c in ['CHN','IND']],
        fiscal_candidates_require_fiscal_period_display=True,
        calendar_candidates='data/research/south_asia_expansion_v7/calendar_model_candidates.json',
        calendar_actual_claim_permitted=False,additive_with_old_tourist_model=False,payer='UNK',quantity=None,
        package_registration=['sources.json','observations.json','coverage.json'],shared_files_modified=False),
      limitations=['财政前四年原件未提供本包已核实的Gregorian精确起止日，保持FY标签，不补造日期。',
        '2025自然年仅最新财政年水平代理，未获得FY2025/26实际。',
        '14228全国联邦账户与部门子账、门户签证加罚金范围不同，保持非加总。',
        '签发份数包括免费项目且源表算术有差异，没有匹配付费数量，不能生成每次申请费用。'])
    write('report.json',report)
    table='\n'.join(f'| FY{r["fiscal_year"]} | {r["amount"]:,.2f} | {r["source_id"]} |' for r in controls)
    (OUT/'README.md').write_text(f'''# 尼泊尔签证实际收入与签发背景 v7

离线重建：`.research-venv/bin/python scripts/research_south_asia_expansion_v7.py`。仅写本包目录，不改共享模型或主数据。

新增{len(sources)}个官方原始来源（{len(SOURCES)}份PDF、2个官方目录），{len(observations)}条观察；7个连续财政年全国14228 Visa Fee实际收入。最新FY2024/25为NPR **4,725,958,738.12**。

| 财政期间 | 全国14228签证费实收NPR | 来源 |
|---|---:|---|
{table}

FY2018/19与FY2020/21原表单位百万并保留两位小数，原币数值精度为1万NPR。其他年度保留到分。选财政Collection叶科目，Utilization对照表仅校核一次，不重复加钱。2024/25扫描PDF看图转录fixture附原件SHA、PDF页、印刷页与页面图像；它不是新的独立来源。

`model_candidates.json`仅含7条原始财政年候选，不能直接按year当作自然年。`calendar_model_candidates.json`另含2023、2024精确期间日数加权桥接与2025最新FY年度水平代理。桥接假设收入在各FY内均匀，2025代理±15%是时间情景，均不冒充自然年实绩。

接入需替换旧`game_npl_tourist_single_entry`模型的2024/25游客费用情景；保留有明确政策支持的CHN旅游零费与IND无需签证零费边共4条，其余26条旧正额情景边移除，新增总量不能叠加旧正额。`replacement_impact.json`列出逐年完整旧id、替换id和保留id。旧游客×标准费推算的国籍份额不保留为财政分配；新总量国籍未知为UNK。费用用途未知；数量为null，不把签发或游客用作收费分母。

签发背景包含经济调查2019–2025共17类及已发布总数、移民局2025共218个原始国籍/地区桶×17类和原表总数。相同页内与跨页离页文字核对相同后仅取一次；同一ISO代码不同原始标签的源行保留身份。源表35行类别合计与总数不一致，合计差592；Transit列总数2115与叶项2215不同；总表863684与国家行合计864276不同。经济调查2019、2023总数也有算术差异，全部保留原值及标记。

移民局部门收入表和审计门户签证加罚金表单独保存。全国财政、部门子账、门户统计不相加，也不求平均。2025签发总数不同来源版本保留区别，不用来倒算实际收入。

本项目遵循一个中国原则；显示使用中国大陆、中国香港、中国澳门、中国台湾。来源原称另存，仅为统计关联。

{len(checks)}项确定性检查通过。`report.json`含接入契约、期间与剩余缺口；未修改共享注册、模型、UI或线上版本。
''')
    print(json.dumps({k:report[k] for k in ['package','source_count','observation_count','selected_fiscal_actuals','checks','passed']},ensure_ascii=False))


if __name__=='__main__':main()
