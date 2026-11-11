/** Only a prior explicit Update Everything approval may resume non-installing preparation. */
export type UpdateSession={version:string;token:string;channel:string;started:number};
const key='deckpilot-approved-update-v1';
export function readUpdateSession():UpdateSession|undefined{
 try{
  const raw=localStorage.getItem(key);if(!raw||raw.length>1024)return;
  const v=JSON.parse(raw) as UpdateSession;
  if(!/^\d+\.\d+\.\d+(?:-preview\.\d+)?$/.test(v.version)||! /^[a-f0-9]{64}$/.test(v.token)||!['stable','preview'].includes(v.channel)||!Number.isFinite(v.started)||Date.now()-v.started<0||Date.now()-v.started>30*60*1000)return;
  return v;
 }catch{return;}
}
export function saveUpdateSession(value?:UpdateSession){try{if(value)localStorage.setItem(key,JSON.stringify(value));else localStorage.removeItem(key);}catch{/* No persistence: current panel still works. */}}
