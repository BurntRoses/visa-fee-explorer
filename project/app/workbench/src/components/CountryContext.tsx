import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight,Download,FileText,RotateCcw} from 'lucide-react';
import type {CountryContextData,CountryContextPartner,CountryContextPoint,CountryContextSeries,WorkbenchIndex} from '../types';
import {csv,loadCountryContext,number} from '../data';
import {ChoiceField} from './ChoiceField';

const domainNames:Record<string,string>={mobility:'旅行与边境',visa_activity:'签证活动',document_activity:'证件签发',rate:'比例'};
const pointKey=(p:CountryContextPoint)=>p.period_start+'|'+p.period_end;
const isFullYear=(p:CountryContextPoint)=>p.period_start===p.year+'-01-01'&&p.period_end===p.year+'-12-31';
const monthName=(p:CountryContextPoint)=>p.period_start.slice(0,7);
const quarterName=(p:CountryContextPoint)=>p.period_start.slice(0,4)+'年Q'+Math.ceil(Number(p.period_start.slice(5,7))/3);
const periodName=(p:CountryContextPoint,s:CountryContextSeries)=>/month/.test(s.period_type)?monthName(p):/quarter/.test(s.period_type)?quarterName(p):isFullYear(p)?String(p.year)+'年':p.period_start+' — '+p.period_end;
const cadence=(s:CountryContextSeries)=>/month/.test(s.period_type)?'月度':/quarter/.test(s.period_type)?'季度':/half/.test(s.period_type)?'半年':/fiscal|financial/.test(s.period_type)?'财年':/partial|year_to_date|ytd/.test(s.period_type)?'年内已发布':'年度';
const valueText=(value:number,s:CountryContextSeries)=>new Intl.NumberFormat('zh-CN',{maximumFractionDigits:s.domain==='rate'?2:1}).format(value);
const figureText=(value:number,s:CountryContextSeries)=>s.domain==='rate'||value<1e4?valueText(value,s):value>=1e8?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value/1e8)+'亿':new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value/1e4)+'万';
const boundPrefix=(p:CountryContextPoint)=>p.bound_type==='strict_lower_floor'||p.source_status==='strict_lower_floor'?'> ':p.bound_type==='lower_bound'?'≥ ':p.bound_type==='upper_bound'?'≤ ':p.source_status==='approximate_count'?'≈ ':'';
const pointStatus=(p:CountryContextPoint)=>p.source_status==='strict_lower_floor'?'原文累计下限':p.source_status==='approximate_count'?'原文约数':p.source_status==='partial_fiscal_year'?'不完整财年':p.source_status==='complete_fiscal_year'?'完整财年':p.source_status==='published_rounded'?'来源公布取整值':p.source_status==='published'?'来源公布值':p.source_status_label&&p.source_status_label!=='Normal value'?p.source_status_label:p.source_status&&p.source_status!=='A'?p.source_status:'';
const pointValue=(p:CountryContextPoint,s:CountryContextSeries,short=false)=>boundPrefix(p)+(short?figureText(p.value,s):valueText(p.value,s));
const compact=(value:number)=>new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:1}).format(value);
const shortUnit=(s:CountryContextSeries)=>s.domain==='rate'?'%':s.unit_label.replace(/（.*?）/g,'');
const originCaption=(s:CountryContextSeries,p:CountryContextPartner)=>s.flow_direction==='outbound'?(p.code==='WORLD'?'全部目的地':'目的地 · '+p.name):p.code==='WORLD'?'全部来源':s.origin_basis_label+' · '+p.name;
function initialPartner(s:CountryContextSeries):CountryContextPartner|undefined{return s.partners.find(p=>p.code==='WORLD')||s.partners.find(p=>p.code==='CHN')||s.partners[0];}
function initialSeries(data:CountryContextData,year:number):string{
 const score=(s:CountryContextSeries)=>s.context_selection_default===false||s.partners.every(p=>p.points.every(p=>p.context_selection_default===false))||/冲突/.test(s.label)?-10000:(s.partners.some(p=>p.points.some(p=>p.year===year))?1000:0)+(s.domain==='mobility'?20:0)+(s.metric==='visa_free_entries'?40:/tourist|visitor/.test(s.metric)?25:0)+(s.partners.some(p=>p.code==='WORLD')?10:0)-(/month/.test(s.period_type)?5:0);
 return [...data.series].sort((a,b)=>score(b)-score(a))[0]?.id||'';
}

