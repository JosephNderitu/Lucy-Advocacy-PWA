from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    #conversation and chat message endpoints
    path('api/contact/send-code/', views.send_verification_code, name='send_verification_code'),
    path('api/contact/verify-code/', views.verify_code, name='verify_code'),
    path('api/contact/messages/', views.get_messages, name='get_messages'),
    path('api/contact/send-message/', views.send_message, name='send_message'),
    path('api/contact/logout/', views.contact_logout, name='contact_logout'),
    
    path("newsletter/subscribe/", views.newsletter_subscribe, name="newsletter_subscribe"),
    path("newsletter/unsubscribe/<str:token>/", views.newsletter_unsubscribe, name="newsletter_unsubscribe"),
]