#!/usr/bin/env python3
"""DeckPilot TV 0.6: cautious Steam Deck game preset synchronizer.

Only edits existing Unreal Engine GameUserSettings.ini files found inside
Steam Proton prefixes. Does not touch Steam client settings or display mode.
"""
from __future__ import annotations
import argparse
import csv
from functools import lru_cache
from io import BytesIO
import platform
import secrets
import zipfile
import urllib.request
import urllib.error
import statistics
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import signal
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = '0.6.0'
APP = 'deckpilot-tv'
PORT = 38647
MODES = {'graphics', 'performance', 'balanced'}
DEFAULT_MODE = 'balanced'
BASE = Path(os.environ.get('DECKPILOT_DATA', str(Path.home() / '.local/share/deckpilot-tv'))).expanduser()
CONFIG = BASE / 'config.json'
STATE = BASE / 'state.json'
LOG = BASE / 'deckpilot.log'
BACKUPS = BASE / 'backups'
REPORTS = BASE / 'reports'
CLOUD = BASE / 'cloud.json'
CLOUD_REMOTE = 'deckpilot:'
CLOUD_FOLDER = 'DeckPilot Diagnostics'
CLOUD_FILENAME = 'DeckPilot-Latest.zip'
LOCK = threading.RLock()

# Conservative starting points. All can be overwritten by a game's own
# settings menu, and actual FPS depends on the game/hardware.
PRESETS = {
    'graphics': {'x': 1920, 'y': 1080, 'quality': 3, 'resolution_scale': 100},
    'balanced': {'x': 1600, 'y': 900, 'quality': 2, 'resolution_scale': 100},
    'performance': {'x': 1280, 'y': 720, 'quality': 1, 'resolution_scale': 100},
}
SCALABILITY_KEYS = [
    'sg.ViewDistanceQuality', 'sg.AntiAliasingQuality', 'sg.ShadowQuality',
    'sg.PostProcessQuality', 'sg.TextureQuality', 'sg.EffectsQuality',
    'sg.FoliageQuality', 'sg.ShadingQuality',
]
GAME_KEYS = ['ResolutionSizeX', 'ResolutionSizeY',
             'LastUserConfirmedResolutionSizeX', 'LastUserConfirmedResolutionSizeY',
             'DesiredScreenWidth', 'DesiredScreenHeight']


def mkdir():
    BASE.mkdir(parents=True, exist_ok=True)


def log(message):
    mkdir()
    with LOG.open('a', encoding='utf-8') as f:
        f.write(dt.datetime.now(dt.timezone.utc).isoformat() + ' ' + str(message).replace('\n', ' ') + '\n')


def atomic_json(path, value):
    mkdir()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(path)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def config():
    obj = read_json(CONFIG, {})
    if not isinstance(obj, dict): obj = {}
    games = obj.get('games', {})
    if not isinstance(games, dict):
        games = {}
    return {'enabled': obj.get('enabled', False) is True,
            'default': obj.get('default', DEFAULT_MODE) if obj.get('default') in MODES else DEFAULT_MODE,
            'games': {str(k): v for k, v in games.items() if str(k).isdigit() and v in MODES}}


def effective_mode(appid, cfg=None):
    cfg = cfg or config()
    return cfg['games'].get(str(appid), cfg['default'])


def parse_vdf_key(text, key):
    match = re.search(r'^\s*"' + re.escape(key) + r'"\s+"((?:\\.|[^"])*)"', text, re.I | re.M)
    if not match:
        return None
    return match.group(1).replace('\\\\', '\\').replace('\\"', '"')


def library_paths(home=None):
    home = home or Path.home()
    roots = [home / '.local/share/Steam', home / '.steam/steam', home / '.steam/root']
    folders = set()
    for root in roots:
        if (root / 'steamapps').is_dir():
            folders.add(str((root / 'steamapps').resolve()))
        vdf = root / 'steamapps/libraryfolders.vdf'
        try:
            body = vdf.read_text(encoding='utf-8-sig')
        except OSError:
            continue
        # Steam libraryfolders.vdf typically contains a path on a line inside
        # each numbered folder block, not nested in a game's metadata.
        for raw in re.findall(r'^\s*"path"\s+"((?:\\.|[^"])*)"', body, re.M):
            path = Path(raw.replace('\\\\', '\\').replace('\\"', '"')).expanduser()
            target = path / 'steamapps'
            if target.is_dir():
                folders.add(str(target.resolve()))
    return [Path(s) for s in sorted(folders)]


def installed_games(home=None):
    results = {}
    for folder in library_paths(home):
        for manifest in folder.glob('appmanifest_*.acf'):
            try:
                raw = manifest.read_text(encoding='utf-8-sig', errors='replace')
            except OSError:
                continue
            appid = parse_vdf_key(raw, 'appid')
            name = parse_vdf_key(raw, 'name')
            if not appid or not appid.isdigit() or not name:
                continue
            results[appid] = {'appid': appid, 'name': name, 'library': str(folder), 'path': str(manifest)}
    return sorted(results.values(), key=lambda g: g['name'].casefold())


def proton_prefix(library, appid):
    return Path(library) / 'compatdata' / str(appid) / 'pfx/drive_c/users/steamuser/AppData/Local'


def find_ue_configs(game):
    """Only paths explicitly matching Unreal Engine's known saved config layout."""
    local = proton_prefix(game['library'], game['appid'])
    if not local.is_dir():
        return []
    result = []
    try:
        products = list(local.iterdir())
    except OSError:
        return []
    for product in products:
        if not product.is_dir() or product.is_symlink():
            continue
        saved = product / 'Saved/Config'
        for platform in ('WindowsNoEditor', 'Windows', 'WinGDK'):
            target = saved / platform / 'GameUserSettings.ini'
            if (target.is_file() and not target.is_symlink()
                    and not saved.is_symlink() and not (saved / platform).is_symlink()
                    and target.resolve().is_relative_to(local.resolve())):
                result.append(target)
    return result


def parse_ini_sections(text):
    # Preserve full text and comments; edit only known key assignments.
    return re.split(r'(?=^\s*\[[^\r\n]+\]\s*$)', text, flags=re.M)


