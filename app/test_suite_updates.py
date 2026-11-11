"""Paired update trust, approval, crash recovery and local Decky transport contracts."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile
import updater as u
from test_updater import make_pkg

class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.updates=self.root/'updates';self.updates.mkdir();self.app=self.root/'app';self.app.mkdir()
        (self.app/'deckpilot.py').write_text("VERSION = '0.8.2'\n")
        for key,value in {'UPDATES':self.updates,'SUITE_STATE':self.updates/'suite.json','CHANNEL_FILE':self.updates/'channel.json'}.items():
            p=patch.object(u,key,value);p.start();self.addCleanup(p.stop)
        p=patch.object(u,'current_version',return_value='0.8.2');p.start();self.addCleanup(p.stop)
    def release(self,version='0.8.3-preview.1'):
        app=self.root/('DeckPilot_TV_v'+version+'.zip')
        make_pkg(app,version,code="VERSION = '%s'\nBUILD_ID = '%s'\n"%(version.split('-')[0],version))
        plugin=self.root/('DeckPilot_Decky_v'+version+'.zip')
        with zipfile.ZipFile(plugin,'w') as z:
            for name in u.PLUGIN_FILES:
                content='pass\n' if name.endswith('.py') else 'test'
                if name=='plugin.json':content=json.dumps({'name':'DeckPilot TV','flags':[]})
                if name=='package.json':content=json.dumps({'name':'deckpilot-tv-decky','version':version,'deckpilot':{'product':'deckpilot-tv','ui_schema':2,'update_protocol':1}})
                z.writestr('DeckPilot/'+name,content)
        manifest={'format':1,'product':u.SUITE_PRODUCT,'repository':u.TRUSTED_REPOSITORY,'version':version,'tag':'v'+version,'channel':'preview' if '-' in version else 'stable','commit':'a'*40}
        for key,path in [('app',app),('plugin',plugin)]:manifest[key]={'name':path.name,'version':version,'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'ui_schema':2,'update_protocol':1}
        raw={app.name:app.read_bytes(),plugin.name:plugin.read_bytes(),u.SUITE_MANIFEST:json.dumps(manifest).encode()}
        raw['SHA256SUMS']=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in raw.items()).encode()
        release={'tag_name':'v'+version,'draft':False,'prerelease':'-' in version,'html_url':'https://github.com/'+u.TRUSTED_REPOSITORY+'/releases/tag/v'+version,'assets':[]}
        for name,data in raw.items():release['assets'].append({'name':name,'size':len(data),'digest':'sha256:'+hashlib.sha256(data).hexdigest(),'browser_download_url':'https://github.com/'+u.TRUSTED_REPOSITORY+'/releases/download/v'+version+'/'+name})
        return release,raw
    def stage(self):
        release,raw=self.release();u.set_suite_channel('preview')
        def get(url,*args,**kwargs):return json.dumps([release]).encode() if '/releases?' in url else raw[url.rsplit('/',1)[1]]
        with patch.object(u,'_limited_get',side_effect=get):result=u.fetch_suite_update()
        self.assertEqual(result['status'],'ready');return result,release,raw
    def test_default_stable_and_preview_excludes_drafts(self):
        preview,_=self.release();stable,_=self.release('0.8.3');draft={**preview,'draft':True,'tag_name':'v99.0.0-preview.1'}
        self.assertEqual(u.suite_channel(),'stable')
        self.assertEqual(u.select_suite_release([draft,preview,stable],'stable'),stable)
        self.assertEqual(u.select_suite_release([draft,preview,stable],'preview'),preview)
        self.assertLess(u.semver('0.8.3-preview.9'),u.semver('0.8.3'))
    def test_stage_both_components_offline_cache_and_channel_invalidates_approval(self):
        state,_,_=self.stage();token=state['token']
        self.assertTrue(u.suite_status('0.8.2')['app_first'])
        with patch.object(u,'_limited_get',side_effect=OSError('offline')):u.fetch_suite_update()
        self.assertEqual(u.suite_proposal(token)['token'],token)
        u.set_suite_channel('stable')
        with self.assertRaisesRegex(u.UpdateError,'Channel changed'):u.suite_proposal(token)
    def test_tampered_cache_and_stale_approval_rejected(self):
        state,_,_=self.stage()
        with self.assertRaises(u.UpdateError):u.suite_proposal('wrong-token')
        proposal=state['proposal'];(Path(proposal['folder'])/proposal['assets']['plugin']['name']).write_bytes(b'bad')
        with self.assertRaisesRegex(u.UpdateError,'changed'):u.suite_proposal(state['token'])
    def test_wrong_repository_missing_digest_duplicate_and_partial_release(self):
        release,_=self.release();name=release['assets'][0]['name']
        for mutation in ('url','digest','duplicate','missing','malformed'):
            changed=json.loads(json.dumps(release))
            if mutation=='url':changed['assets'][0]['browser_download_url']=changed['assets'][0]['browser_download_url'].replace('goddenator','attacker')
            if mutation=='digest':changed['assets'][0]['digest']=None
            if mutation=='duplicate':changed['assets'].append(changed['assets'][0])
            if mutation=='missing':changed['assets']=[]
            if mutation=='malformed':changed['assets']=None
            with self.subTest(mutation=mutation),self.assertRaises(u.UpdateError):u.release_asset(changed,name,u.MAX_ZIP_BYTES)
    def test_corrupted_download_or_manifest_never_installs(self):
        release,raw=self.release();u.set_suite_channel('preview');raw['SHA256SUMS']=b'corrupt'
        with patch.object(u,'_limited_get',side_effect=lambda url,*a,**k:json.dumps([release]).encode() if '/releases?' in url else raw[url.rsplit('/',1)[1]]),patch.object(u,'install_archive') as install:
            self.assertEqual(u.fetch_suite_update()['status'],'error');install.assert_not_called()
    def test_protocol_incompatible_rejected(self):
        release,raw=self.release();manifest=json.loads(raw[u.SUITE_MANIFEST]);assets={k:{f:manifest[k][f] for f in ('name','size','sha256')} for k in ('app','plugin')}
        manifest['plugin']['ui_schema']=999
        with self.assertRaisesRegex(u.UpdateError,'incompatible'):u.validate_suite_manifest(manifest,release,assets,'preview')
    def test_downgrade_requires_explicit_approval_and_duplicate_queue_blocked(self):
        state,_,_=self.stage()
        with patch.object(u,'current_version',return_value='1.0.0'),self.assertRaisesRegex(u.UpdateError,'explicit approval'):u.start_suite_install(state['token'])
        u.atomic_record(self.updates/'approved-app.json',{'approved_at':time.time()});u.atomic_record(self.updates/'result.json',{'status':'queued'})
        with patch.object(u.shutil,'which',return_value='/bin/systemd-run'),self.assertRaisesRegex(u.UpdateError,'already in progress'):u.start_suite_install(state['token'])
    def test_plugin_requires_healthy_matching_app(self):
        state,_,_=self.stage()
        with self.assertRaisesRegex(u.UpdateError,'app update first'):u.prepare_plugin_handoff(state['token'],self.root)
    def test_plugin_snapshot_read_only_and_traversal_rejected(self):
        _,raw=self.release();plugin=self.root/'installed';plugin.mkdir()
        with zipfile.ZipFile(self.root/'DeckPilot_Decky_v0.8.3-preview.1.zip') as z:z.extractall(plugin)
        root=plugin/'DeckPilot';before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
        saved=u.snapshot_plugin(root);self.assertEqual(u.inspect_plugin_zip(saved['path'])['version'],'0.8.3-preview.1')
        self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))
        bad=self.root/'bad.zip'
        with zipfile.ZipFile(bad,'w') as z:z.writestr('DeckPilot/../../other/main.py','bad')
        with self.assertRaises(u.UpdateError):u.inspect_plugin_zip(bad)
    def test_loopback_serves_only_nonce_and_expires(self):
        self.release();path=self.root/'DeckPilot_Decky_v0.8.3-preview.1.zip';dest=self.updates/path.name;dest.write_bytes(path.read_bytes())
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        descriptor=self.updates/'handoff-test.json';nonce='a'*43
        u.atomic_record(descriptor,{'path':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'nonce':nonce,'port':port,'expires':time.time()+1.2})
        thread=threading.Thread(target=u.serve_plugin,args=(descriptor,));thread.start();self.addCleanup(lambda:thread.join(3))
        url='http://127.0.0.1:'+str(port)+'/'
        for attempt in range(30):
            try:
                with urllib.request.urlopen(url+nonce+'/DeckPilot.zip',timeout=1) as response:self.assertEqual(response.read(),dest.read_bytes())
                break
            except OSError:
                if attempt==29:raise
                time.sleep(.02)
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+'other/DeckPilot.zip')
        self.assertEqual(error.exception.code,404);thread.join(3);self.assertFalse(thread.is_alive());self.assertFalse(descriptor.exists())
    def test_crash_persists_snapshot_and_recovery_preserves_preferences(self):
        for name in u.APP_FILES:(self.app/name).write_text("VERSION = '0.8.2'\n" if name=='deckpilot.py' else 'old')
        config=self.root/'preferences.json';config.write_text('precious');backup=u.begin_recovery_snapshot(self.app,self.updates,'0.8.3')
        (self.app/'deckpilot.py').write_text('partial broken write')
        self.assertTrue((backup/'deckpilot.py').is_file())
        u.recover_interrupted(appdir=self.app,updates=self.updates,manage_service=False)
        self.assertIn('0.8.2',(self.app/'deckpilot.py').read_text());self.assertEqual(config.read_text(),'precious');self.assertFalse((self.updates/'transaction.json').exists())
    def test_corrupt_recovery_never_overwrites_current(self):
        backup=u.begin_recovery_snapshot(self.app,self.updates,'0.8.3');(backup/'deckpilot.py').write_text('tampered')
        with self.assertRaisesRegex(u.UpdateError,'missing or changed'):u.recover_interrupted(appdir=self.app,updates=self.updates,manage_service=False)
        self.assertIn('0.8.2',(self.app/'deckpilot.py').read_text())
    def test_process_death_mid_replacement_keeps_recovery_available(self):
        pkg=self.root/'DeckPilot_TV_v0.8.3.zip';make_pkg(pkg,'0.8.3')
        (self.app/'updater.py').write_text('original updater');(self.app/'VERSION.txt').write_text('original version')
        replace=u.os.replace
        def killed(source,dest):
            if Path(dest)==self.app/'updater.py':raise SystemExit('simulated process death')
            return replace(source,dest)
        with patch.object(u.os,'replace',side_effect=killed),self.assertRaises(SystemExit):u.install_archive(pkg,appdir=self.app,updates=self.updates,manage_service=False)
        self.assertIn('0.8.3',(self.app/'deckpilot.py').read_text());self.assertTrue((self.updates/'transaction.json').exists())
        u.recover_interrupted(appdir=self.app,updates=self.updates,manage_service=False)
        self.assertIn('0.8.2',(self.app/'deckpilot.py').read_text());self.assertEqual((self.app/'updater.py').read_text(),'original updater')
    def test_publisher_validates_exact_commit_channel_and_checksums(self):
        release,raw=self.release()
        spec=importlib.util.spec_from_file_location('publish_approved',Path(__file__).parents[1]/'tools/publish_approved.py');publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
        for name,data in raw.items():(self.root/name).write_bytes(data)
        publisher.validate(self.root,'a'*40,'preview')
        for sha,channel in [('b'*40,'preview'),('a'*40,'stable')]:
            with self.assertRaises(ValueError):publisher.validate(self.root,sha,channel)
        (self.root/'SHA256SUMS').write_text('tampered')
        with self.assertRaises(ValueError):publisher.validate(self.root,'a'*40,'preview')
    def test_verified_handoff_saves_old_plugin_and_serves_target(self):
        from types import SimpleNamespace
        state,_,_=self.stage();self.release('0.8.2');installed=self.root/'old-plugin'
        with zipfile.ZipFile(self.root/'DeckPilot_Decky_v0.8.2.zip') as z:z.extractall(installed)
        threads=[];server=u.serve_plugin
        def run(cmd,**kwargs):
            descriptor=Path(cmd[-1]);data=json.loads(descriptor.read_text());data['expires']=time.time()+1.5;u.atomic_record(descriptor,data)
            thread=threading.Thread(target=server,args=(descriptor,));threads.append(thread);thread.start()
            return SimpleNamespace(returncode=0)
        with patch.object(u,'current_version',return_value='0.8.3-preview.1'),patch.object(u.shutil,'which',return_value='/bin/systemd-run'),patch.object(u.subprocess,'run',side_effect=run):
            result=u.prepare_plugin_handoff(state['token'],installed/'DeckPilot')
            with urllib.request.urlopen(result['url']) as response:downloaded=response.read()
            self.assertEqual(hashlib.sha256(downloaded).hexdigest(),result['sha256'])
            saved=json.loads((self.updates/'plugin-rollback.json').read_text());self.assertEqual(saved['version'],'0.8.2');self.assertTrue(Path(saved['path']).is_file())
            self.assertEqual(json.loads((installed/'DeckPilot/package.json').read_text())['version'],'0.8.2')
        for thread in threads:thread.join(3)
