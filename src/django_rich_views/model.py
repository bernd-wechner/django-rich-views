'''
Django Rich Views

Model Extensions

One aim with these Extensions is to help concentrate model specific configurations in the model declaration.

Of particular note, we add support for a number of attributes that can be used in models to achieve certain outcomes.

intrinsic_relations, is a way of listing relations without which this model makes no sense.

    for example: if you have a models Team and Member, the Team model may have:
        intrinsic_relations = 'members'
    assuming Team has a ManyToMany relationship with Member and an attribute "members".

    This would request of the RichCreateView and RichUpdateView that they provide enough form
    context to easily build rich forms (say a Team form, with a list of Member forms under it).

    Similarly the RichDetailView wants a rich object in its context, to display, as defined by
    the network of intrinsic_relations.

sort_by, is like the Django Meta option "ordering" only it can include properties of the model as well, and is honoured by RichListView

link_internal and link_external, are two attributes (or properties) that can supply a URL (internal or external respectively)

    By internal we mean a link to the DetailView of the object (model instance) that supplies the link_internal.

    By external we mean a link to some other site if desired. For example you may have a model Person, and the
    external link may point to their profile on Facebook or LinkedIn or wherever. We support only one external
    link conveniently for now.

inherit_fields, which is a string that names

    1) a field in this model, or
    2) a field in another model in the format model.field

    or a list of such strings, then we take this as an instruction to inherit
    the values of those fields form form to form during one login session.

    This is useful when eterig a strig fo similar objects. Each successive instance of the RichCreateForm
    will seek to initialise the fields of a new one using the rules suppled here.

__verbose_str_,
__rich_str__,
__detail_str__,    are properties like __str__ that permit a model to supply different degrees of detail.

    This is intended to support the .options and levels of detail in the RichListView, RichDetailView and RichDeleteView.

    A convention is assumed in which:

    __str__             references only model fields (should be fast to provide), contain no HTML and ideally no
                        newlines (if possible).

    __verbose_str__     can reference related model fields (can be a little slower), contain no HTML and ideally
                        no newlines (if possible)

    __rich_str__        like __verbose_str__, but can contain internal HTML markup for a richer presentation.
                        Should have a signature of:
                            def __rich_str__(self,  link=None):
                        and should call on field_render herein passing that link in.

    __detail_str__      like __richs_str__, but can span multiple lines.
                        Should have a signature of:
                            def __detail_str__(self,  link=None):
                        and should call on field_render herein passing that link in.

TODO: Add __table_str__ which returns a TR, and if an arg is specified or if it's a class method perhaps a header TR
'''
# Python imports
import html
import collections
import inspect

# Django imports
from django.db import models
from django.db.models.options import Options
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.functional import cached_property
from django.utils.timezone import get_current_timezone
from django.forms.models import inlineformset_factory
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings

# Django related imports
from markdownfield.models import MarkdownField, RenderedMarkdownField
from markdownfield.validators import VALIDATOR_STANDARD

# Package imports
from . import FIELD_LINK_CLASS, NONE, NOT_SPECIFIED
from .logs import logger as log
from .util import isListType, isListValue, isDictionary, safetitle
from .datetime import time_str
from .options import default, flt, osf, odf
from .decorators import is_property_method
from .html import odm_str

summary_methods = ["__str__", "__verbose_str__",
                   "__rich_str__", "__detail_str__"]


def safe_get(model, pk):
    try:
        return model.objects.get(pk=pk)
    except ObjectDoesNotExist:
        return None


def intrinsic_relations(model):
    '''
    Provides a safe way of testing a given model's intrinsic_relations attribute by ensuring always
    a list is provided.

    If a model has an attribute named intrinsic_relations and it is a string that names

    1) a field in this model, or
    2) a field in another model in the format model.field

    or a list of such strings, then we take this as an instruction to include that
    those fields should be included in forms for the model.

    The attribute may be missing, None, or invalid as well, and so to make testing
    easier throughout the generic form processors this function always returns a list,
    empty if no valid intrinsic_relations is found.
    '''

    if not hasattr(model, "intrinsic_relations"):
        return []

    if isinstance(model.intrinsic_relations, str):
        return [model.intrinsic_relations]

    if isinstance(model.intrinsic_relations, list):
        return model.intrinsic_relations

    return []


