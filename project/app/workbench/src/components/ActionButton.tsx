import {useRef,useState,type ReactNode} from 'react';
import {Check,LoaderCircle,RotateCcw} from 'lucide-react';
export function ActionButton({children,onAction,className=''}:{children:ReactNode;onAction:()=>Promise<void>|void;className?:string}){
 const [status,setStatus]=useState<'idle'|'pending'|'done'|'error'>('idle'),busy=useRef(false);
 return <button className={'async-action '+className} disabled={status==='pending'} aria-busy={status==='pending'} onClick={async()=>{if(busy.current)return;busy.current=true;setStatus('pending');try{await new Promise(resolve=>setTimeout(resolve,0));await onAction();setStatus('done');}catch{setStatus('error');}finally{busy.current=false;}}}><span className="action-label">{children}</span><span className="action-status" aria-live="polite">{status==='pending'?<><LoaderCircle size={17}/>准备中</>:status==='done'?<><Check size={17}/>已导出</>:status==='error'?<><RotateCcw size={17}/>重试</>:null}</span></button>;
}
