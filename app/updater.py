#!/usr/bin/env python3
"""User-space DeckPilot updater with explicit approval and paired release verification.

Stable/Preview checks never install. Only allowlisted runtime files are replaced;
failed health checks restore the saved app. Decky owns plugin installation.
GitHub HTTPS and SHA256 provide integrity, not an independent signature.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
import zipfile
import fcntl
from contextlib import contextmanager
from functools import wraps
import inspect

APPDIR = Path.home() / '.local/share/deckpilot-tv/app'
DATA = Path.home() / '.local/share/deckpilot-tv'
UPDATES = DATA / 'updates'
DOWNLOADS = Path.home() / 'Downloads'
MANIFEST_NAME = 'deckpilot-release.json'
REMOTE_STATE = UPDATES / 'github-release.json'
SOURCE = UPDATES / 'github-source.json'
READY = UPDATES / 'ready'
MAX_ZIP_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
ALLOWED = frozenset({
    'deckpilot.py', 'updater.py', 'README.md', 'VERSION.txt',
    'install.sh', 'uninstall.sh', 'check.sh', 'setup_drive.sh',
    'test_deckpilot.py', 'test_updater.py', MANIFEST_NAME,
})
APP_FILES = ('deckpilot.py', 'updater.py', 'VERSION.txt')


class UpdateError(Exception):
    pass


def atomic_record(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.', delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write((json.dumps(value, indent=2)+'\n').encode('utf-8'))
            handle.flush(); os.fsync(handle.fileno()); temp.replace(path)
        finally: temp.unlink(missing_ok=True)


@contextmanager
def update_lock(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    with (directory/'.operation.lock').open('a') as handle:
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc: raise UpdateError('Another update operation is running. Try again shortly.') from exc
        try: yield
        finally: fcntl.flock(handle, fcntl.LOCK_UN)


def serialized_update(fn):
    @wraps(fn)
    def guarded(*args, **kwargs):
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        directory = Path(bound.arguments.get('ready', READY)).parent if fn.__name__ == 'fetch_github_update' else bound.arguments.get('updates', UPDATES)
        try:
            with update_lock(directory): return fn(*args, **kwargs)
        except UpdateError as exc:
            if fn.__name__ == 'fetch_github_update':
                return {'status': 'error', 'message': str(exc)}
            raise
    return guarded


def version_tuple(raw):
    return semver(raw)


def current_version(appdir=APPDIR):
    try:
        text = (appdir / 'deckpilot.py').read_text(encoding='utf-8')
        match = re.search(r"^BUILD_ID\s*=\s*['\"]([^'\"]+)['\"]",text,re.M) or re.search(r"^VERSION\s*=\s*['\"](\d+\.\d+\.\d+)['\"]", text, re.M)
        return match.group(1) if match else '0.0.0'
    except OSError:
        return '0.0.0'


def inspect_zip(path, installed_version='0.0.0', allow_older=False, expected_version=None):
    """Return validated metadata; never extract untrusted paths to disk."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_ZIP_BYTES:
        raise UpdateError('Update ZIP is missing or too large.')
    if not path.name.startswith('DeckPilot_TV_v') or path.suffix.lower() != '.zip':
        raise UpdateError('This is not a DeckPilot update ZIP.')
    try:
        with zipfile.ZipFile(path) as z:
            files = {}
            total_size = 0
            for entry in z.infolist():
                if entry.is_dir():
                    continue
                if entry.file_size > MAX_FILE_BYTES:
                    raise UpdateError('A file in this update exceeds its size limit.')
                total_size += entry.file_size
                if total_size > 12 * 1024 * 1024:
                    raise UpdateError('Update uncompressed content is too large.')
                if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK:
                    raise UpdateError('ZIP contains an unsafe symbolic link.')
                p = PurePosixPath(entry.filename)
                if len(p.parts) != 2 or not re.fullmatch(r'deckpilot_tv_v\d+_\d+(?:_\d+)?', p.parts[0]):
                    raise UpdateError('Invalid update ZIP folder structure.')
                if p.parts[1] not in ALLOWED or p.parts[1] in files:
                    raise UpdateError('Unexpected or duplicate file inside update ZIP.')
                files[p.parts[1]] = entry.filename
            if MANIFEST_NAME not in files:
                raise UpdateError('No update manifest. Older ZIPs cannot be auto-installed.')
            manifest = json.loads(z.read(files[MANIFEST_NAME]))
            if not isinstance(manifest, dict) or manifest.get('product') != 'deckpilot-tv':
                raise UpdateError('Invalid DeckPilot update manifest.')
            version = manifest.get('version')
            if expected_version is not None and version!=expected_version:raise UpdateError('Approved version and app package disagree.')
            if not allow_older and version_tuple(version) <= version_tuple(installed_version):
                raise UpdateError('This ZIP is not newer than the installed version.')
            listed = manifest.get('files')
            if not isinstance(listed, dict) or set(listed) != set(files) - {MANIFEST_NAME}:
                raise UpdateError('Manifest does not match the ZIP contents.')
            for filename, expected in listed.items():
                if not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected):
                    raise UpdateError('Invalid checksum in update manifest.')
                actual = hashlib.sha256(z.read(files[filename])).hexdigest()
                if actual != expected:
                    raise UpdateError('Update ZIP contents failed SHA256 verification.')
            for required in APP_FILES + ('setup_drive.sh',):
                if required not in files:
                    raise UpdateError('Required updater file is missing.')
            source = z.read(files['deckpilot.py']).decode('utf-8')
            code_version = re.search(r"^VERSION\s*=\s*['\"](\d+\.\d+\.\d+)['\"]", source, re.M)
            build = re.search(r"^BUILD_ID\s*=\s*['\"]([^'\"]+)['\"]",source,re.M)
            actual = build.group(1) if build else (code_version.group(1) if code_version else '')
            if not code_version or actual != version or tuple(map(int,code_version.group(1).split('.'))) != semver(version)[:3]:
                raise UpdateError('App version and update manifest disagree.')
            for filename in ('deckpilot.py', 'updater.py'):
                compile(z.read(files[filename]).decode('utf-8'), filename, 'exec')
            return {'version': version, 'path': path, 'root': files[MANIFEST_NAME].rsplit('/', 1)[0], 'files': files}
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, SyntaxError, json.JSONDecodeError) as exc:
        raise UpdateError('Update ZIP is invalid or contains broken Python files.') from exc


