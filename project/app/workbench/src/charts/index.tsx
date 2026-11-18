import {useEffect,useMemo,useState} from 'react';
import {Minus,Plus,Scan} from 'lucide-react';
import type {ChartProps} from '../types';
import {ChordPlot} from './Chord';
import {SinglePlot} from './Single';
import {SankeyPlot} from './Sankey';
import {ComparePlot,type CompareOrder} from './Compare';
import {HeatmapPlot} from './Heatmap';
import {globalSankeyGraph,globalHeatmapGraph,type BilateralGraph} from './bilateral';
import {useCamera} from './Camera';
import {Tooltip,type ChartEvents,type MarkHint} from './common';
import {aggregateRegions,countryColor,graphData,money,nameMap,OTHER,singleCountryGraph,unknown,viewNodeCap} from './helpers';
import './charts.css';

export function WorkbenchChart(originalProps:ChartProps&{compareOrder?:CompareOrder}){
 const regional=originalProps.state.spatialScale==='region'&&originalProps.state.view!=='single';
 const analysis=useMemo(()=>regional?aggregateRegions(originalProps.analysis):originalProps.analysis,[regional,originalProps.analysis]);
 const props=regional?{...originalProps,analysis,state:{...originalProps.state,countries:analysis.nodes.map(n=>n.code)}}:originalProps;
 const width=Math.max(260,props.width),height=Math.max(235,props.height-92),{view,year,flowScope,focusCountry,singleMode,spatialScale}=props.state;
 const selection=props.state.countries.join('|'),resetKey=[view,flowScope,selection,focusCountry,singleMode,spatialScale].join(':');
 const camera=useCamera(width,height,resetKey);
 const [hover,setHover]=useState<string|null>(null),[locked,setLocked]=useState<string|null>(null),[hint,setHint]=useState<MarkHint|null>(null);
 useEffect(()=>{setHover(null);setLocked(null);setHint(null);},[resetKey,year]);
 const graph=useMemo(()=>view==='single'?singleCountryGraph(props.analysis,props.state,width,height):view==='sankey'?globalSankeyGraph(props.analysis,props.state,width,height):view==='heatmap'?globalHeatmapGraph(props.analysis,props.state,width,height):graphData(props.analysis,{...props.state,maxNodes:viewNodeCap(view,width,height,props.state.maxNodes)},width),[props.analysis,view,singleMode,spatialScale,selection,focusCountry,props.state.maxNodes,props.state.minAmount,props.state.showFree,width,height]);
 const clear=()=>{setLocked(null);setHover(null);setHint(null);};
 const expand=(codes?:string[])=>{setHint(null);props.onMembers([...new Set(codes?.length?codes:graph.nodes.find(n=>n.code===OTHER)?.members||[])]);};
 const focus=(code:string)=>{if(code===OTHER){expand();return;}setLocked(old=>old===code?null:code);setHover(null);if(unknown(code))setHint({title:'国籍未分配',detail:'金额已计入收款政府；付款人的国籍尚未识别。',color:countryColor(code)});};
 const events:ChartEvents={highlight:camera.dragging?null:hover||locked,selected:locked,setHighlight:setHover,hint:setHint,focus,route:props.onRoute,expand};
 const names=useMemo(()=>nameMap(originalProps.analysis),[originalProps.analysis]);
 const Plot=view==='chord'?ChordPlot:view==='single'?SinglePlot:view==='sankey'?SankeyPlot:ComparePlot;
 const {scale,x,y}=camera.pose;
 return <div className={'visa-visualization'+(props.reducedMotion?' reduce-motion':'')+(props.state.motionMode==='presentation'?' presentation':'')} data-view={view} data-graph-total={graph.displayed} data-analysis-total={props.analysis.total} onKeyDown={e=>{if(e.key==='Escape'&&locked){e.preventDefault();clear();}}}>
  <div className="plot-viewport" ref={camera.frame} data-scale={scale} data-x={x} data-y={y}
   data-dragging={camera.dragging} tabIndex={0} aria-label="图形画布，按加减键缩放，方向键移动，0 恢复"
   onPointerDown={camera.pointerDown} onPointerMove={camera.pointerMove} onPointerUp={camera.pointerEnd} onPointerCancel={camera.pointerEnd} onLostPointerCapture={camera.pointerEnd}
   onClickCapture={e=>{if(camera.skipClick.current){camera.skipClick.current=false;e.preventDefault();e.stopPropagation();}}}
   onDoubleClick={e=>{if(!(e.target as Element).closest('[data-chart-interactive]'))camera.reset();}}
   onKeyDown={e=>{
    if(e.target!==e.currentTarget)return;
    if(e.key==='+'||e.key==='='){e.preventDefault();camera.zoom(1.25);}
    else if(e.key==='-'){e.preventDefault();camera.zoom(.8);}
    else if(e.key==='0'){e.preventDefault();camera.reset();}
    else if(scale>1&&['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();camera.position({scale,x:x+(e.key==='ArrowLeft'?35:e.key==='ArrowRight'?-35:0),y:y+(e.key==='ArrowUp'?35:e.key==='ArrowDown'?-35:0)});}
   }}>
   <div className="plot-world" style={{transform:scale===1?undefined:`translate(${x}px,${y}px) scale(${scale})`}}>
    {view==='heatmap'?<HeatmapPlot {...props} graph={graph as BilateralGraph} width={width} height={height} events={events}/>
     :<Plot {...props} graph={graph} width={width} height={height} events={events} order={props.compareOrder}/>}
   </div>
  </div>
  <div className="plot-actions">
   <div className="plot-caption">
    {locked?<><span className="plot-locked" style={{color:countryColor(locked)}}>●</span><strong>{names.get(locked)||locked}</strong>{!unknown(locked)&&!locked.startsWith('REG_')&&!(view==='single'&&focusCountry===locked)&&<button onClick={()=>props.onFocus(locked)}>单国查看</button>}<button aria-label="清除国家高亮" onClick={clear}>×</button></>
    :view!=='compare'&&graph.others>0?<button onClick={()=>expand()}>查看其余 {graph.others} 项</button>:<span>{scale>1?'拖动图形查看细节':'可放大查看路线'}</span>}
   </div>
   <div className="viz-zoom-tools" role="group" aria-label="画布缩放">
    <button aria-label="缩小" disabled={scale<=1} onClick={()=>camera.zoom(.8)}><Minus size={16}/></button>
    <output aria-label="当前缩放">{Math.round(scale*100)}%</output>
    <button aria-label="放大" disabled={scale>=4} onClick={()=>camera.zoom(1.25)}><Plus size={16}/></button>
    <button aria-label="恢复适配" disabled={scale===1} onClick={camera.reset}><Scan size={15}/></button>
   </div>
  </div>
  <Tooltip hint={camera.dragging?null:hint}/>
 </div>;
}
export default WorkbenchChart;
