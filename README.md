# Experiment Daily Logger

面向 Codex 的实验记录 Skill。每次实验用几行说明：**改了什么、是否跑完、结果如何、输出在哪**。独立 JSON 保存完整命令、运行信息和结果证据，便于跨会话核对，减少上下文压缩后的结果混淆。

日报示例（命令与证据默认折叠，点击记录 ID 可查看完整元数据）：

```markdown
已完成 1 · 已中止 1

## 14:20 · [已完成] batch-32

- 改动：batch 16 → 32，数据划分和评估设置不变；对照：batch-16
- 结果：accuracy=0.812；完整验证集，比对照高 0.7 个百分点。
- 输出：`/project/outputs/batch-32`

## 15:10 · [已中止] batch-64

- 改动：batch 32 → 64，其余配置不变
- 输出：`/project/outputs/batch-64`
- 原因：数据划分配置错误，手动终止。
```

目的、对照、标签和备注按需填写；不要求写长篇动机或补齐所有字段。关键数值、对照条件和评估范围应写准确。

## 安装

```bash
python3 install.py
```

默认安装 Skill 到 `$HOME/.agents/skills/experiment-daily-logger`、入口到 `$HOME/.local/bin/exp-run`，并配置 `$HOME/.codex/hooks.json`。日报默认保存到 `$HOME/experiment-daily-report`，可通过 `EXPERIMENT_DAILY_REPORT_DIR` 修改。若找不到 `exp-run`，把 `$HOME/.local/bin` 加入 `PATH`。

## 日常用法

启动实验，写一句具体改动即可：

```bash
exp-run --title "batch-32" \
  --changes "batch 16 → 32，数据划分和评估设置不变" \
  --baseline "batch-16" --result-dir auto \
  -- python train.py --batch-size 32 --output-dir outputs/batch-32
```

终端会打印 `RUN_ID`。包装器自动记录命令、Git 状态及结束信息。正常退出为 `completed`，非零退出为 `failed`，观察到中断为 `interrupted`。需要说明研究问题时才添加 `--purpose`，分组时可用 `--tag`。

看过结果文件后登记关键指标和一句结论：

```bash
LOGGER="$HOME/.agents/skills/experiment-daily-logger/scripts/experiment_logger.py"
python3 "$LOGGER" update <run-id> \
  --metric "accuracy=0.812" \
  --metric-source "accuracy=/project/outputs/batch-32/metrics.json" \
  --conclusion "完整验证集，比对照高 0.7 个百分点。"
```

需要长期引用的文件可用 `--artifact /absolute/path/to/file` 登记。指标未关联来源时会标为“缺证据”；`verify` 检查路径、文件大小和修改时间，不计算文件摘要。

手动停止或决定丢弃时，写清原因：

```bash
python3 "$LOGGER" update <run-id> \
  --status interrupted --reason "数据划分配置错误，手动 Ctrl-C 终止。"

python3 "$LOGGER" update <run-id> \
  --status discarded --reason "使用了错误的数据划分，排除本次结果。"
```

`discarded` 保留记录和产物。尚在运行、失败、中止、丢弃及待核实的结果都不纳入正式比较；`completed` 只证明命令正常结束，仍需核对指标证据和评估范围。

每日回顾或跨会话继续时，先读取记录：

```bash
python3 "$LOGGER" reconcile --date 2026-10-12
python3 "$LOGGER" list --date 2026-10-12
python3 "$LOGGER" show <run-id> --json
python3 "$LOGGER" verify <run-id>
```

`list` 可加 `--status completed` 筛选。`reconcile` 发现本机进程已消失但记录仍是运行中时，只改为 `unknown`（待核实）。后台调度或脱离包装器的任务，需要核对实际任务和输出后再更新状态。

## 补记与存储

用 `record` 补记外部实验；无法确认是否跑完时，保留待核实状态：

```bash
python3 "$LOGGER" record --source recovered --status unknown \
  --status-reason "待核对集群任务状态和结果文件" \
  --title "外部集群训练" --changes "运行 configs/a.yaml" \
  --project-dir /project --result-dir /project/outputs/a \
  --command "python train.py --config configs/a.yaml"
```

日报位于 `YYYY-MM-DD.md`，每次实验的事实记录位于 `.experiment-daily-logger/runs/YYYY-MM-DD/<run-id>.json`。用 CLI 更新，避免手改生成字段。保留旧版 `--summary` 参数和已有 Markdown 条目。

可选 PreToolUse Hook 只作为未使用包装器时的兜底：它无法看到执行结果，因此记录为 `unknown`。使用 `exp-run` 或 `experiment_logger.py launch` 才能自动跟踪命令结束状态。

完整规则见 [记录与证据](references/record-schema.md)，显示格式见 [日报格式](references/log-format.md)。

## 卸载

```bash
bash uninstall.sh
```

卸载保留日报和 JSON。`hooks.json` 中的相关条目需按卸载提示人工核对。
