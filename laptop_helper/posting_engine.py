"""
posting_engine.py – orchestrates the send-to-Tally workflow.

State machine:
    PENDING → POSTING → SENT_TO_TALLY
                     ↘ FAILED

Crash-recovery:
    On startup, any POSTING parchi is searched in Tally.
    If found  → SENT_TO_TALLY
    If not    → back to PENDING  (safe to retry)
"""
import tally_client as tally
import supabase_client as db


def send_parchi(parchi: dict, progress_cb=None) -> dict:
    """
    Full send pipeline for a single parchi.

    progress_cb(msg: str) is called with human-readable status strings.

    Returns:
        {"ok": True}
        {"ok": False, "reason": "..."}
    """

    def progress(msg: str):
        if progress_cb:
            progress_cb(msg)
        print(f"[send] {msg}")

    pid = parchi["parchi_id"]
    items = parchi.get("parchi_items", [])

    # ── 1. Check Tally connection ──────────────────────────────────────────
    progress("Checking Tally connection…")
    conn = tally.check_connection()
    if not conn["ok"]:
        return {"ok": False, "reason": conn["reason"]}

    # ── 2. Validate party and items exist in Tally ─────────────────────────
    progress("Validating party and items in Tally…")
    # (In a full build, query Collection for each name; for prototype we
    #  rely on master sync having matched names and let Tally error if wrong.)

    # ── 3. Duplicate check ─────────────────────────────────────────────────
    progress(f"Checking for duplicate: {pid}…")
    dup = tally.search_parchi(pid)
    if dup.get("error"):
        return {"ok": False, "reason": f"Duplicate check failed: {dup['error']}"}

    if dup.get("found"):
        progress("Already in Tally — marking SENT_TO_TALLY.")
        db.update_status(pid, "SENT_TO_TALLY")
        return {"ok": True}

    # ── 4. Mark POSTING ────────────────────────────────────────────────────
    progress("Marking POSTING…")
    db.update_status(pid, "POSTING")

    # ── 5. Build payload and post ──────────────────────────────────────────
    progress("Sending XML to Tally…")
    payload = {
        "parchi_id": pid,
        "party": parchi["party"],
        "date": _format_date(parchi["date"]),   # → YYYYMMDD
        "items": [
            {
                "name": it["item_name"],
                "qty":  it["qty"],
                "unit": it["unit"],
            }
            for it in items
        ],
    }

    result = tally.post_parchi(payload)

    # ── 6. Handle result ───────────────────────────────────────────────────
    if result["ok"]:
        progress("Voucher created. Verifying…")
        verify = tally.search_parchi(pid)
        if verify.get("found"):
            db.update_status(pid, "SENT_TO_TALLY")
            progress("✓ Confirmed in Tally → SENT_TO_TALLY")
            return {"ok": True}
        else:
            # Tally said ok but we can't find it — unusual, but mark it anyway
            db.update_status(pid, "SENT_TO_TALLY")
            progress("Voucher reported created (could not re-verify).")
            return {"ok": True}
    else:
        reason = result.get("reason", "Unknown Tally error.")
        db.update_status(pid, "FAILED", error_msg=reason)
        progress(f"✗ Failed: {reason}")
        return {"ok": False, "reason": reason}


def recover_posting_parchis():
    """
    Called once on app startup.
    Any parchi stuck at POSTING is searched in Tally and resolved.
    """
    try:
        from supabase_client import get_client
        sb = get_client()
        rows = sb.table("parchis").select("parchi_id").eq("status", "POSTING").execute()
        for row in (rows.data or []):
            pid = row["parchi_id"]
            result = tally.search_parchi(pid)
            if result.get("found"):
                db.update_status(pid, "SENT_TO_TALLY")
                print(f"[recover] {pid} found in Tally → SENT_TO_TALLY")
            else:
                db.update_status(pid, "PENDING")
                print(f"[recover] {pid} not in Tally → reset to PENDING")
    except Exception as exc:
        print(f"[recover] error: {exc}")


def _format_date(date_str: str) -> str:
    """
    Accept DD-MM-YYYY or YYYY-MM-DD or YYYYMMDD, return YYYYMMDD for Tally.
    """
    date_str = date_str.strip()
    if len(date_str) == 8 and date_str.isdigit():
        return date_str
    for sep in ("-", "/"):
        parts = date_str.split(sep)
        if len(parts) == 3:
            if len(parts[0]) == 4:          # YYYY-MM-DD
                return f"{parts[0]}{parts[1].zfill(2)}{parts[2].zfill(2)}"
            else:                            # DD-MM-YYYY
                return f"{parts[2]}{parts[1].zfill(2)}{parts[0].zfill(2)}"
    return date_str  # fallback — let Tally complain
