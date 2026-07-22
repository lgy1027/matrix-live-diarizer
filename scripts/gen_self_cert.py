#!/usr/bin/env python3
"""Generate a local self-signed HTTPS certificate on Windows, macOS, or Linux."""

from __future__ import annotations

import ipaddress
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Sequence


IPV4_PATTERN = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")


def extract_ipv4_addresses(output: str) -> list[str]:
    """Extract usable IPv4 addresses from command output, preserving order."""
    addresses: list[str] = []
    for candidate in IPV4_PATTERN.findall(output):
        try:
            address = ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError:
            continue
        if address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            continue
        text = str(address)
        if text not in addresses:
            addresses.append(text)
    return addresses


def platform_commands(system_name: str) -> list[list[str]]:
    """Return safe, argument-separated commands used to discover local IPv4 addresses."""
    if system_name == "Windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
        return [
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue "
                    "| Select-Object -ExpandProperty IPAddress"
                ),
            ]
        ]
    if system_name == "Darwin":
        return [["ifconfig"]]
    if system_name == "Linux":
        return [["hostname", "-I"], ["ip", "-4", "-o", "addr", "show"]]
    return []


def run_command(command: Sequence[str]) -> str:
    """Run an address-discovery command without invoking a shell."""
    try:
        result = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""
    return result.stdout


def socket_ipv4_addresses() -> list[str]:
    """Provide a standard-library fallback when platform utilities are unavailable."""
    try:
        records = socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return []
    return extract_ipv4_addresses(" ".join(record[4][0] for record in records))


def collect_ipv4_addresses(system_name: str | None = None) -> list[str]:
    """Collect and deterministically order local IPv4 addresses."""
    addresses: set[str] = set()
    for command in platform_commands(system_name or platform.system()):
        addresses.update(extract_ipv4_addresses(run_command(command)))
    addresses.update(socket_ipv4_addresses())
    addresses.discard("127.0.0.1")
    return sorted(addresses, key=ipaddress.IPv4Address)


def build_subject_alt_name(addresses: Sequence[str]) -> str:
    """Build the OpenSSL subjectAltName extension value."""
    unique_addresses = sorted(
        {address for address in addresses if address != "127.0.0.1"},
        key=ipaddress.IPv4Address,
    )
    parts = ["DNS:localhost", "IP:127.0.0.1"]
    parts.extend(f"IP:{address}" for address in unique_addresses)
    return ",".join(parts)


def generate_certificate(ssl_dir: Path) -> int:
    """Generate the certificate and private key, returning a process-style status code."""
    ssl_dir.mkdir(parents=True, exist_ok=True)
    certificate = ssl_dir / "selfsigned.crt"
    private_key = ssl_dir / "selfsigned.key"

    if certificate.is_file() and private_key.is_file():
        print(f"[cert] 已存在: {certificate} (如需重生成请先删除证书和密钥)")
        return 0

    openssl = shutil.which("openssl")
    if openssl is None:
        print(
            "[cert] 未找到 OpenSSL。请先安装 OpenSSL 并确保 openssl 命令位于 PATH 中。",
            file=sys.stderr,
        )
        return 1

    subject_alt_name = build_subject_alt_name(collect_ipv4_addresses())
    command = [
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-config",
        os.devnull,
        "-keyout",
        str(private_key),
        "-out",
        str(certificate),
        "-days",
        "3650",
        "-subj",
        "/CN=matrix-live-diarizer-local",
        "-addext",
        f"subjectAltName={subject_alt_name}",
    ]

    print(f"[cert] 生成自签证书 SAN={subject_alt_name}")
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[cert] OpenSSL 执行失败: {exc}", file=sys.stderr)
        return 1

    print(f"[cert] 完成: {certificate} / {private_key}")
    print("[cert] 浏览器首次访问会提示不安全，请选择‘高级 → 继续前往’。")
    return 0


def main() -> int:
    ssl_dir = Path(os.environ.get("SSL_DIR", "data/ssl"))
    return generate_certificate(ssl_dir)


if __name__ == "__main__":
    raise SystemExit(main())
