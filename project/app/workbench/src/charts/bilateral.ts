import type {AnalysisResult,WorkbenchState} from '../types';
import {label,nameMap,OTHER,unknown,type GraphData,type GraphEdge,type GraphNode} from './helpers';

/** The two sides of a payment matrix have different populations and rankings. */
export interface BilateralGraph extends GraphData {
 sources:GraphNode[];
 targets:GraphNode[];
 sourceHidden:string[];
 targetHidden:string[];
}
export function bilateralGraph(a:AnalysisResult,s:WorkbenchState,options:{sourceCap:number;targetCap:number;includeFree?:boolean}):BilateralGraph{
 const names=nameMap(a),input=a.edges.filter(e=>e.amount>=(options.includeFree?0:s.minAmount||0)&&(e.amount>0||options.includeFree||s.showFree));
 const weights=(side:'origin'|'destination')=>{
  const out=new Map<string,number>();
  for(const edge of input)out.set(edge[side],(out.get(edge[side])||0)+edge.amount);
  return out;
 };
 const axes=(totals:Map<string,number>,limit:number)=>{
  const ranked=[...totals.keys()].sort((x,y)=>(totals.get(y)||0)-(totals.get(x)||0)||x.localeCompare(y));
  const unknowns=ranked.filter(unknown),named=ranked.filter(code=>!unknown(code)),cap=Math.max(3,limit);
  const namedCap=Math.max(1,cap-unknowns.length-(ranked.length>cap?1:0));
  const keep=named.slice(0,namedCap),pinned=s.countries.length<=5?s.countries.filter(code=>named.includes(code)):[];
  for(const code of pinned)if(!keep.includes(code)){
   const removable=keep.map(c=>!pinned.includes(c)).lastIndexOf(true);
   if(keep.length>=namedCap&&removable>=0)keep.splice(removable,1);
   if(keep.length<namedCap)keep.push(code);
  }
  keep.sort((x,y)=>(totals.get(y)||0)-(totals.get(x)||0)||x.localeCompare(y));
  const hidden=named.filter(code=>!keep.includes(code));
  return {codes:[...keep,...unknowns,...(hidden.length?[OTHER]:[])],hidden,keep:new Set([...keep,...unknowns])};
 };
 const sourceTotals=weights('origin'),targetTotals=weights('destination'),source=axes(sourceTotals,options.sourceCap),target=axes(targetTotals,options.targetCap);
 const combined=new Map<string,GraphEdge>();
 for(const edge of input){
  const origin=source.keep.has(edge.origin)?edge.origin:OTHER,destination=target.keep.has(edge.destination)?edge.destination:OTHER,key=origin+'|'+destination;
  if(!combined.has(key))combined.set(key,{...edge,id:key,origin,destination,amount:0,count:0,ids:[],groups:{},originals:[]});
  const out=combined.get(key)!;out.amount+=edge.amount;out.count+=edge.count;out.ids.push(...edge.ids);out.originals.push(edge);
  for(const [group,value]of Object.entries(edge.groups||{}))out.groups[group as keyof typeof out.groups]=(out.groups[group as keyof typeof out.groups]||0)+(value||0);
 }
 const edges=[...combined.values()],node=(code:string,side:'source'|'target'):GraphNode=>{
  const relevant=edges.filter(e=>(side==='source'?e.origin:e.destination)===code),amount=relevant.reduce((sum,e)=>sum+e.amount,0),members=code===OTHER?(side==='source'?source.hidden:target.hidden):(a.entities.find(e=>e.code===code)?.members||[code]);
  return {code,name:code===OTHER?`其余 ${members.length} 国`:label(code,names),amount,incoming:side==='target'?amount:0,outgoing:side==='source'?amount:0,incomingKnown:side==='target',outgoingKnown:side==='source',members};
 };
 const sources=source.codes.map(code=>node(code,'source')),targets=target.codes.map(code=>node(code,'target')),allCodes=[...new Set([...source.codes,...target.codes])];
 const hidden=[...new Set([...source.hidden,...target.hidden])],nodes=allCodes.map(code=>{
  const incoming=targets.find(n=>n.code===code),outgoing=sources.find(n=>n.code===code);
  return {code,name:code===OTHER?`其余 ${hidden.length} 国`:label(code,names),amount:(incoming?.amount||0)+(outgoing?.amount||0),incoming:incoming?.amount||0,outgoing:outgoing?.amount||0,incomingKnown:!!incoming,outgoingKnown:!!outgoing,members:code===OTHER?hidden:(a.entities.find(e=>e.code===code)?.members||[code])};
 });
 const displayed=edges.reduce((sum,e)=>sum+e.amount,0);
 return {sources,targets,nodes,edges,displayed,omitted:Math.max(0,a.total-displayed),others:hidden.length,sourceHidden:source.hidden,targetHidden:target.hidden};
}
export function globalSankeyGraph(a:AnalysisResult,s:WorkbenchState,width:number,height:number){
 if(s.spatialScale==='region')return bilateralGraph(a,s,{sourceCap:8,targetCap:8});
 const cap=Math.max(4,Math.min(width<600?11:19,Math.floor((height-(width<600?120:105))/(width<600?33:31))));
 return bilateralGraph(a,s,{sourceCap:cap,targetCap:cap});
}
export function globalHeatmapGraph(a:AnalysisResult,s:WorkbenchState,width:number,height:number){
 if(s.spatialScale==='region')return bilateralGraph(a,s,{sourceCap:8,targetCap:8,includeFree:true});
 const mobile=width<600,left=mobile?83:139,right=mobile?39:51,available=Math.max(120,width-left-right);
 const columns=Math.max(3,Math.min(25,Math.floor(available/(mobile?34:43)))),rows=Math.max(4,Math.min(32,Math.floor((height-(mobile?179:157))/(mobile?26:24))));
 return bilateralGraph(a,s,{sourceCap:rows,targetCap:columns,includeFree:true});
}
export const bilateralMembers=(origin:GraphNode,destination:GraphNode)=>[...new Set([...(origin.code===OTHER||origin.code.startsWith('REG_')?origin.members:[]),...(destination.code===OTHER||destination.code.startsWith('REG_')?destination.members:[])])];
