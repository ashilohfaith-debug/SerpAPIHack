"""Spoken arithmetic — "what is 25 times 4", "10 percent of 250", "2 lakh by 12".

Turns a spoken calculation into a small arithmetic expression and evaluates it with
an AST whitelist (numbers, + - * / % **, and sqrt) — never ``eval``. Understands
number words ("twenty five", "two hundred and fifty", "one point five") including
Indian scales (lakh, crore) and common Indian-English phrasing ("5 into 3" = times,
"1200 by 12" = divided by). Returns None when the utterance isn't a calculation, so
it can't swallow other commands.
"""

from __future__ import annotations

import ast
import math
import operator
import re

_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "lakhs": 100_000,
           "lac": 100_000, "lacs": 100_000, "million": 1_000_000, "crore": 10_000_000,
           "crores": 10_000_000, "billion": 1_000_000_000}

_LEAD = re.compile(r"^(?:what(?:'s| is)|whats|calculate|compute|how much is|solve|"
                   r"tell me|find|work out)\s+", re.I)
_TAIL = re.compile(r"\s+(?:equals?|is equal to|is)$", re.I)

_OPS = [
    (r"\bmultiplied by\b|\btimes\b|\binto\b|(?<=\d)\s*x\s*(?=\d)|\bx\b", " * "),
    (r"\bdivided by\b|\bover\b|\bby\b", " / "),
    (r"\bplus\b|\badded to\b", " + "),
    (r"\bminus\b|\bless\b|\btake away\b", " - "),
    (r"\bpercent of\b|% of\b", " * 0.01 * "),
    (r"\bpercent\b|%", " * 0.01 "),
    (r"\bto the power of\b|\braised to(?: the power of)?\b|\bpower\b", " ** "),
    (r"\bsquared\b", " ** 2 "),
    (r"\bcubed\b", " ** 3 "),
    (r"\bmod(?:ulo)?\b", " % "),
]


def _words_to_numbers(text: str) -> str:
    """Replace runs of number words with digits: 'two hundred and fifty' -> '250'."""
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?|[^\sa-z\d]", text.lower().replace(",", ""))
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in _UNITS or t in _TENS or (t in _SCALES and out and _is_num(out[-1])) \
                or (t == "a" and i + 1 < len(tokens) and tokens[i + 1] in _SCALES):
            total, current, j = 0.0, 0.0, i
            seen = False
            if t in _SCALES:                       # "2 lakh" -> scale a digit
                current = float(out.pop())
            while j < len(tokens):
                w = tokens[j]
                if w in _UNITS:
                    current += _UNITS[w]
                elif w in _TENS:
                    current += _TENS[w]
                elif w == "a" and j + 1 < len(tokens) and tokens[j + 1] in _SCALES:
                    current = max(current, 1)
                elif re.fullmatch(r"\d+(?:\.\d+)?", w) and not seen:
                    current += float(w)
                elif w in _SCALES:
                    s = _SCALES[w]
                    if s == 100:
                        current = (current or 1) * s
                    else:
                        total += (current or 1) * s
                        current = 0
                elif w == "and" and j + 1 < len(tokens) and (tokens[j + 1] in _UNITS
                                                             or tokens[j + 1] in _TENS):
                    pass
                elif w == "point" and j + 1 < len(tokens) and tokens[j + 1] in _UNITS:
                    digits = []
                    j += 1
                    while j < len(tokens) and tokens[j] in _UNITS and _UNITS[tokens[j]] < 10:
                        digits.append(str(_UNITS[tokens[j]]))
                        j += 1
                    current += float("0." + "".join(digits))
                    continue
                else:
                    break
                seen = True
                j += 1
            value = total + current
            out.append(str(int(value)) if value == int(value) else str(value))
            i = j
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", t) and i + 1 < len(tokens) and tokens[i + 1] in _SCALES:
            out.append(t)                           # let the scale branch multiply it
            i += 1
            continue
        out.append(t)
        i += 1
    return " ".join(out)


def _is_num(s: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", s))


_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
            raise ValueError("too large")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "sqrt" and len(node.args) == 1:
        return math.sqrt(_eval(node.args[0]))
    raise ValueError("not arithmetic")


def to_expression(text: str) -> tuple[str, str] | None:
    """Return (spoken_question, python_expression) or None if not a calculation."""
    t = text.strip().lower().rstrip("?.! ")
    t = _LEAD.sub("", t)
    t = _TAIL.sub("", t)
    if not t:
        return None
    t = re.sub(r"^(?:the )?sum of (.+?) and (.+)$", r"\1 plus \2", t)
    t = re.sub(r"^add (.+?) (?:and|to) (.+)$", r"\1 plus \2", t)
    t = re.sub(r"^subtract (.+?) from (.+)$", r"\2 minus \1", t)
    t = re.sub(r"^(?:the )?product of (.+?) and (.+)$", r"\1 times \2", t)
    t = re.sub(r"^half of (.+)$", r"0.5 times \1", t)
    spoken = t
    expr = _words_to_numbers(t)
    expr = re.sub(r"(?:the )?square root of\s+([\d.]+)", r"sqrt(\1)", expr)
    for pat, rep in _OPS:
        expr = re.sub(pat, rep, expr)
    expr = re.sub(r"\s+", " ", expr).strip()
    # must be only numbers, operators, parentheses and sqrt — and contain an operation
    if not re.fullmatch(r"[\d.\s+\-*/%()]*(?:sqrt\([\d.]+\)[\d.\s+\-*/%()]*)*", expr):
        return None
    if not re.search(r"\d", expr) or not re.search(r"[+\-*/%]|sqrt", expr):
        return None
    return spoken, expr


def calculate(text: str) -> tuple[str, float] | None:
    """Evaluate a spoken calculation. Returns (spoken_question, value) or None.
    Raises ZeroDivisionError for division by zero (caller says so plainly)."""
    parsed = to_expression(text)
    if parsed is None:
        return None
    spoken, expr = parsed
    try:
        value = _eval(ast.parse(expr, mode="eval"))
    except ZeroDivisionError:
        raise
    except (ValueError, SyntaxError, TypeError, OverflowError):
        return None
    return spoken, float(value)


def format_number(value: float) -> str:
    """Speakable number: whole numbers without '.0', others to 4 decimals."""
    if math.isnan(value) or math.isinf(value):
        return "undefined"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):d}"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def answer(text: str) -> str | None:
    """Full spoken answer, or None if the text isn't a calculation."""
    try:
        res = calculate(text)
    except ZeroDivisionError:
        return "You can't divide by zero."
    if res is None:
        return None
    spoken, value = res
    return f"{spoken} is {format_number(value)}."
