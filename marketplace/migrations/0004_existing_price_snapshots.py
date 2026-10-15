from django.db import migrations


def fill_prices(apps, schema_editor):
    alias = schema_editor.connection.alias
    Order = apps.get_model('marketplace', 'Order')
    Rental = apps.get_model('marketplace', 'Rental')
    for order in Order.objects.using(alias).filter(agreed_price__isnull=True).select_related('service').iterator():
        Order.objects.using(alias).filter(pk=order.pk).update(agreed_price=order.service.price)
    for rental in Rental.objects.using(alias).filter(agreed_rate__isnull=True).select_related('offer').iterator():
        Rental.objects.using(alias).filter(pk=rental.pk).update(agreed_rate=rental.offer.rate)


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0003_alter_application_status')]
    operations = [migrations.RunPython(fill_prices, migrations.RunPython.noop)]
