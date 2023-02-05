'''
Django Rich Views

Filterset extensions

django-url-filter is a great package that parses GET parameters into Django filter arguments.

    http://django-url-filter.readthedocs.io/en/latest/

Alas it does not have a nice way to pretty print the filter for reporting it on views,
nor for extracting the filter options cleanly for reconstructing a URL or QuerySet.
'''
# Python imports
import urllib.parse
import datetime
import re

# Django imports
from django.utils.formats import localize
from django.utils.safestring import mark_safe
from django.http.request import QueryDict
from django.db.models.query_utils import DeferredAttribute

# Other imports
from url_filter.filtersets import ModelFilterSet
from url_filter.constants import StrictMode

operation_text = {
    "exact": " = ",
    "iexact": " = ",
    "contains": " contains ",
    "icontains": " contains ",
    "startswith": " starts with ",
    "istartswith": " starts with ",
    "endswith": " ends with ",
    "iendswith": " ends with ",
    "range": " is between ",
    "isnull": " is NULL ",
    "regex": " matches ",
    "iregex": " matches ",
    "in": " is in ",
    "gt": " > ",
    "gte": " >= ",
    "lt": " < ",
    "lte": " <= ",
    # Date modifiers, probably not relevant in filters? If so may need some special handling.
    #         "date" : "__date",
    #         "year" : "__year",
    #         "quarter" : "__quarter",
    #         "month" : "__month",
    #         "day" : "__day",
    #         "week" : "__week",
    #         "week_day" : "__weekday",
    #         "time" : "__time",
    #         "hour" : "__hour",
    #         "minute" : "__minute",
    #         "second" : "__second",
}


def fix(obj):
    '''
    There's a sad, known round trip problem with date_times in Python 3.6 and earlier.
    The str() value fo a datetime for timezone aware date_times produces a timezone
    format of ±[hh]:[mm] but the django DateTimeField when it validates inputs does not
    recognize this format (because it uses datetime.strptime() and this is a known round
    trip bug discussed for years here:

        https://bugs.python.org/issue15873

    fix() is like str() except for datetime objects only it removes that offending colon
    so the datetime can be parsed with a strptime format of '%Y-%m-%d %H:%M:%S%z' (which
    must be added to Django's DATETIME_INPUT_FORMATS of it's going to support round
    tripping on DateTimeFields.
    '''
    if isinstance(obj, datetime.datetime):
        return re.sub(r'(\+|\-)(\d\d):(\d\d)$', r'\1\2\3', str(obj))
    else:
        return str(obj)


def get_filterset(request, model):
    '''
    Returns a ModelFilterSet (from url_filter) that is built from
    the GET params and the session stored filter(s).

    In the session supports "filter" and "filter_priorities". The latter
    is just a dict supplying a of field names to try "filter" if "filter"
    is not a field on the model. This means for example you specify a generic
    name for a filter that is implemented on different models in different
    fields. The fields can be related too (so in a related model).

    Each entry in priorities is test in order to see if is_filter_field is
    True, and if so that is the field used. is_filter_field suppports
    related model fields (components seprated with "__")

    the model and request are taken from the view, unless overrriden, a
    mechanism making these tailored filtersets available more gnerally from
    places without a view object.

    :param request: The Django request that specifies (or not) a filter
    :param model: The model the filter applies to
    '''
    FilterSet = type("FilterSet", (ModelFilterSet,), {
        'Meta': type("Meta", (object,), {
            'model': model
        })
    })

    qs = model.objects.all()

    # Create a mutable QueryDict (default ones are not mutable)
    qd = QueryDict('', mutable=True)

    # Add the GET parameters unconditionally, a user request overrides a
    # session saved filter
    if hasattr(request, 'GET'):
        qd.update(request.GET)

    # Use the session stored filter as a fall back, it is expected
    # in session["filter"] as a dictionary of (pseudo) fields and
    # values. That is to say, they are  nominally fields in the model,
    # but don't need to be, as long as they are keys into
    # session["filter_priorities"] which defines prioritised lists of
    # fields for that key. We do that because the same thing (that a
    # pseudo field or key describes) may exist in different models in
    # different fields of different names. Commonly the case when
    # spanning relationships to get from this model to the pseudo field.
    #
    # To cut a fine example consider an Author model and a Book model,
    # in which the Author has name and each book has a name and a ForeignKey
    # related field author__name. We might have a psuedo field authors_name
    # as the key and a list of filter_priorities of [author__name, name]
    # And so if this model has author__name we use than and if not if it has
    # name we use that. Clearly this cannot cover all confusions and requires
    # careful model, field and filter design to support a clear naming
    # convention ...
    session = request.session
    if 'filter' in session:
        # the session filters we make a copy of as we may be modifying them
        # based on the filter_priorities, and don't want to modify
        # the session stored filters (our mods are only used for
        # selecting the model field to filter on based on stated
        # priorities).
        session_filters = session["filter"].copy()
        priorities = session.get("filter_priorities", {})

        # Now if priority lists are supplied we apply them keeping only the highest
        # priority field in any priority list in the list of priorities. The highest
        # priority one being the lowest index in the list that list which is a field
        # we can filter on.
        for f in session["filter"]:
            if f in priorities:
                p = priorities[f]

                # From the list of priorites, find the highest priority one that
                # is a field we could actually filter on
                filter_field = None
                for field in p:
                    if is_filter_field(model, field):
                        filter_field = field
                        break

                # If we found one or more fields in the priority list that are
                # filterable we must now have the highest priority one, we replace
                # the pseudo filter field with this field.
                if filter_field and not filter_field == f:
                    val = session_filters[f]
                    del session_filters[f]
                    session_filters[filter_field] = val

        # The GET filters were already added to qd, so before we add session filters
        # we throw out any that are already in there as we provide priority to
        # user specified filters in the GET params over the session defined
        # fall backs.
        F = session_filters.copy()
        for f in session_filters:
            if f in qd:
                del F[f]

        if F:
            qd.update(F)

    # TODO: test this with GET params and session filter!
    fs = FilterSet(data=qd, queryset=qs, strict_mode=StrictMode.fail)

    # get_specs raises an Empty exception if there are no specs, and a
    # ValidationError if a value is illegal
    try:
        specs = fs.get_specs()
    except Exception as E:
        specs = []

    if len(specs) > 0:
        fs.fields = format_filterset(fs)
        fs.text = format_filterset(fs, as_text=True)
        return fs
    else:
        return None


