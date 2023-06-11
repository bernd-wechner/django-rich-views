import unittest

from datetime import datetime, date, time, timedelta
from decimal import Decimal
from uuid import UUID
from django.utils.functional import lazystr


from django_rich_views.serializers import dumps, loads

class TypedEncoderTestCase(unittest.TestCase):

    test_obj = { "int": 1,
                 "float": 1.2,
                 "string": 'This is a string',
                 "dict": {"key1": 1, "key2": 2},
                 "list": [1, 2, 3],
                 "bool": True,
                 "none": None,
                 "datetime": datetime(year=1234, month=5, day=6, hour=7, minute=8, second=9, microsecond=10),
                 "date": date(year=1234, month=5, day=6),
                 "time": time(hour=1, minute=2, second=3, microsecond=4),
                 "timedelta": timedelta(days=1, hours=2, minutes=3, seconds=4, milliseconds=5),
                 "Decimal": Decimal("1.234567890123456789"),
                 "UUID": UUID(bytes=b'\xb6;\x02\xaf\xa3\xea\x88\x1b\xcd\xea\xb8/\xca\xae\xa9\xfa', version=4),
                 "Promise": lazystr("This is a promise")
                }


    expected_json = '''{
    "int": 1,
    "float": 1.2,
    "string": "This is a string",
    "dict": {
        "key1": 1,
        "key2": 2
    },
    "list": [
        1,
        2,
        3
    ],
    "bool": true,
    "none": null,
    "datetime": {
        "_type_": "datetime",
        "_value_": "1234-05-06T07:08:09.000"
    },
    "date": {
        "_type_": "date",
        "_value_": "1234-05-06"
    },
    "time": {
        "_type_": "time",
        "_value_": "01:02:03.000"
    },
    "timedelta": {
        "_type_": "timedelta",
        "_value_": "P1DT02H03M04.005000S"
    },
    "Decimal": {
        "_type_": "Decimal",
        "_value_": "1.234567890123456789"
    },
    "UUID": "b63b02af-a3ea-481b-8dea-b82fcaaea9fa",
    "Promise": "This is a promise"
}'''

    def test_TypedDecoder(self):
        obj = loads(self.expected_json)
        self.assertEqual(obj, self.test_obj)

    def test_TypedEncoder(self):
        json = dumps(self.test_obj, indent=4)
        # TODO: Compare objects
        self.assertEqual(json, self.expected_json)


if __name__ == '__main__':
    unittest.main()