"""Class registry helpers: parsing the violation strings stored in ppes.class1."""
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ModelClass

# Legacy spellings seen in ppes.class1 from older inference scripts
_ALIASES = {"no glove": "no gloves", "no shoe": "no shoes", "no goggle": "no goggles", "glove": "gloves", "shoe": "shoes", "goggle": "goggles"}


def normalize(name: str) -> str:
    s = re.sub(r"[\s_]+", " ", str(name).strip().lower())
    return _ALIASES.get(s, s)


@dataclass(frozen=True)
class Registry:
    names: list[str]                 # index = YOLO class id
    violation_names: list[str]       # display names of violation classes, registry order
    by_normalized: dict[str, str]    # normalized -> display name
    violation_set: frozenset[str]

    def violations_in(self, value: str | None) -> list[str]:
        """'No Helmet, no_glove; Helmet' -> ['No Helmet', 'No Gloves'] (registry order, deduplicated)."""
        if not value:
            return []
        found = set()
        for part in re.split(r"[,;]", str(value)):
            display = self.by_normalized.get(normalize(part))
            if display in self.violation_set:
                found.add(display)
        return [n for n in self.violation_names if n in found]


def load_registry(db: Session) -> Registry:
    rows = db.scalars(select(ModelClass).order_by(ModelClass.class_id)).all()
    return Registry(
        names=[r.name for r in rows],
        violation_names=[r.name for r in rows if r.is_violation],
        by_normalized={normalize(r.name): r.name for r in rows},
        violation_set=frozenset(r.name for r in rows if r.is_violation),
    )
