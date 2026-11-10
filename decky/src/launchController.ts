import type { Mode, Preview, Profile, Result } from './api';

export type LaunchTarget={appid:string;name:string;context:Profile;installed:boolean;enabled:boolean};
export type LaunchPlan=Result & {status?:string;appid?:string;context?:Profile;name?:string;saved_mode?:Mode;can_apply?:boolean;report_count?:number;sources?:string[];stale?:boolean;display_match?:boolean;resolution?:string;fps?:string;fps_kind?:string;recommendation?:{mode:Mode;confidence:string;reason:string;note:string}};
export type LaunchPhase='idle'|'loading'|'prompt'|'previewing'|'review'|'remembering'|'applying'|'launching'|'launched'|'error';
export type LaunchState={phase:LaunchPhase;target?:LaunchTarget;mode?:Mode;plan?:LaunchPlan;preview?:Preview;message?:string;uncertain?:boolean};
export interface LaunchPorts {
  plan:(id:string,context:Profile)=>Promise<LaunchPlan>;
  preview:(id:string,mode:Mode,context:Profile)=>Promise<Preview>;
  approve:(id:string,mode:Mode,token:string,context:Profile)=>Promise<Result>;
  dismiss:(id:string,value:boolean)=>Promise<Result>;
  available:()=>boolean;
  launch:(id:string)=>void|Promise<void>;
  now?:()=>number;
  readTimeoutMs?:number;
}
const validId=(id:string)=>/^[1-9][0-9]{0,9}$/.test(id)&&Number(id)<=4294967295;
const validMode=(mode:unknown):mode is Mode=>mode==='graphics'||mode==='performance'||mode==='balanced';

