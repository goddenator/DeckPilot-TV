"""Negative and fault-injection audit cases; no real games, settings or processes modified."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import deckpilot as d
import updater
from test_research import GameFixture

class ProcessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def process(self,pid,appid=None,comm='game',status='S',exe='/games/game',wine=False):
        p=self.root/str(pid);p.mkdir();(p/'stat').write_text(str(pid)+' ('+comm+') '+status+' '+' '.join(['0']*18+['123']))
        (p/'environ').write_bytes(b'' if appid is None else ('SteamAppId='+appid+'\0').encode());(p/'exe').symlink_to(exe)
        (p/'cmdline').write_bytes(b'game.exe\0' if wine else b'game\0');return p
    def check(self):return d.game_running_state('270880',self.root)
    def test_closed_steam_alive_exact_running_and_closed_again(self):
        self.process(10,comm='steam',exe='/usr/bin/steam');self.assertEqual(self.check()['state'],'closed')
        p=self.process(11,'270880');self.assertEqual(self.check()['state'],'running')
        (p/'environ').write_bytes(b'');self.assertEqual(self.check()['state'],'closed')
    def test_exact_id_not_substring_and_zombie_ignored(self):
        self.process(11,'2708801');self.process(12,'270880',status='Z');self.assertEqual(self.check()['state'],'closed')
    def test_stale_helper_and_conflicting_ids_are_uncertain_not_running(self):
        p=self.process(11,'270880',comm='steamwebhelper',exe='/usr/bin/steamwebhelper');self.assertEqual(self.check()['state'],'uncertain')
        (p/'environ').write_bytes(b'SteamAppId=270880\0SteamGameId=9999\0');self.assertEqual(self.check()['reason'],'conflicting-app-id')
    def test_many_unreadable_same_uid_helpers_do_not_mark_games_running(self):
        for i in range(10,14):self.process(i,comm='steamwebhelper',exe='/usr/bin/steamwebhelper')
        original=Path.open
        def read(path,*args,**kw):
            if path.name=='environ':raise PermissionError('simulated SteamOS permission')
            return original(path,*args,**kw)
        with patch.object(Path,'open',read):self.assertEqual(self.check()['state'],'closed')
    def test_helper_name_without_helper_executable_is_not_trusted(self):
        self.process(10,comm='steamwebhelper',exe='/games/real-game');original=Path.open
        def read(path,*args,**kw):
            if path.name=='environ':raise PermissionError()
            return original(path,*args,**kw)
        with patch.object(Path,'open',read):self.assertEqual(self.check()['state'],'uncertain')
    def test_unreadable_unknown_process_is_uncertain_not_closed(self):
        self.process(10);original=Path.open
        def read(path,*args,**kw):
            if path.name=='environ':raise PermissionError()
            return original(path,*args,**kw)
        with patch.object(Path,'open',read):self.assertEqual(self.check()['state'],'uncertain')
    def test_pid_exit_and_pid_reuse(self):
        self.process(10,'270880');original=Path.read_text;count=0
        def read(path,*args,**kw):
            nonlocal count
            raw=original(path,*args,**kw)
            if path.name=='stat':
                count+=1
                if count>1:return raw.replace('123','456')
            return raw
        with patch.object(Path,'read_text',read):self.assertEqual(self.check()['state'],'uncertain')
        with patch.object(Path,'read_text',side_effect=FileNotFoundError()):self.assertEqual(self.check()['state'],'closed')
    def test_proton_and_native_and_proc_denial(self):
        p=self.process(10,'270880',exe='/usr/bin/wine64-preloader',wine=True);self.assertEqual(self.check()['state'],'running')
        (p/'cmdline').write_bytes(b'wine64\0');self.assertEqual(self.check()['state'],'uncertain')
        with patch.object(d.os,'scandir',side_effect=PermissionError()):self.assertEqual(self.check()['reason'],'proc-unavailable')
    def test_result_is_redacted_and_bounded(self):
        self.process(10,'270880',exe='/private/person/secret-game');result=self.check()
        self.assertEqual(set(result),{'appid','state','source','reason','scanned'});self.assertNotIn('secret',json.dumps(result))

    def test_foreign_uid_is_not_evidence_and_scan_deadline_is_uncertain(self):
        from types import SimpleNamespace
        p=self.process(10,'270880');original=Path.stat
        def stat(path,*args,**kw):
            if path==p:return SimpleNamespace(st_uid=os.getuid()+1)
            return original(path,*args,**kw)
        with patch.object(Path,'stat',stat):self.assertEqual(self.check()['state'],'closed')
        with patch.object(d.time,'monotonic',side_effect=[0,1]):self.assertEqual(self.check()['reason'],'scan-limit')
    def test_proton_system_executable_is_not_a_running_game(self):
        p=self.process(10,'270880',exe='/usr/bin/wine64-preloader');(p/'cmdline').write_bytes(b'C:\\windows\\system32\\services.exe\0')
        self.assertEqual(self.check()['state'],'uncertain')

class SettingsAuditTests(GameFixture):
    def test_uncertain_advice_no_apply_restore_or_dismissed_dispatch(self):
        d.set_play_assistant(True);d.dismiss_play_advice('1234',True);self.running.return_value={'state':'uncertain'}
        self.assertEqual(d.prepare_play('1234')['status'],'uncertain');self.assertEqual(d.prepare_play('1234',protocol=1)['status'],'profile-changed');self.assertEqual(d.preview_profile('1234','graphics')['status'],'uncertain')
        self.assertEqual(d.apply_profile(self.game,'graphics')['status'],'uncertain');self.assertIn('Cannot confirm game closed',d.restore_game('1234'));self.assertEqual(self.path.read_text(),self.raw)
    def test_corrupt_original_backup_blocks_restore_and_further_apply(self):
        p=d.preview_profile('1234','graphics');d.approve_profile('1234','graphics',p['token'])
        record=next(iter(d.read_json(d.STATE,{}).values()));Path(record['backup']).write_text('corruption')
        current=self.path.read_bytes();d.restore_game('1234');self.assertEqual(self.path.read_bytes(),current)
        self.assertEqual(d.apply_profile(self.game,'performance')['status'],'error')
    def test_duplicate_section_rejected_and_unrelated_section_not_in_preview(self):
        with self.assertRaisesRegex(ValueError,'Duplicate settings section'):d.transform_ue_ini(self.raw+self.raw,'graphics')
        self.path.write_text(self.raw+'[Other]\nResolutionSizeX=999\n')
        p=d.preview_profile('1234','graphics');change=next(c for c in p['files'][0]['changes'] if c['key']=='ResolutionSizeX');self.assertEqual(change['before'],'800')
    def test_prefix_symlink_outside_library_is_not_an_adapter(self):
        local=d.proton_prefix(self.game['library'],'1234');outside=self.root/'outside';local.rename(outside);local.symlink_to(outside,target_is_directory=True)
        self.assertEqual(d.adapter_files(self.game),[])
    def test_forged_backup_record_cannot_restore_unrelated_save(self):
        save=self.root/'save';save.write_text('keep');backup=d.BACKUPS/'fake';backup.parent.mkdir(parents=True);backup.write_text('destroy')
        d.atomic_json(d.STATE,{'fake':{'appid':'1234','file':str(save),'backup':str(backup),'after_sha':d.sha('keep')}})
        d.restore_game('1234');self.assertEqual(save.read_text(),'keep')
    def test_local_process_evidence_never_enters_automatic_drive_report(self):
        self.assertNotIn('process_checks',d.diagnostic_report());self.assertIn('process_checks',d.diagnostic_report(include_process=True))

    def test_permission_denied_apply_preserves_original_and_backup(self):
        replace=Path.replace
        def fail(path,target):
            if Path(target)==self.path:raise PermissionError('simulated read-only config')
            return replace(path,target)
        with patch.object(Path,'replace',fail):self.assertEqual(d.apply_profile(self.game,'graphics')['status'],'error')
        self.assertEqual(self.path.read_text(),self.raw);self.assertEqual(next(d.BACKUPS.rglob('*.ini')).read_text(),self.raw)
    def test_screen_refresh_does_not_execute_rclone(self):
        with patch.object(d,'drive_ready',side_effect=AssertionError('slow subprocess')):d.state_for_ui()

    def test_malformed_profile_mode_does_not_crash_state(self):
        d.atomic_json(d.CONFIG,{'profiles':{'docked':{'default':[]},'handheld':{'default':{}}}})
        self.assertEqual(d.config()['profiles']['docked']['default'],'balanced');d.state_for_ui()

class BridgeAuditTests(unittest.TestCase):
    def test_malformed_or_failed_approval_is_an_uncertain_mutation(self):
        import asyncio
        from unittest.mock import AsyncMock,Mock
        from test_research import BridgeTests
        bridge=BridgeTests().load_bridge()
        for code,stdout in [(0,b'not-json'),(1,b'partial')]:
            proc=Mock(returncode=code);proc.communicate=AsyncMock(return_value=(stdout,b''))
            with patch.object(bridge,'deck_command_environment',return_value=(Path('/home/deck'),{'HOME':'/home/deck'},{'user':1000,'group':1000})),patch.object(bridge.Path,'is_file',return_value=True),patch.object(bridge.asyncio,'create_subprocess_exec',new_callable=AsyncMock,return_value=proc):
                result=asyncio.run(bridge.Plugin()._run('play-approve','1234'))
            self.assertFalse(result['ok']);self.assertTrue(result['uncertain'])

class RecoveryAuditTests(unittest.TestCase):
    def test_empty_recovery_journal_cannot_delete_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);app=root/'app';app.mkdir();(app/'deckpilot.py').write_text('keep');updates=root/'updates';(updates/'recovery-app').mkdir(parents=True)
            (updates/'transaction.json').write_text(json.dumps({'files':{},'version':'0.8.3'}))
            with self.assertRaises(updater.UpdateError):updater.recover_interrupted(appdir=app,updates=updates,manage_service=False)
            self.assertEqual((app/'deckpilot.py').read_text(),'keep')
    def test_manifest_filename_mismatch_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'appmanifest_1234.acf').write_text('"appid" "5678"\n"name" "Wrong"\n')
            with patch.object(d,'library_paths',return_value=[root]):self.assertEqual(d.installed_games(),[])
