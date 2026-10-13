#!/usr/bin/env python3
"""Install the lifecycle logger skill, exp-run, and fallback hook."""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
HOME = Path.home()
DEST = HOME / ".agents" / "skills" / "experiment-daily-logger"
BIN = HOME / ".local" / "bin" / "exp-run"
HOOKS = HOME / ".codex" / "hooks.json"
REPORTS = Path(
    os.environ.get(
        "EXPERIMENT_DAILY_REPORT_DIR",
        str(HOME / "experiment-daily-report"),
    )
).expanduser()
HOOK_MARKER = "experiment-daily-logger/scripts/codex_hook.py"


def install_skill() -> None:
    DEST.parent.mkdir(parents=True, exist_ok=True)

    if DEST.exists():
        shutil.rmtree(DEST)

    shutil.copytree(
        SOURCE,
        DEST,
        ignore=shutil.ignore_patterns(
            ".git",
            ".gitignore",
            "tests",
            "__pycache__",
            "*.pyc",
            "*.pyo",
        ),
    )

    executable_files = (
        list((DEST / "scripts").glob("*.py"))
        + list((DEST / "bin").glob("*"))
    )
    for path in executable_files:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def install_bin() -> None:
    BIN.parent.mkdir(parents=True, exist_ok=True)
    BIN.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'exec python3 "{DEST / "scripts" / "experiment_logger.py"}" '
        'launch --source manual "$@"\n',
        encoding="utf-8",
    )
    BIN.chmod(BIN.stat().st_mode | stat.S_IXUSR)


def is_ours(group: dict) -> bool:
    return any(
        HOOK_MARKER in str(item.get("command", ""))
        for item in group.get("hooks", [])
    )


def install_hook() -> None:
    HOOKS.parent.mkdir(parents=True, exist_ok=True)

    if HOOKS.exists():
        shutil.copy2(
            HOOKS,
            HOOKS.with_name(
                f"hooks.json.bak-{datetime.now():%Y%m%d-%H%M%S}"
            ),
        )
        config = json.loads(HOOKS.read_text(encoding="utf-8"))
    else:
        config = {
            "description": "User-level Codex hooks.",
            "hooks": {},
        }

    hooks = config.setdefault("hooks", {})

    for event in list(hooks):
        groups = hooks[event]
        if isinstance(groups, list):
            groups = [group for group in groups if not is_ours(group)]
            if groups:
                hooks[event] = groups
            else:
                hooks.pop(event, None)

    hooks.setdefault("PreToolUse", []).append(
        {
            "matcher": "^Bash$",
            "hooks": [
                {
                    "type": "command",
                    "command": (
                        f'python3 "{DEST / "scripts" / "codex_hook.py"}"'
                    ),
                    "timeout": 30,
                    "statusMessage": "Recording experiment launch",
                }
            ],
        }
    )

    HOOKS.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    install_skill()
    install_bin()
    install_hook()
    REPORTS.mkdir(parents=True, exist_ok=True)

    print("安装完成。exp-run 会记录实验启动，并在命令结束后回写生命周期状态。")
    print(f"Skill: {DEST}")
    print(f"命令: {BIN}")
    print(f"Hook: {HOOKS}（仅兜底；无法观察结束，因此记录为 unknown）")
    print(f"日志: {REPORTS}")
    print("重启 Codex 后执行 /hooks 检查并信任 Hook。")

    if str(BIN.parent) not in os.environ.get("PATH", "").split(":"):
        print('请加入 ~/.bashrc：export PATH="$HOME/.local/bin:$PATH"')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
