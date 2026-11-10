#!/usr/bin/env python3
"""Assemble local artifacts only. Never tag, upload, or publish a release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Keep the v0.6 updater's allowlist compatible: research runtime is in deckpilot.py.
APP_FILES = ['deckpilot.py', 'updater.py', 'README.md', 'VERSION.txt', 'install.sh',
             'uninstall.sh', 'check.sh', 'setup_drive.sh', 'test_deckpilot.py', 'test_updater.py']


def package(output, version=None):
    src = ROOT/'app'
    source_version = re.search(r"^VERSION = '(\d+\.\d+\.\d+)'", (src/'deckpilot.py').read_text(), re.M).group(1)
    build = re.search(r"^BUILD_ID = '([^']+)'", (src/'deckpilot.py').read_text(), re.M)
    build = build.group(1) if build else source_version
    version = version or build
    if version != build or version.split('-')[0]!=source_version or version not in (src/'VERSION.txt').read_text():
        raise ValueError('Tag, source and VERSION.txt must agree.')
    if json.loads((ROOT/'decky/package.json').read_text())['version'] != version:
        raise ValueError('Decky and app versions must agree.')
    if not (ROOT/'decky/dist/index.js').is_file(): raise ValueError('Build the Decky frontend first.')
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    folder = 'deckpilot_tv_v'+source_version.replace('.','_')
    manifest = {'product':'deckpilot-tv','version':version,'files':{}}
    appzip = output/('DeckPilot_TV_v'+version+'.zip')
    with zipfile.ZipFile(appzip,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in APP_FILES:
            data = (src/name).read_bytes()
            manifest['files'][name] = hashlib.sha256(data).hexdigest()
            archive.writestr(folder+'/'+name,data)
        archive.writestr(folder+'/deckpilot-release.json',json.dumps(manifest,indent=2)+'\n')
    pluginzip=output/('DeckPilot_Decky_v'+version+'.zip')
    with zipfile.ZipFile(pluginzip,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in ['plugin.json','package.json','main.py','LICENSE','README.md','dist/index.js']:
            archive.write(ROOT/'decky'/name,'DeckPilot/'+name)
        archive.write(src/'updater.py','DeckPilot/update_client.py')
    channel='preview' if '-preview.' in version else 'stable'
    suite={'format':1,'product':'deckpilot-tv-suite','repository':'goddenator/DeckPilot-TV','version':version,'tag':'v'+version,'channel':channel,
           'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    for key,path in [('app',appzip),('plugin',pluginzip)]:
        suite[key]={'name':path.name,'version':version,'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'ui_schema':2,'update_protocol':1}
    suitepath=output/'DeckPilot-Update.json';suitepath.write_text(json.dumps(suite,indent=2)+'\n')
    (output/'SHA256SUMS').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n' for path in [appzip,pluginzip,suitepath]))
    return appzip


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT/'out'))
    parser.add_argument('--version')
    args = parser.parse_args()
    print(package(args.output, args.version))