def newest_candidate(downloads=DOWNLOADS, installed_version=None):
    installed_version = installed_version or current_version()
    best = None
    try:
        candidates = list(Path(downloads).glob('DeckPilot_TV_v*.zip'))[:150]
    except OSError:
        return None
    for path in candidates:
        try:
            item = inspect_zip(path, installed_version)
        except (UpdateError, OSError):
            continue
        if best is None or version_tuple(item['version']) > version_tuple(best['version']):
            best = item
    return best


def valid_repository(repo):
    """Accept GitHub owner/name only, never arbitrary download URLs."""
    return isinstance(repo, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repo)) and '..' not in repo


def release_source(source=SOURCE):
    try:
        data = json.loads(Path(source).read_text(encoding='utf-8'))
        repo = data.get('repository', '')
        if data.get('enabled') is True and valid_repository(repo):
            return repo
    except (OSError, ValueError, AttributeError):
        pass
    return ''


def configure_source(repository, source=SOURCE):
    if repository and not valid_repository(repository):
        raise UpdateError('Use a GitHub repository in owner/name format.')
    source = Path(source)
    source.parent.mkdir(parents=True, exist_ok=True)
    atomic_record(source, {'enabled': bool(repository), 'repository': repository})
    return repository


def safe_redirect_url(url):
    """Only GitHub release assets and GitHub-hosted asset redirects are allowed."""
    try:
        v = urllib.parse.urlsplit(url)
        return v.scheme == 'https' and v.hostname in {
            'api.github.com', 'github.com', 'objects.githubusercontent.com',
            'release-assets.githubusercontent.com',
        } and v.username is None and v.password is None and v.port in (None,443)
    except (ValueError, TypeError): return False


class GitHubRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_redirect_url(newurl):
            raise UpdateError('GitHub tried to redirect the update outside trusted hosts.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def remote_release_metadata(payload, installed_version, repository):
    """Validate GitHub's release response and select a matching SHA256 asset."""
    if not valid_repository(repository) or not isinstance(payload,dict):
        raise UpdateError('Invalid GitHub release metadata.')
    if payload.get('draft') or payload.get('prerelease'):
        raise UpdateError('Latest release is not a stable published release.')
    tag = payload.get('tag_name','').removeprefix('v')
    if version_tuple(tag) <= version_tuple(installed_version):
        return None
    expected = 'DeckPilot_TV_v'+tag+'.zip'
    for asset in payload.get('assets',[]):
        if not isinstance(asset,dict) or asset.get('name') != expected:
            continue
        digest = asset.get('digest')
        url = asset.get('browser_download_url')
        if (isinstance(digest,str) and re.fullmatch(r'sha256:[a-fA-F0-9]{64}',digest)
                and isinstance(url,str) and safe_redirect_url(url)
                and urllib.parse.urlsplit(url).hostname == 'github.com'
                and urllib.parse.urlsplit(url).path.startswith('/'+repository+'/releases/download/')
                and isinstance(asset.get('size'),int) and 0 < asset['size'] <= MAX_ZIP_BYTES):
            return {'version':tag, 'name':expected, 'sha256':digest.split(':',1)[1].lower(),
                    'url':url, 'repository':repository}
    raise UpdateError('Latest release has no matching ZIP with a GitHub SHA256 digest.')


def record_remote(status, message, **other):
    REMOTE_STATE.parent.mkdir(parents=True, exist_ok=True)
    d = {'status':status, 'message':message[:240], 'checked_at':time.time(), **other}
    atomic_record(REMOTE_STATE, d)
    return d


def remote_status():
    try:
        v=json.loads(REMOTE_STATE.read_text(encoding='utf-8'))
        return v if isinstance(v,dict) else {}
    except (OSError,ValueError):
        return {}


def _limited_get(url, limit, timeout=12):
    if not safe_redirect_url(url):
        raise UpdateError('Untrusted release address.')
    opener=urllib.request.build_opener(GitHubRedirects())
    req=urllib.request.Request(url, headers={
        'User-Agent':'DeckPilot-TV-Update-Checker', 'Accept':'application/vnd.github+json'})
    with opener.open(req, timeout=timeout) as response:
        if not safe_redirect_url(response.geturl()):
            raise UpdateError('Untrusted final download address.')
        raw=response.read(limit+1)
        if len(raw)>limit:raise UpdateError('Remote update response exceeds safety limit.')
        return raw


@serialized_update
def fetch_github_update(repository=None, installed_version=None, ready=READY):
    """Fetch signed-by-GitHub digest asset from explicitly configured public repo.

    Never installs: network download -> GitHub API SHA256 verification -> ZIP internal
    manifest and structure verification -> one staged ZIP; install remains opt-in.
    """
    repository=repository or release_source()
    installed_version=installed_version or current_version()
    if not repository:
        return record_remote('disabled','Connect your GitHub release repository first.')
    try:
        addr='https://api.github.com/repos/'+repository+'/releases/latest'
        payload=json.loads(_limited_get(addr,1024*1024).decode('utf-8'))
        data=remote_release_metadata(payload,installed_version,repository)
        if data is None:
            return record_remote('current','Latest GitHub release is already installed.',repository=repository)
        ready=Path(ready);ready.mkdir(parents=True,exist_ok=True)
        target=ready/data['name']
        if target.is_file():
            try:
                if hashlib.sha256(target.read_bytes()).hexdigest()!=data['sha256']:
                    target.unlink(missing_ok=True)
                else:
                    inspect_zip(target, installed_version)
                    return record_remote('ready','Verified release downloaded. Press Install Update.',
                                         repository=repository,version=data['version'],path=str(target),sha256=data['sha256'])
            except (OSError,UpdateError):
                target.unlink(missing_ok=True)
        raw=_limited_get(data['url'],MAX_ZIP_BYTES,timeout=25)
        if hashlib.sha256(raw).hexdigest()!=data['sha256']:
            raise UpdateError('Downloaded ZIP does not match GitHub release digest.')
        part=ready/(data['name']+'.part')
        part.write_bytes(raw)
        try:
            # Validation requires the final name, so move into place before testing.
            part.replace(target)
            inspect_zip(target,installed_version)
        except Exception:
            part.unlink(missing_ok=True);target.unlink(missing_ok=True)
            raise
        for obsolete in ready.glob('DeckPilot_TV_v*.zip'):
            if obsolete!=target: obsolete.unlink(missing_ok=True)
        return record_remote('ready','Verified release downloaded. Press Install Update.',
                             repository=repository,version=data['version'],path=str(target),sha256=data['sha256'])
    except urllib.error.HTTPError as exc:
        messages = {
            404: 'No public release found. The repository may be private, missing, or have no published release yet.',
            401: 'GitHub denied authentication. Verify the public release repository.',
            403: 'GitHub access denied or rate limited. Check network policy and retry later.',
            429: 'GitHub rate limit reached. Retry later.',
        }
        return record_remote('error', messages.get(exc.code, 'GitHub returned HTTP '+str(exc.code)+'. Retry later.'), repository=repository)
    except UpdateError as exc:
        # These are locally generated validation messages, never remote response bodies.
        return record_remote('error', str(exc), repository=repository)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError) as exc:
        return record_remote('error', 'Cannot reach the GitHub release feed or read its response. Check connectivity, TLS trust and network access to api.github.com; current installation is unchanged.', repository=repository)