function ContextTrend({series,points,selected,onSelect}:{series:CountryContextSeries;points:CountryContextPoint[];selected?:CountryContextPoint;onSelect:(p:CountryContextPoint)=>void}){
 const ref=useRef<HTMLDivElement>(null),[width,setWidth]=useState(560);
 useEffect(()=>{const element=ref.current;if(!element)return;const resize=new ResizeObserver(entries=>{const next=entries[0]?.contentRect.width;if(next)setWidth(Math.max(240,next));});resize.observe(element);return()=>resize.disconnect();},[]);
 const id=useId().replace(/:/g,''),w=width,h=222,left=44,right=14,top=20,bottom=36;
 const dates=points.map(p=>Date.parse(p.period_end)),lo=Math.min(...dates),hi=Math.max(...dates),max=Math.max(1,...points.map(p=>p.upper??p.value));
 const x=(i:number)=>hi===lo?(w+left-right)/2:left+(dates[i]-lo)/(hi-lo)*(w-left-right);
 const y=(value:number)=>h-bottom-value/max*(h-top-bottom);
 const active=selected?points.findIndex(p=>pointKey(p)===pointKey(selected)):-1;
 const segments:{path:string;start:number;end:number}[]=[];let path='',start=0;
 points.forEach((p,i)=>{const previous=points[i-1],gap=previous&&(/month/.test(series.period_type)?dates[i]-dates[i-1]>45*86400000:/quarter/.test(series.period_type)?dates[i]-dates[i-1]>110*86400000:p.year-previous.year>1);if(gap&&path){segments.push({path,start,end:i-1});path='';start=i;}path+=(path?' L':'M')+x(i)+','+y(p.value);});if(path)segments.push({path,start,end:points.length-1});
 const tickParts=w<440?[0,.5,1]:[0,.25,.5,.75,1],ticks=[...new Set(tickParts.map(r=>Math.round((points.length-1)*r)))];
 return <div ref={ref} className="context-trend" data-testid="context-trend">
  <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={series.label+'历史变化，'+points.length+'期'}>
   <defs><linearGradient id={'context-area-'+id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5d9c7d" stopOpacity=".2"/><stop offset="1" stopColor="#5d9c7d" stopOpacity=".02"/></linearGradient></defs>
   {[0,.5,1].map(r=><g key={r}><line x1={left} x2={w-right} y1={y(max*r)} y2={y(max*r)} stroke="#e2ebe5" strokeDasharray={r?'3 5':undefined}/><text x={left-10} y={y(max*r)+4} textAnchor="end" fill="#687f7c" fontSize="12">{compact(max*r)}</text></g>)}
   {active>=0&&<rect x={Math.max(left,x(active)-13)} y={top-6} width={26} height={h-top-bottom+12} rx={8} fill="#e5f0e8"/>}
   {segments.map((s,i)=><g key={i}><path d={s.path+` L${x(s.end)},${h-bottom} L${x(s.start)},${h-bottom} Z`} fill={`url(#context-area-${id})`}/><path d={s.path} fill="none" stroke="#558f74" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></g>)}
   {points.map((p,i)=><g key={pointKey(p)} className={'context-plot-point'+(i===active?' active':'')} onClick={()=>onSelect(p)}><title>{periodName(p,series)+'：'+pointValue(p,series)+' '+shortUnit(series)}</title><circle cx={x(i)} cy={y(p.value)} r={i===active?5:points.length>50?1.8:3} fill={i===active?'#26734f':'#87ad98'} stroke="#fff" strokeWidth={i===active?2:0}/><rect x={Math.max(left-8,x(i)-Math.min(14,(w-left-right)/Math.max(1,points.length)/2))} y={top-8} width={Math.min(28,(w-left-right)/Math.max(1,points.length))} height={h-top-bottom+16} fill="transparent"/></g>)}
   {ticks.map(i=><text key={i} x={x(i)} y={h-11} textAnchor={i===0?'start':i===points.length-1?'end':'middle'} fontSize="12" fill="#687f7c">{/month/.test(series.period_type)?monthName(points[i]):/quarter/.test(series.period_type)?quarterName(points[i]):isFullYear(points[i])||/fiscal|financial/.test(series.period_type)?points[i].year:points[i].period_end.slice(0,7)}</text>)}
  </svg>
  <div className="context-period-picker"><button aria-label="前一期背景数据" disabled={active<=0} onClick={()=>onSelect(points[active-1])}><ChevronLeft size={16}/></button><input type="range" aria-label="选择背景数据期间" min={0} max={points.length-1} step={1} value={Math.max(0,active)} onChange={e=>onSelect(points[Number(e.target.value)])} aria-valuetext={active>=0?periodName(points[active],series):'当前主图年份无记录，移动以选择已发布期间'} disabled={points.length<2}/><button aria-label="后一期背景数据" disabled={active===points.length-1} onClick={()=>onSelect(points[Math.max(0,active+1)])}><ChevronRight size={16}/></button></div>
 </div>;
}

export function CountryContext({index,code,year,onSources}:{index:WorkbenchIndex;code:string;year:number;onSources:(ids:string[])=>void}){
 const [data,setData]=useState<CountryContextData|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 const [seriesId,setSeriesId]=useState(''),[partnerCode,setPartnerCode]=useState(''),[selectedKey,setSelectedKey]=useState<string|null>(null),[exported,setExported]=useState(false);
 const [memberCode,setMemberCode]=useState(()=>index.schengenMembers.includes('DEU')&&index.countryContext?.DEU?'DEU':index.schengenMembers.find(c=>index.countryContext?.[c])||'');
 useEffect(()=>{let cancelled=false;setLoading(true);setError('');setData(null);loadCountryContext(index,code,attempt>0).then(result=>{if(cancelled)return;setData(result);if(result){const id=initialSeries(result,year),s=result.series.find(s=>s.id===id);setSeriesId(id);setPartnerCode(s?initialPartner(s)?.code||'':'');}setSelectedKey(null);setLoading(false);}).catch(e=>{if(!cancelled){setError(e instanceof Error?e.message:String(e));setLoading(false);}});return()=>{cancelled=true;};},[index,code,attempt]);
 const series=data?.series.find(s=>s.id===seriesId),partner=series?.partners.find(p=>p.code===partnerCode),points=useMemo(()=>[...(partner?.points||[])].sort((a,b)=>a.period_end.localeCompare(b.period_end)||a.period_start.localeCompare(b.period_start)),[partner]);
 const current=selectedKey?points.find(p=>pointKey(p)===selectedKey):points.filter(p=>p.year===year).at(-1),latest=points.at(-1);
 const chooseSeries=(id:string)=>{setSeriesId(id);const s=data?.series.find(s=>s.id===id);setPartnerCode(s?.partners.find(p=>p.code===partnerCode)?.code||(s?initialPartner(s)?.code:'')||'');setSelectedKey(null);setExported(false);};
 if(loading)return <div className="context-state" role="status">正在读取{nameFor(index,code)}的签证与旅行序列…</div>;
 if(error)return <div className="context-state" role="alert"><p>{error}</p><button onClick={()=>setAttempt(v=>v+1)}><RotateCcw size={15}/>重新载入</button></div>;
 if(code==='SCH'&&!data?.series.length)return <div className="context-member-view"><ChoiceField label="选择申根成员背景" caption="申根成员" value={memberCode} onChange={setMemberCode} searchable options={index.schengenMembers.filter(c=>index.countryContext?.[c]).map(c=>({id:c,label:nameFor(index,c),search:c})).sort((a,b)=>a.label.localeCompare(b.label,'zh-CN'))}/><p className="context-definition">成员的边境范围与单位按原表保留，欧盟总计与申根范围分别识别。</p>{memberCode?<CountryContext key={memberCode} index={index} code={memberCode} year={year} onSources={onSources}/>:<p className="context-state">尚未归档成员的可展示序列。</p>}</div>;
 if(!data?.series.length)return <div className="context-state"><p>{code==='SCH'?'申根成员的边境统计范围各有定义，欧盟总计与申根范围不同。成员原表保留在完整数据与来源中。':'当前尚未归档'+nameFor(index,code)+'的可展示签证或出入境序列。'}</p><p>费用收付和人口折算可在“费用”中查看。</p></div>;
 if(!series||!partner||!points.length)return <div className="context-state">这条序列暂没有可显示的期间。</div>;
 const exactRange=current&&current.lower!=null&&current.upper!=null&&current.lower!==current.upper;
 const exportSeries=()=>{csv(points.map(p=>({country:code,country_name:data.name,series:series.label,metric:series.metric,domain:series.domain,partner:partner.code,partner_name:partner.name,origin_basis:series.origin_basis,unit:series.unit,...p})),`visa-context-${code}-${series.id}-${partner.code}.csv`);setExported(true);};
 return <section className="country-context" data-testid="country-context">
  <div className="context-selectors">
   <ChoiceField label="选择背景指标" caption="指标" value={series.id} onChange={chooseSeries} searchable
    options={data.series.map(s=>({id:s.id,label:s.label,detail:cadence(s)+(data.series.some(other=>other.id!==s.id&&other.label===s.label&&cadence(other)===cadence(s))?' · '+(s.partners.some(p=>p.code==='WORLD')?'含总量':s.origin_basis_label):'')}))}/>
   <ChoiceField label="选择背景来源" caption={series.flow_direction==='outbound'?'目的地':series.origin_basis_label.includes('国籍')?'来源国籍':series.origin_basis_label==='通常居住地'?'来源居住地':'统计来源'} value={partner.code} searchable
    onChange={id=>{setPartnerCode(id);setSelectedKey(null);setExported(false);}} options={series.partners.map(p=>({id:p.code,label:p.code==='WORLD'&&series.flow_direction==='outbound'?'全部目的地':p.name,search:p.code}))}/>
  </div>
  <div className="context-overview"><div><span className="context-domain">{domainNames[series.domain]||'背景数据'} · {cadence(series)}</span><h3>{series.label}</h3><p>{originCaption(series,partner)}</p></div><span className="context-series-count">{points[0].year}–{latest?.year}<small>{number(points.length)} 期</small></span></div>
  <div className="context-keyfigure" aria-live="polite"><div><span>{current?periodName(current,series):year+'年'}</span><strong>{current?pointValue(current,series,true):'无记录'}{current&&<small>{shortUnit(series)}</small>}</strong>{current&&boundPrefix(current).includes('>')&&<span className="context-value-range">原文为累计下限，截止 {current.period_end}</span>}{exactRange&&<span className="context-value-range">{current.lower}–{current.upper} {shortUnit(series)} · {String(current.calculation_type).includes('suppress')?'抑制区间，中点显示':'来源范围'}</span>}{current&&!isFullYear(current)&&!/month/.test(series.period_type)&&<span className="context-value-range">按原始统计期展示</span>}{current?.quality_issue&&<span className="context-value-range" title={current.quality_issue}>来源版本存在差异 · 见统计口径</span>}</div>{!current&&latest&&<button onClick={()=>setSelectedKey(pointKey(latest))}>查看最新 {periodName(latest,series)}<ChevronRight size={14}/></button>}{current&&selectedKey&&<button onClick={()=>setSelectedKey(null)}>返回主图 {year} 年</button>}</div>
  <ContextTrend series={series} points={points} selected={current} onSelect={p=>setSelectedKey(pointKey(p))}/>
  <p className="context-definition">{series.metric==='border_entry_refusals'?'同一报告国、同一参考期内每人计一次，原表按5人取整；跨国统计可能重叠。边境拒绝入境与签证拒签分别统计。':<>{series.domain==='mobility'?'旅行与边境按原表人次统计，同一人可有多次记录。':series.domain==='visa_activity'?'签证活动按申请、决定或签发的原指标计次，同一人可多次申请。':series.domain==='document_activity'?'本系列包含原表列明的签证、居留等证件。':'比例的分子与分母见来源定义。'}背景序列独立于费用账。</>}</p>
  <div className="context-actions"><button onClick={()=>onSources(series.source_ids)}><FileText size={15}/>查看来源</button><button onClick={exportSeries}><Download size={15}/>{exported?'已导出 CSV':'导出这条序列'}</button></div>
  <details className="context-evidence"><summary>统计口径与原始定位</summary><dl><dt>来源归属</dt><dd>{series.origin_basis_label}</dd><dt>原始单位</dt><dd>{series.unit_label}</dd>{current&&<><dt>统计期间</dt><dd>{current.period_start} — {current.period_end}</dd><dt>观察编号</dt><dd>{current.observation_id}</dd><dt>原表定位</dt><dd>{current.source_locator||'见来源原表'}</dd>{current.source_rounding_unit!=null&&<><dt>来源显示精度</dt><dd>{number(current.source_rounding_unit)} {shortUnit(series)}一档{current.original_value!=null?' · 原文 '+current.original_value+' '+(current.original_unit||''):''}</dd></>}{pointStatus(current)&&<><dt>原始数值状态</dt><dd>{pointStatus(current)}</dd></>}{current.quality_issue&&<><dt>版本差异</dt><dd>{current.quality_issue}</dd></>}</>}</dl>{series.notes&&<p>{series.notes}</p>}</details>
  <details className="context-records"><summary>数据表 · {number(points.length)} 期</summary><div><table><thead><tr><th>统计期间</th><th>{shortUnit(series)}</th><th>来源</th></tr></thead><tbody>{[...points].reverse().map(p=><tr key={pointKey(p)} className={current&&pointKey(current)===pointKey(p)?'selected':''}><td><button onClick={()=>setSelectedKey(pointKey(p))}>{periodName(p,series)}</button></td><td>{pointValue(p,series)}{p.lower!=null&&p.upper!=null&&p.lower!==p.upper&&<small>{p.lower}–{p.upper}</small>}</td><td><button onClick={()=>onSources([p.source_id])} aria-label={'查看'+periodName(p,series)+'来源'}><FileText size={13}/></button></td></tr>)}</tbody></table></div></details>
 </section>;
}
function nameFor(index:WorkbenchIndex,code:string){return index.entities.find(e=>e.code===code)?.name||code;}
