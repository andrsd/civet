from django.conf import settings
import os
from ci.tests import utils, DBTester
from ci.client import ParseOutput

class ClientTester(DBTester.DBTester):
  def setUp(self):
    super(ClientTester, self).setUp()
    self.orig_remote_update = settings.REMOTE_UPDATE
    settings.REMOTE_UPDATE = False
    settings.INSTALLED_GITSERVERS = [settings.GITSERVER_GITHUB,]

  def tearDown(self):
    super(ClientTester, self).tearDown()
    settings.REMOTE_UPDATE = self.orig_remote_update

  def get_file(self, filename):
    dirname, fname = os.path.split(os.path.abspath(__file__))
    with open(dirname + '/' + filename, 'r') as f:
      js = f.read()
      return js

  def check_modules(self, job, mods):
    self.assertEqual(len(mods), job.loaded_modules.count())
    for mod in mods:
      self.assertTrue(job.loaded_modules.filter(name=mod).exists())

  def check_output(self, output, os_name, os_version, os_other, mods):
    user = utils.get_test_user()
    job = utils.create_job(user=user)
    step_result = utils.create_step_result(job=job)
    step_result.output = output
    step_result.save()
    client = utils.create_client()
    job.client = client
    job.save()

    ParseOutput.set_job_info(job)
    job.refresh_from_db()
    self.assertEqual(job.operating_system.name, os_name)
    self.assertEqual(job.operating_system.version, os_version)
    self.assertEqual(job.operating_system.other, os_other)
    self.check_modules(job, mods)