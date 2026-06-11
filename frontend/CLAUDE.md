# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm run dev      # dev server on port 5173
npm run build    # tsc + vite build → dist/
npm run preview  # preview the production build locally
```

No linter or test runner is configured — `tsc -b` (run as part of `build`) is the type-check step.

## Architecture

### Routing (`App.tsx`)

React Router v6 with two guard wrappers:
- `RequireAuth` — redirects unauthenticated users to `<Landing />` (not `/login`)
- `RequireAdmin` — reads the JWT payload directly; returns `<Unauthorized />` or `<UpgradeRequired />` on failure

The axios interceptor in `api/client.ts` dispatches a `CustomEvent('auth:logout')` on any 401. `AuthRedirector` (mounted inside the router) listens for it and calls `navigate('/login')` — no hard reload.

Admin-only routes: `/admin`, `/model`, `/data-management`, `/pairs`, `/community`.

### API Layer (`api/client.ts`)

Single axios instance; `baseURL` defaults to `http://localhost:8000` (override with `VITE_API_URL`). JWT is stored in `localStorage` (remember me) or `sessionStorage` (session only) under the key `access_token`. The request interceptor attaches it as `Authorization: Bearer <token>`. All API calls go through this client — never create a second axios instance.

### State

TanStack Query (v5) for all server state. No global state library — component-local `useState` for UI state. `ThemeContext` is the only React context; all other cross-cutting concerns are custom hooks.

### Hooks

- `useAdminUser` — decodes the JWT payload client-side to read `is_admin` and `email`; no network call
- `useBranding` — fetches `/config/branding` (app name + logo URL); relative logo paths are prefixed with `VITE_API_URL`

### Theming & Styles

Dark/light toggle via `ThemeContext`. Theme is applied by toggling the `light` class on `<html>` — default is dark. Preference is persisted to `localStorage`.

All colours are CSS custom properties defined in `index.css` (`:root` for dark, `html.light` for light). Tailwind is configured to consume them as named tokens:

| Token | Var | Usage |
|---|---|---|
| `bg` | `--color-bg` | Page background |
| `s1/s2/s3` | `--color-s1/2/3` | Surface layers (sidebar, cards, inputs) |
| `tx/tx2/tx3` | `--color-tx/2/3` | Text hierarchy |
| `cy` | `#00e5cc` | Primary accent (active nav, highlights) |
| `gd` | `#f0b429` | Warning / gold |
| `rd` | `#ff3d5a` | Danger / red |
| `bl` | `#4f8ef7` | Info / blue |

Fonts: `font-sans` → Figtree, `font-head` → Syne, `font-mono` → IBM Plex Mono.

Utility CSS classes (defined in `index.css`, not Tailwind plugins): `.rg4/.rg3/.rg2` for responsive grids, `.page-enter` / `.card-anim` for entry animations, `.tick-up/.tick-dn` for price flash animations.

### Layout (`components/Layout.tsx`)

Single shared shell: collapsible sidebar (224 px) + topbar with live price ticker. The ticker polls `/prices` every 2 s (backs off to 30 s on error). Sidebar collapses to a hamburger on mobile via CSS (no JS breakpoint detection). Admin nav group is rendered only when `useAdminUser().isAdmin` is true.

## Non-Negotiable Rules

- **Never create a second axios instance.** Always import from `api/client.ts`.
- **Auth checks are JWT-decode only** (`useAdminUser`) — do not add network calls to auth guards.
- **Theme is CSS-variable-driven.** Add new colours as CSS custom properties in `index.css` and expose them in `tailwind.config.js` — never hardcode hex values in components.
- **Build output goes to `dist/`** and is served by the FastAPI backend as a SPA. Do not change the output directory.
- **`VITE_API_URL`** is the only env var. Set it in a `.env.local` file for local dev if the backend runs on a port other than 8000.
