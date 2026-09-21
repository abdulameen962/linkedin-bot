import os
import base64
import asyncio
import json
import random
import time
import urllib.parse
import nest_asyncio
from typing import List, Dict, Any, Optional
from smolagents import tool

import db
import tags_manager
from bridge_server import bridge
from llms import glm_53
import lead_scorer
import messaging_engine
import notifier
import calendar_sync

# Enable nested event loops for seamless execution inside active asyncio loops
nest_asyncio.apply()

def run_async(coro, timeout: float = 60.0):
    """Executes a coroutine safely on the dedicated RPC background thread."""
    if bridge.loop and bridge.loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, bridge.loop)
        return future.result(timeout=timeout)
    else:
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(coro)
        except Exception:
            return asyncio.run(coro)

# ==============================================================================
# ATOMIC BROWSER PRIMITIVE TOOLS (Exposed to smolagents CodeAgent)
# ==============================================================================

@tool
def browser_navigate(url: str, group_title: str = "🎯 Ascentrader AI Outreach") -> str:
    """
    Navigates the active Chrome browser tab to a specified URL and assigns it to a Chrome Tab Group.

    Args:
        url: The full web page URL to navigate to (e.g. 'https://www.linkedin.com' or 'https://ascentrader.com').
        group_title: Tab group visual title label shown in Chrome tab bar. Default '🎯 Ascentrader AI Outreach'.
    """
    try:
        res = run_async(bridge.navigate(url, group_title=group_title))
        time.sleep(2.0)
        return json.dumps({"status": "success", "url": url, "group_title": group_title, "result": res})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def browser_snapshot() -> str:
    """
    Captures an accessibility AXTree snapshot of the active browser page.
    Returns page title, URL, and a tree of interactive UI elements with ref IDs (e.g. @e1, @e2, role, text/name).
    Use ref IDs (e.g. '@e5') with browser_click or browser_fill to interact with UI elements reliably!
    """
    try:
        res = run_async(bridge.snapshot())
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def browser_inspect_page(query_selector: Optional[str] = None) -> str:
    """
    Inspects interactive DOM elements on the active page (or within a container selector).
    Returns complete information about visible buttons, links, inputs, cards, CSS classes, text, aria-labels, and a visual screenshot path.
    Use this whenever you need to see the exact structure, CSS classes, and buttons of the current page!

    Args:
        query_selector: Optional CSS selector to scope inspection (e.g. 'div.search-results-container' or '.entity-result'). Default inspects full page.
    """
    try:
        inspect_script = f"""
        (() => {{
          const root = {json.dumps(query_selector)} ? document.querySelector({json.dumps(query_selector)}) || document : document;
          const interactive = Array.from(root.querySelectorAll('button, a, input, [role="button"], [role="link"], li.grid, .entity-result'));
          const elements = interactive.map((el, index) => {{
            const rect = el.getBoundingClientRect();
            const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
            return {{
              id: el.id || null,
              tag: el.tagName,
              text: (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120),
              classes: el.className || '',
              role: el.getAttribute('role') || null,
              aria_label: el.getAttribute('aria-label') || null,
              href: el.href ? el.href.split('?')[0] : null,
              is_visible: isVisible
            }};
          }}).filter(e => e.is_visible && (e.text || e.aria_label || e.href));
          
          return {{
            url: window.location.href,
            title: document.title,
            element_count: elements.length,
            elements: elements.slice(0, 50)
          }};
        }})()
        """
        res = run_async(bridge.evaluate(inspect_script))
        data = res.get("value", {}) if isinstance(res, dict) else {}
        
        screenshot_path = None
        try:
            ss_res = run_async(bridge.screenshot(format="png"))
            if isinstance(ss_res, dict) and "data" in ss_res:
                img_bytes = base64.b64decode(ss_res["data"])
                filename = f"inspect_{int(time.time())}.png"
                screenshot_path = os.path.join(SCREENSHOTS_DIR, filename)
                with open(screenshot_path, "wb") as f:
                    f.write(img_bytes)
        except Exception:
            pass

        data["screenshot_path"] = screenshot_path
        return json.dumps(data, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def browser_click(selector: str) -> str:
    """
    Clicks an element on the active web page using an accessibility ref ID (e.g. '@e1'), a CSS selector (e.g. 'button.artdeco-button'), or button text (e.g. 'text=Connect').

    Args:
        selector: The ref ID ('@e12'), CSS selector ('button[aria-label*="Connect"]'), or text query ('text=Connect').
    """
    try:
        if selector.startswith("text="):
            target_text = selector[5:].strip().lower()
            code = f"""
            (() => {{
              const buttons = Array.from(document.querySelectorAll('button, a, [role="button"]'));
              const match = buttons.find(b => {{
                const t = (b.textContent || '').toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return t.includes({json.dumps(target_text)}) || aria.includes({json.dumps(target_text)});
              }});
              if (!match) return {{ error: 'No button found with text: ' + {json.dumps(target_text)} }};
              match.scrollIntoView({{ block: 'center' }});
              match.click();
              return {{ success: true, tag: match.tagName, text: match.textContent.trim() }};
            }})()
            """
            res = run_async(bridge.evaluate(code))
            return json.dumps({"status": "success", "clicked": selector, "result": res.get("value")})

        res = run_async(bridge.click(selector))
        return json.dumps({"status": "success", "clicked": selector, "result": res})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def browser_fill(selector: str, value: str) -> str:
    """
    Types text into an input field or contenteditable element on the active page.

    Args:
        selector: The ref ID (e.g. '@e3') from browser_snapshot, or a CSS selector.
        value: The text string to fill into the element.
    """
    try:
        res = run_async(bridge.fill(selector, value))
        return json.dumps({"status": "success", "selector": selector, "result": res})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def browser_send_keys(keys: str) -> str:
    """
    Sends keyboard key presses or shortcuts to the active browser page.

    Args:
        keys: Key string to send (e.g. 'Enter', 'Escape', 'Tab', 'Mod+A', 'PageDown').
    """
    try:
        res = run_async(bridge.send_keys(keys))
        return json.dumps({"status": "success", "keys": keys, "result": res})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def browser_evaluate(code: str) -> str:
    """
    Executes raw JavaScript code in the active page context and returns the result.

    Args:
        code: The JavaScript snippet or IIFE expression to execute in browser.
    """
    try:
        res = run_async(bridge.evaluate(code))
        return json.dumps({"status": "success", "result": res.get("value") if isinstance(res, dict) else res})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def browser_scroll(direction: str = "down", amount: int = 500) -> str:
    """
    Scrolls the active browser window up or down by a pixel amount. Useful for infinite-scroll pages (e.g. LinkedIn search results).

    Args:
        direction: Direction to scroll ('down' or 'up'). Default 'down'.
        amount: Number of pixels to scroll (e.g. 500). Default 500.
    """
    try:
        res = run_async(bridge.scroll(direction=direction, amount=amount))
        time.sleep(1.0)
        return json.dumps({"status": "success", "direction": direction, "amount": amount})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def browser_scroll_into_view(selector: str) -> str:
    """
    Scrolls a specific element into the center of the viewport using a CSS selector or ref ID (e.g. '@e5').

    Args:
        selector: The CSS selector or ref ID to scroll into view.
    """
    try:
        code = f"""
        (() => {{
          const el = document.querySelector({json.dumps(selector)});
          if (!el) return {{ error: 'Element not found: {selector}' }};
          el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          return {{ success: true }};
        }})()
        """
        res = run_async(bridge.evaluate(code))
        time.sleep(1.0)
        return json.dumps({"status": "success", "selector": selector, "result": res.get("value")})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
_step_counter = 0

def save_screenshot_step_callback(step_log=None, agent=None):
    global _step_counter
    _step_counter += 1
    try:
        if bridge.is_connected:
            res = run_async(bridge.screenshot(format="png"))
            if isinstance(res, dict) and "data" in res:
                img_bytes = base64.b64decode(res["data"])
                filepath = os.path.join(SCREENSHOTS_DIR, f"step_{_step_counter}.png")
                with open(filepath, "wb") as f:
                    f.write(img_bytes)
                print(f"📸 [Step Callback #{_step_counter}] Saved browser screenshot: {filepath}")
    except Exception as e:
        if "chrome://" not in str(e):
            print(f"⚠️ [Step Callback] Could not capture step screenshot: {e}")

@tool
def browser_screenshot(save_name: str = "current_page") -> str:
    """
    Captures a visual screenshot of the current active browser page, saves it to disk, and returns the file path for inspection.

    Args:
        save_name: Base filename to save screenshot as (e.g. 'search_results'). Default is 'current_page'.
    """
    try:
        res = run_async(bridge.screenshot(format="png"))
        if isinstance(res, dict) and "data" in res:
            img_bytes = base64.b64decode(res["data"])
            filename = f"{save_name}_{int(time.time())}.png"
            filepath = os.path.join(SCREENSHOTS_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(img_bytes)
            return json.dumps({
                "status": "success",
                "screenshot_path": filepath,
                "format": res.get("format")
            })
        return json.dumps({"status": "error", "message": "No image data returned"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


# ==============================================================================
# SPECIALIZED LINKEDIN & DATA DOMAIN TOOLS
# ==============================================================================

@tool
def db_check_is_connected(profile_url: str) -> str:
    """
    Checks if a candidate profile URL has already had a connection REQUEST sent in this session.
    NOTE: This only blocks re-sending a connection invite. It does NOT check LinkedIn's actual
    connection status — the browser screenshot is the source of truth for that.
    Returns already_connected=True only if we have already MESSAGED them (strongest guarantee).

    Args:
        profile_url: The candidate profile URL to check.
    """
    already_messaged = db.is_already_messaged(profile_url)
    already_in_db = db.is_already_connected(profile_url)
    return json.dumps({
        "profile_url": profile_url,
        "already_connected": already_in_db,
        "already_messaged": already_messaged,
        "skip_outreach": already_messaged  # Only hard-skip if we already sent them a message
    })

@tool
def db_record_connection_success(profile_url: str, full_name: str, headline: str, query_used: str, target_goal: int = 50) -> str:
    """
    Records a successful connection request in SQLite DB, increments daily counter, and enforces 10-20 second human pacing delay.

    Args:
        profile_url: Candidate's profile URL.
        full_name: Candidate's full name.
        headline: Candidate's headline snippet.
        query_used: Search tag query used.
        target_goal: Daily connection target goal.
    """
    db.record_connection(profile_url, full_name, headline, query_used)
    new_count = db.increment_daily_count(target_goal=target_goal)
    pacing_delay = random.uniform(10.0, 20.0)
    time.sleep(pacing_delay)

    return json.dumps({
        "status": "recorded",
        "profile_url": profile_url,
        "name": full_name,
        "daily_count": new_count,
        "target_goal": target_goal,
        "pacing_delay_sec": round(pacing_delay, 1)
    })

@tool
def tags_get_next_search_tag() -> str:
    """
    Gets the highest priority search tag query from tags.json for LinkedIn search.
    """
    tag_obj = tags_manager.get_next_search_tag()
    return json.dumps(tag_obj if tag_obj else {"error": "No tags found"})

@tool
def search_linkedin_people(query: str, page: int = 1) -> str:
    """
    Searches LinkedIn people with a search query tag and optional page number (default 1), and extracts candidates with CSS classes, buttons, and screenshot path.

    Args:
        query: Search query tag (e.g. '"prop firm trader"').
        page: Page number for pagination (e.g. 1, 2, 3). Default is 1.
    """
    try:
        tags_manager.record_tag_usage(query)
        encoded_query = urllib.parse.quote(query)
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_query}&origin=GLOBAL_SEARCH_HEADER"
        if page > 1:
            search_url += f"&page={page}"
        
        try:
            res_nav = run_async(bridge.navigate(search_url))
        except Exception as nav_err:
            print(f"⚠️ [search_linkedin_people] Navigation warning: {nav_err}. Checking current page...")
            
        time.sleep(random.uniform(3.5, 5.0))

        extract_script = """
        (() => {
          const results = [];
          const cardSelectors = [
            '.reusable-search__result-container',
            'li.grid',
            'div.entity-result',
            '[data-chameleon-result-urn]',
            'ul.reusable-search__entity-result-list > li',
            'li[class*="result"]'
          ];
          
          let cards = [];
          for (const sel of cardSelectors) {
            const found = document.querySelectorAll(sel);
            if (found.length > 0) {
              cards = Array.from(found);
              break;
            }
          }
          
          cards.forEach(card => {
            const linkEl = card.querySelector('a.app-aware-link[href*="/in/"], a[href*="/in/"]');
            const nameEl = card.querySelector('.entity-result__title-text a span[aria-hidden="true"], span.entity-result__title-text, .entity-result__title-text a');
            const headlineEl = card.querySelector('.entity-result__primary-subtitle, [class*="primary-subtitle"]');
            const buttonEl = card.querySelector('button[aria-label*="Connect"], button[aria-label*="Invite"], button.artdeco-button--secondary');
            
            if (linkEl) {
              const rawUrl = linkEl.href;
              const cleanUrl = rawUrl.split('?')[0].replace(/\\/$/, '');
              const name = nameEl ? nameEl.textContent.trim().replace(/\\s+/g, ' ') : '';
              const headline = headlineEl ? headlineEl.textContent.trim().replace(/\\s+/g, ' ') : '';
              
              let buttonText = buttonEl ? buttonEl.textContent.trim() : '';
              let buttonClass = buttonEl ? buttonEl.className : '';
              let buttonAria = buttonEl ? (buttonEl.getAttribute('aria-label') || '') : '';
              
              const canConnect = !!buttonEl && (buttonText.toLowerCase().includes('connect') || buttonAria.toLowerCase().includes('connect') || buttonAria.toLowerCase().includes('invite'));
              
              results.push({
                name: name,
                headline: headline,
                profile_url: cleanUrl,
                can_connect: canConnect,
                button_text: buttonText,
                button_class: buttonClass,
                button_aria: buttonAria
              });
            }
          });
          return results;
        })()
        """
        res = run_async(bridge.evaluate(extract_script))
        candidates = res.get("value", []) if isinstance(res, dict) else []
        
        # Deduplicate by profile_url
        unique_candidates = []
        seen_urls = set()
        for c in candidates:
            if c.get("profile_url") and c["profile_url"] not in seen_urls:
                seen_urls.add(c["profile_url"])
                unique_candidates.append(c)

        unconnected = [c for c in unique_candidates if not db.is_already_connected(c["profile_url"])]

        # Save visual screenshot
        screenshot_path = None
        try:
            ss_res = run_async(bridge.screenshot(format="png"))
            if isinstance(ss_res, dict) and "data" in ss_res:
                img_bytes = base64.b64decode(ss_res["data"])
                filename = f"search_{int(time.time())}.png"
                screenshot_path = os.path.join(SCREENSHOTS_DIR, filename)
                with open(screenshot_path, "wb") as f:
                    f.write(img_bytes)
        except Exception:
            pass

        return json.dumps({
            "query": query,
            "page": page,
            "total_found": len(unique_candidates),
            "unconnected_count": len(unconnected),
            "screenshot_path": screenshot_path,
            "candidates": unconnected
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to search LinkedIn: {str(e)}"})

@tool
def browser_click_next_page() -> str:
    """
    Scrolls down to the bottom of the current search results page and clicks the 'Next' pagination button.
    """
    try:
        # Scroll to bottom to ensure pagination controls are loaded
        run_async(bridge.scroll("down", 1000))
        time.sleep(1.5)

        next_page_script = """
        (() => {
          const nextBtn = document.querySelector('button[aria-label="Next"], button.artdeco-pagination__button--next');
          if (!nextBtn || nextBtn.disabled) {
            return { success: false, reason: "Next pagination button not found or disabled" };
          }
          nextBtn.scrollIntoView({ block: 'center' });
          nextBtn.click();
          return { success: true };
        })()
        """
        res = run_async(bridge.evaluate(next_page_script))
        result = res.get("value", {}) if isinstance(res, dict) else {}
        time.sleep(3.0)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed to click next page: {str(e)}"})

@tool
def connect_with_candidate(profile_url: str, full_name: str, headline: str, query_used: str, target_goal: int = 50) -> str:
    """
    Sends direct connection request (NO NOTES) to candidate profile.
    Tries connecting directly from the search page card first. If unavailable, navigates to profile URL as fallback.
    Verifies that candidate state strictly transitions to 'Pending' in the DOM and screenshot.
    Enforces 10-20s human pacing delay.

    Args:
        profile_url: Candidate's profile URL.
        full_name: Full name.
        headline: Headline snippet.
        query_used: Search query tag used.
        target_goal: Target connection goal.
    """
    try:
        # ONLY skip if we have ALREADY SENT THEM A MESSAGE.
        # db.is_already_connected() is NOT used here — the LinkedIn profile button is the ground truth.
        if db.is_already_messaged(profile_url):
            return json.dumps({
                "status": "skipped",
                "reason": f"Already messaged '{full_name}' previously. No action needed.",
                "already_messaged": True
            })

        # Evaluate lead probability score
        score_info = lead_scorer.calculate_lead_score(headline=headline)
        lead_score = score_info["score"]
        is_high_probable = score_info["is_high_probable"]
        persona = score_info["persona"]
        reasons = score_info["reasons"]

        # Record candidate score in DB
        db.record_lead_score(
            profile_url=profile_url,
            score=lead_score,
            reasons=reasons,
            persona=persona,
            is_high_probable=is_high_probable,
            full_name=full_name,
            headline=headline
        )

        if not is_high_probable:
            return json.dumps({
                "status": "skipped",
                "reason": f"Skipped: Lead probability score too low ({lead_score}% < {score_info['threshold']}%)",
                "lead_score": lead_score,
                "persona": persona,
                "reasons": reasons
            })


        # Step 1: Try direct connection on current search page if candidate card is present
        search_connect_script = f"""
        (async () => {{
          const targetUrlClean = ({json.dumps(profile_url)} || '').split('?')[0].replace(/\\/$/, '').toLowerCase();
          const targetNameLower = ({json.dumps(full_name)} || '').trim().toLowerCase();

          const handleModalAndVerifyPending = async (cardEl) => {{
            let modalOpened = false;
            let modalClicked = false;
            let modalRequiresEmail = false;

            for (let i = 0; i < 12; i++) {{
              const modal = document.querySelector('div[role="dialog"], .artdeco-modal, div[id*="artdeco-modal"]');
              if (modal) {{
                modalOpened = true;
                const modalText = (modal.textContent || '').toLowerCase();
                if (modalText.includes('enter email') || modalText.includes('verify email') || modalText.includes('know this member')) {{
                  modalRequiresEmail = true;
                  const closeBtn = modal.querySelector('button[aria-label*="Dismiss"], button.artdeco-modal__dismiss, button[aria-label*="Close"]');
                  if (closeBtn) closeBtn.click();
                  break;
                }}

                const buttons = Array.from(modal.querySelectorAll('button, div[role="button"], span'));
                const sendBtn = buttons.find(b => {{
                  const text = (b.textContent || '').trim().toLowerCase();
                  const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                  return (
                    text.includes('send without a note') ||
                    text.includes('send now') ||
                    text === 'send' ||
                    aria.includes('send without a note') ||
                    aria.includes('send now')
                  );
                }});
                if (sendBtn) {{
                  sendBtn.click();
                  modalClicked = true;
                  await new Promise(r => setTimeout(r, 1200));
                  break;
                }}
              }}
              await new Promise(r => setTimeout(r, 250));
            }}

            if (modalRequiresEmail) {{
              return {{ success: false, reason: "Candidate requires email verification to connect" }};
            }}

            let isPending = false;
            for (let i = 0; i < 12; i++) {{
              const targetScope = cardEl || document;
              const buttons = Array.from(targetScope.querySelectorAll('button, span, div[role="button"]'));
              isPending = buttons.some(b => {{
                const text = (b.textContent || '').trim().toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return text.includes('pending') || aria.includes('pending') || text.includes('withdraw') || text.includes('invitation sent');
              }});

              if (isPending) break;

              const toast = document.querySelector('.artdeco-toast, .artdeco-inline-feedback--success, [class*="toast"]');
              if (toast && (toast.textContent || '').toLowerCase().includes('sent')) {{
                isPending = true;
                break;
              }}
              await new Promise(r => setTimeout(r, 250));
            }}

            if (!isPending && modalOpened && !modalClicked) {{
              return {{ success: false, reason: "Connect modal opened but 'Send without a note' button was not found or clicked" }};
            }}

            return {{ success: isPending || modalClicked, verified_pending: isPending, modalOpened, modalClicked }};
          }};

          if (window.location.href.includes('/search/results/people/')) {{
            const cards = Array.from(document.querySelectorAll('.entity-result, li.reusable-search__result-container'));
            let targetCard = cards.find(c => {{
              const link = c.querySelector('.app-aware-link, a[href*="/in/"]');
              if (link) {{
                const cleanHref = link.href.split('?')[0].replace(/\\/$/, '').toLowerCase();
                if (cleanHref.includes(targetUrlClean) || targetUrlClean.includes(cleanHref)) return true;
              }}
              if (targetNameLower) {{
                const nameEl = c.querySelector('.entity-result__title-text, [class*="title-text"]');
                if (nameEl && nameEl.textContent.toLowerCase().includes(targetNameLower)) return true;
              }}
              return false;
            }});

            if (targetCard) {{
              const connectBtn = targetCard.querySelector('button[aria-label*="Connect"], button[aria-label*="Invite"], button.artdeco-button--secondary');
              if (connectBtn) {{
                const btnText = (connectBtn.textContent || '').trim().toLowerCase();
                const btnAria = (connectBtn.getAttribute('aria-label') || '').toLowerCase();
                if (btnText.includes('connect') || btnAria.includes('connect') || btnAria.includes('invite')) {{
                  connectBtn.scrollIntoView({{ block: 'center' }});
                  connectBtn.click();
                  const modalRes = await handleModalAndVerifyPending(targetCard);
                  return {{ ...modalRes, mode: 'search_page_direct' }};
                }}
              }}
            }}
          }}
          return {{ requireProfileNavigation: true }};
        }})()
        """
        
        search_res = run_async(bridge.evaluate(search_connect_script))
        search_val = search_res.get("value", {}) if isinstance(search_res, dict) else {}

        profile_navigated = False
        if search_val.get("requireProfileNavigation", False):
            # Step 2: Fallback to Profile Page navigation
            try:
                run_async(bridge.navigate(profile_url))
                profile_navigated = True
            except Exception as nav_err:
                print(f"[WARN] [connect_with_candidate] Navigation warning: {nav_err}. Proceeding...")
            time.sleep(random.uniform(2.5, 4.0))

            # === GROUND TRUTH: Read the actual button state on the profile page ===
            button_check_script = """
            (() => {
              const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
              for (const b of buttons) {
                const text = (b.textContent || '').trim().toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                if (text === 'message' || aria.includes('message') && !aria.includes('more')) {
                  return { button_state: 'message', label: text || aria };
                }
                if (text.includes('pending') || aria.includes('pending') || text.includes('withdraw')) {
                  return { button_state: 'pending', label: text || aria };
                }
                if (text === 'connect' || aria.includes('invite') || (aria.includes('connect') && !aria.includes('more'))) {
                  return { button_state: 'connect', label: text || aria };
                }
                if (text === 'follow' || aria.includes('follow')) {
                  return { button_state: 'follow', label: text || aria };
                }
              }
              return { button_state: 'unknown' };
            })()
            """
            btn_res = run_async(bridge.evaluate(button_check_script))
            btn_state = btn_res.get("value", {}).get("button_state", "unknown") if isinstance(btn_res, dict) else "unknown"

            if btn_state == "message":
                # Already a 1st-degree connection — upsert as accepted, queue for messaging
                db.upsert_accepted_connection(profile_url, full_name=full_name, headline=headline)
                return json.dumps({
                    "status": "already_connected",
                    "reason": f"'{full_name}' is already a 1st-degree connection (button shows 'Message'). Queued for welcome message.",
                    "profile_url": profile_url,
                    "name": full_name,
                    "headline": headline,
                    "action": "queue_for_message"
                })
            elif btn_state == "pending":
                # Connection request already sent — do nothing
                return json.dumps({
                    "status": "skipped",
                    "reason": f"Connection request to '{full_name}' is already pending (button shows 'Pending'/'Withdraw').",
                    "profile_url": profile_url
                })
            # btn_state == "connect" or "unknown" → proceed with connect



            profile_connect_script = """
            (async () => {
              const handleModalAndVerifyPending = async () => {
                let modalOpened = false;
                let modalClicked = false;
                let modalRequiresEmail = false;

                for (let i = 0; i < 12; i++) {
                  const modal = document.querySelector('div[role="dialog"], .artdeco-modal, div[id*="artdeco-modal"]');
                  if (modal) {
                    modalOpened = true;
                    const modalText = (modal.textContent || '').toLowerCase();
                    if (modalText.includes('enter email') || modalText.includes('verify email') || modalText.includes('know this member')) {
                      modalRequiresEmail = true;
                      const closeBtn = modal.querySelector('button[aria-label*="Dismiss"], button.artdeco-modal__dismiss, button[aria-label*="Close"]');
                      if (closeBtn) closeBtn.click();
                      break;
                    }

                    const buttons = Array.from(modal.querySelectorAll('button, div[role="button"], span'));
                    const sendBtn = buttons.find(b => {
                      const text = (b.textContent || '').trim().toLowerCase();
                      const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                      return (
                        text.includes('send without a note') ||
                        text.includes('send now') ||
                        text === 'send' ||
                        aria.includes('send without a note') ||
                        aria.includes('send now')
                      );
                    });
                    if (sendBtn) {
                      sendBtn.click();
                      modalClicked = true;
                      await new Promise(r => setTimeout(r, 1200));
                      break;
                    }
                  }
                  await new Promise(r => setTimeout(r, 250));
                }

                if (modalRequiresEmail) {
                  return { success: false, reason: "Candidate requires email verification to connect" };
                }

                let isPending = false;
                for (let i = 0; i < 12; i++) {
                  const buttons = Array.from(document.querySelectorAll('button, span, div[role="button"]'));
                  isPending = buttons.some(b => {
                    const text = (b.textContent || '').trim().toLowerCase();
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    return text.includes('pending') || aria.includes('pending') || text.includes('withdraw') || text.includes('invitation sent');
                  });

                  if (isPending) break;

                  const toast = document.querySelector('.artdeco-toast, .artdeco-inline-feedback--success, [class*="toast"]');
                  if (toast && (toast.textContent || '').toLowerCase().includes('sent')) {
                    isPending = true;
                    break;
                  }
                  await new Promise(r => setTimeout(r, 250));
                }

                if (!isPending && modalOpened && !modalClicked) {
                  return { success: false, reason: "Connect modal opened but 'Send without a note' button was not found or clicked" };
                }

                return { success: isPending || modalClicked, verified_pending: isPending, modalOpened, modalClicked };
              };

              let connectBtn = Array.from(document.querySelectorAll('button')).find(b => {
                const text = (b.textContent || '').trim().toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return text === 'connect' || aria.includes('invite') || (aria.includes('connect') && !aria.includes('more'));
              });

              if (!connectBtn) {
                const moreBtn = Array.from(document.querySelectorAll('button')).find(b => {
                  const text = (b.textContent || '').trim().toLowerCase();
                  const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                  return text === 'more' || text === 'more actions' || aria.includes('more actions');
                });

                if (moreBtn) {
                  moreBtn.click();
                  await new Promise(r => setTimeout(r, 800));
                  connectBtn = Array.from(document.querySelectorAll('div[role="button"], button, li')).find(b => {
                    const text = (b.textContent || '').trim().toLowerCase();
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    return text.includes('connect') || aria.includes('connect');
                  });
                }
              }

              if (!connectBtn) {
                return { success: false, reason: "Connect button not found on profile or dropdown" };
              }

              connectBtn.scrollIntoView({ block: 'center' });
              connectBtn.click();
              const modalRes = await handleModalAndVerifyPending();

              return { ...modalRes, mode: 'profile_direct' };
            })()
            """
            profile_res = run_async(bridge.evaluate(profile_connect_script))
            result = profile_res.get("value", {}) if isinstance(profile_res, dict) else {}
        else:
            result = search_val

        # Capture post-connect screenshot
        screenshot_path = None
        try:
            ss_res = run_async(bridge.screenshot(format="png"))
            if isinstance(ss_res, dict) and "data" in ss_res:
                img_bytes = base64.b64decode(ss_res["data"])
                filename = f"connect_{int(time.time())}.png"
                screenshot_path = os.path.join(SCREENSHOTS_DIR, filename)
                with open(screenshot_path, "wb") as f:
                    f.write(img_bytes)
        except Exception:
            pass

        if not result.get("success", False):
            return json.dumps({
                "status": "failed",
                "verified_pending": False,
                "reason": result.get("reason", "Connection not confirmed in DOM (state did not change to Pending)"),
                "screenshot_path": screenshot_path
            })

        # Save to database with lead score and qualification metadata
        db.record_connection(
            profile_url=profile_url,
            full_name=full_name,
            headline=headline,
            query_used=query_used,
            lead_score=lead_score,
            lead_score_reasons=reasons,
            persona=persona,
            is_high_probable=is_high_probable,
            status="pending"
        )
        new_count = db.increment_daily_count(target_goal=target_goal)

        pacing_delay = random.uniform(10.0, 20.0)
        time.sleep(pacing_delay)

        return json.dumps({
            "status": "connected",
            "verified_pending": result.get("verified_pending", True),
            "mode": result.get("mode", "direct"),
            "profile_navigated": profile_navigated,
            "profile_url": profile_url,
            "name": full_name,
            "daily_count": new_count,
            "target_goal": target_goal,
            "pacing_delay_sec": round(pacing_delay, 1),
            "screenshot_path": screenshot_path
        })
    except Exception as e:
        return json.dumps({"status": "error", "reason": str(e)})

@tool
def analyze_ascentrader_and_update_tags() -> str:
    """
    Navigates to https://ascentrader.com, captures site copy, uses GLM-5.3 to re-rank tags in tags.json and generate new target trader search terms.
    """
    try:
        run_async(bridge.navigate("https://ascentrader.com"))
        time.sleep(3.5)

        extract_copy_script = """
        (() => {
          const headings = Array.from(document.querySelectorAll('h1, h2, h3')).map(h => h.textContent.trim()).filter(Boolean);
          const paragraphs = Array.from(document.querySelectorAll('p')).map(p => p.textContent.trim()).filter(p => p.length > 20).slice(0, 10);
          return { headings, paragraphs };
        })()
        """
        res = run_async(bridge.evaluate(extract_copy_script))
        site_data = res.get("value", {}) if isinstance(res, dict) else {}

        headings = site_data.get("headings", [])
        paragraphs = site_data.get("paragraphs", [])

        site_summary = f"Headlines: {' | '.join(headings[:8])}\nDetails: {' '.join(paragraphs[:5])}"
        current_tags = tags_manager.load_tags()
        tag_list_str = ", ".join([t["tag"] for t in current_tags[:30]])

        prompt = f"""
You are an expert growth marketer for Ascentrader (https://ascentrader.com), a platform for forex and prop firm traders.
Here is the current homepage content of Ascentrader:
{site_summary}

Here are some current search tags:
{tag_list_str}

Analyze Ascentrader's current value proposition (e.g. journaling, MT5 integration, risk management, drawdown analytics).
Produce a JSON array of up to 15 search tags, assigning a priority score from 50 to 100 based on alignment with Ascentrader's core features.
Include existing seed tags (re-ranked) and introduce up to 5 NEW dynamic search tags that prop firm / forex traders search on LinkedIn.

Return ONLY valid JSON in this exact structure:
[
  {{"tag": "\"example search term\"", "priority": 95, "category": "prop_firm", "is_dynamic": false}},
  ...
]
"""
        response = glm_53(messages=[{"role": "user", "content": prompt}])
        response_text = response.content if hasattr(response, "content") else str(response)

        import re
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            ranked_tags = json.loads(json_match.group(0))
            tags_manager.update_tag_priorities(ranked_tags)
            return json.dumps({
                "status": "success",
                "message": f"Updated priorities for {len(ranked_tags)} tags based on Ascentrader homepage analysis.",
                "sample_tags": [t["tag"] for t in ranked_tags[:5]]
            }, indent=2)
        else:
            return json.dumps({"status": "warning", "message": "Could not parse JSON from LLM response", "raw": response_text[:200]})
    except Exception as e:
        return json.dumps({"status": "error", "reason": str(e)})

# ==============================================================================
# EXPANDED LEAD QUALIFICATION & CONVERSION TOOLS
# ==============================================================================

@tool
def score_candidate_lead(profile_url: str, full_name: str, headline: str) -> str:
    """
    Evaluates a candidate's headline using Ascentrader's probability formula.
    Returns the qualification score, whether they meet the threshold, persona, and breakdown reasons.

    Args:
        profile_url: Candidate's LinkedIn profile URL.
        full_name: Full name of the candidate.
        headline: Professional headline from candidate's profile or search card.
    """
    try:
        res = lead_scorer.calculate_lead_score(headline=headline)
        db.record_lead_score(
            profile_url=profile_url,
            score=res["score"],
            reasons=res["reasons"],
            persona=res["persona"],
            is_high_probable=res["is_high_probable"],
            full_name=full_name,
            headline=headline
        )
        return json.dumps({
            "status": "success",
            "profile_url": profile_url,
            "name": full_name,
            "score": res["score"],
            "is_high_probable": res["is_high_probable"],
            "persona": res["persona"],
            "reasons": res["reasons"]
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def send_welcome_message(profile_url: str, full_name: str, headline: str, variant_override: Optional[str] = None) -> str:
    """
    Sends an A/B tested welcome message (Variant A standard or Variant B personalized) to an accepted connection.
    Navigates to their profile/message box, types message with human pacing, submits, captures screenshot, and logs to DB.

    Args:
        profile_url: Candidate's LinkedIn profile URL.
        full_name: Full name of the candidate.
        headline: Headline of candidate.
        variant_override: Optional override for message variant ('variant_a_standard' or 'variant_b_personalized').
    """
    try:
        # Layer 1: Strict Database Pre-Flight Guard
        if db.is_already_messaged(profile_url):
            return json.dumps({
                "status": "skipped",
                "reason": f"ALREADY MESSAGED: Candidate '{full_name}' was already sent a message previously in the database. Aborting to prevent duplicate message.",
                "profile_url": profile_url
            })

        score_info = lead_scorer.calculate_lead_score(headline=headline)
        persona = score_info.get("persona", "Trader")
        
        variant, msg_text = messaging_engine.generate_welcome_message(
            full_name=full_name,
            headline=headline,
            persona=persona,
            variant_override=variant_override
        )

        # Step 1: Navigate to candidate profile
        run_async(bridge.navigate(profile_url))
        time.sleep(random.uniform(2.5, 3.5))

        # Step 2: Open message modal or thread
        open_msg_script = """
        (async () => {
          // If chat textbox is already open and ready
          const inputReady = document.querySelector('div.msg-form__contenteditable, div[role="textbox"]');
          if (inputReady) {
            return { clicked: true, already_open: true };
          }
          let msgBtn = Array.from(document.querySelectorAll('button')).find(b => {
            const text = (b.textContent || '').trim().toLowerCase();
            const aria = (b.getAttribute('aria-label') || '').toLowerCase();
            return text === 'message' || (aria.includes('message') && !aria.includes('more'));
          });
          if (msgBtn) {
            msgBtn.scrollIntoView({ block: 'center' });
            msgBtn.click();
            await new Promise(r => setTimeout(r, 1500));
            return { clicked: true };
          }
          return { clicked: false, reason: "Message button not found on profile" };
        })()
        """
        open_res = run_async(bridge.evaluate(open_msg_script))
        time.sleep(1.5)
        open_val = open_res.get("value", {}) if isinstance(open_res, dict) else {}
        if not open_val.get("clicked"):
            return json.dumps({
                "status": "failed",
                "reason": open_val.get("reason", "Message button not found on profile"),
                "profile_url": profile_url
            })

        # Layer 2: In-DOM LinkedIn Message Thread History Guard
        # Actively wait for conversation history to load and detect any prior messages
        check_history_script = """
        (async () => {
          // Poll for up to 4.5 seconds to ensure message history has loaded from LinkedIn servers
          const selectors = [
            '.msg-s-event-listitem__body',
            '.msg-s-message-list__event',
            '.msg-s-event-listitem',
            '.msg-s-message-group',
            '[data-event-urn]',
            '.msg-s-message-list-container li',
            'p[class*="msg-s-event-listitem__body"]',
            'div[data-view-name*="message"]'
          ];
          
          let existingCount = 0;
          for (let i = 0; i < 15; i++) {
            for (const sel of selectors) {
              const elements = Array.from(document.querySelectorAll(sel)).filter(el => {
                const text = (el.textContent || '').trim();
                return text.length > 0;
              });
              if (elements.length > 0) {
                existingCount = elements.length;
                return { existing_count: existingCount, selector_matched: sel, sample: elements[0].textContent.trim().slice(0, 60) };
              }
            }
            // If input box is already ready and no loading spinner, check once more
            const inputReady = document.querySelector('div.msg-form__contenteditable, div[role="textbox"]');
            const spinner = document.querySelector('.artdeco-spinner');
            if (inputReady && !spinner && i >= 6) {
              break;
            }
            await new Promise(r => setTimeout(r, 300));
          }
          return { existing_count: existingCount };
        })()
        """
        hist_res = run_async(bridge.evaluate(check_history_script))
        hist_val = hist_res.get("value", {}) if isinstance(hist_res, dict) else {}
        if hist_val.get("existing_count", 0) > 0:
            # Record in DB so future runs instantly skip
            db.record_message_sent(profile_url, "existing_thread", "Detected existing message thread on LinkedIn", full_name=full_name, headline=headline)
            return json.dumps({
                "status": "skipped",
                "reason": f"ALREADY MESSAGED: Found {hist_val['existing_count']} existing message(s) in LinkedIn thread for '{full_name}'. Skipping to prevent spamming.",
                "profile_url": profile_url,
                "detected_via": hist_val.get("selector_matched")
            })

        # Step 3: Type and send message
        send_script = f"""
        (async () => {{
          const msgContent = {json.dumps(msg_text)};
          let input = null;
          for (let i = 0; i < 15; i++) {{
            input = document.querySelector('div.msg-form__contenteditable[contenteditable="true"], div[role="textbox"]');
            if (input) break;
            await new Promise(r => setTimeout(r, 250));
          }}
          if (!input) return {{ success: false, reason: "Message input box not found" }};

          input.focus();
          document.execCommand('insertText', false, msgContent);
          await new Promise(r => setTimeout(r, 800));

          const sendBtn = document.querySelector('button.msg-form__send-button, button[type="submit"]');
          if (sendBtn && !sendBtn.disabled) {{
            sendBtn.click();
            await new Promise(r => setTimeout(r, 1500));
            return {{ success: true }};
          }}
          return {{ success: false, reason: "Send button not found or disabled" }};
        }})()
        """
        send_res = run_async(bridge.evaluate(send_script))
        send_val = send_res.get("value", {}) if isinstance(send_res, dict) else {}

        # Capture screenshot
        screenshot_path = None
        try:
            ss_res = run_async(bridge.screenshot(format="png"))
            if isinstance(ss_res, dict) and "data" in ss_res:
                img_bytes = base64.b64decode(ss_res["data"])
                filename = f"msg_{int(time.time())}.png"
                screenshot_path = os.path.join(SCREENSHOTS_DIR, filename)
                with open(screenshot_path, "wb") as f:
                    f.write(img_bytes)
        except Exception:
            pass

        if not send_val.get("success"):
            return json.dumps({
                "status": "failed",
                "reason": send_val.get("reason", "Could not send message in DOM"),
                "screenshot_path": screenshot_path
            })

        db.record_message_sent(profile_url, variant, msg_text)
        
        # Pacing delay
        pacing = random.uniform(12.0, 20.0)
        time.sleep(pacing)

        return json.dumps({
            "status": "success",
            "profile_url": profile_url,
            "name": full_name,
            "variant": variant,
            "message_text": msg_text,
            "screenshot_path": screenshot_path,
            "pacing_delay_sec": round(pacing, 1)
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def sync_accepted_connections() -> str:
    """
    Navigates to LinkedIn Connections page (https://www.linkedin.com/mynetwork/invite-connect/connections/),
    scrapes ALL visible 1st-degree connections from the page, upserts each into the database as 'accepted',
    and returns those who have NEVER been messaged yet.

    IMPORTANT: The browser/LinkedIn page is the ONLY source of truth for whether someone is connected.
    This tool does NOT require someone to already be in the DB — it accepts everyone visible on the page.
    """
    try:
        run_async(bridge.navigate("https://www.linkedin.com/mynetwork/invite-connect/connections/"))
        time.sleep(3.5)

        extract_script = """
        (() => {
          const cards = Array.from(document.querySelectorAll('li.mn-connection-card, div.mn-connection-card'));
          const connections = cards.map(c => {
            const link = c.querySelector('a[href*="/in/"]');
            const nameEl = c.querySelector('.mn-connection-card__name, span.mn-connection-card__name');
            const occEl = c.querySelector('.mn-connection-card__occupation');
            return {
              profile_url: link ? link.href.split('?')[0].replace(/\\/$/, '') : null,
              name: nameEl ? nameEl.textContent.trim() : '',
              headline: occEl ? occEl.textContent.trim() : ''
            };
          }).filter(c => c.profile_url);
          return connections;
        })()
        """
        res = run_async(bridge.evaluate(extract_script))
        conns = res.get("value", []) if isinstance(res, dict) else []

        unmessaged_connections = []
        for c in conns:
            url = c.get("profile_url")
            name = c.get("name", "")
            headline = c.get("headline", "")
            if not url:
                continue

            # GROUND TRUTH: LinkedIn connections page = they ARE connected to us.
            # Upsert into DB as accepted regardless of whether they were in DB before.
            db.upsert_accepted_connection(url, full_name=name, headline=headline)

            # Only queue for messaging if they have NEVER been messaged
            if not db.is_already_messaged(url):
                unmessaged_connections.append({
                    "profile_url": url,
                    "full_name": name,
                    "headline": headline
                })

        return json.dumps({
            "status": "success",
            "total_scanned_on_page": len(conns),
            "unmessaged_connections": len(unmessaged_connections),
            "ready_to_message": unmessaged_connections[:10]  # Return up to 10 for agent to process
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def verify_and_message_connections_batch(start_index: int = 0, chunk_size: int = 5) -> str:
    """
    Inspects a chunk of accepted connections from LinkedIn connections page (https://www.linkedin.com/mynetwork/invite-connect/connections/).
    For the slice of candidates [start_index : start_index + chunk_size]:
    - Opens each candidate's chat thread on LinkedIn to verify live message history in the DOM.
    - If unmessaged: sends the personalized A/B Welcome Message with Google Calendar booking link, and records in DB.
    - If already messaged: records existing_thread in DB and skips.
    - If ANY unmessaged connections were found and messaged in this chunk, there may be more, so recommendation is 'continue_next_chunk'.
    - If ALL candidates in this chunk were already messaged, recommendation is 'stop_reached_old_connections'.

    Args:
        start_index: Starting index in the connections list (0 for first 5, 5 for next 5, 10 for next 5, etc.).
        chunk_size: Number of connections to inspect in this batch (default 5).
    """
    try:
        # Navigate to connections page if not already there
        run_async(bridge.navigate("https://www.linkedin.com/mynetwork/invite-connect/connections/"))
        time.sleep(3.5)

        # Smart adaptive scroll: ensure at least (start_index + chunk_size) connection cards are loaded
        needed_cards = start_index + chunk_size
        prev_card_count = -1
        scroll_attempts = 0
        max_scroll_attempts = max(3, (start_index // 4) + 3)

        while scroll_attempts < max_scroll_attempts:
            count_res = run_async(bridge.evaluate("(() => document.querySelectorAll('li.mn-connection-card, div.mn-connection-card, .mn-connection-card, a[href*=\"/in/\"]').length)()"))
            current_card_count = count_res.get("value", 0) if isinstance(count_res, dict) else 0
            if current_card_count >= needed_cards:
                break
            run_async(bridge.scroll(direction="down", amount=1000))
            time.sleep(1.4)
            if current_card_count == prev_card_count and scroll_attempts >= 2:
                # DOM didn't load more cards after scrolling twice -> reached end of list
                break
            prev_card_count = current_card_count
            scroll_attempts += 1

        # Extract all available connection cards
        extract_script = """
        (() => {
          let cards = Array.from(document.querySelectorAll('li.mn-connection-card, div.mn-connection-card, .mn-connection-card'));
          if (cards.length === 0) {
            const allLinks = Array.from(document.querySelectorAll('a[href*="/in/"]'));
            const seenCards = new Set();
            cards = allLinks.map(a => a.closest('li') || a.closest('div')).filter(el => {
              if (!el || seenCards.has(el)) return false;
              seenCards.add(el);
              return true;
            });
          }

          const results = [];
          const seenUrls = new Set();
          for (const c of cards) {
            const link = c.querySelector('a[href*="/in/"]');
            if (!link) continue;
            let rawUrl = link.href.split('?')[0].replace(/\\/$/, '');
            if (!rawUrl.includes('/in/') || rawUrl.endsWith('/in')) continue;
            if (seenUrls.has(rawUrl)) continue;
            seenUrls.add(rawUrl);

            const nameEl = c.querySelector('.mn-connection-card__name, span.mn-connection-card__name, span[aria-hidden="true"]');
            const occEl = c.querySelector('.mn-connection-card__occupation');
            results.push({
              profile_url: rawUrl,
              name: nameEl ? nameEl.textContent.trim() : '',
              headline: occEl ? occEl.textContent.trim() : ''
            });
          }
          return results;
        })()
        """
        res = run_async(bridge.evaluate(extract_script))
        all_conns = res.get("value", []) if isinstance(res, dict) else []

        if start_index >= len(all_conns):
            return json.dumps({
                "status": "end_of_connections",
                "start_index": start_index,
                "total_available": len(all_conns),
                "has_more": False,
                "recommendation": "stop_no_more_connections",
                "message": f"No more connection cards found at index {start_index}."
            }, indent=2)

        chunk = all_conns[start_index : start_index + chunk_size]
        newly_messaged = []
        already_messaged = []

        for candidate in chunk:
            url = candidate.get("profile_url")
            name = candidate.get("name", "")
            headline = candidate.get("headline", "")
            if not url:
                continue

            # Ground truth update: record accepted
            db.upsert_accepted_connection(url, full_name=name, headline=headline)

            # Step 1: Check if DB already recorded a message in this or prior runs
            if db.is_already_messaged(url):
                already_messaged.append({"name": name, "profile_url": url, "reason": "db_verified"})
                continue

            # Step 2: Live DOM Verification by attempting to send welcome message
            # send_welcome_message() checks live DOM thread history. If prior messages exist,
            # it marks DB and returns skipped. If clean, it sends and returns success.
            msg_res_str = send_welcome_message(profile_url=url, full_name=name, headline=headline)
            try:
                msg_res = json.loads(msg_res_str)
            except Exception:
                msg_res = {"status": "error"}

            if msg_res.get("status") == "success":
                newly_messaged.append({
                    "name": name,
                    "profile_url": url,
                    "variant": msg_res.get("variant"),
                    "action": "welcome_message_sent"
                })
            else:
                already_messaged.append({
                    "name": name,
                    "profile_url": url,
                    "reason": msg_res.get("reason", "already_messaged_on_linkedin")
                })

        newly_count = len(newly_messaged)
        has_more = (start_index + chunk_size) < len(all_conns)
        
        # Stop condition: if 0 newly messaged in this chunk, we have hit older previously messaged network!
        # If any were newly messaged AND more exist, continue to next chunk!
        if newly_count > 0 and has_more:
            recommendation = "continue_next_chunk"
        elif not has_more:
            recommendation = "stop_no_more_connections"
        else:
            recommendation = "stop_reached_old_connections"

        return json.dumps({
            "status": "success",
            "start_index": start_index,
            "chunk_size": len(chunk),
            "newly_messaged_count": newly_count,
            "already_messaged_count": len(already_messaged),
            "newly_messaged": newly_messaged,
            "already_messaged": already_messaged,
            "next_start_index": start_index + len(chunk),
            "has_more": has_more,
            "recommendation": recommendation
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def check_replies_and_send_followups(grace_period_hours: int = 48) -> str:
    """
    Checks unreplied leads who reached the 48-hour grace period window.
    Opens their messaging threads to check for replies:
    - If replied: classifies intent, updates DB, and dispatches founder email alert for custom inquiries.
    - If unreplied and follow_up_count == 0: sends a single gentle follow-up check-in message.

    Args:
        grace_period_hours: Minimum hours elapsed since initial outreach message before follow-up (default 48).
    """
    try:
        leads_for_check = db.get_unreplied_leads_for_followup(grace_hours=grace_period_hours)
        if not leads_for_check:
            return json.dumps({"status": "success", "message": "No leads pending 48h follow-up check."})

        results = []
        for lead in leads_for_check[:5]: # Process up to 5 per batch to maintain safety
            p_url = lead["profile_url"]
            name = lead["full_name"]
            first_name = messaging_engine.extract_first_name(name)
            headline = lead["headline"] or ""

            # Navigate to profile
            run_async(bridge.navigate(p_url))
            time.sleep(random.uniform(2.5, 3.5))

            # Check if there is an active message thread with a reply
            inspect_thread_script = """
            (async () => {
              let msgBtn = Array.from(document.querySelectorAll('button')).find(b => {
                const text = (b.textContent || '').trim().toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return text === 'message' || (aria.includes('message') && !aria.includes('more'));
              });
              if (msgBtn) {
                msgBtn.click();
                await new Promise(r => setTimeout(r, 2000));
              }

              // Extract messages
              const bubbles = Array.from(document.querySelectorAll('.msg-s-event-listitem__body, .msg-s-message-list__event'));
              const msgs = bubbles.map(b => b.textContent.trim()).filter(Boolean);
              return { has_thread: msgs.length > 0, messages: msgs.slice(-4) };
            })()
            """
            thread_res = run_async(bridge.evaluate(inspect_thread_script))
            thread_val = thread_res.get("value", {}) if isinstance(thread_res, dict) else {}
            recent_msgs = thread_val.get("messages", [])

            # Check if there is an inbound message from the candidate (different from our sent messages)
            inbound_reply = None
            for m in reversed(recent_msgs):
                # If message does not contain our pitch keywords, it's from the candidate
                if "ascentrader" not in m.lower() and "calendar.app.google" not in m.lower():
                    inbound_reply = m
                    break

            if inbound_reply:
                # Candidate replied!
                classification = notifier.classify_reply_intent(inbound_reply, name)
                db.record_reply(p_url, inbound_reply, classification["intent"])
                
                # If custom inquiry or positive, dispatch email alert to founder
                email_sent = False
                if classification["requires_alert"]:
                    email_sent = notifier.send_founder_email_alert(
                        candidate_name=name,
                        headline=headline,
                        profile_url=p_url,
                        reply_text=inbound_reply,
                        intent=classification["intent"],
                        summary=classification["summary"]
                    )
                results.append({
                    "name": name,
                    "action": "reply_detected",
                    "intent": classification["intent"],
                    "email_alert_dispatched": email_sent
                })
            else:
                # No reply detected: Send single follow-up check-in
                follow_up_msg = messaging_engine.build_single_followup(first_name)
                
                send_followup_script = f"""
                (async () => {{
                  const followText = {json.dumps(follow_up_msg)};
                  const input = document.querySelector('div.msg-form__contenteditable[contenteditable="true"], div[role="textbox"]');
                  if (!input) return {{ success: false, reason: "Input not found" }};
                  input.focus();
                  document.execCommand('insertText', false, followText);
                  await new Promise(r => setTimeout(r, 600));

                  const sendBtn = document.querySelector('button.msg-form__send-button, button[type="submit"]');
                  if (sendBtn && !sendBtn.disabled) {{
                    sendBtn.click();
                    await new Promise(r => setTimeout(r, 1200));
                    return {{ success: true }};
                  }}
                  return {{ success: false, reason: "Send button disabled or missing" }};
                }})()
                """
                send_res = run_async(bridge.evaluate(send_followup_script))
                db.record_followup_sent(p_url, follow_up_msg)
                results.append({
                    "name": name,
                    "action": "single_followup_sent",
                    "follow_up_text": follow_up_msg
                })

            time.sleep(random.uniform(10.0, 15.0))

        return json.dumps({"status": "success", "processed_leads": results}, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def scan_backlog_connections_and_message(min_score: int = 70, limit: int = 15) -> str:
    """
    Traverses existing 1st-degree connections at /mynetwork/invite-connect/connections/,
    calculates lead probability scores, and messages unmessaged high-probability leads.

    Args:
        min_score: Minimum lead probability score required to qualify for outreach (default 70).
        limit: Maximum number of backlog leads to qualify and return in this batch (default 15).
    """
    try:
        run_async(bridge.navigate("https://www.linkedin.com/mynetwork/invite-connect/connections/"))
        time.sleep(3.5)

        extract_script = """
        (() => {
          const cards = Array.from(document.querySelectorAll('li.mn-connection-card, div.mn-connection-card'));
          return cards.map(c => {
            const link = c.querySelector('a[href*="/in/"]');
            const nameEl = c.querySelector('.mn-connection-card__name, span.mn-connection-card__name');
            const occEl = c.querySelector('.mn-connection-card__occupation');
            return {
              profile_url: link ? link.href.split('?')[0].replace(/\\/$/, '') : null,
              full_name: nameEl ? nameEl.textContent.trim() : '',
              headline: occEl ? occEl.textContent.trim() : ''
            };
          }).filter(c => c.profile_url);
        })()
        """
        res = run_async(bridge.evaluate(extract_script))
        connections = res.get("value", []) if isinstance(res, dict) else []

        qualified_backlog = []
        for c in connections:
            url = c["profile_url"]
            name = c["full_name"]
            headline = c["headline"]

            score_data = lead_scorer.calculate_lead_score(headline=headline, threshold=min_score)
            score = score_data["score"]
            is_high = score_data["is_high_probable"]

            # Save / update in DB
            db.record_lead_score(
                profile_url=url,
                score=score,
                reasons=score_data["reasons"],
                persona=score_data["persona"],
                is_high_probable=is_high,
                full_name=name,
                headline=headline
            )

            # Check if eligible for message (high score and NEVER messaged before)
            if is_high and not db.is_already_messaged(url):
                db.mark_connection_accepted(url)
                qualified_backlog.append({
                    "profile_url": url,
                    "full_name": name,
                    "headline": headline,
                    "score": score,
                    "persona": score_data["persona"]
                })

        return json.dumps({
            "status": "success",
            "total_connections_scanned": len(connections),
            "qualified_count": len(qualified_backlog),
            "leads": qualified_backlog[:limit]
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def sync_google_calendar_bookings() -> str:
    """
    Queries Google Calendar API for booked appointments, matches attendees against leads,
    and updates their status to 'call_booked' in the database and dashboard.
    """
    try:
        res = calendar_sync.sync_google_calendar_events()
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


