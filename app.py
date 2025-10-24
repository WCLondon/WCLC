#!/usr/bin/env python3
"""
Streamlit app: Wild Capital — Contract first-page filler

- Connects to a database (PostgreSQL or Supabase) to fetch a submission by reference_number
- Supports direct PostgreSQL connection via database.url (recommended) or legacy Supabase client
- Table name is configurable (defaults to submissions_attio)
- Presents a form with additional questions (not stored)
- Renders a first-page contract preview and lets user download HTML (print to PDF via browser)
"""

import os
import json
from datetime import datetime
from html import escape as html_escape
from typing import Any, Dict, List, Optional

import streamlit as st

# supabase-py client
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = Any

# SQLAlchemy for direct PostgreSQL connection
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine
except Exception:
    create_engine = None
    text = None
    Engine = Any

st.set_page_config(page_title="Wild Capital — Contract filler", layout="wide")


# ---------- Helpers ----------

def get_database_connection():
    """
    Try to establish a database connection using either:
    1. Direct PostgreSQL connection via database.url (preferred)
    2. Legacy Supabase client via SUPABASE_URL and SUPABASE_KEY
    
    Returns a tuple: (connection_type, connection_object)
    where connection_type is either 'postgres' or 'supabase'
    """
    # First, try to get PostgreSQL connection string from secrets
    db_url = None
    try:
        db_url = st.secrets["database"]["url"]
    except Exception:
        pass
    
    if not db_url:
        try:
            db_url = os.getenv("DATABASE_URL")
        except Exception:
            pass
    
    # If we have a PostgreSQL URL, use that
    if db_url:
        if create_engine is None:
            st.error("SQLAlchemy not installed. Please install sqlalchemy and psycopg.")
            return None, None
        try:
            engine = create_engine(db_url)
            return 'postgres', engine
        except Exception as e:
            st.error(f"Failed to create PostgreSQL connection: {e}")
            return None, None
    
    # Fall back to legacy Supabase client
    url = None
    key = None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        st.warning("Neither database.url nor SUPABASE_URL/SUPABASE_KEY found in st.secrets or environment.")
        return None, None

    if create_client is None:
        st.error("supabase package not installed. See requirements.txt and install it.")
        return None, None

    return 'supabase', create_client(url, key)


def get_table_name():
    """
    Get the table name from secrets or environment, defaulting to 'submissions_attio'
    """
    table_name = None
    try:
        table_name = st.secrets.get("table_name")
    except Exception:
        pass
    
    if not table_name:
        table_name = os.getenv("TABLE_NAME")
    
    return table_name or "submissions_attio"


