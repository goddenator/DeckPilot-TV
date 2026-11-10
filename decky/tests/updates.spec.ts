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
  if(name==='plugin_handoff')result={url:'http://127.0.0.1:45678/'+'a'.repeat(43)+'/DeckPilot.zip'};
  await route.fulfill({json:result});
 });
 await page.goto('/');await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:'Updates',exact:true}).click();
 await expect(page.getByText('App '+state.app_installed+' · Plugin '+state.plugin_installed)).toBeVisible();return {state,calls};
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
 const {calls}=await setup(page);await button(page,'Restore Previous Plugin').click();await button(page,'Confirm').click();
 await expect(page.getByRole('status')).toHaveText(/Clipboard unavailable/);await expect(page.getByRole('textbox')).toBeVisible();
 expect(calls.find(c=>c.name==='plugin_handoff').args).toEqual(['',true]);
});
test('mismatch pauses game profile mutation and recovery remains available',async({page})=>{
 await setup(page,{compatible:false,recovery_required:true});await expect(page.getByText(/versions differ/)).toBeVisible();await expect(button(page,'Recover Interrupted Update')).toBeVisible();
 await button(page,'Back').click();await button(page,'Back').click();await expect(page.getByRole('button',{name:/Best Graphics/})).toBeDisabled();
});
