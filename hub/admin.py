"""Admin configuration for Orochi hub models."""

from django.contrib import admin

from hub.models import (
    AgentGroup,
    Channel,
    Message,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
)


class WorkspaceTokenInline(admin.TabularInline):
    model = WorkspaceToken
    extra = 1
    readonly_fields = ("token", "created_at")


class WorkspaceMemberInline(admin.TabularInline):
    model = WorkspaceMember
    extra = 1


class ChannelInline(admin.TabularInline):
    model = Channel
    extra = 0


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at")
    inlines = [WorkspaceTokenInline, WorkspaceMemberInline, ChannelInline]


@admin.register(WorkspaceToken)
class WorkspaceTokenAdmin(admin.ModelAdmin):
    list_display = ("label", "workspace", "token", "created_at")
    list_filter = ("workspace",)
    readonly_fields = ("token",)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "created_at")
    list_filter = ("workspace",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "channel", "content_preview", "ts")
    list_filter = ("workspace", "channel")
    readonly_fields = ("ts",)

    @admin.display(description="Content")
    def content_preview(self, obj):
        return obj.content[:80] if obj.content else ""


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    list_display = ("user", "workspace", "role", "joined_at")
    list_filter = ("workspace", "role")


@admin.register(AgentGroup)
class AgentGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "display_name", "workspace", "is_builtin", "member_count", "owner", "created_at")
    list_filter = ("workspace", "is_builtin")
    filter_horizontal = ("members",)
    readonly_fields = ("created_at", "updated_at")
    search_fields = ("name", "display_name")

    @admin.display(description="Members")
    def member_count(self, obj):
        return obj.members.count()
