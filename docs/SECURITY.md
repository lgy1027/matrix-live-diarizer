# 安全模型 (Roadmap 安全项)

> 本文档描述 Matrix Live Diarizer 的鉴权 / 密码 / token 机制,以及**生产部署**前必须检查的事项。

---

## 1. 默认账户

| 字段 | 值 |
|---|---|
| 用户名 | `admin` |
| 密码 | `admin` |
| 首次登录标志 | `must_change_password=1` |
| 启动行为 | DB 启动时若 `users` 表空,自动创建 |

**首次登录后**,前端会**强制弹出**"修改密码"modal,不修改不能使用其他功能。

修改密码:`Settings → 账户 → 修改密码`(需要旧密码)。

---

## 2. 鉴权机制

### Token
- **算法**: JWT (HS256)
- **库**: PyJWT
- **有效期**: 默认 24 小时 (`TOKEN_TTL_HOURS` 可调)
- **存储**: 前端 `localStorage.matrix_token`
- **传输**: `Authorization: Bearer <token>` header

### 中间件
- 路径: `app/middleware/auth.py`
- 策略: 全部 `/v1/*` 需 token,白名单路径除外
- 白名单:
  - `/v1/auth/login` (登录)
  - `/v1/auth/logout` (退出,no-op)
  - `/health`, `/ready` (K8s 探针)
  - `/v1/models`, `/v1/llm/status` (公开元信息)
- OPTIONS 预检:放行(CORS)

### 密码哈希
- **算法**: PBKDF2-HMAC-SHA256
- **库**: werkzeug.security(Flask 同款)
- **迭代**: 600,000
- **Salt**: 16 字节随机
- **存**: `users.password_hash`,格式 `pbkdf2:sha256:600000$<salt>$<hash>`

### 端点

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/v1/auth/login` | POST | 否 | 返 `{token, user, must_change_password}` |
| `/v1/auth/logout` | POST | 否(无状态) | 客户端删 token |
| `/v1/auth/me` | GET | 是 | 返当前用户信息 |
| `/v1/auth/change-password` | POST | 是 | 改密 + 清除 must_change_password + 返新 token |
| 其他 `/v1/*` | * | 是 | 需 Bearer token |

---

## 3. 端点失败响应

| 场景 | 状态码 | detail |
|---|---|---|
| 缺 token | 401 | "未登录或登录已过期,请重新登录" |
| token 失效/过期 | 401 | "token 无效或已过期" |
| token 格式错 | 401 | "token 格式错误" |
| 缺 Bearer 前缀 | 401 | "未登录或登录已过期,请重新登录" |
| 错密码登录 | 401 | "用户名或密码错误"(模糊,防枚举) |
| 旧密码错(改密) | 400 | "旧密码错误" |
| 密码 < 6 字符 | 422 | Pydantic 校验 |

---

## 4. ⚠️ 生产部署前必检

建议先明确部署模式:

| `DEPLOYMENT_MODE` | 用途 | 启动校验 |
|---|---|---|
| `local` | 本机试用/开发,默认值 | 不强制 `JWT_SECRET` / CORS |
| `lan` | 局域网多人访问 | 必须设置 `JWT_SECRET`,且 `ALLOWED_ORIGINS` 不能是 `*` |
| `public` | 公网或半公网访问 | 同 `lan`,并在日志中提示必须放在 HTTPS/反向代理/防火墙之后 |

项目不建议公网裸露部署。`DEPLOYMENT_MODE=public` 只表示"我知道这是公网环境,请启用更严格启动校验",不是生产安全的一键开关。

| 项 | 风险 | 必须改 |
|---|---|---|
| **`JWT_SECRET` 环境变量** | 不设的话,每次启动用随机密钥,**所有用户 token 立即失效** | 生产必须设一个长随机值(32+ 字节) |
| **HTTPS** | JWT 在 HTTP 明文传输,中间人可截获 | 生产必须 HTTPS(Nginx/Caddy 反代 + Let's Encrypt) |
| **CORS `allowed_origins`** | 默认 `*` 允许任意源,任何网站可调你的 API | LAN/生产必须改成具体 origin 列表 |
| **公网暴露** | 项目是本地工具,**不推荐公网部署** | 如必须,用防火墙限制 + HTTPS + 强密码 |
| **`admin/admin` 默认密码** | 任何人可登录 | 第一次登录后**强制改** |
| **token TTL** | 24h 偏长,泄露窗口大 | 改 `TOKEN_TTL_HOURS=2` (短) |

### 配置示例 `.env`
```bash
# 必设
DEPLOYMENT_MODE=lan
JWT_SECRET=$(openssl rand -hex 32)

# 推荐
TOKEN_TTL_HOURS=8
ALLOWED_ORIGINS=https://matrix.example.com
```

---

## 5. 紧急 — 密码忘了

**目前没有"忘记密码"流程**(单用户本地工具,无 email 通道)。

恢复步骤:
1. 停服务: `pkill -f "python main.py"`
2. 删 users 表一行:
   ```bash
   sqlite3 data/matrix.db "DELETE FROM users WHERE username='admin';"
   ```
3. 重启服务: `python main.py` — 自动重建 `admin/admin` 账户

⚠️ 删 users 表会**清空所有用户配置**,但**不影响转写历史/说话人**(这些存在 sessions/segments 表)。

如要保留 sessions 历史但重置密码,SQL 改:
```bash
sqlite3 data/matrix.db \
  "UPDATE users SET password_hash='<新 pbkdf2 哈希>', must_change_password=0 WHERE username='admin';"
```
生成 pbkdf2 哈希用 Python:
```python
from werkzeug.security import generate_password_hash
print(generate_password_hash("your-new-password", method="pbkdf2:sha256", salt_length=16))
```

---

## 6. 测试模式 bypass

`AuthMiddleware` 在 `TEST_AUTH_BYPASS=1` 时跳过鉴权(给测试 fixture 用,避免测试用例都先登录)。

生产环境**不应**设这个环境变量。`DEPLOYMENT_MODE=lan/public` 时服务会拒绝带 `TEST_AUTH_BYPASS=1` 启动;本地开发如需使用,请保持 `DEPLOYMENT_MODE=local`。
