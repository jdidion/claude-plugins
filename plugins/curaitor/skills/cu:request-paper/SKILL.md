# /cu:request-paper — Request full text of a paywalled paper

Request a paywalled paper via an institutional library service. This is a human-powered service — use sparingly.

## Setup

Set `LIBRARY_REQUEST_EMAIL` in your environment (or `.env`) to the address of your institution's library request inbox. If unset, the skill will prompt you for the address before composing.

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

## Step 2: Compose the request

Extract from the URL or user input:
- **Title** of the paper
- **Authors** (at least first author)
- **Journal** and volume/year
- **URL** (DOI or publisher link)

## Step 3: Ask for permission

Present the draft email:

```
To: ${LIBRARY_REQUEST_EMAIL}
Subject: Library request: {Title}

Hi, could you please obtain a copy of:

{Authors}. "{Title}." {Journal}, {Volume} ({Year}).
{URL}

Thank you!
```

Then ask: **"Send this request? (This is a human-powered service — confirming before sending.)"**

## Step 4: Send

Only after explicit approval. Open Gmail compose via:
```bash
cmux browser open "https://mail.google.com/mail/?view=cm&to=${LIBRARY_REQUEST_EMAIL}&su={encoded_subject}&body={encoded_body}"
```

Tell the user the compose window is open and they need to click Send.

## Step 5: Track

Add a note to the article's Obsidian note or Zotero entry:
```
Library request sent: YYYY-MM-DD
```

## Notes
- The library team typically responds within 1-2 business days
- Papers are usually added to an institutional reference library and a link is provided
- Previous requests: search Gmail for `from:${LIBRARY_REQUEST_EMAIL}` or `to:${LIBRARY_REQUEST_EMAIL}`
