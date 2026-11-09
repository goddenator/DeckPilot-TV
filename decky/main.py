"""Decky bridge to DeckPilot's user-space service; NO root requirement."""
import asyncio
import json
import os
from pathlib import Path

import decky

HOME = Path(decky.DECKY_USER_HOME)
APP = HOME / '.local/share/deckpilot-tv/app/deckpilot.py'

class Plugin:
    async def _run(self, *args):
        if not APP.is_file():
            return {'ok': False, 'error': 'Install DeckPilot TV app first.'}
        try:
            proc = await asyncio.create_subprocess_exec(
                '/usr/bin/python3', str(APP), *args,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, 'HOME': str(HOME)},
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return {'ok': False, 'error': 'DeckPilot took too long to respond.'}
            if proc.returncode:
                return {'ok': False, 'error': 'DeckPilot command failed: '+stderr.decode(errors='replace')[:250]}
            raw=stdout.decode(errors='replace').strip()
            try: return json.loads(raw)
            except ValueError: return {'ok': True, 'message': raw[:250]}
        except (OSError, ValueError) as exc:
            return {'ok': False, 'error': 'Cannot run the local DeckPilot service.'}

    async def get_state(self):
        return await self._run('plugin-state')

    async def set_mode(self, mode: str, appid: str = ''):
        if mode not in ('graphics', 'performance', 'balanced'):
            return {'ok': False, 'error': 'Unknown mode'}
        if appid and not appid.isdigit():
            return {'ok': False, 'error': 'Invalid game id'}
        args=['set-mode']
        if appid: args.append(appid)
        args += ['--mode', mode]
        return await self._run(*args)

    async def check_github(self):
        return await self._run('check-github')

    async def install_update(self):
        return await self._run('install-update')

    async def rollback_update(self):
        return await self._run('rollback-update')

    async def _main(self):
        decky.logger.info('DeckPilot TV plugin started')
