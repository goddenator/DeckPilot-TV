import { callable } from '@decky/api';
import type { LaunchPlan } from './launchController';

export type Mode = 'graphics' | 'performance' | 'balanced';
export type Profile = 'docked' | 'handheld';
export type Result = {uncertain?:boolean;ok?:boolean;error?:string;message?:string};
export type Game = {appid:string;name:string;mode?:Mode;supported?:boolean;adapter?:string;approved?:boolean;metrics?:{avg_fps:number;low_1pct_fps:number;frame_time_p95_ms?:number;measurement_note?:string}};
export type UpdateSuite = Result & {app_running?:string;app_healthy?:boolean;installation?:{status:string;message:string;target_version?:string;files_verified?:number;kind?:string};protocol?:number;channel?:string;repository?:string;app_installed?:string;plugin_installed?:string;compatible?:boolean;status?:string;operation?:{status?:string;message?:string;version?:string;timestamp_utc?:string};available?:boolean;version?:string;token?:string;commit?:string;app_needed?:boolean;plugin_needed?:boolean;downgrade?:boolean;app_first?:boolean;app_rollback?:boolean;plugin_rollback?:boolean;recovery_required?:boolean};
export type State = Result & {
  plugin_version?:string;update_suite?:UpdateSuite;
  version?:string;build_id?:string;schema_version?:number;context?:Profile;default?:Mode;
  profiles?:Record<Profile,{default:Mode;games:Record<string,Mode>}>;
  games?:Game[];saved_games?:Record<string,Mode>;measurements_enabled?:boolean;
  cloud?:{enabled?:boolean;connection?:string;last_status?:string};
  launch_prompt?:{protocol?:number;enabled:boolean;available:boolean;native_play?:boolean;method?:string;dismissed?:string[];reason:string};
  display?:{vrr_capability:string;vrr_enabled:string;note:string;external_outputs:{connector:string;advertised_modes:string[]}[]};
  update?:{available?:boolean;version?:string;can_undo?:boolean;status?:string;github?:{message?:string}};
};
export type Checkup = Result & {supported_files?:number;verified_files?:number;coverage?:{message?:string;partial?:boolean;native_checks?:Record<string,boolean>;probes?:{kind:string;status:string;known_keys:number}[]};process?:{state?:string;reason?:string;appid?:string;message?:string;counts?:Record<string,number>};status?:string;optimised?:boolean;can_restore?:boolean;backups?:number};
export type Report = {source:string;url:string;device:string;game_version?:string;report_date?:string;retrieved_at:string;resolution?:string;fps?:string;fps_kind?:string;report_id?:string;display_context:string;summary:string;uncertainty:string;stale?:boolean};
export type Research = Result & {game?:Game;reports?:Report[];recommendation?:{mode:Mode;confidence:string;reason:string;note:string};sources?:{source:string;status:string;url:string;page_url?:string;message?:string;cached?:boolean;stale?:boolean}[]};
export type Preview = Result & {status?:string;token?:string;summary?:{resolution:string;quality?:string;files:number;manual_files:number};files?:{file:string;location?:string;adapter:string;manual_changes:boolean;changes:{key:string;before?:string;after:string}[]}[]};
export const api = {
  recordEvidence: callable<[string,string,import('./steamEvidence').SteamObservation],Result & {evidence?:{appid:string;proc_state:string;proc_reason:string;steam_ui:{status:string;listed_running?:boolean;display_status?:number}}}>('record_game_evidence'),
  processState:callable<[string,Profile],{state?:string}>('process_state'),
  getUpdates: callable<[],UpdateSuite>('get_updates'),
  checkUpdates: callable<[],UpdateSuite>('check_updates'),
  setUpdateChannel: callable<[string],Result>('set_update_channel'),
  updateApp: callable<[string,boolean],Result>('update_app'),
  verifyUpdateInstallation: callable<[],Result>('verify_update_installation'),
  preparePluginFile: callable<[string,boolean],Result & {version?:string;folder?:string;file?:string}>('prepare_plugin_file'),
  pluginHandoff: callable<[string,boolean],Result & {url?:string}>('plugin_handoff'),
  playAssistant: callable<[boolean],Result>('set_play_assistant'),
  playPlan: callable<[string,Profile],LaunchPlan>('play_plan'),
  playPreview: callable<[string,Mode,Profile],Preview>('play_preview'),
  playApprove: callable<[string,Mode,string,Profile],Result>('play_approve'),
  dismissPlay: callable<[string,boolean],Result>('dismiss_play_advice'),
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
