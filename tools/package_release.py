#!/usr/bin/env python3
"""Assemble local artifacts only. Never tag, upload, or publish a release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# Keep the v0.6 updater's allowlist compatible: research runtime is in deckpilot.py.
APP_FILES = ['deckpilot.py', 'updater.py', 'README.md', 'VERSION.txt', 'install.sh',
             'uninstall.sh', 'check.sh', 'setup_drive.sh', 'test_deckpilot.py', 'test_updater.py']


def package(output, version=None):
    src = ROOT/'app'
    source_version = re.search(r"^VERSION = '(\d+\.\d+\.\d+)'", (src/'deckpilot.py').read_text(), re.M).group(1)
    version = version or source_version
    if version != source_version or version not in (src/'VERSION.txt').read_text():
        raise ValueError('Tag, source and VERSION.txt must agree.')
    if json.loads((ROOT/'decky/package.json').read_text())['version'] != version:
        raise ValueError('Decky and app versions must agree.')
    if not (ROOT/'decky/dist/index.js').is_file(): raise ValueError('Build the Decky frontend first.')
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    folder = 'deckpilot_tv_v'+version.replace('.','_')
    manifest = {'product':'deckpilot-tv','version':version,'files':{}}
    appzip = output/('DeckPilot_TV_v'+version+'.zip')
    with zipfile.ZipFile(appzip,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in APP_FILES:
            data = (src/name).read_bytes()
            manifest['files'][name] = hashlib.sha256(data).hexdigest()
            archive.writestr(folder+'/'+name,data)
        archive.writestr(folder+'/deckpilot-release.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(output/('DeckPilot_Decky_v'+version+'.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for name in ['plugin.json','package.json','main.py','LICENSE','README.md','dist/index.js']:
            archive.write(ROOT/'decky'/name,'DeckPilot/'+name)
    return appzip


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT/'out'))
    parser.add_argument('--version')
    args = parser.parse_args()
    print(package(args.output, args.version))
