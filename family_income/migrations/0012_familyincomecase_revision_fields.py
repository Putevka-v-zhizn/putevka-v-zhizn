from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("family_income", "0011_familyincomecase_review_timestamps"),
    ]

    operations = [
        migrations.AddField(
            model_name="familyincomecase",
            name="revision_comment",
            field=models.TextField(blank=True, verbose_name="Комментарий к доработке"),
        ),
        migrations.AddField(
            model_name="familyincomecase",
            name="revision_requested_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Запрошена доработка"),
        ),
    ]
