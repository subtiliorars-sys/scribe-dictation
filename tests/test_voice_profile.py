from pathlib import Path

from scribe_dictation.licensing import LicenseTier
from scribe_dictation.transcribe.voice_profile import VoiceProfile


def test_free_tier_profile_is_disabled(tmp_path: Path):
    profile = VoiceProfile(tmp_path / "profile.json", tier=LicenseTier.FREE)
    assert not profile.enabled
    profile.observe("Kubernetes Kubernetes Kubernetes is great")
    assert profile.word_counts == {}
    assert profile.bias_prompt() is None


def test_pro_tier_learns_repeated_distinctive_words(tmp_path: Path):
    profile = VoiceProfile(tmp_path / "profile.json", tier=LicenseTier.PRO)
    assert profile.enabled
    profile.observe("Please email Anaximander about the Kubernetes rollout.")
    profile.observe("I told Anaximander the Kubernetes rollout is done.")
    terms = profile.top_terms()
    assert "Anaximander" in terms
    assert "Kubernetes" in terms
    # Common stopwords never make it in.
    assert "the" not in terms and "about" not in terms


def test_bias_prompt_none_until_min_observations(tmp_path: Path):
    profile = VoiceProfile(tmp_path / "profile.json", tier=LicenseTier.PRO)
    profile.observe("Zylofenix appears exactly once here.")
    # Single occurrence shouldn't count as "learned" yet.
    assert profile.bias_prompt() is None


def test_lifetime_cap_larger_than_pro_cap(tmp_path: Path):
    pro = VoiceProfile(tmp_path / "pro.json", tier=LicenseTier.PRO)
    lifetime = VoiceProfile(tmp_path / "lifetime.json", tier=LicenseTier.LIFETIME)
    assert lifetime.cap > pro.cap


def test_profile_persists_across_instances(tmp_path: Path):
    path = tmp_path / "profile.json"
    profile = VoiceProfile(path, tier=LicenseTier.PRO)
    profile.observe("I saw Anaximander and then Anaximander again.")
    assert path.exists()

    reloaded = VoiceProfile(path, tier=LicenseTier.PRO)
    assert reloaded.word_counts.get("Anaximander", 0) >= 2


def test_add_terms_seeds_vocabulary(tmp_path: Path):
    profile = VoiceProfile(tmp_path / "profile.json", tier=LicenseTier.PRO)
    profile.add_terms(["Xanthopoulos", "SharePoint"])
    prompt = profile.bias_prompt()
    assert prompt is not None
    assert "Xanthopoulos" in prompt and "SharePoint" in prompt


def test_cap_enforced_keeps_highest_counts(tmp_path: Path):
    profile = VoiceProfile(tmp_path / "profile.json", tier=LicenseTier.PRO)
    profile.cap  # sanity access
    for i in range(profile.cap + 50):
        profile.word_counts[f"word{i}"] = i
    profile._enforce_cap()
    assert len(profile.word_counts) == profile.cap
    # Highest-count words survive.
    assert f"word{profile.cap + 49}" in profile.word_counts
