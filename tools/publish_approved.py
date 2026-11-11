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
    if not isinstance(manifest,dict) or manifest.get('format')!=1 or manifest.get('product')!='deckpilot-tv-suite':raise ValueError('Invalid suite manifest')
    version=manifest['version']
    pattern=r'\d+\.\d+\.\d+'+(r'-preview\.[1-9]\d*' if channel=='preview' else '')
    if channel not in ('stable','preview') or not re.fullmatch(pattern,version):raise ValueError('Channel/version mismatch')
    if not re.fullmatch('[a-f0-9]{40}',sha) or manifest['commit']!=sha or manifest['repository']!=REPO or manifest['channel']!=channel or manifest['tag']!='v'+version:raise ValueError('Reviewed commit/source mismatch')
    names=['DeckPilot_TV_v'+version+'.zip','DeckPilot_Decky_v'+version+'.zip','DeckPilot-Update.json']
    expected={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in names}
    if (folder/'SHA256SUMS').read_text()!=''.join(expected[name]+'  '+name+'\n' for name in names):raise ValueError('Checksum mismatch')
    for key,name in zip(('app','plugin'),names):
        item=manifest[key]
        if item['name']!=name or item['sha256']!=expected[name] or item['size']!=(folder/name).stat().st_size or item['version']!=version or item.get('ui_schema')!=2 or item.get('update_protocol')!=1:raise ValueError('Component mismatch')
    expected['SHA256SUMS']=hashlib.sha256((folder/'SHA256SUMS').read_bytes()).hexdigest()
    return manifest,expected

def api(path, fields=None):
    cmd=['gh','api','repos/'+REPO+'/'+path]
    if fields is not None:
        cmd += ['--method','PATCH']
        for key,value in fields.items():cmd += ['--field',key+'='+str(value).lower()]
    result=subprocess.run(cmd,capture_output=True,text=True)
    if result.returncode:raise ValueError('GitHub release API failed; no automatic retry. Check permissions/access and inspect release state before recovery.')
    return json.loads(result.stdout)


def releases_for_tag(tag):
    # The public releases/tags endpoint cannot reliably find unpublished drafts.
    result=subprocess.run(['gh','api','--paginate','--slurp','repos/'+REPO+'/releases?per_page=100'],capture_output=True,text=True)
    if result.returncode:raise ValueError('Cannot list releases, including drafts; check GitHub API permissions/access before retrying')
    pages=json.loads(result.stdout)
    if not isinstance(pages,list) or any(not isinstance(page,list) for page in pages):raise ValueError('Invalid paginated release list')
    releases=[release for page in pages for release in page]
    if any(not isinstance(release,dict) for release in releases):raise ValueError('Invalid release metadata')
    matches=[release for release in releases if release.get('tag_name')==tag]
    if len(matches)>1:raise ValueError('Multiple releases use this tag; do not guess which draft to recover')
    return matches


def release_id(release):
    if not isinstance(release,dict):raise ValueError('Invalid release metadata')
    ident=release.get('id')
    if type(ident) is not int or ident<=0:raise ValueError('Invalid release ID')
    return ident


def check_tag(tag,sha,recovery=False):
    refs=subprocess.check_output(['git','ls-remote','--tags','origin','refs/tags/'+tag,'refs/tags/'+tag+'^{}'],text=True).splitlines()
    if not refs:return
    if not recovery:raise ValueError('Tag already exists; use a new version')
    found={}
    for line in refs:
        parts=line.split()
        if len(parts)!=2 or not re.fullmatch('[a-f0-9]{40}',parts[0]) or parts[1] not in ('refs/tags/'+tag,'refs/tags/'+tag+'^{}') or parts[1] in found:raise ValueError('Invalid existing tag metadata')
        found[parts[1]]=parts[0]
    if found.get('refs/tags/'+tag+'^{}',found.get('refs/tags/'+tag))!=sha:raise ValueError('Existing tag does not point to the approved commit')


