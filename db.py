import sqlite3
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "linkedin_bot.db")

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=10000;")
        # Base table creation
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                profile_url TEXT PRIMARY KEY,
                full_name TEXT,
                headline TEXT,
                query_used TEXT,
                status TEXT DEFAULT 'pending',
                connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_logs (
                date TEXT PRIMARY KEY,
                target_goal INTEGER DEFAULT 50,
                connections_sent INTEGER DEFAULT 0
            )
        """)
        
        # Migration: Ensure all new columns exist in connections
        cursor.execute("PRAGMA table_info(connections)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        
        new_columns = [
            ("lead_score", "INTEGER DEFAULT 0"),
            ("lead_score_reasons", "TEXT DEFAULT '[]'"),
            ("persona", "TEXT DEFAULT 'Trader'"),
            ("is_high_probable", "BOOLEAN DEFAULT 0"),
            ("connection_status", "TEXT DEFAULT 'pending'"),
            ("accepted_at", "TIMESTAMP"),
            ("message_variant", "TEXT"),
            ("first_message_text", "TEXT"),
            ("first_message_at", "TIMESTAMP"),
            ("follow_up_count", "INTEGER DEFAULT 0"),
            ("follow_up_text", "TEXT"),
            ("follow_up_at", "TIMESTAMP"),
            ("reply_status", "TEXT DEFAULT 'no_reply'"),
            ("last_reply_at", "TIMESTAMP"),
            ("last_reply_text", "TEXT"),
            ("reply_intent", "TEXT"),
            ("call_booked", "BOOLEAN DEFAULT 0"),
            ("call_booked_at", "TIMESTAMP"),
            ("calendar_event_id", "TEXT"),
            ("calendar_attendee_email", "TEXT"),
            ("notes", "TEXT")
        ]
        
        for col_name, col_def in new_columns:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE connections ADD COLUMN {col_name} {col_def}")
                
        # Data integrity heal: Mark previously messaged contacts who had first_message_at as NULL
        cursor.execute("""
            UPDATE connections
            SET first_message_at = COALESCE(first_message_at, connected_at, CURRENT_TIMESTAMP),
                status = CASE WHEN status = 'call_booked' THEN 'call_booked' ELSE 'messaged' END,
                connection_status = 'accepted',
                message_variant = COALESCE(message_variant, query_used)
            WHERE (query_used LIKE '%welcome%' OR message_variant IS NOT NULL) AND first_message_at IS NULL
        """)
        conn.commit()

def normalize_url(url: str) -> str:
    """
    Canonicalize a LinkedIn profile URL to a stable primary key format.
    Handles all known variants:
      - http vs https
      - linkedin.com vs www.linkedin.com
      - Trailing slashes
      - Query strings (?miniProfileUrn=...)
      - Locale path suffixes (/en, /fr, /de, etc.)
      - Overlay paths (/overlay/...)
      - Mixed case slugs
      - Percent-encoded vs decoded unicode characters (encodes consistently)
    """
    import urllib.parse
    import re

    if not url:
        return ""

    # Strip query params and fragments
    url = url.split("?")[0].split("#")[0].strip()

    # Normalise scheme to https
    if url.startswith("http://"):
        url = "https://" + url[7:]

    # Normalise www. prefix
    url = re.sub(r'^https://linkedin\.com/', 'https://www.linkedin.com/', url)

    # Lowercase the whole URL (LinkedIn slugs are case-insensitive)
    url = url.lower()

    # Strip trailing slash
    url = url.rstrip("/")

    # Extract the /in/<slug> portion — ignore everything after the slug
    # This removes locale suffixes (/en, /fr, /de), /overlay, /detail, etc.
    m = re.match(r'(https://www\.linkedin\.com/in/[^/]+)(/.*)?$', url)
    if m:
        slug_part = m.group(1)
        # Decode any percent-encoded characters, then re-encode to canonical form
        # This ensures "rapha%c3%abl" and "raphël" both map to the same key
        try:
            decoded = urllib.parse.unquote(slug_part, encoding='utf-8')
            # Re-encode only non-ASCII characters so ASCII slugs stay human-readable
            reencoded = urllib.parse.quote(decoded, safe='/:.-_~')
        except Exception:
            reencoded = slug_part
        return reencoded

    return url

def is_already_connected(profile_url: str) -> bool:
    """
    Checks if a profile URL is already in our connections database.
    Uses both exact-match on the normalized URL AND a slug-based LIKE fallback
    to catch edge-cases where percent-encoding differs between stored and queried URLs.
    """
    clean = normalize_url(profile_url)
    if not clean:
        return False

    # Extract the slug for a fallback LIKE search (handles encode/decode mismatches)
    import urllib.parse
    try:
        decoded_clean = urllib.parse.unquote(clean, encoding='utf-8')
    except Exception:
        decoded_clean = clean

    with get_connection() as conn:
        cursor = conn.cursor()
        # Primary: exact match on normalized URL
        cursor.execute("SELECT 1 FROM connections WHERE profile_url = ?", (clean,))
        if cursor.fetchone():
            return True
        # Secondary: decoded form match (handles stored-encoded vs queried-decoded)
        if decoded_clean != clean:
            cursor.execute("SELECT 1 FROM connections WHERE profile_url = ?", (decoded_clean,))
            if cursor.fetchone():
                return True
        # Tertiary: slug LIKE match (handles /en suffix stored or queried)
        # Extract slug from path e.g. "rapha%c3%abl-rostworowski-539787260"
        parts = clean.split("/in/")
        if len(parts) == 2:
            slug = parts[1].split("/")[0]
            cursor.execute(
                "SELECT 1 FROM connections WHERE profile_url LIKE ? OR profile_url LIKE ?",
                (f"%/in/{slug}%", f"%/in/{urllib.parse.unquote(slug)}%")
            )
            if cursor.fetchone():
                return True
    return False

def is_already_messaged(profile_url: str) -> bool:
    clean = normalize_url(profile_url)
    if not clean:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 1 FROM connections 
            WHERE profile_url = ? AND (
                first_message_at IS NOT NULL 
                OR status IN ('messaged', 'followed_up', 'replied', 'call_booked')
                OR message_variant IS NOT NULL
                OR query_used LIKE '%welcome%'
            )
        """, (clean,))
        return cursor.fetchone() is not None

