import type {AnalysisEdge, AnalysisNode, AnalysisResult, WorkbenchState} from '../types';
export const OTHER='__OTHER__';
export const IN='#4d877d', OUT='#ad7c60', UNKNOWN='#83939a';
const palette=['#548b83','#6a8aab','#9b88a2','#bc9573','#819887'];
export const unknown=(code:string)=>/^(UNK|UNALLOCATED|OTHER|RAW_|WORLD|TOTAL)/i.test(code);
export function countryColor(code:string){if(code===OTHER)return '#9aa9af';if(unknown(code))return UNKNOWN;let h=0;for(const c of code)h=(h*31+c.charCodeAt(0))>>>0;return palette[h%palette.length];}
const formats=new Map<number,Intl.NumberFormat>();
export const fmt=(value:number,d=2)=>{if(!formats.has(d))formats.set(d,new Intl.NumberFormat('zh-CN',{maximumFractionDigits:d}));return formats.get(d)!.format(value);};
export function money(value:number){return !Number.isFinite(value)?'未识别':Math.abs(value)>=1e8?`${fmt(value/1e8)}亿元`:Math.abs(value)>=1e4?`${fmt(value/1e4)}万元`:`${fmt(value)}元`;}
export const shortMoney=(value:number)=>Math.abs(value)>=1e8?`${fmt(value/1e8)}亿`:Math.abs(value)>=1e4?`${fmt(value/1e4)}万`:fmt(value);
export function nameMap(a:AnalysisResult){const m=new Map(a.entities.map(n=>[n.code,n.name]));a.nodes.forEach(n=>m.set(n.code,n.name));m.set('SCH','申根整体');m.set(OTHER,'其余国家／地区');m.set('UNK','国籍未分配');return m;}
export function label(code:string,names:Map<string,string>){return code===OTHER?'其余国家／地区':unknown(code)?'国籍未分配':names.get(code)||code;}
export interface GraphNode {code:string;name:string;amount:number;incoming:number;outgoing:number;incomingKnown:boolean;outgoingKnown:boolean;members:string[];}
export interface GraphEdge extends AnalysisEdge {originals:AnalysisEdge[];}
export interface GraphData {nodes:GraphNode[];edges:GraphEdge[];displayed:number;omitted:number;others:number;}
export function singleCountryEdges(a:AnalysisResult,s:WorkbenchState){
 const focus=s.focusCountry||s.countries[0];
 return a.edges.filter(e=>{
  if(s.singleMode==='origins')return e.destination===focus;
  if(s.singleMode==='destinations')return e.origin===focus;
  return e.origin===focus||e.destination===focus;
 });
}
export function singleCountryGraph(a:AnalysisResult,s:WorkbenchState,width:number,height:number):GraphData{
 const focus=s.focusCountry||s.countries[0],edges=singleCountryEdges(a,s);
 return graphData({...a,edges,total:edges.reduce((sum,e)=>sum+e.amount,0)},
  {...s,countries:[],maxNodes:viewNodeCap('chord',width,height,s.maxNodes)},width,focus);
}
export function graphData(a:AnalysisResult,s:WorkbenchState,width:number,focus?:string):GraphData{
 const names=nameMap(a),cap=Math.max(focus?3:2,Math.min(s.maxNodes||24,width<600?12:24)),positive=a.edges.filter(e=>e.amount>=(s.minAmount||0)&&(e.amount>0||s.showFree));
 const weights=new Map<string,number>();for(const e of positive){weights.set(e.origin,(weights.get(e.origin)||0)+e.amount);weights.set(e.destination,(weights.get(e.destination)||0)+e.amount);}
 // Countries without a recorded route stay in the picker, not as empty ring sectors.
 const ranked=[...weights].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
 const overflow=ranked.length>cap,keep=ranked.slice(0,overflow?cap-1:cap).map(([c])=>c);
 const pinned=[...(focus?[focus]:s.countries.length<=Math.max(2,cap-3)?s.countries:[]),...ranked.filter(([code])=>unknown(code)).map(([code])=>code)].filter(code=>weights.has(code));
 for(const code of pinned)if(!keep.includes(code)){if(keep.length>=cap-1){const removable=keep.map(c=>!pinned.includes(c)).lastIndexOf(true);if(removable>=0)keep.splice(removable,1);}keep.unshift(code);}
 const regions=new Map(a.entities.map(e=>[e.code,e.region||'其他'])),order=['亚洲','欧洲','非洲','美洲','大洋洲','其他'];
 const hidden=ranked.filter(([c])=>!keep.includes(c)).map(([c])=>c),codes=[...keep].sort((a,b)=>{if(a===focus)return -1;if(b===focus)return 1;if(unknown(a)!==unknown(b))return unknown(a)?1:-1;const region=(c:string)=>{const i=order.indexOf(regions.get(c)||'其他');return i<0?5:i;};return region(a)-region(b)||a.localeCompare(b);});if(hidden.length)codes.push(OTHER);
 const ids=new Set(keep),map=new Map<string,GraphEdge>();
 for(const e of positive){const origin=ids.has(e.origin)?e.origin:OTHER,destination=ids.has(e.destination)?e.destination:OTHER,key=origin+'|'+destination;if(!map.has(key))map.set(key,{...e,id:key,origin,destination,amount:0,count:0,ids:[],groups:{},originals:[]});const out=map.get(key)!;out.amount+=e.amount;out.count+=e.count;out.ids.push(...e.ids);out.originals.push(e);for(const [g,v]of Object.entries(e.groups||{}))out.groups[g as keyof typeof out.groups]=(out.groups[g as keyof typeof out.groups]||0)+(v||0);}
 const edges=[...map.values()],nodes=codes.map(code=>{const inEdges=edges.filter(e=>e.destination===code),outEdges=edges.filter(e=>e.origin===code),incoming=inEdges.reduce((v,e)=>v+e.amount,0),outgoing=outEdges.reduce((v,e)=>v+e.amount,0);return {code,name:code===OTHER?`其余 ${hidden.length} 项`:label(code,names),amount:incoming+outgoing,incoming,outgoing,incomingKnown:!!inEdges.length,outgoingKnown:!!outEdges.length,members:code===OTHER?hidden:a.entities.find(e=>e.code===code)?.members||[code]};});
 const displayed=edges.reduce((v,e)=>v+e.amount,0);return {nodes,edges,displayed,omitted:Math.max(0,a.total-displayed),others:hidden.length};
}
export function distributeLabels<T extends {y:number}>(items:T[],top:number,bottom:number,gap:number):T[]{
 if(!items.length)return items;const sorted=[...items].sort((a,b)=>a.y-b.y).map(x=>({...x}));const effective=Math.min(gap,(bottom-top)/Math.max(1,items.length-1));let prev=top-effective;for(const item of sorted){item.y=Math.max(item.y,prev+effective);prev=item.y;}let next=bottom+effective;for(let i=sorted.length-1;i>=0;i--){sorted[i].y=Math.min(sorted[i].y,next-effective);next=sorted[i].y;}return sorted;
}

