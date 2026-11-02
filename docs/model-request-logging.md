# 模型请求进度日志

普通模型长跑曾停在等待响应头，原终态诊断只能在请求结束后查看。现在可以为
`effect-subject` 显式开启脱敏 JSON 日志：

```bash
lunar-evolution effect-subject /absolute/path/request.json \
  --model-profile /absolute/path/profile.json \
  --model-request-log --json \
  > subject-result.json 2> model-requests.jsonl
```

其余模型配置仍使用既有环境变量。默认不开日志；`--json` 的 stdout 协议保持原样，
日志单独写 stderr。日志文件由调用方保留和轮转，命令不会自动创建额外日志目录。

每次请求有本地关联 ID 和 UTC 时间，记录开始、每 30 秒的等待观察及已知终态。
字段包括本地耗时、原 timeout、传输阶段和最后可验证里程碑；失败时复用现有
请求体字节数/SHA256。成功请求不增加指纹计算。文件不记录 endpoint、密钥、模型名、
提示词、工具参数、请求或响应正文、任意异常文字。ID 仅供本地对照，不发送给网关。

`wait_response_headers` 表示本地写入已返回、仍未收到响应头，不能据此判断服务端
正在排队还是推理。等待日志不会延长原 deadline，不会重试或增加 HTTP 请求，
也不能证明客户端断开后服务端已取消或停止计费。没有 timeout 的直接调用只记录
开始和终态，没有周期性的传输里程碑。

Python 调用方也可为 `lunar_evolution.model_requests` logger 配置 INFO handler；
CLI 的开关只在当前 subject 调用内使用专用 stderr handler，结束后恢复原配置，
不修改 root logger。日志属于诊断信息，不替代原 receipt、usage ledger 或评分。
历史失败不会回填这些字段。

传输失败可附带固定的 `transport_error_category`：`peer_closed`、
`connection_reset`、`connection_refused`、`connection_aborted`、`broken_pipe`、
`dns_error`、`tls_error`、`timeout` 或 `os_error`。它来自本地捕获的异常类型，
不包含异常文字。未识别或不可信的分类省略；HTTP 错误及父进程 deadline 不推测
分类。字段不改变原 `reason`，也不进入 receipt。`peer_closed` 只表示未收到
响应头便观察到连接关闭，不能据此确定是网关、上游还是网络设备关闭了连接。
具体兼容边界见[分类规格](../specs/061-subject-failure-diagnostics/transport-error-category.md)。

验证和实现边界见[规格](../specs/061-subject-failure-diagnostics/live-request-progress.md)。