def candidate_for_install(installed_version=None):
    installed_version=installed_version or current_version()
    local=newest_candidate(DOWNLOADS,installed_version)
    remote=remote_status()
    online=None
    if (remote.get('status')=='ready' and remote.get('repository')==release_source()
            and remote.get('path')):
        try:
            path=Path(remote['path'])
            if path.parent.resolve()==READY.resolve():
                digest = remote.get('sha256')
                if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
                    raise UpdateError('Refresh the release feed to verify this staged download.')
                if path.stat().st_size > MAX_ZIP_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise UpdateError('Staged download changed. Check for updates again.')
                online=inspect_zip(path,installed_version)
                online['sha256']=digest
        except (ValueError,UpdateError,OSError):
            pass
    if not online:return local
    if not local:return online
    return online if version_tuple(online['version'])>version_tuple(local['version']) else local


def record(status, message, version=None, updates=UPDATES):
    updates.mkdir(parents=True, exist_ok=True)
    result = {'status': status, 'message': message, 'version': version,
              'timestamp_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    dest = updates / 'result.json'
    atomic_record(dest, result)


def service_call(action):
    result = subprocess.run(['systemctl', '--user', action, 'deckpilot-tv.service'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=25, check=False)
    if result.returncode != 0:
        raise UpdateError('Could not ' + action + ' the DeckPilot user service.')


def healthy(version, timeout=18):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:38647/api/state', timeout=3) as resp:
                if (lambda state: state.get('build_id',state.get('version')))(json.load(resp)) == version:
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(.7)
    return False


def begin_recovery_snapshot(appdir,updates,target_version):
    updates=Path(updates);backup=updates/'recovery-app';journal=updates/'transaction.json'
    if journal.exists():raise UpdateError('An interrupted update needs recovery first.')
    if backup.exists():backup.rename(updates/('orphan-app-'+str(time.time_ns())))
    backup.mkdir(parents=True)
    hashes={}
    for name in APP_FILES:
        source=Path(appdir)/name
        if source.is_file():
            shutil.copy2(source,backup/name);hashes[name]=hashlib.sha256((backup/name).read_bytes()).hexdigest()
    atomic_record(journal,{'version':current_version(appdir),'target':target_version,'files':hashes})
    return backup


@serialized_update
def recover_interrupted(appdir=APPDIR,updates=UPDATES,manage_service=True):
    appdir=Path(appdir);updates=Path(updates);journal=updates/'transaction.json'
    try:data=json.loads(journal.read_text());hashes=data['files']
    except (OSError,ValueError,KeyError) as exc:raise UpdateError('No valid interrupted-update recovery record.') from exc
    if not isinstance(hashes,dict) or 'deckpilot.py' not in hashes or not set(hashes).issubset(APP_FILES) or any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in hashes.values()):raise UpdateError('Invalid recovery file list.')
    candidates=[updates/'recovery-app',updates/'previous-app']
    backup=next((root for root in candidates if all((root/name).is_file() and not (root/name).is_symlink() and hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())),None)
    if backup is None:raise UpdateError('Recovery snapshot is missing or changed. No files were written.')
    if manage_service:service_call('stop')
    appdir.mkdir(parents=True,exist_ok=True)
    for name in APP_FILES:
        if name in hashes:shutil.copy2(backup/name,appdir/name)
        else:(appdir/name).unlink(missing_ok=True)
    if manage_service:
        service_call('start')
        if not healthy(data['version']):raise UpdateError('Recovered app did not pass the restart check. Snapshot retained.')
    record('recovered','Interrupted update recovered; prior app restored.',data['version'],updates)
    journal.unlink(missing_ok=True)
    if backup.name=='recovery-app':
        previous=updates/'previous-app'
        if previous.exists():previous.rename(updates/('previous-before-recovery-'+str(time.time_ns())))
        backup.rename(previous)
    return data['version']



@serialized_update
def install_archive(path, appdir=APPDIR, updates=UPDATES, manage_service=True, expected_sha256=None, allow_older=False, expected_version=None):
    """Freeze the approved archive before validation/installation to prevent replacement races."""
    path = Path(path); updates = Path(updates); updates.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='deckpilot-approved-', dir=updates) as temp:
        with path.open('rb') as handle: raw = handle.read(MAX_ZIP_BYTES+1)
        if len(raw) > MAX_ZIP_BYTES: raise UpdateError('Update ZIP exceeds the size limit.')
        if expected_sha256 is not None:
            if not re.fullmatch(r'[a-f0-9]{64}', expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
                raise UpdateError('Approved GitHub digest does not match this ZIP. Download again.')
        snapshot = Path(temp)/path.name; snapshot.write_bytes(raw)
        return _install_snapshot(snapshot, appdir, updates, manage_service, allow_older, expected_version)


def _install_snapshot(path, appdir=APPDIR, updates=UPDATES, manage_service=True, allow_older=False, expected_version=None):
    appdir = Path(appdir)
    updates = Path(updates)
    info = inspect_zip(path, current_version(appdir), allow_older=allow_older, expected_version=expected_version)
    updates.mkdir(parents=True, exist_ok=True)
    # A local ZIP's SHA256 proves integrity relative to its included manifest,
    # not authorship. The user must obtain it from a trusted source.
    with tempfile.TemporaryDirectory(prefix='deckpilot-stage-', dir=updates) as temp:
        stage = Path(temp)
        replacement = stage / 'new'
        backup = updates/'recovery-app'
        replacement.mkdir()
        with zipfile.ZipFile(path) as z:
            for name in APP_FILES:
                data = z.read(info['files'][name])
                (replacement / name).write_bytes(data)
        backup=begin_recovery_snapshot(appdir,updates,info['version'])
        record('working', 'Installing v' + info['version'] + '…', info['version'], updates)
        stopped = False
        try:
            if manage_service:
                service_call('stop'); stopped = True
            appdir.mkdir(parents=True, exist_ok=True)
            for name in APP_FILES:
                os.replace(replacement/name, appdir/name)
            os.chmod(appdir/'deckpilot.py', 0o700)
            os.chmod(appdir/'updater.py', 0o700)
            if manage_service:
                service_call('start')
                if not healthy(info['version']):
                    raise UpdateError('Updated version did not pass the restart check.')
            last = updates / 'previous-app'
            # Keep only one prior app snapshot. Preferences and saved game config
            # backups are elsewhere and never touched by this updater.
            prior = stage/'prior-snapshot'
            if last.exists(): last.rename(prior)
            try: backup.rename(last)
            except Exception:
                if prior.exists(): prior.rename(last)
                raise
            record('success', 'Installed v' + info['version'] + '. Previous version saved for rollback.', info['version'], updates)
            (updates/'transaction.json').unlink(missing_ok=True)
            return info['version']
        except Exception as exc:
            recovery = backup if backup.exists() else updates/'previous-app'
            for name in APP_FILES:
                old = recovery / name
                if old.is_file():
                    shutil.copy2(old, appdir/name)
                else:
                    (appdir/name).unlink(missing_ok=True)
            if manage_service and stopped:
                try: service_call('start')
                except Exception: pass
            record('rolled-back', 'Update failed; previous app files restored.', info['version'], updates)
            (updates/'transaction.json').unlink(missing_ok=True)
            raise UpdateError('Update failed and was rolled back.') from exc


@serialized_update
def rollback_previous(appdir=APPDIR, updates=UPDATES, manage_service=True):
    """Restore the single prior version after a regression (manual action)."""
    appdir, updates = Path(appdir), Path(updates)
    old = updates / 'previous-app'
    if not old.is_dir() or not (old/'deckpilot.py').is_file():
        raise UpdateError('No previous version is saved.')
    wanted = current_version(old)
    with tempfile.TemporaryDirectory(prefix='deckpilot-rollback-', dir=updates) as td:
        snapshot = Path(td)
        for name in APP_FILES:
            if (appdir/name).is_file():
                shutil.copy2(appdir/name, snapshot/name)
        recovery_backup=begin_recovery_snapshot(appdir,updates,wanted)
        record('working','Restoring the previous DeckPilot version…',wanted,updates)
        stopped = False
        try:
            if manage_service:
                service_call('stop'); stopped = True
            for name in APP_FILES:
                if (old/name).is_file():
                    shutil.copy2(old/name, appdir/name)
                else:
                    (appdir/name).unlink(missing_ok=True)
            if manage_service:
                service_call('start')
                if not healthy(wanted):
                    raise UpdateError('Old version failed the restart check.')
            # Keep a single previous version (the newer version in case user wants to undo rollback).
            for name in APP_FILES:
                (old/name).unlink(missing_ok=True)
                if (snapshot/name).is_file():
                    shutil.copy2(snapshot/name, old/name)
            record('success','Restored DeckPilot v'+wanted+'.',wanted,updates)
            (updates/'transaction.json').unlink(missing_ok=True)
            shutil.rmtree(recovery_backup)
            return wanted
        except Exception as exc:
            for name in APP_FILES:
                if (snapshot/name).is_file(): shutil.copy2(snapshot/name, appdir/name)
                else: (appdir/name).unlink(missing_ok=True)
            if manage_service and stopped:
                try: service_call('start')
                except Exception: pass
            record('rolled-back','Rollback failed; current app files restored.',wanted,updates)
            (updates/'transaction.json').unlink(missing_ok=True)
            raise UpdateError('Could not restore the previous version; current files were preserved.') from exc


# Approved update channels. This client never talks to Actions artifacts or private APIs.
TRUSTED_REPOSITORY = 'goddenator/DeckPilot-TV'
SUITE_PRODUCT = 'deckpilot-tv-suite'
SUITE_MANIFEST = 'DeckPilot-Update.json'
MAX_PLUGIN_BYTES = 16*1024*1024
CHANNEL_FILE = UPDATES/'channel.json'
SUITE_STATE = UPDATES/'suite.json'
SUPPORTED_UI_SCHEMA = 2
PLUGIN_FILES = {'plugin.json','package.json','main.py','dist/index.js','LICENSE','README.md','update_client.py'}


def semver(value):
    if not isinstance(value,str): raise UpdateError('Invalid release version.')
    match = re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-preview\.(0|[1-9][0-9]*))?',value)
    if not match: raise UpdateError('Use X.Y.Z or X.Y.Z-preview.N.')
    return tuple(int(v) for v in match.groups()[:3]) + ((1,0) if match[4] is None else (0,int(match[4])))


