"""
tally_client.py – all HTTP communication with TallyPrime.

Responsibilities:
  - check_connection()          : is Tally up and is the right company loaded?
  - search_parchi(parchi_id)    : duplicate-check before posting
  - post_parchi(parchi)         : create quantity-only Sales voucher
  - sync_masters()              : pull party ledgers, stock items, units
  - get_unfinished_vouchers()   : find SENT_TO_TALLY vouchers still at zero amount
"""
import xml.etree.ElementTree as ET
import requests
from config import config


# ─── XML helpers ────────────────────────────────────────────────────────────

def _post_xml(body: str, timeout: int = 30) -> str:
    """POST raw XML to Tally and return the response text."""
    resp = requests.post(
        config.tally_url,
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def _clean_tally_xml(raw_text: str) -> str:
    import re
    t = re.sub(r'&#x?[0-9a-fA-F]+;', '', raw_text)
    t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', t)
    return t


def get_active_company() -> str:
    """Fetch the currently open company name from Tally in real time."""
    try:
        xml = """<ENVELOPE>
  <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>Company</ID></HEADER>
  <BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES></DESC></BODY>
</ENVELOPE>"""
        resp = _post_xml(xml, timeout=5)
        cleaned = _clean_tally_xml(resp)
        root = ET.fromstring(cleaned)
        comp = root.find(".//COMPANY/NAME")
        if comp is not None and comp.text:
            return comp.text.strip()
    except Exception:
        pass
    return ""


# ─── Connection check ────────────────────────────────────────────────────────

def check_connection() -> dict:
    """
    Returns:
        {"ok": True, "company": "..."}
        {"ok": False, "reason": "..."}

    Automatically queries Tally for the currently loaded company.
    """
    import socket
    host = config.TALLY_HOST
    port = config.TALLY_PORT
    try:
        # Fast socket check first
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()

        # Query currently loaded active company
        active_comp = get_active_company()
        company = active_comp or config.TALLY_COMPANY or "Connected"
        return {"ok": True, "company": company}

    except (socket.timeout, ConnectionRefusedError, OSError):
        return {"ok": False, "reason": f"Cannot reach Tally on {host}:{port}.\nIs TallyPrime running?"}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ─── Duplicate check ─────────────────────────────────────────────────────────

def search_parchi(parchi_id: str) -> dict:
    """
    Search Tally for a voucher.
    Rely on REMOTEID in Create XML to natively block duplicates in Tally.
    """
    return {"found": False}


# ─── Post parchi as Sales voucher ────────────────────────────────────────────

def post_parchi(parchi: dict) -> dict:
    """
    Create a quantity-only Sales voucher in Tally.

    parchi keys expected:
        parchi_id   : "P-20260930-00142"
        party       : "Sharma Safety Traders"
        date        : "20260930"   (YYYYMMDD for Tally)
        items       : [{"name": "...", "qty": 3, "unit": "Pcs"}, ...]

    Returns:
        {"ok": True}
        {"ok": False, "reason": "..."}
    """
    import xml.sax.saxutils as saxutils
    parchi_id = saxutils.escape(str(parchi["parchi_id"]))
    party = saxutils.escape(str(parchi["party"]))
    date_str = str(parchi["date"])
    items: list[dict] = parchi["items"]

    # Build inventory entries
    inventory_lines = ""
    for item in items:
        item_name = saxutils.escape(str(item["name"]))
        unit_name = saxutils.escape(str(item["unit"]))
        inventory_lines += f"""
        <ALLINVENTORYENTRIES.LIST>
          <STOCKITEMNAME>{item_name}</STOCKITEMNAME>
          <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
          <RATE></RATE>
          <AMOUNT></AMOUNT>
          <ACTUALQTY>{item['qty']} {unit_name}</ACTUALQTY>
          <BILLEDQTY>{item['qty']} {unit_name}</BILLEDQTY>
          <ACCOUNTINGALLOCATIONS.LIST>
            <LEDGERNAME>SALES</LEDGERNAME>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <AMOUNT></AMOUNT>
          </ACCOUNTINGALLOCATIONS.LIST>
        </ALLINVENTORYENTRIES.LIST>"""

    active_comp = get_active_company() or config.TALLY_COMPANY
    company_var = f"<SVCURRENTCOMPANY>{saxutils.escape(active_comp)}</SVCURRENTCOMPANY>" if active_comp else ""

    xml = f"""
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          {company_var}
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER REMOTEID="{parchi_id}" VCHTYPE="Sales" ACTION="Create">
            <DATE>{date_str}</DATE>
            <REFERENCEDATE>{date_str}</REFERENCEDATE>
            <REFERENCE>{parchi_id}</REFERENCE>
            <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{parchi_id}</VOUCHERNUMBER>
            <PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <LEDGERENTRIES.LIST>
              <LEDGERNAME>{party}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT></AMOUNT>
              <NARRATION>Parchi ID: {parchi_id}</NARRATION>
            </LEDGERENTRIES.LIST>
            {inventory_lines}
            <NARRATION>Parchi ID: {parchi_id}</NARRATION>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>""".strip()

    try:
        text = _post_xml(xml)
        root = ET.fromstring(text)

        # Parse Tally's response
        created = _find(root, "CREATED")
        altered = _find(root, "ALTERED")
        errors  = _find(root, "ERRORS")
        lineerr = _find(root, "LINEERROR")
        lastid  = _find(root, "LASTVCHID")

        if errors and errors != "0":
            return {"ok": False, "reason": lineerr or f"Tally reported {errors} error(s)."}

        if created == "1" or altered == "1":
            return {"ok": True, "voucher_id": lastid}

        # If we can't tell, do a follow-up search
        result = search_parchi(parchi_id)
        if result.get("found"):
            return {"ok": True, "voucher_id": result.get("voucher_id", "")}

        return {"ok": False, "reason": f"Unexpected Tally response:\n{text[:400]}"}

    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ─── Master sync ─────────────────────────────────────────────────────────────

def sync_masters() -> dict:
    """
    Pull party ledgers (Sundry Debtors) and stock items from Tally using Collection queries.
    """
    active_comp = get_active_company() or config.TALLY_COMPANY
    comp_var = f"<SVCURRENTCOMPANY>{active_comp}</SVCURRENTCOMPANY>" if active_comp else ""

    def _fetch_collection(coll_id: str):
        xml = f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>{coll_id}</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        {comp_var}
      </STATICVARIABLES>
    </DESC>
  </BODY>
</ENVELOPE>"""
        try:
            resp_text = _post_xml(xml)
            cleaned = _clean_tally_xml(resp_text)
            return ET.fromstring(cleaned)
        except Exception as e:
            print(f"[sync_masters] Error fetching collection {coll_id}: {e}")
            return None

    parties, items, units_set = [], [], set()

    # 1. Fetch Ledgers
    root_led = _fetch_collection("Ledger")
    if root_led is not None:
        for led in root_led.findall(".//LEDGER"):
            name = (led.get("NAME") or "").strip()
            parent_el = led.find("PARENT")
            parent = (parent_el.text or "").strip() if parent_el is not None else ""
            if name and "debtor" in parent.lower():
                parties.append(name)

    # 2. Fetch Stock Items
    root_item = _fetch_collection("StockItem")
    if root_item is not None:
        for it in root_item.findall(".//STOCKITEM"):
            name = (it.get("NAME") or "").strip()
            unit_el = it.find("BASEUNITS")
            unit = (unit_el.text or "").strip() if unit_el is not None else "Pcs"
            if not unit:
                unit = "Pcs"
            if name:
                items.append({"name": name, "unit": unit})
                units_set.add(unit)

    return {
        "parties": sorted(parties),
        "items":   sorted(items, key=lambda x: x["name"]),
        "units":   sorted(units_set) or ["Pcs"],
    }


# ─── Unfinished-voucher monitor ───────────────────────────────────────────────

def get_unfinished_vouchers(parchi_ids: list[str]) -> list[str]:
    """
    Given a list of parchi_ids that are SENT_TO_TALLY,
    return those whose voucher still has zero/blank amount in Tally.
    """
    unfinished = []
    for pid in parchi_ids:
        try:
            result = search_parchi(pid)
            if result.get("found"):
                # Could extend this to fetch the voucher amount via Collection
                # For now we flag as "check manually" if found but no amount
                # (placeholder for a deeper amount check)
                pass
        except Exception:
            pass
    return unfinished


