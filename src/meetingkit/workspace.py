"""Local workspace preferences and user-confirmed terminology; no API credentials."""
import json
import threading
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
            data['terms'] = list(cleaned.values())
        path = config_dir() / 'workspace.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
        return data
