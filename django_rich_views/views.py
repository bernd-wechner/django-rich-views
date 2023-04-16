'''
Django Rich Views

The Views themselves

Provides:

    RichListView
    RichDetailView
    RichDeleteView
    RichCreateView
    RichUpdateView

which all derive from the class of the same name less Extended (i.e. the standard Djago Generic Views).

These Extensions aim at providing primarily two things:

1) Support for rich objects (objects which make sense only as a collection of model instances).
2) Generic detail and list in the same ilk as Djangos Generic Form view, providing easy HTML for rapid easy generic rendering.

In the process it also supports Field Privacy and Admin fields though these were spun out as independent packages.
'''
# Python imports
import os
import datetime

# Django imports
from django.views.generic import TemplateView, ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib.auth.views import LoginView

from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.db import transaction
# from django.db.models.query import QuerySet
from django.db.utils import IntegrityError, ProgrammingError
from django.db.models import Q
from django.db.models.aggregates import Count
from django.http import Http404
from django.http.response import HttpResponse, HttpResponseRedirect  # , JsonResponse
from django.template.response import TemplateResponse
#from django.http.request import QueryDict
from django.forms.models import fields_for_model, ModelChoiceField, ModelMultipleChoiceField
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
#from django.contrib.gis.geos import Point

# 3rd Party package imports (dependencies)
#from url_filter.filtersets import ModelFilterSet
#from url_filter.constants import StrictMode
from dal import autocomplete, forward
from markdownfield.forms import MarkdownFormField
from markdownfield.widgets import MDEWidget
from mapbox_location_field.forms import LocationField
from mapbox_location_field.widgets import MapInput

# Package imports
from .logs import logger as log
from .forms import classify_widgets
from .util import app_from_object, class_from_string, is_to_many
from .html import list_html_output, object_html_output, object_as_html, object_as_table, object_as_ul, object_as_p, object_as_br
from .context import add_rich_context, add_model_context, add_timezone_context, add_format_context, add_filter_context, add_ordering_context, add_debug_context
from .options import get_list_display_format, get_object_display_format
from .neighbours import get_neighbour_pks
from .model import collect_rich_object_fields, inherit_fields, intrinsic_relations
from .related_forms import RelatedForms
from .filterset import get_filterset, format_filterset, is_filter_field

if settings.DEBUG:
    import sys
    import traceback

# import sys, os
# print(f'DEBUG: current trace function in {os.getpid()}', sys.gettrace())
# # import pydevd;
# # pydevd.settrace()
# def trace_func(frame, event, arg):
#     with open(f"pydev-trace-{os.getpid()}.txt", 'a') as f:
#         print('Context: ', frame.f_code.co_name, '\tFile:', frame.f_code.co_filename, '\tLine:', frame.f_lineno, '\tEvent:', event, file=f)
#     return trace_func
#
# sys.settrace(trace_func)
# print(f'DEBUG: current trace function in {os.getpid()}', sys.gettrace())


def get_ordering(self):
    if (self.format.ordering):
        return self.format.ordering.split(',')
    else:
        return getattr(self.model._meta, 'ordering', None)


def dispatch_generic(self, request, *args, **kwargs):
    '''
    Adds attributes to the view describing the app and model a
    and provides a pre_dispatch hook for setting view properties
    in derived classes.

    :param self: and instance of CreateView, UpdateView, ListView, DetailView, DeleteView, LoginView or TemplateView
    '''
    if isinstance(self, (CreateView, UpdateView, ListView, DetailView, DeleteView)):
        self.app = app_from_object(self)
        # The model can be supplied as a kwarg (when passed in as a URL aprameter) or as an attribute
        # if passed in as an arg to as_view(). This porvides two clean ways to supply a model to the
        # rich view. If passed as an arg to as_view() it will already exist as
        # self.model!
        if not 'model' in self.kwargs and hasattr(self, 'model'):
            self.kwargs['model'] = self.model
        self.model = class_from_string(self, self.kwargs['model'])

        if not self.model:
            raise Http404("Invalid model name specified.")

        if isinstance(self, (CreateView, UpdateView)):
            if not hasattr(self, 'fields') or self.fields == None:
                self.fields = '__all__'

        if callable(getattr(self, 'pre_dispatch', None)):
            self.pre_dispatch()

        if isinstance(self, CreateView):
            return super(CreateView, self).dispatch(request, *args, **kwargs)
        elif isinstance(self, UpdateView):
            return super(UpdateView, self).dispatch(request, *args, **kwargs)
        elif isinstance(self, ListView):
            return super(ListView, self).dispatch(request, *args, **kwargs)
        elif isinstance(self, DetailView):
            return super(DetailView, self).dispatch(request, *args, **kwargs)
        elif isinstance(self, DeleteView):
            return super(DeleteView, self).dispatch(request, *args, **kwargs)

    elif isinstance(self, (LoginView, TemplateView)):
        if callable(getattr(self, 'pre_dispatch', None)):
            self.pre_dispatch()

        if isinstance(self, LoginView):
            return super(LoginView, self).dispatch(request, *args, **kwargs)
        elif isinstance(self, TemplateView):
            return super(TemplateView, self).dispatch(request, *args, **kwargs)
    else:
        raise NotImplementedError(
            "Generic dispatch only for use by CreateView, UpdateView, ListView, DetailView, DeleteView, LoginView and TemplateView and derivatives.")