def transform_ue_ini(raw, mode):
    preset = PRESETS[mode]
    mapping = {k: str(preset['quality']) for k in SCALABILITY_KEYS}
    mapping['sg.ResolutionQuality'] = str(preset['resolution_scale'])
    mapping.update({k: str(preset['x']) for k in GAME_KEYS if k.endswith('X') or k.endswith('Width')})
    mapping.update({k: str(preset['y']) for k in GAME_KEYS if k.endswith('Y') or k.endswith('Height')})
    sections = parse_ini_sections(raw)
    endings = '\r\n' if '\r\n' in raw else '\n'
    used = set()
    targets = {'ScalabilityGroups': {k: v for k, v in mapping.items() if k.startswith('sg.')},
               '/Script/Engine.GameUserSettings': {k: v for k, v in mapping.items() if not k.startswith('sg.')}}
    found_groups = set()
    output = []
    for part in sections:
        head = re.match(r'^\s*\[([^\r\n\]]+)\]', part)
        if not head or head.group(1).casefold() not in {x.casefold() for x in targets}:
            output.append(part)
            continue
        section = next(x for x in targets if x.casefold() == head.group(1).casefold())
        found_groups.add(section)
        group_map = targets[section]
        lines = part.splitlines(keepends=True)
        existing = set()
        revised = []
        for line in lines:
            match = re.match(r'^(\s*)([A-Za-z][\w.]*)(\s*=\s*)([^\r\n]*)(\r?\n?)$', line)
            if match:
                name = next((k for k in group_map if k.casefold() == match.group(2).casefold()), None)
                if name is not None:
                    if name not in existing:
                        revised.append(match.group(1) + match.group(2) + match.group(3) + group_map[name] + match.group(5))
                        existing.add(name)
                    else:
                        revised.append(line)  # don't remove duplicates in an unknown file
                    continue
            revised.append(line)
        if revised and not revised[-1].endswith(('\n', '\r')):
            revised[-1] += endings
        for key, value in group_map.items():
            if key not in existing:
                revised.append(key + '=' + value + endings)
        output.append(''.join(revised))
    combined = ''.join(output)
    for group, group_map in targets.items():
        if group in found_groups:
            continue
        if combined and not combined.endswith(('\r', '\n')):
            combined += endings
        combined += endings + '[' + group + ']' + endings
        for k, v in group_map.items():
            combined += k + '=' + v + endings
    return combined


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def safe_read_text(path):
    # Unreal config files are typically UTF-8, but many game launchers save
    # UTF-16. We avoid modifying encodings we cannot safely round-trip.
    data = path.read_bytes()
    if b'\x00' in data or len(data) > 2_000_000:
        raise ValueError('unsupported encoding or size')
    return data.decode('utf-8-sig')


def game_is_running(appid):
    """Best-effort SteamAppId environment scan. Fail safe on uncertainty."""
    proc = Path('/proc')
    try:
        pids = list(proc.iterdir())
    except OSError:
        return True
    for item in pids:
        if not item.name.isdigit():
            continue
        try:
            blob = (item / 'environ').read_bytes()
        except (OSError, PermissionError):
            continue
        if (b'SteamAppId=' + appid.encode() + b'\x00') in b'\x00' + blob + b'\x00':
            return True
        if (b'SteamGameId=' + appid.encode() + b'\x00') in b'\x00' + blob + b'\x00':
            return True
    return False


def apply_profile(game, mode, force=False):
    """Returns status. Only modifies supported existing files when no game runs."""
    files = find_ue_configs(game)
    if not files:
        return {'status': 'unsupported', 'count': 0}
    if game_is_running(game['appid']):
        return {'status': 'running', 'count': 0}
    previous = read_json(STATE, {})
    changed = 0
    skipped_manual = 0
    backups = 0
    for path in files:
        try:
            original = safe_read_text(path)
            updated = transform_ue_ini(original, mode)
            if updated == original:
                continue
            rel_id = hashlib.sha256(str(path).encode()).hexdigest()[:16]
            old = previous.get(rel_id, {})
            if old.get('after_sha') and sha(original) != old['after_sha']:
                # A game or user changed these settings since our last edit.
                # Never override this change during automatic syncing.
                # Explicit user re-selection can apply a mode again, after
                # preserving a snapshot of the newer file.
                if not force:
                    skipped_manual += 1
                    log('SKIP user/game changed file ' + str(path))
                    continue
                reselect = BACKUPS / game['appid'] / (rel_id + '.before-reselect.ini')
                shutil.copy2(path, reselect)
                old['backup'] = str(reselect)
            # Keep a backup of the user's ORIGINAL, not each later DeckPilot
            # edit. Always back up before modifying an existing configuration.
            backdir = BACKUPS / game['appid']
            backup = backdir / (rel_id + '.original.ini')
            backdir.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(path, backup)
                backups += 1
            temp = path.with_name(path.name + '.deckpilot.tmp')
            temp.write_bytes(updated.encode('utf-8'))
            os.chmod(temp, path.stat().st_mode & 0o777)
            temp.replace(path)
            previous[rel_id] = {'appid': game['appid'], 'file': str(path),
                                'backup': old.get('backup', str(backup)), 'mode': mode, 'after_sha': sha(updated)}
            changed += 1
        except (OSError, UnicodeError, ValueError) as ex:
            log('SKIP ' + game['appid'] + ' ' + str(path) + ': ' + str(ex))
    if changed:
        atomic_json(STATE, previous)
        log('APPLY ' + game['appid'] + ' ' + game['name'] + ' mode=' + mode + ' files=' + str(changed))
    return {'status': 'applied' if changed else ('manual-changes' if skipped_manual else 'already-set'),
            'count': changed, 'backups': backups, 'skipped_manual': skipped_manual}


def restore_game(appid):
    if game_is_running(appid):
        return 'Game appears to be running. Close it before restoring.'
    state = read_json(STATE, {})
    n = 0
    for k, v in list(state.items()):
        if v.get('appid') != appid:
            continue
        path = Path(v['file'])
        backup = Path(v['backup'])
        if not backup.is_file() or not path.is_file():
            continue
        try:
            current = safe_read_text(path)
            if sha(current) != v.get('after_sha'):
                log('RESTORE SKIP modified after DeckPilot: ' + str(path))
                continue  # never overwrite user/game changes
            shutil.copy2(backup, path)
            del state[k]
            n += 1
        except (OSError, ValueError):
            continue
    atomic_json(STATE, state)
    log('RESTORE ' + appid + ' restored=' + str(n))
    return f'Restored {n} unchanged DeckPilot-managed file(s). Files modified since are left alone.'


