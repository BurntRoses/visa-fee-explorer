#!/usr/bin/env python3
"""Calendar-year core flows: China, Schengen members, India and observed waivers.

Working parameters are explicit scenarios, not fitted probabilities. No network.
The country-of-submission -> nationality conversion keeps non-national payers unknown.
"""
from pathlib import Path
import json,collections
from build_dataset import entity
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/estimates';OUT.mkdir(exist_ok=True)
def load(p):return json.loads((ROOT/p).read_text())
flows=[];models=[];destination_ranges=[]
def edge(payer,receiver,year,kind,amount,cur,lo,hi,q,sids,method,notes,parameters,oids=(),group='other'):
 if payer==receiver:payer='UNK'
 flows.append(dict(id=f'model_{receiver}_{year}_{payer}_{kind}',payer=payer,receiver=receiver,year=year,visa_group=group,visa_type=kind,visa_label=kind,amount=amount,currency=cur,lower=max(0,lo),upper=max(amount,hi),quantity=q,quantity_basis='modeled_paid_events',source_ids=list(sids),observation_ids=list(oids),method_id=method,notes=notes,parameters=parameters,model_status='modeled_estimate',origin_basis='unknown' if payer=='UNK' else 'modeled_nationality',period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_label=f'{year}自然年模型',period_type='calendar_year_model'))

