from django.db import migrations


class Migration(migrations.Migration):
    # Commit the subject reassignment before altering Course on PostgreSQL.
    dependencies = [("my_study", "0008_olympiad_subjects")]
    operations = [migrations.RemoveField(model_name="course", name="is_olympiad")]