def can_save_related_formsets(model, related_model):
    '''
    For related forms to be saved they must have a foreign key back
    to the parent form's model. It's impossible to save the related formset
    without a way to relate the forms in the formset back to a specific
    parent object.

    Specifying such a relation in intrinsic_relations can provide model forms
    but they cannot be saved as formsets. it's a good idea to flag a
    warning to the model designer in that case, and to avoid crashing
    when trying to save the a formset.

    This is a consistent way code using intrinsic_relations, to check if a
    field specified thusly can be saved as a formset.

    :param model: A Django model
    :param related_model: A Django model that has a relation to the first one.
    '''
    try:
        # The most reliable way to test this simply to try and build an inline_formset.
        # This searches for a foreign key as needed and there's no convenient way to do
        # that in Django that's better. As at Django 3, first thing it does is call a
        # private function (_get_foreign_key()) to do this test andit's a little involved.
        #
        # It fails with an exception if no ForeignKey is found and we simply loook for that
        # before exception
        inlineformset_factory(model, related_model, fields=('__all__'))
        return True
    except ValueError:
        return False


def is_intrinsic_relation(model, field):
    '''
    Return true if the supplied field is a relation and in the
    intrinsic_relations property of the model the field belongs to.

    Defines the syntax that the intrinsic_relations property supports,
    which is basically the field name itself, a field of a field.

    :param model: A Django model
    :param field: A field in model
    '''
    if field.is_relation:
        if field.name in intrinsic_relations(model):
            if not can_save_related_formsets(model, field.remote_field.model):
                m = model._meta.object_name
                rm = field.remote_field.model._meta.object_name
                if settings.WARNINGS:
                    log.warning(
                        f"Warning: A {rm} model form is provided for {m}.{field.name} BUT formsets of {rm} for {m}.{field.name} cannot be saved (because {rm} has no ForeignKey back to {m} - which is a prerequisite for Django Formsets).")
            return True
        # FIXME (ASAP): double check this and what it's about
        # Check my models for . syntax add related and try the form
        elif hasattr(field, "field"):
            field_name = field.field.model.__name__ + "." + field.field.name
            if field_name in intrinsic_relations(model):
                return True
            else:
                return False
        else:
            return False
    else:
        return False


def inherit_fields(model):
    '''
    Provides a safe way of testing a given model's inherit_fields attribute by ensuring always
    a list is provided.

    If a model has an attribute named inherit_fields and it is a string that names

    1) a field in this model, or
    2) a field in another model in the format model.field

    or a list of such strings, then we take this as an instruction to inherit
    the values of those fields form form to form during one login session.

    The attribute may be missing, None, or invalid as well, and so to make testing
    easier throughout the generic form processors this function always returns a list,
    empty if no valid intrinsic_relations is found.
    '''

    if not hasattr(model, "inherit_fields"):
        return []

    if isinstance(model.inherit_fields, str):
        return [model.inherit_fields]

    if isinstance(model.inherit_fields, list):
        return model.inherit_fields

    return []


def apply_sort_by(queryset):
    '''
    Sorts a query set by the the fields and properties listed in a sort_by attribute if it's specified.
    This augments the meta option order_by in models because that option cannot respect properties.
    This option though wants a sortable property to be specified and that isn't an object, has to be
    like an int or string or something, specifically a field in the object that is sortable. So usage
    is a tad different to order_by.
    '''
    model = queryset.model
    if hasattr(model, 'sort_by'):
        try:
            sort_lambda = "lambda obj: (obj." + \
                ", obj.".join(model.sort_by) + ")"
            return sorted(queryset, key=eval(sort_lambda))
        except Exception:
            return queryset
    else:
        return queryset


