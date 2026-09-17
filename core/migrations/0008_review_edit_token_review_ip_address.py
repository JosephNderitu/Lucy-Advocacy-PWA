import uuid
from django.db import migrations, models


def generate_unique_tokens(apps, schema_editor):
    Review = apps.get_model('core', 'Review')
    for review in Review.objects.all():
        review.edit_token = uuid.uuid4()
        review.save(update_fields=['edit_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_review'),
    ]

    operations = [
        migrations.AddField(
            model_name='review',
            name='edit_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='review',
            name='ip_address',
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.RunPython(generate_unique_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='review',
            name='edit_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]