def get_field(model, components, component=0):
    '''
    Gets a field given the components of a filterset sepcification.

    :param model:      The model in which the identified component is expected to be a field
    :param components: A list of components
    :param component:  An index into that list identifying the component to consider
    '''

    def model_field(model, field_name):
        for field in model._meta.fields:
            if field.attname == field_name:
                return field
        return None

    field_name = components[component]
    field = getattr(model, field_name, None)

    # To Many fields
    if hasattr(field, "rel"):
        if component + 1 < len(components):
            if field.rel.many_to_many:
                field = get_field(field.field.related_model,
                                  components, component + 1)
            elif field.rel.one_to_many:
                field = get_field(field.field.model, components, component + 1)

    # To One fields
    elif hasattr(field, "field"):
        if component + 1 < len(components):
            field = get_field(field.field.related_model,
                              components, component + 1)

    # local model field
    else:
        field = model_field(model, field_name)

    return field


def is_filter_field(model, field):
    # For now just splitting for components. This does not in fact generalise if
    # the filter has an operation at its end, like __gt or such. I've steppped into
    # the filterset code to see how it builds components, but it's a slow job and I
    # bailed for now.
    #
    # TODO: work out how filtersets build components as we should really see there
    # how it both ignores the operation at end of the name, and also seems to take one
    # step further to the id field in relations.
    #
    # For now this serves purposes finely as we aren't using it on any filters
    # with operations (yet) and the last tier trace to id is not important to
    # establishing if it's a valid field to filter on.
    components = field.split("__")
    filter_field = get_field(model, components)
    return not filter_field is None


def format_filterset(filterset, as_text=False):
    '''
    Returns a list of filter criteria that can be used in a URL construction
    or if as_text is True a pretty formatted string version of same.

    :param filterset:   A filterset as produced by url_filter
    :param as_text:     Returns a list if False, or a formatted string if True
    '''
    result = []

    try:
        # get_specs raises an Empty exception if there are no specs, and a
        # ValidationError if a value is illegal
        specs = filterset.get_specs()

        for spec in specs:
            field = get_field(filterset.queryset.model, spec.components)
            field_name = None

            if len(spec.components) > 1 and spec.lookup == "exact":
                # The field may be deferred in which case it's attributes
                # accessible as field.field
                if isinstance(field, DeferredAttribute):
                    field = field.field

                if field.model:
                    Os = field.model.objects.filter(
                        **{f"{field.attname}__{spec.lookup}": spec.value})
                    O = Os[0] if Os.count() > 0 else None

                    if as_text:
                        if field.primary_key:
                            field_name = field.model._meta.object_name
                            field_value = str(O)
                        else:
                            field_name = "{} {}".format(
                                field.model._meta.object_name, spec.components[-1])
                            field_value = spec.value
                    else:
                        if field.primary_key:
                            field_name = "__".join(spec.components[:-1])
                            field_value = O.pk
                        else:
                            field_name = "__".join(spec.components)
                            field_value = spec.value

            if field_name is None:
                if as_text:
                    field_name = field.verbose_name
                else:
                    field_name = "__".join(spec.components)

                # DateTimeFields are a tad special.
                # In as_text mode, localize them. In normal mode fix the str representation.
                # One for convenience and nicety, the other to get around a round-trip bug
                # in Python 3.6 and earlier!
                field_value = (localize(spec.value) if isinstance(spec.value, datetime.datetime) else str(
                    spec.value)) if as_text else urllib.parse.quote_plus(fix(spec.value))

            if as_text and spec.lookup in operation_text:
                op = operation_text[spec.lookup]
            elif spec.lookup != "exact":
                op = "__{}=".format(spec.lookup)
            else:
                op = "="

            result += ["{}{}{}".format(field_name, op, field_value)]

        if as_text:
            result = mark_safe(" <b>and</b> ".join(result))

        return result
    except Exception as E:
        return "" if as_text else []
