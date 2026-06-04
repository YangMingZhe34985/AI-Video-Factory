from decimal import Decimal

from sqlalchemy.inspection import inspect

from app.utils.time_utils import isoformat


class SerializerMixin:
    def to_dict(self) -> dict:
        result = {}
        for column in inspect(self.__class__).columns:
            if column.name == "metadata" and hasattr(self, "meta"):
                value = self.meta
            else:
                value = getattr(self, column.key)
            if isinstance(value, Decimal):
                value = float(value)
            result[column.name] = isoformat(value)
        return result