def link_target_url(obj, link_target=None):
    '''
    Given an object returns the url linking to that object as defined in the model methods.
    :param obj:            an object, being an instance of a Django model which has link methods
    :param link_target:    a field_link_target that selects which link method to use
    '''
    url = ""

    if link_target is None:
        link_target = default(flt)

    if link_target == flt.internal and hasattr(obj, "link_internal"):
        url = obj.link_internal
    elif link_target == flt.external and hasattr(obj, "link_external"):
        url = obj.link_external

    return url


def field_render(field, link_target=None, sum_format=None):
    '''
    Given a field attempts to render it as text to use in a view. Tries to do two things:

    1) Wrap it in an HTML Anchor tag if requested to. Choosing the appropriate URL to use as specified by link_target.
    2) Convert the field to text using a method selected by sum_format.

    :param field: The contents of a field that we want to wrap in a link. This could be a text scalar value
    or an object. If it's a scalar value we do no wrapping and just return it unchanged. If it's an object
    we check and honor the specified link_target and sum_format as best possible.

    :param link_target: a field_link_target which tells us what to link to.
    The object must provide properties that return a URL for this purpose.

    :param sum_format: an object_summary_format which tells us which string representation to use. The
    object should provide methods that return a string for each possible format, if not, there's a
    fall back trickle down to the basic str() function.

    detail and rich summaries are expected to contain HTML code including links so they need to know the link_target
    and cannot be wrapped in an Anchor tag and must be marked safe

    verbose and brief summaries are expected to be free of HTML so can be wrapped in an Anchor tag and don't
    need to be marked safe.
    '''
    if link_target is None:
        link_target = default(flt)

    if sum_format is None:
        sum_format = default(osf)

    tgt = None

    if link_target == flt.mailto:
        tgt = f"mailto:{field}"
    elif isinstance(link_target, str) and link_target:
        tgt = link_target
    elif link_target == flt.internal and hasattr(field, "link_internal"):
        tgt = field.link_internal
    elif link_target == flt.external and hasattr(field, "link_external"):
        tgt = field.link_external

    fmt = sum_format
    txt = None
    if fmt == osf.detail:
        if callable(getattr(field, '__detail_str__', None)):
            tgt = None
            txt = field.__detail_str__(link_target)
        else:
            fmt = osf.rich

    if fmt == osf.rich:
        if callable(getattr(field, '__rich_str__', None)):
            tgt = None
            txt = field.__rich_str__(link_target)
        else:
            fmt = osf.verbose

    if fmt == osf.verbose:
        if callable(getattr(field, '__verbose_str__', None)):
            txt = html.escape(field.__verbose_str__())
        else:
            fmt = osf.brief

    if fmt == osf.brief:
        if callable(getattr(field, '__str__', None)):
            txt = html.escape(field.__str__())
        else:
            if isinstance(field, models.DateTimeField):
                txt = time_str(field)
            else:
                txt = str(field)

    if fmt == osf.template:
        if hasattr(field, 'pk'):
            txt = f"{{{field._meta.model.__name__}.{field.pk}}}"
        else:
            txt = "{field_value}"
            raise ValueError(
                "Internal error, template format not supported for field.")

    if link_target == flt.template:
        tgt = f"{{link.{FIELD_LINK_CLASS}.{field._meta.model.__name__}.{field.pk}}}"
        # Provides enough info for a template to build the link below.
        return mark_safe(f"{tgt}{txt}{{link_end}}")
    elif tgt is None:
        return mark_safe(txt)
    else:
        return mark_safe(f'<A href="{tgt}" class="{FIELD_LINK_CLASS}">{txt}</A>')


def object_in_list_format(obj, context):
    '''
    For use in a template tag which can simply pass the object (from the context item object_list)
    and context here and this will produce a string (marked safe as needed) for rendering respecting
    the requests that came in via the context.
    :param obj:        an object, probably from the object_list in a context provided to a list view template
    :param context:    the context provided to the view (from which we can extract the formatting requests)
    '''
    # we expect an instance list_display_format in the context element "format"
    fmt = context['format'].elements
    flt = context['format'].link

    return field_render(obj, flt, fmt)


