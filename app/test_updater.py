import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import updater


def make_pkg(path, version='0.9.0', bad_checksum=False, injection=False, code=None):
    root = 'deckpilot_tv_v0_9'
    payload = {
        'deckpilot.py': (code or "VERSION = '%s'\n" % version).encode(),
        'updater.py': b'pass\n',
        'VERSION.txt': ('DeckPilot TV v'+version).encode(),
        'setup_drive.sh': b'#!/bin/bash\n',
    }
    manifest = {'product': 'deckpilot-tv', 'version': version,
                'files': {n: hashlib.sha256(contents).hexdigest() for n, contents in payload.items()}}
    if bad_checksum: manifest['files']['deckpilot.py'] = '0'*64
    with zipfile.ZipFile(path,'w') as z:
        for name, contents in payload.items(): z.writestr(root+'/'+name, contents)
        if injection: z.writestr('../../evil', b'bad')
        z.writestr(root+'/'+updater.MANIFEST_NAME, json.dumps(manifest))


class TestUpdater(unittest.TestCase):
    def test_valid_package_and_install_without_service(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp); downloads=p/'Downloads'; downloads.mkdir()
            a=downloads/'DeckPilot_TV_v0.9.zip'; make_pkg(a)
            appdir=p/'app'; appdir.mkdir(); (appdir/'deckpilot.py').write_text("VERSION = '0.3.0'\n")
            (appdir/'updater.py').write_text('OLD UPDATER\n')
            (appdir/'VERSION.txt').write_text('OLD VERSION\n')
            self.assertEqual(updater.inspect_zip(a, '0.3.0')['version'], '0.9.0')
            with patch.object(updater,'APPDIR',appdir):
                latest=updater.newest_candidate(downloads, '0.3.0')
            self.assertEqual(latest['version'], '0.9.0')
            self.assertEqual(updater.install_archive(a,appdir=appdir,updates=p/'update',manage_service=False),'0.9.0')
            self.assertEqual(updater.current_version(appdir),'0.9.0')
            self.assertIn('0.3.0',(p/'update/previous-app/deckpilot.py').read_text())
    def test_rejects_corrupt_checksum(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'DeckPilot_TV_v0.9.zip';make_pkg(a,bad_checksum=True)
            with self.assertRaisesRegex(updater.UpdateError, 'SHA256'):
                updater.inspect_zip(a,'0.3.0')
    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'DeckPilot_TV_v0.9.zip';make_pkg(a,injection=True)
            with self.assertRaisesRegex(updater.UpdateError, 'structure'):
                updater.inspect_zip(a,'0.3.0')
    def test_rejects_old_version(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'DeckPilot_TV_v0.9.zip';make_pkg(a)
            with self.assertRaisesRegex(updater.UpdateError, 'not newer'):
                updater.inspect_zip(a,'0.9.0')
    def test_rolls_back_if_restart_fails(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t); a=p/'DeckPilot_TV_v0.9.zip'; make_pkg(a)
            appdir=p/'app';appdir.mkdir(); (appdir/'deckpilot.py').write_text("VERSION = '0.3.0'\n")
            with patch.object(updater, 'service_call') as ctl, patch.object(updater,'healthy',return_value=False):
                with self.assertRaisesRegex(updater.UpdateError,'rolled back'):
                    updater.install_archive(a,appdir=appdir,updates=p/'updates',manage_service=True)
            self.assertEqual(updater.current_version(appdir),'0.3.0')
            self.assertEqual(json.loads((p/'updates/result.json').read_text())['status'],'rolled-back')
            self.assertEqual(ctl.call_count, 3)


if __name__=='__main__':unittest.main()

class TestManualRollback(unittest.TestCase):
    def test_restore_previous_preserves_current_snapshot(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t); app=p/'app'; old=p/'updates/previous-app';app.mkdir();old.mkdir(parents=True)
            (app/'deckpilot.py').write_text("VERSION = '0.5.0'\n")
            (old/'deckpilot.py').write_text("VERSION = '0.3.0'\n")
            result=updater.rollback_previous(appdir=app,updates=p/'updates',manage_service=False)
            self.assertEqual(result,'0.3.0')
            self.assertEqual(updater.current_version(app),'0.3.0')
            self.assertEqual(updater.current_version(old),'0.5.0')

class TestGitHubUpdates(unittest.TestCase):
    def test_source_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.json'
            self.assertEqual(updater.configure_source('example/DeckPilot-TV',path),'example/DeckPilot-TV')
            self.assertEqual(updater.release_source(path),'example/DeckPilot-TV')
            for value in ('https://evil.example/something','example/../bad','localhost:8080/x','a'*40+'/b'):
                with self.assertRaises(updater.UpdateError):
                    updater.configure_source(value,path)
            updater.configure_source('',path)
            self.assertEqual(updater.release_source(path),'')

    def test_release_requires_github_digest_and_matching_asset(self):
        asset={'name':'DeckPilot_TV_v0.6.1.zip','digest':'sha256:'+'a'*64,
               'size':200,'browser_download_url':
               'https://github.com/example/DeckPilot-TV/releases/download/v0.6.1/DeckPilot_TV_v0.6.1.zip'}
        release={'tag_name':'v0.6.1','draft':False,'prerelease':False,'assets':[asset]}
        d=updater.remote_release_metadata(release,'0.6.0','example/DeckPilot-TV')
        self.assertEqual(d['sha256'],'a'*64)
        self.assertIsNone(updater.remote_release_metadata(release,'0.6.1','example/DeckPilot-TV'))
        release['assets'][0]['digest']=None
        with self.assertRaises(updater.UpdateError):
            updater.remote_release_metadata(release,'0.6.0','example/DeckPilot-TV')
        self.assertFalse(updater.safe_redirect_url('http://github.com/example/repo'))
        self.assertFalse(updater.safe_redirect_url('https://fake.github.com/a'))

    def test_downloads_verified_without_installing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); zpath=root/'DeckPilot_TV_v0.9.zip';make_pkg(zpath,version='0.9.0')
            raw=zpath.read_bytes();sha=hashlib.sha256(raw).hexdigest()
            url='https://github.com/example/DeckPilot-TV/releases/download/v0.9.0/DeckPilot_TV_v0.9.0.zip'
            metadata={'tag_name':'v0.9.0','draft':False,'prerelease':False,'assets':[
                {'name':'DeckPilot_TV_v0.9.0.zip','size':len(raw),'digest':'sha256:'+sha,'browser_download_url':url}]}
            def read_url(addr,limit,timeout=12):
                return json.dumps(metadata).encode() if addr.startswith('https://api.github.com/') else raw
            with patch.object(updater,'_limited_get',side_effect=read_url),\
                 patch.object(updater,'record_remote',side_effect=lambda st,msg,**kw:{'status':st,'message':msg,**kw}):
                status=updater.fetch_github_update('example/DeckPilot-TV','0.5.0',ready=root/'ready')
            self.assertEqual(status['status'],'ready')
            self.assertTrue((root/'ready'/'DeckPilot_TV_v0.9.0.zip').is_file())
