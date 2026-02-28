import { useState } from "react";
import type { ToolCallEvent } from "../types";

interface Props {
  toolCalls: ToolCallEvent[];
}

export function ToolCallTrace({ toolCalls }: Props) {
  const failedCount = toolCalls.filter(
    (e) => e.status === "malformed" || e.status === "error"
  ).length;

  const summaryLabel = [
    `${toolCalls.length} step${toolCalls.length === 1 ? "" : "s"}`,
    failedCount > 0 ? `(${failedCount} failed)` : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <details className="tool-trace">
      <summary className="tool-trace-summary">{summaryLabel}</summary>
      <div className="tool-timeline">
        {toolCalls.map((event, i) => (
          <TimelineEvent key={i} event={event} isLast={i === toolCalls.length - 1} />
        ))}
      </div>
    </details>
  );
}

function TimelineEvent({
  event,
  isLast,
}: {
  event: ToolCallEvent;
  isLast: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isFailure = event.status === "malformed" || event.status === "error";
  const dotClass = `timeline-dot ${isFailure ? "timeline-dot--error" : "timeline-dot--success"}`;

  return (
    <div className={`timeline-event${isLast ? " timeline-event--last" : ""}`}>
      <div className="timeline-rail">
        <span className={dotClass} />
        {!isLast && <span className="timeline-line" />}
      </div>
      <div className="timeline-content">
        {event.status === "malformed" ? (
          <MalformedContent event={event} expanded={expanded} onToggle={() => setExpanded(!expanded)} />
        ) : (
          <ToolContent event={event} expanded={expanded} onToggle={() => setExpanded(!expanded)} />
        )}
      </div>
    </div>
  );
}

function ToolContent({
  event,
  expanded,
  onToggle,
}: {
  event: ToolCallEvent;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isError = event.status === "error";
  const hasExpandable =
    (event.arguments && Object.keys(event.arguments).length > 0) ||
    (isError && event.error_message);

  return (
    <>
      <button className="timeline-header" onClick={onToggle} disabled={!hasExpandable}>
        <span className={`tool-name${isError ? " tool-name--error" : ""}`}>
          {event.tool}
        </span>
        {isError && <span className="timeline-badge timeline-badge--error">error</span>}
      </button>
      {expanded && hasExpandable && (
        <div className="timeline-detail">
          {event.arguments && Object.keys(event.arguments).length > 0 && (
            <pre className="tool-args">
              {JSON.stringify(event.arguments, null, 2)}
            </pre>
          )}
          {isError && event.error_message && (
            <p className="timeline-error-msg">{event.error_message}</p>
          )}
        </div>
      )}
    </>
  );
}

function MalformedContent({
  event,
  expanded,
  onToggle,
}: {
  event: ToolCallEvent;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <button className="timeline-header" onClick={onToggle} disabled={!event.error_message}>
        <span className="timeline-badge timeline-badge--malformed">Malformed call</span>
        {event.retry_attempt != null && (
          <span className="timeline-retry">retry #{event.retry_attempt}</span>
        )}
      </button>
      {expanded && event.error_message && (
        <div className="timeline-detail">
          <p className="timeline-error-msg">{event.error_message}</p>
        </div>
      )}
    </>
  );
}
