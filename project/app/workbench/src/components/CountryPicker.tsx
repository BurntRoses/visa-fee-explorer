import {useMemo,useState} from 'react';
import {Search,Check,ChevronRight} from 'lucide-react';
import type {Entity} from '../types';
import {ChoiceField} from './ChoiceField';

const regions=['亚洲','欧洲','美洲','非洲','大洋洲','其他地区'];
const regionOptions=[{id:'',label:'所有地区'},...regions.map(r=>({id:r,label:r}))];
const alphabet=new Intl.Collator('zh-CN');
export function CountryPicker({entities,initial,single,apply}:{entities:Entity[];initial:string[];single:boolean;apply:(codes:string[])=>void}){
 const [draft,setDraft]=useState(()=>new Set(initial)),[query,setQuery]=useState(''),[region,setRegion]=useState(''),[selectedOnly,setSelectedOnly]=useState(false);
 const ordered=useMemo(()=>[...entities].sort((a,b)=>alphabet.compare(a.name,b.name)),[entities]);
 const countries=ordered.filter(e=>(!region||e.region===region)&&(!selectedOnly||draft.has(e.code))&&[e.name,e.code,e.code==='SCH'?'申根 Schengen':''].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
 const toggle=(code:string)=>setDraft(old=>{const next=new Set(old);if(next.has(code))next.delete(code);else next.add(code);return next;});
 const visibleSelected=countries.length>0&&countries.every(e=>draft.has(e.code));
 return <div className="country-picker">
  <p className="picker-intro">{single?'选择一个国家／辖区，查看它与全球的签证费用往来。':'选择要分析的国家／辖区，再应用范围。申根以整体计。'}</p>
  <label className="search-field"><Search size={17}/><input aria-label="搜索国家" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索国家、辖区或代码"/></label>
  <div className="picker-filters">
   <ChoiceField label="按地区筛选" value={region} options={regionOptions} onChange={setRegion}/>
   {!single&&<button type="button" className="picker-filter-btn" aria-pressed={selectedOnly} onClick={()=>setSelectedOnly(v=>!v)}>仅看已选</button>}
  </div>
  <div className="picker-bulk">
   <span>{countries.length} 项</span>
   {!single&&<><button disabled={!countries.length} onClick={()=>setDraft(old=>{const next=new Set(old);for(const e of countries)if(visibleSelected)next.delete(e.code);else next.add(e.code);return next;})}>{visibleSelected?'取消本列表':'全选本列表'}</button><button disabled={!draft.size} onClick={()=>setDraft(new Set())}>清空</button></>}
  </div>
  <div className="country-options" aria-label={single?'可查看的国家':'可选择的国家'}>
   {countries.map(e=><button key={e.code} type="button" className="country-option" aria-current={single&&draft.has(e.code)?true:undefined} aria-pressed={single?undefined:draft.has(e.code)} onClick={()=>single?apply([e.code]):toggle(e.code)}>
    {!single&&<span aria-hidden="true" className="check-box">{draft.has(e.code)&&<Check size={14}/>}</span>}<strong>{e.name}</strong><code>{e.code}</code>{single&&(draft.has(e.code)?<Check size={14} aria-hidden="true"/>:<ChevronRight size={14} aria-hidden="true"/>)}
   </button>)}
   {!countries.length&&<p className="picker-empty">没有匹配项，试试更换搜索词或地区。</p>}
  </div>
  {!single&&<footer className="picker-footer"><span>已选 {draft.size} 项</span><button className="primary" disabled={!draft.size} onClick={()=>apply([...draft])}>应用选择</button></footer>}
 </div>;
}
