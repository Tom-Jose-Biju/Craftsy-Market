from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='delivery',
            name='destination_lat',
        ),
        migrations.RemoveField(
            model_name='delivery',
            name='destination_lng',
        ),
    ] 