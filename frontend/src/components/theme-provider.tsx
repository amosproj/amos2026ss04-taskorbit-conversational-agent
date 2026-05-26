import { useEffect, useState, type ReactNode } from "react";
import { ThemeProviderContext, type Theme, type ThemeProviderState } from "./theme-context";

type ThemeProviderProps = {
  children: ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
};

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "taskorbit-ui-theme",
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() => {
    try {
      return (localStorage.getItem(storageKey) as Theme) || defaultTheme;
    } catch {
      return defaultTheme;
    }
  });

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");

    if (theme === "system") {
      const systemTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
      root.classList.add(systemTheme);
      return;
    }

    root.classList.add(theme);
  }, [theme]);

  const value: ThemeProviderState = {
    theme,
    setTheme: (next) => {
      try {
        localStorage.setItem(storageKey, next);
      } catch {
        // Storage unavailable (incognito) — fall through; preference won't persist.
      }
      setThemeState(next);
    },
  };

  return <ThemeProviderContext.Provider value={value}>{children}</ThemeProviderContext.Provider>;
}
