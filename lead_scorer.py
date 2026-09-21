import os
import re
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv

load_dotenv()

DEFAULT_THRESHOLD = int(os.getenv("LEAD_SCORE_THRESHOLD", "70"))

PROP_FIRM_KEYWORDS: List[Tuple[str, int]] = [
    ("ftmo", 40),
    ("fundednext", 40),
    ("myforexfunds", 40),
    ("topstep", 40),
    ("the5ers", 40),
    ("apex trader", 40),
    ("prop trader", 35),
    ("prop firm", 35),
    ("funded trader", 35),
    ("funded account", 35),
    ("prop trading", 30),
    ("passing prop", 30),
    ("funded challenge", 30)
]

ALGO_MT5_KEYWORDS: List[Tuple[str, int]] = [
    ("mt5", 35),
    ("metatrader 5", 35),
    ("mql5", 35),
    ("mql4", 25),
    ("algorithmic trader", 35),
    ("algo trader", 35),
    ("quant trader", 35),
    ("quantitative trader", 35),
    ("quantitative analyst", 30),
    ("algorithmic trading", 30),
    ("quant researcher", 25),
    ("ea developer", 30),
    ("expert advisor", 30),
    ("pine script", 25),
    ("trading bot", 25),
    ("automated trading", 30)
]

FOREX_ACTIVE_KEYWORDS: List[Tuple[str, int]] = [
    ("forex trader", 30),
    ("fx trader", 30),
    ("currency trader", 25),
    ("day trader", 25),
    ("swing trader", 25),
    ("full-time trader", 25),
    ("independent trader", 20),
    ("forex", 20),
    ("fx", 15),
    ("day trading", 20),
    ("price action", 15),
    ("smc", 20),
    ("ict", 20),
    ("order flow", 15),
    ("trader", 10)
]

METHODOLOGY_KEYWORDS: List[Tuple[str, int]] = [
    ("risk management", 20),
    ("drawdown", 20),
    ("trade journal", 20),
    ("journaling", 15),
    ("trading psychology", 15),
    ("trading edge", 15),
    ("portfolio manager", 15)
]

DISQUALIFIER_KEYWORDS: List[Tuple[str, int]] = [
    ("recruiter", -50),
    ("talent acquisition", -50),
    ("human resources", -50),
    ("hr manager", -50),
    ("technical recruiter", -60),
    ("student", -45),
    ("intern", -35),
    ("broker sales", -45),
    ("signal provider", -45),
    ("signals provider", -45),
    ("affiliate marketer", -40),
    ("account executive", -40),
    ("sales development representative", -40),
    ("sdr", -35),
    ("bdr", -35),
    ("crypto promoter", -50)
]

def calculate_lead_score(
    headline: str = "", 
    about_text: str = "", 
    experience_text: str = "",
    threshold: int = DEFAULT_THRESHOLD
) -> Dict[str, Any]:
    """
    Computes a transparent probability score (0 to 100) determining if a LinkedIn
    candidate is a high-probable lead for Ascentrader.
    """
    combined_text = f" {headline} {about_text} {experience_text} ".lower()
    
    score = 15 # Baseline
    reasons: List[str] = []
    persona = "Trader"
    
    # 1. Prop Firm Category (max 50)
    prop_pts = 0
    for kw, weight in PROP_FIRM_KEYWORDS:
        if re.search(r'(?i)\b' + re.escape(kw) + r'\b', combined_text):
            add = min(weight, 50 - prop_pts)
            if add > 0:
                prop_pts += add
                reasons.append(f"+{add} Prop/Funded ('{kw}')")
                persona = "Prop Firm Trader"
            if prop_pts >= 50:
                break
    score += prop_pts

    # 2. Algo / MT5 Category (max 50)
    algo_pts = 0
    for kw, weight in ALGO_MT5_KEYWORDS:
        if re.search(r'(?i)\b' + re.escape(kw) + r'\b', combined_text):
            add = min(weight, 50 - algo_pts)
            if add > 0:
                algo_pts += add
                reasons.append(f"+{add} Algo/MT5 ('{kw}')")
                if prop_pts == 0:
                    persona = "MT5 & Algo Trader"
            if algo_pts >= 50:
                break
    score += algo_pts

    # 3. Forex / Active Category (max 40)
    fx_pts = 0
    for kw, weight in FOREX_ACTIVE_KEYWORDS:
        if re.search(r'(?i)\b' + re.escape(kw) + r'\b', combined_text):
            add = min(weight, 40 - fx_pts)
            if add > 0:
                fx_pts += add
                reasons.append(f"+{add} FX/Active ('{kw}')")
                if prop_pts == 0 and algo_pts == 0:
                    persona = "Forex Trader"
            if fx_pts >= 40:
                break
    score += fx_pts

    # 4. Methodology / Risk (max 30)
    meth_pts = 0
    for kw, weight in METHODOLOGY_KEYWORDS:
        if re.search(r'(?i)\b' + re.escape(kw) + r'\b', combined_text):
            add = min(weight, 30 - meth_pts)
            if add > 0:
                meth_pts += add
                reasons.append(f"+{add} Risk/Journal ('{kw}')")
            if meth_pts >= 30:
                break
    score += meth_pts

    # 5. Disqualifiers
    disq_pts = 0
    for kw, penalty in DISQUALIFIER_KEYWORDS:
        if re.search(r'(?i)\b' + re.escape(kw) + r'\b', combined_text):
            if any(h in kw for h in ["recruit", "human resources", "talent", "hr"]):
                disq_pts += penalty
                reasons.append(f"{penalty} Disqualifier ('{kw}')")
            elif prop_pts == 0 and algo_pts == 0:
                disq_pts += penalty
                reasons.append(f"{penalty} Negative signal ('{kw}')")
    score += disq_pts

    final_score = max(0, min(100, score))
    is_high_probable = final_score >= threshold

    return {
        "score": final_score,
        "is_high_probable": is_high_probable,
        "reasons": reasons,
        "persona": persona,
        "threshold": threshold
    }

if __name__ == "__main__":
    test_cases = [
        "FTMO Funded Trader | Prop Firm Risk Management | MT5 Algo Dev",
        "Technical Recruiter at Apex Systems | Hiring Talent",
        "Forex & Commodities Trader | Price Action & SMC",
        "Computer Science Student at University",
        "Quantitative Analyst & MQL5 Automated Trading Specialist",
        "Full-time Day Trader | FX & Gold | Disciplined Risk Management"
    ]
    print(f"Testing Lead Scorer (Threshold: {DEFAULT_THRESHOLD})...\n")
    for text in test_cases:
        res = calculate_lead_score(headline=text)
        print(f"Headline: '{text}'")
        print(f" -> Score: {res['score']}% | Qualified: {res['is_high_probable']} | Persona: {res['persona']}")
        print(f" -> Reasons: {', '.join(res['reasons'])}\n")
