"""CI-only worker: all provider operations are disabled, including background sync."""
import os
assert os.environ.get('PM_TEST_DATABASE_URL')
os.environ['DATABASE_URL']=os.environ['PM_TEST_DATABASE_URL']
from worker.app import app,registry
original=registry.get
class NoNetwork:
    async def __aenter__(self):raise ValueError('Meta disabled in CI')
    async def __aexit__(self,*_):pass
def get(owner):
    workspace=original(owner)
    workspace.manager.graph_factory=NoNetwork
    workspace.scheduler.graph_factory=NoNetwork
    return workspace
registry.get=get