def china():
 # Preserve observables separately from the behavioral parameters converting entry events.
 params={'entry_share_of_two_way_2024':{'central':.5,'lower':.47,'upper':.53,'basis':'分析参数；出入境近似平衡，不是官方单向统计'},
         'resident_or_other_nonconsular_share':{'central':.2,'lower':.05,'upper':.4,'basis':'分析参数；剔除居留证等非本年驻外签证入境'},
         'entries_per_new_consular_visa':{'central':2,'lower':1.25,'upper':4,'basis':'分析参数；有效签证存量与多次使用'},
         'unused_new_visas_share':{'central':.1,'lower':0,'upper':.25,'basis':'分析参数；已签发但当年未使用'},
         'mean_consular_fee_cny':{'central':300,'lower':150,'upper':600,'basis':'分析参数；印度实际价目约CNY249—757提供量级参照，不代表全球同价'},
         'port_mean_fee_cny':{'central':200,'lower':100,'upper':400,'basis':'分析参数；口岸类别/国籍收费结构未披露，不是观测价'},
         'india_fee_mix':{'single':.5,'double':.3,'six_month':.15,'year_plus':.05,'basis':'显式次数混合情景；观测仅有28万签发与四档费率'}}
 fx=load('data/research/schengen_fx/fx.json');rates={(r['year'],r['currency']):r['usd_per_unit'] for r in fx}
 india_floor=next(r for r in load('data/research/china_visa_context_v4/observations.json') if r['observation_id']=='cvc_cn_ind_2025_ytd_0922')
 assert india_floor['source_status']=='strict_lower_floor' and india_floor['period_end']=='2025-09-22'
 for y in [2024,2025]:
  # 2025 denominator derives from the published visa-free share; 2024 only two-way total exists.
  entries=64882000*.5 if y==2024 else 30080000/.731
  low_entries=64882000*.47 if y==2024 else 30080000/.731
  high_entries=64882000*.53 if y==2024 else 30080000/.731
  waiver=20115000 if y==2024 else 30080000
  port=1476000 if y==2024 else 1476000 # 2025 port count unavailable: last-observed rate, broad scenario.
  nonfree=max(0,entries-waiver-port)
  n=nonfree*.8/2/(1-.1)
  nl=max(0,low_entries-waiver-port)*.6/4
  nh=max(0,high_entries-waiver-port)*.95/1.25/(1-.25)
  total=n*300;tl=nl*150;th=nh*600
  p=dict(params,observed_two_way_2024=64882000,visa_free_entries=waiver,modeled_entries=entries,port_visas=port,consular_new_visas=n,port_2025='2024 running rate' if y==2025 else 'observed')
  source=['cn_nia_2024','cn_nia_2025'] if y==2025 else ['cn_nia_2024']
  # One identified bilateral source; all other payers stay unknown, never assigned by whim.
  indian_q=280000
  rate=rates[(y,'INR')]/rates[(y,'CNY')]
  mean=(2900*.5+4400*.3+5900*.15+8800*.05)*rate
  india=indian_q*mean;il=indian_q*2900*rate;ih=indian_q*8800*rate
  qlow=indian_q if y==2024 else max(indian_q*.7,india_floor['value'])
  qhigh=indian_q*(1.3 if y==2025 else 1)
  il=qlow*2900*rate;ih=qhigh*8800*rate
  india_sources=['cn_india_2024','cn_india_fee']+([india_floor['source_id']] if y==2025 else [])
  india_parameters={'fee_mix':params['india_fee_mix'],'quantity_2025_imputed':y==2025,'issuance_scenario':{'lower':qlow,'central':indian_q,'upper':qhigh},'fee_waiver_share_unobserved':True,'interpretation':'签发队列按既有四档费率情景计价，非实际付费人数或无条件实收下界。'}
  if y==2025:india_parameters['issuance_floor_evidence']={'observation_id':india_floor['observation_id'],'value':india_floor['value'],'source_id':india_floor['source_id'],'period_end':india_floor['period_end'],'strict':True,'use':'只约束全年签发量情景；保留原全年中心，不按天外推。'}
  edge('IND','CHN',y,'驻外签证',india,'CNY',il,ih,indian_q,india_sources,'china_india_issuance_mix','2024印度28万签发×四档费率混合。' if y==2024 else '2025沿用28万全年中心，全年签发量情景下端由9月22日官方累计超过26.5万约束，上端仍36.4万。未按日历比例外推。费用为既有四档标准费结构情景，减免结构未知，金额下端不是无条件实收下界。',india_parameters,['cn_indian_2024_issued'])
  flows[-1]['quantity_basis']='observed_consular_visa_issuance_not_paid_applications' if y==2024 else 'modeled_consular_visa_issuance_scenario'
  edge('UNK','CHN',y,'驻外签证_未分配来源',max(0,total-india),'CNY',max(0,tl-ih),max(0,th-il),max(0,n-indian_q),source,'china_entry_stock_model','非免签入境→扣除非驻外签证份额→除多次使用→加未使用新签→平均收费。来源国别不分配；上下端为共同参数情景。不是外交部实收。',p)
  edge('UNK','CHN',y,'口岸签证',port*200,'CNY',port*(70 if y==2025 else 100),port*(520 if y==2025 else 400),port,source,'china_port_issuance_model','2024口岸签证147.6万证次是已签发事件；收费及减免混合未知。2025数量沿用2024运行率±30%。',{'mean_fee':params['port_mean_fee_cny'],'quantity_2025_imputed':y==2025})
  models.append(dict(model_id=f'china_{y}',destination='CHN',year=y,target='驻外与口岸政府签证费',central_native=total+port*200,lower_native=tl+port*(70 if y==2025 else 100),upper_native=th+port*(520 if y==2025 else 400),currency='CNY',formula='((foreign_entries - visa_free - port_visas)*(1-resident_share)/reuse/(1-unused_share))*mean_fee + port_visas*port_fee',parameters=p,source_ids=source,quality='需求与存量情景；弱识别，中心为工作参数',unallocated='除印度外国籍未知；不按游客份额虚分',missing='费用国籍结构、签证存量、驻外全球签发、官方实收'))
  destination_ranges.append(dict(receiver='CHN',year=y,amount=total+port*200,lower=tl+port*(70 if y==2025 else 100),upper=th+port*(520 if y==2025 else 400),currency='CNY',range_method='入境与存量模型共同参数端点；印度分配与未知残差负相关，不累加二者边际端点'))

