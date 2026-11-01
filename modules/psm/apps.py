from django.apps import AppConfig


class PSMConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.psm"
    label = "psm"
    verbose_name = "Purchase and Stores Management"
