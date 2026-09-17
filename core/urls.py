from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path("reviews/submit/", views.submit_review, name="submit_review"),
    
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
    
    path("portal/login/", views.portal_login, name="portal_login"),
    path("portal/logout/", views.portal_logout, name="portal_logout"),
    path("portal/", views.portal_dashboard, name="portal_dashboard"),
    path("portal/documents/<int:pk>/delete/", views.portal_document_delete, name="portal_document_delete"),
    path("portal/activity/", views.portal_activity_log, name="portal_activity_log"),
    
    path('sw.js', views.service_worker, name='service_worker'),
]