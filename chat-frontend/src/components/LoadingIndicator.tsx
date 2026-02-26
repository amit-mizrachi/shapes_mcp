export function LoadingIndicator() {
  return (
    <div className="loading-indicator" role="status" aria-label="Thinking...">
      <div className="message-label">Assistant</div>
      <div className="loading-dots">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
      </div>
    </div>
  );
}
