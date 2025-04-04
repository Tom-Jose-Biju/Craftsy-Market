# Generated by Django 5.0.6 on 2025-02-19 14:40

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_remove_deliveryrating_delivery_partner_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='deliverypartner',
            name='user',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='delivery_partner', to=settings.AUTH_USER_MODEL),
        ),
    ]