/** Controlled button only. No Steam observer, cancellation, patch, or relaunch hook. */
export class LaunchController {
  private state:LaunchState={phase:'idle'};
  private listeners=new Set<()=>void>();
  private generation=0;
  private attempts=new Map<string,number>();
  private uncertainMutations=new Set<string>();
  private uncertainLaunches=new Set<string>();
  private mutationPending=false;
  constructor(private ports:LaunchPorts){}
  getSnapshot=()=>this.state;
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
  private update(state:LaunchState){this.state=state;for(const listener of this.listeners)listener();}
  private available(){try{return this.ports.available();}catch{return false;}}
  private current(generation:number){return this.generation===generation;}
  private async read<T>(promise:Promise<T>):Promise<T>{
    let timer:ReturnType<typeof setTimeout>|undefined;
    try{return await Promise.race([promise,new Promise<T>((_,reject)=>{timer=setTimeout(()=>reject(Error('Local service unavailable')),this.ports.readTimeoutMs??3000);})]);}
    finally{if(timer)clearTimeout(timer);}
  }
  async start(target:LaunchTarget){
    if(!target.enabled||!target.installed||!validId(target.appid))return;
    if(this.state.phase!=='idle')return; // includes pending prompts and active launches
    if(this.mutationPending){this.update({phase:'error',target,uncertain:true,message:'An approved settings operation is still in progress. Use Steam after checking settings.'});return;}
    if(this.uncertainLaunches.has(target.appid)){this.update({phase:'error',target,uncertain:true,message:'A launch was already requested. Check Steam before trying again.'});return;}
    if(this.uncertainMutations.has(target.appid)){this.update({phase:'error',target,message:'Previous apply result is unknown. Check settings and use Steam to play.',uncertain:true});return;}
    const now=(this.ports.now??Date.now)();
    if(now-(this.attempts.get(target.appid)??-Infinity)<30000){this.update({phase:'error',target,message:'A launch was already requested. Check Steam before trying again.',uncertain:true});return;}
    const generation=++this.generation;
    const captured={...target};
    this.update({phase:'loading',target:captured,message:'Reading saved advice…'});
    if(!this.available()){this.update({phase:'error',target:captured,message:'Steam launch API unavailable. Use Steam’s Play button.'});return;}
    try{
      const plan=await this.read(this.ports.plan(captured.appid,captured.context));
      if(!this.current(generation))return;
      if(plan.status==='disabled'||plan.status==='dismissed'){await this.dispatch(generation);return;}
      if(plan.status==='running'||plan.status==='not-installed'||plan.status==='profile-changed'){
        this.update({phase:'error',target:captured,message:plan.error||'Use Steam to play or resume this game.'});return;
      }
      if(plan.ok===false||plan.error||plan.status!=='prompt'){
        await this.dispatch(generation,'Advice unavailable. Launch requested without changes.');return;
      }
      if(plan.appid!==captured.appid||plan.context!==captured.context){this.update({phase:'error',target:captured,message:'Game or profile changed. Open the game again.'});return;}
      this.update({phase:'prompt',target:captured,plan,mode:validMode(plan.recommendation?.mode)?plan.recommendation!.mode:'balanced'});
    }catch{
      if(this.current(generation))await this.dispatch(generation,'Advice unavailable. Launch requested without changes.');
    }
  }
  selectMode(mode:Mode){if(this.state.phase==='prompt'&&validMode(mode))this.update({...this.state,mode});}
  async review(){
    const state=this.state;if(state.phase!=='prompt'||!state.target||!state.mode||!state.plan?.can_apply)return;
    const generation=this.generation;
    this.update({...state,phase:'previewing',message:'Preparing exact changes…'});
    try{
      const preview=await this.read(this.ports.preview(state.target.appid,state.mode,state.target.context));
      if(!this.current(generation))return;
      if(preview.ok===false||preview.error||preview.status!=='preview'||!preview.token){this.update({...state,message:preview.error||preview.message||'No safe changes available. Play without changes.'});return;}
      this.update({...state,phase:'review',preview,message:undefined});
    }catch{if(this.current(generation))this.update({...state,message:'Preview unavailable. Nothing applied. You can play without changes.'});}
  }
  async approve(){
    const state=this.state;if(state.phase!=='review'||!state.target||!state.mode||!state.preview?.token)return;
    const generation=this.generation;
    if(!this.available()){this.update({...state,phase:'error',preview:undefined,message:'Steam launch API unavailable. Use Steam’s Play button.'});return;}
    this.mutationPending=true;
    this.update({...state,phase:'applying',message:'Backing up and applying approved settings…'});
    try{
      // Do NOT race a mutation against a timer and launch while it may still write.
      // The bridge confirms completion/termination before returning a result.
      const result=await this.ports.approve(state.target.appid,state.mode,state.preview.token,state.target.context);
      if(!this.current(generation))return;
      if(result.ok!==true||result.error){this.update({...state,phase:'prompt',preview:undefined,message:result.error||result.message||'Settings were not applied. Review again or play without further changes.'});return;}
      await this.dispatch(generation,'Approved settings applied. Launch requested.');
    }catch{
      this.uncertainMutations.add(state.target.appid);
      if(this.current(generation))this.update({...state,phase:'error',preview:undefined,uncertain:true,message:'Apply result unavailable. No automatic launch or retry. Check settings and use Steam to play.'});
    }finally{this.mutationPending=false;}
  }
  async playWithoutChanges(){
    if(this.state.phase==='prompt'||this.state.phase==='review')await this.dispatch(this.generation);
  }
  async dontAskAgain(){
    const state=this.state;if(state.phase!=='prompt'||!state.target)return;
    const generation=this.generation;this.update({...state,phase:'remembering',message:'Saving your choice…'});
    let message='Advice hidden for this game. Launch requested without changes.';
    try{const result=await this.read(this.ports.dismiss(state.target.appid,true));if(result.ok!==true||result.error)message='Could not remember your choice. Launch requested without changes.';}
    catch{message='Could not remember your choice. Launch requested without changes.';}
    if(this.current(generation))await this.dispatch(generation,message);
  }
  private async dispatch(generation:number,message='Launch requested without changes.'){
    if(!this.current(generation)||!this.state.target||['launching','launched'].includes(this.state.phase))return;
    const state=this.state;const target=state.target!;
    if(!this.available()){this.update({...state,phase:'error',message:'Steam launch API unavailable. Use Steam’s Play button.'});return;}
    this.attempts.set(target.appid,(this.ports.now??Date.now)());
    // Mark before RunGame: a synchronous re-entry or repeated press cannot dispatch twice.
    this.update({...state,phase:'launching',message:'Requesting launch…'});
    try{
      await this.read(Promise.resolve(this.ports.launch(target.appid)));
      if(this.current(generation))this.update({...state,phase:'launched',preview:undefined,message});
    }catch{
      this.uncertainLaunches.add(target.appid);
      if(this.current(generation))this.update({...state,phase:'error',preview:undefined,uncertain:true,message:'Steam did not confirm the launch request. Check Steam; no automatic retry.'});
    }
  }
  cancel(){
    if(this.state.phase==='applying'||this.state.phase==='launching')return false;
    ++this.generation;this.update({phase:'idle'});return true;
  }
  dispose(){++this.generation;this.update({phase:'idle'});} // unload never starts/restarts a game
}

