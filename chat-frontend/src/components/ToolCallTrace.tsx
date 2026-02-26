import type { ToolCall } from "../types";

interface Props {
  toolCalls: ToolCall[];
}

export function ToolCallTrace({ toolCalls }: Props) {
  return (
    <details className="tool-trace">
      <summary className="tool-trace-summary">
        {toolCalls.length} tool {toolCalls.length === 1 ? "call" : "calls"} used
      </summary>
      <ul className="tool-trace-list">
        {toolCalls.map((tc) => (
          <li key={tc.id} className="tool-trace-item">
            <span className="tool-name">{tc.name}</span>
            <pre className="tool-args">
              {JSON.stringify(tc.arguments, null, 2)}
            </pre>
          </li>
        ))}
      </ul>
    </details>
  );
}
