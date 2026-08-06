from django.db import models


class CacheVersionIndex(models.Model):
    namespace = models.CharField(max_length=100, unique=True, db_index=True)
    version = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.namespace} (v{self.version})'

    class Meta:
        db_table = 'cache_version_indexes'
        verbose_name = 'Cache Version Index'
        verbose_name_plural = 'Cache Version Indexes'