def collect_rich_object_fields(view):
    '''
    Passed a view instance (a detail view or delete view is expected, but any view could call this)
    which has an object already (view.obj) (so after or in get_object), will define view.fields with
    a dictionary of fields that a renderer can walk through later.

    Additionally view.fields_bucketed (is a copy of view.fields in the buckets specified in
    object_display_format by object_display_flags) and view.fields_flat and view.fields_list
    also contain all the view.fields split into the scalar (flat) values and the list values
    respectively (which are ToMany relations to other models).

    Expects ManyToMany relationships to be set up bi-directionally, in both involved models,
    i.e. makes no special effort to find the reverse relationships and if they are not set up
    bi-directionally may miss the indirect, or reverse relationship).

    Converts foreign keys to the string representation of that related object using the level of
    detail specified view.format and respecting privacy settings where applicable (values are
    obtained through odm_str where privacy constraints are checked.
    '''
    # Build the list of fields
    # fields_for_model includes ForeignKey and ManyToMany fields in the model
    # definition

    # Fields are categorized as follows for convenience and layout and performance decisions
    #    flat or list
    #    model, internal, related or properties
    #
    # By default we will populate view.fields only with flat model fields.

    def is_list(field):
        return hasattr(field, 'is_relation') and field.is_relation and (field.one_to_many or field.many_to_many)

    def is_property(name):
        return isinstance(getattr(view.model, name), (property, cached_property))

    def is_cached(name):
        return isinstance(getattr(view.model, name), cached_property)

    def is_bitfield(field):
        return type(field).__name__ == "BitField"

    def is_locationfield(field):
        return type(field).__name__ == "LocationField"

    def is_renderedmarkdown(field):
        return type(field).__name__ == "RenderedMarkdownField"

    if settings.DEBUG:
        log.debug(f"Collecting Rich Object: {view.obj}")

    ODF = view.format.flags

    all_fields = view.obj._meta.get_fields()  # All fields

    # respect any ordering requested by model.field_order:
    if hasattr(view.model, "field_order"):
        field_order = view.model.field_order
        all_field_names = [f.name for f in all_fields]
        all_fields_ordered = []
        for f in field_order:
            if f in all_field_names:
                all_fields_ordered.append(f)
                all_field_names.pop(all_field_names.index(f))
        # Add any fields no mentioned in field_order
        for f in all_field_names:
            all_fields_ordered.append(f)
        # Now rebuild all_fields
        all_fields_dict = {f.name: f for f in all_fields}
        all_fields = [all_fields_dict[f] for f in all_fields_ordered]

    model_fields = collections.OrderedDict()  # Editable fields in the model
    internal_fields = collections.OrderedDict()  # Non-editable fields in the model
    # Fields in other models related to this one
    related_fields = collections.OrderedDict()

    # Categorize all fields into one of the three buckets above (model,
    # internal, related)
    for field in all_fields:
        if (is_list(field) and ODF & odf.list) or (not is_list(field) and ODF & odf.flat):
            if field.is_relation:
                if ODF & odf.related:
                    related_fields[field.name] = field
            else:
                if ODF & odf.model and field.editable and not field.auto_created:
                    model_fields[field.name] = field
                elif ODF & odf.internal:
                    internal_fields[field.name] = field

    # List properties, but respect the format request (list and flat selectors)
    properties = []
    if ODF & odf.properties:
        for name in dir(view.model):
            if is_property(name):
                # Function annotations appear in Python 3.6. In 3.5 and earlier they aren't present.
                # Use the annotations provided on model properties to classify properties and include
                # them based on the classification. The classification is for list and flat respecting
                # the object_display_flags selected. That is all we need here.
                prop = getattr(view.model, name)
                func = prop.real_func if is_cached(name) else prop.fget
                annotations = getattr(func, "__annotations", {})

                if "return" in annotations:
                    return_type = annotations["return"]
                    if (isListType(return_type) and ODF & odf.list) or (not isListType(return_type) and ODF & odf.flat):
                        properties.append(name)
                else:
                    properties.append(name)

    # List properties_methods, but respect the format request (list and flat selectors)
    # Look for property_methods (those decorated with property_method and
    # having defaults for all parameters)
    property_methods = []
    if ODF & odf.methods:
        for method in inspect.getmembers(view.obj, predicate=is_property_method):
            name = method[0]
            if hasattr(getattr(view.model, name), "__annotations__"):
                annotations = getattr(view.model, name).__annotations__
                if "return" in annotations:
                    return_type = annotations["return"]
                    if (isListType(return_type) and ODF & odf.list) or (not isListType(return_type) and ODF & odf.flat):
                        property_methods.append(name)
                else:
                    property_methods.append(name)

    # List summaries (these are always flat)
    summaries = []
    if ODF & odf.summaries:
        for summary in summary_methods:
            if hasattr(view.model, summary) and callable(getattr(view.model, summary)):
                summaries.append(summary)

    # Define some (empty) buckets for all the fields so we can group them on
    # display (by model, internal, related, property, scalars and lists)
    if ODF & odf.flat:
        view.fields_flat = {}  # Fields that have scalar values
        view.all_fields_flat = collections.OrderedDict()
        if ODF & odf.model:
            view.fields_flat[odf.model] = collections.OrderedDict()
        if ODF & odf.internal:
            view.fields_flat[odf.internal] = collections.OrderedDict()
        if ODF & odf.related:
            view.fields_flat[odf.related] = collections.OrderedDict()
        if ODF & odf.properties:
            view.fields_flat[odf.properties] = collections.OrderedDict()
        if ODF & odf.methods:
            view.fields_flat[odf.methods] = collections.OrderedDict()
        if ODF & odf.summaries:
            view.fields_flat[odf.summaries] = collections.OrderedDict()

    if ODF & odf.list:
        # Fields that are list items (have multiple values)
        view.fields_list = {}
        view.all_fields_list = collections.OrderedDict()
        if ODF & odf.model:
            view.fields_list[odf.model] = collections.OrderedDict()
        if ODF & odf.internal:
            view.fields_list[odf.internal] = collections.OrderedDict()
        if ODF & odf.related:
            view.fields_list[odf.related] = collections.OrderedDict()
        if ODF & odf.properties:
            view.fields_list[odf.properties] = collections.OrderedDict()
        if ODF & odf.methods:
            view.fields_list[odf.methods] = collections.OrderedDict()
        if ODF & odf.summaries:
            view.fields_list[odf.summaries] = collections.OrderedDict()

    # For all fields we've collected set the value and label properly
    # Problem is that relationship fields are by default listed by primary keys (pk)
    # and we want to fetch the actual string representation of that reference an save
    # that not the pk. The question is which string (see object_list_format() for the
    # types of string we support).
    for field in all_fields:
        # All fields in other models that point to this one should have an
        # is_relation flag

        # These are the field types we can expect:
        #    flat
        #        simple:            a simple database field in this model
        #        many_to_one:       this is a ForeignKey field pointing to another model
        #        one_to_one:        this is a OneToOneField
        #    list:
        #        many_to_many:      this is a ManyToManyField, so this object could be pointing at many making a list of items
        #        one_to_many        this is an _set field (i.e. has a ForeignKey in another model pointing to this model and this field is the RelatedManager)
        #
        # We want to build a fields dictionaries here with field values
        # There are two types of field_value we'd like to report in the result:
        #    flat values:    fields_flat contains these
        #                            if the field is scalar, just its value
        #                            if the field is a relation (a foreign object) its string representation
        #    list values:    fields_list contains these
        #                            if the field is a relation to many objects, a list of their string representations
        #
        # We also build fields_model and fields_other

        if settings.DEBUG:
            log.debug(f"Collecting Rich Object Field: {field.name}")

        bucket = (odf.model if field.name in model_fields
                  else odf.internal if field.name in internal_fields
                  else odf.related if field.name in related_fields
                  else None)

        if not bucket is None:
            #######################################################################
            # We preapre each field by giving it the following attribues expected
            # downstream in this package:
            #
            #     field.label
            #     field.label
            #     field.is_list
            #
            # And placing it into one of the appropriate buckets of
            #
            #    view.fields_flat, or
            #    view.fields_list
            #
            # We handle the rendering of field.value here based on the field
            # type and field.value can be a scalar (flat) or a list.
            field.label = safetitle(field)

            if is_bitfield(field):
                if ODF & odf.flat:
                    field.is_list = False
                    flags = []
                    for f in field.flags:
                        bit = getattr(getattr(view.obj, field.name), f)
                        if bit.is_set:
                            flags.append(
                                getattr(view.obj, field.name).get_label(f))

                    if len(flags) > 0:
                        field.value = odm_str(", ".join(flags), view.format.mode)
                    else:
                        field.value = NONE

                    view.fields_flat[bucket][field.name] = field
            elif is_locationfield(field):
                field.is_list = False
                value = getattr(view.obj, field.name)
                prefix = f"Within {value[2]}m of " if len(value) > 2 else ""
                field.value = f"{prefix}Latitude: {value[1]}, Longitude: {value[0]}"
                view.fields_flat[bucket][field.name] = field
            elif is_renderedmarkdown(field):
                # This is a block not flat or a list ...
                # TODO: consider best rendering
                field.is_list = False
                field.value = mark_safe(getattr(view.obj, field.name))
                view.fields_flat[bucket][field.name] = field
            elif is_list(field):
                if ODF & odf.list:
                    field.is_list = True

                    # If it's a model field it has an attname attribute, else
                    # it's a _set atttribute
                    attname = field.name if hasattr(field, 'attname') else field.name + '_set' if field.related_name is None else field.related_name

                    #field.label = safetitle(attname.replace('_', ' '))

                    ros = apply_sort_by(getattr(view.obj, attname).all())

                    if len(ros) > 0:
                        field.value = [odm_str(item, view.format.mode)
                                       for item in ros]
                    else:
                        field.value = NONE

                    view.fields_list[bucket][field.name] = field
            else:
                if ODF & odf.flat:
                    field.is_list = False
                    try:
                        field.value = odm_str(getattr(view.obj, field.name), view.format.mode)
                    except ObjectDoesNotExist:
                        field.value = None

                    if not str(field.value):
                        field.value = NOT_SPECIFIED

                    view.fields_flat[bucket][field.name] = field

    # Capture all the property, property_method and summary values as needed
    # (these are not fields)
    if ODF & odf.properties or ODF & odf.methods or ODF & odf.summaries:
        names = []
        if ODF & odf.properties:
            names += properties
        if ODF & odf.methods:
            names += property_methods
        if ODF & odf.summaries:
            names += summaries

        for name in names:
            if settings.DEBUG:
                log.debug(f"Collecting Rich Object Property: {name}")

            label = safetitle(name.replace('_', ' '))

            # property_methods and summaries are functions, and properties are attributes
            # so we have to fetch their values appropriately
            if name in property_methods:
                value = getattr(view.obj, name)()
                bucket = odf.methods
            elif name in summaries:
                value = getattr(view.obj, name)()
                bucket = odf.summaries
            else:
                value = getattr(view.obj, name)
                bucket = odf.properties

            if not str(value):
                value = NOT_SPECIFIED

            p = models.Field()
            p.label = label

            if isListValue(value):
                if ODF & odf.list:
                    p.is_list = True

                    if len(value) == 0:
                        p.value = NONE
                    elif isDictionary(value):
                        # Value becomes Key: Value
                        p.value = [f"{odm_str(k, view.format.mode)}: {odm_str(v, view.format.mode)}" for k, v in dict.items(value)]
                    else:
                        p.value = [odm_str(val, view.format.mode)
                                   for val in list(value)]
                    view.fields_list[bucket][name] = p
            else:
                if ODF & odf.flat:
                    p.is_list = False
                    p.value = odm_str(value, view.format.mode, True)
                    view.fields_flat[bucket][name] = p

    # Some more buckets to put the fields in so we can separate lists of
    # fields on display
    view.fields = collections.OrderedDict()  # All fields
    view.fields_bucketed = collections.OrderedDict()

    buckets = []
    if ODF & odf.summaries:  # Put Summaries at top if they are requested
        view.fields_bucketed[odf.summaries] = collections.OrderedDict()
        buckets += [odf.summaries]
    if ODF & odf.model:
        view.fields_bucketed[odf.model] = collections.OrderedDict()
        buckets += [odf.model]
    if ODF & odf.internal:
        view.fields_bucketed[odf.internal] = collections.OrderedDict()
        buckets += [odf.internal]
    if ODF & odf.related:
        view.fields_bucketed[odf.related] = collections.OrderedDict()
        buckets += [odf.related]
    if ODF & odf.properties:
        view.fields_bucketed[odf.properties] = collections.OrderedDict()
        buckets += [odf.properties]
    if ODF & odf.methods:
        view.fields_bucketed[odf.methods] = collections.OrderedDict()
        buckets += [odf.methods]

    for bucket in buckets:
        passes = []
        if ODF & odf.flat:
            passes += [True]
        if ODF & odf.list:
            passes += [False]
        for Pass in passes:
            field_list = view.fields_flat[bucket] if Pass else view.fields_list[bucket]
            for name, value in field_list.items():
                view.fields_bucketed[bucket][name] = value
                view.fields[name] = value

    if settings.DEBUG:
        log.debug(f"DONE Collecting Rich Object: {view.obj}")


