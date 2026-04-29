import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@livekit/components-styles";
import "./index.css";

import { App } from "@/App";
import { ThemeProvider } from "@/components/theme-provider";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Root element #root not found in index.html");

createRoot(rootEl).render(
  <StrictMode>
    <ThemeProvider defaultTheme="system" storageKey="taskorbit-ui-theme">
      <App />
    </ThemeProvider>
  </StrictMode>,
);
