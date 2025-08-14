from django.db import models


class Deploy(models.Model):
	STATUS_CHOICES = [
		("rascunho", "Rascunho"),
		("em_andamento", "Em andamento"),
		("pronto", "Pronto"),
		("abortado", "Abortado"),
		("erro", "Erro"),
	]

	app_name = models.CharField(max_length=200)
	github_repo = models.URLField(blank=True, null=True)
	github_branch = models.CharField(max_length=100, default="main", blank=True, null=True)
	dockerfile_path = models.CharField(max_length=255, blank=True, null=True)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="rascunho")
	analysis = models.JSONField(blank=True, null=True)
	logs = models.TextField(blank=True, null=True)
	error_message = models.TextField(blank=True, null=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-updated_at"]
		verbose_name = "Deploy"
		verbose_name_plural = "Deploys"

	def __str__(self) -> str:
		return f"{self.app_name}@{self.github_branch or 'latest'} - {self.status}"


