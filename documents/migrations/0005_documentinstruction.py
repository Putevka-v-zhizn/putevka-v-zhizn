from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0004_document_slot_label"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentInstruction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True, verbose_name="Показывать плашку")),
                ("title", models.CharField(default="Инструкция к документам", max_length=120, verbose_name="Заголовок")),
                ("text", models.TextField(blank=True, default="Перед загрузкой документов ознакомьтесь с инструкцией.", verbose_name="Текст")),
                ("url", models.URLField(blank=True, default="", verbose_name="Ссылка на инструкцию")),
                ("button_text", models.CharField(default="Открыть инструкцию", max_length=60, verbose_name="Текст кнопки")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Инструкция к документам",
                "verbose_name_plural": "Инструкция к документам",
            },
        ),
    ]
