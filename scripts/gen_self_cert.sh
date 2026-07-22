#!/usr/bin/env bash
# 生成自签证书供 main.py 的 HTTPS 模式使用(uvicorn ssl_certfile/ssl_keyfile)。
# 把本机所有 IP 写进 SAN,减少跨 IP 访问时的证书警告。
# 证书输出到 data/ssl/ (data/ 已被 .gitignore 覆盖,不会进 git)。
#
# 注意:本脚本仅支持 macOS(用 ipconfig getifaddr 收集本机 IP)。Linux 用户请用
# hostname -I / ip addr 自行填 SAN,或直接删掉 IP 收集段、只保留 DNS:localhost。
set -euo pipefail

if [ "$(uname)" != "Darwin" ]; then
  echo "[cert] 本脚本当前仅支持 macOS;Linux 请参考脚本头注释自行收集 IP。" >&2
  exit 1
fi

SSL_DIR="${SSL_DIR:-data/ssl}"
mkdir -p "$SSL_DIR"
CRT="$SSL_DIR/selfsigned.crt"
KEY="$SSL_DIR/selfsigned.key"

# 收集 SAN:localhost + 所有本机 IPv4
SANS="DNS:localhost"
for ip in $(ipconfig getifaddr en0 2>/dev/null; ipconfig getifaddr en1 2>/dev/null; hostname 2>/dev/null); do
  case "$ip" in
    *.*.*.*) SANS="$SANS,IP:$ip" ;;
    *)       SANS="$SANS,DNS:$ip" ;;
  esac
done

if [ -f "$CRT" ] && [ -f "$KEY" ]; then
  echo "[cert] 已存在: $CRT (如需重生成先删除它)"
  exit 0
fi

echo "[cert] 生成自签证书 SAN=$SANS"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$KEY" -out "$CRT" -days 3650 \
  -subj "/CN=matrix-live-diarizer-local" \
  -addext "subjectAltName=$SANS"

echo "[cert] 完成: $CRT / $KEY"
echo "[cert] 浏览器首次访问会提示不安全,点'高级 → 继续前往'。"
