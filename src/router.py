# hermes-repo-watcher - router.py
"""事件路由模块。

将事件与配置中的 handler 进行匹配，决定由哪个 handler 处理。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .config import Config, HandlerConfig

logger = logging.getLogger("repo-watcher.router")


@dataclass
class RouteResult:
    """路由匹配结果，包含匹配的 handler 和对应事件。"""

    handler: HandlerConfig
    event: Dict[str, Any]
    event_type: str = ""


def _match_action(handler_actions: List[str], event_action: str, event_type: str) -> bool:
    """检查 handler 的 on 配置是否匹配事件的动作。

    Args:
        handler_actions: handler 配置的 on 列表（如 ["opened", "synchronize"]）。
        event_action: 事件的 action（如 "opened", "main", "synchronize"）。
        event_type: 事件类型（用于 push 类型特殊处理）。

    Returns:
        匹配返回 True，否则 False。
    """
    for ha in handler_actions:
        # 精确匹配
        if ha == event_action:
            return True
        # push 事件的 action 是分支名，匹配任意分支名
        if event_type == "push" and ha == event_action:
            return True
    return False


def route_events(
    events: List[Dict[str, Any]], config: Config
) -> List[RouteResult]:
    """将事件列表路由到匹配的 handler。

    根据事件类型（pull_request / issues / push）和动作（opened / synchronize / 分支名）
    在配置的 handlers 中查找匹配的处理器。

    Args:
        events: 事件列表，每个事件包含 type、action 等字段。
        config: Config 对象，包含 handlers 配置。

    Returns:
        路由结果列表，每个结果包含匹配的 handler 和对应事件。
        没有匹配 handler 的事件会被跳过。
    """
    results: List[RouteResult] = []

    for event in events:
        event_type = event.get("type", "")
        event_action = event.get("action", "")

        # 查找匹配事件类型的 handler 组
        handlers_for_type = config.handlers.get(event_type, [])
        if not handlers_for_type:
            logger.debug(
                "事件 %s/%s 无匹配 handler 类型（%s），跳过",
                event.get("repo", ""),
                event.get("event_id", ""),
                event_type,
            )
            continue

        # 在每个 handler 中匹配动作
        matched = False
        for handler in handlers_for_type:
            if _match_action(handler.on, event_action, event_type):
                results.append(
                    RouteResult(handler=handler, event=event, event_type=event_type)
                )
                matched = True
                logger.info(
                    "事件 %s/%s (%s) 匹配 handler: %s",
                    event.get("repo", ""),
                    event.get("event_id", ""),
                    event_action,
                    handler.name,
                )
                break  # 每个事件只匹配第一个 handler

        if not matched:
            logger.debug(
                "事件 %s/%s (%s/%s) 无匹配 handler 动作，跳过",
                event.get("repo", ""),
                event.get("event_id", ""),
                event_type,
                event_action,
            )

    logger.info("路由完成: %d 个事件中 %d 个匹配到 handler", len(events), len(results))
    return results