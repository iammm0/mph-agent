"""Schemas - Agent 数据结构定义"""
from schemas.geometry import GeometryShape, GeometryPlan, GeometryOperation
from schemas.material import MaterialProperty, MaterialDefinition, MaterialAssignment, MaterialPlan
from schemas.physics import (
    PhysicsField, PhysicsPlan,
    BoundaryCondition, DomainCondition, InitialCondition, CouplingDefinition,
)
from schemas.study import StudyType, StudyPlan, ParametricSweep
from schemas.mesh import MeshPlan, RefinementRegion
from schemas.message import AgentMessage

__all__ = [
    "GeometryShape", "GeometryPlan", "GeometryOperation",
    "MaterialProperty", "MaterialDefinition", "MaterialAssignment", "MaterialPlan",
    "PhysicsField", "PhysicsPlan",
    "BoundaryCondition", "DomainCondition", "InitialCondition", "CouplingDefinition",
    "StudyType", "StudyPlan", "ParametricSweep",
    "MeshPlan", "RefinementRegion",
    "AgentMessage",
]
