from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def rubles(value):
    if value is None:
        return "Не указана"
    value = Decimal(value)
    places = 0 if value == value.to_integral_value() else 2
    return f"{value:,.{places}f}".replace(",", "\u00a0").replace(".", ",") + " ₽"
