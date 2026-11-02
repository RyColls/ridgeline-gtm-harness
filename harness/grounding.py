"""Checks on LLM output. The model writes, plain code decides whether it ships.

Contract for the score note: every sentence cites the record fields it uses in
[brackets]. The check enforces three rules, all deterministic:
  1. every sentence has at least one citation
  2. every cited field exists in the record and is not null
  3. every number in the sentence appears in a cited field (or its sibling,
     e.g. job_posts -> job_post_age_days)
Fail any rule and the note is blocked; the SDR sees the template reasons instead.
"""
from __future__ import annotations

import re

CITE = re.compile(r"\[([a-z_]+\.[a-z0-9_]+)\]")
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")


def _get(record, path):
    node = record
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return ("missing", None)
        node = node[part]
    return ("ok", node)


def _norm(n: str) -> str:
    n = n.replace(",", "")
    return str(int(float(n))) if float(n).is_integer() else n


def _numbers_in(value) -> set[str]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return {str(round(value))}
    return {_norm(m) for m in NUMBER.findall(str(value))}


def _related_numbers(record, path) -> set[str]:
    parent_path, key = path.rsplit(".", 1)
    status, parent = _get(record, parent_path)
    if status != "ok" or not isinstance(parent, dict):
        return set()
    stem = key.split("_")[0].rstrip("s")
    out = set()
    for k, v in parent.items():
        if k == key or k.split("_")[0].rstrip("s") == stem:
            out |= _numbers_in(v)
    return out


def split_sentences(text: str) -> list[str]:
    # A sentence ends at . ! or ? followed by space, or after a closing citation group.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def check_summary(text: str, record: dict) -> dict:
    sentences = []
    for s in split_sentences(text):
        cites = CITE.findall(s)
        body = re.sub(r"\s+([.,!?])", r"\1", CITE.sub("", s))
        problems = []
        if not cites:
            problems.append("No field cited")
        allowed = set()
        for c in cites:
            status, val = _get(record, c)
            if status == "missing":
                problems.append(f"Cites {c}, which is not in the record")
            elif val is None:
                problems.append(f"Cites {c}, but that field is empty (unknown)")
            else:
                allowed |= _related_numbers(record, c)
        for n in NUMBER.findall(body):
            if _norm(n) not in allowed:
                problems.append(f"Number {n} does not appear in any cited field")
        sentences.append({"text": body.strip(), "cites": cites, "ok": not problems, "problems": problems})
    passed = bool(sentences) and all(x["ok"] for x in sentences)
    return {"status": "pass" if passed else "blocked", "sentences": sentences,
            "rule": "Every claim must trace to a non-empty field in the record."}


def template_note(result: dict) -> str:
    """Deterministic fallback when the LLM note is blocked: top reasons, no prose."""
    top = sorted([r for r in result["reasons"] if r["points"] > 0], key=lambda r: -r["points"])[:4]
    return "; ".join(f"{r['signal']}: {r['evidence']} (+{r['points']})" for r in top) + "."
