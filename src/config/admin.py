from django.conf import settings


def environment_callback(request):
    if settings.DEBUG:
        return ['Desenvolvimento', 'warning']
    return ['Produção', 'success']
