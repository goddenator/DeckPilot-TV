import {test,expect,Page} from '@playwright/test';
async function setup(page:Page,overrides:any={}){
 const state:any={protocol:1,channel:'stable',app_installed:'0.8.2',plugin_installed:'0.8.2',compatible:true,available:true,version:'0.8.3',token:'reviewed-token',commit:'a'.repeat(40),app_needed:true,plugin_needed:true,app_first:true,app_rollback:true,plugin_rollback:true,...overrides};
 const calls:any[]=[];
 await page.route('**/rpc',async route=>{
  const {name,args}=route.request().postDataJSON();calls.push({name,args});let result:any={ok:true,message:'Saved.'};
  if(name==='get_state')result={schema_version:2,version:state.app_installed,update_suite:state,games:[],profiles:{docked:{default:'balanced',games:{}},handheld:{default:'balanced',games:{}}}};
  if(name==='get_updates'||name==='check_updates')result={...state};
  if(name==='set_update_channel')state.channel=args[0];
  if(name==='update_app')result=overrides.stale?{error:'Update changed or is unavailable. Check and review again.'}:{message:'App update started.'};
  if(name==='verify_update_installation')result={ok:true,message:'Verification check finished.'};
  if(name==='prepare_plugin_file')result={ok:true,folder:'DeckPilot Updates',file:'DeckPilot.zip',version:state.version,message:'Verified ZIP prepared; not installed yet.'};
  if(name==='plugin_handoff')result={url:'http://127.0.0.1:45678/'+'a'.repeat(43)+'/DeckPilot.zip'};
  await route.fulfill({json:result});
 });
 await page.goto('/');await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:'Updates',exact:true}).click();
 await expect(page.getByText('App '+state.app_installed+' · Plugin '+state.plugin_installed)).toBeVisible();
 if(overrides.separate!==false)await page.getByRole('button',{name:'Separate update actions',exact:true}).click();
 return {state,calls};
}
const button=(page:Page,name:string)=>page.getByRole('button',{name,exact:true});
test('Stable default, opt-in Preview and cancellation never installs',async({page})=>{
 const {calls}=await setup(page);await expect(page.getByText('Stable · recommended')).toBeVisible();
 await button(page,'Enable Preview').click();expect(calls.some(c=>c.name==='set_update_channel')).toBe(false);await button(page,'Cancel').click();
 await button(page,'Enable Preview').click();await button(page,'Confirm').click();await expect(page.getByText('Preview · approved development builds')).toBeVisible();
 expect(calls.find(c=>c.name==='set_update_channel').args).toEqual(['preview']);expect(calls.some(c=>c.name==='update_app'||c.name==='plugin_handoff')).toBe(false);
});
test('app first and bound approval, stale token error visible',async({page})=>{
 const {calls}=await setup(page,{stale:true});await expect(button(page,'Install Plugin in Decky')).toBeDisabled();
 await button(page,'Update App').click();expect(calls.some(c=>c.name==='update_app')).toBe(false);await button(page,'Confirm').click();
 await expect(page.getByRole('status')).toHaveText(/Update changed/);expect(calls.find(c=>c.name==='update_app').args).toEqual(['reviewed-token',false]);
});
test('downgrade is explicit and app rollback separately confirmed',async({page})=>{
 const {calls}=await setup(page,{downgrade:true});await button(page,'Update App').click();await expect(page.getByText(/This is a downgrade/)).toBeVisible();await button(page,'Confirm').click();
 await expect.poll(()=>calls.filter(c=>c.name==='update_app').length).toBe(1);expect(calls.find(c=>c.name==='update_app').args).toEqual(['reviewed-token',true]);
 await button(page,'Restore Previous App').click();await button(page,'Cancel').click();expect(calls.some(c=>c.name==='rollback_update')).toBe(false);
 await button(page,'Restore Previous App').click();await button(page,'Confirm').click();await expect.poll(()=>calls.filter(c=>c.name==='rollback_update').length).toBe(1);
});
test('plugin uses local URL and public Decky navigation after approval',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async(text:string)=>{document.body.dataset.clipboard=text;}}}));
 const {calls}=await setup(page,{app_installed:'0.8.3',compatible:false,app_needed:false,app_first:false});
 await button(page,'Install Plugin in Decky').click();expect(calls.some(c=>c.name==='plugin_handoff')).toBe(false);await button(page,'Confirm').click();
 await expect(page.getByRole('textbox',{name:'Local plugin installation link'})).toHaveValue(/127\.0\.0\.1/);
 await expect.poll(()=>page.evaluate(()=>document.body.dataset.deckyRoute)).toBe('/decky/settings/developer');
 expect(calls.find(c=>c.name==='plugin_handoff').args).toEqual(['reviewed-token',false]);
});
test('clipboard failure keeps selectable link and plugin rollback requires approval',async({page})=>{
 await page.addInitScript(()=>{Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw Error('denied');}}});document.execCommand=()=>false;});
 const {calls}=await setup(page);await button(page,'Plugin Rollback by URL').click();await button(page,'Confirm').click();
 await expect(page.getByRole('status')).toHaveText(/Clipboard unavailable/);await expect(page.getByRole('textbox')).toBeVisible();
 expect(calls.find(c=>c.name==='plugin_handoff').args).toEqual(['',true]);
});
test('mismatch pauses game profile mutation and recovery remains available',async({page})=>{
 await setup(page,{compatible:false,recovery_required:true});await expect(page.getByText(/versions differ/)).toBeVisible();await expect(button(page,'Recover Interrupted Update')).toBeVisible();
 await button(page,'Back').click();await button(page,'Back').click();await expect(page.getByRole('button',{name:/Best Graphics/})).toBeDisabled();
});


