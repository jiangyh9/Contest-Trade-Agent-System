"""
Wind 数据库 JDBC 客户端

通过 JayDeBeApi + ojdbc8 连接 Oracle 11.2.0.4（thin 模式不支持，需要 JDBC 驱动）。
使用方式：
    from utils.wind_jdbc_client import get_wind_client
    client = get_wind_client()
    df = client.query_to_df("SELECT ...")
"""

import os
import re
import pandas as pd
import jaydebeapi
from pathlib import Path
from loguru import logger
from typing import Optional, Dict, Any


class WindJDBCClient:
    """基于 JayDeBeApi 的 Wind Oracle 客户端"""

    def __init__(
        self,
        java_home: Optional[str] = None,
        jdbc_jar: Optional[str] = None,
        jdbc_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.java_home = java_home or os.environ.get("WIND_JAVA_HOME") or os.environ.get("JAVA_HOME")
        self.jdbc_jar = jdbc_jar or os.environ.get("WIND_JDBC_JAR")
        self.jdbc_url = jdbc_url or os.environ.get("WIND_JDBC_URL")
        self.username = username or os.environ.get("WIND_JDBC_USER")
        self.password = password or os.environ.get("WIND_JDBC_PASS")
        self._conn = None
        self._cur = None

    def _ensure_java_home(self) -> str:
        if not self.java_home:
            raise RuntimeError(
                "未配置 JAVA_HOME。请设置环境变量 WIND_JAVA_HOME 或 JAVA_HOME，"
                "或在 wind_jdbc 配置中指定 java_home。"
            )
        jh = Path(self.java_home).expanduser()
        if not jh.exists():
            raise RuntimeError(f"JAVA_HOME 路径不存在: {jh}")
        os.environ["JAVA_HOME"] = str(jh)
        return str(jh)

    def _ensure_jdbc_jar(self) -> str:
        if not self.jdbc_jar:
            raise RuntimeError(
                "未配置 Wind JDBC jar 路径。请设置环境变量 WIND_JDBC_JAR，"
                "或在 wind_jdbc 配置中指定 jdbc_jar。"
            )
        jar = Path(self.jdbc_jar).expanduser()
        if not jar.exists():
            raise RuntimeError(f"JDBC jar 不存在: {jar}")
        return str(jar)

    def connect(self):
        """建立 JDBC 连接（幂等）"""
        if self._conn is not None:
            return self
        self._ensure_java_home()
        jar = self._ensure_jdbc_jar()
        if not self.jdbc_url or not self.username or not self.password:
            raise RuntimeError("Wind JDBC URL / 用户名 / 密码 未配置")
        logger.info("Connecting to Wind JDBC")
        self._conn = jaydebeapi.connect(
            "oracle.jdbc.OracleDriver",
            self.jdbc_url,
            [self.username, self.password],
            jar,
        )
        self._cur = self._conn.cursor()
        return self

    def close(self):
        if self._cur:
            try:
                self._cur.close()
            except Exception:
                pass
            self._cur = None
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def execute(self, sql: str, params: Optional[tuple] = None):
        self.connect()
        if params:
            self._cur.execute(sql, params)
        else:
            self._cur.execute(sql)

    def fetchall(self):
        self.connect()
        return self._cur.fetchall()

    def query_to_df(self, sql: str, params: Optional[tuple] = None) -> pd.DataFrame:
        """执行查询并返回 pandas DataFrame"""
        self.connect()
        self.execute(sql, params)
        rows = self._cur.fetchall()
        if not rows:
            return pd.DataFrame()
        columns = [desc[0] for desc in self._cur.description]
        return pd.DataFrame(rows, columns=columns)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 全局缓存，避免重复建立连接
_GLOBAL_WIND_CLIENT: Optional[WindJDBCClient] = None


def get_wind_client(cfg: Optional[Dict[str, Any]] = None) -> WindJDBCClient:
    """
    获取全局 Wind JDBC 客户端。
    如果传入 cfg，优先使用 cfg 中 wind_jdbc 配置；否则从环境变量读取。
    """
    global _GLOBAL_WIND_CLIENT
    if _GLOBAL_WIND_CLIENT is not None:
        return _GLOBAL_WIND_CLIENT

    kwargs = {}
    if cfg is not None:
        wind_cfg = getattr(cfg, "wind_jdbc", None) if hasattr(cfg, "wind_jdbc") else cfg.get("wind_jdbc") if isinstance(cfg, dict) else None
        if isinstance(wind_cfg, dict):
            kwargs = {
                "java_home": wind_cfg.get("java_home"),
                "jdbc_jar": wind_cfg.get("jdbc_jar"),
                "jdbc_url": wind_cfg.get("jdbc_url"),
                "username": wind_cfg.get("username"),
                "password": wind_cfg.get("password"),
            }

    _GLOBAL_WIND_CLIENT = WindJDBCClient(**kwargs)
    return _GLOBAL_WIND_CLIENT