def schengen():
 from schengen_tariffs import annual_tariff
 rows=load('data/research/schengen_fx/observations.json')
 issuing_members=sorted({entity(r['destination']) for r in rows if r['metric']=='applications'})
 members=sorted(set(issuing_members)|{'LIE'})
 exempt=set('ALB AND ARG AUS BHS BRB BIH BRA BRN CAN CHL COL CRI DMA SLV GEO GRD GTM HND HKG ISR JPN KIR KOR MAC MYS MHL MUS MEX FSM MDA MCO MNE NZL NIC MKD PLW PAN PRY PER KNA LCA VCT WSM SMR SRB SYC SGP SLB TWN TLS TON TTO TUV UKR ARE GBR USA URY VUT VAT VEN'.split())|set(members)
 data=collections.defaultdict(lambda:[0,[]])
 for r in rows:
  if r['metric']!='applications' or r.get('consulate_country') is None:continue
  key=(int(r['period_start'][:4]),entity(r['consulate_country']),entity(r['destination']))
  data[key][0]+=r['value'];data[key][1].append(r['observation_id'])
 totals=collections.defaultdict(lambda:dict(amount=0.,lower=0.,upper=0.))
 year_sources=collections.defaultdict(set)
 for (y,payer,dst),(q,oids) in data.items():
  if not q:continue
  local=annual_tariff(payer,dst,y);unknown=annual_tariff('UNK',dst,y)
  share=0 if payer in exempt or str(payer).startswith('RAW') else .95
  sids=sorted({f'sch_{y}',*local['source_ids'],*unknown['source_ids']})
  year_sources[y].update(sids)
  if share:
   edge(payer,dst,y,'申根短期',q*.9*share*local['center'],'EUR',q*.8*.8*local['lower'],q*local['upper'],q*share,sids,'sch_consulate_nationality_fee_model',
    '领馆递交地转国籍：非免签递交地95%归本国申请人，敏感性80—100%；按国籍、收款政府及协议生效日匹配普通成人费。有效收费比例90%，敏感性80—100%；年度申请日未知，中心按日均匀。',
    {'national_share':share,'national_share_range':[.8,1],'effective_tariff_share':.9,'effective_tariff_range':[.8,1],
     'adult_tariff':local['center'],'adult_tariff_range':[local['lower'],local['upper']],
     'tariff_basis':local['basis'],'tariff_segments':local['segments'],'tariff_uncertainty':local['uncertainty']},oids,group='visitor')
  edge('UNK',dst,y,f'申根短期_{payer}_非本国递交',q*.9*(1-share)*unknown['center'],'EUR',0 if share else q*.8*unknown['lower'],q*(.2 if share else 1)*unknown['upper'],q*(1-share),
   sorted({f'sch_{y}',*unknown['source_ids']}),'sch_consulate_nationality_fee_model',
   '递交地不能确认付款人国籍；未知残差按一般成人费建模，未自动套用递交地国籍优惠。免签递交地全部保留未知；有效收费与申请日结构为情景。',
   {'submission_country':payer,'national_share':share,'adult_tariff':unknown['center'],
    'adult_tariff_range':[unknown['lower'],unknown['upper']],'unknown_tariff_policy':'general adult fee; nationality concessions not assigned'},oids,group='visitor')
  t=totals[dst,y]
  t['amount']+=q*.9*(share*local['center']+(1-share)*unknown['center'])
  if share:
   # Local-national share changes tariff composition when a concession applies.
   t['lower']+=q*.8*min(z*local['lower']+(1-z)*unknown['lower'] for z in [.8,1])
   t['upper']+=q*max(z*local['upper']+(1-z)*unknown['upper'] for z in [.8,1])
  else:
   t['lower']+=q*.8*unknown['lower'];t['upper']+=q*unknown['upper']
 for (dst,y),t in sorted(totals.items()):
  destination_ranges.append(dict(receiver=dst,year=y,**t,currency='EUR',range_method='国籍×收款政府×日期费率；有效收费80—100%、本地国籍80—100%及收费日期共同端点；未知国籍保留一般成人费'))
 for y in [2024,2025]:
  models.append(dict(model_id=f'schengen_members_{y}',year=y,destination='SCH',members=members,issuing_members=issuing_members,target='各成员国短期政府申请费',
   parameters={'effective_fee_share':.9,'range':[.8,1],'local_national_share':.95,'range_national':[.8,1],
    'tariff_dimensions':['nationality','receiving_government','effective_date'],'unknown_origin_tariff':'general adult; no presumed nationality concession'},
   source_ids=sorted(year_sources[y]),quality='逐领馆申请与按年代协议费率模型；国籍转换显式保留。列支敦士登无单独签发合计',missing='长期签、真实免费与年龄结构、递交人完整国籍与年内日期'))

def india():
 # Replace the old receipt run rate in place; an unallocated national control
 # must never be added on top of the superseded fee edge.
 for row in load('data/research/india_recent_v7/calendar_model_candidates.json'):
  y=row['year'];assert row['payer']=='UNK' and row['receiver']=='IND' and row['quantity'] is None
  notes=row['notes'].split('须替换')[0]+'付款国籍与类别未披露；没有匹配付费次数分母。'
  edge('UNK','IND',y,'全类签证_来源未分配',row['amount'],'INR',row['lower'],row['upper'],None,row['source_ids'],row['method_id'],notes,row['parameters'],row['observation_ids'])
  flows[-1].update(quantity_basis='not_available',category_detail_status='unclassified',
                   model_status='actual_fiscal_receipts_calendar_bridge' if y==2024 else 'latest_actual_fiscal_level_proxy')
  models.append(dict(model_id=f'india_{y}',destination='IND',year=y,central_native=row['amount'],currency='INR',lower_native=row['lower'],upper_native=row['upper'],source_ids=row['source_ids'],observation_ids=row['observation_ids'],parameters=row['parameters'],quality='相邻完整财年实收25%/75%桥接' if y==2024 else '最近完整财年实收水平代理±35%',missing='付费国籍、类别及匹配次数；FY2025/26实际签证费未知'))

