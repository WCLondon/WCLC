```markdown
# Wild Capital — Contract first-page filler (Streamlit)

This repository contains a small Streamlit app that fetches submission rows from a database and renders a preview of the contract "first page". The additional form answers are used only to populate the preview and are not stored.

Features
- Lookup submission by planning reference (table: configurable, defaults to `submissions_attio`, column: `reference_number`)
- Supports both direct PostgreSQL connection and legacy Supabase client
- Parses JSON columns commonly used in your data (demand_habitats, banks_selected, allocation_results, site_location)
- Presents additional questions (not stored)
- Renders printable HTML preview and offers an HTML download

## Configuration

The app supports two connection methods:

### Option 1: Direct PostgreSQL Connection (Recommended)

This is the recommended approach for Supabase Pooler connections.

In Streamlit Cloud (App → Settings → Secrets), add:
```toml
[database]
url = "postgresql+psycopg://postgres.xxxxx:password@aws-1-eu-north-1.pooler.supabase.com:6543/postgres"

# Optional: Override default table name (defaults to "submissions_attio")
table_name = "submissions_attio"

# Optional: Authentication credentials (if needed by your app)
[auth]
username = "WC0323"
password = "Wimborne"

[admin]
password = "WCAdmin2024"
```

### Option 2: Legacy Supabase Client

For backward compatibility with existing Supabase setups:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-anon-or-service-role-key"

# Optional: Override default table name
table_name = "submissions"
```

## Deployment (Streamlit Cloud)

1. Create a new GitHub repository and push these files.
2. On Streamlit Cloud, create a new app, connect it to the repository and branch.
3. Add secrets in Streamlit Cloud (App → Settings → Secrets) using one of the configuration options above.
4. Launch the app. Open the app and enter a planning reference (e.g. `BNG01549`) from your DB to preview.

## Local Development

1. Create a virtualenv and install requirements:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure secrets:
   - Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
   - Update with your actual database credentials
   - **Important**: Never commit `secrets.toml` to version control

3. Run:
   ```bash
   streamlit run app.py
   ```

## Environment Variables (Alternative to secrets)

You can also use environment variables instead of secrets:
```bash
export DATABASE_URL="postgresql+psycopg://..."
export TABLE_NAME="submissions_attio"  # Optional, defaults to "submissions_attio"
streamlit run app.py
```

## Security Notes

- The example uses your database credentials: always set them in Streamlit secrets or environment variables rather than committing to the repo.
- The app only reads data; the additional user answers are kept in the user's session and not persisted.
- The `.gitignore` file prevents accidental commits of secrets.
```
