#!/usr/bin/env python3
"""Offline official fee controls, with explicit precedence and modeled allocations."""
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
import zipfile

from bs4 import BeautifulSoup
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PKG = 'r12_fiscal'
OUT = ROOT / 'data/research' / PKG
FRA = {2019:(219,0.5), 2020:(61,0.5), 2021:(56,0.5), 2024:(261,1)}
FX_SID = 'afx_wb_exchange_rates'
FX_CNY = 'fx_fed_g5a_20260105'


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',',':'))+'\n')


def read(path):
    return json.loads((ROOT/path).read_bytes())


def fiscal_observation(oid, code, year, value, currency, sid, locator, notes):
    return dict(observation_id=oid, destination=code, origin='UNK', origin_basis='unallocated_nationality',
                year=year, period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                period_type='calendar_year', observation_domain='finance',
                metric='visa_fee_receipts', visa_group='unclassified', visa_type='visa_fiscal_leaf',
                value=value, unit=currency, source_id=sid, source_locator=locator, source_status='actual',
                calculation_type='official_reported_receipts', aggregation_role='non_additive_financial_control',
                context_only=True, eligible_money_ledger=False, notes=notes)


def new_row(code, year, slug, amount, low, high, currency, sids, oids, label, status, notes, **params):
    return dict(id=f'r12_{slug}_{year}_UNK', payer='UNK', receiver=code, year=year,
                amount=amount, lower=low, upper=high, currency=currency,
                quantity=None, quantity_basis='no_matching_paid_application_denominator',
                visa_group='unclassified', category_detail_status='unclassified',
                visa_type=slug, visa_label=label, method_id=f'r12_{slug}',
                source_ids=sids, observation_ids=oids, model_status=status,
                calculation_type=status, origin_basis='unallocated_nationality', notes=notes, parameters=params)


def make_range(r, method):
    return {**{k:r[k] for k in ('receiver','year','currency','amount','lower','upper')}, 'range_method':method}


def evidence():
    OUT.mkdir(parents=True, exist_ok=True)
    obs=[]
    fr = BeautifulSoup((ROOT/'data/raw/france/senate-visa-report-20250924.html').read_bytes(), 'html.parser')
    p = next(x for x in fr.select('p') if '61 millions' in x.get_text(' ',strip=True).replace('\xa0',' ')
             and '2020 (61 millions' in x.get_text(' ',strip=True).replace('\xa0',' '))
    t = ' '.join(p.get_text(' ',strip=True).split())
    assert all(k in t for k in ('2020 (61 millions','2021 (56 millions','2024 à près de 261 millions','2019 (219 millions'))
    for y,(whole,uncertainty) in FRA.items():
        obs.append(fiscal_observation(f'r12_fr_senate_receipts_{y}','FRA',y,whole*1_000_000,'EUR',
            'fr_senate_visa_2024','Rapport 904, partie III.I, § après la comparaison Allemagne/États-Unis/Japon (#toc46)',
            '参议院财政委员会引用主管机构资料，签证费按国库非税收入登记。原文按百万欧元表述，2024为接近261百万。没有分开公布短期与长期实收，也没有国籍拆分。'))
    page = PdfReader(ROOT/'data/raw/global_asia_me_europe/lka_2025.pdf').pages[44].extract_text(extraction_mode='layout')
    assert 'Extensions of' in page and 'Travel' in page
    records = {}
    for year,*nums in re.findall(r'^\s*(201[9]|202[0-5])' + r'\s+([\d,]+)'*7 + r'\s*$',page,re.M):
        records[int(year)] = [int(n.replace(',','')) for n in nums]
    assert [records[y][3] for y in range(2019,2026)]==[1170,823,1335,4476,7091,8557,8186]
    for y in range(2019,2024):
        obs.append(fiscal_observation(f'r12_lka_receipts_{y}','LKA',y,records[y][3]*1_000_000,'LKR',
            'game_lka_report2025',f'PDF p45, Revenue Analysis 2019–2025, {y}, Issuances/Extensions of visa',
            '签证签发／延期实收；原表以LKR百万计，ETA、护照及其他科目排除。'))
    fx = []
    with zipfile.ZipFile(ROOT/'data/raw/africa_expansion_v3/wb_fx_dataset.zip') as z:
        member=next(n for n in z.namelist() if n.startswith('API_') and n.endswith('.csv'))
        for r in csv.DictReader(z.read(member).decode('utf-8-sig').splitlines()[4:]):
            code=r['Country Code']
            if code not in ('NPL','LKA'):continue
            for y in range(2019,2024 if code=='LKA' else 2023):
                n=float(r[str(y)])
                assert n>0
                fx.append(dict(fx_id=f'r12_fx_{code}_{y}',year=y,currency={'LKA':'LKR','NPL':'NPR'}[code],usd_per_unit=1/n,local_per_usd=n,
                               source_id=FX_SID,source_locator=f'{member}; {code}; PA.NUS.FCRF; {y}'))
    assert len(fx)==9
    dump(OUT/'sources.json',[])  # All sources already have stable entries in earlier packages.
    dump(OUT/'coverage.json',[
        dict(code=code,year=y,visa_group='unclassified',source_ids=[sid],notes=note)
        for code,years,sid,note in [
            ('FRA',FRA,'fr_senate_visa_2024','法国参议院签证费总额约束，短期模型与未分余额互斥。'),
            ('LKA',range(2019,2024),'game_lka_report2025','签发及延期实际收款；排除单列电子旅行授权。')]
        for y in years
    ])
    dump(OUT/'observations.json',obs)
    dump(OUT/'fx.json',fx)
    return obs


