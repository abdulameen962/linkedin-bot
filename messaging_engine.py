import os
import random
from typing import Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()

CALENDAR_URL = os.getenv("CALENDAR_BOOKING_URL", "https://calendar.app.google/Lmv6oh4jkB8oCd6K7")

VARIANT_A_STANDARD = (
    f"Hi, I am the co-founder of Ascentrader, can we get on a 5-10 mins call to see how we can help supercharge your trading from risk management to consistent journalling to creating ai watchers\n\n"
    f"{CALENDAR_URL} The link to pick a time comfortable for you"
)

def extract_first_name(full_name: str) -> str:
    if not full_name:
        return "there"
    # Remove honorifics/prefixes and split
    clean = full_name.strip()
    for prefix in ["mr.", "ms.", "mrs.", "dr.", "engr."]:
        if clean.lower().startswith(prefix):
            clean = clean[len(prefix):].strip()
    parts = clean.split()
    if parts:
        first = parts[0].capitalize()
        # Exclude weird non-name strings
        if len(first) > 1 and first.isalpha():
            return first
    return "there"

def build_variant_b_personalized(first_name: str, persona: str, headline: str = "") -> str:
    """
    Builds a high-converting, personalized outreach message tailored to the trader's persona.
    """
    headline_lower = headline.lower()
    
    # 1. Custom Hook
    if "prop" in persona.lower() or "funded" in headline_lower or "ftmo" in headline_lower:
        hook = f"Hi {first_name}, saw you're trading prop accounts - staying disciplined with strict daily drawdowns and risk rules is tough to manage manually."
    elif "algo" in persona.lower() or "mt5" in headline_lower or "quant" in headline_lower:
        hook = f"Hi {first_name}, noticed your focus on MT5 / algorithmic systems - syncing trades and tracking multi-strategy edge usually takes hours of manual journaling."
    elif "forex" in persona.lower() or "fx" in headline_lower:
        hook = f"Hi {first_name}, noticed your focus on the FX markets - consistent risk management and automated trade tracking make a massive difference in compounding edge."
    else:
        hook = f"Hi {first_name}, great connecting with you!"

    pitch = "I'm the co-founder of Ascentrader, where we help traders automate their risk management, journal trades seamlessly, and deploy custom AI watchers."
    cta = f"Can we get on a quick 5-10 min call to explore how we can supercharge your trading analytics?\n\n{CALENDAR_URL} The link to pick a time comfortable for you"

    return f"{hook}\n\n{pitch}\n\n{cta}"

def build_single_followup(first_name: str) -> str:
    return (
        f"Hey {first_name}, just following up quickly in case this got buried in your inbox. "
        f"Still open to a quick 5-10 min chat on streamlining your trading analytics? "
        f"Either way, great connecting with you!"
    )

def get_next_message_variant(last_variant_used: str = None) -> str:
    """
    Determines whether to send Variant A or Variant B for balanced 50/50 A/B testing.
    """
    if last_variant_used == "variant_a_standard":
        return "variant_b_personalized"
    elif last_variant_used == "variant_b_personalized":
        return "variant_a_standard"
    return random.choice(["variant_a_standard", "variant_b_personalized"])

def generate_welcome_message(
    full_name: str, 
    headline: str = "", 
    persona: str = "Trader", 
    variant_override: str = None
) -> Tuple[str, str]:
    """
    Returns (variant_id, message_text).
    """
    first_name = extract_first_name(full_name)
    variant = variant_override or get_next_message_variant()

    if variant == "variant_b_personalized":
        msg = build_variant_b_personalized(first_name, persona, headline)
    else:
        msg = VARIANT_A_STANDARD

    return variant, msg

if __name__ == "__main__":
    print("--- VARIANT A (STANDARD) ---")
    print(VARIANT_A_STANDARD)
    print("\n--- VARIANT B (PERSONALIZED: Prop Trader) ---")
    print(build_variant_b_personalized("Alex", "Prop Firm Trader", "FTMO Trader"))
    print("\n--- VARIANT B (PERSONALIZED: MT5 Algo) ---")
    print(build_variant_b_personalized("Dmitri", "MT5 & Algo Trader", "MQL5 EA Dev"))
    print("\n--- SINGLE FOLLOW-UP (48h) ---")
    print(build_single_followup("Alex"))
