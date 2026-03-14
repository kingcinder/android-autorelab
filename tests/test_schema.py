from arelab.schemas import SwapCandidate


def test_swap_schema_validation() -> None:
    candidate = SwapCandidate.model_validate(
        {
            "title": "Auth logic issue",
            "class": "CWE-287-like improper authentication / fail-open decision",
            "confidence": 0.8,
            "impact": "high",
            "reachability": "caller controlled auth inputs",
            "evidence": {
                "binary": "/tmp/demo",
                "function": "check_admin_token",
                "address": "0x401111",
                "decompile_excerpt": "return is_admin || pin_ok;",
                "cfg_summary": "nodes=4 edges=4",
            },
            "remediation_intent": "deny by default",
            "verification_tests": "invalid pin fails",
        }
    )
    assert candidate.class_name.startswith("CWE-287")
