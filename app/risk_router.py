import re

HIGH_RISK_KEYWORDS = [
    r"penalty",
    r"indemnif",
    r"liabilit",
    r"insurance",
    r"uncapped",
    r"exclusiv",
    r"minimum",
    r"commitment",
    r"most[-_\s]+favored[-_\s]+nation",
    r"terminat",
    r"on-time",
    r"rate"
]

def is_high_risk(question: str) -> tuple[bool, str]:
    q_lower = question.lower()
    
    # Check for termination for convenience override
    if "convenience" in q_lower and "terminat" in q_lower:
        return False, "Termination for Convenience (low risk)"
        
    for pattern in HIGH_RISK_KEYWORDS:
        if re.search(pattern, q_lower):
            return True, f"Matched high-risk keyword pattern: {pattern}"
            
    return False, ""

def assess_confidence_and_risk(question: str, top_score: float) -> tuple[str, str]:
    """
    Returns (decision, reason)
    decision is either 'auto_answer' or 'queue_for_review'
    """
    if top_score < 0.45:
        return "queue_for_review", f"Low confidence: top similarity score ({top_score:.4f}) is below 0.45"
        
    high_risk, reason = is_high_risk(question)
    if high_risk:
        return "queue_for_review", f"High risk category: {reason}"
        
    return "auto_answer", "Low risk and high confidence"
