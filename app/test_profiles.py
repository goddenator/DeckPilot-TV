"""Profiles, checkups, offline evidence, measurements and updater regression tests."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import os
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import deckpilot as d
import updater as up
from test_research import GameFixture, IsolatedData
from test_updater import make_pkg


class ProfileTests(GameFixture):
    def test_legacy_migration_preserves_choices_and_does_not_reapprove(self):
        d.atomic_json(d.CONFIG,{'enabled':True,'default':'graphics','games':{'1234':'performance'},'approved':{'1234':'performance'},'approved_files':{'1234':[str(self.path)]}})
        cfg=d.config()
        for context in d.CONTEXTS:
            self.assertEqual(d.effective_mode('1234',cfg,context),'performance')
            self.assertEqual(d.effective_mode('999',cfg,context),'graphics')
        d.synchronize();self.assertEqual(self.path.read_text(),self.raw)
        self.assertFalse(d.game_checkup('1234')['optimised'])

    def test_separate_profiles_switch_requires_approval_and_restore_preserves_baseline(self):
        d.save_mode('graphics','1234','docked');d.save_mode('performance','1234','handheld')
        d.set_context('handheld');self.assertEqual(self.path.read_text(),self.raw)
        self.assertEqual(d.effective_mode('1234'),'performance')
        p=d.preview_profile('1234','performance','handheld')
        self.assertEqual(p['summary']['resolution'],'1152 × 720')
        self.assertTrue(d.approve_profile('1234','performance',p['token'],'handheld')['ok'])
        self.assertIn('ResolutionSizeX=1152',self.path.read_text())
        self.assertTrue(d.game_checkup('1234')['optimised'])
        after=self.path.read_text();d.set_context('docked');d.synchronize();self.assertEqual(self.path.read_text(),after)
        self.assertEqual(d.effective_mode('1234'),'graphics')
        self.assertFalse(d.game_checkup('1234')['optimised'])
        p=d.preview_profile('1234','graphics','docked');d.approve_profile('1234','graphics',p['token'],'docked')
        self.assertIn('ResolutionSizeX=1920',self.path.read_text())
        d.restore_game('1234');d.synchronize();self.assertEqual(self.path.read_text(),self.raw)
        self.assertEqual(len(list((d.BACKUPS/'1234').glob('*.ini'))),1)
        self.assertEqual(d.config()['profiles']['handheld']['games']['1234'],'performance')

    def test_profile_preferences_survive_an_older_app_rewriting_legacy_config(self):
        d.save_mode('graphics','1234','docked');d.save_mode('performance','1234','handheld')
        d.set_context('handheld')
        # v0.8.0 only knows the top-level fields and drops unknown fields on save.
        d.atomic_json(d.CONFIG,{'enabled':True,'default':'balanced','games':{'1234':'balanced'}})
        cfg=d.config()
        self.assertEqual(cfg['context'],'handheld')
        self.assertEqual(d.effective_mode('1234',cfg,'handheld'),'balanced')
        self.assertEqual(d.effective_mode('1234',cfg,'docked'),'graphics')
        d.synchronize();self.assertEqual(self.path.read_text(),self.raw)

    def test_context_is_bound_to_preview_and_cannot_apply_after_switch(self):
        p=d.preview_profile('1234','balanced','docked')
        d.set_context('handheld')
        self.assertFalse(d.approve_profile('1234','balanced',p['token'],'docked')['ok'])
        self.assertFalse(d.approve_profile('1234','balanced',p['token'],'handheld')['ok'])
        self.assertEqual(self.path.read_text(),self.raw)

    def test_checkup_reports_actual_manual_changes_and_restore_safety(self):
        self.assertEqual(d.game_checkup('1234')['status'],'needs-review')
        p=d.preview_profile('1234','graphics');d.approve_profile('1234','graphics',p['token'])
        self.assertTrue(d.game_checkup('1234')['can_restore'])
        self.path.write_text(self.path.read_text().replace('1920','1700'))
        c=d.game_checkup('1234');self.assertEqual(c['status'],'manual-changes');self.assertFalse(c['optimised']);self.assertFalse(c['can_restore']);self.assertEqual(c['backups'],1)
        self.running.return_value={'state':'running'};self.assertEqual(d.game_checkup('1234')['status'],'running')
        self.assertEqual(d.game_checkup('5555')['status'],'not-installed')

    def test_missing_backup_is_not_reported_as_optimised(self):
        p=d.preview_profile('1234','graphics');d.approve_profile('1234','graphics',p['token'])
        next((d.BACKUPS/'1234').glob('*.ini')).unlink()
        checkup=d.game_checkup('1234')
        self.assertEqual(checkup['status'],'error');self.assertFalse(checkup['optimised']);self.assertFalse(checkup['can_restore'])

    def test_apply_rechecks_file_contents_and_running_state(self):
        fingerprints={str(self.path):d.sha(self.raw)}
        self.path.write_text(self.raw+'UserKey=changed\n')
        result=d.apply_profile(self.game,'graphics',expected_hashes=fingerprints)
        self.assertEqual(result['status'],'error');self.assertIn('UserKey=changed',self.path.read_text());self.assertNotIn('1920',self.path.read_text())
        self.path.write_text(self.raw)
        self.running.side_effect=[{'state':'closed'},{'state':'running'}]
        result=d.apply_profile(self.game,'graphics')
        self.assertEqual(result['status'],'error');self.assertEqual(self.path.read_text(),self.raw)

    def test_invalid_context_and_malformed_preferences_fail_safely(self):
        with self.assertRaises(ValueError):d.set_context('television')
        d.atomic_json(d.CONFIG,{'profiles':{'docked':{'default':[],'games':{'1234':[]}}},'context':{},'default':[]})
        self.assertEqual(d.config()['context'],'docked');self.assertEqual(d.effective_mode('1234'),'balanced')
        self.assertFalse(d.config()['measurements_enabled']);self.assertFalse(d.config()['launch_prompts'])

    def test_native_hollow_knight_resolution_preserves_saves_and_handles_single_quotes(self):
        prefs=self.root/'.config/unity3d/Team Cherry/Hollow Knight/prefs';prefs.parent.mkdir(parents=True)
        raw="<unity_prefs><pref type='int' name='Screenmanager Resolution Width'>800</pref><pref name='Screenmanager Resolution Height' type='int'>600</pref><pref name='Unknown' type='string'>KEEP</pref></unity_prefs>"
        prefs.write_text(raw);save=prefs.parent/'user1.dat';save.write_bytes(b'PLAYER SAVE')
        game={'appid':'367520','name':'Hollow Knight','library':str(self.root/'steamapps')}
        with patch.object(d.Path,'home',return_value=self.root),patch.object(d,'installed_games',return_value=[game]):
            d.set_context('handheld');p=d.preview_profile('367520','graphics')
            self.assertIsNone(p['summary']['quality'])
            self.assertEqual(len(p['files'][0]['changes']),2)
            self.assertTrue(d.approve_profile('367520','graphics',p['token'])['ok'])
            self.assertIn('1280',prefs.read_text());self.assertIn('KEEP',prefs.read_text());self.assertEqual(save.read_bytes(),b'PLAYER SAVE')
            self.assertTrue(d.game_checkup('367520')['can_restore'])
            d.restore_game('367520');self.assertEqual(prefs.read_text(),raw)

    def test_logs_are_opt_in_and_similar_titles_are_not_attributed(self):
        with patch.object(d,'game_metrics',return_value=None) as metrics,patch.object(d,'cloud_status',return_value={}):
            d.state_for_ui();metrics.assert_not_called()
            d.set_measurements(True);d.state_for_ui();self.assertEqual(metrics.call_count,1)
        logs=self.root/'mangologs';logs.mkdir()
        (logs/'VeryCoolGame2_2026-11-10.csv').write_text('fps,frametime\n')
        (logs/'VeryCoolGame_2026-11-10.csv').write_text('fps,frametime\n')
        found=d.game_log_candidates({'appid':'999','name':'Very Cool Game'},home=self.root)
        self.assertEqual([p.name for p in found],['VeryCoolGame_2026-11-10.csv'])

    def test_true_frame_times_and_invalid_samples_are_handled(self):
        csv=self.root/'metrics.csv';csv.write_text('fps,frametime\n'+('40,25\n'*100)+'nan,nan\ninf,inf\n')
        result=d.summarize_mangohud_csv(csv)
        self.assertEqual(result['frame_time_avg_ms'],25);self.assertEqual(result['frame_time_p95_ms'],25)
        self.assertEqual(result['samples'],100);self.assertIn('unverified',result['measurement_note'])


class OfflineEvidenceTests(IsolatedData):
    def test_expired_verified_identity_and_source_reports_survive_offline_but_expire_after_30_days(self):
        key='steam:892970';game={'appid':'892970','name':'Valheim','verified':True}
        d.research_cached(key,lambda:game)
        now=d.time.time()
        with patch.object(d.time,'time',return_value=now+d.RESEARCH_TTL+1):
            result=d.research_cached(key,lambda:(_ for _ in ()).throw(OSError()),allow_stale=True)
            self.assertTrue(result['stale']);self.assertTrue(result['verified'])
        with patch.object(d.time,'time',return_value=now+31*86400):
            with self.assertRaises(OSError):d.research_cached(key,lambda:(_ for _ in ()).throw(OSError()),allow_stale=True)
        source={'status':'ok','reports':[{'summary':'Saved report'}]}
        d.research_cached('ShareDeck:892970',lambda:source)
        with patch.object(d.time,'time',return_value=now+d.RESEARCH_TTL+10):
            fallback=d.research_cached('ShareDeck:892970',lambda:{'status':'unavailable','reports':[]},allow_stale=True)
            self.assertTrue(fallback['stale']);self.assertEqual(fallback['reports'],source['reports'])
            saved=d.read_json(d.BASE/'research-cache.json',{})['ShareDeck:892970']
            self.assertEqual(saved['value'],source)  # failed fetch cannot destroy good reports

    def test_source_fallback_is_labelled_and_confidence_is_downgraded(self):
        report={'source':'ShareDeck','device':'Steam Deck OLED','display_context':'handheld','report_date':d.dt.datetime.now(d.dt.timezone.utc).isoformat(),'game_version':'1','resolution':'1280x800'}
        self.assertEqual(d.evidence_summary([report],'handheld')['confidence'],'medium')
        self.assertEqual(d.evidence_summary([report],'docked')['confidence'],'low')
        self.assertEqual(d.evidence_summary([{**report,'stale':True}],'handheld')['confidence'],'low')
        duplicate=[report,dict(report)]
        self.assertNotEqual(d.evidence_summary(duplicate,'handheld')['confidence'],'high')
        independent=[report,{**report,'source':'SteamDeckHQ'}]
        self.assertEqual(d.evidence_summary(independent,'handheld')['confidence'],'high')
        self.assertEqual(d.evidence_summary([],'docked')['confidence'],'none')
        self.assertIn('not guaranteed',d.evidence_summary(independent,'handheld')['note'])

    def test_independent_processes_do_not_lose_each_others_cache_entries(self):
        code="import deckpilot as d,sys; d.research_cached(sys.argv[1],lambda:{'status':'ok','reports':[]})"
        env={**os.environ,'DECKPILOT_DATA':str(d.BASE)}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(subprocess.run,[sys.executable,'-c',code,'source-'+str(i)],cwd=Path(__file__).parent,env=env,check=True,capture_output=True) for i in range(8)]
            for future in futures:future.result()
        self.assertEqual(len(d.read_json(d.BASE/'research-cache.json',{})),8)

    def test_malformed_cache_entries_do_not_crash(self):
        for value in [None,[],{'value':'invalid','at':'bad'}]:
            d.atomic_json(d.BASE/'research-cache.json',{'key':value})
            self.assertEqual(d.research_cached('key',lambda:'fresh'),'fresh')


class DriveReliabilityTests(IsolatedData):
    def test_disabling_during_an_upload_is_not_overwritten_by_completion(self):
        d.atomic_json(d.CLOUD,{'enabled':True})
        def upload(*args,**kwargs):
            d.cloud_enable(False)
            return type('Result',(),{'returncode':0})()
        with patch.object(d,'drive_ready',return_value=(True,'')),patch.object(d,'rclone_binary',return_value='rclone'),patch.object(d.subprocess,'run',side_effect=upload) as run:
            d.upload_cloud_report(force=True,report={'errors':[]})
            self.assertFalse(d.cloud_config()['enabled'])
            self.assertIn('disabled',d.upload_cloud_report(force=True,report={'errors':[]}))
            self.assertEqual(run.call_count,1)

    def test_concurrent_upload_is_not_started(self):
        d.mkdir()
        with (d.BASE/'cloud-upload.lock').open('a') as handle,patch.object(d.subprocess,'run') as run:
            d.fcntl.flock(handle,d.fcntl.LOCK_EX)
            self.assertIn('already in progress',d.upload_cloud_report(force=True))
            run.assert_not_called()


class UpdaterReliabilityTests(unittest.TestCase):
    def test_install_rejects_changed_github_digest_and_preserves_current_app(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);archive=root/'DeckPilot_TV_v0.9.zip';make_pkg(archive)
            app=root/'app';app.mkdir();(app/'deckpilot.py').write_text("VERSION = '0.8.0'\n")
            with self.assertRaisesRegex(up.UpdateError,'digest'):
                up.install_archive(archive,appdir=app,updates=root/'updates',manage_service=False,expected_sha256='0'*64)
            self.assertEqual(up.current_version(app),'0.8.0')
            digest=hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(up.install_archive(archive,appdir=app,updates=root/'updates',manage_service=False,expected_sha256=digest),'0.9.0')

    def test_staged_download_is_reverified_not_just_its_internal_manifest(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);ready=root/'ready';ready.mkdir();archive=ready/'DeckPilot_TV_v0.9.zip';make_pkg(archive)
            digest=hashlib.sha256(archive.read_bytes()).hexdigest()
            metadata={'status':'ready','repository':'goddenator/DeckPilot-TV','path':str(archive),'sha256':digest}
            with patch.object(up,'READY',ready),patch.object(up,'newest_candidate',return_value=None),patch.object(up,'release_source',return_value='goddenator/DeckPilot-TV'),patch.object(up,'remote_status',return_value=metadata):
                self.assertEqual(up.candidate_for_install('0.8.0')['sha256'],digest)
                make_pkg(archive,code="VERSION = '0.9.0'\n# changed content and valid internal checksum\n")
                self.assertIsNone(up.candidate_for_install('0.8.0'))

    def test_lock_contention_does_not_start_an_install(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);archive=root/'DeckPilot_TV_v0.9.zip';make_pkg(archive)
            with up.update_lock(root/'updates'),patch.object(up,'_install_snapshot') as install:
                with self.assertRaisesRegex(up.UpdateError,'Another update'):
                    up.install_archive(archive,appdir=root/'app',updates=root/'updates',manage_service=False)
                install.assert_not_called()

    def test_late_record_failure_still_recovers_from_committed_backup(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);archive=root/'DeckPilot_TV_v0.9.zip';make_pkg(archive)
            app=root/'app';app.mkdir();(app/'deckpilot.py').write_text("VERSION = '0.8.0'\n")
            original_record=up.record
            def record(status,*args,**kwargs):
                if status=='success':raise OSError('Disk full while recording success')
                return original_record(status,*args,**kwargs)
            with patch.object(up,'record',side_effect=record):
                with self.assertRaisesRegex(up.UpdateError,'rolled back'):
                    up.install_archive(archive,appdir=app,updates=root/'updates',manage_service=False)
            self.assertEqual(up.current_version(app),'0.8.0')
            self.assertTrue((root/'updates/previous-app/deckpilot.py').is_file())

    def test_redirect_parser_fails_closed_for_invalid_ports(self):
        for url in ['https://github.com:wrong/x','https://github.com:999999/x','https://user:pass@github.com/x']:
            self.assertFalse(up.safe_redirect_url(url))


if __name__=='__main__':unittest.main()