def get_context_data_generic_for_forms(self, *args, **kwargs):
    '''
    Augments the standard context with model and related model information
    so that the template in well informed - and can do JavaScript wizardry
    based on this information

    :param self: and instance of CreateView or UpdateView

    This is code shared by the two views so peeled out into a generic.
    '''
    if settings.DEBUG:
        log.debug("Preparing context data.")

    if isinstance(self, CreateView):
        # Note that the super.get_context_data initialises the form with
        # get_initial
        context = super(CreateView, self).get_context_data(*args, **kwargs)
        title = 'New'
    elif isinstance(self, UpdateView):
        # Note that the super.get_context_data initialises the form with
        # get_object
        context = super(UpdateView, self).get_context_data(*args, **kwargs)
        title = 'Edit'
    else:
        raise NotImplementedError(
            "Generic get_context_data only for use by CreateView or UpdateView derivatives.")

    # Now add some context extensions ....
    add_rich_context(self, context)
    add_model_context(self, context, plural=False, title=title)
    add_timezone_context(self, context)
    add_debug_context(self, context)
    if callable(getattr(self, 'extra_context_provider', None)):
        context.update(self.extra_context_provider(context))

    if settings.DEBUG:
        log.debug("Prepared this context data.")
        for k, v in context.items():
            # For the form we want to list the form.data really. The rest is
            # unnecessary.
            if k == "form":
                log.debug(f"\tform.data:")
                for field, value in sorted(v.data.items()):
                    log.debug(f"\t\t{field}: {value}")
            else:
                log.debug(f"\t{k}: {v}")

    return context


class RichLoginView(LoginView):
    '''
    An extension to the LoginView that adds timezone context and a hook for providing more context
    to the basic Django LoginView (in a manner compatible with other Rich Views)
    '''
    dispatch = dispatch_generic

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        add_timezone_context(self, context)
        if callable(getattr(self, 'extra_context_provider', None)):
            context.update(self.extra_context_provider(context))
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        form.request.session['timezone'] = form.request.POST['timezone']
        return response


class RichTemplateView(TemplateView):
    '''
    An extension of the basic TemplateView for a home page on the site say (not related to any model)
    which provides some extra context if desired in a manner compatible with the other Rich Views
    '''
    dispatch = dispatch_generic

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        add_rich_context(self, context)
        add_timezone_context(self, context)
        if callable(getattr(self, 'extra_context_provider', None)):
            context.update(self.extra_context_provider(context))
        return context


class RichListView(ListView):
    # HTML formattters stolen straight form the Django ModelForm class basically.
    # Allowing us to present lists basically with the same flexibility as pre-formattted
    # HTML objects.
    operation = 'list'
    _html_output = list_html_output

    as_table = object_as_table
    as_ul = object_as_ul
    as_p = object_as_p
    as_br = object_as_br
    as_html = object_as_html  # Chooses one of the first four based on request parameters

    dispatch = dispatch_generic

    # Fetch all the objects for this model
    def get_queryset(self, *args, **kwargs):
        if settings.DEBUG:
            log.debug(
                f"Getting Queryset for List View. Process ID: {os.getpid()}.")
            if len(self.request.GET) > 0:
                log.debug(f"GET parameters:")
                for key, val in self.request.GET.items():
                    log.debug(f"\t{key}={val}")
            else:
                log.debug(f"No GET parameters!")

        self.app = app_from_object(self)
        self.model = class_from_string(self, self.kwargs['model'])

        self.format = get_list_display_format(self.request.GET)

        self.ordering = get_ordering(self)

        self.filterset = None  # Default

        fs = None
        if len(self.request.GET) > 0 or len(self.request.session.get("filter", {})) > 0:
            # If the URL has GET parameters (following a ?) then self.request.GET
            # will contain a dictionary of name: value pairs that FilterSet uses
            # construct a new filtered queryset.
            fs = get_filterset(self.request, self.model)

        # If there is a filter specified in the URL
        if fs:
            self.filterset = fs
            self.queryset = fs.filter()
        else:
            self.queryset = self.model.objects.all()

        if (self.ordering):
            # We clean the list of ordering fields, removing invalid entries and
            # annotating the query with a count for To_Many fields so we can order_
            # by on that annotation. That count should inherit any valid filters
            # we configure above.
            ordering = []
            for field_name in self.ordering:
                # TODO: We can order games by 'sessions' which translates to a Count, Tick.
                # But can we filter that count by League and keep it generic, The sessions
                # have a 'league' and so we might support an in house syntax?
                # ordering=sessions__league=id
                # OR, here's a better idea, if there's a filter, which we can tell if fs.get_specs()
                # has any entries, then we could apply that filter comehow to the Count maybe?
                # IFF the filter spec makes sense there, and IFF there's a way to aggregate filtered
                # session (an F or Q expression?)
                # YES!
                # https://docs.djangoproject.com/en/dev/ref/models/conditional-expressions/#conditional-aggregation
                if field_name.startswith('-'):
                    real_field_name = field_name[1:]
                    desc = True
                else:
                    real_field_name = field_name
                    desc = False

                field = getattr(self.model, real_field_name, None)

                if field:
                    if is_to_many(field):
                        count_filter = None
                        if fs:
                            fspecs = fs.get_specs()
                            if fspecs:
                                for fspec in fspecs:
                                    # self.model is Game
                                    # self.model.sessions.rel.related_model() is Session
                                    #    this is field.rel.related_model()
                                    # real_field_name is sessions
                                    # fspec.components is ['leagues', 'id']
                                    rel_model = field.rel.related_model
                                    rel_fs = get_filterset(self.request, rel_model)
                                    rel_specs = rel_fs.get_specs()
                                    rel_filters = [
                                        "__".join([real_field_name] + rel_spec.components) for rel_spec in rel_specs]
                                    rel_values = [
                                        rel_spec.value for rel_spec in rel_specs]
                                    count_filter = Q()
                                    for f, v in zip(rel_filters, rel_values):
                                        count_filter &= Q(**{f: v})

                        ordering_name = f"count_{field_name}"
                        ordering.append(('-' if desc else '') + ordering_name)

                        if count_filter is None:
                            kwarg = {ordering_name: Count(real_field_name)}
                        else:
                            kwarg = {ordering_name: Count(
                                real_field_name, filter=count_filter)}

                        self.queryset = self.queryset.annotate(**kwarg)
                    else:
                        ordering.append(field_name)

            self.queryset = self.queryset.order_by(*ordering)

        if settings.DEBUG:
            log.debug(f"ordering  = {self.ordering}")
            log.debug(
                f"filterset = {self.filterset.get_specs() if self.filterset else None}")

        self.count = len(self.queryset)

        return self.queryset

    # Add some model identifiers to the context (if 'model' is passed in via
    # the URL)
    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        add_rich_context(self, context)
        add_model_context(self, context, plural=True)
        add_timezone_context(self, context)
        add_format_context(self, context)
        add_filter_context(self, context)
        add_ordering_context(self, context)
        add_debug_context(self, context)
        context["total"] = self.model.objects.all().count
        if callable(getattr(self, 'extra_context_provider', None)):
            context.update(self.extra_context_provider(context))
        return context


