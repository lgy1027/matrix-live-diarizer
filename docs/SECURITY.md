# 安全

## 支持的部署

受支持的 beta 部署是单用户在受信任的电脑上。默认服务绑定 `127.0.0.1`。本地浏览器请求仅在网络对端和浏览器 Origin 都是可信回环地址时才可绕过登录。

LAN 模式是高级部署，不是多用户安全边界。所有已认证用户会访问相同的会议和人物。

## 安全默认

- 默认配置无通配 CORS
- 本地绕过需 HTTP 与 WebSocket Origin 校验
- 可信本地绕过之外走 JWT 鉴权
- 默认账户首次登录强制改密
- 限流与基础浏览器安全响应头
- 公网 LLM endpoint 需显式 opt-in

## LAN 清单

```dotenv
HOST=0.0.0.0
DEPLOYMENT_MODE=lan
LOCAL_AUTH_DISABLED=false
JWT_SECRET=<至少 32 字节随机>
ALLOWED_ORIGINS=https://matrix.example.internal
```

把服务放到 HTTPS 反向代理和防火墙之后。不要把 8000 端口直接暴露到互联网。保持 `WORKERS=1`；推理引擎和进程内 job runner 按单进程设计。

## 敏感材料

音频、转写、embedding、SQLite 文件、`.env`、JWT 密钥和 LLM key 绝不可提交。**API key 不写入 SQLite**——仅通过 `LLM_API_KEY` 环境变量配置，应用层不存储。需要更强的机密隔离时，优先用本地 LLM 或环境变量。

模型加载器会下载第三方产物，部分 ModelScope 包可能执行受信任的上游模型代码。请审查模型来源与许可、使用隔离环境，避免以提升的权限运行未审查的缓存内容。

## 报告

不要在公开 Issue 中附带录音、转写、凭据或漏洞细节。请通过 [GitHub Security Advisories](https://github.com/lgy1027/matrix-live-diarizer/security/advisories/new) 私下报告漏洞。仓库维护者须在发布前启用私下漏洞报告。
