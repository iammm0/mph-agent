"""ReAct 架构测试"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agent.react.action_executor import ActionExecutor
from agent.react.iteration_controller import IterationController
from agent.react.observer import Observer
from agent.react.react_agent import ReActAgent
from agent.react.reasoning_engine import ReasoningEngine
from agent.run.actions import do_config_save
from agent.schemas.task import ExecutionStep, Observation, ReActTaskPlan


class TestReasoningEngine:
    """测试推理引擎"""

    def test_understand_requirement(self):
        """测试需求理解"""
        # Mock LLM
        mock_llm = Mock()
        mock_llm.call.return_value = (
            '{"task_type": "geometry", "required_steps": ["create_geometry"], "parameters": {}}'
        )

        engine = ReasoningEngine(mock_llm)
        with patch("agent.react.reasoning_engine.get_skill_injector") as mock_get_injector:
            mock_injector = Mock()
            mock_injector.inject_into_prompt.side_effect = lambda _query, prompt: prompt
            mock_get_injector.return_value = mock_injector
            result = engine.understand_requirement("创建一个矩形")

        assert "task_type" in result
        assert result["task_type"] == "geometry"

    def test_plan_execution_path(self):
        """测试执行路径规划"""
        mock_llm = Mock()
        engine = ReasoningEngine(mock_llm)

        understanding = {
            "task_type": "full",
            "required_steps": ["create_geometry", "add_physics", "solve"],
        }

        path = engine.plan_execution_path(understanding)
        actions = [step.action for step in path]

        assert len(path) == 3
        assert actions == ["create_geometry", "add_physics", "solve"]

    def test_plan_execution_path_with_global_definitions(self):
        """有全局参数时才插入 define_globals。"""
        mock_llm = Mock()
        engine = ReasoningEngine(mock_llm)

        understanding = {
            "task_type": "full",
            "required_steps": ["create_geometry", "add_physics", "solve"],
            "parameters": {
                "global_definitions": [{"name": "L", "value": "0.1[m]"}],
            },
        }

        path = engine.plan_execution_path(understanding)
        actions = [step.action for step in path]

        assert len(path) == 4
        assert actions == ["create_geometry", "define_globals", "add_physics", "solve"]

    def test_understand_and_plan_retains_global_definitions_in_fallback(self):
        """回退到 LLM 单次规划时，global_definitions 也要进入执行路径和计划。"""
        mock_llm = Mock()
        mock_llm.call.return_value = (
            '{"task_type":"full","required_steps":["create_geometry","add_physics","solve"],'
            '"parameters":{"global_definitions":[{"name":"L","value":"0.1[m]"}]}}'
        )
        engine = ReasoningEngine(mock_llm, use_planner_orchestrator=False)

        with patch("agent.react.reasoning_engine.get_skill_injector") as mock_get_injector:
            mock_injector = Mock()
            mock_injector.inject_into_prompt.side_effect = lambda _query, prompt: prompt
            mock_get_injector.return_value = mock_injector

            plan = engine.understand_and_plan("创建一个参数化模型", "m_with_globals")

        assert [step.action for step in plan.execution_path] == [
            "create_geometry",
            "define_globals",
            "add_physics",
            "solve",
        ]
        assert len(plan.global_definitions) == 1
        assert plan.global_definitions[0].name == "L"
        assert plan.global_definitions[0].value == "0.1[m]"

    def test_plan_execution_path_new_actions(self):
        """规划路径支持 import_geometry / create_selection / export_results。"""
        mock_llm = Mock()
        engine = ReasoningEngine(mock_llm)
        understanding = {
            "task_type": "full",
            "required_steps": [
                "create_geometry",
                "import_geometry",
                "create_selection",
                "export_results",
            ],
            "parameters": {
                "geometry_input": "矩形",
                "file_path": "/data/part.step",
                "tag": "sel1",
                "out_path": "/out/result.png",
            },
        }
        path = engine.plan_execution_path(understanding)
        actions = [s.action for s in path]
        assert "import_geometry" in actions
        assert "create_selection" in actions
        assert "export_results" in actions
        step_types = [s.step_type for s in path]
        assert "geometry_io" in step_types
        assert "selection" in step_types
        assert "postprocess" in step_types

    def test_plan_reasoning_path(self):
        """测试推理路径规划"""
        mock_llm = Mock()
        engine = ReasoningEngine(mock_llm)

        execution_path = [
            ExecutionStep(
                step_id="step_1", step_type="geometry", action="create_geometry", status="pending"
            )
        ]

        reasoning_path = engine.plan_reasoning_path(execution_path)

        assert len(reasoning_path) >= 1
        assert reasoning_path[0].checkpoint_type == "validation"


class TestActionExecutor:
    """测试行动执行器"""

    def test_execute_unknown_action_returns_error(self):
        """未知 action 返回错误；import_geometry / create_selection / export_results 有对应 handler。"""
        executor = ActionExecutor()
        plan = Mock()
        plan.model_path = None
        plan.output_dir = None
        step = ExecutionStep(
            step_id="s1", step_type="geometry", action="unknown_action", status="pending"
        )
        result = executor.execute(plan, step, {"parameters": {}})
        assert result.get("status") == "error"
        assert "未知" in result.get("message", "")

    def test_execute_import_geometry_uses_local_java_api_by_default(self):
        """默认关闭 claw-code 时，import_geometry 走本地 JavaAPIController。"""
        executor = ActionExecutor()
        executor.settings.claw_code_enabled = False
        plan = ReActTaskPlan(task_id="t1", model_name="m1", user_input="u1")
        plan.model_path = "/tmp/model.mph"
        step = ExecutionStep(
            step_id="s1",
            step_type="geometry_io",
            action="import_geometry",
            parameters={"file_path": "/x.step"},
            status="pending",
        )
        dispatcher = Mock()
        executor._clawcode_dispatcher = dispatcher
        controller = Mock()
        controller.import_geometry.return_value = {
            "status": "success",
            "message": "ok",
            "saved_path": "/tmp/imported.mph",
        }
        executor._java_api_controller = controller

        result = executor.execute(plan, step, {"parameters": {"file_path": "/x.step"}})
        assert result.get("status") == "success"
        assert plan.model_path == "/tmp/imported.mph"
        controller.import_geometry.assert_called_once()
        dispatcher.dispatch.assert_not_called()

    def test_execute_export_results_uses_local_java_api_by_default(self):
        """默认关闭 claw-code 时，export_results 走本地 JavaAPIController。"""
        executor = ActionExecutor()
        executor.settings.claw_code_enabled = False
        plan = ReActTaskPlan(task_id="t2", model_name="m2", user_input="u2")
        plan.model_path = "/tmp/model.mph"
        step = ExecutionStep(
            step_id="s1",
            step_type="postprocess",
            action="export_results",
            parameters={"out_path": "/out.png"},
            status="pending",
        )
        dispatcher = Mock()
        executor._clawcode_dispatcher = dispatcher
        controller = Mock()
        controller.export_plot_image.return_value = {
            "status": "success",
            "message": "exported",
        }
        executor._java_api_controller = controller

        result = executor.execute(plan, step, {"parameters": {"out_path": "/out.png"}})
        assert result.get("status") == "success"
        assert result.get("path") == "/out.png"
        controller.export_plot_image.assert_called_once()
        dispatcher.dispatch.assert_not_called()

    def test_execute_import_geometry_delegates_to_clawcode_when_enabled(self):
        """CLAW_CODE_ENABLED=1 时，import_geometry 交给 dispatcher。"""
        executor = ActionExecutor()
        executor.settings.claw_code_enabled = True
        plan = ReActTaskPlan(task_id="t1", model_name="m1", user_input="u1")
        step = ExecutionStep(
            step_id="s1",
            step_type="geometry_io",
            action="import_geometry",
            parameters={"file_path": "/x.step"},
            status="pending",
        )
        dispatcher = Mock()
        dispatcher.dispatch.return_value = {
            "status": "success",
            "message": "ok",
            "model_path": "/tmp/imported.mph",
        }
        executor._clawcode_dispatcher = dispatcher

        result = executor.execute(plan, step, {"parameters": {"file_path": "/x.step"}})
        assert result.get("status") == "success"
        assert plan.model_path == "/tmp/imported.mph"
        dispatcher.dispatch.assert_called_once()

    def test_execute_export_results_delegates_to_clawcode_when_enabled(self):
        """CLAW_CODE_ENABLED=1 时，export_results 交给 dispatcher。"""
        executor = ActionExecutor()
        executor.settings.claw_code_enabled = True
        plan = ReActTaskPlan(task_id="t2", model_name="m2", user_input="u2")
        step = ExecutionStep(
            step_id="s1",
            step_type="postprocess",
            action="export_results",
            parameters={"out_path": "/out.png"},
            status="pending",
        )
        dispatcher = Mock()
        dispatcher.dispatch.return_value = {
            "status": "success",
            "message": "exported",
            "artifacts": ["/out.png"],
        }
        executor._clawcode_dispatcher = dispatcher

        result = executor.execute(plan, step, {"parameters": {"out_path": "/out.png"}})
        assert result.get("status") == "success"
        assert result.get("artifacts") == ["/out.png"]
        dispatcher.dispatch.assert_called_once()

    def test_execute_clawcode_error_is_collected(self):
        """opt-in 委托失败时收集结构化错误。"""
        error_collector = Mock()
        executor = ActionExecutor(error_collector=error_collector)
        executor.settings.claw_code_enabled = True
        plan = ReActTaskPlan(task_id="t3", model_name="m3", user_input="u3")
        step = ExecutionStep(
            step_id="s1",
            step_type="geometry_io",
            action="import_geometry",
            status="pending",
        )
        dispatcher = Mock()
        dispatcher.dispatch.return_value = {"status": "error", "message": "failed"}
        executor._clawcode_dispatcher = dispatcher

        result = executor.execute(plan, step, {"parameters": {"file_path": "/x.step"}})

        assert result["status"] == "error"
        error_collector.submit.assert_called_once()
        assert error_collector.submit.call_args.args[1] == "clawcode_dispatch_error"

    def test_execute_define_globals_validation_failed(self):
        """define_globals 参数校验失败时返回结构化错误并要求回到规划澄清。"""
        executor = ActionExecutor()
        plan = ReActTaskPlan(
            task_id="g1",
            model_name="m1",
            user_input="u1",
            execution_path=[],
        )
        step = ExecutionStep(
            step_id="s_global_1",
            step_type="global",
            action="define_globals",
            status="pending",
        )

        result = executor.execute_define_globals(
            plan,
            step,
            {
                "parameters": {
                    "global_definitions": [
                        {"name": "L", "value": "0.1[m]"},
                        {"name": "L", "value": "0.2[m]"},
                    ]
                }
            },
        )

        assert result["status"] == "error"
        assert result["error_code"] == "define_globals_validation_failed"
        assert result["needs_planning_clarification"] is True
        assert isinstance(result.get("details"), list)

    def test_execute_define_globals_success_with_mocked_controller(self):
        """define_globals 成功分支会调用 controller 并回写 plan.global_definitions。"""
        executor = ActionExecutor()
        plan = ReActTaskPlan(
            task_id="g2",
            model_name="m2",
            user_input="u2",
            execution_path=[],
            model_path="E:/tmp/in.mph",
        )
        step = ExecutionStep(
            step_id="s_global_2",
            step_type="global",
            action="define_globals",
            status="pending",
        )

        mocked_controller = Mock()
        mocked_controller.define_global_parameters.return_value = {
            "status": "success",
            "saved_path": "E:/tmp/out_global.mph",
        }
        executor._java_api_controller = mocked_controller

        result = executor.execute_define_globals(
            plan,
            step,
            {"parameters": {"global_definitions": [{"name": "L", "value": "0.1[m]"}]}},
        )

        assert result["status"] == "success"
        assert len(plan.global_definitions) == 1
        mocked_controller.define_global_parameters.assert_called_once()

    def test_execute_define_globals_empty_is_noop(self):
        """未提供全局参数时，define_globals 应直接跳过而不是报错。"""
        executor = ActionExecutor()
        plan = ReActTaskPlan(
            task_id="g3",
            model_name="m3",
            user_input="u3",
            execution_path=[],
            model_path="E:/tmp/in.mph",
        )
        step = ExecutionStep(
            step_id="s_global_3",
            step_type="global",
            action="define_globals",
            status="pending",
        )

        mocked_controller = Mock()
        executor._java_api_controller = mocked_controller

        result = executor.execute_define_globals(
            plan,
            step,
            {"parameters": {"global_definitions": []}},
        )

        assert result["status"] == "success"
        assert result["global_definitions"] == []
        mocked_controller.define_global_parameters.assert_not_called()

    def test_execute_geometry(self):
        """测试几何执行"""
        executor = ActionExecutor()

        # Mock plan
        plan = Mock()
        plan.user_input = "创建一个矩形，宽1米，高0.5米"
        plan.model_name = "test_model"
        plan.model_path = None
        plan.geometry_plan = None

        step = ExecutionStep(
            step_id="step_1", step_type="geometry", action="create_geometry", status="pending"
        )

        thought = {"action": "create_geometry", "parameters": {}}

        # Mock GeometryAgent
        with patch("agent.react.action_executor.GeometryAgent") as mock_agent_class:
            mock_agent = Mock()
            mock_plan = Mock()
            mock_plan.shapes = [Mock()]
            mock_plan.model_name = "test_model"
            mock_plan.model_dump.return_value = {}
            mock_agent.parse.return_value = mock_plan
            mock_agent_class.return_value = mock_agent

            # Mock COMSOLRunner
            with patch("agent.react.action_executor.COMSOLRunner") as mock_runner_class:
                mock_runner = Mock()
                mock_path = Path("test.mph")
                mock_path.touch()
                mock_runner.create_model_from_plan.return_value = mock_path
                mock_runner_class.return_value = mock_runner

                result = executor.execute_geometry(plan, step, thought)

                assert result["status"] == "success"
                assert "model_path" in result


class TestConfigSync:
    """测试桌面端配置与内置 claw-code 后端保持一致。"""

    def test_config_save_sets_claw_code_openai_compatible_defaults(self, tmp_path, monkeypatch):
        from agent.utils import config as config_mod

        monkeypatch.setattr(config_mod, "get_project_root", lambda: tmp_path)
        monkeypatch.setattr(config_mod, "reload_settings", lambda: None)

        ok, message = do_config_save(
            {
                "LLM_BACKEND": "openai-compatible",
                "OPENAI_COMPATIBLE_MODEL": "gpt-test",
                "OPENAI_COMPATIBLE_BASE_URL": "https://example.test/v1",
                "OPENAI_COMPATIBLE_API_KEY": "sk-test",
            }
        )

        assert ok is True, message
        env_text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "CLAW_CODE_ENABLED=" not in env_text
        assert "CLAW_CODE_MODEL=gpt-test" in env_text
        assert "CLAW_CODE_BASE_URL=https://example.test/v1" in env_text
        assert "CLAW_CODE_API_KEY=sk-test" in env_text


class TestObserver:
    """测试观察器"""

    def test_observe_geometry_success(self):
        """测试几何观察（成功）"""
        observer = Observer()

        plan = Mock()
        plan.model_path = "test.mph"

        step = ExecutionStep(
            step_id="step_1", step_type="geometry", action="create_geometry", status="completed"
        )

        result = {"status": "success", "model_path": "test.mph"}

        # 创建临时文件
        test_path = Path("test.mph")
        test_path.touch()

        try:
            observation = observer.observe_geometry(plan, step, result)

            assert observation.status == "success"
            assert "几何构建成功" in observation.message
        finally:
            if test_path.exists():
                test_path.unlink()

    def test_observe_geometry_error(self):
        """测试几何观察（错误）"""
        observer = Observer()

        plan = Mock()
        plan.model_path = None

        step = ExecutionStep(
            step_id="step_1", step_type="geometry", action="create_geometry", status="failed"
        )

        result = {"status": "error", "message": "创建失败"}

        observation = observer.observe_geometry(plan, step, result)

        assert observation.status == "error"
        assert "失败" in observation.message


class TestIterationController:
    """测试迭代控制器"""

    def test_should_iterate_on_error(self):
        """测试错误时应该迭代"""
        mock_llm = Mock()
        controller = IterationController(mock_llm)

        plan = Mock()
        plan.execution_path = []
        plan.iterations = []
        plan.observations = []

        observation = Observation(
            observation_id="obs_1", step_id="step_1", status="error", message="执行失败"
        )

        assert controller.should_iterate(plan, observation) is True

    def test_should_not_iterate_on_success(self):
        """测试成功时不应该迭代"""
        mock_llm = Mock()
        controller = IterationController(mock_llm)

        plan = Mock()
        plan.execution_path = [Mock(status="completed")]
        plan.iterations = []
        plan.observations = []

        observation = Observation(
            observation_id="obs_1", step_id="step_1", status="success", message="执行成功"
        )

        assert controller.should_iterate(plan, observation) is False

    def test_generate_feedback(self):
        """测试生成反馈"""
        mock_llm = Mock()
        controller = IterationController(mock_llm)

        plan = Mock()
        plan.get_current_step.return_value = Mock(
            action="create_geometry",
            step_type="geometry",
            status="failed",
            result={"error": "创建失败"},
        )
        plan.execution_path = [Mock(status="completed"), Mock(status="pending")]
        plan.observations = []

        observation = Observation(
            observation_id="obs_1", step_id="step_1", status="error", message="执行失败"
        )

        feedback = controller.generate_feedback(plan, observation)

        assert "观察结果" in feedback
        assert "当前步骤" in feedback
        assert "进度" in feedback

    def test_update_plan_stops_retry_when_step_needs_planning_clarification(self):
        """需要规划澄清的错误应直接终止重试并建议重新编排。"""
        controller = IterationController(Mock())
        step = ExecutionStep(
            step_id="step_global_1",
            step_type="global",
            action="define_globals",
            parameters={},
            status="failed",
            result={
                "status": "error",
                "message": "global definitions are empty",
                "needs_planning_clarification": True,
            },
        )
        plan = ReActTaskPlan(
            task_id="t_iter_1",
            model_name="m_iter_1",
            user_input="u_iter_1",
            execution_path=[step],
        )
        observation = Observation(
            observation_id="obs_iter_1",
            step_id="step_global_1",
            status="error",
            message="global definitions are empty",
        )

        updated = controller.update_plan(plan, observation)

        assert updated.status == "failed"
        assert updated.error is not None
        assert updated.error.startswith("[REORCHESTRATE]")


class TestReActAgent:
    """测试 ReAct Agent"""

    @pytest.mark.skip(reason="需要完整的 COMSOL 环境")
    def test_run_basic(self):
        """测试基本运行流程"""
        # 这个测试需要实际的 COMSOL 环境，所以跳过
        pass

    def test_think(self):
        """测试思考方法"""
        mock_llm = Mock()

        with patch("agent.react.react_agent.ReasoningEngine") as mock_engine_class:
            mock_engine = Mock()
            mock_engine.reason.return_value = {
                "action": "create_geometry",
                "reasoning": "需要创建几何",
                "parameters": {},
            }
            mock_engine_class.return_value = mock_engine

            agent = ReActAgent(llm=mock_llm)
            agent.reasoning_engine = mock_engine

            plan = Mock()
            plan.get_current_step.return_value = None
            plan.execution_path = []
            plan.current_step_index = 0
            plan.status = "planning"

            thought = agent.think(plan)

            assert "action" in thought
            assert thought["action"] == "create_geometry"

    def test_act_binds_thought_action_to_current_step(self):
        """回归：think 输出 action 与 act 执行步强绑定。"""
        agent = ReActAgent(llm=Mock())
        plan = ReActTaskPlan(
            task_id="t1",
            model_name="m1",
            user_input="u1",
            execution_path=[
                ExecutionStep(
                    step_id="step_1",
                    step_type="geometry",
                    action="create_geometry",
                    parameters={},
                    status="pending",
                )
            ],
        )

        # 模拟 think 给出不同 action，act 必须覆盖当前步骤 action
        thought = {"action": "add_material", "parameters": {"material_input": "steel"}}
        agent.action_executor = Mock()
        agent.action_executor.execute.return_value = {"status": "success", "message": "ok"}

        result = agent.act(plan, thought)

        assert result["status"] == "success"
        assert plan.execution_path[0].action == "add_material"
        assert plan.execution_path[0].parameters.get("material_input") == "steel"
        assert plan.execution_path[0].status == "completed"

    def test_observe_binds_to_executed_step_not_shifted_step(self):
        """回归：observe 绑定本轮执行步，避免索引推进后错步观察。"""
        agent = ReActAgent(llm=Mock())
        step1 = ExecutionStep(
            step_id="step_1",
            step_type="geometry",
            action="create_geometry",
            parameters={},
            status="pending",
        )
        step2 = ExecutionStep(
            step_id="step_2",
            step_type="material",
            action="add_material",
            parameters={},
            status="pending",
        )
        plan = ReActTaskPlan(
            task_id="t2",
            model_name="m2",
            user_input="u2",
            execution_path=[step1, step2],
            current_step_index=1,  # 模拟已推进到下一步
        )

        expected = Observation(
            observation_id="obs_1",
            step_id="step_1",
            status="success",
            message="ok",
        )
        agent.observer = Mock()
        agent.observer.observe.return_value = expected

        obs = agent.observe(plan, {"status": "success"}, executed_step=step1)

        assert obs.step_id == "step_1"
        agent.observer.observe.assert_called_once()
        called_plan, called_step, called_result = agent.observer.observe.call_args[0]
        assert called_plan is plan
        assert called_step.step_id == "step_1"
        assert called_result["status"] == "success"

    def test_reasoning_engine_empty_execution_path_not_complete(self):
        """回归：空 execution_path 时不能误判 complete。"""
        engine = ReasoningEngine(Mock())
        plan = ReActTaskPlan(
            task_id="t3",
            model_name="m3",
            user_input="u3",
            execution_path=[],
        )

        thought = engine.reason(plan)

        assert thought["action"] == "replan"
        assert "执行路径为空" in thought["reasoning"]

    def test_is_all_steps_complete_guard_empty_path(self):
        """回归：_is_all_steps_complete 对空路径返回 False。"""
        agent = ReActAgent(llm=Mock())
        plan = ReActTaskPlan(
            task_id="t4",
            model_name="m4",
            user_input="u4",
            execution_path=[],
        )
        assert agent._is_all_steps_complete(plan) is False

    def test_run_end_success_and_message_clawcode_trusts_last_observation(self, monkeypatch):
        """启用 claw-code 时，以外层末次成功观察为准，不再套用「达到最大调整次数」。"""
        agent = ReActAgent(llm=Mock())
        monkeypatch.setattr(
            "agent.react.react_agent.get_settings",
            lambda: SimpleNamespace(claw_code_enabled=True),
        )
        plan = ReActTaskPlan(
            task_id="t_cc",
            model_name="m_cc",
            user_input="u_cc",
            status="executing",
            observations=[
                Observation(
                    observation_id="o_cc",
                    step_id="s_cc",
                    status="success",
                    message="研究配置成功",
                ),
            ],
        )
        ok, msg = agent._run_end_success_and_message(plan)
        assert ok is True
        assert msg == "研究配置成功"

    def test_run_end_success_and_message_without_clawcode_generic_incomplete(self, monkeypatch):
        """未启用 claw-code 时，非 completed 仍回落到轮次用尽提示。"""
        agent = ReActAgent(llm=Mock())
        agent.max_iterations = 10
        monkeypatch.setattr(
            "agent.react.react_agent.get_settings",
            lambda: SimpleNamespace(claw_code_enabled=False),
        )
        plan = ReActTaskPlan(
            task_id="t_nc",
            model_name="m_nc",
            user_input="u_nc",
            status="executing",
            observations=[
                Observation(
                    observation_id="o_nc",
                    step_id="s_nc",
                    status="success",
                    message="研究配置成功",
                ),
            ],
        )
        ok, msg = agent._run_end_success_and_message(plan)
        assert ok is False
        assert "最大调整次数" in msg

    def test_warning_iteration_threshold_behavior(self):
        """回归：warning 未达阈值不迭代，达到阈值才迭代。"""
        controller = IterationController(Mock())
        step = ExecutionStep(
            step_id="step_1",
            step_type="geometry",
            action="create_geometry",
            parameters={},
            status="warning",
        )
        warn_obs = Observation(
            observation_id="obs_w",
            step_id="step_1",
            status="warning",
            message="w",
        )

        plan_low = ReActTaskPlan(
            task_id="t5",
            model_name="m5",
            user_input="u5",
            execution_path=[step],
            observations=[
                Observation(observation_id="o1", step_id="s1", status="warning", message="w1"),
                Observation(observation_id="o2", step_id="s1", status="warning", message="w2"),
            ],
        )
        plan_high = ReActTaskPlan(
            task_id="t6",
            model_name="m6",
            user_input="u6",
            execution_path=[step],
            observations=[
                Observation(observation_id="o1", step_id="s1", status="warning", message="w1"),
                Observation(observation_id="o2", step_id="s1", status="warning", message="w2"),
                Observation(observation_id="o3", step_id="s1", status="warning", message="w3"),
            ],
        )

        assert controller.should_iterate(plan_low, warn_obs) is False
        assert controller.should_iterate(plan_high, warn_obs) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