class RichMixIn():
    '''
    A general mixin for Django Rich Views model support
    '''

    @cached_property
    def link_internal(self) -> str:
        return reverse('view', kwargs={"model": self._meta.model.__name__, "pk": self.pk})

class TimeZoneMixIn():
    '''
    An abstract model that ensures timezone data is saved with all DateTimeField's that have
    a CharField of same name with _tz appended by placing the currentlya ctive Django timezone
    name into that field.
    '''

    def update_timezone_fields(self):
        '''
        Update the timezone fields that accompany any DateTimeFields
        '''

        for field in self._meta.concrete_fields:
            if isinstance(field, models.DateTimeField):
                tzfieldname = f"{field.name}_tz"
                if hasattr(self, tzfieldname):
                    setattr(self, tzfieldname, str(get_current_timezone()))

    def save(self, *args, **kwargs):
        self.update_timezone_fields()
        super().save(*args, **kwargs)


class NotesMixIn(models.Model):
    '''
    An abstract model that ensures a Markdown notes field is added to the model. Uses:

    https://pypi.org/project/django-markdownfield/

    and centralises that here for DRY reasons.
    '''
    notes = MarkdownField(rendered_field='notes_rendered', validator=VALIDATOR_STANDARD, blank=True, null=True, default="")
    notes_rendered = RenderedMarkdownField(null=True)

    __notes_mixin_marker__ = True

    # This produces perfect field_order ... but field_rder seems unrespected on model :-(
    def __new__(cls, *args, **kwargs):
        mixin_fields = []
        for base in cls.__bases__:
            if hasattr(base, '__notes_mixin_marker__'):
                mixin_fields += base._meta.fields
        mixin_field_names = [f.name for f in mixin_fields]

        model_fields = [f for f in cls._meta.get_fields() if f.name not in mixin_field_names]
        field_order = []
        for f in model_fields:
            field_order.append(f.name)
        field_order += [f.name for f in mixin_fields]

        if hasattr(cls, 'field_order'):
            existing_fields = list(cls.field_order)
            existing_field_names = set(existing_fields)
            for f in field_order:
                if f not in existing_field_names:
                    existing_fields.append(f)
            cls.field_order = tuple(existing_fields)
        else:
            cls.field_order = tuple(field_order)

        return super().__new__(cls)

    class Meta:
        abstract = True