def suite_channel():
    try:
        value=json.loads(CHANNEL_FILE.read_text()).get('channel','stable')
        return value if value in ('stable','preview') else 'stable'
    except (OSError,ValueError,AttributeError): return 'stable'


def set_suite_channel(channel):
    if channel not in ('stable','preview'): raise UpdateError('Choose Stable or Preview.')
    with update_lock(UPDATES):
        atomic_record(CHANNEL_FILE,{'channel':channel})
    return {'ok':True,'message':channel.title()+' selected. No installation or downgrade was started.'}


def read_suite_state():
    try:
        value=json.loads(SUITE_STATE.read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def suite_record(status,message,**values):
    old=read_suite_state()
    if status=='error' and old.get('status')=='ready' and old.get('channel')==suite_channel():
        result={**old,'last_check_error':message,'message':'Check failed. Previously verified update is still available.','checked_at':time.time()}
        atomic_record(SUITE_STATE,result);return result
    result={'status':status,'message':message,'checked_at':time.time(),'channel':suite_channel(),**values}
    atomic_record(SUITE_STATE,result)
    return result


def release_asset(release,name,limit):
    assets=release.get('assets',[])
    if not isinstance(assets,list):raise UpdateError('Invalid release assets.')
    matches=[a for a in assets if isinstance(a,dict) and a.get('name')==name]
    if len(matches)!=1: raise UpdateError('Release must contain exactly one '+name+'.')
    asset=matches[0]; digest=asset.get('digest'); tag=release.get('tag_name')
    expected='https://github.com/'+TRUSTED_REPOSITORY+'/releases/download/'+tag+'/'+name
    if (asset.get('browser_download_url')!=expected or not isinstance(digest,str)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',digest)
            or type(asset.get('size')) is not int or not 0<asset['size']<=limit):
        raise UpdateError('Release asset source, size or GitHub SHA256 is invalid.')
    return {'name':name,'url':expected,'sha256':digest[7:],'size':asset['size']}


def select_suite_release(releases,channel):
    if not isinstance(releases,list):raise UpdateError('Invalid GitHub Releases response.')
    candidates=[]
    for release in releases:
        if not isinstance(release,dict) or release.get('draft') is not False:continue
        if type(release.get('prerelease')) is not bool:continue
        if release['prerelease'] != (channel=='preview'):continue
        tag=release.get('tag_name','')
        if not isinstance(tag,str) or not tag.startswith('v'):continue
        try: key=semver(tag[1:])
        except UpdateError:continue
        if ('-preview.' in tag) != (channel=='preview'):continue
        if release.get('html_url')!='https://github.com/'+TRUSTED_REPOSITORY+'/releases/tag/'+tag:
            raise UpdateError('Release came from an unexpected repository.')
        candidates.append((key,release))
    if not candidates:return None
    return max(candidates,key=lambda pair:pair[0])[1]


def verified_bytes(asset,limit):
    raw=_limited_get(asset['url'],limit,timeout=25)
    if len(raw)!=asset['size'] or hashlib.sha256(raw).hexdigest()!=asset['sha256']:
        raise UpdateError('Release asset failed GitHub SHA256/size verification.')
    return raw


def validate_suite_manifest(manifest,release,assets,channel):
    version=release['tag_name'][1:];semver(version)
    if not isinstance(manifest,dict) or manifest.get('format')!=1 or manifest.get('product')!=SUITE_PRODUCT:
        raise UpdateError('Not a DeckPilot suite manifest.')
    if manifest.get('repository')!=TRUSTED_REPOSITORY or manifest.get('version')!=version or manifest.get('channel')!=channel or manifest.get('tag')!=release['tag_name']:
        raise UpdateError('Release version, tag, source and channel disagree.')
    if not isinstance(manifest.get('commit'),str) or not re.fullmatch(r'[a-f0-9]{40}',manifest['commit']):
        raise UpdateError('Release has no exact reviewed commit.')
    for key in ('app','plugin'):
        component=manifest.get(key,{})
        if not isinstance(component,dict) or any(component.get(field)!=assets[key][field] for field in ('name','sha256','size')):
            raise UpdateError('Manifest and GitHub component metadata disagree.')
        if component.get('version')!=version or component.get('ui_schema')!=SUPPORTED_UI_SCHEMA or component.get('update_protocol')!=1:
            raise UpdateError('Update protocol or paired component version is incompatible.')
    return manifest


def inspect_plugin_zip(path,version=None,legacy=False):
    path=Path(path)
    if path.stat().st_size>MAX_PLUGIN_BYTES:raise UpdateError('Plugin ZIP is too large.')
    try:
        with zipfile.ZipFile(path) as z:
            files={};total=0
            for entry in z.infolist():
                if entry.is_dir():continue
                total+=entry.file_size
                parts=PurePosixPath(entry.filename).parts
                if (len(parts)<2 or parts[0]!='DeckPilot' or '..' in parts
                        or '\\' in entry.filename or entry.filename.startswith('/')
                        or stat.S_IFMT(entry.external_attr>>16)==stat.S_IFLNK):raise UpdateError('Unsafe plugin archive path.')
                name='/'.join(parts[1:])
                if name not in PLUGIN_FILES or name in files or entry.file_size>MAX_FILE_BYTES or total>32*1024*1024:
                    raise UpdateError('Unexpected, duplicate or oversized plugin file.')
                files[name]=entry.filename
            required=PLUGIN_FILES-({'update_client.py'} if legacy else set())
            if not required.issubset(files):raise UpdateError('Plugin package is incomplete.')
            plugin=json.loads(z.read(files['plugin.json']));package=json.loads(z.read(files['package.json']))
            if plugin.get('name')!='DeckPilot TV' or plugin.get('flags')!=[] or package.get('name')!='deckpilot-tv-decky':
                raise UpdateError('Plugin identity or permissions changed.')
            if not legacy and package.get('deckpilot')!={'product':'deckpilot-tv','ui_schema':2,'update_protocol':1}:raise UpdateError('Plugin protocol is incompatible.')
            semver(package.get('version'))
            if version and package['version']!=version:raise UpdateError('Plugin and release versions disagree.')
            compile(z.read(files['main.py']).decode(),'main.py','exec')
            if 'update_client.py' in files:compile(z.read(files['update_client.py']).decode(),'update_client.py','exec')
            return {'version':package['version']}
    except (OSError,ValueError,KeyError,SyntaxError,zipfile.BadZipFile) as exc:raise UpdateError('Invalid plugin package.') from exc


@serialized_update
def fetch_suite_update():
    channel=suite_channel()
    try:
        releases=[]
        for page in range(1,4):
            payload=json.loads(_limited_get('https://api.github.com/repos/'+TRUSTED_REPOSITORY+'/releases?per_page=50&page='+str(page),1024*1024))
            if not isinstance(payload,list):raise UpdateError('Invalid release list.')
            releases.extend(payload)
            if len(payload)<50:break
        release=select_suite_release(releases,channel)
        if release is None:return suite_record('empty','No approved '+channel+' suite release is published yet.')
        version=release['tag_name'][1:]
        assets={
            'app':release_asset(release,'DeckPilot_TV_v'+version+'.zip',MAX_ZIP_BYTES),
            'plugin':release_asset(release,'DeckPilot_Decky_v'+version+'.zip',MAX_PLUGIN_BYTES),
            'manifest':release_asset(release,SUITE_MANIFEST,65536),
            'checksums':release_asset(release,'SHA256SUMS',65536),
        }
        manifest_raw=verified_bytes(assets['manifest'],65536)
        manifest=validate_suite_manifest(json.loads(manifest_raw),release,assets,channel)
        lines=verified_bytes(assets['checksums'],65536).decode().splitlines()
        expected={assets[k]['name']:assets[k]['sha256'] for k in ('app','plugin','manifest')}
        found={}
        for line in lines:
            match=re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.-]+)',line)
            if not match or match[2] in found:raise UpdateError('Invalid release checksum list.')
            found[match[2]]=match[1]
        if found!=expected:raise UpdateError('Release checksums and manifest do not match.')
        folder=UPDATES/'suite-cache'/version;folder.mkdir(parents=True,exist_ok=True)
        for kind in ('app','plugin'):
            asset=assets[kind];target=folder/asset['name']
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=asset['sha256']:
                raw=verified_bytes(asset,MAX_ZIP_BYTES if kind=='app' else MAX_PLUGIN_BYTES)
                temp=target.with_suffix('.part')
                try:temp.write_bytes(raw);temp.replace(target)
                finally:temp.unlink(missing_ok=True)
            if kind=='app':inspect_zip(target,'0.0.0',allow_older=True,expected_version=version)
            else:inspect_plugin_zip(target,version)
        proposal={'manifest':manifest,'assets':assets,'folder':str(folder)}
        token=hashlib.sha256(json.dumps(proposal,sort_keys=True).encode()).hexdigest()
        return suite_record('ready','Verified '+channel+' update ready for review.',proposal=proposal,token=token)
    except urllib.error.HTTPError as exc:
        return suite_record('error','GitHub release check returned HTTP '+str(exc.code)+'. No installation was started.')
    except (OSError,ValueError,TypeError,UpdateError) as exc:
        message=str(exc) if isinstance(exc,UpdateError) else 'Cannot reach or validate the GitHub release feed. Check network access to api.github.com.'
        return suite_record('error',message)


