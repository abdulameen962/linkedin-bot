import os
import smtplib
import re
import json
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

def classify_reply_intent(reply_text: str, candidate_name: str = "", use_llm: bool = True) -> Dict[str, Any]:
    """
    Classifies the intent of an inbound LinkedIn message from a candidate.
    Returns: { "intent": str, "requires_alert": bool, "summary": str }
    """
    clean_text = (reply_text or "").strip().lower()
    
    # 1. Check if booked
    booked_keywords = ["booked", "scheduled", "calendar", "picked a time", "accepted the invite", "see you on", "looking forward to our call"]
    if any(kw in clean_text for kw in booked_keywords):
        return {
            "intent": "CALL_BOOKED",
            "requires_alert": False,
            "summary": "Candidate indicated they scheduled/booked a time on Google Calendar."
        }

    # 2. Check if not interested
    negative_keywords = ["not interested", "no thanks", "stop messaging", "unsubscribe", "remove me", "don't message", "not looking"]
    if any(kw in clean_text for kw in negative_keywords):
        return {
            "intent": "NOT_INTERESTED",
            "requires_alert": False,
            "summary": "Candidate declined or indicated no interest."
        }

    # 3. Fast LLM Classification for nuanced replies
    if use_llm:
        try:
            from llms import glm_53
            prompt = f"""
Classify this reply from a trader ({candidate_name}) to our outreach pitch:
Reply: "{reply_text}"

Options:
- CUSTOM_INQUIRY (asking specific questions about features, pricing, tech stack, partnerships, or off-script questions)
- POSITIVE_INTEREST (interested, wants to talk, or asked for details)
- GENERAL_CHATTER (polite acknowledgement, greeting, e.g. "thanks for connecting")
- NOT_INTERESTED (polite or direct rejection)

Respond with ONLY valid JSON:
{{"intent": "CUSTOM_INQUIRY", "requires_founder_intervention": true, "reason": "short explanation"}}
"""
            res = glm_53(messages=[{"role": "user", "content": prompt}])
            text_out = res.content if hasattr(res, "content") else str(res)
            m = re.search(r'\{.*\}', text_out, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                intent = data.get("intent", "CUSTOM_INQUIRY")
                requires_alert = data.get("requires_founder_intervention", True)
                return {
                    "intent": intent,
                    "requires_alert": requires_alert,
                    "summary": data.get("reason", "Inbound reply requiring attention")
                }
        except Exception as e:
            print(f"[WARN] [classify_reply_intent] LLM notice: {e}")

    # Heuristic fallback
    if "?" in reply_text or len(clean_text) > 15:
        return {
            "intent": "CUSTOM_INQUIRY",
            "requires_alert": True,
            "summary": "Candidate asked an off-script question or provided custom feedback."
        }

    return {
        "intent": "GENERAL_CHATTER",
        "requires_alert": False,
        "summary": "Short polite greeting or acknowledgement."
    }

def send_founder_email_alert(
    candidate_name: str,
    headline: str,
    profile_url: str,
    reply_text: str,
    intent: str,
    summary: str = ""
) -> bool:
    """
    Sends an immediate HTML email notification to the founder.
    Tries SSL (port 465) first, then falls back to STARTTLS (port 587).
    """
    if not (SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO):
        print("[WARN] [send_founder_email_alert] SMTP credentials not fully configured in .env. Skipping email.")
        return False

    now_str = datetime.now(timezone.utc).strftime("%b %d, %Y - %H:%M UTC")
    subject = f"[Ascentrader Alert] {candidate_name} replied to outreach!"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0f19; color: #f1f5f9; margin: 0; padding: 24px; }}
        .card {{ background-color: #131b2e; border: 1px solid #23314d; border-radius: 12px; max-width: 600px; margin: 0 auto; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); padding: 24px; border-bottom: 1px solid #23314d; }}
        .badge {{ background: #6366f1; color: white; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; text-transform: uppercase; }}
        .title {{ margin: 12px 0 4px 0; font-size: 20px; font-weight: 700; color: #ffffff; }}
        .headline {{ color: #94a3b8; font-size: 14px; margin: 0; }}
        .content {{ padding: 24px; }}
        .reply-box {{ background-color: #080c14; border-left: 4px solid #10b981; padding: 16px; border-radius: 6px; margin: 16px 0; font-size: 15px; color: #e2e8f0; line-height: 1.5; }}
        .intent-badge {{ display: inline-block; background-color: #064e3b; color: #34d399; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-bottom: 8px; }}
        .btn {{ display: inline-block; background: #10b981; color: #000000 !important; font-weight: 700; text-decoration: none; padding: 12px 24px; border-radius: 8px; margin-top: 16px; text-align: center; }}
        .footer {{ padding: 16px 24px; background-color: #0c1220; border-top: 1px solid #1e293b; color: #64748b; font-size: 12px; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <span class="badge">Ascentrader AI Bot</span>
          <h2 class="title">{candidate_name}</h2>
          <p class="headline">{headline}</p>
        </div>
        <div class="content">
          <span class="intent-badge">Classification: {intent}</span>
          <p style="color: #cbd5e1; font-size: 14px; margin-top: 4px;"><strong>AI Summary:</strong> {summary}</p>
          
          <p style="color: #94a3b8; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Their Message:</p>
          <div class="reply-box">
            "{reply_text}"
          </div>

          <a href="{profile_url}" class="btn" target="_blank">Open Candidate LinkedIn Profile</a>
        </div>
        <div class="footer">
          Received at {now_str} - Ascentrader Automated Outreach System
        </div>
      </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Ascentrader Bot <{ALERT_EMAIL_FROM}>"
    msg["To"] = ALERT_EMAIL_TO

    plain_text = f"Ascentrader Lead Alert!\n\nCandidate: {candidate_name}\nHeadline: {headline}\nIntent: {intent}\n\nTheir Message:\n{reply_text}\n\nProfile Link: {profile_url}"
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html, "html"))

    clean_pass = SMTP_PASS.replace(" ", "")

    # Attempt 1: Port 465 SSL (standard for Gmail app passwords)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=12) as server:
            server.login(SMTP_USER, clean_pass)
            server.sendmail(ALERT_EMAIL_FROM, [ALERT_EMAIL_TO], msg.as_string())
            print(f"[OK] [send_founder_email_alert] Alert dispatched via SSL (465) to {ALERT_EMAIL_TO}")
            return True
    except Exception as e_ssl:
        print(f"[WARN] SSL 465 attempt failed ({e_ssl}). Trying TLS 587...")

    # Attempt 2: Port 587 STARTTLS fallback
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=12) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, clean_pass)
            server.sendmail(ALERT_EMAIL_FROM, [ALERT_EMAIL_TO], msg.as_string())
            print(f"[OK] [send_founder_email_alert] Alert dispatched via TLS (587) to {ALERT_EMAIL_TO}")
            return True
    except Exception as e_tls:
        print(f"[ERROR] [send_founder_email_alert] Failed to send email alert: {e_tls}")
        return False

if __name__ == "__main__":
    print("Testing reply intent classification and email alerting...")
    test_reply = "Hey! This sounds interesting, but does Ascentrader support MT5 broker bridge directly or do I have to export CSV logs manually?"
    classification = classify_reply_intent(test_reply, "David Miller")
    print("Classification:", classification)
    
    if classification["requires_alert"]:
        print(f"\nSending test alert to {ALERT_EMAIL_TO}...")
        sent = send_founder_email_alert(
            candidate_name="David Miller",
            headline="MT5 Algo Developer | Quantitative Trading Systems",
            profile_url="https://www.linkedin.com/in/sample-trader",
            reply_text=test_reply,
            intent=classification["intent"],
            summary=classification["summary"]
        )
        print(f"Email sent: {sent}")
