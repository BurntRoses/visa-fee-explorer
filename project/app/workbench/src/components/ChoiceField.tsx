import {useId,useMemo,useRef,useState,type KeyboardEvent} from 'react';
import {Check,ChevronDown,Search} from 'lucide-react';
import './choice-field.css';

export type ChoiceOption={id:string;label:string;detail?:string;search?:string};

export function ChoiceField({label,caption,value,options,onChange,searchable=false}:{
 label:string;caption?:string;value:string;options:ChoiceOption[];onChange:(id:string)=>void;searchable?:boolean;
}){
 const id=useId(),trigger=useRef<HTMLButtonElement>(null),list=useRef<HTMLUListElement>(null),search=useRef<HTMLInputElement>(null);
 const [open,setOpen]=useState(false),[query,setQuery]=useState(''),[active,setActive]=useState('');
 const selected=options.find(option=>option.id===value),canSearch=searchable&&options.length>10;
 const visible=useMemo(()=>{
  const q=query.trim().toLocaleLowerCase();
  return q?options.filter(option=>[option.label,option.detail,option.search].join(' ').toLocaleLowerCase().includes(q)):options;
 },[options,query]);
 const close=(restore=false)=>{if(restore)trigger.current?.focus();setOpen(false);setQuery('');};
 const pick=(id:string)=>{onChange(id);close(true);};
 const move=(position:number)=>{
  if(!visible.length)return;
  const at=Math.max(0,Math.min(visible.length-1,position));
  setActive(visible[at].id);
  list.current?.children.item(at)?.scrollIntoView({block:'nearest'});
 };
 const show=(mode:'first'|'last'|'selected'='selected')=>{
  const at=mode==='first'?0:mode==='last'?options.length-1:Math.max(0,options.findIndex(o=>o.id===value));
  setActive(options[at]?.id||'');setOpen(true);
  requestAnimationFrame(()=>{
   if(canSearch&&mode==='selected'){search.current?.focus({preventScroll:true});return;}
   list.current?.focus({preventScroll:true});list.current?.children.item(at)?.scrollIntoView({block:'nearest'});
  });
 };
 const current=visible.findIndex(option=>option.id===active),position=Math.max(0,current);
 const handleList=(event:KeyboardEvent)=>{
  if(event.key==='ArrowDown')move(current+1);
  else if(event.key==='ArrowUp')move(position-1);
  else if(event.key==='Home')move(0);
  else if(event.key==='End')move(visible.length-1);
  else if((event.key==='Enter'||event.key===' ')&&visible.length)pick(visible[position].id);
  else return;
  event.preventDefault();
 };
 return <div className="choice-field" onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))close();}}
  onKeyDown={event=>{if(open&&event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);}}}>
  {caption&&<span className="choice-caption">{caption}</span>}
  <button type="button" ref={trigger} className="choice-trigger" aria-label={label} aria-describedby={id+'-value'}
   aria-haspopup="listbox" aria-expanded={open} aria-controls={open?id:undefined} data-value={value} disabled={!options.length}
   onClick={()=>open?close():show()} onKeyDown={event=>{
    if(event.key!=='ArrowDown'&&event.key!=='ArrowUp')return;
    event.preventDefault();
    if(open){list.current?.focus();move(event.key==='ArrowDown'?0:visible.length-1);}
    else show(event.key==='ArrowDown'?'first':'last');
   }}>
   <span id={id+'-value'}>{selected?.label||'暂无选项'}{selected?.detail&&<small>{selected.detail}</small>}</span>
   <ChevronDown size={15} aria-hidden="true"/>
  </button>
  {open&&<div className="choice-surface">
   {canSearch&&<label className="choice-search"><Search size={15} aria-hidden="true"/><input ref={search} value={query}
    aria-label={label+'：搜索选项'} placeholder="搜索选项" onChange={event=>{setQuery(event.target.value);setActive('');if(list.current)list.current.scrollTop=0;}}
    onKeyDown={event=>{
     if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();list.current?.focus();move(event.key==='ArrowDown'?0:visible.length-1);}
     else if(event.key==='Enter'&&visible.length){event.preventDefault();pick(visible[0].id);}
    }}/></label>}
   <ul id={id} ref={list} role="listbox" aria-label={label} className="choice-options" tabIndex={0}
    aria-activedescendant={visible.length?id+'-'+position:undefined} onKeyDown={handleList}>
    {visible.map((option,i)=><li id={id+'-'+i} key={option.id} role="option" aria-selected={option.id===value} data-value={option.id}
     data-active={i===position} onMouseDown={event=>event.preventDefault()} onClick={()=>pick(option.id)}>
     <span>{option.label}{option.detail&&<small>{option.detail}</small>}</span>
     {option.id===value&&<Check size={15} aria-hidden="true"/>}
    </li>)}
   </ul>
   {!visible.length&&<p className="choice-empty" role="status">没有匹配选项</p>}
  </div>}
 </div>;
}
