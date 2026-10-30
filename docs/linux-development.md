# Linux / SSH 开发与本地回归

Linux 服务器可以并行执行 CPU 回归和独立开发切片。当前 provider-free 测试不需要 GPU；不要为 pytest 安装 CUDA、加载模型或预留 GPU。服务器结果是补充验证，不能替代 GitHub Actions 的三版 Python、完整角色矩阵及原始 artifacts 审计。

以下使用 Bash、Git、已安装的 Python 3.11+ 和 `uv 0.11.8`。示例选择系统已有的 `python3.12`；没有该命令时，将其替换为已核实版本的本地解释器。`uv venv` 不依赖系统 `ensurepip`，也不会下载 Python。将 SSH 目标和工作目录换成自己的环境；不要将 SSH 凭据、私钥或 `.env` 复制进 checkout。本文不安装 runner/service，也不配置远程 evaluator 或真实 producer campaign。遇到 native fixture 编译问题时保留原始日志、编译命令和 `cc --version`；保留严格编译 flags，不通过关闭 warnings/errors 掩盖失败。

## 隔离工作树与 Python 环境

先检查目标目录的 `git status --short` 和 `git worktree list`，保留已有修改。以明确的提交创建独立工作树；不要在正在验收的 candidate 上直接开发。

```bash
# 在现有仓库根目录执行；替换为已核实的提交。
revision="$(git rev-parse HEAD)"
dev_checkout="$(dirname "$PWD")/lunar-linux-dev"
git worktree add -b codex/linux-development "$dev_checkout" "$revision"
cd "$dev_checkout"

# SSH 非交互会话可能未把 user bin 加入 PATH。
export PATH="$HOME/.local/bin:$PATH"
# 确认输出为 uv 0.11.8、已安装的 Python 3.11+。
uv --version
python3.12 --version
uv venv --no-config --no-python-downloads --python python3.12 .venv
uv sync --locked --no-config --no-python-downloads --extra dev --extra lint
export PATH="$PWD/.venv/bin:$HOME/.local/bin:$PATH"
export PYTHONPATH="$PWD/src"

python -c 'import sys, lunar_evolution; print(sys.executable); print(lunar_evolution.__file__)'
lunar-evolution --help
```

每个 worktree 都重新建立自己的 `.venv`；不要复用另一 checkout 的 editable install 或 console launcher。`PYTHONPATH` 指向本 worktree 的 `src`，`lunar-evolution` 和 `python` 都从本 worktree 的 `.venv/bin` 启动。不要把虚拟环境加入 Git。

回归依赖必须来自 `uv.lock`。未锁定安装可能升级 pytest，改变参数化用例 ID，
导致历史清单核验或 hostile-object 收集失败。不要为适配依赖漂移而改历史源或清单 SHA。

修改后运行对应 focused tests，以及静态检查：

```bash
python -m pytest -q tests/test_regression_runner_shards.py
ruff check src tests tools
python -m compileall -q src tests tools
git diff --check
```

用改动实际覆盖的测试替换示例 focused test。运行 native fixture 前确认 Linux、C 编译器和所需内核功能可用；查看 skip、failure 和 error 的具体原因。

## 六个普通 current 分片与七个独立重用例

当前 CI 使用 `tools/run_tests.py`，六个普通分片统一 `--shard-count 6 --isolate-heavy`，另以 `current-heavy` 独立执行三个 DRS mixed 用例和四个 BRS serial 用例。十三个角色必须使用同一 Git 提交；普通分片与重用例的清单互斥，并集必须等于完整 collection。focused 和 history 仍分别运行，完整角色及 Python 版本以 [workflow](../.github/workflows/test.yml) 为准。

旧 `current --shard-count 6` 不带 `--isolate-heavy` 时仍完整运行六个 whole-file 分片；同文件的重用例会串行，可能超过 CI job 时限。已有旧版运行不要中途更换算法或补写 summary，新方案应另建目录和源码快照。

`current` 内的 runner 回归也会读取固定历史提交，因此 current 和 history 都需要先检查完整历史。浅 clone 在联网时先执行 `git fetch --unshallow origin`；也可以显式 fetch 下列固定对象。不要更改 runner 中的 pins 来绕过缺失历史。

先在仓库根目录检查固定对象，再创建一轮全新的目录和十三个独立 checkout。已有目录不要复用；结果和运行状态保留在 checkout 外。

```bash
set -euo pipefail
revision="$(git rev-parse HEAD)"
# 对应 tools/run_tests.py 的 archive/frozen/product pins；全部必须存在。
for pinned_commit in \
  c6947fdfbf43d84e83cc29cc215e7bc0250db83a \
  5560eb9f67463badc31fed17e309bb5dc1dabf8f \
  519fea5ca70ac1ede3df356ee7391112801ab45d; do
  git cat-file -e "$pinned_commit^{commit}" || exit 1
done
run_parent="$(dirname "$PWD")/lunar-local-runs"
mkdir -p "$run_parent"
run_root="$(mktemp -d "$run_parent/$(date -u +%Y%m%dT%H%M%SZ)-${revision:0:12}-XXXXXX")"
printf '%s\n' "$revision" > "$run_root/revision.txt"
for test_role in current-0 current-1 current-2 current-3 current-4 current-5 heavy-0 heavy-1 heavy-2 heavy-3 heavy-4 heavy-5 heavy-6; do
  shard_root="$run_root/$test_role"
  mkdir -p "$shard_root/home" "$shard_root/results"
  # binding 会重复记录绝对路径；使用短、独占的临时根，保持原字节上限。
  mktemp -d /tmp/le.XXXXXXXX > "$shard_root/tmp-root.txt"
  git worktree add --detach "$shard_root/checkout" "$revision"
  uv venv --no-config --no-python-downloads --python python3.12 \
    "$shard_root/checkout/.venv"
  uv sync --locked --no-config --no-python-downloads \
    --project "$shard_root/checkout" --extra dev --extra lint
done
printf 'run_root=%s\n' "$run_root"
```

