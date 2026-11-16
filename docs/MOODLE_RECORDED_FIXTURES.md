# Moodle recorded-response replay format

The replay harness accepts only reviewed, sanitized JSON. It does not connect to Moodle and does
not make a fixture "real" or establish compatibility; keep the staging evidence record separately.
Do not commit a fixture until its sanitization has been reviewed.

The document has this shape:

```json
{
  "schema_version": 1,
  "site_url": "https://moodle.example.edu",
  "responses": {
    "core_webservice_get_site_info": "<sanitized response object>",
    "core_enrol_get_users_courses": "<sanitized response array>",
    "core_course_get_contents": "<sanitized response array>"
  }
}
```

The angle-bracketed values above are descriptions, not Moodle responses or a runnable fixture.
Each value under `responses` is the JSON response body for that exact Moodle function. Preserve
the response structure, types, visibility flags, and relationships needed by the adapter.

Before replay:

- Remove tokens, credentials, names, usernames, email addresses, and other personal data from
  response values and embedded URLs. Never include request headers, request bodies, or tokens.
- Replace `core_webservice_get_site_info.userid` with the synthetic integer `1`. Replace Moodle
  course/module/file identifiers consistently with synthetic identifiers and use a reserved
  example hostname throughout `site_url` and Moodle file URLs.
- Remove query strings from file URLs; the adapter rejects token-bearing file URLs.
- Retain only the three required read-function response bodies. Never represent a synthetic
  response as staging evidence.

Replay locally with:

```bash
cd backend
uv run --locked python scripts/replay_moodle_fixtures.py /path/to/sanitized.json --course-id 42
```

The fixture transport and resolver are in-process stubs. The harness prints capability, course,
and course-context read results produced by `moallem.moodle.read`; it never opens a network
connection. Moodle staging validation remains BLOCKED until an authorized Moodle administrator
provides real, sanitized evidence for the target site and teacher role.
