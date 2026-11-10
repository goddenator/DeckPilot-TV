import { test,expect,Page } from '@playwright/test';

type Options={enabled?:boolean;unsupported?:boolean;dismissed?:boolean;backendDown?:boolean;failApply?:boolean;launchThrows?:boolean;noSteam?:boolean;uncertain?:boolean;slowPlan?:boolean};
async function setup(page:Page,options:Options={}){
 await page.addInitScript(({noSteam,launchThrows})=>{
  const w=window as any;w.steamCalls=[];
  w.SteamClient={Apps:{
   RunGame:(...args:unknown[])=>{w.steamCalls.push({name:'RunGame',args});if(launchThrows)throw Error('Steam launch failed');},
   RegisterForGameActionStart:()=>{w.steamCalls.push({name:'hook'});throw Error('Native hook forbidden');},
   CancelGameAction:()=>{w.steamCalls.push({name:'cancel'});throw Error('Native cancel forbidden');},
  }};
  if(noSteam)delete w.SteamClient.Apps.RunGame;
 },options);
 const state:any={schema_version:2,version:'0.8.2',context:'docked',default:'balanced',profiles:{docked:{default:'balanced',games:{}},handheld:{default:'balanced',games:{}}},games:[{appid:'1234',name:'Test Game',supported:!options.unsupported}],launch_prompt:{protocol:2,available:true,enabled:options.enabled??true,native_play:false,dismissed:options.dismissed?['1234']:[]}};
 const calls:{name:string;args:any[]}[]=[];
 await page.route('**/rpc',async route=>{
  const {name,args}=route.request().postDataJSON();calls.push({name,args});let result:any={ok:true};
  if(name==='get_state')result=state;
  if(name==='get_checkup')result={ok:true,status:options.unsupported?'advisory':'needs-review',message:'Review settings.'};
  if(name==='set_play_assistant')state.launch_prompt.enabled=args[0];
  if(name==='dismiss_play_advice'){state.launch_prompt.dismissed=args[1]?[args[0]]:[];}
  if(name==='play_plan'){
   if(options.backendDown){await route.fulfill({status:503});return;}
   if(options.slowPlan)await new Promise(r=>setTimeout(r,250));
   result=state.launch_prompt.dismissed.includes('1234')?{ok:true,status:'dismissed',appid:'1234'}:{ok:true,status:'prompt',appid:'1234',context:'docked',can_apply:!options.unsupported,report_count:1,sources:['ShareDeck'],stale:true,display_match:true,resolution:'1280x800',fps:'40 FPS',fps_kind:'target, not measured FPS',recommendation:{mode:'balanced',confidence:'low',reason:'Saved OLED report; TV unverified.',note:'Starting point'}};
  }
  if(name==='play_plan'&&options.uncertain)result={ok:true,status:'uncertain',appid:'1234',context:'docked',can_apply:false,message:'Cannot confirm game closed. Use Steam’s Play/Resume button.'};
  if(name==='process_state')result={state:'closed'};
  if(name==='play_preview')result={ok:true,status:'preview',token:'exact-token',files:[{adapter:'unreal',file:'GameUserSettings.ini',manual_changes:false,changes:[{key:'ResolutionSizeX',before:'800',after:'1920'},{key:'ResolutionSizeY',before:'600',after:'1080'}]}]};
  if(name==='play_approve')result=options.failApply?{ok:false,error:'Preview changed. No changes applied.'}:{ok:true,message:'Backed up and applied.'};
  await route.fulfill({json:result});
 });
 await page.goto('/');await page.getByRole('button',{name:'Find Games',exact:true}).click();await page.getByRole('button',{name:'Test Game',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Game Checkup',exact:true})).toBeVisible();return {calls,state};
}
const button=(page:Page,name:string)=>page.getByRole('button',{name,exact:true});
const steamCalls=(page:Page)=>page.evaluate(()=>(window as any).steamCalls as {name:string;args?:unknown[]}[]);

test('prototype stays off until explicit opt-in and keeps native Steam Play unhooked',async({page})=>{
 const {calls}=await setup(page,{enabled:false});await expect(button(page,'Play with DeckPilot')).toHaveCount(0);
 await button(page,'Advanced').click();await button(page,'Play recommendations · Off').click();
 expect(calls.filter(c=>c.name==='set_play_assistant')).toHaveLength(0);
 await expect(page.getByText(/Steam’s own Play button stays unchanged/)).toBeVisible();await button(page,'Enable Play recommendations').click();
 await expect(button(page,'Play recommendations · On')).toBeVisible();await expect.poll(()=>calls.filter(c=>c.name==='set_play_assistant').length).toBe(1);
 expect(await steamCalls(page)).toEqual([]);
});

test('Apply & Play displays every exact change and waits for approval before launching',async({page})=>{
 const {calls}=await setup(page);await button(page,'Play with DeckPilot').click();await expect(button(page,'Apply & Play')).toBeVisible();
 await expect(page.getByText('Evidence: low · Offline/older copy')).toBeVisible();
 await button(page,'Best Graphics').click();await button(page,'Apply & Play').click();
 await expect(page.getByText('ResolutionSizeX: 800 → 1920')).toBeVisible();await expect(page.getByText('ResolutionSizeY: 600 → 1080')).toBeVisible();
 expect(calls.filter(c=>c.name==='play_approve')).toHaveLength(0);expect(await steamCalls(page)).toEqual([]);
 await button(page,'Approve & Play').click();
 await expect.poll(()=>steamCalls(page)).toEqual([{name:'RunGame',args:['1234','',-1,100]}]);
 expect(calls.find(c=>c.name==='play_approve')?.args).toEqual(['1234','graphics','exact-token','docked']);
 expect(calls.some(c=>c.name==='research_game'||c.name==='set_mode')).toBe(false);
});

test('Play Without Changes sends one ordinary launch without preview or config edits',async({page})=>{
 const {calls}=await setup(page);await button(page,'Play with DeckPilot').click();await button(page,'Play Without Changes').click();
 await expect.poll(()=>steamCalls(page)).toEqual([{name:'RunGame',args:['1234','',-1,100]}]);
 expect(calls.some(c=>['play_preview','play_approve','set_mode','research_game'].includes(c.name))).toBe(false);
});

test('Don’t Ask Again is per-game and the next Play bypasses the prompt without applying',async({page})=>{
 const {calls}=await setup(page);await button(page,'Play with DeckPilot').click();await button(page,"Don't Ask Again").click();
 await expect.poll(()=>steamCalls(page)).toHaveLength(1);expect(calls.find(c=>c.name==='dismiss_play_advice')?.args).toEqual(['1234',true]);
 expect(calls.some(c=>c.name==='play_approve')).toBe(false);
 await page.reload();await button(page,'Find Games').click();await button(page,'Test Game').click();await button(page,'Play with DeckPilot').click();
 await expect.poll(()=>steamCalls(page)).toHaveLength(1);await expect(button(page,'Apply & Play')).toHaveCount(0);
 expect(calls.filter(c=>c.name==='play_plan')).toHaveLength(2);
});

test('dismissed game immediately requests play and reset remains in Advanced',async({page})=>{
 const {calls}=await setup(page,{dismissed:true});await button(page,'Play with DeckPilot').click();
 await expect.poll(()=>steamCalls(page)).toHaveLength(1);await expect(button(page,'Apply & Play')).toHaveCount(0);
 await button(page,'Done').click();await button(page,'Advanced').click();await button(page,'Ask again for this game').click();
 expect(calls.find(c=>c.name==='dismiss_play_advice')?.args).toEqual(['1234',false]);
});

test('Cancel and Back abandon a pending or reviewed launch without writes',async({page})=>{
 const {calls}=await setup(page,{slowPlan:true});await button(page,'Play with DeckPilot').click();await button(page,'Cancel').click();
 await expect(page.getByRole('heading',{name:'Game Checkup'})).toBeVisible();await page.waitForTimeout(300);expect(await steamCalls(page)).toEqual([]);
 await button(page,'Play with DeckPilot').click();await button(page,'Apply & Play').click();await button(page,'Back').click();
 expect(calls.some(c=>c.name==='play_approve')).toBe(false);expect(await steamCalls(page)).toEqual([]);
});

test('unsupported games have advice and Play Without Changes but no false Apply',async({page})=>{
 const {calls}=await setup(page,{unsupported:true});await button(page,'Play with DeckPilot').click();
 await expect(button(page,'Play Without Changes')).toBeVisible();await expect(button(page,'Apply & Play')).toHaveCount(0);
 await button(page,'Play Without Changes').click();await expect.poll(()=>steamCalls(page)).toHaveLength(1);expect(calls.some(c=>c.name==='play_preview'||c.name==='play_approve')).toBe(false);
});

test('unavailable backend falls back once; missing Steam API makes no changes',async({page})=>{
 const {calls}=await setup(page,{backendDown:true});await button(page,'Play with DeckPilot').click();await expect.poll(()=>steamCalls(page)).toHaveLength(1);
 expect(calls.some(c=>c.name==='play_approve')).toBe(false);
});

test('missing Steam API gives a native Play fallback without applying',async({page})=>{
 const {calls}=await setup(page,{noSteam:true});await button(page,'Play with DeckPilot').click();await expect(page.getByRole('status')).toHaveText('Steam launch API unavailable. Use Steam’s Play button.');
 expect(await steamCalls(page)).toEqual([]);expect(calls.some(c=>c.name==='play_approve')).toBe(false);
});

test('launch failure never retries or registers cancellation/relaunch hooks',async({page})=>{
 await setup(page,{launchThrows:true});await button(page,'Play with DeckPilot').click();await button(page,'Play Without Changes').click();
 await expect(page.getByRole('status')).toHaveText('Steam did not confirm the launch request. Check Steam; no automatic retry.');
 await button(page,'Done').click();await button(page,'Play with DeckPilot').click();
 await expect(page.getByRole('status')).toHaveText('A launch was already requested. Check Steam before trying again.');expect((await steamCalls(page)).map(c=>c.name)).toEqual(['RunGame']);
});

test('apply rejection never launches automatically and permits an explicit unchanged launch',async({page})=>{
 await setup(page,{failApply:true});await button(page,'Play with DeckPilot').click();await button(page,'Apply & Play').click();await button(page,'Approve & Play').click();
 await expect(page.getByRole('status')).toHaveText('Preview changed. No changes applied.');expect(await steamCalls(page)).toEqual([]);
 await button(page,'Play Without Changes').click();await expect.poll(()=>steamCalls(page)).toHaveLength(1);
});

test('keyboard navigation preserves mode focus and Cancel abandons reviewed Play',async({page})=>{
 const {calls}=await setup(page);await button(page,'Play with DeckPilot').click();
 const performance=page.getByRole('button',{name:/Best Performance/});await performance.focus();await page.keyboard.press('Enter');
 await expect(performance).toBeFocused();await expect(performance).toHaveText(/✓ Best Performance/);
 await page.keyboard.press('Tab');await expect(page.getByRole('button',{name:/Balanced/})).toBeFocused();
 await page.keyboard.press('Tab');await expect(button(page,'Apply & Play')).toBeFocused();await page.keyboard.press('Enter');
 await expect(page.getByText('ResolutionSizeX: 800 → 1920')).toBeVisible();
 await button(page,'Cancel').focus();await page.keyboard.press('Enter');await expect(page.getByRole('heading',{name:'Game Checkup'})).toBeVisible();
 expect(calls.some(c=>c.name==='play_approve')).toBe(false);expect(await steamCalls(page)).toEqual([]);
});

test('uncertain process visibility offers advice and native fallback without apply or dispatch',async({page})=>{
 const {calls}=await setup(page,{uncertain:true});await button(page,'Play with DeckPilot').click();
 await expect(page.getByRole('status')).toContainText('Cannot confirm game closed');
 for(const name of ['Apply & Play','Play Without Changes',"Don't Ask Again"])await expect(button(page,name)).toHaveCount(0);
 await button(page,'Cancel').click();expect(await steamCalls(page)).toEqual([]);expect(calls.some(c=>c.name==='play_approve')).toBe(false);
});