def external_vrr_capability(drm_root=Path('/sys/class/drm')):
    """Read-only VRR capability probe; does not indicate whether VRR is enabled.

    Most Steam Deck external outputs present as DP connectors even when the
    official dock's HDMI port is used. A missing sysfs attribute means unknown,
    not unsupported. Never attempt to change TV, gamescope or DRM settings.
    """
    reported = []
    try:
        connectors = list(drm_root.glob('card*-*'))
    except OSError:
        return 'unknown'
    for connector in connectors:
        name = connector.name.upper()
        if not ('-DP-' in name or '-HDMI-' in name or '-DVI-' in name):
            continue
        try:
            if (connector / 'status').read_text(encoding='ascii').strip() != 'connected':
                continue
        except OSError:
            continue
        try:
            v = (connector / 'vrr_capable').read_text(encoding='ascii').strip()
        except OSError:
            continue
        if v in ('0', '1'):
            reported.append(v == '1')
    if any(reported):
        return 'available'
    if reported and not any(reported):
        return 'not-advertised'
    return 'unknown'


def metrics_roots(home=None):
    """MangoHud log directories; never configure the overlay or Steam."""
    h = Path(home) if home is not None else Path.home()
    return [h / 'mangologs', h / 'Documents/MangoLogs',
            h / 'Downloads/mango-logs', h / '.local/share/MangoHud',
            Path('/tmp/MangoHud')]


def game_log_candidates(game, home=None):
    """Match logs conservatively by App ID or game title, not by timestamp alone.

    Generic mangoapp_YYYY.csv files cannot be unambiguously mapped to a game
    and are intentionally skipped to avoid misleading performance estimates.
    """
    target = re.sub(r'[^a-z0-9]', '', game['name'].casefold())
    appid = game['appid']
    files = []
    for root in metrics_roots(home):
        if not root.is_dir():
            continue
        try:
            options = list(root.glob('*.csv')) + list(root.glob('*/*.csv'))
        except OSError:
            continue
        for f in options:
            if not f.is_file() or f.is_symlink() or f.name.endswith('_summary.csv'):
                continue
            stem = re.sub(r'[^a-z0-9]', '', f.stem.casefold())
            if (re.search(r'^(?:appid[-_ ]?)?' + re.escape(appid) + r'[-_ .]', f.stem, re.I)
                    or (len(target) >= 5 and target in stem)):
                try:
                    if f.stat().st_size <= 20_000_000:
                        files.append(f)
                except OSError:
                    pass
    return sorted(set(files), key=lambda f: f.stat().st_mtime, reverse=True)[:4]


def summarize_mangohud_csv(path):
    try:
        st = path.stat()
    except OSError:
        return None
    return _read_mangohud_csv(str(path), st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=128)
def _read_mangohud_csv(path_name, mtime_ns, size):
    path = Path(path_name)
    """Read recorded samples, never pretend metrics are captured live.

    MangoHud CSV often starts with hardware metadata before the header.
    Per-sample FPS is not a substitute for a repeatable gameplay benchmark.
    """
    vals = []
    elapsed = []
    try:
        if path.stat().st_size > 20_000_000:
            return None
        with path.open('r', encoding='utf-8-sig', errors='replace', newline='') as f:
            rd = csv.reader(f)
            idx = None
            idx_elapsed = None
            for row in rd:
                names = [v.strip().casefold() for v in row]
                if idx is None:
                    if 'fps' in names and ('frametime' in names or 'elapsed' in names):
                        idx = names.index('fps')
                        idx_elapsed = names.index('elapsed') if 'elapsed' in names else None
                    continue
                if len(row) <= idx:
                    continue
                try:
                    number = float(row[idx])
                    if 1 <= number <= 300:
                        vals.append(number)
                        if idx_elapsed is not None and len(row) > idx_elapsed:
                            elapsed.append(float(row[idx_elapsed]))
                except (ValueError, IndexError):
                    continue
                if len(vals) >= 120_000:
                    break
    except OSError:
        return None
    if len(vals) < 60:
        return None
    ordered = sorted(vals)
    slow = max(1, int(len(ordered) * 0.01))
    duration = None
    if len(elapsed) >= 2:
        # MangoHud elapsed is often nanoseconds; other versions use seconds.
        diff = max(elapsed) - min(elapsed)
        duration = round(diff / (1e9 if diff > 1e8 else 1), 1)
    return {'avg_fps': round(statistics.mean(vals), 1),
            'low_1pct_fps': round(statistics.mean(ordered[:slow]), 1),
            'samples': len(vals), 'duration_s': duration}


def game_metrics(game):
    for path in game_log_candidates(game):
        val = summarize_mangohud_csv(path)
        if val:
            return dict(val, source=path.name)
    return None


# ===== Privacy-preserving diagnostic export and optional AI analysis =====
# No uploads happen from the background service. The optional AI command
# requires an explicitly supplied API credential and sends only this report.

def redact_diagnostic(text):
    """Best-effort sanitisation: diagnostic exports should omit user paths/secrets.

    Reports are uploaded only after the user enables Drive sync; review an example first.
    """
    text = str(text)
    home = str(Path.home())
    if home and home != '/':
        text = text.replace(home, '[HOME]')
    text = re.sub(r'(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,})\b', '[REDACTED_KEY]', text)
    text = re.sub(r'(?i)\b(authorization\s*[:=]\s*(?:Bearer\s+)?)\S+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)\b(password|secret|token|apikey|api_key)\s*[:=]\s*[^\s,;]+', r'\1=[REDACTED]', text)
    text = re.sub(r'(?i)[\w.+-]+@[\w.-]+\.[a-z]{2,}', '[EMAIL]', text)
    text = re.sub(r'(?<!\w)(?:\d{1,3}\.){3}\d{1,3}(?!\w)', '[IP]', text)
    # The log may contain absolute file paths from games and Steam library folders.
    text = re.sub(r'(?<!\w)/(?:home|run/media|mnt|media)/[^\s,;"\']+', '[FILE_PATH]', text)
    return text[:500]


