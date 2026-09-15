"""COMSOL 平台路径解析：Windows x64 与 macOS Apple Silicon。"""
from pathlib import Path

from agent.utils.comsol_platform import (
    apply_native_library_env,
    detect_comsol_plugins_dir,
    get_platform_info,
    java_home_from_jvm,
    resolve_comsol_jvm_path,
    resolve_comsol_native_path,
    unsupported_platform_message,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def _make_windows_layout(root: Path) -> Path:
    plugins = root / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "comsol.jar").write_bytes(b"pk")
    (root / "lib" / "win64").mkdir(parents=True)
    (root / "bin" / "win64").mkdir(parents=True)
    (root / "license" / "win64" / "lmadmin").mkdir(parents=True)
    _touch(root / "java" / "win64" / "jre" / "bin" / "server" / "jvm.dll")
    _touch(root / "java" / "win64" / "jre" / "bin" / "java.exe")
    return plugins


def _make_mac_arm_layout(root: Path) -> Path:
    plugins = root / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "comsol.jar").write_bytes(b"pk")
    (root / "lib" / "macarm64").mkdir(parents=True)
    (root / "bin" / "macarm64").mkdir(parents=True)
    _touch(root / "java" / "macarm64" / "jre" / "lib" / "server" / "libjvm.dylib")
    _touch(root / "java" / "macarm64" / "jre" / "bin" / "java")
    return plugins


def test_platform_ids():
    win = get_platform_info("Windows", "AMD64")
    assert win.supported is True
    assert win.platform_id == "windows-x64"
    assert win.comsol_arch == "win64"

    mac = get_platform_info("Darwin", "arm64")
    assert mac.supported is True
    assert mac.platform_id == "darwin-arm64"
    assert mac.comsol_arch == "macarm64"

    win_arm = get_platform_info("Windows", "ARM64")
    assert win_arm.supported is False
    assert unsupported_platform_message(win_arm)

    mac_intel = get_platform_info("Darwin", "x86_64")
    assert mac_intel.supported is False
    assert mac_intel.comsol_arch == "maci64"


def test_windows_native_and_jvm_paths(tmp_path):
    plugins = _make_windows_layout(tmp_path / "Multiphysics")
    info = get_platform_info("Windows", "AMD64")
    native = resolve_comsol_native_path(plugins, info=info)
    assert native is not None
    assert "lib" in native and "win64" in native
    assert "bin" in native and "win64" in native
    assert "license" in native

    jvm = resolve_comsol_jvm_path(plugins, info=info)
    assert jvm is not None
    assert jvm.endswith("jvm.dll")
    java_home = java_home_from_jvm(jvm)
    assert (Path(java_home) / "bin" / "java.exe").exists()


def test_mac_apple_silicon_uses_macarm64_not_darwin64(tmp_path):
    root = tmp_path / "Multiphysics"
    plugins = _make_mac_arm_layout(root)
    (root / "lib" / "darwin64").mkdir(parents=True)
    (root / "bin" / "darwin64").mkdir(parents=True)
    (root / "lib" / "maci64").mkdir(parents=True)

    info = get_platform_info("Darwin", "arm64")
    native = resolve_comsol_native_path(plugins, info=info)
    assert native is not None
    assert "macarm64" in native
    assert "darwin64" not in native
    assert "maci64" not in native

    jvm = resolve_comsol_jvm_path(plugins, info=info)
    assert jvm is not None
    assert "macarm64" in jvm
    assert jvm.endswith("libjvm.dylib")


def test_mac_does_not_pick_intel_layout_on_apple_silicon(tmp_path):
    root = tmp_path / "Multiphysics"
    plugins = root / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "comsol.jar").write_bytes(b"pk")
    (root / "lib" / "maci64").mkdir(parents=True)
    (root / "bin" / "maci64").mkdir(parents=True)
    _touch(root / "java" / "maci64" / "jre" / "lib" / "server" / "libjvm.dylib")

    info = get_platform_info("Darwin", "arm64")
    native = resolve_comsol_native_path(plugins, info=info)
    # macarm64 不存在时，darwin64 也不存在，不应误用 maci64
    assert native is None or "maci64" not in native
    jvm = resolve_comsol_jvm_path(plugins, info=info)
    assert jvm is None


def test_detect_prefers_63(tmp_path):
    older = tmp_path / "COMSOL62" / "Multiphysics" / "plugins"
    newer = tmp_path / "COMSOL63" / "Multiphysics" / "plugins"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "old.jar").write_bytes(b"pk")
    (newer / "new.jar").write_bytes(b"pk")

    found = detect_comsol_plugins_dir(roots=[older, newer, tmp_path / "missing"])
    assert found is not None
    assert Path(found).resolve() == newer.resolve()


def test_native_override(tmp_path):
    plugins = _make_mac_arm_layout(tmp_path / "Multiphysics")
    override = tmp_path / "custom-native"
    override.mkdir()
    info = get_platform_info("Darwin", "arm64")
    native = resolve_comsol_native_path(plugins, native_override=str(override), info=info)
    assert Path(native).resolve() == override.resolve()


def test_apply_native_library_env_darwin(monkeypatch):
    import os

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.delenv("DYLD_LIBRARY_PATH", raising=False)
    info = get_platform_info("Darwin", "arm64")
    apply_native_library_env("/opt/comsol/lib/macarm64", info=info)
    assert "/opt/comsol/lib/macarm64" in os.environ["PATH"]
    assert os.environ["DYLD_LIBRARY_PATH"].startswith("/opt/comsol/lib/macarm64")
