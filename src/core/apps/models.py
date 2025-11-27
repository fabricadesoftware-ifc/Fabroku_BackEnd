from django.db import models

from core.project.models import Project


class App(models.Model):

    SATATUS_CHOICES = [
        ('running', 'Running'),
        ('stopped', 'Stopped'),
        ('error', 'Error'),
    ]
    name = models.CharField(max_length=255)
    git = models.URLField()
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=50, choices=SATATUS_CHOICES, default='stopped')
    domain = models.CharField(max_length=255, null=True, blank=True)
    port = models.IntegerField(null=True, blank=True)
    variables = models.JSONField(default=dict)