class RichDetailView(DetailView):
    '''
    An enhanced DetailView which provides the HTML output methods as_table, as_ul and as_p just like the ModelForm does (defined in BaseForm).
    '''
    # HTML formatters stolen straight form the Django ModelForm class
    # Allowing us to present object detail views  basically with the same flexibility
    # as pre-formattted HTML objects.
    operation = 'view'
    _html_output = object_html_output

    as_table = object_as_table
    as_ul = object_as_ul
    as_p = object_as_p
    as_br = object_as_br
    as_html = object_as_html  # Chooses one of the first three based on request parameters

    dispatch = dispatch_generic

    # Fetch the URL specified object, needs the URL parameters "model" and "pk"
    def get_object(self, *args, **kwargs):
        if settings.DEBUG:
            log.debug("Getting object.")

        self.model = class_from_string(self, self.kwargs['model'])
        self.pk = self.kwargs['pk']

        # Get the ordering
        self.ordering = get_ordering(self)

        # Get Neighbour info for the object browser
        self.filterset = get_filterset(self.request, self.model)

        neighbours = get_neighbour_pks(self.model, self.pk, filterset=self.filterset, ordering=self.ordering)

        # Support for incoming next/prior requests via a GET
        if 'next' in self.request.GET or 'prior' in self.request.GET:
            self.ref = get_object_or_404(self.model, pk=self.pk)

            # If requesting the next or prior object look for that
            # FIXME: Totally fails for Ranks, the get dictionary fails when there are ties!
            #        Doesn't generalise well at all. Must find a general way to do this for
            #        arbitrary orders. Still should specify orders in models that create unique
            #        ordering not reliant on pk break ties.
            if neighbours:
                if 'next' in self.request.GET and not neighbours[1] is None:
                    self.pk = neighbours[1]
                elif 'prior' in self.request.GET and not neighbours[0] is None:
                    self.pk = neighbours[0]

            self.obj = get_object_or_404(self.model, pk=self.pk)
            self.kwargs["pk"] = self.pk
        else:
            self.obj = get_object_or_404(self.model, pk=self.pk)

        # Add this information to the view (so it's available in the context).
        self.object_browser = neighbours

        self.format = get_object_display_format(self.request.GET)

        collect_rich_object_fields(self)

        return self.obj

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        add_rich_context(self, context)
        add_model_context(self, context, plural=False)
        add_timezone_context(self, context)
        add_format_context(self, context)
        add_filter_context(self, context)
        add_ordering_context(self, context)
        add_debug_context(self, context)
        if callable(getattr(self, 'extra_context_provider', None)):
            context.update(self.extra_context_provider(context))
        return context


