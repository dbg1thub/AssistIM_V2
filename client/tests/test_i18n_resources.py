import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ZH_CN_PATH = PROJECT_ROOT / "client" / "resources" / "i18n" / "zh-CN.json"
SCAN_DIRS = (
    PROJECT_ROOT / "client" / "ui",
    PROJECT_ROOT / "client" / "managers",
    PROJECT_ROOT / "client" / "services",
    PROJECT_ROOT / "client" / "storage",
)
TR_KEY_PATTERN = re.compile(r"\btr\(\s*['\"]([^'\"]+)['\"]\s*,")


def test_zh_cn_contains_all_tr_keys_used_by_client_code():
    zh_cn = json.loads(ZH_CN_PATH.read_text(encoding="utf-8"))
    assert isinstance(zh_cn, dict)

    used_keys: set[str] = set()
    for scan_dir in SCAN_DIRS:
        for file_path in scan_dir.rglob("*.py"):
            used_keys.update(TR_KEY_PATTERN.findall(file_path.read_text(encoding="utf-8")))

    missing = sorted(key for key in used_keys if key not in zh_cn)
    assert missing == []
