"""鉴权服务。

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
            # 多行醒目警告,避免生产部署忘设导致重启后全员掉线
            logger.error(
                "\n"
                "=" * 70 + "\n"
                "  ⚠  [AUTH] JWT_SECRET 未设 — 用了临时密钥\n"
                "  ⚠  每次重启会生成新密钥,所有用户 token 立即失效\n"
                "  ⚠  生产环境务必设 JWT_SECRET 环境变量(32+ 字节随机)\n"
                "  ⚠  详见 docs/SECURITY.md\n"
                + "=" * 70
            )
        self._ttl_hours = config.auth.token_ttl_hours
        # 进程内已注销 token 集合(重启丢失,本地单用户可接受;
        # 改密失效走 pwd_iat 比较,这里只覆盖主动 logout)。
        self._revoked_tokens: set[str] = set()

    # ---- 密码哈希 ----

    def hash_password(self, plain: str) -> str:
        """pbkdf2:sha256 哈希(600k 迭代,salt 16 字节)"""
        return generate_password_hash(plain, method="pbkdf2:sha256", salt_length=16)

    def verify_password(self, plain: str, hashed: str) -> bool:
        return check_password_hash(hashed, plain)

    # ---- JWT ----

    # 固定 iss/aud,防止 token 被同机上其他服务误用
    _ISS = "matrix-live-diarizer"
    _AUD = "matrix-client"

    def create_token(self, user_id: int, username: str, pwd_iat: float = 0) -> str:
        """签发 JWT (HS256)

        payload: {sub, username, iat, exp, pwd_iat, iss, aud}
        - pwd_iat: 改密时间戳,用于改密后失效旧 token
        """
        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "username": username,
            "iat": now,
            "exp": now + self._ttl_hours * 3600,
            "pwd_iat": float(pwd_iat),
            "iss": self._ISS,                # 固定 issuer
            "aud": self._AUD,                # 固定 audience
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def decode_token(self, token: str) -> Optional[dict]:
        """解码 + 验签 + 查过期 + 校验 iss/aud;失败返 None(让上层返 401)"""
        try:
            return jwt.decode(
                token, self._secret, algorithms=["HS256"],
                audience=self._AUD,  # 校验 aud
                issuer=self._ISS,    # 校验 iss
            )
        except jwt.ExpiredSignatureError:
            logger.info("[AUTH] token 过期")
        except jwt.InvalidTokenError as e:
            logger.info(f"[AUTH] token 无效: {e}")
        return None

    def revoke_token(self, token: str) -> None:
        """注销 token:加入进程内 revoked 集合,使其立即失效。

        先 decode 校验为合法 JWT 才入集合(防白名单 logout 端点接收任意串投毒
        撑爆内存),并记录其 exp 供惰性过期清理(过期 token 本就会被 decode_token 拒)。
        """
        if not token:
            return
        payload = self.decode_token(token)
        if not payload:
            # 无效/过期 token 不需要 revoke(decode 已拒),避免任意串入集合
            return
        self._revoked_tokens.add(token)
        # 容量上界:超限时惰性清理过期条目,防无界增长
        if len(self._revoked_tokens) > 10_000:
            self._prune_revoked()

    def _prune_revoked(self) -> None:
        """清理已过期的 revoked token(exp < now),它们本就会被 decode_token 拒。"""
        now = int(time.time())
        to_keep = set()
        for tok in self._revoked_tokens:
            try:
                payload = jwt.decode(
                    tok, self._secret, algorithms=["HS256"],
                    audience=self._AUD, issuer=self._ISS,
                )
                if payload.get("exp", 0) > now:
                    to_keep.add(tok)
            except jwt.PyJWTError:
                # 过期或无效 → 不保留
                continue
        self._revoked_tokens = to_keep

    def is_revoked(self, token: str) -> bool:
        if not token:
            return False
        return token in self._revoked_tokens

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
                "SELECT id, username, must_change_password, is_active, created_at, last_login_at, password_changed_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def change_password(self, user_id: int, new_password: str) -> bool:
        """改密 + 清除 must_change_password 标志 + 更新 password_changed_at"""
        new_hash = self.hash_password(new_password)
        pwd_changed_at = time.time()
        with self.db.connect() as conn:
            cur = conn.execute(
                """UPDATE users
                   SET password_hash = ?, must_change_password = 0, password_changed_at = ?
                   WHERE id = ?""",
                (new_hash, pwd_changed_at, user_id),
            )
            conn.commit()
        return cur.rowcount > 0