def get_form_generic(self, return_mqfns=False):
    '''
    Augments the standard form with related model forms
    so that the template is well informed - and can do
    Javascript wizardry based on this information

    Also replaces the widget for all ModelChoiceField instances
    with a django-autocomplete-light (DAL) widget. And for formsets
    that contain a model selector provides a convenient hook for
    configuring DAL to sensibly provide unique selections across
    the formset.

    A view attribute `unique_model_choice` is consulted. It should be
    a list of model qualified field names, which will receive a custom
    DAL forward declaration. There MUST be a Javascript Forward handler
    registered with that field's name for this to work on client side.

    :param return_mqfns: If True, does not return a form, but instead
                         a list of Model Qualified Field Names that are
                         candidates for the unique_model_choice attribute
                         if it is specified.

    :param self: and instance of CreateView or UpdateView

    This is code shared by the two views so peeled out into a generic.
    '''
    if settings.DEBUG:
        log.debug("Building form.")

    model = self.model
    selector = getattr(model, "selector_field", None)

    if isinstance(self, CreateView):
        form = super(CreateView, self).get_form()
    elif isinstance(self, UpdateView):
        form = super(UpdateView, self).get_form()
    else:
        raise NotImplementedError(
            "Generic get_form only for use by CreateView or UpdateView derivatives.")

    unique_model_choice = getattr(self, 'unique_model_choice', [])

    # If the model has a field_order attribute, and the form does not have one already
    # Use the model field_ordering. DJango provides no way of specifying field_order
    # in a model that is respected in the model form alas. So we use the model.field_order
    # here to reorder the form fields.
    if hasattr(model, "field_order") and getattr(form, "field_order", None) is None:
        form.order_fields(model.field_order)

    # Attach the MDE widget to all any markdown fields and note any LocationFields
    # MDEWidget add CSS and js to form.media
    # LocationField does not. Its media and template tags should be included if
    # needed with code like this in the template:
    #     {% if has_location %}
    #         {% load mapbox_location_field_tags %}
    #         {% location_field_includes %}
    #     {% endif %}
    self.has_location = False
    self.has_markdown = False
    for field_name, field in form.fields.items():
        if isinstance(field, MarkdownFormField):
            field.widget = MDEWidget()
            self.has_markdown = True
        if isinstance(field, LocationField):

            # geo_box can define a bounding box.
            # Alas I see no way of initialising the LocationField with a bounding box.
            # There may be a way to estimate a zoom factor given a bounding box. But
            # from the doc:
            #    https://docs.mapbox.com/help/glossary/zoom-level/
            # it seems we'd need to
            if 'geo_box' in self.request.session:
                box = self.request.session['geo_box']
                lats = box[:2]
                lons = box[2:]
                sw_lat = float(max(lats))
                sw_lon = float(min(lons))
                ne_lat = float(min(lats))
                ne_lon = float(max(lons))

                mid_lat = (sw_lat + ne_lat) / 2
                mid_lon = (sw_lon + ne_lon) / 2

            # geo_point takes precedence over the geo_box.
            if 'geo_point' in self.request.session:
                p = self.request.session['geo_point']
                mid_lat, mid_lon = p.latitude, p.longitude

            # field.initial sets the value of the text box
            # field.widget.map_attrs["center"] sets the center of the displayed map
            # field.widget.map_attrs["zoom"] sets the zoom level of the displayed map
            #
            # field.initial is set for us already if using an Update form.
            # field.initial  is (0,0) on any Update forms where locaction is null.
            # The (0,0) is rendered and interpreted so we need to remove it from form.initial
            #
            # if for any reason we want to set field.intiial it take two formats readily:
            #
            #    field.initial = Point(lon, lat)
            #    field.initial = f"({lon}, {lat})"
            #
            # Note: these are lon, lat not lat, lon
            if form.initial:
                initial = form.initial[field_name]
                if initial == (0, 0):
                     del form.initial[field_name]

            field.widget.map_attrs = {
                "center": [mid_lon, mid_lat],
                "zoom": 12,  # https://docs.mapbox.com/help/glossary/zoom-level/
                # chatGPT thought "bounds" would work but I see no doc for that nor does it seem to work.
                #"bounds": [[sw_lon, sw_lat], [ne_lon, ne_lat]]
                }

            self.has_location = True

    # Attach DAL (Django Autocomplete Light) Select2
    # widgets to all the model selectors
    mqfns = []
    for field_name, field in form.fields.items():
        if isinstance(field, ModelChoiceField):
            field_model = field.queryset.model
            selector = getattr(field_model, "selector_field", None)
            if not selector is None:
                url = reverse_lazy('autocomplete', kwargs={
                                   "model": field_model.__name__, "field_name": selector})
                qualified_field_name = f"{form._meta.model.__name__}.{field_name}"
                mqfns.append(qualified_field_name)
                if qualified_field_name in unique_model_choice:
                    forward_function = qualified_field_name
                    forward_parameter = 'exclude'
                    forward_declaration = (forward.JavaScript(
                        forward_function, forward_parameter),)
                else:
                    forward_declaration = None

                if isinstance(field, ModelMultipleChoiceField):
                    field.widget = autocomplete.ModelSelect2Multiple(
                        url=url, forward=forward_declaration)
                else:
                    field.widget = autocomplete.ModelSelect2(
                        url=url, forward=forward_declaration)

                field.widget.choices = field.choices

    # Include forms for all intrinsic relations ...
    if len(intrinsic_relations(model)) > 0:
        if len(getattr(self.request, 'POST', [])) > 0:
            form_data = self.request.POST
        elif len(getattr(self.request, 'GET', [])) > 0:
            form_data = self.request.GET
        else:
            form_data = None

        if isinstance(getattr(self, "object", None), model):
            db_object = self.object
        else:
            db_object = None

        # related_forms = get_related_forms(model, form_data, db_object)
        related_forms = RelatedForms(model, form_data, db_object)

        for related_model_name, related_form in related_forms.items():
            for field_name, field in related_form.fields.items():
                # Attach the MDE widget to all any markdown fields and note any LocationFields
                if isinstance(field, MarkdownFormField):
                    field.widget = MDEWidget()
                    self.has_markdown = True
                if isinstance(field, LocationField):
                    self.has_location = True

                # Attach DAL (Django Autocomplete Light) Select2
                # widgets to all the model selectors
                if isinstance(field, ModelChoiceField):
                    field_model = field.queryset.model
                    selector = getattr(field_model, "selector_field", None)
                    if not selector is None:
                        url = reverse_lazy('autocomplete', kwargs={
                                           "model": field_model.__name__, "field_name": selector})

                        qualified_field_name = f"{related_model_name}.{field_name}"
                        mqfns.append(qualified_field_name)
                        if qualified_field_name in unique_model_choice:
                            forward_function = qualified_field_name
                            forward_parameter = 'exclude'
                            forward_declaration = (forward.JavaScript(
                                forward_function, forward_parameter),)
                        else:
                            forward_declaration = None

                        if isinstance(field, ModelMultipleChoiceField):
                            field.widget = autocomplete.ModelSelect2Multiple(
                                url=url, forward=forward_declaration)
                        else:
                            field.widget = autocomplete.ModelSelect2(
                                url=url, forward=forward_declaration)

                        field.widget.choices = field.choices

        form.related_forms = related_forms

    # Classify the widgets on the form (atach HTML class attributes to them)
    classify_widgets(form)

    return mqfns if return_mqfns else form


