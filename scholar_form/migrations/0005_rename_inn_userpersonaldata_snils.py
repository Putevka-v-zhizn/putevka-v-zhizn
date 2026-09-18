from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scholar_form", "0004_userpersonaldata_submitted_by_user_at"),
    ]

    operations = [
        migrations.RenameField(
            model_name="userpersonaldata",
            old_name="inn",
            new_name="snils",
        ),
        migrations.AlterField(
            model_name="userpersonaldata",
            name="snils",
            field=models.CharField("СНИЛС", blank=True, max_length=20),
        ),
    ]
