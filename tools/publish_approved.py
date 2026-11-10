#!/usr/bin/env python3
"""Workflow-only publisher. Requires a protected-environment owner approval first."""
import argparse
import shlex
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPO='goddenator/DeckPilot-TV'

def validate(folder,sha,channel):
    manifest=json.loads((folder/'DeckPilot-Update.json').read_text())
    version=manifest['version']
    pattern=r'\d+\.\d+\.\d+'+(r'-preview\.[1-9]\d*' if channel=='preview' else '')
    if channel not in ('stable','preview') or not re.fullmatch(pattern,version):raise ValueError('Channel/version mismatch')
    if not re.fullmatch('[a-f0-9]{40}',sha) or manifest['commit']!=sha or manifest['repository']!=REPO or manifest['channel']!=channel or manifest['tag']!='v'+version:raise ValueError('Reviewed commit/source mismatch')
    names=['DeckPilot_TV_v'+version+'.zip','DeckPilot_Decky_v'+version+'.zip','DeckPilot-Update.json']
    expected={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in names}
    if (folder/'SHA256SUMS').read_text()!=''.join(expected[name]+'  '+name+'\n' for name in names):raise ValueError('Checksum mismatch')
    for key,name in zip(('app','plugin'),names):
        item=manifest[key]
        if item['name']!=name or item['sha256']!=expected[name] or item['size']!=(folder/name).stat().st_size or item['version']!=version:raise ValueError('Component mismatch')
    expected['SHA256SUMS']=hashlib.sha256((folder/'SHA256SUMS').read_bytes()).hexdigest()
    return manifest,expected

def main(preflight=False):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise ValueError('Run only through the owner-approved publication workflow')
    sha=os.environ['APPROVED_SHA'];channel=os.environ['APPROVED_CHANNEL'];folder=Path('out')
    manifest,expected=validate(folder,sha,channel);tag=manifest['tag']
    if subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=sha:raise ValueError('Checkout changed')
    # Never replace an existing tag/release, including a failed unpublished draft.
    if subprocess.check_output(['git','ls-remote','--tags','origin','refs/tags/'+tag],text=True).strip():raise ValueError('Tag already exists; use a new version')
    gh=['gh','--repo',REPO]
    result=subprocess.run(['gh','api','repos/'+REPO+'/releases/tags/'+tag],capture_output=True,text=True)
    if result.returncode==0:raise ValueError('Release already exists; do not overwrite')
    if result.returncode!=1 or '(HTTP 404)' not in result.stderr:raise ValueError('Cannot verify release absence; check GitHub API permissions/access before retrying')
    args=gh+['release','create',tag,'--target',sha,'--draft','--title','DeckPilot '+manifest['version'],'--notes','Owner-approved paired app and Decky build. See repository update instructions.']
    if channel=='preview':args.append('--prerelease')
    args += [str(folder/name) for name in expected]
    if preflight:
        # These commands only display local CLI help; the real plan is printed, never run.
        for command in ('create','edit'):
            subprocess.run(gh+['release',command,'--help'],check=True,stdout=subprocess.DEVNULL)
        print('NON-PUBLISHING PREFLIGHT PASSED: exact checkout, paired assets/checksums, unused tag/release and CLI syntax verified.')
        print('After a separate publication approval: '+shlex.join(args))
        print('Final step after uploaded digest checks: '+shlex.join(gh+['release','edit',tag,'--draft=false']))
        return
    subprocess.run(args,check=True)
    release=json.loads(subprocess.check_output(['gh','api','repos/'+REPO+'/releases/tags/'+tag],text=True))
    assets={a['name']:a for a in release['assets']}
    if set(assets)!=set(expected) or any(assets[n].get('digest')!='sha256:'+digest for n,digest in expected.items()):raise ValueError('Uploaded asset verification failed; draft left unpublished')
    subprocess.run(gh+['release','edit',tag,'--draft=false'],check=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight',action='store_true',help='Read-only checks; never create a draft, tag or release')
    args=parser.parse_args()
    try:main(preflight=args.preflight)
    except (ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:sys.exit(str(exc))
