import { test, expect, Page } from '@playwright/test';

async function setup(page:Page,options:{offline?:boolean;unsupported?:boolean;failApply?:boolean;searchError?:boolean;slowSearch?:boolean;oldApp?:boolean}={}){
 await page.addInitScript(()=>{
  const w=window as any;w.steamCalls=[];w.SteamClient={Apps:{}};
  for(const method of ['RegisterForGameActionStart','CancelGameAction','RunGame'])w.SteamClient.Apps[method]=()=>{w.steamCalls.push(method);throw Error('Unexpected Steam launch hook');};
 });
 const state:any={schema_version:options.oldApp?1:2,version:'0.8.1',context:'docked',default:'balanced',saved_games:{},
  profiles:{docked:{default:'balanced',games:{}},handheld:{default:'balanced',games:{}}},
  games:Array.from({length:12},(_,i)=>({appid:String(100+i),name:i===0?'My Game':'Game '+i,supported:!options.unsupported})),
  cloud:{enabled:false},measurements_enabled:false,update:{available:true,version:'0.8.2',can_undo:true}};
 const calls:{name:string;args:any[]}[]=[];
 let applied=false;
 await page.route('**/rpc',async route=>{
  const {name,args}=route.request().postDataJSON();calls.push({name,args});
  if(options.offline&&name==='get_state'){await route.fulfill({status:503});return;}
  let result:any={ok:true,message:'Saved.'};
  if(name==='get_state')result=state;
  if(name==='set_context'){state.context=args[0];state.default=state.profiles[args[0]].default;state.saved_games=state.profiles[args[0]].games;}
  if(name==='set_mode'){
   if(args[1])state.profiles[args[2]].games[args[1]]=args[0];else state.profiles[args[2]].default=args[0];
   state.default=state.profiles[state.context].default;state.saved_games=state.profiles[state.context].games;
  }
  if(name==='get_checkup')result={ok:true,status:options.unsupported?'advisory':applied?'ready':'needs-review',message:options.unsupported?'Advice only.':'Ready to review settings.',can_restore:applied,backups:applied?1:0};
  if(name==='search_games'){
   if(options.slowSearch)await new Promise(r=>setTimeout(r,250));
   result=options.searchError?{ok:false,error:'Steam unavailable.',games:[]}:{ok:true,games:[{appid:'892970',name:'Valheim'}]};
  }
  if(name==='preview')result=options.unsupported?{ok:true,status:'unsupported',message:'Advice only. No supported settings file.',files:[]}:{ok:true,status:'preview',token:'bound-preview',summary:{resolution:'1280 × 800',quality:'High',files:1,manual_files:0},files:[{file:'settings.ini',adapter:'unreal',changes:[{key:'ResolutionSizeX',before:'800',after:'1280'}]}]};
  if(name==='approve'){applied=!options.failApply;result=options.failApply?{ok:false,error:'Preview changed. Preview again.'}:{ok:true,message:'Applied safely.'};}
  if(name==='restore'){applied=false;result={ok:true,message:'Restored.'};}
  if(name==='set_measurements')state.measurements_enabled=args[0];
  if(name==='cloud_action')state.cloud.enabled=args[0]==='enable';
  if(name==='research_game')result={ok:true,recommendation:{mode:'balanced',confidence:'low',reason:'Handheld-only evidence.',note:'No TV guarantee.'},sources:[{source:'ShareDeck',status:'ok',url:'https://sharedeck.games/apps/892970',cached:true,stale:true}],reports:[{source:'ShareDeck',url:'https://sharedeck.games/apps/892970',device:'Steam Deck OLED',display_context:'handheld',summary:'<img src=x onerror=alert(1)> Untrusted text',uncertainty:'TV unverified',report_date:'2026-10-01',retrieved_at:'2026-11-10'}]};
  await route.fulfill({json:result});
 });
 await page.goto('/');
 await expect(page.getByRole('button',{name:'Find Games',exact:true})).toBeVisible();
 if(!options.offline)await expect(page.getByText('Update the app for the new profile controls.')).toHaveCount(options.oldApp?1:0);
 return {calls,state};
}
const button=(page:Page,name:string)=>page.getByRole('button',{name,exact:true});
async function openGame(page:Page){await button(page,'Find Games').click();await button(page,'My Game').click();await expect(page.getByRole('heading',{name:'Game Checkup'})).toBeVisible();}

