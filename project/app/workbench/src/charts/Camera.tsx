import {useCallback,useEffect,useRef,useState,type PointerEvent as ReactPointerEvent} from 'react';
type Pose={scale:number;x:number;y:number};
const fit:Pose={scale:1,x:0,y:0};
const clamp=(v:number,max:number)=>Math.max(-max,Math.min(v,max));

export function useCamera(width:number,height:number,resetKey:string) {
 const frame=useRef<HTMLDivElement>(null),[pose,setPose]=useState(fit),[dragging,setDragging]=useState(false);
 const current=useRef(fit),drag=useRef<{id:number;x:number;y:number;pose:Pose;moved:boolean}|null>(null),skipClick=useRef(false);
 const position=useCallback((next:Pose)=>{
  const limit=next.scale-1;
  const bounded={...next,x:clamp(next.x,width*limit/2),y:clamp(next.y,height*limit/2)};
  current.current=bounded;setPose(bounded);
 },[width,height]);
 const reset=useCallback(()=>position(fit),[position]);
 const zoom=useCallback((factor:number,x=0,y=0)=>{
  const p=current.current,scale=Math.max(1,Math.min(4,Math.round(p.scale*factor*100)/100)),r=scale/p.scale;
  position({scale,x:x-(x-p.x)*r,y:y-(y-p.y)*r});
 },[position]);
 useEffect(()=>{current.current=fit;setPose(fit);},[resetKey]);
 useEffect(()=>{position(current.current);},[position]);
 useEffect(()=>{
  const node=frame.current;if(!node)return;
  const wheel=(e:WheelEvent)=>{
   if(!e.altKey)return;
   e.preventDefault();
   const rect=node.getBoundingClientRect();
   zoom(Math.exp(-Math.max(-150,Math.min(150,e.deltaY))*.003),e.clientX-rect.left-rect.width/2,e.clientY-rect.top-rect.height/2);
  };
  node.addEventListener('wheel',wheel,{passive:false});
  return()=>node.removeEventListener('wheel',wheel);
 },[zoom]);
 const pointerDown=(e:ReactPointerEvent<HTMLDivElement>)=>{
  skipClick.current=false;
  if(e.button!==0||!e.isPrimary||current.current.scale<=1)return;
  drag.current={id:e.pointerId,x:e.clientX,y:e.clientY,pose:current.current,moved:false};
 };
 const pointerMove=(e:ReactPointerEvent<HTMLDivElement>)=>{
  const p=drag.current;if(!p||p.id!==e.pointerId)return;
  const dx=e.clientX-p.x,dy=e.clientY-p.y;
  if(!p.moved&&Math.hypot(dx,dy)<5)return;
  if(!p.moved){p.moved=true;e.currentTarget.setPointerCapture(e.pointerId);setDragging(true);}
  position({...p.pose,x:p.pose.x+dx,y:p.pose.y+dy});
 };
 const pointerEnd=(e:ReactPointerEvent<HTMLDivElement>)=>{
  const p=drag.current;if(!p||p.id!==e.pointerId)return;
  skipClick.current=p.moved;drag.current=null;setDragging(false);
  if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);
 };
 return {pose,dragging,zoom,reset,position,current,frame,pointerDown,pointerMove,pointerEnd,skipClick};
}
