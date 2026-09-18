from django.db import migrations


def create_income_years(apps, schema_editor):
    IncomeYear = apps.get_model("family_income", "IncomeYear")
    for year, sort_order in ((2025, 1), (2026, 2)):
        IncomeYear.objects.get_or_create(
            year=year,
            defaults={"is_active": True, "sort_order": sort_order},
        )


def remove_income_years(apps, schema_editor):
    IncomeYear = apps.get_model("family_income", "IncomeYear")
    IncomeYear.objects.filter(year__in=(2025, 2026)).delete()


class Migration(migrations.Migration):
    dependencies = [("family_income", "0001_initial")]

    operations = [migrations.RunPython(create_income_years, remove_income_years)]
