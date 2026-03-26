# Profile Navigator Skill

## Purpose
Navigate to a LinkedIn profile URL and extract structured data into a prospect JSON file.

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

5. Write output to `outreach/prospects/<prospect_id>.json` using the prospect schema.

6. If a prospect file already exists for this `prospect_id`, merge: update fields that changed, preserve `outreach_stage`, `notes`, and `target_action`.

7. Append to action log:
```json
{ "action": "profile_navigated", "prospect_id": "<id>", "timestamp": "<ISO>", "url": "<url>" }
```

## Error Handling
- If the page redirects to login, stop and report: "LinkedIn authentication required."
- If the profile is not found (404), mark prospect as `status: not_found` and skip.
- If bot detection triggers (CAPTCHA or unusual activity warning), stop immediately and report to operator.
