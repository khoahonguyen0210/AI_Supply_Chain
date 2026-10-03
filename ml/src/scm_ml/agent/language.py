from __future__ import annotations

import re

NUMBER_WORDS = {
    "one": 1,
    "a": 1,
    "an": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_NUM = r"(\d+|" + "|".join(k for k in NUMBER_WORDS if len(k) > 2) + r")"


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def to_int(token: str) -> int:
    return int(token) if token.isdigit() else NUMBER_WORDS[token]


def words(*items: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(items) + r")\b")


UP = words(
    r"ris(?:e|es|ing)",
    r"increas(?:e|es|ed|ing)",
    r"grow(?:s|ing|th)?",
    r"go(?:es)? up",
    r"going up",
    r"up",
    r"higher",
    r"more",
    r"jump(?:s|ing)?",
    r"surg(?:e|es|ing)",
    r"spik(?:e|es|ing)",
    r"climb(?:s|ing)?",
    r"boost(?:s|ed)?",
    r"faster",
    r"rais(?:e|es|ed|ing)",
    r"doubl(?:e|es|ing)",
)
DOWN = words(
    r"drop(?:s|ping)?",
    r"fall(?:s|ing)?",
    r"declin(?:e|es|ing)",
    r"decreas(?:e|es|ing)",
    r"go(?:es)? down",
    r"down",
    r"lower",
    r"less",
    r"fewer",
    r"shrink(?:s|ing)?",
    r"slower",
    r"cut(?:s)?",
    r"reduc(?:e|es|ed|ing)",
)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)")

HYPOTHETICAL = re.compile(
    r"^say\b|\bhow would\b.{0,60}\b(affect|hit|impact|change)|\bwhat does (that|it|this) mean for|"
    r"\b(what if|suppose|imagine|let's say|lets say|say that|assume|what would happen|"
    r"what happens|in case|what's the impact|what is the impact|how does that affect|"
    r"how would that affect|stress[- ]test|scenario|disruption)\b|^if\b|\bif\b.*\?$"
)
DEMAND = words(
    r"demand",
    r"sales?",
    r"sell(?:s|ing)?",
    r"sold",
    r"promotion",
    r"customer orders",
    r"customers? (?:are |is )?buying",
)
PRICE = words(
    r"prices?", r"pricing", r"more expensive", r"cheaper", r"charg(?:e|es|ing) more", r"unit costs?"
)
TRANSPORT = words(
    r"shipping",
    r"freight",
    r"transport(?:ation)?",
    r"logistics",
    r"delivery costs?",
    r"carrier rates?",
)
OUTAGE = words(
    r"outage",
    r"go(?:es)? down",
    r"went down",
    r"is down",
    r"fail(?:s|ed)?",
    r"shuts? down",
    r"can't deliver",
    r"cannot deliver",
    r"won't deliver",
    r"stops? delivering",
    r"stopped delivering",
    r"unavailable",
    r"out of business",
    r"bankrupt",
    r"goes bust",
)
LEAD_DELAY = re.compile(
    _NUM + r"[\s-]*(days?|weeks?)[\s-]*(?:longer|late|later|more|extra|delay(?:ed)?)|"
    r"(?:delay(?:ed)?|late) by\s*" + _NUM + r"\s*(days?|weeks?)|"
    r"lead times?\b.{0,30}?" + _NUM + r"\s*(days?|weeks?)"
)
LEAD_LIMIT = re.compile(
    r"(?:within|in under|in less than|under|no more than|at most)\s*" + _NUM + r"\s*(days?|weeks?)|"
    r"\bin\s*" + _NUM + r"\s*(days?|weeks?)\s*or less"
)
WAREHOUSE = re.compile(r"\bwh[-\s]?(\d{1,2})\b")
MAIN_SUPPLIER = re.compile(r"\b(main|biggest|largest|primary|top|usual|current) supplier\b")

DOCUMENT = words(
    r"contracts?",
    r"agreements?",
    r"polic(?:y|ies)",
    r"slas?",
    r"sops?",
    r"clauses?",
    r"certificat\w*",
    r"rebates?",
    r"payment terms?",
    r"committed",
    r"guaranteed?",
    r"agreed",
    r"promised",
)