def post_generic(self, request, *args, **kwargs):
    '''
    Processes a form submission.

    Provides five hooks:

        pre_validation     called before the first form validation, returns a dict that is unpacked as kwargs for pre_transaction
        pre_transaction    called before a transaction starts, returns a dict that is unpacked as kwargs for pre_save
        pre_save           called after form validation and cleaning, a transaction has been opened but before saving, returns a dict that is unpacked as kwargs for pre_commit
        pre_commit         called just before committing the transaction. Raise IntergityError or ValidationError if needed.
        post_save          called after the forms is saved and transaction committed.

    :param self: and instance of CreateView or UpdateView

    This is code shared by the two views so peeled out into a generic.
    '''
    if settings.DEBUG:
        log.debug("Received POST data.")

    # Just reflect the POST data back to client for debugging if requested
    if self.request.POST.get("debug_post_data", "off") == "on":
        html = "<h1>self.request.POST:</h1>"
        html += "<table>"
        for key in sorted(self.request.POST):
            html += "<tr><td>{}:</td><td>{}</td></tr>".format(
                key, self.request.POST[key])
        html += "</table>"
        return HttpResponse(html)

    self.model = class_from_string(self, self.kwargs['model'])
    if not hasattr(self, 'fields') or self.fields == None:
        self.fields = '__all__'

    if isinstance(self, CreateView):
        # The self.object atttribute MUST exist and be None in a CreateView.
        self.object = None
    elif isinstance(self, UpdateView) or isinstance(self, DeleteView):
        self.object = self.get_object()
    else:
        raise NotImplementedError(
            "Generic post only for use by CreateView or UpdateView derivatives.")

    # Delete is handled specially (it's much simpler that Create and Update
    # Views)
    if isinstance(self, DeleteView):
        # Hook for pre-processing steps (before the object is actually deleted)
        # The handler can return a kwargs dict to pass to the post delete
        # handler.
        if callable(getattr(self, 'pre_delete', None)):
            next_kwargs = self.pre_delete()
            if not next_kwargs:
                next_kwargs = {}
            if "debug_only" in next_kwargs:
                return HttpResponse(next_kwargs["debug_only"])

        with transaction.atomic():
            if settings.DEBUG:
                log.debug(
                    f"Deleting: {self.object._meta.object_name} {self.object.pk}.")

            # For deletes we won't concern ourselves with related forms.
            # Generally the on_delete property of ForeignKey relations will hanld cascading
            # deletes if properly configured in the models, and if any special follow-on
            # deletes or other actions are needed the pre_delete and post_delete hooks are
            # available for a derived class lient to manage that in code
            # explicitly.
            response = self.delete(request, *args, **kwargs)

            # Hook for post-processing steps (after the object is actually deleted)
            # Accept arguments from the pre_handler
            if callable(getattr(self, 'post_delete', None)):
                self.post_delete(**next_kwargs)

        return response

    # Create and Update are comparatively similar
    # There's a form that contains the submission and we want to
    # validate it before we commit any changes to the database.
    else:
        # Get the form
        self.form = self.get_form()

        # Just reflect the form data back to client for debugging if requested
        if self.request.POST.get("debug_form_data", "off") == "on":
            html = "<h1>self.form.data:</h1>"
            html += "<table>"
            for key in sorted(self.form.data):
                html += "<tr><td>{}:</td><td>{}</td></tr>".format(
                    key, self.form.data[key])
            html += "</table>"
            return HttpResponse(html)

        # Perform an inital validity check before proceeding. There is a deep GOTCHA in this though
        # that we have to avoid. self.get_form() sets self.form.instance from self.object
        # (in django.forms.models.BaseModelForm.__init__) then during a full_clean() that is_valid()
        # performs one fo the final steps to apply the form data to self.insance
        # (in django.forms.models.BaseModelForm._post_clean). This is all fairly intrinsic to what
        # Django methods do, leaving an instance which is self.object with the form data applied.
        #
        # Note: The assigment self.form.instance = self.object is by reference and the two refer to
        # the same object which is why when self.form.instance is updated in the full_clean to conatin
        # form data, it also updates self.object (the same object)
        #
        # The problem for us, is we want to offer the pre_transaction handler the form.data and
        # ideally form.cleaned_data so it does not have to replciate any of Django's already
        # implemented form parsing and interpretation.
        #
        # The way to do that is in this first pass to feign a Creation form, by removing self.form.instance.
        # Calling is_valid() and then replacing self.form.instance  again so that the pre_transaction handler
        # can see it and compare form.cleaned_data with the object to make change based decisions and
        # pass them back as arguments into pre_save and indirectly the
        # pre_commit handler.

        # Cloak self.form.instance.
        # Django wants to see an new instance of the model though.
        # This simply mimics what django.forms.models.BaseModelForm.__init__ does when no object is porvided.
        #
        # The pre_transaction and pre_save handler now both have accesss to self.object as it was.
        # We will uncloak this just before saving.
        if self.object:  # protect it from the full_clean augmentation
            self.form.instance = self.form._meta.model()
            # Setting the instance to a newly instantiated instance seesm to trigger a form clean which
            # Can generate errors based on a a the CreateView context (like unique value constarints)
            # which have no bearing on the UpdateView which has an object attached. As we validate the
            # form below in the proper context, we clear any form errors that this (dummy) context
            # may have generated. The joy of trying to trick Django ...
            self.form.errors.clear()

        # HOOK 1 pre_validation: Hook for pre-processing the form (before the first from validation)
        # Ideal for injecting any form submission alterationsdata cleaning or reconiliation as needed
        # to ensure that the is_valid() call passes or fails as desired.
        if callable(getattr(self, 'pre_validation', None)):
            next_kwargs = self.pre_validation()
            if not next_kwargs:
                next_kwargs = {}
            if "debug_only" in next_kwargs:
                return HttpResponse(next_kwargs["debug_only"])

        if settings.DEBUG:
            log.debug(f"Is_valid? {self.form.is_valid()}: {self.form.data}")

        if self.form.is_valid():
            # HOOK 2 pre_transaction: Hook for pre-processing the form (before a database transaction is opened)
            # The form has passed first validation and now is a chance to inject some code before we open a
            # database transaction. Ideal for pre-transaction checks on the form data (can add form errors
            # if neeed and the next validation will fail.
            if callable(getattr(self, 'pre_transaction', None)):
                next_kwargs = self.pre_transaction(**next_kwargs)
                if not next_kwargs:
                    next_kwargs = {}
                if "debug_only" in next_kwargs:
                    return HttpResponse(next_kwargs["debug_only"])

            # The pre-transaction handler can add form errors
            if self.form.is_valid():
                try:
                    if settings.DEBUG:
                        log.debug(f"Open a transaction")
                    with transaction.atomic():
                        # HOOK 3 pre_save: Hook for pre-processing the form (before the data is saved)
                        # The form has passed validation (twice now, before and after a database transaction
                        # was opened) and now is a chance to do something before the form (and all its
                        # related forms).
                        if callable(getattr(self, 'pre_save', None)):
                            next_kwargs = self.pre_save(**next_kwargs)
                            if not next_kwargs:
                                next_kwargs = {}

                        if settings.DEBUG:
                            log.debug(
                                "Saving form with this submitted for data:")
                            for (key, val) in sorted(self.form.data.items()):
                                # See: https://code.djangoproject.com/ticket/1130
                                # list items are hard to identify it seems in a
                                # generic manner
                                log.debug(
                                    f"\t{key}: {val} & {self.form.data.getlist(key)}")

                        if self.object:  # unprotect it from the full_clean augmentation once more
                            # Uncloak self.form.instance. From here on in we
                            # can proceed as normal.
                            self.form.instance = self.object
                            # Reclean the data which ensures this instance has the form data applied now.
                            # This may raise a ValidationError if it fails to apply form data to the instance
                            # for any reason.  Which rightly, rolls back our
                            # transaction.
                            self.form.full_clean()
                            # Or maybe not, so check for errors and raise one
                            # if found:
                            if self.form.errors:
                                raise ValidationError(
                                    f'Some errors were detected in your submission. Errors: {self.form.errors}')

                        self.object = self.form.save()

                        if settings.DEBUG:
                            log.debug(
                                f"Saved object: {self.object._meta.object_name} {self.object.pk}.")

                        kwargs = self.kwargs
                        kwargs['pk'] = self.object.pk

                        # By default, on success jump to a view of the obbject
                        # just submitted.
                        if not self.success_url:
                            self.success_url = reverse_lazy(
                                'view', kwargs=kwargs)

                        if isinstance(self, CreateView):
                            # Having saved the root object we reinitialise related forms
                            # with that object attached. Failure to this results in the
                            # form_clean failing as the formsets don't have populated
                            # back references (as we had no object) and it fails with
                            # 'This field is required.' erros on the primary keys
                            self.form.related_forms = RelatedForms(
                                self.model, self.form.data, self.object)

                        if hasattr(self.form, 'related_forms') and isinstance(self.form.related_forms, RelatedForms):
                            if settings.DEBUG:
                                log.debug(f"Saving the related forms.")

                            # Either of the pre_transaction or pre_save handlers might have replace self.form.data with
                            # something cleaned up. self.form.related_forms was initialised before these were alled and
                            # noted the contents of self.form.data. We need to
                            # inform it of any change.
                            self.form.related_forms.set_data(self.form.data)

                            if self.form.related_forms.are_valid(self.model.__name__):
                                peak = self.form.related_forms.errors
                                self.form.related_forms.save()
                                if settings.DEBUG:
                                    log.debug(f"Saved the related forms.")
                            else:
                                if settings.DEBUG:
                                    log.debug(
                                        f"Invalid related forms. Errors: {self.form.related_forms.errors}")
                                # Attach the newly annotated (with errors) related forms to the
                                # form so that theyt reach the response template.
                                # self.form.related_forms = related_forms
                                # We raise an exception to break out of the
                                # atomic transaction triggering a rollback.
                                for rm, errors in self.form.related_forms.errors.items():
                                    for error in errors:
                                        self.form.add_error(
                                            None, f"{rm}: {error.as_text()}")

                                raise ValidationError(
                                    f"Please fix these and resubmit.")

                        # Give the object a chance to cleanup relations before we commit.
                        # Really a chance for the model to set some standards on relations
                        # They are all saved in the transaction now and the object can see
                        # them all in the ORM (the related objects that is)
                        if callable(getattr(self.object, 'clean_relations', None)):
                            self.object.clean_relations()

                        # HOOK 4 pre_commit: Before committing give the view defintion a chance to do something
                        # prior to committing the update. This is ideal for any checks that rely on the form (and its
                        # related formsets_having been saved. Code therein can access the saved objects and draw
                        # conclusions. Raising an IntegrityError or ValidationError  will roll back the transaction.
                        # and bounce back to display the form with form.errors
                        # shown.
                        if callable(getattr(self, 'pre_commit', None)):
                            next_kwargs = self.pre_commit(**next_kwargs)
                            if not next_kwargs:
                                next_kwargs = {}

                        if settings.DEBUG:
                            log.debug(f"Cleaned the relations.")
                except (IntegrityError, ValidationError) as e:
                    # Validation errors arrive with a message.
                    # Integrity errors tend to arise when the Models don't reflect the Database schema
                    #    that is migrations should be made and applied. The don't have a message but
                    #    a message can be found in the first argument.
                    if settings.DEBUG:
                        # Some tracback generation for debugging if needed
                        exc_type, exc_obj, exc_tb = sys.exc_info()
                        fname = os.path.split(
                            exc_tb.tb_frame.f_code.co_filename)[1]
                        log.debug(
                            f"{exc_type.__name__} in {fname} at line {exc_tb.tb_lineno}")
                        log.debug(traceback.format_exc())

                    message = getattr(e, 'message', e.args[0])
                    if e.__class__.__name__ == "IntegrityError":
                        category = "Database integrity error"
                    else:
                        category = "Form validation error"
                    self.form.add_error(None, f"{category}: {message}")
                    return self.form_invalid(self.form)

                # HOOK 5 post_save: Hook for post-processing data (after it's all saved)
                # The form is valid now and returns form_valid() so post save processing
                # is not the place to raise any exceptions or add any form errors, that
                # is all done and dusted. It is a place for any post save
                # bookkeeping.
                if callable(getattr(self, 'post_save', None)):
                    self.post_save(**next_kwargs)

                return self.form_valid(self.form)
            else:
                # Bounced by the pre transaction handler
                return self.form_invalid(self.form)
        else:
            # Bounced by the first pass of per handled form data
            # Uncloak self.form.instance. From here on in we can proceed as
            # normal.
            self.form.instance = self.object
            return self.form_invalid(self.form)


