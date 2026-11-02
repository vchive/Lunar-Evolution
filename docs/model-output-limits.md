# 模型输出上限

模型 profile 可以同时设置单次生成上限与累计观测预算。两者用途不同：

| 配置 | 作用 |
| --- | --- |
| `max_completion_tokens` | 可选；把每次 completion 的生成上限发送给支持该字段的 OpenAI-compatible 网关，包含可见输出和 reasoning tokens。 |
| `max_total_tokens` | 累计输入加输出的观测预算；响应返回并报告 usage 后检查，超额响应不被接纳。 |

例如，将以下内容保存为 `model-profile.json`，将 `model` 改为已配置的模型名：

```json
{
  "name": "bounded-local",
  "model": "your-model-name",
  "max_steps": 40,
  "timeout_seconds": 900,
  "max_total_tokens": 160000,
  "max_completion_tokens": 8192
}
```

在已有模型环境变量配置下使用：

```bash
lunar-evolution solve '读取工作区输入并生成可验证的结果' \
  --runtime openai-compatible --agent-loop \
  --model-profile model-profile.json --json
```

`max_completion_tokens` 必须是 1 到 1,000,000 的整数；实际可用范围取决于
模型和网关。省略或设为 `null` 时不发送该参数，旧 profile 身份保持不变。
显式配置会改变 profile 指纹，恢复或验收时必须使用匹配的 profile。
不要用新配置重开旧 attempt。

如果网关返回 `finish_reason: "length"`，本次显式限额调用失败；截断文本
不会被当作最终答案，截断工具调用也不会执行。错误使用既有
`invalid_response_shape` 分类，不自动续写或重试，不自动改发 `max_tokens`。
失败前已接纳的用量仍保留；失败请求不提供完整用量或计费保证。

旧网关可能拒绝或忽略该参数，兼容性需要独立确认。没有该结束字段的兼容响应
沿用现有解析行为，因此参数接线不能证明服务端确实执行上限。累计预算仍保留，
也不能事先精确限制 prompt tokens 或形成硬计费上限。真实任务还需有有效产物、
完成回执及独立评分才能算验收通过。

本功能的[规格与验证记录](../specs/061-subject-failure-diagnostics/completion-token-limit.md)
保留默认兼容边界；字段含义参考[官方 Chat Completions 文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。