def safe_parse(v: Any) -> Optional[Any]:
    """Try to parse JSON-like strings into Python objects; return original if not parseable."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    s = str(v).strip()
    if not s:
        return None
    # sometimes stored as Python repr or double-quoted JSON
    try:
        return json.loads(s)
    except Exception:
        # Try to fix common double-escaped quotes
        try:
            cleaned = s.replace('""', '"')
            return json.loads(cleaned)
        except Exception:
            return s


def fetch_submission_by_ref(conn_type: str, conn: Any, ref: str, table_name: str = "submissions_attio") -> Optional[Dict]:
    """
    Query the submissions table by reference_number.
    Supports both PostgreSQL (via SQLAlchemy) and Supabase clients.
    Returns a parsed dictionary or None.
    """
    if not conn:
        return None
    
    try:
        if conn_type == 'postgres':
            # Use SQLAlchemy to query PostgreSQL directly
            with conn.connect() as connection:
                query = text(f"SELECT * FROM {table_name} WHERE reference_number = :ref LIMIT 1")
                result = connection.execute(query, {"ref": ref})
                row = result.mappings().fetchone()
                if not row:
                    return None
                # Convert to dict
                row = dict(row)
        elif conn_type == 'supabase':
            # Use Supabase client
            resp = conn.table(table_name).select("*").eq("reference_number", ref).limit(1).execute()
            # supabase-py returns a dict with 'data' key
            data = None
            try:
                data = resp.get("data", None) if isinstance(resp, dict) else getattr(resp, "data", None)
            except Exception:
                data = resp

            if not data:
                return None
            if isinstance(data, list):
                row = data[0] if data else None
            else:
                row = data

            if not row:
                return None
        else:
            st.error(f"Unknown connection type: {conn_type}")
            return None
            
    except Exception as e:
        st.error(f"Database query failed: {e}")
        return None

    # Parse JSON-ish columns
    demand_habitats = safe_parse(row.get("demand_habitats"))
    banks_selected = safe_parse(row.get("banks_selected"))
    allocation_results = safe_parse(row.get("allocation_results"))
    site_location = safe_parse(row.get("site_location"))

    contract = {
        "application_reference": row.get("reference_number"),
        "developer_name": row.get("client_name"),
        "developer_company_number": row.get("client_company_number", ""),
        "submission_date": row.get("submission_date"),
        "development_land": (site_location.get("line_1") if isinstance(site_location, dict) and site_location.get("line_1") else row.get("site_location")),
        "site_location_full": site_location or row.get("site_location"),
        "purchase_price": str(row.get("total_cost")) if row.get("total_cost") is not None else None,
        "total_with_admin": str(row.get("total_with_admin")) if row.get("total_with_admin") is not None else None,
        "reservation_fee": str(row.get("reservation_fee")) if row.get("reservation_fee") is not None else None,
        "transaction_fee": str(row.get("transaction_fee")) if row.get("transaction_fee") is not None else None,
        "longstop_date": row.get("longstop_date"),
        "wild_capital_habitat_bank": ", ".join(banks_selected) if isinstance(banks_selected, list) else (str(banks_selected) if banks_selected else ""),
        "conservation_covenant_date": row.get("conservation_covenant_date"),
        "bng_units": demand_habitats if isinstance(demand_habitats, list) else ( [demand_habitats] if demand_habitats else [] ),
        "allocation_results": allocation_results,
        "raw_row": row,
    }
    return contract


def render_contract_html(contract: Dict, answers: Dict) -> str:
    """
    Produce an HTML snippet for the first page with the contract fields + answers.
    Keep it simple, printable by browser Print -> Save as PDF.
    Formatted to match legal contract standards.
    """
    def show(val):
        return val if val not in (None, "", []) else "&nbsp;________________________&nbsp;"
    
    # Get today's date in proper format for legal contracts
    today_date = datetime.now().strftime("%d %B %Y")

    # bng units list items
    bng_html = ""
    bngs = contract.get("bng_units") or []
    if bngs:
        for u in bngs:
            habitat = u.get("habitat_name") or u.get("habitat") or "habitat"
            units = u.get("units_required") or u.get("units") or ""
            bng_html += f"<li style='margin-bottom: 8px;'>{units} {html_escape(habitat)}</li>"
    else:
        bng_html = "<li style='margin-bottom: 8px;'>________________________ distinctiveness ________________________ biodiversity net gain offsite units;</li><li style='margin-bottom: 8px;'>________________________</li>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <title>Allocation Agreement — {html_escape(contract.get('application_reference') or '')}</title>
      <style>
        @page {{
          size: A4;
          margin: 2.5cm;
        }}
        body {{
          font-family: 'Times New Roman', Times, serif;
          font-size: 12pt;
          line-height: 1.6;
          margin: 0;
          padding: 20px;
          color: #000;
          max-width: 21cm;
          margin: 0 auto;
        }}
        h1 {{
          text-align: center;
          font-size: 16pt;
          font-weight: bold;
          margin: 20px 0;
          text-transform: uppercase;
        }}
        h2 {{
          text-align: center;
          font-size: 14pt;
          font-weight: bold;
          margin: 15px 0;
        }}
        h3 {{
          font-size: 12pt;
          font-weight: bold;
          margin: 15px 0 10px 0;
          text-decoration: underline;
        }}
        h4 {{
          font-size: 12pt;
          font-weight: bold;
          margin: 12px 0 6px 0;
        }}
        p {{
          margin: 8px 0;
          text-align: justify;
        }}
        .defined-term {{
          font-weight: bold;
        }}
        .party-details {{
          margin-left: 40px;
        }}
        ol {{
          margin: 8px 0;
          padding-left: 30px;
        }}
        li {{
          margin-bottom: 6px;
        }}
        .signature-block {{
          margin-top: 30px;
          page-break-inside: avoid;
        }}
        .signature-line {{
          margin: 20px 0;
          border-bottom: 1px solid #000;
          width: 60%;
          display: inline-block;
        }}
        .metadata {{
          margin-top: 30px;
          padding-top: 20px;
          border-top: 2px solid #ccc;
          font-size: 10pt;
          color: #666;
        }}
        .metadata-section {{
          margin: 10px 0;
        }}
        hr {{
          border: none;
          border-top: 1px solid #000;
          margin: 20px 0;
        }}
        @media print {{
          body {{
            padding: 0;
          }}
          .metadata {{
            page-break-before: always;
          }}
        }}
      </style>
    </head>
    <body>
      <h1>Allocation Agreement</h1>
      
      <h2>This Contract is dated {today_date}</h2>

      <p>and made on the following terms and incorporating the Conditions and, where Applicable, the Schedule:</p>

      <h3>Parties</h3>
      
      <p class="party-details">
        <span class="defined-term">WILD CAPITAL 1 LTD</span> (company number 14747595) of Lynton House, 7-12 Tavistock Square, London, WC1H 9BQ ("<span class="defined-term">Wild Capital</span>"); and
      </p>
      
      <p class="party-details">
        <span class="defined-term">{html_escape(contract.get('developer_name') or '________________________')}</span> (company number {html_escape(contract.get('developer_company_number') or '________________________')}) whose registered office is at {html_escape(contract.get('development_land') or '________________________')} ("<span class="defined-term">Developer</span>").
      </p>

      <h3>Defined Terms</h3>

      <h4>Application Reference Number</h4>
      <p>{html_escape(answers.get('planningRef') or contract.get('application_reference') or '________________________')}</p>

      <h4>BNG Units</h4>
      <p>From the Wild Capital {html_escape(contract.get('wild_capital_habitat_bank') or '________________________')} Habitat Bank:</p>
      <ol>
        {bng_html}
      </ol>

      <h4>Development Land</h4>
      <p>{html_escape(contract.get('development_land') or '________________________')}</p>

      <h4>Wild Capital Habitat Bank(s)</h4>
      <p>{html_escape(contract.get('wild_capital_habitat_bank') or '________________________')}</p>

      <h4>Conservation Covenant</h4>
      <p>means a conservation covenant dated {html_escape(contract.get('conservation_covenant_date') or '________________________')} and made between {html_escape(contract.get('developer_name') or '________________________')} in respect of the Wild Capital Habitat Bank(s).</p>

      <h4>Purchase Price</h4>
      <p>means {html_escape(contract.get('purchase_price') or contract.get('total_with_admin') or '________________________')} (exclusive of VAT)</p>

      <h4>Reservation Fee</h4>
      <p>{html_escape(contract.get('reservation_fee') or '________________________')}</p>

      <h4>Transaction Fee</h4>
      <p>{html_escape(contract.get('transaction_fee') or '________________________')}</p>

      <h4>Longstop Date</h4>
      <p>{html_escape(contract.get('longstop_date') or '________________________')}</p>

      <div class="signature-block">
        <h3>Signatures</h3>
        
        <p>Signed for and on behalf of <span class="defined-term">Wild Capital</span>:</p>
        <p><span class="signature-line">&nbsp;</span></p>
        
        <p>Signed for and on behalf of the <span class="defined-term">Developer</span>:</p>
        <p><span class="signature-line">&nbsp;</span></p>
      </div>

      <div class="metadata">
        <div class="metadata-section">
          <strong>Contract Type Selected:</strong> {html_escape('Buy It Now' if answers.get('contractType') == 'buyNow' else 'Reservation and Purchase' if answers.get('contractType') == 'reservation' else 'Not specified')}
        </div>
        
        <div class="metadata-section">
          <strong>Important Dates (for reference only):</strong>
          <ul style="margin: 5px 0; padding-left: 20px;">
            <li>Expected Determination date: {html_escape(answers.get('determinationDate') or 'Not specified')}</li>
            <li>BNG discharge hoped date: {html_escape(answers.get('dischargeDate') or 'Not specified')}</li>
          </ul>
        </div>

        <div class="metadata-section">
          <strong>Authorised Signatory:</strong>
          <p style="margin: 5px 0;">{html_escape(answers.get('authorisedName') or 'Not specified')} — {html_escape(answers.get('authorisedEmail') or 'Not specified')}</p>
        </div>

        <div class="metadata-section" style="margin-top: 15px; font-style: italic;">
          <p>Preview generated on {today_date} from contract data and the answers you provided. The metadata section above is for reference only and not part of the legal contract.</p>
        </div>
      </div>
    </body>
    </html>
    """
    return html


    def show(val):
        return val if val not in (None, "", []) else "&nbsp;________________________&nbsp;"

    # bng units list items
    bng_html = ""
    bngs = contract.get("bng_units") or []
    if bngs:
        for u in bngs:
            habitat = u.get("habitat_name") or u.get("habitat") or "habitat"
            units = u.get("units_required") or u.get("units") or ""
            bng_html += f"<li>{units} {html_escape(habitat)}</li>"
    else:
        bng_html = "<li>________________________ distinctiveness ________________________ biodiversity net gain offsite units;</li><li>________________________</li>"

    html = f"""
    <html>
    <head>
      <meta charset="utf-8"/>
      <title>Contract preview — {html_escape(contract.get('application_reference') or '')}</title>
      <style>
        body {{ font-family: serif; margin: 28px; color: #111; }}
        h2 {{ text-align: center; }}
        .section {{ margin-bottom: 14px; }}
        .small {{ font-size: 0.95em; color: #333; }}
        .muted {{ color: #666; font-size: 0.9em; }}
      </style>
    </head>
    <body>
      <h2>This Contract is dated {show('')}</h2>

      <p>and made on the following terms and incorporating the Conditions and, where Applicable, the Schedule:</p>

      <h3>Parties</h3>
      <p>
        WILD CAPITAL 1 LTD (company number 14747595) of Lynton House, 7-12 Tavistock Square, London, WC1H 9BQ (“Wild Capital”); and
      </p>
      <p>
        <strong>{html_escape(contract.get('developer_name') or '')}</strong> (company number {html_escape(contract.get('developer_company_number') or '')}) whose registered office is at {html_escape(contract.get('development_land') or '')} (“Developer”).
      </p>

      <h4>Application Reference Number</h4>
      <p>{html_escape(answers.get('planningRef') or contract.get('application_reference') or '')}</p>

      <h4>BNG Units</h4>
      <p>From the Wild {html_escape(contract.get('wild_capital_habitat_bank') or '')} Habitat Bank:</p>
      <ol>
        {bng_html}
      </ol>

      <h4>Development Land</h4>
      <p>{html_escape(contract.get('development_land') or '')}</p>

      <h4>Wild Capital Habitat Bank(s)</h4>
      <p>{html_escape(contract.get('wild_capital_habitat_bank') or '')}</p>

      <h4>Conservation Covenant</h4>
      <p>means a conservation covenant dated {html_escape(contract.get('conservation_covenant_date') or '')} and made between {html_escape(contract.get('developer_name') or '')} in respect of the Wild Capital Habitat Bank(s).</p>

      <h4>Purchase Price</h4>
      <p>means {html_escape(contract.get('purchase_price') or contract.get('total_with_admin') or '')} (exclusive of VAT)</p>

      <h4>Reservation Fee</h4>
      <p>{html_escape(contract.get('reservation_fee') or '')}</p>

      <h4>Transaction Fee</h4>
      <p>{html_escape(contract.get('transaction_fee') or '')}</p>

      <h4>Longstop Date</h4>
      <p>{html_escape(contract.get('longstop_date') or '')}</p>

      <hr/>

      <p class="small">Preferred contract type chosen: <strong>{html_escape('Buy It Now' if answers.get('contractType') == 'buyNow' else 'Reservation and Purchase' if answers.get('contractType') == 'reservation' else '')}</strong></p>

      <h4>Signatures</h4>
      <p>Signed for and on behalf of Wild Capital:……………..……………………………………………….</p>
      <p>Signed for and on behalf of the Developer:…………………………………………………………..</p>

      <div class="section small">
        <strong>Important dates filled by user (not stored):</strong>
        <ul>
          <li>Expected Determination date: {html_escape(answers.get('determinationDate') or '')}</li>
          <li>BNG discharge hoped date: {html_escape(answers.get('dischargeDate') or '')}</li>
        </ul>
      </div>

      <div class="section small">
        <strong>Authorised signatory</strong>
        <p>{html_escape(answers.get('authorisedName') or '')} — {html_escape(answers.get('authorisedEmail') or '')}</p>
      </div>

      <div class="muted small">Preview generated from contract data and the answers you provided. These answers are not stored by this application.</div>
    </body>
    </html>
    """
    return html


