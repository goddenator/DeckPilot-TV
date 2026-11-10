"""Offline public-interface contract tests and local config integration tests.

Fixtures are synthetic; these do not assert current third-party live schemas.
"""
import asyncio
from contextlib import ExitStack
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch
import urllib.error
import urllib.request
import zipfile

import deckpilot as d
import updater


class IsolatedData(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, leaf in [('BASE','data'), ('CONFIG','data/config.json'), ('STATE','data/state.json'),
                           ('BACKUPS','data/backups'), ('LOG','data/app.log'), ('REPORTS','data/reports'), ('CLOUD','data/cloud.json')]:
            self.stack.enter_context(patch.object(d, name, self.root/leaf))


class ResearchTests(IsolatedData):
    def test_steam_search_uninstalled_and_identity_verified_on_selection(self):
        payload = {'items': [{'id': 892970, 'name': 'Valheim'}, {'id': 123, 'name': 'Valheim Soundtrack', 'type': 'dlc'}]}
        with patch.object(d, 'public_get', return_value=json.dumps(payload)) as fetch:
            result = d.search_steam('Valheim')
            self.assertEqual(result['games'], [{'appid':'892970','name':'Valheim','verified':False}])
            self.assertIn('storesearch', fetch.call_args.args[0])
        detail = {'892970': {'success': True, 'data': {'steam_appid': 892970, 'name':'Valheim', 'type':'game'}}}
        with patch.object(d, 'public_get', return_value=json.dumps(detail)):
            self.assertTrue(d.search_steam('892970')['games'][0]['verified'])
        detail['892970']['data']['steam_appid'] = 123
        with patch.object(d, 'public_get', return_value=json.dumps(detail)):
            with self.assertRaises(ValueError): d.steam_game('123')

    def test_similar_title_and_mixed_appids_never_match(self):
        wordpress = [{'link':'https://steamdeckhq.com/reviews/similar/', 'date':'2026-01-01',
                      'content':{'rendered':'<a href="https://store.steampowered.com/app/123/">Valheim</a> 60 FPS'}}]
        self.assertEqual(d.parse_source_reports(json.dumps(wordpress), 'SteamDeckHQ', '892970', 'https://steamdeckhq.com/'), [])
        page = '<a href="https://store.steampowered.com/app/123/">one</a><a href="https://store.steampowered.com/app/892970/">two</a> 60 FPS'
        self.assertEqual(d.parse_source_reports(page, 'ShareDeck', '892970', 'https://www.sharedeck.games/apps/892970'), [])

    def test_reports_provenance_metadata_unknown_and_host_validation(self):
        data = {'reports':[{'appid':892970,'summary':'Steam Deck OLED docked 1920x1080 40 FPS game version: 0.220',
                            'date':'2026-10-01','url':'https://deckverified.games/report/1'},
                           {'appid':892970,'summary':'Handheld 30 FPS','url':'https://evil.example/x'},
                           {'appid':123,'summary':'Valheim 100 FPS'}]}
        reports = d.parse_source_reports(json.dumps(data), 'Deck Settings', '892970','https://deckverified.games/')
        self.assertEqual(len(reports), 1)
        r = reports[0]
        self.assertEqual((r['device'],r['display_context'],r['resolution'],r['fps']), ('Steam Deck OLED','docked','1920x1080','40 FPS'))
        self.assertEqual(r['game_version'], '0.220')
        self.assertEqual(r['report_date'], '2026-10-01')
        self.assertIn('retrieved_at', r)
        unknown = d.report_record('ShareDeck','892970','https://www.sharedeck.games/apps/892970','No metadata')
        self.assertEqual(unknown['display_context'], 'unknown')
        self.assertIsNone(unknown['fps'])

    def test_json_ld_and_public_html_and_wordpress(self):
        content = '<a href="https://store.steampowered.com/app/892970/">Valheim</a> Steam Deck handheld 1280x800 30 FPS'
        for raw in [content, '<script type="application/ld+json">'+json.dumps({'appid':892970,'reviewBody':'Steam Deck handheld 30 FPS'})+'</script>',
                    json.dumps([{'link':'https://steamdeckhq.com/reviews/valheim/', 'content':{'rendered':content}}])]:
            with self.subTest(raw=raw[:40]):
                r = d.parse_source_reports(raw, 'Source', '892970', 'https://steamdeckhq.com/reviews/valheim/')
                self.assertEqual(len(r), 1)
                self.assertIn('Handheld-only', r[0]['uncertainty'])

    def test_independent_sources_rank_oled_docked_and_cache_failures(self):
        game = {'appid':'892970','name':'Valheim','verified':True}
        def read(url, deadline):
            if 'sharedeck' in url: raise TimeoutError('private error body')
            if 'deckverified' in url: return json.dumps({'appid':892970,'summary':'Steam Deck handheld 30 FPS'})
            return json.dumps({'appid':892970,'summary':'Steam Deck OLED docked 40 FPS'})
        with patch.object(d, 'steam_game', return_value=game), patch.object(d,'permitted_get', side_effect=read) as fetch:
            result = d.research_game('892970')
            self.assertEqual(len(result['sources']), 3)
            self.assertEqual(len(result['reports']), 2)
            self.assertEqual(result['reports'][0]['display_context'], 'docked')
            self.assertEqual(result['sources'][1]['status'], 'unavailable')
            self.assertNotIn('private error body',json.dumps(result))
            d.research_game('892970')
            self.assertEqual(fetch.call_count, 3)

    def test_no_source_lookup_without_verified_steam_identity(self):
        with patch.object(d,'steam_game',side_effect=ValueError()), patch.object(d,'source_research') as source:
            self.assertFalse(d.research_game('892970')['ok']); source.assert_not_called()

    def test_source_robots_deny_prevents_fetch(self):
        with patch.object(d, 'public_get', return_value='User-agent: *\nDisallow: /') as fetch:
            with self.assertRaisesRegex(ValueError,'does not permit'):
                d.permitted_get('https://www.sharedeck.games/apps/892970', d.time.monotonic()+8)
            self.assertEqual(fetch.call_count, 1)

    def test_missing_robots_allowed_but_failed_robots_fail_closed(self):
        missing = urllib.error.HTTPError('https://deckverified.games/robots.txt',404,'Not found',{},None)
        with patch.object(d,'public_get',side_effect=[missing,'content']):
            self.assertEqual(d.permitted_get('https://deckverified.games/',d.time.monotonic()+8),'content')
        with patch.object(d,'public_get',side_effect=TimeoutError()):
            with self.assertRaisesRegex(ValueError,'could not be verified'):
                d.permitted_get('https://www.sharedeck.games/',d.time.monotonic()+8)

    def test_bounded_cache_and_expiry(self):
        for n in range(70): d.research_cached(str(n),lambda: 'data')
        self.assertEqual(len(d.read_json(d.BASE/'research-cache.json',{})),64)
        with patch.object(d.time,'time',return_value=d.time.time()+d.RESEARCH_TTL+1):
            self.assertEqual(d.research_cached('69',lambda:'fresh'),'fresh')

    def test_public_client_bounds_deadline_and_redirects(self):
        response = Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.headers = {'Content-Length':str(d.RESEARCH_LIMIT+1)}
        with patch.object(d.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            with self.assertRaisesRegex(ValueError,'size limit'): d.public_get('https://deckverified.games/',d.time.monotonic()+3)
            response.headers={};response.read.side_effect=[b'x'*16384]*65
            with self.assertRaisesRegex(ValueError,'size limit'): d.public_get('https://deckverified.games/',d.time.monotonic()+3)
        with self.assertRaises(TimeoutError): d.public_get('https://deckverified.games/',0)
        for url in ['http://deckverified.games/','https://deckverified.games.evil.example/','https://deckverified.games:123/','https://user@deckverified.games/','file:///etc/passwd']:
            self.assertFalse(d.public_url(url))
        with self.assertRaises(ValueError):
            d.ResearchRedirects().redirect_request(urllib.request.Request('https://deckverified.games/'),None,302,'',{},'https://steamdeckhq.com/')

    def test_malicious_report_is_data_only(self):
        payload = {'appid':892970,'summary':'$(touch /tmp/evil); rm -rf ~; ResolutionSizeX=99999', 'commands':['sh','-c','evil']}
        with patch.object(d.subprocess,'run') as run:
            r=d.parse_source_reports(json.dumps(payload),'ShareDeck','892970','https://www.sharedeck.games/apps/892970')
            self.assertEqual(len(r),1);run.assert_not_called()
            self.assertNotIn('commands',r[0])
            self.assertEqual(d.PRESETS['graphics']['x'],1920)


class GameFixture(IsolatedData):
    def setUp(self):
        super().setUp()
        self.game={'appid':'1234','name':'Example UE','library':str(self.root/'steamapps')}
        self.path=d.proton_prefix(self.game['library'],'1234')/'Game/Saved/Config/Windows/GameUserSettings.ini'
        self.path.parent.mkdir(parents=True)
        self.raw='[/Script/Engine.GameUserSettings]\nResolutionSizeX=800\nResolutionSizeY=600\nOther=preserve\n'
        self.path.write_text(self.raw)
        self.stack.enter_context(patch.object(d,'installed_games',return_value=[self.game]))
        self.running=self.stack.enter_context(patch.object(d,'game_is_running',return_value=False))



class AdapterIntegrationTests(GameFixture):
    def test_uninstalled_preference_preserved_by_global_mode(self):
        d.save_mode('graphics','892970');d.save_mode('performance')
        self.assertEqual(d.config()['games']['892970'],'graphics')
        self.assertEqual(d.config()['default'],'performance')
        self.assertEqual(self.path.read_text(), self.raw)
        d.synchronize();self.assertEqual(self.path.read_text(),self.raw)

    def test_preview_approve_apply_restore_and_no_reapply(self):
        p=d.preview_profile('1234','graphics')
        self.assertEqual(self.path.read_text(),self.raw)
        self.assertTrue(any(c['after']=='1920' for c in p['files'][0]['changes']))
        self.assertTrue(d.approve_profile('1234','graphics',p['token'])['ok'])
        self.assertIn('1920',self.path.read_text())
        self.assertEqual(next((d.BACKUPS/'1234').glob('*.ini')).read_text(),self.raw)
        self.assertIn('Restored 1',d.restore_game('1234'))
        d.synchronize();self.assertEqual(self.path.read_text(),self.raw)
        self.assertNotIn('1234',d.config()['approved'])

    def test_stale_preview_running_game_and_manual_edits_are_preserved(self):
        p=d.preview_profile('1234','graphics')
        self.path.write_text(self.raw+'New=mine\n')
        self.assertFalse(d.approve_profile('1234','graphics',p['token'])['ok'])
        p=d.preview_profile('1234','graphics')
        self.running.return_value=True
        self.assertFalse(d.approve_profile('1234','graphics',p['token'])['ok'])
        self.running.return_value=False
        d.approve_profile('1234','graphics',p['token'])
        manual=self.path.read_text().replace('1920','1000');self.path.write_text(manual)
        p=d.preview_profile('1234','balanced')
        self.assertTrue(p['files'][0]['manual_changes'])
        self.assertFalse(d.approve_profile('1234','balanced',p['token'])['ok'])
        d.restore_game('1234');self.assertEqual(self.path.read_text(),manual)

    def test_symlink_utf16_and_unsupported_never_written(self):
        outside=self.root/'user.ini';outside.write_text(self.raw)
        self.path.unlink();self.path.symlink_to(outside)
        self.assertEqual(d.preview_profile('1234','graphics')['status'],'unsupported')
        self.assertEqual(outside.read_text(),self.raw)
        self.path.unlink();self.path.write_bytes(self.raw.encode('utf-16'))
        self.assertFalse(d.preview_profile('1234','graphics')['ok'])
        self.assertEqual(d.preview_profile('4567','graphics')['status'],'not-installed')

    def test_native_valheim_only_known_resolution_keys(self):
        path=self.root/'.config/unity3d/IronGate/Valheim/prefs';path.parent.mkdir(parents=True)
        raw='<unity_prefs><pref name="Screenmanager Resolution Width" type="int">800</pref><pref name="Screenmanager Resolution Height" type="int">600</pref><pref name="saves" type="string">KEEP</pref></unity_prefs>'
        path.write_text(raw)
        game={'appid':'892970','name':'Valheim','library':str(self.root/'steamapps')}
        with patch.object(d.Path,'home',return_value=self.root),patch.object(d,'installed_games',return_value=[game]):
            self.assertEqual(d.find_valheim_configs(game),[path])
            p=d.preview_profile('892970','graphics')
            self.assertTrue(d.approve_profile('892970','graphics',p['token'])['ok'])
            self.assertIn('1920',path.read_text());self.assertIn('KEEP',path.read_text())
            self.assertIn('Restored 1',d.restore_game('892970'));self.assertEqual(path.read_text(),raw)
        for bad in [raw.replace('type="int"','type="string"'), '<!DOCTYPE a>'+raw, '<prefs/>']:
            with self.assertRaises(ValueError): d.transform_valheim(bad,'graphics')

    def test_display_capability_is_not_enabled_status(self):
        root=self.root/'drm';connector=root/'card0-DP-1';connector.mkdir(parents=True)
        (connector/'status').write_text('connected');(connector/'modes').write_text('3840x2160\n2560x1440\n');(connector/'vrr_capable').write_text('1')
        result=d.display_diagnostics(root)
        self.assertEqual(result['vrr_capability'],'available');self.assertEqual(result['vrr_enabled'],'unknown')
        self.assertEqual(result['active_mode'],'unknown');self.assertEqual(len(result['external_outputs']),1)

    def test_drive_opt_in_single_destination_and_redacted_report(self):
        with patch.object(d.subprocess,'run') as run:
            self.assertIn('disabled',d.upload_cloud_report(force=True));run.assert_not_called()
        d.atomic_json(d.CLOUD,{'enabled':True})
        report={'errors':[], 'log_lines':[d.redact_diagnostic('token=SECRET /home/alex/game test@example.com')]}
        def upload(args,**kw):
            self.assertEqual(args[3],'deckpilot:DeckPilot Diagnostics/DeckPilot-Latest.zip')
            self.assertNotIn('link',args)
            with zipfile.ZipFile(args[2]) as z:
                text=z.read('DeckPilot-Diagnostics.json').decode()
                for value in ['SECRET','/home/alex','test@example.com']: self.assertNotIn(value,text)
            return types.SimpleNamespace(returncode=0)
        with patch.object(d,'drive_ready',return_value=(True,'')),patch.object(d,'rclone_binary',return_value='rclone'),patch.object(d.subprocess,'run',side_effect=upload) as run:
            for _ in range(2): self.assertIn('Uploaded',d.upload_cloud_report(force=True,report=report))
            self.assertEqual(run.call_count,2)

    def test_http_mode_preview_approval_and_mocked_steam(self):
        d.Handler.token='session'
        server=d.ThreadingHTTPServer(('127.0.0.1',0),d.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def post(path,body,token='session'):
            request=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,data=json.dumps(body).encode(),headers={'Host':'localhost:38647','Content-Type':'application/json','X-DeckPilot-Token':token})
            with urllib.request.urlopen(request,timeout=3) as r: return json.load(r)
        self.assertTrue(post('/api/mode',{'appid':'999','mode':'balanced'})['ok'])
        p=post('/api/preview',{'appid':'1234','mode':'graphics'})
        self.assertTrue(post('/api/apply',{'appid':'1234','mode':'graphics','token':p['token']})['ok'])
        with self.assertRaises(urllib.error.HTTPError) as error: post('/api/mode',{'mode':'graphics'},token='wrong')
        self.assertEqual(error.exception.code,403)
        with patch.object(d,'public_get',return_value=json.dumps({'items':[{'id':892970,'name':'Valheim'}]})):
            self.assertEqual(post('/api/search',{'query':'Valheim'})['games'][0]['appid'],'892970')


class BridgeTests(unittest.TestCase):
    def load_bridge(self):
        fake=types.SimpleNamespace(DECKY_USER_HOME='/home/deck',logger=Mock())
        spec=importlib.util.spec_from_file_location('deckpilot_bridge',Path(__file__).resolve().parents[1]/'decky/main.py')
        bridge=importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules',{'decky':fake}): spec.loader.exec_module(bridge)
        return bridge

    def test_root_bridge_sets_deck_uid_gid_groups_home_and_session(self):
        b=self.load_bridge();account=types.SimpleNamespace(pw_dir='/home/deck',pw_uid=1000,pw_gid=1000)
        with patch.object(b.pwd,'getpwnam',return_value=account),patch.object(b.os,'geteuid',return_value=0),patch.object(b.os,'getgrouplist',return_value=[1000,1001]):
            home,env,identity=b.deck_command_environment()
        self.assertEqual(identity,{'user':1000,'group':1000,'extra_groups':[1000,1001]})
        self.assertEqual(env['HOME'],'/home/deck');self.assertEqual(env['XDG_RUNTIME_DIR'],'/run/user/1000')
        self.assertNotIn('DECKPILOT_DATA',env)
        self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'],'unix:path=/run/user/1000/bus')

    def test_bridge_launch_uses_identity_and_passes_query_as_single_argument(self):
        b=self.load_bridge();proc=Mock(returncode=0);proc.communicate=AsyncMock(return_value=(b'{"ok":true,"games":[]}',b''))
        with patch.object(b,'deck_command_environment',return_value=(Path('/home/deck'),{'HOME':'/home/deck'},{'user':1000,'group':1000,'extra_groups':[1000]})),patch.object(b.Path,'is_file',return_value=True),patch.object(b.asyncio,'create_subprocess_exec',new_callable=AsyncMock,return_value=proc) as launch:
            result=asyncio.run(b.Plugin().search_games('$(touch /tmp/never)'))
        self.assertTrue(result['ok']);self.assertEqual(launch.call_args.kwargs['user'],1000)
        self.assertEqual(launch.call_args.args[-1],'$(touch /tmp/never)')

    def test_bridge_fails_closed_without_deck_account(self):
        b=self.load_bridge()
        with patch.object(b.pwd,'getpwnam',side_effect=KeyError('deck')),patch.object(b.asyncio,'create_subprocess_exec',new_callable=AsyncMock) as launch:
            self.assertFalse(asyncio.run(b.Plugin().get_state())['ok']);launch.assert_not_called()


class UpdateErrors(unittest.TestCase):
    def test_specific_http_and_network_errors_without_response_secrets(self):
        for code,expected in [(404,'No public release'),(403,'denied'),(429,'rate limit')]:
            error=urllib.error.HTTPError('https://api.github.com/',code,'SECRET',{},None)
            with patch.object(updater,'_limited_get',side_effect=error),patch.object(updater,'record_remote',side_effect=lambda st,msg,**kw:{'status':st,'message':msg}):
                result=updater.fetch_github_update('goddenator/DeckPilot-TV','0.8.0')
            self.assertIn(expected,result['message']);self.assertNotIn('SECRET',str(result))

class PublicSchemaContracts(IsolatedData):
    def test_deckverified_documented_game_details_schema_and_no_external_blending(self):
        payload={'appId':892970,'reports':[{'number':42,'html_url':'https://github.com/DeckSettings/game-reports-steamos/issues/42','created_at':'2026-01-01','data':{'app_id':892970,'summary':'OLED docked report','device':'Valve Steam Deck OLED','target_framerate':'40 FPS','game_resolution':'1920x1080'}}], 'external_reviews':[{'data':{'app_id':892970,'summary':'Another publisher'}}]}
        r=d.parse_source_reports(json.dumps(payload),'Deck Settings / deckverified.games','892970','https://deckverified.games/deck-verified/api/v1/game_details?appid=892970')
        self.assertEqual(len(r),1);self.assertIn('/issues/42',r[0]['url']);self.assertEqual(r[0]['fps_kind'],'target, not measured FPS')
        payload['reports'][0]['data']['app_id']=123
        self.assertEqual(d.parse_source_reports(json.dumps(payload),'Deck Settings / deckverified.games','892970','https://deckverified.games/'),[])

    def test_sharedeck_documented_experimental_report_schema(self):
        payload=[{'id':17,'app_id':892970,'app_build_id':'202600','resolution_horizontal':1280,'resolution_vertical':800,'average_framerate':35,'framerate_limit':40,'note':'Handheld test','created_at':'2026-10-01'}, {'id':18,'app_id':123,'average_framerate':90}]
        r=d.parse_source_reports(json.dumps(payload),'ShareDeck','892970','https://sharedeck.games/api/experimental/reports?app_id=892970')
        self.assertEqual(len(r),1);self.assertEqual(r[0]['resolution'],'1280x800');self.assertEqual(r[0]['fps'],'35 FPS')
        self.assertEqual(r[0]['device'],'unknown');self.assertEqual(r[0]['game_version'],'202600')
        self.assertEqual(r[0]['report_id'],'17');self.assertIn('Handheld-only',r[0]['uncertainty'])

    def test_steamdeckhq_documented_wordpress_review_and_target_not_benchmark(self):
        payload=[{'id':42,'date':'2026-01-01','link':'https://steamdeckhq.com/game-reviews/valheim/','content':{'rendered':'<a href="https://store.steampowered.com/app/892970/">Valheim</a> Handheld review'},'acf':{'optimized_and_recommended_settings':{'steamos_settings':{'fps_cap':'40 FPS'},'game_settings':'1280x800'}}}]
        r=d.parse_source_reports(json.dumps(payload),'SteamDeckHQ','892970','https://steamdeckhq.com/wp-json/wp/v2/game-reviews/')
        self.assertEqual(len(r),1);self.assertEqual(r[0]['fps'],'40 FPS');self.assertIn('not measured',r[0]['fps_kind']);self.assertEqual(r[0]['device'],'unknown')
        payload[0]['acf']['steam_app_id']=123
        self.assertEqual(d.parse_source_reports(json.dumps(payload),'SteamDeckHQ','892970','https://steamdeckhq.com/'),[])

    def test_malformed_steam_payload_and_report_conflicting_ids(self):
        for payload in [[],{'items':None}]:
            with patch.object(d,'public_get',return_value=json.dumps(payload)):
                self.assertFalse(d.search_steam('Test')['ok'])
        raw=json.dumps({'appid':123,'content':'<a href="https://store.steampowered.com/app/892970/">Other game</a> 60 FPS'})
        self.assertEqual(d.parse_source_reports(raw,'Source','892970','https://deckverified.games/'),[])

    def test_source_deadline_does_not_hide_other_results(self):
        release=threading.Event()
        def source(name,url,appid):
            if name=='ShareDeck':release.wait(1)
            return {'source':name,'url':url,'status':'ok','reports':[]}
        original=d.wait
        try:
            with patch.object(d,'steam_game',return_value={'appid':'892970','name':'Valheim'}),patch.object(d,'source_research',side_effect=source),patch.object(d,'wait',side_effect=lambda futures,timeout:original(futures,timeout=.02)):
                result=d.research_game('892970')
            self.assertEqual(result['sources'][1]['status'],'timeout');self.assertEqual(result['sources'][0]['status'],'ok')
        finally:release.set()


class AdditionalSafetyTests(GameFixture):
    def test_reapply_after_restore_uses_new_user_baseline(self):
        p=d.preview_profile('1234','graphics');d.approve_profile('1234','graphics',p['token']);d.restore_game('1234')
        new=self.raw.replace('800','1000');self.path.write_text(new)
        p=d.preview_profile('1234','graphics');d.approve_profile('1234','graphics',p['token']);d.restore_game('1234')
        self.assertEqual(self.path.read_text(),new)
        self.assertEqual(len(list((d.BACKUPS/'1234').glob('*.ini'))),2)

    def test_duplicate_ue_key_rejected_and_backup_failure_never_writes(self):
        duplicate=self.raw+'ResolutionSizeX=999\n';self.path.write_text(duplicate)
        self.assertFalse(d.preview_profile('1234','graphics')['ok']);self.assertEqual(self.path.read_text(),duplicate)
        self.path.write_text(self.raw)
        with patch.object(d.shutil,'copy2',side_effect=OSError('Disk full')):
            self.assertEqual(d.apply_profile(self.game,'graphics')['status'],'error')
        self.assertEqual(self.path.read_text(),self.raw)


class BackupRecoveryTests(GameFixture):
    def test_missing_original_backup_blocks_followup_edit(self):
        self.assertEqual(d.apply_profile(self.game,'graphics')['status'],'applied')
        before=self.path.read_text()
        next((d.BACKUPS/'1234').glob('*.ini')).unlink()
        self.assertEqual(d.apply_profile(self.game,'balanced')['status'],'error')
        self.assertEqual(self.path.read_text(),before)


class SyncApprovalTests(GameFixture):
    def test_new_files_need_a_fresh_preview(self):
        p=d.preview_profile('1234','graphics')
        self.assertTrue(d.approve_profile('1234','graphics',p['token'])['ok'])
        extra=self.path.parent.parent/'WindowsNoEditor/GameUserSettings.ini'
        extra.parent.mkdir();extra.write_text(self.raw)
        d.synchronize()
        self.assertEqual(extra.read_text(),self.raw)
        p=d.preview_profile('1234','graphics')
        self.assertTrue(d.approve_profile('1234','graphics',p['token'])['ok'])
        self.assertIn('1920',extra.read_text())


if __name__ == '__main__': unittest.main()


