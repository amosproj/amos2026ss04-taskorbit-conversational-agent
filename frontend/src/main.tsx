import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ThemeProvider as NextThemesProvider } from "next-themes";

import "@livekit/components-styles";
import "./index.css";

import { App } from "@/App";
import { ActiveAgentProvider } from "@/components/active-agent-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Root element #root not found in index.html");

createRoot(rootEl).render(
  <StrictMode>
    {/* Our ThemeProvider owns the toggle (writes the .dark class on <html>);
        next-themes only reads that class so the sonner Toaster can theme
        itself. Keeping both avoids forking the existing provider. */}
    <ThemeProvider defaultTheme="system" storageKey="taskorbit-ui-theme">
      <NextThemesProvider attribute="class" defaultTheme="system" enableSystem>
        <ActiveAgentProvider>
          <App />
          <Toaster richColors position="bottom-right" />
        </ActiveAgentProvider>
      </NextThemesProvider>
    </ThemeProvider>
  </StrictMode>,
);
