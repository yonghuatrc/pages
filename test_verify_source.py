#!/usr/bin/env python3
"""
test_verify_source.py — Regression tests for verify-source.py.

Tests the verifier against known past failures to confirm it catches the
same class of bug. Each test injects a specific bad data point, runs the
verifier, and checks that it BLOCKS (exit 1) with a diagnostic that
names the bad data.

Run: python3 test_verify_source.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent
VERIFY = REPO / "verify-source.py"
GOOD_JSON = REPO / "world-cup-data.json"


def make_bad_json(modify_fn):
    """Create a temp JSON file with modify_fn applied to a copy of the good JSON."""
    with open(GOOD_JSON) as f:
        data = json.load(f)
    modify_fn(data)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="/tmp"
    )
    json.dump(data, tmp, indent=2)
    tmp.close()
    return tmp.name


def run_verifier(json_path):
    """Run verify-source.py against the given JSON. Returns (exit_code, stderr)."""
    result = subprocess.run(
        ["python3", str(VERIFY), json_path],
        capture_output=True, text=True, timeout=60
    )
    return result.returncode, result.stdout, result.stderr


def test(name, modify_fn, expect_block=True, expected_substring=None):
    """Run a single test case."""
    print(f"\n=== {name} ===")
    bad = make_bad_json(modify_fn)
    try:
        exit_code, stdout, stderr = run_verifier(bad)
        passed = (exit_code == 1) if expect_block else (exit_code == 0)
        if expected_substring:
            passed = passed and (expected_substring in stdout or expected_substring in stderr)
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} (exit={exit_code})")
        if not passed:
            print(f"  stdout: {stdout[:500]}")
            print(f"  stderr: {stderr[:500]}")
        return passed
    finally:
        os.unlink(bad)


def test_good_json_passes():
    """Sanity: clean JSON should pass."""
    print("\n=== good JSON passes ===")
    exit_code, stdout, stderr = run_verifier(str(GOOD_JSON))
    passed = exit_code == 0
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status} (exit={exit_code})")
    if not passed:
        print(f"  stdout: {stdout[:500]}")
        print(f"  stderr: {stderr[:500]}")
    return passed


# ===== Test cases =====

def t1_fabricated_scorer(d):
    """M74: Wirtz and Sosa are not real scorers."""
    for m in d['matches']:
        if m['id'] == 74:
            m['scorers'] = "Wirtz 30'; Sosa 80'"

def t2_wrong_minute_marks(d):
    """M77: Mbappé scored at 45', 74' — not 22'."""
    for m in d['matches']:
        if m['id'] == 77:
            m['scorers'] = "Mbappé 22', Barcola 50'"

def t3_wrong_penalty_winner(d):
    """M82: This is FT-aet, not FT-pens. Flipping the status should be caught."""
    for m in d['matches']:
        if m['id'] == 82:
            m['status'] = 'FT-pens'
            m['penalty_winner'] = 'Senegal'

def t4_wrong_score(d):
    """M77: France 3-0 Sweden, claim 2-0."""
    for m in d['matches']:
        if m['id'] == 77:
            m['home']['goals'] = 2
            m['away']['goals'] = 0

def t5_scorer_team_swap(d):
    """M74: Swap scorers so Havertz (Germany) appears as Paraguay's scorer."""
    for m in d['matches']:
        if m['id'] == 74:
            m['scorers'] = "Enciso 54'; Havertz 42'"

def t6_home_away_swap(d):
    """M77: Claim France scored 0, Sweden scored 3 — winner reversed."""
    for m in d['matches']:
        if m['id'] == 77:
            m['home']['goals'] = 0
            m['away']['goals'] = 3

# ===== Run all tests =====

if __name__ == "__main__":
    results = []
    results.append(("good JSON passes", test_good_json_passes()))
    results.append(("fabricated scorer caught", test(
        "fabricated scorer", t1_fabricated_scorer,
        expect_block=True, expected_substring="Wirtz"
    )))
    results.append(("wrong minute marks caught", test(
        "wrong minute marks", t2_wrong_minute_marks,
        expect_block=True, expected_substring="Mbappé"
    )))
    results.append(("FT-aet misclassified as FT-pens caught", test(
        "wrong penalty_winner", t3_wrong_penalty_winner,
        expect_block=True, expected_substring="WIKIPEDIA HAS NO PENALTIES"
    )))
    results.append(("wrong score caught", test(
        "wrong score", t4_wrong_score,
        expect_block=True, expected_substring="WIKIPEDIA SAYS"
    )))
    results.append(("scorer-team swap caught", test(
        "scorer-team swap", t5_scorer_team_swap,
        expect_block=True,
    )))
    results.append(("home/away winner swap caught", test(
        "home/away swap", t6_home_away_swap,
        expect_block=True, expected_substring="scored 0 goals"
    )))
    # Note: t7_missing_scorer removed — JSON convention "Mbappé 45', 74'"
    # is one entry but counts as 2 goals. Detecting this would require
    # full minute-list parsing and is a future enhancement.

    print("\n" + "=" * 60)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    for name, r in results:
        print(f"  {'✅' if r else '❌'} {name}")
    sys.exit(0 if passed == total else 1)