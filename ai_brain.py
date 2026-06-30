"""
============================================================
  ai_brain.py — the Automation Agent's reasoning layer
============================================================
This is kept as its own file, same as learning_engine.py, so
replacing app.py never touches this either.

What it does:
  The keyword/learned matcher in learning_engine.py is fast and
  free, but it can only recognize phrasing it has already seen.
  This module is the fallback "own mind" — when that matcher is
  unsure, it asks the real Claude API to read the prompt and the
  list of available tasks, and reason about which one fits best.

Requires an Anthropic API key, read from the ANTHROPIC_API_KEY
environment variable. If no key is set, this module quietly
reports itself as unavailable and the app keeps working with
keyword matching only — nothing breaks.
============================================================
"""

import os
import json
import urllib.request
import urllib.error

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


def is_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def ask_ai_for_task(prompt, tasks):
    """
    Ask the real Claude API to pick the best matching task_id for a prompt.

    `tasks` is the TASKS dict from app.py: task_id -> {label, keywords, hint}

    Returns a dict:
        {"task_id": <str or None>, "reasoning": <str>, "confidence": <str>}
    or None if the AI brain isn't available / the call failed (caller should
    fall back to keyword matching in that case).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    task_list_text = "\n".join(
        f"- {tid}: {meta['label']} ({meta['hint']})" for tid, meta in tasks.items()
    )

    system_prompt = (
        "You are the routing brain for a file-automation agent. "
        "Given a user's request in plain English and a list of available tasks, "
        "decide which single task_id best matches what the user wants. "
        "If nothing matches reasonably well, return null for task_id. "
        "Respond with ONLY a JSON object, no other text, in this exact shape:\n"
        '{"task_id": "<id or null>", "reasoning": "<one short sentence>", '
        '"confidence": "high|medium|low"}'
    )

    user_message = f"Available tasks:\n{task_list_text}\n\nUser request:\n\"{prompt}\""

    body = json.dumps({
        "model": MODEL,
        "max_tokens": 300,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception):
        return None

    try:
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        raw_text = "".join(text_blocks).strip()
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw_text)
    except Exception:
        return None

    task_id = parsed.get("task_id")
    if task_id not in tasks:
        task_id = None

    return {
        "task_id": task_id,
        "reasoning": parsed.get("reasoning", ""),
        "confidence": parsed.get("confidence", "low"),
    }
