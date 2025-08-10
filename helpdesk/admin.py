from django.contrib import admin
from .models import HelpTopic, SLAPlan, Ticket, TicketMessage, Attachment, CannedResponse, Tag, TicketEvent


@admin.register(HelpTopic)
class HelpTopicAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(SLAPlan)
class SLAPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "first_response_hours", "resolution_hours")


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0


class TicketMessageInline(admin.StackedInline):
    model = TicketMessage
    extra = 0
    show_change_link = True
    inlines = [AttachmentInline]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "customer", "status", "priority", "assignee", "updated_at")
    list_filter = ("status", "priority", "topic")
    search_fields = ("subject", "description", "customer__email")
    filter_horizontal = ("watchers", "tags")


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "author", "is_internal", "created_at")
    search_fields = ("body",)


admin.site.register(Attachment)
admin.site.register(CannedResponse)
admin.site.register(Tag)
admin.site.register(TicketEvent)