from django.db import migrations, models


def backfill_review_timestamps(apps, schema_editor):
    FamilyIncomeCase = apps.get_model("family_income", "FamilyIncomeCase")
    FamilyIncomeDocument = apps.get_model("family_income", "FamilyIncomeDocument")

    for case in FamilyIncomeCase.objects.filter(status__in=("pending_review", "approved")):
        case.last_submitted_at = case.updated_at
        if case.status == "approved":
            case.approved_at = case.updated_at
        case.save(update_fields=("last_submitted_at", "approved_at"))

    revision_case_ids = (
        FamilyIncomeDocument.objects
        .filter(clarification_requested_at__isnull=False)
        .values_list("case_id", flat=True)
        .distinct()
    )
    for case in FamilyIncomeCase.objects.filter(status="revision", pk__in=revision_case_ids):
        case.last_submitted_at = case.updated_at
        case.save(update_fields=("last_submitted_at",))


class Migration(migrations.Migration):
    dependencies = [
        ("family_income", "0010_copy_latest_current_income"),
    ]

    operations = [
        migrations.AddField(
            model_name="familyincomecase",
            name="last_submitted_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="Последняя отправка на проверку",
            ),
        ),
        migrations.AddField(
            model_name="familyincomecase",
            name="approved_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Подтверждено",
            ),
        ),
        migrations.RunPython(backfill_review_timestamps, migrations.RunPython.noop),
    ]
