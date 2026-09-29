from django.db import migrations, models


def migrate_audience(apps, schema_editor):
    DocumentType = apps.get_model("documents", "DocumentType")
    DocumentType.objects.filter(available_to_alternative=True).update(audience="alternative")


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0007_alter_documentinstruction_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="documenttype",
            name="audience",
            field=models.CharField(
                choices=[
                    ("program", "Участники программы"),
                    ("alternative", "Альтернативный трек"),
                    ("all", "Обе группы"),
                ],
                default="program",
                max_length=16,
                verbose_name="Кому показывать",
            ),
        ),
        migrations.RunPython(migrate_audience, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="documenttype",
            name="available_to_alternative",
        ),
    ]