def diagnostic_report():
    """Aggregate technical indicators only; no raw config, library paths or keys."""
    games = installed_games()
    cfg = config()
    file_count = sum(bool(find_ue_configs(g)) for g in games)
    state = read_json(STATE, {})
    try:
        raw_log = LOG.read_text(encoding='utf-8', errors='replace')[-100_000:]
    except OSError:
        raw_log = ''
    lines = [redact_diagnostic(line) for line in raw_log.splitlines()[-180:]]
    # Include startup, sync, errors, changes, restores; users can review ZIP.
    try:
        os_release = Path('/etc/os-release').read_text(encoding='utf-8')
        m = re.search(r'^PRETTY_NAME=(.*)$', os_release, re.M)
        os_name = m.group(1).strip('"\'') if m else 'Linux'
    except OSError:
        os_name = 'Linux'
    return {
        'format': 1, 'app': 'DeckPilot TV', 'version': VERSION,
        'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'operating_system': os_name[:120], 'kernel': platform.release()[:120],
        'python_version': platform.python_version(),
        'games_detected': len(games), 'supported_configs': file_count,
        'profile_enabled': cfg['enabled'], 'default_profile': cfg['default'],
        'per_game_overrides': len(cfg['games']),
        'known_backup_records': len(state) if isinstance(state, dict) else 0,
        'external_vrr_advertised': external_vrr_capability(),
        'log_lines': lines, 'errors': [l for l in lines if re.search(r'(?i)\b(error|exception|traceback|failed)\b', l)][-40:],
        'notes': ['Google Drive upload is optional and requires enabling it in DeckPilot.', 'Log redaction is best-effort; review before sharing.',
                  'VRR capability is not proof VRR is active.', 'No raw game configuration files are included.']
    }


def make_diagnostic_zip(report=None):
    report = report if report is not None else diagnostic_report()
    out = BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('DeckPilot-Diagnostics.json', json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        z.writestr('PLEASE_READ.txt',
                   'DeckPilot TV diagnostic package. Automatic Google Drive upload is opt-in.\n'
                   'Open DeckPilot-Diagnostics.json and REVIEW it before sharing, as log\n'
                   'sanitisation cannot guarantee that all personal information was removed.\n'
                   'It contains no intended passwords, credentials, settings files or raw Steam manifests.\n')
    return out.getvalue()


def save_diagnostic_zip():
    REPORTS.mkdir(parents=True, exist_ok=True)
    name = 'DeckPilot-Latest-Local.zip'  # replace instead of accumulating ZIP files
    dest = REPORTS / name
    dest.write_bytes(make_diagnostic_zip())
    os.chmod(dest, 0o600)
    return dest



# ===== Optional private Google Drive diagnostic sync (no OpenAI API) =====
# Only one fixed remote ZIP is used, so Drive's visible folder does not grow.
# This requires a separate, user-authorised rclone Google Drive remote named
# "deckpilot". Google tokens are held only by rclone; never by this app.

def cloud_config():
    raw = read_json(CLOUD, {})
    if not isinstance(raw, dict):
        raw = {}
    return {'enabled': raw.get('enabled') is True,
            'last_success': raw.get('last_success') if isinstance(raw.get('last_success'), (int, float)) else 0,
            'last_fingerprint': raw.get('last_fingerprint') if isinstance(raw.get('last_fingerprint'), str) else '',
            'last_error_fingerprint': raw.get('last_error_fingerprint') if isinstance(raw.get('last_error_fingerprint'), str) else '',
            'last_status': raw.get('last_status', 'Not connected') if isinstance(raw.get('last_status'), str) else 'Not connected'}


def rclone_binary():
    own = BASE / 'bin' / 'rclone'
    if own.is_file() and os.access(own, os.X_OK):
        return str(own)
    return shutil.which('rclone')


def drive_ready():
    """Never print/record rclone config: it contains OAuth secrets."""
    binary = rclone_binary()
    if not binary:
        return False, 'rclone is not installed. Launch DeckPilot - Connect Drive in Desktop Mode.'
    try:
        result = subprocess.run([binary, 'listremotes'], capture_output=True,
                                text=True, timeout=15, check=False)
        if result.returncode != 0:
            return False, 'Could not read the Google Drive connection.'
        if CLOUD_REMOTE not in result.stdout.splitlines():
            return False, 'Google Drive not linked. Launch DeckPilot - Connect Drive to connect it.'
        return True, 'Google Drive connection configured (online access not yet tested).'
    except (OSError, subprocess.TimeoutExpired):
        return False, 'Could not start rclone.'


def cloud_fingerprint(report):
    """Stable payload hash; creation timestamp cannot trigger repeat uploads."""
    stable = {k: v for k, v in report.items() if k not in ('created_utc', 'notes')}
    return sha(json.dumps(stable, ensure_ascii=False, sort_keys=True))


def cloud_status():
    cfg = cloud_config()
    ready, message = drive_ready()
    return {'enabled': cfg['enabled'], 'ready': ready, 'connection': message,
            'folder': CLOUD_FOLDER, 'file': CLOUD_FILENAME,
            'last_success_utc': (dt.datetime.fromtimestamp(cfg['last_success'], dt.timezone.utc).isoformat()
                                 if cfg['last_success'] else None),
            'last_status': cfg['last_status'][:180]}


def cloud_enable(enabled):
    enabled = enabled is True
    if enabled:
        ready, reason = drive_ready()
        if not ready:
            raise ValueError(reason)
    cfg = cloud_config()
    cfg['enabled'] = enabled
    cfg['last_status'] = 'Cloud uploads enabled' if enabled else 'Cloud uploads disabled'
    atomic_json(CLOUD, cfg)
    return cfg['last_status']


def upload_cloud_report(force=False, report=None):
    """Only writes a ZIP to ONE fixed, private Drive path. Never deletes remote files.

    Automatic updates are throttled: on new errors at most every 30 minutes,
    otherwise at most daily, and only when enabled. Manual uploads bypass the
    throttle but still require the prior opt-in switch.
    """
    with LOCK:
        cfg = cloud_config()
        if not cfg['enabled']:
            return 'Google Drive uploads are disabled.'
        ready, reason = drive_ready()
        if not ready:
            cfg['last_status'] = reason
            atomic_json(CLOUD, cfg)
            return reason
        report = report if report is not None else diagnostic_report()
        fingerprint = cloud_fingerprint(report)
        error_fingerprint = sha(json.dumps(report.get('errors', []), sort_keys=True))
        now = time.time()
        changed = fingerprint != cfg['last_fingerprint']
        errors_changed = bool(report.get('errors')) and error_fingerprint != cfg['last_error_fingerprint']
        elapsed = now - cfg['last_success']
        if not force and elapsed < (1800 if errors_changed else 86400):
            return 'Drive report is up to date; next check later.'
        if not force and not changed and elapsed < 86400:
            return 'No new changes to upload.'
        binary = rclone_binary()
        REPORTS.mkdir(parents=True, exist_ok=True)
        path = None
        try:
            with tempfile.NamedTemporaryFile(prefix='deckpilot-cloud-', suffix='.zip', dir=REPORTS,
                                              delete=False) as f:
                path = Path(f.name)
                os.chmod(path, 0o600)
                f.write(make_diagnostic_zip(report))
            dest = CLOUD_REMOTE + CLOUD_FOLDER + '/' + CLOUD_FILENAME
            result = subprocess.run([binary, 'copyto', str(path), dest, '--retries', '1',
                                     '--contimeout', '15s', '--timeout', '45s'],
                                    capture_output=True, text=True, timeout=90, check=False)
            if result.returncode != 0:
                cfg['last_status'] = 'Google Drive upload failed (check your connection and rclone setup).'
                atomic_json(CLOUD, cfg)
                log('CLOUD upload failed')  # no rclone stderr or OAuth tokens in app log
                return cfg['last_status']
            cfg.update(last_success=now, last_fingerprint=fingerprint,
                       last_error_fingerprint=error_fingerprint,
                       last_status='Uploaded latest diagnostic ZIP to your private Drive folder.')
            atomic_json(CLOUD, cfg)
            return cfg['last_status']
        except (OSError, subprocess.TimeoutExpired):
            cfg['last_status'] = 'Google Drive upload failed or timed out.'
            atomic_json(CLOUD, cfg)
            log('CLOUD upload error')
            return cfg['last_status']
        finally:
            if path is not None:
                path.unlink(missing_ok=True)


def mode_hint(mode, metrics):
    if metrics is None:
        return 'No matched benchmark log yet'
    # Indicators, not automatic unvalidated tweaks. 1% lows based on sampled
    # FPS are only approximations when logs are not per-frame.
    target = {'graphics': 30, 'balanced': 40, 'performance': 60}[mode]
    if metrics['avg_fps'] < target * 0.9:
        return 'Measured below the mode target; try a lighter preset if needed'
    if metrics['low_1pct_fps'] < target * 0.6:
        return 'Frame pacing may be uneven; test a demanding game section'
    return 'Measured FPS looks promising; confirm during demanding gameplay'


def update_state():
    """Read a staged Github release or local ZIP. Never install automatically."""
    import updater
    try:
        candidate = updater.candidate_for_install(VERSION)
        result = read_json(BASE / 'updates' / 'result.json', {})
        if not isinstance(result, dict): result = {}
        github = updater.remote_status()
        return {'available': bool(candidate),
                'version': candidate['version'] if candidate else None,
                'archive': candidate['path'].name if candidate else None,
                'status': str(result.get('message', 'No updates installed yet.'))[:220],
                'result': str(result.get('status', 'idle'))[:30],
                'can_undo': (BASE/'updates'/'previous-app'/'deckpilot.py').is_file(),
                'github': {'repository':updater.release_source(),
                           'status':github.get('status','disabled'),
                           'message':github.get('message','Connect a GitHub repository to enable automatic downloads.'),
                           'version':github.get('version'),
                           'checked_at':github.get('checked_at')}}
    except Exception:
        return {'available':False,'version':None,'archive':None,
                'status':'Update check failed.','result':'error','can_undo':False,
                'github':{'repository':'','status':'error','message':'Update status unavailable.'}}


def start_local_update(action='install'):
    """Run updater separately so it survives the service being restarted."""
    import updater
    if action == 'install':
        candidate=updater.candidate_for_install(VERSION)
        if candidate is None:
            return 'No newer update downloaded yet.'
    elif action == 'rollback':
        if not (BASE/'updates'/'previous-app'/'deckpilot.py').is_file():
            return 'No previous version available.'
    else:
        raise ValueError('Unknown update action.')
    runner=shutil.which('systemd-run')
    if not runner: raise ValueError('The SteamOS update helper is unavailable.')
    cmd=[runner,'--user','--collect','--unit=deckpilot-update-'+str(int(time.time())),
         '/usr/bin/python3',str(BASE/'app'/'updater.py'),action]
    if action=='install':cmd.append(str(candidate['path']))
    result=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12,check=False)
    if result.returncode:raise ValueError('Could not start update. Current app is unchanged.')
    return 'Update started. DeckPilot will restart; your settings are preserved.'


