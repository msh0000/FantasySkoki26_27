from django.contrib import admin, messages

from . import services
from .models import (
    Adjustment,
    BonusUse,
    Competition,
    Jumper,
    Player,
    QueueSlot,
    Result,
    Transfer,
    Weekend,
)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "order"]


@admin.register(Jumper)
class JumperAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "gender", "owner", "active"]
    list_filter = ["gender", "owner", "active", "country"]
    search_fields = ["name"]


class ResultInline(admin.TabularInline):
    model = Result
    extra = 0
    autocomplete_fields = ["jumper"]


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ["name", "weekend", "gender", "series", "start_at", "counts", "roster_locked"]
    list_filter = ["weekend", "gender", "series"]
    inlines = [ResultInline]
    actions = ["snapshot_rosters"]

    @admin.action(description="Zamroź składy graczy na te konkursy")
    def snapshot_rosters(self, request, queryset):
        for competition in queryset:
            services.snapshot_rosters(competition)
        self.message_user(request, f"Zamrożono składy: {queryset.count()} konkursów.")


class QueueInline(admin.TabularInline):
    model = QueueSlot
    extra = 0


@admin.register(Weekend)
class WeekendAdmin(admin.ModelAdmin):
    list_display = ["name", "place", "start_date"]
    inlines = [QueueInline]
    actions = ["build_queue"]

    @admin.action(description="Utwórz kolejkę transferów (wg rankingu sprzed weekendu)")
    def build_queue(self, request, queryset):
        for weekend in queryset:
            services.build_queue(weekend)
        self.message_user(request, "Kolejka utworzona.", messages.SUCCESS)


@admin.register(BonusUse)
class BonusUseAdmin(admin.ModelAdmin):
    list_display = ["player", "code", "weekend", "competition", "target_player", "target_jumper"]
    list_filter = ["code", "weekend", "player"]


admin.site.register(Transfer)
admin.site.register(Adjustment)
