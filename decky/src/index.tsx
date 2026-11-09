import { callable, definePlugin } from '@decky/api';
import { ButtonItem, PanelSection, PanelSectionRow } from '@decky/ui';
import { useEffect, useState } from 'react';
import { FaGamepad } from 'react-icons/fa';

type Mode = 'graphics' | 'performance' | 'balanced';
type Game = {appid:string;name:string;mode:Mode;supported:boolean};
type State = {
  version?:string;
  default?:Mode;
  games?:Game[];
  update?:{available?:boolean;version?:string;can_undo?:boolean;
    github?:{repository?:string;status?:string;message?:string}};
  ok?:boolean;
  error?:string;
  message?:string;
};
const stateCall = callable<[], State>('get_state');
const modeCall = callable<[mode:Mode, appid:string], Record<string,unknown>>('set_mode');
const checkCall = callable<[], Record<string,unknown>>('check_github');
const installCall = callable<[], Record<string,unknown>>('install_update');
const undoCall = callable<[], Record<string,unknown>>('rollback_update');
const MODES: [Mode,string][] = [['graphics','Best Graphics'],['performance','Best Performance'],['balanced','Balanced']];

function Content(){
  const [info,setInfo]=useState<State>({});
  const [active,setActive]=useState(0);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const reload=async()=>{try{const s=await stateCall();setInfo(s);if(s.error)setMessage(s.error);}catch(e){setMessage('DeckPilot is unavailable. Check that the app is installed.');}};
  useEffect(()=>{void reload();},[]);
  const games=info.games||[];
  const game=games[active%Math.max(1,games.length)];
  const setPreset=async(mode:Mode,appid='')=>{
    if(busy)return;setBusy(true);
    try{const r=await modeCall(mode,appid);setMessage(String(r.error||r.message||'Setting saved.'));await reload();}
    catch(e){setMessage('Could not save the setting.');}
    finally{setBusy(false);}
  };
  const action=async(fn:()=>Promise<Record<string,unknown>>)=>{
    if(busy)return;setBusy(true);
    try{const r=await fn();setMessage(String(r.message||r.error||'Request sent.'));await reload();}
    catch(e){setMessage('Action failed.');}
    finally{setBusy(false);}
  };
  return <>
    <PanelSection title={'DeckPilot TV '+(info.version||'')}>
      <PanelSectionRow><div style={{fontSize:12,opacity:.8}}>Default for new games</div></PanelSectionRow>
      {MODES.map(([m,label])=><PanelSectionRow key={'default'+m}>
        <ButtonItem disabled={busy} onClick={()=>void setPreset(m)}>{info.default===m?'✓ ':''}{label}</ButtonItem>
      </PanelSectionRow>)}
    </PanelSection>
    <PanelSection title="Installed game">
      <PanelSectionRow><div style={{fontSize:14}}>{game?game.name:'No Steam games found'}</div></PanelSectionRow>
      {game && <>
        <PanelSectionRow><ButtonItem onClick={()=>setActive(i=>(i+1)%games.length)}>
          Next game ({active%games.length+1}/{games.length})
        </ButtonItem></PanelSectionRow>
        <PanelSectionRow><div style={{fontSize:12,opacity:.8}}>{game.supported?'Supported Unreal Engine config':'No supported graphics config — preference only'}</div></PanelSectionRow>
        {MODES.map(([m,label])=><PanelSectionRow key={'game'+m}>
          <ButtonItem disabled={busy} onClick={()=>void setPreset(m,game.appid)}>{game.mode===m?'✓ ':''}{label}</ButtonItem>
        </PanelSectionRow>)}
      </>}
    </PanelSection>
    <PanelSection title="Updates">
      <PanelSectionRow><div style={{fontSize:12,opacity:.8}}>{info.update?.github?.message||'GitHub releases not connected'}</div></PanelSectionRow>
      <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(checkCall)}>Check GitHub releases</ButtonItem></PanelSectionRow>
      {info.update?.available && <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(installCall)}>
        Install v{info.update.version}</ButtonItem></PanelSectionRow>}
      {info.update?.can_undo && <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void action(undoCall)}>Undo last update</ButtonItem></PanelSectionRow>}
      <PanelSectionRow><ButtonItem onClick={()=>void reload()}>Refresh status</ButtonItem></PanelSectionRow>
    </PanelSection>
    {message && <PanelSection title="Status"><PanelSectionRow><div style={{fontSize:12}}>{message}</div></PanelSectionRow></PanelSection>}
  </>;
}
export default definePlugin(()=>({name:'DeckPilot TV',titleView:<div>DeckPilot TV</div>,content:<Content/>,icon:<FaGamepad/>}));
