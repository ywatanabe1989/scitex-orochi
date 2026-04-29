# Stub migration: this was the original 0035_add_agentgroup_model migration that ran
# on deployed instances before the AgentGroup migration was renumbered to 0037.
# The actual schema operations are in 0037_add_agentgroup_model.py.
# This stub exists so Django's migration state for previously-deployed containers
# (which have hub.0035_add_agentgroup_model in their django_migrations table)
# remains consistent when 0035_channelmembership_mention_only runs.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hub', '0034_alter_workspacetoken_agent_name'),
    ]

    operations = []
