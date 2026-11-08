import { useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { MphbStepPreview } from "../lib/types";

const NODE_WIDTH = 320;
const NODE_GAP = 120;
const START_ID = "flow-start";
const END_ID = "flow-end";

/** 步骤状态 → 展示音调（兼容旧 completed/error 别名） */
export type WorkflowTone = "ok" | "err" | "warn" | "skip" | "pending";

export const WORKFLOW_STATUS_COLOR: Record<WorkflowTone, string> = {
  ok: "#1b7a3d",
  err: "#a12622",
  warn: "#8a6d00",
  skip: "#7a828c",
  pending: "#7a828c",
};

export function statusClass(status: string | undefined): string {
  const s = (status || "").toLowerCase();
  if (s === "success" || s === "completed" || s === "ok") return "mphb-status--ok";
  if (s === "failed" || s === "error") return "mphb-status--err";
  if (s === "warning" || s === "running") return "mphb-status--warn";
  if (s === "skipped") return "mphb-status--skip";
  return "mphb-status--pending";
}

function toneOf(status: string | undefined): WorkflowTone {
  const s = (status || "").toLowerCase();
  if (s === "success" || s === "completed" || s === "ok") return "ok";
  if (s === "failed" || s === "error") return "err";
  if (s === "warning" || s === "running") return "warn";
  if (s === "skipped") return "skip";
  return "pending";
}

function basename(path: string | null | undefined): string {
  if (!path) return "";
  const i = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return i >= 0 ? path.slice(i + 1) : path;
}

type StepFlowData = {
  kind: "step";
  step: MphbStepPreview;
  color: string;
  selected: boolean;
};
type StartEndFlowData = {
  kind: "start" | "end";
  label: string;
  text: string;
  color: string;
};
type FlowNode = Node<StepFlowData, "step"> | Node<StartEndFlowData, "startEnd">;

function StepNode({ data }: NodeProps<Node<StepFlowData, "step">>) {
  const { step, color, selected } = data;
  return (
    <div
      className="mphb-flow-step"
      style={
        selected
          ? {
              borderColor: color,
              boxShadow: `0 0 0 2px ${color}26, 0 4px 12px rgba(0,0,0,0.15)`,
            }
          : undefined
      }
    >
      <Handle
        type="target"
        position={Position.Top}
        className="mphb-flow-handle"
        isConnectable={false}
      />
      <div className="mphb-flow-step__accent" style={{ background: color }} />
      <div className="mphb-flow-step__body">
        <div className="mphb-flow-step__head">
          <span className="mphb-flow-step__index">{step.index}</span>
          <span className="mphb-flow-step__label" title={step.message || undefined}>
            {step.label || step.action || "步骤"}
          </span>
          <span className={`mphb-status ${statusClass(step.status)}`}>
            {step.status || "pending"}
          </span>
        </div>
        {step.step_type && (
          <div className="mphb-flow-step__type">{step.step_type}</div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="mphb-flow-handle"
        isConnectable={false}
      />
    </div>
  );
}

function StartEndNode({ data }: NodeProps<Node<StartEndFlowData, "startEnd">>) {
  return (
    <div className="mphb-flow-startend">
      {data.kind === "start" ? (
        <Handle
          type="source"
          position={Position.Bottom}
          className="mphb-flow-handle"
          isConnectable={false}
        />
      ) : (
        <Handle
          type="target"
          position={Position.Top}
          className="mphb-flow-handle"
          isConnectable={false}
        />
      )}
      <span className="mphb-flow-startend__label">{data.label}</span>
      <span className="mphb-flow-startend__text" title={data.text}>
        {data.text}
      </span>
    </div>
  );
}

const nodeTypes = { step: StepNode, startEnd: StartEndNode } satisfies NodeTypes;

export interface MphbWorkflowGraphProps {
  steps: MphbStepPreview[];
  success: boolean;
  modelPath?: string | null;
  userInput?: string;
  planDescription?: string | null;
}

export function MphbWorkflowGraph({
  steps,
  success,
  modelPath,
  userInput,
  planDescription,
}: MphbWorkflowGraphProps) {
  const [selected, setSelected] = useState<MphbStepPreview | null>(null);

  const startText = (planDescription || userInput || "开始").slice(0, 48);
  const endText = basename(modelPath) || (success ? "构建完成" : "未完成");
  const endColor = success ? WORKFLOW_STATUS_COLOR.ok : WORKFLOW_STATUS_COLOR.err;

  const nodes = useMemo<FlowNode[]>(
    () => {
      const list: FlowNode[] = [
        {
          id: START_ID,
          type: "startEnd",
          position: { x: 0, y: 0 },
          width: NODE_WIDTH,
          height: 56,
          data: { kind: "start", label: "需求", text: startText, color: "#64748b" },
        },
      ];
      steps.forEach((step, i) => {
        list.push({
          id: `step-${i}`,
          type: "step",
          position: { x: 0, y: (i + 1) * NODE_GAP },
          width: NODE_WIDTH,
          height: 84,
          data: {
            kind: "step",
            step,
            color: WORKFLOW_STATUS_COLOR[toneOf(step.status)],
            selected: selected?.index === step.index,
          },
        });
      });
      list.push({
        id: END_ID,
        type: "startEnd",
        position: { x: 0, y: (steps.length + 1) * NODE_GAP },
        width: NODE_WIDTH,
        height: 56,
        data: { kind: "end", label: "模型", text: endText, color: endColor },
      });
      return list;
    },
    [steps, startText, endText, endColor, selected],
  );

  const edges = useMemo<Edge[]>(
    () => {
      const ids = [START_ID, ...steps.map((_, i) => `step-${i}`), END_ID];
      return ids.slice(1).map((target, j) => {
        const tone =
          j < steps.length ? toneOf(steps[j].status) : success ? "ok" : "err";
        const color = WORKFLOW_STATUS_COLOR[tone];
        return {
          id: `mphb-edge-${j}`,
          source: ids[j],
          target,
          type: "smoothstep",
          animated: tone === "pending" || tone === "warn",
          style: { stroke: color, strokeWidth: 1.5 },
        };
      });
    },
    [steps, success],
  );

  const params =
    selected?.parameters && Object.keys(selected.parameters).length > 0
      ? JSON.stringify(selected.parameters, null, 2)
      : null;

  return (
    <div className="mphb-flow">
      <div className="mphb-flow-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.18, maxZoom: 1.1 }}
          nodesDraggable={false}
          nodesConnectable={false}
          zoomOnScroll={false}
          minZoom={0.4}
          maxZoom={2}
          onNodeClick={(_, node) => {
            const step =
              node.data.kind === "step" ? (node.data as StepFlowData).step : null;
            setSelected((cur) =>
              cur?.index === step?.index ? null : step,
            );
          }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--border)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      {selected && (
        <div className="mphb-flow-detail">
          <div className="mphb-flow-detail__head">
            <span className="mphb-flow-step__index">{selected.index}</span>
            <span className="mphb-step-label">
              {selected.label || selected.action || "步骤"}
            </span>
            <span className={`mphb-status ${statusClass(selected.status)}`}>
              {selected.status || "pending"}
            </span>
          </div>
          {selected.message && (
            <p className="mphb-flow-detail__msg">{selected.message}</p>
          )}
          {selected.step_type && (
            <p className="mphb-flow-detail__type">
              类型：{selected.step_type} · 动作：{selected.action}
            </p>
          )}
          {selected.model_path && (
            <code className="mphb-preview-path" title={selected.model_path}>
              {selected.model_path}
            </code>
          )}
          {params && <pre className="mphb-flow-detail__params">{params}</pre>}
        </div>
      )}
    </div>
  );
}
