"""Surrogate generation — realistic fake values that keep the prompt natural.

Instead of replacing "Jane Doe" with ``[PERSON_1]`` (which makes models refuse
or get confused), we swap in a believable fake of the *same type* — e.g.
"Maria Lopez". The closed model reads a normal sentence; the mapping
surrogate -> original is kept locally so we can restore the real values in the
answer.

Uses `Faker` when installed for rich, varied data; otherwise falls back to
built-in word lists so the system always runs. Generation is seeded per process
and cached per original value, so the *same* input always maps to the *same*
surrogate within a run (keeps multi-mention text coherent).
"""

from __future__ import annotations

import random

try:  # pragma: no cover - optional dependency
    from faker import Faker  # type: ignore

    _FAKER_AVAILABLE = True
except Exception:  # pragma: no cover
    Faker = None  # type: ignore
    _FAKER_AVAILABLE = False

_FIRST_NAMES = [
    "Maria", "James", "Aisha", "Liam", "Sofia", "Noah", "Priya", "Mateo",
    "Hannah", "Omar", "Chloe", "Ethan", "Yuki", "Lucas", "Nina", "Diego",
    "Sara", "Caleb", "Leila", "Marcus", "Elena", "Tariq", "Grace", "Ivan",
]
_LAST_NAMES = [
    "Lopez", "Carter", "Khan", "Nguyen", "Rossi", "Patel", "Murphy", "Silva",
    "Kim", "Hassan", "Brooks", "Walsh", "Tanaka", "Reyes", "Bauer", "Okafor",
    "Cohen", "Ferreira", "Larsson", "Mwangi", "Novak", "Haddad", "Fisher",
]
_CITIES = [
    "Riverton", "Maplewood", "Fairhaven", "Glenview", "Ashford", "Bridgeport",
    "Cedar Falls", "Westbrook", "Elmgrove", "Northvale", "Hillcrest", "Lakemont",
]
_ORGS = [
    "Northwind Labs", "Brightpath", "Meridian Group", "Acme Holdings",
    "Solstice Systems", "Greenfield Co", "Vantage Partners", "Lumen Works",
]


class SurrogateGenerator:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)
        self._faker = Faker() if _FAKER_AVAILABLE else None
        if self._faker is not None and seed is not None:
            Faker.seed(seed)
        # original value -> surrogate, so repeats stay consistent within a run.
        self._cache: dict[tuple[str, str], str] = {}

    def for_entity(self, entity_type: str, original: str) -> str:
        key = (entity_type, original)
        if key in self._cache:
            return self._cache[key]
        value = self._generate(entity_type, original)
        # Guard against the (rare) case where the surrogate equals the original.
        for _ in range(5):
            if value != original:
                break
            value = self._generate(entity_type, original)
        self._cache[key] = value
        return value

    def _generate(self, entity_type: str, original: str) -> str:
        t = entity_type.upper()
        f = self._faker
        if t in ("PERSON", "JOB_TITLE", "CONTEXTUAL_IDENTIFIER"):
            return f.name() if f else self._name()
        if t in ("ORGANIZATION", "ORG"):
            return f.company() if f else self._rng.choice(_ORGS)
        if t in ("LOCATION", "GPE", "ADDRESS"):
            return f.city() if f else self._rng.choice(_CITIES)
        if t == "EMAIL_ADDRESS":
            return f.email() if f else self._email()
        if t == "PHONE_NUMBER":
            return f.phone_number() if f else self._phone()
        if t == "IP_ADDRESS":
            return f.ipv4() if f else self._ip()
        if t == "URL":
            return f.url() if f else "https://example.com/page"
        if t == "US_SSN":
            return f.ssn() if f else self._ssn()
        if t == "CREDIT_CARD":
            return f.credit_card_number() if f else self._cc()
        if t in ("US_BANK_NUMBER", "IBAN_CODE"):
            return f.iban() if (f and hasattr(f, "iban")) else self._digits(12)
        # Unknown identifier type -> a neutral fake name keeps text readable.
        return f.name() if f else self._name()

    def _name(self) -> str:
        return f"{self._rng.choice(_FIRST_NAMES)} {self._rng.choice(_LAST_NAMES)}"

    def _email(self) -> str:
        first = self._rng.choice(_FIRST_NAMES).lower()
        last = self._rng.choice(_LAST_NAMES).lower()
        return f"{first}.{last}@example.com"

    def _phone(self) -> str:
        return f"({self._digits(3)}) {self._digits(3)}-{self._digits(4)}"

    def _ip(self) -> str:
        return ".".join(str(self._rng.randint(1, 254)) for _ in range(4))

    def _ssn(self) -> str:
        return f"{self._digits(3)}-{self._digits(2)}-{self._digits(4)}"

    def _cc(self) -> str:
        return " ".join(self._digits(4) for _ in range(4))

    def _digits(self, n: int) -> str:
        return "".join(str(self._rng.randint(0, 9)) for _ in range(n))
