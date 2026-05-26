# hermes-repo-watcher - __main__.py
"""CLI 入口模块。

支持三种运行模式:
- python -m src          → 执行一次完整轮询
- python -m src --once   → 同上（单次运行模式）
- python -m src --watch  → 持续轮询模式
- python -m src --help   → 显示帮助
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import NoReturn

from .config import load_config
from .monitor import fetch_events
from .tracker import get_tracker, get_stats
from .router import route_events
from .executor import execute
from .notify import notify_batch


def setup_logging(verbose: bool = False) -> None:
    """配置日志。

    Args:
        verbose: 是否输出调试日志。
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run_once(config_path: str | None = None, verbose: bool = False) -> int:
    """执行一次完整的轮询流程。

    流程: monitor → tracker → router → executor → notify

    Args:
        config_path: 配置文件路径，None 则自动查找。
        verbose: 是否输出调试日志。

    Returns:
        0 表示成功，1 表示失败。
    """
    # 1. 加载配置
    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ 配置加载失败: {e}", file=sys.stderr)
        return 1

    total_repos = len(config.repos)
    print(f"📡 仓库监控 v0.1 — 监控 {total_repos} 个仓库，轮询间隔 {config.interval} 分钟")

    # 2. 获取事件
    events = fetch_events(config)
    if not events:
        print("📭 未发现新事件")
        return 0

    # 3. 去重检查
    tracker = get_tracker()
    new_events = [e for e in events if tracker.is_new(e)]
    print(f"📊 共 {len(events)} 个事件，{len(new_events)} 个未处理")

    if not new_events:
        print("✅ 所有事件均已处理")
        return 0

    # 4. 路由匹配
    route_results = route_events(new_events, config)
    if not route_results:
        print("📭 无匹配的 handler 配置")
        return 0

    print(f"🔀 {len(route_results)} 个事件匹配到 handler")

    # 5. 执行
    exec_results = []
    for rr in route_results:
        event = rr.event
        # 标记为 running
        tracker.mark(event, "running", handler=rr.handler.name)
        print(f"⚡ 执行 {rr.handler.name} → {event.get('repo', '')}/{event.get('event_id', '')}")

        result = execute(rr)
        exec_results.append(result)

        # 更新状态
        if result.get("success"):
            tracker.mark(event, "done", result=result.get("summary"), handler=rr.handler.name)
        else:
            tracker.mark(event, "failed", result=result.get("summary"), handler=rr.handler.name)

    # 6. 通知
    notify_batch(exec_results)

    # 7. 打印统计
    stats = get_stats()
    print(f"\n📊 统计: 总事件 {stats['total']} 个")
    for state, count in stats.get("states", {}).items():
        print(f"   {state}: {count}")

    return 0


def run_watch(config_path: str | None = None, verbose: bool = False) -> NoReturn:
    """持续轮询模式。

    按配置的 interval 间隔循环执行轮询。

    Args:
        config_path: 配置文件路径。
        verbose: 是否输出调试日志。
    """
    config = load_config(config_path)
    interval_seconds = config.interval * 60

    print(f"👀 持续监控模式已启动，每 {config.interval} 分钟轮询一次")
    print("按 Ctrl+C 停止\n")

    while True:
        try:
            run_once(config_path, verbose)
        except KeyboardInterrupt:
            print("\n👋 监控已停止")
            sys.exit(0)
        except Exception as e:
            print(f"⚠️ 轮询异常: {e}", file=sys.stderr)
            logger = logging.getLogger("repo-watcher")
            logger.exception("轮询异常")

        print(f"\n💤 等待 {config.interval} 分钟...\n")
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\n👋 监控已停止")
            sys.exit(0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表，默认使用 sys.argv。

    Returns:
        解析后的参数命名空间。
    """
    parser = argparse.ArgumentParser(
        prog="hermes-repo-watcher",
        description="GitHub 仓库监控 + AI 自动处理工具",
        epilog="示例: python -m src --once  |  python -m src --watch  |  python -m src --config /path/to/watcher.yaml",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="执行一次完整轮询（默认）",
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="持续轮询模式（循环执行）",
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="配置文件路径（默认: ~/.hermes/repo-watcher/watcher.yaml）",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出调试日志",
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="查看事件处理统计",
    )

    return parser.parse_args(argv)


def main() -> int:
    """主函数。

    Returns:
        退出码。
    """
    args = parse_args()
    setup_logging(args.verbose)

    # 查看统计
    if args.stats:
        from .tracker import get_stats
        stats = get_stats()
        print(f"📊 事件处理统计:")
        print(f"   数据库: {stats.get('db_path', 'N/A')}")
        print(f"   总事件: {stats['total']}")
        for state, count in stats.get("states", {}).items():
            print(f"   {state}: {count}")
        return 0

    try:
        if args.watch:
            run_watch(args.config, args.verbose)
            return 0  # 不会执行到这里
        else:
            # --once 或不指定参数都执行单次
            return run_once(args.config, args.verbose)
    except KeyboardInterrupt:
        print("\n👋 已取消")
        return 0
    except Exception as e:
        print(f"❌ 运行异常: {e}", file=sys.stderr)
        logging.getLogger("repo-watcher").exception("运行异常")
        return 1


if __name__ == "__main__":
    sys.exit(main())