def model(obs):
    rows, ranges, replacements = [], [], []
    candidate={}
    for src, years in [('history',(2019,2020,2021)),('core',(2024,))]:
        old = read(f'data/estimates/{src}_flows.json')
        scope = [r for r in old['flows'] if r['receiver']=='FRA' and r['year'] in years]
        replacements.append(dict(package=src,flow_ids=[r['id'] for r in scope],
                                 range_scopes=[dict(receiver='FRA',year=y) for y in years],
                                 reason='Move the unchanged Schengen short-stay model into the jointly controlled French receipt scope.'))
        for y in years:
            base=next(r for r in old['destination_ranges'] if r['receiver']=='FRA' and r['year']==y)
            parts=[r for r in scope if r['year']==y]
            assert abs(sum(r['amount'] for r in parts)-base['amount'])<0.001
            candidate[y]=(parts,base)
    for y,(value,uncertainty) in FRA.items():
        scope,base=candidate[y]
        value*=1_000_000
        uncertainty*=1_000_000
        low,high=value-uncertainty,value+uncertainty
        center=base['amount']
        assert low>center
        rows.extend(scope)
        r=new_row('FRA',y,'fr_visa_receipts_unallocated_residual',value-center,max(0,low-base['upper']),high-base['lower'],
                  'EUR',['fr_senate_visa_2024',*sorted({s for p in scope for s in p['source_ids']})],
                  [f'r12_fr_senate_receipts_{y}'],'国家签证费总额扣除已建模短期份额后的余额',
                  'official_total_control_modeled_scope_residual',
                  '官方总额与原短期签证模型只计一次：保留短期估算分项，差额保留国籍及类别未分。差额不是已证实的长期签证费。分项情景随实收总额约束，不能独立相加。',
                  reported_receipts_eur=value,receipt_precision_scenario_eur=uncertainty,
                  schengen_fee_model_center_eur=center,schengen_fee_model_range_eur=[base['lower'],base['upper']])
        rows.append(r)
        ranges.append(dict(receiver='FRA',year=y,currency='EUR',amount=value,lower=low,upper=high,
                           range_method='法国参议院非税签证费总额约束：按文本公布精度设情景，短期模型与未归属余项不重复。'))
    for o in obs:
        if o['destination']!='LKA':continue
        year,value=o['year'],o['value']
        r=new_row('LKA',year,'lk_issuances_extensions_receipts',value,value-500_000,value+500_000,'LKR',
                  [o['source_id'],FX_SID,FX_CNY],[o['observation_id']],'签证签发及延期实收',
                  'official_receipts_unallocated','斯里兰卡年度实收，含签证延期；ETA 及其他账户排除。区间表示报告百万卢比取整。',
                  published_rounding_half_unit=500_000)
        rows.append(r)
        ranges.append(make_range(r,'同年实收，原表取整精度情景。'))
    nep=read('data/research/south_asia_expansion_v7/annual_cash_controls.json')
    nep={r['year']:r for r in nep}
    for y in range(2019,2023):
        a,b=nep[y],nep[y+1]
        center=(a['amount']+b['amount'])/2
        bounds=[a['amount']*(1-w)+b['amount']*w for w in (0.4,0.6)]
        r=new_row('NPL',y,'np_receipts_half_year_bridge',center,min(bounds),max(bounds),'NPR',
                  list(dict.fromkeys([a['source_id'],b['source_id'],FX_SID,FX_CNY])),
                  [f'sv7_npl_fy{i}_14228_cash' for i in (y,y+1)],'签证费实收基准（相邻财年桥接）',
                  'half_year_fiscal_bridge_estimate',
                  '当期财政年在7月中旬转换；较早原档未核实逐日界线，中心取相邻两个财年签证科目14228实际收款各半。40–60%为时间分配情景，不代表置信区间。付款人国籍未知。',
                  fiscal_years=[a['fiscal_year'],b['fiscal_year']],fiscal_receipts_npr=[a['amount'],b['amount']],
                  adjacent_fiscal_weight=.5,adjacent_fiscal_weight_range=[.4,.6])
        rows.append(r)
        ranges.append(make_range(r,'两财年实收各半；次财年权重40–60%情景。'))
    assert len(rows)==len({r['id'] for r in rows})
    assert all(0<=r['lower']<=r['amount']<=r['upper'] for r in rows)
    models=[dict(model_id=f'r12_{slug}', destination=dest, years=years, status='fiscal_evidence_2026',
                 formula=formula, limitations=limits)
            for slug,dest,years,formula,limits in [
     ('fr_visa_receipts_unallocated_residual','FRA',list(FRA),'published total minus modeled C fee sum',
      ['短期分项仍为模型。','余额不归属国籍或签证类别。','2024原文给约数，±100万为展示情景。']),
     ('lk_issuances_extensions_receipts','LKA',list(range(2019,2024)),'observed issuance/extension receipts × 1,000,000',
      ['排除 ETA，付款人国籍与匹配申请次数未知。']),
     ('np_receipts_half_year_bridge','NPL',list(range(2019,2023)),'0.5 × each adjacent fiscal actual; 0.4–0.6 next-FY scenario',
      ['保持原财政年实绩与自然年估算的区别。'])]]
    dump(ROOT/f'data/estimates/{PKG}_flows.json',dict(package=PKG,flows=rows,destination_ranges=ranges,models=models,replaces=replacements))
    print(json.dumps(dict(observations=len(obs),new_components=13,retained_french_model_components=len(rows)-13,
                          paired_national_controls=len(ranges))))


if __name__=='__main__':
    import sys
    obs=evidence()
    if '--evidence-only' not in sys.argv:
        model(obs)
