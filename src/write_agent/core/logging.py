"""
日志配置 - Python logging 最佳实践
"""
import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    """
    配置日志系统

    类似于 Java 的 logback.xml 配置
    """
    # 日志格式
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # 创建 formatter
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    root_logger.addHandler(console_handler)

    # 设置第三方库日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器

    用法:
        logger = get_logger(__name__)
        logger.info("信息日志")
    """
    return logging.getLogger(name)
