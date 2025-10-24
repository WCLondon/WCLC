```markdown
# Wild Capital — Contract first-page filler (Streamlit)

This repository contains a small Streamlit app that fetches submission rows from Supabase and renders a preview of the contract "first page". The additional form answers are used only to populate the preview and are not stored.

Features
- Lookup submission by planning reference (table: `submissions`, column: `reference_number`)
- Parses JSON columns commonly used in your data (demand_habitats, banks_selected, allocation_results, site_location)
- Presents additional questions (not stored)
- Renders printable HTML preview and offers an HTML download

Deployment (Streamlit Cloud)
1. Create a new GitHub repository and push these files.
2. On Streamlit Cloud, create a new app, connect it to the repository and branch.
3. Add secrets in Streamlit Cloud (App → Settings → Secrets) with:
   - SUPABASE_URL = https://<your-project>.supabase.co
   - SUPABASE_KEY = <anon-or-service-role-key> (for read-only fetching, anon key is OK if table is public)
4. Launch the app. Open the app and enter a planning reference (e.g. `BNG01549`) from your DB to preview.

Local run
1. Create a virtualenv and install requirements:
   - pip install -r requirements.txt
2. Provide env vars:
   - export SUPABASE_URL=...
   - export SUPABASE_KEY=...
3. Run:
   - streamlit run app.py

Security notes
- The example uses your Supabase key: prefer to set it in Streamlit secrets or environment variables rather than committing to the repo.
- The app only reads data; the additional user answers are kept in the user's session and not persisted.

If you want, I can:
- Create the GitHub repository and push these files for you (tell me owner/repo and confirm),
- Or open a PR if you prefer the files added to an existing repo (provide repo and target branch).
- Add server-side PDF generation and an auditable download flow.
```
