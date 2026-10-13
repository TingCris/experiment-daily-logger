---
name: experiment-daily-logger
description: Keep concise daily Markdown logs and durable experiment records when Codex launches, resumes, compares, reviews, stops, or discards computational experiments. Track completion status, concrete changes, output locations, and evidence-backed results across sessions.
---

# Experiment Daily Logger

Keep each experiment easy to identify and revisit: what changed, whether it finished, what the result was, and where its outputs are. Read saved records and evidence when recalling experiments; conversation memory is not a result source.

## Record briefly

Use a short title and one or two factual sentences for the change. Add the purpose or baseline only when it clarifies this run; tags and notes are optional. Do not expand these into experimental motivation or fill every available field. Preserve exact values, important controls, and evaluation scope when they affect interpretation.

The daily report shows a one-line status count and a few lines per run. Commands and evidence paths are in a collapsed section; the run ID links to full JSON metadata. Do not repeat that metadata in the visible summary. See [references/log-format.md](references/log-format.md) when working on the report layout.

## Launch and track

```bash
LOGGER="$HOME/.agents/skills/experiment-daily-logger/scripts/experiment_logger.py"
python3 "$LOGGER" launch \
  --source codex --title "batch-32" \
  --changes "batch 16 → 32; same data split and evaluation" \
  --result-dir auto \
  -- python train.py --batch-size 32 --output-dir outputs/batch-32
```

`exp-run` is the launch shorthand. The wrapper records the exact command, project, Git state, and outputs automatically; do not execute the command again separately. Use `--baseline`, `--purpose`, or `--tag` when useful.

- `completed`: the wrapper observed exit code 0; this alone does not establish scientific validity or complete evaluation coverage.
- `failed`: a nonzero exit without an identified interruption.
- `interrupted`: an observed interruption or termination.
- `discarded`: an explicit decision to exclude the run, with a reason.
- `unknown`: the outcome cannot be established; `running` means no terminal event has been recorded yet.

For detached or scheduled jobs, inspect the underlying job and output evidence before recording its final status. A launcher exiting is not proof the job finished.

## Add results or explain a stop

Read the result file before registering metrics. Use the run ID printed at launch:

```bash
python3 "$LOGGER" update <run-id> \
  --metric "accuracy=0.812" \
  --metric-source "accuracy=/absolute/path/to/metrics.json" \
  --conclusion "Full validation split; +0.7 percentage points vs batch-16."

python3 "$LOGGER" update <run-id> \
  --status discarded --reason "Wrong data split; exclude this result."
```

One or two factual sentences suffice. Do not infer metrics from filenames, recollection, or temporary progress output. If an observed result exists only in tool output, save that output as evidence. Keep partial results labeled with their scope and exclude non-completed runs from formal comparisons. Preserve discarded records and their outputs.

Use `--status interrupted --reason ...` for a confirmed stop. Never relabel a failed, interrupted, discarded, or unknown run as completed without direct evidence. Read [references/record-schema.md](references/record-schema.md) when auditing evidence or correcting status.

## Review and recover

```bash
python3 "$LOGGER" reconcile --date YYYY-MM-DD
python3 "$LOGGER" list --date YYYY-MM-DD
python3 "$LOGGER" show <run-id> --json
python3 "$LOGGER" verify <run-id>
```

Before recalling or comparing runs, reconcile and inspect their records and relevant evidence. Compare compatible settings and baselines, distinguish measured values from interpretation, and briefly state abnormal-status reasons or missing evidence. A daily recap needs only the useful outcomes and unresolved issues, with run references when needed.

`reconcile` changes stale local `running` records to `unknown`, never guesses completion. `verify` checks evidence paths, size, and modification time. Use `record` to recover an externally launched run; use `unknown` if its completion is unverified. The optional PreToolUse hook is a fallback for unwrapped commands and records `unknown` because it cannot observe completion.

The default report directory is `$HOME/experiment-daily-report`, overridden by `EXPERIMENT_DAILY_REPORT_DIR`. Daily Markdown lives at `YYYY-MM-DD.md`; canonical records live at `.experiment-daily-logger/runs/YYYY-MM-DD/<run-id>.json`. Use the CLI to update both consistently. Existing v1 Markdown entries remain intact.