def record_connection(
    profile_url: str, 
    full_name: str = "", 
    headline: str = "", 
    query_used: str = "",
    lead_score: int = 0,
    lead_score_reasons: Optional[List[str]] = None,
    persona: str = "Trader",
    is_high_probable: bool = False,
    status: str = "pending"
):
    clean = normalize_url(profile_url)
    if not clean:
        return
    reasons_json = json.dumps(lead_score_reasons or [])
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO connections (
                profile_url, full_name, headline, query_used, status, 
                lead_score, lead_score_reasons, persona, is_high_probable,
                connection_status, connected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(profile_url) DO UPDATE SET
                full_name = COALESCE(NULLIF(excluded.full_name, ''), connections.full_name),
                headline = COALESCE(NULLIF(excluded.headline, ''), connections.headline),
                query_used = COALESCE(NULLIF(excluded.query_used, ''), connections.query_used),
                lead_score = CASE WHEN excluded.lead_score > 0 THEN excluded.lead_score ELSE connections.lead_score END,
                lead_score_reasons = CASE WHEN excluded.lead_score > 0 THEN excluded.lead_score_reasons ELSE connections.lead_score_reasons END,
                persona = COALESCE(NULLIF(excluded.persona, ''), connections.persona),
                is_high_probable = CASE WHEN excluded.is_high_probable THEN 1 ELSE connections.is_high_probable END
        """, (
            clean, full_name, headline, query_used, status, 
            lead_score, reasons_json, persona, 1 if is_high_probable else 0,
            status
        ))
        conn.commit()

def record_lead_score(
    profile_url: str, 
    score: int, 
    reasons: List[str], 
    persona: str = "Trader", 
    is_high_probable: bool = False,
    full_name: str = "",
    headline: str = ""
):
    clean = normalize_url(profile_url)
    if not clean:
        return
    reasons_json = json.dumps(reasons or [])
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO connections (profile_url, full_name, headline, lead_score, lead_score_reasons, persona, is_high_probable, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'scored')
            ON CONFLICT(profile_url) DO UPDATE SET
                lead_score = excluded.lead_score,
                lead_score_reasons = excluded.lead_score_reasons,
                persona = excluded.persona,
                is_high_probable = excluded.is_high_probable,
                full_name = COALESCE(NULLIF(excluded.full_name, ''), connections.full_name),
                headline = COALESCE(NULLIF(excluded.headline, ''), connections.headline)
        """, (clean, full_name, headline, score, reasons_json, persona, 1 if is_high_probable else 0))
        conn.commit()