def form_valid_generic(self, form):
    '''
    If the form is valid, redirect to the supplied URL.

    :param self: and instance of CreateView or UpdateView
    :param form: and instance of ModelForm

    This is code shared by the two views so peeled out into a generic.

    This is specifically intended NOT to call Django's form_valid()
    implementation which saves the object. In these Extensions we
    perform the save in the post not the form_valid method.
    '''
    return HttpResponseRedirect(self.get_success_url())


def form_invalid_generic(self, form):
    '''
    If the form is invalid, reload the form with the rich context

    :param self: and instance of CreateView or UpdateView
    :param form: and instance of ModelForm

    This is code shared by the two views so peeled out into a generic.

    This is specifically intended NOT to call Django's form_invalid()
    implementation which renders the simple form directly to response
    without aboy related form data.
    '''
    context = self.get_context_data(form=form)
    response = TemplateResponse(self.request, self.template_name, context, headers={
                                "Cache-Control": "no-store"})
    response.render()

    if settings.DEBUG:
        log.debug("Form errors:")
        log.debug(f"\t{response.context_data['form'].errors}")
        log.debug("Form context:")
        for k, v in context.items():
            # For the form we want to list the form.data really. The rest is
            # unnecessary.
            if k == "form":
                log.debug(f"\tform.data:")
                for field, value in sorted(v.data.items()):
                    log.debug(f"\t\t{field}: {value}")
            else:
                log.debug(f"\t{k}: {v}")

    return response


