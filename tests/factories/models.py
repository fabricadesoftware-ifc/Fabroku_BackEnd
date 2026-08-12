"""Factory definitions for all models."""
import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from applications.models import App, AppProcessScale, AppStatus
from identity.models import CLIToken
from projects.models import Project
from service_mgmt.models import Service, ServiceType

User = get_user_model()


class UserFactory(DjangoModelFactory):
    """Factory for User model."""

    class Meta:
        model = User

    email = factory.Sequence(lambda n: f'user{n}@example.com')
    name = factory.Faker('name')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')


class ProjectFactory(DjangoModelFactory):
    """Factory for Project model."""

    class Meta:
        model = Project

    name = factory.Faker('word')

    @factory.post_generation
    def users(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            self.users.add(*extracted)
        else:
            self.users.add(UserFactory())


class AppFactory(DjangoModelFactory):
    """Factory for App model."""

    class Meta:
        model = App

    name = factory.Sequence(lambda n: f'app-{n}')
    project = factory.SubFactory(ProjectFactory)
    git = factory.Faker('url')
    branch = 'main'
    status = AppStatus.RUNNING


class ServiceFactory(DjangoModelFactory):
    """Factory for Service model."""

    class Meta:
        model = Service

    name = factory.Sequence(lambda n: f'service-{n}')
    project = factory.LazyAttribute(lambda o: o.app.project)
    app = factory.SubFactory(AppFactory)
    password = factory.Faker('password', length=20)
    host = factory.Faker('hostname')
    port = 5432
    service_type = ServiceType.POSTGRES


class AppProcessScaleFactory(DjangoModelFactory):
    """Factory for AppProcessScale model."""

    class Meta:
        model = AppProcessScale

    app = factory.SubFactory(AppFactory)
    process_name = 'web'
    desired_quantity = 1


class CLITokenFactory(DjangoModelFactory):
    """Factory for CLIToken model."""

    class Meta:
        model = CLIToken

    user = factory.SubFactory(UserFactory)
    name = factory.Faker('word')
