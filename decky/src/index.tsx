import { callable, definePlugin } from '@decky/api';
import { ButtonItem, PanelSection, PanelSectionRow, TextField, Navigation } from '@decky/ui';
import { useEffect, useState } from 'react';
import { FaGamepad } from 'react-icons/fa';

type Mode = 'graphics' | 'performance' | 'balanced';
type Game = {appid:string;name:string;mode?:Mode;supported?:boolean;adapter?:string;approved?:boolean};
type Result = {ok?:boolean;error?:string;message?:string};
type State = Result & {
  version?:string;default?:Mode;games?:Game[];saved_games?:Record<string,Mode>;
  display?:{vrr_capability:string;vrr_enabled:string;note:string;external_outputs:{connector:string;advertised_modes:string[]}[]};
  update?:{available?:boolean;version?:string;can_undo?:boolean;github?:{message?:string}};
};
type Report = {source:string;url:string;device:string;game_version?:string;report_date?:string;retrieved_at:string;resolution?:string;fps?:string;fps_kind?:string;report_id?:string;display_context:string;summary:string;uncertainty:string};
type Research = Result & {game?:Game;reports?:Report[];sources?:{source:string;status:string;url:string;page_url?:string;message?:string}[]};
type Preview = Result & {status?:string;token?:string;files?:{file:string;adapter:string;manual_changes:boolean;changes:{key:string;before?:string;after:string}[]}[]};
const stateCall = callable<[], State>('get_state');
const modeCall = callable<[mode:Mode, appid:string], Result>('set_mode');
const searchCall = callable<[query:string], Result & {games?:Game[]}>('search_games');
const researchCall = callable<[appid:string], Research>('research_game');
const previewCall = callable<[appid:string, mode:Mode], Preview>('preview');
const approveCall = callable<[appid:string, mode:Mode, token:string], Result>('approve');
const restoreCall = callable<[appid:string], Result>('restore');
const checkCall = callable<[], Result>('check_github');
const installCall = callable<[], Result>('install_update');
const undoCall = callable<[], Result>('rollback_update');
const MODES: [Mode,string][] = [['graphics','Best Graphics'],['performance','Best Performance'],['balanced','Balanced']];

