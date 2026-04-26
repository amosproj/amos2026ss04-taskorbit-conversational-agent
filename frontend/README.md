# TaskOrbit — frontend

React 19 + Vite 5 + TypeScript + Tailwind CSS v4 + shadcn/ui (new-york).

This package is the browser-side client for the TaskOrbit Conversational
Agent. It hosts the voice-interaction UI and the LiveKit client that
streams audio to the backend agent worker.


---

## Setup

```bash
cd frontend
cp .env.example .env.local       # adjust if the backend is not on :8000
npm install
npm run dev
```

Vite serves on <http://localhost:5173> with hot module reload. API
calls to `/api/*` are proxied to `VITE_API_URL` (default
`http://localhost:8000`), which removes the need for CORS configuration
during local development.

---

## Adding shadcn components

`components.json` is committed and `lib/utils.ts` contains the `cn()`
helper, so the shadcn CLI can be used directly:

```bash
npx shadcn@latest add button
npx shadcn@latest add input
npx shadcn@latest add card
```

The CLI writes the source file into `src/components/ui/`. The
generated files are owned by the project and intended to be modified
as needed.

---

## Project layout

```
frontend/
├── package.json
├── package-lock.json            # commit this
├── vite.config.ts
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── components.json              # shadcn config
├── index.html
├── .env.example                 # commit this; never commit .env.local
├── Dockerfile
├── README.md
├── public/                      # static assets served at /
└── src/
    ├── main.tsx                 # React entry
    ├── App.tsx                  # Placeholder page; replaced in #19
    ├── index.css                # Tailwind v4 + shadcn tokens
    ├── vite-env.d.ts            # Typed import.meta.env
    ├── components/
    │   └── ui/                  # shadcn components land here
    ├── lib/
    │   └── utils.ts             # cn() helper
    ├── hooks/
    └── pages/
```

---

## Useful commands

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | Type-check then build for production into `dist/` |
| `npm run preview` | Serve the built bundle locally |
| `npm run lint` | ESLint over `src/` |
| `npm run format` | Prettier over `src/` |
| `npm run type-check` | `tsc --noEmit` only |

---

`package-lock.json` is the committed source of truth for resolved
versions.