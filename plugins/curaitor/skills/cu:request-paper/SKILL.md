# /cu:request-paper — Request full text of a paywalled paper

Request a paywalled paper via an institutional library service. This is a human-powered service — use sparingly. The skill is also invoked automatically by the `g` (get-paper) verdict in `/cu:read` and `/cu:review`.

## Configuration

The target address and template live in `config/user-settings.yaml` under `paper_request`. If that block is absent, the skill falls back to the `LIBRARY_REQUEST_EMAIL` environment variable, and finally prompts the user.

```yaml
paper_request:
  enabled: true                          # set false to hide the g verdict
  method: email                          # only "email" is supported today
  email: libraryrequests@example.com     # institutional library inbox
  subject: "paper request"               # fixed subject; citation goes in body
  # Optional template. Variables: {title}, {authors}, {journal}, {volume}, {year}, {url}
  # Default template is used if omitted.
  body_template: |
    {citation}

    {url}
```

`{citation}` expands to `Authors. "Title." Journal, Volume (Year).` — whatever fields are available. Missing fields are dropped gracefully.

## Arguments

$ARGUMENTS — URL of the paywalled paper, or title + journal if URL not available.

## Rules

**CRITICAL: Always ask the user for permission before sending.** Present the draft email and wait for explicit approval. This service is human-powered, not automated. Use only when:
- The paper is genuinely needed (not just curiosity)
- No open-access version exists (check bioRxiv, PubMed Central, author's website first)
- The user explicitly wants to request it

## Step 1: Check for open access

Before requesting, check if a free version exists:
1. Search for the DOI on `https://scholar.google.com` — look for [PDF] links
2. Check if there's a bioRxiv/medRxiv preprint version
3. Check PubMed Central for open-access deposit

If found, tell the user and skip the request.

## Step 2: Resolve the target address

Resolve in this order and stop at the first hit:

1. `config/user-settings.yaml:paper_request.email` (preferred)
2. `LIBRARY_REQUEST_EMAIL` environment variable
3. Prompt the user and, if they want it saved, offer to append a `paper_request` block to `config/user-settings.yaml`.

If `paper_request.enabled` is explicitly `false`, tell the user the feature is disabled and stop.

## Step 3: Compose the request

Extract from the URL or user input:
- **Title** of the paper
- **Authors** (at least first author)
- **Journal** and volume/year
- **URL** (DOI or publisher link)

Render the body using `paper_request.body_template` if set, otherwise the default:

```
{citation}

{url}
```

Subject is `paper_request.subject` if set, otherwise `"paper request"`.

## Step 4: Ask for permission

Present the draft email:

```
To: {email}
Subject: {subject}

{body}
```

Then ask: **"Send this request? (This is a human-powered service — confirming before sending.)"**

## Step 5: Send

Only after explicit approval. Open Gmail compose via:

```bash
cmux browser open "https://mail.google.com/mail/?view=cm&to={email}&su={encoded_subject}&body={encoded_body}"
```

Tell the user the compose window is open and they need to click Send.

## Step 6: Track

Add a note to the article's Obsidian note or Zotero entry:
```
Library request sent: YYYY-MM-DD
```

## Notes
- The library team typically responds within 1-2 business days
- Papers are usually added to an institutional reference library and a link is provided
- Previous requests: search Gmail for `from:{email}` or `to:{email}`
