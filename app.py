#!/usr/bin/env python3
"""
Streamlit app: Wild Capital — Contract first-page filler

- Connects to Supabase to fetch a submission by reference_number (table: submissions)
- Presents a form with additional questions (not stored)
- Renders a first-page contract preview and lets user download HTML (print to PDF via browser)
"""

import os
import json
from typing import Any, Dict, List, Optional

import streamlit as st

# supabase-py client
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = Any

st.set_page_config(page_title="Wild Capital — Contract filler", layout="wide")


# ---------- Helpers ----------

def get_supabase_client():
    """
    Prefer st.secrets, then environment variables.
    Set in Streamlit Cloud as secrets: SUPABASE_URL and SUPABASE_KEY
    """
    url = None
    key = None
    # streamlit secrets take precedence
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        st.warning("SUPABASE_URL and SUPABASE_KEY not found in st.secrets or environment.")
        return None

    if create_client is None:
        st.error("supabase package not installed. See requirements.txt and install it.")
        return None

    return create_client(url, key)


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


def fetch_submission_by_ref(supabase: Client, ref: str) -> Optional[Dict]:
    """
    Query the 'submissions' table by reference_number.
    Returns a parsed dictionary or None.
    """
    if not supabase:
        return None
    try:
        resp = supabase.table("submissions").select("*").eq("reference_number", ref).limit(1).execute()
    except Exception as e:
        st.error(f"Supabase query failed: {e}")
        return None

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
    """
    def show(val):
        return val if val not in (None, "", []) else "&nbsp;________________________&nbsp;"

    # bng units list items
    bng_html = ""
    bngs = contract.get("bng_units") or []
    if bngs:
        for u in bngs:
            habitat = u.get("habitat_name") or u.get("habitat") or "habitat"
            units = u.get("units_required") or u.get("units") or ""
            bng_html += f"<li>{units} {st.escape(habitat)}</li>"
    else:
        bng_html = "<li>________________________ distinctiveness ________________________ biodiversity net gain offsite units;</li><li>________________________</li>"

    html = f"""
    <html>
    <head>
      <meta charset="utf-8"/>
      <title>Contract preview — {st.escape(contract.get('application_reference') or '')}</title>
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
        <strong>{st.escape(contract.get('developer_name') or '')}</strong> (company number {st.escape(contract.get('developer_company_number') or '')}) whose registered office is at {st.escape(contract.get('development_land') or '')} (“Developer”).
      </p>

      <h4>Application Reference Number</h4>
      <p>{st.escape(answers.get('planningRef') or contract.get('application_reference') or '')}</p>

      <h4>BNG Units</h4>
      <p>From the Wild {st.escape(contract.get('wild_capital_habitat_bank') or '')} Habitat Bank:</p>
      <ol>
        {bng_html}
      </ol>

      <h4>Development Land</h4>
      <p>{st.escape(contract.get('development_land') or '')}</p>

      <h4>Wild Capital Habitat Bank(s)</h4>
      <p>{st.escape(contract.get('wild_capital_habitat_bank') or '')}</p>

      <h4>Conservation Covenant</h4>
      <p>means a conservation covenant dated {st.escape(contract.get('conservation_covenant_date') or '')} and made between {st.escape(contract.get('developer_name') or '')} in respect of the Wild Capital Habitat Bank(s).</p>

      <h4>Purchase Price</h4>
      <p>means {st.escape(contract.get('purchase_price') or contract.get('total_with_admin') or '')} (exclusive of VAT)</p>

      <h4>Reservation Fee</h4>
      <p>{st.escape(contract.get('reservation_fee') or '')}</p>

      <h4>Transaction Fee</h4>
      <p>{st.escape(contract.get('transaction_fee') or '')}</p>

      <h4>Longstop Date</h4>
      <p>{st.escape(contract.get('longstop_date') or '')}</p>

      <hr/>

      <p class="small">Preferred contract type chosen: <strong>{st.escape('Buy It Now' if answers.get('contractType') == 'buyNow' else 'Reservation and Purchase' if answers.get('contractType') == 'reservation' else '')}</strong></p>

      <h4>Signatures</h4>
      <p>Signed for and on behalf of Wild Capital:……………..……………………………………………….</p>
      <p>Signed for and on behalf of the Developer:…………………………………………………………..</p>

      <div class="section small">
        <strong>Important dates filled by user (not stored):</strong>
        <ul>
          <li>Expected Determination date: {st.escape(answers.get('determinationDate') or '')}</li>
          <li>BNG discharge hoped date: {st.escape(answers.get('dischargeDate') or '')}</li>
        </ul>
      </div>

      <div class="section small">
        <strong>Authorised signatory</strong>
        <p>{st.escape(answers.get('authorisedName') or '')} — {st.escape(answers.get('authorisedEmail') or '')}</p>
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
    supabase = get_supabase_client()
    with st.spinner("Fetching submission..."):
        contract = fetch_submission_by_ref(supabase, ref.strip())
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
