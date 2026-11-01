from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("psm", "0004_reportschedule_and_reportrun_result"),
    ]

    operations = [
        migrations.RenameField(
            model_name="communication",
            old_name="sent_at",
            new_name="created_at",
        ),
        migrations.AlterField(
            model_name="communication",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AlterField(
            model_name="communication",
            name="recipient_id",
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="communication",
            name="recipient_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="communication",
            name="delivery_status",
            field=models.CharField(db_index=True, default="pending", max_length=16),
        ),
        migrations.AddField(
            model_name="communication",
            name="delivery_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="communication",
            name="last_error",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="communication",
            name="delivered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="communication",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="vendor",
            name="contact_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