def verify_draft(release,ident,manifest,expected,folder):
    if (release_id(release)!=ident or release.get('url')!='https://api.github.com/repos/'+REPO+'/releases/'+str(ident)
            or release.get('tag_name')!=manifest['tag'] or release.get('target_commitish')!=manifest['commit']
            or release.get('draft') is not True or release.get('prerelease') is not (manifest['channel']=='preview')):
        raise ValueError('Draft identity, repository, tag, approved commit or channel mismatch; draft left unpublished')
    assets=release.get('assets')
    if not isinstance(assets,list) or len(assets)!=len(expected) or any(not isinstance(a,dict) or not isinstance(a.get('name'),str) for a in assets):raise ValueError('Draft must contain exactly four assets; draft left unpublished')
    by_name={a.get('name'):a for a in assets}
    if len(by_name)!=len(assets) or set(by_name)!=set(expected):raise ValueError('Duplicate, missing or unexpected asset; draft left unpublished')
    for name,digest in expected.items():
        asset=by_name[name]
        if asset.get('state')!='uploaded' or asset.get('digest')!='sha256:'+digest or type(asset.get('size')) is not int or asset['size']!=(folder/name).stat().st_size:
            raise ValueError('Uploaded asset SHA256/size/state verification failed; draft left unpublished')


def exact_draft(tag,ident,manifest,expected,folder):
    matches=releases_for_tag(tag)
    if len(matches)!=1 or release_id(matches[0])!=ident:raise ValueError('Recovery/creation ID is not the unique exact tag match; draft left unpublished')
    verify_draft(matches[0],ident,manifest,expected,folder)
    release=api('releases/'+str(ident))
    verify_draft(release,ident,manifest,expected,folder)
    return release


def main(preflight=False,recover_draft_id=None):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise ValueError('Run only through the owner-approved publication workflow')
    mode=os.environ.get('APPROVED_MODE','')
    if mode not in ('preflight','publish','recover') or (not preflight and mode!=('recover' if recover_draft_id is not None else 'publish')):
        raise ValueError('Explicit owner-approved publication/recovery mode required')
    if recover_draft_id is not None and (type(recover_draft_id) is not int or recover_draft_id<=0):raise ValueError('A positive exact draft ID is required')
    sha=os.environ['APPROVED_SHA'];channel=os.environ['APPROVED_CHANNEL'];folder=Path('out')
    manifest,expected=validate(folder,sha,channel);tag=manifest['tag']
    if subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=sha:raise ValueError('Checkout changed')
    check_tag(tag,sha,recovery=recover_draft_id is not None)
    matches=releases_for_tag(tag)
    gh=['gh','--repo',REPO]
    if recover_draft_id is not None:
        # No create, upload, replacement or deletion is allowed during recovery.
        exact_draft(tag,recover_draft_id,manifest,expected,folder)
        ident=recover_draft_id
    else:
        if matches:raise ValueError('Release/draft already exists; use explicit owner-approved recovery for an exact match, or a new version')
        args=gh+['release','create',tag,'--target',sha,'--draft','--title','DeckPilot '+manifest['version'],'--notes','Owner-approved paired app and Decky build. See repository update instructions.']
        if channel=='preview':args.append('--prerelease')
        args += [str(folder/name) for name in expected]
    if preflight:
        subprocess.run(gh+['release','create','--help'],check=True,stdout=subprocess.DEVNULL)
        print('NON-PUBLISHING PREFLIGHT PASSED: exact checkout, paired assets/checksums and '+('verified existing draft '+str(ident) if recover_draft_id is not None else 'unused tag/release')+'.')
        if recover_draft_id is None:print('Publish-mode creation plan (not executed): '+shlex.join(args))
        else:print('Recovery would only finalize release ID '+str(ident)+' after fresh owner approval; no assets would be changed.')
        return
    if recover_draft_id is None:
        subprocess.run(args,check=True)
        # CLI creation uploads all assets. Discover the authenticated exact draft
        # by list, then use only its immutable ID, never the public tag endpoint.
        created=releases_for_tag(tag)
        if len(created)!=1:raise ValueError('Created draft is not uniquely visible; do not retry creation automatically')
        ident=release_id(created[0])
    exact_draft(tag,ident,manifest,expected,folder)
    check_tag(tag,sha,recovery=True)
    # Revalidate assets/identity immediately before the only publication request.
    verify_draft(api('releases/'+str(ident)),ident,manifest,expected,folder)
    api('releases/'+str(ident),{'draft':False})
    print('Published verified release ID '+str(ident))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight',action='store_true',help='Read-only checks; never create a draft, tag or release')
    parser.add_argument('--recover-draft-id',type=int,help='Explicitly recover only this exact verified draft; never replace assets')
    args=parser.parse_args()
    try:main(preflight=args.preflight,recover_draft_id=args.recover_draft_id)
    except (ValueError,KeyError,OSError,TypeError,subprocess.SubprocessError) as exc:sys.exit(str(exc))
