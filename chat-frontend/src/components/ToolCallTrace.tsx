import type { ToolCall } from "../types";

interface Props {
  toolCalls: ToolCall[];
}

export function ToolCallTrace({ toolCalls }: Props) {
  const hasArgs = (args: Record<string, unknown>) =>
    Object.keys(args).length > 0;

  return (
    <details className="tool-trace">
      <summary className="tool-trace-summary">
        {toolCalls.length} tool {toolCalls.length === 1 ? "call" : "calls"} used
      </summary>
      <ul className="tool-trace-list">
        {toolCalls.map((tc, i) => (
          <li key={i} className="tool-trace-item">
            <span className="tool-name">{tc.tool}</span>
            {hasArgs(tc.arguments) && (
              <pre className="tool-args">
                {JSON.stringify(tc.arguments, null, 2)}
              </pre>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
