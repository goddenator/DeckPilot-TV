import { ButtonItem, PanelSection, PanelSectionRow } from '@decky/ui';
import type { LaunchController, LaunchState } from './launch';
import type { Mode } from './api';
const modes:[Mode,string][]=[['graphics','Best Graphics'],['performance','Best Performance'],['balanced','Balanced']];

export function LaunchView({state,controller,onDone}:{state:LaunchState;controller:LaunchController;onDone:()=>void}){
  const button=(label:string,action:()=>void,description?:string)=><PanelSectionRow key={label.replace(/^✓ /,'')}><ButtonItem layout="below" childrenContainerWidth="max" onClick={action} description={description}>{label}</ButtonItem></PanelSectionRow>;
  const waiting=['loading','previewing','remembering','applying','launching'].includes(state.phase);
  const locked=state.phase==='applying'||state.phase==='launching';
  const plan=state.plan;
  return <PanelSection title="Play with DeckPilot">
    <PanelSectionRow><div className="dp-card">
      <b>{state.target?.name}</b>
      <p>{state.target?.context==='docked'?'Docked':'Handheld'} · Steam App ID {state.target?.appid}</p>
      {state.phase==='prompt'&&<>
        <p>{plan?.report_count&&plan.display_match?'Cached community evidence':'Suggested starting settings'}</p>
        <p>Evidence: {plan?.recommendation?.confidence||'none'}{plan?.stale?' · Offline/older copy':''}</p>
        {Boolean(plan?.sources?.length)&&<p className="dp-small">{plan!.sources!.join(' · ')}</p>}
        {plan?.display_match&&(plan.resolution||plan.fps)&&<p className="dp-small">{plan.resolution} {plan.fps} {plan.fps_kind}</p>}
        <p className="dp-small">{plan?.recommendation?.reason||'No cached reports. No Internet request will delay play.'} Starting point only; no guaranteed FPS.</p>
      </>}
      {state.message&&<p role="status">{state.message}</p>}
    </div></PanelSectionRow>
    {state.phase==='prompt'&&<>
      {modes.map(([mode,label])=>button((state.mode===mode?'✓ ':'')+label,()=>controller.selectMode(mode)))}
      {plan?.can_apply?button('Apply & Play',()=>void controller.review(),'Review exact changes first.'): <PanelSectionRow><p>Advice only. No safe settings changes available.</p></PanelSectionRow>}
      {plan?.status!=='uncertain'&&button('Play Without Changes',()=>void controller.playWithoutChanges())}
      {plan?.status!=='uncertain'&&button("Don't Ask Again",()=>void controller.dontAskAgain(),'Remember this game and play without changes.')}
      {button('Cancel',onDone)}
    </>}
    {state.phase==='review'&&<>
      <PanelSectionRow><p>Exact changes · {modes.find(([m])=>m===state.mode)?.[1]}. Original files are backed up before editing. Newer manual edits are skipped. Saves stay untouched.</p></PanelSectionRow>
      {state.preview?.files?.map((file,index)=><PanelSectionRow key={index}><div className="dp-card"><b>{file.adapter} · {file.file}</b>{file.location&&<p className="dp-small" style={{overflowWrap:'anywhere'}}>{file.location}</p>}{file.manual_changes&&<p>Skipped: newer user/game edits.</p>}{file.changes.length?file.changes.map(c=><p key={c.key}>{c.key}: {c.before??'(unset)'} → {c.after}</p>):<p>Already matches; no edits needed.</p>}</div></PanelSectionRow>)}
      {button('Approve & Play',()=>void controller.approve(),'Back up, apply these changes, then request launch.')}
      {plan?.status!=='uncertain'&&button('Play Without Changes',()=>void controller.playWithoutChanges())}
      {button('Cancel',onDone)}
    </>}
    {waiting&&!locked&&button('Cancel',onDone)}
    {locked&&<PanelSectionRow><p className="dp-small">An approved operation is in progress. Steam’s own Play button is never intercepted.</p></PanelSectionRow>}
    {(state.phase==='launched'||state.phase==='error')&&<>
      {state.phase==='error'&&<PanelSectionRow><p className="dp-small">Use Steam’s own Play button if needed. No automatic retry or relaunch.</p></PanelSectionRow>}
      {button('Done',onDone)}
    </>}
  </PanelSection>;
}
