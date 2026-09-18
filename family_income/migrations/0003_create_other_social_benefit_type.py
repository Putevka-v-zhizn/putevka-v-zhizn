from django.db import migrations


def create_other_social_benefit_type(apps, schema_editor):
    SocialBenefitType = apps.get_model("family_income", "SocialBenefitType")
    SocialBenefitType.objects.get_or_create(
        name="Другое",
        defaults={"is_other": True, "is_active": True, "sort_order": 0},
    )


def remove_other_social_benefit_type(apps, schema_editor):
    SocialBenefitType = apps.get_model("family_income", "SocialBenefitType")
    SocialBenefitType.objects.filter(name="Другое", is_other=True).delete()


class Migration(migrations.Migration):
    dependencies = [("family_income", "0002_create_income_years")]

    operations = [migrations.RunPython(create_other_social_benefit_type, remove_other_social_benefit_type)]
