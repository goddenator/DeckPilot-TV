"""Rehearse the real CLI publisher with a recording subprocess transport; no writes to GitHub."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('publisher',Path(__file__).parents[1]/'tools/publish_approved.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        previous=Path.cwd();os.chdir(self.temp.name);self.addCleanup(os.chdir,previous)
        self.sha='a'*40;self.version='0.8.3-preview.1';self.commands=[];self.bad_digest=False;self.denied=False
        out=Path('out');out.mkdir()
        manifest={'format':1,'product':'deckpilot-tv-suite','repository':publisher.REPO,'version':self.version,'tag':'v'+self.version,'channel':'preview','commit':self.sha}
        for key,prefix in [('app','DeckPilot_TV_v'),('plugin','DeckPilot_Decky_v')]:
            name=prefix+self.version+'.zip';(out/name).write_bytes(key.encode());manifest[key]={'name':name,'version':self.version,'size':len(key),'sha256':hashlib.sha256(key.encode()).hexdigest()}
        (out/'DeckPilot-Update.json').write_text(json.dumps(manifest))
        self.names=[manifest[k]['name'] for k in ('app','plugin')]+['DeckPilot-Update.json']
        self.digests={n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in self.names}
        (out/'SHA256SUMS').write_text(''.join(self.digests[n]+'  '+n+'\n' for n in self.names));self.digests['SHA256SUMS']=hashlib.sha256((out/'SHA256SUMS').read_bytes()).hexdigest()
        for p in [patch.dict(os.environ,{'GITHUB_ACTIONS':'true','APPROVED_SHA':self.sha,'APPROVED_CHANNEL':'preview'}),patch.object(publisher.subprocess,'run',side_effect=self.subprocess_run),patch.object(publisher.subprocess,'check_output',side_effect=self.output)]:p.start();self.addCleanup(p.stop)
    def subprocess_run(self,cmd,**kwargs):
        self.commands.append(cmd)
        if cmd[:2]==['gh','api']:return SimpleNamespace(returncode=1,stderr='gh: HTTP 403 (HTTP 403)' if self.denied else 'gh: Not Found (HTTP 404)')
        return SimpleNamespace(returncode=0)
    def output(self,cmd,**kwargs):
        self.commands.append(cmd)
        if cmd[:2]==['git','rev-parse']:return self.sha+'\n'
        if cmd[:2]==['git','ls-remote']:return ''
        if cmd[:2]==['gh','api']:return json.dumps({'assets':[{'name':n,'digest':'sha256:'+('0'*64 if self.bad_digest else d)} for n,d in self.digests.items()]})
        self.fail('Unexpected command: '+repr(cmd))
    def mutations(self):return [c for c in self.commands if 'release' in c and any(v in c for v in ('create','edit')) and '--help' not in c]
    def test_nonpublishing_preflight_exercises_real_cli_plan_without_writes(self):
        publisher.main(preflight=True);self.assertEqual(self.mutations(),[])
        self.assertTrue(any(c[:2]==['gh','api'] for c in self.commands));self.assertTrue(any('create' in c and '--help' in c for c in self.commands))
    def test_approved_preview_targets_exact_unmerged_sha_and_verifies_before_publish(self):
        publisher.main();create,edit=self.mutations()
        self.assertEqual(create[create.index('--target')+1],self.sha);self.assertIn('--draft',create);self.assertIn('--prerelease',create);self.assertEqual(edit[-1],'--draft=false')
        self.assertEqual(set(create[-4:]),{'out/'+n for n in self.digests})
        verify=next(i for i,c in enumerate(self.commands) if c[:2]==['gh','api'] and i>self.commands.index(create))
        self.assertLess(verify,self.commands.index(edit))
    def test_api_permission_error_cannot_be_mistaken_for_missing_release(self):
        self.denied=True
        with self.assertRaisesRegex(ValueError,'permissions/access'):publisher.main(preflight=True)
        self.assertEqual(self.mutations(),[])
    def test_corrupt_uploaded_digest_leaves_draft_unpublished(self):
        self.bad_digest=True
        with self.assertRaisesRegex(ValueError,'draft left unpublished'):publisher.main()
        self.assertEqual(len(self.mutations()),1);self.assertIn('create',self.mutations()[0])
    def test_existing_tag_stops_preflight_and_publication(self):
        with patch.object(publisher.subprocess,'check_output',side_effect=[self.sha+'\n','existing-tag']):
            with self.assertRaisesRegex(ValueError,'Tag already exists'):publisher.main(preflight=True)
        self.assertEqual(self.mutations(),[])
    def test_changed_checkout_stops_before_github_calls(self):
        with patch.object(publisher.subprocess,'check_output',return_value='b'*40+'\n'):
            with self.assertRaisesRegex(ValueError,'Checkout changed'):publisher.main(preflight=True)
        self.assertEqual(self.commands,[])
