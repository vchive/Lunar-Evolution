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

# 确认输出为 uv 0.11.8、已安装的 Python 3.11+。
uv --version
python3.12 --version
uv venv --no-config --no-python-downloads --python python3.12 .venv
uv pip install --no-config --python .venv/bin/python -e '.[dev,lint]'
export PATH="$PWD/.venv/bin:$PATH"
export PYTHONPATH="$PWD/src"

python -c 'import sys, lunar_evolution; print(sys.executable); print(lunar_evolution.__file__)'
lunar-evolution --help
```

每个 worktree 都重新建立自己的 `.venv`；不要复用另一 checkout 的 editable install 或 console launcher。`PYTHONPATH` 指向本 worktree 的 `src`，`lunar-evolution` 和 `python` 都从本 worktree 的 `.venv/bin` 启动。不要把虚拟环境加入 Git。

修改后运行对应 focused tests，以及静态检查：

```bash
python -m pytest -q tests/test_regression_runner_shards.py
ruff check src tests tools
python -m compileall -q src tests tools
git diff --check
```

用改动实际覆盖的测试替换示例 focused test。运行 native fixture 前确认 Linux、C 编译器和所需内核功能可用；查看 skip、failure 和 error 的具体原因。

## 六个 current 分片

当前回归使用 `tools/run_tests.py`，分片索引为 **0、1、2、3、4、5**，统一 `--shard-count 6`。分片划分是确定的；六个分片必须使用同一个 Git 提交。`current` 不包含独立的 focused 和 history 角色，不能据此声称完整 CI 已通过。完整角色及 Python 版本以 [workflow](../.github/workflows/test.yml) 为准。

先在仓库根目录创建一轮全新的目录和六个独立 checkout。已有目录不要复用；结果和运行状态保留在 checkout 外。

```bash
revision="$(git rev-parse HEAD)"
run_parent="$(dirname "$PWD")/lunar-local-runs"
mkdir -p "$run_parent"
run_root="$(mktemp -d "$run_parent/$(date -u +%Y%m%dT%H%M%SZ)-${revision:0:12}-XXXXXX")"
printf '%s\n' "$revision" > "$run_root/revision.txt"
for shard_index in 0 1 2 3 4 5; do
  shard_root="$run_root/current-$shard_index"
  mkdir -p "$shard_root/tmp" "$shard_root/home" "$shard_root/results"
  git worktree add --detach "$shard_root/checkout" "$revision"
  uv venv --no-config --no-python-downloads --python python3.12 \
    "$shard_root/checkout/.venv"
  uv pip install --no-config \
    --python "$shard_root/checkout/.venv/bin/python" \
    -e "$shard_root/checkout[dev,lint]"
done
printf 'run_root=%s\n' "$run_root"
```

在六个 SSH 终端分别运行下面一段，将 `run_root` 设为上一步打印的绝对路径，将 `shard_index` 分别设为 0 到 5。每个分片独占 checkout、`.venv`、`TMPDIR`、Lunar home 和 results；不要让多个测试进程共享 SQLite/WAL 或同一临时目录。CPU 和内存资源由运行者按机器负载分配，先保守运行再增加并发。已有 `tmux` 时可在会话内运行测试，断线后重新 attach；不需要安装常驻服务。

```bash
run_root='/absolute/path/to/this-run'
shard_index=0
shard_root="$run_root/current-$shard_index"
cd "$shard_root/checkout"
export PATH="$PWD/.venv/bin:$PATH"
export PYTHONPATH="$PWD/src"
export TMPDIR="$shard_root/tmp"
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
python tools/run_tests.py --suite current \
  --shard-index "$shard_index" --shard-count 6 \
  --junit-dir "$shard_root/results" \
  2>&1 | tee "$shard_root/results/pytest.log"
pipeline_status=("${PIPESTATUS[@]}")
printf '%s\n' "${pipeline_status[0]}" > "$shard_root/results/exit-status.txt"
printf '%s\n' "${pipeline_status[1]}" > "$shard_root/results/log-exit-status.txt"
```

`exit-status.txt` 非零表示测试失败，`log-exit-status.txt` 非零表示日志写入失败；缺少这些文件表示进程可能尚未结束或被中断。保留 JUnit XML、runner 生成的 provenance、stdout/stderr 日志和退出码；不要只看终端最后一行。SSH 断线时先检查原进程和结果，不要直接在原目录重跑。

history 需要完整 Git 历史及 runner 中固定的 archive/frozen/product 提交。先检查 `git rev-parse --is-shallow-repository`；浅 clone 在联网时先执行 `git fetch --unshallow origin`，或按 `tools/run_tests.py` 的固定 commit 显式 fetch 所缺对象，并用 `git cat-file -e '<commit>^{commit}'` 确认。不要改写固定 commit 来绕过缺失历史。

history 会用 uv 离线建立历史环境，因此预先用同一个 uv cache 安装当前 package/build 依赖，并缓存当前环境使用的同版 pytest。仅通过 pip 装过依赖不保证 uv cache 已预热，缺少缓存时 offline 安装会失败。以下在已建立的独立 history checkout 和 `.venv` 内运行；测试前不切换 `UV_CACHE_DIR`，也不要清理该 cache：

```bash
pytest_version="$(python -c 'import importlib.metadata; print(importlib.metadata.version("pytest"))')"
uv pip install --no-config --reinstall-package pytest \
  --python .venv/bin/python -e '.[dev,lint]' "pytest==$pytest_version"
```

需要 history 时使用另一独立 checkout、环境和结果目录，运行 `python tools/run_tests.py --suite history --junit-dir /absolute/path/to/results`，同样捕获日志和退出码。focused 角色需要逐项执行 workflow 的约束；仅运行一个 focused test 不等于完成该角色。

## 结果边界与清理

六分片通过仅证明该提交在这台机器上的 current 测试结果。正式合入仍需核实精确 head/base、GitHub Actions 全部必需角色、原始 artifact 和 source/tree provenance。provider-free 成功不代表真实 solver、原生工具链或生产 admission 已验收；`production_admission=false` 保持原有边界。

结束前保留需要审查的日志和提交身份。只在确认没有运行中的测试、需要保留的修改或未归档产物后，才使用 `git worktree remove` 清理对应 checkout；日志位于外部 results，可独立保留。开发记录和后续验收条件见 [当前发布台账](current-release-backlog.md)。
