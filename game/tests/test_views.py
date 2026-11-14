import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_home_requires_login(client):
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert reverse("login") in response["Location"]


@pytest.mark.django_db
def test_home_for_logged_in_user(client, django_user_model):
    django_user_model.objects.create_user("ania", password="tajne-haslo-123")
    client.login(username="ania", password="tajne-haslo-123")
    assert client.get(reverse("home")).status_code == 200