test('Update Everything stages a controller ZIP only after matching running app, then verifies installation',async({page})=>{
 const {calls,state}=await setup(page,{separate:false,token:'b'.repeat(64)});
 await button(page,'Update Everything').click();
 expect(calls.some(c=>c.name==='update_app'||c.name==='prepare_plugin_file')).toBe(false);
 await expect(page.getByText(/This is a downgrade/)).toHaveCount(0);
 await button(page,'Confirm').click();
 await expect.poll(()=>calls.filter(c=>c.name==='update_app').length).toBe(1);
 expect(calls.some(c=>c.name==='prepare_plugin_file')).toBe(false);
 state.app_installed='0.8.3';state.app_running='0.8.3';state.app_healthy=true;state.app_first=false;state.app_needed=false;
 await expect.poll(()=>calls.filter(c=>c.name==='prepare_plugin_file').length,{timeout:10000}).toBe(1);
 await expect(button(page,'Open Decky Installer')).toBeVisible();
 expect(calls.find(c=>c.name==='prepare_plugin_file').args).toEqual(['b'.repeat(64),false]);
 expect(calls.some(c=>c.name==='plugin_handoff')).toBe(false);
 await button(page,'Open Decky Installer').click();
 await expect.poll(()=>page.evaluate(()=>document.body.dataset.deckyRoute)).toBe('/decky/settings/developer');
 state.plugin_installed='0.8.3';state.compatible=true;state.available=false;
 state.installation={status:'complete',target_version:'0.8.3',files_verified:7,message:'Done. Running app and installed plugin match the approved build.'};
 await button(page,'Verify Installation').click();
 await expect(page.getByText('Done. Running app and installed plugin match the approved build.',{exact:true})).toBeVisible();
});

test('Update Everything cancellation and repeated presses cannot queue duplicate updates',async({page})=>{
 const {calls}=await setup(page,{separate:false,token:'c'.repeat(64)});
 await button(page,'Update Everything').click();await button(page,'Cancel').click();
 expect(calls.some(c=>c.name==='update_app'||c.name==='prepare_plugin_file')).toBe(false);
 await button(page,'Update Everything').click();await button(page,'Confirm').dblclick();
 await expect.poll(()=>calls.filter(c=>c.name==='update_app').length).toBe(1);
 await expect(button(page,'Update Everything')).toBeDisabled();
});

