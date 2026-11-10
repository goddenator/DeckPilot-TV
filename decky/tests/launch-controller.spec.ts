import { test,expect } from '@playwright/test';
import { LaunchController } from '../src/launchController';
import type { LaunchPorts, LaunchPlan, LaunchTarget } from '../src/launchController';

const target:LaunchTarget={appid:'1234',name:'My Game',context:'docked',installed:true,enabled:true};
const plan:LaunchPlan={ok:true,status:'prompt',appid:'1234',context:'docked',can_apply:true,recommendation:{mode:'balanced',confidence:'none',reason:'No cache',note:'Starting point'}};
function deferred<T>(){let resolve!:(v:T)=>void;let reject!:(e:Error)=>void;const promise=new Promise<T>((r,j)=>{resolve=r;reject=j;});return {resolve,reject,promise};}
function fixture(overrides:Partial<LaunchPorts>={}){
 const calls:{name:string;args:unknown[]}[]=[];
 const ports:LaunchPorts={
  plan:async(...args)=>{calls.push({name:'plan',args});return plan;},
  preview:async(...args)=>{calls.push({name:'preview',args});return {ok:true,status:'preview',token:'exact-content-token',files:[{file:'settings.ini',adapter:'unreal',manual_changes:false,changes:[{key:'ResolutionSizeX',before:'800',after:'1920'}]}]};},
  approve:async(...args)=>{calls.push({name:'approve',args});return {ok:true};},
  dismiss:async(...args)=>{calls.push({name:'dismiss',args});return {ok:true};},
  available:()=>true,launch:(...args)=>{calls.push({name:'launch',args});},readTimeoutMs:30,
  ...overrides,
 };
 return {controller:new LaunchController(ports),calls,ports};
}

test('disabled, uninstalled and non-Steam targets perform no work',async()=>{
 const {controller,calls}=fixture();
 for(const t of [{...target,enabled:false},{...target,installed:false},{...target,appid:'0'},{...target,appid:'18446744073709551615'}])await controller.start(t);
 expect(calls).toEqual([]);expect(controller.getSnapshot().phase).toBe('idle');
});

test('missing or throwing launch API cannot modify files',async()=>{
 for(const available of [()=>false,()=>{throw Error('API disappeared');}]){
  const {controller,calls}=fixture({available});await controller.start(target);
  expect(controller.getSnapshot().phase).toBe('error');expect(calls).toEqual([]);
 }
});

test('unavailable or hanging local advice falls back once without preview or apply',async()=>{
 for(const fn of [async()=>{throw Error('offline');},()=>new Promise<LaunchPlan>(()=>{})]){
  const {controller,calls}=fixture({plan:fn});await controller.start(target);
  expect(controller.getSnapshot().phase).toBe('launched');expect(calls).toEqual([{name:'launch',args:['1234']}]);
 }
});

test('disabled and dismissed plans launch normally with no settings operations',async()=>{
 for(const status of ['disabled','dismissed']){
  const {controller,calls}=fixture({plan:async()=>({status,ok:true,appid:'1234'})});await controller.start(target);
  expect(calls).toEqual([{name:'launch',args:['1234']}]);
 }
});

test('wrong IDs, changed profiles and running/uninstalled games never dispatch',async()=>{
 for(const response of [{...plan,appid:'9999'},{...plan,context:'handheld' as const},{status:'running',ok:false},{status:'not-installed',ok:false},{status:'profile-changed',ok:false}]){
  const {controller,calls}=fixture({plan:async()=>response});await controller.start(target);
  expect(controller.getSnapshot().phase).toBe('error');expect(calls).toEqual([]);
 }
});

test('repeated presses and synchronous launch reentry cannot double launch',async()=>{
 const waiting=deferred<LaunchPlan>();const {controller,calls,ports}=fixture({plan:()=>waiting.promise});
 const first=controller.start(target);await controller.start(target);await controller.start({...target,appid:'5678'});
 waiting.resolve(plan);await first;
 ports.launch=id=>{calls.push({name:'launch',args:[id]});void controller.start(target);void controller.playWithoutChanges();};
 await Promise.all([controller.playWithoutChanges(),controller.playWithoutChanges(),controller.dontAskAgain()]);
 expect(calls.filter(c=>c.name==='launch')).toHaveLength(1);expect(calls.filter(c=>c.name==='approve')).toHaveLength(0);
 controller.cancel();await controller.start(target);expect(controller.getSnapshot().phase).toBe('error');
 expect(calls.filter(c=>c.name==='launch')).toHaveLength(1);
});

test('cancellation invalidates late plan and preview results without launching or applying',async()=>{
 const waiting=deferred<LaunchPlan>();const {controller,calls}=fixture({plan:()=>waiting.promise});
 const start=controller.start(target);expect(controller.cancel()).toBe(true);waiting.resolve(plan);await start;
 expect(controller.getSnapshot().phase).toBe('idle');expect(calls).toEqual([]);
 const preview=deferred<any>();const next=fixture({preview:()=>preview.promise});await next.controller.start(target);
 const review=next.controller.review();next.controller.cancel();preview.resolve({ok:true,status:'preview',token:'stale'});await review;
 expect(next.controller.getSnapshot().phase).toBe('idle');expect(next.calls.some(c=>c.name==='launch'||c.name==='approve')).toBe(false);
});

test('exact captured ID, profile, mode and token must be explicitly approved',async()=>{
 const {controller,calls}=fixture();await controller.start(target);controller.selectMode('graphics');await controller.review();
 expect(controller.getSnapshot().phase).toBe('review');expect(calls.filter(c=>c.name==='approve'||c.name==='launch')).toEqual([]);
 controller.selectMode('performance'); // cannot change a reviewed mode without another preview
 await Promise.all([controller.approve(),controller.approve()]);
 expect(calls.find(c=>c.name==='approve')?.args).toEqual(['1234','graphics','exact-content-token','docked']);
 expect(calls.filter(c=>c.name==='approve')).toHaveLength(1);expect(calls.filter(c=>c.name==='launch')).toHaveLength(1);
});

