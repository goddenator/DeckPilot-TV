import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import deckpilot as d

class TestDeckPilot(unittest.TestCase):
    def setUp(self):
        # Never read/write an installed user's preferences while exercising profiles.
        self.data = tempfile.TemporaryDirectory()
        self.addCleanup(self.data.cleanup)
        root = Path(self.data.name)
        binding = patch.multiple(d, BASE=root, CONFIG=root/'config.json',
                                 STATE=root/'state.json', BACKUPS=root/'backups', LOG=root/'app.log')
        binding.start(); self.addCleanup(binding.stop)

    def test_external_vrr_probe(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            external = root/'card0-DP-1'
            external.mkdir()
            (external/'status').write_text('connected\n')
            self.assertEqual(d.external_vrr_capability(root), 'unknown')
            (external/'vrr_capable').write_text('1\n')
            self.assertEqual(d.external_vrr_capability(root), 'available')
            (external/'vrr_capable').write_text('0\n')
            self.assertEqual(d.external_vrr_capability(root), 'not-advertised')
            (external/'status').write_text('disconnected\n')
            self.assertEqual(d.external_vrr_capability(root), 'unknown')

    def test_ini_preserves_other_values(self):
        data = ('[/Script/Engine.GameUserSettings]\nResolutionSizeX=800\n'
                'ResolutionSizeY=600\nRandomSetting=DO_NOT_CHANGE\n\n'
                '[ScalabilityGroups]\nsg.ShadowQuality=2\nOther=Preserve\n')
        new = d.transform_ue_ini(data, 'graphics')
        self.assertIn('ResolutionSizeX=1920', new)
        self.assertIn('ResolutionSizeY=1080', new)
        self.assertIn('sg.ShadowQuality=3', new)
        self.assertIn('RandomSetting=DO_NOT_CHANGE', new)
        self.assertIn('Other=Preserve', new)
        self.assertEqual(new, d.transform_ue_ini(new, 'graphics'))
    def test_ini_blank(self):
        new = d.transform_ue_ini('', 'balanced')
        self.assertIn('ResolutionSizeX=1600', new)
        self.assertIn('sg.ViewDistanceQuality=2', new)
    def test_vdf_detection(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            app = home/'.local/share/Steam/steamapps'
            app.mkdir(parents=True)
            (app/'appmanifest_1234.acf').write_text('"AppState"\n{\n"appid" "1234"\n"name" "A Game"\n}', encoding='utf-8')
            found = d.installed_games(home)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]['name'], 'A Game')
    def test_backup_restore(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            g = {'appid':'1234', 'name':'A Game', 'library': str(base/'steamapps')}
            path = d.proton_prefix(g['library'], g['appid'])/'MyGame/Saved/Config/WindowsNoEditor/GameUserSettings.ini'
            path.parent.mkdir(parents=True)
            text = '[/Script/Engine.GameUserSettings]\nResolutionSizeX=800\nResolutionSizeY=600\n'
            path.write_text(text)
            with patch.object(d,'BASE',base/'data'),patch.object(d,'CONFIG',base/'data/config.json'),patch.object(d,'STATE',base/'data/state.json'),patch.object(d,'BACKUPS',base/'data/backups'),patch.object(d,'LOG',base/'data/deckpilot.log'),patch.object(d,'game_is_running',return_value=False):
                outcome = d.apply_profile(g,'graphics')
                self.assertEqual(outcome['status'],'applied')
                self.assertIn('1920',path.read_text())
                restore = d.restore_game('1234')
                self.assertIn('Restored 1', restore)
                self.assertEqual(text,path.read_text())

    def test_manual_change_is_not_overwritten_automatically(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            g = {'appid':'568', 'name':'Test Game', 'library': str(base/'steamapps')}
            path = d.proton_prefix(g['library'], g['appid'])/'MyGame/Saved/Config/Windows/GameUserSettings.ini'
            path.parent.mkdir(parents=True)
            path.write_text('[ScalabilityGroups]\nsg.ShadowQuality=1\n')
            with patch.object(d,'BASE',base/'data'),patch.object(d,'CONFIG',base/'data/config.json'),patch.object(d,'STATE',base/'data/state.json'),patch.object(d,'BACKUPS',base/'data/backups'),patch.object(d,'LOG',base/'data/deckpilot.log'),patch.object(d,'game_is_running',return_value=False):
                d.apply_profile(g,'graphics')
                path.write_text(path.read_text().replace('sg.ShadowQuality=3','sg.ShadowQuality=0'))
                result = d.apply_profile(g,'balanced')
                self.assertEqual(result['status'], 'manual-changes')
                self.assertIn('sg.ShadowQuality=0',path.read_text())
                d.apply_profile(g,'balanced',force=True)
                self.assertIn('sg.ShadowQuality=2',path.read_text())
                restored = d.restore_game('568')
                self.assertIn('Restored 1', restored)
                self.assertIn('sg.ShadowQuality=0',path.read_text())

if __name__ == '__main__':
    unittest.main()

class TestMetrics(unittest.TestCase):
    def test_reads_realistic_mangoapp_csv_header(self):
        import deckpilot as d
        with tempfile.TemporaryDirectory() as t:
            csvfile = Path(t) / 'Game_2026-11.csv'
            rows = ['os,cpu,gpu,ram,kernel,driver,cpuscheduler',
                    'SteamOS,AMD,,,6.16,,powersave',
                    'fps,frametime,cpu_load,gpu_load,elapsed']
            for i in range(300):
                rows.append('40,25,60,90,' + str(i * 100_000_000))
            csvfile.write_text('\n'.join(rows))
            r = d.summarize_mangohud_csv(csvfile)
            self.assertEqual(r['avg_fps'], 40.0)
            self.assertEqual(r['low_1pct_fps'], 40.0)
            self.assertEqual(r['samples'], 300)
            self.assertAlmostEqual(r['duration_s'], 29.9)

    def test_does_not_attribute_generic_mangoapp_log_to_a_game(self):
        import deckpilot as d
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)/'mangologs'
            root.mkdir()
            for name in ['mangoapp_2026-11-09_12-20-10.csv', 'VeryCoolGame_2026-11-09.csv']:
                (root/name).write_text('fps,frametime\n40,25\n' * 80)
            g = {'appid': '123456', 'name': 'Very Cool Game'}
            hits = d.game_log_candidates(g, home=t)
            self.assertEqual(len(hits), 1)
            self.assertIn('VeryCoolGame', hits[0].name)

    def test_malformed_config_is_safe(self):
        import deckpilot as d
        with tempfile.TemporaryDirectory() as t:
            cfgfile = Path(t)/'config.json'
            cfgfile.write_text('[]')
            with patch.object(d, 'CONFIG', cfgfile):
                c = d.config()
                self.assertFalse(c['enabled'])


class TestDiagnostics(unittest.TestCase):
    def test_report_redacts_private_information(self):
        import deckpilot as d
        raw = 'ERROR /home/alex/Games/Crash token=abcdef98765 mail test@example.com ip 192.168.1.8 sk-testkey12345678'
        safe = d.redact_diagnostic(raw)
        for secret in ('/home/alex', 'abcdef98765', 'test@example.com', '192.168.1.8', 'sk-testkey12345678'):
            self.assertNotIn(secret, safe)

    def test_diagnostic_archive_has_only_report_and_notice(self):
        import deckpilot as d
        import io, json, zipfile
        fake = {'version': '0.3.0', 'log_lines': ['ERROR redacted']}
        data = d.make_diagnostic_zip(fake)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertEqual(sorted(z.namelist()), ['DeckPilot-Diagnostics.json', 'PLEASE_READ.txt'])
            report = json.loads(z.read('DeckPilot-Diagnostics.json'))
            self.assertEqual(report['version'], '0.3.0')
