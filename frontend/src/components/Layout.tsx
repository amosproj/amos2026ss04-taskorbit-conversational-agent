import { NavLink, Outlet } from "react-router-dom";

import { ModeToggle } from "@/components/mode-toggle";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Chat", end: true },
  { to: "/config", label: "Agent Config", end: false },
  { to: "/history", label: "History", end: false },
] as const;

function BrandMark() {
  // Three concentric arcs nodding at "TaskOrbit" — orbital paths around a
  // central node. Inline SVG so it inherits currentColor and stays crisp on
  // any background.
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className="text-primary"
    >
      <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />
      <ellipse cx="12" cy="12" rx="9" ry="3.5" />
      <ellipse cx="12" cy="12" rx="9" ry="3.5" transform="rotate(60 12 12)" />
      <ellipse cx="12" cy="12" rx="9" ry="3.5" transform="rotate(-60 12 12)" />
    </svg>
  );
}

export function Layout() {
  const appName = import.meta.env.VITE_APP_NAME ?? "TaskOrbit";

  return (
    <div className="min-h-svh bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-primary focus-visible:px-3 focus-visible:py-2 focus-visible:text-sm focus-visible:text-primary-foreground"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-6 px-4 sm:px-6">
          <NavLink
            to="/"
            end
            className="flex items-center gap-2 text-sm font-semibold tracking-tight"
            aria-label={`${appName} home`}
          >
            <BrandMark />
            <span>{appName}</span>
          </NavLink>

          <nav aria-label="Main" className="hidden flex-1 sm:block">
            <ul className="flex items-center gap-1">
              {NAV_ITEMS.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      cn(
                        "relative inline-flex h-9 items-center rounded-md px-3 text-sm font-medium transition-colors",
                        "text-muted-foreground hover:text-foreground",
                        "after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent after:transition-colors",
                        isActive && "text-foreground after:bg-primary",
                      )
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <span
              className="hidden items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-xs font-medium text-muted-foreground md:inline-flex"
              aria-label="Sprint 2, in progress"
            >
              <span className="size-1.5 rounded-full bg-primary" aria-hidden />
              Sprint 2 · In Progress
            </span>
            <ModeToggle />
          </div>
        </div>

        <nav aria-label="Main mobile" className="border-t sm:hidden">
          <ul className="mx-auto flex max-w-5xl items-center gap-1 overflow-x-auto px-4 py-2">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "inline-flex h-8 items-center rounded-md px-3 text-xs font-medium transition-colors",
                      "text-muted-foreground hover:text-foreground",
                      isActive && "bg-muted text-foreground",
                    )
                  }
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <main id="main">
        <Outlet />
      </main>
    </div>
  );
}
