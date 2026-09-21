import json
import sys
import time
import threading
import db
import tags_manager
from bridge_server import bridge
from agent import create_linkedin_agent, run_agent_with_retry
import calendar_sync

def start_dashboard_thread():
    try:
        from dashboard_server import start_dashboard
        t = threading.Thread(target=start_dashboard, kwargs={"host": "127.0.0.1", "port": 8080}, daemon=True)
        t.start()
        time.sleep(1.0)
    except Exception as e:
        print(f"[WARN] Could not auto-launch dashboard: {e}")

def run_outreach_session(target_goal: int):
    print(f"\n[START] Initializing Ascentrader CodeAgent (GLM-5.3)... Target Goal: {target_goal} connections.\n")

    current_count = db.get_daily_count()
    print(f"[STATUS] Current connections sent today: {current_count}/{target_goal}")

    if current_count >= target_goal:
        print("[OK] Daily target goal already reached!")
        return

    agent = create_linkedin_agent()
    needed = target_goal - current_count
    
    prompt = f"""
Goal: Perform high-relevance professional networking for Ascentrader (https://ascentrader.com) to reach {target_goal} verified connections today.
Currently, {current_count} connections have been sent today. Connect with {needed} more qualified candidates.

Execution Strategy:
1. Call `tags_get_next_search_tag()` to retrieve the current search tag query from `tags.json`.
2. Use `search_linkedin_people(query=current_tag)` to view relevant professionals.
3. For each candidate card found on the page:
   - Check if already connected via `db_check_is_connected(profile_url)`.
   - Connect using `connect_with_candidate(...)`. This verifies profile fit (Score >= 70) to ensure high-value 1-to-1 networking.
   - If `connect_with_candidate` returns `status == 'connected'`, log: "[VERIFIED] Pending confirmed for <Name> (Score: <Score>%)".
   - Maintain natural 10-20s pauses between invitations.
4. Search Tag Rotation & Pagination Rules:
   - If 0 viable candidates remain on the current search page, use `browser_click_next_page()`.
   - If the current search tag has no more results or lacks viable candidates (e.g. low scores or already connected), DO NOT STOP. Call `tags_get_next_search_tag()` to switch to the next tag query in `tags.json` and run `search_linkedin_people(query=new_tag)`.
   - Continue rotating through search tags until the required {needed} verified connections are reached.
5. Finish when {needed} new connections have been sent (or all search tags have been thoroughly evaluated).
"""
    print("[RUN] CodeAgent executing connection outreach...\n")
    run_agent_with_retry(agent, prompt)

def run_welcome_messaging_session():
    print("\n[START] Checking for accepted connections to send A/B Welcome Messages...")
    agent = create_linkedin_agent()
    prompt = """
Goal: Verify accepted LinkedIn connections and dispatch A/B Welcome Messages with the Google Calendar booking link to candidates who have NEVER been messaged.

Execution Strategy (5-by-5 Progressive Verification Loop):
1. Start at `start_index = 0`.
2. Call `verify_and_message_connections_batch(start_index=start_index, chunk_size=5)`.
   - This tool inspects the slice of 5 connections from LinkedIn's live connections page.
   - For each candidate, it checks their live LinkedIn conversation thread in the DOM.
   - If unmessaged: sends personalized A/B Welcome Message (Variant A/B + Calendar link: https://calendar.app.google/Lmv6oh4jkB8oCd6K7) and records in DB.
   - If already messaged: records existing_thread in DB and skips.
3. Check the tool's returned result:
   - If `recommendation == 'continue_next_chunk'` (meaning unmessaged connections were found in this batch and there are more connections):
     - Advance `start_index` by 5 (e.g. `start_index = next_start_index`) and call `verify_and_message_connections_batch(start_index=start_index, chunk_size=5)`.
     - Repeat as long as unmessaged connections continue to be discovered!
   - If `recommendation == 'stop_reached_old_connections'` (all 5 in the chunk were already messaged):
     - Finish immediately: "[OK] Reached previously messaged network boundary. All recent connections processed."
   - If `recommendation == 'stop_no_more_connections'`:
     - Finish immediately: "[OK] All available connection cards on LinkedIn have been evaluated."
"""
    print("[RUN] CodeAgent executing welcome messaging...\n")
    run_agent_with_retry(agent, prompt)

def run_followup_session():
    print("\n[START] Checking for replies and 48-hour follow-up check-ins...")
    agent = create_linkedin_agent()
    prompt = """
Goal: Check inbound replies and send single 48-hour follow-up check-in messages to non-responders.

Execution Strategy:
1. Call `check_replies_and_send_followups(grace_period_hours=48)`.
2. If a lead replied with custom questions, the tool classifies their intent and dispatches an immediate email alert to the founder.
3. If a lead hasn't replied after 48h, the tool sends a single, gentle check-in follow-up message (at most once).
"""
    print("[RUN] CodeAgent executing follow-up check-in...\n")
    run_agent_with_retry(agent, prompt)

