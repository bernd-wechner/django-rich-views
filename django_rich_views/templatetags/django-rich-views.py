import json as JSON

from os.path import splitext

from django import template
from django.template.loader_tags import do_include
from django.template.base import Token, Origin
from django.utils.safestring import mark_safe

from django_rich_views.util import DjangoObjectJSONEncoder


register = template.Library()


class IncludeVariant(template.Node):
    '''
    A Template Node that tries to include a template file named as a variant
    of the file it's included in. That is if it's in a template named:

        form_data.html

    as:

        {% include_variant context_var %}

    it will try and include:

        form_data_context_var.html

    where context_var is a context variable.

    For help on custom template tags:
    https://docs.djangoproject.com/en/3.1/howto/custom-template-tags/#writing-the-compilation-function
    '''

    def __init__(self, parser, token):
        self.parser = parser
        self.token = token

    def render(self, context):
        try:
            words = self.token.split_contents()
            variant = context.get(self.token.contents.split()[
                                  1], self.token.contents.split()[1])

            path = context.template_name
            parts = splitext(path)
            words[1] = f"'{parts[0]}_{variant}{parts[1]}'"

            include = do_include(self.parser, Token(
                self.token.token_type, " ".join(words)))
            # A Django 4 fix: as of 4 it demands an origin that do_include does
            # not provide!
            include.origin = template.loader.get_template(path).origin
            return include.render(context)
        except template.TemplateDoesNotExist:
            return ''
        except Exception as e:  # @UnusedVariable
            return f"INCLUDE ERROR: {e}"


@register.tag('include_variant')
def include_variant(parser, token):
    '''
    Include the specified variant on this template but only if it exists.

    :param parser:
    :param token:
    '''
    return IncludeVariant(parser, token)


@register.filter
def json(value):
    return mark_safe(JSON.dumps(value, cls=DjangoObjectJSONEncoder))


@register.filter
def checked(value, compare=None):
    '''
    Returns "checked" if the value is truthy, or if a compare value is provided if it matches that.
    '''
    if compare is None:
        if value:
            return "checked"
        else:
            return ""
    else:
        if value == compare:
            return "checked"
        else:
            return ""


@register.simple_tag
def setvar(val=None):
    '''
    Used as follows:

    {% setvar "value" as variable_name %}

    and then applied with {{variable_name}}.

    :param val: a value to set the variable to.
    '''
    return val


@register.simple_tag(takes_context=True)
def active(context, view_name):
    '''
    A simple tag to return " active" or "" if the passed view name is in hte context as view_name.

    Used for BootStrap Nav items:

        https://getbootstrap.com/docs/5.2/components/navs-tabs/

    Expects the 'view' in the Django context and is useful when the navs link to:

        href="{% url '<view_name>' %}

    Each nav can then use two Django template variables to configure a menu item with an active class
    as need and link using setvar() above to avoid repetition (DRY):

        {% setvar "home" as nav_target %}
        <a class="nav-link{%active nav_target%}" data-toggle="pill" href="{% url nav_target %}">{{nav_target|title}}</a>

    :param view_name: The name of the view to check for.
    '''
    if 'view' in context:
        return ' active' if view_name == context['view'].request.resolver_match.view_name else ''
    else:
        return "ERROR: 'view' not in context."
