"""COMSOL 安装布局与当前机器架构解析。

官方支持范围（本仓库测试与打包目标）：
- Windows AMD64 / x86_64 → COMSOL 目录名 ``win64``
- macOS Apple Silicon     → COMSOL 目录名 ``macarm64``

COMSOL 6.3 在 Apple Silicon 上必须使用原生 Apple Silicon 安装包；
Intel 版不能通过 Rosetta 运行（COMSOL Knowledge Base 1321）。
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

SUPPORTED_PLATFORM_IDS = ("windows-x64", "darwin-arm64")


@dataclass(frozen=True)
class PlatformInfo:
    """当前（或注入的）操作系统与 COMSOL 架构信息。"""

    system: str
    machine: str
    platform_id: str
    supported: bool
    comsol_arch: str
    native_kind: str
    label: str


def normalize_machine(machine: Optional[str] = None) -> str:
    value = (machine or platform.machine()).lower()
    if value in ("amd64", "x86_64", "x64"):
        return "x64"
    if value in ("arm64", "aarch64"):
        return "arm64"
    return value


def get_platform_info(
    system: Optional[str] = None,
    machine: Optional[str] = None,
) -> PlatformInfo:
    system_raw = system or platform.system()
    system_key = system_raw.lower()
    arch = normalize_machine(machine)

    if system_key.startswith("win"):
        platform_id = "windows-x64" if arch == "x64" else f"windows-{arch}"
        return PlatformInfo(
            system="Windows",
            machine=arch,
            platform_id=platform_id,
            supported=platform_id == "windows-x64",
            comsol_arch="win64",
            native_kind="dll",
            label="Windows x64 (AMD64)" if arch == "x64" else f"Windows {arch}",
        )

    if system_key == "darwin":
        platform_id = "darwin-arm64" if arch == "arm64" else f"darwin-{arch}"
        return PlatformInfo(
            system="Darwin",
            machine=arch,
            platform_id=platform_id,
            supported=platform_id == "darwin-arm64",
            comsol_arch="macarm64" if arch == "arm64" else "maci64",
            native_kind="dylib",
            label="macOS Apple Silicon" if arch == "arm64" else "macOS Intel",
        )

    platform_id = f"linux-{arch}"
    return PlatformInfo(
        system="Linux",
        machine=arch,
        platform_id=platform_id,
        supported=False,
        comsol_arch="glnxa64" if arch == "x64" else "glnxaarch64",
        native_kind="so",
        label=f"Linux {arch}",
    )


def arch_candidates(info: Optional[PlatformInfo] = None) -> list[str]:
    """按优先级返回可能的 COMSOL 架构目录名。

    Apple Silicon 只使用 ``macarm64``，不回退到 ``maci64``：
    COMSOL 6.3 的 Intel 包无法在 Apple Silicon 上通过 Rosetta 运行。
    """
    info = info or get_platform_info()
    names = [info.comsol_arch]
    if info.system == "Darwin" and info.machine == "arm64":
        # 仅作为探测提示：旧代码曾误用 darwin64
        names.append("darwin64")
        return names
    if info.system == "Darwin":
        names.extend(["macarm64", "darwin64"])
    elif info.system == "Windows":
        names.append("win64")
    elif info.system == "Linux":
        names.extend(["glnxa64", "glnxaarch64"])
    return list(dict.fromkeys(names))


def multiphysics_root_from_jar_path(jar_path: Path) -> Path:
    path = Path(jar_path)
    if path.is_dir():
        return path.parent
    return path.parent.parent


def _first_existing_arch_dir(root: Path, subdir: str, arches: Sequence[str]) -> Optional[Path]:
    for arch in arches:
        candidate = root / subdir / arch
        if candidate.is_dir():
            return candidate
    return None


def resolve_comsol_native_path(
    jar_path: str | Path,
    *,
    native_override: str = "",
    info: Optional[PlatformInfo] = None,
) -> Optional[str]:
    """解析 ``java.library.path`` / PATH 所需的 COMSOL 本地库目录列表。"""
    if native_override:
        override = Path(native_override)
        if override.exists():
            return str(override.resolve())
        # 允许用户直接填 PATH 分隔的多个目录
        if os.pathsep in native_override:
            return native_override

    path = Path(jar_path)
    if not path.exists():
        return None

    info = info or get_platform_info()
    root = multiphysics_root_from_jar_path(path)
    arches = arch_candidates(info)
    parts: list[str] = []

    for subdir in ("lib", "bin", "license"):
        found = _first_existing_arch_dir(root, subdir, arches)
        if found is None and subdir == "license":
            continue
        if found is not None:
            resolved = str(found.resolve())
            if resolved not in parts:
                parts.append(resolved)
            lmadmin = found / "lmadmin"
            if lmadmin.is_dir():
                lm_resolved = str(lmadmin.resolve())
                if lm_resolved not in parts:
                    parts.append(lm_resolved)

    if not parts:
        return None
    return os.pathsep.join(parts)


def _jvm_file_candidates(java_arch_root: Path, info: PlatformInfo) -> list[Path]:
    if info.system == "Windows":
        return [
            java_arch_root / "jre" / "bin" / "server" / "jvm.dll",
            java_arch_root / "bin" / "server" / "jvm.dll",
        ]
    if info.system == "Darwin":
        return [
            java_arch_root / "jre" / "lib" / "server" / "libjvm.dylib",
            java_arch_root / "jre" / "lib" / "aarch64" / "server" / "libjvm.dylib",
            java_arch_root / "jre" / "lib" / "amd64" / "server" / "libjvm.dylib",
            java_arch_root / "lib" / "server" / "libjvm.dylib",
        ]
    return [
        java_arch_root / "jre" / "lib" / "server" / "libjvm.so",
        java_arch_root / "jre" / "lib" / "amd64" / "server" / "libjvm.so",
        java_arch_root / "jre" / "lib" / "aarch64" / "server" / "libjvm.so",
        java_arch_root / "lib" / "server" / "libjvm.so",
    ]


def resolve_comsol_jvm_path(
    jar_path: str | Path,
    *,
    info: Optional[PlatformInfo] = None,
) -> Optional[str]:
    path = Path(jar_path)
    if not path.exists():
        return None

    info = info or get_platform_info()
    root = multiphysics_root_from_jar_path(path)
    for arch in arch_candidates(info):
        java_arch_root = root / "java" / arch
        for candidate in _jvm_file_candidates(java_arch_root, info):
            if candidate.exists():
                return str(candidate.resolve())
    return None


def java_home_from_jvm(jvm_path: str | Path) -> str:
    current = Path(jvm_path).resolve().parent
    for _ in range(8):
        if (current / "bin" / "java").exists() or (current / "bin" / "java.exe").exists():
            return str(current)
        if current.parent == current:
            break
        current = current.parent
    return str(Path(jvm_path).resolve().parent.parent.parent)


def default_plugins_candidates(info: Optional[PlatformInfo] = None) -> list[Path]:
    info = info or get_platform_info()
    candidates: list[Path] = []

    if info.system == "Windows":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidates.extend(
            [
                program_files / "COMSOL" / "COMSOL63" / "Multiphysics" / "plugins",
                program_files / "COMSOL" / "COMSOL 6.3" / "Multiphysics" / "plugins",
            ]
        )
        comsol_root = program_files / "COMSOL"
        if comsol_root.is_dir():
            for child in comsol_root.iterdir():
                plugins = child / "Multiphysics" / "plugins"
                if plugins not in candidates:
                    candidates.append(plugins)
    elif info.system == "Darwin":
        apps = Path("/Applications")
        candidates.extend(
            [
                apps / "COMSOL63" / "Multiphysics" / "plugins",
                apps / "COMSOL 6.3" / "Multiphysics" / "plugins",
            ]
        )
        if apps.is_dir():
            for child in apps.glob("COMSOL*"):
                plugins = child / "Multiphysics" / "plugins"
                if plugins not in candidates:
                    candidates.append(plugins)
    else:
        candidates.extend(
            [
                Path("/usr/local/comsol63/multiphysics/plugins"),
                Path("/opt/comsol63/multiphysics/plugins"),
            ]
        )

    return sorted(candidates, key=_prefer_63_score)


def _prefer_63_score(path: Path) -> tuple[int, str]:
    # 只看安装目录末几段，避免 pytest 临时路径名里的数字干扰。
    names = "/".join(part.lower() for part in path.parts[-3:])
    prefer_63 = 0 if ("63" in names or "6.3" in names) else 1
    return prefer_63, names


def _dir_has_jars(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        next(path.glob("*.jar"))
        return True
    except StopIteration:
        return False


def detect_comsol_plugins_dir(
    *,
    roots: Optional[Iterable[Path]] = None,
    info: Optional[PlatformInfo] = None,
) -> Optional[str]:
    """在常见安装位置查找 COMSOL 6.3 ``plugins`` 目录。"""
    candidates = list(roots) if roots is not None else default_plugins_candidates(info)
    for candidate in sorted(candidates, key=_prefer_63_score):
        path = Path(candidate)
        if _dir_has_jars(path):
            return str(path.resolve())
    return None


def apply_native_library_env(native_path: str, *, info: Optional[PlatformInfo] = None) -> None:
    """把 COMSOL 本地库目录加入进程环境，供 JNI 加载。"""
    info = info or get_platform_info()
    sep = os.pathsep
    path_vars = ["PATH"]
    if info.system == "Darwin":
        path_vars.extend(["DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"])
    elif info.system == "Linux":
        path_vars.append("LD_LIBRARY_PATH")

    for var in path_vars:
        old = os.environ.get(var, "")
        if native_path in old:
            continue
        os.environ[var] = native_path + sep + old if old else native_path


def unsupported_platform_message(info: Optional[PlatformInfo] = None) -> Optional[str]:
    info = info or get_platform_info()
    if info.supported:
        return None
    return (
        f"当前平台 {info.label}（{info.platform_id}）不在官方测试范围内。"
        "本仓库目前支持 Windows x64（AMD64）与 macOS Apple Silicon。"
    )
