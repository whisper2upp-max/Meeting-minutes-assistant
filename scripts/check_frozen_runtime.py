"""Run the actual frozen binary outside the checkout; fail builds on missing SDKs."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def check(executable: Path) -> None:
    executable = executable.resolve(strict=True)
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "DASHSCOPE_API_KEY", "DASHSCOPE_HTTP_BASE_URL"):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="meeting-runtime-") as directory:
        report = Path(directory) / "runtime.json"
        result = subprocess.run([str(executable), "--check-runtime", str(report)],
                                cwd=directory, env=env, timeout=120)
        if not report.exists():
            raise RuntimeError(f"Frozen application produced no report (exit {result.returncode})")
        data = json.loads(report.read_text(encoding="utf-8"))
        if result.returncode or not data.get("ok") or not data.get("frozen"):
            raise RuntimeError(f"Frozen runtime check failed: {data}")
        print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    check(Path(sys.argv[1]))
