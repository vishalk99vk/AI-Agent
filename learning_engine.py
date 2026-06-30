"""
============================================================
  learning_engine.py — the Automation Agent's memory
============================================================
This file is intentionally kept SEPARATE from app.py.

Why: if you ever replace the entire contents of app.py with a
new version (paste over it, regenerate it, etc.), this file —
and everything the agent has learned — is left untouched.

DO NOT paste new app.py code into this file. Keep them apart.
============================================================
"""

import os
import re
import json
import shutil

# ------------------------------------------------------------------
# Storage location — its own folder, separate from app code.
# ------------------------------------------------------------------
LEARNING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learning_data")
os.makedirs(LEARNING_DIR, exist_ok=True)
LEARNED_KEYWORDS_FILE = os.path.join(LEARNING_DIR, "learned_keywords.json")

# Legacy locations this engine knows how to migrate from automatically.
_LEGACY_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "learned_keywords.json"),
]


def _migrate_legacy_files():
    if os.path.exists(LEARNED_KEYWORDS_FILE):
        return
    for old_path in _LEGACY_PATHS:
        if os.path.exists(old_path):
            try:
                shutil.move(old_path, LEARNED_KEYWORDS_FILE)
                return
            except Exception:
                pass


_migrate_legacy_files()


STOPWORDS = {
    "the", "a", "an", "this", "that", "these", "those", "and", "or", "to", "of", "in",
    "on", "for", "with", "from", "my", "me", "i", "want", "please", "file", "files",
    "is", "are", "it", "its", "do", "can", "you", "your", "use", "using", "need",
}


def load_learned_keywords():
    """Read all learned task->phrase mappings from disk."""
    if os.path.exists(LEARNED_KEYWORDS_FILE):
        try:
            with open(LEARNED_KEYWORDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_learned_keyword(task_id, phrase):
    """Append a new phrase to a task's learned list and persist to disk."""
    learned = load_learned_keywords()
    learned.setdefault(task_id, [])
    phrase = (phrase or "").strip().lower()
    if phrase and phrase not in learned[task_id]:
        learned[task_id].append(phrase)
        with open(LEARNED_KEYWORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(learned, f, indent=2)
    return learned


def extract_candidate_phrase(prompt):
    """Pull a short, meaningful phrase out of a prompt to use as a future keyword."""
    words = [w for w in re.findall(r"[a-zA-Z]+", prompt.lower()) if w not in STOPWORDS and len(w) > 2]
    return " ".join(words[:4])


def detect_intent(prompt, tasks):
    """
    Decide which task a prompt refers to.
    `tasks` is the TASKS dict defined in app.py (task_id -> {label, keywords, hint}).
    Returns (task_id, confidence) where confidence is 'high' or 'low', or (None, None).
    """
    learned = load_learned_keywords()
    prompt_l = prompt.lower()
    scores = {}
    for task_id, meta in tasks.items():
        all_kw = meta["keywords"] + learned.get(task_id, [])
        score = sum(1 for kw in all_kw if kw in prompt_l)
        if score > 0:
            scores[task_id] = score
    if not scores:
        return None, None
    best = max(scores, key=scores.get)
    top_score = scores[best]
    tied = [t for t, s in scores.items() if s == top_score]
    confidence = "high" if len(tied) == 1 else "low"
    return best, confidence


def reset_learning():
    """Wipe everything the agent has learned (use with care)."""
    if os.path.exists(LEARNED_KEYWORDS_FILE):
        os.remove(LEARNED_KEYWORDS_FILE)
