from django.db import models


class Network(models.Model):
	name = models.CharField(max_length=100, unique=True, verbose_name="Nome da Rede")
	description = models.TextField(blank=True, verbose_name="Descrição")

	class Meta:
		verbose_name = "Rede"
		verbose_name_plural = "Redes"

	def __str__(self) -> str:
		return self.name 