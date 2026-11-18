import {gunzipSync,strFromU8} from 'fflate';
import type {WorkbenchIndex,WorkbenchState,AnalysisResult,AnalysisEdge,AnalysisNode,VisaGroup,CountryContextData} from './types';
export const groupNames:Record<VisaGroup,string>={visitor:'访客',student:'学生',work:'工作',family:'家庭',other:'其他类别',unclassified:'类别未细分'};
export const allGroups=Object.keys(groupNames) as VisaGroup[];
export const unknown=(c:string)=>!c||/^(UNK|RAW_|OTHER|WORLD|TOTAL|UNALLOCATED)/.test(c);
export const money=(v:number|null|undefined,d=2)=>v==null||!Number.isFinite(v)?'未识别':Math.abs(v)>=1e8?`${new Intl.NumberFormat('zh-CN',{maximumFractionDigits:d}).format(v/1e8)}亿元`:Math.abs(v)>=1e4?`${new Intl.NumberFormat('zh-CN',{maximumFractionDigits:d}).format(v/1e4)}万元`:`${new Intl.NumberFormat('zh-CN',{maximumFractionDigits:d}).format(v)}元`;
export const number=(v:number)=>new Intl.NumberFormat('zh-CN').format(v);
export const defaultState:WorkbenchState={countries:['CHN','USA','GBR','SCH','JPN','CAN','AUS','IND'],focusCountry:'CHN',year:2025,visaGroups:[...allGroups],flowScope:'internal',regionMode:'aggregate',spatialScale:'country',view:'chord',singleMode:'radial',direction:'both',motionMode:'analysis',playing:false,playbackSpeed:3500,flowLight:true,showFree:true,maxNodes:24,minAmount:0};
export async function loadIndex():Promise<WorkbenchIndex>{const embedded=document.getElementById('visa-index');if(embedded)return JSON.parse(embedded.textContent||'{}');const response=await fetch(new URL('./data/index.json',document.baseURI));if(!response.ok)throw new Error(`绘图索引载入失败 ${response.status}`);return response.json();}
const yearlyData=new WeakMap<WorkbenchIndex,{records:Map<number,WorkbenchIndex['records']>;coverage:Map<number,WorkbenchIndex['coverage']>;years:number[]}>();
function byYear(index:WorkbenchIndex){
 let grouped=yearlyData.get(index);
 if(!grouped){
  const records=new Map<number,WorkbenchIndex['records']>(),coverage=new Map<number,WorkbenchIndex['coverage']>();
  for(const row of index.records){const year=row[0],list=records.get(year);if(list)list.push(row);else records.set(year,[row]);}
  for(const row of index.coverage){const list=coverage.get(row.year);if(list)list.push(row);else coverage.set(row.year,[row]);}
  grouped={records,coverage,years:[...records.keys()].sort((a,b)=>a-b)};yearlyData.set(index,grouped);
 }
 return grouped;
}
export function availableYears(index:WorkbenchIndex):number[]{return byYear(index).years;}
export function normalizeSelection(countries:string[],mode:WorkbenchState['regionMode'],members:string[]){const set=new Set(countries.filter(c=>!unknown(c)));if(mode==='aggregate'){if([...set].some(c=>members.includes(c))){members.forEach(c=>set.delete(c));set.add('SCH');}}else if(set.has('SCH')){set.delete('SCH');members.forEach(c=>set.add(c));}return [...set];}
export function hydrateState(index:WorkbenchIndex):WorkbenchState{let saved:any={};try{const q=new URLSearchParams(location.hash.slice(1));saved=q.has('countries')?{...Object.fromEntries(q),countries:q.get('countries')!.split(','),visaGroups:(q.get('visaGroups')||allGroups.join(',')).split(','),year:Number(q.get('year'))}:JSON.parse(localStorage.getItem('visa-workbench-state-v4')||'{}');}catch{}const valid=new Set(index.entities.map(e=>e.code)),s={...defaultState,...saved,playing:false};const years=availableYears(index);if(saved.year===undefined)s.year=years.at(-1)||defaultState.year;s.year=years.includes(Number(s.year))?Number(s.year):years.at(-1)||2025;s.view=['chord','single','sankey','compare','heatmap'].includes(s.view)?s.view:'chord';s.flowScope=s.flowScope==='connected'?'connected':'internal';s.regionMode='aggregate';s.spatialScale=s.spatialScale==='region'?'region':'country';s.countries=normalizeSelection(Array.isArray(s.countries)?s.countries.filter((c:string)=>valid.has(c)):defaultState.countries,s.regionMode,index.schengenMembers);s.visaGroups=[...allGroups];s.maxNodes=defaultState.maxNodes;s.playbackSpeed=[1800,3500,6000].includes(Number(s.playbackSpeed))?Number(s.playbackSpeed):3500;s.singleMode=['radial','origins','destinations'].includes(s.singleMode)?s.singleMode:'radial';s.direction=['both','incoming','outgoing'].includes(s.direction)?s.direction:'both';s.motionMode=s.motionMode==='presentation'?'presentation':'analysis';s.flowLight=![false,'false'].includes(s.flowLight);if(!s.countries.includes(s.focusCountry))s.focusCountry=s.countries[0]||'CHN';s.minAmount=0;s.showFree=true;return s;}
export function saveState(s:WorkbenchState){const share={...s,playing:false};try{localStorage.setItem('visa-workbench-state-v4',JSON.stringify(share));}catch{}const p=new URLSearchParams();for(const k of ['countries','focusCountry','year','flowScope','spatialScale','view','singleMode','motionMode','playbackSpeed','flowLight'] as const)p.set(k,Array.isArray(share[k])?(share[k] as string[]).join(','):String(share[k]));history.replaceState(null,'','#'+p.toString());}
function displayCode(index:WorkbenchIndex,state:WorkbenchState){
 const members=new Set(index.schengenMembers);
 return (code:string)=>unknown(code)?'UNK':state.regionMode==='aggregate'&&members.has(code)?'SCH':code;
}
export function selectionTrend(index:WorkbenchIndex,state:WorkbenchState){
 const rename=displayCode(index,state),selected=new Set(normalizeSelection(state.countries,state.regionMode,index.schengenMembers));
 const focus=state.focusCountry||state.countries[0],groups=new Set(state.visaGroups);
 return availableYears(index).map(year=>{
  const receivers=new Set<string>();let total=0;
  for(const [,oi,di,gi,amount] of byYear(index).records.get(year)||[]){
   if(!groups.has(index.groups[gi]))continue;
   const origin=rename(index.entities[oi].code),destination=rename(index.entities[di].code);
   if(origin===destination)continue;
   const from=selected.has(origin),to=selected.has(destination);
   if(!(state.flowScope==='internal'?from&&to:from||to))continue;
   if(state.view==='single'){
    if(state.singleMode==='origins'?destination!==focus:state.singleMode==='destinations'?origin!==focus:origin!==focus&&destination!==focus)continue;
   }
   total+=amount;receivers.add(destination);
  }
  return {year,total,receivers:receivers.size};
 });
}
export function analyzeSelection(index:WorkbenchIndex,state:WorkbenchState,includePrevious=true):AnalysisResult{
 const selected=new Set(normalizeSelection(state.countries,state.regionMode,index.schengenMembers));
 const rename=displayCode(index,state);
 const names=new Map(index.entities.map(e=>[e.code,e.name]));const edges=new Map<string,AnalysisEdge>();let internal=0,externalIn=0,externalOut=0,unallocated=0,globalTotal=0,rowCount=0;
 const allNodes=new Map<string,AnalysisNode>();const node=(code:string)=>{if(!allNodes.has(code))allNodes.set(code,{code,name:names.get(code)||code,incoming:0,outgoing:0,net:null,incomingKnown:false,outgoingKnown:false,unallocated:0,selected:selected.has(code)});return allNodes.get(code)!;};
 for(const [year,oi,di,gi,amount,count] of byYear(index).records.get(state.year)||[]){
  const group=index.groups[gi];if(!state.visaGroups.includes(group))continue;
  const origin=rename(index.entities[oi].code),destination=rename(index.entities[di].code);if(origin===destination)continue;
  globalTotal+=amount;const org=node(origin),dst=node(destination);org.outgoing+=amount;org.outgoingKnown=true;dst.incoming+=amount;dst.incomingKnown=true;if(origin==='UNK')dst.unallocated+=amount;
  const from=selected.has(origin),to=selected.has(destination);if(from&&to)internal+=amount;else if(to&&origin!=='UNK')externalIn+=amount;else if(from)externalOut+=amount;if(to&&origin==='UNK')unallocated+=amount;
  const included=state.flowScope==='internal'?from&&to:from||to;if(!included)continue;rowCount+=count;
  const key=`${origin}|${destination}`,id=`${year}|${origin}|${destination}|${group}`;
  if(!edges.has(key))edges.set(key,{id:key,origin,destination,amount:0,count:0,ids:[],groups:{}});const e=edges.get(key)!;e.amount+=amount;e.count+=count;e.ids.push(id);e.groups[group]=(e.groups[group]||0)+amount;
 }
 const rr=[...edges.values()].sort((a,b)=>b.amount-a.amount),displayNodes=new Map<string,AnalysisNode>();
 const dnode=(code:string)=>{if(!displayNodes.has(code))displayNodes.set(code,{...node(code),incoming:0,outgoing:0,net:null,incomingKnown:false,outgoingKnown:false,unallocated:0});return displayNodes.get(code)!;};
 selected.forEach(dnode);for(const e of rr){const a=dnode(e.origin),b=dnode(e.destination);a.outgoing+=e.amount;a.outgoingKnown=true;b.incoming+=e.amount;b.incomingKnown=true;if(e.origin==='UNK')b.unallocated+=e.amount;}
 for(const n of allNodes.values())n.net=n.incomingKnown&&n.outgoingKnown?n.incoming-n.outgoing:null;for(const n of displayNodes.values())n.net=n.incomingKnown&&n.outgoingKnown?n.incoming-n.outgoing:null;
 const categoryTotals=allGroups.map(group=>({group,name:groupNames[group],incoming:rr.filter(e=>e.destination===state.focusCountry).reduce((s,e)=>s+(e.groups[group]||0),0),outgoing:rr.filter(e=>e.origin===state.focusCountry).reduce((s,e)=>s+(e.groups[group]||0),0)}));
 const coverCodes=new Set([...selected].flatMap(c=>c==='SCH'?index.schengenMembers:[c]));
 const result:AnalysisResult={edges:rr,nodes:[...displayNodes.values()],entities:index.entities,countryTotals:[...selected].map(node),total:rr.reduce((s,e)=>s+e.amount,0),globalTotal,year:state.year,categoryTotals,coverage:(byYear(index).coverage.get(state.year)||[]).filter(r=>coverCodes.has(r.code)&&state.visaGroups.includes(r.visa_group as VisaGroup)),totals:{internal,externalIn,externalOut,unallocated,amount:rr.reduce((s,e)=>s+e.amount,0),rowCount,edgeCount:rr.length}};
 if(includePrevious){const years=availableYears(index),position=years.indexOf(state.year),otherYear=years[position>0?position-1:1];if(otherYear!==undefined){result.previousNodes=analyzeSelection(index,{...state,year:otherYear},false).nodes;result.comparisonYear=otherYear;}}
 return result;
}
const chunkCache=new Map<string,Promise<any[]>>();
function b64bytes(s:string){return Uint8Array.from(atob(s),c=>c.charCodeAt(0));}
export async function loadChunk(index:WorkbenchIndex,key:string):Promise<any[]>{
 if(!chunkCache.has(key))chunkCache.set(key,(async()=>{const embedded=(window as any).__VISA_CHUNKS__?.[key];if(embedded)return JSON.parse(strFromU8(gunzipSync(b64bytes(embedded))));const path=index.chunks[key];if(!path)return [];const r=await fetch(new URL('./data/'+path,document.baseURI));if(!r.ok)throw new Error(`证据分项载入失败 ${r.status}`);return JSON.parse(strFromU8(gunzipSync(new Uint8Array(await r.arrayBuffer()))));})().catch(error=>{chunkCache.delete(key);throw error;}));return chunkCache.get(key)!;
}
const contextCache=new Map<string,Promise<CountryContextData>>();
export async function loadCountryContext(index:WorkbenchIndex,code:string,retry=false):Promise<CountryContextData|null>{
 const manifest=index.countryContext?.[code];if(!manifest)return null;
 const key=index.meta.version+'|'+code+'|'+manifest.file;if(retry)contextCache.delete(key);
 if(!contextCache.has(key))contextCache.set(key,(async()=>{
  const embedded=(window as any).__VISA_CONTEXT__?.[code];let data:CountryContextData;
  if(embedded)data=JSON.parse(strFromU8(gunzipSync(b64bytes(embedded))));
  else{const response=await fetch(new URL('./data/'+manifest.file,document.baseURI));if(!response.ok)throw new Error(`国家背景数据载入失败 ${response.status}`);data=JSON.parse(strFromU8(gunzipSync(new Uint8Array(await response.arrayBuffer()))));}
  if(data.code!==code||!Array.isArray(data.series))throw new Error('国家背景数据格式不完整');return data;
 })().catch(error=>{contextCache.delete(key);throw error;}));
 return contextCache.get(key)!;
}
export function rawMatches(r:any,index:WorkbenchIndex,state:WorkbenchState,route?:{origin:string;destination:string}){
 const members=new Set(index.schengenMembers),norm=(c:string)=>unknown(c)?'UNK':state.regionMode==='aggregate'&&members.has(c)?'SCH':c;
 const a=norm(r.payer||r.origin),b=norm(r.receiver||r.destination);if(a===b||Number(r.year)!==state.year||!state.visaGroups.includes(r.display_group||r.visa_group))return false;
 if(route)return a===route.origin&&b===route.destination;const s=new Set(normalizeSelection(state.countries,state.regionMode,index.schengenMembers));return state.flowScope==='internal'?s.has(a)&&s.has(b):s.has(a)||s.has(b);
}
export async function selectedRows(index:WorkbenchIndex,state:WorkbenchState,route?:{origin:string;destination:string}){
 const members=index.schengenMembers;let codes: string[];
 if(route)codes=route.destination==='SCH'?members:[route.destination];
 else if(state.flowScope==='internal')codes=state.countries.flatMap(c=>c==='SCH'?members:[c]);else codes=Object.keys(index.chunks).filter(k=>k.endsWith('-'+state.year)).map(k=>k.split('-')[0]);
 const chunks=await Promise.all([...new Set(codes)].map(c=>loadChunk(index,`${c}-${state.year}`)));return chunks.flat().filter(r=>rawMatches(r,index,state,route)).sort((a,b)=>b.amount_cny-a.amount_cny);
}
export async function completeDataFile():Promise<Blob>{
 const embedded=(window as any).__VISA_FULL__;let compressed:Blob;
 if(embedded){
  // Decode bounded chunks so exporting the corpus never creates a large object graph.
  const parts:BlobPart[]=[];for(let offset=0;offset<embedded.length;offset+=524288){const raw=atob(embedded.slice(offset,offset+524288)),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);parts.push(bytes);}compressed=new Blob(parts);
 }else{const response=await fetch(new URL('./data/full-data.json.gz',document.baseURI));if(!response.ok)throw new Error('完整数据包载入失败');compressed=await response.blob();}
 const json=typeof DecompressionStream!=='undefined'?await new Response(compressed.stream().pipeThrough(new DecompressionStream('gzip'))).blob():new Blob([gunzipSync(new Uint8Array(await compressed.arrayBuffer()))]);
 return new Blob([json],{type:'application/json;charset=utf-8'});
}
export function download(content:string|Blob,filename:string,type='text/plain;charset=utf-8'){const blob=content instanceof Blob?content:new Blob([content],{type}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);}
export function csv(rows:any[],filename:string){const keys=[...new Set(rows.flatMap(Object.keys))];const cell=(v:any)=>{let s=v==null?'':typeof v==='object'?JSON.stringify(v):String(v);if(/^[=+@]/.test(s)||/^-\D/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};download('\ufeff'+[keys.map(cell).join(','),...rows.map(r=>keys.map(k=>cell(r[k])).join(','))].join('\r\n'),filename,'text/csv;charset=utf-8');}
