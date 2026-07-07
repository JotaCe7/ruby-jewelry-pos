from decimal import Decimal

import requests
from django.utils.translation import gettext_lazy as _

from .models import DailyExchangeRate

SUNAT_RATE_API_URL = "https://api.apis.net.pe/v1/tipo-cambio-sunat"


class ExchangeRateUnavailable(Exception):
    """Raised when the upstream rate API can't be reached for a given date."""


class ExchangeRateService:
    @classmethod
    def get_for(cls, date, currency: str) -> Decimal:
        if currency == "PEN":
            return Decimal("1.0000")

        cached = DailyExchangeRate.objects.filter(date=date).first()
        if cached:
            return cached.value

        try:
            response = requests.get(
                SUNAT_RATE_API_URL, params={"fecha": date.isoformat()}, timeout=5
            )
            response.raise_for_status()
            data = response.json()
            # "venta" (sell rate) is what a PEN-denominated business pays to
            # acquire USD, which is the correct rate for valuing a USD expense.
            value = Decimal(str(data["venta"]))
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            raise ExchangeRateUnavailable(
                _("Could not fetch the exchange rate for %(date)s.") % {"date": date}
            ) from exc

        DailyExchangeRate.objects.create(
            date=date, value=value, source=data.get("origen", "SUNAT")
        )
        return value
