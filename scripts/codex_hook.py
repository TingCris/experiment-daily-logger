#!/usr/bin/env python3
"""PreToolUse-only fallback logger. It never observes command completion."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from experiment_logger import (
    automatic_summary,
    infer_result,
    project_dir,
    write_entry,
)

POSITIVE_PATTERNS = [
    r"(^|\s)(python\d*|python|bash|sh)\s+[^;&|]*(run|experiment|evaluate|evaluation|benchmark|ablation)",
    r"(^|\s)(sbatch|srun)(\s|$)",
]
NEGATIVE_PATTERNS = [
    r"experiment_logger\.py",
    r"(^|\s)exp-run(\s|$)",
    r"(^|\s)(pytest|unittest|npm test|cargo test)(\s|$)",
]


def is_experiment(command: str) -> bool:
    if os.environ.get("EXPERIMENT_LOG_FORCE") == "1":
        return True

    if any(
        re.search(pattern, command, re.IGNORECASE)
        for pattern in NEGATIVE_PATTERNS
    ):
        return False

    return any(
        re.search(pattern, command, re.IGNORECASE)
        for pattern in POSITIVE_PATTERNS
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("hook_event_name") != "PreToolUse":
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else ""

    if not isinstance(command, str) or not is_experiment(command):
        return 0

    try:
        cwd = project_dir(payload.get("cwd"))
        path = write_entry(
            source="hook",
            summary=automatic_summary(command),
            result_dir=infer_result(command, cwd),
            project_dir_value=str(cwd),
            command=command,
            notes="由 Codex PreToolUse Hook 在启动前一次性记录，不追踪后续状态。",
            run_id=f"codex-{payload.get('tool_use_id') or os.getpid()}",
        )
        print(
            json.dumps(
                {"systemMessage": f"实验启动信息已写入：{path}"},
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {"systemMessage": f"实验启动日志写入失败：{exc}"},
                ensure_ascii=False,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
