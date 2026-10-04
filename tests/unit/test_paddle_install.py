import pytest

from edi_reference.application.paddle_install import build_paddle_install_plan


def test_cpu_plan_isolated_from_gpu_package() -> None:
    plan = build_paddle_install_plan(python_executable="python", profile="cpu")

    commands = [step.argv for step in plan.steps]
    assert any("paddlepaddle==3.2.0" in command for command in commands)
    assert all("paddlepaddle-gpu==3.2.0" not in command for command in commands)
    assert any("paddleocr[doc-parser]>=3.7,<3.8" in command for command in commands)


def test_modern_nvidia_driver_selects_cu126() -> None:
    plan = build_paddle_install_plan(
        python_executable="python",
        profile="nvidia",
        nvidia_driver_version=(610, 62, 0),
    )

    engine = next(step for step in plan.steps if step.name == "install-engine")
    assert engine.argv[-1].endswith("/cu126/")


def test_compatible_legacy_nvidia_driver_selects_cu118() -> None:
    plan = build_paddle_install_plan(
        python_executable="python",
        profile="nvidia",
        nvidia_driver_version=(535, 10, 0),
    )

    engine = next(step for step in plan.steps if step.name == "install-engine")
    assert engine.argv[-1].endswith("/cu118/")


def test_reject_driver_below_windows_cu118_floor() -> None:
    with pytest.raises(ValueError, match="NVIDIA_DRIVER_TOO_OLD"):
        build_paddle_install_plan(
            python_executable="python",
            profile="nvidia",
            nvidia_driver_version=(451, 99, 0),
        )
