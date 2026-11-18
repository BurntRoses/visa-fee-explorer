import {useState,useEffect,useLayoutEffect,useMemo,useRef,useCallback,type ReactNode} from 'react';
import {useSystemReducedMotion} from './hooks/useSystemReducedMotion';
import {ArrowUpRight,ArrowDownLeft,ArrowLeftRight,Search,Plus,X,SlidersHorizontal,ChevronDown,ChevronRight,ChevronLeft,Maximize2,Minimize2,Download,Share2,Waves,Play,Pause,RotateCcw,Info,ExternalLink,Globe2,Network,ChartNoAxesCombined,Grid3X3,GitFork,PanelLeftClose,PanelLeftOpen,Check,Database,FileText,Image,Layers} from 'lucide-react';
import type {WorkbenchIndex,WorkbenchState,View,VisaGroup,IndexTuple} from './types';
import {groupNames,allGroups,hydrateState,globalCountries,loadDetails,loadYear,hasYear,previousYear,withYearRows,normalizeSelection,analyzeSelection,availableYears,selectionTrend,saveState,money,number,selectedRows,download,csv,completeDataFile,unknown} from './data';
import {ActionButton} from './components/ActionButton';
import {SegmentedControl} from './components/SegmentedControl';
import {WorkbenchChart} from './charts';
import {CountrySummary,CountryProfileDetails} from './components/CountrySummary';
import {singleCountryEdges} from './charts/helpers';
import {CountryPicker} from './components/CountryPicker';
import './styles.css';
import './prescription-focus.css';
import './workspace.css';

const viewOptions=[{id:'chord',label:'环形',icon:Network},{id:'sankey',label:'桑基',icon:GitFork},{id:'compare',label:'比较',icon:ChartNoAxesCombined},{id:'heatmap',label:'热图',icon:Grid3X3}] as const;
const statusNames:Record<string,string>={modeled_nationality:'已有国籍费用模型',modeled_total:'已有总额模型，国籍未分',fee_only:'已取得收费规则',quantity_only:'已取得签证数量',mobility_context_only:'已取得旅行／边境背景',researched_gap:'已检索，金额仍缺',not_researched:'待补充资料',current_fee_only:'仅当前价目，历史适用期未核实'};
const archiveLabel=(kind?:string)=>kind==='redacted_inert_web_snapshot'?'脱敏归档':kind==='fact_excerpt'||kind==='structured_factual_capture'?'事实摘录':kind==='provider_browser_text_capture'||kind==='official_original_web_text_snapshot'?'原文文本快照':kind==='indexed_official_page_extract'?'页面摘录':'本地归档';

