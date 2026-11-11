"""Decky bridge: every app operation runs as deck, including from root Decky."""
import asyncio
import json
import os
from pathlib import Path
import pwd
import decky


def deck_command_environment():
    account = pwd.getpwnam('deck')
    home = Path(account.pw_dir)
    if home != Path(decky.DECKY_USER_HOME) or account.pw_uid == 0:
        raise ValueError('Decky home does not match the deck account.')
    if os.geteuid() not in (0, account.pw_uid):
        raise ValueError('DeckPilot must run as deck.')
    runtime = '/run/user/' + str(account.pw_uid)
    env = {key: value for key, value in os.environ.items()
           if key in ('PATH', 'LANG', 'LC_ALL', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY',
                      'https_proxy', 'http_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
    env.update(HOME=str(home), USER='deck', LOGNAME='deck', XDG_RUNTIME_DIR=runtime,
               XDG_CONFIG_HOME=str(home/'.config'), XDG_DATA_HOME=str(home/'.local/share'),
               DBUS_SESSION_BUS_ADDRESS='unix:path='+runtime+'/bus')
    identity = ({'user': account.pw_uid, 'group': account.pw_gid,
                 'extra_groups': os.getgrouplist('deck', account.pw_gid)} if os.geteuid() == 0 else {})
    return home, env, identity


class Plugin:
    async def _run(self, *args, update_helper=False):
        try:
            home, env, identity = deck_command_environment()
            app = Path(__file__).with_name('update_client.py') if update_helper else home / '.local/share/deckpilot-tv/app/deckpilot.py'
            if not app.is_file(): return {'ok': False, 'error': 'Install DeckPilot TV app first.'}
            proc = await asyncio.create_subprocess_exec(
                '/usr/bin/python3', str(app), *args, cwd=str(home),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, **identity)
            try: stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180 if update_helper and args and args[0]=='suite-check' else 120 if args and args[0]=='cloud-upload' else 45)
            except asyncio.TimeoutError:
                proc.kill(); await proc.communicate()
                return {'ok': False,'uncertain':args[0] in ('approve','play-approve'), 'error': 'DeckPilot timed out. Check settings before retrying.'}
            if proc.returncode: return {'ok': False,'uncertain':args[0] in ('approve','play-approve'), 'error': 'DeckPilot command failed. Check local diagnostics.'}
            raw = stdout.decode(errors='replace').strip()
            try: return json.loads(raw)
            except ValueError:
                if args[0] in ('approve','play-approve'):return {'ok':False,'uncertain':True,'error':'Apply result is unknown. Check settings and use Steam.'}
                return {'ok': True, 'message': raw[:250]}
        except (OSError, ValueError, KeyError):
            return {'ok': False, 'error': 'Cannot run DeckPilot as deck. Verify the app installation and Decky user configuration.'}

    def _plugin_version(self):
        try:return json.loads(Path(__file__).with_name('package.json').read_text())['version']
        except (OSError,ValueError,KeyError):return 'unknown'

    async def get_state(self):
        state=await self._run('plugin-state')
        if not isinstance(state,dict):state={'ok':False,'error':'App state unavailable.'}
        state['plugin_version']=self._plugin_version()
        state['update_suite']=await self.get_updates()
        return state

    async def process_state(self, appid: str, context: str):
        return await self._run('process-status',str(appid),'--context',context)

    async def get_updates(self):
        return await self._run('suite-status','--plugin-version',self._plugin_version(),'--plugin-dir',str(Path(__file__).parent),update_helper=True)
    async def check_updates(self):
        return await self._run('suite-check','--plugin-version',self._plugin_version(),'--plugin-dir',str(Path(__file__).parent),update_helper=True)
    async def verify_update_installation(self):
        return await self._run('suite-verify','--plugin-dir',str(Path(__file__).parent),update_helper=True)
    async def set_update_channel(self, channel: str):
        if channel not in ('stable','preview'):return {'ok':False,'error':'Unknown channel'}
        return await self._run('suite-channel','--channel',channel,update_helper=True)
    async def update_app(self, token: str, downgrade: bool=False):
        if not isinstance(downgrade,bool):return {'ok':False,'error':'Expected approval'}
        return await self._run('suite-install','--token',token,*(['--allow-downgrade'] if downgrade else []),update_helper=True)
    async def prepare_plugin_file(self, token: str='', rollback: bool=False):
        if not isinstance(rollback,bool):return {'ok':False,'error':'Expected approval'}
        return await self._run('plugin-prepare-rollback' if rollback else 'plugin-prepare-file',
                               '--token',str(token),'--plugin-dir',str(Path(__file__).parent),update_helper=True)

    async def plugin_handoff(self, token: str='', rollback: bool=False):
        if not isinstance(rollback,bool):return {'ok':False,'error':'Expected approval'}
        return await self._run('plugin-rollback' if rollback else 'plugin-handoff','--token',token,'--plugin-dir',str(Path(__file__).parent),update_helper=True)

    async def set_mode(self, mode: str, appid: str = '', context: str = ''):
        if mode not in ('graphics', 'performance', 'balanced'): return {'ok': False, 'error': 'Unknown mode'}
        if appid and (not appid.isascii() or not appid.isdigit()): return {'ok': False, 'error': 'Invalid game id'}
        return await self._run('set-mode', *([appid] if appid else []), '--mode', mode, *(['--context', context] if context else []))
    async def search_games(self, query: str): return await self._run('search', str(query)[:120])
    async def research_game(self, appid: str, context: str = ''):
        return await self._run('research', str(appid), *(['--context', context] if context else []))
    async def preview(self, appid: str, mode: str, context: str = ''):
        return await self._run('preview', str(appid), '--mode', str(mode), *(['--context', context] if context else []))
    async def approve(self, appid: str, mode: str, token: str, context: str = ''):
        return await self._run('approve', str(appid), '--mode', str(mode), '--preview-token', str(token), *(['--context', context] if context else []))
    async def restore(self, appid: str):
        if not isinstance(appid, str) or not appid.isascii() or not appid.isdigit(): return {'ok': False, 'error': 'Invalid game id'}
        return await self._run('restore', appid)
    async def set_context(self, context: str): return await self._run('set-context', '--context', context)
    async def get_checkup(self, appid: str, context: str):
        return await self._run('checkup', str(appid), '--context', context)
    async def set_measurements(self, enabled: bool):
        if not isinstance(enabled, bool): return {'ok': False, 'error': 'Expected on/off'}
        return await self._run('measurements-enable' if enabled else 'measurements-disable')
    async def record_game_evidence(self, appid: str, reference: str, observation: dict):
        if not isinstance(observation,dict) or len(json.dumps(observation))>4096:return {'ok':False,'error':'Invalid observation'}
        return await self._run('record-game-evidence',str(appid),'--reference',str(reference),'--observation',json.dumps(observation))
    async def diagnostics(self): return await self._run('export')
    async def cloud_action(self, action: str):
        if action not in ('enable', 'disable', 'upload'): return {'ok': False, 'error': 'Unknown diagnostics action'}
        return await self._run('cloud-'+action)
    async def set_play_assistant(self, enabled: bool):
        if not isinstance(enabled, bool): return {'ok':False,'error':'Expected on/off'}
        return await self._run('play-enable' if enabled else 'play-disable')
    async def play_plan(self, appid: str, context: str):
        return await self._run('play-plan','--launch-protocol','2', str(appid), '--context', context)
    async def play_preview(self, appid: str, mode: str, context: str):
        return await self._run('play-preview', str(appid), '--mode', mode, '--context', context)
    async def play_approve(self, appid: str, mode: str, token: str, context: str):
        return await self._run('play-approve', str(appid), '--mode', mode, '--preview-token', token, '--context', context)
    async def dismiss_play_advice(self, appid: str, dismissed: bool):
        if not isinstance(dismissed, bool): return {'ok':False,'error':'Expected on/off'}
        return await self._run('play-dismiss' if dismissed else 'play-reset', str(appid))
    async def check_github(self): return await self.check_updates()
    async def install_update(self): return await self._run('install-update')
    async def rollback_update(self): return await self._run('suite-rollback',update_helper=True)
    async def _main(self): decky.logger.info('DeckPilot TV plugin started')
