'''
Django Rich Views

Template rendering wrappers. Providing context injection points for anyone using:

	django.shortcuts.render
	django.template.loader.render_to_string

Equivalently implemented in:
	django_rich_views.context.add_rich_context

for use in the Rich class based views. These wrappers are for plain function views that returns a rendered template

'''
from django.conf import settings
from django.shortcuts import render
from django.template.loader import render_to_string


def rich_render(request, template_name, context=None, content_type=None, status=None, using=None):
    if context is None:
        context = {}
    context["USE_BOOTSTRAP"] = getattr(settings, 'USE_BOOTSTRAP', False)
    return render(request, template_name, context, content_type, status, using)


def rich_render_to_string(template_name, context=None, request=None, using=None):
    if context is None:
        context = {}
    context["USE_BOOTSTRAP"] = getattr(settings, 'USE_BOOTSTRAP', False)
    return render_to_string(template_name, context, request, using)
