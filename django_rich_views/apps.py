from django.apps import AppConfig

class DjangoRichViewsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'django_rich_views'
    verbose_name = 'Django Rich Views'

    # def ready(self):
    #     '''
    #     This works, it adds to INSTALLED_APPS, alas the apps templates are not found.
    #     And so this is disabled for now. The markdownfield app has to be added manyally
    #     to the site's INSTALLED_APPS, django_rich_views can't meaningfully do it for you.
    #     '''
    #     from django.conf import settings
    #     settings.INSTALLED_APPS = ('markdownfield',) + settings.INSTALLED_APPS
    #     print(f"Installed apps: {settings.INSTALLED_APPS}")
    #     print(f"Template dirs: {settings.TEMPLATES}")


