# Implementation plan

1. 固化 RSI 的状态、episode、verifier outcome、memory snapshot 和 transfer test 数据模型，
   提供只读解析和 canonical digest。（已完成协议 MVP。）
2. 增加 `SolverGateway` 和 `PracticeEpisodeRunner`，让 Actor 复用现有 solve/solver adapter，
   但把 contract/evaluator/memory snapshot 固定到一次 practice。
3. 增加独立 verifier 边界和 verifier-gated memory commit；外部 solver 分数只进入 provenance。
4. 实现 BRS wave 和 DRS target-gap-practice 调度，默认使用确定性 curriculum，
   再预留 LLM-assisted curriculum。（provider-free 控制器已完成；持久恢复仍开放。）
5. 实现 frozen-memory target runner、transfer receipt 和 no-memory-write guard。（已完成。）
6. 增加 CLI 或现有 `solve` 的显式 RSI 入口，补齐状态、诊断和恢复输出。
7. 用本地 mock solver、OpenEvolve fixture、Shinka export fixture 和失败/unknown/timeout
   fixture 完成 provider-free 回归，再考虑任何真实模型验收。

## MVP sequence

先实现单任务 DRS：一个固定 target、确定性 capability-gap curriculum、mock/native solver、
local exact evaluator、独立 verifier 和 immutable memory commit。它证明“target 失败后挑一个
练习，验证经验，再用同一 snapshot 重试 target”的完整闭环和恢复语义。之后再加入 BRS 并行
wave、OpenEvolve/Shinka fixture、LLM-assisted curriculum 和 frozen transfer benchmark。外部
producer score 始终只是 provenance，不是 memory approval。

Feature 044 Verified Experiment Memory 不被替换：它反馈一个候选搜索 run 内的 experiment
cards；Feature 160 管理跨 practice/target episode 的 verifier-gated snapshots。实现需为两个
数据域保留独立 schema、权限和 retrieval scope。
