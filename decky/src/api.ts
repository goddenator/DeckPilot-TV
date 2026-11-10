import { callable } from '@decky/api';

export type Mode = 'graphics' | 'performance' | 'balanced';
export type Profile = 'docked' | 'handheld';
export type Result = {ok?:boolean;error?:string;message?:string};
export type Game = {appid:string;name:string;mode?:Mode;supported?:boolean;adapter?:string;approved?:boolean;metrics?:{avg_fps:number;low_1pct_fps:number;frame_time_p95_ms?:number;measurement_note?:string}};
export type State = Result & {
  version?:string;schema_version?:number;context?:Profile;default?:Mode;
  profiles?:Record<Profile,{default:Mode;games:Record<string,Mode>}>;
  games?:Game[];saved_games?:Record<string,Mode>;measurements_enabled?:boolean;
  cloud?:{enabled?:boolean;connection?:string;last_status?:string};
  launch_prompt?:{enabled:boolean;available:boolean;reason:string};
  display?:{vrr_capability:string;vrr_enabled:string;note:string;external_outputs:{connector:string;advertised_modes:string[]}[]};
  update?:{available?:boolean;version?:string;can_undo?:boolean;status?:string;github?:{message?:string}};
};
export type Checkup = Result & {status?:string;optimised?:boolean;can_restore?:boolean;backups?:number};
export type Report = {source:string;url:string;device:string;game_version?:string;report_date?:string;retrieved_at:string;resolution?:string;fps?:string;fps_kind?:string;report_id?:string;display_context:string;summary:string;uncertainty:string;stale?:boolean};
export type Research = Result & {game?:Game;reports?:Report[];recommendation?:{mode:Mode;confidence:string;reason:string;note:string};sources?:{source:string;status:string;url:string;page_url?:string;message?:string;cached?:boolean;stale?:boolean}[]};
export type Preview = Result & {status?:string;token?:string;summary?:{resolution:string;quality?:string;files:number;manual_files:number};files?:{file:string;adapter:string;manual_changes:boolean;changes:{key:string;before?:string;after:string}[]}[]};
export const api = {
  state: callable<[],State>('get_state'),
  mode: callable<[Mode,string,Profile],Result>('set_mode'),
  context: callable<[Profile],Result>('set_context'),
  search: callable<[string],Result & {games?:Game[]}>('search_games'),
  research: callable<[string,Profile],Research>('research_game'),
  checkup: callable<[string,Profile],Checkup>('get_checkup'),
  preview: callable<[string,Mode,Profile],Preview>('preview'),
  approve: callable<[string,Mode,string,Profile],Result>('approve'),
  restore: callable<[string],Result>('restore'),
  measurements: callable<[boolean],Result>('set_measurements'),
  diagnostics: callable<[],Result>('diagnostics'),
  cloud: callable<[string],Result>('cloud_action'),
  checkUpdate: callable<[],Result>('check_github'),
  installUpdate: callable<[],Result>('install_update'),
  rollbackUpdate: callable<[],Result>('rollback_update'),
};
