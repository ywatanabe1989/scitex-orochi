"""Django app config for hub — wires up DM rename signals (spec v3 §2.2)."""

from django.apps import AppConfig


class HubConfig(AppConfig):
    name = "hub"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Importing the module registers the post_save handlers.
        from hub import signals  # noqa: F401
