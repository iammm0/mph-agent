"""ReAct 架构测试"""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from agent.react.react_agent import ReActAgent
from agent.react.reasoning_engine import ReasoningEngine
from agent.react.action_executor import ActionExecutor
from agent.react.observer import Observer
from agent.react.iteration_controller import IterationController
from schemas.task import ExecutionStep, Observation


class TestReasoningEngine:
    """测试推理引擎"""
    
    def test_understand_requirement(self):
        """测试需求理解"""
        # Mock LLM
        mock_llm = Mock()
        mock_llm.call.return_value = '{"task_type": "geometry", "required_steps": ["create_geometry"], "parameters": {}}'
        
        engine = ReasoningEngine(mock_llm)
        result = engine.understand_requirement("创建一个矩形")
        
        assert "task_type" in result
        assert result["task_type"] == "geometry"
    
    def test_plan_execution_path(self):
        """测试执行路径规划"""
        mock_llm = Mock()
        engine = ReasoningEngine(mock_llm)
        
        understanding = {
            "task_type": "full",
            "required_steps": ["create_geometry", "add_physics", "solve"]
        }
        
        path = engine.plan_execution_path(understanding)
        
        assert len(path) == 3
        assert path[0].action == "create_geometry"
        assert path[1].action == "add_physics"
        assert path[2].action == "solve"

    def test_plan_execution_path_new_actions(self):
        """规划路径支持 import_geometry / create_selection / export_results。"""
        mock_llm = Mock()
        engine = ReasoningEngine(mock_llm)
        understanding = {
            "task_type": "full",
            "required_steps": ["create_geometry", "import_geometry", "create_selection", "export_results"],
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
            ExecutionStep(step_id="step_1", step_type="geometry", action="create_geometry", status="pending")
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
        step = ExecutionStep(step_id="s1", step_type="geometry", action="unknown_action", status="pending")
        result = executor.execute(plan, step, {"parameters": {}})
        assert result.get("status") == "error"
        assert "未知" in result.get("message", "")

    def test_execute_import_geometry_without_model_path(self):
        """import_geometry 在无 model_path 时返回明确错误。"""
        executor = ActionExecutor()
        plan = Mock()
        plan.model_path = None
        step = ExecutionStep(
            step_id="s1", step_type="geometry_io", action="import_geometry",
            parameters={"file_path": "/x.step"}, status="pending",
        )
        result = executor.execute(plan, step, {"parameters": {"file_path": "/x.step"}})
        assert result.get("status") == "error"
        assert "模型文件不存在" in result.get("message", "")

    def test_execute_export_results_without_model_path(self):
        """export_results 在无 model_path 时返回明确错误。"""
        executor = ActionExecutor()
        plan = Mock()
        plan.model_path = None
        step = ExecutionStep(
            step_id="s1", step_type="postprocess", action="export_results",
            parameters={"out_path": "/out.png"}, status="pending",
        )
        result = executor.execute(plan, step, {"parameters": {"out_path": "/out.png"}})
        assert result.get("status") == "error"
        assert "模型文件不存在" in result.get("message", "")

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
            step_id="step_1",
            step_type="geometry",
            action="create_geometry",
            status="pending"
        )
        
        thought = {
            "action": "create_geometry",
            "parameters": {}
        }
        
        # Mock GeometryAgent
        with patch('agent.react.action_executor.GeometryAgent') as mock_agent_class:
            mock_agent = Mock()
            mock_plan = Mock()
            mock_plan.shapes = [Mock()]
            mock_plan.model_name = "test_model"
            mock_plan.model_dump.return_value = {}
            mock_agent.parse.return_value = mock_plan
            mock_agent_class.return_value = mock_agent
            
            # Mock COMSOLRunner
            with patch('agent.react.action_executor.COMSOLRunner') as mock_runner_class:
                mock_runner = Mock()
                mock_path = Path("test.mph")
                mock_path.touch()
                mock_runner.create_model_from_plan.return_value = mock_path
                mock_runner_class.return_value = mock_runner
                
                result = executor.execute_geometry(plan, step, thought)
                
                assert result["status"] == "success"
                assert "model_path" in result


class TestObserver:
    """测试观察器"""
    
    def test_observe_geometry_success(self):
        """测试几何观察（成功）"""
        observer = Observer()
        
        plan = Mock()
        plan.model_path = "test.mph"
        
        step = ExecutionStep(
            step_id="step_1",
            step_type="geometry",
            action="create_geometry",
            status="completed"
        )
        
        result = {
            "status": "success",
            "model_path": "test.mph"
        }
        
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
            step_id="step_1",
            step_type="geometry",
            action="create_geometry",
            status="failed"
        )
        
        result = {
            "status": "error",
            "message": "创建失败"
        }
        
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
            observation_id="obs_1",
            step_id="step_1",
            status="error",
            message="执行失败"
        )
        
        assert controller.should_iterate(plan, observation) is True
    
    def test_should_not_iterate_on_success(self):
        """测试成功时不应该迭代"""
        mock_llm = Mock()
        controller = IterationController(mock_llm)
        
        plan = Mock()
        plan.execution_path = [
            Mock(status="completed")
        ]
        plan.iterations = []
        plan.observations = []
        
        observation = Observation(
            observation_id="obs_1",
            step_id="step_1",
            status="success",
            message="执行成功"
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
            result={"error": "创建失败"}
        )
        plan.execution_path = [Mock(status="completed"), Mock(status="pending")]
        plan.observations = []
        
        observation = Observation(
            observation_id="obs_1",
            step_id="step_1",
            status="error",
            message="执行失败"
        )
        
        feedback = controller.generate_feedback(plan, observation)
        
        assert "观察结果" in feedback
        assert "当前步骤" in feedback
        assert "进度" in feedback


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
        
        with patch('agent.react.react_agent.ReasoningEngine') as mock_engine_class:
            mock_engine = Mock()
            mock_engine.reason.return_value = {
                "action": "create_geometry",
                "reasoning": "需要创建几何",
                "parameters": {}
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
