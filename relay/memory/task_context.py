"""L2 — task and conversation memory (in RAM).

Holds the current goal, the plan and step states, the last-narrated snapshot (so
change deltas can be computed), and the reference bindings that let commands like
"click the second result" or "read that" resolve to a specific OBSERVED element.

A reference is bound to an element's identity plus the observation_version it was
seen in. Resolving re-finds the element in the CURRENT snapshot; if the snapshot has
moved on (stale) or the element is gone, resolution fails and the caller re-observes
or asks — RELAY never acts on a guessed or stale reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from relay.perception.semantic import ScreenSnapshot, UIElement

CLICKABLE = {
    "Button",
    "Hyperlink",
    "MenuItem",
    "ListItem",
    "TabItem",
    "CheckBox",
    "RadioButton",
    "TreeItem",
    "SplitButton",
}
_DEMONSTRATIVES = {"that", "it", "this", "the same", "them", "the one"}
# spoken role word -> UIA roles it covers
ROLE_WORDS = {
    "link": {"Hyperlink"},
    "result": {"Hyperlink"},
    "button": {"Button", "SplitButton"},
    "item": {"ListItem", "TreeItem", "MenuItem"},
    "option": CLICKABLE,
    "checkbox": {"CheckBox"},
    "tab": {"TabItem"},
    "menu item": {"MenuItem"},
    "field": {"Edit", "ComboBox"},
    "heading": {"Text"},
}


def reading_order(elements):
    """Top-to-bottom, then left-to-right — the order a user means by 'the second one'."""
    return sorted(elements, key=lambda e: (e.bbox[1] // 12, e.bbox[0]))


@dataclass(frozen=True)
class ElementRef:
    name: str
    role: str
    bbox: tuple[int, int, int, int]
    observation_version: int


@dataclass
class TaskContext:
    task_id: str
    goal: str = ""
    references: dict[str, ElementRef] = field(default_factory=dict)
    last_ref_key: str | None = None
    last_narrated: ScreenSnapshot | None = None

    def remember(self, key: str, el: UIElement, version: int) -> None:
        self.references[key] = ElementRef(el.name, el.role, el.bbox, version)
        self.last_ref_key = key


def resolve_reference(
    ctx: TaskContext,
    current: ScreenSnapshot | None,
    target: str | None = None,
    ordinal: int | None = None,
    role: str | None = None,
) -> tuple[UIElement | None, str | None]:
    """Return (element, error). error is a machine code the caller narrates:
    no_screen | out_of_range | no_prior_reference | reference_stale | not_found | no_target."""
    if current is None:
        return None, "no_screen"

    if ordinal is not None:
        roles = ROLE_WORDS.get(role or "", CLICKABLE)
        pool = [e for e in current.elements if e.role in roles and e.name]
        if not pool and not role:
            pool = [e for e in current.elements if e.name]
        pool = reading_order(pool)
        idx = ordinal - 1 if ordinal > 0 else len(pool) - 1
        if 0 <= idx < len(pool):
            el = pool[idx]
            ctx.remember("last", el, current.observation_version)
            return el, None
        return None, "out_of_range"

    if target:
        t = target.strip().lower()
        if t in ("previous field", "the previous field", "last field", "prior field"):
            fields = [e for e in current.elements if e.role in ("Edit", "ComboBox") and e.name]
            fields = reading_order(fields)
            if current.focus and current.focus in fields:
                idx = fields.index(current.focus)
                if idx > 0:
                    el = fields[idx - 1]
                    ctx.remember("last", el, current.observation_version)
                    return el, None
            elif fields:
                el = fields[-1]
                ctx.remember("last", el, current.observation_version)
                return el, None
            return None, "not_found"

        if t in ("next field", "the next field", "following field"):
            fields = [e for e in current.elements if e.role in ("Edit", "ComboBox") and e.name]
            fields = reading_order(fields)
            if current.focus and current.focus in fields:
                idx = fields.index(current.focus)
                if idx < len(fields) - 1:
                    el = fields[idx + 1]
                    ctx.remember("last", el, current.observation_version)
                    return el, None
            elif fields:
                el = fields[0]
                ctx.remember("last", el, current.observation_version)
                return el, None
            return None, "not_found"

        if t in _DEMONSTRATIVES:
            ref = ctx.references.get(ctx.last_ref_key) if ctx.last_ref_key else None
            if ref is None:
                return None, "no_prior_reference"
            for e in current.elements:
                if e.name.lower() == ref.name.lower() and e.role == ref.role:
                    ctx.remember("last", e, current.observation_version)
                    return e, None
            return None, "reference_stale"
        matches = current.find(target)
        if not matches:  # "click the login button" -> "login"
            bare = " ".join(
                w
                for w in t.split()
                if w not in ROLE_WORDS and w not in ("the", "a", "an", "on", "named", "called")
            )
            if bare and bare != t:
                matches = current.find(bare)
        if matches:
            if len(matches) > 1 and (len({m.name for m in matches}) > 1 or len({m.bbox for m in matches}) > 1):
                # Ambiguous match among distinct elements
                return None, "ambiguous"
            ctx.remember("last", matches[0], current.observation_version)
            return matches[0], None
        return None, "not_found"

    return None, "no_target"
