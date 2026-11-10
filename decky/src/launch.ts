import { api } from './api';
import { LaunchController } from './launchController';
export * from './launchController';

type SteamApps={RunGame?:(id:string,options:string,launchOption:number,source:number)=>void|Promise<void>};
const steamApps=()=> (globalThis as unknown as {SteamClient?:{Apps?:SteamApps}}).SteamClient?.Apps;
export const launchController=new LaunchController({
  plan:api.playPlan,preview:api.playPreview,approve:api.playApprove,dismiss:api.dismissPlay,
  available:()=>typeof steamApps()?.RunGame==='function',
  launch:(id)=>{
    const apps=steamApps();if(!apps?.RunGame)throw Error('Steam launch API unavailable');
    // Standard library-details launch, default launch choice. Never rewrite stored launch options.
    return apps.RunGame(id,'',-1,100);
  },
});