class RichCreateView(CreateView):
    '''
    A CreateView which makes the model and the related_objects it defines available
    to the View so it can render form elements for the related_objects if desired.

    On a GET request get_context_data() is called to augment the context data for the form render,
    then get_initial() is called for initial values of the form fields.

    On a POST request post() is called to validate the submission and save it if good
    or bounce back with a rerender of the form with errors listed.

    Both sequences need to defined these:
        self.model
        self.fields

    So we do it in get_context_data() and in post() as our two entry points.

    Both call get_queryset() in order to obtain the model from the returned queryset, if it's not
    defined in self.model. And so we could define self.model and self.fields in one place. But it
    is a little odd and confusing to think of get_queryset() for a CreateView, so here we avoid
    that convenience and confusions.

    NOTE: We do also include a form_valid() override. This is important because in the standard
    Django post/form_valid pair, post does not save, form_valid does. If we defer to the Django
    form_valid it goes and saves the form again. This doesn't create a new copy on creates as it
    happens that by that point self.instance already has a PK thanks to the save here in post() but
    it is an unnecessary repeat save all the same.
    '''
    operation = 'add'
    dispatch = dispatch_generic
    get_context_data = get_context_data_generic_for_forms
    get_form = get_form_generic
    post = post_generic
    form_init = None
    form_valid = form_valid_generic
    form_invalid = form_invalid_generic

    # Fields identified in this list will, if (and only if) they are a ModelChoiceField and a DAL widget is
    # attached to the field, have a forward configured that calls a forwardHandler as per:
    # https://django-autocomplete-light.readthedocs.io/en/master/tutorial.html#customizing-forwarding-logic
    #
    # A ForwardHandler must be registered in the client side Javascript with the name excludeModel or the DAL
    # widget will fail because of an unregistered handler.
    unique_model_choice = []

    # Fields in unique_model_choice are identfied by the model qualified field name, in form <model>.field_name>.
    # The qualified names that are DAL widgets are saved in this form property for reference to see what qualified
    # field names have DAL widgets. This is  a dict keyed on the qualified
    # field name with the widget as a value
    dal_widgets = {}

    def get_initial(self):
        '''
        Returns a dictionary of values keyed on model field names that are used to populated the form widgets
        with initial values.
        '''
        if settings.DEBUG:
            log.debug("Getting initial data from defaults.")

        initial = super().get_initial()

        ####################################################################
        # Inheritance support
        #
        # Initial values can be inherited from earlier objects that were
        # created. Specifically we honor three special model fields that
        # can communicate inheritance preferences:
        #
        # inherit_fields: A list of fields that would be inherited from
        #                 "latest" object of the same model, entered by
        #                 the same user.
        #
        # inherit_time_delta: for any field in inherit_fields that is a
        #                     date_time will add this delta. if it is callable
        #                     will be called with the "latest" object as an arg.
        #
        # Latest is defined by Djangos latest() method whcuh respects amodels
        # Meta setting "get_latest_by".

        try:
            user = self.request.user
            last = self.model.objects.filter(created_by=user).latest()
        except ObjectDoesNotExist:
            last = None

        if last:
            for field_name in inherit_fields(self.model):
                field_value = getattr(last, field_name)
                if isinstance(field_value, datetime.datetime):
                    # If there's a local date_time on offer use that!
                    if hasattr(last, field_name + "_local"):
                        field_value = getattr(last, field_name + "_local")

                    # Find a time delta if any
                    delta = getattr(
                        self.model, "inherit_time_delta", datetime.timedelta(0))

                    # If delta is a callable, call it
                    if callable(delta):
                        delta = delta(last)

                    if delta:
                        initial[field_name] = field_value + delta
                else:
                    initial[field_name] = field_value

        # Hook for aurgmenting the initial form data
        if callable(self.form_init):
            initial = self.form_init(initial)

        return initial

