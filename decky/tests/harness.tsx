// This renders the production App with native-control shims, not Steam's focus engine.
import { createRoot } from 'react-dom/client';
import plugin from '../src/index';
window.bridge=async(name,args)=>{
 const response=await fetch('/rpc',{method:'POST',body:JSON.stringify({name,args})});
 if(!response.ok)throw Error('Bridge unavailable');
 return response.json();
};
createRoot(document.getElementById('root')!).render((plugin as unknown as ()=>{content:React.ReactNode})().content);