test('Home is simple, keyboard accessible, and hides technical controls',async({page})=>{
 const {calls}=await setup(page);
 await expect(page.getByRole('heading',{name:'How do you want to play?'})).toBeVisible();
 for(const word of ['Private diagnostics','Display & App','Sources','Updates'])await expect(page.getByRole('heading',{name:word,exact:true})).toHaveCount(0);
 const performance=page.getByRole('button',{name:/Best Performance/});
 await performance.focus();await page.keyboard.press('Enter');
 await expect.poll(()=>calls.filter(c=>c.name==='set_mode').length).toBe(1);
 expect(calls.find(c=>c.name==='set_mode')?.args).toEqual(['performance','','docked']);
 await expect(performance).toHaveText(/Best Performance/);
 await expect(performance).toBeFocused();
 expect((await performance.boundingBox())!.height).toBeGreaterThanOrEqual(52);
 await page.keyboard.press('Tab');await expect(page.getByRole('button',{name:/Balanced/})).toBeFocused();
 await page.screenshot({path:'test-results/home.png'});
});

test('Find Games paginates and searches uninstalled Steam games',async({page})=>{
 const {calls}=await setup(page);
 await button(page,'Find Games').click();
 await expect(page.getByRole('button',{name:/Game 11/})).toHaveCount(0);
 await button(page,'More games').click();await expect(page.getByRole('button',{name:/Game 11/})).toBeVisible();
 await page.getByRole('textbox',{name:'Name or Steam App ID'}).fill('Valheim');await button(page,'Search Steam').click();
 await page.getByRole('button',{name:'Valheim'}).click();
 await expect(page.getByRole('heading',{name:'Valheim',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Best Graphics'}).click();
 expect(calls.filter(c=>c.name==='approve')).toHaveLength(0);
 expect(calls.find(c=>c.name==='set_mode')?.args).toEqual(['graphics','892970','docked']);
});

test('Review is concrete and requires approval; restore requires separate confirmation',async({page})=>{
 const {calls}=await setup(page);await openGame(page);
 await page.getByRole('button',{name:/Review & Apply/}).click();
 await expect(page.getByText('1280 × 800 · High')).toBeVisible();
 await expect(page.getByText('ResolutionSizeX: 800 → 1280')).toHaveCount(0);
 await button(page,'Advanced details').click();await expect(page.getByText('ResolutionSizeX: 800 → 1280')).toBeVisible();
 expect(calls.filter(c=>c.name==='approve')).toHaveLength(0);
 await button(page,'Cancel').click();expect(calls.filter(c=>c.name==='approve')).toHaveLength(0);
 await page.getByRole('button',{name:/Review & Apply/}).click();await button(page,'Apply Settings').click();
 await expect.poll(()=>calls.filter(c=>c.name==='approve').length).toBe(1);
 expect(calls.find(c=>c.name==='approve')?.args).toEqual(['100','balanced','bound-preview','docked']);
 await expect(page.getByText('Ready',{exact:true})).toBeVisible();
 await button(page,'Advanced').click();await page.getByRole('button',{name:'Restore game settings',exact:true}).click();expect(calls.filter(c=>c.name==='restore')).toHaveLength(0);
 await button(page,'Confirm Restore').click();await expect.poll(()=>calls.filter(c=>c.name==='restore').length).toBe(1);
});

test('unsupported games remain advisory and stale approvals fail visibly',async({page})=>{
 const {calls}=await setup(page,{unsupported:true});await openGame(page);
 await page.getByRole('button',{name:/Review & Apply/}).click();
 await expect(button(page,'Apply Settings')).toHaveCount(0);expect(calls.filter(c=>c.name==='approve')).toHaveLength(0);
 await expect(page.getByRole('status')).toHaveText('Advice only. No supported settings file.');
});

test('profile changes are separate and do not apply files',async({page})=>{
 const {calls}=await setup(page);await button(page,'Settings').click();await button(page,'Handheld').click();
 await expect(page.getByText('Handheld profile',{exact:true})).toBeVisible();await button(page,'Back').click();
 await page.getByRole('button',{name:'Best Graphics'}).click();
 expect(calls.find(c=>c.name==='set_mode')?.args).toEqual(['graphics','','handheld']);
 expect(calls.filter(c=>c.name==='approve')).toHaveLength(0);
});

test('advice is concise; optional sources show cached data and escape hostile content',async({page})=>{
 await setup(page);await openGame(page);await button(page,'Get Advice').click();
 await expect(page.getByText('Evidence: low')).toBeVisible();await expect(page.getByText('Untrusted text',{exact:false})).toHaveCount(0);
 await button(page,'View Sources').click();await expect(page.getByText(/Offline saved reports/)).toBeVisible();
 await expect(page.getByText('<img src=x onerror=alert(1)> Untrusted text')).toBeVisible();await expect(page.locator('img')).toHaveCount(0);
});

test('updates, diagnostics, and measurement opt-in stay in Settings/Advanced',async({page})=>{
 const {calls}=await setup(page);await button(page,'Settings').click();
 await button(page,'Review app update · v0.8.2').click();expect(calls.filter(c=>c.name==='install_update')).toHaveLength(0);
 await button(page,'Cancel').click();await button(page,'Decky plugin updates').click();
 expect(calls.filter(c=>/install/.test(c.name))).toHaveLength(0);
 await button(page,'Advanced').click();await expect(page.getByText('Off · Not available yet. Steam Play is untouched.')).toBeVisible();
 await button(page,'Existing FPS logs · Off').click();await expect(button(page,'Existing FPS logs · On')).toBeVisible();
 await page.getByRole('button',{name:/Set up Drive uploads/}).click();expect(calls.filter(c=>c.name==='cloud_action')).toHaveLength(0);
 await button(page,'Enable Drive uploads').click();expect(calls.find(c=>c.name==='cloud_action')?.args).toEqual(['enable']);
 expect(calls.some(c=>/launch|cancel|RunGame/.test(c.name))).toBe(false);
 expect(await page.evaluate(()=>(window as any).steamCalls)).toEqual([]);
});

test('offline connection and old backend fail clearly without mutating settings',async({page})=>{
 const {calls}=await setup(page,{offline:true});await expect(button(page,'Retry connection')).toBeVisible();
 await expect(page.getByRole('button',{name:/Best Graphics/})).toBeDisabled();expect(calls.filter(c=>c.name==='approve')).toHaveLength(0);
});

test('failed Steam search and duplicate clicks recover without duplicate work',async({page})=>{
 const {calls}=await setup(page,{searchError:true,slowSearch:true});await button(page,'Find Games').click();
 await page.getByRole('textbox').fill('Unknown');await button(page,'Search Steam').dblclick();
 await expect(page.getByRole('status')).toHaveText('Steam unavailable.');
 expect(calls.filter(c=>c.name==='search_games')).toHaveLength(1);await expect(button(page,'Search Steam')).toBeEnabled();
});

test('failed apply is shown and never claims success',async({page})=>{
 await setup(page,{failApply:true});await openGame(page);await page.getByRole('button',{name:/Review & Apply/}).click();await button(page,'Apply Settings').click();
 await expect(page.getByRole('status')).toHaveText('Preview changed. Preview again.');await expect(page.getByText('Ready',{exact:true})).toHaveCount(0);
});


test('older installed apps need an update before using profile controls',async({page})=>{
 const {calls}=await setup(page,{oldApp:true});
 await expect(page.getByText('Update the app for the new profile controls.')).toBeVisible();
 await expect(page.getByRole('button',{name:'Best Graphics',exact:true})).toBeDisabled();
 expect(calls.some(c=>c.name==='set_mode')).toBe(false);
});
