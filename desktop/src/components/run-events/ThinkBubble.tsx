import type { RunEvent } from "../../lib/types";
import { sanitizeLLMDisplayText } from "../../lib/textSanitizer";

/** 思维流（LLM 流式 / think_chunk）：气泡样式 */
export function ThinkBubble({
  event,
  isLiveStreamTail = false,
}: {
  event: RunEvent;
  /** 当前会话进行中且本块为最后一个流式片段时显示打字光标 */
  isLiveStreamTail?: boolean;
}) {
  const d = event.data ?? {};
  const type = event.type;

  if (type === "llm_stream_chunk") {
    const chunk = sanitizeLLMDisplayText(String(d.chunk ?? d.text ?? ""));
    const phase = (d.phase as string) ?? "";
    if (!chunk && !isLiveStreamTail) return null;
    return (
      <div className="run-event-bubble run-event-bubble--think">
        {phase && <span className="run-event-bubble__phase">{phase}</span>}
        <div
          className={`run-event-bubble__content run-event-bubble__content--stream${
            isLiveStreamTail ? " run-event-bubble__content--stream-live" : ""
          }`}
        >
          {chunk}
          {isLiveStreamTail && (
            <span className="run-event-bubble__stream-caret" aria-hidden />
          )}
        </div>
      </div>
    );
  }

  const thought = d.thought as Record<string, unknown> | undefined;
  if (!thought) return null;
  const action = (thought.label as string | undefined) || (thought.action as string | undefined);
  const reasoning = thought.reasoning as string | undefined;
  const basis = thought.basis as string | undefined;
  const progress = thought.progress as string | undefined;
  const highlights = Array.isArray(thought.input_highlights)
    ? thought.input_highlights.map((item) => String(item ?? "").trim()).filter(Boolean)
    : [];

  return (
    <div className="run-event-bubble run-event-bubble--think">
      {(action || progress) && (
        <div className="run-event-bubble__action">
          {progress ? `${progress} · ` : ""}
          {action}
        </div>
      )}
      {reasoning && <div className="run-event-bubble__content">{reasoning}</div>}
      {basis && (
        <div className="run-event-bubble__basis">
          <span className="run-event-bubble__basis-label">依据</span>
          {basis}
        </div>
      )}
      {highlights.length > 0 && (
        <ul className="run-event-bubble__inputs">
          {highlights.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
      {!action && !reasoning && (
        <div className="run-event-bubble__content">{JSON.stringify(thought).slice(0, 200)}</div>
      )}
    </div>
  );
}
