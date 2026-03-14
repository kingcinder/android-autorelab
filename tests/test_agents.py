from arelab.agents import merge_candidates
from arelab.schemas import SwapCandidate


def test_swap_merge_consensus_logic() -> None:
    base = {
        "title": "Potential unsafe buffer handling in vulnerable_copy",
        "class": "CWE-120-like stack/heap buffer misuse",
        "confidence": 0.6,
        "impact": "high",
        "reachability": "controlled input",
        "evidence": {
            "binary": "/tmp/demo",
            "function": "vulnerable_copy",
            "address": "0x401000",
            "decompile_excerpt": "strcpy(buffer, input);",
            "cfg_summary": "nodes=3 edges=2",
        },
        "remediation_intent": "use bounded copy",
        "verification_tests": "oversized input rejected",
        "sources": ["heuristic"],
    }
    merged = merge_candidates(
        [
            SwapCandidate.model_validate(base),
            SwapCandidate.model_validate({**base, "confidence": 0.7, "sources": ["deep"]}),
        ]
    )
    assert len(merged) == 1
    assert merged[0].confidence > 0.7
    assert merged[0].id == "SWAP-001"
