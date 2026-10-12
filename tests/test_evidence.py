"""Batch 10 (T-21): evidence pack. check_evidence, generated docs, and the rows /proof renders (SPEC TS-11)."""
import json
import os
import subprocess
import sys

import pytest

from vigil import docsgen
from vigil.web.service import REQUIRED_CLAIMS, VigilService
from vigil.web.settings import DEFAULT_REPO_URL, WebSettings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "check_evidence")


def row(claim, status="pending", url=None):
    return {"claim": claim, "kind": "k", "url": url, "added_at": None, "status": status}


def full(**over):
    items = [row(c) for c in REQUIRED_CLAIMS]
    for i, it in enumerate(items):
        if it["claim"] in over:
            items[i] = over[it["claim"]]
    return items


def run_check(tmp_path, items):
    p = tmp_path / "evidence.json"
    p.write_text(json.dumps(items), encoding="utf-8")
    return subprocess.run([sys.executable, SCRIPT, str(p)], capture_output=True, text=True, cwd=ROOT)


def test_check_evidence_passes_with_pending_rows_and_lists_them(tmp_path):
    r = run_check(tmp_path, full())
    assert r.returncode == 0 and "EVIDENCE OK: 0 ok, 7 pending" in r.stdout and "PENDING: used neatlogs" in r.stdout


def test_check_evidence_fails_on_an_ok_row_without_a_url(tmp_path):
    r = run_check(tmp_path, full(**{"used neatlogs": row("used neatlogs", "ok", None)}))
    assert r.returncode == 1 and "marked ok without an https URL" in r.stdout


@pytest.mark.parametrize("url", ["", "http://example.com/x", "javascript:alert(1)", "https://a b", 5])
def test_check_evidence_rejects_non_https_urls_marked_ok(tmp_path, url):
    r = run_check(tmp_path, full(**{"used Entire": row("used Entire", "ok", url)}))
    assert r.returncode == 1 and "used Entire" in r.stdout


def test_check_evidence_accepts_an_ok_row_with_an_https_url(tmp_path):
    r = run_check(tmp_path, full(**{"used Entire": row("used Entire", "ok", "https://example.com/x")}))
    assert r.returncode == 0 and "1 ok, 6 pending" in r.stdout


def test_check_evidence_fails_on_a_missing_required_claim_bad_status_and_pending_with_url(tmp_path):
    missing = [it for it in full() if it["claim"] != "built in public"]
    r = run_check(tmp_path, missing)
    assert r.returncode == 1 and "required claim missing: built in public" in r.stdout
    r = run_check(tmp_path, full(**{"used neatlogs": row("used neatlogs", "done", None)}))
    assert r.returncode == 1 and "status must be ok or pending" in r.stdout
    r = run_check(tmp_path, full(**{"used neatlogs": row("used neatlogs", "pending", "https://example.com")}))
    assert r.returncode == 1 and "pending rows must have url null" in r.stdout


def test_check_evidence_fails_clearly_on_unreadable_or_non_array_files(tmp_path):
    r = subprocess.run([sys.executable, SCRIPT, str(tmp_path / "nope.json")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 1 and "cannot read" in r.stdout
    assert run_check(tmp_path, {"claim": "x"}).returncode == 1


def test_committed_evidence_file_is_valid_and_every_ok_row_is_https():
    items = docsgen.load_evidence(os.path.join(ROOT, "docs", "evidence.json"))
    assert docsgen.validate_evidence(items) == []
    assert all(i["url"].startswith("https://") for i in items if i["status"] == "ok")


def _without_first_commit_line(text):
    return "\n".join(ln for ln in text.split("\n") if not ln.startswith("- First commit:"))


def test_committed_generated_docs_match_their_sources():
    plan = open(os.path.join(ROOT, "docs", "business-plan-inputs.md"), encoding="utf-8").read()
    assert plan == docsgen.render_plan_inputs(ROOT), "docs/business-plan-inputs.md is stale: run make render"
    sub = open(os.path.join(ROOT, "docs", "submission.md"), encoding="utf-8").read()
    if docsgen._root_commit(ROOT) is not None:
        assert sub == docsgen.render_submission(ROOT, DEFAULT_REPO_URL, include_git=True), "docs/submission.md is stale"
    else:
        # shallow clone (for example a default CI checkout): the git section cannot be regenerated, so compare the rest
        want = docsgen.render_submission(ROOT, DEFAULT_REPO_URL, include_git=False)
        assert _without_first_commit_line(sub) == want, "docs/submission.md is stale: run make render"


def test_root_commit_is_unavailable_in_a_shallow_clone(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": os.environ["PATH"], "HOME": str(tmp_path)}

    def git(cwd, *a):
        subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, env=env)

    git(src, "init", "-q")
    for n in ("a", "b"):
        (src / n).write_text(n)
        git(src, "add", n)
        git(src, "commit", "-q", "-m", n)
    full = docsgen._root_commit(str(src))
    assert full is not None and len(full[0]) == 7
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", "file://" + str(src), str(shallow))
    assert docsgen._root_commit(str(shallow)) is None


def test_submission_renders_pending_and_never_links_a_row_that_is_not_ok(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "eval" / "results").mkdir(parents=True)
    items = full(**{"used neatlogs": row("used neatlogs", "pending", "https://example.com/hidden"),
                    "used Entire": row("used Entire", "ok", "https://example.com/e")})
    (tmp_path / "docs" / "evidence.json").write_text(json.dumps(items), encoding="utf-8")
    text = docsgen.render_submission(str(tmp_path), "https://example.com/r", include_git=False)
    assert "| used neatlogs | k | PENDING |" in text and "hidden" not in text
    assert "[link](https://example.com/e)" in text and "- none" in text


def test_plan_inputs_numbers_come_from_results_and_no_price_is_assumed():
    text = docsgen.render_plan_inputs(ROOT)
    for label in ("v0", "v1", "v1h", "v1h2"):
        d = json.load(open(os.path.join(ROOT, "eval", "results", f"{label}.json"), encoding="utf-8"))
        t_in = sum(s["tokens_in"] for s in d["scenarios"])
        assert f"| {t_in} |" in text
    assert "not set" in text and "NOT computed" in text


def test_proof_evidence_rows_follow_the_committed_file(tmp_path):
    s = WebSettings(db_path=str(tmp_path / "c.db"), receipts_dir=str(tmp_path / "r"))
    rows = VigilService(s).evidence()
    ok = {(r["claim"], r["url"]) for r in rows if r["status"] == "ok"}
    assert ("wrote code during the hackathon", "https://github.com/MusaAis/vigil/commits/main") in ok
    pending = {r["claim"] for r in rows if r["status"] == "pending"}
    assert {"used neatlogs"} <= pending
    assert ("used Entire", "https://github.com/MusaAis/vigil/commit/9db1bb7") in ok
    assert all(r["url"] is None for r in rows if r["status"] == "pending")
