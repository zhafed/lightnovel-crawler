#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build lightnovel-crawler source index to use for update checking.
"""
import hashlib
import json
import re
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from pathlib import Path

PYPI_JSON_URL = 'https://pypi.org/pypi/lightnovel-crawler/json'
SOURCE_URL_PREFIX = 'https://github.com/dipu-bd/lightnovel-crawler/master/%s'
HISTORY_URL_PREFIX = 'https://github.com/dipu-bd/lightnovel-crawler/commits/master/%s'
SOURCE_DOWNLOAD_URL_PREFIX = 'https://raw.githubusercontent.com/dipu-bd/lightnovel-crawler/master/%s'
WHEEL_RELEASE_URL = 'https://github.com/dipu-bd/lightnovel-crawler/releases/download/v%s/lightnovel_crawler-%s-py3-none-any.whl'

WORKDIR = Path(__file__).parent.parent.absolute()

SOURCES_FOLDER = WORKDIR / 'sources'
INDEX_FILE = SOURCES_FOLDER / '_index.json'
REJECTED_FILE = SOURCES_FOLDER / '_rejected.json'

README_FILE = WORKDIR / 'README.md'
SUPPORTED_SOURCE_LIST_QUE = '<!-- auto generated supported sources list -->'
REJECTED_SOURCE_LIST_QUE = '<!-- auto generated rejected sources list -->'

DATE_FORMAT = '%d %B %Y %I:%M:%S %p'

INDEX_DATA = {
    'v': int(time.time()),
    'app': {
        'windows': 'https://rebrand.ly/lncrawl',
        'linux': 'https://rebrand.ly/lncrawl-linux',
    },
    'rejected': {},
    'supported': {},
    'crawlers': {},
}

executor = ThreadPoolExecutor(8)

# =========================================================================================== #
# The index data
# =========================================================================================== #

print('-' * 50)
with urlopen(PYPI_JSON_URL) as fp:
    pypi_data = json.load(fp)

latest_version = pypi_data['info']['version']
INDEX_DATA['app']['version'] = latest_version
INDEX_DATA['app']['home'] = pypi_data['info']['home_page']
INDEX_DATA['app']['pypi'] = pypi_data['info']['release_url']
INDEX_DATA['app']['release'] = pypi_data['releases'][latest_version]
print('Latest version', latest_version)
print('-' * 50)

# =========================================================================================== #
# Generate sources index
# =========================================================================================== #

try:
    sys.path.insert(0, str(WORKDIR))
    from lncrawl.sources import load_crawlers
    from lncrawl.assets.user_agents import user_agents
except ImportError:
    traceback.print_exc()
    exit(1)

assert SOURCES_FOLDER.is_dir()

with open(REJECTED_FILE, encoding='utf8') as fp:
    rejected_sources = json.load(fp)


def git_history(file_path):
    try:
        cmd = 'git log --follow --diff-filter=AMT --pretty="%%at||%%aN||%%aE||%%s" "%s"' % file_path
        # cmd = 'git log -1 --diff-filter=AMT --pretty="%%at||%%aN||%%aE||%%s" "%s"' % file_path
        logs = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
        logs = [line.strip().split('||', maxsplit=4) for line in logs.splitlines(False)]
        logs = [{'time': int(x[0]), 'author': x[1], 'email': x[2], 'subject': x[3]} for x in logs]
        return logs
    except Exception:
        traceback.print_exc()
        return {}


name_alias = {
    'Sudipto Chandra': 'dipu-bd',
    'Sudipto Chandra Dipu': 'dipu-bd'
}


def process_contributors(history):
    global email_to_name
    for data in history:
        aN = data['author']
        aE = data['email']
        name_alias.setdefault(aN, aN)
        name_alias.setdefault(aE, aN)
        if len(aN) < len(name_alias[aE]):
            name_alias[aE] = aN


def process_file(py_file: Path) -> float:
    if py_file.name[0] == '_':
        return 0

    start = time.time()
    relative_path = py_file.relative_to(WORKDIR).as_posix()
    download_url = SOURCE_DOWNLOAD_URL_PREFIX % relative_path

    history = git_history(relative_path)
    process_contributors(history)

    with open(py_file, 'rb') as f:
        md5 = hashlib.md5(f.read()).hexdigest()

    for info in load_crawlers(py_file):
        info['id'] = hashlib.md5(download_url.encode()).hexdigest()
        info['file_path'] = str(relative_path)
        info['url'] = download_url
        info['md5'] = md5
        info['version'] = history[0]['time']
        info['total_commits'] = len(history)
        # info['last_commit'] = history[0]
        # info['first_commit'] = history[-1]
        # info['author'] = history[-1]['author']
        info['contributors'] = list(set([name_alias[x['email']] for x in history]))

        INDEX_DATA['crawlers'][info['id']] = info
        for url in info['base_urls']:
            if url in rejected_sources:
                INDEX_DATA['rejected'][url] = rejected_sources[url]
            else:
                INDEX_DATA['supported'][url] = info['id']

    return time.time() - start


futures = {}
for py_file in sorted(SOURCES_FOLDER.glob('**/*.py')):
    futures[py_file] = executor.submit(process_file, py_file)
for py_file, future in futures.items():
    print('> %-40s' % py_file.name, end='')
    runtime = future.result()
    print('%.3fs' % runtime)

print('-' * 50)
print('%d crawlers.' % len(INDEX_DATA['crawlers']),
      '%d supported urls.' % len(INDEX_DATA['supported']),
      '%d rejected urls.' % len(INDEX_DATA['rejected']))
print('-' * 50)

with open(INDEX_FILE, 'w', encoding='utf8') as fp:
    json.dump(INDEX_DATA, fp)  # , indent='  ')

# =========================================================================================== #
# Update README.md
# =========================================================================================== #

print('Rendering supported and rejected source list for README.md...')

with open(README_FILE, encoding='utf8') as fp:
    readme_text = fp.read()

before, supported, after = readme_text.split(SUPPORTED_SOURCE_LIST_QUE)
supported = '\n\n<table>\n<tbody>\n'
supported += '<tr>'
supported += '<th></th>\n'
supported += '<th>Source URL</th>\n'
supported += '<th>Version</th>\n'
# supported += '<th>Created At</th>\n'
supported += '<th>Contributors</th>\n'
supported += '</tr>\n'
for url, crawler_id in sorted(INDEX_DATA['supported'].items(), key=lambda x: x[0]):
    info = INDEX_DATA['crawlers'][crawler_id]
    source_url = SOURCE_URL_PREFIX % info['file_path']
    # history_url = HISTORY_URL_PREFIX % info['file_path']
    # created_at = datetime.fromtimestamp(info['first_commit']['time']).strftime(DATE_FORMAT)

    supported += '<tr>'
    supported += '<td>'
    supported += '<span title="Supports searching">%s</span>' % ('🔍' if info['can_search'] else '')
    supported += '<span title="Supports login">%s</span>' % ('🔑' if info['can_login'] else '')
    supported += '</td>\n'
    supported += '<td><a href="%s" target="_blank">%s</a></td>\n' % (url, url)
    supported += '<td><a href="%s">%s</a></td>\n' % (source_url, info['version'])
    # supported += '<td><a href="%s">%s</a></td>\n' % (history_url, created_at)
    supported += '<td>%s</td>\n' % ', '.join(list(set([name_alias[x]
                                             for x in info['contributors']])))
    supported += '</tr>\n'
supported += '</tbody>\n</table>\n\n'
readme_text = SUPPORTED_SOURCE_LIST_QUE.join([before, supported, after])

print('Generated supported sources list.')

before, rejected, after = readme_text.split(REJECTED_SOURCE_LIST_QUE)
rejected = '\n\n<table>\n<tbody>\n'
rejected += '<tr>'
rejected += '<th>Source URL</th>\n'
rejected += '<th>Rejection Cause</th>\n'
rejected += '</tr>\n'
for url, cause in sorted(INDEX_DATA['rejected'].items(),  key=lambda x: x[0]):
    rejected += '<tr>'
    rejected += '<td><a href="%s" target="_blank">%s</a></td>\n' % (url, url)
    rejected += '<td>%s</td>\n' % cause
    rejected += '</tr>\n'
rejected += '</tbody>\n</table>\n\n'
readme_text = REJECTED_SOURCE_LIST_QUE.join([before, rejected, after])

print('Generated rejected sources list.')

with open(README_FILE, 'w', encoding='utf8') as fp:
    fp.write(readme_text)

print('-' * 50)

executor.shutdown()
