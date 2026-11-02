# DeepSeek 钢卷裁切本地 smoke（2026-11-02）

原160,000-token预算尝试已失败：22次请求全部HTTP200，观测累计169,992tokens
超过登记阈值；仅接纳21轮、155,656tokens（152,910输入、2,746输出）及28个
工具结果。触发轮13,065输入+1,271输出=14,336tokens未接纳，保留partial边界。
Subject耗时117.46290920861065秒，rc2，schema2 runtime/budget_exceeded。

没有传输失败、完成receipt、solution.csv或本地评分；分数为null。原child已回收、
pipe EOF验证，无watchdog信号。预算失败未改写为成功，未调用评分器验证或修补
中间产物。见[原预先登记规格](../specs/061-subject-failure-diagnostics/deepseek-steel-case-acceptance.md)。

该案例在查看评分接口前，仅按公开数据复杂度选定：50母卷、51需求、两份小CSV。
原instruction和information、数据及评分器保持字节不变，只新增明确的公开CSV
提交契约。原评分器依赖pandas，因此另备hash-locked独立venv；已安装依赖约
95MiB，不修改owner或开发环境。模型失败后，评测环境4,586文件/434目录保持
一致，评测前专用快照不存在，与未启动evaluator一致。首依赖import30秒超时原件
单列保留；后续导入preflight通过，均非模型或评分调用。

登记提交93831e75推送后，于`2026-11-02T13:51:48.247337Z`单次启动，零重试。
执行源始终是f3257898/tree dfb61885（2,826文件/308目录），非后继source-pin
修正源；240实际模块来源匹配，case14/original13/profile及全部旧train/hospital
原件pins未变。独立终态审查报告11,564字节，SHA256：
`43c4d7d59114909b1a63df8354a1e27ebbda6dd0b9aef01b7cdf0d0c6773200b`。
审查通过仅确认这份失败记录。原件位于主工作区 ignored
`.lunar-evolution/validation/deepseek-steel-case-20261102/steel_coil_cutting/`。

下一次仅按[独立扩展预算规格](../specs/061-subject-failure-diagnostics/deepseek-steel-extended-acceptance.md)
另建profile/manifest/attempt：80工具、100万观测tokens，模型、3,000秒、16,384
生成上限、案例及评分器不变。该新实验保留全部旧失败，不续跑旧attempt；不再
追加预算升级。真实E2E P0及native RSI P1均未因本记录关闭。
