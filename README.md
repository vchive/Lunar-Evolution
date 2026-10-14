# Lunar Evolution

[![CI](https://github.com/vchive/Lunar-Evolution/actions/workflows/test.yml/badge.svg)](https://github.com/vchive/Lunar-Evolution/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-2ea44f)](pyproject.toml)

Lunar Evolution 是一个**本地优先、可恢复、可审计**的 Agent 与算法演化控制器。它把任务计划、执行、评测、产物和恢复状态写入本地 ledger 与 run workspace；模型、solver 和 evaluator 都通过显式 adapter 接入。

当前主线是单机 provider-free 可靠执行和 RSI（recursive/self-improving learning）控制闭环。RSI producer 路径默认保持 `production_admission=false`；本地 fixture 用于验证执行和恢复流程，真实 solver campaign 仍需独立验收。普通任务的模型接口可以按显式配置使用。

## 当前状态

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 普通任务与 `solve` | ✅ 可用 | 本地 plan、AgentLoop、评测、artifact 和 delivery ledger。 |
| provider-free RSI（DRS/BRS） | ✅ 可回归 | 本地 mock/fixture，支持 run、inspect、resume、usage、replay、reconcile。 |
| durable resume / unknown gate / fingerprint / budget | ✅ 已接入 | 恢复前复核原 checkpoint、预算、deadline 和组件身份；未知状态 fail-closed。 |
| 逐 episode producer 执行 | 🧪 实验 API | 单 child 本地 fixture 已贯穿 claim、发布、verifier 和恢复；需显式 `producer_child_execution=True`，默认保持 staging-only，多 episode 尚未验收。 |
| native producer / OpenEvolve / ShinkaEvolve 真实 campaign | ⏳ 未验收 | 需要真实 source、toolchain、runtime、process lifecycle 和独立 acceptance evidence。 |
| 远程 evaluator、多机 worker、分布式 scheduler | ⏸ 后置 | 不属于当前单机 RSI 正确性的前置条件。 |

因此，当前仓库适合做本地协议回归、恢复测试和架构开发；它不是已经上线的远程演化服务，也不宣称与任何外部 Agent 或评测平台效果持平。

## 主要能力

- **普通任务执行**：把 goal 编译成有依赖关系的 plan，调度本地 task，记录 attempt、evaluation、artifact 和事件。
- **会话式算法求解**：`solve` 先生成严格的 `AlgorithmProblemContract`，再运行 `data_discovery → formulate → solve → verify`；可以选择本地 population evolution，或显式配置本地 OpenEvolve 命令。
- **受控产物交付**：候选源文件在隔离 workspace 中执行，交付前检查路径、格式、大小和 SHA-256；多文件发布、execution、delivery 和恢复证据都保留在 ledger 中。
- **RSI learning mode**：DRS（围绕目标缺口逐步深入）和 BRS（在冻结 wave 上横向展开）共享 run 预算、component fingerprint、memory governance 和 transfer evidence。
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

所有状态都放在 `--home` 指定的目录中，默认是当前目录的 `.lunar-evolution/`。mock runtime 不读取网络、模型、凭据或机器上的其他 Agent 状态。

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

连接 OpenAI-compatible endpoint 时必须显式提供 endpoint 和 model。密钥只从环境变量读取，不要把它写进仓库或命令历史：

```bash
export LUNAR_EVOLUTION_MODEL_ENDPOINT='http://127.0.0.1:11434/v1/chat/completions'
export LUNAR_EVOLUTION_MODEL='your-local-model'

lunar-evolution solve '分析订单并给出可验证的路线方案' \
  --runtime openai-compatible \
  --endpoint "$LUNAR_EVOLUTION_MODEL_ENDPOINT" \
  --model "$LUNAR_EVOLUTION_MODEL" \
  --home .lunar-evolution --json
```

先在运行环境中配置 `LUNAR_EVOLUTION_API_KEY`。普通 CLI 不自动加载 `.env`；配置字段可参考 [`.env.example`](.env.example)。需要工具调用时显式加 `--agent-loop`；`--max-steps`、workspace、超时和 artifact 限制仍由 Lunar 控制。

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
  --suite current --shard-index 0 --shard-count 3 \
  --junit-dir .lunar-evolution/test-results
```

测试保持 provider-free，不会因为运行测试而发起模型调用、远程 evaluator 或真实 solver campaign。

## 路线图与明确边界

### P0：完成本地闭环

- 验收单 child 的 controller → gateway → scheduler → admission/publication → verifier → recovery 链路。
- 支持连续发布及历史批次恢复，再验收 practice success、target retry、新 approved memory 和多 child。
- 在本地 fixture 覆盖取消、deadline、中断、只读证据恢复和原 episode settlement。
- 为每个 side effect 保留 launch、execution、receipt、publication 和 unknown reconcile 证据。

### P1：接入真实本地运行时

- 独立核验 Python source/toolchain/runtime，完成 sealed startup、loader negative tests、owner/lifecycle 和 Linux acceptance matrix。
- 为本地 OpenEvolve/Shinka 增加受 pin 约束的 process adapter、result export、cancel/cleanup、producer admission 和 opt-in CLI。
- 不改变 provider-free 默认值，不把 producer score 直接当作 official verdict。

### P2：后置能力

remote evaluator、external worker authentication、multi-host ownership、distributed scheduler、service API、remote Shinka/Slurm，以及模型训练/SFT/RL 都需要单独定义身份、租约、故障和部署边界，不是当前单机 RSI 正确性的前置条件。

当前工作台账、结束条件和证据分级见 [`docs/current-release-backlog.md`](docs/current-release-backlog.md)；系统架构见 [`docs/architecture.md`](docs/architecture.md)。

## 贡献与许可证

`pyproject.toml` 声明项目使用 MIT license。提交代码时请同时更新对应 SDD spec、focused tests 和验证记录；不要提交 provider 凭据、远程运行结果或未经独立核验的 producer evidence。
