# 实验记录与证据规则

## 状态语义

| 状态 | 含义 | 能否进入正式结果比较 |
|---|---|---|
| `running` | 进程仍在运行，或尚未获得结束事件 | 否 |
| `completed` | 包装器观察到命令以 0 退出，或有等价的直接证据 | 只有指标证据完整时可以 |
| `failed` | 命令非零退出且不是已识别的中断 | 否；可用于故障分析 |
| `interrupted` | 用户/系统在完成前终止 | 否；保留部分产物供诊断 |
| `discarded` | 明确判定该运行不应被使用 | 否；必须保留原因 |
| `unknown` | 启动已知，但结束方式无法可靠判断 | 否，直到人工核对 |

状态和结论是两个不同维度：`completed` 只描述执行生命周期；科学结论必须由指标和证据文件支持。

## JSON 事实源

每个 run 的 JSON 至少包含：

- 身份：`schema_version`、`run_id`、`title`、`tags`；
- 生命周期：`status`、`status_reason`、`started_at`、`ended_at`、`exit_code`、`events`；
- 可复现信息：`project_dir`、`command`、`git`、`host`、`pid`；
- 实验设计：`purpose`、`changes`、`baseline`；
- 结果定位：`result_dirs`、`result_snapshots`、`artifacts`；
- 结果解释：`metrics`、`conclusion`、`notes`。

这些是存储字段，不是每条日报必须填写的表单。通常只需写清改动、结果和输出位置；目的、对照等按需提供。Markdown 默认简短展示，命令和证据按需展开，Git、PID、时间及目录快照等信息通过实验 ID 查询。

不要手改 JSON。CLI 使用文件锁、临时文件和原子替换来避免并发写坏。

## 指标证据

一条指标包含 `name`、`value`、`source` 和登记时的 `source_meta`。`source` 应是本次运行产生或明确引用的绝对文件路径，例如 metrics JSON、CSV、评估器输出或保存的终端日志。CLI 会记录证据文件的大小和修改时间；`verify` 会检查这些元数据是否发生变化。不要把以下内容当成充分证据：

- Codex 对先前上下文的回忆；
- 文件名里出现的数字；
- 另一个 run 的结果，除非明确作为 baseline；
- 中断前的一行临时进度；
- 仅表示训练结束的 checkpoint 文件。

同名指标再次写入时，以最新的显式更新为准，并保留 annotation event。

## 产物与目录快照

`artifact` 表示需要长期引用的关键文件。CLI 记录绝对路径、存在性、大小和修改时间，不计算文件摘要。

目录快照只证明结束时目录是否存在，以及可枚举文件的数量和总字节数；它不证明内容正确。扫描上限为 10,000 个文件，超过时 `truncated=true`。

## 状态更正

- 自动 `completed`：包装器观察到 exit code 0。
- 自动 `failed`：包装器观察到非零退出码。
- 自动 `interrupted`：包装器观察到 Ctrl-C、信号或常见中断退出码。
- `reconcile` 发现本机 PID 消失时只能设为 `unknown`，不能猜测完成状态。
- `discarded` 必须由显式 `update --status discarded --reason ...` 产生。
- 手工把 `unknown` 改成其他状态时，原因中应写清核对了什么证据。
