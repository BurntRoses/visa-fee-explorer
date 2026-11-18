import {createRoot} from 'react-dom/client';
import Workbench from './Workbench';
import {hydrateState,loadIndex,loadYear,withYearRows} from './data';

function stylesReady(){
 const link=document.getElementById('workspace-style') as HTMLLinkElement|null;
 if(!link||link.media==='all')return Promise.resolve();
 return new Promise<void>((resolve,reject)=>{
  const timer=setTimeout(()=>reject(new Error('样式暂时无法读取')),20000);
  link.addEventListener('load',()=>{clearTimeout(timer);link.media='all';resolve();},{once:true});
  link.addEventListener('error',()=>{clearTimeout(timer);reject(new Error('样式暂时无法读取'));},{once:true});
 });
}
async function start(){
 const style=stylesReady();
 const [index]=await Promise.all([loadIndex(),style]),state=hydrateState(index);
 const requested=state.year===index.initialYear?index:withYearRows(index,await loadYear(index,state.year));
 createRoot(document.getElementById('root')!).render(<Workbench index={requested}/>);
}
start().catch(()=>{(window as Window&{showBootError?:()=>void}).showBootError?.();});
