"""Prompt screening for image generation.

SCOPE, which is deliberately narrow and is not a taste filter. Exactly two things are
refused:

  1. Sexual material involving minors.
  2. Sexual content depicting a real, named person (NCII).

Everything else passes, **including adult content between adults**. That is a product
decision, and this module's job is to enforce those two lines rather than to have opinions
about anything else. Adding "while I'm here" rules would make the filter unpredictable and
would quietly turn a safety control into a content policy nobody agreed to.

WHAT THIS IS, HONESTLY. It screens PROMPTS — the text a caller supplies — with normalised
pattern matching. It is not an image classifier and does not inspect output; there is no
``check_image`` here, because writing one that returned "fine" without looking would be
worse than not having it. Prompt screening has real limits: paraphrase exists, and a
determined caller will get things past a matcher. It is one layer, and the others are what
make it defensible — image generation now requires a **wallet session**, so requests are
attributable to an identity rather than anonymous, and it is rate-limited per wallet.

FAIL-CLOSED. Any error inside the filter refuses the prompt. A screening component that
passes traffic when it breaks is not a screening component: the failure would be invisible
in exactly the case it exists for.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from loguru import logger


@dataclass(frozen=True)
class Verdict:
    """A moderation decision. ``allowed`` is the only field a caller may act on."""

    allowed: bool
    #: Machine-readable reason, for logs and metrics. Never returned to the caller verbatim.
    category: str | None = None

    @staticmethod
    def refuse(category: str) -> "Verdict":
        return Verdict(allowed=False, category=category)

    @staticmethod
    def allow() -> "Verdict":
        return Verdict(allowed=True)


class Moderator(Protocol):
    """What image generation requires before it will serve anything."""

    def is_configured(self) -> bool:
        """Whether this moderator can actually make decisions."""
        ...

    async def check_prompt(self, prompt: str) -> Verdict:
        """Screen a generation request before any GPU time is spent on it."""
        ...


# ── normalisation ──────────────────────────────────────────────────────────────────────
# Matching raw text is defeated by punctuation and homoglyphs, so the prompt is flattened
# first. This is not "defeating evasion" — a determined caller still wins — it is refusing
# to be beaten by `c.h.i.l.d` and `сhild` (Cyrillic с), which cost an attacker nothing.

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a"})


def _fold(text: str) -> str:
    """Lowercase, strip accents and homoglyph decoration, separators to spaces."""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"[^a-z0-9]+", " ", folded.lower())
    return re.sub(r"\s+", " ", folded).strip()


def _rejoin_single_letters(text: str) -> str:
    """`c h i l d` -> `child`, leaving real words alone."""
    return re.sub(r"\b(?:[a-z0-9] ){2,}[a-z0-9]\b", lambda m: m.group(0).replace(" ", ""), text)


def normalise(text: str) -> str:
    """The word-matching form: folded, de-leeted, single letters rejoined.

    ⚠️ Leetspeak substitution DESTROYS DIGITS — `1` becomes `i`, so "12 year old" reads as
    "i2 year old" and no age is found. That is fine here and fatal for age matching, which is
    why ``numeric_form`` exists separately rather than this being the one normalisation. The
    first version of this module had only this form, and age detection silently never fired.
    """
    return _rejoin_single_letters(_fold(text).translate(_LEET))


def numeric_form(text: str) -> str:
    """The age-matching form: folded, digits INTACT (no leet substitution)."""
    return _rejoin_single_letters(_fold(text))


_SPACED_OUT = re.compile(r"\b(?:[a-z0-9] ){3,}[a-z0-9]\b")


def looks_spaced_out(text: str) -> bool:
    """Whether the text contains a run of single letters, i.e. `n u d e c h i l d`.

    This gates the compact pass, and the gate is not optional. Substring matching on
    despaced text is wildly false-positive: `documentary` contains `cum`, `cucumber`
    contains `cum`, `circumference` contains `cum`. Applying it to every prompt refused
    "documentary photo of children in a classroom" as CSAM — an ordinary, obviously fine
    request, refused by a filter that is supposed to touch two narrow categories.

    Ordinary prose never contains a four-letter run of single characters. Deliberate
    spacing evasion always does. So the expensive, blunt pass runs only when the input
    already shows the pattern it exists to defeat.
    """
    return bool(_SPACED_OUT.search(_fold(text)))


def compact_form(text: str) -> str:
    """Word form with every space removed, so `n u d e c h i l d` reads as one run.

    Rejoining single letters produces `nudechild`, where whole-word matching finds neither
    `nude` nor `child`. Substring matching on this form catches that — but only for inputs
    that ``looks_spaced_out`` has already identified, and never for the real-person check,
    where substring matching would fire `photograph` inside `photography`.
    """
    return normalise(text).replace(" ", "")


def _has(text: str, terms: frozenset[str]) -> bool:
    """Whole-word membership. Substring matching would fire on `assassin` for `ass`."""
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)


def _has_substring(text: str, terms: frozenset[str]) -> bool:
    """Substring membership, for the compact form only. See ``compact_form``."""
    return any(term in text for term in terms)


# ── vocabularies ───────────────────────────────────────────────────────────────────────

_SEXUAL = frozenset(
    {
        "sex",
        "sexual",
        "sexually",
        "nude",
        "nudes",
        "nudity",
        "naked",
        "topless",
        "porn",
        "porno",
        "pornographic",
        "pornography",
        "explicit",
        "erotic",
        "erotica",
        "nsfw",
        "hentai",
        "fetish",
        "orgasm",
        "masturbating",
        "masturbation",
        "genitals",
        "genitalia",
        "penis",
        "vagina",
        "breasts",
        "nipples",
        "buttocks",
        "lingerie",
        "undressed",
        "unclothed",
        "stripping",
        "striptease",
        "intercourse",
        "blowjob",
        "handjob",
        "cum",
        "creampie",
        "bdsm",
        "bondage",
    }
)

# Indicators that the subject is a minor. Deliberately broad: over-refusing here costs a
# caller one rejected prompt, and under-refusing costs something that cannot be undone.
_MINOR = frozenset(
    {
        "child",
        "children",
        "kid",
        "kids",
        "minor",
        "minors",
        "underage",
        "preteen",
        # NOT bare "pre": it is a substring of present/pretty/prepare, and the compact pass
        # below matches substrings — "a pretty woman, nude" would have been refused as CSAM.
        # "pre-teen" normalises to "pre teen" and is caught by "teen" anyway.
        "prepubescent",
        "pubescent",
        "toddler",
        "toddlers",
        "infant",
        "infants",
        "baby",
        "babies",
        "newborn",
        "boy",
        "boys",
        "girl",
        "girls",
        "schoolgirl",
        "schoolboy",
        "schoolkid",
        "student",
        "students",
        "pupil",
        "kindergarten",
        "elementary",
        "middleschool",
        "juvenile",
        "adolescent",
        "teen",
        "teens",
        "teenage",
        "teenager",
        "teenagers",
        "loli",
        "lolita",
        "shota",
        "jailbait",
        "youngster",
        "tween",
    }
)

# Ages written as numbers. Anything below 18 alongside sexual content is refused outright.
_AGE = re.compile(r"\b(\d{1,2})\s*(?:y(?:ea)?rs?(?:\s*old)?|yo|year old)\b")

# Words that mark the subject as a real, identifiable person rather than an invention.
#
# Deliberately NARROW, unlike the minors vocabulary above. Over-refusing here does not buy
# safety, it just refuses ordinary adult art — which the product explicitly allows. So the
# obvious-looking additions are absent on purpose: "photo"/"photograph"/"selfie" would refuse
# "nude photography", "model" would refuse "a nude model", and "real" would refuse "realistic
# style". None of those name a person, and NCII is about a named, identifiable one.
_REAL_PERSON = frozenset(
    {
        "celebrity",
        "celebrities",
        "actress",
        "actor",
        "singer",
        "popstar",
        "politician",
        "president",
        "influencer",
        "streamer",
        "youtuber",
        "journalist",
        "reallife",
        "deepfake",
        "deepfakes",
        "lookalike",
    }
)

# A capitalised given-name + surname, read from the ORIGINAL text (normalisation destroys
# case). Two capitalised words in a row is what "a named person" looks like in a prompt.
_PROPER_NAME = re.compile(r"\b[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b")

# Sentence-start and other benign capitalisation that would otherwise read as a name.
_NAME_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "with",
        "and",
        "or",
        "for",
        "to",
        "digital",
        "oil",
        "water",
        "high",
        "close",
        "wide",
        "full",
        "studio",
        "golden",
        "photo",
        "photograph",
        "portrait",
        "painting",
        "drawing",
        "sketch",
        "render",
        "art",
        "style",
        "shot",
        "view",
        "angle",
        "light",
        "colour",
        "color",
        "new",
    }
)


def _names_in(text: str) -> list[str]:
    """Capitalised two-word sequences that plausibly name a person."""
    found = []
    for match in _PROPER_NAME.finditer(text):
        first, second = match.group(0).split()
        if first.lower() in _NAME_STOPWORDS or second.lower() in _NAME_STOPWORDS:
            continue
        found.append(match.group(0))
    return found


def _mentions_minor(prompt: str) -> bool:
    """Three passes, because one form cannot answer all three questions.

    Words come from the normalised form, ages from the digit-preserving one (leetspeak
    substitution turns `12` into `i2`), and the compact form catches spaced-out spellings
    that rejoining fuses into a single unmatchable run.
    """
    flat = normalise(prompt)
    if _has(flat, _MINOR):
        return True
    if any(int(age) < 18 for age in _AGE.findall(numeric_form(prompt))):
        return True
    return looks_spaced_out(prompt) and _has_substring(compact_form(prompt), _MINOR)


class PromptModerator:
    """The real filter. Refuses the two categories above and nothing else."""

    def is_configured(self) -> bool:
        return True

    async def check_prompt(self, prompt: str) -> Verdict:
        try:
            return self._check(prompt)
        except Exception as exc:  # noqa: BLE001 - fail CLOSED, always
            # A filter that lets traffic through when it breaks is not a filter. Refusing
            # here costs a caller one prompt; the alternative is an outage that is invisible
            # precisely in the case this exists for.
            logger.error("prompt moderation failed, refusing: {}", exc)
            return Verdict.refuse("moderation_error")

    def _check(self, prompt: str) -> Verdict:
        flat = normalise(prompt)
        # The compact form is consulted for the sexual half too, or `n u d e c h i l d`
        # would fail the sexual test and never reach the minors test at all.
        sexual = _has(flat, _SEXUAL) or (
            looks_spaced_out(prompt) and _has_substring(compact_form(prompt), _SEXUAL)
        )

        # Category 1: sexual material involving minors. Checked first because it is the one
        # that must never be traded off against anything.
        if sexual and _mentions_minor(prompt):
            return Verdict.refuse("csam")

        # Category 2: sexual content about a real, named person. Requires BOTH a sexual
        # request and a subject that reads as a real individual — a named person in a
        # non-sexual prompt is fine, and a sexual prompt with no named subject is fine.
        if sexual and (_names_in(prompt) or _has(flat, _REAL_PERSON)):
            return Verdict.refuse("ncii")

        # Everything else, adult content included. Not this filter's business.
        return Verdict.allow()


class UnconfiguredModerator:
    """Refuses everything, and says so. The default when nothing has been installed."""

    def is_configured(self) -> bool:
        return False

    async def check_prompt(self, prompt: str) -> Verdict:  # noqa: ARG002 - refuses regardless
        return Verdict.refuse("moderation_unconfigured")


# Installed by default: image generation is gated on a configured moderator, and this is it.
_moderator: Moderator = PromptModerator()


def get_moderator() -> Moderator:
    return _moderator


def set_moderator(moderator: Moderator) -> None:
    """Swap the moderator. Used by tests, and by anything that supplies a better one."""
    global _moderator
    _moderator = moderator


def image_generation_available() -> bool:
    """Whether image generation may serve anything at all.

    Means "prompt screening is configured" and nothing more — there is no output screening,
    so this must not be read as "generated images are checked".
    """
    return get_moderator().is_configured()
