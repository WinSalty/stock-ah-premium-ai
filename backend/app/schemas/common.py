from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    """ORM 响应基类。

    创建日期：2026-05-04
    author: sunshengxian
    """

    model_config = ConfigDict(from_attributes=True)
