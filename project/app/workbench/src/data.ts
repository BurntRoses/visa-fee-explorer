import {gunzipSync} from 'fflate';
import {version as uiVersion} from '../package.json';
import type {WorkbenchIndex,WorkbenchState,AnalysisResult,AnalysisEdge,AnalysisNode,VisaGroup,CountryContextData} from './types';
export const groupNames:Record<VisaGroup,string>={visitor:'访客',student:'学生',work:'工作',family:'家庭',other:'其他类别',unclassified:'类别未细分'};
export const allGroups=Object.keys(groupNames) as VisaGroup[];
export const unknown=(c:string)=>!c||/^(UNK|RAW_|OTHER|WORLD|TOTAL|UNALLOCATED)/.test(c);
const formatters=new Map<number,Intl.NumberFormat>();
const fmt=(v:number,d:number)=>{if(!formatters.has(d))formatters.set(d,new Intl.NumberFormat('zh-CN',{maximumFractionDigits:d}));return formatters.get(d)!.format(v);};
export const money=(v:number|null|undefined,d=2)=>v==null||!Number.isFinite(v)?'未识别':Math.abs(v)>=1e8?`${fmt(v/1e8,d)}亿元`:Math.abs(v)>=1e4?`${fmt(v/1e4,d)}万元`:`${fmt(v,d)}元`;
export const number=(v:number)=>new Intl.NumberFormat('zh-CN').format(v);
export const defaultState:WorkbenchState={countries:['CHN','USA','GBR','SCH','JPN','CAN','AUS','IND'],focusCountry:'CHN',year:2025,visaGroups:[...allGroups],flowScope:'connected',regionMode:'aggregate',spatialScale:'country',view:'chord',singleMode:'radial',direction:'both',motionMode:'analysis',playing:false,playbackSpeed:3500,flowLight:false,showFree:true,maxNodes:24,minAmount:0};
type Details = 'coverage'|'profiles'|'references';
const dataParts=new Map<Details,Promise<Partial<WorkbenchIndex>>>();
const localBlock=(id:string)=>document.getElementById(`visa-${id}`)?.textContent;
async function dataBlob(id:string,path:string):Promise<Blob>{
 const embedded=localBlock(id);
 if(embedded){
  const parts:BlobPart[]=[];
  for(let offset=0;offset<embedded.length;offset+=524288){
   const raw=atob(embedded.slice(offset,offset+524288)), bytes=new Uint8Array(raw.length);
   for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
   parts.push(bytes);
  }
  return new Blob(parts);
 }
 const response=await fetch(new URL('./data/'+path,document.baseURI));
 if(!response.ok)throw new Error(`数据载入失败 (${response.status})`);
 return response.blob();
}
async function unzip(blob:Blob){
 return typeof DecompressionStream==='undefined'
  ?new Blob([gunzipSync(new Uint8Array(await blob.arrayBuffer()))])
  :new Response(blob.stream().pipeThrough(new DecompressionStream('gzip'))).blob();
}
async function payload(id:string,path:string){return JSON.parse(await (await unzip(await dataBlob(id,path))).text());}
export async function loadIndex():Promise<WorkbenchIndex>{
 const boot=await payload('boot',`boot-${uiVersion}.json.gz`);
 return {coverage:[],sources:[],models:[],feeRules:[],bills:[],finances:[],...boot};
}
export function loadDetails(kind:Details){
 if(!dataParts.has(kind))dataParts.set(kind,payload(kind,`${kind}-${uiVersion}.json.gz`).catch(error=>{dataParts.delete(kind);throw error;}));
 return dataParts.get(kind)!;
}
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
export const globalCountries=(index:WorkbenchIndex)=>normalizeSelection(index.entities.filter(e=>e.kind!=='unallocated').map(e=>e.code),'aggregate',index.schengenMembers);
export function hydrateState(index:WorkbenchIndex):WorkbenchState{
 const q=new URLSearchParams(location.hash.slice(1)),years=availableYears(index),all=globalCountries(index);
 const codes=q.get('countries'),valid=new Set(index.entities.map(e=>e.code));
 const countries=codes===null||codes==='all'?all:normalizeSelection(codes.split(',').filter(c=>valid.has(c)),'aggregate',index.schengenMembers);
 const view=q.get('view') as WorkbenchState['view'],singleMode=q.get('singleMode') as WorkbenchState['singleMode'];
 const global=countries.length===all.length,year=Number(q.get('year')),speed=Number(q.get('playbackSpeed'));
 const focus=q.get('focusCountry'),focusCountry=focus&&countries.includes(focus)?focus:countries[0]||'CHN';
 return {...defaultState,countries,focusCountry,year:years.includes(year)?year:years.at(-1)||2025,
  view:['chord','single','sankey','compare','heatmap'].includes(view)?view:'chord',
  flowScope:global||q.get('flowScope')==='connected'||(q.get('flowScope')!=='internal'&&view==='single')?'connected':'internal',
  spatialScale:q.get('spatialScale')==='region'?'region':'country',
  singleMode:['radial','origins','destinations'].includes(singleMode)?singleMode:'radial',
  motionMode:q.get('motionMode')==='presentation'?'presentation':'analysis',
  playbackSpeed:[1800,3500,6000].includes(speed)?speed:3500,flowLight:q.get('flowLight')==='true'};
}
export function stateUrl(s:WorkbenchState,global:boolean){
 const p=new URLSearchParams({countries:global?'all':s.countries.join(',')});
 for(const k of ['focusCountry','year','flowScope','spatialScale','view','singleMode','motionMode','playbackSpeed','flowLight'] as const)p.set(k,String(s[k]));
 return '#'+p.toString();
}
export function saveState(s:WorkbenchState,global:boolean){const hash=stateUrl(s,global);if(location.hash!==hash)history.replaceState(null,'',hash);}
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
export async function loadChunk(index:WorkbenchIndex,key:string):Promise<any[]>{
 if(!chunkCache.has(key))chunkCache.set(key,(async()=>{const path=index.chunks[key];return path?payload('chunk-'+key,path):[];})().catch(error=>{chunkCache.delete(key);throw error;}));return chunkCache.get(key)!;
}
const contextCache=new Map<string,Promise<CountryContextData>>();
export async function loadCountryContext(index:WorkbenchIndex,code:string,retry=false):Promise<CountryContextData|null>{
 const manifest=index.countryContext?.[code];if(!manifest)return null;
 const key=index.meta.version+'|'+code+'|'+manifest.file;if(retry)contextCache.delete(key);
 if(!contextCache.has(key))contextCache.set(key,(async()=>{
  const data:CountryContextData=await payload('context-'+code,manifest.file);
  if(data.code!==code||!Array.isArray(data.series))throw new Error('国家背景数据格式不完整');return data;
 })().catch(error=>{contextCache.delete(key);throw error;}));
 return contextCache.get(key)!;
}
function rowMatcher(index:WorkbenchIndex,state:WorkbenchState,route?:{origin:string;destination:string}){
 const norm=displayCode(index,state),selected=new Set(normalizeSelection(state.countries,state.regionMode,index.schengenMembers));
 return (r:any)=>{
  const a=norm(r.payer||r.origin),b=norm(r.receiver||r.destination);
  if(a===b||Number(r.year)!==state.year||!state.visaGroups.includes(r.display_group||r.visa_group))return false;
  if(route)return a===route.origin&&b===route.destination;
  if(state.view==='single'&&(state.singleMode==='origins'?b!==state.focusCountry:state.singleMode==='destinations'?a!==state.focusCountry:a!==state.focusCountry&&b!==state.focusCountry))return false;
  return state.flowScope==='internal'?selected.has(a)&&selected.has(b):selected.has(a)||selected.has(b);
 };
}
export function rawMatches(r:any,index:WorkbenchIndex,state:WorkbenchState,route?:{origin:string;destination:string}){return rowMatcher(index,state,route)(r);}
export async function selectedRows(index:WorkbenchIndex,state:WorkbenchState,route?:{origin:string;destination:string}){
 const members=index.schengenMembers;let codes: string[];
 if(route)codes=route.destination==='SCH'?members:[route.destination];
 else if(state.flowScope==='internal')codes=state.countries.flatMap(c=>c==='SCH'?members:[c]);else codes=Object.keys(index.chunks).filter(k=>k.endsWith('-'+state.year)).map(k=>k.split('-')[0]);
 const chunks=await Promise.all([...new Set(codes)].map(c=>loadChunk(index,`${c}-${state.year}`)));return chunks.flat().filter(rowMatcher(index,state,route)).sort((a,b)=>b.amount_cny-a.amount_cny);
}
export async function completeDataFile():Promise<Blob>{
 const json=await unzip(await dataBlob('full','full-data.json.gz'));
 return new Blob([json],{type:'application/json;charset=utf-8'});
}
export function download(content:string|Blob,filename:string,type='text/plain;charset=utf-8'){const blob=content instanceof Blob?content:new Blob([content],{type}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);}
export function csv(rows:any[],filename:string){const keys=[...new Set(rows.flatMap(Object.keys))];const cell=(v:any)=>{let s=v==null?'':typeof v==='object'?JSON.stringify(v):String(v);if(/^[=+@]/.test(s)||/^-\D/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};download('\ufeff'+[keys.map(cell).join(','),...rows.map(r=>keys.map(k=>cell(r[k])).join(','))].join('\r\n'),filename,'text/csv;charset=utf-8');}