function IconButton({label,children,onClick,active=false,disabled=false}:{label:string;children:ReactNode;onClick:()=>void;active?:boolean;disabled?:boolean}){return <button className={'icon-button'+(active?' selected':'')} aria-label={label} title={label} onClick={onClick} disabled={disabled}>{children}</button>;}
function Dialog({title,subtitle,onClose,children,wide=false}:{title:string;subtitle?:string;onClose:()=>void;children:ReactNode;wide?:boolean}){
 const ref=useRef<HTMLElement>(null),body=useRef<HTMLDivElement>(null),close=useRef(onClose);
 close.current=onClose;
 useEffect(()=>{
  const panel=ref.current!,previous=document.activeElement as HTMLElement|null;
  const escape=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!e.defaultPrevented)close.current();};
  document.addEventListener('keydown',escape);
  panel.focus({preventScroll:true});
  if(matchMedia('(max-width: 880px)').matches)panel.scrollIntoView({block:'start'});
  return()=>{document.removeEventListener('keydown',escape);if(previous?.isConnected){previous.focus({preventScroll:true});if(matchMedia('(max-width: 880px)').matches)previous.scrollIntoView({block:'nearest'});}};
 },[]);
 useEffect(()=>{if(body.current)body.current.scrollTop=0;},[title]);
 return <aside className={'docked-panel'+(wide?' wide':'')} aria-label={title} tabIndex={-1} ref={ref}>
  <header className="dialog-top"><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><IconButton label="关闭面板" onClick={onClose}><X size={19}/></IconButton></header>
  <div className="docked-body" ref={body}>{children}</div>
 </aside>;
}
export default function Workbench({index:initialIndex}:{index:WorkbenchIndex}){
 const [index,setIndex]=useState(initialIndex);
 const [state,setState]=useState<WorkbenchState>(()=>hydrateState(index));
 const [menu,setMenu]=useState(false),[picker,setPicker]=useState<'selection'|'country'|null>(null),[fullscreen,setFullscreen]=useState(false);
 const [drawer,setDrawer]=useState<'sources'|'route'|'data'|'coverage'|'export'|'help'|'focus'|'profile'|'members'|null>(null),[route,setRoute]=useState<{origin:string;destination:string}|null>(null),[sourceIds,setSourceIds]=useState<string[]|null>(null);
 const [memberCodes,setMemberCodes]=useState<string[]>([]),[memberQuery,setMemberQuery]=useState('');
 const [partError,setPartError]=useState(''),[retry,setRetry]=useState(0);
 const [yearError,setYearError]=useState(''),[yearRetry,setYearRetry]=useState(0);
 const [rows,setRows]=useState<any[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState(''),[detailQuery,setDetailQuery]=useState(''),[limit,setLimit]=useState(12),[sourceLimit,setSourceLimit]=useState(24),[toast,setToast]=useState('');
 const canvasRef=useRef<HTMLDivElement>(null),[size,setSize]=useState({width:0,height:0}),reduced=useSystemReducedMotion();
 const names=useMemo(()=>new Map(index.entities.map(e=>[e.code,e.name])),[index]);const name=(c:string)=>c==='SCH'?'申根':names.get(c)||c;
 const update=useCallback((patch:Partial<WorkbenchState>)=>setState(s=>{const next={...s,...patch,regionMode:'aggregate' as const,visaGroups:[...allGroups],minAmount:0,showFree:true};next.countries=normalizeSelection(next.countries,next.regionMode,index.schengenMembers);if(!next.countries.includes(next.focusCountry)&&next.countries.length)next.focusCountry=next.countries[0];return next;}),[index]);
 const analysis=useMemo(()=>analyzeSelection(index,state,state.view==='compare'),[index,state.countries.join(','),state.year,state.visaGroups.join(','),state.flowScope,state.regionMode,state.focusCountry,state.view==='compare']);
 const years=useMemo(()=>availableYears(index),[index]);
 const yearCoverage=useMemo(()=>new Map((index.globalTrend||[]).map(row=>[row.year,row])),[index.globalTrend]);
 const latestYear=years.at(-1)||2025,yearReceivers=yearCoverage.get(state.year)?.receivers||0,onlySchengen=!!yearCoverage.get(state.year)?.onlySchengen,limitedYear=yearReceivers<(yearCoverage.get(latestYear)?.receivers||0);
 const originalReceivers=index.meta.year_coverage?.find((item:{year:number})=>item.year===state.year)?.receivers?.length||yearReceivers;
 const countryProfile=index.countryProfiles?.[state.focusCountry]?.[String(state.year)];
 const focus=analysis.countryTotals.find(n=>n.code===state.focusCountry),focusView=analysis.nodes.find(n=>n.code===state.focusCountry);
 const singleLabel=state.singleMode==='origins'?'收到':state.singleMode==='destinations'?'付出':'双向';
 const plotEdges=useMemo(()=>state.view==='single'?singleCountryEdges(analysis,state):analysis.edges,[analysis,state.view,state.focusCountry,state.singleMode]),plotTotal=state.view==='single'?plotEdges.reduce((sum,e)=>sum+e.amount,0):analysis.total;
 const allCountries=useMemo(()=>globalCountries(initialIndex),[initialIndex]);
 const selected=useMemo(()=>new Set(state.countries),[state.countries]);
 const globalSelection=state.view!=='single'&&selected.size===allCountries.length&&allCountries.every(c=>selected.has(c));
 const yearReady=hasYear(index,state.year);
 const comparisonYear=state.view==='compare'?previousYear(index,state.year):undefined;
 const compareReady=comparisonYear===undefined||hasYear(index,comparisonYear);
 const chronology=useMemo(()=>{
  if(globalSelection&&index.globalTrend)return index.globalTrend;
  const calculated=new Map(selectionTrend(index,state).map(row=>[row.year,row]));
  return years.map(year=>calculated.get(year)||{year,total:0,receivers:0});
 },[globalSelection,index,years,state.countries.join(','),state.flowScope,state.view==='single',state.focusCountry,state.singleMode]);
 const timelineMax=Math.max(1,...chronology.map(row=>row.total));
 const currentCoverage=chronology.find(y=>y.year===state.year);
 const mode=state.view==='single'?'country':globalSelection?'global':'selection';
 const networkView=useRef<Exclude<View,'single'>>(state.view==='single'?'chord':state.view);
 if(state.view!=='single')networkView.current=state.view;
 const savedSelection=useRef<string[]>(mode==='selection'?state.countries:[]);
 useEffect(()=>{if(mode==='selection')savedSelection.current=state.countries;},[mode,state.countries]);
 const selectorEntities=useMemo(()=>{const members=new Set(initialIndex.schengenMembers);return initialIndex.entities.filter(e=>!unknown(e.code)&&!members.has(e.code));},[initialIndex]);
 const selectionLabel=mode==='global'?'全球':mode==='country'?name(state.focusCountry):`已选 ${state.countries.length} 项`;
 const showPicker=(kind:'selection'|'country')=>{setDrawer(null);setPicker(picker===kind?null:kind);};
 const showDrawer=(kind:typeof drawer)=>{setPicker(null);setDrawer(kind);};
 const showGlobal=()=>{setPicker(null);setDrawer(null);update({countries:allCountries,view:networkView.current,flowScope:'connected',playing:false});};
 useEffect(()=>{
  setYearError('');
  let canceled=false;
  const required=[state.year,...(comparisonYear===undefined?[]:[comparisonYear])].filter(year=>!hasYear(index,year));
  if(required.length)Promise.all(required.map(year=>loadYear(index,year))).then(rows=>{
   if(!canceled)setIndex(current=>withYearRows(current,...rows));
  }).catch(()=>{if(!canceled)setYearError('该年度暂时无法读取');});
  return()=>{canceled=true;};
 },[index,state.year,comparisonYear,yearRetry]);
 useEffect(()=>{
  if(globalSelection||!yearReady)return;
  let canceled=false;
  // Filtered trend amounts are optional; give the selected year priority.
  const pending=years.filter(year=>!hasYear(index,year));
  if(pending.length)void (async()=>{
   const loaded:IndexTuple[][]=[];
   for(let i=0;i<pending.length&&!canceled;i+=3){
    const results=await Promise.allSettled(pending.slice(i,i+3).map(year=>loadYear(index,year)));
    for(const result of results)if(result.status==='fulfilled')loaded.push(result.value);
   }
   if(!canceled&&loaded.length)setIndex(current=>withYearRows(current,...loaded));
  })();
  return()=>{canceled=true;};
 },[globalSelection,yearReady,index,years]);
 const needed=drawer==='coverage'?'coverage':drawer==='route'||drawer==='sources'||drawer==='profile'?'references':null;
 useEffect(()=>{
  setPartError('');
  const parts:Array<'coverage'|'references'|'profiles'>=[];
  if(needed)parts.push(needed);
  if(state.view==='single'||drawer==='profile')parts.push('profiles');
  if(!parts.length)return;
  let canceled=false;
  for(const part of parts)loadDetails(part).then(payload=>{if(!canceled)setIndex(current=>Object.keys(payload).every(key=>current[key as keyof WorkbenchIndex]===payload[key as keyof WorkbenchIndex])?current:{...current,...payload});}).catch(error=>{if(!canceled)setPartError(String(error.message));});
  return()=>{canceled=true;};
 },[needed,state.view,drawer,retry]);
 const toggleFullscreen=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.querySelector('.workbench')?.requestFullscreen();}catch{notify('当前浏览器不支持全屏');}};
 useEffect(()=>{const changed=()=>setFullscreen(!!document.fullscreenElement);document.addEventListener('fullscreenchange',changed);return()=>document.removeEventListener('fullscreenchange',changed);},[]);
 useEffect(()=>{if(menu)requestAnimationFrame(()=>document.querySelector<HTMLButtonElement>('.utility-menu button')?.focus());},[menu]);
 const notify=(text:string)=>{setToast(text);setTimeout(()=>setToast(''),2400);};
 useEffect(()=>{saveState(state,globalSelection);},[state,globalSelection]);
 useLayoutEffect(()=>{
  const box=canvasRef.current;if(!box)return;
  const measure=({width,height}:{width:number;height:number})=>{
   const next={width:Math.round(width),height:Math.round(height)};
   setSize(old=>old.width===next.width&&old.height===next.height?old:next);
  };
  measure(box.getBoundingClientRect());
  const observer=new ResizeObserver(([e])=>measure(e.contentRect));observer.observe(box);
  return()=>observer.disconnect();
 },[]);
 useEffect(()=>{if(!state.playing||state.motionMode!=='presentation'||reduced||!yearReady)return;const position=years.indexOf(state.year);if(position>=years.length-1){update({playing:false});return;}const next=years[position+1];void loadYear(index,next).catch(()=>{});const id=setTimeout(()=>update({year:next}),state.playbackSpeed||3500);return()=>clearTimeout(id);},[state.playing,state.motionMode,state.year,state.playbackSpeed,reduced,years,yearReady,index]);
 useEffect(()=>{if(reduced&&state.playing)update({playing:false});},[reduced,state.playing]);
 useEffect(()=>{if(drawer!=='route'&&drawer!=='data')return;let cancelled=false;setLoading(true);setError('');setRows([]);setLimit(12);setDetailQuery('');selectedRows(index,state,drawer==='route'?route||undefined:undefined).then(r=>{if(!cancelled)setRows(r);}).catch(e=>{if(!cancelled)setError(String(e.message));}).finally(()=>{if(!cancelled)setLoading(false);});return()=>{cancelled=true;};},[drawer,route,state.year,state.visaGroups.join(','),state.countries.join(','),state.flowScope,state.regionMode]);
 const focusCountry=(code:string)=>{if(unknown(code))return;setPicker(null);setDrawer(null);update({countries:[code],focusCountry:code,flowScope:'connected',spatialScale:'country',view:'single',playing:false});};
 const applyPicker=(codes:string[])=>{if(picker==='country'){focusCountry(codes[0]);return;}setPicker(null);update({countries:codes,view:networkView.current,flowScope:codes.length===allCountries.length||codes.length===1?'connected':mode==='selection'?state.flowScope:'internal',playing:false});};
 const openRoute=(origin:string,destination:string)=>{setRoute({origin,destination});showDrawer('route');};
 const openSources=(ids:string[]|null=null)=>{setSourceIds(ids);setDetailQuery('');setSourceLimit(24);showDrawer('sources');};
 const openMembers=(codes:string[])=>{if(codes.length){setMemberCodes(codes);setMemberQuery('');showDrawer('members');}};
 const memberRows=useMemo(()=>{
  if(drawer!=='members')return [];
  const nodes=new Map(memberCodes.map(code=>[code,{code,name:names.get(code)||code,incoming:0,outgoing:0,hasIn:false,hasOut:false}]));
  for(const edge of plotEdges){
   const a=nodes.get(edge.origin),b=nodes.get(edge.destination);
   if(a){a.outgoing+=edge.amount;a.hasOut=true;}
   if(b){b.incoming+=edge.amount;b.hasIn=true;}
  }
  return [...nodes.values()].sort((a,b)=>b.incoming+b.outgoing-a.incoming-a.outgoing);
 },[drawer,memberCodes,plotEdges,names]);
 const currentCoverageRows=useMemo(()=>{
  const map=new Map<string,WorkbenchIndex['coverage']>();
  if(drawer==='coverage')for(const row of index.coverage)if(row.year===state.year){const values=map.get(row.code);if(values)values.push(row);else map.set(row.code,[row]);}
  return map;
 },[drawer,index.coverage,state.year]);
 const sourceResults=useMemo(()=>{if(drawer!=='sources')return [];const ids=sourceIds&&new Set(sourceIds),q=detailQuery.trim().toLowerCase();return index.sources.filter(s=>(!ids||ids.has(s.source_id))&&[s.title,s.publisher,s.source_id,s.url,s.local_path].join(' ').toLowerCase().includes(q));},[drawer,index,sourceIds,detailQuery]);
 const filteredDetail=useMemo(()=>rows.filter(r=>[name(r.payer||r.origin),name(r.receiver||r.destination),r.visa_label,groupNames[r.display_group as VisaGroup],r.visa_type].join(' ').toLowerCase().includes(detailQuery.toLowerCase())),[rows,detailQuery,names]);
 const scopes=[{id:'internal',label:'所选之间'},{id:'connected',label:'与全球往来'}] as const;
 const exportChart=async(format:'svg'|'png')=>{const svg=canvasRef.current?.querySelector('svg');if(!svg){notify('当前视图暂无可导出图形');return;}const copy=svg.cloneNode(true) as SVGElement;const original=[svg,...svg.querySelectorAll('*')],copies=[copy,...copy.querySelectorAll('*')];original.forEach((el,i)=>{const style=getComputedStyle(el);for(const key of ['fill','stroke','stroke-width','font-family','font-size','font-weight','opacity','fill-opacity','stroke-opacity','text-anchor','stroke-dasharray','stroke-dashoffset','stroke-linecap','clip-path'])copies[i]?.setAttribute(key,style.getPropertyValue(key));copies[i]?.removeAttribute('style');});copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.setAttribute('width',String(size.width));copy.setAttribute('height',String(size.height+72));copy.setAttribute('viewBox',`0 0 ${size.width} ${size.height+72}`);const plot=document.createElementNS('http://www.w3.org/2000/svg','g');while(copy.firstChild)plot.append(copy.firstChild);plot.setAttribute('transform','translate(0 42)');copy.append(plot);const background=document.createElementNS('http://www.w3.org/2000/svg','rect');background.setAttribute('width','100%');background.setAttribute('height','100%');background.setAttribute('fill','#ffffff');copy.prepend(background);const caption=document.createElementNS('http://www.w3.org/2000/svg','text');caption.setAttribute('x','14');caption.setAttribute('y','22');caption.setAttribute('fill','#385d65');caption.setAttribute('font-size','12');caption.setAttribute('font-family','sans-serif');caption.textContent=`${state.year} 签证费用 · ${state.flowScope==='internal'?'所选国家之间':'与全球往来'} · ${state.view==='single'?name(state.focusCountry)+' · '+singleLabel:state.countries.length+'个国家/辖区'} · 人民币`;copy.append(caption);const foot=document.createElementNS('http://www.w3.org/2000/svg','text');foot.setAttribute('x','14');foot.setAttribute('y',String(size.height+62));foot.setAttribute('fill','#8b9aa3');foot.setAttribute('font-size','9');foot.setAttribute('font-family','sans-serif');foot.textContent=`${index.meta.version} · 申请人国籍 → 收款政府 · 已建模范围 · ${money(plotTotal)} · 每条费用流计一次`;copy.append(foot);const metadata=document.createElementNS('http://www.w3.org/2000/svg','metadata');metadata.textContent=JSON.stringify({version:index.meta.version,state,amount_cny:plotTotal,definition:'申请人国籍→收款政府；费用模型；每条计一次'});copy.prepend(metadata);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`签证费用流向 ${state.year} · ${state.flowScope==='internal'?'所选国家之间':'与全球往来'} · ${state.view==='single'?name(state.focusCountry)+' · '+singleLabel:state.countries.map(name).join('、')}`;copy.prepend(title);const text=new XMLSerializer().serializeToString(copy),filename=`签证费用-${state.year}-${state.view}`;if(format==='svg'){download(text,filename+'.svg','image/svg+xml');return;}const image=new window.Image(),url=URL.createObjectURL(new Blob([text],{type:'image/svg+xml'}));await new Promise<void>((resolve,reject)=>{image.onload=()=>{const c=document.createElement('canvas');c.width=size.width*2;c.height=(size.height+72)*2;const ctx=c.getContext('2d')!;ctx.fillStyle='#f8fafb';ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(image,0,0,c.width,c.height);c.toBlob(blob=>{if(!blob){URL.revokeObjectURL(url);reject(new Error('PNG导出失败'));return;}download(blob,filename+'.png');URL.revokeObjectURL(url);resolve();});};image.onerror=()=>{URL.revokeObjectURL(url);reject(new Error('PNG导出失败'));};image.src=url;});};
 useEffect(()=>{(window as any).VISA_WORKBENCH={get state(){return state;},get analysis(){return analysis;},index,update,analyzeSelection:(s:WorkbenchState)=>analyzeSelection(index,s),selectedRows:(s=state)=>selectedRows(index,s),openRoute,openSources};},[state,analysis,index]);
 const focusPanel=<aside className="focus-panel"><p className="focus-scope">国家全部已建模往来 · {state.year}</p><div className="focus-balance"><div><span><ArrowDownLeft size={14}/>政府收到</span><strong>{money(focus?.incomingKnown?focus.incoming:null)}</strong></div><div><span><ArrowUpRight size={14}/>申请人付出</span><strong>{money(focus?.outgoingKnown?focus.outgoing:null)}</strong></div></div><div className="focus-net"><span>收到 − 付出</span><strong>{money(focus?.net)}</strong></div><div className="focus-chart-scope"><span>其中，当前图中</span><p>收到 <b>{money(focusView?.incoming||0)}</b> · 付出 <b>{money(focusView?.outgoing||0)}</b></p></div>{!!focus?.unallocated&&<div className="focus-note"><Info size={15}/><p>{money(focus.unallocated)}流入尚未分配付款国籍，已计入收到。</p></div>}<h3>主要往来</h3><div className="focus-routes">{analysis.edges.filter(e=>e.origin===state.focusCountry||e.destination===state.focusCountry).slice(0,6).map(e=><button key={e.id} onClick={()=>openRoute(e.origin,e.destination)}><span>{e.origin===state.focusCountry?<ArrowUpRight size={13}/>:<ArrowDownLeft size={13}/>} {name(e.origin===state.focusCountry?e.destination:e.origin)}</span><strong>{money(e.amount)}</strong></button>)}</div><button className="focus-more" onClick={()=>setDrawer('data')}>查看当前范围全部明细<ChevronRight size={14}/></button><div className="focus-bottom"><span>数据截至 {index.meta.cutoff||'2026-11-15'}</span><button onClick={()=>openSources()}>来源与计算依据<ExternalLink size={12}/></button></div></aside>;
 return <div className="workbench simple-workbench modern-workbench">
  <header className="app-header"><h1>签证费用</h1><div className="header-actions"><button className="flow-light-toggle" aria-label="流向流光" aria-pressed={state.flowLight&&!reduced} title={reduced?'系统已开启减少动态，流光暂停':'流光从申请人移向收款政府；独立于年份播放'} disabled={reduced} onClick={()=>update({flowLight:!state.flowLight})}><Waves size={17}/><span>流光</span></button><button id="utility-trigger" className="menu-trigger" aria-expanded={menu} aria-label="打开资料菜单" onClick={()=>setMenu(!menu)}>资料<ChevronDown size={15}/></button><IconButton label={fullscreen?'退出全屏':'全屏画布'} onClick={toggleFullscreen}>{fullscreen?<Minimize2 size={17}/>:<Maximize2 size={17}/>}</IconButton><button className="export-button" onClick={()=>showDrawer('export')}><Download size={17}/><span>导出</span></button></div>{menu&&<nav className="utility-menu" aria-label="资料菜单" onKeyDown={e=>{const items=[...e.currentTarget.querySelectorAll('button')];if(e.key==='Escape'){setMenu(false);document.getElementById('utility-trigger')?.focus();}if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const i=items.indexOf(document.activeElement as HTMLButtonElement),n=e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;items[n]?.focus();}}}>{[{id:'data',label:'费用明细',icon:Database},{id:'sources',label:'来源',icon:FileText},{id:'coverage',label:'数据覆盖',icon:Globe2},{id:'help',label:'读图',icon:Info}].map(item=><button key={item.id} onClick={()=>{setMenu(false);if(item.id==='sources')openSources();else showDrawer(item.id as any);}}><item.icon size={17}/>{item.label}</button>)}<button onClick={async()=>{try{await navigator.clipboard.writeText(location.href);notify('链接已复制');}catch{notify('可复制浏览器地址保存');}setMenu(false);}}><Share2 size={17}/>复制链接</button></nav>}</header>
  <div className={`workspace-layout ${picker?'with-picker':drawer?'with-drawer':''}`}>
  <main className="main-workspace">
   <div className="primary-controls">
    <div className="scope-controls" role="group" aria-label="分析范围">
     <button className="scope-button" aria-pressed={mode==='global'} onClick={showGlobal}><Globe2 size={15}/>全球</button>
     <button className="scope-button" aria-pressed={mode==='selection'} aria-expanded={picker==='selection'} onClick={()=>showPicker('selection')}>自选{mode==='selection'&&<small>{state.countries.length}</small>}<ChevronDown size={13}/></button>
     <button className="scope-button" aria-pressed={mode==='country'} aria-expanded={picker==='country'} onClick={()=>showPicker('country')}>{mode==='country'?name(state.focusCountry):'单国'}<ChevronDown size={13}/></button>
    </div>
    {mode!=='country'?<SegmentedControl label="图形" className="view-tabs" value={state.view as Exclude<View,'single'>} options={viewOptions} onChange={view=>update({view})}/>
    :<SegmentedControl label="单国往来方向" value={state.singleMode==='categories'?'radial':state.singleMode} options={[{id:'radial',label:'双向'},{id:'origins',label:'收到'},{id:'destinations',label:'付出'}]} onChange={singleMode=>update({singleMode})}/>}
   </div>
   <div className="result-toolbar">
    <div className="result-context">
     {mode==='global'?<span className="scope-caption">全部已识别路线 · 含未分配国籍</span>:mode==='country'?<span className="scope-caption">{selectionLabel}与全球的往来</span>:<SegmentedControl label="往来范围" value={state.flowScope} options={scopes} onChange={flowScope=>update({flowScope,playing:false})}/>}
     {mode!=='country'&&<SegmentedControl label="空间尺度" className="spatial-scale" value={state.spatialScale} options={[{id:'country',label:'国家'},{id:'region',label:'大区'}]} onChange={spatialScale=>update({spatialScale})}/>}
    </div>
    <div className="result-amount"><span>{state.year}</span><strong title="当前范围的已建模政府费用">{yearReady?money(plotEdges.length?plotTotal:null):'—'}</strong></div>
   </div>
   <div className={'year-coverage'+(limitedYear?' limited':'')} data-testid="year-coverage" data-year={state.year} data-receivers={yearReceivers}><div><strong>{onlySchengen?`${state.year} 年仅有申根短期费用数据`:`${state.year} 年有金额记录：${originalReceivers} 个收款政府`}</strong><span>{onlySchengen?'更换来源国，仍只会显示流向申根的已知费用。':`申根合并统计后，当前范围显示 ${currentCoverage?.receivers||0} 个收款方`}</span></div>{limitedYear?<button onClick={()=>update({year:latestYear,playing:false})}>查看 {latestYear} 多国数据<ChevronRight size={14}/></button>:<button onClick={()=>showDrawer('coverage')}>查看覆盖<ChevronRight size={14}/></button>}</div>
   {state.view==='single'&&index.countryContext&&<CountrySummary profile={countryProfile} name={name(state.focusCountry)} mode={state.singleMode} onOpen={()=>showDrawer('profile')}/>}
   <div className="chart-stage" ref={canvasRef} data-testid="chart-stage" aria-busy={!yearReady||!compareReady}>{!yearReady?<div className="canvas-empty">{yearError?<><h2>{yearError}</h2><button className="primary" onClick={()=>setYearRetry(n=>n+1)}>重新载入</button></>:<div className="year-placeholder" role="status"><span aria-hidden="true"/><p>读取 {state.year} 年</p></div>}</div>:!state.countries.length?<div className="canvas-empty"><h2>选择国家</h2><button className="primary" onClick={()=>showPicker('selection')}>选择国家</button></div>:analysis.edges.length===0?<div className="canvas-empty"><h2>{state.countries.length===1&&state.flowScope==='internal'?'查看全球往来':'暂无费用记录'}</h2>{state.flowScope==='internal'?<button className="primary" onClick={()=>update({flowScope:'connected'})}>查看全球往来</button>:<button className="primary" onClick={()=>showPicker('selection')}>更换国家／地区</button>}</div>:size.width>0&&<WorkbenchChart analysis={analysis} state={state} width={size.width} height={size.height} onFocus={focusCountry} onRoute={openRoute} onMembers={openMembers} onState={update} reducedMotion={reduced}/>}

   </div>
   <div className="timeline"><div className="timeline-actions"><IconButton label={state.playing?'暂停播放':'播放时间变化'} active={state.playing} disabled={reduced||years.length<2} onClick={()=>update({motionMode:'presentation',year:!state.playing&&state.year===latestYear?years[Math.max(0,years.length-2)]:state.year,playing:!state.playing})}>{state.playing?<Pause size={18}/>:<Play size={18}/>}</IconButton><button className="speed-button" aria-label="播放速度" title="切换播放速度" onClick={()=>update({playbackSpeed:state.playbackSpeed===3500?1800:state.playbackSpeed===1800?6000:3500})}>{state.playbackSpeed===1800?'2×':state.playbackSpeed===6000?'0.5×':'1×'}</button></div><SegmentedControl label="年份" className="year-rail" value={String(state.year)} options={chronology.map(y=>({id:String(y.year),label:String(y.year),title:`${y.year} · 全库${yearCoverage.get(y.year)?.receivers||0}个收款方 · 当前筛选${globalSelection||hasYear(index,y.year)?y.receivers+"个":"—"} ${globalSelection||hasYear(index,y.year)?money(y.total):"点击查看"}`,content:<><span className="year-bar" style={{height:Math.max(2,y.total/timelineMax*24)}}/><span className="full-year">{y.year}</span><span className="short-year">{String(y.year).slice(2)}</span><small className="year-coverage-label">{yearCoverage.get(y.year)?.receivers===1?'仅申根':`${yearCoverage.get(y.year)?.receivers||0}收款方`}</small></>}))} onChange={year=>update({year:Number(year),playing:false})}/><div className="timeline-compact"><button aria-label="上一年" disabled={years.indexOf(state.year)===0} onClick={()=>update({year:years[years.indexOf(state.year)-1],playing:false})}><ChevronLeft size={18}/></button><div><output>{state.year}</output><input aria-label="年份滑块" type="range" min="0" max={years.length-1} step="1" value={Math.max(0,years.indexOf(state.year))} onChange={e=>update({year:years[Number(e.target.value)],playing:false})}/><span>{years[0]}<i/>{years.at(-1)}</span></div><button aria-label="下一年" disabled={years.indexOf(state.year)===years.length-1} onClick={()=>update({year:years[years.indexOf(state.year)+1],playing:false})}><ChevronRight size={18}/></button></div></div>
   <footer className="canvas-footer"><span>人民币 · {state.view==='single'?new Set(plotEdges.map(e=>e.destination)).size:currentCoverage?.receivers||0}个已建模收款方</span>{state.view==='single'&&<button onClick={()=>showDrawer('focus')}>收到 {money(focusView?.incomingKnown?focusView.incoming:null)}<span className="footer-separator"/>付出 {money(focusView?.outgoingKnown?focusView.outgoing:null)}<ChevronRight size={15}/></button>}{yearReady&&!compareReady&&<div className="comparison-status" role="status">{yearError?<>{comparisonYear} 年对照暂不可用 <button onClick={()=>setYearRetry(n=>n+1)}>重试</button></>:<>读取 {comparisonYear} 年对照</>}</div>}</footer>
  </main>
  {drawer==='members'&&<Dialog title="聚合成员" subtitle={`${memberRows.length} 个国家／地区 · 当前范围`} onClose={()=>setDrawer(null)}>
   <label className="search-field"><Search size={16}/><input aria-label="搜索聚合成员" placeholder="搜索国家或代码" value={memberQuery} onChange={e=>setMemberQuery(e.target.value)}/></label>
   <div className="viz-member-heading"><span>国家／地区</span><span>收到</span><span>付出</span></div>
   <div className="viz-member-list">{memberRows.filter(n=>[n.name,n.code].join(' ').toLowerCase().includes(memberQuery.trim().toLowerCase())).map(n=><button key={n.code} onClick={()=>focusCountry(n.code)}><span>{n.name}</span><b>{money(n.hasIn?n.incoming:null)}</b><b>{money(n.hasOut?n.outgoing:null)}</b></button>)}</div>
  </Dialog>}
  {drawer==='focus'&&<Dialog title={name(state.focusCountry)} onClose={()=>setDrawer(null)}><div className="focus-drawer-content">{focusPanel}</div></Dialog>}
  {picker&&<Dialog title={picker==='country'?'选择一个国家／辖区':'选择分析范围'} onClose={()=>setPicker(null)}><CountryPicker key={picker} single={picker==='country'} initial={mode==='selection'?state.countries:savedSelection.current} apply={applyPicker} entities={selectorEntities}/></Dialog>}
  {drawer==='route'&&route&&<Dialog title={`${name(route.origin)} → ${name(route.destination)}`} subtitle={`${state.year}`} onClose={()=>setDrawer(null)}><div className="detail-total"><span>合计</span><strong>{loading?'载入中…':money(rows.reduce((s,r)=>s+r.amount_cny,0))}</strong><p>费用模型分项 · {rows.length} 项</p></div>{loading?<p className="loading-message">正在读取这一条费用流的依据…</p>:error?<div className="error-message">{error}<button onClick={()=>{setDrawer(null);setTimeout(()=>setDrawer('route'),0);}}>重新载入</button></div>:<><label className="search-field"><Search size={16}/><input aria-label="搜索路线分项" value={detailQuery} onChange={e=>{setDetailQuery(e.target.value);setLimit(12);}} placeholder="搜索类型、费用分项…"/></label><p className="result-caption">{Math.min(limit,filteredDetail.length)} / {filteredDetail.length} 项</p>{filteredDetail.slice(0,limit).map(r=><details className="evidence-card" key={r.id}><summary><span>{r.visa_label||r.visa_type}</span><strong>{money(r.amount_cny)}</strong><Plus size={14}/></summary><dl><dt>原币金额</dt><dd>{r.currency} {number(r.amount||0)}</dd><dt>数量与口径</dt><dd>{r.quantity==null?'数量未单独识别':number(r.quantity)} · {r.quantity_basis||'见模型'}</dd><dt>原始归属</dt><dd>{r.origin_basis||'见来源'}</dd><dt>统计期间</dt><dd>{r.period_label||r.year}</dd><dt>模型方法</dt><dd>{r.method_id||'见参数'}</dd><dt>分项范围</dt><dd>{money(r.lower_cny)} — {money(r.upper_cny)}</dd><dt>原始端点</dt><dd>{name(r.payer)} → {name(r.receiver)}</dd></dl>{r.notes&&<p>{typeof r.notes==='string'?r.notes:JSON.stringify(r.notes)}</p>}<details className="parameter-details"><summary>模型参数</summary><pre>{JSON.stringify(r.parameters,null,2)}</pre></details><button className="text-button" onClick={()=>openSources(r.source_ids)}>查看分项来源<ExternalLink size={13}/></button></details>)}{limit<filteredDetail.length&&<button className="load-more" onClick={()=>setLimit(limit+12)}>继续显示 {Math.min(12,filteredDetail.length-limit)} 个分项</button>}<div className="drawer-actions"><button onClick={()=>csv(rows,`visa-${route.origin}-${route.destination}-${state.year}.csv`)}><Download size={15}/>完整路线 CSV</button><button onClick={()=>openSources([...new Set(rows.flatMap(r=>r.source_ids||[]))])}><FileText size={15}/>全部路线来源</button></div>{index.bills.filter(b=>b.origin===route.origin&&b.destination===route.destination&&Number(b.year)===state.year).map((b,i)=><details className="bill-card" key={i}><summary>申请人完整账单示例 · {b.label}</summary>{(b.components||[]).map((c:any,j:number)=><div key={j}><span>{c.label}</span><strong>{c.currency} {c.amount}</strong></div>)}<p>{b.notes}</p></details>)}</>}</Dialog>}
  {drawer==='data'&&<Dialog title="费用明细" subtitle={`${state.year}`} onClose={()=>setDrawer(null)} wide>{loading?<p className="loading-message">正在按当前范围读取模型分项…</p>:error?<p className="error-message">{error}</p>:<><div className="data-drawer-toolbar"><label className="search-field"><Search size={16}/><input aria-label="搜索费用记录" value={detailQuery} onChange={e=>{setDetailQuery(e.target.value);setLimit(12);}} placeholder="搜索国家、类别、路线…"/></label><button className="primary" onClick={()=>csv(filteredDetail,`visa-selection-${state.year}.csv`)}><Download size={14}/>筛选 CSV</button></div><p className="result-caption">{number(filteredDetail.length)} 个模型分项 · {money(filteredDetail.reduce((s,r)=>s+r.amount_cny,0))}</p><div className="data-records">{filteredDetail.slice(0,limit).map(r=><button key={r.id} onClick={()=>openRoute(state.regionMode==='aggregate'&&index.schengenMembers.includes(r.payer)?'SCH':r.payer,state.regionMode==='aggregate'&&index.schengenMembers.includes(r.receiver)?'SCH':r.receiver)}><span>{name(r.payer)} <ArrowUpRight size={13}/> {name(r.receiver)}<small>{r.visa_label||r.visa_type}</small></span><strong>{money(r.amount_cny)}</strong><ChevronRight size={15}/></button>)}</div>{limit<filteredDetail.length&&<button className="load-more" onClick={()=>setLimit(limit+24)}>继续显示 24 项</button>}</>}</Dialog>}
  {drawer==='sources'&&index.sources.length>0&&<Dialog title="来源" onClose={()=>setDrawer(null)}><label className="search-field"><Search size={16}/><input aria-label="搜索来源" value={detailQuery} onChange={e=>{setDetailQuery(e.target.value);setSourceLimit(24);}} placeholder="搜索标题、机构、来源编号…"/></label>{route&&sourceIds&&<button className="load-more" onClick={()=>setDrawer('route')}>返回 {name(route.origin)} → {name(route.destination)} 的费用明细</button>}<div className="source-results"><p className="result-caption" role="status">{sourceResults.length?`显示 ${Math.min(sourceLimit,sourceResults.length)} / ${sourceResults.length} 项`:'未找到匹配来源'}</p><button className="text-button" disabled={!sourceResults.length} onClick={()=>csv(sourceResults.map(s=>({source_id:s.source_id,title:s.title,publisher:s.publisher,url:s.url,archive_path:s.local_path,archive_kind:s.archive_kind,sha256:s.sha256,retrieved_at:s.retrieved_at,locator:s.source_locator,archive_note:s.archive_note})),`visa-sources-${index.meta.version}.csv`)}><Download size={14}/> 导出来源 CSV</button></div><div className="source-items">{sourceResults.slice(0,sourceLimit).map(s=><article key={s.source_id}><code>{s.source_id}</code><h3>{s.title}</h3><p>{s.publisher} · {s.publication_date||s.published_at||s.retrieved_at}</p><div><a href={s.url} target="_blank" rel="noreferrer">原始页面<ExternalLink size={12}/></a>{s.local_path&&<a href={'../'+s.local_path} target="_blank" rel="noreferrer">{archiveLabel(s.archive_kind)}<FileText size={12}/></a>}</div>{(s.notes||s.archive_note)&&<p>{[s.notes,s.archive_note].filter(Boolean).join(' ')}</p>}</article>)}</div>{sourceLimit<sourceResults.length&&<button className="load-more" onClick={()=>setSourceLimit(sourceLimit+24)}>继续显示 {Math.min(24,sourceResults.length-sourceLimit)} 项</button>}</Dialog>}
  {drawer==='coverage'&&index.coverage.length>0&&<Dialog title="数据覆盖" onClose={()=>setDrawer(null)} wide><div className="coverage-summary with-context"><div><strong>{index.entities.filter(e=>e.kind==='country_or_jurisdiction').length}</strong><span>国家／辖区底册</span></div><div><strong>{new Set(index.coverage.filter(c=>c.year===state.year&&c.amount_known).map(c=>c.code)).size}</strong><span>{state.year} 有金额模型</span></div><div><strong>{new Set(index.coverage.filter(c=>c.year===state.year&&c.fee_known).map(c=>c.code)).size}</strong><span>有历史收费规则</span></div><div><strong>{new Set(index.coverage.filter(c=>c.year===state.year&&c.mobility_context_known).map(c=>c.code)).size}</strong><span>有旅行／边境背景</span></div></div><p className="jurisdiction-note">{index.meta.jurisdiction_note}</p><p className="method-caption">金额边是费用模型分项。未分配国籍仍属于收款方收到，缺失方向保留未识别。不同国家实际覆盖的签证类别可逐项查看。“现价”表示已取得当前价目，历史年度适用期尚未确认。旅行／边境背景单列，不计入签证数量或费用分母。</p><label className="search-field"><Search size={16}/><input aria-label="搜索覆盖国家" value={detailQuery} onChange={e=>setDetailQuery(e.target.value)} placeholder="搜索国家或地区…"/></label><div className="coverage-table">{index.entities.filter(e=>e.kind==='country_or_jurisdiction'&&[e.name,e.code,e.region].join(' ').toLowerCase().includes(detailQuery.toLowerCase())).map(e=>{const cc=currentCoverageRows.get(e.code)||[];return <div key={e.code}><strong>{e.name}<small>{e.region}</small></strong><div>{cc.some(c=>c.mobility_context_known)&&<span className="coverage-chip context" title="旅行、出入境或边境统计；与签证申请数量分别识别">旅行背景</span>}{allGroups.map(g=>{const c=cc.find(c=>c.visa_group===g);return <span key={g} className={'coverage-chip '+(c?.amount_known?'known':c?.fee_known?'fee':c?.fee_current_snapshot_known?'current':'missing')} title={c?statusNames[c.status]+' · '+c.notes:'尚未识别'}>{groupNames[g]} · {c?.amount_known?'金额':c?.fee_known?'费率':c?.quantity_known?'签证量':c?.fee_current_snapshot_known?'现价':'缺'}</span>;})}</div></div>;})}</div><button className="load-more" onClick={()=>csv(index.coverage,'visa-world-coverage.csv')}>下载完整覆盖底册 CSV</button></Dialog>}
  {drawer==='export'&&<Dialog title="导出" subtitle={`${state.year} · 人民币`} onClose={()=>setDrawer(null)}><div className="export-options"><ActionButton onAction={()=>exportChart('svg')}><Image size={21}/><span><strong>图形 SVG</strong></span><Download size={16}/></ActionButton><ActionButton onAction={()=>exportChart('png')}><Image size={21}/><span><strong>图形 PNG</strong></span><Download size={16}/></ActionButton><ActionButton onAction={async()=>{const rr=await selectedRows(index,state);csv(rr,`visa-selection-${state.year}.csv`);}}><Database size={21}/><span><strong>当前筛选 CSV</strong></span><Download size={16}/></ActionButton><ActionButton onAction={()=>{download(JSON.stringify({version:index.meta.version,state,amount_cny:plotTotal,displayed_edges:plotEdges,analysis},null,2),`visa-analysis-${state.year}.json`,'application/json');}}><Layers size={21}/><span><strong>分析状态 JSON</strong></span><Download size={16}/></ActionButton><ActionButton onAction={async()=>{download(await completeDataFile(),'visa-complete-'+index.meta.version+'.json','application/json');}}><FileText size={21}/><span><strong>完整数据 JSON</strong></span><Download size={16}/></ActionButton></div></Dialog>}
  {drawer==='profile'&&index.sources.length>0&&index.countryContext&&<Dialog title={name(state.focusCountry)+'费用摘要'} subtitle={String(state.year)} onClose={()=>setDrawer(null)}><CountryProfileDetails index={index} code={state.focusCountry} year={state.year} profile={countryProfile} name={name(state.focusCountry)} entityName={name} onSources={openSources}/></Dialog>}
  {drawer==='help'&&<Dialog title="读图" onClose={()=>setDrawer(null)}><div className="help-content"><h3>国家与地区统计口径</h3><p>{index.meta.jurisdiction_note}</p><h3>申请人国籍 → 收款政府</h3><p>同一笔费用在付款方记付出，在收款方记收到。当前范围总额按每条费用流计一次。</p><h3>先选择国家，再选择范围</h3><p>“所选之间”包含两端都在集合中的费用。“全球往来”包含集合外对手方。</p><h3>国家与大区</h3><p>“大区”按亚洲、欧洲、非洲、美洲、大洋洲汇总当前国家集合的费用。同一大区内国家之间的签证费仍计入；点击大区可展开实际国家。国籍未分配保持单列。</p><h3>选择国家和费用连接</h3><p>点击图中的国家锁定高亮，可继续选择“单国查看”；再次点击或按Escape取消。点击色带或热图金额，查看费用、数量、参数和来源。画布随窗口自动适配，可使用顶部全屏按钮扩大。使用画布下方的 ＋／－ 缩放；放大后拖动，双击空白或按 0 恢复。</p><h3>未知与免费</h3><p>灰色为付款国籍未分配，金额已经计入收款方。无记录显示未识别。已知免费路线可用虚线显示并标0。</p><h3>金额与区间</h3><p>主图为费用模型中心；原始申请、签发与财政期间随分项保留。各年来源和签证类别覆盖不同。年份轨道列出收款范围，年度合计应结合当年覆盖阅读。签发量、财政收入和跨期估算分别保留原口径；缺失没有补零。</p><h3>动态演示</h3><p>时间轴可选择年度、播放和调整速度；播放到最新年份停止，从最新年份启动时只播放最近两年。色带宽度表示金额，光痕从付款方持续移向收款方；双向费用各走自己的色带。顶部“流光”独立开关，不改变年份或金额，暂停年份播放后仍继续显示。系统减少动态会暂停流光；导出保存当前静态光痕。</p></div></Dialog>}
  {((drawer==='sources'&&!index.sources.length)||(drawer==='coverage'&&!index.coverage.length)||(drawer==='profile'&&(!index.countryContext||!index.sources.length)))&&<Dialog title={drawer==='sources'?'来源':drawer==='coverage'?'数据覆盖':'国家费用摘要'} onClose={()=>setDrawer(null)}>{partError?<p className="error-message">{partError} <button onClick={()=>setRetry(n=>n+1)}>重新载入</button></p>:<p className="loading-message" role="status">正在读取资料…</p>}</Dialog>}
  </div>
  {!!toast&&<div className="toast" role="status">{toast}</div>}
 </div>;
}