test('source text version without a healthy running app never prepares the plugin',async({page})=>{
 const {calls}=await setup(page,{separate:false,token:'d'.repeat(64),app_installed:'0.8.3',app_running:'0.8.2',app_healthy:false});
 await button(page,'Update Everything').click();await button(page,'Confirm').click();
 await expect(page.getByText(/Waiting for app/)).toBeVisible();
 expect(calls.some(c=>c.name==='prepare_plugin_file')).toBe(false);
});

test('plugin rollback uses local ZIP without clipboard or URL dependency',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw Error('denied');}}}));
 const {calls}=await setup(page,{separate:false});
 await button(page,'Restore Previous Plugin').click();await button(page,'Confirm').click();
 await expect(button(page,'Open Decky Installer')).toBeVisible();
 expect(calls.find(c=>c.name==='prepare_plugin_file').args).toEqual(['',true]);
 expect(calls.some(c=>c.name==='plugin_handoff')).toBe(false);
 await expect(page.getByText(/No URL or clipboard is needed/)).toBeVisible();
});

test('pending approved flow resumes preparation after panel reload without queuing the app again',async({page})=>{
 const {calls,state}=await setup(page,{separate:false,token:'e'.repeat(64)});
 await button(page,'Update Everything').click();await button(page,'Confirm').click();
 await expect.poll(()=>calls.filter(c=>c.name==='update_app').length).toBe(1);
 await button(page,'Back').click();state.app_installed='0.8.3';state.app_running='0.8.3';state.app_healthy=true;state.app_first=false;state.app_needed=false;
 await button(page,'Updates').click();
 await expect.poll(()=>calls.filter(c=>c.name==='prepare_plugin_file').length).toBe(1);
 expect(calls.filter(c=>c.name==='update_app')).toHaveLength(1);
});

test('a changed approval token cancels auto preparation and never installs another selection',async({page})=>{
 const {calls,state}=await setup(page,{separate:false,token:'f'.repeat(64)});
 await button(page,'Update Everything').click();await button(page,'Confirm').click();
 await expect.poll(()=>calls.filter(c=>c.name==='update_app').length).toBe(1);
 state.token='a'.repeat(64);state.app_installed='0.8.3';state.app_running='0.8.3';state.app_healthy=true;
 await expect(page.getByText('Update selection changed. Review the new update before continuing.',{exact:true})).toBeVisible({timeout:10000});
 expect(calls.some(c=>c.name==='prepare_plugin_file')).toBe(false);
});

test('same-version wrong plugin bytes are not a successful update',async({page})=>{
 await setup(page,{separate:false,installation:{status:'changed',target_version:'0.8.3',message:'Plugin files do not match the approved package.'}});
 await expect(page.getByText('Plugin files do not match the approved package.',{exact:true})).toBeVisible();
 await expect(page.getByText(/^Done\./)).toHaveCount(0);
});


test('an older failed operation does not cancel a newly approved update session',async({page})=>{
 const {calls,state}=await setup(page,{separate:false,token:'b'.repeat(64),operation:{status:'error',version:'0.8.3',timestamp_utc:'2020-01-01T00:00:00Z',message:'Earlier attempt failed.'}});
 await button(page,'Update Everything').click();await button(page,'Confirm').click();
 await expect.poll(()=>calls.filter(c=>c.name==='update_app').length).toBe(1);
 await expect(page.getByText(/Waiting for app/)).toBeVisible();
 state.operation={status:'success',version:'0.8.3',timestamp_utc:new Date().toISOString()};
 state.app_installed='0.8.3';state.app_running='0.8.3';state.app_healthy=true;
 await expect.poll(()=>calls.filter(c=>c.name==='prepare_plugin_file').length,{timeout:10000}).toBe(1);
});