export function fitLabel(text:string,maxWidth:number,fontSize=12){const width=(s:string)=>[...s].reduce((v,c)=>v+(/[\u3400-\u9fff]/.test(c)?fontSize:fontSize*.58),0);if(width(text)<=maxWidth)return text;let out='';for(const c of text){if(width(out+c+'…')>maxWidth)break;out+=c;}return out+'…';}
export function labelLines(text:string,maxWidth:number,fontSize=14){const lines:string[]=[];let line='',width=0;for(const c of text){const charWidth=/[\u3400-\u9fff]/.test(c)?fontSize:fontSize*.6;if(line&&width+charWidth>Math.max(fontSize*2,maxWidth)){lines.push(line);line='';width=0;}line+=c;width+=charWidth;}if(line)lines.push(line);return lines;}
export function viewNodeCap(view:string,width:number,height:number,maxNodes=24){const mobile=width<600;return Math.max(3,Math.min(maxNodes,view==='chord'?(mobile?Math.min(width<350?8:10,Math.floor((height-60)/27)):Math.min(22,Math.floor((height-70)/25))):view==='sankey'?Math.max(6,Math.floor((height-90)/30)):(mobile?10:24)));}

export function shortName(code:string,name:string){const names:Record<string,string>={CHN:'中国大陆',AUS:'澳大利亚',SCH:'申根',USA:'美国',GBR:'英国',HKG:'中国香港',MAC:'中国澳门',TWN:'中国台湾'};return unknown(code)?'未分配':names[code]||name;}

