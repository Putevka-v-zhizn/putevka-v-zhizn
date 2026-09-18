from django.db import migrations, models
from django.db.models import F


def set_requested_at_for_existing_clarifications(apps, schema_editor):
    FamilyIncomeDocument = apps.get_model("family_income", "FamilyIncomeDocument")
    FamilyIncomeDocument.objects.filter(
        review_status="clarification",
        clarification_requested_at__isnull=True,
    ).update(clarification_requested_at=F("updated_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("family_income", "0004_simplify_social_benefit_evidence"),
    ]

    operations = [
        migrations.AddField(
            model_name="familyincomedocument",
            name="candidate_response_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Соискатель сохранил ответ"),
        ),
        migrations.AddField(
            model_name="familyincomedocument",
            name="clarification_requested_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Запрошено уточнение"),
        ),
        migrations.RunPython(
            set_requested_at_for_existing_clarifications,
            migrations.RunPython.noop,
        ),
    ]
