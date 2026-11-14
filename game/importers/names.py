"""Porównywanie imion i nazwisk zawodników (różne zapisy tego samego nazwiska)."""

import re
import unicodedata


def name_tokens(name: str) -> list[str]:
    """Nazwisko i imiona jako posortowane małe litery bez znaków diakrytycznych."""
    text = name.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return sorted(re.findall(r"[a-z]+", text.lower()))


def names_match(a: str, b: str) -> bool:
    """Ta sama osoba: te same słowa (w dowolnej kolejności) albo skrócone imię (Alex~Alexandru)."""
    tokens_a, tokens_b = name_tokens(a), name_tokens(b)
    if not tokens_a or tokens_a == tokens_b:
        return bool(tokens_a)
    if len(tokens_a) != len(tokens_b):
        return False
    return all(
        min(len(x), len(y)) >= 3 and (x.startswith(y) or y.startswith(x))
        for x, y in zip(tokens_a, tokens_b, strict=True)
    )
