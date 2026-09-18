from django.db import migrations, models


def deactivate_legacy_active_instructions(apps, schema_editor):
    FamilyIncomeInstruction = apps.get_model("family_income", "FamilyIncomeInstruction")
    FamilyIncomeInstruction.objects.filter(status="published").update(status="draft")


class Migration(migrations.Migration):
    dependencies = [("family_income", "0007_alter_incomeevidence_average_monthly_amount")]

    operations = [
        migrations.AddField(
            model_name="familyincomeinstruction",
            name="file",
            field=models.FileField(blank=True, upload_to="family_income/instructions/", verbose_name="Файл"),
        ),
        migrations.AddField(
            model_name="familyincomeinstruction",
            name="text",
            field=models.TextField(blank=True, verbose_name="Текст"),
        ),
        migrations.AddField(
            model_name="familyincomeinstruction",
            name="title",
            field=models.CharField(blank=True, max_length=200, verbose_name="Заголовок"),
        ),
        migrations.AlterField(
            model_name="familyincomeinstruction",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Черновик"),
                    ("published", "Активна"),
                    ("archived", "Архив"),
                ],
                default="draft",
                max_length=16,
                verbose_name="Статус",
            ),
        ),
        migrations.AlterField(
            model_name="familyincomeinstruction",
            name="url",
            field=models.URLField(blank=True, verbose_name="Ссылка"),
        ),
        migrations.RunPython(deactivate_legacy_active_instructions, migrations.RunPython.noop),
    ]
