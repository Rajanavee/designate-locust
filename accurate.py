import csv
import json
import datetime
import random

from locust import HttpLocust
from locust import TaskSet
from locust import task
from locust.clients import HttpSession
import locust.events
import locust.config

import gevent

import client
import graphite_client
import digaas_integration
import persistence
import insight
from greenlet_manager import GreenletManager
from client import DesignateClient
from web import *
from datagen import *
import accurate_config as CONFIG

from tasks.gather import GatherTasks
from tasks.recordset import RecordsetTasks
from tasks.zone import ZoneTasks
from models import Tenant

# require a username + password to access the web interface
setup_authentication(CONFIG.username, CONFIG.password)

# send metrics to a graphite server
graphite_client.setup_graphite_communication(
    CONFIG.graphite_host, CONFIG.graphite_port)

# save a report when the test finishes
persistence.setup_persistence()

locust.config.RESET_STATS_AFTER_HATCHING = CONFIG.reset_stats

_client = HttpSession(CONFIG.designate_host)
_designate_client = DesignateClient(_client)
_digaas_client = digaas_integration.DigaasClient(CONFIG.digaas_endpoint)

# use digaas to externally poll the nameserver(s) to record zone propagation
# times through Designate's stack
if CONFIG.use_digaas and not insight.is_slave():
    digaas_integration.setup_digaas_integration(_digaas_client)

if not insight.is_master():
    SMALL_TENANTS = [ Tenant(id=id, api_key=None, type=Tenant.SMALL)
                      for id in CONFIG.small_tenants ]
    LARGE_TENANTS = [ Tenant(id=id, api_key=None, type=Tenant.LARGE)
                     for id in CONFIG.large_tenants ]
    ALL_TENANTS = SMALL_TENANTS + LARGE_TENANTS

    # the greenlet_manager keeps track of greenlets spawned for polling
    # todo: it's hard to ensure cleanup_greenlets gets run before the stats
    # are persisted to a file...

    # ensure cleanup when the test is stopped
    locust.events.locust_stop_hatching += \
        lambda: GreenletManager.get().cleanup_greenlets()
    # ensure cleanup on interrupts
    locust.events.quitting += \
        lambda: GreenletManager.get().cleanup_greenlets()

class LargeTasks(ZoneTasks, RecordsetTasks):

    tasks = {
        ZoneTasks.get_domain_by_id:   CONFIG.large_weights.get_domain_by_id,
        ZoneTasks.get_domain_by_name: CONFIG.large_weights.get_domain_by_name,
        ZoneTasks.list_domains:       CONFIG.large_weights.list_domain,
        ZoneTasks.import_zone:        CONFIG.large_weights.import_zone,
        ZoneTasks.export_domain:      CONFIG.large_weights.export_domain,
        ZoneTasks.create_domain:      CONFIG.large_weights.create_domain,
        ZoneTasks.modify_domain:      CONFIG.large_weights.modify_domain,
        ZoneTasks.remove_domain:      CONFIG.large_weights.remove_domain,
        RecordsetTasks.list_records:  CONFIG.large_weights.list_records,
        RecordsetTasks.get_record:    CONFIG.large_weights.get_record,
        RecordsetTasks.create_record: CONFIG.large_weights.create_record,
        RecordsetTasks.remove_record: CONFIG.large_weights.remove_record,
        RecordsetTasks.modify_record: CONFIG.large_weights.modify_record,
    }

    def __init__(self, *args, **kwargs):
        super(LargeTasks, self).__init__(LARGE_TENANTS, *args, **kwargs)
        self.designate_client = DesignateClient(self.client)


class SmallTasks(ZoneTasks, RecordsetTasks):

    tasks = {
        ZoneTasks.get_domain_by_id:   CONFIG.small_weights.get_domain_by_id,
        ZoneTasks.get_domain_by_name: CONFIG.small_weights.get_domain_by_name,
        ZoneTasks.list_domains:       CONFIG.small_weights.list_domain,
        ZoneTasks.import_zone:        CONFIG.small_weights.import_zone,
        ZoneTasks.export_domain:      CONFIG.small_weights.export_domain,
        ZoneTasks.create_domain:      CONFIG.small_weights.create_domain,
        ZoneTasks.modify_domain:      CONFIG.small_weights.modify_domain,
        ZoneTasks.remove_domain:      CONFIG.small_weights.remove_domain,
        RecordsetTasks.list_records:  CONFIG.small_weights.list_records,
        RecordsetTasks.get_record:    CONFIG.small_weights.get_record,
        RecordsetTasks.create_record: CONFIG.small_weights.create_record,
        RecordsetTasks.remove_record: CONFIG.small_weights.remove_record,
        RecordsetTasks.modify_record: CONFIG.small_weights.modify_record,
    }

    def __init__(self, *args, **kwargs):
        super(SmallTasks, self).__init__(SMALL_TENANTS, *args, **kwargs)
        self.designate_client = DesignateClient(self.client)

#class HatchingLargeTaskSet(ZoneTasks, RecordsetTasks):
#
#    tasks = {
#        ZoneTasks.get_domain_by_id:   0,
#        ZoneTasks.get_domain_by_name: 0,
#        ZoneTasks.list_domains:       0,
#        ZoneTasks.import_zone:        0,
#        ZoneTasks.export_domain:      0,
#        ZoneTasks.create_domain:      10,
#        ZoneTasks.modify_domain:      0,
#        ZoneTasks.remove_domain:      0,
#        RecordsetTasks.list_records:  0,
#        RecordsetTasks.get_record:    0,
#        RecordsetTasks.create_record: 10,
#        RecordsetTasks.remove_record: 0,
#        RecordsetTasks.modify_record: 0,
#    }
#
#    def __init__(self, *args, **kwargs):
#        super(HatchingLargeTaskSet, self).__init__(LARGE_DATA, *args, **kwargs)
#        self.designate_client = DesignateClient(self.client)


