#!/usr/bin/env python3
"""Evidence-oriented experiment lifecycle logger.

JSON run records are the source of truth. Daily Markdown is a deterministic,
human-readable projection that is updated in place as a run changes state.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

SCHEMA_VERSION = 2
DEFAULT_REPORT_DIR = Path.home() / "experiment-daily-report"
UNKNOWN_RESULT = "未识别（需要后补）"
UNKNOWN_TEXT = "未提供"
STATUSES = ("running", "completed", "failed", "interrupted", "discarded", "unknown")
TERMINAL_STATUSES = set(STATUSES) - {"running"}
STATUS_LABELS = {
    "running": "RUNNING · 运行中",
    "completed": "COMPLETED · 已完整结束",
    "failed": "FAILED · 失败",
    "interrupted": "INTERRUPTED · 中途终止",
    "discarded": "DISCARDED · 已丢弃",
    "unknown": "UNKNOWN · 结束状态未知",
}
SHORT_STATUS_LABELS = {
    "running": "运行中", "completed": "已完成", "failed": "失败",
    "interrupted": "已中止", "discarded": "已丢弃", "unknown": "待核实",
}
RESULT_FLAGS = {
    "--output_dir", "--output-dir", "--output", "--out_dir", "--out-dir",
    "--save_dir", "--save-dir", "--save_path", "--save-path",
    "--result_dir", "--result-dir", "--results_dir", "--results-dir",
    "--work_dir", "--work-dir", "--logging_dir", "--logging-dir",
    "--log_dir", "--log-dir", "--checkpoint_dir", "--checkpoint-dir",
    "--run_dir", "--run-dir", "--experiment_dir", "--experiment-dir",
}


def now_local() -> datetime:
    return datetime.now().astimezone()


def report_dir() -> Path:
    return Path(os.environ.get("EXPERIMENT_DAILY_REPORT_DIR", str(DEFAULT_REPORT_DIR))).expanduser()


def state_dir() -> Path:
    return report_dir() / ".experiment-daily-logger"


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


def infer_results(command: str | Iterable[str], cwd: Path) -> list[str]:
    parts = tokens(command)
    results: list[str] = []
    for index, part in enumerate(parts):
        for flag in RESULT_FLAGS:
            if part.startswith(flag + "="):
                results.append(absolute_result(part.split("=", 1)[1], cwd))
            elif part == flag and index + 1 < len(parts):
                results.append(absolute_result(parts[index + 1], cwd))
    environment_value = os.environ.get("OUTPUT_DIR") or os.environ.get("RESULT_DIR")
    if environment_value:
        results.append(absolute_result(environment_value, cwd))
    return list(dict.fromkeys(results)) or [UNKNOWN_RESULT]


def automatic_title(command: str) -> str:
    for part in tokens(command):
        name = Path(part).name
        lowered = name.lower()
        if lowered.endswith((".py", ".sh")) or any(
            word in lowered for word in ("run", "train", "experiment", "evaluate", "benchmark")
        ):
            return name
    return "未命名实验"


def automatic_summary(command: str) -> str:
    """Conservative compatibility fallback; never states an unstated purpose."""
    parts = tokens(command)
    title = automatic_title(command)
    configs = [Path(p).name for p in parts if p.lower().endswith((".yaml", ".yml", ".json", ".toml"))][:3]
    overrides: list[str] = []
    index = 0
    while index < len(parts) and len(overrides) < 8:
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
    text = f"执行 {title}"
    if configs:
        text += "，配置文件为 " + "、".join(configs)
    if overrides:
        text += "，显式参数为 " + "、".join(overrides)
    return text + "。"


def git_state(cwd: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"commit": None, "branch": None, "dirty": None}
    try:
        result["commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, text=True, capture_output=True, timeout=5, check=True
        ).stdout.strip()
        result["branch"] = subprocess.run(
            ["git", "branch", "--show-current"], cwd=cwd, text=True, capture_output=True, timeout=5, check=True
        ).stdout.strip() or "detached"
        result["dirty"] = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=cwd, text=True, capture_output=True, timeout=5, check=True
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return result


@contextlib.contextmanager
def report_lock(timeout: float = 15.0) -> Iterator[None]:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "write.lock"
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"pid": os.getpid(), "time": time.time()}).encode("utf-8"))
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 300:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待日志锁超时：{lock}")
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


def record_path(record: dict[str, Any]) -> Path:
    return state_dir() / "runs" / record["started_at"][:10] / f"{record['run_id']}.json"


def save_record(record: dict[str, Any]) -> None:
    record["updated_at"] = now_local().isoformat(timespec="seconds")
    atomic_write(record_path(record), json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    upsert_markdown(record)


def iter_record_paths() -> Iterator[Path]:
    root = state_dir() / "runs"
    if root.exists():
        yield from root.glob("*/*.json")


def load_record(run_id: str) -> tuple[dict[str, Any], Path]:
    direct = Path(run_id)
    matches = [direct] if direct.is_file() else [
        p for p in iter_record_paths() if p.stem == run_id or p.stem.startswith(run_id)
    ]
    if not matches:
        raise ValueError(f"未找到实验 ID：{run_id}")
    if len(matches) > 1:
        raise ValueError(f"实验 ID 前缀不唯一：{run_id}")
    return json.loads(matches[0].read_text(encoding="utf-8")), matches[0]


def duration_text(record: dict[str, Any]) -> str:
    if not record.get("ended_at"):
        return "—"
    try:
        start = datetime.fromisoformat(record["started_at"])
        end = datetime.fromisoformat(record["ended_at"])
        seconds = max(0, int((end - start).total_seconds()))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "—"


def md_text(value: Any, default: str = UNKNOWN_TEXT) -> str:
    text = str(value).replace("\n", " ").strip() if value is not None else ""
    return (text or default).replace("|", "\\|")


def render_record(record: dict[str, Any]) -> str:
    status = record["status"]
    result_dirs = record.get("result_dirs") or [UNKNOWN_RESULT]
    changes = md_text(record.get("changes"), "待补充")
    if record.get("baseline"):
        changes += f"；对照：{md_text(record['baseline'])}"
    lines = [
        f"<!-- experiment:{record['run_id']} -->",
        f"## {record['started_at'][11:16]} · [{SHORT_STATUS_LABELS.get(status, status)}] {md_text(record.get('title'), '未命名实验')}",
        "",
        f"- 改动：{changes}",
    ]
    if record.get("purpose"):
        lines.append(f"- 目的：{md_text(record['purpose'])}")
    metrics = record.get("metrics") or []
    result_parts = []
    for metric in metrics:
        value = f"{md_text(metric.get('name'))}={md_text(metric.get('value'))}"
        if not metric.get("source") or metric["source"] == UNKNOWN_TEXT:
            value += "（缺证据）"
        result_parts.append(value)
    if record.get("conclusion"):
        result_parts.append(md_text(record["conclusion"]))
    if result_parts:
        label = "结果" if status == "completed" else "结果（不纳入正式比较）"
        lines.append(f"- {label}：{'；'.join(result_parts)}")
    elif status == "completed":
        lines.append("- 结果：待登记")
    lines.append(f"- 输出：{'；'.join(f'`{item}`' for item in result_dirs)}")
    if status not in {"completed", "running"}:
        lines.append(f"- 原因：{md_text(record.get('status_reason'), '待补充')}")

    day = record["started_at"][:10]
    record_link = f".experiment-daily-logger/runs/{day}/{record['run_id']}.json"
    lines += [
        "",
        f"记录：[{record['run_id']}]({record_link})",
        "",
        "<details>",
        "<summary>命令与证据</summary>",
        "",
        f"- 项目：`{record['project_dir']}`",
    ]
    if metrics:
        for metric in metrics:
            lines.append(f"- 证据（{md_text(metric.get('name'))}）：`{metric.get('source') or UNKNOWN_TEXT}`")
    artifacts = record.get("artifacts") or []
    if artifacts:
        artifact_text = "；".join(f"`{item.get('path')}`" for item in artifacts)
        lines.append(f"- 产物：{artifact_text}")
    if record.get("notes"):
        lines.append(f"- 备注：{md_text(record['notes'])}")
    command = record.get("command") or "未提供"
    fence = "```"
    while fence in command:
        fence += "`"
    lines += [
        "",
        fence + "bash",
        command,
        fence,
        "",
        "</details>",
        "",
        f"<!-- /experiment:{record['run_id']} -->",
    ]
    return "\n".join(lines) + "\n"


def render_daily_summary(day: str) -> str:
    counts = dict.fromkeys(STATUSES, 0)
    directory = state_dir() / "runs" / day
    if directory.exists():
        for path in directory.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                status = item.get("status", "unknown")
                counts[status] = counts.get(status, 0) + 1
            except (OSError, ValueError, KeyError):
                continue
    summary = " · ".join(
        f"{SHORT_STATUS_LABELS[status]} {counts[status]}"
        for status in ("completed", "running", "failed", "interrupted", "discarded", "unknown")
        if counts[status]
    )
    return "\n".join([
        "<!-- experiment-summary:start -->", summary or "暂无结构化记录",
        "<!-- experiment-summary:end -->", "", "",
    ])


def upsert_daily_summary(content: str, day: str) -> str:
    start_marker = "<!-- experiment-summary:start -->"
    end_marker = "<!-- experiment-summary:end -->"
    summary = render_daily_summary(day)
    start = content.find(start_marker)
    if start >= 0:
        end = content.find(end_marker, start)
        if end >= 0:
            end += len(end_marker)
            while end < len(content) and content[end] == "\n":
                end += 1
            return content[:start].rstrip() + "\n\n" + summary + content[end:].lstrip("\n")
    first_line_end = content.find("\n")
    if first_line_end >= 0:
        return content[: first_line_end + 1].rstrip() + "\n\n" + summary + content[first_line_end + 1 :].lstrip("\n")
    return content.rstrip() + "\n\n" + summary


def upsert_markdown(record: dict[str, Any]) -> None:
    day = record["started_at"][:10]
    path = report_dir() / f"{day}.md"
    content = path.read_text(encoding="utf-8") if path.exists() else f"# 实验日报 · {day}\n"
    start_marker = f"<!-- experiment:{record['run_id']} -->"
    end_marker = f"<!-- /experiment:{record['run_id']} -->"
    block = render_record(record)
    start = content.find(start_marker)
    if start >= 0:
        end = content.find(end_marker, start)
        if end >= 0:
            end += len(end_marker)
            while end < len(content) and content[end] == "\n":
                end += 1
        else:
            next_marker = content.find("<!-- experiment:", start + len(start_marker))
            end = next_marker if next_marker >= 0 else len(content)
        content = content[:start].rstrip() + "\n\n" + block + content[end:].lstrip("\n")
    else:
        content = content.rstrip() + "\n\n" + block
    content = upsert_daily_summary(content, day)
    atomic_write(path, content.rstrip() + "\n")


def result_paths(values: list[str], command: str, cwd: Path) -> list[str]:
    explicit = [absolute_result(value, cwd) for value in values if value.lower() != "auto"]
    inferred = infer_results(command, cwd) if not values or any(v.lower() == "auto" for v in values) else []
    return list(dict.fromkeys(explicit + inferred)) or [UNKNOWN_RESULT]


def new_record(args: argparse.Namespace, command: str, status: str = "running") -> dict[str, Any]:
    cwd = project_dir(args.project_dir)
    started = datetime.fromisoformat(args.launch_time).astimezone() if args.launch_time else now_local()
    run_id = args.run_id or f"{started:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    changes = args.changes or args.summary or automatic_summary(command)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "title": args.title or automatic_title(command),
        "status": status,
        "status_reason": getattr(args, "status_reason", "") or "",
        "source": args.source,
        "project_name": cwd.name,
        "project_dir": str(cwd),
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": None,
        "updated_at": started.isoformat(timespec="seconds"),
        "purpose": args.purpose or "",
        "changes": changes,
        "baseline": args.baseline or "",
        "tags": list(dict.fromkeys(args.tag or [])),
        "command": command or "未提供",
        "result_dirs": result_paths(args.result_dir or [], command, cwd),
        "git": git_state(cwd),
        "host": socket.gethostname(),
        "pid": None,
        "exit_code": None,
        "metrics": [],
        "artifacts": [],
        "result_snapshots": [],
        "conclusion": "",
        "notes": args.notes or "",
        "events": [{"at": started.isoformat(timespec="seconds"), "type": "created", "status": status}],
    }


def snapshot_path(value: str, limit: int = 10000) -> dict[str, Any]:
    path = Path(value)
    snapshot: dict[str, Any] = {"path": value, "exists": path.exists(), "file_count": 0, "total_bytes": 0, "truncated": False}
    if not path.exists() or value == UNKNOWN_RESULT:
        return snapshot
    files = [path] if path.is_file() else path.rglob("*")
    for item in files:
        if snapshot["file_count"] >= limit:
            snapshot["truncated"] = True
            break
        try:
            if item.is_file():
                snapshot["file_count"] += 1
                snapshot["total_bytes"] += item.stat().st_size
        except OSError:
            continue
    return snapshot


def artifact_info(value: str, cwd: Path) -> dict[str, Any]:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = cwd / path
    path = path.resolve()
    info: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.is_file():
        stat = path.stat()
        info.update({"size": stat.st_size, "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")})
    return info


def parse_metrics(values: list[str], sources: list[str]) -> list[dict[str, Any]]:
    source_map: dict[str, str] = {}
    for item in sources:
        if "=" not in item:
            raise ValueError("--metric-source 格式应为 NAME=PATH")
        name, path = item.split("=", 1)
        source_map[name.strip()] = path.strip()
    metrics = []
    for item in values:
        if "=" not in item:
            raise ValueError("--metric 格式应为 NAME=VALUE")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name or not value.strip():
            raise ValueError("--metric 的名称和值都不能为空")
        metrics.append({"name": name, "value": value.strip(), "source": source_map.get(name, UNKNOWN_TEXT)})
    extra_sources = set(source_map) - {metric["name"] for metric in metrics}
    if extra_sources:
        raise ValueError("--metric-source 与指标名称不匹配：" + "、".join(sorted(extra_sources)))
    return metrics


def normalize_metric_sources(metrics: list[dict[str, Any]], cwd: Path) -> list[dict[str, Any]]:
    for metric in metrics:
        source = metric["source"]
        if source != UNKNOWN_TEXT:
            metric["source"] = absolute_result(source, cwd)
            metric["source_meta"] = artifact_info(metric["source"], cwd)
    return metrics


def detached_command(command: str) -> bool:
    parts = tokens(command)
    executable = Path(parts[0]).name.lower() if parts else ""
    return executable in {"sbatch", "qsub", "bsub"} or command.rstrip().endswith("&")


def set_status(record: dict[str, Any], status: str, reason: str = "", exit_code: Optional[int] = None, ended_at: str = "") -> None:
    record["status"] = status
    if status in TERMINAL_STATUSES:
        if ended_at:
            record["ended_at"] = ended_at
        elif not record.get("ended_at"):
            record["ended_at"] = now_local().isoformat(timespec="seconds")
    if reason:
        record["status_reason"] = reason
    if exit_code is not None:
        record["exit_code"] = exit_code
    record.setdefault("events", []).append({
        "at": now_local().isoformat(timespec="seconds"), "type": "status", "status": status, "reason": reason
    })


def remainder_command(parts: list[str]) -> str:
    if parts and parts[0] == "--":
        parts = parts[1:]
    if not parts:
        raise ValueError("缺少实验命令，请使用 `-- <command>`。")
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def launch(args: argparse.Namespace) -> int:
    command = remainder_command(args.command)
    record = new_record(args, command)
    cwd = Path(record["project_dir"])
    with report_lock():
        save_record(record)
    print(f"[experiment-log] RUN_ID={record['run_id']}", file=sys.stderr)
    print(f"[experiment-log] 日报={report_dir() / (record['started_at'][:10] + '.md')}", file=sys.stderr)
    sys.stderr.flush()

    shell_executable = None if os.name == "nt" else os.environ.get("SHELL", "/bin/bash")
    process = subprocess.Popen(command, cwd=cwd, shell=True, executable=shell_executable)
    record["pid"] = process.pid
    with report_lock():
        save_record(record)
    interrupted = False
    received_signal: Optional[int] = None
    previous_handlers: dict[int, Any] = {}

    def interrupt_handler(signum: int, _frame: Any) -> None:
        nonlocal received_signal
        received_signal = signum
        raise KeyboardInterrupt

    for signame in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, signame, None)
        if signum is not None:
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, interrupt_handler)
    try:
        return_code = process.wait()
    except KeyboardInterrupt:
        interrupted = True
        with contextlib.suppress(ProcessLookupError, OSError):
            process.send_signal(received_signal or signal.SIGINT)
        try:
            return_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            return_code = process.wait()
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)

    if interrupted or return_code in (130, 143) or return_code < 0:
        status = "interrupted"
        reason = "包装器观察到中断信号或被终止的返回码。"
    elif return_code == 0 and detached_command(command):
        status = "unknown"
        reason = "调度器或后台命令已成功提交，但包装器没有观察到底层实验结束；需要核对任务状态和结果文件。"
    elif return_code == 0:
        status = "completed"
        reason = "实验命令正常退出；这只表示运行完整结束，不代表实验假设成立。"
    else:
        status = "failed"
        reason = "实验命令以非零退出码结束。"
    set_status(record, status, reason, return_code)
    record["result_snapshots"] = [snapshot_path(path) for path in record["result_dirs"]]
    with report_lock():
        save_record(record)
    print(f"[experiment-log] {STATUS_LABELS[status]} · {record['run_id']}", file=sys.stderr)
    return return_code


def record_existing(args: argparse.Namespace) -> int:
    record = new_record(args, args.command_text, args.status)
    if args.status in TERMINAL_STATUSES:
        set_status(record, args.status, args.status_reason, args.exit_code, args.end_time)
        record["result_snapshots"] = [snapshot_path(path) for path in record["result_dirs"]]
    with report_lock():
        save_record(record)
    print(record["run_id"])
    return 0


def update(args: argparse.Namespace) -> int:
    with report_lock():
        record, _ = load_record(args.run_id)
        if args.status:
            if args.status != record.get("status") and args.status in {"completed", "interrupted", "discarded"} and not args.reason:
                raise ValueError(f"把状态改为 {args.status} 时必须提供 --reason 和直接核对依据。")
            set_status(record, args.status, args.reason, args.exit_code, args.end_time)
        cwd = Path(record["project_dir"])
        if args.metric:
            incoming = normalize_metric_sources(parse_metrics(args.metric, args.metric_source or []), cwd)
            existing = {item["name"]: item for item in record.get("metrics", [])}
            for item in incoming:
                existing[item["name"]] = item
            record["metrics"] = list(existing.values())
        if args.artifact:
            existing_artifacts = {item["path"]: item for item in record.get("artifacts", [])}
            for value in args.artifact:
                item = artifact_info(value, cwd)
                existing_artifacts[item["path"]] = item
            record["artifacts"] = list(existing_artifacts.values())
        if args.conclusion is not None:
            record["conclusion"] = args.conclusion
        if args.notes:
            record["notes"] = (record.get("notes", "") + "\n" + args.notes).strip()
        if args.result_dir:
            additions = [absolute_result(value, cwd) for value in args.result_dir]
            record["result_dirs"] = list(dict.fromkeys(record.get("result_dirs", []) + additions))
        if record["status"] in TERMINAL_STATUSES or args.snapshot:
            record["result_snapshots"] = [snapshot_path(path) for path in record["result_dirs"]]
        record.setdefault("events", []).append({"at": now_local().isoformat(timespec="seconds"), "type": "annotation"})
        save_record(record)
    print(report_dir() / f"{record['started_at'][:10]}.md")
    return 0


def list_runs(args: argparse.Namespace) -> int:
    records = []
    for path in iter_record_paths():
        if args.date and path.parent.name != args.date:
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if args.status and record.get("status") != args.status:
            continue
        records.append(record)
    records.sort(key=lambda item: item["started_at"], reverse=True)
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        for record in records:
            print(f"{record['run_id']}\t{record['status']}\t{record['started_at']}\t{record.get('title', '')}")
    return 0


def show(args: argparse.Namespace) -> int:
    record, path = load_record(args.run_id)
    print(json.dumps(record, ensure_ascii=False, indent=2) if args.json else render_record(record))
    if args.path:
        print(path, file=sys.stderr)
    return 0


def pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (TypeError, ValueError, OSError):
        return False


def reconcile(args: argparse.Namespace) -> int:
    changed = 0
    with report_lock():
        for path in list(iter_record_paths()):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") != "running":
                continue
            if args.date and record["started_at"][:10] != args.date:
                continue
            if record.get("host") != socket.gethostname() or pid_alive(record.get("pid")):
                continue
            set_status(record, "unknown", "记录中的进程已不存在，但无法可靠判断是完成、失败还是被终止；需要人工核对。")
            record["result_snapshots"] = [snapshot_path(item) for item in record.get("result_dirs", [])]
            save_record(record)
            changed += 1
    print(f"reconciled={changed}")
    return 0


def verify(args: argparse.Namespace) -> int:
    record, _ = load_record(args.run_id)
    issues: list[str] = []
    if record["status"] == "running" and not pid_alive(record.get("pid")):
        issues.append("记录为 running，但本机 PID 不存在；请先运行 reconcile。")
    for metric in record.get("metrics", []):
        source = metric.get("source")
        if not source or source == UNKNOWN_TEXT:
            issues.append(f"指标 {metric.get('name')} 缺少证据来源。")
            continue
        source_path = Path(source).expanduser()
        if not source_path.exists():
            issues.append(f"指标 {metric.get('name')} 的证据路径不存在：{source}")
            continue
        if not source_path.is_file():
            issues.append(f"指标 {metric.get('name')} 的证据路径不是文件：{source}")
            continue
        recorded_meta = metric.get("source_meta") or {}
        current_meta = artifact_info(str(source_path), Path(record["project_dir"]))
        if recorded_meta.get("size") is not None and current_meta.get("size") != recorded_meta.get("size"):
            issues.append(f"指标 {metric.get('name')} 的证据文件大小在登记后发生变化：{source}")
        elif recorded_meta.get("mtime") and current_meta.get("mtime") != recorded_meta.get("mtime"):
            issues.append(f"指标 {metric.get('name')} 的证据文件修改时间在登记后发生变化：{source}")
    for artifact in record.get("artifacts", []):
        if not Path(artifact["path"]).exists():
            issues.append(f"关键产物不存在：{artifact['path']}")
    if record["status"] == "completed" and not record.get("result_snapshots"):
        issues.append("完整结束的记录没有结果目录快照。")
    if record["status"] == "completed":
        for snapshot in record.get("result_snapshots", []):
            if snapshot.get("path") == UNKNOWN_RESULT:
                issues.append("完整结束的记录仍未识别结果目录。")
            elif not snapshot.get("exists"):
                issues.append(f"完整结束时结果路径不存在：{snapshot.get('path')}")
    if issues:
        for issue in issues:
            print(f"WARN\t{issue}")
        return 1
    print("OK\t记录状态与已声明证据通过检查")
    return 0


def add_common(
    parser: argparse.ArgumentParser,
    *,
    command_text: bool = False,
    default_source: str = "manual",
) -> None:
    parser.add_argument("--title", default="")
    parser.add_argument("--purpose", default="")
    parser.add_argument("--changes", default="")
    parser.add_argument("--summary", default="", help="旧版兼容参数，等同于 --changes")
    parser.add_argument("--baseline", default="")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--result-dir", action="append", default=[])
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--source", default=default_source, choices=["manual", "codex", "recovered", "hook"])
    parser.add_argument("--notes", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--launch-time", default="")
    if command_text:
        parser.add_argument("--command", dest="command_text", default="")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="实验生命周期与证据日志")
    subcommands = root.add_subparsers(dest="subcommand", required=True)

    launch_parser = subcommands.add_parser("launch", help="记录、运行，并自动回写结束状态")
    add_common(launch_parser)
    launch_parser.add_argument("command", nargs=argparse.REMAINDER)
    launch_parser.set_defaults(func=launch)

    record_parser = subcommands.add_parser("record", help="补记已有实验")
    add_common(record_parser, command_text=True, default_source="recovered")
    record_parser.add_argument("--status", choices=STATUSES, default="unknown")
    record_parser.add_argument("--status-reason", default="")
    record_parser.add_argument("--end-time", default="")
    record_parser.add_argument("--exit-code", type=int)
    record_parser.set_defaults(func=record_existing)

    update_parser = subcommands.add_parser("update", help="按实验 ID 更新状态、指标与证据")
    update_parser.add_argument("run_id")
    update_parser.add_argument("--status", choices=STATUSES)
    update_parser.add_argument("--reason", default="")
    update_parser.add_argument("--end-time", default="")
    update_parser.add_argument("--exit-code", type=int)
    update_parser.add_argument("--metric", action="append", default=[])
    update_parser.add_argument("--metric-source", action="append", default=[])
    update_parser.add_argument("--artifact", action="append", default=[])
    update_parser.add_argument("--result-dir", action="append", default=[])
    update_parser.add_argument("--conclusion")
    update_parser.add_argument("--notes", default="")
    update_parser.add_argument("--snapshot", action="store_true")
    update_parser.set_defaults(func=update)

    list_parser = subcommands.add_parser("list", help="列出实验记录")
    list_parser.add_argument("--date", default="")
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=list_runs)

    show_parser = subcommands.add_parser("show", help="查看单个实验的事实记录")
    show_parser.add_argument("run_id")
    show_parser.add_argument("--json", action="store_true")
    show_parser.add_argument("--path", action="store_true")
    show_parser.set_defaults(func=show)

    reconcile_parser = subcommands.add_parser("reconcile", help="将已消失但仍为 running 的本机进程标为 unknown")
    reconcile_parser.add_argument("--date", default="")
    reconcile_parser.set_defaults(func=reconcile)

    verify_parser = subcommands.add_parser("verify", help="检查状态、指标证据与产物路径")
    verify_parser.add_argument("run_id")
    verify_parser.set_defaults(func=verify)
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
