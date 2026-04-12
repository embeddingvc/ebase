---
name: scrape-profile
description: Scrape a LinkedIn profile via the MCP scrape_profile tool and print the structured result. Use when the user asks to scrape, fetch, look up, or inspect a LinkedIn profile URL.
---

# Scrape Profile

Fetch structured data from a LinkedIn profile by calling the `scrape_profile` MCP tool and printing the result to the operator.

## Test and fixture data (do not corrupt)

- This tool is **read-only** on the repo. Do not save scrape output into `tests/fixtures/` or overwrite
  fixture files unless the user explicitly asked you to **update test data** for a test change.

## When to Use

- User provides a LinkedIn profile URL and asks to scrape or look up the profile
- User wants name, headline, location, about section, or recent posts from a profile
- Upstream skills (e.g. profile-navigator) need raw profile data before writing a prospect file

## Inputs

- `profile_url` (required) — full LinkedIn profile URL, e.g. `https://www.linkedin.com/in/username/`

## Steps

### 1. Call the MCP tool

Invoke `scrape_profile` with the provided URL:

```
Tool: scrape_profile
  profile_url: <the LinkedIn URL>
```

The tool attaches to the already-running Chrome session, navigates to the profile (and its recent-activity feed), extracts fields, and returns a JSON string.

### 2. Parse the JSON response

The tool returns a JSON-encoded object with these fields:

| Field               | Type            | Description                                      |
|---------------------|-----------------|--------------------------------------------------|
| `linkedin_url`      | string          | The URL that was scraped                         |
| `name`              | string          | Full name from the profile heading               |
| `title`             | string          | Current headline / job title                     |
| `location`          | string          | City / region shown on the profile               |
| `connection_degree` | integer or null | 1, 2, or 3 (null if not determinable)            |
| `about`             | string          | Content of the About section (may be empty)      |
| `recent_posts`      | array of dicts  | Up to 3 posts: `{text, timestamp, likes}`        |
| `scraped_at`        | string (ISO)    | UTC timestamp of when the scrape ran             |

### 3. Print the result

Display the profile data clearly to the operator. Use this format:

```
── Scraped Profile ───────────────────────────────────────────
Name:        <name>
Title:       <title>
Location:    <location>
Connection:  <connection_degree>° (or "unknown")
URL:         <linkedin_url>
Scraped at:  <scraped_at>

About:
<about text, or "(none)">

Recent Posts (<N> found):
  1. <first 120 chars of post text> …
  2. <first 120 chars of post text> …
  3. <first 120 chars of post text> …
─────────────────────────────────────────────────────────────
```

If `recent_posts` is empty, print `"No recent posts found."` instead of the numbered list.

Also print the raw JSON below the summary so the caller can pipe it downstream:

```json
{
  "linkedin_url": "...",
  ...
}
```

## Example

**User:** "Scrape https://www.linkedin.com/in/satyanadella/"

```
Tool call → scrape_profile(profile_url="https://www.linkedin.com/in/satyanadella/")

── Scraped Profile ───────────────────────────────────────────
Name:        Satya Nadella
Title:       Chairman and CEO at Microsoft
Location:    Redmond, Washington, United States
Connection:  2°
URL:         https://www.linkedin.com/in/satyanadella/
Scraped at:  2026-04-01T14:00:00+00:00

About:
(none)

Recent Posts (3 found):
  1. "Excited to share our latest AI announcements at Microsoft Build …"
  2. "Had a great conversation with leaders from across the industry …"
  3. "Cloud and AI are transforming every industry …"
─────────────────────────────────────────────────────────────

Raw JSON:
{
  "linkedin_url": "https://www.linkedin.com/in/satyanadella/",
  "name": "Satya Nadella",
  ...
}
```

## Error Handling

- **Not logged in** — the tool raises an error if Chrome is not authenticated. Instruct the user to log in to LinkedIn in the Chrome window and retry.
- **Profile not found / redirected** — if the URL resolves to a "Page not found" or login wall, report: `"Profile not accessible at <url>. It may be private or the URL is incorrect."`
- **Chrome not running** — if the CDP connection fails, report: `"Could not connect to Chrome at <cdp_url>. Make sure Chrome is running with --remote-debugging-port=9222."`
- **Bot detection** — if the scrape returns an empty name or raises a timeout, stop and report: `"LinkedIn may have triggered bot detection. Wait a few minutes before retrying."`
- **Partial data** — missing fields (empty string or null) are normal for private profiles; print what was returned and note which fields are missing.
