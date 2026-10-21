# Lunar Evolution

[![CI](https://github.com/vchive/Lunar-Evolution/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/vchive/Lunar-Evolution/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-2ea44f)](pyproject.toml)

Lunar Evolution 是一个**本地优先、可恢复、可审计**的 Agent 与算法演化控制器。它管理从任务计划、候选生成、评测到产物交付的完整链路，并把预算、执行记录和恢复证据保留在本地。

你可以用 CLI 执行普通任务和算法求解，也可以用 Python API 组合 solver、verifier 与 RSI 学习流程。模型和本地 solver 按显式配置接入；默认回归使用 mock/fixture，可以在没有模型服务和密钥的环境中运行。

当前主线是单机可靠执行和 RSI（递归学习）控制闭环。RSI 改进候选程序与经验证的任务记忆；模型权重训练和修改 Lunar 自身代码不在当前主线内。RSI producer 路径保持 `production_admission=false`，真实 solver campaign 仍需独立验收。

截至 2026-10-21，`main` 已包含 PR153/154/155/160/161/165/166/169/170/173/176/177/178/179/182；当前 HEAD 还包含安装与构建产物 pin 绑定、完整 build provenance section 校验、reserved serial worker 的绝对 deadline/unknown fence、输入/结果 placeholder pin 拒绝，以及启动失败诊断与
retained producer-process 生命周期 CLI、Python producer receipt 的 task/timeout 绑定、
OpenEvolve/Shinka 项目生命周期 profile preflight、retained Python terminal 的只读
binding/deadline 检查、static Python no-dynamic recipe gate、acceptance envelope provenance
绑定、retained producer acceptance 的只读组合 CLI、5090gpu frozen bootstrap 与 linecache
closure 观察、detached replay schema 收紧、producer cleanup 生命周期门禁，以及 producer
adapter 的固定失败分类与 cleanup uncertainty 优先级。它们都只提供本地、只读或 provider-free plumbing；真实
sealed runtime、producer campaign 和生产准入仍未开放。

[本地试跑](#五分钟本地试跑) · [RSI 示例](#rsi-provider-free-回归) · [执行链路](#执行链路) · [架构说明](docs/architecture.md) · [剩余工作与验收条件](docs/current-release-backlog.md)

## 当前状态

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 普通任务与 `solve` | ✅ 可用 | 本地 plan、AgentLoop、评测、artifact 和 delivery ledger。 |
| 外部优化 case 本地 smoke | 🧪 已验证 | [基础记录](docs/benchmark-case-smoke-20261020.md)、[irregular packing](docs/benchmark-case-smoke-20261021.md) 与[剩余 case](docs/benchmark-case-smoke-20261021-remaining.md)：复制的 `train_delay_rescheduling`、`city_delivery_routing`、`hospital_or_scheduling`、`irregular_packing`、`steel_coil_cutting`、`supply_chain_inventory`、`ore_reclaiming_scheduling` 已完成原 evaluator 的合法/负向检查；材料在 ignored validation 目录，不改变生产准入。 |
| provider-free RSI（DRS/BRS） | ✅ 可回归 | 本地 mock/fixture；支持 run、inspect、resume、usage、replay、reconcile，不启动真实 producer。 |
| durable resume / unknown gate / fingerprint / budget | ✅ 已接入 | 恢复前复核原 checkpoint、预算、deadline 和组件身份；未知状态保留证据并拒绝自动重试。 |
| 单 child producer 执行 | 🧪 已合入的实验 API | PR99 已在 main；显式 `producer_child_execution=True` 的本地 fixture 闭环已验收，默认保持 staging-only。 |
| 同 workspace 连续 DRS 发布 | ✅ P0 控制链已合入 | 三个不同 child、练习记忆晋级、目标重试与历史只读恢复已完成主线控制链；真实 producer/runtime 仍按 P1 独立验收。 |
| DRS known rejection | ✅ P0 控制链已合入 | 原 owner、连续 reconcile、早期中断及三组混合链已纳入主线；真实运行时来源仍不因 fixture 通过而自动放行。 |
| BRS partial-wave resume | ✅ provider-free 单机链路已合入 | Reserved projection/prefix、全域 ledger/reservation、fresh child preparation exchange、native provider/completion、serial owner、terminal lifecycle、exact root settlement、partial-wave resume 与 finalization replay 已在 PR138 合入；自然 inert 混合波按 ordinal 完成并保持 128 KiB reserved checkpoint 上限。真实 CPython/producer/runtime 仍需独立验收。 |
| 多 child native BRS | 🧪 私有 provider-free 路径 | 已有 owner/mailbox、result CAS、delivery/settlement、serial successor 和显式 reconcile API。未消费的 BRS obligation 会阻止默认恢复、推进和终结；消费时核对原始记录的合法后继、持久化终态及 native claim/result。四个自然 inert serial integration case 已通过；serial continuation 仍保持 private，public native BRS 与生产 admission 关闭。 |
| Feature189 static-Python build probe receipt | ✅ 已合入 | `lunar-static-python-build-probe-v1` 只保存真实构建、ELF 和启动观察；5090gpu 的原始 stock image 仍在 `encodings` 前失败，后续 no-dynamic fixed-main inert probe 已通过 broker/loader-negative 观察但仍不授予 sealed runtime 或生产准入。 |
| static Python 启动失败诊断 | 🧪 诊断工具已接入 | [PR153](https://github.com/vchive/Lunar-Evolution/pull/153) 增加 bounded stderr 摘要与固定失败分类；只保留 digest/size，`runtime_execution_performed=false`、`production_admission=false`，不能替代 sealed startup 验收。 |
| retained producer-process 生命周期 CLI | 🧪 本地 plumbing 已接入 | [PR153](https://github.com/vchive/Lunar-Evolution/pull/153) 提供只读 `producer-process inspect` 与显式确认的 `producer-process cleanup --confirm`；沿用 owner/recovery gate，仍保持 `production_admission=false`，不启动真实 producer 或 campaign。详见 [`docs/local-producer-process-cli.md`](docs/local-producer-process-cli.md)。 |
| retained Python producer terminal CLI | 🧪 本地只读门禁已接入 | [PR160](https://github.com/vchive/Lunar-Evolution/pull/160) 校验 terminal 的 binding/deadline，`unknown` 固定返回 `reconcile_required`；不初始化 ledger、不启动 producer/evaluator，保持 `production_admission=false`。详见 [`docs/local-producer-process-cli.md`](docs/local-producer-process-cli.md)。 |
| static Python no-dynamic recipe gate | ✅ 描述符门禁已合入 | [PR161](https://github.com/vchive/Lunar-Evolution/pull/161) 拒绝 shared/PIE/dynamic-loader flags、共享 link inputs、重复或 shell-like 值；这是构建前策略检查，不等于实际 ELF/sealed runtime 验收。 |
| static Python acceptance envelope provenance | ✅ provider-free 边界已合入 | [PR165](https://github.com/vchive/Lunar-Evolution/pull/165) 将 descriptor、source/toolchain/frozen/link/artifact 的 detached pins 绑定到 canonical wire；`detached-pins-only` 不代表真实构建或 sealed runtime。 |
| retained producer acceptance envelope | 🧪 本地只读组合已接入 | [PR166](https://github.com/vchive/Lunar-Evolution/pull/166) 提供 `rsi producer-acceptance`，组合 project preflight、terminal 和可选 replay；始终 `blocked/runtime_acceptance_required`，不初始化 ledger、不启动 producer/evaluator。 |
| detached static-Python acceptance CLI | 🧪 provider-free 组合已接入 | [PR182](https://github.com/vchive/Lunar-Evolution/pull/182) 提供 `rsi static-python-acceptance`，以独立 canonical pins 组合 installation/build/startup/input-result/handoff DTO；命令只读、始终 `status=blocked`，不启动 runtime/evaluator，`production_admission=false`。输入/结果 DTO 同时拒绝全零和全 f 占位 digest。 |
| producer cleanup lifecycle gate | ✅ provider-free 门禁已加固 | [PR176](https://github.com/vchive/Lunar-Evolution/pull/176) 要求已知 terminal 只能在 `cleaned` 或 `already_exited` 证据下进入组合 envelope；`unknown`/`missing` 和未审计标签 fail closed，不启动 producer/evaluator。 |
| producer adapter failure fence | ✅ provider-free 门禁已加固 | [PR178](https://github.com/vchive/Lunar-Evolution/pull/178) 为取消、deadline、cleanup uncertainty 保留固定生命周期错误码，并在 native 失败后复核 binding sidecar；[PR179](https://github.com/vchive/Lunar-Evolution/pull/179) 让 cleanup uncertainty note 覆盖更窄的取消/deadline 标签。 |
| frozen bootstrap closure observation | 🧪 5090gpu 诊断已记录 | [PR169](https://github.com/vchive/Lunar-Evolution/pull/169) 记录静态 ELF、`--version/--help` 成功，以及 command-body/codec 路径因 `linecache` 缺失失败；不构成 sealed runtime 或 production acceptance。 |
| linecache closure observation | 🧪 受控诊断已记录 | [PR173](https://github.com/vchive/Lunar-Evolution/pull/173) 将 source-owned `linecache.py` 冻结进 no-dynamic fixed-main，验证 `sys_path=[]`、静态 ELF 与 loader-negative；完整 stdlib closure、owner/lifecycle 和 production admission 仍未验收。 |
| next frozen stdlib closure probe | 🧪 5090gpu 受控诊断已记录 | [linecache closure probe](specs/189-static-python-fixture/linecache-closure-probe-20261020.md) 证明 `linecache` 加入冻结表后 `-S -c` 可继续到 `traceback`，并保留完整 source/toolchain/ELF/sealed runtime 缺口；不是发布构建。 |
| detached replay schema gate | ✅ provider-free 边界已加固 | [PR170](https://github.com/vchive/Lunar-Evolution/pull/170) 对 acceptance envelope 的 replay report 强制四字段闭合 schema 和固定类型，拒绝未审计字段/path/authority。 |
| Python producer task/timeout binding | ✅ 已合入 | PR154 将 `parent_task_id`、`task_id` 和 `request_timeout_seconds` 绑定到 terminal receipt；漂移返回 `receipt_binding_drift`，focused regression 保持 provider-free。 |
| project lifecycle profile preflight | 🧪 只读门禁已合入 | PR155 校验 source/runtime/toolchain/request/result 摘要及固定 bootstrap、cancel、resume 模式；有效 profile 仍返回 `blocked/runtime_acceptance_required`，不启动项目、evaluator 或 RSI ledger。`--diagnostics` 可输出 path-free capability matrix，明确生产 RSI CLI 的剩余门禁。 |
| project/producer lifecycle diagnostics | 🧪 provider-free 验收投影 | `rsi project-preflight --diagnostics` 固定列出 startup、cancel、deadline、parent-loss、cleanup、restart 及漂移场景；`producer_lifecycle_diagnostics` 对 retained phase evidence 做只读 owner/lifecycle 检查。完整报告仍不授予 runtime、production admission 或 publication。详见 [`docs/producer-lifecycle-diagnostics.md`](docs/producer-lifecycle-diagnostics.md)。 |
| native producer / OpenEvolve / ShinkaEvolve 真实 campaign | ⏳ 未验收 | 需要真实 source、toolchain、runtime、process lifecycle 和独立 acceptance evidence。 |
| 远程 evaluator、多机 worker、分布式 scheduler | ⏸ 后置 | 不属于当前单机 RSI 正确性的前置条件。 |

BRS 中断恢复需要显式提交证据；普通 `resume` 遇到未消费的 obligation 会返回 `rsi_brs_reconcile_required`。只有与本地 ledger 终态、原 native plan/claim 和已保存 result 一致的证据才能消费对应 obligation；unknown、running 和 drift 保留记录。多条 obligation 分别处理，单次消费在同一个 SQLite 事务内完成校验和 checkpoint CAS。批量 API 按项提交，后项失败时已成功项保持提交，调用方应先读取剩余 obligation。PR138 已将 private reserved-wave serial 的 owner admission、mailbox、terminal、root settlement 和 partial-wave resume 接入 main；public native BRS、真实 producer/runtime 和生产 CLI 仍保持独立门禁。详见[恢复契约](specs/196-brs-owner-worker-handoff/reconcile-controller-consume.md)、[mailbox 登记契约](specs/196-brs-owner-worker-handoff/owner-mailbox-reconcile-registration.md)、[serial contract](specs/196-brs-owner-worker-handoff/reserved-wave-serial.md)及[发布台账](docs/current-release-backlog.md)。

## 主要能力

- **普通任务执行**：把 goal 编译成有依赖关系的 plan，调度本地 task，记录 attempt、evaluation、artifact 和事件。
- **会话式算法求解**：`solve` 先生成严格的 `AlgorithmProblemContract`，再运行 `data_discovery → formulate → solve → verify`；可以选择本地 population evolution，或显式配置本地 OpenEvolve 命令。
- **受控产物交付**：候选源文件在隔离 workspace 中执行，交付前检查路径、格式、大小和 SHA-256；多文件发布、execution、delivery 和恢复证据都保留在 ledger 中。
- **RSI learning mode**：DRS 围绕目标缺口生成练习、验证记忆再重试目标；BRS 在冻结 wave 上横向展开。两者共享 run 预算、组件指纹、记忆治理和迁移证据。
- **证据优先恢复**：已完成的 side effect 只读重放；`unknown`、证据缺失、身份漂移、取消和 deadline 不会自动 retry 或晋级。

## 安装

要求 Python 3.11 或更高版本。运行时没有第三方依赖；下面安装 pytest、ruff，并使用与 CI 一致的 uv 版本建立开发环境。

```bash
git clone https://github.com/vchive/Lunar-Evolution.git
cd Lunar-Evolution
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'uv==0.11.8'
uv pip install --python .venv/bin/python -e '.[dev,lint]'
```

## 五分钟本地试跑

本地状态目录优先使用 `--home`，其次使用 `LUNAR_EVOLUTION_HOME` 环境变量，未配置时使用当前目录的 `.lunar-evolution/`。mock runtime 不读取网络、模型、凭据或机器上的其他 Agent 状态。

```bash
lunar-evolution init --home .lunar-evolution --json
mkdir -p .lunar-evolution/demo
lunar-evolution run '生成一个本地执行报告' \
  --runtime mock --home .lunar-evolution --json \
  > .lunar-evolution/demo/run.json

RUN_ID="$(python -c 'import json; print(json.load(open(".lunar-evolution/demo/run.json"))["run_id"])')"
lunar-evolution status "$RUN_ID" --home .lunar-evolution --json
lunar-evolution events "$RUN_ID" --home .lunar-evolution --json
```

成功时 `run.json` 包含 `run_id`、`status=succeeded` 和 `workspace`。mock 产生确定性的演示结果；真实业务任务需要配置模型或求解器。任务文件和产物保留在返回的 workspace 中。需要恢复时使用原来的 run ID：

```bash
lunar-evolution resume "$RUN_ID" \
  --runtime mock --home .lunar-evolution --json
```

### `solve` 与本地模型

没有模型服务时，先用 mock 编译和执行控制链：

```bash
lunar-evolution solve '根据订单数据设计配送路线' \
  --runtime mock --home .lunar-evolution --json
```

连接 OpenAI-compatible endpoint 时，以下示例显式提供 endpoint 和 model。建议通过环境变量提供密钥，避免写进仓库或命令历史：

```bash
export LUNAR_EVOLUTION_MODEL_ENDPOINT='http://127.0.0.1:11434/v1/chat/completions'
export LUNAR_EVOLUTION_MODEL='your-local-model'

lunar-evolution solve '分析订单并给出可验证的路线方案' \
  --runtime openai-compatible \
  --endpoint "$LUNAR_EVOLUTION_MODEL_ENDPOINT" \
  --model "$LUNAR_EVOLUTION_MODEL" \
  --home .lunar-evolution --json
```

endpoint 需要认证时，先在运行环境中配置 `LUNAR_EVOLUTION_API_KEY`；不需要认证的本地服务可以省略。普通 CLI 不自动加载 `.env`；配置字段可参考 [`.env.example`](.env.example)。需要工具调用时显式加 `--agent-loop`；`--max-steps`、workspace、超时和 artifact 限制仍由 Lunar 控制。

## RSI provider-free 回归

下面的命令只运行本地 fixture。`--solver` 记录 solver provenance，但不会启动 OpenEvolve、Shinka、远程 evaluator 或真实模型。

```bash
mkdir -p .lunar-evolution/demo
cat > .lunar-evolution/demo/rsi-contract.json <<'JSON'
{"problem_id":"readme-fixture"}
JSON

lunar-evolution rsi run .lunar-evolution/demo/rsi-contract.json \
  --run-id readme-rsi \
  --mode drs \
  --solver mock \
  --max-practice-rounds 1 \
  --max-target-attempts 2 \
  --usage-ledger .lunar-evolution/demo/rsi-usage.json \
  --home .lunar-evolution \
  --json
```

这里的最小 JSON 仅作为 fixture 演示输入；普通 `evolve` 使用完整算法合同。正常结果包含 `status=completed`、目标／练习统计、`solver_execution=provider_free_fixture` 和 `production_admission=false`。
在同一个 home 内开始另一轮演示时，使用新的 `--run-id`；恢复已有演示沿用原 ID。

```bash
lunar-evolution rsi inspect readme-rsi --home .lunar-evolution --json
lunar-evolution rsi usage .lunar-evolution/demo/rsi-usage.json --json
lunar-evolution rsi resume readme-rsi \
  --usage-ledger .lunar-evolution/demo/rsi-usage.json \
  --home .lunar-evolution --json
```

`resume` 复核原 run 的计划、预算、deadline、组件身份和历史记忆。结果为 `unknown` 时需要显式对账，控制器不会自动重启。已有 producer 结果的 `replay` 需要原始文件和独立摘要；高级恢复／重放接口见下面的运行时说明。

未来 OpenEvolve/Shinka 项目接线先经过只读 profile preflight；它只校验固定的 source/runtime/toolchain/request/result 摘要和受控的启动、取消、恢复模式，不启动项目或 evaluator：`lunar-evolution rsi project-preflight PROFILE.json --json`。有效 profile 仍返回 `status=blocked`，直到 sealed runtime、entrypoint 和 Linux lifecycle 验收证据齐全。详见 [`project-lifecycle-preflight.md`](specs/160-rsi-learning-mode/project-lifecycle-preflight.md)。

更完整的 Python API、数据模型、DRS/BRS wave、memory promotion、Actor clean-room evidence 和 producer receipt 说明见 [`docs/rsi-local-runtime.md`](docs/rsi-local-runtime.md) 与 [`specs/160-rsi-learning-mode/`](specs/160-rsi-learning-mode/)。

## 执行链路

```mermaid
flowchart LR
    U[CLI / parent Agent] --> C[普通任务控制器]
    C --> P[任务计划 / AgentLoop]
    P --> R[Mock / 模型 / 本地 adapter]
    R --> E[评测与交付检查]
    E --> A[结果与产物]
    C --- L[(普通任务状态库)]

    U --> X[RSI 学习控制器]
    X --> Q[目标 / 练习 episode]
    Q --> G[SolverGateway]
    G --> V[Verifier + receipts]
    V --> M[经验证并接纳的记忆快照]
    M --> X
    M -. 可选 .-> H[冻结记忆迁移测试]
    H --> X
    X --- S[(RSI 状态库)]
```

CLI 选择入口，controller 管理执行、预算、持久状态和恢复；runtime／solver 负责产生候选和执行结果。评测、verifier 判断、记忆晋级和产物交付分别保留证据，未知结果进入恢复门禁。

普通任务和 RSI 都是单机流程；模型接口和本地 solver 按显式配置接入。完整架构与尚未验收的 native producer 边界见 [`docs/architecture.md`](docs/architecture.md) 和 [`docs/rsi-local-runtime.md`](docs/rsi-local-runtime.md)。

## 本地数据布局

```text
.lunar-evolution/
├── state.db                 # 普通任务 ledger
├── rsi.sqlite3              # RSI run / episode / receipt ledger
└── runs/<run-id>/            # prompt、result、evaluation、候选和发布证据
```

文件会记录 SHA-256、大小、相对路径，以及需要时的 inode/launch identity。不要手动编辑已完成 run 的证据文件来“修复”状态。

## 验证与开发

```bash
# RSI focused regression
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_rsi_*.py

# 当前测试
PYTHONPATH=src .venv/bin/python -m pytest -q

# 静态检查
.venv/bin/ruff check src tests tools
.venv/bin/python -m compileall -q src tests tools
git diff --check
```

GitHub Actions 在 Ubuntu 上运行 Python 3.11/3.12/3.13 的 focused、current shards 和 history jobs。需要复现 current shard 时：

```bash
.venv/bin/python tools/run_tests.py \
  --suite current --shard-index 0 --shard-count 6 --isolate-heavy \
  --junit-dir .lunar-evolution/test-results
```

完整 current 覆盖需要普通分片 0–5，以及三个独立重用例。重用例使用各自新结果目录，
分别运行 `--suite current-heavy --heavy-index 0`、`1`、`2`；它们与普通分片的精确
清单互斥且并集等于完整 collection。省略 `--isolate-heavy` 的旧 current 命令仍按
完整文件划分全部用例，但会把同文件的三个重用例放在同一分片，可能超过 CI job 时限。

测试保持 provider-free，不会因为运行测试而发起模型调用、远程 evaluator 或真实 solver campaign。

Linux / SSH 服务器的独立环境、六个普通分片加三个重用例的并行运行和日志保留步骤见 [Linux 开发指南](docs/linux-development.md)。

## 路线图与明确边界

### P0：收尾当前 DRS/BRS 发布批次

单 child 的 controller → gateway → scheduler → admission/publication → verifier → recovery 链路，以及 reserved-wave serial owner/ledger/terminal/finalization 链路，已经合入 `main`（PR138，`af1cc62`）。Feature189 的真实构建观察 receipt 也已合入（PR144/145，`cb33a38`/`d6ce8a9`）。这些合入关闭的是 provider-free 控制链和证据传输，不会把本地 fixture 或一次静态链接自动升级为生产能力。

恢复始终复核原 claim、预算、身份、deadline 与取消门禁；没有原始证据的中断保留 unknown，不启动后继 child。

### P1：多 child BRS 与真实本地运行时

- 独立核验 Python source/toolchain/runtime，完成 sealed startup、loader negative tests、owner/lifecycle 和 Linux acceptance matrix。当前 5090gpu 的原始静态 CPython 在 `encodings` 前失败；冻结 `encodings` 的实验镜像可以空启动但仍缺少完整 stdlib closure，sealed runtime 和 lifecycle 仍开放。
- 基于已有 adapter/exporter 接通实际 OpenEvolve/Shinka project lifecycle、cancel/cleanup、producer admission 和生产用 opt-in CLI。PR155 目前只提供只读 profile preflight；`rsi run` 默认保持 provider-free fixture，真实 project entrypoint 仍需独立验收。
- 保留 provider-free 默认值；producer score 仍须经独立 verifier/evaluation 才能产生官方结论。

### P2：后置能力

远程 evaluator、外部 worker 来源认证、多机 ownership、分布式 scheduler、service API、远程 Shinka/Slurm，以及模型训练/SFT/RL 均后置。它们需要独立的身份、租约、故障与部署契约，不是本轮单机 DRS 发布的出口条件。

当前工作台账、结束条件和证据分级见 [`docs/current-release-backlog.md`](docs/current-release-backlog.md)；系统架构见 [`docs/architecture.md`](docs/architecture.md)。

## 贡献与许可证

`pyproject.toml` 声明项目使用 MIT license。提交代码时请同时更新对应 SDD spec、focused tests 和验证记录；不要提交 provider 凭据、远程运行结果或未经独立核验的 producer evidence。
