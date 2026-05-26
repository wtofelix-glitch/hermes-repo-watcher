# hermes-repo-watcher - notify.py
"""通知模块。

接收执行结果，打印格式化的微信友好报告到 stdout。
Hermes cronjob 会捕获 stdout 作为推送内容。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("repo-watcher.notify")


def _format_event_type(etype: str) -> str:
    """将事件类型转换为中文友好名称。

    Args:
        etype: 事件类型（pull_request / issues / push）。

    Returns:
        中文名称。
    """
    mapping = {
        "pull_request": "PR",
        "issues": "Issue",
        "push": "提交",
    }
    return mapping.get(etype, etype)


def _format_action(action: str) -> str:
    """格式化动作为中文。

    Args:
        action: 动作名。

    Returns:
        中文描述。
    """
    if action == "opened":
        return "🆕 新建"
    elif action == "synchronize":
        return "🔄 更新"
    elif action == "closed":
        return "🔒 关闭"
    else:
        return f"📌 {action}"


def _truncate(text: str, max_len: int = 40) -> str:
    """截断文本到指定长度。

    Args:
        text: 原始文本。
        max_len: 最大长度。

    Returns:
        截断后的文本。
    """
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _format_result(result: Dict[str, Any]) -> str:
    """格式化单个执行结果为一条微信友好的消息。

    每条消息约 25-45 字，emoji 开头。

    Args:
        result: 执行结果字典。

    Returns:
        格式化后的消息字符串。
    """
    repo = _truncate(result.get("event_repo", ""), 30)
    etype = _format_event_type(result.get("event_type", ""))
    action_display = _format_action(result.get("event_action", ""))
    title = _truncate(result.get("event_title", "无标题"), 30)
    handler = result.get("handler", "")
    summary = result.get("summary", "")

    if result.get("skipped"):
        return f"⏭ {repo} {etype}「{title}」已跳过（{handler}）"

    if result.get("notify_only"):
        return f"🔔 {repo} 新{etype}「{title}」需您查看 {result.get('event_url', '')}"

    success = result.get("success", False)
    duration = result.get("duration", 0)
    duration_str = f"{duration:.1f}s" if duration else ""

    if success:
        return f"✅ {repo} {action_display}{etype}「{title}」— {handler} 完成 {duration_str}"
    else:
        stderr = result.get("stderr", "")
        err_detail = _truncate(stderr, 20) if stderr else "执行异常"
        return f"❌ {repo} {action_display}{etype}「{title}」— {handler} 失败: {err_detail}"


def notify(result: Dict[str, Any]) -> str:
    """通知单个执行结果。

    打印格式化的微信友好报告到 stdout，并返回消息文本。

    Args:
        result: 执行结果字典。

    Returns:
        格式化的消息文本。
    """
    msg = _format_result(result)
    print(msg)
    logger.info("通知: %s", msg)
    return msg


def notify_batch(results: List[Dict[str, Any]]) -> str:
    """批量通知多个执行结果。

    将多个结果合并为一条报告，每个事件一行。

    Args:
        results: 执行结果列表。

    Returns:
        合并后的消息文本。
    """
    if not results:
        msg = "✅ 本轮检查完成，无新事件"
        print(msg)
        return msg

    lines: List[str] = []
    for r in results:
        lines.append(_format_result(r))

    msg = "\n".join(lines)
    print(msg)
    logger.info("批量通知 %d 条: %s", len(results), msg)
    return msg