from django.test import TestCase, Client
from django.test.client import RequestFactory
from django.core.urlresolvers import reverse
from django.http import HttpResponseNotAllowed, HttpResponseBadRequest
from django.conf import settings
import json, os, shutil
from mock import patch
from ci import models
from ci.client import views
from ci.recipe import file_utils
from ci.tests import utils

class ViewsTestCase(TestCase):
  fixtures = ['base']

  def setUp(self):
    self.client = Client()
    self.factory = RequestFactory()
    settings.REMOTE_UPDATE = False
    settings.INSTALLED_GITSERVERS = [settings.GITSERVER_GITHUB,]
    self.recipe_dir, self.repo = utils.create_recipe_dir()
    self.orig_recipe_dir = settings.RECIPE_BASE_DIR
    settings.RECIPE_BASE_DIR = self.recipe_dir

  def tearDown(self):
    shutil.rmtree(self.recipe_dir)
    settings.RECIPE_BASE_DIR = self.orig_recipe_dir

  def get_file(self, filename):
    dirname, fname = os.path.split(os.path.abspath(__file__))
    with open(dirname + '/' + filename, 'r') as f:
      js = f.read()
      return js

  def test_client_ip(self):
    request = self.factory.get('/')
    request.META['REMOTE_ADDR'] = '1.1.1.1'
    ip = views.get_client_ip(request)
    self.assertEqual('1.1.1.1', ip)
    request.META['HTTP_X_FORWARDED_FOR'] = '2.2.2.2'
    ip = views.get_client_ip(request)
    self.assertEqual('2.2.2.2', ip)

  def test_ready_jobs(self):
    url = reverse('ci:client:ready_jobs', args=['123', 'client'])
    # only get allowed
    response = self.client.post(url)
    self.assertEqual(response.status_code, 405) # not allowed

    # valid request, but no user with build key, so no jobs
    response = self.client.get(url)
    self.assertEqual(response.status_code, 200)
    data = json.loads(response.content)
    self.assertIn('jobs', data)
    self.assertEqual(len(data['jobs']), 0)

    user = utils.get_test_user()
    job = utils.create_job(user=user)
    job.ready = True
    job.active = True
    job.save()
    r2 = utils.create_recipe(name='recipe2', user=user)
    r3 = utils.create_recipe(name='recipe3', user=user)
    r4 = utils.create_recipe(name='recipe4', user=user)
    job2 = utils.create_job(recipe=r2, user=user)
    job3 = utils.create_job(recipe=r3, user=user)
    job4 = utils.create_job(recipe=r4, user=user)
    job2.ready = True
    job2.active = True
    job2.save()
    job3.ready = True
    job3.active = True
    job3.save()
    job4.ready = True
    job4.active = True
    job4.save()
    r2.priority = 10
    r2.save()
    r3.priority = 5
    r3.save()
    job.recipe.priority = 1
    job.recipe.save()
    r4.priority = 1
    r4.save()

    # valid request with a ready job
    url = reverse('ci:client:ready_jobs', args=[user.build_key, 'client'])
    response = self.client.get(url)
    self.assertEqual(response.status_code, 200)
    data = json.loads(response.content)
    self.assertIn('jobs', data)
    self.assertEqual(len(data['jobs']), 4)
    self.assertEqual(data['jobs'][0]['id'], job2.pk)
    self.assertEqual(data['jobs'][1]['id'], job3.pk)
    # two jobs with the same priorty, the one created first should run first
    self.assertEqual(data['jobs'][2]['id'], job.pk)
    self.assertEqual(data['jobs'][3]['id'], job4.pk)

  def json_post_request(self, data):
    jdata = json.dumps(data)
    return self.factory.post('/', jdata, content_type='application/json')

  def client_post_json(self, url, data):
    jdata = json.dumps(data)
    return self.client.post(url, jdata, content_type='application/json')

  def test_check_post(self):
    # only post allowed
    request = self.factory.get('/')
    required = ['foo',]
    data, response = views.check_post(request, required)
    self.assertEqual(data, None)
    self.assertTrue(isinstance(response, HttpResponseNotAllowed))

    # bad json decoding
    request = self.factory.post('/', {'bar': 'bar'}, content_type='text/html')
    data, response = views.check_post(request, required)
    self.assertEqual(data, None)
    self.assertTrue(isinstance(response, HttpResponseBadRequest))

    # should be successful
    request = self.json_post_request({'foo': 'bar'})
    data, response = views.check_post(request, required)
    self.assertNotEqual(data, None)
    self.assertEqual(None, response)

    # failed because we don't have the right data
    request = self.json_post_request({'bar': 'bar'})
    data, response = views.check_post(request, required)
    self.assertNotEqual(data, None)
    self.assertTrue(isinstance(response, HttpResponseBadRequest))

  @patch.object(file_utils, 'get_contents')
  def test_get_job_info(self, contents_mock):
    contents_mock.return_value = 'contents'
    user = utils.get_test_user()
    job = utils.create_job(user=user)
    utils.create_prestepsource(recipe=job.recipe)
    step = utils.create_step(recipe=job.recipe)
    utils.create_step_environment(step=step)
    utils.create_recipe_environment(recipe=job.recipe)
    self.assertEqual(job.recipe_sha, "")
    data = views.get_job_info(job)
    job.refresh_from_db()
    self.assertNotEqual(job.recipe_sha, "")
    # hex shas are 40 characters
    self.assertEqual(len(job.recipe_sha), 40)
    self.assertIn('recipe_name', data)
    self.assertIn('environment', data)
    self.assertIn('job_id', data)
    self.assertIn('prestep_sources', data)
    self.assertIn('steps', data)

  def test_claim_job(self):
    post_data = {'job_id': 0}
    user = utils.get_test_user()
    url = reverse('ci:client:claim_job', args=[user.build_key, 'testconfig', 'testClient'])

    # only post allowed
    response = self.client.get(url)
    self.assertEqual(response.status_code, 405) # not allowed

    # setup a ready job
    job = utils.create_job(user=user)
    job.ready = True
    job.active = True
    job.event.cause = models.Event.PULL_REQUEST
    pr = utils.create_pr()
    job.event.pull_request = pr
    job.event.save()
    job.status = models.JobStatus.NOT_STARTED
    job_id = job.pk
    job.save()

    # bad config
    post_data = {'job_id': job_id}
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

   # config different than job
    config2 = models.BuildConfig.objects.exclude(pk=job.config.pk).first()
    url = reverse('ci:client:claim_job', args=[user.build_key, config2.name, 'testClient'])
    post_data = {'job_id': job_id}
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # bad job
    url = reverse('ci:client:claim_job', args=[user.build_key, job.config.name, 'testClient'])
    post_data = {'job_id': 0}
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # valid job, should be ok
    post_data = {'job_id': job_id}
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)

    data = json.loads(response.content)
    self.assertEqual(data['job_id'], job_id)
    self.assertEqual(data['status'], 'OK')
    job.refresh_from_db()
    job.event.refresh_from_db()
    job.event.pull_request.refresh_from_db()
    self.assertEqual(job.status, models.JobStatus.RUNNING)
    self.assertEqual(job.event.status, models.JobStatus.RUNNING)
    self.assertEqual(job.event.pull_request.status, models.JobStatus.RUNNING)

    # create a job with a newer event.
    # This allows to test the update_status() function
    event2 = utils.create_event(commit1="2345", commit2="2345")
    job2 = utils.create_job(user=user, event=event2)
    job2.ready = True
    job2.active = True
    job2.event.cause = models.Event.PULL_REQUEST
    job2.event.pull_request = pr
    job2.event.save()
    job2.status = models.JobStatus.NOT_STARTED
    job2.save()
    job.status = models.JobStatus.NOT_STARTED
    job.client = None
    job.save()
    job.event.status = models.JobStatus.SUCCESS
    job.event.save()
    job.event.pull_request.status = models.JobStatus.SUCCESS
    job.event.pull_request.save()

    # valid job, should be ok, shouldn't update the status since
    # there is a newer event
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)

    data = json.loads(response.content)
    self.assertEqual(data['job_id'], job_id)
    self.assertEqual(data['status'], 'OK')
    job.refresh_from_db()
    job.event.refresh_from_db()
    job.event.pull_request.refresh_from_db()
    self.assertEqual(job.status, models.JobStatus.RUNNING)
    self.assertEqual(job.event.status, models.JobStatus.RUNNING)
    # there is a newer event so this event doesn't update the PullRequest status
    self.assertEqual(job.event.pull_request.status, models.JobStatus.SUCCESS)

    # valid job, but wrong client
    job.invalidated = True
    job.same_client = True
    job.status = models.JobStatus.NOT_STARTED
    client = utils.create_client(name='old_client')
    job.client = client
    job.save()

    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400)

    # valid job, and correct client
    url = reverse('ci:client:claim_job', args=[user.build_key, job.config.name, client.name])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    data = json.loads(response.content)
    self.assertEqual(data['job_id'], job_id)
    self.assertEqual(data['status'], 'OK')

    # valid job, and job client was null, should go through
    job.client = None
    job.save()
    url = reverse('ci:client:claim_job', args=[user.build_key, job.config.name, 'new_client'])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    data = json.loads(response.content)
    self.assertEqual(data['job_id'], job_id)
    self.assertEqual(data['status'], 'OK')
    job.refresh_from_db()
    job.event.refresh_from_db()
    job.event.pull_request.refresh_from_db()
    self.assertEqual(job.status, models.JobStatus.RUNNING)
    self.assertEqual(job.event.status, models.JobStatus.RUNNING)
    # there is a newer event so this event doesn't update the PullRequest status
    self.assertEqual(job.event.pull_request.status, models.JobStatus.SUCCESS)

  def test_job_finished_status(self):
    user = utils.get_test_user()
    recipe = utils.create_recipe(user=user)
    job = utils.create_job(recipe=recipe, user=user)
    step0 = utils.create_step(name='step0', recipe=recipe)
    step1 = utils.create_step(name='step1', recipe=recipe, position=1)
    step0_result = utils.create_step_result(step=step0, job=job)
    step1_result = utils.create_step_result(step=step1, job=job)
    step0_result.status = models.JobStatus.FAILED_OK
    step0_result.save()
    step1_result.status = models.JobStatus.SUCCESS
    step1_result.save()
    client = utils.create_client()
    job.client = client
    job.save()
    job.event.comments_url = 'http://localhost'
    job.event.save()
    url = reverse('ci:client:job_finished', args=[user.build_key, client.name, job.pk])

    # A step has FAILED_OK
    # So final status is FAILED_OK and we update the PR
    post_data = {'seconds': 0, 'complete': True}
    with patch('ci.github.api.GitHubAPI') as mock_api:
      response = self.client_post_json(url, post_data)
      self.assertEqual(response.status_code, 200)
      self.assertTrue(mock_api.called)
      self.assertTrue(mock_api.return_value.update_pr_status.called)
      job.refresh_from_db()
      self.assertEqual(job.status, models.JobStatus.FAILED_OK)
      os_obj = models.OSVersion.objects.get(name="Other")
      self.assertEqual(job.operating_system.pk, os_obj.pk)
      self.assertEqual(job.loaded_modules.count(), 0)

    # A step FAILED
    # So final status is FAILED and we update the PR
    step0_result.status = models.JobStatus.FAILED
    step0_result.save()
    with patch('ci.github.api.GitHubAPI') as mock_api:
      response = self.client_post_json(url, post_data)
      self.assertEqual(response.status_code, 200)
      self.assertTrue(mock_api.called)
      self.assertTrue(mock_api.return_value.update_pr_status.called)
      job.refresh_from_db()
      self.assertEqual(job.status, models.JobStatus.FAILED)

    step0_result.status = models.JobStatus.SUCCESS
    step0_result.save()

    # All steps passed
    # So final status is SUCCESS and we update the PR
    with patch('ci.github.api.GitHubAPI') as mock_api:
      response = self.client_post_json(url, post_data)
      self.assertEqual(response.status_code, 200)
      self.assertTrue(mock_api.called)
      self.assertTrue(mock_api.return_value.update_pr_status.called)
      job.refresh_from_db()
      self.assertEqual(job.status, models.JobStatus.SUCCESS)

    step0_result.status = models.JobStatus.FAILED
    step0_result.save()

    # A step FAILED
    # So final status is FAILED and we update the PR
    with patch('ci.github.api.GitHubAPI') as mock_api:
      response = self.client_post_json(url, post_data)
      self.assertEqual(response.status_code, 200)
      self.assertTrue(mock_api.called)
      self.assertTrue(mock_api.return_value.update_pr_status.called)
      job.refresh_from_db()
      self.assertEqual(job.status, models.JobStatus.FAILED)

  def test_job_finished(self):
    user = utils.get_test_user()
    job = utils.create_job(user=user)
    step_result = utils.create_step_result(job=job)
    step_result.output = self.get_file("ubuntu_gcc_output.txt")
    step_result.save()
    client = utils.create_client()
    client2 = utils.create_client(name='other_client')
    job.client = client
    job.save()
    job.event.comments_url = 'http://localhost'
    job.event.save()

    post_data = {'seconds': 0, 'complete': True}
    url = reverse('ci:client:job_finished', args=[user.build_key, client.name, job.pk])

    # only post allowed
    response = self.client.get(url)
    self.assertEqual(response.status_code, 405) # not allowed

    # bad url
    url = reverse('ci:client:job_finished', args=[user.build_key, client.name, 0])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # unknown client
    url = reverse('ci:client:job_finished', args=[user.build_key, 'unknown_client', job.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # bad client
    url = reverse('ci:client:job_finished', args=[user.build_key, client2.name, job.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # should be ok
    url = reverse('ci:client:job_finished', args=[user.build_key, client.name, job.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    data = json.loads(response.content)
    self.assertIn('message', data)
    self.assertEqual(data['status'], 'OK')
    job.refresh_from_db()
    self.assertTrue(job.complete)
    self.assertEqual(job.operating_system.name, "Ubuntu")
    self.assertEqual(job.operating_system.version, "14.04")
    self.assertEqual(job.operating_system.other, "trusty")
    mods = [ 'moose/.gcc_4.9.1', 'moose/.tbb', 'moose/.mpich-3.1.2_gcc', 'moose/.mpich_petsc-3.6.3-gcc-superlu', 'moose-tools', 'moose/.ccache', 'moose/.vtk-6', 'moose-dev-gcc']
    for mod in mods:
      self.assertTrue(job.loaded_modules.filter(name=mod).exists())

    job2 = utils.create_job(event=job.event)
    job2.ready = False
    job2.complete = False
    job2.status = models.JobStatus.NOT_STARTED
    job2.active = True
    job2.save()
    # should be ok. Make sure jobs get ready after one is finished.
    url = reverse('ci:client:job_finished', args=[user.build_key, client.name, job.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    data = json.loads(response.content)
    self.assertIn('message', data)
    self.assertEqual(data['status'], 'OK')
    job2 = models.Job.objects.get(pk=job2.pk)
    self.assertTrue(job2.ready)

  def test_step_start_pr_status(self):
    user = utils.get_test_user()
    job = utils.create_job(user=user)
    job.status = models.JobStatus.CANCELED
    job.save()
    results = utils.create_step_result(job=job)
    results.exit_status = 1
    results.save()
    request = self.factory.get('/')
    # this would normally just update the remote status
    # not something we can check.
    # So just make sure that it doesn't throw
    views.step_start_pr_status(request, results, job)

  def test_step_complete_pr_status(self):
    user = utils.get_test_user()
    job = utils.create_job(user=user)
    job.status = models.JobStatus.CANCELED
    job.save()
    results = utils.create_step_result(job=job)
    results.exit_status = 1
    results.save()
    request = self.factory.get('/')
    # this would normally just update the remote status
    # not something we can check.
    # So just make sure that it doesn't throw
    views.step_complete_pr_status(request, results, job)

  def test_start_step_result(self):
    user = utils.get_test_user()
    job = utils.create_job(user=user)
    result = utils.create_step_result(job=job)
    client = utils.create_client()
    client2 = utils.create_client(name='other_client')
    job.client = client
    job.event.cause = models.Event.PULL_REQUEST
    job.event.pr = utils.create_pr()
    job.event.save()
    job.save()

    post_data = {
        'step_num': result.position,
        'output': 'output',
        'time': 5,
        'complete': True,
        'exit_status': 0
        }
    url = reverse('ci:client:start_step_result', args=[user.build_key, client.name, result.pk])
    # only post allowed
    response = self.client.get(url)
    self.assertEqual(response.status_code, 405) # not allowed

    # bad step result
    url = reverse('ci:client:start_step_result', args=[user.build_key, client.name, 0])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # unknown client
    url = reverse('ci:client:start_step_result', args=[user.build_key, 'unknown_client', result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # bad client
    url = reverse('ci:client:start_step_result', args=[user.build_key, client2.name, result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # ok
    url = reverse('ci:client:start_step_result', args=[user.build_key, client.name, result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.RUNNING)

  def test_update_step_result(self):
    user = utils.get_test_user()
    job = utils.create_job(user=user)
    result = utils.create_step_result(job=job)
    client = utils.create_client()
    client2 = utils.create_client(name='other_client')
    job.client = client
    job.event.cause = models.Event.PULL_REQUEST
    job.status = models.JobStatus.RUNNING
    job.save()

    post_data = {
        'step_num': result.position,
        'output': 'output',
        'time': 5,
        'complete': True,
        'exit_status': 0
        }
    url = reverse('ci:client:update_step_result', args=[user.build_key, client.name, result.pk])
    # only post allowed
    response = self.client.get(url)
    self.assertEqual(response.status_code, 405) # not allowed

    # bad step result
    url = reverse('ci:client:update_step_result', args=[user.build_key, client.name, 0])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # unknown client
    url = reverse('ci:client:update_step_result', args=[user.build_key, 'unknown_client', result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # bad client
    url = reverse('ci:client:update_step_result', args=[user.build_key, client2.name, result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # ok
    url = reverse('ci:client:update_step_result', args=[user.build_key, client.name, result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.RUNNING)

    # test when the user invalidates a job while it is running
    job.status = models.JobStatus.NOT_STARTED
    job.save()
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.NOT_STARTED)

    # test when the user cancel a job while it is running
    job.status = models.JobStatus.CANCELED
    job.save()
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.CANCELED)

    # a step exited with nonzero, make sure we don't do the
    # next step
    job.status = models.JobStatus.RUNNING
    job.save()
    post_data['exit_status'] = 1
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    result.refresh_from_db()
    self.assertEqual(result.exit_status, 1)
    self.assertEqual(result.status, models.JobStatus.RUNNING)

  def test_complete_step_result(self):
    user = utils.get_test_user()
    job = utils.create_job(user=user)
    result = utils.create_step_result(job=job)
    client = utils.create_client()
    client2 = utils.create_client(name='other_client')
    job.client = client
    job.event.cause = models.Event.PULL_REQUEST
    job.status = models.JobStatus.RUNNING
    job.save()

    post_data = {
        'step_num': result.position,
        'output': 'output',
        'time': 5,
        'complete': True,
        'exit_status': 0
        }
    url = reverse('ci:client:complete_step_result', args=[user.build_key, client.name, result.pk])
    # only post allowed
    response = self.client.get(url)
    self.assertEqual(response.status_code, 405) # not allowed

    # bad step result
    url = reverse('ci:client:complete_step_result', args=[user.build_key, client.name, 0])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # unknown client
    url = reverse('ci:client:complete_step_result', args=[user.build_key, 'unknown_client', result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # bad client
    url = reverse('ci:client:complete_step_result', args=[user.build_key, client2.name, result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 400) # bad request

    # ok
    url = reverse('ci:client:complete_step_result', args=[user.build_key, client.name, result.pk])
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    json_data = json.loads(response.content)
    self.assertTrue(json_data.get('next_step'))
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.SUCCESS)

    # step failed and abort_on_failure=True
    post_data['exit_status'] = 1
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    json_data = json.loads(response.content)
    self.assertFalse(json_data.get('next_step'))
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.FAILED)

    # step failed and abort_on_failure=False
    post_data['exit_status'] = 1
    result.abort_on_failure = False
    result.save()
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    json_data = json.loads(response.content)
    self.assertTrue(json_data.get('next_step'))
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.FAILED)

    # step failed but allowed, abort_on_failure=True
    post_data['exit_status'] = 1
    result.abort_on_failure = True
    result.allowed_to_fail = True
    result.save()
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    json_data = json.loads(response.content)
    self.assertFalse(json_data.get('next_step'))
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.FAILED_OK)

    # step failed but allowed, abort_on_failure=False
    post_data['exit_status'] = 1
    result.abort_on_failure = False
    result.allowed_to_fail = True
    result.save()
    response = self.client_post_json(url, post_data)
    self.assertEqual(response.status_code, 200)
    json_data = json.loads(response.content)
    self.assertTrue(json_data.get('next_step'))
    result.refresh_from_db()
    self.assertEqual(result.status, models.JobStatus.FAILED_OK)
