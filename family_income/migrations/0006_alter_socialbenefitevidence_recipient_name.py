from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("family_income", "0005_familyincomedocument_clarification_dates")]

    operations = [
        migrations.AlterField(
            model_name="socialbenefitevidence",
            name="recipient_name",
            field=models.CharField(max_length=255, verbose_name="Чья справка"),
        ),
    ]
