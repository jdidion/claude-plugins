# /cu:dashboard — Launch the curaitor dashboard webapp

Start the curaitor dashboard (hono/node-server webapp) and open it in a browser. Prefers `cmux browser open`; falls back to the system default.

## Arguments

$ARGUMENTS — Optional:
- `--port N` — override port (default: 3141)
- `--dir PATH` — override webapp directory (default: `$CURAITOR_DIR` or `~/projects/curaitor`)
- `--no-open` — start the server but do not open a browser
- `--force` — bypass the inside-the-repo self-guard

## Rules

**Self-guard: do not spawn nested servers.** If the current working directory is the curaitor webapp repo (or any subdirectory), the command is a no-op: it prints the expected URL and exits without starting a new server or opening a browser. Override with `--force` only if you are certain you want a second instance.

**Idempotent.** If a server is already listening on the target port, reuse it instead of starting a new one.

## Step 1: Launch the dashboard

Run the launcher script. It handles: self-guard check, port probe, detached `npm run dev` if needed, readiness wait (up to 30s), browser open.

```bash
bash scripts/dashboard.sh
```

The script prints the URL to stdout and status messages to stderr. Logs go to `~/curaitor-dashboard.log`.

## Step 2: Present result

Tell the user whether the dashboard was newly started or reused, and the URL:

```
Dashboard ready at http://localhost:3141 (reused existing server)
Opened in cmux browser.
```

If the self-guard fires, tell the user:

```
Already inside the curaitor webapp repo — not starting a nested server.
Dashboard URL: http://localhost:3141
```

## Troubleshooting

- **"CURAITOR_DIR not found"** — clone the webapp: `git clone https://github.com/jdidion/curaitor.git ~/projects/curaitor`, or export `CURAITOR_DIR` to an existing checkout.
- **"dashboard did not start within 30s"** — check `~/curaitor-dashboard.log` for compile errors. First run may need `npm install` in the webapp repo.
- **Browser didn't open** — run `bash scripts/dashboard.sh --no-open` and open the printed URL manually.
