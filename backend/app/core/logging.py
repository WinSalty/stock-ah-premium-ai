from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    """配置应用日志。

    创建日期：2026-05-04
    author: sunshengxian
    """

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
