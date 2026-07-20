---
name: experiment-daily-logger
description: Record experiment launches in a daily Markdown report. Use whenever Codex is asked to launch, rerun, resume, compare, or record a computational experiment. Record once immediately before launch; never monitor the experiment or modify the entry afterward.
---

# Experiment Daily Logger

Use this skill whenever an experiment is about to be launched or an already-running experiment needs to be added to the daily report.

## Report location

Write reports under:

`$HOME/experiment-daily-report`

The location can be overridden with:

`EXPERIMENT_DAILY_REPORT_DIR`

Use one file per local calendar day:

`YYYY-MM-DD.md`

Append to the existing file for that day. Create it only when it does not exist.

## Write-once rule

Record the experiment exactly once at launch time.

- Do not poll or periodically inspect the process.
- Do not wait in order to modify the Markdown entry.
- Do not record end time, duration, status, or exit code.
- Do not edit the entry after the experiment starts.

## Required fields

Each entry contains only:

- project name;
- absolute project directory;
- local launch time with timezone;
- source: `codex`, `manual`, `recovered`, or `hook`;
- one-sentence summary of the experimental change;
- exact command;
- result/output directory;
- optional notes.

Never invent a result directory. Infer it from the user's instruction or command-line options. When it cannot be identified, write `未识别（需要后补）`.

## One-sentence change summary

Produce one concise Chinese sentence describing what changed in this run.

Use evidence in this order:

1. the user's current instruction;
2. code or configuration changes made in the current task;
3. command-line overrides;
4. configuration and script filenames.

Good:

`将批处理大小从 16 调整为 32，并保持其他配置不变。`

Bad:

`运行实验。`

Do not invent an experimental purpose that was not stated.

## Launching from Codex

Use:

```bash
python3 "$HOME/.agents/skills/experiment-daily-logger/scripts/experiment_logger.py" launch \
  --source codex \
  --summary "<一句话实验改动>" \
  --result-dir "<结果目录或 auto>" \
  -- <原始实验命令及参数>
```

The launcher appends one Markdown entry, then replaces itself with the original command through `exec`. No monitoring process remains.

Rules:

1. Preserve the original command and environment variables.
2. Use `--result-dir auto` when a recognizable output argument is present.
3. Do not create another entry after launch.
4. For background or scheduler commands, record only the launch.
5. The `PreToolUse` Hook is a fallback for unwrapped commands. It skips `exp-run` and `experiment_logger.py` to avoid duplicate entries.

## Recording an existing experiment

```bash
python3 "$HOME/.agents/skills/experiment-daily-logger/scripts/experiment_logger.py" record \
  --source recovered \
  --summary "<一句话实验改动>" \
  --project-dir "<项目目录>" \
  --result-dir "<结果目录或 auto>" \
  --command "<实际命令>"
```

Do not inspect the process repeatedly.

## Manual experiments

```bash
exp-run \
  --summary "<一句话实验改动>" \
  --result-dir "<结果目录或 auto>" \
  -- <原始实验命令及参数>
```

`exp-run` writes once and directly hands control to the original command.

## Final checks

- Verify exactly one entry was appended.
- Verify project and result paths are absolute or explicitly unknown.
- Preserve the exact command.
- Ensure the entry contains no completion, duration, status, or exit-code fields.
- Never overwrite unrelated entries.
