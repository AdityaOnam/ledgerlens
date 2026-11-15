"""Who at the customer may agree terms with a vendor.

A price only binds the customer if someone allowed to agree it did: an agreement must be signed
by a listed signatory, and an email price must be agreed by a listed address. The list is a small
TOML file kept next to the mailbox:

    # authority.toml
    [[signatory]]
    name = "Priya Raman"
    email = "priya.raman@acme-robotics.com"

Without the file no authority check is made and every signed or emailed term is taken at face
value, which is how Ledgerlens behaved before the check existed.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

FILENAME = "authority.toml"


class AuthorityError(ValueError):
    """The authority file is missing a field or has one of the wrong type."""


@dataclass(frozen=True)
class Signatory:
    name: str
    email: str


def _name(signed_by: str) -> str:
    """'Priya Raman, VP Finance' -> 'priya raman'."""
    return " ".join(signed_by.split(",")[0].split()).casefold()


@dataclass(frozen=True)
class Authority:
    signatories: tuple[Signatory, ...]

    def may_sign(self, signed_by: str) -> bool:
        """True if the printed signatory of an agreement is on the list (matched by name)."""
        who = _name(signed_by)
        return bool(who) and any(_name(s.name) == who for s in self.signatories)

    def may_agree(self, address: str) -> bool:
        """True if an email address belongs to someone on the list."""
        return address.strip().lower() in {s.email.lower() for s in self.signatories}

    @property
    def contact(self) -> str:
        """Whom to ask for a sign-off: the first signatory listed."""
        return self.signatories[0].email if self.signatories else ""

    @classmethod
    def parse(cls, text: str) -> Authority:
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise AuthorityError(f"not valid TOML: {exc}") from exc
        people = raw.get("signatory", [])
        if not isinstance(people, list):
            raise AuthorityError("[[signatory]] must be an array of tables")
        out = []
        for i, p in enumerate(people, 1):
            name, email = (p.get("name"), p.get("email")) if isinstance(p, dict) else (None, None)
            if not isinstance(name, str) or not isinstance(email, str) or "@" not in email:
                raise AuthorityError(f"signatory {i} needs a name and an email address")
            out.append(Signatory(name.strip(), email.strip().lower()))
        return cls(tuple(out))

    @classmethod
    def load(cls, path: Path) -> Authority:
        return cls.parse(path.read_text(encoding="utf-8"))


def find(mailbox: Path) -> Path | None:
    """The authority file that sits at the top of a mailbox, if there is one."""
    path = mailbox / FILENAME
    return path if path.is_file() else None
