# Profile Navigator Skill

## Purpose
Navigate to a LinkedIn profile URL and extract structured data into a prospect JSON file.

## Test and fixture data (do not corrupt)

- Do **not** write prospect or conversation data under `tests/` or `tests/fixtures/`.
- Persist prospects only via MCP **`upsert_prospect`** (`tools/server.py`), not by constructing
  `outreach/prospects/...` paths in the editor. Never overwrite fixture JSON used by `tests/test_*.py`.

## Inputs
- `linkedin_url`: the full profile URL
- `prospect_id`: short slug used as the output filename (e.g. `alex_chen_softeng`)

## Steps

1. Navigate to the LinkedIn profile URL in the browser.
2. Wait for the page to fully load (check for presence of the name heading).
3. Extract the following fields:
   - `name`: full name from the profile heading
   - `title`: current job title
   - `company`: current employer
   - `location`: city/region
   - `connection_degree`: "1st", "2nd", or "3rd+" (look for the degree badge near the name)
   - `mutual_connections`: list names if shown, else empty array
   - `recent_posts`: scroll to the Activity section; collect up to 3 most recent posts with `text`, `likes`, `timestamp`

4. Check connection status:
   - "none" if a "Connect" button is visible
   - "pending" if "Pending" is shown
   - "connected" if "Message" button is shown without "Connect"

5. Build a prospect object matching `outreach/schemas/prospect.schema.json`. Prefer **`scrape_profile`**
   MCP where possible, then merge with manual fields (`connection_status`, etc.).

6. If **`get_prospect(prospect_id)`** succeeds, merge: update fields that changed, preserve `outreach_stage`,
   `notes`, and `target_action`. If it returns an error, start from the new scrape only.

7. **`upsert_prospect(prospect_id, json.dumps(prospect))`**

8. **`append_action_log(entry=json.dumps({...}))`**:
```json
{ "action": "profile_navigated", "prospect_id": "<id>", "timestamp": "<ISO>", "url": "<url>" }
```

## Error Handling
- If the page redirects to login, stop and report: "LinkedIn authentication required."
- If the profile is not found (404), mark prospect as `status: not_found` and skip.
- If bot detection triggers (CAPTCHA or unusual activity warning), stop immediately and report to operator.
