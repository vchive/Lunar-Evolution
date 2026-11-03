# 普通模型公开执行环境验收（2026-11-03）

本次独立尝试失败，未生成完成回执、`solution.csv` 或评分。公开环境声明和工具
环境已正确接通；新的阻断是第六次 HTTP200 响应中的工具参数不是合法 JSON，
现有解析器以 `invalid_tool_calls` 拒绝，可选失败日志明确记录
`tool_call_error_category=arguments_invalid_json`。

原 subject 耗时12.861271333415061秒、rc2，child已回收、pipe EOF确认，
无watchdog信号、超时或预算终止。共6次HTTP200：5次completed，第6次failed；
接纳5轮、10个工具结果。两次已接纳的run_command均为直接argv，以python3.13
执行且exit_code=0。这次没有再次出现Python选择询问，但不推断模型以后不会询问。

schema7保留已接纳部分用量：input19,665/output470/total20,135 tokens，
rounds5、cost=null、usage_completeness=partial。被拒绝响应的用量未知，
不得将20,135解释为全部服务用量或填入零费用。固定请求体指纹为22,554 bytes/
SHA256 `81bbe6b73de611ee5bea408b2732ad5bf4480227cd3962ceba4ff7f0f520790e`。
原日志没有失败参数正文、JSON错误位置或该响应的finish_reason；不能由这个
固定分类进一步断言是截断、某种引号错误、模型服务或网关改写。

按[预先登记的独立规格](../specs/061-subject-failure-diagnostics/ordinary-public-execution-environment.md)，
使用新公开入口和新case/publication/attempt身份，source仍为已验收main7038fae1，
tree25e55f36。保留原212字节extended profile：deepseek-chat、80工具、
100万累计观测tokens、3,000秒、单次上限16,384；一次零重试，无预算增加、
自动回答、参数或答案修补。现有receipt和评分门保持，无完成结果便不调评分器。

登记a2668db3a5deab00b4b743865865cafdade66a1d已推送并验证远端，随后将用户
已有DeepSeek/复制本地case授权具体绑定到manifest。启动时间
2026-11-03T05:48:05.698813Z（北京时间13:48:05），外层监督耗时
17.443614665884525秒、rc2，无outer timeout。
Manifest SHA256：
`04db3c813d5855b73ff7943c550929c0e1b8d86a024fcd5e41bd1f91cbd167a1`。
实际request1,706 bytes/SHA256：
`b11ec4b2b4d7480f95aba75df507ab491b2f10c4726bb5294f165ab89f2880ed`，
与登记前独立重建一致。

准备及离线检查各只执行一次。能力probe在完整五键工具环境中确认Python3.13.12、
pandas3.0.6；launch时在实际subject cwd再次probe并与准备观察逐项相等。
固定subject PATH与独立评分process环境均经门禁，评分器仍使用原hash-locked venv。
4个adapter场景、27个拒绝场景和launcher的3个环境seam通过，234实际加载模块
匹配冻结源。Ruff、compileall、diff检查通过；临时编译缓存已移除。

原件位于主工作区ignored
`.lunar-evolution/validation/ordinary-public-environment-20261103/`；具体attempt在
`steel_coil_cutting/`。保留preparer、原helper、精确差异、能力stdout/stderr/process、
输入清单、登记及授权、history、请求进度、failure、原child与未评分终态。
独审分别核验helpers、prepared输入、接口脚本与接口结果。最终原件独审3,705 bytes/
SHA256 `674eb539250649814e10ed6bea188353d2a4f0fbdf28b49bc22334aff68e631b`
通过，仅确认失败记录：2,835源文件/308目录和240实际模块、case15/public6、
原13/旧14文件、212字节profile、20 assets及评测venv4,586/434均匹配。
初次lint的旧版本及已执行wrapper原件也保留，没有重跑已通过的能力准备或fake批次。

这是不同公开输入和环境的独立实验，不能替换之前失败或回填历史用量/解析分支。
HTTP200和参数拒绝定位也不解释旧响应头超时。当前P0仍缺真实普通模型完成并有效
评分的case；下一步应调查这次工具参数协议失败，现有证据不足以选择解析修复规则。
不能未经证据就放宽JSON解析、自动补括号或重试来制造成功。

native RSI P1仍缺实际不可变worker输入消费及完整构建保护，之后才是accepted
runtime/live owner、scheduler context和生产CLI验收。远程评测、多机服务及训练
仍后置；`production_admission=false`、`online_publication=false`。
