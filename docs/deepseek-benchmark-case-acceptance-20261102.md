# DeepSeek 两例真实本地验收（2026-11-02）

两例均已单次执行完毕，结果失败。新模型没有重现本批次的传输失败，但两例都未
产出完成回执或有效提交，因此本地 evaluator 未启动，分数为 null。

| 项目 | 列车重排 | 手术室排程 |
| --- | --- | --- |
| 模型 | deepseek-chat | deepseek-chat |
| Subject rc / 秒 | 2 / 415.635339833796 | 2 / 109.0237058326602 |
| 已接纳模型轮次 / 工具结果 | 18 / 21 | 17 / 24 |
| HTTP 请求 | 19 次均完成、HTTP200 | 17 次完成；第18次 HTTP200 后校验失败 |
| 实际终态 | schema2 runtime/budget_exceeded | schema7 model/model_failed，invalid_tool_calls |
| 已接纳部分 tokens | 144,050（138,578 输入、5,472 输出） | 114,715（108,564 输入、6,151 输出） |
| 完成回执 / 提交 / evaluator / 分数 | 无 / 无 / 未调用 / null | 无 / 无 / 未调用 / null |

列车第19次响应带来的16,521 tokens（16,145输入、376输出），使观测累计达到
160,571，超过原160,000阈值；触发轮未接纳，ledger 保留 partial 边界。
这次是累计预算终止，非传输或生成截断错误。手术室第18次请求用时6,415ms，
实际失败阶段为 validate_response，末次本地里程碑为 response_headers_received。
当前原件只保留固定 invalid_tool_calls 原因，未保存响应正文或具体解析分支，
不能判断是参数 JSON、名称、ID 还是其他工具调用形状；触发请求用量/费用未知。

两例都没有 transport_error/transport_timeout，未输出传输异常分类。
这只描述本次新模型的观察，不能解释旧模型故障根因，也不证明网关已修复。
历史失败全部保留；本次没有重试、参数降级、旧 attempt resume 或评分替代。

采用[预先登记的规格](../specs/061-subject-failure-diagnostics/deepseek-benchmark-case-acceptance.md)，
登记提交 `24098669f4430ed5af84b8d34623e058d3ece6f4` 推送后，两例于
`2026-11-02T13:00:37.966Z` 启动。执行源为 `f3257898`，tree `dfb61885`，
保持16,384生成上限、160,000观测tokens、40工具、3,000秒及一次零重试。
只在新 child 内覆盖模型名，owner .env 不变；所有 evaluator 门保持关闭。

独立终态审查47项通过，报告16,803字节，SHA256：
`caf6001b5eea78aa2880dc1c81162b2eba40788681366e69bd1c5702f8c8f72b`。
两套2,826源文件/308目录、240实际加载模块来源、案例/公开文件/profile/Python
和绑定一致；原child已回收、pipe EOF验证，无watchdog信号或终态超时。
原native工具历史完整配对，均无pending调用。列车存在有界工具输出截断标记，
不据此宣称全历史与最初 wire 字节等价。旧 capped 原件和审计 pins 均未变。
审查通过只确认两份失败记录；普通模型真实E2E P0继续开放。

原件位于主工作区 ignored
`.lunar-evolution/validation/deepseek-benchmark-cases-20261102/`。
固定传输分类的软件回归与 PR217 集成独立跟进，不由这些失败结果替代。
