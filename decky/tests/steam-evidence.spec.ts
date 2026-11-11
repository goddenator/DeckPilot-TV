import {test,expect} from '@playwright/test';
import {observeSteam} from '../src/steamEvidence';
const ready=(appid:number,display=11)=>({appStore:{m_bIsInitialized:true,GetAppOverviewByAppID:()=>({appid,display_name:'PRIVATE',owner_account_id:999,local_per_client_data:{installed:true,display_status:display,client_name:'PRIVATE'}})},SteamUIStore:{RunningApps:[] as unknown[]}});
test('missing, uninitialized, mismatched and throwing Steam globals remain diagnostic only',()=>{
 expect(observeSteam('270880',{}).status).toBe('missing');
 const scope=ready(270880);scope.appStore.m_bIsInitialized=false;expect(observeSteam('270880',scope).status).toBe('uninitialized');
 expect(observeSteam('270880',ready(359870)).status).toBe('id-mismatch');
 expect(observeSteam('270880',{appStore:{m_bIsInitialized:true,GetAppOverviewByAppID:()=>{throw Error('private path');}}}).status).toBe('error');
});
test('native and Proton observations bind exact App IDs without exposing other library data',()=>{
 for(const id of ['270880','359870']){
  const scope=ready(Number(id),4);scope.SteamUIStore.RunningApps=[{appid:Number(id)},{appid:42,display_name:'PRIVATE'}];
  const evidence=observeSteam(id,scope);expect(evidence.listed_running).toBe(true);expect(evidence.display_status).toBe(4);
  expect(JSON.stringify(evidence)).not.toContain('PRIVATE');expect(JSON.stringify(evidence)).not.toContain('999');
 }
});
test('ready-to-launch reports absence, never a closed-state authorisation',()=>{
 const evidence=observeSteam('270880',ready(270880));expect(evidence.listed_running).toBe(false);expect(evidence.display_status).toBe(11);
 expect(evidence).not.toHaveProperty('state');expect(evidence).not.toHaveProperty('can_apply');
});
test('malformed and oversized running lists cannot establish absence',()=>{
 const scope=ready(270880);scope.SteamUIStore.RunningApps=[{appid:'270880'}];expect(observeSteam('270880',scope).listed_running).toBeUndefined();
 scope.SteamUIStore.RunningApps=Array.from({length:257},()=>({appid:1}));expect(observeSteam('270880',scope).status).toBe('limited');
 expect(observeSteam('270880',scope).listed_running).toBeUndefined();
});
