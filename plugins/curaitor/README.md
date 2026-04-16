# curaitor

AI-powered article discovery, triage, and interactive review — built as a [Claude Code](https://claude.ai/claude-code) plugin.

curaitor helps researchers and knowledge workers stay on top of their reading by automating the tedious parts of article discovery and triage while keeping the human in the loop for what matters: deciding what's worth reading and discussing it deeply.

## How it works

```
RSS feeds ──> /cu:discover ──> Obsidian vault (Inbox / Review / Ignored)
                                     ^
Instapaper ──> /cu:triage ───────────┘──> Instapaper Archive
                                     |
                         /cu:review (interactive triage)
                         /cu:read   (deep reading + discussion)
                                     |
                          cmux browser + Claude discussion
                                     |
                          reading-prefs.md updated
                          Zotero / Topics / Tools catalog
                          GitHub repos starred
```

### Three-tier confidence routing

Every article is evaluated against your learned preferences:

- **Inbox/** — Claude is confident you'll want this. Ready to read.
- **Review/** — Claude is uncertain. Queued for your interactive review.
- **Ignored/** — Claude is confident you won't want this. Periodically review for false negatives.

### Preference learning

curaitor learns your interests over time. Every time you give feedback during `/cu:review` or `/cu:read`, Claude updates `config/reading-prefs.md` with what your decision reveals. Deterministic routing rules in `config/triage-rules.yaml` supplement the LLM evaluation.

## Commands

| Command | Mode | What it does |
|---------|------|-------------|
| `/cu:triage` | Unattended | Fetch Instapaper saves, evaluate, route to Obsidian, archive |
| `/cu:discover` | Unattended | Scan RSS feeds for new articles, evaluate, route to Obsidian |
| `/cu:review` | Interactive | Browse Review queue in cmux browser, discuss, give verdicts |
| `/cu:read` | Interactive | Deep read Inbox articles: full summary, RAG discussion, save or discard |
| `/cu:review-ignored` | Interactive | Check Ignored folder for false negatives |
| `/cu:seed-preferences` | Interactive | One-time: analyze reading history to build initial preferences |

### Review verdicts (`/cu:review`)

| Key | Action |
|-----|--------|
| `!` | **Deep read** — save permanently, discuss interactively, save discussion notes |
| `?` | **Discuss** — ask questions about the article before deciding |
| `y` | Interested — move to Inbox. Star GitHub repo if detected. |
| `t` | **Topic** — attach to an existing or new topic in Obsidian |
| `c` | **Clip** — add repo/tool to Tools & Projects catalog, delete article |
| `b` | **Bookmark** — save link to `Bookmarks.md` (or custom command), delete article |
| `r` | Save to Zotero as reference |
| `n` | **Recycle** — not keeping. Appended to `Curaitor/Recycle.md`, note deleted. |
| `skip` | Leave in Curaitor/Review/ for later |
| `q` | Quit review session |

Inline commands: `! compare to our pipeline`, `? does this support hg38?`, `t Variant Calling`

### Read verdicts (`/cu:read`)

| Key | Action |
|-----|--------|
| `r` | Save to Zotero (papers), with discussion notes |
| `t` | Attach to a topic |
| `c` | Clip tool to Tools & Projects catalog |
| `b` | Bookmark link to `Bookmarks.md` (or custom command) |
| `n` | **Recycle** — not keeping. Appended to `Curaitor/Recycle.md`, note deleted. |
| `skip` | Leave in Inbox |
| `q` | Quit |

## Setup

There are two ways to run curaitor: as a **Claude Code plugin** (direct) or in a **Docker container** (sandboxed).

### Prerequisites

- [Claude Code](https://claude.ai/claude-code) CLI
- [Obsidian](https://obsidian.md) with an [MCP server](https://github.com/modelcontextprotocol/servers) configured
- Python 3 with `requests-oauthlib` and `pyyaml`
- [cmux](https://github.com/manaflow-ai/cmux) (optional, for interactive browser review)
- [Docker](https://www.docker.com/) (optional, for sandboxed execution)

---

### Option A: Claude Code Plugin (direct)

Run curaitor directly in Claude Code. Simplest setup, full access to your environment.

#### 1. Clone the repo

```bash
git clone https://github.com/jdidion/curaitor.git ~/projects/curaitor
```

#### 2. Install dependencies

```bash
pip3 install requests-oauthlib pyyaml
```

#### 3. Configure credentials

```bash
cp .env.example .env
# Edit .env with your API keys
```

You'll need:
- **Instapaper API keys** — apply at [instapaper.com/developers](https://www.instapaper.com/main/request_oauth_consumer_token), then do a one-time xAuth token exchange:

```python
from requests_oauthlib import OAuth1Session

session = OAuth1Session('CONSUMER_KEY', client_secret='CONSUMER_SECRET')
resp = session.post('https://www.instapaper.com/api/1/oauth/access_token',
    data={'x_auth_username': 'you@email.com',
          'x_auth_password': 'your_password',
          'x_auth_mode': 'client_auth'})
print(resp.text)  # oauth_token=X&oauth_token_secret=Y
```

- **Zotero API key** (optional) — get at [zotero.org/settings/keys](https://www.zotero.org/settings/keys)

#### 4. Import RSS feeds

Export OPML from your feed reader (Feedly, Inoreader, etc.) and import:

```bash
python scripts/import-opml.py ~/Downloads/feedly-export.opml --folder Science
```

This creates `config/feeds.yaml` (gitignored). Append from multiple folders:

```bash
python scripts/import-opml.py ~/Downloads/export.opml --folder Tech --append
```

See `config/feeds.yaml.example` for format. Per-feed `user_agent` overrides are supported for sites that block bots.

#### 5. Seed preferences

```bash
cd $CURAITOR_DIR && claude
# then: /cu:seed-preferences
```

#### 6. Run

```bash
# Interactive review/reading
cd $CURAITOR_DIR && claude
# then: /cu:review, /cu:read, etc.

# Unattended triage
cd $CURAITOR_DIR && claude -p "/cu:triage" --permission-mode bypassPermissions
```

#### 7. Schedule (optional)

```bash
# Triage Instapaper every 6 hours
0 */6 * * * cd $CURAITOR_DIR && claude -p "/cu:triage" --permission-mode bypassPermissions >> ~/curaitor-triage.log 2>&1

# Discover from feeds daily at 6am
0 6 * * * cd $CURAITOR_DIR && claude -p "/cu:discover" --permission-mode bypassPermissions >> ~/curaitor-discover.log 2>&1
```

#### 8. Separate workspaces (optional)

For isolated Claude sessions between interactive and unattended modes:

```bash
bash scripts/setup.sh both
```

This creates `workspace directories with symlinked commands and local credentials. See `scripts/setup.sh` for details.

---

### Option B: Docker (sandboxed)

Run curaitor in a Docker container for security isolation. The container only has access to your credentials (read-only), config (read-write for preferences), and Obsidian vault.

#### 1. Clone and configure

```bash
git clone https://github.com/jdidion/curaitor.git ~/projects/curaitor
cd $CURAITOR_DIR
cp .env.example .env
# Edit .env with your API keys (see Option A step 3)
```

#### 2. Import feeds and seed preferences

These steps require direct Claude access (run outside Docker first):

```bash
python scripts/import-opml.py ~/Downloads/feedly-export.opml --folder Science
claude -p "/cu:seed-preferences"
```

#### 3. Set environment variables

```bash
# Required: your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# Required: path to your Obsidian vault
export OBSIDIAN_VAULT=~/Library/CloudStorage/GoogleDrive-you@gmail.com/My\ Drive/Obsidian

# Optional: for GitHub starring and Bitwarden
export GITHUB_TOKEN=ghp_...
export BW_SESSION=...
```

#### 4. Build

```bash
docker compose build
```

#### 5. Run

```bash
# Sandboxed triage (unattended)
docker compose --profile triage up

# Sandboxed discover
docker compose --profile discover up

# Interactive review (attached terminal)
docker compose --profile review run review
```

#### 6. Schedule with cron

```bash
0 */6 * * * cd $CURAITOR_DIR && docker compose --profile triage up >> ~/curaitor-triage.log 2>&1
0 6 * * * cd $CURAITOR_DIR && docker compose --profile discover up >> ~/curaitor-discover.log 2>&1
```

#### What the container can access

| Resource | Access | Why |
|----------|--------|-----|
| `.env` | Read-only | API credentials |
| `config/` | Read-write | Preferences + feeds (needs to update prefs) |
| Obsidian vault | Read-write | Create/move/update notes |
| Network | Host | MCP servers on localhost |

What it **cannot** access: `~/.ssh`, `~/.aws`, other projects, system commands beyond the allowlist in `docker/settings.json`.

See `config/default-permissions.md` for the full permissions analysis.

---

## Helper scripts

These reduce token usage by handling mechanical operations outside the LLM:

```bash
# Instapaper API (replaces inline OAuth Python)
python scripts/instapaper.py list [--limit N] [--folder archive]
python scripts/instapaper.py text BOOKMARK_ID
python scripts/instapaper.py archive ID [ID ...]

# RSS feeds (fetch + parse all feeds)
python scripts/feeds.py [--days N] [--category CAT]

# Batch write Obsidian notes (faster than MCP for >10 notes)
echo '[{"path":"Inbox/title.md","frontmatter":{...},"content":"..."}]' | python scripts/write-notes.py

# Import feeds from OPML
python scripts/import-opml.py FILE [--folder NAME] [--append]

# Find correct Python (pixi/homebrew/system)
eval "$(bash scripts/find-python.sh)"

# Set up workspaces
bash scripts/setup.sh [review|triage|both]
```

## Auto-tagging and topics

curaitor automatically generates semantic tags for every article and searches for related topic notes in your Obsidian vault's `Topics/` folder. When matches are found, it offers to link the article to existing topics. Use the `t` verdict to attach articles to topics or create new ones.

Articles attached to topics are removed from the review/inbox queue — they live under the topic note.

## Customization

### Link-saving tools

curaitor is built around **Instapaper** but can be adapted:

| Tool | Auth | Key change |
|------|------|-----------|
| **Pocket** | OAuth 2.0 | Replace API calls in `cu:triage.md` with `/v3/get` and `/v3/send` |
| **Raindrop.io** | OAuth 2.0 or test token | `GET /raindrops/{id}`, `PUT /raindrop/{id}` |
| **Readwise Reader** | Token | `/api/v3/list/` — can also replace Feedly for RSS |
| **None (RSS only)** | — | Remove `/cu:triage`, use only `/cu:discover` |

### Reference managers

| Tool | Key change |
|------|-----------|
| **Zotero** (default) | Web API, save items + notes |
| **Mendeley** | OAuth 2.0, `POST /documents` + `POST /annotations` |
| **Plain Obsidian** | Save to `Library/` with citation metadata in frontmatter |

### Note systems

| Tool | Key change |
|------|-----------|
| **Obsidian** (default) | Via MCP server |
| **Notion** | Swap MCP calls for Notion API/MCP |
| **Local markdown** | Replace `mcp__obsidian__*` with `Write` tool calls |

### RSS sources

Any RSS/Atom/RDF feed URL works in `config/feeds.yaml`. Per-feed `user_agent` overrides supported. See `config/feeds.yaml.example`.

#### Example: Social network links via Sill

[Sill](https://sill.social/) aggregates links shared by people you follow on Bluesky and Mastodon. With Sill+, you get RSS feeds filtered by your interests — a great way to discover articles your network is talking about.

Setup:
1. Sign up for [Sill+](https://sill.social/) ($5/mo for premium features including RSS and custom notifications)
2. Connect your Bluesky and/or Mastodon accounts
3. Set up Custom Notifications with keyword filters matching your interests (e.g., genomics, bioinformatics, AI tools, variant calling, cfDNA)
4. Copy the RSS feed URL from your Sill+ dashboard
5. Add to `config/feeds.yaml`:

```yaml
- name: Sill Social Network Links
  url: https://sill.social/rss/YOUR_FEED_ID
  category: social
```

Sill articles will flow through `/cu:discover` like any other RSS feed, with three-tier routing based on your preferences.

## Architecture

```
curaitor/
├── CLAUDE.md                       # Plugin context for Claude
├── .claude/commands/               # Slash commands (cu:*)
│   ├── cu:triage.md
│   ├── cu:discover.md
│   ├── cu:review.md
│   ├── cu:read.md
│   ├── cu:review-ignored.md
│   └── cu:seed-preferences.md
├── config/
│   ├── feeds.yaml                  # Your RSS feeds (gitignored)
│   ├── feeds.yaml.example          # Feed format example
│   ├── reading-prefs.md            # Learned preferences (gitignored)
│   ├── triage-rules.yaml           # Deterministic routing rules
│   └── default-permissions.md      # Safe permissions for sandboxing
├── scripts/
│   ├── instapaper.py               # Instapaper API client
│   ├── feeds.py                    # RSS feed fetcher + parser
│   ├── write-notes.py              # Batch Obsidian note writer
│   ├── import-opml.py              # OPML → feeds.yaml converter
│   ├── find-python.sh              # Find Python with deps installed
│   └── setup.sh                    # Workspace setup script
├── docker/
│   └── settings.json               # Scoped permissions for Docker
├── Dockerfile
├── docker-compose.yaml
├── .env.example
└── .gitignore
```

## Roadmap

See [GitHub Issues](https://github.com/jdidion/curaitor/issues) for planned features and sources.

## License

MIT