def mark_connection_accepted(profile_url: str) -> bool:
    clean = normalize_url(profile_url)
    if not clean:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE connections 
            SET status = CASE WHEN first_message_at IS NOT NULL THEN status ELSE 'accepted' END, 
                connection_status = 'accepted', 
                accepted_at = COALESCE(accepted_at, CURRENT_TIMESTAMP)
            WHERE profile_url = ? AND (connection_status != 'accepted' OR connection_status IS NULL)
        """, (clean,))
        changed = cursor.rowcount > 0
        conn.commit()
        return changed

def upsert_accepted_connection(profile_url: str, full_name: str = "", headline: str = "") -> None:
    """
    Upserts a LinkedIn 1st-degree connection as 'accepted' into the DB.
    Called whenever the connections page confirms someone is connected to us.
    This is the browser ground-truth write — does NOT require prior DB entry.
    Never overwrites first_message_at or messaged status.
    """
    clean = normalize_url(profile_url)
    if not clean:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO connections (
                profile_url, full_name, headline, status, connection_status, accepted_at, connected_at
            )
            VALUES (?, ?, ?, 'accepted', 'accepted', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(profile_url) DO UPDATE SET
                connection_status = 'accepted',
                accepted_at = COALESCE(connections.accepted_at, CURRENT_TIMESTAMP),
                full_name = COALESCE(NULLIF(excluded.full_name, ''), connections.full_name),
                headline = COALESCE(NULLIF(excluded.headline, ''), connections.headline),
                status = CASE
                    WHEN connections.first_message_at IS NOT NULL THEN connections.status
                    WHEN connections.status IN ('messaged', 'followed_up', 'replied', 'call_booked') THEN connections.status
                    ELSE 'accepted'
                END
        """, (clean, full_name, headline))
        conn.commit()


def get_leads_ready_for_welcome_message(limit: int = 10) -> List[Dict[str, Any]]:
    """Returns accepted leads who have not received a welcome message yet."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM connections 
            WHERE connection_status = 'accepted' AND first_message_at IS NULL
            ORDER BY lead_score DESC, connected_at ASC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

def record_message_sent(profile_url: str, variant: str, message_text: str, full_name: str = "", headline: str = ""):
    clean = normalize_url(profile_url)
    if not clean:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO connections (profile_url, full_name, headline, message_variant, first_message_text, first_message_at, status, connection_status)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'messaged', 'accepted')
            ON CONFLICT(profile_url) DO UPDATE SET
                message_variant = excluded.message_variant,
                first_message_text = excluded.first_message_text,
                first_message_at = COALESCE(connections.first_message_at, CURRENT_TIMESTAMP),
                status = CASE WHEN connections.status = 'call_booked' THEN 'call_booked' ELSE 'messaged' END,
                connection_status = 'accepted',
                full_name = COALESCE(NULLIF(excluded.full_name, ''), connections.full_name),
                headline = COALESCE(NULLIF(excluded.headline, ''), connections.headline)
        """, (clean, full_name, headline, variant, message_text))
        conn.commit()

def get_unreplied_leads_for_followup(grace_hours: int = 48) -> List[Dict[str, Any]]:
    """Returns messaged leads who have not replied and have not received a follow-up after grace_hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=grace_hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM connections
            WHERE status IN ('messaged', 'connected')
              AND first_message_at IS NOT NULL
              AND first_message_at <= ?
              AND follow_up_count = 0
              AND (reply_status IS NULL OR reply_status != 'replied')
              AND (call_booked IS NULL OR call_booked = 0)
            ORDER BY first_message_at ASC
        """, (cutoff,))
        return [dict(row) for row in cursor.fetchall()]

def record_followup_sent(profile_url: str, follow_up_text: str):
    clean = normalize_url(profile_url)
    if not clean:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE connections
            SET follow_up_count = follow_up_count + 1,
                follow_up_text = ?,
                follow_up_at = CURRENT_TIMESTAMP,
                status = 'followed_up'
            WHERE profile_url = ?
        """, (follow_up_text, clean))
        conn.commit()

def record_reply(profile_url: str, reply_text: str, intent: str = "custom_inquiry"):
    clean = normalize_url(profile_url)
    if not clean:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE connections
            SET reply_status = 'replied',
                last_reply_at = CURRENT_TIMESTAMP,
                last_reply_text = ?,
                reply_intent = ?,
                status = 'replied'
            WHERE profile_url = ?
        """, (reply_text, intent, clean))
        conn.commit()

