import {createRoot} from 'react-dom/client';
import Workbench from './Workbench';
import {loadIndex} from './data';
loadIndex().then(index=>createRoot(document.getElementById('root')!).render(<Workbench index={index}/>)).catch(error=>{const root=document.getElementById('root')!;root.replaceChildren();const h=document.createElement('h2');h.textContent='工作台未能载入';const p=document.createElement('p');p.textContent=String(error.message);const b=document.createElement('button');b.textContent='重新载入';b.onclick=()=>location.reload();root.style.cssText='padding:40px;font:14px system-ui;color:#253a46';root.append(h,p,b);});
