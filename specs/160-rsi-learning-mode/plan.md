# Implementation plan

1. 固化 RSI 的状态、episode、verifier outcome、memory snapshot 和 transfer test 数据模型，
   提供只读解析和 canonical digest。（已完成协议 MVP。）
2. 增加 `SolverGateway` 和 `PracticeEpisodeRunner`，让 Actor 复用现有 solve/solver adapter，
   但把 contract/evaluator/memory snapshot 固定到一次 practice。
3. 增加独立 verifier 边界和 verifier-gated memory commit；外部 solver 分数只进入 provenance。
4. 实现 BRS wave 和 DRS target-gap-practice 调度，默认使用确定性 curriculum，
   再预留 LLM-assisted curriculum。（持久控制器及确定性 diversity/failure-boundary 历史反馈已完成。）
5. 实现 frozen-memory target runner、transfer receipt 和 no-memory-write guard。（已完成。）
6. 增加显式 RSI CLI，补齐状态、诊断和恢复输出。（run/inspect/resume/result-backed reconcile 已完成。）
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

## 2026-09-29 implementation boundary

`recovery-design.md`、`verifier-design.md`、`curriculum-design.md` 对应实现已经落地。
本地 native gateway 执行真实候选/评测子进程；独立 verifier 在新的隔离工作目录重评，
并保留可只读复验的终态证据。它仍不是 OS sandbox 或真实模型 Actor 验收。
后续按现有 SDD 完成 frozen-memory baseline 对照、外部 producer 生产边界及独立真实验收，
不重新设计三层架构，也不把 fixture solver 名称当成已启动开源 campaign。
