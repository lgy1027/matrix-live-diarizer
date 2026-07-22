import os
from pathlib import Path

from scripts import gen_self_cert


def test_extract_ipv4_addresses_filters_invalid_and_link_local_addresses():
    output = "127.0.0.1 192.168.1.8 169.254.10.2 999.1.2.3 192.168.1.8"

    assert gen_self_cert.extract_ipv4_addresses(output) == [
        "127.0.0.1",
        "192.168.1.8",
    ]


def test_platform_commands_support_windows_macos_and_linux(monkeypatch):
    monkeypatch.setattr(gen_self_cert.shutil, "which", lambda name: name)

    windows = gen_self_cert.platform_commands("Windows")
    macos = gen_self_cert.platform_commands("Darwin")
    linux = gen_self_cert.platform_commands("Linux")

    assert windows[0][0] == "powershell"
    assert "Get-NetIPAddress" in windows[0][-1]
    assert macos == [["ifconfig"]]
    assert linux == [["hostname", "-I"], ["ip", "-4", "-o", "addr", "show"]]


def test_collect_ipv4_addresses_combines_commands_and_socket_fallback(monkeypatch):
    monkeypatch.setattr(
        gen_self_cert,
        "platform_commands",
        lambda _system_name: [["first"], ["second"]],
    )
    monkeypatch.setattr(
        gen_self_cert,
        "run_command",
        lambda command: {
            "first": "192.168.1.9 169.254.1.2",
            "second": "10.0.0.5 192.168.1.9",
        }[command[0]],
    )
    monkeypatch.setattr(
        gen_self_cert,
        "socket_ipv4_addresses",
        lambda: ["172.16.0.3", "10.0.0.5"],
    )

    assert gen_self_cert.collect_ipv4_addresses("Linux") == [
        "10.0.0.5",
        "172.16.0.3",
        "192.168.1.9",
    ]


def test_build_subject_alt_name_always_includes_localhost():
    assert gen_self_cert.build_subject_alt_name(["192.168.1.9", "127.0.0.1"]) == (
        "DNS:localhost,IP:127.0.0.1,IP:192.168.1.9"
    )


def test_generate_certificate_does_not_overwrite_existing_pair(tmp_path, monkeypatch):
    cert = tmp_path / "selfsigned.crt"
    key = tmp_path / "selfsigned.key"
    cert.write_text("cert", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    monkeypatch.setattr(
        gen_self_cert.shutil,
        "which",
        lambda _name: (_ for _ in ()).throw(AssertionError("OpenSSL should not run")),
    )

    assert gen_self_cert.generate_certificate(tmp_path) == 0


def test_generate_certificate_invokes_openssl_with_collected_sans(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(gen_self_cert.shutil, "which", lambda _name: "openssl")
    monkeypatch.setattr(
        gen_self_cert,
        "collect_ipv4_addresses",
        lambda: ["10.0.0.8", "192.168.1.9"],
    )
    monkeypatch.setattr(
        gen_self_cert.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )

    assert gen_self_cert.generate_certificate(tmp_path) == 0
    assert calls == [
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-config",
            os.devnull,
            "-keyout",
            str(Path(tmp_path) / "selfsigned.key"),
            "-out",
            str(Path(tmp_path) / "selfsigned.crt"),
            "-days",
            "3650",
            "-subj",
            "/CN=matrix-live-diarizer-local",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:10.0.0.8,IP:192.168.1.9",
        ]
    ]
