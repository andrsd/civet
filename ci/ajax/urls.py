from django.conf.urls import url
from . import views

urlpatterns = [
  url(r'^result_output/', views.get_result_output, name='get_result_output'),
  url(r'^main_update/', views.main_update, name='main_update'),
  url(r'^main_update_html/', views.main_update_html, name='main_update_html'),
  url(r'^pr_update/(?P<pr_id>[0-9]+)/$', views.pr_update, name='pr_update'),
  url(r'^event_update/(?P<event_id>[0-9]+)/$', views.event_update, name='event_update'),
  url(r'^job_results/', views.job_results, name='job_results'),
  url(r'^job_results_html/', views.job_results_html, name='job_results_html'),
  ]
