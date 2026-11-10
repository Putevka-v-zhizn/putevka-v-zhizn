from django.db import migrations, models
import django.db.models.deletion


def remove_subjectless_directions(apps, schema_editor):
    # The discarded general olympiad direction has no EGE subject.
    Direction = apps.get_model("my_study", "PreparationDirection")
    Direction.objects.using(schema_editor.connection.alias).filter(subject__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("my_study", "0005_alter_preparationdirection_options")]
    operations = [
        migrations.RemoveConstraint(model_name="preparationdirection", name="unique_preparation_olympiad"),
        migrations.RemoveConstraint(model_name="preparationdirection", name="preparation_direction_kind"),
        migrations.RunPython(remove_subjectless_directions, migrations.RunPython.noop),
        migrations.RemoveField(model_name="course", name="is_olympiad"),
        migrations.RemoveField(model_name="preparationdirection", name="is_olympiad"),
        migrations.AlterField(model_name="preparationdirection", name="subject", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="my_study.subject")),
        migrations.AlterModelOptions(name="preparationdirection", options={"ordering": ["subject__name"], "verbose_name": "Направление подготовки", "verbose_name_plural": "Направления подготовки"}),
    ]