class HatchingSmallTaskSet(ZoneTasks, RecordsetTasks):

    tasks = {
        ZoneTasks.get_domain_by_id:   0,
        ZoneTasks.get_domain_by_name: 0,
        ZoneTasks.list_domains:       0,
        ZoneTasks.import_zone:        0,
        ZoneTasks.export_domain:      0,
        ZoneTasks.create_domain:      10,
        ZoneTasks.modify_domain:      0,
        ZoneTasks.remove_domain:      0,
        RecordsetTasks.list_records:  0,
        RecordsetTasks.get_record:    0,
        RecordsetTasks.create_record: 10,
        RecordsetTasks.remove_record: 0,
        RecordsetTasks.modify_record: 0,
    }

    def __init__(self, *args, **kwargs):
        super(HatchingSmallTaskSet, self).__init__(SMALL_TENANTS, *args, **kwargs)
        self.designate_client = DesignateClient(self.client)


class AccurateTaskSet(TaskSet):
    """Combines large tenants and small tenants with appropriate weights."""
    tasks = {
        LargeTasks: CONFIG.total_large_weight,
        SmallTasks: CONFIG.total_small_weight,
    }

class GatherShim(GatherTasks):

    done_gathering = locust.events.EventHook()

    tasks = {
        GatherTasks.gather_zones: 1,
        GatherTasks.gather_recordsets: 1,
    }

    def __init__(self, *args, **kwargs):
        super(GatherShim, self).__init__(ALL_TENANTS, *args, **kwargs)
        print "init GatherShim"

class GatherData(TaskSet):

    tasks = [ GatherShim ]

    def __init__(self, *args, **kwargs):
        super(GatherData, self).__init__(*args, **kwargs)
        self.hatch_complete_handlers = None
        self.is_done = False
        self.already_did_it = False

        def _handler():
            self.is_done = True
            self.be_done_if_done()
        GatherShim.done_gathering += _handler

    def on_start(self):
        self.disable_hatch_complete_handlers()

    def disable_hatch_complete_handlers(self):
        print "disable_hatch_complete_handlers"
        # disable hatch complete handlers to delay the hatch complete event
        if self.hatch_complete_handlers is None:
            self.hatch_complete_handlers = locust.events.hatch_complete._handlers
            locust.events.hatch_complete._handlers = []

    def restore_hatch_complete_handlers(self):
        print "restore_hatch_complete_handlers"
        if locust.runners.locust_runner.state == locust.runners.STATE_HATCHING \
                and self.hatch_complete_handlers is not None:
            print locust.events.hatch_complete._handlers
            locust.events.hatch_complete._handlers = self.hatch_complete_handlers
            self.hatch_complete_handlers = None

    def be_done_if_done(self):
        if not self.already_did_it and self.is_done:
            print "be_done_if_done!"
            self.restore_hatch_complete_handlers()
            locust.events.hatch_complete.fire(user_count=locust.runners.locust_runner.user_count)
            self.already_did_it = True

class TaskSwitcher(TaskSet):
    """This is a bit of a hack. This will use one set of tasks for hatching and
    a different set of tasks otherwise. This lets us easily do data preparation
    before the perf test starts using one set of task weights, and then run the
    performance test with the usual set of task weights.

    TODO: only use the hatching task set on the first hatch.
        we want dynamic changes in the number of users to work right.
    TODO: if we data prep on one instance and save a bunch of zones to that
        instance, and then we switch to a different instance to a
    """

    tasks = []

    def __init__(self, *args, **kwargs):
        super(TaskSwitcher, self).__init__(*args, **kwargs)
        # this is a little awkward, but it works. these must be instances
        # of a class that has the task methods as members.
        self.regular_tasks = AccurateTaskSet(*args, **kwargs)
        self.hatching_tasks = GatherData(*args, **kwargs)
        # self.hatching_tasks = GatherTaskSet(SMALL_DATA, *args, **kwargs)
        # self.hatching_tasks = HatchingSmallTaskSet(*args, **kwargs)
        print self.regular_tasks.tasks
        print self.hatching_tasks.tasks
        # self.hatching_tasks = HatchingSmallTaskSet(*args, **kwargs)

        def on_hatch_complete_poo(user_count):
            print "HATCH COMPLETE"
            print "before:", self.tasks
            self.tasks = self.regular_tasks.tasks
            print "after:", self.tasks
            self.interrupt()
        locust.events.hatch_complete += on_hatch_complete_poo

    def on_start(self):
        self.hatching_tasks.on_start()

    def get_next_task(self):
        print "get_next_task"
        if locust.runners.locust_runner.state in \
                (None, locust.runners.STATE_INIT, locust.runners.STATE_HATCHING):
            self.tasks = self.hatching_tasks.tasks
            print "Using hatching tasks"
            print self.tasks
        else:
            self.tasks = self.regular_tasks.tasks
            print "Using regular tasks"
            print self.tasks
        next_task = super(TaskSwitcher, self).get_next_task()
        print "next task =", next_task
        return next_task

class Locust(HttpLocust):
    task_set = TaskSwitcher

    min_wait = CONFIG.min_wait
    max_wait = CONFIG.max_wait

    host = CONFIG.designate_host
