"""单例型 Agent：Q&A、Summary、Analysis 等。"""
from agent.agents.analysis_agent import AnalysisAgent
from agent.agents.qa_agent import QAAgent
from agent.agents.summary_agent import SummaryAgent

__all__ = ["AnalysisAgent", "QAAgent", "SummaryAgent"]
