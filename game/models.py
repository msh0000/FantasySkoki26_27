from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from . import bonuses, rules


class Player(models.Model):
    """Gracz gry (jeden z 7 znajomych), powiązany z kontem logowania."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField("nazwa", max_length=50)
    order = models.PositiveSmallIntegerField(
        "pozycja w bazie", default=0, help_text="Rozstrzyga remisy w rankingu (mniejsza = wyżej)."
    )

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class Jumper(models.Model):
    GENDERS = [(rules.MALE, "Mężczyzna"), (rules.FEMALE, "Kobieta")]

    name = models.CharField("imię i nazwisko", max_length=100)
    country = models.CharField("kraj (kod FIS)", max_length=3)
    gender = models.CharField("płeć", max_length=1, choices=GENDERS)
    owner = models.ForeignKey(
        Player, null=True, blank=True, on_delete=models.SET_NULL, related_name="jumpers"
    )
    external_id = models.CharField("id w źródle wyników", max_length=50, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.country})"


class Weekend(models.Model):
    name = models.CharField(max_length=100)
    place = models.CharField("miejsce", max_length=100, blank=True)
    start_date = models.DateField("początek")

    class Meta:
        ordering = ["start_date"]

    def __str__(self):
        return f"{self.name} ({self.start_date:%d.%m.%Y})"

    def first_start(self):
        return self.competitions.order_by("start_at").values_list("start_at", flat=True).first()

    def is_locked(self, now=None) -> bool:
        """Transfery i bonusy weekendowe są zablokowane od startu pierwszej serii."""
        first = self.first_start()
        return first is not None and (now or timezone.now()) >= first


class Competition(models.Model):
    TYPES = [(rules.MALE, "Mężczyźni"), (rules.FEMALE, "Kobiety"), (rules.MIXED, "Mieszany")]
    SERIES = [(rules.WC, "Puchar Świata"), (rules.TCS, "TCS"), (rules.WCH, "Mistrzostwa Świata")]

    weekend = models.ForeignKey(Weekend, on_delete=models.CASCADE, related_name="competitions")
    name = models.CharField(max_length=100)
    gender = models.CharField("typ", max_length=1, choices=TYPES)
    series = models.CharField("cykl", max_length=3, choices=SERIES, default=rules.WC)
    start_at = models.DateTimeField("start pierwszej serii")
    counts = models.BooleanField("liczy się do gry", default=True)
    roster_locked = models.BooleanField("składy zamrożone", default=False)
    external_id = models.CharField("id w źródle wyników", max_length=50, blank=True)

    class Meta:
        ordering = ["start_at"]

    def __str__(self):
        return f"{self.name} - {self.weekend.name}"

    def is_locked(self, now=None) -> bool:
        return (now or timezone.now()) >= self.start_at


class RosterEntry(models.Model):
    """Zamrożony skład gracza na konkretny konkurs (zrzut z chwili startu)."""

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="rosters")
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    jumper = models.ForeignKey(Jumper, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["competition", "jumper"], name="unique_jumper_per_competition_roster"
            )
        ]


class Result(models.Model):
    """Miejsce zawodnika w konkursie, w klasyfikacji swojej płci (puste = brak punktów)."""

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="results")
    jumper = models.ForeignKey(Jumper, on_delete=models.CASCADE)
    rank = models.PositiveSmallIntegerField("miejsce", null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["competition", "jumper"], name="unique_result")
        ]


class Transfer(models.Model):
    weekend = models.ForeignKey(Weekend, on_delete=models.CASCADE, related_name="transfers")
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    out_jumper = models.ForeignKey(Jumper, on_delete=models.CASCADE, related_name="+")
    in_jumper = models.ForeignKey(Jumper, on_delete=models.CASCADE, related_name="+")
    made_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class QueueSlot(models.Model):
    """Miejsce gracza w kolejce transferów danego weekendu."""

    PENDING, DONE, SKIPPED = "pending", "done", "skipped"
    STATUSES = [(PENDING, "Oczekuje"), (DONE, "Zrobił transfer"), (SKIPPED, "Pominął")]

    weekend = models.ForeignKey(Weekend, on_delete=models.CASCADE, related_name="queue")
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    position = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)

    class Meta:
        ordering = ["weekend", "position"]
        constraints = [
            models.UniqueConstraint(fields=["weekend", "player"], name="unique_queue_player")
        ]


class BonusUse(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="bonus_uses")
    code = models.CharField("bonus", max_length=20, choices=bonuses.CHOICES)
    weekend = models.ForeignKey(Weekend, on_delete=models.CASCADE, related_name="bonus_uses")
    competition = models.ForeignKey(
        Competition, null=True, blank=True, on_delete=models.CASCADE, related_name="bonus_uses"
    )
    target_player = models.ForeignKey(
        Player, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    target_jumper = models.ForeignKey(
        Jumper, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    give_jumper = models.ForeignKey(
        Jumper, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    picks = models.JSONField(
        "wybrani zawodnicy (id)",
        default=list,
        blank=True,
        help_text="Typer: 5 id, Drużyna marzeń: 6 id.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.player}: {bonuses.SPECS[self.code].label}"

    def to_bonus(self) -> bonuses.Bonus:
        return bonuses.Bonus(
            code=self.code,
            player_id=self.player_id,
            weekend_id=self.weekend_id,
            competition_id=self.competition_id,
            target_player_id=self.target_player_id,
            target_jumper_id=self.target_jumper_id,
            give_jumper_id=self.give_jumper_id,
            picks=tuple(self.picks or ()),
        )

    def clean(self):
        if not (self.player_id and self.weekend_id and self.code):
            return
        others = BonusUse.objects.exclude(pk=self.pk)
        errors = bonuses.validate_bonus_use(self.to_bonus(), [b.to_bonus() for b in others])
        if errors:
            raise ValidationError(errors)


class Adjustment(models.Model):
    """Ręczna korekta punktów gracza w weekendzie (np. poprawka admina)."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    weekend = models.ForeignKey(Weekend, on_delete=models.CASCADE, related_name="adjustments")
    points = models.DecimalField(max_digits=6, decimal_places=1)
    reason = models.CharField(max_length=200, blank=True)
