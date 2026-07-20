#!/usr/bin/env python3
"""Append one launch-time Markdown entry without monitoring the experiment."""

from __future__ import annotations

import argparse
import fcntl
import os
import shlex
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_REPORT_DIR = Path.home() / "experiment-daily-report"
UNKNOWN_RESULT = "未识别（需要后补）"

RESULT_FLAGS = {
    "--output_dir", "--output-dir", "--output", "--out_dir", "--out-dir",
    "--save_dir", "--save-dir", "--save_path", "--save-path",
    "--result_dir", "--result-dir", "--results_dir", "--results-dir",
    "--work_dir", "--work-dir", "--logging_dir", "--logging-dir",
    "--log_dir", "--log-dir", "--checkpoint_dir", "--checkpoint-dir",
    "--run_dir", "--run-dir", "--experiment_dir", "--experiment-dir",
}


@dataclass
class ExperimentRecord:
    run_id: str
    source: str
    project_name: str
    project_dir: str
    launch_time: str
    summary: str
    command: str
    result_dir: str
    notes: str
    log_date: str


def now_local() -> datetime:
    return datetime.now().astimezone()


def report_dir() -> Path:
    return Path(
        os.environ.get("EXPERIMENT_DAILY_REPORT_DIR", str(DEFAULT_REPORT_DIR))
    ).expanduser()


def project_dir(value: Optional[str]) -> Path:
    return Path(value or os.getcwd()).expanduser().resolve()


def tokens(command: str | Iterable[str]) -> list[str]:
    if not isinstance(command, str):
        return list(command)
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def absolute_result(value: str, cwd: Path) -> str:
    value = value.strip().strip("\"'")
    if not value or value.lower() == "auto":
        return UNKNOWN_RESULT
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return str(path.resolve())


def infer_result(command: str | Iterable[str], cwd: Path) -> str:
    parts = tokens(command)
    for index, part in enumerate(parts):
        for flag in RESULT_FLAGS:
            if part.startswith(flag + "="):
                return absolute_result(part.split("=", 1)[1], cwd)
            if part == flag and index + 1 < len(parts):
                return absolute_result(parts[index + 1], cwd)

    environment_value = os.environ.get("OUTPUT_DIR") or os.environ.get("RESULT_DIR")
    return absolute_result(environment_value, cwd) if environment_value else UNKNOWN_RESULT


def automatic_summary(command: str) -> str:
    parts = tokens(command)
    entry = "实验命令"

    for part in parts:
        name = Path(part).name
        lowered = name.lower()
        if lowered.endswith((".py", ".sh")) or any(
            word in lowered
            for word in ("run", "experiment", "evaluate", "evaluation", "benchmark")
        ):
            entry = name
            break

    configuration_files = [
        Path(part).name
        for part in parts
        if part.lower().endswith((".yaml", ".yml", ".json", ".toml"))
    ][:3]

    overrides: list[str] = []
    index = 0
    while index < len(parts) and len(overrides) < 6:
        part = parts[index]
        if part.startswith("--") and part not in RESULT_FLAGS:
            if "=" in part:
                overrides.append(part)
            elif index + 1 < len(parts) and not parts[index + 1].startswith("-"):
                overrides.append(f"{part} {parts[index + 1]}")
                index += 1
            else:
                overrides.append(part)
        index += 1

    text = f"运行 {entry}"
    if configuration_files:
        text += "，使用配置 " + "、".join(configuration_files)
    if overrides:
        text += "，主要参数为 " + "、".join(overrides)
    return text + "。"


def render(record: ExperimentRecord) -> str:
    summary = record.summary.replace("\n", " ").strip()
    return f"""<!-- experiment:{record.run_id} -->
## {record.launch_time[11:19]} · {record.project_name}

- **实验 ID**：`{record.run_id}`
- **来源**：`{record.source}`
- **项目目录**：`{record.project_dir}`
- **启动时间**：{record.launch_time}
- **一句话改动**：{summary}
- **结果目录**：`{record.result_dir}`
- **命令**：

```bash
{record.command}
```

- **备注**：{record.notes or "无"}
"""