function Content(){
  const [info,setInfo]=useState<State>({});
  const [selected,setSelected]=useState<Game>();
  const [query,setQuery]=useState('');
  const [matches,setMatches]=useState<Game[]>([]);
  const [research,setResearch]=useState<Research>();
  const [preview,setPreview]=useState<Preview>();
  const [pendingMode,setPendingMode]=useState<Mode>('balanced');
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const reload=async()=>{const s=await stateCall();setInfo(s);if(s.error)setMessage(s.error);};
  useEffect(()=>{void reload().catch(()=>setMessage('DeckPilot is unavailable. Check the app installation.'));},[]);
  const action=async(fn:()=>Promise<Result>)=>{
    if(busy)return;setBusy(true);
    try{const r=await fn();setMessage(r.error||r.message||'Done.');await reload();}
    catch{setMessage('DeckPilot request failed. Try again.');}
    finally{setBusy(false);}
  };
  const choose=(g:Game)=>{setSelected(g);setResearch(undefined);setPreview(undefined);};
  const game=info.games?.find(g=>g.appid===selected?.appid)||selected;
  const mode=game?(info.saved_games?.[game.appid]||info.default):undefined;
  return <>
    <PanelSection title={'DeckPilot TV '+(info.version||'')}>
      <PanelSectionRow><div>Default for games without an override. Existing per-game choices are kept. Local edits require preview and approval.</div></PanelSectionRow>
      {MODES.map(([m,label])=><PanelSectionRow key={m}><ButtonItem disabled={busy} onClick={()=>void action(async()=>{setPreview(undefined);return modeCall(m,'');})}>{info.default===m?'✓ ':''}{label}</ButtonItem></PanelSectionRow>)}
    </PanelSection>
    <PanelSection title="Find any Steam game">
      <PanelSectionRow><TextField label="Game name or Steam App ID" value={query} onChange={e=>setQuery(e.target.value)} /></PanelSectionRow>
      <PanelSectionRow><ButtonItem disabled={busy||!query.trim()} onClick={()=>void action(async()=>{const r=await searchCall(query);setMatches(r.games||[]);return {...r,message:r.games?.length?'Select the exact game and App ID below.':'No games found.'};})}>Search Steam (including uninstalled)</ButtonItem></PanelSectionRow>
      {matches.map(g=><PanelSectionRow key={g.appid}><ButtonItem disabled={busy} onClick={()=>choose(g)}>{g.name} · App ID {g.appid}</ButtonItem></PanelSectionRow>)}
    </PanelSection>
    <PanelSection title="Installed games and saved preferences">
      {(info.games||[]).map(g=><PanelSectionRow key={g.appid}><ButtonItem disabled={busy} onClick={()=>choose(g)}>{g.name} · {g.appid}</ButtonItem></PanelSectionRow>)}
      {Object.keys(info.saved_games||{}).filter(id=>!info.games?.some(g=>g.appid===id)).map(id=><PanelSectionRow key={id}><ButtonItem disabled={busy} onClick={()=>choose({appid:id,name:'Saved Steam game'})}>App ID {id} · not installed · {MODES.find(([m])=>m===info.saved_games?.[id])?.[1]}</ButtonItem></PanelSectionRow>)}
    </PanelSection>
    {game&&<PanelSection title={game.name+' · '+game.appid}>
      <PanelSectionRow><div>{game.supported?game.adapter+' · '+(game.approved?'Approved local profile':'Approval needed'):'Advisory until a compatible installed config is found.'}</div></PanelSectionRow>
      {MODES.map(([m,label])=><PanelSectionRow key={m}><ButtonItem disabled={busy} onClick={()=>void action(async()=>{setPreview(undefined);return modeCall(m,game.appid);})}>{mode===m?'✓ ':''}Save {label}</ButtonItem></PanelSectionRow>)}
      <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(async()=>{setPreview(undefined);setPendingMode(mode||'balanced');const p=await previewCall(game.appid,mode||'balanced');setPreview(p);return p;})}>Preview saved mode</ButtonItem></PanelSectionRow>
      {preview?.files?.map((f,i)=><PanelSectionRow key={i}><div><b>{f.adapter} · {f.file}</b>{f.manual_changes&&<p>Manual/game edits detected. This file will be skipped.</p>}{f.changes.map(c=><div key={c.key}>{c.key}: {c.before??'(unset)'} → {c.after}</div>)}</div></PanelSectionRow>)}
      {preview?.status==='preview'&&preview.token&&<PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(async()=>{const r=await approveCall(game.appid,pendingMode,preview.token!);setPreview(undefined);return r;})}>Approve preview and apply (backup first)</ButtonItem></PanelSectionRow>}
      <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(async()=>{setPreview(undefined);return restoreCall(game.appid);})}>Restore unchanged managed settings / stop auto-apply</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(async()=>{setResearch(undefined);const r=await researchCall(game.appid);setResearch(r);return r;})}>Research community reports (verify App ID)</ButtonItem></PanelSectionRow>
    </PanelSection>}
    {research&&<PanelSection title="Independent community evidence">
      <PanelSectionRow><div>{research.game?.name} · {research.game?.appid}<p>Reports are advisory. Unknown metadata stays unknown. These are not TV performance guarantees or DeckPilot benchmarks.</p></div></PanelSectionRow>
      {research.sources?.map(s=><PanelSectionRow key={s.source}><div>{s.source}: {s.status}<p>{s.message}</p><ButtonItem disabled={busy} onClick={()=>Navigation.NavigateToExternalWeb(s.page_url||s.url)}>Open {s.source}</ButtonItem></div></PanelSectionRow>)}
      {!research.reports?.length&&<PanelSectionRow><div>No verified reports available. Source failures never prevent saving preferences.</div></PanelSectionRow>}
      {research.reports?.map((r,i)=><PanelSectionRow key={i}><div><b>{r.source} {r.report_id?"#"+r.report_id:""}</b><p>{r.device} · {r.display_context} · {r.resolution||'Resolution unknown'} · {r.fps||'FPS unknown'} ({r.fps_kind||'community report'})</p><p>Game version: {r.game_version||'unknown'} · Report date: {r.report_date||'unknown'} · Retrieved: {r.retrieved_at}</p><p>{r.summary}</p><p>{r.uncertainty}</p><ButtonItem disabled={busy} onClick={()=>Navigation.NavigateToExternalWeb(r.url)}>View original report</ButtonItem></div></PanelSectionRow>)}
    </PanelSection>}
    <PanelSection title="Display diagnostics">
      <PanelSectionRow><div>External VRR capability: {info.display?.vrr_capability||'unknown'} · VRR enabled: {info.display?.vrr_enabled||'unknown'}<p>{info.display?.note}</p>{info.display?.external_outputs.map(o=><div key={o.connector}>{o.connector}: {o.advertised_modes.join(', ')||'Modes unknown'}</div>)}</div></PanelSectionRow>
    </PanelSection>
    <PanelSection title="Updates">
      <PanelSectionRow><div>{info.update?.github?.message||'Connect a trusted GitHub release feed in the Desktop dashboard.'}</div></PanelSectionRow>
      <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(checkCall)}>Check GitHub releases</ButtonItem></PanelSectionRow>
      {info.update?.available&&<PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(installCall)}>Approve install v{info.update.version}</ButtonItem></PanelSectionRow>}
      {info.update?.can_undo&&<PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(undoCall)}>Undo last app update</ButtonItem></PanelSectionRow>}
      <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(async()=>{await reload();return {message:'Status refreshed.'};})}>Refresh status</ButtonItem></PanelSectionRow>
    </PanelSection>
    {message&&<PanelSection title="Status"><PanelSectionRow><div role="status">{message}</div></PanelSectionRow></PanelSection>}
  </>;
}
export default definePlugin(()=>({name:'DeckPilot TV',titleView:<div>DeckPilot TV</div>,content:<Content/>,icon:<FaGamepad/>}));
