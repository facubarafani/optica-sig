"""A customer's phone, as WhatsApp wants it.

WhatsApp is reached through a wa.me link, which takes the number in
international form, digits only. A shop types phones the way people say them
("011 15-5555-0000", "351 155 123456", "15 5555 0000"), so this turns that into
``549`` + area code + number:

* ``54`` is Argentina and ``9`` marks a mobile. WhatsApp accounts are mobiles,
  so a number that does not say which it is gets the 9.
* ``0`` before the area code and ``15`` after it are how a mobile is dialled
  from inside the country. Neither belongs in the international form.
* The area code plus the number is always ten digits: 11 plus eight, a
  three-digit code plus seven, a four-digit one plus six. That is what tells
  where the 15 sits without a list of area codes: right after 11, after three
  digits, or after four, and only one of those can hold it.
* A local number without its area code ("4555-0000", or "15 512 3456" outside
  Buenos Aires) cannot be completed: which city it is in is not written down.
  "15" plus eight digits can, since only 11 has eight-digit numbers.

A number written with ``+`` and another country code is taken as typed. A
field with two numbers ("4555-0000 / 15 5555 0000") gives the first one that
works.

Nothing here talks to WhatsApp: the console opens the link, the shop's own
phone sends the message.
"""
from __future__ import annotations

import re

AR_MOBILE = "549"

# The area codes that are three digits long, each with the fourth digits that
# turn it into a longer code of its own instead: 294 is Bariloche, 2945 is
# Esquel. 11 is the only two-digit code and every other one has four. Only the
# display needs this; the number itself never depends on it, so a code missing
# here is still dialled right, only spaced wrong. Checked against
# libphonenumber's Argentine metadata.
_AREA_3 = {
    "220": "2", "221": "", "223": "", "230": "2", "236": "", "237": "",
    "249": "", "260": "", "261": "", "263": "", "264": "678", "266": "",
    "280": "", "291": "", "294": "02568", "297": "2", "298": "23", "299": "",
    "336": "", "341": "", "342": "", "343": "5678", "345": "4568",
    "348": "2379", "351": "", "353": "237", "358": "2345", "362": "",
    "364": "", "370": "", "376": "", "379": "", "380": "", "381": "",
    "383": "2578", "385": "45678", "387": "3678", "388": "5678",
}

# What separates two numbers typed in one field.
_SEPARATORS = re.compile(r"/|,|;|\||\s(?:o|y)\s", re.IGNORECASE)


class WhatsAppError(ValueError):
    """The phone cannot be turned into a WhatsApp number. Says why, in Spanish."""


def normalize(phone: str | None) -> str:
    """The digits wa.me takes for ``phone``, or WhatsAppError saying why not."""
    if not phone or not re.search(r"\d", phone):
        raise WhatsAppError("El cliente no tiene teléfono cargado.")
    first_error = None
    for piece in _SEPARATORS.split(phone):
        if not re.search(r"\d", piece):
            continue
        try:
            return _one(piece)
        except WhatsAppError as exc:
            first_error = first_error or exc
    raise first_error


def _one(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    international = text.strip().startswith("+")
    if digits.startswith("00"):
        digits, international = digits[2:], True
    # No Argentine area code starts with 5, so a long number opening with 54
    # was written in international form even without its "+".
    if international or (digits.startswith("54") and len(digits) >= 11):
        if not digits.startswith("54"):
            if 8 <= len(digits) <= 15:
                return digits
            raise WhatsAppError(f"El teléfono «{text.strip()}» no parece un número completo.")
        digits = digits[2:]
        if digits.startswith("9"):
            digits = digits[1:]

    national = digits.lstrip("0")
    if len(national) == 11 and national.startswith("9"):
        national = national[1:]                     # "9 11 5555 0000", without the 54
    if len(national) == 12:
        national = _without_15(national, text)
    elif len(national) == 10 and national.startswith("15"):
        national = "11" + national[2:]              # "15 5555 0000": only 11 has 8 digits
    if 6 <= len(national) <= 9:
        raise WhatsAppError(
            f"Al teléfono «{text.strip()}» le falta el código de área: "
            "cargalo completo, por ejemplo 11 5555-0000 o 351 512-3456."
        )
    if len(national) != 10 or not (national.startswith("11") or national[0] in "23"):
        raise WhatsAppError(
            f"El teléfono «{text.strip()}» no parece un celular de Argentina."
        )
    return AR_MOBILE + national


def _without_15(national: str, text: str) -> str:
    """Area code + 15 + number, with the 15 taken out.

    It sits after 11, or after three or four digits; for any other code, 15
    after the third digit and 15 after the fourth cannot both be there.
    """
    if national.startswith("11"):
        if national[2:4] == "15":
            return national[:2] + national[4:]
    else:
        for n in (3, 4):
            if national[n:n + 2] == "15":
                return national[:n] + national[n + 2:]
    raise WhatsAppError(f"El teléfono «{text.strip()}» tiene dígitos de más.")


def _area_length(national: str) -> int:
    if national.startswith("11"):
        return 2
    longer = _AREA_3.get(national[:3])
    return 3 if longer is not None and national[3] not in longer else 4


def display(number: str) -> str:
    """How a normalized number reads: ``+54 9 11 5555-0000``."""
    if not (number.startswith(AR_MOBILE) and len(number) == 13):
        return "+" + number
    national = number[3:]
    area = _area_length(national)
    rest = national[area:]
    return f"+54 9 {national[:area]} {rest[:-4]}-{rest[-4:]}"
