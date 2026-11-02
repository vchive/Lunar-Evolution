# DeepSeek 独立扩展预算钢卷验收（2026-11-02）

本次单次尝试失败，原因为 `input_required`，没有完成回执、`solution.csv` 或评分。
8 次模型请求均完成且返回 HTTP200，接纳 8 轮、12 个工具结果后，模型调用
`ask_user` 询问使用哪个 Python。Subject rc2，耗时 42.60591754177585 秒；
原 child 已回收、pipe EOF 验证，无 watchdog 信号。未发生本次传输失败或预算终止。

停止前的原始工具记录显示：第一次 stringified argv 被拒绝；随后 login shell
中的 `python3` 为系统 Python 3.9.6，导入 pandas/ortools/pulp 失败，scipy 导入
成功，另一个 pip 列表却包含 pandas。再一次探测明确找到 Miniforge Python 3.13
可以导入 pandas，模型随后仍询问选择哪一个解释器。这是执行环境歧义和模型行为
的实际观察，不证明所有解释器都缺依赖，也不证明求解必须依赖这些库或 runtime 有缺陷。

schema1 失败记录保留 `runtime/input_required`、8 轮和 12 工具；它没有 token
ledger，本次日志与历史也没有 token 计数，因此累计用量和费用保持未知，不填零。
未调用评分器验证、提取或修补中间产物。

这次使用[预先登记的独立规格](../specs/061-subject-failure-diagnostics/deepseek-steel-extended-acceptance.md)：
deepseek-chat、80 工具、100 万累计观测 tokens、3,000 秒、单次生成上限16,384，
一次零重试。登记提交 `859650fe509f5549be7a608656d9e0354077ee97` 推送并核对
远端后，于 `2026-11-02T14:14:17.143052Z` 启动。Manifest SHA256：
`7a65468b35efc79427af3ffe95774584bf27675ae182232b14d9543d8796d714`。
执行源仍为 f3257898/tree dfb61885，而非后继 fixed-profile pin 修正源。
owner .env 不变，本实验不再增加预算。

独立终态审查报告13,329字节，SHA256：
`9ace53976009acb2e62c04cbd08450cefbc473b98d389ee840fa6a801b9a921c`。
2,826 源文件/308 目录、240 实际模块来源、case14/original13、profile 和独立评测
venv4,586文件/434目录均匹配。旧钢卷及列车/手术室原件 pins 未变，secret scan
零匹配。审查通过仅确认这份失败证据。原件在主工作区 ignored
`.lunar-evolution/validation/deepseek-steel-extended-20261102/steel_coil_cutting/`。

本批四次 DeepSeek 尝试均未完成评分：列车和原钢卷为累计预算终止，手术室为
`invalid_tool_calls`，扩展钢卷为 `input_required`。原失败均保留。旧模型传输故障
根因仍未知，手术室具体工具解析分支也无原始证据。后续普通模型验收应先明确
公开执行环境契约，按新的独立规格固定输入；不能续跑本次失败或把加预算视为修复。
真实模型可靠性 P0 与 native RSI P1 仍开放；`production_admission=false`、
`online_publication=false`，本地技术 MVP 的软件机制与这些验收边界分开报告。
