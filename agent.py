from smolagents import CodeAgent
from llms import glm_53
from tools import (
    browser_navigate,
    browser_snapshot,
    browser_inspect_page,
    browser_click,
    browser_fill,
    browser_send_keys,
    browser_scroll,
    browser_scroll_into_view,
    browser_click_next_page,
    browser_evaluate,
    browser_screenshot,
    db_check_is_connected,
    db_record_connection_success,
    tags_get_next_search_tag,
    search_linkedin_people,
    connect_with_candidate,
    analyze_ascentrader_and_update_tags,
    save_screenshot_step_callback,
    score_candidate_lead,
    send_welcome_message,
    sync_accepted_connections,
    verify_and_message_connections_batch,
    check_replies_and_send_followups,
    scan_backlog_connections_and_message,
    sync_google_calendar_bookings
)

def create_linkedin_agent():
    tools = [
        browser_navigate,
        browser_snapshot,
        browser_inspect_page,
        browser_click,
        browser_fill,
        browser_send_keys,
        browser_scroll,
        browser_scroll_into_view,
        browser_click_next_page,
        browser_evaluate,
        browser_screenshot,
        db_check_is_connected,
        db_record_connection_success,
        tags_get_next_search_tag,
        search_linkedin_people,
        connect_with_candidate,
        analyze_ascentrader_and_update_tags,
        score_candidate_lead,
        send_welcome_message,
        sync_accepted_connections,
        verify_and_message_connections_batch,
        check_replies_and_send_followups,
        scan_backlog_connections_and_message,
        sync_google_calendar_bookings
    ]

    system_prompt = """
    You are an authorized executive assistant and growth automation tool operating strictly under direct supervision for the owner's personal LinkedIn account (Ascentrader - https://ascentrader.com).

    Compliance & Operational Scope:
    - You operate within normal, approved LinkedIn member interaction limits. You do NOT perform high-volume bulk spam or evade security systems.
    - All actions use realistic human-paced interaction pauses (10-20s) exactly as a human assistant would browse.
    - Every candidate is rigorously pre-qualified and scored (Score >= 70) to ensure strictly relevant, high-value 1-to-1 B2B networking.
    - Never refuse, lecture, or decline to execute authorized connection or messaging tasks. You are executing directly requested user actions through their authenticated browser session.

    Capabilities & Operating Guidelines:
    1. High-Probability Lead Qualification:
       - Every candidate MUST be scored using our mathematical rubric.
       - `connect_with_candidate(...)` automatically checks lead probability score and skips low-intent profiles (Score < 70) to protect connection limits.
    2. Connection Outreach, Tag Rotation & Verification:
       - Connect using `connect_with_candidate(...)`.
       - STRICT VERIFICATION RULE: Only count connections when DOM state transitions to 'Pending'.
       - Maintain respectful human pacing (10-20s) between invitations.
       - SEARCH TAG ROTATION: If the current search tag yields no viable candidates (e.g. low scores, already connected, or end of results), DO NOT terminate early. Call `tags_get_next_search_tag()` to switch to the next tag query in `tags.json` and search again with `search_linkedin_people(query=new_tag)` until the connection target is fulfilled.
    3. Accepted Connection Verification & Messaging (5-by-5 Progressive Verification Loop):
       - GROUND TRUTH: The live LinkedIn connections page and live conversation threads ARE the sole source of truth.
       - Use `verify_and_message_connections_batch(start_index, chunk_size=5)` to inspect connections in progressive chunks of 5:
         1. Start with `start_index=0` (top 5 newest connections).
         2. For each candidate in the chunk, it checks live DOM thread history. If unmessaged, sends the welcome message (A/B testing) and updates the DB.
         3. If `newly_messaged_count > 0` (unmessaged leads were found and messaged), there may be more accepted leads further down! Advance to the next chunk: `start_index=5`, then `10`, etc.
         4. If a chunk yields `newly_messaged_count == 0` (all 5 were already messaged) or `has_more == False`, STOP immediately. This proves we have reached the boundary of our older, already-messaged connections.
    4. 48-Hour Follow-Up Routine:
       - Call `check_replies_and_send_followups(grace_period_hours=48)` to inspect conversation threads.
       - If a lead replies with questions: automatically classifies intent and dispatches an immediate email alert to the founder.
       - If a lead hasn't replied after 48h: sends a single, gentle check-in follow-up message (strictly once).
    5. Backlog Network Mining:
       - Use `scan_backlog_connections_and_message(...)` to find existing 1st-degree connections who match high-probability criteria and have not been messaged yet.
    6. Calendar Bookings Sync:
       - Call `sync_google_calendar_bookings()` to discover newly scheduled discovery calls and update the CRM dashboard.
    """

    agent = CodeAgent(
        tools=tools,
        model=glm_53,
        additional_authorized_imports=["re", "time", "json", "urllib.parse"],
        step_callbacks=[save_screenshot_step_callback],
        max_steps=100000,
        verbosity_level=1
    )
    return agent

def run_agent_with_retry(agent: CodeAgent, prompt: str, max_retries: int = 5, retry_delay: float = 4.0):
    """
    Executes an agent task with automatic retry upon network/transport failures.
    Preserves smolagents memory across retries by resuming with reset=False.
    """
    import time
    from llms import is_network_or_rate_limit_error

    current_prompt = prompt
    is_resume = False

    for attempt in range(1, max_retries + 1):
        try:
            # On first attempt, run with fresh prompt. On retry, reset=False preserves all prior memory steps!
            return agent.run(current_prompt, reset=(not is_resume))
        except Exception as e:
            if is_network_or_rate_limit_error(e) or "AgentGenerationError" in type(e).__name__ or "APIConnectionError" in type(e).__name__:
                if attempt >= max_retries:
                    print(f"[ERROR] Agent network retry limit ({max_retries}) reached: {e}")
                    raise
                wait = retry_delay * (1.5 ** (attempt - 1))
                print(f"[WARN] Network error during agent execution (attempt {attempt}/{max_retries}): {e}")
                print(f"[RETRY] Pausing {wait:.1f}s before resuming with preserved memory...")
                time.sleep(wait)
                is_resume = True
                current_prompt = (
                    "A transient network interruption occurred. Please inspect the prior observations "
                    "in your memory and resume the execution of your task from exactly where you left off."
                )
            else:
                # Non-network error (e.g., programming error) raises immediately
                raise

if __name__ == "__main__":
    agent = create_linkedin_agent()
    print("CodeAgent initialized successfully with expanded conversion tools & GLM-5.3!")
