# hermes-repo-watcher - config.py
"""YAML 配置加载与校验模块。

从 watcher.yaml 加载配置，校验必填字段，返回结构化 Config 对象。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class HandlerConfig:
    """单个事件处理器的配置。"""

    name: str
    on: List[str] = field(default_factory=lambda: ["opened"])
    action: str = "notify"
    template: Optional[str] = None
    auto_confirm: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HandlerConfig":
        """从字典构建 HandlerConfig，填充默认值。"""
        return cls(
            name=d.get("name", "unnamed"),
            on=d.get("on", ["opened"]),
            action=d.get("action", "notify"),
            template=d.get("template"),
            auto_confirm=d.get("auto_confirm", False),
        )


@dataclass
class NotifyConfig:
    """通知配置。"""

    channel: str = "stdout"
    on: List[str] = field(default_factory=lambda: ["handler:done", "error"])

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "NotifyConfig":
        if not d:
            return cls()
        return cls(
            channel=d.get("channel", "stdout"),
            on=d.get("on", ["handler:done", "error"]),
        )


@dataclass
class Config:
    """完整的仓库监控配置。"""

    repos: List[str]
    interval: int
    handlers: Dict[str, List[HandlerConfig]]
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Config":
        """从字典构建 Config，校验必填字段。"""
        repos = d.get("repos")
        interval = d.get("interval")
        raw_handlers = d.get("handlers")

        errors: List[str] = []
        if not repos:
            errors.append("缺少必填字段 'repos'（仓库列表）")
        if interval is None:
            errors.append("缺少必填字段 'interval'（轮询间隔，分钟）")
        if not raw_handlers:
            errors.append("缺少必填字段 'handlers'（事件处理器配置）")

        if errors:
            raise ValueError(
                "配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        handlers: Dict[str, List[HandlerConfig]] = {}
        for event_type, handler_list in raw_handlers.items():
            handlers[event_type] = [
                HandlerConfig.from_dict(h) for h in handler_list
            ]

        return cls(
            repos=repos,
            interval=int(interval),
            handlers=handlers,
            notify=NotifyConfig.from_dict(d.get("notify")),
        )


def find_config_path(custom_path: Optional[str] = None) -> str:
    """查找配置文件路径。

    优先级:
    1. 传入的自定义路径
    2. ~/.hermes/repo-watcher/watcher.yaml
    3. 当前目录下的 watcher.yaml
    """
    if custom_path:
        return custom_path

    home_cfg = os.path.expanduser("~/.hermes/repo-watcher/watcher.yaml")
    if os.path.isfile(home_cfg):
        return home_cfg

    local_cfg = os.path.join(os.getcwd(), "watcher.yaml")
    if os.path.isfile(local_cfg):
        return local_cfg

    # 默认返回 home 路径，即使不存在，让 load_config 报错
    return home_cfg


def load_config(config_path: Optional[str] = None) -> Config:
    """加载并校验 YAML 配置文件。

    Args:
        config_path: 配置文件的路径，为 None 时自动查找。

    Returns:
        校验通过的 Config 对象。

    Raises:
        FileNotFoundError: 配置文件不存在。
        ValueError: 配置内容校验失败。
        yaml.YAMLError: YAML 语法错误。
    """
    path = find_config_path(config_path)

    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"配置文件不存在: {path}\n"
            f"请参考 watcher.yaml.example 创建配置文件。"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        raise ValueError("配置文件为空或格式不正确")

    return Config.from_dict(data)