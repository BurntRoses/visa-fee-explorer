#!/usr/bin/env python3
"""Offline extension: 2011–14 consular applications and selected US cash controls.

Only documented annual records enter the package. Early Schengen workbooks have
different schemas; source subtotal rows never enter the bilateral ledger. US
calendar controls use two adjacent fiscal actuals and retain unknown nationality.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
import hashlib, json, math, re, warnings
import openpyxl
import pdfplumber
from bs4 import BeautifulSoup
from research_history import code as historic_code, UNKNOWN_LOCATIONS
from schengen_tariffs import FACILITATION_RULES, ASSOCIATED_RECEIVERS

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/time_space'
OUT = ROOT / 'data/research/time_space'
YEARS = tuple(range(2011, 2015))
URLS = json.loads((RAW / 'download_urls.json').read_text())
URLS['schengen_2014.xlsx'] = 'https://home-affairs.ec.europa.eu/document/download/a1620905-cb84-4de0-abd0-0e9358c45a4e_en?prefLang=en'


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def country(value):
    return 'CZE' if str(value).strip().upper() == 'CZECH REP.' else historic_code(str(value).strip())


class Package:
    def __init__(self):
        self.sources, self.obs, self.flows, self.models, self.ranges = [], [], [], [], []
        self.coverage, self.checks, self.conflicts = [], [], []
        self.used_tariff_sources = set()

    def source(self, name, title, publisher):
        p = RAW / name
        sid = 'tsx_' + name.replace('.', '_')
        self.sources.append(dict(source_id=sid, url=URLS[name], publisher=publisher, title=title,
                                 local_path=str(p.relative_to(ROOT)), sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                 bytes=p.stat().st_size, source_quality='official_primary',
                                 retrieved_at=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()))
        return sid

    def edge(self, payer, receiver, year, typ, amount, lower, upper, currency, sids, oids, quantity, notes, parameters):
        key=json.dumps([payer, receiver, year, typ], ensure_ascii=False)
        self.flows.append(dict(id='tsx_'+hashlib.sha256(key.encode()).hexdigest()[:20], payer=payer, receiver=receiver,
                               year=year, visa_group='visitor' if receiver!='USA' else 'other', visa_type=typ,
                               visa_label='申根短期' if receiver!='USA' else 'MRV（类别未分配）',
                               amount=amount, lower=lower, upper=upper, currency=currency, quantity=quantity,
                               quantity_basis='applications' if receiver!='USA' else 'official_receipt_control_without_payment_event_count',
                               source_ids=sorted(set(sids)), observation_ids=sorted(set(oids)),
                               method_id='tsx_schengen_early' if receiver!='USA' else 'tsx_us_fiscal_cash_bridge',
                               model_status='modeled_estimate' if receiver!='USA' else 'actual_cash_control_calendar_bridge',
                               origin_basis='modeled_nationality' if payer!='UNK' else 'unallocated_nationality',
                               period_start=f'{year}-01-01', period_end=f'{year}-12-31', period_type='calendar_year_model',
                               period_label=f'{year}自然年模型', notes=notes, parameters=parameters))

    def tariff(self, nationality, receiver, year):
        start, end = date(year,1,1), date(year+1,1,1)
        current=start; vals=[]; lows=[]; sids={'tsx_visa_code2009_html'}; gaps=[]
        while current<end:
            day=current.isoformat();amount=60.;low=60.
            rule=next((r for r in FACILITATION_RULES if r['nationality']==nationality and receiver in r['receivers']
                       and r['effective_from']<=day and (not r['effective_to'] or r['effective_to']>=day)),None)
            if rule:
                amount=rule['amount'] if rule['multiplier'] is None else 60*rule['multiplier']
                low=amount;sids.update(rule['source_ids'])
            elif receiver in ASSOCIATED_RECEIVERS and nationality in {'ARM','AZE','GEO','UKR','RUS','BLR','CPV'}:
                low=35.;gaps.append('关联国当期双边优惠缺证；60欧中心、35–60欧范围')
            # No backcast of the Iceland rule whose documented modelling start is 2015.
            vals.append(amount);lows.append(low);current+=timedelta(days=1)
        self.used_tariff_sources.update(sids-{'tsx_visa_code2009_html'})
        return sum(vals)/len(vals), min(lows), max(vals), sorted(sids), sorted(set(gaps))

    def schengen(self):
        sidfee=self.source('visa_code2009.html','Regulation (EC)810/2009, adopted Article16: EUR60 and child/waiver rules','European Parliament / Council; legislation.gov.uk')
        fee_text=BeautifulSoup((RAW/'visa_code2009.html').read_text(),'html.parser').get_text(' ',strip=True)
        assert re.search(r'EUR\s+60',fee_text)
        for year in YEARS:
            sid=self.source(f'schengen_{year}.xlsx',f'{year} Schengen visa statistics for consulates','European Commission DG HOME')
            workbook=openpyxl.load_workbook(RAW/f'schengen_{year}.xlsx',read_only=True,data_only=True)
            sheet=workbook['SCHENGEN' if year==2011 else 'Sheet1' if year==2012 else 'Complete data' if year==2013 else 'Data for consulates']
            header=next(sheet.iter_rows(values_only=True))
            qcol=next(i for i,value in enumerate(header) if str(value).strip() in {'C visas applied for','Uniform visas applied for'})
            ocol=2 if year<2013 else 1; ccol=ocol+1
            groups=defaultdict(lambda:dict(q=0,oids=[]));totals=defaultdict(float);row_count=0
            explicit_total=None
            for rownum,row in enumerate(sheet.iter_rows(min_row=2,values_only=True),2):
                if 'Total worldwide' in str(row[ccol]) or f'TOTAL Visas in {year}' in str(row[ccol]):explicit_total=row[qcol]
                if not all(row[index] for index in (0,ocol,ccol)):continue
                receiver,origin=country(row[0]),country(row[ocol]);rawq=row[qcol]
                assert receiver!='UNK',(year,rownum,row[0])
                assert rawq is None or isinstance(rawq,(int,float)),(year,rownum,rawq)
                q=rawq or 0;row_count+=1
                oid=f'tsx_sch_{year}_r{rownum}_{qcol+1}'
                self.obs.append(dict(observation_id=oid,source_id=sid,source_locator=f"'{sheet.title}'!{openpyxl.utils.get_column_letter(qcol+1)}{rownum}",
                                     destination=receiver,consulate_country=row[ocol],consulate=row[ccol],nationality=None,
                                     origin_basis='consulate_country',year=year,metric='applications',raw_metric=str(header[qcol]).strip(),
                                     value=rawq,unit='applications',visa_type='schengen_short_stay',visa_group='visitor',
                                     period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year',
                                     calculation_type='direct_observation' if rawq is not None else 'missing_source_cell',
                                     notes='逐领馆短期C/统一签申请；不含ATV、边检签与长期签。空白保持null。领馆所在地不是国籍。'))
                groups[origin,receiver]['q']+=q;groups[origin,receiver]['oids'].append(oid);totals[receiver]+=q
            detail_total=sum(totals.values())
            if explicit_total is not None:
                self.checks.append(dict(check='detail_matches_own_worldwide_total',year=year,detail=detail_total,reported=explicit_total,passed=detail_total==explicit_total))
            # Preserve a distinct summary-sheet conflict rather than modifying detailed cells.
            summary_sheet=workbook['Totals by Schengen State'] if year==2013 else workbook['Totals - Schengen State'] if year==2014 else None
            if summary_sheet is not None:
                for rownum,row in enumerate(summary_sheet.iter_rows(values_only=True),1):
                    receiver=country(row[0]) if row[0] else None
                    if receiver in totals and isinstance(row[1],(int,float)) and row[1]!=totals[receiver]:
                        self.conflicts.append(dict(year=year,receiver=receiver,detail_applications=totals[receiver],summary_applications=row[1],difference=totals[receiver]-row[1],source_id=sid,
                                                   source_locator=f"'{summary_sheet.title}'!B{rownum}",resolution='retain detailed consulate cells; separate inconsistent source summary not used as cash or calibrated total'))
            bydst=defaultdict(lambda:[0.,0.,0.]);sids={sid,sidfee}
            for (origin,receiver),group in sorted(groups.items()):
                q=group['q']
                if not q:continue
                # Moldova's biometric exemption began in 2014: keep that transition unallocated.
                share=.95 if (origin=='MDA' and year<2014) or (origin not in UNKNOWN_LOCATIONS and origin!='UNK') else 0.
                central,low,high,tsids,gaps=self.tariff(origin,receiver,year);sids.update(tsids)
                params=dict(consulate_country=origin,national_share_center=share,national_share_range=[.8,1] if share else [0,0],
                            effective_adult_fee_fraction=.9,effective_adult_fee_range=[.8,1],adult_fee_center_EUR=central,
                            historical_fee_timing_range_EUR=[low,high],tariff_uncertainties=gaps,unknown_nationality_fee_center_EUR=60,
                            historical_membership='source workbook Schengen rows only',excluded=['ATV','LTV as separate charge','long_stay','border_crossing_visas','private_service'],
                            uncertain_fee_scope='children, waivers, fee-exempt nationality distribution and expedited fees not observed')
                if share:
                    amount=q*.95*central*.9
                    self.edge(origin,receiver,year,'schengen_short_stay',amount,q*.8*low*.8,q*high,'EUR',[sid]+tsids,group['oids'],q*.95,
                              '官方逐领馆C类/统一短期申请×按当期国籍、收款政府与日期匹配成人费；递交地按95%本国国籍（80–100%情景）、有效收费90%（80–100%）。属于费用模型。',params)
                unknown_q=q*(1-share);amount=unknown_q*60*.9
                self.edge('UNK',receiver,year,'schengen_unknown_from_'+origin,amount,0 if share else unknown_q*35*.8,q*.2*60 if share else q*60,'EUR',[sid,sidfee],group['oids'],unknown_q,
                          '无法由递交地证明的国籍保留未知。未知中心按普通成人60欧，不继承所在地国籍优惠；低情景含35欧便利化。',params)
                bydst[receiver][0]+=q*(share*central+(1-share)*60)*.9
                bydst[receiver][1]+=q*.8*(.8*low+.2*35) if share else q*35*.8
                bydst[receiver][2]+=q*max(.8*high+.2*60,high) if share else q*60
            for receiver,(amount,lower,upper) in bydst.items():
                self.ranges.append(dict(receiver=receiver,year=year,amount=amount,lower=lower,upper=upper,currency='EUR',range_method='共同国籍分配/有效费率情景；不相加各国籍边际端点'))
            for conflict in (r for r in self.conflicts if r['year']==year):
                note=(f"原件口径冲突：{year}年{conflict['receiver']}逐领馆申请合计{conflict['detail_applications']:,.0f}，"
                      f"另表汇总{conflict['summary_applications']:,.0f}（{conflict['source_locator']}），"
                      f"差{conflict['difference']:+,.0f}；采用可定位明细，未校准抹平。")
                for edge in self.flows:
                    if edge['year']==year and edge['receiver']==conflict['receiver']:
                        edge['notes']+=' '+note
                        edge['parameters']['source_summary_conflict']=deepcopy(conflict)
            self.models.append(dict(model_id=f'tsx_schengen_{year}',destination='SCH',year=year,issuing_members=sorted(totals),members=sorted(set(totals)|{'LIE'}),
                                    source_ids=sorted(sids),quality='官方逐领馆申请×历史费率模型；不是官方实收',
                                    parameters=dict(nationality_share_center=.95,effective_fee_fraction_center=.9),
                                    missing='实际国籍、儿童与免收组合、长期与机场过境、急件与未证实关联国双边优惠；2013另有捷克/瑞士源汇总冲突'))
            self.coverage.append(dict(year=year,receiver='SCH',destination='SCH',issuing_receiver_count=len(totals),issuing_members=sorted(totals),applications=detail_total,
                                      consulate_rows=row_count,coverage_status='partial_visa_types',source_ids=[sid],
                                      notes=f'{year}年仅含25个当期独立收款政府的C类/统一短期签；长期、ATV与边检未包含。'+('捷克和瑞士源汇总与逐领馆明细冲突，采用明细，路线记录保留差异与定位。' if year==2013 else ''),
                                      scope='逐领馆C类/统一短期申请'+('；明细匹配本表全球总行，另表捷克/瑞士汇总冲突' if year==2013 else '；明细与原表总行核对')))
            self.checks.append(dict(check='historical_issuers_and_no_nationality_relabel',year=year,passed=len(totals)==25 and not set(totals)&{'BGR','ROU','HRV'},detail=dict(receivers=len(totals),applications=detail_total)))
            workbook.close()
        # Register the exact shared dated-treaty originals referenced by this extension.
        refined=json.loads((ROOT/'data/research/evidence_refinement/schengen/sources.json').read_text())
        self.sources.extend(s for s in refined if s['source_id'] in self.used_tariff_sources)
        self.checks.append(dict(check='2013_source_conflicts_explicit',passed={(r['receiver'],r['difference']) for r in self.conflicts if r['year']==2013}=={('CZE',-2751),('CHE',37626)},conflicts=self.conflicts))

    def us_cash(self):
        fiscal={}
        # Each actual column contains several MRV receipt sub-lines; sum all of them.
        for fy,budget_year in ((2019,2021),(2020,2022),(2021,2023),(2023,2025)):
            sid=self.source(f'budget{budget_year}_state.pdf',f'Budget FY{budget_year} Appendix, State: FY{fy} actual MRV cash','U.S. Office of Management and Budget / GovInfo')
            with pdfplumber.open(RAW/f'budget{budget_year}_state.pdf') as pdf:
                page=pdf.pages[2];w,h=float(page.width),float(page.height)
                texts=[page.crop(bounds).extract_text(x_tolerance=1) or '' for bounds in [(0,0,w/2,h),(w/2,0,w,h)]]
            text=next(t for t in texts if 'Special and Trust Fund Receipts' in t)
            table=text[text.index('Special and Trust Fund Receipts'):];table=table[:table.index('1199 Total current law receipts')]
            assert f'{fy} actual' in table
            entries=re.findall(r'1130 Machine-Readable Visa Fee, Consular and Border Security\nPrograms\s*\.+\s+([^\n]+)',table)
            assert entries,(fy,table)
            actuals=[]
            for entry in entries:
                token=entry.split()[0]
                actuals.append(0. if token.startswith('.') else float(token.replace(',','')))
            expected={2019:[1847,0],2020:[1,0,895],2021:[826,0],2023:[2220,0]}[fy]
            assert actuals==expected,(fy,actuals)
            amount=sum(actuals)*1e6;oid=f'tsx_us_FY{fy}_actual_mrv'
            self.obs.append(dict(observation_id=oid,source_id=sid,source_locator=f'PDF p3; Special and Trust Fund Receipts account019-5713, ALL row1130 Machine-Readable Visa Fee, FY{fy} actual column',
                                 destination='USA',nationality='UNK',origin_basis='unallocated_nationality',year=fy,metric='mrv_fee_receipts_actual',raw_metric='Machine-Readable Visa Fee, Consular and Border Security Programs',
                                 value=amount,unit='USD',visa_type='MRV_all_unallocated',visa_group='other',period_start=f'{fy-1}-10-01',period_end=f'{fy}-09-30',period_type='fiscal_year',calculation_type='official_cash_receipt',
                                 notes='MRV including BCC; all identically named MRV sub-lines summed. Excludes passport, IV surcharge, diversity, affidavit, SEVIS and USCIS. Source rounds each row to USD million.'))
            (OUT/f'us_FY{fy}_receipt_table.txt').write_text(table+'\n')
            fiscal[fy]=dict(amount=amount,sid=sid,oid=oid,precision=sum(v>0 for v in actuals)*.5e6)
        # Existing independently verified FY2024 original, not a new duplicate cash flow.
        existing=json.loads((ROOT/'data/research/us/actual_receipts.json').read_text())
        fy24=next(r for r in existing if r['period_label']=='FY2024')
        fiscal[2024]=dict(amount=fy24['value']*1e6,sid='us_omb2026',oid=fy24['observation_id'],precision=.5e6)
        for year in (2019,2020,2023):
            a,b=fiscal[year],fiscal[year+1];value=.75*a['amount']+.25*b['amount']
            alternatives=[(1-share)*a['amount']+share*b['amount'] for share in (.15,.25,.35)]
            precision=max(a['precision'],b['precision']);low=max(0,min(alternatives)-precision);high=max(alternatives)+precision
            self.edge('UNK','USA',year,'MRV_cash_control_unallocated',value,low,high,'USD',[a['sid'],b['sid']],[a['oid'],b['oid']],None,
                      '已核实两相邻美国财年MRV实际收款，按9/12与3/12均匀收款桥接自然年；不是观察到的自然年实收。第四季度权重15–35%是工作敏感性；历史国籍和签证类型未分配，保留UNK及其他类别。',
                      dict(fiscal_receipt_USD={str(year):a['amount'],str(year+1):b['amount']},next_fiscal_year_share_center=.25,next_fiscal_year_share_range=[.15,.35],
                           period_assumption='uniform receipts inside fiscal year',receipt_precision_USD=precision,nationality_allocation='none',type_allocation='none',actual_cash_not_visa_issuance=True))
            self.ranges.append(dict(receiver='USA',year=year,amount=value,lower=low,upper=high,currency='USD',range_method='两相邻财年MRV实收；次财年权重15–35%共同期间情景及原表取整'))
            self.coverage.append(dict(receiver='USA',destination='USA',year=year,coverage_status='fiscal_actual_calendar_bridge_unallocated',source_ids=[a['sid'],b['sid']],
                                      notes=f'美国{year}自然年由FY{year}和FY{year+1} MRV实际现金科目按75%/25%桥接；不是观测到的自然年实收。历史国籍和用途未分配，UNK/其他类别。',
                                      scope='全部MRV现金科目；未分配国籍/用途；非全部美国移民收费'))
        self.models.append(dict(model_id='tsx_us_fiscal_cash_bridge',destination='USA',years=[2019,2020,2023],source_ids=sorted({r['sid'] for r in fiscal.values()}),
                                formula='calendar[y]=0.75*actual_MRV_FY[y]+0.25*actual_MRV_FY[y+1]',
                                limitations=['财年内均匀收款是假设，第四季度15–35%是期间敏感性。','付款国籍/用途未识别，全部保留UNK/其他，不借用2024分配。','CY2021/2022未补：已归档FY2022表只有泛称offsetting receipts，未把位置推测当MRV科目证据。']))
        self.checks.append(dict(check='us_calendar_controls_use_two_actual_adjacent_fiscal_years',passed=True,calendar_years=[2019,2020,2023],fiscal_receipts_USD={str(y):r['amount'] for y,r in fiscal.items()}))

    def fx(self):
        sid=self.source('fed_g5a_20150102.html','G.5A annual exchange rates 2014, with 2011–13 comparisons','Federal Reserve Board')
        soup=BeautifulSoup((RAW/'fed_g5a_20150102.html').read_text(),'html.parser');columns=[];rates=[]
        for tr in soup.find_all('tr'):
            cells=[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'],recursive=False)]
            if cells and cells[0]=='COUNTRY':columns=[int(x) for x in cells[2:] if re.fullmatch(r'20\d\d',x)];continue
            if not columns or len(cells)!=2+len(columns):continue
            currency={'CHINAPR':'CNY','EMUMEMBERS':'EUR','UNITEDKINGDOM':'GBP'}.get(re.sub(r'[^A-Z]','',cells[0]))
            if not currency:continue
            for year,raw in zip(columns,cells[2:]):
                if year not in YEARS:continue
                value=float(raw.replace(',','').replace(' ',''))
                rates.append(dict(fx_id=f'tsx_fed_{year}_{currency}',year=year,currency=currency,raw_rate=value,
                                  raw_direction='currency_per_USD' if currency=='CNY' else 'USD_per_currency',usd_per_unit=1/value if currency=='CNY' else value,
                                  source_id=sid,source_locator=f'G.5A annual table; {cells[0]}; {year}',method='year-specific Federal Reserve annual average; no present-day FX backcast'))
        for year in YEARS:rates.append(dict(fx_id=f'tsx_fed_{year}_USD',year=year,currency='USD',usd_per_unit=1,source_id=sid,source_locator='USD numeraire',method='identity'))
        assert len(rates)==16
        return rates

    def run(self):
        OUT.mkdir(parents=True,exist_ok=True);self.schengen();self.us_cash();rates=self.fx()
        available_sources={s['source_id'] for s in self.sources}|{s['source_id'] for s in json.loads((ROOT/'data/research/us/sources.json').read_text())}
        available_obs={o['observation_id'] for o in self.obs}|{o['observation_id'] for o in json.loads((ROOT/'data/research/us/observations.json').read_text())}
        for edge in self.flows:
            assert set(edge['source_ids'])<=available_sources,(edge['id'],set(edge['source_ids'])-available_sources)
            assert set(edge['observation_ids'])<=available_obs,(edge['id'],'observations')
            assert 0<=edge['lower']<=edge['amount']<=edge['upper'] and edge['payer']!=edge['receiver'],edge['id']
            assert edge['year']<2024
        assert len({r['id'] for r in self.flows})==len(self.flows)
        assert len({r['observation_id'] for r in self.obs})==len(self.obs)
        for total in self.ranges:
            summed=sum(r['amount'] for r in self.flows if (r['receiver'],r['year'])==(total['receiver'],total['year']))
            assert math.isclose(summed,total['amount'],abs_tol=.001),(total,summed)
        self.checks.append(dict(check='flow_ids_references_nonnegative_ranges_and_conservation',passed=True,flows=len(self.flows),observations=len(self.obs)))
        conflict_edges=[r for r in self.flows if r['year']==2013 and r['receiver'] in {'CZE','CHE'}]
        self.checks.append(dict(check='source_conflict_visible_on_every_affected_route',passed=bool(conflict_edges) and all(r['parameters'].get('source_summary_conflict') and '原件口径冲突' in r['notes'] for r in conflict_edges),affected_flows=len(conflict_edges)))
        assert all(c['passed'] for c in self.checks),self.checks
        fees=[dict(fee_id='tsx_sch_adult_pre2020',destination='SCH',visa_type='schengen_short_stay',visa_group='visitor',amount=60,currency='EUR',effective_from='2011-01-01',effective_to='2014-12-31',fee_component='government_application_fee',source_ids=['tsx_visa_code2009_html'],source_locator='Article16(1); children and waivers Article16(2),(4)',notes='一般成人；优惠按国籍×收款政府×日期另行匹配，不是每人实付60欧。')]
        for name,value in [('sources.json',self.sources),('observations.json',self.obs),('fee_rules.json',fees),('fx.json',rates),('coverage.json',self.coverage),('checks.json',self.checks),('source_conflicts.json',self.conflicts)]:dump(name,value)
        (ROOT/'data/estimates/time_space_flows.json').write_text(json.dumps(dict(flows=self.flows,models=self.models,destination_ranges=self.ranges),ensure_ascii=False,indent=2)+'\n')
        report=['# 时空扩展：2011–2014与美国历史现金科目','',f'新增{len(self.flows):,}条费用分项、{len(self.obs):,}条来源观察；本包{len(self.sources)}条来源登记含复用，主库净增10个来源。','',
                '申根新增2011–2014。按各年原表25个独立收款政府处理；仅C类/统一短期，机场过境、边检和长期未加入。2011/12使用原表L列C申请，2013/14使用I列。2011/12没有把NON SCHENGEN、汇总、最大/最小/平均等行加入。',
                '', '历史一般成人法定费60欧；便利化按已有逐国籍、收款政府与生效日期原件匹配。关联国未证实双边优惠保留35–60范围；未反推2015起才有确切建模依据的冰岛/急件政策。国籍与收费仍采用显式情景。摩尔多瓦2011–13按需签递交地95%分配，2014免签过渡年保留未知。',
                '', '2013原件冲突：Complete data逐领馆合计17,285,449，等于同表Total worldwide；Totals by Schengen State合计17,250,574。差异全部来自捷克（明细646,719/汇总649,470）和瑞士（512,797/475,171）。保留逐行观察与单独冲突，不校准抹平、不宣称该年跨表总量复现。',
                '', '美国新增2019/2020/2023自然年模型，各自由当年FY实际收款75%+次年FY实际收款25%桥接。FY2019/20/21/23 MRV分别1847/896/826/2220百万美元（FY2020含1+895两条同名MRV子项）；FY2024使用已有2561百万美元。不是签发数量乘价、不是观察到的自然年实收。15–35%的次财年权重是工作情景。未知国籍及类别全部保持UNK/其他，未借2024份额回填。',
                '', 'FY2022原件只把全部科目写成offsetting receipts，未以行序猜测1644百万美元是MRV。因此2021/2022自然年金额没有填补。其他2015–2020预算也不因泛总科目而扩成签证实收。',
                '', '2011–14汇率来自美联储2014年度G.5A中各对应年度CNY/EUR/GBP，不用现价回填。旧2019后汇率由既有数据包提供。',
                '', '| 范围 | 年份 | 明细申请/金额 |','|---|---|---:|']
        report += [f"| {r['receiver']} | {r['year']} | {r.get('applications','相邻财年MRV实收桥接')} |" for r in self.coverage]
        report += ['','重建：`.research-venv/bin/python scripts/research_time_space.py`，不联网。来源SHA、观察单元格、冲突和检查分别在同目录JSON中。']
        (OUT/'REPORT.md').write_text('\n'.join(report)+'\n')
        (OUT/'README.md').write_text('\n'.join(report)+'\n')
        print(json.dumps(dict(flows=len(self.flows),observations=len(self.obs),models=len(self.models),sources=len(self.sources),fx=len(rates),checks=len(self.checks),passed=True,coverage=self.coverage),ensure_ascii=False))


if __name__=='__main__':
    warnings.filterwarnings('ignore',message='Cannot parse header or footer')
    Package().run()
