"""Country/year summaries built from the same directed fee rows as the charts."""
from collections import defaultdict
import math

# These are events/cohorts, never deduplicated people. Allocation proxies and
# arrival counts are deliberately excluded from per-application denominators.
EVENTS={
 'applications':('applications','每次模型申请','包含模型归属的申请次数；同一人多次申请分别计次。'),
 'applications_by_biometric_enrolment_date':('applications','每次模型申请','按生物信息采集日期记录的申请次数。'),
 'modeled_paid_events':('paid_events','每次估算付费','模型推算的收费事件，非独立申请人数。'),
 'modeled_paid_600_applications':('paid_events','每次估算付费','600类估算付费申请，非全部访澳申请。'),
 'visas_issued':('issued','每次签发对应费用','按签发次数折算的费用值，未计入未获签付费申请。'),
 'observed_evisas_issued_not_paid_applications':('issued','每次签发对应费用','官方电子签签发次数对应国家费值；不是财政实收或独立申请人数。'),
 'evisas_issued':('issued','每次签发对应费用','按电子签发次数折算；非全部签证申请。'),
 'modeled_calendar_decided_applications':('decisions','每次模型结案','按自然年模型结案次数折算，收费日期可能不同。'),
 'applications_received_with_suppression_midpoints':('applications','每次模型申请','含保密小单元中点估算的已收申请次数。'),
 'modeled_calendar_events_from_explicit_source_period':('modeled_events','每次模型事件','从明确统计期桥接的事件次数，原始期间见模型。'),
 'modeled_full_year_VOA_issued':('issued','每次签发对应费用','全年落地签签发次数模型，非独立人数。'),
 'observed_consular_visa_issuance_not_paid_applications':('issued','每次签发对应费用','驻外签发量对应的费用规模，不含未获签付费次数。'),
 'modeled_consular_visa_issuance_scenario':('issued','每次签发对应费用','全年驻外签发量情景对应的标准费混合值；年内累计只约束数量范围，减免结构未知，非实际付费均额。'),
 'observed_visas_issued_not_unique_people_or_paid_applications':('issued','每次签发对应费用','已签发队列对应的法定标准费值；减免未观测，不是实际付费均额，也不含未获签付费申请。'),
 'observed_processed_national_visa_cohort_standard_fee_benchmark':('processed_benchmark','每次处理对应标准费值','已处理长期签证队列的全额标准费基准；儿童、免费和收付跨期另列情景，不是当年实收或实际人均付费。'),
 'observed_visa_issuances_in_documented_fee_exempt_category':('issued','每次签发签证费','已观测签发属于有明确依据的免收签证费类别；其他证件或服务收费按来源另列。'),
 'issued_evisa_benchmark_annual_model_not_all_paid_applications':('issued','每次签发对应费用','已签发电子签数量基准，不含拒签付费。'),
}

def amount_basis(row):
 status=str(row.get('model_status','')).lower();calc=str(row.get('calculation_type','')).lower()
 if any(x in status for x in ['budget','run_rate','runrate','flat_time_proxy','prior_year']):
  return 'runrate','预算／运行率情景'
 if any(x in status for x in ['receipt','actual_revenue','actual_cash','visa_cash','account_calibrated','official_control','reported_fiscal_revenue','retained_collection']):
  return 'receipt_control','财政账目与财年桥接'
 if status=='statutory_fee_exempt_observed_quantity':
  return 'fee_exempt','明确免收签证费'
 if any(x in status for x in ['standard_fee','tariff_value','statutory_fee_value']) or 'tariff' in calc:
  return 'cohort_value','数量与标准费值'
 return 'modeled','其他费用模型'

def build_country_profiles(flows,entities,members,population):
 members=set(members);names={e['code']:e['name'] for e in entities}
 normalize=lambda c:'SCH' if c in members else c
 buckets=defaultdict(lambda:{'incoming':[],'outgoing':[]})
 for row in flows:
  a,b=normalize(row['payer']),normalize(row['receiver'])
  if a==b:continue
  buckets[a,row['year']]['outgoing'].append((row,b))
  buckets[b,row['year']]['incoming'].append((row,a))
 pop={(r['code'],r['year']):r for r in population};years=sorted({r['year'] for r in flows})
 for year in years:
  rr=[pop.get((c,year)) for c in members]
  if rr and all(rr):pop['SCH',year]={'code':'SCH','year':year,'value':sum(r['value'] for r in rr),'basis':'sum_member_total_population','label':'申根成员同年总人口合计','source_id':'population_wdi','is_estimate':True}
 result={}
 for code in names:
  if code=='UNK' or code.startswith(('RAW_','WORLD')):continue
  own={}
  available=sorted(year for c,year in buckets if c==code)
  for year in years:
   box=buckets.get((code,year));p=pop.get((code,year))
   if not box and not p:continue
   out={'code':code,'year':year,'available_years':available,'population':p}
   for direction in ['incoming','outgoing']:
    rr=box[direction] if box else [];total=sum(r['amount_cny'] for r,_ in rr)
    routes=defaultdict(float)
    for r,c in rr:routes[c]+=r['amount_cny']
    known={c:v for c,v in routes.items() if c!='UNK' and v>0};top=max(known,key=known.get) if known else None
    metrics=defaultdict(lambda:{'quantity':0.,'amount_cny':0.,'source_ids':set(),'notes':set(),'rows':0})
    bases={}
    for r,_ in rr:
     key,label=amount_basis(r);item=bases.setdefault(key,{'key':key,'label':label,'amount_cny':0.,'rows':0});item['amount_cny']+=r['amount_cny'];item['rows']+=1
     q=r.get('quantity');basis=r.get('quantity_basis')
     if basis not in EVENTS or not isinstance(q,(float,int)) or not math.isfinite(q) or q<=0:continue
     group,label,note=EVENTS[basis];metric=metrics[group];metric['quantity']+=q;metric['amount_cny']+=r['amount_cny'];metric['source_ids'].update(r.get('source_ids',[]));metric['notes'].add(note);metric['label']=label;metric['basis']=group;metric['rows']+=1
    benchmark=None
    if metrics:
     best=max(metrics.values(),key=lambda m:(m['amount_cny'],m['quantity']))
     benchmark={**{k:v for k,v in best.items() if k not in ['source_ids','notes']},'source_ids':sorted(best['source_ids']),'notes':' '.join(sorted(best['notes'])),'fee_per_event_cny':best['amount_cny']/best['quantity'],'amount_share':best['amount_cny']/total if total else None}
    out[direction]={'amount_cny':total if rr else None,'counterparts':len(known),'top_code':top,'top_amount_cny':known.get(top) if top else None,'unallocated_cny':routes.get('UNK',0),'benchmark':benchmark,'amount_bases':sorted(bases.values(),key=lambda x:-x['amount_cny']),'source_ids':sorted({s for r,_ in rr for s in r.get('source_ids',[])})}
   own[str(year)]=out
  result[code]=own
 return result
