"""鉴权服务 (Roadmap 安全项)

提供:
- hash_password / verify_password(werkzeug pbkdf2 哈希)
- create_token / decode_token(PyJWT HS256)
- authenticate / get_user / change_password

JWT 在 localStorage 存(单用户本地用),走 Authorization: Bearer header。
"""
import secrets
import time
from typing import Optional
import jwt
from werkzeug.security import generate_password_hash, check_password_hash

import logging
from ..config import config
from ..repositories.database import Database

logger = logging.getLogger("Matrix_Auth")


class AuthService:
    def __init__(self, db: Database):
        self.db = db
        # 启动时若无 JWT_SECRET,生成随机密钥(token 跨进程失效,但本地够用)
        self._secret = config.auth.jwt_secret or secrets.token_urlsafe(48)
        if not config.auth.jwt_secret:
            logger.warning(
                "[AUTH] JWT_SECRET 未设 — 用了临时密钥。token 在重启后会失效。"
                "生产环境务必设 JWT_SECRET 环境变量!"
            )
        self._ttl_hours = config.auth.token_ttl_hours

    # ---- 密码哈希 ----

    def hash_password(self, plain: str) -> str:
        """pbkdf2:sha256 哈希(600k 迭代,salt 16 字节)"""
        return generate_password_hash(plain, method="pbkdf2:sha256", salt_length=16)

    def verify_password(self, plain: str, hashed: str) -> bool:
        return check_password_hash(hashed, plain)

    # ---- JWT ----

    def create_token(self, user_id: int, username: str) -> str:
        """签发 JWT (HS256)

        payload: {sub: user_id, username, iat, exp}
        """
        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "username": username,
            "iat": now,
            "exp": now + self._ttl_hours * 3600,
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def decode_token(self, token: str) -> Optional[dict]:
        """解码 + 验签 + 查过期;失败返 None(让上层返 401)"""
        try:
            return jwt.decode(token, self._secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            logger.info("[AUTH] token 过期")
        except jwt.InvalidTokenError as e:
            logger.info(f"[AUTH] token 无效: {e}")
        return None

    # ---- 用户 CRUD ----

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        """校验 username/password;成功返 user dict,失败 None

        user dict: {id, username, must_change_password, is_active}
        """
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, must_change_password, is_active FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return None
        user = dict(row)
        if not user["is_active"]:
            return None
        if not self.verify_password(password, user["password_hash"]):
            return None
        # 校验成功,更新 last_login_at
        with self.db.connect() as conn:
            conn.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
            conn.commit()
        # 不返 password_hash
        user.pop("password_hash", None)
        return user

    def get_user(self, user_id: int) -> Optional[dict]:
        """按 id 取 user(用于鉴权后查 user 信息)"""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, username, must_change_password, is_active, created_at, last_login_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def change_password(self, user_id: int, new_password: str) -> bool:
        """改密 + 清除 must_change_password 标志"""
        new_hash = self.hash_password(new_password)
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (new_hash, user_id),
            )
            conn.commit()
        return cur.rowcount > 0
