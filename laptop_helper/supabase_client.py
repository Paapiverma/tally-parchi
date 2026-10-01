"""
supabase_client.py – all Supabase interactions.

Tables assumed (see schema.sql):
    parchis      – one row per parchi (id, party, date, status, ...)
    parchi_items – one row per line item (parchi_id FK, item_name, qty, unit)
    masters      – cached party/item/unit data from Tally
"""
from supabase import create_client, Client
from config import config

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
    return _client


# ─── Auth ────────────────────────────────────────────────────────────────────

def login(email: str, password: str) -> dict:
    """Returns {"ok": True} or {"ok": False, "reason": "..."}"""
    try:
        sb = get_client()
        res = sb.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            return {"ok": True}
        return {"ok": False, "reason": "Login failed."}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ─── Parchis ─────────────────────────────────────────────────────────────────

def get_pending_parchis() -> list[dict]:
    """Fetch all parchis with status PENDING."""
    try:
        sb = get_client()
        res = (
            sb.table("parchis")
            .select("*, parchi_items(*)")
            .eq("status", "PENDING")
            .order("created_at")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        print(f"[supabase] get_pending_parchis error: {exc}")
        return []


def get_sent_parchis() -> list[dict]:
    """Fetch parchis with status SENT_TO_TALLY (for monitor tab)."""
    try:
        sb = get_client()
        res = (
            sb.table("parchis")
            .select("*, parchi_items(*)")
            .eq("status", "SENT_TO_TALLY")
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        print(f"[supabase] get_sent_parchis error: {exc}")
        return []


def update_status(parchi_id: str, status: str, error_msg: str = "") -> bool:
    """Update the status field (and optionally error_message) of a parchi."""
    try:
        sb = get_client()
        payload = {"status": status}
        if error_msg:
            payload["error_message"] = error_msg
        sb.table("parchis").update(payload).eq("parchi_id", parchi_id).execute()
        return True
    except Exception as exc:
        print(f"[supabase] update_status error: {exc}")
        return False


def void_parchi(parchi_id: str) -> bool:
    """Set status to VOID (only allowed when PENDING)."""
    return update_status(parchi_id, "VOID")


# ─── Masters ─────────────────────────────────────────────────────────────────

def upsert_masters(masters: dict) -> bool:
    """
    Upsert synced masters into the 'masters' table.
    masters = {"parties": [...], "items": [...], "units": [...]}
    """
    try:
        sb = get_client()
        # Clear and rewrite is simplest for a prototype
        sb.table("masters").delete().neq("id", 0).execute()
        rows = []
        for name in masters.get("parties", []):
            rows.append({"type": "PARTY", "name": name, "unit": None})
        for item in masters.get("items", []):
            rows.append({"type": "ITEM", "name": item["name"], "unit": item.get("unit")})
        for unit in masters.get("units", []):
            rows.append({"type": "UNIT", "name": unit, "unit": None})
        if rows:
            sb.table("masters").insert(rows).execute()
        return True
    except Exception as exc:
        print(f"[supabase] upsert_masters error: {exc}")
        return False
