import { ButtonItem, PanelSection, PanelSectionRow, TextField, Navigation } from '@decky/ui';
import { useEffect, useRef, useState } from 'react';
import { launchController } from './launch';
import { Updates } from './Updates';
import { LaunchView } from './LaunchView';
import type { ReactNode } from 'react';
import { api, Checkup, Game, Mode, Preview, Profile, Research, Result, State } from './api';

const MODES:[Mode,string,string][] = [
  ['graphics','Best Graphics','Sharper detail'],
  ['performance','Best Performance','Smoother play'],
  ['balanced','Balanced','A bit of both'],
];
type Screen = 'home'|'find'|'game'|'settings'|'advanced'|'updates';
type Detail = 'main'|'review'|'restore'|'sources';
const row = (children:ReactNode,key?:string)=><PanelSectionRow key={key}>{children}</PanelSectionRow>;
const statusLabels:Record<string,string> = {ready:'Ready',running:'Game running','needs-review':'Review settings','manual-changes':'Your changes are safe','settings-match':'Settings match','not-installed':'Not installed',advisory:'Advice only',error:'Checkup unavailable'};
const labelFor=(mode?:Mode)=>MODES.find(([m])=>m===mode)?.[1]||'Balanced';

export function DeckPilotApp(){
  const [launchState,setLaunchState]=useState(launchController.getSnapshot);
  const launchActive=launchState.phase!=='idle';
  const launchLocked=launchState.phase==='applying'||launchState.phase==='launching';
  useEffect(()=>{
    const update=()=>setLaunchState(launchController.getSnapshot());
    const unsubscribe=launchController.subscribe(update);update();
    return()=>{unsubscribe();launchController.cancel();};
  },[]);
  const [screen,setScreen]=useState<Screen>(launchActive?'game':'home');
  const [detail,setDetail]=useState<Detail>('main');
  const [info,setInfo]=useState<State>({});
  const [selected,setSelected]=useState<Game|undefined>(launchState.target?{appid:launchState.target.appid,name:launchState.target.name}:undefined);
  const [checkup,setCheckup]=useState<Checkup>();
  const [research,setResearch]=useState<Research>();
  const [review,setReview]=useState<{preview:Preview;mode:Mode;context:Profile;appid:string}>();
  const [query,setQuery]=useState('');
  const [matches,setMatches]=useState<Game[]>([]);
  const [searched,setSearched]=useState(false);
  const [page,setPage]=useState(0);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const [offline,setOffline]=useState(false);
  const [confirm,setConfirm]=useState<'install'|'rollback'|'drive'|'play'|undefined>();
  const [technical,setTechnical]=useState(false);
  const inFlight=useRef(false);
  const context=info.context||'docked';
  const modern=info.schema_version===2 && (!info.update_suite || (info.update_suite.compatible===true&&!info.update_suite.recovery_required));
  const profile=info.profiles?.[context];
  const game=info.games?.find(g=>g.appid===selected?.appid)||selected;
  const mode=game?(profile?.games[game.appid]||profile?.default||info.saved_games?.[game.appid]||info.default||'balanced'):(profile?.default||info.default||'balanced');

  const refresh=async()=>{
    const state=await api.state();
    if(state.error||state.ok===false)throw Error(state.error||'DeckPilot unavailable.');
    setInfo(state);setOffline(false);
    return state;
  };
  useEffect(()=>{let live=true;void api.state().then(state=>{if(!live)return;if(state.error||state.ok===false)throw Error();setInfo(state);}).catch(()=>{if(live){setOffline(true);setMessage('DeckPilot unavailable. Try again.');}});return()=>{live=false;};},[]);
  const run=async(fn:()=>Promise<Result>)=>{
    if(inFlight.current)return;
    const focused=document.activeElement instanceof HTMLElement?document.activeElement:undefined;
    inFlight.current=true;setBusy(true);setMessage('');
    try{
      const result=await fn();setMessage(result.error||result.message||'Done.');
      try{await refresh();}catch{setOffline(true);setMessage((result.error||result.message||'Request completed.')+' Status unavailable.');}
    }catch{setMessage('Could not finish. Try again.');}
    finally{
      inFlight.current=false;setBusy(false);
      requestAnimationFrame(()=>{
        // Async disabling blurs native buttons. Keep keyboard focus unless the
        // user moved it or navigation removed the original control.
        if(focused?.isConnected&&(document.activeElement===document.body||document.activeElement===focused))focused.focus();
      });
    }
  };
  const navigate=(next:Screen)=>{if(!launchController.cancel())return;setScreen(next);setDetail('main');setReview(undefined);setConfirm(undefined);setTechnical(false);setMessage('');};
  const selectGame=(g:Game)=>{
    setSelected(g);setResearch(undefined);setReview(undefined);setCheckup(undefined);navigate('game');
    void run(async()=>{const c=await api.checkup(g.appid,context);setCheckup(c);return c;});
  };
  const refreshGame=async()=>{if(game){const c=await api.checkup(game.appid,context);setCheckup(c);return c;}return {};};
  const chooseMode=(m:Mode)=>void run(async()=>{
    setReview(undefined);
    const r=await api.mode(m,screen==='game'&&game?game.appid:'',context);
    if(r.ok!==false&&!r.error&&game&&screen==='game')await refreshGame();return r;
  });
  const bigButton=(text:string,onClick:()=>void,description?:string,disabled=false,key?:string)=>row(<ButtonItem layout="below" childrenContainerWidth="max" disabled={busy||disabled} onClick={onClick} description={description}>{text}</ButtonItem>,key||text.replace(/^✓ /,'').split(' · ')[0]);
  const modeButtons=()=>MODES.map(([m,title,description])=>bigButton((mode===m?'✓ ':'')+title,()=>chooseMode(m),description,!modern||offline));
  const back=()=>{
    if(launchActive){if(launchController.cancel())setMessage('Play cancelled.');return;}
    if(screen==='game'&&detail!=='main'){setDetail('main');setReview(undefined);setTechnical(false);}
    else navigate(screen==='advanced'||screen==='updates'?'settings':'home');
  };
  const evidence=research?.recommendation;
  const reportDate=(research?.reports||[]).map(r=>r.report_date).filter((date):date is string=>Boolean(date)&&Number.isFinite(Date.parse(date!))).sort().slice(-1)[0];
  const title=screen==='home'?'DeckPilot':screen==='find'?'Find Games':screen==='settings'?'Settings':screen==='advanced'?'Advanced':screen==='updates'?'Updates':game?.name||'Game Details';

  const allGames=new Map<string,Game>();
  for(const g of info.games||[])allGames.set(g.appid,g);
  for(const id of Object.keys(profile?.games||info.saved_games||{}))if(!allGames.has(id))allGames.set(id,{appid:id,name:'Saved game · '+id});
  if(searched)for(const g of matches)allGames.set(g.appid,{...allGames.get(g.appid),...g});
  const filtered=Array.from(allGames.values()).filter(g=>g.name.toLowerCase().includes(query.trim().toLowerCase())||g.appid===query.trim());
  const maxPage=Math.max(0,Math.ceil(filtered.length/8)-1);
  const currentPage=Math.min(page,maxPage);

  return <div className="deckpilot-app" style={{paddingBottom:16}}>
    <style>{`.deckpilot-app button,.deckpilot-app [role="button"]{min-height:52px}.deckpilot-app p{margin:8px 0;line-height:1.4}.deckpilot-app .dp-card{padding:12px;border-radius:10px;background:rgba(255,255,255,.06)}.deckpilot-app .dp-small{font-size:12px;opacity:.8}.deckpilot-app h2{font-size:20px;margin:6px 0}.deckpilot-app button:focus-visible{outline:3px solid #67dfce;outline-offset:2px}`}</style>
    <PanelSection title={title}>
      {screen!=='home'&&bigButton('Back',back,undefined,launchLocked)}
      {row(<div className="dp-small">{context==='docked'?'Docked':'Handheld'} profile</div>)}
      {offline&&row(<div role="alert">App connection unavailable.</div>)}
      {!modern&&row(<div className="dp-small">Update the app for the new profile controls.</div>)}
    </PanelSection>

    {screen==='home'&&<>
      <PanelSection title="How do you want to play?">{modeButtons()}</PanelSection>
      <PanelSection>
        {bigButton('Find Games',()=>navigate('find'),'Installed or anywhere on Steam')}
        {selected&&bigButton('Continue · '+selected.name,()=>selectGame(selected))}
        {bigButton('Settings',()=>navigate('settings'))}
        {offline&&bigButton('Retry connection',()=>void run(async()=>{await refresh();return {message:'Connected.'};}))}
      </PanelSection>
    </>}

    {screen==='find'&&<PanelSection>
      {row(<TextField label="Name or Steam App ID" value={query} onChange={e=>{setQuery(e.target.value);setPage(0);setSearched(false);setMatches([]);}}/>)}
      {bigButton('Search Steam',()=>void run(async()=>{const r=await api.search(query);setMatches(r.games||[]);setSearched(true);setPage(0);return {...r,message:r.error||((r.games||[]).length?'Choose your game.':'No Steam matches. Try its App ID.')};}),undefined,!query.trim()||offline)}
      {row(<div className="dp-small">{searched?'Steam results + your library':'Your games'}</div>)}
      {filtered.slice(currentPage*8,currentPage*8+8).map(g=>bigButton(g.name,()=>selectGame(g),'Steam App ID '+g.appid,false,'game-'+g.appid))}
      {!filtered.length&&row(<p>No games found. Try Search Steam.</p>)}
      {currentPage>0&&bigButton('Previous games',()=>setPage(currentPage-1))}
      {currentPage<maxPage&&bigButton('More games',()=>setPage(currentPage+1))}
    </PanelSection>}

    {screen==='game'&&game&&launchActive&&<LaunchView state={launchState} controller={launchController} onDone={()=>{if(launchController.cancel()){setMessage('');void run(refreshGame);}}}/>}

    {screen==='game'&&game&&!launchActive&&detail==='main'&&<>
      <PanelSection title="Game Checkup">
        {row(<div className="dp-card"><b>{checkup?.error?'Checkup unavailable':statusLabels[checkup?.status||'']||'Checking…'}</b><p>{checkup?.error||checkup?.message}</p>{Boolean(checkup?.backups)&&<div className="dp-small">Backups kept · {checkup?.can_restore?'Restore available':'Newer changes stay protected'}</div>}</div>)}
        {checkup?.error&&bigButton('Retry checkup',()=>void run(refreshGame))}
      </PanelSection>
      <PanelSection title="Your choice">{modeButtons()}</PanelSection>
      <PanelSection>
        {modern&&!offline&&info.launch_prompt?.enabled&&info.launch_prompt.protocol===1&&info.games?.some(g=>g.appid===game.appid)&&bigButton('Play with DeckPilot',()=>void launchController.start({appid:game.appid,name:game.name,context,installed:true,enabled:true}),'Opt-in cached advice before launching.',checkup?.status==='running')}
        {bigButton('Review & Apply',()=>void run(async()=>{
          const p=await api.preview(game.appid,mode,context);
          if(p.status==='preview'&&p.token&&!p.error){setReview({preview:p,mode,context,appid:game.appid});setDetail('review');}
          return p;
        }),'You approve. We back up first.',!modern||offline||checkup?.status==='running')}
        {bigButton('Get Advice',()=>void run(async()=>{const r=await api.research(game.appid,context);setResearch(r);return {...r,message:r.error||'Advice updated.'};}),undefined,offline)}
        {bigButton('Advanced',()=>navigate('advanced'),'Restore, measurements & diagnostics')}
      </PanelSection>
      {research&&<PanelSection title="Recommendation">
        {row(<div className="dp-card"><b>{labelFor(evidence?.mode)}</b><p>Evidence: {evidence?.confidence||'none'}</p><p>{evidence?.reason||research.error||'No verified reports yet.'}</p><p className="dp-small">{reportDate?'Latest report: '+reportDate.slice(0,10):'Report date unknown'}</p><div className="dp-small">Starting point only. Performance varies.</div></div>)}
        {bigButton('View Sources',()=>setDetail('sources'))}
      </PanelSection>}
    </>}

    {screen==='game'&&game&&detail==='review'&&review&&<PanelSection title="Review settings">
      {row(<div className="dp-card"><b>{labelFor(review.mode)} · {review.context==='docked'?'Docked':'Handheld'}</b><p>{review.preview.summary?.resolution||'Conservative local preset'}{review.preview.summary?.quality?' · '+review.preview.summary.quality:''}</p><p>{review.preview.summary?.files||review.preview.files?.length||0} settings file(s). Backups first.</p>{Boolean(review.preview.summary?.manual_files)&&<p>Your newer edits will be skipped.</p>}<div className="dp-small">Saves are never changed. This is not a benchmark.</div></div>)}
      {bigButton('Apply Settings',()=>void run(async()=>{const r=await api.approve(review.appid,review.mode,review.preview.token!,review.context);setDetail('main');setReview(undefined);await refreshGame();return r;}),undefined,offline)}
      {bigButton('Cancel',()=>{setDetail('main');setReview(undefined);})}
      {bigButton(technical?'Hide Advanced details':'Advanced details',()=>setTechnical(!technical))}
      {technical&&review.preview.files?.map((f,i)=>row(<div className="dp-small"><b>{f.adapter} · {f.file}</b>{f.manual_changes&&<p>Manual edits: skipped</p>}{f.changes.map(c=><p key={c.key}>{c.key}: {c.before??'unset'} → {c.after}</p>)}</div>,String(i)))}
    </PanelSection>}

    {screen==='game'&&detail==='restore'&&<PanelSection title="Restore settings?">
      {row(<p>Restore unchanged DeckPilot settings. Your newer changes and saves stay untouched. Automatic sync stops.</p>)}
      {bigButton('Confirm Restore',()=>void run(async()=>{const r=await api.restore(game!.appid);setDetail('main');await refreshGame();return r;}))}
      {bigButton('Cancel',()=>setDetail('main'))}
    </PanelSection>}

    {screen==='game'&&detail==='sources'&&<PanelSection title="Sources">
      {row(<p className="dp-small">Steam App ID {game?.appid}. Reports are advice, not commands or performance guarantees.</p>)}
      {research?.sources?.map(s=>bigButton(s.source,()=>Navigation.NavigateToExternalWeb(s.page_url||s.url),(s.stale?'Offline saved reports':s.cached?'Cached reports':s.status)))}
      {research?.reports?.map((r,i)=>row(<div className="dp-card"><b>{r.source} {r.report_id?'#'+r.report_id:''}</b><p>{r.device} · {r.display_context}</p><p>{r.resolution||'Resolution unknown'} · {r.fps||'FPS unknown'}</p><p className="dp-small">{r.fps_kind} · {r.report_date||'Date unknown'} · Game version {r.game_version||'unknown'}{r.stale?' · Offline copy':''}</p><p>{r.summary}</p><p className="dp-small">{r.uncertainty}</p><ButtonItem disabled={busy} onClick={()=>Navigation.NavigateToExternalWeb(r.url)}>Original report</ButtonItem></div>,String(i)))}
      {!research?.reports?.length&&row(<p>No verified reports available.</p>)}
    </PanelSection>}

    {screen==='settings'&&<>
      <PanelSection title="Where you play">
        {(['docked','handheld'] as Profile[]).map(c=>bigButton((context===c?'✓ ':'')+(c==='docked'?'Docked':'Handheld'),()=>void run(async()=>{setReview(undefined);setResearch(undefined);setCheckup(undefined);return api.context(c);}),undefined,!modern||offline))}
        {row(<p className="dp-small">Selected by you. Switching profiles never changes game files.</p>)}
      </PanelSection>
      <PanelSection>{bigButton('Updates',()=>navigate('updates'))}</PanelSection>
      <PanelSection>{bigButton('Advanced',()=>navigate('advanced'))}</PanelSection>
    </>}

    {screen==='updates'&&<Updates/>}

    {screen==='advanced'&&<>
      {game&&<PanelSection title={game.name}>
        {checkup?.can_restore&&bigButton('Restore game settings',()=>{setScreen('game');setDetail('restore');})}
        {bigButton('Refresh Game Checkup',()=>void run(refreshGame))}
      </PanelSection>}
      <PanelSection title="Play-time recommendations">
        {info.launch_prompt?.protocol===1?<>
          {confirm==='play'?<>
            {row(<p>Enable the experimental DeckPilot Play button? It uses cached advice. Steam’s own Play button stays unchanged. Hardware launch behavior still needs testing.</p>)}
            {bigButton('Enable Play recommendations',()=>void run(async()=>{setConfirm(undefined);return api.playAssistant(true);}))}
            {bigButton('Cancel',()=>setConfirm(undefined))}
          </>:bigButton('Play recommendations · '+(info.launch_prompt.enabled?'On':'Off'),()=>info.launch_prompt?.enabled?void run(()=>api.playAssistant(false)):setConfirm('play'))}
          {row(<p className="dp-small">DeckPilot’s Play button only. Native Steam Play is not intercepted.</p>)}
          {game&&info.launch_prompt.dismissed?.includes(game.appid)&&bigButton('Ask again for this game',()=>void run(()=>api.dismissPlay(game.appid,false)))}
        </>:row(<p>Off · Update the app for the opt-in DeckPilot Play prototype. Steam Play is untouched.</p>)}
      </PanelSection>
      <PanelSection title="Optional measurements">
        {bigButton('Existing FPS logs · '+(info.measurements_enabled?'On':'Off'),()=>void run(()=>api.measurements(!info.measurements_enabled)),undefined,!modern||offline)}
        {row(<p className="dp-small">Read your existing MangoHud FPS and frame-time samples. No recording, upload, or automatic tuning.</p>)}
        {info.measurements_enabled&&game?.metrics&&row(<p>{game.metrics.avg_fps} average FPS · {game.metrics.frame_time_p95_ms??'Unknown'} ms p95 frame time. Profile/session unverified.</p>)}
      </PanelSection>
      <PanelSection title="Private diagnostics">
        {row(<p className="dp-small">Drive uploads {info.cloud?.enabled?'on':'off'}. {info.cloud?.connection}</p>)}
        {bigButton('Export diagnostics',()=>void run(api.diagnostics),'Review before sharing.')}
        {confirm==='drive'?<>
          {row(<p>Send a redacted ZIP to your connected private Drive? It replaces DeckPilot-Latest.zip. Review an export first.</p>)}
          {bigButton('Enable Drive uploads',()=>void run(async()=>{setConfirm(undefined);return api.cloud('enable');}))}
          {bigButton('Cancel',()=>setConfirm(undefined))}
        </>:bigButton(info.cloud?.enabled?'Disable Drive uploads':'Set up Drive uploads',()=>info.cloud?.enabled?void run(()=>api.cloud('disable')):setConfirm('drive'))}
        {info.cloud?.enabled&&bigButton('Upload latest diagnostics',()=>void run(()=>api.cloud('upload')))}
      </PanelSection>
      <PanelSection title="Display & App">
        {row(<p className="dp-small">VRR capability: {info.display?.vrr_capability||'unknown'}. VRR enabled: {info.display?.vrr_enabled||'unknown'}. {info.display?.note}</p>)}
        {row(<p className="dp-small">App {info.version||'unknown'} · Plugin {info.plugin_version||'0.8.3-preview.1'}. {info.update?.github?.message}</p>)}
        {bigButton('Refresh status',()=>void run(async()=>{await refresh();return {message:'Refreshed.'};}))}
      </PanelSection>
    </>}
    {!launchActive&&(busy||message)&&<PanelSection>{row(<div role="status" aria-live="polite">{busy?'Working…':message}</div>)}</PanelSection>}
  </div>;
}