def suite_proposal(token=None):
    state=read_suite_state()
    if state.get('status')!='ready' or not state.get('proposal') or (token is not None and token!=state.get('token')):
        raise UpdateError('Update changed or is unavailable. Check and review again.')
    proposal=state['proposal'];manifest=proposal['manifest'];version=manifest['version'];semver(version)
    if hashlib.sha256(json.dumps(proposal,sort_keys=True).encode()).hexdigest()!=state.get('token'):raise UpdateError('Staged approval metadata changed.')
    if manifest['channel']!=suite_channel():raise UpdateError('Channel changed. Check and review again.')
    expected_folder=(UPDATES/'suite-cache'/version).resolve()
    if Path(proposal['folder']).resolve()!=expected_folder:raise UpdateError('Invalid staged update location.')
    for kind,limit in (('app',MAX_ZIP_BYTES),('plugin',MAX_PLUGIN_BYTES)):
        asset=proposal['assets'][kind];path=expected_folder/asset['name']
        if path.is_symlink() or path.stat().st_size>limit or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:
            raise UpdateError('Staged update changed. Download it again.')
    return state


def suite_status(plugin_version=None):
    app=current_version();state=read_suite_state();channel=suite_channel()
    result={'recovery_required':(UPDATES/'transaction.json').exists(),'protocol':1,'channel':channel,'repository':TRUSTED_REPOSITORY,'app_installed':app,'plugin_installed':plugin_version,
            'status':state.get('status','idle'),'message':state.get('message','Check for approved updates.'),
            'app_rollback':(UPDATES/'previous-app/deckpilot.py').is_file() or (UPDATES/'transaction.json').exists(),
            'plugin_rollback':(UPDATES/'plugin-rollback.json').is_file(),
            'compatible':plugin_version is not None and plugin_version==app}
    try:
        work=json.loads((UPDATES/'result.json').read_text())
        if work.get('status')=='queued':
            try:approved=json.loads((UPDATES/'approved-app.json').read_text())
            except (OSError,ValueError):approved={}
            if time.time()-approved.get('approved_at',0)>180:work={**work,'status':'error','message':'Queued update did not start. Review and retry.'}
        result['operation']=work
    except (OSError,ValueError):pass
    if state.get('channel')==channel and state.get('status')=='ready':
        try:
            checked=suite_proposal();manifest=checked['proposal']['manifest'];version=manifest['version']
            result.update(available=app!=version or plugin_version!=version,version=version,token=checked['token'],commit=manifest['commit'],
                          app_needed=app!=version,plugin_needed=plugin_version!=version,
                          downgrade=semver(version)<semver(app),app_first=app!=version or result['recovery_required'] or result.get('operation',{}).get('status') in ('queued','working'))
        except (OSError,ValueError,KeyError,UpdateError):result.update(status='error',message='Staged update is invalid. Check again.')
    return result


