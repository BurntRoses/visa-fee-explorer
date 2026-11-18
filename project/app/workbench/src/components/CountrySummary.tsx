import {useState} from 'react';
import {ChevronRight,FileText} from 'lucide-react';
import type {CountryProfile,ProfileDirection,WorkbenchIndex,WorkbenchState} from '../types';
import {money,number} from '../data';
import {SegmentedControl} from './SegmentedControl';
import {CountryContext} from './CountryContext';

const yuan=(amount:number)=>new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(amount)+'元';
const percent=(value:number)=>new Intl.NumberFormat('zh-CN',{style:'percent',maximumFractionDigits:1}).format(value);
const primary=(p:CountryProfile,mode:WorkbenchState['singleMode'])=>mode==='origins'?p.incoming:mode==='destinations'?p.outgoing:p.outgoing.amount_cny!==null?p.outgoing:p.incoming;

export function CountrySummary({profile,name,mode,onOpen}:{profile?:CountryProfile;name:string;mode:WorkbenchState['singleMode'];onOpen:()=>void}){
 const metric=profile&&primary(profile,mode),out=profile?.outgoing.amount_cny,incoming=profile?.incoming.amount_cny;
 return <section className="country-summary" aria-label={name+'费用摘要'} data-testid="country-summary">
  <div><p>{out!=null?<><b>{name}</b>申请人付出 <strong>{money(out)}</strong></>:<><b>{name}</b>申请人付出尚未识别</>}{incoming!=null?<>，政府收到 <strong>{money(incoming)}</strong>。</>:<>，政府收到尚未识别。</>}</p>
   <span>全部已建模 · {metric?.benchmark?<>{metric.benchmark.amount_share!=null&&metric.benchmark.amount_share<.995?'有数量部分，':''}{metric.benchmark.label}约 <b>{yuan(metric.benchmark.fee_per_event_cny)}</b></>:<>查看收付、数量与人口折算</>}{profile?.population&&out!=null&&<> · 按人口折合支出 <b>{yuan(out/profile.population.value)}/人</b></>}</span>
  </div><button onClick={onOpen} aria-label={'查看'+name+'费用摘要'}>摘要<ChevronRight size={14}/></button>
 </section>;
}

export function CountryProfileDetails({index,code,year,profile,name,entityName,onSources}:{index:WorkbenchIndex;code:string;year:number;profile?:CountryProfile;name:string;entityName:(code:string)=>string;onSources:(ids:string[])=>void}){
 const [tab,setTab]=useState<'fees'|'context'>('fees');
 return <div className="country-profile-details"><SegmentedControl label="国家摘要内容" value={tab} options={[{id:'fees',label:'费用'},{id:'context',label:'签证与出入境'}]} onChange={setTab} className="profile-tabs"/>{tab==='fees'?<CountryFeeDetails profile={profile} name={name} entityName={entityName} onSources={onSources}/>:<CountryContext index={index} code={code} year={year} onSources={onSources}/>}</div>;
}

function CountryFeeDetails({profile,name,entityName,onSources}:{profile?:CountryProfile;name:string;entityName:(code:string)=>string;onSources:(ids:string[])=>void}){
 if(!profile)return <p>当前年份尚无{name}的可用金额或人口数据。可在时间轴选择其他年份。</p>;
 const {incoming,outgoing,population}=profile;
 const direction=(d:ProfileDirection,label:string)=><section className="profile-section"><h3>{label}</h3><strong className="profile-total">{money(d.amount_cny)}</strong>{d.amount_cny!=null&&<p>已识别 {d.counterparts} 个{label==='申请人付出'?'收款方':'付款来源'}{d.top_code&&d.top_amount_cny!=null&&<>，主要{label==='申请人付出'?'去向':'来源'}为{entityName(d.top_code)}，占{percent(d.top_amount_cny/d.amount_cny||0)}</>}。{d.unallocated_cny>0&&<>另有{money(d.unallocated_cny)}付款国籍未分配，已包含在收到中。</>}</p>}
  {!!d.amount_bases?.length&&<dl className="profile-basis" aria-label={label+'金额依据'}>{d.amount_bases.map(b=><div key={b.key}><dt>{b.label}</dt><dd>{money(b.amount_cny)}</dd></div>)}</dl>}
  {d.benchmark?<div className="profile-calculation"><span>{d.benchmark.label}</span><b>{yuan(d.benchmark.fee_per_event_cny)}</b><p>{money(d.benchmark.amount_cny)} ÷ {number(Math.round(d.benchmark.quantity))} 次。{d.benchmark.amount_share!=null&&<>对应本方向已建模金额的{percent(d.benchmark.amount_share)}。</>} {d.benchmark.notes}</p></div>:<p>尚无与本方向金额匹配的申请或签发次数。</p>}
  {!!d.source_ids.length&&<button className="profile-source" onClick={()=>onSources(d.source_ids)}><FileText size={14}/>查看费用来源</button>}
 </section>;
 return <div className="country-profile" data-testid="country-profile"><p className="profile-scope">{profile.year} 年 · {name}全部已建模往来 · 人民币等值</p>{direction(outgoing,'申请人付出')}{direction(incoming,'政府收到')}
  <section className="profile-section"><h3>按人口折算</h3>{population?<><div className="profile-population"><span>{population.year} 年{population.label}</span><b>{number(population.value)} 人</b></div>{outgoing.amount_cny!=null&&<div className="profile-calculation"><span>申请人支出 ÷ 人口</span><b>{yuan(outgoing.amount_cny/population.value)}/人</b></div>}{incoming.amount_cny!=null&&<div className="profile-calculation"><span>政府收到 ÷ 人口</span><b>{yuan(incoming.amount_cny/population.value)}/人</b></div>}<p>这是费用规模的人口折算值，不是居民个人账单。申请与签发按次数统计，同一人可有多次记录。</p><button className="profile-source" onClick={()=>onSources([population.source_id])}><FileText size={14}/>查看人口来源</button></>:<p>当前年份没有同口径人口，暂不折算。</p>}</section>
  <p className="profile-scope">金额是当前来源覆盖的费用模型；已建模年份：{profile.available_years.length?profile.available_years.join('、'):'暂无'}。图中筛选范围可小于此摘要范围。</p>
 </div>;
}
