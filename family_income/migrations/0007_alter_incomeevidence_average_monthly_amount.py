from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("family_income", "0006_alter_socialbenefitevidence_recipient_name")]

    operations = [
        migrations.AlterField(
            model_name="incomeevidence",
            name="average_monthly_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=14,
                null=True,
                verbose_name="Средний доход в месяц",
            ),
        ),
    ]
