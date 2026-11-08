"""可选 MPh 后端（https://github.com/MPh-py/MPh）。

用途：在现有 JavaAPIController 建模主链路之外，提供 Pythonic 的
load / 参数 / 求解验收 / evaluate / export。不替代几何/材料/物理场搭建。

依赖为可选：`uv sync --extra mph` 或 `pip install MPh`。
未安装或 JVM/会话冲突时，调用方应回退到 JavaAPIController。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from agent.utils.logger import get_logger

logger = get_logger(__name__)

Number = Union[int, float]


def mph_backend_mode() -> str:
    """auto | on | off，来自 Settings.mph_backend / 环境变量 MPH_BACKEND。"""
    raw = ""
    try:
        from agent.utils.config import get_settings

        raw = str(getattr(get_settings(), "mph_backend", "") or "").strip().lower()
    except Exception:
        raw = ""
    if not raw:
        raw = (os.getenv("MPH_BACKEND") or "auto").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return "on"
    if raw in ("0", "false", "no", "off"):
        return "off"
    return "auto"


def is_mph_installed() -> bool:
    try:
        import mph  # noqa: F401

        return True
    except Exception:
        return False


def should_use_mph(*, force: Optional[bool] = None) -> bool:
    """是否尝试走 MPh。force=True/False 可覆盖配置。"""
    if force is True:
        return is_mph_installed()
    if force is False:
        return False
    mode = mph_backend_mode()
    if mode == "off":
        return False
    if mode == "on":
        if not is_mph_installed():
            logger.warning("MPH_BACKEND=on 但未安装 MPh，请执行: uv sync --extra mph")
            return False
        return True
    # auto
    return is_mph_installed()


def mph_status() -> Dict[str, Any]:
    return {
        "installed": is_mph_installed(),
        "mode": mph_backend_mode(),
        "active": should_use_mph(),
        "package": "MPh",
        "repo": "https://github.com/MPh-py/MPh",
    }


@contextmanager
def _mph_model(model_path: str) -> Iterator[Any]:
    """加载 .mph 为 MPh Model；退出时尽量保存/清理引用。

    注意：进程内通常只能有一个 COMSOL client。若本项目已通过 jpype
    启动 JVM，MPh 可能复用或失败——失败时向上抛出，由调用方回退。
    """
    path = Path(model_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"模型不存在: {path}")
    import mph

    client = None
    model = None
    try:
        # mph.start() 返回 Client；已有会话时库内部多为单例
        client = mph.start(cores=1)
        model = client.load(str(path))
        yield model
    finally:
        # 只卸掉本次加载的模型，避免多次调用后会话里模型堆积。
        # 不用 client.clear() / disconnect()：与主链路 JPype 共享同一 COMSOL 会话时会伤到 JavaAPIController。
        try:
            if client is not None and model is not None:
                remover = getattr(client, "remove", None)
                if callable(remover):
                    remover(model)
        except Exception as e:
            logger.debug("MPh 释放模型失败（可忽略）: %s", e)
        model = None
        client = None


def set_parameters(
    model_path: str,
    parameters: Dict[str, Any],
    *,
    save_path: Optional[str] = None,
) -> Dict[str, Any]:
    """批量设置全局参数。parameters: {name: value}，value 可为数字或 COMSOL 字符串。"""
    if not parameters:
        return {"status": "error", "message": "parameters 为空", "backend": "mph"}
    try:
        with _mph_model(model_path) as model:
            applied: Dict[str, Any] = {}
            for name, value in parameters.items():
                key = str(name).strip()
                if not key:
                    continue
                model.parameter(key, value)
                applied[key] = value
            out = save_path or model_path
            model.save(out)
            return {
                "status": "success",
                "message": f"已用 MPh 写入 {len(applied)} 个参数",
                "backend": "mph",
                "parameters": applied,
                "saved_path": str(Path(out).resolve()),
            }
    except Exception as e:
        logger.warning("MPh set_parameters 失败: %s", e)
        return {"status": "error", "message": f"MPh set_parameters 失败: {e}", "backend": "mph"}


def solve_model(
    model_path: str,
    *,
    study: Optional[str] = None,
    save_path: Optional[str] = None,
) -> Dict[str, Any]:
    """用 MPh 触发求解（适合已建好的模型验收/重算）。"""
    try:
        with _mph_model(model_path) as model:
            if study:
                model.solve(study)
            else:
                model.solve()
            out = save_path or model_path
            model.save(out)
            return {
                "status": "success",
                "message": "MPh 求解完成",
                "backend": "mph",
                "saved_path": str(Path(out).resolve()),
                "study": study,
            }
    except Exception as e:
        logger.warning("MPh solve 失败: %s", e)
        return {"status": "error", "message": f"MPh solve 失败: {e}", "backend": "mph"}


def evaluate(
    model_path: str,
    expression: str,
    *,
    dataset: Optional[str] = None,
    unit: Optional[str] = None,
) -> Dict[str, Any]:
    """求值表达式（如 maxop1(T)、intop1(T)）。用于求解后物理量验收。"""
    expr = (expression or "").strip()
    if not expr:
        return {"status": "error", "message": "expression 为空", "backend": "mph"}
    try:
        with _mph_model(model_path) as model:
            kwargs: Dict[str, Any] = {}
            if dataset:
                kwargs["dataset"] = dataset
            if unit:
                kwargs["unit"] = unit
            # MPh Model.evaluate 签名随版本略有差异，尽量兼容
            try:
                value = model.evaluate(expr, **kwargs) if kwargs else model.evaluate(expr)
            except TypeError:
                value = model.evaluate(expr)
            # numpy / list / scalar
            serialized: Any
            try:
                import numpy as np  # type: ignore

                if isinstance(value, np.ndarray):
                    serialized = value.tolist()
                else:
                    serialized = value
            except Exception:
                serialized = value
            return {
                "status": "success",
                "message": f"MPh evaluate: {expr}",
                "backend": "mph",
                "expression": expr,
                "value": serialized,
            }
    except Exception as e:
        logger.warning("MPh evaluate 失败: %s", e)
        return {"status": "error", "message": f"MPh evaluate 失败: {e}", "backend": "mph"}


def export_data(
    model_path: str,
    out_path: str,
    *,
    node: Optional[str] = None,
    dataset: Optional[str] = None,
) -> Dict[str, Any]:
    """导出数据/表格到文件（CSV 等）。优先 node，其次 dataset 标签。"""
    target = (node or dataset or "").strip()
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _mph_model(model_path) as model:
            if target:
                # MPh: model.export(node, file)
                model.export(target, str(out))
            else:
                # 尝试常见结果导出节点
                last_err: Optional[Exception] = None
                for guess in ("export1", "tbl1", "pg1"):
                    try:
                        model.export(guess, str(out))
                        target = guess
                        last_err = None
                        break
                    except Exception as exc:
                        last_err = exc
                if last_err and not target:
                    raise last_err
            return {
                "status": "success",
                "message": f"MPh 已导出到 {out.name}",
                "backend": "mph",
                "path": str(out),
                "node": target or None,
            }
    except Exception as e:
        logger.warning("MPh export 失败: %s", e)
        return {"status": "error", "message": f"MPh export 失败: {e}", "backend": "mph"}


def list_parameters(model_path: str) -> Dict[str, Any]:
    """读取模型全局参数表，便于 Agent/调试对齐参数化扫描。"""
    try:
        with _mph_model(model_path) as model:
            params = {}
            try:
                raw = model.parameters()
                if isinstance(raw, dict):
                    params = {str(k): str(v) for k, v in raw.items()}
                else:
                    params = {"_raw": str(raw)}
            except Exception:
                # 旧版可能是 names() + parameter(name)
                names: List[str] = []
                try:
                    names = list(model.parameters())  # type: ignore[arg-type]
                except Exception:
                    pass
                for n in names:
                    try:
                        params[str(n)] = str(model.parameter(n))
                    except Exception:
                        params[str(n)] = ""
            return {
                "status": "success",
                "message": f"读取到 {len(params)} 个参数",
                "backend": "mph",
                "parameters": params,
            }
    except Exception as e:
        logger.warning("MPh list_parameters 失败: %s", e)
        return {"status": "error", "message": f"MPh list_parameters 失败: {e}", "backend": "mph"}


def verify_after_solve(
    model_path: str,
    *,
    expressions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """求解后轻量验收：默认尝试若干常见温度/位移标量。"""
    exprs = expressions or [
        "maxop1(T)",
        "minop1(T)",
        "T",
    ]
    results: List[Dict[str, Any]] = []
    for expr in exprs:
        r = evaluate(model_path, expr)
        results.append(r)
        if r.get("status") == "success":
            return {
                "status": "success",
                "message": f"求解验收通过（{expr}）",
                "backend": "mph",
                "checks": results,
                "value": r.get("value"),
                "expression": expr,
            }
    return {
        "status": "warning",
        "message": "MPh 未能对默认表达式求值（可能缺少 maxop/对应物理量）",
        "backend": "mph",
        "checks": results,
    }
