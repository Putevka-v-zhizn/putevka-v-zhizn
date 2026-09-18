from django.db import migrations


def copy_latest_current_income(apps, schema_editor):
    Decision = apps.get_model("family_income", "FamilyIncomeDecision")
    decisions = Decision.objects.using(schema_editor.connection.alias)
    case_ids = decisions.filter(year__isnull=False).values_list("case_id", flat=True).distinct()
    for case_id in case_ids.iterator():
        if decisions.filter(case_id=case_id, year__isnull=True).exists():
            continue
        latest = decisions.filter(case_id=case_id).order_by("-updated_at", "-pk").first()
        current = decisions.create(
            case_id=case_id,
            amount_per_member=latest.amount_per_member,
            comment=latest.comment,
            is_low_income_recognized=latest.is_low_income_recognized,
            created_by_id=latest.created_by_id,
            updated_by_id=latest.updated_by_id,
        )
        decisions.filter(pk=current.pk).update(created_at=latest.created_at, updated_at=latest.updated_at)


class Migration(migrations.Migration):
    dependencies = [("family_income", "0009_alter_familyincomedecision_year_and_more")]
    operations = [migrations.RunPython(copy_latest_current_income, migrations.RunPython.noop)]
