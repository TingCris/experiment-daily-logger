#!/usr/bin/env python3
"""PreToolUse fallback logger; it cannot observe command completion."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from experiment_logger import automatic_summary, new_record, report_dir, report_lock, save_record

POSITIVE_PATTERNS = [
    r"(^|\s)(python\d*|python|bash|sh)\s+[^;&|]*(run|train|experiment|evaluate|evaluation|benchmark|ablation)",
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
    if any(re.search(pattern, command, re.IGNORECASE) for pattern in NEGATIVE_PATTERNS):
        return False
    return any(re.search(pattern, command, re.IGNORECASE) for pattern in POSITIVE_PATTERNS)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str) or not is_experiment(command):
        return 0

    try:
        args = argparse.Namespace(
            project_dir=payload.get("cwd"),
            launch_time="",
            run_id=f"codex-{payload.get('tool_use_id') or os.getpid()}",
            title="",
            purpose="",
            changes=automatic_summary(command),
            summary="",
            baseline="",
            tag=["hook-fallback"],
            result_dir=["auto"],
            source="hook",
            notes="PreToolUse Hook 只能确认命令将被启动，不能观察结束状态。请人工核对或改用 exp-run。",
            status_reason="Hook 未获得命令结束事件，完成状态不可知。",
        )
        record = new_record(args, command, status="unknown")
        with report_lock():
            save_record(record)
        message = f"已用 UNKNOWN 状态补记实验：{record['run_id']}；日报：{report_dir()}"
        print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"systemMessage": f"实验日志写入失败：{exc}"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
