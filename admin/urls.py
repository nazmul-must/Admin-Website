"""
URL configuration for admin project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib.auth import views as auth_views
from django.urls import path

from accounts import views as accounts
from accounts.forms import LoginForm
from analytics import views as analytics
from tenants.views import org_detail_view, org_list, user_detail_view, user_list

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(authentication_form=LoginForm, redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', analytics.overview, name='overview'),
    path('orgs/', org_list, name='org-list'),
    path('orgs/<str:org_id>/', org_detail_view, name='org-detail'),
    path('users/', user_list, name='user-list'),
    path('users/<str:user_id>/', user_detail_view, name='user-detail'),
    path('analytics/growth/', analytics.growth, name='growth'),
    path('analytics/billing/', analytics.billing, name='billing'),
    path('analytics/ai/', analytics.ai_usage, name='ai-usage'),
    path('analytics/engagement/', analytics.engagement, name='engagement'),
    path('analytics/access/', analytics.access, name='access'),
    path('employees/', accounts.employee_list, name='employee-list'),
    path('employees/new/', accounts.employee_add, name='employee-add'),
    path('employees/<int:pk>/', accounts.employee_edit, name='employee-edit'),
    path('employees/<int:pk>/password/', accounts.employee_password, name='employee-password'),
]
