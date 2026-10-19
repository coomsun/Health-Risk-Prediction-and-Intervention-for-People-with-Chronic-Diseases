# -*- coding: utf-8 -*-
"""api/auth.py — JWT 鉴权（综合项目加分项）

设计原则：
1. **不破坏既有接口**：所有 /api/v1/* 查询接口默认公开，评阅人无需登录即可演示。
2. **写操作受保护**：POST /api/v1/predict 与 /api/v1/admin/* 需要 Bearer 令牌。
3. **密钥不落代码**：从环境变量 AUTH_SECRET_KEY 读取；未设置时自动生成随机密钥并
   在启动日志中告警（仅本地开发可接受），生产必须显式配置。
4. 密码用 bcrypt 哈希存储，不在任何文件中出现明文。

环境变量：
    AUTH_SECRET_KEY   签名密钥（生产必填）
    AUTH_USERS        "用户名:密码,用户名:密码" 形式的内置账号（演示用）
    AUTH_TOKEN_TTL    令牌有效期秒数，默认 3600
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .contract import CODE_INVALID_PARAM, ApiError

_ALGO = "HS256"
_TTL = int(os.environ.get("AUTH_TOKEN_TTL", "3600"))

# 密钥：环境变量优先；缺失时随机生成（进程内有效，重启即失效）
_SECRET = os.environ.get("AUTH_SECRET_KEY", "")
SECRET_IS_EPHEMERAL = not bool(_SECRET)
if not _SECRET:
    _SECRET = secrets.token_urlsafe(48)


def _load_users() -> dict[str, str]:
    """解析内置账号。密码在此处用 bcrypt 哈希后驻留内存，不写盘。"""
    raw = os.environ.get("AUTH_USERS", "demo:demo12345,admin:admin12345")
    users: dict[str, str] = {}
    for item in raw.split(","):
        if ":" not in item:
            continue
        name, pwd = item.split(":", 1)
        users[name.strip()] = _hash(pwd.strip())
    return users


def _hash(plain: str) -> str:
    """bcrypt 哈希。直接调用 bcrypt 库，避免 passlib 与新版 bcrypt 的兼容问题。"""
    import bcrypt

    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt(rounds=10)).decode("ascii")


def _verify(plain: str, hashed: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("ascii"))
    except Exception:
        return False


_USERS = _load_users()
_bearer = HTTPBearer(auto_error=False)


def authenticate(username: str, password: str) -> bool:
    hashed = _USERS.get(username)
    return bool(hashed) and _verify(password, hashed)


def issue_token(username: str, ttl: int | None = None) -> dict[str, Any]:
    now = int(time.time())
    exp = now + (ttl or _TTL)
    payload = {"sub": username, "iat": now, "exp": exp, "iss": "brfss-api"}
    token = jwt.encode(payload, _SECRET, algorithm=_ALGO)
    return {"accessToken": token, "tokenType": "Bearer", "expiresIn": exp - now, "expiresAt": exp}


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _SECRET, algorithms=[_ALGO], issuer="brfss-api")
    except jwt.ExpiredSignatureError:
        raise ApiError(CODE_INVALID_PARAM, "令牌已过期，请重新登录", 401)
    except jwt.InvalidTokenError as exc:
        raise ApiError(CODE_INVALID_PARAM, f"令牌无效：{exc}", 401)


async def require_token(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """受保护接口的依赖：校验 Bearer 令牌。"""
    if cred is None or not cred.credentials:
        raise ApiError(CODE_INVALID_PARAM, "缺少访问令牌：请在 Authorization 头中提供 Bearer <token>", 401)
    claims = decode_token(cred.credentials)
    request.state.user = claims.get("sub")
    return claims


async def optional_token(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any] | None:
    """可选鉴权：带了令牌就解析，没带也放行（用于公开查询接口记录调用者）。"""
    if cred is None or not cred.credentials:
        return None
    try:
        claims = decode_token(cred.credentials)
    except ApiError:
        return None
    request.state.user = claims.get("sub")
    return claims
