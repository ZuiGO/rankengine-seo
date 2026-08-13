import re
from backend.models.schemas import SeoSuggestion
from backend.logging_setup import get_logger

logger = get_logger("suggestion_validator")

def validate_suggestion(suggestion: SeoSuggestion, snapshot: dict) -> bool:
    """
    Validates that a suggestion has a verifiable evidence_source in the baseline snapshot.
    Returns True if valid, False otherwise.
    """
    evidence = suggestion.evidence_source
    if not evidence:
        logger.warning("Suggestion %s rejected: missing evidence_source", suggestion.id)
        return False

    dom = snapshot.get("dom", "")
    meta_tags = snapshot.get("meta_tags", [])
    title = snapshot.get("title", "")
    h1 = snapshot.get("h1", "")

    # For dummy suggestions, they won't have real evidence in the DOM.
    # We do a naive check: is the evidence_source string present in the raw DOM or meta tags?
    
    # We will normalize spaces for comparison
    def normalize(text):
        if not text:
            return ""
        return re.sub(r'\s+', ' ', str(text)).strip()
        
    norm_evidence = normalize(evidence)
    norm_dom = normalize(dom)
    
    if norm_evidence in norm_dom:
        return True
        
    for tag in meta_tags:
        if norm_evidence in normalize(tag.get('name')) or norm_evidence in normalize(tag.get('content')):
            return True
            
    if norm_evidence in normalize(title) or norm_evidence in normalize(h1):
        return True

    # If evidence_source is the exact "current_value", and current_value is found, accept it
    if suggestion.current_value and normalize(suggestion.current_value) in norm_dom:
        return True

    # Check if evidence mentions a specific field and that field is present (e.g. "missing schema.org")
    if "missing schema.org" in evidence.lower() and "application/ld+json" not in norm_dom:
        return True

    logger.warning("Suggestion %s rejected: evidence_source '%s' not verifiable in snapshot", suggestion.id, evidence)
    return False
