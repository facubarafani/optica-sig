"""A customer's phone as WhatsApp wants it (services.whatsapp).

Cross-checked once against libphonenumber's Argentine metadata, every area
code in a dozen spellings; these are the cases worth keeping in the suite.
"""
import pytest

from app.services import whatsapp


@pytest.mark.parametrize("typed, number", [
    # Buenos Aires, every way people write it.
    ("11 5555-0000", "5491155550000"),
    ("1155550000", "5491155550000"),
    ("011 15 5555-0000", "5491155550000"),
    ("(011) 15-5555-0000", "5491155550000"),
    ("15 5555 0000", "5491155550000"),            # only 11 has eight-digit numbers
    ("+54 9 11 5555-0000", "5491155550000"),
    ("+54 11 5555 0000", "5491155550000"),         # no 9: a WhatsApp number is a mobile
    ("+54 9 11 15 5555 0000", "5491155550000"),    # both marks at once
    ("5491155550000", "5491155550000"),            # international without the +
    ("0054 9 11 5555 0000", "5491155550000"),
    ("9 11 5555 0000", "5491155550000"),
    ("11 15 1555 0000", "5491115550000"),          # a number that itself starts with 15
    # Three-digit area codes (Córdoba).
    ("0351 15 512-3456", "5493515123456"),
    ("(351) 155-123456", "5493515123456"),
    ("351 512 3456", "5493515123456"),
    ("+54 351 15 512 3456", "5493515123456"),
    ("+54 9 351 5123456", "5493515123456"),
    # Four-digit ones, including one that starts like a three-digit code
    # (294 is Bariloche, 2945 is Esquel).
    ("02966 15 41-2345", "5492966412345"),
    ("2966 412345", "5492966412345"),
    ("(02945) 15 45-1234", "5492945451234"),
    ("0294 15 451-2345", "5492944512345"),
    # Two numbers in one field: the first that works.
    ("4555-0000 / 15 5555 0000", "5491155550000"),
    ("11 5555-0000 o 11 4444-0000", "5491155550000"),
    # Another country, written with its code, is taken as typed.
    ("+598 99 123 456", "59899123456"),
    ("+1 (305) 555-1234", "13055551234"),
])
def test_normalize(typed, number):
    assert whatsapp.normalize(typed) == number


@pytest.mark.parametrize("typed, says", [
    (None, "no tiene teléfono"),
    ("", "no tiene teléfono"),
    ("sin teléfono", "no tiene teléfono"),
    ("4555-0000", "falta el código de área"),
    ("15 512 3456", "falta el código de área"),    # a mobile, but in which city?
    ("12345", "no parece un celular de Argentina"),
    ("4555000012", "no parece un celular de Argentina"),
    ("351 99 512 3456", "dígitos de más"),
    ("+12", "no parece un número completo"),
])
def test_normalize_says_why_not(typed, says):
    with pytest.raises(whatsapp.WhatsAppError) as exc:
        whatsapp.normalize(typed)
    assert says in str(exc.value)


@pytest.mark.parametrize("number, shown", [
    ("5491155550000", "+54 9 11 5555-0000"),
    ("5493515123456", "+54 9 351 512-3456"),
    ("5492966412345", "+54 9 2966 41-2345"),
    ("5492945451234", "+54 9 2945 45-1234"),
    ("5492944512345", "+54 9 294 451-2345"),
    ("59899123456", "+59899123456"),
])
def test_display(number, shown):
    assert whatsapp.display(number) == shown
