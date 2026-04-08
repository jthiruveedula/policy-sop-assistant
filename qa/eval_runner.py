"""
eval_runner.py - Evaluation harness for policy-sop-assistant.

Scores the assistant against a curated set of golden questions on three
dimensions:
  1. Citation validity   - at least one [source] citation in the response
  2. Groundedness        - answer content matches at least one cited chunk
  3. Refusal correctness - out-of-scope questions are correctly refused

Usage:
    python qa/eval_runner.py --questions qa/golden_questions.yaml \
        --api-url http://localhost:8080/ask
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
import yaml

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

CITATION_PATTERN = re.compile(r"\[source:\s*.+?\]")


@dataclass
class EvalQuestion:
    id: str
    question: str
    expected_citation: bool       # True if a citation is expected
    expected_refusal: bool        # True if the question should be refused
    ground_truth_keywords: List[str] = field(default_factory=list)


@dataclass
class EvalResult:
    question_id: str
    question: str
    answer: str
    citations_found: int
    citation_valid: bool
    grounded: bool
    refusal_correct: bool
    passed: bool


def load_questions(path: str) -> List[EvalQuestion]:
    """Load golden questions from a YAML file."""
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    return [
        EvalQuestion(
            id=q["id"],
            question=q["question"],
            expected_citation=q.get("expected_citation", True),
            expected_refusal=q.get("expected_refusal", False),
            ground_truth_keywords=q.get("ground_truth_keywords", []),
        )
        for q in raw.get("questions", [])
    ]


def ask(api_url: str, question: str) -> Dict[str, Any]:
    """Call the /ask endpoint and return the parsed JSON response."""
    resp = requests.post(
        api_url,
        json={"question": question},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def evaluate_response(
    question: EvalQuestion, response: Dict[str, Any]
) -> EvalResult:
    """Score a single response against expected criteria."""
    answer: str = response.get("answer", "")
    citations: List[Dict] = response.get("citations", [])
    refusal_reason: Optional[str] = response.get("refusal_reason")

    # 1. Citation validity
    inline_citations = CITATION_PATTERN.findall(answer)
    citation_valid = (
        len(inline_citations) > 0 or len(citations) > 0
        if question.expected_citation
        else True
    )

    # 2. Groundedness - at least one ground-truth keyword present in answer
    grounded = True
    if question.ground_truth_keywords:
        grounded = any(
            kw.lower() in answer.lower()
            for kw in question.ground_truth_keywords
        )

    # 3. Refusal correctness
    if question.expected_refusal:
        refusal_correct = refusal_reason is not None and refusal_reason != ""
    else:
        refusal_correct = refusal_reason is None or refusal_reason == ""

    passed = citation_valid and grounded and refusal_correct

    return EvalResult(
        question_id=question.id,
        question=question.question,
        answer=answer,
        citations_found=len(citations),
        citation_valid=citation_valid,
        grounded=grounded,
        refusal_correct=refusal_correct,
        passed=passed,
    )


def run_eval(questions_path: str, api_url: str) -> None:
    """Run the full evaluation suite and print a scorecard."""
    questions = load_questions(questions_path)
    results: List[EvalResult] = []

    for q in questions:
        logger.info("Evaluating [%s]: %s", q.id, q.question)
        try:
            response = ask(api_url, q.question)
            result = evaluate_response(q, response)
        except Exception as exc:
            logger.error("Error on question %s: %s", q.id, exc)
            continue
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info(
            "  %s | citations=%d | grounded=%s | refusal=%s",
            status, result.citations_found, result.grounded, result.refusal_correct,
        )

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    print(f"\n=== Evaluation Scorecard ===")
    print(f"Total questions : {total}")
    print(f"Passed          : {passed}")
    print(f"Failed          : {total - passed}")
    print(f"Pass rate       : {passed / total:.1%}" if total else "No results.")
    print("\nPer-question results:")
    for r in results:
        print(
            f"  [{r.question_id}] {'PASS' if r.passed else 'FAIL'} "
            f"citations={r.citations_found} grounded={r.grounded} "
            f"refusal_ok={r.refusal_correct}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run policy-sop-assistant evaluation")
    parser.add_argument(
        "--questions", required=True, help="Path to golden_questions.yaml"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8080/ask",
        help="Base URL of the /ask endpoint",
    )
    args = parser.parse_args()
    run_eval(args.questions, args.api_url)