def start_suite_install(token,allow_downgrade=False):
    with update_lock(UPDATES):
        if (UPDATES/'transaction.json').exists():raise UpdateError('Restore the interrupted app update first.')
        state=suite_proposal(token);version=state['proposal']['manifest']['version']
        if semver(version)<semver(current_version()) and not allow_downgrade:raise UpdateError('Downgrade needs explicit approval.')
        runner=shutil.which('systemd-run')
        if not runner:raise UpdateError('The SteamOS user update service is unavailable.')
        # Pin an approved descriptor rather than reading the periodically refreshed proposal later.
        approved=UPDATES/'approved-app.json'
        try:
            previous=json.loads(approved.read_text());work=json.loads((UPDATES/'result.json').read_text())
            if work.get('status') in ('queued','working') and time.time()-previous.get('approved_at',0)<180:raise UpdateError('An approved update is already in progress.')
        except (OSError,ValueError):pass
        state['approved_at']=time.time();atomic_record(approved,state)
        cmd=[runner,'--user','--collect','--unit=deckpilot-update-'+str(time.time_ns()),sys.executable,str(Path(__file__).resolve()),'perform-suite-install','--token',token]
        if allow_downgrade:cmd.append('--allow-downgrade')
        record('queued','Approved app update queued.',version)
        try:run=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            record('error','User update service did not accept the request. Review and retry.',version)
            raise UpdateError('Cannot start the user update service.') from exc
        if run.returncode:
            record('error','Could not queue app update. Installation unchanged.',version)
            raise UpdateError('Could not queue the user-space app update. Installation unchanged.')
        return {'ok':True,'message':'App update started. Wait for restart, then update the plugin.'}