APPROVE_VERB = words(r"approve", r"reject", r"sign off on", r"authori[sz]e")
QUESTION_START = re.compile(
    r"^(what|which|who|whom|when|where|how|why|does|do|is|are|can|could|may|must|should|"
    r"would|will|am i|tell me|explain)\b"
)
PERFORMANCE = re.compile(
    r"\b(how reliable|reliability of|track record|supplier performance|performance of|"
    r"been performing|been doing|on[- ]time (rate|record|delivery|deliveries)|delivery record|"
    r"how (good|well) (is|has|are|have)|dependable|trustworthy|can we (trust|rely on))\b"
)
SOURCING = re.compile(
    r"\b(compare suppliers|which suppliers?|who can (supply|ship|deliver|provide|make)|"
    r"find (me )?(a |some )?suppliers?|best suppliers?|supplier options|suppliers? (for|that|who)|"
    r"alternative suppliers?|other suppliers?|can (ship|deliver|supply)|vendors?|"
    r"who could (supply|ship|deliver|provide)|providers? (for|of))\b"
)
STOCK = re.compile(
    r"\b(inventory|in stock|on hand|on the shelf|on the shelves|stock levels?|stock on hand|"
    r"run(ning)? out|run(ning)? low|stock ?outs?|enough (stock|inventory|units)|how much stock|"
    r"how many units do we have|do we have|stock position|inventory position|stock status)\b"
)
ACTION = re.compile(
    r"\b(plan\b.{0,25}\b(buying|purchas\w*|procurement|orders?)|"
    r"what (we|i) should (purchase|buy|order)|should (we|i) purchase|"
    r"work out (what|an order|a plan)|book (a |an )?(purchase )?order|purchase order for|"
    r"what should (i|we)|should (i|we) (buy|order|restock|reorder|get)|(buy|order|get) more|"
    r"restock|replenish|reorder|re-order|recommend|purchase plan|plan (the|our) purchases?|"
    r"what (do|should) (i|we) (need to )?(order|buy)|what to (order|buy)|place an order|"
    r"prepare (the |an |a )?(order|purchase|po)|put together a (purchase )?plan|"
    r"how much (should|do) (i|we) (order|buy))\b"
)
FORECAST = re.compile(
    r"\b(forecast|expected demand|demand forecast|how much demand|expected to sell|"
    r"(will|we'll|going to|gonna|likely to|expect to) sell|projected (sales|demand)|predict|"
    r"(how much|how many)\b.{0,40}\b(sell|sold|demand)|outlook|projection|"
    r"expect(ed)? to (move|sell|ship))\b"
)


# small talk with no topic: ask what they need instead of searching documents
SMALL_TALK = re.compile(
    r"^(how are things|how's (it|everything) going|how is (it|everything) going|"
    r"how are we doing|what's up|whats up|any (news|updates?)|what's new|hello|hi|hey)\b"
)

DELAY = words(r"delay(?:s|ed)?", r"late deliver(?:y|ies)", r"deliveries (?:are|arrive|come) late")
CAPACITY = re.compile(
    r"\b(capacity|only (deliver|ship|supply|produce|make)|of (their|its|the) (usual|normal)|"
    r"reduced (volume|supply|output))\b"
)
SHARE_OF_USUAL = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of (their|its|the) (usual|normal)")


def percent(text: str) -> float | None:
    m = PERCENT.search(text)
    return float(m.group(1)) if m else None


def change_factor(text: str) -> float | None:
    """1 + p/100 for a rise of p%, 1 - p/100 for a fall; None without both."""
    m = PERCENT.search(text)
    if m is None:
        return None
    p = float(m.group(1))
    clean = LEAD_LIMIT.sub(
        lambda x: " " * len(x.group(0)), OUTAGE.sub(lambda x: " " * len(x.group(0)), text)
    )
    # the direction word closest to the percentage wins ("drops 30% ... more stock" is a fall)
    candidates = [(abs(w.start() - m.start()), 1) for w in UP.finditer(clean)]
    candidates += [(abs(w.start() - m.start()), -1) for w in DOWN.finditer(clean)]
    if not candidates:
        return None
    sign = min(candidates)[1]
    return round(1 + sign * p / 100, 4)


def _days(number: str, unit: str) -> int:
    return to_int(number) * (7 if unit.startswith("week") else 1)


def lead_time_limit(text: str) -> tuple[int | None, str]:
    m = LEAD_LIMIT.search(text)
    if not m:
        return None, text
    number = m.group(1) or m.group(3)
    unit = m.group(2) or m.group(4)
    return _days(number, unit), text[: m.start()] + " " + text[m.end() :]


def delay_days(text: str) -> int | None:
    m = LEAD_DELAY.search(text)
    if not m:
        return None
    groups = [g for g in m.groups() if g]
    return _days(groups[0], groups[1])


def horizon_weeks(text: str) -> int | None:
    if m := re.search(_NUM + r"\s*(?:weeks?|wks?)\b", text):
        return to_int(m.group(1))
    if m := re.search(_NUM + r"\s*months?\b", text):
        return 4 * to_int(m.group(1))
    if re.search(r"\b(next|this|coming) quarter\b", text):
        return 12
    if re.search(r"\b(next|this|coming) month\b", text):
        return 4
    return None


def warehouse(text: str) -> str | None:
    m = WAREHOUSE.search(text)
    return f"WH-{int(m.group(1))}" if m else None


def is_approval_command(text: str) -> bool:
    if not APPROVE_VERB.search(text):
        return False
    return not (QUESTION_START.search(text) or text.rstrip().endswith("?"))
