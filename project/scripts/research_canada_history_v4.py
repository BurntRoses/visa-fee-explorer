#!/usr/bin/env python3
"""Offline Public Accounts leaf-revenue history; no nationality backcasting.

Thirteen frozen official Volume II PDFs expose FY2010/11–FY2023/24.
Latest comparative presentation wins; earlier values remain in revisions.json.
Calendar flows stop at 2023, before the existing Canada model scopes.
"""
from pathlib import Path
from collections import defaultdict, Counter
import csv, hashlib, json, math, re
from bs4 import BeautifulSoup
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/canada_history_v4'
OUT = ROOT / 'data/research/canada_history_v4'
EST = ROOT / 'data/estimates/canada_history_v4_flows.json'
ASOF = '2026-11-17'
PAGES = {2012:195, 2013:191, 2014:200, 2015:201, 2016:302, 2017:289,
         2018:296, 2019:271, 2020:298, 2021:289, 2022:288, 2023:283, 2024:292}
COMPONENTS = {
    'trv_single_extension': dict(pattern=r'^Single entry and extension of status in Canada\b', label='单次入境及境内访客身份延期收费', group='visitor'),
    'trv_multiple': dict(pattern=r'^Multiple entry\b', label='访客签证多次入境收费科目', group='visitor'),
    'trv_family': dict(pattern=r'^Maximum per family\b', label='访客签证家庭封顶收费科目', group='visitor'),
    'work': dict(pattern=r'^Work permits?\b(?!.*(?:Group of artists|Exempt foreign workers))', label='工作许可基本申请收费', group='work'),
    'work_artists': dict(pattern=r'^(?:Work permits?\s*[—–-]\s*)?Group of artists\b', label='表演团体工作许可收费', group='work'),
    'study': dict(pattern=r'^Study permit\b', label='学习许可申请收费', group='student'),
    'open_work': dict(pattern=r'^Open Work Permit\s*[—–-]\s*Exempt foreign workers\b', label='开放工作许可持有人收费', group='work'),
}
NUMBER = re.compile(r'\(?-?\d{1,3}(?:,\d{3})+(?:\))?|[–—]')
BASE = ['trv_multiple', 'trv_family', 'work', 'work_artists', 'study']


