#!/usr/bin/env python3
"""DeckPilot TV 0.8: cautious Steam Deck game preset synchronizer.

Only edits allowlisted existing Unreal Engine config files in Steam Proton
prefixes and native Valheim resolution preferences after preview approval. Does not touch Steam client settings or display mode.
"""
from __future__ import annotations
import argparse
import updater
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

VERSION = '0.8.3'
BUILD_ID = '0.8.3-preview.1'
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.', delete=False) as f:
        temp = Path(f.name)
        try:
            f.write((json.dumps(value, indent=2, ensure_ascii=False)+'\n').encode('utf-8'))
            f.flush()
            os.fsync(f.fileno())
            temp.replace(path)
        finally: temp.unlink(missing_ok=True)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


from functools import wraps
import fcntl
TRANSACTION_LOCAL = threading.local()


def game_transaction(fn):
    @wraps(fn)
    def guarded(*args, **kwargs):
        with LOCK:
            if getattr(TRANSACTION_LOCAL, 'active', False): return fn(*args, **kwargs)
            mkdir()
            with (BASE / 'settings.lock').open('a') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                TRANSACTION_LOCAL.active = True
                try: return fn(*args, **kwargs)
                finally:
                    TRANSACTION_LOCAL.active = False
                    fcntl.flock(handle, fcntl.LOCK_UN)
    return guarded


CONTEXTS = {'docked', 'handheld'}
HANDHELD_PRESETS = {
    'graphics': {'x': 1280, 'y': 800, 'quality': 3, 'resolution_scale': 100},
    'balanced': {'x': 1280, 'y': 800, 'quality': 2, 'resolution_scale': 100},
    'performance': {'x': 1152, 'y': 720, 'quality': 1, 'resolution_scale': 100},
}


def profile_context(context=None, cfg=None):
    context = context if context is not None else (cfg or config()).get('context', 'docked')
    if not isinstance(context, str) or context not in CONTEXTS:
        raise ValueError('Choose Docked or Handheld.')
    return context


def clean_modes(value):
    if not isinstance(value, dict): return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and k.isascii()
            and k.isdigit() and isinstance(v, str) and v in MODES}


def config():
    obj = read_json(CONFIG, {})
    if not isinstance(obj, dict): obj = {}
    default = obj.get('default') if isinstance(obj.get('default'), str) and obj['default'] in MODES else DEFAULT_MODE
    legacy = {'default': default, 'games': clean_modes(obj.get('games'))}
    shadow = read_json(BASE/'profiles-v2.json', {})
    if not isinstance(shadow, dict): shadow = {}
    recovering = 'profiles' not in obj and isinstance(shadow.get('profiles'), dict)
    profiles = {}
    raw_profiles = shadow['profiles'] if recovering else obj.get('profiles', {})
    for context in sorted(CONTEXTS):
        raw = raw_profiles.get(context, {}) if isinstance(raw_profiles, dict) else {}
        if not isinstance(raw, dict): raw = {}
        mode = raw.get('default', default)
        profiles[context] = {'default': mode if isinstance(mode, str) and mode in MODES else default,
                             'games': clean_modes(raw.get('games', legacy['games']))}
    context = obj.get('context', shadow.get('context', 'docked') if recovering else 'docked')
    if not isinstance(context, str) or context not in CONTEXTS: context = 'docked'
    if recovering and ('default' in obj or 'games' in obj):
        profiles[context] = legacy
    approved_context = obj.get('approved_context', {})
    return {'enabled': obj.get('enabled') is True, 'context': context, 'profiles': profiles,
            # Retain legacy aliases so an app rollback can still read current preferences.
            'default': profiles[context]['default'], 'games': dict(profiles[context]['games']),
            'measurements_enabled': obj.get('measurements_enabled', shadow.get('measurements_enabled', False) if recovering else False) is True,
            'launch_prompts': False,  # native Steam Play remains completely unhooked
            'play_assistant_enabled': obj.get('play_assistant_enabled', shadow.get('play_assistant_enabled', False) if recovering else False) is True,
            'launch_dismissed': [k for k in obj.get('launch_dismissed', shadow.get('launch_dismissed', []) if recovering else []) if isinstance(k,str) and k.isascii() and k.isdigit() and len(k)<=10 and 0 < int(k) <= 4294967295] if isinstance(obj.get('launch_dismissed', shadow.get('launch_dismissed', []) if recovering else []), list) else [],
            'approved_files': {str(k): [p for p in paths if isinstance(p, str)][:40] for k, paths in obj.get('approved_files', {}).items() if isinstance(paths, list)} if isinstance(obj.get('approved_files'), dict) else {},
            'approved_context': {k: v for k, v in approved_context.items() if isinstance(v, str) and v in CONTEXTS} if isinstance(approved_context, dict) else {},
            'approved': clean_modes(obj.get('approved'))}


def effective_mode(appid, cfg=None, context=None):
    cfg = cfg or config()
    context = profile_context(context, cfg)
    profile = cfg.get('profiles', {}).get(context, cfg)
    return profile['games'].get(str(appid), profile['default'])


def write_config(cfg):
    active = cfg['profiles'][cfg['context']]
    cfg['default'], cfg['games'] = active['default'], dict(active['games'])
    # Keep inactive choices recoverable when a rollback writes the legacy schema.
    atomic_json(BASE/'profiles-v2.json', {'context':cfg['context'], 'profiles':cfg['profiles'], 'measurements_enabled':cfg['measurements_enabled'],
                                         'play_assistant_enabled':cfg['play_assistant_enabled'], 'launch_dismissed':cfg['launch_dismissed']})
    atomic_json(CONFIG, cfg)


@game_transaction
def set_context(context):
    context = profile_context(context)
    cfg = config()
    if cfg['context'] != context:
        cfg['context'] = context
        # Selecting a profile must never start changing files behind the UI.
        cfg['approved'], cfg['approved_files'], cfg['approved_context'] = {}, {}, {}
        write_config(cfg)
    return {'ok': True, 'message': context.title() + ' profile selected. Preview before applying.'}


@game_transaction
def set_measurements(enabled):
    if not isinstance(enabled, bool): raise ValueError('Expected an on/off choice.')
    cfg = config(); cfg['measurements_enabled'] = enabled; write_config(cfg)
    return {'ok': True, 'message': 'Existing FPS logs ' + ('enabled.' if enabled else 'disabled.')}


# Public research is deliberately data-only. None of this text reaches adapters.
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser
from concurrent.futures import ThreadPoolExecutor, wait

RESEARCH_AGENT = 'DeckPilot/0.8.2 (+public game-settings research)'
RESEARCH_HOSTS = {'store.steampowered.com', 'deckverified.games',
                  'www.sharedeck.games', 'sharedeck.games', 'steamdeckhq.com', 'github.com'}
RESEARCH_LIMIT = 1024 * 1024
RESEARCH_TTL = 6 * 3600
RESEARCH_LOCK = threading.RLock()


def steam_id(value):
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]{0,9}', value) or int(value) > 4294967295:
        raise ValueError('Enter a valid Steam App ID.')
    return value


def public_url(url, hosts=RESEARCH_HOSTS):
    try:
        p = urllib.parse.urlsplit(url)
        return (p.scheme == 'https' and p.hostname in hosts and p.port in (None, 443)
                and p.username is None and p.password is None)
    except ValueError:
        return False


class ResearchRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Stay on the same source (www/apex ShareDeck are the same publisher).
        old = urllib.parse.urlsplit(req.full_url).hostname
        new = urllib.parse.urlsplit(newurl).hostname
        if not public_url(newurl) or old.removeprefix('www.') != new.removeprefix('www.'):
            raise ValueError('Source redirected outside its public host.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_get(url, deadline):
    if not public_url(url, RESEARCH_HOSTS - {'github.com'}):
        raise ValueError('Unapproved public source.')
    request = urllib.request.Request(url, headers={'User-Agent': RESEARCH_AGENT,
                                                  'Accept': 'application/json, text/html, text/plain'})
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Source deadline exceeded.')
    with urllib.request.build_opener(ResearchRedirects()).open(request, timeout=min(2, remaining)) as response:
        if int(response.headers.get('Content-Length', '0')) > RESEARCH_LIMIT:
            raise ValueError('Source response exceeds size limit.')
        parts, size = [], 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('Source deadline exceeded.')
            chunk = response.read(16384)
            if not chunk:
                break
            size += len(chunk)
            if size > RESEARCH_LIMIT:
                raise ValueError('Source response exceeds size limit.')
            parts.append(chunk)
        return b''.join(parts).decode('utf-8')


from contextlib import contextmanager


@contextmanager
def research_guard():
    with RESEARCH_LOCK:
        mkdir()
        with (BASE/'research.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(handle, fcntl.LOCK_UN)


def research_cached(key, loader, ttl=RESEARCH_TTL, allow_stale=False):
    """Bounded private cache. Retain verified reports for offline use up to 30 days."""
    path = BASE / 'research-cache.json'
    with research_guard():
        cache = read_json(path, {})
        item = cache.get(key, {}) if isinstance(cache, dict) else {}
        age = time.time() - item.get('at', 0) if isinstance(item, dict) and isinstance(item.get('at'), (int, float)) else float('inf')
        if not isinstance(item, dict): item = {}
        old = item.get('value')
        valid = isinstance(old, (dict, list)) and 0 <= age <= 30*86400
        short_failure = isinstance(old, dict) and (old.get('status') == 'unavailable' or old.get('blocked'))
        if 'value' in item and 0 <= age < (min(ttl, 300) if short_failure else ttl):
            if allow_stale and isinstance(old, dict): return {**old, 'cached': True, 'cache_age_s': round(age)}
            return old
    def fallback():
        if isinstance(old, dict): return {**old, 'cached': True, 'stale': True, 'cache_age_s': round(age)}
        return old
    try: result = loader()
    except (OSError, ValueError):
        if allow_stale and valid and not short_failure: return fallback()
        raise
    if allow_stale and valid and not short_failure and isinstance(result, dict) and result.get('status') == 'unavailable':
        return fallback()
    with research_guard():
        cache = read_json(path, {})
        if not isinstance(cache, dict): cache = {}
        cache[key] = {'at': time.time(), 'value': result}
        cache = {k:v for k,v in cache.items() if isinstance(v, dict) and isinstance(v.get('at'), (int,float))}
        cache = dict(sorted(cache.items(), key=lambda kv: kv[1]['at'])[-64:])
        atomic_json(path, cache)
    return result


def permitted_get(url, deadline):
    parsed = urllib.parse.urlsplit(url)
    root = 'https://' + parsed.netloc
    def robots():
        try:
            return {'text': public_get(root + '/robots.txt', deadline)}
        except urllib.error.HTTPError as exc:
            if exc.code == 404: return {'text': ''}
            return {'blocked': True}
        except (OSError, ValueError):
            return {'blocked': True}
    rules = research_cached('robots:' + root, robots, 3600)
    if rules.get('blocked'):
        raise ValueError('Public access policy could not be verified.')
    parser = RobotFileParser()
    parser.parse(rules['text'].splitlines())
    if not parser.can_fetch('DeckPilot', url):
        raise ValueError('Source does not permit automated access to this page.')
    return public_get(url, deadline)


def clean_text(value, limit=1200):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


class PublicDocument(HTMLParser):
    """Extract visible text, links and structured data; never execute scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.structured = [], [], []
        self.hidden = 0
        self.json_script = False
        self.script_text = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.hidden += 1
            self.json_script = tag == 'script' and attrs.get('type') in ('application/ld+json', 'application/json')
            self.script_text = ''
        if tag == 'a' and attrs.get('href'): self.links.append(attrs['href'])

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            if self.json_script:
                try: self.structured.append(json.loads(self.script_text))
                except (ValueError, RecursionError): pass
            self.hidden = max(0, self.hidden - 1)
            self.json_script = False
        if not self.hidden: self.text.append(' ')

    def handle_data(self, data):
        if self.json_script: self.script_text += data
        elif not self.hidden: self.text.append(data)


def document(raw):
    parser = PublicDocument(); parser.feed(raw)
    return parser


def steam_links(links):
    ids = set()
    for link in links:
        p = urllib.parse.urlsplit(link)
        if p.scheme == 'https' and p.hostname == 'store.steampowered.com':
            m = re.match(r'^/app/([1-9][0-9]*)(?:/|$)', p.path)
            if m: ids.add(m.group(1))
    return ids


def steam_game(appid):
    appid = steam_id(appid)
    def load():
        deadline = time.monotonic() + 6
        data = json.loads(public_get('https://store.steampowered.com/api/appdetails?appids=' + appid + '&l=english', deadline))
        if not isinstance(data, dict): raise ValueError('Invalid Steam response.')
        entry = data.get(appid, {})
        if not isinstance(entry, dict): raise ValueError('Invalid Steam game.')
        item = entry.get('data', {})
        if not isinstance(item, dict): raise ValueError('Invalid Steam game details.')
        if entry.get('success') is not True or str(item.get('steam_appid')) != appid or item.get('type') != 'game':
            raise ValueError('Steam did not verify this App ID as a game.')
        return {'appid': appid, 'name': clean_text(item.get('name'), 200), 'verified': True}
    return research_cached('steam:' + appid, load, allow_stale=True)


def search_steam(query):
    query = clean_text(query, 120)
    if not query: return {'ok': True, 'games': []}
    try:
        if query.isdigit():
            return {'ok': True, 'games': [steam_game(query)]}
        def load():
            url = 'https://store.steampowered.com/api/storesearch/?' + urllib.parse.urlencode({'term': query, 'l': 'english', 'cc': 'GB'})
            payload = json.loads(public_get(url, time.monotonic() + 6))
            if not isinstance(payload, dict) or not isinstance(payload.get('items'), list): raise ValueError('Invalid Steam search results.')
            result = []
            for item in payload['items'][:20]:
                if not isinstance(item, dict) or item.get('type') not in (None, 'app', 'game'): continue
                try: appid = steam_id(item['id'])
                except (ValueError, KeyError): continue
                result.append({'appid': appid, 'name': clean_text(item.get('name'), 200),
                               'verified': False})  # appdetails is checked on selection, never by name alone
            return result
        return {'ok': True, 'games': research_cached('search:' + query.casefold(), load, allow_stale=True)}
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return {'ok': False, 'games': [], 'error': 'Steam search unavailable or invalid response. Try again later; installed games and saved preferences still work.'}


def report_record(source, appid, url, text, date=None, fields=None):
    """Return only attributable data. No settings or instructions are executable."""
    text = clean_text(text)
    fields = fields or {}
    def labelled(pattern):
        m = re.search(pattern, text, re.I)
        return clean_text(m.group(1), 80) if m else None
    device = clean_text(fields.get('device'), 80) or labelled(r'\b(Steam Deck OLED|Steam Deck LCD|Steam Deck)\b')
    context = clean_text(fields.get('display_context'), 80) or ('docked' if re.search(r'\bdocked\b', text, re.I) and not re.search(r'\bhandheld\b', text, re.I) else 'handheld' if re.search(r'\bhandheld\b', text, re.I) and not re.search(r'\bdocked\b', text, re.I) else 'unknown')
    return {'source': source, 'appid': appid, 'url': url,
            'retrieved_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'report_date': clean_text(date, 80) or None,
            'game_version': clean_text(fields.get('game_version'), 80) or labelled(r'game version\s*[:=]\s*([\w.\-]+)'),
            'device': device or 'unknown', 'display_context': context,
            'resolution': clean_text(fields.get('resolution'), 80) or labelled(r'\b(\d{3,4}\s*[x×]\s*\d{3,4})\b'),
            'fps': clean_text(fields.get('fps'), 80) or labelled(r'\b(\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*FPS)\b'),
            'summary': text,
            'uncertainty': 'Community report, not a DeckPilot benchmark. ' + ('Handheld-only evidence; TV performance is unverified.' if context == 'handheld' else 'Dock/TV configuration and achieved performance are not independently verified.')}


def normalize_public_source(payload, source, appid, url):
    """Adapt documented public schemas without trusting server-side search filtering.

    Schema provenance is recorded in docs/RESEARCH.md. External reviews returned
    by Deck Verified are deliberately excluded so publishers stay independent.
    """
    result = []
    def emit(fields, link, text, date, report_id=None):
        if not public_url(link): return
        record = report_record(source, appid, link, text, date, fields)
        record['report_id'] = clean_text(report_id, 80) or None
        record['fps_kind'] = fields.get('fps_kind', 'reported/unspecified')
        result.append(record)
    if source == 'Deck Settings / deckverified.games' and isinstance(payload, dict) and 'reports' in payload:
        if str(payload.get('appId')) != appid: return []
        for entry in payload.get('reports', [])[:20]:
            if not isinstance(entry, dict) or not isinstance(entry.get('data'), dict): continue
            data = entry['data']
            if str(data.get('app_id')) != appid: continue
            link = entry.get('html_url', '')
            # Attributable user report in the publisher's official public reports repo.
            if not re.fullmatch(r'https://github\.com/DeckSettings/game-reports-steamos/issues/[1-9][0-9]*', link):
                link = 'https://deckverified.games/app/' + appid
            fields = {'device': data.get('device'), 'resolution': data.get('game_resolution'),
                      'fps': data.get('target_framerate'), 'fps_kind': 'target, not measured FPS',
                      'game_version': data.get('game_version'), 'display_context': data.get('display_context')}
            text = ' '.join(clean_text(data.get(k), 500) for k in ('summary', 'game_display_settings', 'game_graphics_settings', 'additional_notes'))
            emit(fields, link, text, entry.get('created_at'), entry.get('number'))
        return result
    if source == 'ShareDeck' and isinstance(payload, list):
        for entry in payload[:20]:
            if not isinstance(entry, dict) or str(entry.get('app_id')) != appid: continue
            resolution = None
            if entry.get('resolution_horizontal') and entry.get('resolution_vertical'):
                resolution = str(entry['resolution_horizontal'])+'x'+str(entry['resolution_vertical'])
            fps = entry.get('average_framerate')
            fields = {'device': entry.get('device'), 'game_version': entry.get('app_build_id'),
                      'resolution': resolution, 'fps': str(fps)+' FPS' if fps is not None else None,
                      'fps_kind': 'community reported average, not independently measured',
                      'display_context': entry.get('display_context')}
            emit(fields, 'https://sharedeck.games/apps/'+appid, clean_text(entry.get('note')) or 'Community settings report; missing metadata is unknown.', entry.get('created_at'), entry.get('id'))
        return result
    if source == 'SteamDeckHQ' and isinstance(payload, list):
        for entry in payload[:5]:
            if not isinstance(entry, dict): continue
            acf = entry.get('acf') if isinstance(entry.get('acf'), dict) else {}
            meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
            raw = entry.get('content', {}).get('rendered', '') if isinstance(entry.get('content'), dict) else ''
            content = document(raw)
            # A filtered API URL alone is not proof: validate record fields or a unique Steam URL.
            identity = acf.get('steam_app_id', meta.get('steam_app_id'))
            linked_ids = steam_links(content.links)
            if identity is not None:
                if str(identity) != appid or linked_ids - {appid}: continue
            elif linked_ids != {appid}: continue
            link = entry.get('link', '')
            if not public_url(link, {'steamdeckhq.com'}): continue
            settings = acf.get('optimized_and_recommended_settings', {})
            if not isinstance(settings, dict): settings = {}
            steamos = settings.get('steamos_settings', {})
            if not isinstance(steamos, dict): steamos = {}
            fields = {'fps': steamos.get('fps_cap'), 'fps_kind': 'configured cap/target, not measured FPS'}
            extra = settings.get('game_settings', '')
            text = ''.join(content.text) + ' ' + (''.join(document(extra).text) if isinstance(extra, str) else '')
            emit(fields, link, text, entry.get('date'), entry.get('id'))
        return result
    return None  # generic public HTML/JSON-LD, with strict record-level identity checks


def parse_source_reports(raw, source, appid, url):
    """Accept exact App ID evidence per report; a search result title is insufficient."""
    reports = []
    try: payload = json.loads(raw)
    except ValueError: payload = None
    specialized = normalize_public_source(payload, source, appid, url)
    if specialized is not None: return specialized
    doc = document(raw) if payload is None else None
    roots = [payload] if payload is not None else doc.structured
    def visit(obj, depth=0):
        if depth > 12 or len(reports) >= 20: return
        if isinstance(obj, list):
            for entry in obj[:100]: visit(entry, depth+1)
        elif isinstance(obj, dict):
            # Explicit data records only. Do not inherit a parent's ID into other reports.
            identity = obj.get('steam_app_id', obj.get('steam_appid', obj.get('appid')))
            content = obj.get('content', obj.get('reviewBody', obj.get('description', obj.get('summary', ''))))
            if isinstance(content, dict): content = content.get('rendered', '')
            content = content if isinstance(content, str) else ''
            parsed = document(content)
            ids = steam_links(parsed.links)
            exact = (str(identity) == appid and not (ids - {appid})) if identity is not None else ids == {appid}
            link = obj.get('url', obj.get('link', url))
            link = urllib.parse.urljoin(url, link) if isinstance(link, str) else url
            if exact and content and public_url(link, {urllib.parse.urlsplit(url).hostname}):
                reports.append(report_record(source, appid, link, ''.join(parsed.text),
                                              obj.get('datePublished', obj.get('date')), obj))
                return
            for value in list(obj.values())[:100]:
                if isinstance(value, (dict, list)): visit(value, depth+1)
    for root in roots: visit(root)
    if not reports and doc and steam_links(doc.links) == {appid} and re.search(r'\b(?:FPS|resolution|handheld|docked)\b', ''.join(doc.text), re.I):
        # A verified single-game public page. Unknown metadata stays unknown.
        reports.append(report_record(source, appid, url, ''.join(doc.text)))
    return reports


def source_research(source, url, appid):
    def load():
        try:
            raw = permitted_get(url, time.monotonic() + 8)
            reports = parse_source_reports(raw, source, appid, url)
            return {'source': source, 'url': url, 'status': 'ok' if reports else 'no-verified-reports',
                    'reports': reports, 'message': 'Only exact App ID matches are included.'}
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return {'source': source, 'url': url, 'status': 'unavailable', 'reports': [],
                    'message': 'Source unavailable, denied automated access, timed out, or returned an unsupported format.'}
    # Keep successes for six hours and failures for five minutes.
    result = dict(research_cached(source + ':' + appid, load, RESEARCH_TTL, allow_stale=True))
    result['page_url'] = ('https://deckverified.games/app/' + appid if source.startswith('Deck Settings') else 'https://sharedeck.games/apps/' + appid if source == 'ShareDeck' else 'https://steamdeckhq.com/')
    return result


def research_game(appid, context=None):
    context = profile_context(context)
    try: game = steam_game(appid)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return {'ok': False, 'error': 'Cannot verify this game with Steam. No similarly named game will be substituted.', 'sources': [], 'reports': []}
    appid = game['appid']
    sources = [
        ('Deck Settings / deckverified.games', 'https://deckverified.games/deck-verified/api/v1/game_details?' + urllib.parse.urlencode({'appid': appid, 'include_external': 'false'})),
        ('ShareDeck', 'https://sharedeck.games/api/experimental/reports?' + urllib.parse.urlencode({'app_id': appid})),
        ('SteamDeckHQ', 'https://steamdeckhq.com/wp-json/wp/v2/game-reviews/?' + urllib.parse.urlencode({'meta_key': 'steam_app_id', 'meta_value': appid, 'per_page': 5})),
    ]
    pool = ThreadPoolExecutor(max_workers=3)
    futures = {pool.submit(source_research, source, url, appid): (source, url) for source, url in sources}
    done, pending = wait(futures, timeout=10)
    results = []
    for future, (source, url) in futures.items():
        if future in done:
            try: results.append(future.result())
            except Exception: results.append({'source': source, 'url': url, 'status': 'unavailable', 'reports': []})
        else:
            future.cancel()
            results.append({'source': source, 'url': url, 'status': 'timeout', 'reports': []})
    pool.shutdown(wait=False, cancel_futures=True)
    reports = [{**report, 'stale': result.get('stale', False), 'cached': result.get('cached', False)} for result in results for report in result['reports']]
    reports.sort(key=lambda r: (r['display_context'] == context, not r.get('stale'), 'OLED' in r['device'].upper()), reverse=True)
    return {'ok': True, 'game': game, 'sources': results, 'reports': reports, 'recommendation': evidence_summary(reports, context),
            'message': 'Reports are advisory. Missing data means unknown, not a performance guarantee. Only local allowlisted adapters can apply settings.'}

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


NATIVE_UNITY = {'892970': ('IronGate', 'Valheim'), '367520': ('Team Cherry', 'Hollow Knight')}

def find_valheim_configs(game, home=None):
    """Native Unity PlayerPrefs only; never touch saves or Proton registry."""
    if game['appid'] not in NATIVE_UNITY: return []
    root = (Path(home) if home is not None else Path.home()) / '.config/unity3d'
    path = root.joinpath(*NATIVE_UNITY[game['appid']], 'prefs')
    if not path.is_file() or any(p.is_symlink() for p in [path, *path.parents][:-1]): return []
    try:
        transform_valheim(safe_read_text(path), 'balanced')
    except (OSError, ValueError, UnicodeError): return []
    return [path]


def transform_valheim(raw, mode, context=None):
    # Unity's native Linux XML prefs. Only existing standard resolution integers.
    # No invented Valheim quality keys, save-file edits, registry changes or commands.
    import xml.etree.ElementTree as ET
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        raise ValueError('Unsupported XML declarations.')
    try: root = ET.fromstring(raw)
    except ET.ParseError as exc: raise ValueError('Unsupported native preferences.') from exc
    preset = (HANDHELD_PRESETS if profile_context(context) == 'handheld' else PRESETS)[mode]
    keys = {'Screenmanager Resolution Width': preset['x'],
            'Screenmanager Resolution Height': preset['y']}
    if root.tag != 'unity_prefs' or any(len(root.findall("pref[@name='"+k+"']")) != 1 for k in keys):
        raise ValueError('Native resolution preferences not found.')
    for key, value in keys.items():
        node = root.find("pref[@name='"+key+"']")
        if node.get('type') != 'int' or not re.fullmatch(r'\d+', node.text or ''):
            raise ValueError('Unsupported preference type.')
        pattern = r'(<pref\b(?=[^>]*\bname=[\"\']' + re.escape(key) + r'[\"\'])[^>]*>)\d+(</pref>)'
        raw, count = re.subn(pattern, lambda m: m[1]+str(value)+m[2], raw)
        if count != 1: raise ValueError('Unsupported preference layout.')
    return raw


def adapter_files(game):
    # Existing UE handling remains an explicit compatible-format adapter.
    return [(p, 'unreal') for p in find_ue_configs(game)] + [(p, 'valheim-native' if game['appid'] == '892970' else 'hollow-knight-native') for p in find_valheim_configs(game)]


def transform_adapter(path, raw, mode, adapter, context=None):
    if adapter == 'unreal': return transform_ue_ini(raw, mode, context)
    if adapter in ('valheim-native', 'hollow-knight-native'): return transform_valheim(raw, mode, context)
    raise ValueError('No allowlisted adapter.')


@game_transaction
def save_mode(mode, appid=None, context=None):
    if not isinstance(mode, str) or mode not in MODES: raise ValueError('Unknown optimisation mode.')
    if appid is not None: appid = steam_id(appid)
    cfg = config(); context = profile_context(context, cfg)
    profile = cfg['profiles'][context]
    cfg['enabled'] = True
    if appid:
        profile['games'][appid] = mode
        cfg['approved'].pop(appid, None)
        cfg['approved_files'].pop(appid, None)
        cfg['approved_context'].pop(appid, None)
    else:
        profile['default'] = mode
        cfg['approved'] = {k: v for k, v in cfg['approved'].items() if k in profile['games']}
    write_config(cfg)
    return {'ok': True, 'mode': mode, 'context': context, 'message': 'Preference saved. Preview before applying.'}


@game_transaction
def preview_profile(appid, mode, context=None):
    appid = steam_id(appid)
    context = profile_context(context)
    if not isinstance(mode, str) or mode not in MODES: raise ValueError('Unknown mode.')
    game = next((g for g in installed_games() if g['appid'] == appid), None)
    if not game: return {'ok': True, 'status': 'not-installed', 'files': [], 'message': 'Preference can be saved now. Install and launch once, then preview supported settings.'}
    if game_is_running(appid): return {'ok': True, 'status': 'running', 'files': [], 'message': 'Close the game before previewing or applying.'}
    files, fingerprints = [], []
    state = read_json(STATE, {})
    if not isinstance(state, dict): return {'ok': False, 'error': 'Invalid local backup state; no changes approved.'}
    for path, adapter in adapter_files(game):
        try:
            raw = safe_read_text(path)
            changed = transform_adapter(path, raw, mode, adapter, context)
            rel_id = hashlib.sha256(str(path).encode()).hexdigest()[:16]
            old = state.get(rel_id, {})
            if not isinstance(old, dict): raise ValueError('Invalid backup record.')
            manual = bool(old.get('after_sha') and sha(raw) != old['after_sha'])
            fingerprints.append([str(path), sha(raw), sha(changed)])
            # Only allowlisted settings lines are shown, never raw unrelated user configuration.
            if adapter == 'unreal':
                allowed = set(SCALABILITY_KEYS + GAME_KEYS + ['sg.ResolutionQuality'])
                def values(text):
                    return {m[1]: m[2] for m in re.finditer(r'^\s*([\w.]+)\s*=\s*([^\r\n]*)', text, re.M) if m[1] in allowed}
                before, after = values(raw), values(changed)
            else:
                import xml.etree.ElementTree as ET
                def values(text):
                    return {n.get('name'): n.text for n in ET.fromstring(text).findall('pref')
                            if n.get('name') in ('Screenmanager Resolution Width', 'Screenmanager Resolution Height')}
                before, after = values(raw), values(changed)
            files.append({'file': path.name, 'location': str(path), 'adapter': adapter, 'manual_changes': manual,
                          'changes': [{'key': k, 'before': before.get(k), 'after': v} for k, v in after.items() if before.get(k) != v]})
        except (OSError, ValueError, UnicodeError):
            return {'ok': False, 'status': 'unreadable', 'files': [], 'error': 'A supported config cannot be safely read. No changes approved.'}
    if not files: return {'ok': True, 'status': 'unsupported', 'files': [], 'message': 'No compatible local adapter. Research and mode preference are advisory only.'}
    token = sha(json.dumps([appid, mode, context, fingerprints], sort_keys=True))
    preset = (HANDHELD_PRESETS if context == 'handheld' else PRESETS)[mode]
    summary = {'resolution': str(preset['x'])+' × '+str(preset['y']),
               'quality': {1:'Low',2:'Medium',3:'High'}[preset['quality']] if any(f['adapter']=='unreal' for f in files) else None,
               'files': len(files), 'manual_files': sum(f['manual_changes'] for f in files)}
    return {'ok': True, 'status': 'preview', 'appid': appid, 'mode': mode, 'context': context, 'files': files, 'summary': summary, 'fingerprints': {p[0]:p[1] for p in fingerprints}, 'paths': [p[0] for p in fingerprints], 'token': token,
            'message': 'Conservative local starting points, not downloaded report instructions or measured optimal settings. Manual/game edits will be skipped. Backups precede every first edit.'}


@game_transaction
def approve_profile(appid, mode, token, context=None):
    appid = steam_id(appid)
    context = profile_context(context)
    if context != config()['context']: return {'ok': False, 'error': 'Profile changed. Preview again.'}
    with LOCK:
        preview = preview_profile(appid, mode, context)
        if preview.get('status') != 'preview' or not secrets.compare_digest(str(preview.get('token', '')), str(token)):
            return {'ok': False, 'error': 'Preview changed or game is running. Preview again before applying.'}
        game = next(g for g in installed_games() if g['appid'] == appid)
        # Never force manual changes, even after approval; preserve the user's newer edits.
        result = apply_profile(game, mode, allowed_files=preview['paths'], context=context, expected_hashes=preview['fingerprints'])
        if result['status'] in ('applied', 'already-set'):
            cfg = config(); cfg['profiles'][context]['games'][appid] = mode; cfg['enabled'] = True; cfg['approved'][appid] = mode
            cfg['approved_context'][appid] = context
            cfg['approved_files'][appid] = preview['paths']
            write_config(cfg)
        return {'ok': result['status'] in ('applied', 'already-set'), 'result': result,
                'message': ('Updated '+str(result.get('count', 0))+' file(s). ' if result.get('count') else '') + 'Local settings: ' + result['status'] + '. Manual/game changes are preserved.'}


@game_transaction
def game_checkup(appid, context=None):
    appid = steam_id(appid); cfg = config(); context = profile_context(context, cfg)
    game = next((g for g in installed_games() if g['appid'] == appid), None)
    mode = effective_mode(appid, cfg, context)
    result = {'ok': True, 'appid': appid, 'context': context, 'mode': mode,
              'status': 'not-installed', 'can_restore': False, 'backups': 0, 'optimised': False}
    if not game: return {**result, 'message': 'Saved for when you install it.'}
    files = adapter_files(game)
    if not files: return {**result, 'status': 'advisory', 'message': 'Advice only. No supported settings file.'}
    running = game_is_running(appid)
    state = read_json(STATE, {})
    if not isinstance(state, dict): return {**result, 'status': 'error', 'message': 'Backup records need review.'}
    matches, manual, restorable, unreadable = True, False, 0, False
    for path, adapter in files:
        try:
            raw = safe_read_text(path)
            matches &= transform_adapter(path, raw, mode, adapter, context) == raw
            record = state.get(hashlib.sha256(str(path).encode()).hexdigest()[:16], {})
            if not isinstance(record, dict): raise ValueError('Invalid backup record')
            if record:
                unchanged = sha(raw) == record.get('after_sha')
                manual |= not unchanged
                backup = Path(record.get('backup', ''))
                safe = backup.is_file() and not backup.is_symlink() and backup.resolve().is_relative_to(BACKUPS.resolve())
                result['backups'] += int(safe)
                unreadable |= not safe
                restorable += int(safe and unchanged)
        except (OSError, ValueError, UnicodeError, TypeError): unreadable = True
    approved = (cfg['approved'].get(appid) == mode and cfg['approved_context'].get(appid) == context
                and all(str(p) in cfg['approved_files'].get(appid, []) for p, _ in files))
    result['can_restore'] = bool(restorable and not running)
    result['optimised'] = bool(matches and approved and not manual and not unreadable)
    if running: status, message = 'running', 'Close the game to make changes.'
    elif unreadable: status, message = 'error', 'A settings file or backup needs review.'
    elif manual: status, message = 'manual-changes', 'Your changes are protected.'
    elif result['optimised']: status, message = 'ready', 'Your approved settings match.'
    elif matches: status, message = 'settings-match', 'Settings match. Review to enable safe sync.'
    else: status, message = 'needs-review', 'Ready to review settings.'
    return {**result, 'status': status, 'message': message}


def evidence_summary(reports, context):
    """Specificity of community evidence, never a probability of achieved FPS."""
    matching = [r for r in reports if r.get('display_context') == context]
    fresh = []
    now = dt.datetime.now(dt.timezone.utc)
    for report in matching:
        try:
            date = dt.datetime.fromisoformat(report.get('report_date', '').replace('Z', '+00:00'))
            if date.tzinfo is None: date = date.replace(tzinfo=dt.timezone.utc)
            if 0 <= (now-date).days <= 180 and not report.get('stale'): fresh.append(report)
        except (TypeError, ValueError, AttributeError): pass
    independent = len({r.get('source') for r in fresh})
    oled = [r for r in fresh if 'OLED' in r.get('device', '').upper()]
    complete = [r for r in oled if r.get('resolution') and r.get('game_version')
                and str(r['game_version']).lower() not in ('unknown', 'n/a', 'default')]
    if independent >= 2 and len({r.get('source') for r in complete}) >= 2:
        confidence, reason = 'high', 'Recent OLED reports from independent sources match this profile.'
    elif fresh and (oled or independent >= 2):
        confidence, reason = 'medium', 'Some recent reports match this profile; details are incomplete.'
    elif reports:
        confidence, reason = 'low', 'Reports are old, incomplete, offline, or from a different display setup.'
    else: confidence, reason = 'none', 'No verified reports yet.'
    return {'mode': 'balanced', 'confidence': confidence, 'reason': reason,
            'context': context, 'matching_reports': len(matching),
            'note': 'Balanced is a conservative starting point. Confidence describes matching evidence, not guaranteed performance.'}



# Controlled Play is opt-in. These functions never invoke Steam or a network client.
@game_transaction
def set_play_assistant(enabled):
    if not isinstance(enabled, bool): raise ValueError('Expected on/off.')
    cfg = config(); cfg['play_assistant_enabled'] = enabled; write_config(cfg)
    return {'ok': True, 'message': 'DeckPilot Play recommendations '+('enabled.' if enabled else 'disabled.')}


@game_transaction
def dismiss_play_advice(appid, dismissed):
    appid = steam_id(appid)
    if not isinstance(dismissed, bool): raise ValueError('Expected on/off.')
    cfg = config(); ids = set(cfg['launch_dismissed'])
    if dismissed: ids.add(appid)
    else: ids.discard(appid)
    cfg['launch_dismissed'] = sorted(ids); write_config(cfg)
    return {'ok': True, 'message': 'Advice hidden for this game.' if dismissed else 'Advice enabled for this game.'}


def cached_launch_advice(appid, context):
    """Read existing exact-ID cache only. No loader, refresh, or Internet request."""
    cache = read_json(BASE/'research-cache.json', {})
    if not isinstance(cache, dict): cache = {}
    reports = []
    sources = ('Deck Settings / deckverified.games', 'ShareDeck', 'SteamDeckHQ')
    for source in sources:
        item = cache.get(source+':'+appid, {})
        if not isinstance(item, dict) or not isinstance(item.get('at'), (int,float)): continue
        age = time.time()-item['at']; value = item.get('value')
        if not 0 <= age <= 30*86400 or not isinstance(value, dict) or value.get('status') != 'ok': continue
        raw_reports = value.get('reports', [])
        if not isinstance(raw_reports, list): continue
        for report in raw_reports[:20]:
            if not isinstance(report, dict) or report.get('appid') != appid or report.get('source') != source: continue
            if not isinstance(report.get('url'), str) or not public_url(report['url']): continue
            # Bound data exposed by this fast path, even if a local cache was malformed.
            text_fields = ('device','display_context','resolution','fps','fps_kind','game_version','report_date')
            normalized = {key: clean_text(report.get(key), 100) or None for key in text_fields}
            normalized['device'] = normalized['device'] or 'unknown'
            normalized['display_context'] = normalized['display_context'] or 'unknown'
            normalized.update(source=source, appid=appid, stale=age>=RESEARCH_TTL)
            reports.append(normalized)
    evidence = evidence_summary(reports, context)
    matching = [r for r in reports if r.get('display_context') == context]
    return {'recommendation': evidence, 'report_count': len(reports),
            'sources': sorted({r['source'] for r in reports}),
            'latest_report': max((r.get('report_date') or '' for r in reports), default='') or None,
            'stale': any(r['stale'] for r in reports),
            # Metadata is evidence, not instructions or measured DeckPilot performance.
            'display_match': bool(matching),
            'resolution': matching[0].get('resolution') if matching else None,
            'fps': matching[0].get('fps') if matching else None,
            'fps_kind': matching[0].get('fps_kind') if matching else None}


def prepare_play(appid, context=None):
    appid = steam_id(appid); cfg = config(); context = profile_context(context, cfg)
    if not cfg['play_assistant_enabled']: return {'ok': True, 'status': 'disabled', 'appid': appid}
    if context != cfg['context']: return {'ok': False, 'status': 'profile-changed', 'error': 'Profile changed. Open the game again.'}
    game = next((g for g in installed_games() if g['appid'] == appid), None)
    if game is None: return {'ok': False, 'status': 'not-installed', 'error': 'This game is not installed.'}
    if game_is_running(appid): return {'ok': False, 'status': 'running', 'error': 'Already running. Use Steam to resume.'}
    if appid in cfg['launch_dismissed']: return {'ok': True, 'status': 'dismissed', 'appid': appid}
    checkup = game_checkup(appid, context)
    return {'ok': True, 'status': 'prompt', 'appid': appid, 'name': game['name'], 'context': context,
            'saved_mode': effective_mode(appid, cfg, context),
            'can_apply': checkup['status'] in ('needs-review','ready','settings-match'),
            **cached_launch_advice(appid, context)}


@game_transaction
def play_preview(appid, mode, context=None):
    appid = steam_id(appid); cfg = config(); context = profile_context(context, cfg)
    if not cfg['play_assistant_enabled'] or appid in cfg['launch_dismissed']:
        return {'ok': False, 'error': 'Recommendations disabled. Play without changes.'}
    if cfg['context'] != context: return {'ok': False, 'error': 'Profile changed. Preview again.'}
    return preview_profile(appid, mode, context)


@game_transaction
def play_approve(appid, mode, token, context=None):
    appid = steam_id(appid); cfg = config()
    if not cfg['play_assistant_enabled'] or appid in cfg['launch_dismissed']:
        return {'ok': False, 'error': 'Recommendations disabled. No settings applied.'}
    return approve_profile(appid, mode, token, context)



def display_diagnostics(drm_root=Path('/sys/class/drm')):
    outputs = []
    for connector in drm_root.glob('card*-*'):
        if not re.search(r'-(DP|HDMI|DVI)-', connector.name, re.I): continue
        try:
            if (connector/'status').read_text().strip() != 'connected': continue
            modes = (connector/'modes').read_text().splitlines()[:40] if (connector/'modes').is_file() else []
            outputs.append({'connector': connector.name, 'advertised_modes': modes})
        except OSError: continue
    return {'external_outputs': outputs, 'vrr_capability': external_vrr_capability(drm_root),
            'vrr_enabled': 'unknown', 'active_mode': 'unknown',
            'note': 'Advertised resolutions/capability do not establish active refresh rate or VRR. Check SteamOS Display settings; official dock supports up to 4K60 or 1440p120 depending on connection.'}



def parse_ini_sections(text):
    # Preserve full text and comments; edit only known key assignments.
    return re.split(r'(?=^\s*\[[^\r\n]+\]\s*$)', text, flags=re.M)


def transform_ue_ini(raw, mode, context=None):
    preset = (HANDHELD_PRESETS if profile_context(context) == 'handheld' else PRESETS)[mode]
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
                        raise ValueError('Duplicate settings key; use the game menu to resolve it first.')
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
    with path.open('rb') as handle:
        data = handle.read(2_000_001)
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
            try:
                if item.stat().st_uid == os.getuid(): return True
            except (OSError, PermissionError): pass
            continue
        if (b'SteamAppId=' + appid.encode() + b'\x00') in b'\x00' + blob + b'\x00':
            return True
        if (b'SteamGameId=' + appid.encode() + b'\x00') in b'\x00' + blob + b'\x00':
            return True
    return False


@game_transaction
def apply_profile(game, mode, force=False, allowed_files=None, context=None, expected_hashes=None):
    """Returns status. Only modifies supported existing files when no game runs."""
    files = adapter_files(game)
    if allowed_files is not None:
        files = [(p, a) for p, a in files if str(p) in allowed_files]
    if not files:
        return {'status': 'unsupported', 'count': 0}
    if game_is_running(game['appid']):
        return {'status': 'running', 'count': 0}
    previous = read_json(STATE, {})
    if not isinstance(previous, dict): return {'status': 'error', 'count': 0}
    changed = 0
    skipped_manual = 0
    backups = 0
    errors = 0
    for path, adapter in files:
        try:
            original = safe_read_text(path)
            if expected_hashes is not None and expected_hashes.get(str(path)) != sha(original):
                raise ValueError('Settings changed since preview; no changes made.')
            updated = transform_adapter(path, original, mode, adapter, context)
            if updated == original:
                continue
            rel_id = hashlib.sha256(str(path).encode()).hexdigest()[:16]
            old = previous.get(rel_id, {})
            if not isinstance(old, dict): raise ValueError('Invalid backup record.')
            if old:
                saved_backup = Path(old.get('backup', ''))
                if (not saved_backup.is_file() or saved_backup.is_symlink()
                        or not saved_backup.resolve().is_relative_to(BACKUPS.resolve())):
                    raise ValueError('Original backup missing or unsafe; no changes made.')
            if old.get('after_sha') and sha(original) != old['after_sha']:
                # A game or user changed these settings since our last edit.
                # Never override this change during automatic syncing.
                # Explicit user re-selection can apply a mode again, after
                # preserving a snapshot of the newer file.
                if not force:
                    skipped_manual += 1
                    log('SKIP user/game changed file ' + str(path))
                    continue
                reselect = BACKUPS / game['appid'] / (rel_id + '.' + secrets.token_hex(6) + '.before-reselect.ini')
                shutil.copy2(path, reselect)
                old['backup'] = str(reselect)
            # Keep a backup of the user's ORIGINAL, not each later DeckPilot
            # edit. Always back up before modifying an existing configuration.
            backdir = BACKUPS / game['appid']
            backup = backdir / (rel_id + '.original.ini')
            if not old and backup.exists():
                backup = backdir / (rel_id + '.' + secrets.token_hex(6) + '.original.ini')
            backdir.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(path, backup)
                backups += 1
            managed_backup = Path(old.get('backup', str(backup)))
            if (not managed_backup.is_file() or managed_backup.is_symlink()
                    or not managed_backup.resolve().is_relative_to(BACKUPS.resolve())):
                raise ValueError('Original backup is missing or unsafe; no changes made.')
            temp = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.deckpilot.', delete=False) as f:
                    temp = Path(f.name)
                    f.write(updated.encode('utf-8')); f.flush(); os.fsync(f.fileno())
                os.chmod(temp, path.stat().st_mode & 0o777)
                if game_is_running(game['appid']) or sha(safe_read_text(path)) != sha(original):
                    raise ValueError('Game started or settings changed during apply; file left alone.')
                previous[rel_id] = {'appid': game['appid'], 'file': str(path),
                                    'backup': old.get('backup', str(backup)), 'mode': mode, 'after_sha': sha(updated)}
                atomic_json(STATE, previous)
                temp.replace(path)
            finally:
                if temp is not None: temp.unlink(missing_ok=True)
            changed += 1
        except (OSError, UnicodeError, ValueError) as ex:
            errors += 1
            log('SKIP ' + game['appid'] + ' ' + str(path) + ': ' + str(ex))
    if changed:
        atomic_json(STATE, previous)
        log('APPLY ' + game['appid'] + ' ' + game['name'] + ' mode=' + mode + ' files=' + str(changed))
    return {'status': 'error' if errors else ('manual-changes' if skipped_manual else ('applied' if changed else 'already-set')),
            'count': changed, 'backups': backups, 'skipped_manual': skipped_manual}


@game_transaction
def restore_game(appid):
    if game_is_running(appid):
        return 'Game appears to be running. Close it before restoring.'
    cfg = config()
    cfg['approved'].pop(appid, None)
    cfg['approved_files'].pop(appid, None)
    cfg['approved_context'].pop(appid, None)
    write_config(cfg)
    state = read_json(STATE, {})
    if not isinstance(state, dict): return 'Invalid backup state. No files changed.'
    n = 0
    for k, v in list(state.items()):
        if not isinstance(v, dict) or v.get('appid') != appid:
            continue
        if not isinstance(v.get('file'), str) or not isinstance(v.get('backup'), str): continue
        path = Path(v['file'])
        backup = Path(v['backup'])
        if (not backup.is_file() or not path.is_file() or path.is_symlink() or backup.is_symlink()
                or any(p.is_symlink() for p in path.parents)
                or not backup.resolve().is_relative_to(BACKUPS.resolve())):
            continue
        try:
            current = safe_read_text(path)
            if sha(current) != v.get('after_sha'):
                log('RESTORE SKIP modified after DeckPilot: ' + str(path))
                continue  # never overwrite user/game changes
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.restore.', delete=False) as handle:
                restored = Path(handle.name)
            try:
                shutil.copy2(backup, restored)
                if game_is_running(appid) or sha(safe_read_text(path)) != v.get('after_sha'):
                    continue
                restored.replace(path)
            finally: restored.unlink(missing_ok=True)
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
                    or (len(target) >= 5 and re.match(re.escape(target) + r'(?:20[0-9]{6}|$)', stem))):
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
    frame_times = []
    try:
        if path.stat().st_size > 20_000_000:
            return None
        with path.open('r', encoding='utf-8-sig', errors='replace', newline='') as f:
            rd = csv.reader(f)
            idx = None
            idx_elapsed = None
            idx_frame_time = None
            for row in rd:
                names = [v.strip().casefold() for v in row]
                if idx is None:
                    if 'fps' in names and ('frametime' in names or 'elapsed' in names):
                        idx = names.index('fps')
                        idx_frame_time = names.index('frametime') if 'frametime' in names else None
                        idx_elapsed = names.index('elapsed') if 'elapsed' in names else None
                    continue
                if len(row) <= idx:
                    continue
                try:
                    number = float(row[idx])
                    if 1 <= number <= 300:
                        vals.append(number)
                        if idx_frame_time is not None and len(row) > idx_frame_time:
                            try:
                                frametime = float(row[idx_frame_time])
                                if 0 < frametime <= 1000: frame_times.append(frametime)
                            except ValueError: pass
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
            'samples': len(vals), 'duration_s': duration,
            'frame_time_avg_ms': round(statistics.mean(frame_times), 2) if len(frame_times) >= 60 else None,
            'frame_time_p95_ms': round(sorted(frame_times)[max(0, (95*len(frame_times)+99)//100-1)], 2) if len(frame_times) >= 60 else None,
            'measurement_note': 'Existing user-recorded MangoHud data. Device/profile/session is unverified; no automatic tuning.'}


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
    text = re.sub(r'(?i)([\"\'](?:password|secret|token|access_token|refresh_token|api_key)[\"\']\s*:\s*[\"\'])[^\"\']+', r'\1[REDACTED]', text)
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
    file_count = sum(bool(adapter_files(g)) for g in games)
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
        'format': 1, 'app': 'DeckPilot TV', 'version': VERSION, 'build_id': BUILD_ID,
        'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'operating_system': os_name[:120], 'kernel': platform.release()[:120],
        'python_version': platform.python_version(),
        'games_detected': len(games), 'supported_configs': file_count,
        'profile_enabled': cfg['enabled'], 'default_profile': cfg['default'],
        'per_game_overrides': len(cfg['games']),
        'known_backup_records': len(state) if isinstance(state, dict) else 0,
        'external_vrr_advertised': external_vrr_capability(),
        'display': display_diagnostics(),
        'unsupported_games': len(games) - file_count,
        'adapter_counts': {name: sum(any(a == name for _, a in adapter_files(g)) for g in games) for name in ('unreal', 'valheim-native', 'hollow-knight-native')},
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


def cloud_state_update(**changes):
    # Short metadata lock only: slow Drive operations must not block game settings.
    with LOCK:
        mkdir()
        with (BASE/'cloud-state.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                cfg = cloud_config(); cfg.update(changes); atomic_json(CLOUD, cfg)
                return cfg
            finally: fcntl.flock(handle, fcntl.LOCK_UN)


def serialized_cloud_upload(fn):
    @wraps(fn)
    def guarded(*args, **kwargs):
        mkdir()
        with (BASE/'cloud-upload.lock').open('a') as handle:
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: return 'A diagnostic upload is already in progress.'
            try: return fn(*args, **kwargs)
            finally: fcntl.flock(handle, fcntl.LOCK_UN)
    return guarded


def cloud_enable(enabled):
    enabled = enabled is True
    if enabled:
        ready, reason = drive_ready()
        if not ready:
            raise ValueError(reason)
    message = 'Cloud uploads enabled' if enabled else 'Cloud uploads disabled'
    cloud_state_update(enabled=enabled, last_status=message)
    return message


@serialized_cloud_upload
def upload_cloud_report(force=False, report=None):
    """Only writes a ZIP to ONE fixed, private Drive path. Never deletes remote files.

    Automatic updates are throttled: on new errors at most every 30 minutes,
    otherwise at most daily, and only when enabled. Manual uploads bypass the
    throttle but still require the prior opt-in switch.
    """
    cfg = cloud_config()
    if not cfg['enabled']:
        return 'Google Drive uploads are disabled.'
    ready, reason = drive_ready()
    if not ready:
        cfg['last_status'] = reason
        cloud_state_update(last_status=cfg['last_status'])
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
        if not cloud_config()['enabled']: return 'Google Drive uploads are disabled.'
        dest = CLOUD_REMOTE + CLOUD_FOLDER + '/' + CLOUD_FILENAME
        result = subprocess.run([binary, 'copyto', str(path), dest, '--retries', '1',
                                 '--contimeout', '15s', '--timeout', '45s'],
                                capture_output=True, text=True, timeout=90, check=False)
        if result.returncode != 0:
            cfg['last_status'] = 'Google Drive upload failed (check your connection and rclone setup).'
            cloud_state_update(last_status=cfg['last_status'])
            log('CLOUD upload failed')  # no rclone stderr or OAuth tokens in app log
            return cfg['last_status']
        cfg = cloud_state_update(last_success=now, last_fingerprint=fingerprint,
                   last_error_fingerprint=error_fingerprint,
                   last_status='Uploaded latest diagnostic ZIP to your private Drive folder.')
        return cfg['last_status']
    except (OSError, subprocess.TimeoutExpired):
        cfg['last_status'] = 'Google Drive upload failed or timed out.'
        cloud_state_update(last_status=cfg['last_status'])
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
    """Trusted Stable/Preview suite only. No manual Downloads or arbitrary feed."""
    import updater
    try:
        suite=updater.suite_status()
        return {'suite':suite,'available':suite.get('app_needed',False),'version':suite.get('version'),
                'can_undo':suite.get('app_rollback',False),'status':suite['message'],
                'github':{'repository':updater.TRUSTED_REPOSITORY,'message':suite['message'],'status':suite['status']}}
    except Exception:return {'available':False,'status':'Update status unavailable.'}


def start_local_update(action='install', token=None, allow_downgrade=False):
    import updater
    if action=='rollback':return updater.start_suite_rollback()['message']
    if not token:raise ValueError('Review the update again before approving installation.')
    return updater.start_suite_install(token,allow_downgrade)['message']


def check_github_async():
    import updater
    threading.Thread(target=updater.fetch_suite_update,daemon=True).start()
    return 'Checking the approved '+updater.suite_channel()+' release feed.'


def state_for_ui():
    games = installed_games()
    cfg = config()
    result = []
    for g in games:
        adapters = adapter_files(g)
        has_adapter = bool(adapters)
        mode = effective_mode(g['appid'], cfg)
        metrics = game_metrics(g) if cfg['measurements_enabled'] else None
        result.append({'appid': g['appid'], 'name': g['name'], 'mode': mode,
                       'adapter': ', '.join(sorted({a for _, a in adapters})) if has_adapter else 'Advisory only',
                       'approved': cfg['approved'].get(g['appid']) == mode and cfg['approved_context'].get(g['appid']) == cfg['context'],
                       'supported': has_adapter, 'metrics': metrics, 'hint': mode_hint(mode, metrics)})
    return {'version': VERSION, 'build_id': BUILD_ID, 'schema_version': 2, 'context': cfg['context'], 'profiles': cfg['profiles'],
            'measurements_enabled': cfg['measurements_enabled'],
            'launch_prompt': {'protocol': 1, 'enabled': cfg['play_assistant_enabled'], 'available': True, 'native_play': False, 'method': 'deckpilot-button', 'dismissed': cfg['launch_dismissed'], 'reason': 'Opt-in DeckPilot Play button only. Native Steam Play is untouched.'},
            'enabled': cfg['enabled'], 'default': cfg['default'], 'games': result, 'count': len(result),
            'supported': sum(1 for g in result if g['supported']),
            'vrr_capability': external_vrr_capability(), 'display': display_diagnostics(), 'saved_games': cfg['games'], 'cloud': cloud_status()}


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
<div class="top"><div><h1>DeckPilot <span style="color:#5fe9de">TV</span></h1><p>Steam Deck OLED · Official Dock · 4K / 120Hz VRR TV</p></div><span class="tag">v0.8 · Community research</span></div>
<div class="box"><h2>Default optimisation</h2><p>Choose one mode. Games without overrides inherit it; preview and approve local edits per game.</p>
<div id="defaults" class="modes"></div><div id="feedback" role="status"></div></div>
<div class="notice" style="margin-bottom:13px"><b>VRR / FreeSync:</b> <span id="vrr">Checking connected output…</span><br><small>This is a read-only capability check, not an enabled/disabled switch. SteamOS controls VRR; DeckPilot does not change display or TV settings.</small></div>
<div class="notice"><b>Safe first version:</b> offers conservative local presets for compatible Unreal Engine configs and native Valheim resolution preferences after preview and approval. Other games are identified but not modified. It does not change SteamOS display, FPS limits, TDP or Steam launch options. Original config files are backed up before edits. If a compatible MangoHud CSV already exists, DeckPilot reports recorded FPS, but it does not silently change your Steam overlay or claim to benchmark every game.</div>
<div class="box"><h2>Steam-wide research</h2><input id="steam-query" aria-label="Steam game name or App ID" placeholder="Name or Steam App ID (including uninstalled)"/><button onclick="steamSearch()">Search Steam</button><div id="steam-results"></div><div id="research-results"></div></div>
<div class="box"><div class="top"><div><h2 style="margin:0">Installed Steam games</h2><p id="count">Scanning library…</p></div><button onclick="refresh()">Rescan</button></div>
<input id="search" placeholder="Find a game…" oninput="drawGames()" aria-label="Find installed game"/><div id="games"></div></div>
<div class="box"><h2>Updates</h2><p id="update-status">Checking local update status…</p><p id="github-status"></p><div style="display:flex;gap:8px;flex-wrap:wrap"><button onclick="checkGithub()">Check for Updates</button><button onclick="selectChannel('stable')">Stable</button><button onclick="selectChannel('preview')">Enable Preview</button><button id="install-update" onclick="installUpdate()" disabled>No update yet</button><button id="undo-update" onclick="undoUpdate()" style="display:none">Restore Previous App</button></div><button id="plugin-rollback" onclick="pluginRollback()" style="display:none">Prepare Plugin Rollback</button><div id="plugin-rollback-link"></div><small>Only approved goddenator/DeckPilot-TV builds. Updates never install automatically. App backups are saved; game files, preferences and saves are kept. Complete matching plugin installation or rollback in Decky → Settings → Updates. No PC or file transfer required.</small></div>
<details class="box"><summary style="cursor:pointer;font-weight:700">Safety and restore</summary><p>DeckPilot keeps original copies before editing supported settings. Close your games before restoring. Files changed by a game after DeckPilot's edits will be left alone.</p><button onclick="restoreAll()">Restore all DeckPilot changes</button></details>
<details class="box"><summary style="cursor:pointer;font-weight:700">Diagnostics and private Google Drive</summary><p>Optional: keep ONE constantly updated <b>DeckPilot-Latest.zip</b> in your private <b>DeckPilot Diagnostics</b> folder. No paid ChatGPT API. Reports include redacted app logs only, but redaction is best-effort. Review a local export before opting in. Connect Google Drive once using the <b>DeckPilot - Connect Drive</b> shortcut in the Desktop Mode application launcher. Nothing is uploaded until you enable it below.</p><p id="cloud-status">Checking connection…</p><button onclick="exportReport()">Export diagnostic ZIP</button> <button onclick="toggleCloud(true)">Enable Drive uploads</button> <button onclick="toggleCloud(false)">Disable Drive uploads</button> <button onclick="uploadNow()">Upload latest now</button><p id="export-status"></p></details>
<p><small>DeckPilot never needs root access or your Steam password. MangoHud logs are optional and are only read when they can be reliably matched to a game. It cannot optimise games whose graphics settings are stored in unsupported formats. Changes to a game may not take effect until it is relaunched. Use the Safety and restore controls or the per-game Decky restore action to undo unchanged managed files.</small></p>
<script>
let info={default:'balanced',games:[]};const choices=[['graphics','Best Graphics'],['performance','Best Performance'],['balanced','Balanced']];
const token='__TOKEN__';
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function buttons(mode,appid){return choices.map(([v,name])=>`<button class="${v===mode?'active':''}" onclick="setMode('${v}',${appid?`'${appid}'`:'null'})">${name}</button>`).join('');}
function drawGames(){let q=document.getElementById('search').value.toLowerCase();let items=info.games.filter(g=>g.name.toLowerCase().includes(q));document.getElementById('games').innerHTML=items.map(g=>`<div class="game"><div><div class="game-title">${esc(g.name)}</div><div class="game-status">${g.supported?'✓ Compatible local adapter found':'• Game detected — no supported settings file'}${g.metrics?` · ${g.metrics.avg_fps} FPS avg / ${g.metrics.low_1pct_fps} sampled 1% low`:''}</div></div><div class="modes">${buttons(g.mode,g.appid)}</div></div>`).join('')||'<p>No matching installed games found.</p>'}
function draw(){const vrrLabels={'available':'Advertised as supported by the connected display','not-advertised':'Not advertised through the current output','unknown':'Could not be verified (check SteamOS Display settings)'};document.getElementById('vrr').innerText=vrrLabels[info.vrr_capability]||vrrLabels.unknown;document.getElementById('defaults').innerHTML=buttons(info.enabled?info.default:'',null);if(!info.enabled)document.getElementById('feedback').innerText='Select a mode, then preview and approve supported game changes.';document.getElementById('count').innerText=`${info.count} games detected · ${info.supported} with supported settings`;const c=info.cloud||{};document.getElementById('cloud-status').innerText=(c.enabled?'Uploads ON · ':'Uploads OFF · ')+(c.connection||'')+(c.last_success_utc?' · Last upload '+new Date(c.last_success_utc).toLocaleString():'')+' · '+(c.last_status||'');drawGames();}
async function refresh(){try{let r=await fetch('/api/state');if(!r.ok)throw Error('Server error');info=await r.json();draw();}catch(e){document.getElementById('feedback').innerText='Could not connect: '+e.message;}}
async function setMode(mode,appid){try{let r=await fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({mode,appid})});let j=await r.json();if(!r.ok)throw Error(j.error||'Unknown error');document.getElementById('feedback').innerText=j.message;await refresh();if(appid)await previewMode(appid,mode);}catch(e){document.getElementById('feedback').innerText=e.message;}}
async function localAction(path,payload){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify(payload)});const j=await r.json();if(!r.ok||j.error)throw Error(j.error||'Request failed');return j;}
async function previewMode(appid,mode){const p=await localAction('preview',{appid,mode});document.getElementById('feedback').innerText=p.message||p.status;if(!p.token)return;const summary=p.files.map(f=>f.adapter+' '+f.file+(f.manual_changes?' (manual edits: will skip)':'')+'\n'+f.changes.map(c=>c.key+': '+(c.before||'(unset)')+' → '+c.after).join('\n')).join('\n');if(confirm(summary+'\nApprove these local changes? Backups first.')){const r=await localAction('apply',{appid,mode,token:p.token});document.getElementById('feedback').innerText=r.message||r.error;await refresh();}}

async function steamSearch(){try{const r=await localAction('search',{query:document.getElementById('steam-query').value});document.getElementById('steam-results').innerHTML=(r.games||[]).map(g=>`<div class="game"><span>${esc(g.name)} · ${esc(g.appid)}</span><button onclick="researchGame('${g.appid}')">Research</button><div class="modes">${buttons(info.saved_games?.[g.appid]||info.default,g.appid)}</div></div>`).join('')||'<p>No games found.</p>';}catch(e){document.getElementById('feedback').innerText=e.message;}}
async function researchGame(appid){try{const r=await localAction('research',{appid});document.getElementById('research-results').innerHTML='<p>'+esc(r.message||'')+'</p>'+(r.sources||[]).map(s=>`<p>${esc(s.source)}: ${esc(s.status)}</p>`).join('')+(r.reports||[]).map(s=>`<p><a href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.source)}</a> · ${esc(s.device)} · ${esc(s.display_context)} · ${esc(s.resolution||'unknown resolution')} · ${esc(s.fps||'unknown FPS')} (${esc(s.fps_kind||'reported/unspecified')}) · ${esc(s.report_date||'unknown date')} · ${esc(s.game_version||'unknown game version')}<br>${esc(s.summary)}<br>${esc(s.uncertainty)}</p>`).join('');}catch(e){document.getElementById('feedback').innerText=e.message;}}
async function exportReport(){try{const r=await fetch('/api/diagnostics',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:'{}'});if(!r.ok)throw Error('Export failed');const b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download='DeckPilot-Diagnostics.zip';a.click();setTimeout(()=>URL.revokeObjectURL(u),30000);document.getElementById('export-status').innerText='Report generated locally. Review it before sharing.';}catch(e){document.getElementById('export-status').innerText=e.message;}}
async function cloudAction(action){try{let r=await fetch('/api/cloud',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({action})});let j=await r.json();document.getElementById('export-status').innerText=j.message||j.error||'No response';await refresh();}catch(e){document.getElementById('export-status').innerText=e.message;}}
let reviewedUpdate={};
async function checkUpdate(){try{const r=await fetch('/api/update');const j=await r.json();reviewedUpdate=j.suite||{};document.getElementById('plugin-rollback').style.display=reviewedUpdate.plugin_rollback?'inline-block':'none';const b=document.getElementById('install-update');b.disabled=!j.available;b.textContent=j.available?'Install App '+j.version:'No app update';document.getElementById('undo-update').style.display=j.can_undo?'inline-block':'none';document.getElementById('update-status').textContent=j.status;document.getElementById('github-status').textContent='App '+(reviewedUpdate.app_installed||info.version||'unknown')+' · '+(reviewedUpdate.channel||'stable')+' · goddenator/DeckPilot-TV';}catch(e){document.getElementById('update-status').textContent='Update status unavailable.';}}
async function githubAction(action,channel){try{const r=await fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({action,channel})});const j=await r.json();if(!r.ok)throw Error(j.error||'Update check failed');await checkUpdate();document.getElementById('update-status').textContent=j.message;}catch(e){document.getElementById('update-status').textContent=e.message;}}
function selectChannel(channel){if(channel==='preview'&&!confirm('Enable approved Preview development builds? They may contain bugs. Nothing installs automatically.'))return;githubAction('channel',channel);}
function checkGithub(){githubAction('check');}
async function pluginRollback(){if(!confirm('Prepare the previous plugin for Decky-approved rollback? Nothing installs automatically.'))return;try{const r=await fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({action:'plugin-rollback'})});const j=await r.json();if(j.error)throw Error(j.error);const box=document.getElementById('plugin-rollback-link');box.replaceChildren();const label=document.createElement('p');label.textContent='Copy this five-minute local link into Decky Settings → Developer → Install from URL and approve:';const field=document.createElement('textarea');field.readOnly=true;field.value=j.url;field.setAttribute('aria-label','Plugin rollback link');box.append(label,field);try{await navigator.clipboard.writeText(j.url);}catch{field.select();}}catch(e){document.getElementById('update-status').textContent=e.message;}}
async function undoUpdate(){if(!confirm('Restore the previous DeckPilot version? This restarts the app but preserves game profiles and backups.'))return;await updateAction('rollback');}
async function updateAction(action,approval={}){try{let r=await fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:JSON.stringify({action,...approval})});let j=await r.json();if(!r.ok)throw Error(j.error||'Could not start installer');document.getElementById('update-status').textContent=j.message;setTimeout(()=>location.reload(),9000);}catch(e){document.getElementById('update-status').textContent='Could not start: '+e.message;document.getElementById('install-update').disabled=false;}}
async function installUpdate(){const approved={token:reviewedUpdate.token,allow_downgrade:!!reviewedUpdate.downgrade};if(!approved.token)return;if(!confirm('Install app '+reviewedUpdate.version+'? '+(approved.allow_downgrade?'This is a downgrade. ':'')+'The app restarts. Preferences and game backups are kept. Complete the matching plugin in Decky.'))return;document.getElementById('install-update').disabled=true;await updateAction('install',approved);}
function toggleCloud(enabled){if(enabled&&!confirm('Send a redacted diagnostic ZIP to your private Google Drive automatically? Review an exported report first.'))return;cloudAction(enabled?'enable':'disable');}
function uploadNow(){cloudAction('upload');}
async function restoreAll(){if(!confirm('Restore backed-up game settings? Please close all games first.'))return;try{let r=await fetch('/api/restore',{method:'POST',headers:{'Content-Type':'application/json','X-DeckPilot-Token':token},body:'{}'});let j=await r.json();if(!r.ok)throw Error(j.error||'Restore failed');alert(j.message);await refresh();}catch(e){alert('Restore failed: '+e.message)}}
refresh().then(checkUpdate);
</script></body></html>'''


@game_transaction
def synchronize():
    cfg = config()
    if not cfg['enabled']:
        return
    for g in installed_games():
        mode = effective_mode(g['appid'], cfg)
        approved_paths = cfg['approved_files'].get(g['appid'], [])
        if cfg['approved'].get(g['appid']) == mode and cfg['approved_context'].get(g['appid']) == cfg['context'] and approved_paths:
            apply_profile(g, mode, allowed_files=approved_paths, context=cfg['context'])


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
        if self.path not in ('/api/mode', '/api/restore', '/api/diagnostics', '/api/cloud', '/api/update', '/api/preview', '/api/apply', '/api/research', '/api/search'): self.send_error(404); return
        if self.headers.get('X-DeckPilot-Token') != self.token:
            self.send_json({'error': 'Invalid session token'}, 403); return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.send_json({'error': 'JSON expected'}, 415); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 1024: raise ValueError('Invalid message length')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict): raise ValueError('JSON object required')
            if self.path == '/api/search':
                self.send_json(search_steam(payload.get('query', ''))); return
            if self.path == '/api/research':
                self.send_json(research_game(steam_id(payload['appid']), payload.get('context'))); return
            if self.path == '/api/preview':
                self.send_json(preview_profile(payload['appid'], payload['mode'], payload.get('context'))); return
            if self.path == '/api/apply':
                self.send_json(approve_profile(payload['appid'], payload['mode'], payload['token'], payload.get('context'))); return
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
                    self.send_json({'message':start_local_update(action,payload.get('token'),payload.get('allow_downgrade') is True)});return
                if action == 'check':
                    self.send_json({'message':check_github_async()});return
                if action == 'plugin-rollback':
                    import updater
                    self.send_json(updater.prepare_plugin_handoff('',None,rollback=True));return
                if action == 'channel':
                    import updater
                    updater.set_suite_channel(payload.get('channel'))
                    self.send_json({'message':check_github_async()});return
                if action in ('connect','disconnect'):
                    import updater
                    self.send_json({'message':'Updates use only goddenator/DeckPilot-TV. Select Stable or Preview in Decky Settings.'});return
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
            self.send_json(save_mode(payload['mode'], payload.get('appid'), payload.get('context')))
        except (ValueError, KeyError, json.JSONDecodeError, updater.UpdateError) as ex:
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
        # Check the fixed public release feed; never install without approval.
        while True:
            try:
                import updater
                updater.fetch_suite_update()
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
    parser.add_argument('command', choices=['serve', 'scan', 'apply', 'restore', 'status', 'diagnose', 'export', 'cloud-status', 'cloud-upload', 'cloud-enable', 'cloud-disable', 'update-status', 'set-mode', 'plugin-state', 'check-github', 'install-update', 'rollback-update', 'search', 'research', 'preview', 'approve', 'set-context', 'checkup', 'measurements-enable', 'measurements-disable', 'play-enable', 'play-disable', 'play-plan', 'play-preview', 'play-approve', 'play-dismiss', 'play-reset'])
    parser.add_argument('appid', nargs='?')
    parser.add_argument('--mode', choices=sorted(MODES))
    parser.add_argument('--preview-token', default='')
    parser.add_argument('--context', choices=sorted(CONTEXTS))
    args = parser.parse_args()
    if args.command in ('play-enable','play-disable','play-plan','play-preview','play-approve','play-dismiss','play-reset'):
        try:
            if args.command in ('play-enable','play-disable'): result = set_play_assistant(args.command=='play-enable')
            elif args.command == 'play-plan': result = prepare_play(args.appid, args.context)
            elif args.command == 'play-preview': result = play_preview(args.appid, args.mode, args.context)
            elif args.command == 'play-approve': result = play_approve(args.appid, args.mode, args.preview_token, args.context)
            else: result = dismiss_play_advice(args.appid, args.command=='play-dismiss')
            print(json.dumps(result, ensure_ascii=False))
        except ValueError as exc: print(json.dumps({'ok':False,'error':str(exc)}))
        return
    if args.command in ('set-context', 'checkup', 'measurements-enable', 'measurements-disable'):
        try:
            if args.command == 'set-context': result = set_context(args.context)
            elif args.command == 'checkup': result = game_checkup(args.appid, args.context)
            else: result = set_measurements(args.command == 'measurements-enable')
            print(json.dumps(result))
        except ValueError as exc: print(json.dumps({'ok': False, 'error': str(exc)}))
        return
    if args.command in ('search', 'research', 'preview', 'approve'):
        try:
            if args.command == 'search': result = search_steam(args.appid or '')
            elif args.command == 'research': result = research_game(steam_id(args.appid), args.context)
            elif args.command == 'preview': result = preview_profile(args.appid, args.mode, args.context)
            else: result = approve_profile(args.appid, args.mode, args.preview_token, args.context)
            print(json.dumps(result, ensure_ascii=False))
        except ValueError as exc: print(json.dumps({'ok': False, 'error': str(exc)}))
        return
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
        print(json.dumps(updater.fetch_suite_update()));return
    if args.command == 'set-mode':
        if not args.mode: parser.error('--mode is required')
        try: print(json.dumps(save_mode(args.mode, args.appid, args.context)))
        except ValueError as exc: parser.error(str(exc))
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
            print(g['name'], approve_profile(g['appid'], effective_mode(g['appid']), args.preview_token))
    elif args.command == 'restore':
        for g in selected:
            print(g['name'], restore_game(g['appid']))

if __name__ == '__main__':
    main()
