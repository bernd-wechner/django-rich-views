import datetime, json, decimal, uuid

from django.core.serializers.json import DjangoJSONEncoder

from django.utils.timezone import is_aware
from django.utils.duration import duration_iso_string
from django.utils.dateparse import parse_duration
from django.utils.functional import Promise

class TypedEncoder(json.JSONEncoder):
    '''
    A derivation of the DjangoJSONEncoder that attempts to efficently decode the types it encodes
    '''

    def default(self, o):
        '''
        A simple variant on django.core.serializers.json.DjangoJSONEncoder.

        A copy of it's code from:

        https://github.com/django/django/blob/8a844e761d098d4005725f991a5e120a1f17cb70/django/core/serializers/json.py#L77

        adding a type indicating wrapper to the types it encodes, to faciltate decoding back to Python.
        '''
        # See "Date Time String Format" in the ECMA-262 specification.
        typed = False
        if isinstance(o, datetime.datetime):
            r = o.isoformat()
            if o.microsecond:
                r = r[:23] + r[26:]
            if r.endswith("+00:00"):
                r = r.removesuffix("+00:00") + "Z"
            value = r
            typed = True
        elif isinstance(o, datetime.date):
            value = o.isoformat()
            typed = True
        elif isinstance(o, datetime.time):
            if is_aware(o):
                raise ValueError("JSON can't represent timezone-aware times.")
            r = o.isoformat()
            if o.microsecond:
                r = r[:12]
            value = r
            typed = True
        elif isinstance(o, datetime.timedelta):
            value = duration_iso_string(o)
            typed = True
        elif isinstance(o, (decimal.Decimal, uuid.UUID, Promise)):
            value = str(o)
            # Only type the Decimals (UUID and Promise can remain as strings)
            typed = isinstance(o, decimal.Decimal)
        else:
            value = super().default(o)

        return {'_type_': type(o).__name__, '_value_': value} if typed else value

class TypedDecoder(json.JSONDecoder):
    '''
    The decoder that django.core.serializers.json.DjangoJSONEncoder
    failed to implement. Using the type hints that the TypedEncoder
    (above) supplied.
    '''

    def __init__(self, *args, **kargs):
        super().__init__(object_hook=self.typed_decode, *args, **kargs)

    def typed_decode(self, d):
        '''
        json.JSONDecoder supplies a dict.

        :param d: A dict.
        '''
        assert isinstance(d, dict), f"object_hook received: {type(d)}"
        # Untyped dicts return untouched
        if '_type_' in d:
            data_type = d.pop('_type_')
            str_value = d.get('_value_', None)
            if str_value:
                if data_type == 'datetime':
                    v = datetime.datetime.fromisoformat(str_value)
                elif data_type == 'date':
                    v = datetime.date.fromisoformat(str_value)
                elif data_type == 'time':
                    v = datetime.time.fromisoformat(str_value)
                elif data_type == 'timedelta':
                    v = parse_duration(str_value)
                elif data_type == 'Decimal':
                    v = decimal.Decimal(str_value)
            else:
                v = d
            return v
        else:
            return d

def dumps(*args, **kwargs) -> str:
    '''Return json string from object'''
    kwargs['cls'] = TypedEncoder
    return json.dumps(*args, **kwargs)

def dump(*args, **kwargs):
    '''Export object to json file'''
    kwargs['cls'] = TypedEncoder
    json.dump(*args, **kwargs)

def loads(*args, **kwargs):
    '''Load json string and return python object'''
    kwargs['cls'] = TypedDecoder
    return json.loads(*args, **kwargs)

def load(*args, **kwargs):
    '''Load json file and return python object'''
    kwargs['cls'] = TypedDecoder
    return json.load(*args, **kwargs)


