"""Regressions from issues #6/#7; synthetic proc/config fixtures, no hardware claim."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import deckpilot as d
import test_audit
from test_research import GameFixture


class SteamOSProbeTests(unittest.TestCase):
    setUp = test_audit.ProcessEvidenceTests.setUp
    process = test_audit.ProcessEvidenceTests.process
    check = test_audit.ProcessEvidenceTests.check
    def test_real_kernel_stat_layout_and_arbitrary_comm_bytes(self):
        comm, state, start, flags = d.parse_process_stat(Path('/proc/self/stat').read_bytes())
        self.assertGreater(start, 0)
        self.assertIsInstance(flags, int)
        raw = b'123 (a ) strange\xff name) S ' + b' '.join([b'0']*18+[b'987'])
        self.assertEqual(d.parse_process_stat(raw)[2], 987)
        p = self.process(10)
        (p/'stat').write_bytes(raw)
        self.assertEqual(self.check()['state'], 'closed')

    def test_nondumpable_user_game_with_root_proc_owner_is_not_skipped(self):
        from types import SimpleNamespace
        p = self.process(10, '270880')
        (p/'status').write_text('Uid:\t1000\t1000\t1000\t1000\n')
        original = Path.stat
        def stat(path, *args, **kw):
            if path == p: return SimpleNamespace(st_uid=0)
            return original(path, *args, **kw)
        with patch.object(Path, 'stat', stat), patch.object(d.os, 'getuid', return_value=1000):
            self.assertEqual(self.check()['state'], 'running')

    def test_environment_then_exe_denial_is_categorised_without_identifiers(self):
        self.process(10); original = Path.open
        def read(path, *args, **kw):
            if path.name == 'environ': raise PermissionError()
            return original(path, *args, **kw)
        with patch.object(Path, 'open', read), patch.object(d.os, 'readlink', side_effect=PermissionError()):
            result = self.check()
        self.assertEqual(result['state'], 'uncertain')
        self.assertEqual(result['reason'], 'exe-permission')
        self.assertEqual(result['counts'], {'environment-permission':1, 'exe-permission':1})
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_truncated_linux_helper_comm_requires_executable_corroboration(self):
        name = 'steam-runtime-launcher-service'
        self.process(10, comm=name[:15], exe='/usr/bin/'+name)
        original = Path.open
        def read(path, *args, **kw):
            if path.name == 'environ': raise PermissionError()
            return original(path, *args, **kw)
        with patch.object(Path, 'open', read):
            result = self.check()
        self.assertEqual(result['state'], 'closed')
        self.assertEqual(result['counts']['unrelated-helper'], 1)

    def test_kernel_thread_flag_not_empty_command_line_grants_exclusion(self):
        p = self.process(10)
        fields = ['0']*18+['123']; fields[5] = str(0x00200000)
        (p/'stat').write_text('10 (kernel task) S '+' '.join(fields))
        original = Path.open
        def read(path, *args, **kw):
            if path.name == 'environ': raise PermissionError()
            return original(path, *args, **kw)
        with patch.object(Path, 'open', read):
            self.assertEqual(self.check()['state'], 'closed')
        fields[5] = '0'; (p/'stat').write_text('10 (kernel task) S '+' '.join(fields))
        (p/'cmdline').write_bytes(b'')
        with patch.object(Path, 'open', read):
            self.assertEqual(self.check()['state'], 'uncertain')

    def test_live_process_missing_executable_is_not_assumed_exited(self):
        p = self.process(10, '270880'); (p/'exe').unlink()
        self.assertEqual(self.check()['reason'], 'attribute-missing')

    def test_malformed_identity_and_duplicate_environment_ids_fail_closed(self):
        p = self.process(10, '270880')
        (p/'stat').write_text('10 (bad) S not-a-stat')
        self.assertEqual(self.check()['reason'], 'stat-format')
        (p/'stat').write_text('10 (game) S '+' '.join(['0']*18+['123']))
        (p/'environ').write_bytes(b'SteamAppId=9\0SteamAppId=270880\0')
        self.assertEqual(self.check()['reason'], 'conflicting-app-id')

    def test_stat_read_is_bounded_before_parsing(self):
        import io
        p = self.process(10)
        reads = []
        class Guarded(io.BytesIO):
            def read(self, size=-1):
                reads.append(size)
                if size < 0: raise AssertionError('Unbounded proc read')
                return super().read(size)
        original = Path.open
        def read(path, *args, **kw):
            if path == p/'stat': return Guarded(b'x'*20000)
            return original(path, *args, **kw)
        with patch.object(Path, 'open', read):
            self.assertEqual(self.check()['reason'], 'stat-format')
        self.assertEqual(reads, [16385])

    def test_stat_failure_after_denied_environment_has_correct_category(self):
        self.process(10, comm='steam', exe='/usr/bin/steam')
        original = Path.open; stat_reads = 0
        def read(path, *args, **kw):
            nonlocal stat_reads
            if path.name == 'environ': raise PermissionError()
            if path.name == 'stat':
                stat_reads += 1
                if stat_reads > 1: raise PermissionError()
            return original(path, *args, **kw)
        with patch.object(Path, 'open', read):
            result = self.check()
        self.assertEqual(result['reason'], 'stat-permission')
        self.assertEqual(result['counts'], {'environment-permission':1,'stat-permission':1})

    def test_scan_finishing_past_deadline_cannot_authorise_writes(self):
        self.process(10)
        with patch.object(d.time, 'monotonic', side_effect=[0, 0.1, 0.6]):
            self.assertEqual(self.check()['reason'], 'scan-limit')


class SettingsOutcomeTests(GameFixture):
    def test_choice_changes_preference_only_and_reports_zero(self):
        result = d.save_mode('graphics', '1234')
        self.assertEqual(result['files_changed'], 0)
        self.assertFalse(result['settings_changed'])
        self.assertIn('no settings were changed', result['message'])
        self.assertEqual(self.path.read_text(), self.raw)
        self.assertFalse(d.STATE.exists())

    def test_apply_readback_checkup_and_restore(self):
        preview = d.preview_profile('1234', 'graphics')
        result = d.approve_profile('1234', 'graphics', preview['token'])
        self.assertTrue(result['ok'])
        self.assertEqual(result['files_changed'], 1)
        self.assertEqual(result['verified_files'], 1)
        self.assertEqual(d.game_checkup('1234')['verified_files'], 1)
        d.restore_game('1234')
        self.assertEqual(self.path.read_text(), self.raw)

    def test_wrong_readback_is_failure_and_retains_backup(self):
        preview = d.preview_profile('1234', 'graphics')
        original = d.safe_read_text
        def read(path):
            text = original(path)
            if path == self.path and text != self.raw: return text+'unexpected=1\n'
            return text
        with patch.object(d, 'safe_read_text', read):
            result = d.approve_profile('1234', 'graphics', preview['token'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['verified_files'], 0)
        self.assertEqual(result['files_changed'], 1)
        self.assertNotIn('1234', d.config()['approved'])
        records = d.read_json(d.STATE, {})
        self.assertEqual(len(records), 1)
        self.assertTrue(Path(next(iter(records.values()))['backup']).is_file())

    def test_ats_candidate_is_read_only_exact_id_no_private_contents(self):
        game = {**self.game, 'appid':'270880', 'name':'American Truck Simulator'}
        path = self.root/'.local/share/American Truck Simulator/config.cfg'
        path.parent.mkdir(parents=True)
        raw = 'uset r_mode_width "1280"\nuset r_mode_height "800"\nprivate "secret"\n'
        path.write_text(raw)
        result = d.settings_coverage(game, self.root)
        self.assertFalse(result['writable'])
        self.assertEqual(result['probes'][0], {'kind':'native','status':'candidate','known_keys':2})
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(path.read_text(), raw)
        self.assertEqual(d.adapter_files(game), [])

    def test_final_fantasy_id_is_taken_from_manifest_not_assigned_by_title(self):
        result = d.settings_coverage({**self.game, 'appid':'9999', 'name':'FINAL FANTASY X/X-2 HD Remaster'})
        self.assertEqual(result['appid'], '9999')
        self.assertFalse(result['writable'])
        self.assertNotIn('probes', result)

    def test_extended_local_evidence_is_omitted_from_automatic_reports(self):
        automatic = d.diagnostic_report()
        self.assertNotIn('process_checks', automatic)
        self.assertNotIn('settings_coverage', automatic)
        manual = d.diagnostic_report(include_process=True)
        self.assertIn('settings_coverage', manual)
        self.assertIn('process_checks', manual)

    def test_failed_readback_revokes_existing_background_sync_grant(self):
        preview = d.preview_profile('1234', 'graphics')
        self.assertTrue(d.approve_profile('1234', 'graphics', preview['token'])['ok'])
        original = d.safe_read_text
        current = self.path.read_text()
        def read(path):
            text = original(path)
            if path == self.path and text != current: return text+'unexpected=1\n'
            return text
        with patch.object(d, 'safe_read_text', read):
            # Exercise the shared write path directly, as the background sync does.
            result = d.apply_profile(self.game, 'performance')
        self.assertEqual(result['status'], 'error')
        cfg = d.config()
        for key in ('approved','approved_files','approved_context'):
            self.assertNotIn('1234', cfg[key])
        with patch.object(d, 'apply_profile') as apply:
            d.synchronize()
        apply.assert_not_called()
