/** Read-only observations from the globals described by @decky/ui.
 * These reverse-engineered UI types are not a supported write-authorisation API.
 * Nothing here calls Steam actions, subscribes to events or declares a game closed.
 */
export type SteamObservation={appid:string;status:'available'|'missing'|'error'|'uninitialized'|'id-mismatch'|'limited';initialized?:boolean;overview_match?:boolean;listed_running?:boolean;local_installed?:boolean;display_status?:number};
export function observeSteam(appid:string,scope:unknown=globalThis):SteamObservation{
 const result:SteamObservation={appid,status:'missing'};
 if(!/^[1-9][0-9]{0,9}$/.test(appid)||Number(appid)>4294967295)return {...result,status:'id-mismatch'};
 try{
  const globals=scope as {appStore?:{m_bIsInitialized?:unknown;GetAppOverviewByAppID?:(id:number)=>unknown};SteamUIStore?:{RunningApps?:unknown}};
  const store=globals.appStore;
  if(typeof store?.GetAppOverviewByAppID!=='function')return result;
  if(typeof store.m_bIsInitialized==='boolean')result.initialized=store.m_bIsInitialized;
  if(result.initialized!==true)return {...result,status:'uninitialized'};
  const overview=store.GetAppOverviewByAppID(Number(appid)) as {appid?:unknown;local_per_client_data?:{display_status?:unknown;installed?:unknown}}|null;
  if(!overview||overview.appid!==Number(appid))return {...result,status:'id-mismatch',overview_match:false};
  result.overview_match=true;result.status='available';
  const local=overview.local_per_client_data;
  if(typeof local?.installed==='boolean')result.local_installed=local.installed;
  if(typeof local?.display_status==='number'&&Number.isInteger(local.display_status)&&local.display_status>=0&&local.display_status<=40)result.display_status=local.display_status;
  const running=globals.SteamUIStore?.RunningApps;
  if(Array.isArray(running)){
   if(running.length>256)return {...result,status:'limited'};
   if(running.every(v=>v&&Number.isInteger(v.appid)))result.listed_running=running.some(v=>v.appid===Number(appid));
  }
  return result;
 }catch{return {...result,status:'error'};}
}