#     def form_invalid(self, form):
#         """
#         If the form is invalid, re-render the context data with the
#         data-filled form and errors.
#         """
#         context = self.get_context_data(form=form)
#         response = self.render_to_response(context)
#         return response


class RichUpdateView(UpdateView):
    '''
    An UpdateView which makes the model and the related_objects it defines available to the View so it can render form elements for the related_objects if desired.

    Note: This is almost identical to the RichCreateView class above bar one line, where we set self.object!
          Which is precisely how Django differentiates a Create from an Update!

          Aside from that though we define get_object() in place of get_initial().

          Unlike the CreateView on a GET request Django calls get_object() first then get_context_data().
          And on a POST request it just calls post(). So we set up self.model and self.object in
          get_object() for GET requests and post() for POST requests.
    '''
    operation = 'edit'
    dispatch = dispatch_generic
    get_context_data = get_context_data_generic_for_forms
    get_form = get_form_generic
    post = post_generic
    form_valid = form_valid_generic
    form_invalid = form_invalid_generic

    # Fields identified in this list will, if (and only if) they are a ModelChoiceField and a DAL widget is
    # attached to the field, have a forward configured that calls a forwardHandler as per:
    # https://django-autocomplete-light.readthedocs.io/en/master/tutorial.html#customizing-forwarding-logic
    #
    # A ForwardHandler must be registered in the client side Javascript with the name excludeModel or the DAL
    # widget will fail because of an unregistered handler.
    unique_model_choice = []

    # Fields in unique_model_choice are identfied by the model qualified field name, in form <model>.field_name>.
    # The qualified names that are DAL widgets are saved in this form property for reference to see what qualified
    # field names have DAL widgets. This is  a dict keyed on the qualified
    # field name with the widget as a value
    dal_widgets = {}

    def get_object(self, *args, **kwargs):
        '''Fetches the object to edit and augments the standard queryset by passing the model to the view so it can make model based decisions and access model attributes.'''
        if settings.DEBUG:
            log.debug("Getting initial data from an existing object.")

        self.pk = self.kwargs['pk']
        self.model = class_from_string(self, self.kwargs['model'])
        self.obj = get_object_or_404(self.model, pk=self.kwargs['pk'])

        if not hasattr(self, 'fields') or self.fields == None:
            self.fields = '__all__'

        if callable(getattr(self.obj, 'fields_for_model', None)):
            self.fields = self.obj.fields_for_model()
        else:
            self.fields = fields_for_model(self.model)

        return self.obj


class RichDeleteView(DeleteView):
    '''An enhanced DeleteView which provides the HTML output methods as_table, as_ul and as_p just like the ModelForm does.'''
    # HTML formatters stolen straight form the Django ModelForm class
    operation = 'delete'
    _html_output = object_html_output
    as_table = object_as_table
    as_ul = object_as_ul
    as_p = object_as_p
    as_br = object_as_br
    as_html = object_as_html  # Chooses one of the first three based on request parameters

    dispatch = dispatch_generic
    post = post_generic

    # Get the actual object to update
    def get_object(self, *args, **kwargs):
        self.app = app_from_object(self)
        self.model = class_from_string(self, self.kwargs['model'])

        self.pk = self.kwargs['pk']
        self.obj = get_object_or_404(self.model, pk=self.kwargs['pk'])
        self.format = get_object_display_format(self.request.GET)

        # By default jump to a list of objects (fomr which htis one was
        # deleted)
        if not self.success_url:
            self.success_url = reverse_lazy(
                'list', kwargs={'model': self.kwargs['model']})

        collect_rich_object_fields(self)

        return self.obj

    # Add some model identifiers to the context (if 'model' is passed in via
    # the URL)
    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        add_rich_context(self, context)
        add_model_context(self, context, plural=False, title='Delete')
        add_timezone_context(self, context)
        add_format_context(self, context)
        add_debug_context(self, context)
        if callable(getattr(self, 'extra_context_provider', None)):
            context.update(self.extra_context_provider(context))
        return context