def waivers():
 for y in [2024,2025]:
  for dst,sid in [('THA','th_waiver_temporary'),('MYS','my_waiver')]:
   edge('CHN',dst,y,'合资格短访免签',0,'CNY',0,0,None,[sid],'observed_waiver_zero','仅对应合资格中国普通护照短访；非所有签证类别都免费。',{'eligibility':'ordinary passport qualifying short visit'},group='visitor')
 # Singapore Jan/early-Feb 2024 still required visas. Existing frozen model supplies calendar-period reuse scenarios.
 obs=load('data/research/china_seasia/estimates.json')
 ref=next(r for r in obs if r['estimate_id']=='waiver_SGP_2024_reuse2')
 all_arrivals=3080054
 before_low=all_arrivals-ref['parameters']['arrival_upper'];before_high=all_arrivals-ref['parameters']['arrival_lower']
 before=(before_low+before_high)/2
 edge('CHN','SGP',2024,'免签生效前短访',before*.5/2*30,'SGD',before_low*.25/4*30,before_high/1*30,before*.5/2,['sg_arrivals','sg_waiver','sg_fee'],'singapore_prewaiver_new_visa_model','2024全年居民地到达减免签生效后月度区间；非本年新办需签比例中心50%、范围25—100%，每签复用中心2趟、范围1—4；居住地→国籍近似。免签后费用0。',{'arrivals_before_waiver':[before_low,before_high],'new_required_share':.5,'trips_per_visa':2,'government_fee_sgd':30},group='visitor')
 for y in [2024,2025]:
  if y==2025:edge('CHN','SGP',y,'合资格短访免签',0,'CNY',0,0,None,['sg_waiver'],'observed_waiver_zero','合资格短访免签政府费0，长期活动另计。',{},group='visitor')

def turkey():
 rows=load('data/research/turkey_russia_saudi/turkey_annual.json')
 for y in [2024,2025]:
  for channel in ['evisa','sticker_visa']:
   r=next((r for r in rows if r['year']==y and r['visa_group']==channel),None)
   if r:q=r['value'];sids=[r['source_id']];scale=[1,1]
   else:q=1161392;sids=['tr_annual_2024'];scale=[.8,1.2]
   # No nationality-weighted schedule exists: retain total as a broad tariff-mix scenario.
   fee=50 if channel=='evisa' else 80;low=20 if channel=='evisa' else 40;high=100 if channel=='evisa' else 160
   edge('UNK','TUR',y,channel,q*fee,'USD',q*low*scale[0],q*high*scale[1],q,sids+['tr_prc_fee_2015'],'turkey_channel_tariff_mix_model','官方渠道签发数×未观测国籍费率混合情景；电子签中心USD50（20—100），纸签80（40—160）为分析参数，不以中国价套全球。拒签付费及免费另缺；2025纸签沿用2024运行率±20%。',{'mean_tariff_usd':fee,'tariff_sensitivity':[low,high],'quantity_scale':scale,'origin_allocation':'unknown'},group='visitor' if channel=='evisa' else 'other')
  models.append(dict(model_id=f'turkey_{y}',destination='TUR',year=y,source_ids=[f'tr_annual_{y}'],quality='已知数量＋分析者费率混合情景，非实收',missing='国籍与期限费率组合、拒签收费；2025纸签总量'))

def main():
 china();schengen();india();waivers();turkey()
 # Some source IDs in early packages changed names: resolve with registered policy rows.
 sources=load('data/processed/sources.json');valid={s['source_id'] for s in sources}
 for f in flows:
  assert all(s in valid for s in f['source_ids']),(f['id'],f['source_ids'])
 out={'flows':flows,'models':models,'destination_ranges':destination_ranges};(OUT/'core_flows.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
 print(json.dumps({'flows':len(flows),'models':len(models),'destinations':sorted({f['receiver'] for f in flows})},ensure_ascii=False))
if __name__=='__main__':main()
