# hermes-repo-watcher - monitor.py
"""GitHub API 轮询模块。

通过 gh CLI 调用 GitHub REST API 获取仓库事件（PR、Issue、Push）。
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict, List

logger = logging.getLogger("repo-watcher.monitor")


def _run_gh_api(endpoint: str, timeout: int = 30) -> List[Dict[str, Any]]:
    """执行 gh api 命令并返回解析后的 JSON 列表。

    Args:
        endpoint: GitHub API 端点路径（不含 base URL），如 'repos/owner/repo/pulls'。
        timeout: 请求超时秒数。

    Returns:
        解析后的 JSON 列表，失败时返回空列表。
    """
    cmd = ["gh", "api", "--paginate", endpoint]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning("gh API 调用失败: %s, stderr: %s", endpoint, result.stderr.strip())
            return []
        if not result.stdout.strip():
            return []
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("gh API 请求超时: %s", endpoint)
        return []
    except json.JSONDecodeError as e:
        logger.warning("gh API 返回非 JSON 数据: %s, error: %s", endpoint, e)
        return []
    except FileNotFoundError:
        logger.error("未找到 gh CLI，请安装 GitHub CLI: https://cli.github.com/")
        return []
    except Exception as e:
        logger.warning("gh API 请求异常: %s, error: %s", endpoint, e)
        return []


def _fetch_pull_requests(owner: str, repo: str) -> List[Dict[str, Any]]:
    """获取仓库的 Pull Request 事件。

    检测 opened 和 synchronize 状态的 PR。

    Args:
        owner: 仓库所有者。
        repo: 仓库名称。

    Returns:
        结构化事件列表。
    """
    events: List[Dict[str, Any]] = []
    pulls = _run_gh_api(f"repos/{owner}/{repo}/pulls?state=open&sort=updated&direction=desc&per_page=10")

    for pr in pulls:
        pr_number = pr.get("number", 0)
        pr_title = pr.get("title", "")
        pr_html_url = pr.get("html_url", "")
        pr_state = pr.get("state", "")
        merged = pr.get("merged", False)
        draft = pr.get("draft", False)

        # 检查 PR 的 events/timeline 来判断动作
        action = "opened"
        # 尝试从 PR 对象的 created_at/updated_at 判断
        # 如果是新创建的 PR (created_at close to now)，标记为 opened
        # 如果是更新的，标记为 synchronize
        # 简化处理：用 labels/timeline 判断

        timeline = _run_gh_api(
            f"repos/{owner}/{repo}/issues/{pr_number}/timeline?per_page=5"
        )
        for item in timeline:
            event_type = item.get("event", "")
            if event_type == "review_requested":
                continue
            if event_type in ("committed",):
                action = "synchronize"
                break

        # 如果 timeline 查询失败，默认 opened
        events.append({
            "repo": f"{owner}/{repo}",
            "type": "pull_request",
            "event_id": str(pr_number),
            "action": action,
            "title": pr_title,
            "url": pr_html_url,
            "detail": {
                "pr_number": pr_number,
                "state": pr_state,
                "merged": merged,
                "draft": draft,
                "head": pr.get("head", {}).get("ref", ""),
                "base": pr.get("base", {}).get("ref", ""),
                "body": pr.get("body", "") or "",
                "created_at": pr.get("created_at", ""),
                "updated_at": pr.get("updated_at", ""),
                "user": pr.get("user", {}).get("login", ""),
            },
        })

    return events


def _fetch_issues(owner: str, repo: str) -> List[Dict[str, Any]]:
    """获取仓库的 Issue 事件。

    检测 newly opened issues（通过 created_at 判断）。

    Args:
        owner: 仓库所有者。
        repo: 仓库名称。

    Returns:
        结构化事件列表。
    """
    events: List[Dict[str, Any]] = []
    issues = _run_gh_api(
        f"repos/{owner}/{repo}/issues?state=open&sort=created&direction=desc&per_page=10&filter=all"
    )

    for issue in issues:
        # 排除 Pull Request（GitHub API 中 PR 也是 issue）
        if issue.get("pull_request"):
            continue

        issue_number = issue.get("number", 0)
        events.append({
            "repo": f"{owner}/{repo}",
            "type": "issues",
            "event_id": str(issue_number),
            "action": "opened",
            "title": issue.get("title", ""),
            "url": issue.get("html_url", ""),
            "detail": {
                "issue_number": issue_number,
                "state": issue.get("state", ""),
                "body": issue.get("body", "") or "",
                "labels": [l.get("name", "") for l in issue.get("labels", [])],
                "created_at": issue.get("created_at", ""),
                "user": issue.get("user", {}).get("login", ""),
            },
        })

    return events


def _fetch_commits(owner: str, repo: str, branch: str = "main") -> List[Dict[str, Any]]:
    """获取仓库指定分支的最近提交事件。

    Args:
        owner: 仓库所有者。
        repo: 仓库名称。
        branch: 分支名称，默认 main。

    Returns:
        结构化事件列表。
    """
    events: List[Dict[str, Any]] = []
    commits = _run_gh_api(
        f"repos/{owner}/{repo}/commits?sha={branch}&per_page=5"
    )

    for commit in commits:
        sha = commit.get("sha", "")
        commit_info = commit.get("commit", {})
        events.append({
            "repo": f"{owner}/{repo}",
            "type": "push",
            "event_id": sha,
            "action": branch,
            "title": commit_info.get("message", "").split("\n")[0],
            "url": commit.get("html_url", ""),
            "detail": {
                "sha": sha,
                "branch": branch,
                "message": commit_info.get("message", ""),
                "author": commit_info.get("author", {}).get("name", ""),
                "committer": commit_info.get("committer", {}).get("name", ""),
                "date": commit_info.get("committer", {}).get("date", ""),
            },
        })

    return events


def fetch_events(config) -> List[Dict[str, Any]]:
    """从所有配置的仓库中获取 GitHub 事件。

    对每个仓库获取 PR、Issue 和最近提交，静默跳过 API 调用失败的仓库。

    Args:
        config: Config 对象，包含 repos 列表。

    Returns:
        结构化事件列表，每个事件是一个字典，包含:
            - repo: 仓库全名 (owner/repo)
            - type: 事件类型 (pull_request / issues / push)
            - event_id: 事件 ID（PR/Issue 编号或 commit SHA）
            - action: 动作 (opened / synchronize / 分支名)
            - title: 事件标题
            - url: 事件 URL
            - detail: 详细信息的字典
    """
    all_events: List[Dict[str, Any]] = []

    for repo_full in config.repos:
        if "/" not in repo_full:
            logger.warning("跳过无效仓库格式（需要 owner/repo）: %s", repo_full)
            continue

        owner, repo = repo_full.split("/", 1)
        logger.info("正在轮询仓库: %s", repo_full)

        try:
            all_events.extend(_fetch_pull_requests(owner, repo))
        except Exception as e:
            logger.warning("获取 %s 的 PR 事件失败: %s", repo_full, e)

        try:
            all_events.extend(_fetch_issues(owner, repo))
        except Exception as e:
            logger.warning("获取 %s 的 Issue 事件失败: %s", repo_full, e)

        try:
            all_events.extend(_fetch_commits(owner, repo))
        except Exception as e:
            logger.warning("获取 %s 的提交事件失败: %s", repo_full, e)

    logger.info("本轮共获取 %d 个事件", len(all_events))
    return all_events