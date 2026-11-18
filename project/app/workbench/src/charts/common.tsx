import {useEffect,useId,useRef,useState, type CSSProperties, type ReactNode} from 'react';
import {interpolateString} from 'd3';
import type {ChartProps} from '../types';
import {money,OTHER} from './helpers';
export interface MarkHint {title:string;amount?:number;detail?:string;color?:string;}
export interface ChartEvents {highlight:string|null;selected:string|null;setHighlight:(code:string|null)=>void;hint:(value:MarkHint|null)=>void;focus:(code:string)=>void;route:(origin:string,destination:string)=>void;expand:(members?:string[])=>void;}
export type PlotProps=ChartProps&{events:ChartEvents};
const pathCommandSize:Record<string,number>={M:2,L:2,H:1,V:1,C:6,S:4,Q:4,T:2,A:7,Z:0};
function morphSignature(d:string):string|null{
 const tokens=d.match(/[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?/g);if(!tokens?.length)return null;
 const parts:string[]=[];let i=0;
 while(i<tokens.length){const command=tokens[i++],size=pathCommandSize[command.toUpperCase()];if(size===undefined)return null;const start=i;while(i<tokens.length&&!/^[a-zA-Z]$/.test(tokens[i])){if(!Number.isFinite(Number(tokens[i++])))return null;}const count=i-start;if(size===0?count!==0:count===0||count%size!==0)return null;
  let flags='';if(command.toUpperCase()==='A')for(let j=start;j<i;j+=7){const large=Number(tokens[j+3]),sweep=Number(tokens[j+4]);if(![0,1].includes(large)||![0,1].includes(sweep))return null;flags+=`${large}${sweep}`;}
  parts.push(`${command}:${count}:${flags}`);
 }
 return parts.join('|');
}
export function AnimatedPath({d,reduced=false,...props}:{d:string;reduced?:boolean;[key:string]:any}){
 const ref=useRef<SVGPathElement>(null),current=useRef(d),frame=useRef<number>(0),fade=useRef<Animation|null>(null),mounted=useRef(false);
 useEffect(()=>{
  cancelAnimationFrame(frame.current);fade.current?.cancel();fade.current=null;const node=ref.current;if(!node)return;
  const cleanup=()=>{cancelAnimationFrame(frame.current);fade.current?.cancel();fade.current=null;};
  if(!mounted.current||reduced){node.setAttribute('d',d);current.current=d;mounted.current=true;return cleanup;}
  if(current.current===d)return cleanup;
  const from=current.current,signature=morphSignature(from);
  // Numeric interpolation is safe only when commands, segment counts and arc flags agree.
  if(!signature||signature!==morphSignature(d)){
   node.setAttribute('d',d);current.current=d;
   fade.current=node.animate([{opacity:0},{opacity:Number(getComputedStyle(node).opacity)}],{duration:300,easing:'ease-out'});
   return cleanup;
  }
  const mix=interpolateString(from,d),start=performance.now();const tick=(time:number)=>{const t=Math.min(1,(time-start)/300),p=1-Math.pow(1-t,3),next=t===1?d:mix(p);node.setAttribute('d',next);current.current=next;if(t<1)frame.current=requestAnimationFrame(tick);};frame.current=requestAnimationFrame(tick);return cleanup;
 },[d,reduced]);
 return <path ref={ref} d={current.current} {...props}/>;
}
export function EmptyPlot({title='当前范围没有可绘制的费用流',detail='更改国家或范围，查看已有费用关系。'}:{title?:string;detail?:string}){return <div className="viz-empty"><span aria-hidden="true">↗</span><strong>{title}</strong><p>{detail}</p></div>;}
export function activate(e:React.KeyboardEvent,action:()=>void){if(e.key==='Enter'||e.key===' '){e.preventDefault();action();}}
export function Tooltip({hint}:{hint:MarkHint|null}){return <div className={'viz-tooltip'+(hint?' visible':'')} role="status" aria-live="polite">{hint&&<><span className="viz-tooltip-dot" style={{background:hint.color||'#1b3446'}}/><div><strong>{hint.title}</strong>{hint.detail&&<small>{hint.detail}</small>}</div>{hint.amount!==undefined&&<b>{money(hint.amount)}</b>}</>}</div>;}
export function Mark({children,title,amount,detail,color,code,origin,destination,members,events,className='',onClick,...rest}:{children:ReactNode;title:string;amount?:number;detail?:string;color?:string;code?:string;origin?:string;destination?:string;members?:string[];events:ChartEvents;className?:string;onClick?:()=>void;[key:string]:any}){
 const show=()=>{events.hint({title,amount,detail,color});if(code||origin)events.setHighlight(code||origin!);};const clear=()=>{events.hint(null);events.setHighlight(null);};const click=onClick||(()=>code?code===OTHER||code.startsWith('REG_')?events.expand(members):events.focus(code):origin&&destination?origin===OTHER||destination===OTHER||origin.startsWith('REG_')||destination.startsWith('REG_')?events.expand(members):events.route(origin,destination):undefined);
 return <g role="button" tabIndex={0} data-chart-interactive="true" className={'viz-mark '+className} data-selected={code&&events.selected===code?'true':undefined} aria-pressed={code?events.selected===code:undefined} aria-label={[title,amount===undefined?'':money(amount),detail].filter(Boolean).join('，')} onPointerEnter={show} onPointerLeave={clear} onFocus={show} onBlur={clear} onClick={click} onKeyDown={e=>activate(e,click)} {...rest}>{children}<title>{[title,amount===undefined?'':money(amount),detail].filter(Boolean).join(' · ')}</title></g>;
}
export function FlowMotion({d,clipD,color,origin,destination,reduced,enabled,active=false}:{d:string;clipD:string;color:string;origin:string;destination:string;reduced:boolean;enabled:boolean;active?:boolean}){
 const id='flow-'+useId().replace(/:/g,'');
 if(!enabled||reduced||!d||!clipD)return null;
 // Normalized lengths keep a single short streak moving source → target on every route.
 // Stable phases prevent the whole diagram from flashing in unison.
 const seed=[...origin+'|'+destination].reduce((n,c)=>(n*31+c.charCodeAt(0))>>>0,0),duration=5.4+(seed%1800)/1000;
 const style={'--flow-duration':`${duration}s`,'--flow-delay':`${-(seed%5400)/1000}s`} as CSSProperties;
 return <g className="viz-flow-motion" data-origin={origin} data-destination={destination} data-active={active} style={style} pointerEvents="none" aria-hidden="true">
  <defs><clipPath id={id} clipPathUnits="userSpaceOnUse"><path d={clipD}/></clipPath></defs>
  <g clipPath={`url(#${id})`}>
   <path d={d} pathLength="100" className="viz-flow-trace viz-flow-tail" stroke={color}/>
   <path d={d} pathLength="100" className="viz-flow-trace viz-flow-body" stroke={color}/>
   <path d={d} pathLength="100" className="viz-flow-trace viz-flow-tip" stroke="white"/>
  </g>
 </g>;
}
export function PlotFrame({width,height,title,description,children,view}:{width:number;height:number;title:string;description:string;children:ReactNode;view:string;resetKey?:string}){
 return <div className="viz-svg-frame" style={{width:'100%',height:'100%'}} data-chart={view} data-camera="fit">
  <svg className="viz-main-svg" width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} role="group" aria-label={title}>
   <title>{title}</title><desc>{description}</desc><g data-plot-content="true">{children}</g>
  </svg>
 </div>;
}
