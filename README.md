# Experiment Daily Logger

一个用于 Codex 的轻量实验日志 Skill。

它会在实验启动前，将本次运行的信息追加到当天的 Markdown 日志中。默认日志目录为：

```text
$HOME/experiment-daily-report
```

也可以通过环境变量自定义：

```bash
export EXPERIMENT_DAILY_REPORT_DIR="/path/to/your/report-directory"
```

每天对应一个文件：

```text
YYYY-MM-DD.md
```

## 功能

- 自动记录项目目录；
- 自动记录实验启动时间；
- 记录一句话实验改动说明；
- 保存完整实验命令；
- 自动识别常见结果输出目录；
- 当天日志存在时自动续写；
- 当天日志不存在时自动创建；
- 支持 Codex 自动触发；
- 支持普通终端手动启动实验；
- 使用文件锁避免并发写入冲突。

该版本只在启动时记录一次，不会：

- 持续监控实验；
- 轮询运行进程；
- 等待实验结束；
- 记录结束时间或持续时间；
- 记录状态或退出码；
- 在实验结束后修改日志。

## 目录结构

```text
experiment-daily-logger/
├── SKILL.md
├── README.md
├── install.py
├── uninstall.sh
├── agents/
│   └── openai.yaml
├── bin/
│   └── exp-run
├── references/
│   └── log-format.md
└── scripts/
    ├── codex_hook.py
    └── experiment_logger.py
```

## 安装

进入项目目录后执行：

```bash
cd experiment-daily-logger
python3 install.py
```

安装内容：

```text
$HOME/.agents/skills/experiment-daily-logger
$HOME/.local/bin/exp-run
$HOME/.codex/hooks.json
$HOME/experiment-daily-report
```

## 配置 PATH

如果终端提示找不到 `exp-run`：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

确认安装：

```bash
which exp-run
```

## 重启并检查 Codex

退出当前 Codex：

```text
Ctrl+C
```

重新启动：

```bash
codex
```

检查 Skill：

```text
/skills
```

检查并信任 Hook：

```text
/hooks
```

## 在 Codex 中使用

### 自动触发

直接描述需要修改和运行的实验，例如：

```text
把批处理大小从 16 调整为 32，然后运行实验，
结果保存到 outputs/batch-32。
```

Codex 会根据 `SKILL.md` 的描述判断是否自动使用该 Skill。

### 显式触发

需要确保触发时，可以明确指定：

```text
使用 $experiment-daily-logger，
把批处理大小从 16 调整为 32，
运行实验并把结果保存到 outputs/batch-32。
```

内部执行形式类似：

```bash
python3 "$HOME/.agents/skills/experiment-daily-logger/scripts/experiment_logger.py" launch \
  --source codex \
  --summary "将批处理大小从 16 调整为 32。" \
  --result-dir auto \
  -- python run_experiment.py \
       --batch-size 32 \
       --output-dir outputs/batch-32
```

记录器写入日志后，会通过 `exec` 将自身替换为原命令，不会留下持续监控进程。

## 在普通终端中使用

Codex 无法观察另一个终端中直接输入的命令。自己运行实验时应使用 `exp-run`：

```bash
cd /path/to/project

exp-run \
  --summary "将批处理大小从 16 调整为 32。" \
  --result-dir auto \
  -- python run_experiment.py \
       --batch-size 32 \
       --output-dir outputs/batch-32
```

执行顺序：

1. 向当天 Markdown 追加一条记录；
2. 使用 `exec` 启动原命令；
3. 日志脚本退出，不再监控实验；
4. 命令结束后不再修改日志。

## 参数

### `--summary`

本次运行的一句话改动说明：

```bash
--summary "启用新的数据预处理配置。"
```

建议显式填写。未填写时，脚本会根据命令和参数生成保守概括。

### `--result-dir`

明确指定结果目录：

```bash
--result-dir outputs/run-01
```

或者自动识别：

```bash
--result-dir auto
```

自动识别支持常见参数：

```text
--output
--output-dir
--output_dir
--save-dir
--save_dir
--result-dir
--result_dir
--work-dir
--work_dir
--logging-dir
--logging_dir
--checkpoint-dir
--checkpoint_dir
```

无法识别时会写入：

```text
未识别（需要后补）
```

### `--project-dir`

默认使用当前目录，也可以明确指定：

```bash
--project-dir /path/to/project
```

## 补记已经启动的实验

```bash
python3 "$HOME/.agents/skills/experiment-daily-logger/scripts/experiment_logger.py" record \
  --source recovered \
  --summary "补记：启用新的配置文件运行实验。" \
  --project-dir /path/to/project \
  --result-dir /path/to/project/outputs/run-01 \
  --command "python run_experiment.py --output-dir outputs/run-01"
```

该命令只追加一条 Markdown，不会启动、终止或监控任何进程。

## 日志示例

```markdown
# 实验日报 · 2026-01-01

<!-- experiment:153210-12345-a1b2c3d4 -->
## 15:32:10 · example-project

- **实验 ID**：`153210-12345-a1b2c3d4`
- **来源**：`codex`
- **项目目录**：`/path/to/example-project`
- **启动时间**：2026-01-01T15:32:10+08:00
- **一句话改动**：将批处理大小从 16 调整为 32。
- **结果目录**：`/path/to/example-project/outputs/batch-32`
- **命令**：

```bash
python run_experiment.py --batch-size 32 --output-dir outputs/batch-32
```

- **备注**：无
```

## 卸载

在项目目录中执行：

```bash
bash uninstall.sh
```

该脚本会删除：

```text
$HOME/.agents/skills/experiment-daily-logger
$HOME/.local/bin/exp-run
```

已有实验日志不会被删除。

为了避免误删其他 Codex Hook，脚本不会自动修改：

```text
$HOME/.codex/hooks.json
```

请手动打开该文件，删除 `command` 中包含以下内容的 Hook 条目：

```text
experiment-daily-logger/scripts/codex_hook.py
```

## 注意事项

1. Skill 不能观察另一个普通终端中直接输入的命令。
2. 手动实验应使用 `exp-run`。
3. Hook 只在 Codex 执行匹配的 Bash 命令前触发一次。
4. 日志只记录启动信息，不代表命令成功完成。
5. 自动识别结果目录失败时，可以手动补充。
