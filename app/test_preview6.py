"""Preview.6: real file transactions and synthetic SteamOS permission evidence."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import deckpilot as d
import test_audit as audit
from test_research import IsolatedData


ATS_RAW = '# prism3d variable config data\nuset r_device "gl"\nuset g_veg_detail "0" # keep comment\nuset r_cloud_shadows "0"\nuset r_sunshafts "0"\nuset r_mode_width "1280"\nuset r_mode_height "800"\nuset r_scale_x "1"\nuset r_scale_y "1"\nuset r_fullscreen "1"\nuset unrelated "private value"\n'

class ATSFixture(IsolatedData):
    def setUp(self):
        super().setUp()
        self.library=self.root/'steamapps';self.library.mkdir()
        (self.library/'appmanifest_270880.acf').write_text('"appid" "270880"\n"installdir" "American Truck Simulator"\n')
        self.binary=self.library/'common/American Truck Simulator/bin/linux_x64/amtrucks'
        self.binary.parent.mkdir(parents=True);self.binary.write_bytes(b'\x7fELFfixture')
        self.path=self.root/'.local/share/American Truck Simulator/config.cfg';self.path.parent.mkdir(parents=True)
        self.path.write_text(ATS_RAW)
        self.game={'appid':'270880','name':'American Truck Simulator','library':str(self.library)}
        self.stack.enter_context(patch.object(d.Path,'home',return_value=self.root))
        self.stack.enter_context(patch.object(d,'installed_games',return_value=[self.game]))
        self.running=self.stack.enter_context(patch.object(d,'game_running_state',return_value={'state':'closed','reason':'no-app-process'}))



class ATSAdapterTests(ATSFixture):
    def test_three_modes_change_only_documented_existing_keys(self):
        for mode,expected in d.ATS_PRESETS.items():
            with self.subTest(mode=mode):
                output=d.transform_ats(ATS_RAW,mode)
                self.assertEqual(tuple(d.ats_values(output).values()),expected)
                self.assertIn('uset r_mode_width "1280"',output)
                self.assertIn('uset r_scale_x "1"',output)
                self.assertIn('uset unrelated "private value"',output)
                self.assertIn('# keep comment',output)
                self.assertEqual(d.transform_ats(output,mode),output)

    def test_preview_apply_readback_backup_manual_change_and_restore(self):
        preview=d.preview_profile('270880','graphics')
        self.assertEqual(preview['status'],'preview')
        self.assertEqual({c['key'] for c in preview['files'][0]['changes']},set(d.ATS_KEYS))
        self.assertEqual(self.path.read_text(),ATS_RAW)
        self.assertEqual(preview['summary']['resolution'],'Display resolution unchanged')
        applied=d.approve_profile('270880','graphics',preview['token'])
        self.assertTrue(applied['ok']);self.assertEqual(applied['verified_files'],1)
        self.assertIn('Partial ATS support',d.game_checkup('270880')['message'])
        self.assertEqual(next(d.BACKUPS.rglob('*.ini')).read_text(),ATS_RAW)
        d.restore_game('270880');self.assertEqual(self.path.read_text(),ATS_RAW)
        preview=d.preview_profile('270880','balanced');d.approve_profile('270880','balanced',preview['token'])
        self.path.write_text(self.path.read_text()+'# manual change\n');manual=self.path.read_bytes()
        self.assertEqual(d.apply_profile(self.game,'graphics')['status'],'manual-changes')
        d.restore_game('270880');self.assertEqual(self.path.read_bytes(),manual)

    def test_uncertain_running_and_starting_during_apply_never_write(self):
        for state in ('uncertain','running'):
            self.running.return_value={'state':state}
            self.assertEqual(d.preview_profile('270880','graphics')['status'],state)
            self.assertEqual(d.apply_profile(self.game,'graphics')['count'],0)
            d.restore_game('270880');self.assertEqual(self.path.read_text(),ATS_RAW)
        self.running.side_effect=[{'state':'closed'},{'state':'running'}]
        self.assertEqual(d.apply_profile(self.game,'graphics')['status'],'error')
        self.assertEqual(self.path.read_text(),ATS_RAW)

    def test_missing_keys_duplicates_invalid_values_and_signature_are_unsupported(self):
        for raw in [ATS_RAW.replace('uset r_sunshafts "0"\n',''),ATS_RAW+'uset g_veg_detail "2"\n',ATS_RAW.replace('g_veg_detail "0"','g_veg_detail "9"'),ATS_RAW.replace('g_veg_detail','G_VEG_DETAIL'),ATS_RAW.replace('# prism3d variable config data','# different format'),ATS_RAW.replace('"gl"','"dx11"')]:
            with self.subTest(raw=raw[:40]):
                self.path.write_text(raw)
                self.assertEqual(d.adapter_files(self.game),[])
                self.assertEqual(self.path.read_text(),raw)

    def test_bom_utf16_symlinks_proton_payload_and_invalid_manifest_never_authorise(self):
        for data in [b'\xef\xbb\xbf'+ATS_RAW.encode(),ATS_RAW.encode('utf-16')]:
            self.path.write_bytes(data);self.assertEqual(d.adapter_files(self.game),[])
        self.path.write_text(ATS_RAW)
        windows=self.binary.parent.parent/'win_x64/amtrucks.exe';windows.parent.mkdir();windows.write_bytes(b'MZ')
        self.assertEqual(d.adapter_files(self.game),[]);windows.unlink()
        self.binary.unlink();self.binary.symlink_to(self.root/'elsewhere')
        self.assertEqual(d.adapter_files(self.game),[])
        self.binary.unlink();self.binary.write_bytes(b'\x7fELFfixture')
        manifest=self.library/'appmanifest_270880.acf';manifest.write_text('"appid" "9999"\n"installdir" "../escape"')
        self.assertEqual(d.adapter_files(self.game),[])

    def test_native_config_symlink_is_not_an_adapter(self):
        other=self.root/'other.cfg';self.path.rename(other);self.path.symlink_to(other)
        self.assertEqual(d.adapter_files(self.game),[])
        self.assertEqual(other.read_text(),ATS_RAW)

    def test_readback_failure_keeps_original_backup_and_revokes_sync(self):
        preview=d.preview_profile('270880','graphics');read=d.safe_read_text
        def fail(path):
            value=read(path)
            return value+'# changed during readback\n' if path==self.path and value!=ATS_RAW else value
        with patch.object(d,'safe_read_text',side_effect=fail):result=d.approve_profile('270880','graphics',preview['token'])
        self.assertFalse(result['ok']);self.assertEqual(result['verified_files'],0)
        self.assertEqual(next(d.BACKUPS.rglob('*.ini')).read_text(),ATS_RAW)
        self.assertNotIn('270880',d.config()['approved'])

    def test_crlf_comments_and_unicode_roundtrip_without_unrelated_changes(self):
        raw=ATS_RAW.replace('\n','\r\n')+'# café\r\n'
        out=d.transform_ats(raw,'balanced')
        self.assertEqual(out.replace('g_veg_detail "1"','g_veg_detail "0"').replace('r_sunshafts "1"','r_sunshafts "0"'),raw)

    def test_encoding_change_at_last_guard_is_protected_like_any_manual_edit(self):
        changed=b'\xef\xbb\xbf'+ATS_RAW.encode()
        def race(appid):self.path.write_bytes(changed);return False
        with patch.object(d,'game_is_running',side_effect=race):
            self.assertEqual(d.apply_profile(self.game,'graphics')['status'],'error')
        self.assertEqual(self.path.read_bytes(),changed)

    def test_ats_hint_never_claims_a_resolution_change_or_measured_fps_target(self):
        hint=d.state_for_ui()['games'][0]['hint']
        self.assertIn('resolution/scaling unchanged',hint)
        self.assertIn('Performance not measured',hint)
        self.assertNotIn('30',hint)

    def test_inaccessible_or_symlinked_windows_payload_is_never_assumed_absent(self):
        windows=self.binary.parent.parent/'win_x64/amtrucks.exe'
        lstat=Path.lstat
        def denied(path,*a,**kw):
            if path==windows:raise PermissionError('SteamOS visibility')
            return lstat(path,*a,**kw)
        with patch.object(Path,'lstat',denied):self.assertEqual(d.adapter_files(self.game),[])
        windows.parent.mkdir();windows.symlink_to(self.root/'missing-target')
        self.assertEqual(d.adapter_files(self.game),[])


class VisibilityTests(unittest.TestCase):
    setUp=audit.ProcessEvidenceTests.setUp
    process=audit.ProcessEvidenceTests.process
    def test_28_denied_processes_remain_uncertain_with_redacted_kernel_categories(self):
        for pid in range(10,38):
            item=self.process(pid)
            (item/'status').write_text('Uid:\t'+('\t'.join([str(os.getuid())]*4))+'\nTracerPid:\t0\n')
            (item/'cgroup').write_text('0::/private/user.slice/app-steam-270880.scope\n')
        original=Path.open
        def deny(path,*args,**kw):
            if path.name=='environ':raise PermissionError()
            return original(path,*args,**kw)
        with patch.object(Path,'open',deny),patch.object(d.os,'readlink',side_effect=PermissionError()):
            result=d.game_running_state('270880',self.root,diagnostics=True)
        self.assertEqual(result['state'],'uncertain');self.assertEqual(result['reason'],'exe-permission')
        self.assertEqual(result['counts']['environment-permission'],28);self.assertEqual(result['counts']['exe-permission'],28)
        self.assertEqual(result['visibility']['target_scope'],28)
        for private in ('private/user',str(self.root),'270880.scope'):
            self.assertNotIn(private,json.dumps(result))

    def test_other_game_scope_never_grants_closed_state_and_no_enrichment_on_write_guard(self):
        item=self.process(10);(item/'cgroup').write_text('0::/app-steam-9999.scope\n');original=Path.open
        def deny(path,*a,**k):
            if path.name=='environ':raise PermissionError()
            return original(path,*a,**k)
        with patch.object(Path,'open',deny),patch.object(d.os,'readlink',side_effect=PermissionError()):
            result=d.game_running_state('270880',self.root,diagnostics=True)
            self.assertEqual(result['visibility']['other_game_scope'],1)
            self.assertEqual(result['state'],'uncertain')
            with patch.object(d,'denied_process_visibility',side_effect=AssertionError('Extra scan in guard')):
                self.assertEqual(d.game_running_state('270880',self.root)['state'],'uncertain')


class EvidenceTests(ATSFixture):
    def observation(self):return {'appid':'270880','status':'available','initialized':True,'overview_match':True,'listed_running':False,'display_status':11,'token':'SECRET','client_name':'PRIVATE'}

    def test_reference_and_native_ready_never_authorise_changes(self):
        self.running.return_value={'state':'uncertain','reason':'exe-permission','counts':{'exe-permission':28}}
        with patch.object(d,'save_diagnostic_zip') as export:
            result=d.record_game_evidence('270880','steam-play',self.observation())
        self.assertTrue(result['ok']);self.assertEqual(result['evidence']['proc_state'],'uncertain')
        self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertEqual(self.path.read_text(),ATS_RAW)
        self.assertEqual(self.running.call_count,1);export.assert_called_once()
        self.assertFalse(d.approve_profile('270880','graphics','wrong')['ok'])

    def test_history_is_bounded_manual_only_and_cross_game_observation_is_rejected(self):
        self.running.return_value={'state':'closed','reason':'no-app-process','counts':{}}
        with patch.object(d,'save_diagnostic_zip'):
            for _ in range(14):d.record_game_evidence('270880','steam-play',self.observation())
        self.assertEqual(len(d.evidence_history()),12)
        self.assertNotIn('game_evidence',d.diagnostic_report())
        self.assertEqual(len(d.diagnostic_report(include_process=True)['game_evidence']),12)
        with self.assertRaises(ValueError):d.record_game_evidence('270880','steam-play',{'appid':'9999','status':'available'})

    def test_local_zip_is_real_and_contains_no_raw_config_or_process_payload(self):
        self.running.return_value={'state':'closed','reason':'no-app-process','counts':{}}
        d.record_game_evidence('270880','steam-play',self.observation())
        with zipfile.ZipFile(d.REPORTS/'DeckPilot-Latest-Local.zip') as z:
            report=json.loads(z.read('DeckPilot-Diagnostics.json'))
        raw=json.dumps(report['game_evidence'])
        self.assertNotIn('private value',raw);self.assertNotIn('r_device',raw);self.assertNotIn('SECRET',raw)

    def test_ffx_official_id_candidates_are_read_only_and_actual_manifest_is_used(self):
        library=self.root/'ffx-steamapps';library.mkdir()
        game={'appid':'359870','name':'FINAL FANTASY X/X-2 HD Remaster','library':str(library)}
        (library/'appmanifest_359870.acf').write_text('"appid" "359870"\n"installdir" "FFX"')
        path=library/'common/FFX/FFX&X-2_LAUNCHER.ini';path.parent.mkdir(parents=True);path.write_text('[Graphics]\nwidth=1280\npassword=SECRET\n')
        result=d.settings_coverage(game)
        self.assertTrue(result['store_appid_match']);self.assertFalse(result['writable'])
        self.assertEqual(result['probes'][1]['format'],'ini-like')
        self.assertNotIn('SECRET',json.dumps(result));self.assertEqual(d.adapter_files(game),[])


    def test_failed_report_replacement_preserves_previous_archive_and_rejects_symlink(self):
        d.save_diagnostic_zip({'original':'report'})
        dest=d.REPORTS/'DeckPilot-Latest-Local.zip';old=dest.read_bytes();replace=Path.replace
        def fail(path,target):
            if target==dest:raise PermissionError()
            return replace(path,target)
        with patch.object(Path,'replace',fail),self.assertRaises(PermissionError):d.save_diagnostic_zip({'new':'report'})
        self.assertEqual(dest.read_bytes(),old)
        other=self.root/'private';other.write_text('preserve');dest.unlink();dest.symlink_to(other)
        with self.assertRaises(ValueError):d.save_diagnostic_zip({'new':'report'})
        self.assertEqual(other.read_text(),'preserve')

    def test_automatic_drive_upload_excludes_all_manual_process_and_graphics_evidence(self):
        from types import SimpleNamespace
        d.atomic_json(d.CLOUD,{'enabled':True})
        report={'errors':[],'process_checks':[{'secret':'PROC'}],'game_evidence':[{'secret':'HISTORY'}],'settings_coverage':[{'secret':'CONFIG'}]}
        def upload(args,**kwargs):
            with zipfile.ZipFile(args[2]) as archive:value=json.loads(archive.read('DeckPilot-Diagnostics.json'))
            for key in ('process_checks','game_evidence','settings_coverage'):self.assertNotIn(key,value)
            return SimpleNamespace(returncode=0)
        with patch.object(d,'drive_ready',return_value=(True,'')),patch.object(d,'rclone_binary',return_value='rclone'),patch.object(d.subprocess,'run',side_effect=upload),patch.object(d,'diagnostic_report',return_value=report) as diagnostics:
            self.assertIn('Uploaded',d.upload_cloud_report(force=False))
        diagnostics.assert_called_once_with(include_process=False)
