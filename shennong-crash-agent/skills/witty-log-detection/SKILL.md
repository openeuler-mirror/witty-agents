---
name: witty-log-detection
description: |
  用于对日志文件进行异常检测。支持关键词匹配、聚类离群点检测、LLM 智能检测和基于 embedding
  的检测。适用于 vmcore-dmesg、syslog、业务日志等文本日志。
tools: [Bash, Read]
mcp:
  witty-log-detection:
    type: sse
    url: http://localhost:12144/sse
allowed-tools: Bash(python3:*) Bash(pip:*) Bash(curl:*) Bash(cat:*) Bash(ls:*) Bash(rg:*)
---

# witty-log-detection

Use this skill when the user asks to analyze a log file for anomalies, errors, or suspicious patterns. It is especially useful for `vmcore-dmesg.txt`, system logs, and application logs.

## Agent Contract

1. Accept one or more log file paths from the user.
2. Choose the appropriate detection method based on the question:
   - `log_detection_base_on_keywords`: known error keywords or user-provided anomaly keywords.
   - `log_detection_base_on_clustering`: discover unknown anomaly patterns.
   - `log_detection_base_on_llm`: complex semantic anomaly detection (requires LLM config).
   - `log_detection_base_on_embedding`: embedding + keyword hybrid.
3. Create a task with `create_log_parse_task`.
4. Poll `get_task_message` until status is `SUCCESSFUL` or `FAILED`.
5. Fetch results with `get_task_result`.
6. Summarize anomalies: file path, anomaly reason, anomaly score, and content snippet.

## Tool Calls

### Create a keyword-based log detection task

```json
{
  "tool": "witty-log-detection:create_log_parse_task",
  "arguments": {
    "task_type": "log_detection_base_on_keywords",
    "query": "general protection fault mlx5_core",
    "file_path_list": ["/var/crash/127.0.0.1-2026-06-30-23:12:05/vmcore-dmesg.txt"],
    "anomaly_keywords": ["general protection fault", "BUG:", "RIP:", "Call Trace"],
    "max_anomaly_log_count": 64
  }
}
```

### Poll task status

```json
{
  "tool": "witty-log-detection:get_task_message",
  "arguments": {
    "task_id": "<task_id>"
  }
}
```

### Fetch results

```json
{
  "tool": "witty-log-detection:get_task_result",
  "arguments": {
    "task_id": "<task_id>",
    "is_anomalous": true,
    "limit": 20
  }
}
```

## Output Format

Return a concise summary with the following fields:

```text
method: log_detection_base_on_keywords | log_detection_base_on_clustering | log_detection_base_on_llm | log_detection_base_on_embedding
total_logs: <number>
anomalous_logs: <number>
top_anomalies:
  1. score=<score> file=<path> reason=<reason>
  ...
notes: <any errors or service unavailability>
```

## Execution Rules

- Do not fabricate task IDs, scores, or result counts. Only report what `get_task_result` returns.
- If the service is not running, output the command to start it:
  `cd skills/witty-log-detection/src && python3 server.py`
- If the result is empty, say so explicitly rather than implying anomalies were found.
- Keep query text concise (4-8 tokens); prefer English technical terms for better retrieval accuracy.