def mark_call_booked(
    profile_url: str, 
    event_id: Optional[str] = None, 
    email: Optional[str] = None, 
    booked_at: Optional[str] = None
):
    clean = normalize_url(profile_url)
    if not clean:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE connections
            SET call_booked = 1,
                call_booked_at = COALESCE(?, CURRENT_TIMESTAMP),
                calendar_event_id = COALESCE(?, calendar_event_id),
                calendar_attendee_email = COALESCE(?, calendar_attendee_email),
                status = 'call_booked'
            WHERE profile_url = ?
        """, (booked_at, event_id, email, clean))
        conn.commit()

def toggle_call_booked(profile_url: str, booked: Optional[bool] = None) -> bool:
    clean = normalize_url(profile_url)
    if not clean:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        if booked is None:
            cursor.execute("SELECT call_booked FROM connections WHERE profile_url = ?", (clean,))
            row = cursor.fetchone()
            current = bool(row["call_booked"]) if row and row["call_booked"] is not None else False
            new_val = not current
        else:
            new_val = booked
        
        status_str = 'call_booked' if new_val else 'messaged'
        cursor.execute("""
            UPDATE connections 
            SET call_booked = ?, 
                call_booked_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END,
                status = ?
            WHERE profile_url = ?
        """, (1 if new_val else 0, 1 if new_val else 0, status_str, clean))
        conn.commit()
        return new_val

def find_lead_by_name_or_email(name: str, email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not name and not email:
        return None
    with get_connection() as conn:
        cursor = conn.cursor()
        if email:
            cursor.execute("SELECT * FROM connections WHERE calendar_attendee_email = ? LIMIT 1", (email.lower(),))
            row = cursor.fetchone()
            if row:
                return dict(row)
        
        if name:
            clean_name = name.strip().lower()
            cursor.execute("SELECT * FROM connections WHERE LOWER(full_name) = ? LIMIT 1", (clean_name,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            
            # Fuzzy first + last name match
            parts = clean_name.split()
            if len(parts) >= 2:
                cursor.execute("""
                    SELECT * FROM connections 
                    WHERE LOWER(full_name) LIKE ? AND LOWER(full_name) LIKE ? 
                    LIMIT 1
                """, (f"%{parts[0]}%", f"%{parts[-1]}%"))
                row = cursor.fetchone()
                if row:
                    return dict(row)
    return None

def get_daily_count(date_str: str = None) -> int:
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT connections_sent FROM daily_logs WHERE date = ?", (date_str,))
        row = cursor.fetchone()
        return row["connections_sent"] if row else 0

def increment_daily_count(target_goal: int = 50, date_str: str = None) -> int:
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO daily_logs (date, target_goal, connections_sent)
            VALUES (?, ?, 1)
            ON CONFLICT(date) DO UPDATE SET
                connections_sent = connections_sent + 1,
                target_goal = ?
        """, (date_str, target_goal, target_goal))
        conn.commit()
        return get_daily_count(date_str)