def check_github_async():
    import updater
    if not updater.release_source():
        return 'Connect a GitHub repository first.'
    threading.Thread(target=updater.fetch_github_update,kwargs={'installed_version':VERSION},daemon=True).start()
    return 'Checking the GitHub release feed. Refresh in a moment.'


def state_for_ui():
    games = installed_games()
    cfg = config()
    result = []
    for g in games:
        has_adapter = bool(find_ue_configs(g))
        mode = effective_mode(g['appid'], cfg)
        metrics = game_metrics(g)
        result.append({'appid': g['appid'], 'name': g['name'], 'mode': mode,
                       'adapter': 'Unreal Engine config' if has_adapter else 'No supported config found',
                       'supported': has_adapter, 'metrics': metrics, 'hint': mode_hint(mode, metrics)})
    return {'version': VERSION, 'enabled': cfg['enabled'], 'default': cfg['default'], 'games': result, 'count': len(result),
            'supported': sum(1 for g in result if g['supported']),
            'vrr_capability': external_vrr_capability(), 'cloud': cloud_status()}


WEB = r'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>DeckPilot TV</title><style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#0b101a;color:#e9effa}
*{box-sizing:border-box}body{max-width:920px;margin:0 auto;padding:35px 20px 70px}h1{font-size:34px;margin:0 0 5px}
p{color:#aab5c7;line-height:1.5}small{color:#90a0b8}.top{display:flex;justify-content:space-between;gap:15px;align-items:center;flex-wrap:wrap}
.tag{background:#1c3a40;color:#b1ffef;border-radius:40px;padding:8px 13px;font-weight:700}.box{background:#151e2b;border:1px solid #344257;border-radius:17px;padding:22px;margin:22px 0}
.modes{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:14px}button{border:1px solid #405068;background:#222f41;color:#e9effa;padding:12px 7px;border-radius:11px;cursor:pointer;font:inherit}
button:hover{border-color:#80caff}button.active{background:#087b88;color:white;border-color:#5ffff0;font-weight:750}
input{width:100%;border:1px solid #41516b;border-radius:10px;background:#0d1622;color:#fff;padding:12px;font:inherit}
.game{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:13px 0;border-bottom:1px solid #2b384c}
.game:last-child{border:none}.game-title{font-weight:700}.game-status{font-size:12px;color:#90a0b8;margin-top:4px}
.game .modes{min-width:390px;margin:0}.game .modes button{font-size:12px;padding:9px 6px}
.notice{padding:14px;border:1px solid #435469;border-radius:11px;background:#101927;color:#d1e4fa}
#feedback{min-height:24px;margin-top:11px;color:#9ee2c7}
@media(max-width:700px){.game{display:block}.game .modes{min-width:0;margin-top:10px}.modes{gap:5px}button{padding:10px 4px;font-size:12px}}
</style></head><body>
<div class="top"><div><h1>DeckPilot <span style="color:#5fe9de">TV</span></h1><p>Steam Deck OLED · Official Dock · 4K / 120Hz VRR TV</p></div><span class="tag">v0.6 · Online update ready</span></div>
<div class="box"><h2>Default optimisation</h2><p>Choose one mode. New or unconfigured games inherit it automatically.</p>
<div id="defaults" class="modes"></div><div id="feedback" role="status"></div></div>
<div class="notice" style="margin-bottom:13px"><b>VRR / FreeSync:</b> <span id="vrr">Checking connected output…</span><br><small>This is a read-only capability check, not an enabled/disabled switch. SteamOS controls VRR; DeckPilot does not change display or TV settings.</small></div>
<div class="notice"><b>Safe first version:</b> applies conservative graphics and resolution presets only to detected Unreal Engine configuration files. Other games are identified but not modified. It does not change SteamOS display, FPS limits, TDP or Steam launch options. Original config files are backed up before edits. If a compatible MangoHud CSV already exists, DeckPilot reports recorded FPS, but it does not silently change your Steam overlay or claim to benchmark every game.</div>
<div class="box"><div class="top"><div><h2 style="margin:0">Installed Steam games</h2><p id="count">Scanning library…</p></div><button onclick="refresh()">Rescan</button></div>
<input id="search" placeholder="Find a game…" oninput="drawGames()" aria-label="Find installed game"/><div id="games"></div></div>
<div class="box"><div class="top"><div><h2 style="margin:0">Updates</h2><p id="update-status">Checking for a newer version…</p></div><button id="install-update" onclick="installUpdate()" disabled>No update yet</button></div><p id="github-status">GitHub releases: not connected.</p><input id="github-repo" placeholder="GitHub repository: owner/name" aria-label="GitHub release repository"/><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px"><button onclick="connectGithub()">Connect GitHub</button><button onclick="checkGithub()">Check online</button><button onclick="disconnectGithub()">Disconnect</button><button id="undo-update" onclick="undoUpdate()" style="display:none">Undo last update</button></div><small>After connecting a public GitHub releases repository, DeckPilot checks and downloads verified ZIPs in the background. You choose when to install. Until a repository is published, the existing Downloads ZIP method still works. GitHub digest and HTTPS checks provide integrity but are not a separate developer signature.</small></div>
<details class="box"><summary style="cursor:pointer;font-weight:700">Safety and restore</summary><p>DeckPilot keeps original copies before editing supported settings. Close your games before restoring. Files changed by a game after DeckPilot's edits will be left alone.</p><button onclick="restoreAll()">Restore all DeckPilot changes</button></details>
<details class="box"><summary style="cursor:pointer;font-weight:700">Diagnostics and private Google Drive</summary><p>Optional: keep ONE constantly updated <b>DeckPilot-Latest.zip</b> in your private <b>DeckPilot Diagnostics</b> folder. No paid ChatGPT API. Reports include redacted app logs only, but redaction is best-effort. Review a local export before opting in. Connect Google Drive once using the <b>DeckPilot - Connect Drive</b> shortcut in the Desktop Mode application launcher. Nothing is uploaded until you enable it below.</p><p id="cloud-status">Checking connection…</p><button onclick="exportReport()">Export diagnostic ZIP</button> <button onclick="toggleCloud(true)">Enable Drive uploads</button> <button onclick="toggleCloud(false)">Disable Drive uploads</button> <button onclick="uploadNow()">Upload latest now</button><p id="export-status"></p></details>
<p><small>DeckPilot never needs root access or your Steam password. MangoHud logs are optional and are only read when they can be reliably matched to a game. It cannot optimise games whose graphics settings are stored in unsupported formats. Changes to a game may not take effect until it is relaunched. To restore backups, run the included Restore shortcut or command.</small></p>
<script>
let info={default:'balanced',games:[]};const choices=[['graphics','Best Graphics'],['performance','Best Performance'],['balanced','Balanced']];
const token='__TOKEN__';
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function buttons(mode,appid){return choices.map(([v,name])=>`<button class="${v===mode?'active':''}" onclick="setMode('${v}',${appid?`'${appid}'`:'null'})">${name}</button>`).join('');}
function drawGames(){let q=document.getElementById('search').value.toLowerCase();let items=info.games.filter(g=>g.name.toLowerCase().includes(q));document.getElementById('games').innerHTML=items.map(g=>`<div class="game"><div><div class="game-title">${esc(g.name)}</div><div class="game-status">${g.supported?'✓ Supported graphics config found':'• Game detected — no supported settings file'}${g.metrics?` · ${g.metrics.avg_fps} FPS avg / ${g.metrics.low_1pct_fps} sampled 1% low`:''}</div></div><div class="modes">${buttons(g.mode,g.appid)}</div></div>`).join('')||'<p>No matching installed games found.</p>'}
function draw(){const vrrLabels={'available':'Advertised as supported by the connected display','not-advertised':'Not advertised through the current output','unknown':'Could not be verified (check SteamOS Display settings)'};document.getElementById('vrr').innerText=vrrLabels[info.vrr_capability]||vrrLabels.unknown;document.getElementById('defaults').innerHTML=buttons(info.enabled?info.default:'',null);if(!info.enabled)document.getElementById('feedback').innerText='Select a mode to enable automatic optimisation.';document.getElementById('count').innerText=`${info.count} games detected · ${info.supported} with supported settings`;const c=info.cloud||{};document.getElementById('cloud-status').innerText=(c.enabled?'Uploads ON · ':'Uploads OFF · ')+(c.connection||'')+(c.last_success_utc?' · Last upload '+new Date(c.last_success_utc).toLocaleString():'')+' · '+(c.last_status||'');drawGames();}
async function refresh(){try{let r=await fetch('/api/state');if(!r.ok)throw Error('Server error');info=await r.json();draw();}catch(e){document.getElementById('feedback').innerText='Could not connect: '+e.message;}}
async function setMode(mode,appid){try{let r=await fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({mode,appid})});let j=await r.json();if(!r.ok)throw Error(j.error||'Unknown error');document.getElementById('feedback').innerText=j.message;await refresh();}catch(e){document.getElementById('feedback').innerText=e.message;}}
async function exportReport(){try{const r=await fetch('/api/diagnostics',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:'{}'});if(!r.ok)throw Error('Export failed');const b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download='DeckPilot-Diagnostics.zip';a.click();setTimeout(()=>URL.revokeObjectURL(u),30000);document.getElementById('export-status').innerText='Report generated locally. Review it before sharing.';}catch(e){document.getElementById('export-status').innerText=e.message;}}
async function cloudAction(action){try{let r=await fetch('/api/cloud',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({action})});let j=await r.json();document.getElementById('export-status').innerText=j.message||j.error||'No response';await refresh();}catch(e){document.getElementById('export-status').innerText=e.message;}}
async function checkUpdate(){try{const r=await fetch('/api/update');const j=await r.json();const b=document.getElementById('install-update');const t=document.getElementById('update-status');const undo=document.getElementById('undo-update');undo.style.display=j.can_undo?'inline-block':'none';if(j.available){b.disabled=false;b.textContent='Install v'+j.version;t.textContent='Update available: '+j.archive;}else{b.disabled=true;b.textContent='Up to date';t.textContent='v'+(info.version||'')+' installed · '+(j.status||'No newer update.')}const gh=j.github||{};document.getElementById('github-status').textContent=gh.repository?('GitHub: '+gh.repository+' · '+(gh.message||gh.status)):'GitHub releases not connected yet.';if(gh.repository&&!document.getElementById('github-repo').value)document.getElementById('github-repo').value=gh.repository;}catch(e){document.getElementById('update-status').textContent='Update check failed: '+e.message;}}
async function githubAction(action,repository){try{let r=await fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({action,repository})});let j=await r.json();if(!r.ok)throw Error(j.error||'GitHub action failed');document.getElementById('update-status').textContent=j.message;await checkUpdate();}catch(e){document.getElementById('update-status').textContent=e.message;}}
function connectGithub(){const r=document.getElementById('github-repo').value.trim();if(!r)return alert('Enter the real public GitHub repository first.');if(!confirm('Trust public releases from '+r+' for update downloads? Installation will still require your approval.'))return;githubAction('connect',r);}
function disconnectGithub(){if(confirm('Stop checking GitHub for updates?'))githubAction('disconnect','');}
function checkGithub(){githubAction('check','');}
async function undoUpdate(){if(!confirm('Restore the previous DeckPilot version? This restarts the app but preserves game profiles and backups.'))return;await updateAction('rollback');}
async function updateAction(action){try{let r=await fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({action})});let j=await r.json();if(!r.ok)throw Error(j.error||'Could not start installer');document.getElementById('update-status').textContent=j.message;setTimeout(()=>location.reload(),9000);}catch(e){document.getElementById('update-status').textContent='Could not start: '+e.message;document.getElementById('install-update').disabled=false;}}
async function installUpdate(){if(!confirm('Install this DeckPilot update? The app will restart, and the previous version will be saved for rollback.'))return;const b=document.getElementById('install-update');b.disabled=true;await updateAction('install');}
function toggleCloud(enabled){if(enabled&&!confirm('Send a redacted diagnostic ZIP to your private Google Drive automatically? Review an exported report first.'))return;cloudAction(enabled?'enable':'disable');}
function uploadNow(){cloudAction('upload');}
async function restoreAll(){if(!confirm('Restore backed-up game settings? Please close all games first.'))return;try{let r=await fetch('/api/restore',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:'{}'});let j=await r.json();if(!r.ok)throw Error(j.error||'Restore failed');alert(j.message);await refresh();}catch(e){alert('Restore failed: '+e.message)}}
refresh().then(checkUpdate);
</script></body></html>'''


def synchronize():
    cfg = config()
    if not cfg['enabled']:
        return
    for g in installed_games():
        if find_ue_configs(g):
            apply_profile(g, effective_mode(g['appid'], cfg))


class Handler(BaseHTTPRequestHandler):
    token = ''

    def valid_host(self):
        return self.headers.get('Host', '') in ('127.0.0.1:38647', 'localhost:38647')

    def do_GET(self):
        if not self.valid_host(): self.send_error(403); return
        route = urllib.parse.urlparse(self.path).path
        if route == '/api/state':
            self.send_json(state_for_ui()); return
        if route == '/api/update':
            self.send_json(update_state()); return
        if route == '/':
            body = WEB.replace('__TOKEN__', self.token).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_error(404)

    def do_POST(self):
        if not self.valid_host(): self.send_error(403); return
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://127.0.0.1:38647', 'http://localhost:38647'):
            self.send_error(403); return
        if self.path not in ('/api/mode', '/api/restore', '/api/diagnostics', '/api/cloud', '/api/update'): self.send_error(404); return
        if self.headers.get('X-DeckPilot-Token') != self.token:
            self.send_json({'error': 'Invalid session token'}, 403); return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.send_json({'error': 'JSON expected'}, 415); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 1024: raise ValueError('Invalid message length')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict): raise ValueError('JSON object required')
            if self.path == '/api/diagnostics':
                with LOCK:
                    data = make_diagnostic_zip()
                self.send_response(200); self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename=DeckPilot-Diagnostics.zip')
                self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data); return
            if self.path == '/api/update':
                action=payload.get('action')
                if action in ('install','rollback'):
                    self.send_json({'message':start_local_update(action)});return
                if action == 'check':
                    self.send_json({'message':check_github_async()});return
                if action in ('connect','disconnect'):
                    import updater
                    repo=payload.get('repository','') if action=='connect' else ''
                    self.send_json({'message':'GitHub release source '+('connected: '+repo if repo else 'disconnected.'),
                                    'repository':updater.configure_source(repo)});return
                raise ValueError('Unknown update command')
            if self.path == '/api/cloud':
                action = payload.get('action')
                if action == 'enable':
                    self.send_json({'message': cloud_enable(True)}); return
                if action == 'disable':
                    self.send_json({'message': cloud_enable(False)}); return
                if action == 'upload':
                    self.send_json({'message': upload_cloud_report(force=True)}); return
                raise ValueError('Unknown cloud command')
            if self.path == '/api/restore':
                with LOCK:
                    results = [restore_game(g['appid']) for g in installed_games()]
                self.send_json({'ok': True, 'message': 'Restoration checked for ' + str(len(results)) + ' games. Original files were restored only where it was safe. Check the DeckPilot log for skipped files.'})
                return
            mode = payload['mode']
            appid = payload.get('appid')
            if mode not in MODES: raise ValueError('Unknown optimisation mode')
            if appid is not None and (not isinstance(appid, str) or not appid.isdigit()):
                raise ValueError('Invalid game identifier')
            with LOCK:
                games = installed_games()
                cfg = config()
                if appid is None:
                    cfg['enabled'] = True
                    cfg['default'] = mode
                    cfg['games'] = {}  # global choice resets prior per-game overrides
                    atomic_json(CONFIG, cfg)
                    msg = 'Default changed. Supported games will be updated automatically.'
                else:
                    target = next((g for g in games if g['appid'] == appid), None)
                    if target is None: raise ValueError('Game was not found in installed library')
                    cfg['enabled'] = True
                    cfg['games'][appid] = mode
                    atomic_json(CONFIG, cfg)
                    result = apply_profile(target, mode, force=True)
                    msg = target['name'] + ': ' + (('settings updated (' + str(result['count']) + ' file)' if result['count'] == 1 else 'settings updated (' + str(result['count']) + ' files)') if result['count'] else ('not modified: supported config not found' if result['status'] == 'unsupported' else ('game appears to be running; try after closing it' if result['status'] == 'running' else ('manual/game edits detected; not overwritten automatically' if result['status'] == 'manual-changes' else 'settings already match'))))
            self.send_json({'ok': True, 'message': msg})
        except (ValueError, KeyError, json.JSONDecodeError) as ex:
            self.send_json({'error': str(ex)}, 400)

    def send_json(self, obj, status=200):
        data = json.dumps(obj).encode('utf-8'); self.send_response(status)
        self.send_header('Content-Type', 'application/json'); self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, fmt, *args):
        return  # No user-library data to system journal.


def run_server():
    mkdir()
    import secrets
    Handler.token = secrets.token_urlsafe(30)
    def sync_loop():
        while True:
            with LOCK:
                try: synchronize()
                except Exception as ex: log('SYNC ERROR ' + repr(ex))
            time.sleep(45)
    threading.Thread(target=sync_loop, daemon=True).start()
    def github_loop():
        # Network lookups only for public repositories the user opted into.
        while True:
            try:
                import updater
                if updater.release_source():
                    updater.fetch_github_update(installed_version=VERSION)
            except Exception:
                log('GitHub update check error')
            time.sleep(21600)
    threading.Thread(target=github_loop,daemon=True).start()
    def cloud_loop():
        # Never attempts upload before a user enables the Drive sync explicitly.
        while True:
            try:
                if cloud_config()['enabled']:
                    upload_cloud_report()
            except Exception:
                log('CLOUD unexpected sync error')
            time.sleep(600)
    threading.Thread(target=cloud_loop, daemon=True).start()
    with ThreadingHTTPServer(('127.0.0.1', PORT), Handler) as server:
        log('START DeckPilot TV v' + VERSION + ' listening on localhost')
        server.serve_forever(poll_interval=0.3)


def main():
    parser = argparse.ArgumentParser(description='DeckPilot TV: Steam Deck OLED docked game optimiser')
    parser.add_argument('command', choices=['serve', 'scan', 'apply', 'restore', 'status', 'diagnose', 'export', 'cloud-status', 'cloud-upload', 'cloud-enable', 'cloud-disable', 'update-status', 'set-mode', 'plugin-state', 'check-github', 'install-update', 'rollback-update'])
    parser.add_argument('appid', nargs='?')
    parser.add_argument('--mode', choices=sorted(MODES))
    args = parser.parse_args()
    if args.command == 'serve': run_server(); return
    if args.command == 'plugin-state':
        ui=state_for_ui()
        ui['update']=update_state()
        print(json.dumps(ui,ensure_ascii=False));return
    if args.command == 'install-update':
        print(start_local_update('install'));return
    if args.command == 'rollback-update':
        print(start_local_update('rollback'));return
    if args.command == 'check-github':
        import updater
        print(json.dumps(updater.fetch_github_update(installed_version=VERSION)));return
    if args.command == 'set-mode':
        if not args.mode: parser.error('--mode is required')
        with LOCK:
            cfg=config()
            if args.appid:
                target=next((g for g in installed_games() if g['appid']==args.appid),None)
                if target is None:parser.error('Installed Steam game not found')
                cfg['games'][args.appid]=args.mode
                cfg['enabled']=True
                atomic_json(CONFIG,cfg)
                result=apply_profile(target,args.mode,force=True)
                print(json.dumps({'ok':True,'game':target['name'],'mode':args.mode,'result':result}))
            else:
                cfg['default']=args.mode;cfg['enabled']=True
                cfg['games']={}
                atomic_json(CONFIG,cfg)
                print(json.dumps({'ok':True,'default':args.mode}))
        return
    if args.command == 'export':
        print('Saved local diagnostic ZIP:', save_diagnostic_zip()); return
    if args.command == 'update-status':
        print(json.dumps(update_state(), indent=2)); return
    if args.command == 'cloud-status':
        print(json.dumps(cloud_status(), indent=2)); return
    if args.command == 'cloud-enable':
        try: print(cloud_enable(True))
        except ValueError as e: print(e, file=sys.stderr); sys.exit(2)
        return
    if args.command == 'cloud-disable':
        print(cloud_enable(False)); return
    if args.command == 'cloud-upload':
        print(upload_cloud_report(force=True)); return
    if args.command == 'diagnose':
        print(json.dumps({'version': VERSION, 'steam_libraries': [str(p) for p in library_paths()],
                          'installed_games': len(installed_games()),
                          'vrr_capability': external_vrr_capability(),
                          'mangohud_log_folders': [str(p) for p in metrics_roots() if p.is_dir()],
                          'enabled': config()['enabled']}, indent=2)); return
    if args.command in ('scan', 'status'):
        print(json.dumps(state_for_ui(), indent=2, ensure_ascii=False)); return
    games = installed_games()
    selected = [g for g in games if args.appid is None or g['appid'] == args.appid]
    if args.appid and not selected:
        print('Game not found:', args.appid, file=sys.stderr); sys.exit(2)
    if args.command == 'apply':
        for g in selected:
            print(g['name'], apply_profile(g, effective_mode(g['appid'])))
    elif args.command == 'restore':
        for g in selected:
            print(g['name'], restore_game(g['appid']))

if __name__ == '__main__':
    main()