def run_backlog_session():
    print("\n[START] Scanning existing network backlog for high-probability leads...")
    agent = create_linkedin_agent()
    prompt = """
Goal: Mine existing 1st-degree connections for high-probability leads (Score >= 70) who have NEVER been messaged before.

Execution Strategy:
1. Call `scan_backlog_connections_and_message(min_score=70, limit=15)`.
   This tool automatically filters out anyone who was already messaged in previous runs or on LinkedIn.
2. For each identified unmessaged lead returned:
   - Call `send_welcome_message(profile_url=lead['profile_url'], full_name=lead['full_name'], headline=lead['headline'])`.
   - Enforce randomized human pacing delay.
"""
    print("[RUN] CodeAgent executing backlog network outreach...\n")
    run_agent_with_retry(agent, prompt)

def run_full_autonomous_cycle(target_goal: int = 50):
    print("\n[START] Launching Prioritized Growth & Conversion Cycle...\n")
    
    print("1. 📅 Syncing Google Calendar appointments...")
    try:
        cal_res = calendar_sync.sync_google_calendar_events()
        print(f"   [OK] Matched: {cal_res.get('matched_count', 0)} appointments in database.")
    except Exception as e:
        print(f"   [NOTICE] Calendar sync: {e}")

    print("\n2. 🤝 FIRST PRIORITY: Checking connections we have made but haven't messaged...")
    run_welcome_messaging_session()

    print("\n3. 🔍 SECOND PRIORITY: Mining existing connection backlog for high-probability unmessaged leads...")
    run_backlog_session()

    print("\n4. 📬 THIRD PRIORITY: Checking conversation replies & sending 48h follow-up check-ins...")
    run_followup_session()

    print(f"\n5. 🎯 FOURTH PRIORITY: Making new high-probability connections (Target Goal: {target_goal})...")
    run_outreach_session(target_goal)
    
    print("\n[DONE] Full growth cycle completed successfully!")

def main():
    print("==================================================================")
    print("      Ascentrader AI Growth Bot & Conversion Engine (GLM-5.3)     ")
    print("==================================================================")
    
    # Auto-start Dashboard server
    print("\n1. Starting Conversion & CRM Dashboard server...")
    start_dashboard_thread()
    print("   👉 Dashboard live at: http://localhost:8080")

    print("\n2. Launching WebSocket RPC server on ws://127.0.0.1:10086/ws...")
    bridge.start_in_background()
    
    print("\n⌛ Waiting for Chrome extension (Ascentrader WebBridge) to connect...")
    print("   👉 Ensure you are logged into LinkedIn, and load the extension from: ./ascentrader_extension\n")

    while not bridge.is_connected:
        time.sleep(1)

    print("[OK] Ascentrader WebBridge connected successfully!\n")

    print("------------------------------------------------------------------")
    print("Select an operation mode:")
    print("  [1] Full Autonomous Growth Cycle (Outreach + Sync + Message + 48h Follow-up)")
    print("  [2] High-Probability Connection Outreach Only (Score >= 70)")
    print("  [3] Sync Accepted Connections & Send A/B Welcome Messages")
    print("  [4] Check Inbound Replies & Send 48h Follow-up Check-ins")
    print("  [5] Mine Backlog Connections (Existing Network)")
    print("  [6] Sync Google Calendar Bookings Now")
    print("  [7] Keep Dashboard Server Running (http://localhost:8080)")
    print("------------------------------------------------------------------")

    choice = input("Enter choice [1-7, default 1]: ").strip() or "1"

    if choice == "1":
        goal_input = input("Enter connection target goal for today [default 50]: ").strip()
        target_goal = int(goal_input) if goal_input.isdigit() else 50
        run_full_autonomous_cycle(target_goal)
    elif choice == "2":
        goal_input = input("Enter connection target goal for today [default 50]: ").strip()
        target_goal = int(goal_input) if goal_input.isdigit() else 50
        run_outreach_session(target_goal)
    elif choice == "3":
        run_welcome_messaging_session()
    elif choice == "4":
        run_followup_session()
    elif choice == "5":
        run_backlog_session()
    elif choice == "6":
        res = calendar_sync.sync_google_calendar_events()
        print("Calendar Sync Result:", json.dumps(res, indent=2))
    elif choice == "7":
        print("\nDashboard server running. Open http://localhost:8080 in your browser.")
        print("Press Ctrl+C to exit.\n")
        while True:
            time.sleep(1)
    else:
        print("Invalid option selected. Exiting.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[EXIT] Bot stopped by user.")
