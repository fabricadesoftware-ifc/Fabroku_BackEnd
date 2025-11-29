from django.db import models

from core.apps.models import App


# Create your models here.
class Logs(models.Model):
    app = models.ForeignKey(App, on_delete=models.CASCADE)
    log = models.TextField()  # aramazena cada linha do log
    created_at = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=50)
