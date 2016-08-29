from ci import models
import re

def find_in_output(output, key):
  """
  Find a key in the output and return its value.
  """
  matches = re.search("^%s=(.*)" % key, output)
  if matches:
    return matches.groups()[0]
  return None

def get_output_by_position(job, position):
  """
  Utility function to get the output of a job step result by position
  """
  return job.step_results.get(position=position).output

def check_submodule_update(job, position):
  """
  Checks to see if certain submodules have been updated and post a comment to the PR if so.
  """
  output = get_output_by_position(job, position)
  modules = find_in_output(output, "CIVET_CLIENT_SUBMODULE_UPDATES")
  if not modules:
    return
  if not job.event.pull_request or not job.event.pull_request.review_comments_url:
    return
  for mod in modules.split():
    oauth_session = job.event.build_user.start_session()
    api = job.event.pull_request.repository.server().api()
    url = job.event.pull_request.review_comments_url
    sha = job.event.head.sha
    msg = "**Caution!** This contains a submodule update"
    # The 2 position will leave the message on the new submodule hash
    api.pr_review_comment(oauth_session, url, sha, mod, 2, msg)

def check_post_comment(job, position):
  """
  Checks to see if we should post a message to the PR.
  """
  output = get_output_by_position(job, position)
  message = find_in_output(output, "CIVET_CLIENT_POST_MESSAGE")
  if message and job.event.comments_url:
    oauth_session = job.event.build_user.start_session()
    msg = "Job %s on %s wanted to post the following:\n\n%s" % (job, job.event.head.sha[:7], message)
    api = job.event.pull_request.repository.server().api()
    url = job.event.comments_url
    api.pr_comment(oauth_session, url, msg)

def process_commands(job):
  """
  See if we need to check for any commands on this job.
  Commands take the form of an environment variable set on the recipe to
  indicate that we need to check the output for certain key value pairs.
  """
  if job.event.cause != models.Event.PULL_REQUEST:
    return
  for step in job.recipe.steps.prefetch_related("step_environment").all():
    for step_env in step.step_environment.all():
      if step_env.name == "CIVET_SERVER_POST_ON_SUBMODULE_UPDATE" and step_env.value == "1":
        check_submodule_update(job, step.position)
        break
      elif step_env.name == "CIVET_SERVER_POST_COMMENT" and step_env.value == "1":
        check_post_comment(job, step.position)
        break
