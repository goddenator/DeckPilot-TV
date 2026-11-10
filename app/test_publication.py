"""Real publisher control flow with GitHub draft semantics; all remote calls are recorded stubs."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded);return loaded
publisher=module('publisher',ROOT/'tools/publish_approved.py')
packager=module('packager',ROOT/'tools/package_release.py')

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        previous=Path.cwd();os.chdir(self.temp.name);self.addCleanup(os.chdir,previous)
        self.sha='a'*40;self.version='0.8.3-preview.2';self.ident=440744496
        self.commands=[];self.created=False;self.existing=False;self.denied=False;self.change=lambda release:None;self.late_change=False
        out=Path('out');out.mkdir()
        self.manifest={'format':1,'product':'deckpilot-tv-suite','repository':publisher.REPO,'version':self.version,'tag':'v'+self.version,'channel':'preview','commit':self.sha}
        for key,prefix in [('app','DeckPilot_TV_v'),('plugin','DeckPilot_Decky_v')]:
            name=prefix+self.version+'.zip';(out/name).write_bytes(key.encode());self.manifest[key]={'name':name,'version':self.version,'size':len(key),'sha256':hashlib.sha256(key.encode()).hexdigest(),'ui_schema':2,'update_protocol':1}
        (out/'DeckPilot-Update.json').write_text(json.dumps(self.manifest))
        self.names=[self.manifest[k]['name'] for k in ('app','plugin')]+['DeckPilot-Update.json']
        self.digests={n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in self.names}
        (out/'SHA256SUMS').write_text(''.join(self.digests[n]+'  '+n+'\n' for n in self.names));self.digests['SHA256SUMS']=hashlib.sha256((out/'SHA256SUMS').read_bytes()).hexdigest()
        self.details=0;self.remote=self.draft()
        for p in [patch.object(publisher,'print',create=True),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','APPROVED_SHA':self.sha,'APPROVED_CHANNEL':'preview','APPROVED_MODE':'publish'}),patch.object(publisher.subprocess,'run',side_effect=self.subprocess_run),patch.object(publisher.subprocess,'check_output',side_effect=self.output)]:p.start();self.addCleanup(p.stop)
    def draft(self):
        return {'id':self.ident,'url':'https://api.github.com/repos/'+publisher.REPO+'/releases/'+str(self.ident),'tag_name':self.manifest['tag'],'target_commitish':self.sha,'draft':True,'prerelease':True,'assets':[{'name':n,'digest':'sha256:'+d,'size':(Path('out')/n).stat().st_size,'state':'uploaded'} for n,d in self.digests.items()]}
    def subprocess_run(self,cmd,**kwargs):
        self.commands.append(cmd)
        def result(data,code=0):return SimpleNamespace(returncode=code,stdout=json.dumps(data),stderr='gh: Forbidden (HTTP 403)' if code else '')
        if cmd[:2]==['gh','api']:
            if self.denied:return result({},1)
            if '--paginate' in cmd:return result([[{'id':1,'tag_name':'v0.0.1'}],[self.remote] if self.created or self.existing else []])
            # The actual failure: drafts are invisible at the tag endpoint.
            if '/releases/tags/' in cmd[2]:return SimpleNamespace(returncode=1,stdout='',stderr='gh: Not Found (HTTP 404)')
            self.assertEqual(cmd[2],'repos/'+publisher.REPO+'/releases/'+str(self.ident))
            if '--method' in cmd:
                self.assertEqual(cmd[-4:],['--method','PATCH','--field','draft=false']);return result({**self.remote,'draft':False})
            self.details+=1;release=copy.deepcopy(self.remote)
            if not self.late_change or self.details>=2:self.change(release)
            return result(release)
        if 'create' in cmd and '--help' not in cmd:self.created=True
        return result({})
    def output(self,cmd,**kwargs):
        self.commands.append(cmd)
        if cmd[:2]==['git','rev-parse']:return self.sha+'\n'
        if cmd[:2]==['git','ls-remote']:return ''
        self.fail('Unexpected command: '+repr(cmd))
    def mutations(self):return [c for c in self.commands if ('release' in c and 'create' in c and '--help' not in c) or '--method' in c]
    def recover(self,preflight=False):
        self.existing=True
        with patch.dict(os.environ,{'APPROVED_MODE':'recover'}):publisher.main(preflight=preflight,recover_draft_id=self.ident)
    def test_nonpublishing_preflight_never_creates_tag_draft_or_release(self):
        publisher.main(preflight=True);self.assertEqual(self.mutations(),[])
    def test_cli_creation_then_authenticated_id_verification_never_uses_tag_lookup(self):
        publisher.main();create,finalize=self.mutations()
        self.assertEqual(create[create.index('--target')+1],self.sha);self.assertIn('--draft',create);self.assertIn('--prerelease',create)
        self.assertEqual(set(create[-4:]),{'out/'+n for n in self.digests});self.assertEqual(finalize[2],'repos/'+publisher.REPO+'/releases/'+str(self.ident))
        self.assertEqual(self.details,2);self.assertFalse(any('/releases/tags/' in ' '.join(c) for c in self.commands))
    def test_permission_error_cannot_be_mistaken_for_missing_release(self):
        self.denied=True
        with self.assertRaisesRegex(ValueError,'permissions/access'):publisher.main(preflight=True)
        self.assertEqual(self.mutations(),[])
    def test_all_four_digests_checked_before_publication(self):
        for name in self.digests:
            self.commands=[];self.created=False
            self.change=lambda r,n=name:next(a for a in r['assets'] if a['name']==n).update(digest='sha256:'+'0'*64)
            with self.subTest(asset=name),self.assertRaisesRegex(ValueError,'SHA256'):publisher.main()
            self.assertEqual(len(self.mutations()),1);self.assertIn('create',self.mutations()[0])
    def test_existing_draft_is_not_implicitly_recovered_or_reuploaded(self):
        self.existing=True
        with self.assertRaisesRegex(ValueError,'explicit owner-approved recovery'):publisher.main()
        self.assertEqual(self.mutations(),[])
    def test_explicit_exact_draft_recovery_only_finalizes_by_id(self):
        self.recover();self.assertEqual(len(self.mutations()),1);self.assertIn('PATCH',self.mutations()[0]);self.assertEqual(self.details,3)
    def test_recovery_preflight_is_read_only_even_with_existing_valid_draft(self):
        self.recover(preflight=True);self.assertEqual(self.mutations(),[])
    def test_recovery_requires_explicit_approved_mode_and_exact_id(self):
        with self.assertRaisesRegex(ValueError,'owner-approved'):publisher.main(recover_draft_id=self.ident)
        with patch.dict(os.environ,{'APPROVED_MODE':'recover'}),self.assertRaisesRegex(ValueError,'unique exact tag match'):publisher.main(recover_draft_id=self.ident+1)
        self.assertEqual(self.mutations(),[])
    def test_recovery_rejects_published_release_and_wrong_source_tag_commit_channel(self):
        changes=[lambda r:r.update(draft=False),lambda r:r.update(target_commitish='b'*40),lambda r:r.update(target_commitish='main'),lambda r:r.update(prerelease=False),lambda r:r.update(tag_name='v0.8.3-preview.1'),lambda r:r.update(url=r['url'].replace('goddenator','attacker')),lambda r:r.update(id=self.ident+1)]
        for change in changes:
            self.change=change;self.commands=[]
            with self.subTest(change=change),self.assertRaises(ValueError):self.recover()
            self.assertEqual(self.mutations(),[])
    def test_recovery_rejects_missing_extra_duplicate_incomplete_and_resized_assets(self):
        changes=[lambda r:r['assets'].pop(),lambda r:r['assets'].append({**r['assets'][0],'name':'unexpected.zip'}),lambda r:r['assets'].__setitem__(1,copy.deepcopy(r['assets'][0])),lambda r:r['assets'][0].update(state='new'),lambda r:r['assets'][0].update(size=999),lambda r:r['assets'][0].update(digest=None)]
        for change in changes:
            self.change=change;self.commands=[]
            with self.subTest(change=change),self.assertRaises(ValueError):self.recover()
            self.assertEqual(self.mutations(),[])
    def test_tampering_between_recovery_checks_aborts_finalization(self):
        self.late_change=True;self.change=lambda r:r['assets'][0].update(digest='sha256:'+'0'*64)
        with self.assertRaisesRegex(ValueError,'SHA256'):self.recover()
        self.assertEqual(self.mutations(),[])
    def test_already_created_old_approved_head_cannot_be_recovered_after_code_change(self):
        self.remote['target_commitish']='07e6692a2b4584ba2e0965b5e7247076ee9291af'
        with self.assertRaisesRegex(ValueError,'approved commit'):self.recover()
        self.assertEqual(self.mutations(),[])
    def test_existing_tag_stops_new_creation_and_mismatched_tag_stops_recovery(self):
        with patch.object(publisher.subprocess,'check_output',side_effect=[self.sha+'\n',self.sha+' refs/tags/'+self.manifest['tag']+'\n']):
            with self.assertRaisesRegex(ValueError,'Tag already exists'):publisher.main(preflight=True)
        with patch.object(publisher.subprocess,'check_output',side_effect=[self.sha+'\n','b'*40+' refs/tags/'+self.manifest['tag']+'\n']):
            with self.assertRaisesRegex(ValueError,'approved commit'):self.recover()
        self.assertEqual(self.mutations(),[])
    def test_matching_annotated_tag_can_be_recovered_without_rewriting_it(self):
        refs='c'*40+' refs/tags/'+self.manifest['tag']+'\n'+self.sha+' refs/tags/'+self.manifest['tag']+'^{}\n'
        with patch.object(publisher.subprocess,'check_output',side_effect=[self.sha+'\n',refs,refs]):self.recover()
        self.assertEqual(len(self.mutations()),1)
    def test_changed_checkout_stops_before_github_calls(self):
        with patch.object(publisher.subprocess,'check_output',return_value='b'*40+'\n'):
            with self.assertRaisesRegex(ValueError,'Checkout changed'):publisher.main(preflight=True)
        self.assertEqual(self.commands,[])
    def test_published_collision_and_duplicate_exact_drafts_fail_closed(self):
        self.existing=True;self.remote['draft']=False
        with self.assertRaisesRegex(ValueError,'already exists'):publisher.main(preflight=True)
        with patch.object(publisher.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps([[self.remote,self.remote]]))):
            with self.assertRaisesRegex(ValueError,'Multiple releases'):publisher.main(preflight=True)
        self.assertEqual(self.mutations(),[])

    def test_interrupted_post_creation_lookup_leaves_draft_and_retry_needs_explicit_recovery(self):
        transport=self.subprocess_run
        def fail_read(cmd,**kwargs):
            if cmd[:2]==['gh','api'] and cmd[2]=='repos/'+publisher.REPO+'/releases/'+str(self.ident):
                return SimpleNamespace(returncode=1,stdout='',stderr='gh: Forbidden (HTTP 403)')
            return transport(cmd,**kwargs)
        with patch.object(publisher.subprocess,'run',side_effect=fail_read),self.assertRaisesRegex(ValueError,'no automatic retry'):publisher.main()
        self.assertTrue(self.created);self.assertEqual(len(self.mutations()),1)
        with self.assertRaisesRegex(ValueError,'explicit owner-approved recovery'):publisher.main()
        self.assertEqual(len(self.mutations()),1)
    def test_local_checksum_tampering_stops_before_remote_calls(self):
        (Path('out')/'SHA256SUMS').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'Checksum mismatch'):self.recover()
        self.assertEqual(self.commands,[])

class ReproduciblePackagingTests(unittest.TestCase):
    def test_same_source_and_commit_produce_identical_four_assets_despite_mtimes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);app=root/'app';decky=root/'decky';app.mkdir();(decky/'dist').mkdir(parents=True)
            for name in packager.APP_FILES:(app/name).write_text('fixture')
            (app/'deckpilot.py').write_text("VERSION = '0.8.3'\nBUILD_ID = '0.8.3-preview.2'\n");(app/'VERSION.txt').write_text('0.8.3-preview.2')
            for name in ['plugin.json','main.py','LICENSE','README.md','dist/index.js']:(decky/name).write_text('fixture')
            (decky/'package.json').write_text(json.dumps({'version':'0.8.3-preview.2'}))
            with patch.object(packager,'ROOT',root),patch.object(packager.subprocess,'check_output',return_value='a'*40+'\n'):
                packager.package(root/'first')
                for path in [*app.iterdir(),*decky.iterdir(),decky/'dist/index.js']:
                    if path.is_file():os.utime(path,(1800000000,1800000000))
                packager.package(root/'second')
            files=list((root/'first').iterdir());self.assertEqual(len(files),4)
            for path in files:self.assertEqual(path.read_bytes(),(root/'second'/path.name).read_bytes(),path.name)
