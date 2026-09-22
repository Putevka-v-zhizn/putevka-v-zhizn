from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scholar_form", "0005_rename_inn_userpersonaldata_snils"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpersonaldata",
            name="accepted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="Принято администратором",
            ),
        ),
    ]
