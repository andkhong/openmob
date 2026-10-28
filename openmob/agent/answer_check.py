"""The answer check: a done summary's list items and names against the text the task read on screen.

2026-10-20, measured: "read me the names of the first 30 apps" returned 29 names in screen order and then "and
OpenMob", out of order (likely padding). The model's done summary went to the user unchecked. This soft check is
cheap (string matching, no model call): the list items and proper names in a successful summary are looked up in
everything the task saw (element labels and OCR words of every look, the request and the user's corrections, the
tool calls and their results). When some were never seen, the model gets one short note and one chance to correct
the summary; if the corrected summary still names unseen items, the task ends anyway with them reported as
unverified (Agent._answer_check). It never blocks a task or loops. Config: answer_check (on).

Scoped 2026-10-21 (perf/launch-latency, after the latency review's probes): it runs only on requests that ask to
read, list or report something (asks_to_read), never on action requests ("Start the stopwatch, pause it and reset
it" was flagged for "paused"); contractions ("I've") and the phone's own brand and model words ("your Samsung")
are not names; a word matches its other forms ("paused" for "Pause"). The owner's saved preferences count as seen
(loop.Agent._memory_start / _memory_app). What it flags stays internal: events and history carry only the count.

A screen the task couldn't read as text (no labels and no OCR: a game, a picture) means the model may have read
the pixels, so the check doesn't run on that task.
"""

from __future__ import annotations

import re

MAX_SEEN = 20_000  # labels kept per task (a long scroll reads a few hundred per screen)
MAX_ITEM_WORDS = 6  # a longer comma-separated piece is prose, not a list item

# Words that say nothing about what was on screen: a list item made only of these is not checked.
STOP = set("""
a an the and or but nor of to in on at by for from with without into onto over under about as is are was were be
been being it its this that these those there here i you your my me we our they them their he she his her not no
yes off open opened closed enabled disabled turned set now currently also then only all any some none more most
less few several many first last next previous other another each every both either neither just still yet very
too so than which what who whom whose where when why how can cannot could would should will shall may might must
has have had do does did done one two three four five six seven eight nine ten found shows showing shown called
named listed app apps screen page item items total including include includes see seen read reads etc ok okay
zero
""".split())
# The phone itself: its brand and model words are never on screen, and naming the phone isn't an answer from it.
PHONE_WORDS = set("""
phone device android samsung galaxy pixel google oneplus motorola moto xiaomi redmi poco oppo vivo realme sony
xperia huawei honor nokia lg asus zenfone nothing tecno infinix fairphone
""".split())
# Contractions: "I've", "it's", "don't" are words, not names.
CONTRACTION = re.compile(r"(?i)^[a-z]+(?:['’](?:ve|m|ll|d|re|s|t))$|^[a-z]+n['’]t$")

# A request that asks to read, list or report something: a clause that starts with one of these (after "please",
# "can you"...). Action requests ("open", "start", "text", "set") don't get the check; navigation verbs that also
# read ("see", "check", "look") count only with a question word after them, as in fast.READ_BACK. Message bodies,
# and quoted text are dropped first (as in fast._steps_only): "Text Sam: what time is it" is an action.
READ_REQUEST = re.compile(
    r"^(?:read|list|name|count|summari[sz]e|tell\s+(?:me|us)|let\s+me\s+know|report|find\s+out|"
    r"what|what's|whats|which|who|who's|whose|where|where's|when\s+(?:is|was|does|did|do|are)|when's|"
    r"how\s+(?:many|much|long|old|far|is|are|does|do|did)|is|are|does|did|has|have|"
    r"(?:check|see|look)\s+(?:me\s+)?(?:whether|if|what|how|which|who|when|where))(?![a-z])", re.I)
SENTENCE_START = re.compile(r"(^|[.!?:;]\s+|\n\s*|^\s*[-*\d]+[.)]?\s+)$")


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (text or "").lower()).split())


def asks_to_read(request: str) -> bool:
    """The request (or a correction added mid-task) asks to read, list or report something (READ_REQUEST)."""
    from . import fast

    for line in fast.request_lines(request or ""):
        for clause in fast.clauses(fast._MESSAGE_BODY.sub(" ", fast._QUOTED.sub(" ", line))):
            if READ_REQUEST.match(fast.LEADING_FILLER.sub("", clause.strip())):
                return True
    return False


