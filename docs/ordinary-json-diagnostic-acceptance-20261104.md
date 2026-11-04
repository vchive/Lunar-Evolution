# 普通模型解码诊断后的独立 case 验收（2026-11-04）

本次独立尝试失败，未生成完成回执、`solution.csv` 或评分。第3次 HTTP200 响应
的工具参数不是合法 JSON；解析器按原规则拒绝为 `invalid_tool_calls`，固定类别为
`arguments_invalid_json`。这次新增诊断已实际保存：

| 字段 | 实际值 |
| --- | --- |
| decoder_category | json_syntax |
| argument_characters | 390（Unicode字符数） |
| position | 12（从0开始） |
| line / column | 1 / 13（从1开始） |
| finish_reason_category | tool_calls |

这些是本地解码和所选choice的有限观察。没有保存被拒绝参数正文或异常文字，
不能据此确定具体错误字符、语法、服务端或网关根因；不能回填旧尝试的诊断。

原subject耗时5.261406042147428秒、rc2，原child已回收、pipe EOF确认，无信号、
watchdog超时或预算终止。3次HTTP200中2次completed，第3次failed；已接纳2轮、
5个工具结果（2次list_dir、3次read_file，没有已接纳命令执行）。schema7保留
部分用量：input4,543/output177/total4,720 tokens，
rounds2、cost=null、usage_completeness=partial。被拒绝响应的用量未知，不能把
4,720解释为全部服务用量，也不能填入零费用。失败请求体指纹为13,860 bytes/
SHA256 `b3621e2301bd6ac01c77c321b8aded00065c4416d313ba44d6fd561f5bfd7bd6`。

按[预先登记规格](../specs/061-subject-failure-diagnostics/ordinary-json-diagnostic-acceptance.md)，
source为已验收main85ff5f687df76bf1102f6de9c8966970c827d0c9、
tree4943c9a4b04134ec61b0309b342bd4131cf10bc2。复用PR224同字节软件的完整CI，
本轮只更新测量文档。旧case15/public6、入口、身份、精确212字节profile及五helper
保持同字节；原benchmark和每次旧失败保留。deepseek-chat、80工具、100万累计
观测tokens、3,000秒、单次16,384上限保持，一次零推理重试，无自动回答、参数/
答案修补、额外预算或旧session续跑。观测tokens阈值不是计费硬上限。

Fresh attempt：ordinary-deepseek-85ff5f68-steel-json-diagnostics-20261104-attempt-001。
Manifest7,410bytes/SHA256：
`f2c6714ea619e499762219b6cd147be446a6310bb1f7849f635f36b8b48c1a26`。
登记5037ec0ad0bb161cbaa0009f4bf8446eb7675e19已push并核验远端，随后才把既有
用户授权绑定到此manifest/attempt。启动时间2026-11-04T05:32:14.006193Z，
即北京时间13:32:14。实际request1,706bytes/SHA256：
`b11ec4b2b4d7480f95aba75df507ab491b2f10c4726bb5294f165ab89f2880ed`；
profile protocol SHA256：
`1a23936019ee417aad421f1e6f83a4f7583d56012b5d85f5059cb85dc16f3496`。
这些与登记前独立重建一致；相同输入摘要保持相同，没有人为盐化。

准备及provider-free批次各一次通过：准备probe0.5474697924219072秒/rc0，
wrapper2.318638250231743秒/rc0，确认Python3.13.12/pandas3.0.6；
4adapter/27拒绝/3环境seam批次1.028517917264253秒/rc0，234实际模块来源匹配，
未调用模型、真实工具、评分器或读取owner配置。五个新测量脚本Ruff/compileall和
diff检查通过，临时编译缓存已移除。首次Ruff的3个import/UTC风格问题已最小修正，
原件保留，没有重跑已通过的能力准备或接口批次。

Launch在实际subject cwd中再次probe0.5792466253042221秒/rc0，与准备观察一致。
Source2,846文件/308目录、case15/public6、profile、原evaluator环境和前后清单
保持不变；实际240个产品模块来自冻结源码。原evaluator环境是独立hash-locked
venv4,586文件/434目录，未因subject环境而变更。本次没有完成回执，因此评分器
被跳过，未伪造提交、补默认分或用fixture通过代替任务完成。

外层监督8.209862125106156秒/rc2，原child回收/EOF，无outer timeout或信号。
新外层3250秒只覆盖原capability/subject/evaluator与本地校验，原subject3020秒
watchdog及模型3000秒保持。`whole_group_cleanup_verified=false`仍为false；
原进程回收/EOF不能提升为完整后代清理或OS隔离证明。捕获未溢出，secret scan
完成10文件/21,800字节、0匹配，public_export_allowed=true；原始私密输出未打印。

原件在主工作区ignored
`.lunar-evolution/validation/ordinary-tool-argument-diagnostics-20261104/`；
attempt在`steel_coil_cutting/`。保留准备代码/diff、精确manifest、registration、
授权、过程、history、固定诊断、部分用量及失败/跳过评分终态。独立原件复核
32项通过，仅确认本次失败记录，没有重跑模型或评分：同目录
`independent-actual-result-review-v1.json`，18,658bytes/SHA256
`b38e44b36727440422d34f4a75aaedee00dda4f2f5b5e02c823202d11c6572fb`。

P0真实普通模型完成并有效评分仍开放。这次确认了新诊断捕获链，不能算作JSON
故障已修复，也不能证明通用可靠性、同预算baseline持平或深度演化收益。只读核对
现有工具schema、公开指令与实现，未发现可确认的产品逻辑缺陷；当前也不能确定
被拒绝的工具名称。下一协议修改应先有供应商工具兼容契约或可复现的脱敏fixture，
不能猜测服务支持strict/response_format，也不因本次失败重试、扩预算或放宽解析。
核对报告在同根`next-action-readonly-v1.md`。NativeRSI P1仍缺实际worker不可变输入消费、完整构建输入保护及
外部writer排除，随后才有accepted runtime/live owner、scheduler context和
生产CLI/case验收；它仍有软件集成缺口，不能归结为只差机器环境。P2远程评测、
多机服务和模型训练后置。`production_admission=false`、`online_publication=false`。
