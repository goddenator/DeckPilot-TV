"""Gaming Mode ZIP pickup: simulated Loader, real ZIP/filesystem/readback tests."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import updater as u
import test_suite_updates as suites


class GamingModeUpdateTests(unittest.TestCase):
    release = suites.SuiteTests.release
    stage = suites.SuiteTests.stage

    def setUp(self):
        suites.SuiteTests.setUp(self)
        self.pickup = self.root / 'DeckPilot Updates'
        p = patch.object(u, 'PLUGIN_PICKUP', self.pickup); p.start(); self.addCleanup(p.stop)
        self.target = '0.8.3-preview.1'

    def installed(self, version='0.8.2'):
        self.release(version)
        parent = self.root / ('loader-' + version)
        with zipfile.ZipFile(self.root / ('DeckPilot_Decky_v' + version + '.zip')) as archive:
            archive.extractall(parent)  # Our own allowlisted synthetic fixture only.
        return parent / 'DeckPilot'

    def prepare(self, token, installed, rollback=False):
        with patch.object(u, 'current_version', return_value=self.target), patch.object(u, 'running_app_version', return_value=self.target):
            return u.prepare_plugin_file(token, installed, rollback)

    def loader_install(self, installed):
        with zipfile.ZipFile(self.pickup / 'DeckPilot.zip') as archive:
            archive.extractall(installed.parent)  # Simulate Loader's separate confirmed transaction.

    def test_verified_pickup_does_not_install_and_complete_requires_live_app_and_exact_files(self):
        state, _, _ = self.stage(); installed = self.installed()
        before = {p.relative_to(installed): p.read_bytes() for p in installed.rglob('*') if p.is_file()}
        result = self.prepare(state['token'], installed)
        self.assertEqual(result['method'], 'decky-install-from-zip')
        self.assertNotIn('url', result)
        self.assertEqual(hashlib.sha256((self.pickup/'DeckPilot.zip').read_bytes()).hexdigest(), result['sha256'])
        self.assertTrue(all((installed/p).read_bytes() == raw for p,raw in before.items()))
        self.assertEqual(u.plugin_installation_status(installed, self.target)['status'], 'awaiting-decky')
        self.loader_install(installed)
        self.assertEqual(u.plugin_installation_status(installed, '0.8.2')['status'], 'plugin-verified')
        checked = u.plugin_installation_status(installed, self.target)
        self.assertEqual(checked['status'], 'complete')
        self.assertEqual(checked['files_verified'], len(u.PLUGIN_FILES))
        (installed/'dist/index.js').write_text('wrong same-version bundle')
        self.assertEqual(u.plugin_installation_status(installed, self.target)['status'], 'changed')

    def test_app_source_version_without_matching_running_service_cannot_prepare_plugin(self):
        state, _, _ = self.stage(); installed = self.installed()
        with patch.object(u,'current_version',return_value=self.target),patch.object(u,'running_app_version',return_value='0.8.2'):
            with self.assertRaisesRegex(u.UpdateError, 'restart successfully'):
                u.prepare_plugin_file(state['token'], installed)
        self.assertFalse(self.pickup.exists())

    def test_untrusted_folder_symlink_or_untracked_file_is_preserved(self):
        state, _, _ = self.stage(); installed = self.installed()
        outside = self.root/'outside'; outside.mkdir(); self.pickup.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(u.UpdateError, 'unsafe link'): self.prepare(state['token'], installed)
        self.assertEqual(list(outside.iterdir()), [])
        self.pickup.unlink(); self.pickup.mkdir()
        u.atomic_record(self.pickup/'.deckpilot-owned.json', u.PICKUP_MARKER)
        user = self.pickup/'DeckPilot.zip'; user.write_bytes(b'not owned')
        with self.assertRaisesRegex(u.UpdateError, 'untracked'): self.prepare(state['token'], installed)
        self.assertEqual(user.read_bytes(), b'not owned')

    def test_low_disk_space_cannot_replace_existing_prepared_zip_or_touch_live_plugin(self):
        state, _, _ = self.stage(); installed = self.installed(); self.prepare(state['token'], installed)
        before = (self.pickup/'DeckPilot.zip').read_bytes()
        with patch.object(u.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(u.UpdateError, 'free space'): self.prepare(state['token'], installed)
        self.assertEqual((self.pickup/'DeckPilot.zip').read_bytes(), before)
        self.assertEqual(json.loads((installed/'package.json').read_text())['version'], '0.8.2')

    def test_permission_failure_leaves_previous_pickup_and_live_plugin_untouched(self):
        state, _, _ = self.stage(); installed = self.installed(); self.prepare(state['token'], installed)
        before = (self.pickup/'DeckPilot.zip').read_bytes()
        original = u.tempfile.NamedTemporaryFile
        def deny(*args, **kwargs):
            if kwargs.get('dir') == self.pickup: raise PermissionError('simulated readonly pickup')
            return original(*args, **kwargs)
        with patch.object(u.tempfile,'NamedTemporaryFile',side_effect=deny),self.assertRaises(PermissionError):
            self.prepare(state['token'], installed)
        self.assertEqual((self.pickup/'DeckPilot.zip').read_bytes(), before)

    def test_offline_pickup_needs_no_clipboard_url_server_or_additional_download(self):
        state, _, _ = self.stage(); installed = self.installed()
        with patch.object(u,'_limited_get',side_effect=AssertionError('Unexpected network')),patch.object(u.subprocess,'run',side_effect=AssertionError('Unexpected installer/helper')):
            result = self.prepare(state['token'], installed)
        self.assertTrue(result['ok'])

    def test_stale_approval_and_corrupt_cached_zip_cannot_expose_a_pickup(self):
        state, _, _ = self.stage(); installed = self.installed()
        with self.assertRaises(u.UpdateError): self.prepare('stale', installed)
        asset = state['proposal']['assets']['plugin']
        (Path(state['proposal']['folder'])/asset['name']).write_bytes(b'wrong ZIP')
        with self.assertRaises(u.UpdateError): self.prepare(state['token'], installed)
        self.assertFalse(self.pickup.exists())

    def test_rollback_uses_same_controller_file_path_and_keeps_newer_plugin_snapshot(self):
        state, _, _ = self.stage(); installed = self.installed(); self.prepare(state['token'], installed)
        self.loader_install(installed)
        result = self.prepare('', installed, rollback=True)
        self.assertEqual(result['version'], '0.8.2')
        self.loader_install(installed)
        self.assertEqual(u.plugin_installation_status(installed, '0.8.2')['status'], 'complete')
        saved = json.loads((self.updates/'plugin-rollback.json').read_text())
        self.assertEqual(saved['version'], self.target)

    def test_receipt_and_installed_links_fail_closed_without_private_metadata(self):
        state, _, _ = self.stage(); installed = self.installed(); self.prepare(state['token'], installed)
        self.loader_install(installed)
        path = installed/'dist/index.js'; path.unlink(); path.symlink_to(self.root/'private')
        result = u.plugin_installation_status(installed, self.target)
        self.assertEqual(result['status'], 'unreadable')
        self.assertNotIn(str(self.root), json.dumps(result))
        u.atomic_record(self.updates/u.PLUGIN_RECEIPT, {'format':1,'kind':'update','version':self.target,'files':{'../save':{}}})
        self.assertEqual(u.plugin_installation_status(installed, self.target)['status'], 'unreadable')

    def test_status_is_lightweight_but_mutations_still_verify_cached_bytes(self):
        state, _, _ = self.stage()
        with patch.object(u,'suite_proposal',wraps=u.suite_proposal) as proposal:
            self.assertTrue(u.suite_status('0.8.2')['available'])
        proposal.assert_called_once_with(verify_files=False)
        app = state['proposal']['assets']['app']
        (Path(state['proposal']['folder'])/app['name']).write_bytes(b'changed')
        with self.assertRaises(u.UpdateError): u.suite_proposal(state['token'])

    def test_rollback_queue_blocks_duplicates_channels_and_plugin_preparation(self):
        state, _, _ = self.stage(); installed = self.installed()
        previous = self.updates/'previous-app'; previous.mkdir(); (previous/'deckpilot.py').write_text("VERSION = '0.8.1'\n")
        with patch.object(u.shutil,'which',return_value='/bin/systemd-run'),patch.object(u.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(u.start_suite_rollback()['ok'])
            with self.assertRaisesRegex(u.UpdateError,'already in progress'): u.start_suite_rollback()
            with self.assertRaises(u.UpdateError): u.start_suite_install(state['token'])
            with self.assertRaises(u.UpdateError): u.set_suite_channel('stable')
            with self.assertRaises(u.UpdateError): self.prepare(state['token'], installed)
            self.assertEqual(run.call_count, 1)
        self.assertEqual(u.suite_status()['operation']['status'], 'queued')

    def test_malformed_operation_record_is_not_a_status_crash(self):
        u.atomic_record(self.updates/'result.json', ['bad state'])
        self.assertNotIn('operation', u.suite_status())

    def test_bootstrap_verifies_cached_approved_installation_without_prior_pickup(self):
        self.stage(); installed = self.installed(self.target)
        with patch.object(u,'running_app_version',return_value=self.target):
            result=u.verify_suite_installation(installed)
        self.assertTrue(result['ok'])
        self.assertEqual(result['installation']['status'],'complete')
        self.assertFalse(self.pickup.exists())

    def test_snapshot_detects_loader_changes_instead_of_saving_a_mixed_plugin(self):
        installed=self.installed();original=Path.open;reads=0
        def read(path,*args,**kwargs):
            nonlocal reads
            if path==installed/'main.py' and args and args[0]=='rb':
                reads+=1
                if reads==2:(installed/'main.py').write_text('changed by simulated Loader\n')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',read),self.assertRaisesRegex(u.UpdateError,'changed during snapshot'):
            u.snapshot_plugin(installed)
        self.assertFalse((self.updates/'plugin-backups/DeckPilot_Decky_v0.8.2.zip').exists())

    def test_update_diagnostics_never_export_paths_tokens_fingerprints_or_private_raw_state(self):
        u.atomic_record(self.updates/'result.json',{'status':'error','message':'/private/person/password'})
        u.atomic_record(self.updates/u.PLUGIN_RECEIPT,{'version':self.target,'token':'secret','path':'/private/person','files':{'secret':'contents'}})
        summary=u.update_diagnostic_summary();raw=json.dumps(summary)
        self.assertEqual(summary['operation'],'error')
        for value in ('private','secret','password','contents','token','sha256'):
            self.assertNotIn(value,raw)
        u.atomic_record(self.updates/'result.json',{'status':[]})
        self.assertEqual(u.update_diagnostic_summary()['operation'],'unknown')

    def test_identity_endpoint_returns_only_versions_and_never_scans_the_library(self):
        import threading
        import urllib.request
        import urllib.error
        import deckpilot as d
        server=d.ThreadingHTTPServer(('127.0.0.1',0),d.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/api/identity'
            with patch.object(d,'installed_games',side_effect=AssertionError('Identity must not scan games')):
                request=urllib.request.Request(url,headers={'Host':'127.0.0.1:38647'})
                with urllib.request.urlopen(request) as response:identity=json.load(response)
                self.assertEqual(identity,{'version':d.VERSION,'build_id':d.BUILD_ID})
                request=urllib.request.Request(url,headers={'Host':'untrusted.example'})
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,403)
        finally:server.shutdown();thread.join(3);server.server_close()

    def test_bootstrap_after_an_older_receipt_checks_the_current_approved_package(self):
        self.stage();installed=self.installed(self.target)
        u.atomic_record(self.updates/u.PLUGIN_RECEIPT,{'format':1,'version':'0.8.2','kind':'update','files':{}})
        with patch.object(u,'running_app_version',return_value=self.target):
            self.assertTrue(u.verify_suite_installation(installed)['ok'])
        receipt=json.loads((self.updates/u.PLUGIN_RECEIPT).read_text())
        self.assertEqual(receipt['version'],self.target)
        self.assertEqual(set(receipt['files']),u.PLUGIN_FILES)

    def test_live_transaction_is_not_mislabelled_interrupted_until_operation_is_stale(self):
        (self.updates/'transaction.json').write_text('{}')
        u.record('working','Installing app',self.target)
        self.assertFalse(u.suite_status()['recovery_required'])
        work=json.loads((self.updates/'result.json').read_text());work['timestamp_utc']='2020-01-01T00:00:00+00:00'
        u.atomic_record(self.updates/'result.json',work)
        self.assertTrue(u.suite_status()['recovery_required'])
