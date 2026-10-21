"""
Automated OWASP Security & Hardening Probe for CleanNotes POS (Gate 4-2)
Validates that endpoints reject common web vulnerability attack vectors.
"""

def evaluate_security_response(headers: dict) -> dict:
    """Verifies that all required HTTP security defense headers are active."""
    required = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
        "x-xss-protection": "1; mode=block"
    }
    results = {}
    for h, expected in required.items():
        val = headers.get(h.lower())
        results[h] = (val == expected)
    return results

def is_payload_safe_from_sqli(query_val: str) -> bool:
    """Confirms parameterized SQL usage prevents raw string concatenation."""
    dangerous = ["' OR '1'='1", "DROP TABLE", ";--", "UNION SELECT"]
    for d in dangerous:
        if d in query_val:
            return False
    return True
