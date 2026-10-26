from django.apps import AppConfig


class NtoTravelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "nto_travel"
    verbose_name = "Поездки на финал НТО"

    def ready(self):
        from django.db.models.signals import post_migrate
        from .signals import create_nto_groups

        post_migrate.connect(create_nto_groups, sender=self, dispatch_uid="nto_travel_create_groups")