def get_dashboard_analytics_summary() -> Dict[str, Any]:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Total leads
        cursor.execute("SELECT COUNT(*) as cnt FROM connections")
        total_leads = cursor.fetchone()["cnt"]
        
        # Total sent
        cursor.execute("SELECT COUNT(*) as cnt FROM connections WHERE status != 'scored'")
        total_sent = cursor.fetchone()["cnt"]
        
        # Weekly sent (last 7 days)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("SELECT COUNT(*) as cnt FROM connections WHERE connected_at >= ?", (week_ago,))
        weekly_sent = cursor.fetchone()["cnt"]
        
        # Accepted connections
        cursor.execute("SELECT COUNT(*) as cnt FROM connections WHERE connection_status = 'accepted' OR accepted_at IS NOT NULL")
        total_accepted = cursor.fetchone()["cnt"]
        
        # Total messaged
        cursor.execute("SELECT COUNT(*) as cnt FROM connections WHERE first_message_at IS NOT NULL")
        total_messaged = cursor.fetchone()["cnt"]
        
        # Total replied
        cursor.execute("SELECT COUNT(*) as cnt FROM connections WHERE reply_status = 'replied'")
        total_replied = cursor.fetchone()["cnt"]
        
        # Calls booked
        cursor.execute("SELECT COUNT(*) as cnt FROM connections WHERE call_booked = 1")
        total_calls_booked = cursor.fetchone()["cnt"]
        
        # A/B Test Variant Metrics
        cursor.execute("""
            SELECT 
                message_variant,
                COUNT(*) as sent_count,
                SUM(CASE WHEN reply_status = 'replied' THEN 1 ELSE 0 END) as reply_count,
                SUM(CASE WHEN call_booked = 1 THEN 1 ELSE 0 END) as call_count
            FROM connections
            WHERE message_variant IN ('variant_a_standard', 'variant_b_personalized')
            GROUP BY message_variant
        """)
        ab_data = {
            "variant_a": {"sent": 0, "replies": 0, "reply_rate": 0.0, "calls": 0, "call_rate": 0.0},
            "variant_b": {"sent": 0, "replies": 0, "reply_rate": 0.0, "calls": 0, "call_rate": 0.0}
        }
        for row in cursor.fetchall():
            var_key = "variant_a" if "standard" in row["message_variant"] else "variant_b"
            sent = row["sent_count"] or 0
            replies = row["reply_count"] or 0
            calls = row["call_count"] or 0
            ab_data[var_key] = {
                "sent": sent,
                "replies": replies,
                "reply_rate": round((replies / sent * 100) if sent > 0 else 0.0, 1),
                "calls": calls,
                "call_rate": round((calls / sent * 100) if sent > 0 else 0.0, 1)
            }
        
        # Conversion rates
        acceptance_rate = round((total_accepted / total_sent * 100) if total_sent > 0 else 0.0, 1)
        reply_rate = round((total_replied / total_messaged * 100) if total_messaged > 0 else 0.0, 1)
        booking_rate = round((total_calls_booked / total_sent * 100) if total_sent > 0 else 0.0, 1)
        
        # Average lead score of converted vs contacted
        cursor.execute("SELECT AVG(lead_score) as avg_score FROM connections WHERE lead_score > 0")
        avg_score_row = cursor.fetchone()
        avg_lead_score = round(avg_score_row["avg_score"] or 0.0, 1)

        # High probable count
        cursor.execute("SELECT COUNT(*) as cnt FROM connections WHERE is_high_probable = 1 OR lead_score >= 70")
        high_probable_count = cursor.fetchone()["cnt"]

        return {
            "total_leads": total_leads,
            "total_sent": total_sent,
            "weekly_sent": weekly_sent,
            "weekly_goal": 350,
            "total_accepted": total_accepted,
            "acceptance_rate": acceptance_rate,
            "total_messaged": total_messaged,
            "total_replied": total_replied,
            "reply_rate": reply_rate,
            "total_calls_booked": total_calls_booked,
            "booking_rate": booking_rate,
            "avg_lead_score": avg_lead_score,
            "high_probable_count": high_probable_count,
            "ab_testing": ab_data,
            "funnel": {
                "identified": total_leads,
                "connected_sent": total_sent,
                "accepted": total_accepted,
                "messaged": total_messaged,
                "replied": total_replied,
                "calls_booked": total_calls_booked
            }
        }

def get_leads_crm(
    status_filter: Optional[str] = None, 
    search: Optional[str] = None, 
    min_score: Optional[int] = None,
    limit: int = 50, 
    offset: int = 0
) -> Dict[str, Any]:
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM connections WHERE 1=1"
        params = []
        
        if status_filter and status_filter != "all":
            if status_filter == "high_probable":
                query += " AND (is_high_probable = 1 OR lead_score >= 70)"
            elif status_filter == "accepted":
                query += " AND (connection_status = 'accepted' OR status = 'accepted')"
            elif status_filter == "awaiting_followup":
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
                query += " AND first_message_at IS NOT NULL AND first_message_at <= ? AND follow_up_count = 0 AND (reply_status IS NULL OR reply_status != 'replied') AND (call_booked IS NULL OR call_booked = 0)"
                params.append(cutoff)
            elif status_filter == "messaged":
                query += " AND first_message_at IS NOT NULL"
            elif status_filter == "replied":
                query += " AND reply_status = 'replied'"
            elif status_filter == "call_booked":
                query += " AND call_booked = 1"
            else:
                query += " AND status = ?"
                params.append(status_filter)
                
        if min_score is not None and min_score > 0:
            query += " AND lead_score >= ?"
            params.append(min_score)
            
        if search:
            query += " AND (LOWER(full_name) LIKE ? OR LOWER(headline) LIKE ? OR LOWER(persona) LIKE ?)"
            s = f"%{search.strip().lower()}%"
            params.extend([s, s, s])
            
        # Count total matches
        count_query = query.replace("SELECT *", "SELECT COUNT(*) as total")
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()["total"]
        
        # Order and paginate
        query += " ORDER BY connected_at DESC, lead_score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        leads = []
        for r in cursor.fetchall():
            d = dict(r)
            try:
                d["lead_score_reasons"] = json.loads(d.get("lead_score_reasons") or "[]")
            except Exception:
                d["lead_score_reasons"] = []
            leads.append(d)
            
        return {"total": total_count, "leads": leads, "limit": limit, "offset": offset}

init_db()

if __name__ == "__main__":
    print("Database updated and initialized successfully at:", DB_PATH)
    stats = get_dashboard_analytics_summary()
    print("Initial summary:", json.dumps(stats, indent=2))
