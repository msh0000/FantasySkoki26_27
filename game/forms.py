from django import forms
from django.db.models import Q

from .models import Jumper

MEN_SLOTS = 5
WOMEN_SLOTS = 1


class DraftForm(forms.Form):
    """Skład jednego gracza: 5 skoczków i 1 skoczkini. Puste pola są dozwolone (draft w toku)."""

    def __init__(self, player, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.player = player
        owned = Jumper.objects.filter(owner=player)
        current_men = list(owned.filter(gender="M").order_by("name"))
        current_women = list(owned.filter(gender="K").order_by("name"))
        # Zawodnicy, którzy nie zmieszczą się w polach, zostaną zwolnieni przy zapisie.
        self.extra = current_men[MEN_SLOTS:] + current_women[WOMEN_SLOTS:]

        def options(gender):
            return Jumper.objects.filter(gender=gender).filter(Q(active=True) | Q(owner=player))

        for index in range(MEN_SLOTS):
            self.fields[f"m{index + 1}"] = forms.ModelChoiceField(
                options("M"),
                required=False,
                label=f"Skoczek {index + 1}",
                initial=current_men[index] if index < len(current_men) else None,
            )
        for index in range(WOMEN_SLOTS):
            self.fields[f"k{index + 1}"] = forms.ModelChoiceField(
                options("K"),
                required=False,
                label="Skoczkini",
                initial=current_women[index] if index < len(current_women) else None,
            )

    def chosen(self) -> list[Jumper]:
        return [j for j in self.cleaned_data.values() if j is not None]
