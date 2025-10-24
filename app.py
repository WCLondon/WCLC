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
    Produce a complete BNG Allocation Agreement HTML document based on the official template.
    Matches the structure and content of BNG_Allocation_Agreement_Template.md
    """
    # Get today's date in proper format for legal contracts
    today_date = datetime.now().strftime("%d %B %Y")
    
    # Helper function to show placeholder or value
    def show(val, placeholder="[●]"):
        if val and val not in (None, "", []):
            return html_escape(str(val))
        return placeholder
    
    # Extract contract values with fallbacks
    # Use purchaser info from answers if provided, otherwise fall back to contract data
    developer_name = answers.get('purchaserName') or contract.get('developer_name') or contract.get('client_name') or '[Developer]'
    developer_company_number = answers.get('purchaserCompanyNumber') or contract.get('developer_company_number') or '[●]'
    development_land = contract.get('development_land') or contract.get('site_location') or '[●]'
    app_ref = answers.get('planningRef') or contract.get('application_reference') or '[●]'
    habitat_bank = contract.get('wild_capital_habitat_bank') or '[●]'
    
    # Build BNG Units list
    bng_units_html = ""
    bngs = contract.get("bng_units") or []
    if bngs:
        for idx, u in enumerate(bngs):
            habitat = u.get("habitat_name") or u.get("habitat") or "habitat"
            units = u.get("units_required") or u.get("units") or "[●]"
            letter = chr(97 + idx)  # a, b, c, etc.
            bng_units_html += f"<li>({letter}) <strong>[{show(units, '')}] distinctiveness [{show(habitat, '')}]</strong> biodiversity net gain <strong>offsite units</strong>, and</li>"
    else:
        bng_units_html = "<li>(a) <strong>[medium] distinctiveness [grassland]</strong> biodiversity net gain <strong>offsite units</strong>, and</li><li>(b) <strong>[insert relevant units and distinctiveness]</strong>.</li>"
    
    conservation_covenant_date = contract.get('conservation_covenant_date') or '[●]'
    purchase_price = contract.get('purchase_price') or contract.get('total_with_admin') or '[●]'
    reservation_fee = contract.get('reservation_fee') or '[●]'
    transaction_fee = contract.get('transaction_fee') or '[●]'
    longstop_date = contract.get('longstop_date') or '[●]'
    
    # Get toggle values from answers
    reservation_fee_applies = answers.get('reservationFeeApplies', False)
    transaction_fee_applies = answers.get('transactionFeeApplies', False)
    longstop_date_applies = answers.get('longstopDateApplies', False)
    schedule_applies = answers.get('scheduleApplies', False)
    clause_2_applies = answers.get('clause2Applies', True)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <title>BNG Allocation Agreement — {show(app_ref, '')}</title>
      <style>
        @page {{
          size: A4;
          margin: 2.5cm;
        }}
        body {{
          font-family: 'Times New Roman', Times, serif;
          font-size: 12pt;
          line-height: 1.5;
          margin: 0;
          padding: 20px;
          color: #000;
          max-width: 21cm;
          margin: 0 auto;
        }}
        h1 {{
          text-align: center;
          font-size: 14pt;
          font-weight: bold;
          margin: 20px 0;
        }}
        h2 {{
          font-size: 12pt;
          font-weight: bold;
          margin: 20px 0 10px 0;
          text-transform: uppercase;
        }}
        h3 {{
          font-size: 12pt;
          font-weight: bold;
          margin: 15px 0 8px 0;
        }}
        h4 {{
          font-size: 12pt;
          font-weight: normal;
          font-style: italic;
          margin: 10px 0 5px 0;
        }}
        p {{
          margin: 6px 0;
          text-align: justify;
        }}
        ul, ol {{
          margin: 8px 0;
          padding-left: 30px;
        }}
        li {{
          margin-bottom: 4px;
        }}
        strong {{
          font-weight: bold;
        }}
        hr {{
          border: none;
          border-top: 1px solid #000;
          margin: 20px 0;
        }}
        table {{
          width: 100%;
          border-collapse: collapse;
          margin: 20px 0;
        }}
        table, th, td {{
          border: 1px solid #000;
        }}
        th {{
          padding: 8px;
          text-align: left;
          font-weight: bold;
          background-color: #f5f5f5;
        }}
        td {{
          padding: 8px;
          vertical-align: top;
        }}
        .signature-block {{
          margin: 15px 0;
        }}
        .signature-line {{
          display: inline-block;
          width: 200px;
          border-bottom: 1px solid #000;
        }}
        .indent {{
          margin-left: 30px;
        }}
        .metadata {{
          margin-top: 40px;
          padding-top: 20px;
          border-top: 2px solid #ccc;
          font-size: 10pt;
          color: #666;
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
      <p><strong>This Contract is dated [{today_date}]</strong></p>
      
      <p>and made on the following terms and incorporating the Conditions and, where Applicable, the Schedule:</p>
      
      <table>
        <tr>
          <th rowspan="2" style="width: 30%;">Parties</th>
          <td><strong>(1) WILD CAPITAL 1 LTD</strong> (company number <strong>14747595</strong>) of Lynton House, 7–12 Tavistock Square, London, WC1H 9BQ ("<strong>Wild Capital</strong>"); and</td>
        </tr>
        <tr>
          <td><strong>(2) {show(developer_name)}</strong> (company number <strong>{show(developer_company_number)}</strong>) whose registered office is at <strong>{show(development_land)}</strong> ("<strong>Developer</strong>").</td>
        </tr>
        
        <tr>
          <th>Application Reference Number</th>
          <td>{show(app_ref)}</td>
        </tr>
        
        <tr>
          <th>BNG Units</th>
          <td>
            From the Wild <strong>{show(habitat_bank)}</strong> Habitat Bank:
            <ul style="margin: 5px 0; padding-left: 20px;">
              {bng_units_html}
            </ul>
          </td>
        </tr>
        
        <tr>
          <th>Development Land</th>
          <td>{show(development_land)}</td>
        </tr>
        
        <tr>
          <th>Wild Capital Habitat Bank(s)</th>
          <td>{show(habitat_bank)}</td>
        </tr>
        
        <tr>
          <th>Conservation Covenant</th>
          <td>means a conservation covenant dated <strong>{show(conservation_covenant_date)}</strong> and made between <strong>{show(developer_name)}</strong> in respect of the Wild Capital Habitat Bank(s).</td>
        </tr>
        
        <tr>
          <th>Purchase Price</th>
          <td>means <strong>{show(purchase_price)}</strong> (<strong>{show('[[£ amount in words]]', '[[£ amount in words]]')}</strong>) <strong>(exclusive of VAT)</strong> {'<strong>[and Clause 2.1 is not applicable]</strong>' if not clause_2_applies else ''}</td>
        </tr>
        
        <tr>
          <th>Reservation Fee</th>
          <td><strong>{show(reservation_fee) if reservation_fee_applies else '[●]'}</strong> <strong>(exclusive of VAT)</strong> {'<strong>[or]</strong> <strong>[Not applicable]</strong>' if not reservation_fee_applies else ''}</td>
        </tr>
        
        <tr>
          <th>Transaction Fee</th>
          <td><strong>{show(transaction_fee) if transaction_fee_applies else '[●]'}</strong> <strong>(exclusive of VAT)</strong> {'<strong>[or]</strong> <strong>[Not applicable]</strong>' if not transaction_fee_applies else ''}</td>
        </tr>
        
        <tr>
          <th>Longstop Date</th>
          <td><strong>{show(longstop_date) if longstop_date_applies else '[●]'}</strong> {'<strong>[or]</strong> <strong>[Not applicable]</strong>' if not longstop_date_applies else ''}</td>
        </tr>
        
        <tr>
          <th>The terms of the Schedule apply to this agreement</th>
          <td><strong>{'Yes' if schedule_applies else 'No'}</strong></td>
        </tr>
        
        <tr>
          <th>The terms of Clause 2.1 and 2.2 of the Conditions apply to this agreement</th>
          <td><strong>{'Yes' if clause_2_applies else 'No'}</strong></td>
        </tr>
        
        <tr>
          <th>Signatures</th>
          <td>
            <div class="signature-block">
              <p>Signed for and on behalf of Wild Capital: <span class="signature-line">&nbsp;</span></p>
            </div>
            <div class="signature-block">
              <p>Signed for and on behalf of the Developer: <span class="signature-line">&nbsp;</span></p>
            </div>
          </td>
        </tr>
      </table>
      
      <hr/>
      
      <h2>SIGNATURES</h2>
      
      <div class="signature-block">
        <p>Signed for and on behalf of <strong>WILD CAPITAL 1 LTD</strong><br/>
        Name: <span class="signature-line">&nbsp;</span> &nbsp; Title: <span class="signature-line">&nbsp;</span> &nbsp; Date: <span class="signature-line">&nbsp;</span></p>
      </div>
      
      <div class="signature-block">
        <p>Signed for and on behalf of <strong>{show(developer_name)}</strong><br/>
        Name: <span class="signature-line">&nbsp;</span> &nbsp; Title: <span class="signature-line">&nbsp;</span> &nbsp; Date: <span class="signature-line">&nbsp;</span></p>
      </div>
      
      <hr style="page-break-after: always;"/>
      
      <h1><strong>CONDITIONS</strong></h1>
      
      <h2>BACKGROUND</h2>
      <p>A. Wild Capital operates habitat banks and is able to produce biodiversity net gain offsite units ("<strong>BNG Units</strong>").</p>
      <p>B. Under the <strong>Environment Act 2021</strong>, developments must deliver a minimum <strong>10% biodiversity net gain</strong> and the developer must evidence BNG to the <strong>local planning authority</strong> (the "<strong>Determining Authority</strong>").</p>
      <p>C. The Developer wishes to allocate BNG Units to the <strong>Development Land</strong>.</p>
      <p>D. Wild Capital agrees to allocate BNG Units on the terms of this Agreement.</p>
      
      <hr/>
      
      <h2>AGREED TERMS</h2>
      
      <h3>1. DEFINITIONS and Interpretations</h3>
      <p>In this Agreement the following terms have the meanings set out below:</p>
      
      <p><strong>Application</strong> means the application associated with the <strong>Application Reference Number</strong> on the front sheet.</p>
      
      <p><strong>BNG Capacity</strong> means the area of the <strong>Mitigation Site</strong> allocated on the <strong>Gain Site Register</strong>.</p>
      
      <p><strong>BNG Units</strong> means the offsite units specified on the front sheet (or such other habitat types of <strong>equivalent or higher distinctiveness</strong>) calculated using the <strong>BNG Metric</strong>, taking into account the <strong>Spatial Risk Multiplier</strong> and <strong>Trading Rules</strong> as set out in the <strong>Statutory Biodiversity Metric User Guide</strong> (DEFRA, as updated from time to time, including the version updated <strong>3 July 2025</strong>).</p>
      
      <p><strong>BNG Metric</strong> means the statutory biodiversity metric published by <strong>DEFRA</strong> (or any replacement metric).</p>
      
      <p><strong>Conservation Covenant</strong> has the meaning given on the front sheet and governs creation and management of BNG Units at the <strong>Mitigation Site</strong>.</p>
      
      <p><strong>Determining Authority</strong> means the relevant local planning authority for the <strong>Development Land</strong>.</p>
      
      <p><strong>Development Land</strong> means the land identified on the front sheet.</p>
      
      <p><strong>Electronic Payment</strong> means payment in same‑day cleared funds to the payee's nominated bank account.</p>
      
      <p><strong>Exchange Payment</strong> means <strong>£1.00</strong> <strong>(exclusive of VAT)</strong> payable by the Developer to Wild Capital on the date of this Agreement.</p>
      
      <p><strong>Gain Site Register</strong> means the <strong>Biodiversity Gain Site Register</strong> maintained pursuant to <strong>section 100 of the Environment Act 2021</strong>.</p>
      
      <p><strong>Habitat Bank</strong> means any Wild Capital habitat creation and management site from which BNG Units are produced.</p>
      
      <p><strong>Mitigation Site</strong> means the land comprising the relevant <strong>Habitat Bank</strong>.</p>
      
      <p><strong>Notice of Allocation</strong> means the formal notice to the Determining Authority confirming allocation of BNG Units to the <strong>Development Land</strong> in accordance with the <strong>Conservation Covenant</strong> and the <strong>BNG Metric</strong>.</p>
      
      <p><strong>Party</strong> and <strong>Parties</strong> mean each party named on the front sheet and both of them together.</p>
      
      <p><strong>Planning Permission</strong> means a planning permission granted for the Development Land to which the BNG Units relate.</p>
      
      <p><strong>Purchase Price</strong> has the meaning on the front sheet and is payable as provided in these Conditions.</p>
      
      <p><strong>Transaction fee</strong> means the administration/transaction fee (if applicable) identified on the front sheet.</p>
      
      <p><strong>VAT</strong> means value added tax chargeable under the <strong>Value Added Tax Act 1994</strong> and any similar replacement tax.</p>
      
      <p><strong>Working Days</strong> means <strong>Monday to Friday</strong> other than <strong>Good Friday</strong> and the period <strong>24 December through 2 January (inclusive)</strong>.</p>
      
      <p><strong>Interpretation.</strong> Clause headings are for convenience only and do not affect interpretation. Words in the singular include the plural and vice versa. References to legislation include amendments and re‑enactments.</p>
      
      <hr/>
      
      <h3>2. AGREEMENT and Notice of Allocation</h3>
      <p>2.1 In consideration of the <strong>Exchange Payment</strong> paid on the date of this Agreement, Wild Capital agrees to allocate the <strong>BNG Units</strong> to the <strong>Development Land</strong> on and subject to these Conditions <strong>[this Clause 2.1 applies only if ticked "Yes" on the front sheet]</strong>.</p>
      <p>2.2 Within <strong>5 Working Days</strong> of receipt by Wild Capital of (a) the <strong>Purchase Price</strong> by <strong>Electronic Payment</strong> and (b) a copy of the relevant <strong>Planning Permission decision notice</strong> (and any associated information reasonably required), Wild Capital will:<br/>
      &nbsp;&nbsp;&nbsp;&nbsp;(a) <strong>serve the Notice of Allocation</strong> on the <strong>Determining Authority</strong>; and<br/>
      &nbsp;&nbsp;&nbsp;&nbsp;(b) <strong>update/apply to update the Gain Site Register</strong> to record the allocation of BNG Units to the <strong>Development Land</strong>.</p>
      
      <hr/>
      
      <h3>3. TITLE and Assignment</h3>
      <p>3.1 The Developer accepts Wild Capital's title to the <strong>Mitigation Site</strong> and shall not raise requisitions or object to title. The Developer shall not register or lodge any notice, restriction or other entry against the <strong>Mitigation Site</strong>.</p>
      <p>3.2 This Agreement is <strong>personal</strong> to the Developer. The Developer shall not <strong>assign, transfer, charge or subcontract</strong> any right or obligation under this Agreement. Wild Capital is only obliged to transfer BNG Units to the <strong>owner of the Development Land</strong>.</p>
      
      <hr/>
      
      <h3>4. MATTERS AFFECTING THE PROPERTY</h3>
      <p>4.1 Allocation and registration of BNG Units is subject to and in accordance with the <strong>Conservation Covenant</strong>.</p>
      
      <hr/>
      
      <h3>5. COSTS</h3>
      <p>5.1 The Developer shall pay <strong>£500 plus VAT</strong> towards Wild Capital's administration costs on or before the date of this Agreement.</p>
      
      <hr/>
      
      <h3>6. VAT</h3>
      <p>6.1 All sums payable are <strong>exclusive of VAT</strong>. If VAT is chargeable, it shall be paid in addition at the rate in force when the relevant supply is made.</p>
      
      <hr/>
      
      <h3>7. ENTIRE AGREEMENT</h3>
      <p>7.1 This Agreement constitutes the entire agreement between the Parties and supersedes any prior discussions or representations (whether innocent or negligent) relating to its subject matter. Each Party acknowledges that it has not relied on any statement not expressly set out in this Agreement.</p>
      
      <hr/>
      
      <h3>8. CONFIDENTIAL INFORMATION</h3>
      <p>8.1 Each Party shall keep confidential and not disclose to any person any confidential information concerning the business, affairs, customers, clients or suppliers of the other Party, except to its <strong>Representatives</strong> who need to know such information for the purposes of performing this Agreement and provided such Representatives are bound by confidentiality obligations no less strict.</p>
      <p>8.2 A Party may disclose confidential information if and to the extent required by law or a competent authority, <strong>provided that this Agreement itself shall not be disclosed to the Determining Authority</strong>.</p>
      <p>8.3 Each Party acknowledges that damages alone may not be an adequate remedy and that the other Party shall be entitled to equitable relief.</p>
      
      <hr/>
      
      <h3>9. JOINT AND SEVERAL LIABILITY</h3>
      <p>9.1 Where the <strong>Developer</strong> comprises more than one person, their liability is <strong>joint and several</strong>. Wild Capital may compromise or release one or more of them without affecting the liability of the others.</p>
      
      <hr/>
      
      <h3>10. THIRD PARTY RIGHTS</h3>
      <p>10.1 The <strong>Contracts (Rights of Third Parties) Act 1999</strong> does not apply to this Agreement.</p>
      
      <hr/>
      
      <h3>11. GOVERNING LAW AND JURISDICTION</h3>
      <p>11.1 This Agreement and any non‑contractual obligations arising out of or in connection with it are governed by the <strong>law of England</strong>. The courts of <strong>England</strong> have <strong>exclusive jurisdiction</strong> to settle any dispute.</p>
      
      <hr/>
      
      <p style="text-align: center; margin: 30px 0;"><strong>THIS AGREEMENT HAS BEEN ENTERED INTO on the date stated at the beginning of it.</strong></p>
      
      <hr style="page-break-after: always;"/>
      
      <h1><strong>SCHEDULE</strong> — <strong>RESERVATION AND PURCHASE PROVISIONS</strong></h1>
      <p><em>(Apply only if selected "Yes" on the front sheet.)</em></p>
      
      <h2>A. Schedule Definitions</h2>
      <p><strong>Completion</strong> means completion of the purchase of the BNG Units pursuant to this Schedule.</p>
      <p><strong>Completion Date</strong> means the date falling <strong>10 Working Days</strong> after valid service of an <strong>Exercise Notice</strong>.</p>
      <p><strong>Completion Notice</strong> means the notice issued by Wild Capital to the Developer confirming completion together with: a copy of the <strong>Notice of Allocation</strong>, details of the <strong>Gain Site Register</strong> application/entry, and reasonable evidence of submission.</p>
      <p><strong>Exercise Notice</strong> means a notice served by the Developer exercising the right to purchase all of the BNG Units reserved under this Schedule.</p>
      <p><strong>Notice to Complete</strong> means a notice served following failure to complete by the Completion Date, making time of the essence and specifying a period of <strong>10 Working Days</strong> to complete.</p>
      <p><strong>Reservation Period</strong> means the period stated on the front sheet (or, if none is stated, <strong>[●] Working Days</strong> beginning on the date of this Agreement).</p>
      
      <hr/>
      
      <h2>B. Reservation</h2>
      <p>B1. The <strong>Reservation Fee</strong> (if any) is payable by <strong>Electronic Payment</strong> on the date of this Agreement and is <strong>non‑refundable</strong>.</p>
      <p>B2. Upon receipt of the Reservation Fee, Wild Capital will reserve the <strong>BNG Units</strong> for the <strong>Reservation Period</strong>.</p>
      <p>B3. The right to purchase <strong>lapses</strong> if not exercised before the <strong>Longstop Date</strong> (if any).</p>
      
      <hr/>
      
      <h2>C. Wild Capital Obligations</h2>
      <p>C1. If reasonably required to support the <strong>Application</strong> and requested before the <strong>Longstop Date</strong>, Wild Capital will provide <strong>one planning pack</strong> within <strong>5 Working Days</strong> of request (one pack only; the Developer must supply reasonably required particulars).</p>
      <p>C2. Subject to valid exercise of the right to purchase and except as provided at paragraph <strong>L</strong>, Wild Capital shall keep the BNG Units available for allocation until <strong>Completion</strong>.</p>
      
      <hr/>
      
      <h2>D. Right to Purchase</h2>
      <p>D1. The Developer may exercise the right to purchase by serving an <strong>Exercise Notice</strong> identifying the <strong>Development Land</strong> (by address and plan), confirming the <strong>planning reference</strong>, and attaching the <strong>decision notice</strong>.</p>
      <p>D2. Service of a valid Exercise Notice creates a <strong>binding contract</strong> for the sale of the BNG Units at the <strong>Purchase Price</strong> and on the terms of this Schedule.</p>
      
      <hr/>
      
      <h2>E. Completion</h2>
      <p>E1. <strong>Completion</strong> shall take place on the <strong>Completion Date</strong>. The Developer shall pay the <strong>Transaction fee</strong> (if applicable) by <strong>Electronic Payment</strong> on or before the Completion Date.</p>
      <p>E2. Upon receipt of all monies due, Wild Capital shall:<br/>
      &nbsp;&nbsp;&nbsp;&nbsp;(a) <strong>serve the Notice of Allocation</strong> on the <strong>Determining Authority</strong>; and<br/>
      &nbsp;&nbsp;&nbsp;&nbsp;(b) issue the <strong>Completion Notice</strong> to the Developer.</p>
      <p>E3. Within <strong>5 Working Days</strong> of the later of the <strong>Completion Date</strong> and payment of the <strong>Transaction fee</strong>, Wild Capital shall apply to <strong>Natural England</strong> for registration of the allocation on the <strong>Biodiversity Gain Site Register</strong> and shall provide confirmation details to the Developer as soon as reasonably practicable.</p>
      
      <hr/>
      
      <h2>F. Termination and Insolvency</h2>
      <p>F1. The Developer may terminate this Schedule during the <strong>Reservation Period</strong> by giving <strong>5 Working Days'</strong> written notice to Wild Capital.</p>
      <p>F2. Either Party may terminate prior to <strong>Completion</strong> on written notice if the other Party is subject to an insolvency event, including administration, receivership, winding‑up, bankruptcy, or any analogous procedure under the <strong>Insolvency Act 1986</strong> (as amended).</p>
      
      <hr/>
      
      <h2>G. Disputes</h2>
      <p>G1. Any dispute (other than a question of law or contractual interpretation) shall be referred to a <strong>Specialist</strong> with at least <strong>10 years'</strong> relevant professional experience within a reasonable distance of the <strong>Mitigation Site</strong>. If the Parties cannot agree the Specialist within <strong>10 Working Days</strong>, either Party may request nomination by an appropriate professional body (or the <strong>Law Society</strong>).</p>
      <p>G2. The Specialist shall receive written representations from the Parties and aim to issue a <strong>reasoned written decision within 30 Working Days</strong> of appointment. The Specialist's decision shall be final and binding save for manifest error.</p>
      <p>G3. Matters of law or contractual interpretation may be referred to the courts of <strong>England</strong>.</p>
      
      <hr/>
      
      <h2>H. Notices</h2>
      <p>H1. Notices under this Schedule shall be served by <strong>first‑class post</strong>, <strong>hand delivery</strong>, or <strong>email</strong>.</p>
      <p>H2. The Developer's address and email are as set out on the front sheet.</p>
      <p>H3. Wild Capital's details: <strong>Lynton House, 7–12 Tavistock Square, London, WC1H 9BQ</strong>, attention <strong>Head of Legal</strong>, email <strong>legal@wild-capital.co.uk</strong>.</p>
      <p>H4. Deemed service: by post—the earlier of actual receipt or <strong>2 Working Days</strong> after posting; by hand—on delivery; by email—on transmission if sent on a Working Day before 5pm recipient local time.</p>
      
      <hr/>
      
      <h2>I. Force Majeure</h2>
      <p>I1. Neither Party shall be liable for any delay or failure to perform caused by an event beyond its reasonable control, provided it notifies the other Party and uses reasonable endeavours to mitigate.</p>
      <p>I2. If a material obligation cannot be performed due to such event, either Party may terminate on <strong>2 weeks'</strong> written notice.</p>
      
      <hr/>
      
      <h2>J. Limitation of Liability</h2>
      <p>J1. Subject to paragraph <strong>J3</strong>, each Party's <strong>aggregate liability</strong> under or in connection with this Schedule is <strong>capped at the sum of the Reservation Fee (if any) and the Purchase Price</strong>.</p>
      <p>J2. Neither Party shall be liable for any <strong>consequential or special loss</strong>, or for loss of <strong>profit, revenue, production, contract, opportunity, anticipated savings, reputation/goodwill</strong>, or <strong>wasted expenditure</strong>.</p>
      <p>J3. Nothing in this Schedule limits or excludes liability for <strong>death or personal injury</strong>, <strong>fraud</strong>, or any liability which cannot be limited or excluded by law.</p>
      
      <hr/>
      
      <h2>K. Developer's Failure to Complete</h2>
      <p>K1. If the Developer fails to complete on the <strong>Completion Date</strong>, Wild Capital may serve a <strong>Notice to Complete</strong> making time of the essence and specifying a period of <strong>10 Working Days</strong> for completion.</p>
      <p>K2. If the Developer still fails to complete: (a) the Developer shall pay <strong>£500 + VAT</strong> towards Wild Capital's solicitors' <strong>additional</strong> costs and indemnify Wild Capital's administration costs; (b) Wild Capital may <strong>rescind</strong> the contract, <strong>forfeit</strong> the <strong>Reservation Fee</strong> (if any), <strong>resell</strong> the BNG Units, and <strong>claim damages</strong>; and (c) all other rights are reserved.</p>
      
      <hr/>
      
      <h2>L. Default Interest</h2>
      <p>L1. Any sum not paid when due shall bear <strong>interest at 8% above the Bank of England base rate</strong>, accruing daily from the due date until payment, both before and after judgment.</p>
      
      <hr/>
      
      <h2>M. Non‑Circumvention</h2>
      <p>M1. The Developer (and its group and Representatives) shall not, without Wild Capital's prior written consent, pursue or procure BNG Units with any <strong>landholder</strong> or <strong>third party</strong> introduced by Wild Capital, nor solicit, induce, or respond to approaches in relation to such units other than through Wild Capital.</p>
      
      <hr/>
      
      <div class="metadata">
        <h3>Document Information (not part of legal agreement)</h3>
        
        <p><strong>Contract Type Selected:</strong> {html_escape('Buy It Now' if answers.get('contractType') == 'buyNow' else 'Reservation and Purchase' if answers.get('contractType') == 'reservation' else 'Not specified')}</p>
        
        <p><strong>Important Dates (for reference only):</strong></p>
        <ul>
          <li>Expected Determination date: {html_escape(answers.get('determinationDate') or 'Not specified')}</li>
          <li>BNG discharge hoped date: {html_escape(answers.get('dischargeDate') or 'Not specified')}</li>
        </ul>
        
        <p><strong>Authorised Signatory:</strong> {html_escape(answers.get('authorisedName') or 'Not specified')} — {html_escape(answers.get('authorisedEmail') or 'Not specified')}</p>
        
        <p style="margin-top: 15px; font-style: italic;">Preview generated on {today_date} from contract data and the answers you provided. The metadata section above is for reference only and not part of the legal contract.</p>
      </div>
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
            
            st.markdown("### Applicability Toggles")
            st.markdown("Select which terms apply to this agreement:")
            reservation_fee_applies = st.checkbox("Reservation Fee applies", value=False)
            transaction_fee_applies = st.checkbox("Transaction Fee applies", value=False)
            longstop_date_applies = st.checkbox("Longstop Date applies", value=False)
            schedule_applies = st.checkbox("The terms of the Schedule apply to this agreement", value=(contract_type == "Reservation and Purchase"))
            clause_2_applies = st.checkbox("The terms of Clause 2.1 and 2.2 apply to this agreement", value=(contract_type == "Buy It Now"))
            
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
                "reservationFeeApplies": reservation_fee_applies,
                "transactionFeeApplies": transaction_fee_applies,
                "longstopDateApplies": longstop_date_applies,
                "scheduleApplies": schedule_applies,
                "clause2Applies": clause_2_applies,
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
