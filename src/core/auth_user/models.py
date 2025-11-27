from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    UserTypeChoices = [
        ('admin', 'Admin'),
        ('teacher', 'Teacher'),
        ('student', 'Student'),
    ]
    email = models.EmailField(unique=True)
    user_type = models.CharField(max_length=20, choices=UserTypeChoices, default='student')