def perform_suite_install(token,allow_downgrade=False):
    state=json.loads((UPDATES/'approved-app.json').read_text())
    if state.get('token')!=token or hashlib.sha256(json.dumps(state.get('proposal'),sort_keys=True).encode()).hexdigest()!=token:raise UpdateError('Approval does not match.')
    proposal=state['proposal'];version=proposal['manifest']['version']
    if proposal['manifest']['channel']!=suite_channel():raise UpdateError('Channel changed after approval.')
    asset=proposal['assets']['app'];path=Path(proposal['folder'])/asset['name']
    if path.parent.resolve()!=(UPDATES/'suite-cache'/version).resolve():raise UpdateError('Invalid approved app path.')
    return install_archive(path,expected_sha256=asset['sha256'],allow_older=allow_downgrade or current_version()==version,expected_version=version)


def start_suite_rollback():
    interrupted=(UPDATES/'transaction.json').is_file()
    if not interrupted and not (UPDATES/'previous-app/deckpilot.py').is_file():raise UpdateError('No app rollback is saved.')
    runner=shutil.which('systemd-run')
    if not runner:raise UpdateError('SteamOS user service unavailable.')
    cmd=[runner,'--user','--collect','--unit=deckpilot-rollback-'+str(time.time_ns()),sys.executable,str(Path(__file__).resolve()),'recover-interrupted' if interrupted else 'rollback']
    if subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12,check=False).returncode:
        raise UpdateError('Could not start app rollback.')
    return {'ok':True,'message':'App rollback started. Plugin rollback is a separate Decky-approved step.'}


def snapshot_plugin(plugin_dir):
    root=Path(plugin_dir).resolve();package=json.loads((root/'package.json').read_text());version=package['version'];semver(version)
    dest=UPDATES/'plugin-backups'/('DeckPilot_Decky_v'+version+'.zip');dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent,suffix='.zip',delete=False) as handle:temp=Path(handle.name)
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
            for name in sorted(PLUGIN_FILES):
                source=root/name
                if not source.is_file():
                    if name=='update_client.py':continue
                    raise UpdateError('Current plugin is incomplete; rollback snapshot unavailable.')
                if source.is_symlink() or not source.resolve().is_relative_to(root) or source.stat().st_size>MAX_FILE_BYTES:
                    raise UpdateError('Unsafe current plugin file.')
                z.writestr('DeckPilot/'+name,source.read_bytes())
        inspect_plugin_zip(temp,version,legacy=True);temp.replace(dest)
    finally:temp.unlink(missing_ok=True)
    return {'version':version,'path':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}


