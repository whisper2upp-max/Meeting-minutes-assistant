"""Local workspace preferences and user-confirmed terminology; no API credentials."""
import json
import re
import threading
import unicodedata
from .config import config_dir

_lock = threading.RLock()
_DEFAULT = {"font_size": 15, "reduce_motion": False, "last_minutes": "", "terms": []}


def read_workspace():
    with _lock:
        path = config_dir() / 'workspace.json'
        if not path.exists():
            return dict(_DEFAULT)
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('工作区配置格式无效')
        return {**_DEFAULT, **data}


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

    return [item for item in terms if any(matches(name) for name in (item['from'], item['to'], *item.get('aliases', [])))]


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
            terms = changes['terms']
            if not isinstance(terms, list) or len(terms) > 500:
                raise ValueError('术语库最多保存 500 条')
            cleaned = {}
            for item in terms:
                original = str(item.get('from', '')).strip()
                replacement = str(item.get('to', '')).strip()
                if not original or not replacement or max(len(original), len(replacement)) > 100:
                    raise ValueError('原词与准确名称均需填写，最多 100 字')
                cleaned[original] = {'from': original, 'to': replacement}
                aliases = item.get('aliases', [])
                if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                    raise ValueError('其他别名需按名称填写')
                aliases = list(dict.fromkeys(a.strip() for a in aliases if a.strip() not in ('', original, replacement)))
                if len(aliases) > 20 or any(len(a) > 100 for a in aliases):
                    raise ValueError('最多可填 20 个其他别名，每个最多 100 字')
                if aliases:
                    cleaned[original]['aliases'] = aliases
                meaning = str(item.get('meaning') or '').strip()
                if len(meaning) > 500:
                    raise ValueError('含义与使用场景最多 500 字')
                if meaning:
                    cleaned[original]['meaning'] = meaning
            data['terms'] = list(cleaned.values())
        path = config_dir() / 'workspace.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
        return data
