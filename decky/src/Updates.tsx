import { useEffect, useRef, useState } from 'react';
import { ButtonItem, Navigation, PanelSection, PanelSectionRow } from '@decky/ui';
import { api, UpdateSuite } from './api';

export function Updates(){
  const [state,setState]=useState<UpdateSuite>({});
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const [approval,setApproval]=useState<{kind:string;token?:string;version?:string;downgrade?:boolean}>();
  const [url,setUrl]=useState('');
  const lock=useRef(false);
  const refresh=async()=>{const r=await api.getUpdates();if(r.error)throw Error(r.error);setState(r);};
  useEffect(()=>{let live=true;let pending=false;const load=()=>{if(pending)return;pending=true;void api.getUpdates().then(r=>{if(live){setState(r);if(r.error)setMessage(r.error);}}).catch(()=>{if(live)setMessage('Update helper unavailable.');}).finally(()=>{pending=false;});};load();const timer=setInterval(load,3000);return()=>{live=false;clearInterval(timer);};},[]);
  const run=async(action:()=>Promise<{error?:string;message?:string}>)=>{
    if(lock.current)return;lock.current=true;setBusy(true);setMessage('');
    try{const r=await action();setMessage(r.error||r.message||'Done.');await refresh();}catch(e){setMessage(e instanceof Error?e.message:'Update unavailable.');}
    finally{lock.current=false;setBusy(false);}
  };
  const button=(label:string,action:()=>void,disabled=false)=><PanelSectionRow key={label}><ButtonItem disabled={busy||disabled} onClick={action} layout="below">{label}</ButtonItem></PanelSectionRow>;
  const handoff=async(rollback:boolean,token:string)=>{
    const r=await api.pluginHandoff(token,rollback);if(r.error)return r;
    if(!r.url||!/^http:\/\/127\.0\.0\.1:\d+\/[A-Za-z0-9_-]+\/DeckPilot\.zip$/.test(r.url))throw Error('Invalid local installation link.');
    setUrl(r.url);
    try{await navigator.clipboard.writeText(r.url);}catch{
      const field=document.createElement('textarea');field.value=r.url;document.body.appendChild(field);field.select();const copied=document.execCommand?.('copy');field.remove();
      if(!copied)return {message:'Clipboard unavailable. Select and copy the local link below, then open Decky Settings → Developer → Install from URL.'};
    }
    try{Navigation.Navigate('/decky/settings/developer');}catch{return {message:'Link copied. Open Decky Settings → Developer → Install from URL.'};}
    return {message:'Link copied. In Decky, enable Developer mode once if needed, paste into Install from URL and approve. Link expires in 5 minutes. Decky confirms installation.'};
  };
  const working=!state.recovery_required&&['queued','working'].includes(state.operation?.status||'');
  const approve=()=>{const a=approval;if(!a)return;setApproval(undefined);void run(async()=>{
    if(a.kind==='preview'){const r=await api.setUpdateChannel('preview');if(r.error)return r;return api.checkUpdates();}
    if(a.kind==='app')return api.updateApp(a.token!,Boolean(a.downgrade));
    if(a.kind==='rollback')return api.rollbackUpdate();
    return handoff(a.kind==='plugin-rollback',a.token||'');
  });};
  return <PanelSection title="Updates">
    <PanelSectionRow><div><p>App {state.app_installed||'unknown'} · Plugin {state.plugin_installed||'unknown'}</p><p>{state.channel==='preview'?'Preview · approved development builds':'Stable · recommended'}</p><p>{state.message}</p>{!state.compatible&&<p>App and plugin versions differ. Update the app first, then the plugin. Profile changes are paused.</p>}{state.operation&&<p>{state.operation.message}</p>}{message&&<p role="status">{message}</p>}</div></PanelSectionRow>
    {approval?<>
      <PanelSectionRow><p>{approval.kind==='preview'?'Enable Preview? Development builds may have bugs. Nothing installs automatically.':approval.kind==='app'?`Install app ${approval.version}? ${approval.downgrade?'This is a downgrade. ':''}The app restarts; preferences, saves and game backups are kept. A rollback snapshot is saved.`:approval.kind==='rollback'?'Restore the previous app? Game files and preferences are kept. Match the plugin separately using its rollback button.':approval.kind==='plugin-rollback'?'Restore the saved plugin through Decky? Decky will ask for installation approval.':'Prepare the matching plugin? A rollback snapshot is saved. Decky will ask for installation approval.'}</p></PanelSectionRow>
      {button('Confirm',approve)}{button('Cancel',()=>setApproval(undefined))}
    </>:<>
      {button('Check for Updates',()=>void run(api.checkUpdates),working)}
      {state.channel==='preview'?button('Use Stable',()=>void run(async()=>{const r=await api.setUpdateChannel('stable');if(r.error)return r;return api.checkUpdates();}),working):button('Enable Preview',()=>setApproval({kind:'preview'}),working)}
      {state.available&&<PanelSectionRow><p>Verified {state.version}<br/>Commit {state.commit?.slice(0,12)}</p></PanelSectionRow>}
      {state.available&&state.app_needed&&button('Update App',()=>setApproval({kind:'app',token:state.token,version:state.version,downgrade:state.downgrade}),working)}
      {state.available&&state.plugin_needed&&button('Install Plugin in Decky',()=>setApproval({kind:'plugin',token:state.token,version:state.version}),Boolean(state.app_first)||working)}
      {state.app_rollback&&button(state.recovery_required?'Recover Interrupted Update':'Restore Previous App',()=>setApproval({kind:'rollback'}),working)}
      {state.plugin_rollback&&button('Restore Previous Plugin',()=>setApproval({kind:'plugin-rollback'}),working)}
    </>}
    {url&&<PanelSectionRow><div><p>Paste in Decky → Settings → Developer → Install from URL, then approve. No PC or file transfer needed.</p><textarea aria-label="Local plugin installation link" readOnly value={url} style={{width:'100%',height:90}}/></div></PanelSectionRow>}
    <PanelSectionRow><p className="dp-small">Only approved builds from goddenator/DeckPilot-TV. Checks never install updates. Plugin installation and rollback use Decky’s confirmation; no private installer APIs.</p></PanelSectionRow>
  </PanelSection>;
}
