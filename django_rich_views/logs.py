'''
Django Rich Views

Log support. By default no logged is configured. But you can hook one here by setting

import django_rich_views.logs
django_rich_views.logs.logger = yourlogger.

'''


class null_logger:

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass

    def critical(self, msg):
        pass


logger = null_logger()
