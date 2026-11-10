#!/usr/bin/env python3
"""Optional browser integration smoke test. Requires Python Playwright and Chromium.

Uses an ephemeral port and private temporary data, never an installed service.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
import deckpilot as d


class TestHandler(d.Handler):
    token = 'isolated-browser-test'
    def valid_host(self):
        return self.headers.get('Host') == '127.0.0.1:'+str(self.server.server_port)

    def do_POST(self):
        # Production intentionally accepts only its fixed loopback origin. Adapt
        # this test's ephemeral origin, without loosening production validation.
        if self.headers.get('Origin') == 'http://127.0.0.1:'+str(self.server.server_port):
            self.headers.replace_header('Origin', 'http://127.0.0.1:38647')
        super().do_POST()


def smoke():
    with tempfile.TemporaryDirectory() as temp:
        data=Path(temp)
        with patch.multiple(d, BASE=data,CONFIG=data/'config.json',STATE=data/'state.json',
                            BACKUPS=data/'backups',LOG=data/'app.log',CLOUD=data/'cloud.json'), \
             patch.object(d,'installed_games',return_value=[]):
            server=d.ThreadingHTTPServer(('127.0.0.1',0),TestHandler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
                    try:
                        page=browser.new_page();errors=[]
                        page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto('http://127.0.0.1:'+str(server.server_port))
                        page.get_by_role('heading',name='Default optimisation').wait_for()
                        page.get_by_role('button',name='Balanced',exact=True).click()
                        page.wait_for_function("document.getElementById('feedback').textContent.includes('Preference saved')")
                        page.route('**/api/search',lambda r:r.fulfill(json={'ok':True,'games':[{'appid':'892970','name':'Valheim'}]}))
                        page.get_by_role('textbox',name='Steam game name or App ID').fill('Valheim')
                        page.get_by_role('button',name='Search Steam',exact=True).click()
                        page.locator('#steam-results').get_by_text('Valheim · 892970').wait_for()
                        page.locator('#steam-results').get_by_role('button',name='Best Graphics',exact=True).click()
                        page.wait_for_function("document.getElementById('feedback').textContent.includes('Preference can be saved')")
                        assert json.loads((data/'config.json').read_text())['games']['892970']=='graphics'
                        page.route('**/api/research',lambda r:r.fulfill(json={'ok':True,'sources':[{'source':'ShareDeck','status':'unavailable'}],'reports':[{'source':'Test source','url':'https://sharedeck.games/apps/892970','device':'unknown','display_context':'handheld','summary':'<img src=x onerror=alert(1)> $(touch /tmp/never)','uncertainty':'Handheld-only; TV unknown'}]}))
                        page.get_by_role('button',name='Research',exact=True).click()
                        page.locator('#research-results').get_by_text('ShareDeck: unavailable').wait_for()
                        assert page.locator('#research-results img').count()==0
                        update_calls=[]
                        local_link='http://127.0.0.1:45678/'+'a'*43+'/DeckPilot.zip'
                        def update_route(route):
                            if route.request.method=='GET':
                                route.fulfill(json={'available':True,'version':'0.8.3-preview.1','can_undo':True,'status':'Verified preview','suite':{'token':'captured-approval','version':'0.8.3-preview.1','channel':'preview','plugin_rollback':True,'app_installed':'0.8.2'}})
                            else:
                                body=route.request.post_data_json;update_calls.append(body)
                                route.fulfill(json={'url':local_link} if body['action']=='plugin-rollback' else {'message':'App update started.'})
                        page.route('**/api/update',update_route)
                        page.evaluate('checkUpdate()')
                        page.get_by_role('button',name='Install App 0.8.3-preview.1',exact=True).wait_for()
                        page.once('dialog',lambda dialog:dialog.dismiss())
                        page.get_by_role('button',name='Install App 0.8.3-preview.1',exact=True).click()
                        assert not update_calls
                        page.once('dialog',lambda dialog:dialog.accept())
                        page.get_by_role('button',name='Install App 0.8.3-preview.1',exact=True).click()
                        page.wait_for_function("document.getElementById('update-status').textContent==='App update started.'")
                        assert update_calls[0]=={'action':'install','token':'captured-approval','allow_downgrade':False}
                        page.once('dialog',lambda dialog:dialog.accept())
                        page.get_by_role('button',name='Prepare Plugin Rollback',exact=True).click()
                        page.get_by_role('textbox',name='Plugin rollback link').wait_for()
                        assert page.get_by_role('textbox',name='Plugin rollback link').input_value()==local_link
                        assert not errors,errors
                    finally:browser.close()
            finally:
                server.shutdown();server.server_close()
    print('Browser smoke passed: isolated dashboard, preferences, search, source failures, escaped hostile text, captured update approval and plugin rollback link; no JavaScript errors.')


if __name__=='__main__':smoke()