def stem(word: str) -> str:
    """A rough stem, so a word matches its other forms ("paused" ~ "pause", "names" ~ "name")."""
    for suffix in ("ing", "ed", "es", "s", "e", "d"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


class Seen:
    """Everything a task read: normalized labels and their words."""

    def __init__(self) -> None:
        self.labels: list[str] = []
        self.words: set[str] = set()
        self.stems: set[str] = set()
        self._known: set[str] = set()
        self.unreadable = False  # a look with no text to read (the model may have read the pixels)

    def add(self, text: str) -> None:
        norm = normalize(text)
        if not norm or norm in self._known or len(self._known) >= MAX_SEEN:
            return
        self._known.add(norm)
        self.labels.append(norm)
        self.words.update(norm.split())
        self.stems.update(stem(w) for w in norm.split())

    def has(self, phrase: str) -> bool:
        """`phrase` was seen: as part of one label, or (a longer phrase) every telling word of it was."""
        norm = normalize(phrase)
        if not norm:
            return True
        padded = f" {norm} "
        if any(padded in f" {label} " for label in self.labels):
            return True
        telling = [w for w in norm.split() if w not in STOP and w not in PHONE_WORDS and len(w) > 1]
        return not telling or all(w in self.words or stem(w) in self.stems for w in telling)


def _clean_item(item: str) -> str:
    item = re.sub(r"^\s*(?:and|or|&|plus)\s+", "", item.strip(), flags=re.I)
    item = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", item)
    return item.strip().strip(".!?\"'“”").strip()


def list_items(summary: str) -> list[str]:
    """The items of a list in the summary ("…: A, B, C and D." or one per line), or [] when it holds no list."""
    best: list[str] = []
    for chunk in re.split(r"(?<=[a-z][.!?])\s+(?=[A-Z])", summary or ""):
        body = chunk.split(":", 1)[1] if ":" in chunk else chunk
        parts = re.split(r"[,;\n]", body)
        if len(parts) >= 2 and not re.match(r"\s*(?:and|&)\s", parts[-1]):  # "A, B and C": C after the "and"
            parts[-1:] = re.split(r"\s+(?:and|&)\s+", parts[-1], maxsplit=1)
        items = [_clean_item(p) for p in parts]
        items = [i for i in items if i]
        if len(items) >= 3 and sum(len(i.split()) <= MAX_ITEM_WORDS for i in items) >= 0.8 * len(items):
            best = best if len(best) >= len(items) else [i for i in items if len(i.split()) <= MAX_ITEM_WORDS]
    return best


def proper_names(summary: str) -> list[str]:
    """Capitalized words that don't start a sentence, and CamelCase words anywhere ("OpenMob", "YouTube")."""
    out = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9'’-]*", summary or ""):
        word = match.group(0)
        camel = bool(re.search(r"[a-z][A-Z]", word))
        capital = word[0].isupper() and not SENTENCE_START.search(summary[: match.start()])
        if CONTRACTION.match(word) or normalize(word) in PHONE_WORDS:
            continue
        if (camel or capital) and normalize(word) not in STOP and len(word) > 1:
            out.append(word)
    return out


def unseen(summary: str, seen: Seen) -> list[str]:
    """The summary's list items and names the task never saw, in the summary's order, without repeats."""
    if seen.unreadable or not seen.labels:
        return []
    found: list[str] = []
    items = list_items(summary)
    for item in items:
        if not seen.has(item) and item not in found:
            found.append(item)
    for name in proper_names(summary):
        if any(normalize(name) in normalize(i).split() for i in found):
            continue  # already reported as part of an item
        if not seen.has(name) and name not in found:
            found.append(name)
    return found


def note(missing: list[str]) -> str:
    shown = ", ".join(f'"{m}"' for m in missing[:10]) + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")
    return (f"Answer check: {shown} in your summary did not appear in any screen text this task read. Answer only "
            "from what was on screen, list items in the order they appeared, and say so if you found fewer than "
            "asked. Call done again with the corrected summary (the same one if it was right).")