/** Regional sums keep every international fee, including payments within a region. */
export function aggregateRegions(a:AnalysisResult):AnalysisResult{
 const byCode=new Map(a.entities.map(e=>[e.code,e])),regions=['亚洲','欧洲','非洲','美洲','大洋洲','其他地区'];
 const regionCode=(code:string)=>unknown(code)?'UNK':'REG_'+(regions.indexOf(byCode.get(code)?.region||'其他地区')<0?5:regions.indexOf(byCode.get(code)?.region||'其他地区'));
 const visibleCodes=new Set(a.edges.flatMap(e=>[e.origin,e.destination]));
 const entities=regions.map((name,i)=>({code:'REG_'+i,name,region:name,kind:'aggregate',members:a.entities.filter(e=>visibleCodes.has(e.code)&&!unknown(e.code)&&e.region===name).map(e=>e.code)}));
 const names=new Map(entities.map(e=>[e.code,e.name]));names.set('UNK','国籍未分配');
 const grouped=new Map<string,AnalysisEdge>();
 for(const e of a.edges){const origin=regionCode(e.origin),destination=regionCode(e.destination),key=origin+'|'+destination;
  if(!grouped.has(key))grouped.set(key,{...e,id:key,origin,destination,amount:0,count:0,ids:[],groups:{}});
  const out=grouped.get(key)!;out.amount+=e.amount;out.count+=e.count;out.ids.push(...e.ids);for(const [g,v] of Object.entries(e.groups))out.groups[g as keyof typeof out.groups]=(out.groups[g as keyof typeof out.groups]||0)+(v||0);
 }
 const edges=[...grouped.values()],codes=[...new Set(edges.flatMap(e=>[e.origin,e.destination]))];
 const nodes=codes.map(code=>{const incomingEdges=edges.filter(e=>e.destination===code),outgoingEdges=edges.filter(e=>e.origin===code),incoming=incomingEdges.reduce((n,e)=>n+e.amount,0),outgoing=outgoingEdges.reduce((n,e)=>n+e.amount,0);return {code,name:names.get(code)||code,incoming,outgoing,net:incomingEdges.length&&outgoingEdges.length?incoming-outgoing:null,incomingKnown:!!incomingEdges.length,outgoingKnown:!!outgoingEdges.length,unallocated:incomingEdges.filter(e=>e.origin==='UNK').reduce((n,e)=>n+e.amount,0),selected:true};});
 const previousNodes:AnalysisNode[]=[];
 for(const old of a.previousNodes||[]){const code=regionCode(old.code);let target=previousNodes.find(n=>n.code===code);if(!target){target={...old,code,name:names.get(code)||code,incoming:0,outgoing:0,unallocated:0,incomingKnown:false,outgoingKnown:false,net:null};previousNodes.push(target);}target.incoming+=old.incoming;target.outgoing+=old.outgoing;target.unallocated+=old.unallocated;target.incomingKnown ||= old.incomingKnown;target.outgoingKnown ||= old.outgoingKnown;target.net=target.incomingKnown&&target.outgoingKnown?target.incoming-target.outgoing:null;}
 return {...a,edges,nodes,entities:[...entities,{code:'UNK',name:'国籍未分配',region:'未分配',kind:'unallocated',members:['UNK']}],countryTotals:nodes,previousNodes};
}
