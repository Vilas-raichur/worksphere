from django.contrib import admin

from .models import InAppNotification


@admin.register(InAppNotification)
class InAppNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "organization",
        "category",
        "title",
        "read_at",
        "created_at",
    )
    list_filter = ("organization", "category", "read_at")
    search_fields = (
        "user__username",
        "user__email",
        "title",
        "message",
    )
    readonly_fields = (
        "user",
        "organization",
        "category",
        "title",
        "message",
        "metadata",
        "read_at",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
