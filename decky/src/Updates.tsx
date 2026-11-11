import { useEffect, useRef, useState } from 'react';
import { ButtonItem, Navigation, PanelSection, PanelSectionRow } from '@decky/ui';
import { api, Result, UpdateSuite } from './api';
import { readUpdateSession, saveUpdateSession, UpdateSession } from './updateSession';

export function Updates(){
  const [state,setState]=useState<UpdateSuite>({});
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const [approval,setApproval]=useState<{kind:string;token?:string;version?:string;downgrade?:boolean}>();
  const [url,setUrl]=useState('');
  const lock=useRef(false);
  const mounted=useRef(true);
  const revision=useRef(0);
  const preparing=useRef(false);
  const [session,setSession]=useState<UpdateSession|undefined>(readUpdateSession);
  const [advanced,setAdvanced]=useState(false);
  const [prepared,setPrepared]=useState(false);
  const sessionRef=useRef(session);sessionRef.current=session;
  const remember=(value?:UpdateSession)=>{saveUpdateSession(value);setSession(value);};
  const refresh=async()=>{const r=await api.getUpdates();if(r.error||r.ok===false)throw Error(r.error||'Update status unavailable.');if(mounted.current)setState(r);};
  useEffect(()=>{
    mounted.current=true;let timer:ReturnType<typeof setTimeout>;
    const load=async()=>{
      const epoch=revision.current;
      try{if(!lock.current){const r=await api.getUpdates();if(mounted.current&&epoch===revision.current){setState(r);if(r.error)setMessage(r.error);}}}
      catch{if(mounted.current)setMessage('Update helper unavailable. Retry Check for Updates.');}
      finally{if(mounted.current)timer=setTimeout(()=>void load(),3000);}
    };
    void load();return()=>{mounted.current=false;clearTimeout(timer);};
  },[]);
  const run=async(action:()=>Promise<Result>)=>{
    if(lock.current)return;const focused=document.activeElement instanceof HTMLElement?document.activeElement:undefined;lock.current=true;revision.current++;setBusy(true);setMessage('');
    try{const r=await action();setMessage(r.error||r.message||(r.ok===false?'Operation was not confirmed.':'Request completed.'));await refresh();}catch(e){setMessage(e instanceof Error?e.message:'Update unavailable.');}
    finally{lock.current=false;if(mounted.current){setBusy(false);requestAnimationFrame(()=>{if(focused?.isConnected&&document.activeElement===document.body)focused.focus();});}}
  };
  const button=(label:string,action:()=>void,disabled=false)=><PanelSectionRow key={label}><ButtonItem disabled={busy||disabled} onClick={action} layout="below">{label}</ButtonItem></PanelSectionRow>;
  const prepareFile=async(token:string,rollback:boolean)=>{
    const r=await api.preparePluginFile(token,rollback);
    if(r.error||r.ok===false)return r;
    if(r.folder!=='DeckPilot Updates'||r.file!=='DeckPilot.zip')throw Error('Prepared ZIP was not confirmed. No installation reported.');
    if(mounted.current)setPrepared(true);
    return r;
  };
  const openInstaller=()=>{
    try{Navigation.Navigate('/decky/settings/developer');}
    catch{setMessage('Open Decky Settings → Developer → Install from ZIP. Choose DeckPilot Updates → DeckPilot.zip.');}
  };
  useEffect(()=>{
    const current=sessionRef.current;
    if(!current||preparing.current||lock.current)return;
    if(state.installation?.status==='complete'&&state.installation.target_version===current.version){remember();return;}
    if(state.token&&state.token!==current.token||state.channel&&state.channel!==current.channel){remember();setMessage('Update selection changed. Review the new update before continuing.');return;}
    if(Date.now()-current.started>180000){remember();setMessage('The app update is taking longer than expected. Check status or recover; no automatic install retry.');return;}
    const failed=['error','rolled-back'].includes(state.operation?.status||'');
    const failedAt=Date.parse(state.operation?.timestamp_utc||'');
    if(failed&&state.operation?.version===current.version&&failedAt>=current.started-1000){remember();setMessage(state.operation?.message||'The app update failed. Review recovery before retrying.');return;}
    if(state.recovery_required||['queued','working'].includes(state.operation?.status||''))return;
    if(state.app_installed!==current.version||state.app_running!==current.version||!state.app_healthy||!state.token)return;
    preparing.current=true;
    void run(async()=>{
      try{return await prepareFile(current.token,false);}
      finally{remember();preparing.current=false;}
    });
  },[state,session]);
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
    if(a.kind==='everything'){
      const approved={version:a.version!,token:a.token!,channel:state.channel||'stable',started:Date.now()};
      if(state.app_installed===a.version&&state.app_running===a.version&&state.app_healthy)return prepareFile(a.token!,false);
      remember(approved);
      const r=await api.updateApp(a.token!,Boolean(a.downgrade));
      if(r.error)remember();
      return r;
    }
    if(a.kind==='file-rollback')return prepareFile('',true);
    if(a.kind==='app')return api.updateApp(a.token!,Boolean(a.downgrade));
    if(a.kind==='rollback')return api.rollbackUpdate();
    return handoff(a.kind==='plugin-rollback',a.token||'');
  });};
  return <PanelSection title="Updates">
    <PanelSectionRow><div><p>App {state.app_installed||'unknown'} · Plugin {state.plugin_installed||'unknown'}</p><p>{state.channel==='preview'?'Preview · approved development builds':'Stable · recommended'}</p><p>{state.message}</p>{!state.compatible&&<p>App and plugin versions differ. Update the app first, then the plugin. Profile changes are paused.</p>}{state.operation&&<p>{state.operation.message}</p>}{message&&<p role="status">{message}</p>}</div></PanelSectionRow>
    {approval?<>
      <PanelSectionRow><p>{approval.kind==='everything'?`Update Everything to ${approval.version}? ${approval.downgrade?'This is a downgrade. ':''}The app updates first with recovery saved. DeckPilot then prepares a verified ZIP. In Gaming Mode, choose Decky’s Install from ZIP → DeckPilot Updates → DeckPilot.zip and approve. Decky installs the plugin; preparation alone is not success.`:approval.kind==='file-rollback'?'Prepare the saved plugin for rollback? In Decky, select the prepared ZIP and approve. Match the app separately if needed.':approval.kind==='preview'?'Enable Preview? Development builds may have bugs. Nothing installs automatically.':approval.kind==='app'?`Install app ${approval.version}? ${approval.downgrade?'This is a downgrade. ':''}The app restarts; preferences, saves and game backups are kept. A rollback snapshot is saved.`:approval.kind==='rollback'?'Restore the previous app? Game files and preferences are kept. Match the plugin separately using its rollback button.':approval.kind==='plugin-rollback'?'Restore the saved plugin through Decky? Decky will ask for installation approval.':'Prepare the matching plugin? A rollback snapshot is saved. Decky will ask for installation approval.'}</p></PanelSectionRow>
      {button('Confirm',approve)}{button('Cancel',()=>setApproval(undefined))}
    </>:<>
      {button('Check for Updates',()=>void run(api.checkUpdates),working)}
      {state.channel==='preview'?button('Use Stable',()=>void run(async()=>{const r=await api.setUpdateChannel('stable');if(r.error)return r;return api.checkUpdates();}),working):button('Enable Preview',()=>setApproval({kind:'preview'}),working)}
      {state.available&&<PanelSectionRow><p>Verified {state.version}<br/>Commit {state.commit?.slice(0,12)}</p></PanelSectionRow>}
      {state.available&&button('Update Everything',()=>setApproval({kind:'everything',token:state.token,version:state.version,downgrade:state.downgrade}),working||Boolean(session)||preparing.current)}
      {button(advanced?'Hide separate update actions':'Separate update actions',()=>setAdvanced(!advanced),working)}
      {advanced&&state.available&&state.app_needed&&button('Update App',()=>setApproval({kind:'app',token:state.token,version:state.version,downgrade:state.downgrade}),working)}
      {advanced&&state.available&&state.plugin_needed&&button('Install Plugin in Decky',()=>setApproval({kind:'plugin',token:state.token,version:state.version}),Boolean(state.app_first)||working)}
      {state.app_rollback&&button(state.recovery_required?'Recover Interrupted Update':'Restore Previous App',()=>setApproval({kind:'rollback'}),working)}
      {state.plugin_rollback&&button('Restore Previous Plugin',()=>setApproval({kind:'file-rollback'}),working)}
      {advanced&&state.plugin_rollback&&button('Plugin Rollback by URL',()=>setApproval({kind:'plugin-rollback'}),working)}
    </>}
    {session&&<PanelSectionRow><p role="status">Waiting for app {session.version} to restart and answer. Do not press Update again. The verified plugin ZIP will be prepared next.</p></PanelSectionRow>}
    {state.installation&&<PanelSectionRow><div><p role="status">{state.installation.message}</p>{state.installation.files_verified!==undefined&&<p className="dp-small">{state.installation.files_verified} installed plugin files verified. File verification is separate from hardware validation.</p>}</div></PanelSectionRow>}
    {(prepared||state.installation?.status==='awaiting-decky'||state.installation?.status==='changed')&&<>
      <PanelSectionRow><p>Stay in Gaming Mode. In Decky Settings → Developer, choose Install from ZIP, then DeckPilot Updates → DeckPilot.zip. Accept Decky’s confirmation. No URL or clipboard is needed. Reopen DeckPilot Updates afterwards to verify.</p></PanelSectionRow>
      {button('Open Decky Installer',openInstaller)}
    </>}
    {button('Verify Installation',()=>void run(api.verifyUpdateInstallation),working)}
    {url&&<PanelSectionRow><div><p>Paste in Decky → Settings → Developer → Install from URL, then approve. No PC or file transfer needed.</p><textarea aria-label="Local plugin installation link" readOnly value={url} style={{width:'100%',height:90}}/></div></PanelSectionRow>}
    <PanelSectionRow><p className="dp-small">Only approved builds from goddenator/DeckPilot-TV. Checks never install updates. Plugin installation and rollback use Decky’s confirmation; no private installer APIs.</p></PanelSectionRow>
  </PanelSection>;
}
