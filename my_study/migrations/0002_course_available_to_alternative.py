from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("my_study", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="available_to_alternative",
            field=models.BooleanField(
                default=False,
                verbose_name="Доступен альтернативному треку",
            ),
        ),
    ]
