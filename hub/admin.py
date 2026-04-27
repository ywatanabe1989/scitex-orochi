"""Admin configuration for Orochi hub models."""

from django.contrib import admin

from hub.models import Channel, Message, Workspace, WorkspaceMember, WorkspaceToken


class WorkspaceTokenInline(admin.TabularInline):
    orochi_model = WorkspaceToken
    extra = 1
    readonly_fields = ("token", "created_at")


class WorkspaceMemberInline(admin.TabularInline):
    orochi_model = WorkspaceMember
    extra = 1


class ChannelInline(admin.TabularInline):
    orochi_model = Channel
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