def write(name, obj):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')
    if isinstance(obj,list) and obj and isinstance(obj[0],dict):
        keys=list(dict.fromkeys(k for r in obj for k in r))
        with (OUT/name.replace('.json','.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            w=csv.DictWriter(f,keys);w.writeheader()
            w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in obj)


def pdf_text(path, page):
    d=pdfium.PdfDocument(path);p=d[page-1];tp=p.get_textpage();t=tp.get_text_range()
    tp.close();p.close();d.close()
    return t


def parse_value(token):
    if token in ('–','—'):return 0
    return int(token.replace(',','').replace('(','-').replace(')',''))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sources=[];observations=[];checks=[];versions=defaultdict(list);excluded=[]
    urls={r['year']:r['url'] for r in json.loads((RAW/'pdf_download_manifest.json').read_text())}
    urls[2022]='https://publications.gc.ca/collections/collection_2022/spac-pspc/P51-1-2022-2-eng.pdf'
    for y in (2023,2024):urls[y]=f'https://www.tpsgc-pwgsc.gc.ca/recgen/cpc-pac/{y}/pdf/{y}-vol2-eng.pdf'

    def source(sid,path,url,title,notes=''):
        data=path.read_bytes()
        if path.suffix=='.pdf':assert data.startswith(b'%PDF'),path
        sources.append(dict(source_id=sid,local_path=str(path.relative_to(ROOT)),url=url,
                            publisher='Receiver General for Canada / Public Services and Procurement Canada',
                            title=title,retrieved_at=ASOF,source_quality='official_primary',archive_kind='original_document',
                            sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),notes=notes))
        return sid

    for publication,page in PAGES.items():
        sid=source(f'ca_hist_pa_{publication}',RAW/f'pdf{publication}.pdf',urls[publication],
                   f'Public Accounts of Canada {publication}, Volume II — detailed revenues',
                   '原表财政收入；不推定等于现金。财年4月1日至次年3月31日，保留当前年及比较前一年。PDF原件优先，后期同口径重分类值优先。')
        text=pdf_text(RAW/f'pdf{publication}.pdf',page)
        nexttext=pdf_text(RAW/f'pdf{publication}.pdf',page+1)
        (OUT/f'ca_pa_{publication}_p{page}.txt').write_text(text)
        (OUT/f'ca_pa_{publication}_p{page+1}_notes.txt').write_text(nexttext)
        assert 'Current year' in text and 'Previous year' in text and re.search('Revenue',text,re.I)
        for component,defn in COMPONENTS.items():
            lines=[]
            for line in text.splitlines():
                match=re.search(defn['pattern'],line,re.I)
                if match:
                    tokens=NUMBER.findall(line[match.end():])
                    # The work-permit header has no numeric cells. Do not treat
                    # it as a data row or search arbitrary following amounts.
                    if len(tokens)==2:lines.append((line,tokens))
            if not lines:continue
            assert len(lines)==1,(publication,component,lines)
            line,tokens=lines[0]
            values=[parse_value(t) for t in tokens]
            for column,value in enumerate(values):
                end=publication-column
                rec=dict(publication=publication,component=component,fiscal_end=end,value=value,
                         source_id=sid,source_locator=f'PDF p{page}, right-hand Revenues table, row {line.split(tokens[0])[0].strip()}, '+('Current year' if column==0 else 'Previous year'),
                         raw_line=line,raw_value=tokens[column],
                         comparative_reclassification_note='reclassified' in nexttext.lower() or 'reclassified' in text.lower(),
                         pdf_page=page)
                versions[end,component].append(rec)
        got={c for (y,c),rr in versions.items() if any(r['publication']==publication for r in rr)}
        checks.append(dict(check='five_base_leaf_accounts_present',publication=publication,passed=set(BASE)<=got,components=sorted(got)))
        # Preserve excluded nearby accounts as audit context; these amounts are
        # not monetised and cannot be added back to the selected fee controls.
        for line in text.splitlines():
            if re.search(r'Employer Compliance|Rights? of permanent residence|Citizenship rights|Passport|Permanent resident card|Temporary resident permits?|Restoration|Biometric|Electronic Travel',line,re.I):
                tokens=NUMBER.findall(line)
                if len(tokens)==2:excluded.append(dict(publication=publication,source_id=sid,pdf_page=page,raw_line=line,reason='Not one of the mutually exclusive selected visa/application fee leaves; excluded from this money model.'))

    # Cross-format validation for the latest two source tables. Remove footnote
    # superscripts before parsing; PDF regex already excludes attached footnote1.
    for publication in (2023,2024):
        path=RAW/f'ca_pa_{publication}_ircc.html'
        hsid=source(f'ca_hist_pa_{publication}_html',path,f'https://www.tpsgc-pwgsc.gc.ca/recgen/cpc-pac/{publication}/vol2/ircc/rev-eng.html',
                    f'Public Accounts of Canada {publication} — IRCC revenues HTML cross-check')
        soup=BeautifulSoup(path.read_text(),'html.parser')
        for tr in soup.select('table tr'):
            th=tr.find('th');td=tr.find_all('td')
            if not th or len(td)!=2:continue
            label=th.get_text(' ',strip=True)
            for sup in tr.find_all('sup'):sup.decompose()
            for c,d in COMPONENTS.items():
                if not re.search(d['pattern'],label,re.I):continue
                vals=[int(re.sub(r'[^\d-]','',x.get_text(' ',strip=True))) for x in td]
                native=[next(r['value'] for r in versions[publication-i,c] if r['publication']==publication) for i in (0,1)]
                checks.append(dict(check='HTML_PDF_leaf_values_equal',publication=publication,component=c,passed=vals==native,html=vals,pdf=native))

    revisions=[]
    for (end,component),rr in sorted(versions.items()):
        latest=max(rr,key=lambda x:x['publication']);value=latest['value']
        differing=[r for r in rr if r['value']!=value]
        if differing:revisions.append(dict(fiscal_end=end,component=component,selected=latest,earlier=differing,
                                             decision='Use latest published same-labelled leaf comparative presentation; earlier original retained, never sum versions.'))
        defn=COMPONENTS[component]
        observations.append(dict(observation_id=f'ca_hist_{component}_fy{end-1}_{end}',destination='CAN',origin='UNK',
                  origin_basis='unallocated',visa_group=defn['group'],visa_type=component,component=component,
                  metric='government_application_fee_reported_revenue',raw_metric=latest['raw_line'].split(latest['raw_value'])[0].strip(),
                  value=value,unit='CAD',period_start=f'{end-1}-04-01',period_end=f'{end}-03-31',period_type='fiscal_year',
                  calculation_type='direct_observation',source_id=latest['source_id'],source_ids=sorted({r['source_id'] for r in rr}),
                  source_locator=latest['source_locator'],observation_domain='finance',context_only=False,eligible_money_ledger=True,
                  aggregation_role='fee_leaf',series_id='canada_public_accounts_'+component,series_label=defn['label'],
                  accounting_basis='Reported fiscal revenue; not independently established to be cash receipts.',
                  supporting_evidence=rr,notes='加拿大财政年度已报告收入叶科目；国籍未知。学习／工作包括境内及延期；单次入境科目含境内访客身份延期。缺失科目不补零；明确破折号按0或四舍五入为0保留。'))

    # Reuse archived Fed originals already registered elsewhere. Only CAD values
    # are added, avoiding copies or conflicting rates for existing currencies.
    fx=[];selected_fx={}
    specs=[('data/research/temporal_expansion_v2/sources.json','tmx_fed_g5a_20130102'),
           ('data/research/temporal_expansion_v2/sources.json','tmx_fed_g5a_20160104'),
           ('data/research/history/sources.json','history_fed_20190102'),
           ('data/research/history/sources.json','history_fed_20220103'),
           ('data/research/history/sources.json','history_fed_20260105')]
    for registry,sid in specs:
        s=next(x for x in json.loads((ROOT/registry).read_text()) if x['source_id']==sid)
        assert hashlib.sha256((ROOT/s['local_path']).read_bytes()).hexdigest()==s['sha256']
        sources.append(s)
        soup=BeautifulSoup((ROOT/s['local_path']).read_text(),'html.parser')
        table=next(t for t in soup.select('table') if any('CANADA' in tr.get_text() for tr in t.select('tr')))
        header=[x.get_text(' ',strip=True) for x in table.select('tr')[0].select('th,td')]
        row=next(tr for tr in table.select('tr') if 'CANADA' in tr.get_text())
        values=[x.get_text(' ',strip=True) for x in row.select('th,td')]
        for y,v in zip(header[2:],values[2:]):
            year=int(y)
            if not 2011<=year<=2023:continue
            raw=float(v)
            if year in selected_fx:assert math.isclose(selected_fx[year]['raw_rate'],raw,rel_tol=1e-12)
            selected_fx[year]=dict(fx_id=f'ca_hist_fed_{year}_CAD',year=year,currency='CAD',raw_rate=raw,
                        raw_direction='currency_per_USD',usd_per_unit=1/raw,source_id=sid,
                        source_locator=f'G.5A annual table; CANADA / DOLLAR; {year}',
                        method='Federal Reserve annual average New York noon buying rates; historical year')
    fx=list(sorted(selected_fx.values(),key=lambda r:r['year']))
    assert set(selected_fx)==set(range(2011,2024))
    lookup={(int(r['period_end'][:4]),r['component']):r for r in observations}
    flows=[];ranges=[];models=[]
    for component,defn in COMPONENTS.items():
        years=[]
        for year in range(2011,2024):
            a,b=lookup.get((year,component)),lookup.get((year+1,component))
            if not a or not b:continue
            center=.25*a['value']+.75*b['value']
            scenarios=[w*a['value']+(1-w)*b['value'] for w in (.15,.25,.35)]
            years.append(year)
            flows.append(dict(id=f'ca_hist_{component}_{year}',payer='UNK',receiver='CAN',year=year,
                  visa_group=defn['group'],visa_type=component,visa_label=defn['label'],
                  amount=center,lower=min(scenarios),upper=max(scenarios),currency='CAD',quantity=None,
                  quantity_basis='fiscal_revenue_only_no_matching_application_denominator',
                  source_ids=sorted({*a['source_ids'],*b['source_ids']}),observation_ids=[a['observation_id'],b['observation_id']],
                  method_id='ca_hist_fiscal_bridge_'+component,model_status='calendar_model_from_reported_fiscal_revenue',
                  calculation_type='calendar_estimate',origin_basis='unallocated',
                  notes='明确财政叶科目按4月财年桥接；付款国籍未知保留UNK。无匹配申请次数，不计算每次申请均价。'+('本项同时含单次入境及境内访客身份延期，不能简写为单次签证。' if component=='trv_single_extension' else '包括此原始科目覆盖的境内／延期申请收费。'),
                  parameters=dict(actual_fiscal_revenue_observed=True,cash_receipts_not_independently_established=True,
                      fiscal_anchors=[{k:r[k] for k in ['observation_id','value','period_start','period_end','source_id','source_locator']} for r in [a,b]],
                      first_fiscal_weight=.25,first_fiscal_weight_range=[.15,.35],
                      timing_assumption='Uniform revenue recognition within each source fiscal year; first quarter uses FY ending in calendar year, last three quarters next FY.',
                      nationality_allocation='none; all UNK',event_denominator=None,category_scope=component,
                      range_method='Common fiscal-timing weights0.15/0.25/0.35; selected sensitivity, not confidence bounds.',
                      missing_component_policy='No imputation for absent leaf or introduction year; bridge only adjacent matching fiscal leaves.')))
        if years:models.append(dict(model_id='ca_hist_fiscal_bridge_'+component,destination='CAN',years=years,
                    visa_group=defn['group'],status='calendar_estimate_from_reported_fiscal_leaf',
                    formula='.25 * FY ending in CY + .75 * FY starting in CY',component=component,
                    limitations=['国籍未分配；不按当代份额回填历史。','财政收入不擅自称现金实收。','相同科目跨相邻财年桥接；类别出现或终止时不向外补零。','参数范围为时间配置敏感性。']))
    for year in range(2011,2024):
        rr=[r for r in flows if r['year']==year]
        scenarios=[]
        for w in (.15,.25,.35):
            scenarios.append(sum(w*lookup[year,r['visa_type']]['value']+(1-w)*lookup[year+1,r['visa_type']]['value'] for r in rr))
        ranges.append(dict(receiver='CAN',year=year,amount=sum(r['amount'] for r in rr),lower=min(scenarios),upper=max(scenarios),
                    currency='CAD',scope=' + '.join(r['visa_type'] for r in rr),
                    range_method='All included fee leaves share one common fiscal timing weight0.15/0.25/0.35; not sum of independent component extremes.'))
    coverage=[]
    for year in range(2011,2024):
        for group in ('visitor','student','work'):
            rr=[r for r in flows if r['year']==year and r['visa_group']==group]
            coverage.append(dict(code='CAN',year=year,visa_group=group,status='modeled_total',amount_modeled=bool(rr),
                    fee_known=False,quantity_known=False,quantity_context_known=False,
                    source_ids=sorted({s for r in rr for s in r['source_ids']}),
                    notes='历史财政收入叶科目自然年桥接；没有同口径付费申请数量或历史国籍分配。不同年度可识别叶科目组成见费用分项。'))
    existing=json.loads((ROOT/'data/processed/flows.json').read_text())
    checks += [dict(check='no_existing_Canada_year_overlap',passed=not any(r['receiver']=='CAN' and r['year']<2024 and not r['id'].startswith('ca_hist_') for r in existing)),
               dict(check='calendar_scopes_stop_before_existing_2024',passed=all(r['year']<=2023 and r['payer']=='UNK' and r['quantity'] is None for r in flows)),
               dict(check='no_absent_component_backfilled',passed=all((r['year'],r['visa_type']) in lookup and (r['year']+1,r['visa_type']) in lookup for r in flows)),
               dict(check='finite_ordered_ranges',passed=all(0<=r['lower']<=r['amount']<=r['upper'] for r in flows+ranges)),
               dict(check='source_ids_unique',passed=len({r['source_id'] for r in sources})==len(sources)),
               dict(check='observation_ids_unique',passed=len({r['observation_id'] for r in observations})==len(observations)),
               dict(check='all_sources_resolve',passed=all(s in {x['source_id'] for x in sources} for r in flows for s in r['source_ids'])),
               dict(check='all_calendar_totals_equal_components',passed=all(math.isclose(r['amount'],sum(f['amount'] for f in flows if f['year']==r['year']),rel_tol=1e-12) for r in ranges)),
               dict(check='known_2022_TRV_reclassification_preserved',passed=lookup[2022,'trv_multiple']['value']==76954928 and any(r['fiscal_end']==2022 and r['component']=='trv_multiple' for r in revisions)),
               dict(check='2011_base_revenue_scope_present',passed=set(BASE)<={r['visa_type'] for r in flows if r['year']==2011}),
               dict(check='2018_open_work_comparative_footnote_not_amount_digit',passed=lookup[2017,'open_work']['value']==17907263),
               dict(check='explicit_2016_17_single_leaf_dash_preserved_as_zero',passed=lookup[2017,'trv_single_extension']['value']==0),
               dict(check='excluded_nearby_accounts_have_no_money_flows',passed=all(r['visa_type'] in COMPONENTS for r in flows))]
    passed=all(c['passed'] for c in checks)
    payload=dict(package='canada_history_v4',as_of=ASOF,flows=flows,models=models,destination_ranges=ranges,
                 subtotals=[],scope='Canada historical visa/application revenue leaves; calendar2011–2023; payer nationality unallocated; no overlap with existing2024/25.')
    EST.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    report=dict(package='canada_history_v4',sources=len(sources),original_public_accounts_pdfs=13,
                observations=len(observations),fiscal_years=sorted({int(r['period_end'][:4]) for r in observations}),
                fee_flows=len(flows),models=len(models),calendar_years=list(range(2011,2024)),
                component_counts=dict(Counter(r['visa_type'] for r in flows)),revision_groups=len(revisions),
                observations_by_metric=dict(Counter(r['metric'] for r in observations)),
                annual_native=ranges,checks_passed=passed,check_count=len(checks),
                visual_checks=['Public Accounts2012PDFp195: Revenue table right-side Current/Previous columns, dollars and sixleafscope.',
                               'Public Accounts2018PDFp296: Openwork comparative superscript1, independent employer fee excluded.',
                               'Public Accounts2023PDFp283: Multipleentry previous-year76954928 with footnote1, not769549281.'])
    for name,obj in [('sources.json',sources),('observations.json',observations),('fee_rules.json',[]),('coverage.json',coverage),('fx.json',fx),('checks.json',checks),('revisions.json',revisions),('excluded_accounts.json',excluded),('report.json',report)]:write(name,obj)
    assert passed,[c for c in checks if not c['passed']]
    print(json.dumps({k:report[k] for k in ['package','sources','observations','fee_flows','models','component_counts','revision_groups','checks_passed','check_count']},ensure_ascii=False))


if __name__=='__main__':main()
