#!/usr/bin/env python3
"""DeckPilot local, explicitly approved ZIP updater.

No remote fetches, no root, no post-install hooks, no arbitrary archive extraction.
Checks archive structure and SHA256 integrity, preserves one app snapshot and
rolls back on failed health checks. SHA256 is NOT a signature: accept updates
only from a source you trust (e.g. this ChatGPT conversation).
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
    if not isinstance(raw, str) or not re.fullmatch(r'\d+\.\d+\.\d+', raw):
        raise UpdateError('Invalid version in update package.')
    return tuple(map(int, raw.split('.')))


def current_version(appdir=APPDIR):
    try:
        text = (appdir / 'deckpilot.py').read_text(encoding='utf-8')
        match = re.search(r"^VERSION\s*=\s*['\"](\d+\.\d+\.\d+)['\"]", text, re.M)
        return match.group(1) if match else '0.0.0'
    except OSError:
        return '0.0.0'


def inspect_zip(path, installed_version='0.0.0'):
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
            if version_tuple(version) <= version_tuple(installed_version):
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
            if not code_version or code_version.group(1) != version:
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
                if json.load(resp).get('version') == version:
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(.7)
    return False


@serialized_update
def install_archive(path, appdir=APPDIR, updates=UPDATES, manage_service=True, expected_sha256=None):
    """Freeze the approved archive before validation/installation to prevent replacement races."""
    path = Path(path); updates = Path(updates); updates.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='deckpilot-approved-', dir=updates) as temp:
        with path.open('rb') as handle: raw = handle.read(MAX_ZIP_BYTES+1)
        if len(raw) > MAX_ZIP_BYTES: raise UpdateError('Update ZIP exceeds the size limit.')
        if expected_sha256 is not None:
            if not re.fullmatch(r'[a-f0-9]{64}', expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
                raise UpdateError('Approved GitHub digest does not match this ZIP. Download again.')
        snapshot = Path(temp)/path.name; snapshot.write_bytes(raw)
        return _install_snapshot(snapshot, appdir, updates, manage_service)


def _install_snapshot(path, appdir=APPDIR, updates=UPDATES, manage_service=True):
    appdir = Path(appdir)
    updates = Path(updates)
    info = inspect_zip(path, current_version(appdir))
    updates.mkdir(parents=True, exist_ok=True)
    # A local ZIP's SHA256 proves integrity relative to its included manifest,
    # not authorship. The user must obtain it from a trusted source.
    with tempfile.TemporaryDirectory(prefix='deckpilot-stage-', dir=updates) as temp:
        stage = Path(temp)
        replacement = stage / 'new'
        backup = stage / 'old'
        replacement.mkdir(); backup.mkdir()
        with zipfile.ZipFile(path) as z:
            for name in APP_FILES:
                data = z.read(info['files'][name])
                (replacement / name).write_bytes(data)
        if appdir.exists():
            for name in APP_FILES:
                if (appdir / name).is_file():
                    shutil.copy2(appdir/name, backup/name)
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
            return wanted
        except Exception as exc:
            for name in APP_FILES:
                if (snapshot/name).is_file(): shutil.copy2(snapshot/name, appdir/name)
                else: (appdir/name).unlink(missing_ok=True)
            if manage_service and stopped:
                try: service_call('start')
                except Exception: pass
            record('rolled-back','Rollback failed; current app files restored.',wanted,updates)
            raise UpdateError('Could not restore the previous version; current files were preserved.') from exc


def main():
    parser = argparse.ArgumentParser(description='Install a trusted DeckPilot ZIP and roll back on failure.')
    parser.add_argument('command', choices=['check', 'install', 'rollback'])
    parser.add_argument('archive', nargs='?')
    parser.add_argument('--sha256')
    args = parser.parse_args()
    try:
        if args.command == 'check':
            item = newest_candidate()
            print(item['version'] if item else 'No newer ZIP in Downloads.')
            return
        if args.command == 'rollback':
            print('Restored:', rollback_previous()); return
        if not args.archive:
            raise UpdateError('No update ZIP was provided.')
        print('Installed:', install_archive(args.archive, expected_sha256=args.sha256))
    except UpdateError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
