# hermes-repo-watcher — 技术规格

## 定位

通用 GitHub 仓库监控 + AI 自动处理 CLI 工具。检测仓库变化（PR/Issue/push），智能派活给 Claude Code / Codex CLI 处理。

## 技术栈

- Python 3.12+ (无框架，stdlib + requests)
- GitHub REST API (gh CLI 封装的 token)
- SQLite (事件去重 + 状态跟踪)
- YAML (配置格式, pyyaml)
- 执行层: subprocess 调用 claude / codex CLI

## 目录结构

```
~/.hermes/repo-watcher/
├── watcher.yaml          # 用户配置
├── db/
│   └── state.db          # SQLite 事件跟踪
└── logs/
    └── events.log        # 执行日志

~/workspace/hermes-repo-watcher/
├── src/
│   ├── __init__.py
│   ├── __main__.py       # CLI 入口: python -m src
│   ├── config.py         # YAML 配置加载 + 校验
│   ├── monitor.py        # GitHub API 轮询 + 事件检测
│   ├── tracker.py        # SQLite 去重 + 状态跟踪
│   ├── router.py         # 事件类型 + handler 路由
│   ├── executor.py       # 派活给 Claude Code / Codex CLI
│   └── notify.py         # 微信推送（Hermes notify hook）
├── templates/
│   ├── pr-review.md      # PR 审查 prompt 模板
│   ├── pr-feature.md     # 新功能 PR prompt 模板
│   ├── issue-triage.md   # Issue 分类 prompt 模板
│   └── commit-check.md   # Commit 检查 prompt 模板
├── watcher.yaml.example  # 配置示例
├── README.md
└── SPEC.md               # 本文件
```

## 配置格式

```yaml
# watcher.yaml
repos:
  - owner/repo-name       # 监控的 GitHub 仓库
  - owner/repo2

interval: 30              # 轮询间隔（分钟）

handlers:
  pull_request:
    - name: review-code
      on: [opened, synchronize]
      action: claude-code
      template: pr-review
      auto_confirm: false  # 需用户确认后再执行

  issues:
    - name: triage
      on: [opened]
      action: notify       # 只推微信通知
      template: issue-triage

  push:
    - name: quick-check
      on: [default-branch]
      action: codex        # 小检查用 Codex
      template: commit-check
```

## 核心数据流

1. monitor.py 轮询 GitHub API → 获取 events
2. tracker.py SQLite 去重 → 只返回未处理事件
3. router.py 匹配 handler → 决定执行策略
4. executor.py 写 prompt → subprocess 派活
5. notify.py 结果 → 推送微信

## 执行策略

| action | 执行者 | prompt 模板 | 适用场景 |
|--------|--------|-------------|----------|
| claude-code | `claude -p "..."` | pr-review.md | 复杂 PR 审查、重构 |
| codex | `codex "..."` | commit-check.md | 小修改、typo、测试 |
| notify | 只通知不等 | — | 需用户决策的事件 |
| skip | 忽略 | — | 不需要处理的 |

## 状态跟踪 (SQLite schema)

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    repo TEXT NOT NULL,
    event_type TEXT NOT NULL,     -- pull_request / issues / push
    event_id TEXT NOT NULL,       -- GitHub 事件 ID
    action TEXT NOT NULL,         -- opened / synchronize / closed
    state TEXT NOT NULL DEFAULT 'pending',  -- pending / running / done / failed / skipped
    handler TEXT,                 -- 执行的 handler 名称
    result TEXT,                  -- 执行结果摘要
    created_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT,
    UNIQUE(repo, event_id, action)
);
```
