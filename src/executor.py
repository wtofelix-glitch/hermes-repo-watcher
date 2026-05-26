# hermes-repo-watcher - executor.py
"""事件执行模块。

根据路由结果执行 handler 配置的操作：
- claude-code: 渲染 prompt 模板 → 调 claude CLI
- codex: 渲染 prompt 模板 → 调 codex CLI
- notify: 只返回结果供 notify 模块输出
- skip: 直接跳过
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional

from .router import RouteResult

logger = logging.getLogger("repo-watcher.executor")

# 执行超时（秒）
EXEC_TIMEOUT = 180

# 模板目录
_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"
)


def _load_template(template_name: str) -> Optional[str]:
    """加载 prompt 模板文件。

    Args:
        template_name: 模板名（如 "pr-review"），会自动补全 .md 扩展名。

    Returns:
        模板内容字符串，加载失败返回 None。
    """
    # 尝试有无 .md 后缀
    candidates = [
        os.path.join(_TEMPLATES_DIR, template_name),
        os.path.join(_TEMPLATES_DIR, template_name + ".md"),
    ]

    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.error("读取模板文件失败 %s: %s", path, e)
                return None

    logger.warning("未找到模板文件: %s（路径: %s）", template_name, _TEMPLATES_DIR)
    return None


def _render_template(template: str, event: Dict[str, Any]) -> str:
    """渲染 prompt 模板，替换 {{VARIABLE}} 占位符。

    从事件的 detail 字段提取变量值。

    Args:
        template: 模板字符串。
        event: 事件字典。

    Returns:
        渲染后的字符串。
    """
    detail = event.get("detail", {})
    variables = {
        "REPO_NAME": event.get("repo", ""),
        "EVENT_TYPE": event.get("type", ""),
        "EVENT_TITLE": event.get("title", ""),
        "EVENT_URL": event.get("url", ""),
        "ACTION": event.get("action", ""),
        "PR_NUMBER": str(detail.get("pr_number", "")),
        "PR_TITLE": event.get("title", ""),
        "PR_HEAD": detail.get("head", ""),
        "PR_BASE": detail.get("base", ""),
        "ISSUE_NUMBER": str(detail.get("issue_number", "")),
        "ISSUE_TITLE": event.get("title", ""),
        "ISSUE_AUTHOR": detail.get("user", ""),
        "ISSUE_LABELS": ", ".join(detail.get("labels", [])),
        "ISSUE_BODY": detail.get("body", "")[:2000],
        "BRANCH": detail.get("branch", "main"),
        "COMMIT_SHA": detail.get("sha", ""),
        "COMMIT_AUTHOR": detail.get("author", ""),
    }

    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", str(value))

    return result


def _run_subprocess(cmd: str, prompt_content: str, timeout: int = EXEC_TIMEOUT) -> Dict[str, Any]:
    """执行子进程命令，传入 prompt 内容。

    Args:
        cmd: 命令模板（如 "claude -p"），实际 prompt 通过临时文件传入。
        prompt_content: 渲染后的 prompt 内容。

    Returns:
        执行结果字典，包含 stdout、exit_code、duration 等。
    """
    start_time = time.time()

    # 写 prompt 到临时文件
    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(prompt_content)
            tmp_file = f.name

        # 构造完整命令
        full_cmd = f'{cmd} "$(cat {tmp_file})"'

        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        duration = round(time.time() - start_time, 2)
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if result.returncode != 0:
            logger.warning("子进程执行失败 (exit=%d): %s", result.returncode, stderr[:200])

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
            "duration": duration,
            "success": result.returncode == 0,
        }

    except subprocess.TimeoutExpired:
        duration = round(time.time() - start_time, 2)
        logger.error("子进程执行超时（%d秒）", timeout)
        return {
            "stdout": "",
            "stderr": f"执行超时（{timeout}秒）",
            "exit_code": -1,
            "duration": duration,
            "success": False,
        }
    except FileNotFoundError as e:
        logger.error("未找到可执行命令: %s", e)
        return {
            "stdout": "",
            "stderr": f"未找到命令: {e}",
            "exit_code": -1,
            "duration": round(time.time() - start_time, 2),
            "success": False,
        }
    except Exception as e:
        logger.error("子进程执行异常: %s", e)
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "duration": round(time.time() - start_time, 2),
            "success": False,
        }
    finally:
        # 清理临时文件
        if tmp_file and os.path.isfile(tmp_file):
            try:
                os.unlink(tmp_file)
            except Exception:
                pass


def execute(route_result: RouteResult) -> Dict[str, Any]:
    """执行路由结果。

    根据 handler.action 决定执行方式：
    - claude-code: 渲染模板 → 调 claude CLI
    - codex: 渲染模板 → 调 codex CLI
    - notify: 只返回结果（不执行命令）
    - skip: 直接跳过

    Args:
        route_result: 路由结果，包含 handler 配置和事件。

    Returns:
        执行结果字典，包含:
            - action: 执行的动作类型
            - handler: handler 名称
            - event_repo: 仓库名
            - event_type: 事件类型
            - event_id: 事件 ID
            - event_title: 事件标题
            - stdout: 标准输出
            - stderr: 标准错误
            - exit_code: 退出码
            - duration: 执行耗时（秒）
            - success: 是否成功
            - summary: 简要摘要
            - skipped: 是否被跳过
            - notify_only: 是否仅通知
    """
    handler = route_result.handler
    event = route_result.event

    logger.info(
        "执行 handler: %s (action=%s) 处理事件 %s/%s",
        handler.name,
        handler.action,
        event.get("repo", ""),
        event.get("event_id", ""),
    )

    base_result = {
        "action": handler.action,
        "handler": handler.name,
        "event_repo": event.get("repo", ""),
        "event_type": event.get("type", ""),
        "event_id": event.get("event_id", ""),
        "event_title": event.get("title", ""),
        "event_url": event.get("url", ""),
        "event_action": event.get("action", ""),
    }

    # skip: 直接跳过
    if handler.action == "skip":
        logger.info("handler %s 配置为 skip，跳过执行", handler.name)
        return {
            **base_result,
            "stdout": "",
            "stderr": "已跳过",
            "exit_code": 0,
            "duration": 0.0,
            "success": True,
            "summary": "⏭ 已跳过（配置为 skip）",
            "skipped": True,
            "notify_only": False,
        }

    # notify: 仅返回结果
    if handler.action == "notify":
        logger.info("handler %s 配置为 notify，仅返回通知", handler.name)
        return {
            **base_result,
            "stdout": "",
            "stderr": "仅通知",
            "exit_code": 0,
            "duration": 0.0,
            "success": True,
            "summary": f"🔔 新 {event.get('type', '事件')}: {event.get('title', '')}",
            "skipped": False,
            "notify_only": True,
        }

    # claude-code / codex: 渲染模板并执行
    if handler.action in ("claude-code", "claude", "codex"):
        template_name = handler.template or handler.name
        template_content = _load_template(template_name)

        if not template_content:
            logger.warning("handler %s 未找到模板 %s，跳过执行", handler.name, template_name)
            return {
                **base_result,
                "stdout": "",
                "stderr": f"未找到模板: {template_name}",
                "exit_code": -1,
                "duration": 0.0,
                "success": False,
                "summary": f"❌ 未找到模板 {template_name}",
                "skipped": True,
                "notify_only": False,
            }

        prompt = _render_template(template_content, event)

        # 确定命令
        if handler.action in ("claude-code", "claude"):
            cmd = "claude -p"
        else:
            cmd = "codex"

        logger.info("执行 %s 处理事件 %s/%s", cmd, event.get("repo", ""), event.get("event_id", ""))
        exec_result = _run_subprocess(cmd, prompt)

        summary = f"✅ {handler.name}: OK" if exec_result["success"] else f"❌ {handler.name}: 失败"
        return {
            **base_result,
            **exec_result,
            "summary": summary,
            "skipped": False,
            "notify_only": False,
        }

    # 未知 action
    logger.warning("未知 handler action: %s", handler.action)
    return {
        **base_result,
        "stdout": "",
        "stderr": f"未知 action: {handler.action}",
        "exit_code": -1,
        "duration": 0.0,
        "success": False,
        "summary": f"❌ 未知操作: {handler.action}",
        "skipped": True,
        "notify_only": False,
    }