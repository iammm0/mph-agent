import React from "react";
import ReactDOM from "react-dom/client";
import { MathJaxContext } from "better-react-mathjax";
import { AppStateProvider } from "./context/AppStateContext";
import { ThemeProvider, initTheme } from "./context/ThemeContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import App from "./App";

import "@fontsource/fraunces/400.css";
import "@fontsource/fraunces/600.css";
import "@fontsource/fraunces/700.css";
import "@fontsource/fraunces/900.css";
import "@fontsource/source-serif-4/400.css";
import "@fontsource/source-serif-4/500.css";
import "@fontsource/source-serif-4/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";

import "./App.css";
import "./styles/claude.css";

initTheme();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <MathJaxContext
        version={3}
        config={{
          loader: { load: ["[tex]/ams"] },
          tex: {
            inlineMath: [
              ["$", "$"],
              ["\\(", "\\)"],
            ],
            displayMath: [
              ["$$", "$$"],
              ["\\[", "\\]"],
            ],
            packages: { "[+]": ["ams"] },
          },
        }}
      >
        <AppStateProvider>
          <ThemeProvider>
            <App />
          </ThemeProvider>
        </AppStateProvider>
      </MathJaxContext>
    </ErrorBoundary>
  </React.StrictMode>
);
