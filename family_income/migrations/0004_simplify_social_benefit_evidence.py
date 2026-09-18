from django.db import migrations, models


def copy_social_benefit_description(apps, schema_editor):
    SocialBenefitEvidence = apps.get_model("family_income", "SocialBenefitEvidence")
    for evidence in SocialBenefitEvidence.objects.select_related("benefit_type"):
        if evidence.other_benefit_name:
            evidence.benefit_description = evidence.other_benefit_name
        elif evidence.benefit_type_id:
            evidence.benefit_description = evidence.benefit_type.name
        evidence.save(update_fields=("benefit_description",))


class Migration(migrations.Migration):
    dependencies = [("family_income", "0003_create_other_social_benefit_type")]

    operations = [
        migrations.AddField(
            model_name="socialbenefitevidence",
            name="benefit_description",
            field=models.TextField(blank=True, verbose_name="Описание выплат"),
        ),
        migrations.RunPython(copy_social_benefit_description, migrations.RunPython.noop),
        migrations.RemoveField(model_name="socialbenefitevidence", name="benefit_type"),
        migrations.RemoveField(model_name="socialbenefitevidence", name="other_benefit_name"),
        migrations.DeleteModel(name="SocialBenefitType"),
    ]
