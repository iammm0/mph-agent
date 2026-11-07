"""MPh 可选后端：无安装时应安全降级；API 形状稳定。"""

from agent.executor import mph_backend


def test_mph_status_shape():
    status = mph_backend.mph_status()
    assert "installed" in status
    assert status["mode"] in ("auto", "on", "off")
    assert "active" in status
    assert status["repo"].startswith("https://github.com/")


def test_should_use_mph_force_off():
    assert mph_backend.should_use_mph(force=False) is False


def test_set_parameters_empty():
    result = mph_backend.set_parameters("dummy.mph", {})
    assert result["status"] == "error"
    assert result["backend"] == "mph"


def test_evaluate_empty_expression():
    result = mph_backend.evaluate("dummy.mph", "  ")
    assert result["status"] == "error"
