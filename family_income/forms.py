from django import forms

from .models import FamilyIncomeCase, FamilyIncomeDocument, IncomeEvidence, IncomeYear


class FamilyIncomeDecisionForm(forms.Form):
    amount_per_member = forms.DecimalField(
        label="Среднемесячный доход на члена семьи, ₽",
        max_digits=14, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )
    comment = forms.CharField(label="Пояснение", widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault(
                "class", "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )


class FamilyIncomeCaseForm(forms.ModelForm):
    class Meta:
        model = FamilyIncomeCase
        fields = ("family_members_count", "family_members_description", "family_characteristics")
        widgets = {
            "family_members_count": forms.NumberInput(attrs={"min": 1, "class": "form-control w-auto"}),
            "family_members_description": forms.Textarea(attrs={"rows": 4}),
            "family_characteristics": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name != "family_members_count":
                field.widget.attrs.setdefault("class", "form-control")


class FamilyIncomeCaseStaffForm(FamilyIncomeCaseForm):
    """Служебная форма без полей пользовательского расчёта."""


class FamilyIncomeDocumentReviewForm(forms.ModelForm):
    class Meta:
        model = FamilyIncomeDocument
        fields = ("review_status", "staff_comment")
        widgets = {
            "review_status": forms.Select(attrs={"class": "form-select"}),
            "staff_comment": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("review_status") == FamilyIncomeDocument.ReviewStatus.CLARIFICATION
            and not cleaned_data.get("staff_comment", "").strip()
        ):
            self.add_error(
                "staff_comment",
                "Напишите, что именно нужно уточнить соискателю.",
            )
        return cleaned_data


class IncomeEvidenceStaffForm(forms.ModelForm):
    class Meta:
        model = IncomeEvidence
        fields = (
            "year",
            "owner_name",
            "gross_amount",
            "net_amount",
            "average_monthly_amount",
            "months_received",
            "absence_reason",
            "staff_decision_comment",
        )
        widgets = {
            "year": forms.Select(attrs={"class": "form-select"}),
            "owner_name": forms.TextInput(attrs={"class": "form-control"}),
            "gross_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "net_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "average_monthly_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "months_received": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 12}),
            "absence_reason": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "staff_decision_comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class BaseFamilyIncomeDocumentForm(forms.Form):
    file = forms.FileField(label="Файл")

    def __init__(self, *args, require_file=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].required = require_file
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif not field.widget.attrs.get("class"):
                field.widget.attrs.setdefault("class", "form-control")


class FamilyCharacteristicDocumentForm(BaseFamilyIncomeDocumentForm):
    candidate_comment = forms.CharField(
        label="Какой это документ",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class IncomeDocumentForm(BaseFamilyIncomeDocumentForm):
    year = forms.ModelChoiceField(label="Год", queryset=IncomeYear.objects.none())
    owner_name = forms.CharField(label="Чей документ", max_length=255)
    gross_amount = forms.DecimalField(label="Общая сумма дохода", max_digits=14, decimal_places=2, required=False)
    net_amount = forms.DecimalField(label="Сумма за вычетом налога", max_digits=14, decimal_places=2, required=False)
    average_monthly_amount = forms.DecimalField(label="Средний доход в месяц", max_digits=14, decimal_places=2, required=False)

    def __init__(self, *args, evidence=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["year"].queryset = IncomeYear.objects.filter(is_active=True)
        if evidence:
            for field_name in ("year", "owner_name", "gross_amount", "net_amount", "average_monthly_amount"):
                self.initial[field_name] = getattr(evidence, field_name)


class SocialBenefitDocumentForm(BaseFamilyIncomeDocumentForm):
    recipient_name = forms.CharField(label="Чья справка", max_length=255)
    benefit_description = forms.CharField(
        label="Описание выплат",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, evidence=None, **kwargs):
        super().__init__(*args, **kwargs)
        if evidence:
            for field_name in ("recipient_name", "benefit_description"):
                self.initial[field_name] = getattr(evidence, field_name)


class OtherDocumentForm(BaseFamilyIncomeDocumentForm):
    candidate_comment = forms.CharField(
        label="Что это за документ",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


DOCUMENT_FORM_CLASSES = {
    FamilyIncomeDocument.Category.FAMILY_CHARACTERISTIC: FamilyCharacteristicDocumentForm,
    FamilyIncomeDocument.Category.INCOME: IncomeDocumentForm,
    FamilyIncomeDocument.Category.SOCIAL_BENEFIT: SocialBenefitDocumentForm,
    FamilyIncomeDocument.Category.OTHER: OtherDocumentForm,
}


def document_form_for_category(category, *args, evidence=None, **kwargs):
    try:
        form_class = DOCUMENT_FORM_CLASSES[category]
    except KeyError as exc:
        raise ValueError("Неизвестная категория документа.") from exc
    if category in {
        FamilyIncomeDocument.Category.INCOME,
        FamilyIncomeDocument.Category.SOCIAL_BENEFIT,
    }:
        return form_class(*args, evidence=evidence, **kwargs)
    return form_class(*args, **kwargs)
