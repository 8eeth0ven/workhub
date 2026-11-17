"""Explicit, pinned Workhub module installation; no collection or model calls.

Only a user-triggered start installs a catalog ID. Existing module code is never
executed: builders and the English server use a fresh verified source capsule.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
from http.client import HTTPException
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid
import zipfile

try:
    import fcntl
except ImportError:
    fcntl = None

from module_catalog import MODULE_IDS, MAX_MANIFEST_BYTES, _unique_object, module_catalog, trusted_module

MAX_ARCHIVE = 8 * 1024 * 1024
MAX_UNPACKED = 40 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_FILES = 128
ACTIVE = frozenset({'queued', 'downloading', 'verifying', 'installing', 'building', 'connecting'})
MESSAGES = {'queued': '等待安装', 'downloading': '下载已核实版本', 'verifying': '校验安装包',
            'installing': '准备模块文件', 'building': '准备模块页面', 'connecting': '接入项目空间',
            'completed': '已接入项目空间', 'failed': '安装未完成', 'idle': ''}
ERRORS = {'unknown_module': '未知模块', 'installer_closed': '工作台正在关闭，请稍后重试',
          'download_failed': '下载失败，请检查网络后重试', 'download_timeout': '下载超时，请稍后重试',
          'download_network': '连接下载服务失败，请检查网络或代理',
          'download_unavailable': '下载服务暂时不可用，请稍后重试',
          'download_rate_limited': '下载服务请求过于频繁，请稍后重试',
          'download_not_found': '安装包不存在，请检查模块版本',
          'download_denied': '下载服务拒绝访问，请检查网络访问权限',
          'download_tls': '下载连接证书验证失败，请检查系统网络设置',
          'download_redirect': '下载地址跳转不符合安全要求，已停止',
          'archive_too_large': '安装包超过允许大小', 'checksum_mismatch': '安装包校验失败，未执行或安装',
          'invalid_archive': '安装包格式不符合发布清单', 'invalid_manifest': '模块清单无效',
          'existing_install_invalid': '已有同版本目录需要检查，文件未被覆盖',
          'storage_unsafe': '模块存储目录不可安全使用', 'build_failed': '模块页面未能生成',
          'connect_failed': '模块尚未成功接入项目空间', 'service_failed': '本机服务未能启动',
          'service_stopped': '本机服务已停止，可重新启用', 'in_use': '模块数据正在使用，未修改或删除锁文件',
          'install_failed': '安装未完成，请稍后重试'}


class ModuleInstallError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(ERRORS.get(code, ERRORS['install_failed']))


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def loopback_origin(value):
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        raise ModuleInstallError('connect_failed')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.username is not None or parsed.password is not None or parsed.path not in {'', '/'}
                or parsed.query or parsed.fragment or parsed.port is None or not 1 <= parsed.port <= 65535):
            raise ValueError()
        return value.rstrip('/')
    except (ValueError, TypeError):
        raise ModuleInstallError('connect_failed') from None


def relative_path(value):
    if (not isinstance(value, str) or not value or '\\' in value or '\0' in value
            or any(ord(c) < 32 for c in value)):
        raise ModuleInstallError('invalid_archive')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {'', '.', '..'} or ':' in p for p in value.split('/')):
        raise ModuleInstallError('invalid_archive')
    return path


def _regular_bytes(path, limit=MAX_FILE, code='storage_unsafe'):
    fd = None
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= limit:
            raise ModuleInstallError(code)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        after = os.fstat(fd)
        if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise ModuleInstallError(code)
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ModuleInstallError(code)
        return raw
    except OSError:
        raise ModuleInstallError(code) from None
    finally:
        if fd is not None:
            os.close(fd)


def _json(raw, code='invalid_manifest'):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise ModuleInstallError(code) from None


def validate_manifest(value, meta):
    if (not isinstance(value, dict) or type(value.get('schema_version')) is not int
            or value['schema_version'] != 1 or value.get('kind') != 'workhub-module'
            or value.get('id') != meta['id'] or value.get('version') != meta['version']):
        raise ModuleInstallError('invalid_manifest')
    files = value.get('files')
    if (not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES
            or any(not isinstance(f, str) for f in files) or len(set(files)) != len(files)
            or 'module.json' not in files or 'bin/build_data.py' not in files):
        raise ModuleInstallError('invalid_manifest')
    lowered = set()
    for name in files:
        path = relative_path(name)
        key = unicodedata.normalize('NFKC', name).casefold()
        if key in lowered or any(p.startswith('.') or p.casefold() in {'data', 'logs', 'tests', 'test', '__pycache__', 'node_modules'} for p in path.parts):
            raise ModuleInstallError('invalid_manifest')
        lowered.add(key)
        if path.suffix.lower() not in {'.py', '.html', '.css', '.js', '.json', '.md', '.txt', '.svg'}:
            raise ModuleInstallError('invalid_manifest')
    entry = value.get('entrypoints')
    if not isinstance(entry, dict) or entry.get('build') != 'bin/build_data.py':
        raise ModuleInstallError('invalid_manifest')
    if meta['id'] == 'english-slices' and entry.get('serve') != 'bin/serve.py':
        raise ModuleInstallError('invalid_manifest')
    if meta['id'] == 'ai-opinion' and (entry.get('serve') != 'bin/server.py' or 'bin/server.py' not in files):
        raise ModuleInstallError('invalid_manifest')
    site = value.get('site')
    if not isinstance(site, dict) or site.get('entry') != 'site/index.html':
        raise ModuleInstallError('invalid_manifest')
    return value


def unpack_archive(archive, destination, meta):
    """Validate the entire archive before extracting only manifest-listed files."""
    try:
        with zipfile.ZipFile(archive) as package:
            infos = package.infolist()
            if not 1 <= len(infos) <= MAX_FILES * 3:
                raise ModuleInstallError('invalid_archive')
            names, folded, total = {}, set(), 0
            prefix = meta['id'] + '/'
            for item in infos:
                if item.orig_filename != item.filename:
                    raise ModuleInstallError('invalid_archive')
                name = item.filename[:-1] if item.is_dir() else item.filename
                path = relative_path(name)
                if path.parts[0] != meta['id']:
                    raise ModuleInstallError('invalid_archive')
                key = unicodedata.normalize('NFKC', name).casefold()
                if name in names or key in folded or item.flag_bits & 1:
                    raise ModuleInstallError('invalid_archive')
                names[name], folded = item, folded | {key}
                mode = item.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if (item.is_dir() and kind not in {0, stat.S_IFDIR}) or (not item.is_dir() and kind not in {0, stat.S_IFREG}):
                    raise ModuleInstallError('invalid_archive')
                if item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ModuleInstallError('invalid_archive')
                if item.file_size > MAX_FILE or item.file_size < 0:
                    raise ModuleInstallError('archive_too_large')
                if item.file_size > 65536 and item.file_size > max(1, item.compress_size) * 200:
                    raise ModuleInstallError('invalid_archive')
                total += item.file_size
                if total > MAX_UNPACKED:
                    raise ModuleInstallError('archive_too_large')
            manifest_name = prefix + 'module.json'
            if manifest_name not in names or names[manifest_name].file_size > MAX_MANIFEST_BYTES:
                raise ModuleInstallError('invalid_manifest')
            manifest = validate_manifest(_json(package.read(manifest_name)), meta)
            expected = {prefix + name for name in manifest['files']}
            parents = {str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent) != '.'}
            for name, info in names.items():
                if (info.is_dir() and name not in parents) or (not info.is_dir() and name not in expected):
                    raise ModuleInstallError('invalid_archive')
            if {n for n, i in names.items() if not i.is_dir()} != expected:
                raise ModuleInstallError('invalid_archive')
            root = destination / meta['id']
            root.mkdir(mode=0o700)
            for name in manifest['files']:
                path = root.joinpath(*relative_path(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with package.open(prefix + name) as source, path.open('xb') as output:
                    remaining = MAX_FILE + 1
                    while remaining:
                        chunk = source.read(min(65536, remaining))
                        if not chunk:
                            break
                        output.write(chunk)
                        remaining -= len(chunk)
                    if remaining == 0:
                        raise ModuleInstallError('archive_too_large')
                path.chmod(0o600)
            return root, manifest
    except ModuleInstallError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, ValueError, EOFError):
        raise ModuleInstallError('invalid_archive') from None


def _github_url(value):
    try:
        u = urlsplit(value)
        if (u.scheme != 'https' or u.username is not None or u.password is not None
                or u.port not in {None, 443} or u.fragment or any(ord(c) < 33 for c in value)):
            return False
        if u.hostname == 'github.com':
            return u.path.startswith('/8eeth0ven/workhub-model/releases/download/') and not u.query
        return u.hostname in {'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
    except (ValueError, TypeError):
        return False


class GitHubRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _github_url(newurl):
            raise ModuleInstallError('download_redirect')
        count = getattr(req, '_workhub_redirects', 0)
        if count >= 5:
            raise ModuleInstallError('download_redirect')
        deadline = getattr(req, '_workhub_deadline', None)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ModuleInstallError('download_timeout')
            # urllib follows redirects using the original request's timeout.
            req.timeout = min(20.0, remaining)
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None:
            result._workhub_redirects = count + 1
            result._workhub_deadline = deadline
        return result


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ModuleInstallError('service_failed')


def _download_error(error):
    """Return a fixed error code and retry flag; never expose exception text."""
    if isinstance(error, HTTPError):
        status = error.code
        error.close()
        if status == 429:
            return 'download_rate_limited', False
        if status == 404:
            return 'download_not_found', False
        if status in (401, 403):
            return 'download_denied', False
        if status == 408 or 500 <= status <= 599:
            return 'download_unavailable', True
        return 'download_failed', False
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLError):
        return 'download_tls', False
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'download_timeout', True
    if isinstance(reason, socket.gaierror):
        return 'download_network', reason.errno == getattr(socket, 'EAI_AGAIN', None)
    if isinstance(reason, (ConnectionError, HTTPException)):
        return 'download_network', True
    if isinstance(error, URLError):
        return 'download_network', False
    return 'download_failed', False


def _network_download(url, destination, progress, cancelled):
    if not _github_url(url) or urlsplit(url).hostname != 'github.com':
        raise ModuleInstallError('download_failed')
    deadline = time.monotonic() + 60.0
    for attempt in range(2):
        if cancelled.is_set():
            raise ModuleInstallError('installer_closed')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModuleInstallError('download_timeout')
        request = Request(url, headers={'User-Agent': 'Workhub/module-installer', 'Accept': 'application/octet-stream'})
        request._workhub_deadline = deadline
        created_identity = None
        try:
            with build_opener(GitHubRedirects()).open(request, timeout=min(20.0, remaining)) as response:
                if response.status != 200 or not _github_url(response.geturl()):
                    raise ModuleInstallError('download_failed')
                length = response.headers.get('Content-Length', '')
                total = int(length) if length.isdigit() else None
                if total is not None and total > MAX_ARCHIVE:
                    raise ModuleInstallError('archive_too_large')
                output = destination.open('xb')
                with output:
                    st = os.fstat(output.fileno())
                    created_identity = (st.st_dev, st.st_ino)
                    size = 0
                    while True:
                        if cancelled.is_set():
                            raise ModuleInstallError('installer_closed')
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ModuleInstallError('download_timeout')
                        try:
                            response.fp.raw._sock.settimeout(min(10.0, remaining))
                        except AttributeError:
                            pass
                        chunk = response.read1(min(65536, MAX_ARCHIVE + 1 - size))
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_ARCHIVE:
                            raise ModuleInstallError('archive_too_large')
                        output.write(chunk)
                        progress(size, total)
                    if total is not None and size != total:
                        raise HTTPException('incomplete response')
                return
        except ModuleInstallError as error:
            code, retry = error.code, error.code == 'download_timeout'
        except (HTTPError, URLError, HTTPException, OSError, ValueError) as error:
            code, retry = _download_error(error)
        if created_identity is not None:
            # Remove only the temporary output created by this attempt.
            try:
                st = destination.lstat()
                if (st.st_dev, st.st_ino) == created_identity:
                    destination.unlink()
                else:
                    raise ModuleInstallError('storage_unsafe')
            except FileNotFoundError:
                pass
        if not retry or attempt or time.monotonic() + 0.5 >= deadline:
            raise ModuleInstallError(code) from None
        if cancelled.wait(0.5):
            raise ModuleInstallError('installer_closed')
        progress(0, None)


BUILD_BOOTSTRAP = r'''
import runpy,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'bin'))
sys.argv=[str(root/'bin/build_data.py'),*sys.argv[2:]]
runpy.run_path(str(root/'bin/build_data.py'),run_name='__main__')
'''
AI_BOOTSTRAP = r'''
import runpy,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'bin'))
sys.argv=[str(root/'bin/server.py'),*sys.argv[2:]]
runpy.run_path(str(root/'bin/server.py'),run_name='__main__')
'''

ENGLISH_BOOTSTRAP = r'''
import json,signal,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'bin'))
from serve import LibraryStore,make_handler,page,ThreadingHTTPServer
store=LibraryStore(Path(sys.argv[2]));server=None
try:
    store.get();page(parent_origin=sys.argv[3])
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(store,sys.argv[3]));server.daemon_threads=True
    store.acquire()
except (OSError,ValueError):
    if server:server.server_close()
    print(json.dumps({'error':'in_use'}),flush=True);raise SystemExit(2)
def stop(*_):raise KeyboardInterrupt
signal.signal(signal.SIGTERM,stop)
print(json.dumps({'module_id':'english-slices','port':server.server_port}),flush=True)
try:server.serve_forever(poll_interval=.2)
except KeyboardInterrupt:pass
finally:server.server_close();store.release()
'''


def _environment():
    # No API keys, startup hooks, PYTHONPATH or project environment reach child code.
    return {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP') if key in os.environ}


def _plain_directory(path, create=False):
    try:
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ModuleInstallError('storage_unsafe')
    except OSError:
        raise ModuleInstallError('storage_unsafe') from None


class ModuleInstaller:
    def __init__(self, workspace, parent_origin, *, downloader=None):
        self.workspace, self.store = workspace, workspace.store
        self.parent_origin = loopback_origin(parent_origin)
        self.directory = Path(self.store.directory) / 'modules'
        self.downloader = downloader
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._jobs, self._services = {}, {}
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='workhub-module')

    @staticmethod
    def _meta(module_id):
        try:
            return trusted_module(module_id)
        except ValueError:
            raise ModuleInstallError('unknown_module') from None

    def _site_ids(self, module_id):
        for row in module_catalog(self.workspace.sites())['modules']:
            if row['id'] == module_id:
                return row['site_ids']
        return []

    def _idle(self, module_id):
        return {'id': module_id, 'module_id': module_id, 'job_id': None, 'status': 'idle', 'stage': 'idle',
                'progress': 0, 'site_ids': [], 'error': None, 'message': '', 'created_at': None, 'updated_at': None}

    def _set(self, module_id, stage, progress, error=None, site_ids=None):
        with self._lock:
            job = self._jobs[module_id]
            job.update(status=stage, stage=stage, progress=progress, error=error,
                       message=ERRORS.get(error, ERRORS['install_failed']) if error else MESSAGES[stage], updated_at=stamp())
            if site_ids is not None:
                job['site_ids'] = list(site_ids)
            return deepcopy(job)

    def _check_owned_service(self):
        with self._lock:
            for module_id in ('english-slices', 'ai-opinion'):
                service = self._services.get(module_id)
                if service and service.get('process') and service['process'].poll() is not None:
                    if module_id in self._jobs and self._jobs[module_id]['status'] == 'completed':
                        self._set(module_id, 'failed', 100, 'service_stopped')
                    self._services.pop(module_id, None)
                    service['capsule'].cleanup()

    def status(self, module_id):
        self._meta(module_id)
        self._check_owned_service()
        with self._lock:
            return deepcopy(self._jobs.get(module_id) or self._idle(module_id))

    def catalog(self):
        self._check_owned_service()
        result = module_catalog(self.workspace.sites())
        with self._lock:
            completed_without_site = {row['id'] for row in result['modules'] if not row['site_ids']
                                      and self._jobs.get(row['id'], {}).get('status') == 'completed'}
            if completed_without_site:
                # The first membership read may have preceded a just-completed
                # connection. Recheck once before treating completion as history.
                refreshed = {row['id']: row['site_ids'] for row in module_catalog(self.workspace.sites())['modules']}
                for row in result['modules']:
                    if row['id'] in completed_without_site:
                        row['site_ids'] = refreshed[row['id']]
            for row in result['modules']:
                row['installable'] = not self._closed.is_set()
                row['installation'] = deepcopy(self._jobs.get(row['id']))
                if (not row['site_ids'] and row['installation'] is not None
                        and row['installation']['status'] == 'completed'):
                    row['installation'] = None  # Retain history in status(); never reconnect implicitly.
                row['needs_service'] = row['id'] in {'english-slices', 'ai-opinion'} and row['id'] not in self._services
                if row['needs_service'] and row['site_ids'] and row['installation'] is None:
                    row['installation'] = self._idle(row['id'])
        return result

    def start(self, module_id):
        meta = self._meta(module_id)
        with self._lock:
            if self._closed.is_set():
                raise ModuleInstallError('installer_closed', 503)
            previous = self._jobs.get(module_id)
            if previous and previous['status'] in ACTIVE:
                return deepcopy(previous)
            job = self._idle(module_id)
            job.update(job_id=uuid.uuid4().hex, status='queued', stage='queued', created_at=stamp(), updated_at=stamp(), message=MESSAGES['queued'])
            self._jobs[module_id] = job
            self._executor.submit(self._install, meta)
            return deepcopy(job)

    def _archive(self, meta, work):
        archive = work / 'package.zip'
        cache = self.directory / '.package-cache'
        _plain_directory(cache, create=True)
        cached = cache / (meta['sha256'] + '.zip')
        if cached.exists() or cached.is_symlink():
            raw = _regular_bytes(cached, MAX_ARCHIVE)
            if hashlib.sha256(raw).hexdigest() == meta['sha256']:
                archive.write_bytes(raw)
                return archive
        self._set(meta['id'], 'downloading', 8)
        def progress(done, total=None):
            fraction = done / max(1, total or MAX_ARCHIVE)
            self._set(meta['id'], 'downloading', min(34, 8 + int(26 * fraction)))
        if self.downloader:
            self.downloader(meta['download_url'], archive, progress)
        else:
            _network_download(meta['download_url'], archive, progress, self._closed)
        raw = _regular_bytes(archive, MAX_ARCHIVE, 'archive_too_large')
        self._set(meta['id'], 'verifying', 36)
        if hashlib.sha256(raw).hexdigest() != meta['sha256']:
            raise ModuleInstallError('checksum_mismatch')
        # The cache is installer-owned, expendable source material, never user data.
        descriptor, name = tempfile.mkstemp(prefix='.download-', dir=cache)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(raw)
            os.replace(name, cached)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return archive

    def _validate_existing(self, target, manifest, meta):
        _plain_directory(target)
        local = validate_manifest(_json(_regular_bytes(target / 'module.json', MAX_MANIFEST_BYTES, 'existing_install_invalid')), meta)
        if set(local['files']) != set(manifest['files']):
            raise ModuleInstallError('existing_install_invalid')
        for name in local['files']:
            relative = relative_path(name)
            current = target
            for part in relative.parts[:-1]:
                current = current / part
                _plain_directory(current)
            _regular_bytes(target.joinpath(*relative.parts), MAX_FILE, 'existing_install_invalid')
        data = target / 'data'
        if data.exists() or data.is_symlink():
            _plain_directory(data)

    def _run_builder(self, clean, target, module_id):
        args = []
        data = target / 'data'
        if module_id in {'auto-opinion', 'ai-opinion'}:
            args = ['--data-dir', str(data), '--output-dir', str(clean / 'site')]
        elif module_id == 'coding-graph':
            if (data / 'latest.json').exists():
                _regular_bytes(data / 'latest.json', MAX_FILE)
                args += ['--input', str(data / 'latest.json')]
            if (data / 'frontier.json').exists():
                _regular_bytes(data / 'frontier.json', MAX_FILE)
                args += ['--frontier', str(data / 'frontier.json')]
        elif module_id == 'industry-atlas':
            args = ['--parent-origin', self.parent_origin]
            if (data / 'atlas.json').exists():
                _regular_bytes(data / 'atlas.json', MAX_FILE)
                args += ['--input', str(data / 'atlas.json')]
        elif module_id == 'compute-search':
            source = data / 'latest.json'
            if source.exists() or source.is_symlink():
                _regular_bytes(source, MAX_FILE)
            else:
                source = clean / 'empty-snapshot.json'
                source.write_text(json.dumps({'schema_version': 1, 'module_id': 'compute-search', 'mode': 'live',
                                              'generated_at': stamp(), 'sources': [], 'items': []}))
            args = ['--input', str(source)]
        try:
            process = subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', BUILD_BOOTSTRAP, str(clean), *args],
                                       cwd=clean, env=_environment(), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                code = process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=3)
                raise ModuleInstallError('build_failed') from None
            if code:
                raise ModuleInstallError('build_failed')
        except OSError:
            raise ModuleInstallError('build_failed') from None
        page = _regular_bytes(clean / 'site' / 'index.html', MAX_FILE, 'build_failed')
        try:
            value = page.decode('utf-8')
        except UnicodeError:
            raise ModuleInstallError('build_failed') from None
        if module_id == 'compute-search' and not (data / 'latest.json').exists():
            # A freshly generated empty page is not a fresh market observation.
            value = re.sub(r'("generated_at"\s*:\s*)"[^"\n]*"', r'\1null', value, count=1)
        root = re.search(r'<html\b[^>]*>', value, re.I)
        if root is None:
            raise ModuleInstallError('build_failed')
        if module_id == 'ai-opinion' and 'data-workhub-parent-origin' in root.group(0).lower():
            parent_attr = re.search(r"\bdata-workhub-parent-origin\s*=\s*([\"'])(.*?)\1", root.group(0), re.I)
            if not parent_attr or html.unescape(parent_attr.group(2)) != self.parent_origin:
                raise ModuleInstallError('build_failed')
        if 'data-workhub-parent-origin=' not in root.group(0):
            replacement = root.group(0)[:-1] + ' data-workhub-parent-origin="' + html.escape(self.parent_origin, quote=True) + '">'
            value = value[:root.start()] + replacement + value[root.end():]
        (clean / 'site' / 'index.html').write_text(value, encoding='utf-8')
        return value.encode('utf-8')

    def _local_get(self, origin, route, limit):
        try:
            with build_opener(ProxyHandler({}), NoRedirects()).open(Request(origin + route, headers={'Accept': 'application/json, text/html'}), timeout=3) as response:
                if response.status != 200:
                    raise ModuleInstallError('service_failed')
                deadline, chunks, size = time.monotonic() + 6, [], 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ModuleInstallError('service_failed')
                    try:
                        response.fp.raw._sock.settimeout(min(3, remaining))
                    except AttributeError:
                        pass
                    chunk = response.read1(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk);size += len(chunk)
                    if size > limit:
                        raise ModuleInstallError('service_failed')
                return b''.join(chunks)
        except (OSError, URLError, HTTPException, ValueError):
            raise ModuleInstallError('service_failed') from None

    def _probe_english(self, origin):
        origin = loopback_origin(origin)
        payload = _json(self._local_get(origin, '/api/library', MAX_FILE), 'service_failed')
        library = payload.get('library') if isinstance(payload, dict) else None
        if (not isinstance(payload, dict) or payload.get('storage') != 'local-file' or not isinstance(library, dict)
                or library.get('module_id') != 'english-slices' or library.get('schema_version') != 1
                or not isinstance(library.get('words'), list) or not isinstance(library.get('phrases'), list)):
            raise ModuleInstallError('service_failed')
        page = self._local_get(origin, '/', MAX_FILE)
        if b'id="starter-data"' not in page or b'id="words-tab"' not in page or not re.search(br'"service_mode"\s*:\s*true', page):
            raise ModuleInstallError('service_failed')
        return origin + '/'

    def _existing_english(self, target):
        with self._lock:
            service = self._services.get('english-slices')
        if service and (not service.get('process') or service['process'].poll() is None):
            try:
                return self._probe_english(service['url'])
            except ModuleInstallError:
                pass
        # Reuse only already registered URLs for this exact module directory.
        for site in self.store.sites()[:2000]:
            if site.get('project_path') != str(target) or site.get('kind') != 'url':
                continue
            try:
                return self._probe_english(site.get('url'))
            except ModuleInstallError:
                continue
        return None

    def _launch_english(self, clean, target, capsule):
        data = target / 'data'
        if (data / '.server.lock').exists() or (data / '.server.lock').is_symlink():
            raise ModuleInstallError('in_use')
        try:
            process = subprocess.Popen([sys.executable, '-I', '-S', '-B', '-u', '-c', ENGLISH_BOOTSTRAP,
                                        str(clean), str(data), self.parent_origin], cwd=clean, env=_environment(),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            raise ModuleInstallError('service_failed') from None
        output = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: output.put(process.stdout.readline(512)), daemon=True).start()
        try:
            first = _json(output.get(timeout=12), 'service_failed')
            if first.get('error'):
                raise ModuleInstallError('in_use')
            port = first.get('port')
            if first.get('module_id') != 'english-slices' or type(port) is not int or not 1 <= port <= 65535:
                raise ModuleInstallError('service_failed')
            origin = self._probe_english('http://127.0.0.1:' + str(port))
            if process.poll() is not None or self._closed.is_set():
                raise ModuleInstallError('service_failed')
            with self._lock:
                if self._closed.is_set():
                    raise ModuleInstallError('installer_closed')
                self._services['english-slices'] = {'process': process, 'capsule': capsule, 'url': origin}
            return origin
        except ModuleInstallError:
            self._stop_process(process)
            raise
        except (queue.Empty, ValueError, AttributeError):
            self._stop_process(process)
            raise ModuleInstallError('service_failed') from None
        finally:
            if process.stdout:
                process.stdout.close()

    def _admitted_ai_target(self):
        """Select only one already-admitted AI project directly under modules/."""
        paths = set()
        for site in self.workspace.sites()[:2000]:
            raw = site.get('project_path')
            if not isinstance(raw, str):
                continue
            path = Path(raw)
            if path.parent != self.directory or not re.fullmatch(r'ai-opinion-[0-9]+(?:\.[0-9]+){2}', path.name):
                continue
            try:
                _plain_directory(path)
                manifest = _json(_regular_bytes(path / 'module.json', MAX_MANIFEST_BYTES, 'existing_install_invalid'))
                if (not isinstance(manifest, dict) or manifest.get('id') != 'ai-opinion'
                        or manifest.get('kind') != 'workhub-module' or manifest.get('schema_version') != 1):
                    continue
                data = path / 'data'
                if data.exists() or data.is_symlink():
                    _plain_directory(data)
                _plain_directory(path / 'site')
                paths.add(path)
            except ModuleInstallError:
                raise ModuleInstallError('existing_install_invalid') from None
        if len(paths) > 1:
            raise ModuleInstallError('existing_install_invalid')
        return next(iter(paths), None)

    def _probe_ai(self, origin, data):
        origin = loopback_origin(origin)
        payload = _json(self._local_get(origin, '/api/health', MAX_MANIFEST_BYTES), 'service_failed')
        expected = hashlib.sha256(str(data.resolve()).encode('utf-8')).hexdigest()
        if (not isinstance(payload, dict) or payload.get('module_id') != 'ai-opinion'
                or payload.get('status') != 'ok' or payload.get('data_dir_sha256') != expected):
            raise ModuleInstallError('service_failed')
        if b'id="report-data"' not in self._local_get(origin, '/', MAX_FILE):
            raise ModuleInstallError('service_failed')
        return origin + '/'

    @staticmethod
    def _ai_data_locked(data):
        """Check an existing lock without creating, deleting, or trusting its contents."""
        path = data / '.ai-opinion-service.lock'
        if not path.exists() and not path.is_symlink():
            return False
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                raise ModuleInstallError('storage_unsafe')
            fd = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            try:
                after = os.fstat(fd)
                if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    raise ModuleInstallError('storage_unsafe')
                if fcntl is None:
                    return False
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    return False
            finally:
                os.close(fd)
        except ModuleInstallError:
            raise
        except OSError:
            raise ModuleInstallError('storage_unsafe') from None

    def _launch_ai(self, clean, target, capsule):
        data = target / 'data'
        if data.exists() or data.is_symlink():
            _plain_directory(data)
        if self._ai_data_locked(data):
            raise ModuleInstallError('in_use')
        try:
            process = subprocess.Popen([sys.executable, '-I', '-S', '-B', '-u', '-c', AI_BOOTSTRAP, str(clean),
                                       '--host', '127.0.0.1', '--port', '0', '--data-dir', str(data),
                                       '--site-dir', str(clean / 'site'), '--config-dir', str(self.store.directory),
                                       '--parent-origin', self.parent_origin], cwd=clean, env=_environment(),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            raise ModuleInstallError('service_failed') from None
        output = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: output.put(process.stdout.readline(512)), daemon=True).start()
        try:
            first = _json(output.get(timeout=12), 'service_failed')
            if first.get('error') == 'in_use':
                raise ModuleInstallError('in_use')
            port = first.get('port')
            if first.get('module_id') != 'ai-opinion' or type(port) is not int or not 1 <= port <= 65535:
                raise ModuleInstallError('service_failed')
            origin = self._probe_ai('http://127.0.0.1:' + str(port), data)
            if process.poll() is not None or self._closed.is_set():
                raise ModuleInstallError('service_failed')
            with self._lock:
                if self._closed.is_set():
                    raise ModuleInstallError('installer_closed')
                self._services['ai-opinion'] = {'process': process, 'capsule': capsule, 'url': origin, 'target': target}
            return origin
        except (ModuleInstallError, queue.Empty, ValueError, AttributeError) as error:
            self._stop_process(process)
            if self._ai_data_locked(data):
                raise ModuleInstallError('in_use') from None
            if isinstance(error, ModuleInstallError):
                raise
            raise ModuleInstallError('service_failed') from None
        finally:
            if process.stdout:
                process.stdout.close()

    def _connect_existing_ai(self, target, meta, url):
        """Convert exactly one existing AI registration in-place; preserve its ID and metadata."""
        origin = loopback_origin(url)
        sites = [s for s in self.workspace.sites() if s.get('project_path') == str(target)]
        registered = [s for s in sites if (s.get('kind') == 'directory' and s.get('directory') == str(target / 'site'))]
        receipt_path = target / '.workhub-module-service.json'
        prior_raw = None
        if receipt_path.exists() or receipt_path.is_symlink():
            prior_raw = _regular_bytes(receipt_path, MAX_MANIFEST_BYTES)
            prior = _json(prior_raw, 'storage_unsafe')
            if (not isinstance(prior, dict) or prior.get('module_id') != 'ai-opinion'
                    or prior.get('schema_version') != 1 or not re.fullmatch(r'[0-9a-f]{24}', prior.get('site_id', ''))):
                raise ModuleInstallError('storage_unsafe')
            previous_url = loopback_origin(prior.get('url')) + '/'
            registered += [s for s in sites if s.get('id') == prior['site_id'] and s.get('kind') == 'url'
                           and s.get('url', '').rstrip('/') + '/' == previous_url]
        if len(registered) != 1:
            raise ModuleInstallError('connect_failed')
        row = registered[0]; site_id = row['id']
        receipt = {'schema_version': 1, 'module_id': meta['id'], 'version': meta['version'],
                   'sha256': meta['sha256'], 'site_id': site_id, 'url': origin + '/'}
        encoded = json.dumps(receipt).encode('utf-8')
        fd, name = tempfile.mkstemp(prefix='.module-service-', dir=target)
        moved = False
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            try:
                with self.store.connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    exact = db.execute('SELECT s.kind,s.url,s.directory FROM sites s JOIN projects p ON p.id=s.project_id JOIN workspace_projects w ON w.project_id=p.id WHERE s.id=? AND p.path=?', (site_id,str(target))).fetchone()
                    if exact is None or exact['kind'] != row['kind'] or exact['url'] != row['url'] or exact['directory'] != row['directory']:
                        raise ModuleInstallError('connect_failed')
                    db.execute("UPDATE sites SET kind='url',url=?,directory=NULL,updated_at=? WHERE id=?", (origin + '/',stamp(),site_id))
                    os.replace(name,receipt_path)
                    moved = True
            except Exception:
                # Restore only the receipt bytes this attempt wrote. Never remove
                # or overwrite an unrelated concurrent change.
                if moved:
                    try:
                        if _regular_bytes(receipt_path, MAX_MANIFEST_BYTES) == encoded:
                            if prior_raw is None:
                                receipt_path.unlink()
                            else:
                                prior_fd, prior_name = tempfile.mkstemp(prefix='.module-service-restore-', dir=target)
                                try:
                                    with os.fdopen(prior_fd, 'wb') as previous:
                                        previous.write(prior_raw)
                                    os.replace(prior_name, receipt_path)
                                finally:
                                    if os.path.exists(prior_name):os.unlink(prior_name)
                    except (OSError, ModuleInstallError):
                        pass
                raise
            return [site_id]
        finally:
            if os.path.exists(name):os.unlink(name)

    @staticmethod
    def _stop_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=2)

    def _previous_site(self, target, meta):
        receipt = target / '.workhub-module-service.json'
        if not receipt.exists() and not receipt.is_symlink():
            return None
        raw = _json(_regular_bytes(receipt, MAX_MANIFEST_BYTES), 'storage_unsafe')
        if (not isinstance(raw, dict) or raw.get('schema_version') != 1
                or raw.get('module_id') != meta['id'] or raw.get('version') != meta['version']
                or raw.get('sha256') != meta['sha256']
                or not isinstance(raw.get('site_id'), str) or not re.fullmatch(r'[0-9a-f]{24}', raw['site_id'])):
            raise ModuleInstallError('storage_unsafe')
        loopback_origin(raw.get('url'))
        return raw

    def _remember_site(self, target, meta, site_id, url):
        previous = self._previous_site(target, meta)
        # Delete only a URL registration this installer previously remembered
        # for this exact directory, after the new service has passed its checks.
        if previous and previous['site_id'] != site_id:
            for site in self.store.sites():
                if (site.get('id') == previous['site_id'] and site.get('project_path') == str(target)
                        and site.get('kind') == 'url' and site.get('url') == previous['url']):
                    self.store.site_remove(previous['site_id'])
                    break
        data = {'schema_version': 1, 'module_id': meta['id'], 'version': meta['version'],
                'sha256': meta['sha256'], 'site_id': site_id, 'url': url}
        descriptor, temporary = tempfile.mkstemp(prefix='.module-service-', dir=target)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(data, stream)
            os.replace(temporary, target / '.workhub-module-service.json')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _connect(self, target, meta, url=None):
        if self._closed.is_set():
            raise ModuleInstallError('installer_closed')
        try:
            current = next((project for project in self.workspace.projects() if project.get('path') == str(target)), None)
            name = current['name'] if current else meta['name']['zh-CN']
            agents = list(current['source_agents']) if current else ['other']
            theme_mode = current['theme_mode'] if current else 'original'
            site_name = meta['name']['zh-CN']
            if not url:
                registered = next((site for site in self.store.sites() if site.get('project_path') == str(target)
                                   and site.get('kind') == 'directory' and site.get('directory') == str(target / 'site')), None)
                if registered:
                    site_name = registered['name']
            self.workspace.add(str(target), name=name, agents=agents, theme_mode=theme_mode,
                               site={'kind': 'url' if url else 'directory', 'target': url or str(target / 'site'), 'name': site_name})
            rows = self.workspace.sites()
            ids = [s['id'] for s in rows if s.get('project_path') == str(target)
                   and ((url and s.get('url') == url) or (not url and s.get('directory') == str(target / 'site')))]
            if not ids:
                raise ModuleInstallError('connect_failed')
            if url:
                self._remember_site(target, meta, ids[0], url)
            return ids
        except (OSError, ValueError):
            raise ModuleInstallError('connect_failed') from None

    def _install(self, meta):
        module_id, capsule, keep_capsule, install_lock = meta['id'], None, False, None
        try:
            _plain_directory(self.directory, create=True)
            lock_path = self.directory / ('.install-' + module_id + '.lock')
            try:
                install_lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise ModuleInstallError('in_use') from None
            os.write(install_lock, str(os.getpid()).encode())
            capsule = tempfile.TemporaryDirectory(prefix='.module-install-', dir=self.directory)
            work = Path(capsule.name)
            archive = self._archive(meta, work)
            if self._closed.is_set():
                raise ModuleInstallError('installer_closed')
            self._set(module_id, 'verifying', 40)
            if hashlib.sha256(_regular_bytes(archive, MAX_ARCHIVE)).hexdigest() != meta['sha256']:
                raise ModuleInstallError('checksum_mismatch')
            clean, manifest = unpack_archive(archive, work, meta)
            self._set(module_id, 'installing', 52)
            admitted_ai = self._admitted_ai_target() if module_id == 'ai-opinion' else None
            target = admitted_ai or (self.directory / (module_id + '-' + meta['version']))
            existing = target.exists() or target.is_symlink()
            if existing:
                if not admitted_ai:
                    self._validate_existing(target, manifest, meta)
                if module_id == 'english-slices':
                    self._previous_site(target, meta)
            self._set(module_id, 'building', 65)
            if module_id == 'ai-opinion':
                self._run_builder(clean, target, module_id)
                if not existing:
                    shutil.copytree(clean, work / 'published')
                    if target.exists() or target.is_symlink():
                        raise ModuleInstallError('existing_install_invalid')
                    os.rename(work / 'published', target)
                with self._lock:
                    service = self._services.get(module_id)
                if service and service.get('target') == target and service.get('process') and service['process'].poll() is None:
                    url = self._probe_ai(service['url'], target / 'data')
                else:
                    url = self._launch_ai(clean, target, capsule)
                    keep_capsule = True
            elif module_id == 'english-slices':
                if not existing:
                    # Publish only verified source, then run a separate clean capsule.
                    self._run_builder(clean, target, module_id)
                    shutil.copytree(clean, work / 'published')
                    if target.exists() or target.is_symlink():
                        raise ModuleInstallError('existing_install_invalid')
                    os.rename(work / 'published', target)
                url = self._existing_english(target)
                if url is None:
                    url = self._launch_english(clean, target, capsule)
                    keep_capsule = True
                else:
                    with self._lock:
                        if module_id not in self._services:
                            self._services[module_id] = {'process': None, 'capsule': None, 'url': url, 'external': True}
            else:
                index = target / 'site' / 'index.html'
                if existing and (index.exists() or index.is_symlink()):
                    page = _regular_bytes(index, MAX_FILE, 'existing_install_invalid')
                    if b'<html' not in page.lower():
                        raise ModuleInstallError('existing_install_invalid')
                else:
                    page = self._run_builder(clean, target, module_id)
                    if not existing:
                        if target.exists() or target.is_symlink():
                            raise ModuleInstallError('existing_install_invalid')
                        os.rename(clean, target)
                    else:
                        _plain_directory(target / 'site')
                        # Never overwrite an existing page or any personal source/data.
                        with index.open('xb') as output:
                            output.write(page)
                url = None
            self._set(module_id, 'connecting', 90)
            ids = self._connect_existing_ai(target, meta, url) if module_id == 'ai-opinion' and admitted_ai else self._connect(target, meta, url)
            self._set(module_id, 'completed', 100, site_ids=ids)
        except ModuleInstallError as error:
            self._set(module_id, 'failed', 100, error.code)
        except Exception:
            # Private paths, URLs with signed CDN queries, tracebacks and output
            # from subprocesses never enter the public job response.
            self._set(module_id, 'failed', 100, 'install_failed')
        finally:
            if keep_capsule and self.status(module_id)['status'] != 'completed':
                with self._lock:
                    service = self._services.get(module_id)
                    if service and service.get('capsule') is capsule:
                        self._services.pop(module_id, None)
                if service and service.get('capsule') is capsule:
                    self._stop_process(service['process'])
                keep_capsule = False
            if capsule is not None and not keep_capsule:
                capsule.cleanup()
            if install_lock is not None:
                os.close(install_lock)
                lock_path.unlink(missing_ok=True)

    def close(self):
        self._closed.set()
        with self._lock:
            services = list(self._services.values())
            self._services.clear()
        for service in services:
            if service.get('process'):
                self._stop_process(service['process'])
            if service.get('capsule'):
                service['capsule'].cleanup()
        self._executor.shutdown(wait=False, cancel_futures=True)
