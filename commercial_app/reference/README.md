# Glenigan reference files (gitignored)

Drop the files from the Glenigan API onboarding email in this folder:

- `Project ID Query.json` — example query by project ID
- `Example Query.json` — example search query
- `Results example.json` — example API response (the real field reference — the
  Swagger spec doesn't document response fields)
- `Role query results.json` — example role-filtered response
- `Glenigan Data Dictionary 202x.xlsx` — field definitions
- `Finding a Search query via the....msg` — guide email

Everything in this folder except this README is **gitignored**: the examples
contain licensed Glenigan data and real company/contact details, so they must
never be committed. The API key goes in the repo-root `.env` as
`GLENIGAN_API_KEY=` (also never committed).
