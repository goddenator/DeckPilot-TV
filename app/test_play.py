"""Controlled Play is local-only and cannot apply without exact, explicit approval."""
import json
import unittest
import subprocess
import sys
import os
from pathlib import Path
from unittest.mock import patch
import deckpilot as d
from test_research import GameFixture


class PlayPrototypeTests(GameFixture):
    def test_default_off_and_stale_native_flag_does_not_opt_in(self):
        self.assertFalse(d.config()['play_assistant_enabled'])
        d.atomic_json(d.CONFIG,{'launch_prompts':True})
        self.assertEqual(d.prepare_play('1234')['status'],'disabled')
        self.assertEqual(self.path.read_text(),self.raw)
        with self.assertRaises(ValueError):d.set_play_assistant('on')

    def test_plan_is_cache_only_exact_id_and_context_and_advisory_if_unmatched(self):
        d.set_play_assistant(True)
        now=d.time.time()
        source='ShareDeck'
        report={'appid':'1234','source':source,'url':'https://sharedeck.games/apps/1234',
                'device':'Steam Deck OLED','display_context':'docked','resolution':'1920x1080',
                'fps':'40 FPS','fps_kind':'community reported average','report_date':'2026-11-01','game_version':'1'}
        cache={source+':1234':{'at':now,'value':{'status':'ok','reports':[report,{**report,'appid':'9999'}]}}}
        d.atomic_json(d.BASE/'research-cache.json',cache)
        with patch.object(d,'public_get') as internet,patch.object(d,'permitted_get') as fetch,patch.object(d,'steam_game') as identity,patch.object(d.subprocess,'run') as process:
            plan=d.prepare_play('1234','docked')
            for call in [internet,fetch,identity,process]:call.assert_not_called()
        self.assertEqual(plan['status'],'prompt');self.assertTrue(plan['can_apply'])
        self.assertEqual(plan['report_count'],1);self.assertEqual(plan['resolution'],'1920x1080')
        self.assertEqual(plan['sources'],['ShareDeck']);self.assertEqual(self.path.read_text(),self.raw)
        with patch.object(d.time,'time',return_value=now+31*86400):
            self.assertEqual(d.prepare_play('1234')['report_count'],0)
        cache[source+':1234']['value']['reports']=[{**report,'display_context':'handheld'}]
        d.atomic_json(d.BASE/'research-cache.json',cache)
        plan=d.prepare_play('1234');self.assertFalse(plan['display_match']);self.assertIsNone(plan['fps'])

    def test_no_cache_does_not_fetch_and_unknown_metadata_is_safe(self):
        d.set_play_assistant(True)
        plan=d.prepare_play('1234');self.assertEqual(plan['recommendation']['confidence'],'none')
        self.assertEqual(plan['recommendation']['mode'],'balanced')
        report={'appid':'1234','source':'ShareDeck','url':'https://sharedeck.games/apps/1234'}
        d.atomic_json(d.BASE/'research-cache.json',{'ShareDeck:1234':{'at':d.time.time(),'value':{'status':'ok','reports':[report]}}})
        self.assertEqual(d.prepare_play('1234')['recommendation']['confidence'],'low')

    def test_dont_ask_persists_by_game_and_reset_never_changes_settings(self):
        d.set_play_assistant(True);d.dismiss_play_advice('1234',True)
        self.assertEqual(d.prepare_play('1234')['status'],'dismissed')
        self.assertEqual(self.path.read_text(),self.raw);self.assertFalse(d.BACKUPS.exists())
        self.assertFalse(d.play_preview('1234','graphics')['ok'])
        d.dismiss_play_advice('1234',False);self.assertEqual(d.prepare_play('1234')['status'],'prompt')
        d.set_play_assistant(False);self.assertEqual(d.prepare_play('1234')['status'],'disabled')
        self.assertEqual(self.path.read_text(),self.raw)

    def test_exact_preview_backup_apply_and_restore(self):
        d.set_play_assistant(True)
        p=d.play_preview('1234','graphics','docked')
        self.assertEqual(self.path.read_text(),self.raw);self.assertFalse(d.BACKUPS.exists())
        self.assertTrue(any(c['key']=='ResolutionSizeX' and c['before']=='800' and c['after']=='1920' for c in p['files'][0]['changes']))
        self.assertTrue(d.play_approve('1234','graphics',p['token'],'docked')['ok'])
        self.assertEqual(next((d.BACKUPS/'1234').glob('*.ini')).read_text(),self.raw)
        self.assertIn('1920',self.path.read_text());d.restore_game('1234');self.assertEqual(self.path.read_text(),self.raw)

    def test_disabled_running_wrong_context_or_changed_file_cannot_apply(self):
        d.set_play_assistant(True);p=d.play_preview('1234','graphics')
        d.set_play_assistant(False);self.assertFalse(d.play_approve('1234','graphics',p['token'])['ok'])
        d.set_play_assistant(True);self.running.return_value={'state':'running'}
        self.assertEqual(d.prepare_play('1234')['status'],'running')
        self.assertFalse(d.play_approve('1234','graphics',p['token'])['ok'])
        self.running.return_value={'state':'closed'};self.path.write_text(self.raw+'User=keep\n')
        self.assertFalse(d.play_approve('1234','graphics',p['token'])['ok'])
        self.assertNotIn('1920',self.path.read_text());self.assertIn('User=keep',self.path.read_text())
        d.set_context('handheld');self.assertEqual(d.prepare_play('1234','docked')['status'],'profile-changed')
        self.assertFalse(d.play_preview('1234','graphics','docked')['ok'])

    def test_unsupported_uninstalled_and_nonsteam_ids_do_not_offer_apply(self):
        d.set_play_assistant(True)
        self.path.unlink();plan=d.prepare_play('1234');self.assertFalse(plan['can_apply'])
        self.assertEqual(d.prepare_play('9999')['status'],'not-installed')
        for appid in ['0','-1','1234;sh','18446744073709551615']:
            with self.assertRaises(ValueError):d.prepare_play(appid)

    def test_cli_plan_preview_approve_and_dismiss_are_wired_end_to_end(self):
        home=self.root/'cli-home';library=home/'.local/share/Steam/steamapps';library.mkdir(parents=True)
        (library/'appmanifest_1234.acf').write_text('"AppState"\n{\n"appid" "1234"\n"name" "My Game"\n}\n')
        settings=d.proton_prefix(library,'1234')/'Game/Saved/Config/Windows/GameUserSettings.ini'
        settings.parent.mkdir(parents=True);settings.write_text(self.raw)
        data=self.root/'cli-data'
        bootstrap="""import deckpilot as d
# The integration fixture has no real game process. All network use is forbidden.
d.game_running_state=lambda appid: {'state':'closed'}
def blocked(*args,**kwargs): raise AssertionError('Network on controlled Play path')
d.public_get=d.permitted_get=blocked
d.main()
"""
        def command(*args):
            return json.loads(subprocess.check_output([sys.executable,'-c',bootstrap,*args],cwd=Path(d.__file__).parent,env={**os.environ,'HOME':str(home),'DECKPILOT_DATA':str(data)}))
        self.assertTrue(command('play-enable')['ok'])
        plan=command('play-plan','1234','--context','docked')
        self.assertEqual(plan['status'],'prompt');self.assertTrue(plan['can_apply']);self.assertEqual(plan['report_count'],0)
        preview=command('play-preview','1234','--mode','graphics','--context','docked')
        self.assertEqual(settings.read_text(),self.raw)
        result=command('play-approve','1234','--mode','graphics','--context','docked','--preview-token',preview['token'])
        self.assertTrue(result['ok']);self.assertIn('1920',settings.read_text())
        self.assertEqual(next((data/'backups/1234').glob('*.ini')).read_text(),self.raw)
        self.assertTrue(command('play-dismiss','1234')['ok']);self.assertEqual(command('play-plan','1234')['status'],'dismissed')

    def test_dismissal_and_opt_in_survive_legacy_config_recovery(self):
        d.set_play_assistant(True);d.dismiss_play_advice('1234',True)
        d.atomic_json(d.CONFIG,{'default':'balanced','games':{}})
        self.assertTrue(d.config()['play_assistant_enabled']);self.assertIn('1234',d.config()['launch_dismissed'])


if __name__=='__main__':unittest.main()
