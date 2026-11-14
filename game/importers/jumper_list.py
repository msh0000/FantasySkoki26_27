"""Lista zawodników w grze (data/jumpers_list.tsv) - to ona wyznacza pulę do wyboru."""

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ListRow:
    name: str
    country: str
    gender: str
    external_id: str = ""


def read_jumper_list(path: Path) -> list[ListRow]:
    """Czyta plik TSV z kolumnami: name, country, gender, external_id (ostatnia opcjonalna)."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return [
            ListRow(
                name=(row.get("name") or "").strip(),
                country=(row.get("country") or "").strip().upper(),
                gender=(row.get("gender") or "").strip().upper(),
                external_id=(row.get("external_id") or "").strip(),
            )
            for row in reader
            if (row.get("name") or "").strip()
        ]