def append(record: ExperimentRecord) -> Path:
    directory = report_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.log_date}.md"

    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(f"# 实验日报 · {record.log_date}\n")
        handle.write("\n" + render(record))
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return path


def write_entry(
    *,
    source: str,
    summary: str,
    result_dir: str,
    project_dir_value: Optional[str],
    command: str,
    notes: str,
    launch_time: str = "",
    run_id: str = "",
) -> Path:
    cwd = project_dir(project_dir_value)
    launched = (
        datetime.fromisoformat(launch_time).astimezone()
        if launch_time
        else now_local()
    )
    output = (
        infer_result(command, cwd)
        if not result_dir or result_dir.lower() == "auto"
        else absolute_result(result_dir, cwd)
    )

    record = ExperimentRecord(
        run_id=run_id or f"{launched:%H%M%S}-{os.getpid()}-{uuid.uuid4().hex[:8]}",
        source=source,
        project_name=cwd.name,
        project_dir=str(cwd),
        launch_time=launched.isoformat(timespec="seconds"),
        summary=summary or automatic_summary(command),
        command=command or "未提供",
        result_dir=output,
        notes=notes,
        log_date=launched.date().isoformat(),
    )
    return append(record)


def remainder_command(parts: list[str]) -> str:
    if parts and parts[0] == "--":
        parts = parts[1:]
    if not parts:
        raise ValueError("缺少实验命令，请使用 `-- <command>`。")
    return shlex.join(parts)


def launch(args: argparse.Namespace) -> int:
    cwd = project_dir(args.project_dir)
    command = remainder_command(args.command)
    path = write_entry(
        source=args.source,
        summary=args.summary,
        result_dir=args.result_dir,
        project_dir_value=str(cwd),
        command=command,
        notes=args.notes,
        run_id=args.run_id,
    )
    print(f"[experiment-log] 已记录启动：{path}", file=sys.stderr)
    sys.stderr.flush()

    os.chdir(cwd)
    os.execv("/bin/bash", ["/bin/bash", "-c", command])
    return 127


def record(args: argparse.Namespace) -> int:
    path = write_entry(
        source=args.source,
        summary=args.summary,
        result_dir=args.result_dir,
        project_dir_value=args.project_dir,
        command=args.command_text,
        notes=args.notes,
        launch_time=args.launch_time,
        run_id=args.run_id,
    )
    print(path)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="一次性实验启动日志")
    subcommands = root.add_subparsers(dest="subcommand", required=True)

    launch_parser = subcommands.add_parser("launch")
    launch_parser.add_argument("--summary", default="")
    launch_parser.add_argument("--result-dir", default="auto")
    launch_parser.add_argument("--project-dir", default=None)
    launch_parser.add_argument(
        "--source",
        default="manual",
        choices=["manual", "codex", "recovered", "hook"],
    )
    launch_parser.add_argument("--notes", default="")
    launch_parser.add_argument("--run-id", default="")
    launch_parser.add_argument("command", nargs=argparse.REMAINDER)
    launch_parser.set_defaults(func=launch)

    record_parser = subcommands.add_parser("record")
    record_parser.add_argument("--summary", default="")
    record_parser.add_argument("--result-dir", default="auto")
    record_parser.add_argument("--project-dir", default=None)
    record_parser.add_argument(
        "--source",
        default="recovered",
        choices=["manual", "codex", "recovered", "hook"],
    )
    record_parser.add_argument("--launch-time", default="")
    record_parser.add_argument("--command", dest="command_text", default="")
    record_parser.add_argument("--notes", default="")
    record_parser.add_argument("--run-id", default="")
    record_parser.set_defaults(func=record)

    return root


def main() -> int:
    root = parser()
    args = root.parse_args()

    try:
        return int(args.func(args))
    except ValueError as exc:
        root.error(str(exc))
    except Exception as exc:
        print(f"[experiment-log] 错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
