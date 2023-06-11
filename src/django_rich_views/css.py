import os
import re

from lxml import html
from webcolors import name_to_rgb, hex_to_rgb
from colorsys import hls_to_rgb

from django.conf import settings
from django.template.loader import render_to_string


def get_css(template, context=None):
    '''
    Given a template (as a string of simply sepcifying the filename e.g. "default.css")
    Will return the CSS it specifies as a string, if it's on the local server,

    :param template: A string (as in a Django view's template_name property)
    '''
    template_content = render_to_string(template, context=context)
    root = html.fromstring(template_content)
    css_links = root.cssselect('link[rel="stylesheet"]')
    css_styles = root.cssselect('style')
    css_string = ""
    for link in css_links:
        path = settings.BASE_DIR + link.attrib['href']
        # Stylesheets may be on the local server or come from a CDB or other source.
        # We only concern ourselves with local server style sheets here for
        # now.
        if os.path.isfile(path):
            with open(path, 'r') as file:
                css_file_contents = file.read()
            css_string += css_file_contents
        else:
            pass
        # css_string += requests.get(css_url).text
    for style in css_styles:
        css_string += style.text
    return css_string


def get_css_custom_properties(css_string=None, template=None, context=None):
    '''
    Given a template (as a string of simply sepcifying the filename e.g. "default.css")
    Will return a dict fo the CSS custom properties with name as key and value as value.

    :param template: A string (as in a Django view's template_name property)
    '''
    css_string = get_css(template, context) if css_string is None else css_string
    return dict(re.findall(r"--(.*?)\s*:\s*(.*?)\s*;", css_string))


def parse_color(color_string):
    '''
    Given a CSS color string attempts to return a color as an (R, G, B) tuple.

    :param color_string: A string specifying a color from a CSS style
    '''
    # regular expression to match different types of CSS color specifications
    color_regex = re.compile(
        r'^(rgb|hsl|rgba|hsla|#[0-9a-fA-F]+|[a-zA-Z]+)', re.RegexFlag.IGNORECASE)
    color_type = color_regex.match(color_string).group(0)

    # check the type of color and convert it to RGB
    if color_type.lower() in ('rgb', 'rgba'):
        color_string = color_string.replace(
            color_type, '').replace('(', '').replace(')', '')
        r, g, b = map(int, color_string.split(','))
        return r, g, b
    elif color_type.lower() in ('hsl', 'hsla'):
        match = re.search(r"HSL\(\s*(\d*\.?\d+)\s*,\s*(\d*\.?\d+)(%?)\s*,\s*(\d*\.?\d+)(%?)\s*\)",
                          color_string, re.RegexFlag.IGNORECASE)
        h, s, spct, l, lpct = match.groups()

        H = float(h) / 360
        S = float(s) / 100 if spct == '%' else float(s)
        L = float(l) / 100 if lpct == '%' else float(l)

        return tuple(map(lambda x: int(x * 255), hls_to_rgb(H, L, S)))
    elif color_type.startswith('#'):
        return hex_to_rgb(color_string)
    else:
        return name_to_rgb(color_string)