# ---------- Streamlit UI ----------

st.title("Wild Capital — Contract first-page filler")
st.write("Enter a planning application reference number (e.g. BNG01549) to fetch the submission and preview the contract first page.")

col1, col2 = st.columns([2, 1])
with col1:
    ref = st.text_input("Planning application reference number", value="", placeholder="e.g. BNG01549")
with col2:
    if st.button("Fetch submission"):
        st.session_state.get_submission = True

# allow pressing fetch via keyboard
if "get_submission" not in st.session_state:
    st.session_state.get_submission = False

if ref and st.session_state.get_submission:
    conn_type, conn = get_database_connection()
    table_name = get_table_name()
    with st.spinner("Fetching submission..."):
        contract = fetch_submission_by_ref(conn_type, conn, ref.strip(), table_name)
    if not contract:
        st.error("Submission not found or an error occurred.")
    else:
        st.success("Submission loaded.")
        st.write("Reference:", contract.get("application_reference"))
        st.write("Client:", contract.get("developer_name"))
        st.write("Development land:", contract.get("development_land"))

        st.markdown("---")
        st.header("Additional questions (these values are NOT stored)")

        with st.form("additional_questions"):
            determination_date = st.date_input("What is your expected Determination date?", help="Leave blank if unknown")
            discharge_date = st.date_input("When do you hope to discharge your BNG condition?", help="Leave blank if unknown")
            purchaser_name = st.text_input("Name of the organisation or individual purchasing the BNG Units")
            purchaser_company_number = st.text_input("Company number (if a company)")
            planning_ref_display = st.text_input("Planning application reference number (displayed on contract)", value=contract.get("application_reference") or "")
            planning_address = st.text_input("Planning application address", value=str(contract.get("site_location_full") or ""))
            authorised_name = st.text_input("Name of the authorised signatory")
            authorised_email = st.text_input("Email address of the authorised signatory")
            contract_type = st.radio("Preferred contract type", options=["Buy It Now", "Reservation and Purchase"], index=0)
            submitted = st.form_submit_button("Update preview (not stored)")

        if submitted:
            answers = {
                "determinationDate": determination_date.isoformat() if determination_date else "",
                "dischargeDate": discharge_date.isoformat() if discharge_date else "",
                "purchaserName": purchaser_name,
                "purchaserCompanyNumber": purchaser_company_number,
                "planningRef": planning_ref_display,
                "planningAddress": planning_address,
                "authorisedName": authorised_name,
                "authorisedEmail": authorised_email,
                "contractType": "buyNow" if contract_type == "Buy It Now" else "reservation",
            }

            html = render_contract_html(contract, answers)
            st.header("Preview — First page")
            st.markdown("You can print this page using your browser (Print -> Save as PDF). Use the download button to save HTML for archiving.")
            st.components.v1.html(html, height=900, scrolling=True)

            # Download as HTML file
            st.download_button(
                label="Download preview as HTML",
                data=html,
                file_name=f"contract_preview_{contract.get('application_reference') or ref}.html",
                mime="text/html",
            )

            st.info("This preview is generated locally in your browser session; none of the additional answers are stored.")
else:
    st.info("Enter a reference and press 'Fetch submission' to load a contract.")
