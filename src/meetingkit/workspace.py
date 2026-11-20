"""Local workspace preferences and user-confirmed terminology; no API credentials."""
import json
import re
import threading
import unicodedata
from .config import config_dir

_lock = threading.RLock()
_DEFAULT = {"font_size": 15, "reduce_motion": False, "last_minutes": "", "terms": []}


def _key(value):
    return unicodedata.normalize('NFKC', value.strip()).casefold()


def _canonical_terms(rows):
    """Combine old from/to records and new tag records by the confirmed name."""
    if not isinstance(rows, list):
        raise ValueError('术语库格式无效')
    glossary = {}
    definitions = {}
    for row in rows:
        name = row['to'].strip()
        if not name or len(name) > 100:
            raise ValueError('准确名称必填，最多 100 字')
        key = _key(name)
        entry = glossary.setdefault(key, {'to': name, 'mistakes': [], 'aliases': []})
        for field in ('mistakes', 'aliases'):
            tags = row.get(field, [])
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                raise ValueError('术语标签格式无效')
            if field == 'mistakes' and 'from' in row:
                if not row['from'].strip():
                    raise ValueError('原词不能为空')
                tags = [row['from'], *tags]
            seen = {key, *map(_key, entry[field])}
            for tag in tags:
                tag = tag.strip()
                if len(tag) > 100:
                    raise ValueError('每个标签最多 100 字')
                if tag and _key(tag) not in seen:
                    entry[field].append(tag)
                    seen.add(_key(tag))
        meaning = (row.get('meaning') or '').strip()
        if meaning:
            definitions.setdefault(key, {})[meaning] = None
    if len(glossary) > 500:
        raise ValueError('术语库最多保存 500 个准确名称')
    for key, meanings in definitions.items():
        glossary[key]['meaning'] = '\n'.join(meanings)
    return list(glossary.values())


def _edit_glossary(terms, change):
    # Apply one edit inside the workspace lock, preserving other concurrent additions.
    old = change.get('previous')
    new = change.get('entry')
    rows = list(terms)
    if old is not None:
        if old not in rows:
            raise ValueError('这条术语已更新，请重新打开术语库再编辑')
        index = rows.index(old)
        rows.pop(index)
        if new is not None:
            target = next((term for term in rows if _key(term['to']) == _key(new['to'])), None)
            if target is not None:
                new = {**new, 'to': target['to']}
            rows.insert(index, new)
    elif new is not None:
        rows.append(new)
    return _canonical_terms(rows)


def read_workspace():
    with _lock:
        path = config_dir() / 'workspace.json'
        if not path.exists():
            return dict(_DEFAULT)
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('工作区配置格式无效')
        return {**_DEFAULT, **data, 'terms': _canonical_terms(data.get('terms', []))}


def matching_terms(terms, transcript):
    """Find glossary candidates in a normalized copy; keep the transcript intact."""
    text = unicodedata.normalize('NFKC', transcript).casefold()
    # Collapse whole runs of spoken initials so A F C is not found inside X A F C D.
    separate_initials = r'(?<![a-z0-9])[a-z](?:[. ·\t]+[a-z])+(?![a-z0-9])'
    text = re.sub(separate_initials, lambda m: re.sub(r'[. ·\t]', '', m[0]), text)
    found = {}

    def matches(name):
        if name in found:
            return found[name]
        key = unicodedata.normalize('NFKC', name).strip().casefold()
        if not key:
            return False
        pattern = re.escape(key)
        # ASR may spell Latin initials together, separately or with periods.
        if re.fullmatch(r'[a-z](?:[. ·\t]*[a-z0-9])+\.?', key):
            letters = re.sub(r'[. ·\t]', '', key)
            pattern = r'[. ·\t]*'.join(letters)
        if re.match('[a-z0-9]', key):
            pattern = r'(?<![a-z0-9])(?<![a-z0-9]\.)' + pattern
        if re.search(r'[a-z0-9]\.?$', key):
            pattern += r'(?![a-z0-9]|\.[a-z0-9])'
        found[name] = bool(re.search(pattern, text))
        return found[name]

    return [item for item in terms if any(matches(name) for name in (item['to'], *item.get('mistakes', []), *item.get('aliases', [])))]


def update_workspace(changes):
    with _lock:
        data = read_workspace()
        if 'font_size' in changes:
            size = int(changes['font_size'])
            if size not in (14, 15, 17):
                raise ValueError('请选择 14、15 或 17 号字体')
            data['font_size'] = size
        if 'reduce_motion' in changes:
            data['reduce_motion'] = bool(changes['reduce_motion'])
        if 'last_minutes' in changes:
            data['last_minutes'] = str(changes['last_minutes'])
        if 'terms' in changes:
            data['terms'] = _canonical_terms(changes['terms'])
        if 'glossary_edit' in changes:
            data['terms'] = _edit_glossary(data['terms'], changes['glossary_edit'])
        path = config_dir() / 'workspace.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
        return data
