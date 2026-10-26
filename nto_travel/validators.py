import re

from django.core.exceptions import ValidationError


PHONE_ERROR = "Укажите российский номер: +7 (903) 123-45-67, 8 (903) 123-45-67 или 9031234567."


def normalize_phone(value):
    value = (value or "").strip()
    if not value:
        return ""
    if not re.fullmatch(r"\+?[0-9()\s-]+", value):
        raise ValidationError(PHONE_ERROR)
    digits = re.sub(r"[^0-9]", "", value)
    # Also repair the +8 prefix produced by the previous normalization.
    if len(digits) == 11 and digits[0] in {"7", "8"}:
        digits = digits[1:]
    elif value.startswith("+"):
        raise ValidationError(PHONE_ERROR)
    if not re.fullmatch(r"[3489][0-9]{9}", digits):
        raise ValidationError(PHONE_ERROR)
    return "+7" + digits
