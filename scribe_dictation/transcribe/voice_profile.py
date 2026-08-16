"""
Voice profile — a Pro/Lifetime feature that learns the vocabulary of the
person dictating, so future transcriptions are biased toward the names,
jargon, and phrases they actually use.

Privacy model: 100% local. No audio, and no profile data, ever leaves the
machine — the "learning" is a word-frequency count over the user's own
past transcripts, stored in a local JSON file, used only to build a
short `initial_prompt` string that faster-whisper / the Whisper API
already support as a native decoding hint. There is no model fine-tuning
and no telemetry.

Tier gating: PRO gets a capped vocabulary (good enough for a working
vocabulary of names/jargon); LIFETIME removes the cap.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from scribe_dictation.licensing import LicenseTier

VOCAB_CAP_BY_TIER = {
    LicenseTier.FREE: 0,
    LicenseTier.PRO: 300,
    LicenseTier.LIFETIME: 3000,
}

# Minimum occurrences before a word is considered "learned" rather than noise.
MIN_OBSERVATIONS = 2

# How many top terms actually get sent to the model as a decoding hint.
# Whisper's initial_prompt is only used as short context, not a full grammar.
PROMPT_TERM_LIMIT = 40

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{1,}")

# Common English words are excluded so the profile captures what's
# *distinctive* about this speaker's vocabulary, not the whole language.
_STOPWORDS = frozenset(
    """
    the a an and or but if then so to of in on at for with as by from is
    are was were be been being have has had do does did will would can
    could should may might must shall this that these those it its it's
    he she they we you your his her their our i me my mine him them us
    not no yes just very really about into over under again more most
    some any all no nor own same than too also here there when where why
    how what which who whom
    """.split()
)


class VoiceProfile:
    """Per-user, local vocabulary profile.

    Not thread-safe; used from the single transcription worker.
    """

    def __init__(self, path: Path, tier: LicenseTier = LicenseTier.FREE):
        self.path = path
        self.tier = tier
        self.word_counts: dict[str, int] = {}
        self.transcript_count: int = 0
        self._load()

    @property
    def enabled(self) -> bool:
        return VOCAB_CAP_BY_TIER.get(self.tier, 0) > 0

    @property
    def cap(self) -> int:
        return VOCAB_CAP_BY_TIER.get(self.tier, 0)

    # ── learning ─────────────────────────────────────────────────────

    def observe(self, text: str) -> None:
        """Feed a finished transcript into the profile.

        Case-preserving: capitalized mid-sentence words (likely proper
        nouns) are tracked separately from their lowercase form so names
        don't get diluted by "the same word, different sentence position".
        """
        if not self.enabled or not text:
            return

        self.transcript_count += 1
        words = _WORD_RE.findall(text)
        for idx, word in enumerate(words):
            bare = word.strip("'-")
            if len(bare) < 3 or bare.lower() in _STOPWORDS:
                continue
            # Keep capitalization only when it's not just "start of sentence".
            key = bare if (bare[0].isupper() and idx != 0) else bare.lower()
            self.word_counts[key] = self.word_counts.get(key, 0) + 1

        self._enforce_cap()
        self._save()

    def add_terms(self, terms: list[str]) -> None:
        """Explicitly seed vocabulary (e.g. user pastes a list of names/jargon)."""
        if not self.enabled:
            return
        for term in terms:
            term = term.strip()
            if term:
                self.word_counts[term] = max(
                    self.word_counts.get(term, 0), MIN_OBSERVATIONS
                )
        self._enforce_cap()
        self._save()

    def reset(self) -> None:
        self.word_counts = {}
        self.transcript_count = 0
        self._save()

    # ── use ──────────────────────────────────────────────────────────

    def top_terms(self, limit: int = PROMPT_TERM_LIMIT) -> list[str]:
        learned = [w for w, c in self.word_counts.items() if c >= MIN_OBSERVATIONS]
        learned.sort(key=lambda w: self.word_counts[w], reverse=True)
        return learned[:limit]

    def bias_prompt(self) -> Optional[str]:
        """Build the `initial_prompt` decoding hint, or None if nothing learned yet."""
        if not self.enabled:
            return None
        terms = self.top_terms()
        if not terms:
            return None
        return ", ".join(terms)

    # ── persistence ──────────────────────────────────────────────────

    def _enforce_cap(self) -> None:
        cap = self.cap
        if cap <= 0 or len(self.word_counts) <= cap:
            return
        keep = sorted(self.word_counts.items(), key=lambda kv: kv[1], reverse=True)[
            :cap
        ]
        self.word_counts = dict(keep)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.word_counts = dict(data.get("word_counts", {}))
        self.transcript_count = int(data.get("transcript_count", 0))

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {
                        "word_counts": self.word_counts,
                        "transcript_count": self.transcript_count,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass


def default_profile_path() -> Path:
    """Local per-user storage location, alongside the app's other local data."""
    from PySide6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(base) / "voice_profile.json"
