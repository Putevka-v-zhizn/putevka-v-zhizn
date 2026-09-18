from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0005_documentinstruction"),
    ]

    operations = [
        migrations.AddField(
            model_name="documenttype",
            name="available_to_alternative",
            field=models.BooleanField(
                default=False,
                verbose_name="Доступен альтернативному треку",
            ),
        ),
    ]