为十三个角色分别运行下面一段，将 `run_root` 设为上一步打印的绝对路径，`test_role` 分别设为 `current-0` 到 `current-5`、`heavy-0` 到 `heavy-6`。每个角色独占 checkout、`.venv`、`TMPDIR`、Lunar home 和 results；不要让多个测试进程共享 SQLite/WAL 或同一临时目录。CPU 和内存资源由运行者按机器负载分配，先保守运行再增加并发。已有 `tmux` 时可在会话内运行测试，断线后重新 attach；不需要安装常驻服务。

```bash
run_root='/absolute/path/to/this-run'
test_role=current-0
case "$test_role" in
  current-[0-5]) suite_args=(--suite current --shard-index "${test_role#current-}" --shard-count 6 --isolate-heavy) ;;
  heavy-[0-6]) suite_args=(--suite current-heavy --heavy-index "${test_role#heavy-}") ;;
  *) echo 'invalid test role' >&2; exit 1 ;;
esac
shard_root="$run_root/$test_role"
cd "$shard_root/checkout"
export PATH="$PWD/.venv/bin:$HOME/.local/bin:$PATH"
export PYTHONPATH="$PWD/src"
export TMPDIR="$(cat "$shard_root/tmp-root.txt")"
export LUNAR_EVOLUTION_HOME="$shard_root/home"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

# 保存输入身份；不打印环境变量或凭据。
git rev-parse HEAD > "$shard_root/results/commit.txt"
git rev-parse 'HEAD^{tree}' > "$shard_root/results/tree.txt"
python --version > "$shard_root/results/python.txt" 2>&1

# 即使测试失败，也保存日志和原始退出码。
set +e
set -o pipefail
python tools/run_tests.py "${suite_args[@]}" \
  --junit-dir "$shard_root/results" \
  2>&1 | tee "$shard_root/results/pytest.log"
pipeline_status=("${PIPESTATUS[@]}")
printf '%s\n' "${pipeline_status[0]}" > "$shard_root/results/exit-status.txt"
printf '%s\n' "${pipeline_status[1]}" > "$shard_root/results/log-exit-status.txt"
```

`exit-status.txt` 非零表示测试失败，`log-exit-status.txt` 非零表示日志写入失败；缺少这些文件表示进程可能尚未结束或被中断。保留 JUnit XML、runner 生成的 provenance、stdout/stderr 日志和退出码；不要只看终端最后一行。SSH 断线时先检查原进程和结果，不要直接在原目录重跑。

同样保留每个 `tmp-root.txt` 指向的临时目录；其中可能包含定位失败所需的原始 fixture 证据。长 TMPDIR 会放大重复路径，可能使原本有效的 fixture binding 超过既有 32 KiB 上限；不要提高生产上限来容纳测试目录。短路径只修正测试布局，不是对生产 byte bound 的豁免。

上面的历史对象检查也适用于单独运行 history。缺少对象时先补齐仓库，再创建新的结果目录运行；不能把缺少历史导致的 setup error 计为功能已通过。

history 会用 uv 离线建立历史环境，因此预先用同一个 uv cache 安装锁定的 package/build 依赖，并预热精确锁版本的 registry metadata。仅通过 pip 安装或 `uv sync --locked` 下载 wheel 不保证离线 resolver metadata 已缓存；缺少时，history 会在测试收集前拒绝建立环境。以下在已建立的独立 history checkout 和 `.venv` 内运行；测试前不切换 `UV_CACHE_DIR`，也不要清理该 cache：

```bash
mkdir -p .lunar-evolution/test-results
uv export --locked --no-hashes --no-emit-project --extra dev --extra lint \
  --output-file .lunar-evolution/test-results/ci-locked-requirements.txt
uv pip compile --no-config --no-python-downloads --python .venv/bin/python \
  .lunar-evolution/test-results/ci-locked-requirements.txt \
  --output-file .lunar-evolution/test-results/ci-registry-metadata.txt
```

这一步只在线解析锁定版本并缓存 registry metadata，不重新安装或升级环境；历史执行本身仍使用原 `--offline` 安装流程。保留这两个清单及首次失败日志，再由完整 CI 验证实际缓存命中。

需要 history 时使用另一独立 checkout、环境和结果目录，运行 `python tools/run_tests.py --suite history --junit-dir /absolute/path/to/results`，同样捕获日志和退出码。focused 角色需要逐项执行 workflow 的约束；仅运行一个 focused test 不等于完成该角色。

## 结果边界与清理

九个 current 角色通过仅证明该提交在这台机器上的 current 测试结果。正式合入仍需核实精确 head/base、GitHub Actions 全部必需角色、原始 artifact 和 source/tree provenance。provider-free 成功不代表真实 solver、原生工具链或生产 admission 已验收；`production_admission=false` 保持原有边界。

结束前保留需要审查的日志和提交身份。只在确认没有运行中的测试、需要保留的修改或未归档产物后，才使用 `git worktree remove` 清理对应 checkout；日志位于外部 results，可独立保留。各 `tmp-root.txt` 中的短临时根也应先检查和归档，再由创建者单独清理，不要删除其他用户或其他运行的 `/tmp` 目录。开发记录和后续验收条件见 [当前发布台账](current-release-backlog.md)。
