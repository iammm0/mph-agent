import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** 避免未捕获渲染错误直接白屏；开发时把堆栈显示出来。 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI crashed:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: 24,
            fontFamily: "ui-monospace, Consolas, monospace",
            whiteSpace: "pre-wrap",
            color: "#b91c1c",
            background: "#fff1f2",
            minHeight: "100vh",
            boxSizing: "border-box",
          }}
        >
          <h2 style={{ marginTop: 0 }}>界面渲染失败</h2>
          <p>{this.state.error.message}</p>
          <pre style={{ fontSize: 12, overflow: "auto" }}>
            {this.state.error.stack}
          </pre>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            style={{ marginTop: 12, padding: "6px 12px" }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
