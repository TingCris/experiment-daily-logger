# Markdown 日报格式

每天一个 `YYYY-MM-DD.md`。顶部一行统计非零状态；每次实验标题显示时间、状态和短名称，正文通常 3–6 行。目的仅在填写时显示，对照并入改动行，不显示空标签或备注。

以下是一个已完成实验的示例。CLI 使用成对标记更新对应块，不覆盖其他条目。

````markdown
# 实验日报 · 2026-10-12

<!-- experiment-summary:start -->
已完成 1
<!-- experiment-summary:end -->

<!-- experiment:20261012-142000-a1b2c3d4 -->
## 14:20 · [已完成] batch-32

- 改动：batch 16 → 32，数据划分和评估设置不变；对照：batch-16
- 结果：accuracy=0.812；完整验证集，比对照高 0.7 个百分点。
- 输出：`/project/outputs/batch-32`

记录：[20261012-142000-a1b2c3d4](.experiment-daily-logger/runs/2026-10-12/20261012-142000-a1b2c3d4.json)

<details>
<summary>命令与证据</summary>

- 项目：`/project`
- 证据（accuracy）：`/project/outputs/batch-32/metrics.json`

```bash
python train.py --batch-size 32 --output-dir outputs/batch-32
```

</details>

<!-- /experiment:20261012-142000-a1b2c3d4 -->
````

## 显示约定

- 状态标签：`completed` → 已完成，`running` → 运行中，`failed` → 失败，`interrupted` → 已中止，`discarded` → 已丢弃，`unknown` → 待核实。
- 失败、中止、丢弃和待核实的记录显示原因。保留具体事实，例如“数据划分配置错误，手动终止”。
- 有非完成状态的指标或结论时，标为“结果（不纳入正式比较）”。写清部分评估的范围，不把它说成完整结果。
- 已完成但尚未登记指标或结论时，显示“结果：待登记”。指标缺少来源时，在值后标“缺证据”。
- 改动和结论用一两句事实即可，不删改精确数值、重要控制变量或评估范围来凑短。额外目的、产物和备注仅在提供时显示；产物和备注放在折叠区。
- Git、主机、PID、完整时间、退出码、目录快照和事件历史保存在 JSON 中，通过记录 ID 查看。

状态统计只包含结构化记录，旧版条目保持原样。`completed` 表示命令正常结束，结论的有效性仍需核对证据。存储和状态规则见 [record-schema.md](record-schema.md)。
