import { NavLink, Outlet } from "react-router-dom";

import { LegalNoticesDialog } from "@/components/LegalNoticesDialog";
import { ModeToggle } from "@/components/mode-toggle";
import { cn } from "@/lib/utils";
import logoUrl from "@/assets/taskorbit-logo.png";

const NAV_ITEMS = [
  { to: "/", label: "Chat", end: true },
  { to: "/config", label: "Agent Config", end: false },
  { to: "/history", label: "History", end: false },
] as const;

export function Layout() {
  const appName = import.meta.env.VITE_APP_NAME ?? "TaskOrbit";

  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-primary focus-visible:px-3 focus-visible:py-2 focus-visible:text-sm focus-visible:text-primary-foreground"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 sm:px-6">
          <NavLink
            to="/"
            end
            className="flex items-center gap-2 text-sm font-semibold tracking-tight"
            aria-label={`${appName} home`}
          >
            <img src={logoUrl} alt="" className="size-6 shrink-0" />
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
            <ModeToggle />
          </div>
        </div>

        <nav aria-label="Main mobile" className="border-t sm:hidden">
          <ul className="mx-auto flex max-w-6xl items-center gap-1 overflow-x-auto px-4 py-2">
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

      <main id="main" className="flex-1">
        <Outlet />
      </main>

      <footer className="flex items-center justify-center gap-4 border-t px-4 py-3">
        <LegalNoticesDialog />
        <span className="text-xs text-muted-foreground">
          © {new Date().getFullYear()} {appName}
        </span>
      </footer>
    </div>
  );
}
