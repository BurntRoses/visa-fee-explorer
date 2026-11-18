import {useEffect,useMemo,useState} from 'react';
import type {ChartProps} from '../types';
import {ChordPlot} from './Chord';
import {SinglePlot} from './Single';
import {SankeyPlot} from './Sankey';
import {ComparePlot} from './Compare';
import {HeatmapPlot} from './Heatmap';
import {globalSankeyGraph,globalHeatmapGraph} from './bilateral';
import {Tooltip,type ChartEvents,type MarkHint} from './common';
import {aggregateRegions,countryColor,graphData,money,nameMap,OTHER,singleCountryEdges,singleCountryGraph,unknown,viewNodeCap} from './helpers';
import './charts.css';
export function WorkbenchChart(originalProps:ChartProps){
 const regional=originalProps.state.spatialScale==='region'&&originalProps.state.view!=='single',analysis=useMemo(()=>regional?aggregateRegions(originalProps.analysis):originalProps.analysis,[regional,originalProps.analysis]),props=regional?{...originalProps,analysis,state:{...originalProps.state,countries:analysis.nodes.map(n=>n.code)}}:originalProps;
 const [hover,setHover]=useState<string|null>(null),[locked,setLocked]=useState<string|null>(null),[hint,setHint]=useState<MarkHint|null>(null),[members,setMembers]=useState<string[]|null>(null),[memberQuery,setMemberQuery]=useState(''),highlight=hover||locked;
 useEffect(()=>{setHover(null);setLocked(null);setHint(null);setMembers(null);},[props.state.view,props.state.year,props.state.flowScope,props.state.countries.join('|'),props.state.visaGroups.join('|'),props.state.focusCountry,props.state.singleMode,props.state.spatialScale]);
 const Plot=props.state.view==='chord'?ChordPlot:props.state.view==='single'?SinglePlot:props.state.view==='sankey'?SankeyPlot:props.state.view==='compare'?ComparePlot:HeatmapPlot;
 const graph=useMemo(()=>props.state.view==='single'?singleCountryGraph(props.analysis,props.state,props.width,props.height):props.state.view==='sankey'?globalSankeyGraph(props.analysis,props.state,props.width,props.height):props.state.view==='heatmap'?globalHeatmapGraph(props.analysis,props.state,props.width,props.height):graphData(props.analysis,{...props.state,maxNodes:viewNodeCap(props.state.view,props.width,props.height,props.state.maxNodes)},props.width),[props.analysis,props.state,props.width,props.height]);
 const expand=(codes?:string[])=>{setMembers([...new Set(codes?.length?codes:graph.nodes.find(n=>n.code===OTHER)?.members||[])]);setMemberQuery('');setHint(null);};
 const focus=(code:string)=>{if(code===OTHER){expand();return;}setLocked(old=>old===code?null:code);setHover(null);if(unknown(code))setHint({title:'国籍未分配',detail:'这部分已计入收款政府，付款来源国籍尚未识别。',color:countryColor(code)});};
 const events:ChartEvents={highlight,selected:locked,setHighlight:setHover,hint:setHint,focus,route:props.onRoute,expand};
 const names=nameMap(originalProps.analysis),visibleEdges=props.state.view==='single'?singleCountryEdges(originalProps.analysis,props.state):originalProps.analysis.edges,memberRows=(members||[]).map(code=>({code,name:names.get(code)||code,incomingKnown:visibleEdges.some(e=>e.destination===code),outgoingKnown:visibleEdges.some(e=>e.origin===code),incoming:visibleEdges.filter(e=>e.destination===code).reduce((v,e)=>v+e.amount,0),outgoing:visibleEdges.filter(e=>e.origin===code).reduce((v,e)=>v+e.amount,0)})).sort((a,b)=>b.incoming+b.outgoing-a.incoming-a.outgoing).filter(n=>[n.name,n.code].join(' ').toLowerCase().includes(memberQuery.toLowerCase()));
 return <div className={'visa-visualization'+(props.reducedMotion?' reduce-motion':'')+(props.state.motionMode==='presentation'?' presentation':'')} data-view={props.state.view} data-graph-total={graph.displayed} data-analysis-total={props.analysis.total} onKeyDown={e=>{if(e.key==='Escape'){setLocked(null);setHover(null);setHint(null);}}}>
  <Plot {...props} graph={graph} width={Math.max(260,props.width)} height={Math.max(260,props.height)} events={events}/>
  {locked&&<div className="viz-selection"><span style={{color:countryColor(locked)}}>●</span><strong>{names.get(locked)||locked}</strong>{!unknown(locked)&&!locked.startsWith('REG_')&&!(props.state.view==='single'&&props.state.focusCountry===locked)&&<button onClick={()=>props.onFocus(locked)}>单国查看</button>}<button aria-label="清除国家高亮" onClick={()=>{setLocked(null);setHover(null);setHint(null);}}>×</button></div>}
  {(props.state.view==='chord'||props.state.view==='single')&&(graph.others>0||graph.omitted>.01)&&<div className="viz-aggregation-note">{graph.others>0&&<button onClick={()=>expand()}>已合并 {graph.others} 个国家／地区，查看成员</button>}{graph.omitted>.01&&<span>当前显示 {money(graph.displayed)}，另有 {money(graph.omitted)} 低于显示门槛</span>}</div>}
  {members&&<section className="viz-members-panel" role="dialog" aria-label="聚合国家成员" onKeyDown={e=>{if(e.key==='Escape')setMembers(null);}}><header><div><strong>聚合中的 {members.length} 个国家／地区</strong><small>当前分析范围 · 人民币等值</small></div><button aria-label="关闭国家成员" onClick={()=>setMembers(null)}>×</button></header><input autoFocus aria-label="搜索聚合成员" placeholder="搜索国家名称或代码" value={memberQuery} onChange={e=>setMemberQuery(e.target.value)}/><div className="viz-member-heading"><span>国家／地区</span><span>收到</span><span>付出</span></div><div className="viz-member-list">{memberRows.map(n=><button key={n.code} onClick={()=>{setMembers(null);focus(n.code);}} aria-label={`聚焦${n.name}，收到${n.incomingKnown?money(n.incoming):'未识别'}，付出${n.outgoingKnown?money(n.outgoing):'未识别'}`}><span><i style={{background:countryColor(n.code)}}/>{n.name}</span><b>{n.incomingKnown?money(n.incoming):'未识别'}</b><b>{n.outgoingKnown?money(n.outgoing):'未识别'}</b></button>)}{!memberRows.length&&<p>没有匹配的国家</p>}</div></section>}
  <Tooltip hint={hint}/>
 </div>;
}
export default WorkbenchChart;
