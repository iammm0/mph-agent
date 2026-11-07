"""探测本机计算后端（CPU / NVIDIA GPU），供求解与桌面状态条使用。

说明（COMSOL 6.3）：
- GPU 加速目前主要覆盖「时间显式压力声学 dG」与 DNN 代理训练等有限场景；
- 固体力学 / 固体传热 / 常规稳态求解仍以 CPU（多核）为主。
因此即使检测到 GPU，多数建模任务也会显示「GPU 待命 · CPU 计算」。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

from agent.utils.logger import get_logger

logger = get_logger(__name__)

ComputePreference = Literal["auto", "cpu", "gpu"]
VALID_PREFERENCES = ("auto", "cpu", "gpu")


@dataclass
class ComputeBackendInfo:
    """当前/可用计算后端快照。"""

    mode: str  # cpu | gpu | gpu_standby
    label: str
    detail: str
    gpu_available: bool = False
    gpu_name: str = ""
    cuda_available: bool = False
    comsol_gpu_applicable: bool = False
    preference: str = "auto"  # auto | cpu | gpu

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_cached: Optional[ComputeBackendInfo] = None
_preference_override: Optional[str] = None


def get_compute_preference() -> ComputePreference:
    """读取计算偏好：进程内覆盖 > 环境变量 COMSOL_COMPUTE_PREFERENCE > auto。"""
    raw = (_preference_override or os.environ.get("COMSOL_COMPUTE_PREFERENCE") or "auto")
    value = str(raw).strip().lower()
    if value in ("cpu_only", "force_cpu"):
        value = "cpu"
    if value in ("gpu_prefer", "prefer_gpu", "force_gpu"):
        value = "gpu"
    if value not in VALID_PREFERENCES:
        return "auto"
    return value  # type: ignore[return-value]


def set_compute_preference(preference: str) -> ComputePreference:
    """设置进程内偏好，并写回环境变量供后续求解读取。"""
    global _preference_override, _cached
    value = str(preference or "auto").strip().lower()
    if value not in VALID_PREFERENCES:
        value = "auto"
    _preference_override = value
    os.environ["COMSOL_COMPUTE_PREFERENCE"] = value
    _cached = None
    logger.info("计算偏好已设为: %s", value)
    return value  # type: ignore[return-value]


def should_attempt_gpu() -> bool:
    """按用户偏好决定是否尝试启用 HardwareAcceleration。"""
    pref = get_compute_preference()
    if pref == "cpu":
        return False
    backend = detect_compute_backend()
    if not backend.gpu_available:
        return False
    # auto / gpu：有卡就尝试；不支持的物理场会自动回落 CPU
    return True


def _run_nvidia_smi() -> tuple[bool, str, str]:
    """返回 (available, gpu_name, raw_note)。"""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False, "", "未找到 nvidia-smi"
    try:
        proc = subprocess.run(
            [
                smi,
                "--query-gpu=name,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0:
            return False, "", (proc.stderr or proc.stdout or "nvidia-smi 失败").strip()[:200]
        line = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""
        parts = [p.strip() for p in line.split(",")]
        name = parts[0] if parts else "NVIDIA GPU"
        return True, name, line
    except Exception as exc:
        return False, "", str(exc)[:200]


def detect_compute_backend(*, force_refresh: bool = False) -> ComputeBackendInfo:
    """探测本机 GPU；默认缓存结果。"""
    global _cached
    if _cached is not None and not force_refresh:
        return _cached

    pref = get_compute_preference()
    gpu_ok, gpu_name, note = _run_nvidia_smi()
    if pref == "cpu":
        info = ComputeBackendInfo(
            mode="cpu",
            label="仅 CPU（用户指定）",
            detail="已按偏好强制使用 CPU 多核，不会尝试 GPU HardwareAcceleration。",
            gpu_available=gpu_ok,
            gpu_name=gpu_name if gpu_ok else "",
            cuda_available=gpu_ok,
            comsol_gpu_applicable=False,
            preference=pref,
        )
    elif gpu_ok:
        label = (
            "优先 GPU（有卡则尝试）"
            if pref == "gpu"
            else "GPU 待命 · CPU 计算"
        )
        info = ComputeBackendInfo(
            mode="gpu_standby",
            label=label,
            detail=(
                f"已检测到 {gpu_name or 'NVIDIA GPU'}。"
                "COMSOL 6.3 仅对部分求解（如时间显式声学 dG）启用 GPU；"
                "固体力学/传热等常规任务仍使用 CPU 多核。"
                + (" 当前偏好：优先尝试 GPU。" if pref == "gpu" else " 当前偏好：自动。")
            ),
            gpu_available=True,
            gpu_name=gpu_name or "NVIDIA GPU",
            cuda_available=True,
            comsol_gpu_applicable=False,
            preference=pref,
        )
    else:
        info = ComputeBackendInfo(
            mode="cpu",
            label="CPU 计算",
            detail=f"未检测到可用 NVIDIA GPU（{note or '仅使用 CPU 多核'}）。",
            gpu_available=False,
            gpu_name="",
            cuda_available=False,
            comsol_gpu_applicable=False,
            preference=pref,
        )
    _cached = info
    logger.info(
        "计算后端探测: mode=%s gpu=%s pref=%s",
        info.mode,
        info.gpu_name or "无",
        pref,
    )
    return info


def mark_solve_backend(
    *,
    gpu_active: bool,
    applicable: bool = False,
    reason: str = "",
) -> ComputeBackendInfo:
    """根据本次求解是否真正启用 GPU，更新对外状态。"""
    base = detect_compute_backend()
    pref = get_compute_preference()
    if gpu_active:
        info = ComputeBackendInfo(
            mode="gpu",
            label="GPU 计算",
            detail=reason
            or f"本次求解已启用 HardwareAcceleration（{base.gpu_name or 'GPU'}）。",
            gpu_available=base.gpu_available,
            gpu_name=base.gpu_name,
            cuda_available=base.cuda_available,
            comsol_gpu_applicable=True,
            preference=pref,
        )
    elif pref == "cpu":
        info = ComputeBackendInfo(
            mode="cpu",
            label="仅 CPU（用户指定）",
            detail=reason or "用户选择仅 CPU，已跳过 GPU。",
            gpu_available=base.gpu_available,
            gpu_name=base.gpu_name,
            cuda_available=base.cuda_available,
            comsol_gpu_applicable=False,
            preference=pref,
        )
    elif base.gpu_available:
        info = ComputeBackendInfo(
            mode="gpu_standby",
            label="GPU 待命 · CPU 计算",
            detail=reason
            or (
                f"已检测到 {base.gpu_name}，但本任务物理场/求解器不在 COMSOL GPU 加速范围内，"
                "使用 CPU 多核求解。"
            ),
            gpu_available=True,
            gpu_name=base.gpu_name,
            cuda_available=base.cuda_available,
            comsol_gpu_applicable=applicable,
            preference=pref,
        )
    else:
        info = ComputeBackendInfo(
            mode="cpu",
            label="CPU 计算",
            detail=reason or base.detail,
            gpu_available=False,
            gpu_name="",
            cuda_available=False,
            comsol_gpu_applicable=False,
            preference=pref,
        )
    global _cached
    _cached = info
    return info