test('unsupported or failed previews cannot apply and still allow playing unchanged',async()=>{
 const unsupported=fixture({plan:async()=>({...plan,can_apply:false})});await unsupported.controller.start(target);await unsupported.controller.review();
 expect(unsupported.calls).toEqual([]);await unsupported.controller.playWithoutChanges();expect(unsupported.calls).toEqual([{name:'launch',args:['1234']}]);
 const failed=fixture({preview:async()=>{throw Error('file changed');}});await failed.controller.start(target);await failed.controller.review();
 expect(failed.controller.getSnapshot().phase).toBe('prompt');expect(failed.calls.some(c=>c.name==='approve')).toBe(false);
});

test('known apply rejection permits explicit Play Without Changes, never auto-launches',async()=>{
 const {controller,calls}=fixture({approve:async()=>({ok:false,error:'Preview changed'})});await controller.start(target);await controller.review();await controller.approve();
 expect(controller.getSnapshot().phase).toBe('prompt');expect(calls.filter(c=>c.name==='launch')).toHaveLength(0);
 await controller.playWithoutChanges();expect(calls.filter(c=>c.name==='launch')).toHaveLength(1);
});

test('unknown apply failure never launches, retries, or permits another controlled apply',async()=>{
 const {controller,calls}=fixture({approve:async()=>{throw Error('transport disconnected');}});await controller.start(target);await controller.review();await controller.approve();
 expect(controller.getSnapshot().uncertain).toBe(true);await controller.playWithoutChanges();expect(calls.filter(c=>c.name==='launch')).toHaveLength(0);
 controller.cancel();await controller.start(target);expect(controller.getSnapshot().phase).toBe('error');expect(calls.filter(c=>c.name==='launch')).toHaveLength(0);
});

test('an in-flight approved mutation is not timed out into a concurrent launch',async()=>{
 const waiting=deferred<{ok:boolean}>();const {controller,calls}=fixture({approve:()=>waiting.promise,readTimeoutMs:5});await controller.start(target);await controller.review();
 const apply=controller.approve();expect(controller.cancel()).toBe(false);
 await new Promise(r=>setTimeout(r,15));expect(controller.getSnapshot().phase).toBe('applying');expect(calls.filter(c=>c.name==='launch')).toHaveLength(0);
 waiting.resolve({ok:true});await apply;expect(calls.filter(c=>c.name==='launch')).toHaveLength(1);
});

test('Don’t Ask Again remembers exact game and launches without settings changes',async()=>{
 const {controller,calls}=fixture();await controller.start(target);await controller.dontAskAgain();
 expect(calls.find(c=>c.name==='dismiss')?.args).toEqual(['1234',true]);
 expect(calls.filter(c=>c.name==='preview'||c.name==='approve')).toEqual([]);expect(calls.filter(c=>c.name==='launch')).toHaveLength(1);
});

test('failure to remember a dismissal does not trap the controlled launch',async()=>{
 const {controller,calls}=fixture({dismiss:async()=>{throw Error('disk full');}});await controller.start(target);await controller.dontAskAgain();
 expect(controller.getSnapshot().message).toContain('Could not remember');expect(calls.filter(c=>c.name==='launch')).toHaveLength(1);
});

test('launch throw, rejection or timeout never automatically retries or relaunches',async()=>{
 for(const launch of [()=>{throw Error('Steam API failed');},()=>Promise.reject(Error('Steam API failed')),()=>new Promise<void>(()=>{})]){
  let count=0;const {controller}=fixture({launch:()=>{count++;return launch();}});await controller.start(target);await controller.playWithoutChanges();
  expect(controller.getSnapshot().phase).toBe('error');controller.cancel();await controller.start(target);await controller.playWithoutChanges();expect(count).toBe(1);
 }
});

test('unload cancels queued launch after approval and does not register a relaunch hook',async()=>{
 const waiting=deferred<{ok:boolean}>();const {controller,calls}=fixture({approve:()=>waiting.promise});await controller.start(target);await controller.review();
 const applying=controller.approve();controller.dispose();waiting.resolve({ok:true});await applying;
 expect(calls.filter(c=>c.name==='launch')).toHaveLength(0);expect(controller.getSnapshot().phase).toBe('idle');
});


test('launcher loss before approval prevents settings writes',async()=>{
 let available=true;const {controller,calls}=fixture({available:()=>available});
 await controller.start(target);await controller.review();available=false;await controller.approve();
 expect(controller.getSnapshot().phase).toBe('error');expect(calls.some(c=>c.name==='approve'||c.name==='launch')).toBe(false);
});

test('an uncertain native launch is not retried even after the cooldown',async()=>{
 let now=0,count=0;const {controller}=fixture({now:()=>now,launch:()=>{count++;throw Error('Unknown launch result');}});
 await controller.start(target);await controller.playWithoutChanges();controller.cancel();now=60000;
 await controller.start(target);await controller.playWithoutChanges();expect(count).toBe(1);
});

test('cancelling a pending dismissal invalidates its late launch callback',async()=>{
 const waiting=deferred<{ok:boolean}>();const {controller,calls}=fixture({dismiss:()=>waiting.promise});
 await controller.start(target);const remember=controller.dontAskAgain();controller.cancel();waiting.resolve({ok:true});await remember;
 expect(controller.getSnapshot().phase).toBe('idle');expect(calls.some(c=>c.name==='launch'||c.name==='approve')).toBe(false);
});