def prepare_plugin_handoff(token,plugin_dir,rollback=False):
    with update_lock(UPDATES):
        if rollback:
            artifact=json.loads((UPDATES/'plugin-rollback.json').read_text());path=Path(artifact['path'])
            if path.parent.resolve()!=(UPDATES/'plugin-backups').resolve():raise UpdateError('Invalid rollback snapshot.')
        else:
            state=suite_proposal(token);proposal=state['proposal'];version=proposal['manifest']['version']
            if current_version()!=version or (UPDATES/'transaction.json').exists():raise UpdateError('Finish or recover the app update first, then the matching plugin.')
            installed=json.loads((Path(plugin_dir)/'package.json').read_text()).get('version')
            if installed==version:raise UpdateError('Matching plugin is already installed.')
            previous=snapshot_plugin(plugin_dir)
            asset=proposal['assets']['plugin'];path=Path(proposal['folder'])/asset['name']
            artifact={'version':version,'path':str(path),'sha256':asset['sha256']}
            atomic_record(UPDATES/'plugin-rollback.json',previous)
        raw=path.read_bytes()
        if len(raw)>MAX_PLUGIN_BYTES or hashlib.sha256(raw).hexdigest()!=artifact['sha256']:raise UpdateError('Plugin bytes changed; handoff cancelled.')
        inspect_plugin_zip(path,artifact['version'],legacy=rollback)
        import secrets,socket
        nonce=secrets.token_urlsafe(32)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        descriptor=UPDATES/('handoff-'+secrets.token_hex(8)+'.json')
        atomic_record(descriptor,{**artifact,'nonce':nonce,'port':port,'expires':time.time()+300})
        runner=shutil.which('systemd-run')
        if not runner:raise UpdateError('SteamOS user helper unavailable; no plugin install requested.')
        cmd=[runner,'--user','--collect','--unit=deckpilot-plugin-handoff-'+str(time.time_ns()),sys.executable,str(Path(__file__).resolve()),'serve-plugin','--descriptor',str(descriptor)]
        result=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12,check=False)
        if result.returncode:raise UpdateError('Cannot start the verified plugin handoff.')
        url='http://127.0.0.1:'+str(port)+'/'+nonce+'/DeckPilot.zip'
        started=False
        for _ in range(30):
            try:
                with urllib.request.urlopen(urllib.request.Request(url,method='HEAD'),timeout=.25) as response:
                    if response.status==200:started=True;break
            except OSError:time.sleep(.1)
        if not started:raise UpdateError('Plugin handoff did not become ready. No installation was requested.')
        return {'ok':True,'version':artifact['version'],'url':url,
                'sha256':artifact['sha256'],'expires_in':300,'method':'decky-install-from-url',
                'message':'Copy this URL, open Decky → Developer → Install from URL, paste and approve. This does not install by itself.'}


def serve_plugin(descriptor):
    from http.server import BaseHTTPRequestHandler,HTTPServer
    descriptor=Path(descriptor)
    if descriptor.parent.resolve()!=UPDATES.resolve():raise UpdateError('Invalid handoff descriptor.')
    data=json.loads(descriptor.read_text())
    path=Path(data['path'])
    if (path.is_symlink() or not path.resolve().is_relative_to(UPDATES.resolve())
            or not re.fullmatch(r'[A-Za-z0-9_-]{32,64}',data.get('nonce',''))
            or not time.time()<data.get('expires',0)<=time.time()+301):raise UpdateError('Invalid or expired plugin handoff.')
    raw=path.read_bytes()
    if len(raw)>MAX_PLUGIN_BYTES or hashlib.sha256(raw).hexdigest()!=data['sha256']:raise UpdateError('Plugin snapshot changed.')
    route='/'+data['nonce']+'/DeckPilot.zip'
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(2)
            super().setup()
        def do_HEAD(self):self.do_GET(head=True)
        def do_GET(self,head=False):
            if self.path!=route or time.time()>data['expires']:
                self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers()
            if not head:self.wfile.write(raw)
        def log_message(self,*args):pass
    try:
        with HTTPServer(('127.0.0.1',data['port']),Handler) as server:
            server.timeout=.5
            while time.time()<data['expires']:server.handle_request()
    finally:descriptor.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description='Install a trusted DeckPilot ZIP and roll back on failure.')
    parser.add_argument('command', choices=['check', 'install', 'rollback','suite-status','suite-check','suite-channel','suite-install','perform-suite-install','plugin-handoff','plugin-rollback','serve-plugin','suite-rollback','recover-interrupted'])
    parser.add_argument('archive', nargs='?')
    parser.add_argument('--sha256')
    parser.add_argument('--plugin-version')
    parser.add_argument('--plugin-dir')
    parser.add_argument('--token')
    parser.add_argument('--channel',choices=['stable','preview'])
    parser.add_argument('--allow-downgrade',action='store_true')
    parser.add_argument('--descriptor')
    args = parser.parse_args()
    try:
        if args.command.startswith('suite-') or args.command in ('perform-suite-install','plugin-handoff','plugin-rollback','serve-plugin'):
            if args.command=='suite-status':result=suite_status(args.plugin_version)
            elif args.command=='suite-check':fetch_suite_update();result=suite_status(args.plugin_version)
            elif args.command=='suite-channel':result=set_suite_channel(args.channel)
            elif args.command=='suite-install':result=start_suite_install(args.token,args.allow_downgrade)
            elif args.command=='perform-suite-install':result={'version':perform_suite_install(args.token,args.allow_downgrade)}
            elif args.command=='suite-rollback':result=start_suite_rollback()
            elif args.command=='serve-plugin':serve_plugin(args.descriptor);return
            else:result=prepare_plugin_handoff(args.token,args.plugin_dir,args.command=='plugin-rollback')
            print(json.dumps(result));return
        if args.command == 'check':
            item = newest_candidate()
            print(item['version'] if item else 'No newer ZIP in Downloads.')
            return
        if args.command == 'recover-interrupted':
            print('Recovered:',recover_interrupted());return
        if args.command == 'rollback':
            print('Restored:', rollback_previous()); return
        if not args.archive:
            raise UpdateError('No update ZIP was provided.')
        print('Installed:', install_archive(args.archive, expected_sha256=args.sha256))
    except (UpdateError,OSError,ValueError,KeyError,TypeError) as exc:
        if args.command=='perform-suite-install':record('error','Approved update could not finish. Review local update status; recovery remains available.')
        if args.command.startswith('suite-') or args.command in ('plugin-handoff','plugin-rollback'):
            print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,UpdateError) else 'Update operation unavailable. Current installation is preserved.'}));return
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
