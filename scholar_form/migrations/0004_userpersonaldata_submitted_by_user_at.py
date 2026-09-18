from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scholar_form", "0003_userinfo_after_interview_documents_ready_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpersonaldata",
            name="submitted_by_user_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="Заполнено пользователем",
            ),
        ),
    ]
