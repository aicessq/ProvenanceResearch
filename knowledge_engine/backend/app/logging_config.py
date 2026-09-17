"""日志配置模块。

设计说明（教学向）
==================

1. 为什么统一配置 logging？
   规格 §3.3 要求“使用 Python 标准 logging 统一输出日志”，
   并要求“所有入库、检索、模型调用错误必须记录日志”。
   在应用启动时统一配置一次，后续所有模块只需 `logging.getLogger(__name__)`
   即可获得一致格式的日志，避免每个模块各自 print。

2. 为什么不直接用 print？
   - print 无法分级（DEBUG/INFO/WARNING/ERROR）；
   - print 无法被统一捕获到文件或外部日志系统；
   - 在多 worker / Docker 环境下，标准 logging 更容易接入结构化日志。

3. Phase 0 只做“基础可用”的日志配置：
   - 控制台输出；
   - 统一时间/级别/名称格式；
   - 调试模式可切换更详细的日志级别。
   后续 Phase 可在此基础上扩展文件日志、JSON 日志等，但不属于 Phase 0 范围。
"""

from __future__ import annotations

import logging
import sys


def setup_logging(debug: bool = False) -> None:
    """初始化全局日志配置。

    参数:
        debug: 是否开启 DEBUG 级别日志；为 False 时使用 INFO 级别。
    """
    level = logging.DEBUG if debug else logging.INFO

    # 日志格式：时间 - 级别 - logger名 - 消息
    # 这样在排查问题时可以快速定位是哪个模块输出的日志
    log_format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 重置已有 handler，避免重复配置导致日志重复输出
    root = logging.getLogger()
    root.setLevel(level)
    # 清理可能存在的旧 handler（例如测试中多次调用本函数）
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # 输出到标准错误，便于 Docker 容器中 `docker logs` 直接查看
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(handler)

    # 对第三方库的噪音日志做适度降噪，避免淹没业务日志
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
