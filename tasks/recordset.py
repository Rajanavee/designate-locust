import json
import random

from locust import TaskSet
import gevent

from base import BaseTaskSet
import client
import datagen
from greenlet_manager import GreenletManager
import accurate_config as CONFIG
from models import Recordset


class RecordsetTasks(BaseTaskSet):

    def list_records(self):
        """GET /zones/{id}/recordsets"""
        tenant = self.select_random_tenant()
        recordset = tenant.data.select_recordset_for_get()
        headers = self.get_headers(tenant.id)
        resp = self.designate_client.list_recordsets(
            recordset.zone.id,
            name='/v2/zones/{id}/recordsets',
            headers=headers)

    def get_record(self):
        """GET /zones/{id}/recordsets/recordID"""
        tenant = self.select_random_tenant()
        recordset = tenant.data.select_recordset_for_get()
        headers = self.get_headers(tenant.id)
        self.designate_client.get_recordset(
            recordset.zone.id,
            recordset.id,
            headers=headers,
            name='/v2/zone/{id}/recordsets/recordID')

    def create_record(self):
        """POST /zones/{id}/recordsets"""
        gevent.spawn(
            GreenletManager.get().tracked_greenlet,
            lambda: self._do_create_record(interval=2),
            timeout=60
        )

    def _do_create_record(self, interval):
        tenant = self.select_random_tenant()
        zone = tenant.data.select_zone_for_get()
        if zone is None:
            print "WARNING: don't know of any zones to create records on"
            return
        headers = self.get_headers(tenant.id)

        record_name = "{0}.{1}".format(datagen.randomize("record"), zone.name)
        payload = { "name" : record_name,
                    "type" : "A",
                    "ttl" : 3600,
                    "records" : [ datagen.random_ip() ] }

        with self.designate_client.post_recordset(
                zone.id,
                data=json.dumps(payload),
                name='/v2/zones/{id}/recordsets',
                headers=headers,
                catch_response=True) as post_resp:

            if CONFIG.use_digaas and post_resp.ok:
                self.digaas_behaviors.check_record_create_or_update(post_resp)

            if not post_resp.ok:
                post_resp.failure("Failed with status code %s" % post_resp.status_code)
                return

            api_call = lambda: self.designate_client.get_recordset(
                zone_id=zone.id,
                recordset_id=post_resp.json()['id'],
                headers=headers,
                name='/v2/zones/{id}/recordsets/{id} (POST status check)')
            self._poll_until_active_or_error(
                api_call=api_call,
                interval=interval,
                status_function=lambda r: r.json()['status'],
                success_function=post_resp.success,
                failure_function=post_resp.failure)

            # if we successfully created the recordset, add it to our list
            resp = api_call()
            if resp.ok and resp.json()['status'] == 'ACTIVE':
                recordset = Recordset(
                    zone = zone,
                    id = resp.json()['id'],
                    data = resp.json()['records'][0],
                    type = resp.json()['type'])

                # add to the list of things for deleting, to help us not run
                # out of zones to delete
                print "{0} -- Added recordset {1}".format(tenant, recordset)
                tenant.data.recordsets_for_delete.append(recordset)
                print "have %s records" % tenant.data.recordset_count()

    def modify_record(self):
        gevent.spawn(
            GreenletManager.get().tracked_greenlet,
            lambda: self._do_modify_record(interval=2),
            timeout=60
        )

    def _do_modify_record(self, interval):
        """PATCH /zones/{id}/recordsets/{id}"""
        tenant = self.select_random_tenant()
        recordset = tenant.data.select_recordset_for_get()
        if not recordset:
            print "modify_record: got None record_info"
            return

        headers = self.get_headers(tenant.id)
        payload = { "records": [ datagen.random_ip() ],
                    "ttl": random.randint(2400, 7200) }
        with self.designate_client.put_recordset(
                recordset.zone.id,
                recordset.id,
                data=json.dumps(payload),
                headers=headers,
                name="/v2/zones/{id}/recordsets/{id}",
                catch_response=True) as put_resp:

            if CONFIG.use_digaas and put_resp.ok:
                self.digaas_behaviors.check_record_create_or_update(put_resp)

            if not put_resp.ok:
                put_resp.failure("Failed with status code %s" % put_resp.status_code)
                print "Failed udpate recordset response %s" % put_resp
                print "%s %s" % (put_resp.request.method, put_resp.request.url)
                print put_resp.request.body
                print put_resp.request.headers
                print
                print put_resp.headers
                print put_resp.text
                return

            api_call = lambda: self.designate_client.get_recordset(
                zone_id=put_resp.json()['zone_id'],
                recordset_id=put_resp.json()['id'],
                headers=headers,
                name='/v2/zones/{id}/recordsets/{id} (PUT status check)')
            self._poll_until_active_or_error(
                api_call=api_call,
                interval=interval,
                status_function=lambda r: r.json()['status'],
                success_function=put_resp.success,
                failure_function=put_resp.failure)

    def remove_record(self):
        """DELETE /zones/{id}/recordsets/{id}"""
        gevent.spawn(
            GreenletManager.get().tracked_greenlet,
            lambda: self._do_remove_record(interval=2),
            timeout=60
        )

    def _do_remove_record(self, interval):
        tenant = self.select_random_tenant()
        recordset = tenant.data.pop_recordset_for_delete()
        if not recordset:
            print "remove_record: got None record_info"
            return
        headers = self.get_headers(tenant.id)

        # digaas uses the start_time when computing the propagation
        # time to the nameserver. We're assuming this time is UTC.
        # Normally, we use the created_at/update_at time returned by the api,
        # but the api doesn't gives us that for a delete
        #
        # IMPORTANT: your locust box must be synchronized to network time,
        # along with your digaas box, or digaas will compute bad durations
        if CONFIG.use_digaas:
            start_time = datetime.datetime.now()

        with self.designate_client.delete_recordset(
                recordset.zone.id,
                recordset.id,
                name='/v2/zones/{id}/recordsets/{id}',
                headers=headers,
                catch_response=True) as del_resp:

            if CONFIG.use_digaas and del_resp.ok:
                self.digaas_behaviors.check_name_removed(recordset.zone.name, start_time)

            if not del_resp.ok:
                del_resp.failure("Failed with status_code %s" % del_resp.status_code)
                return

            api_call = lambda: self.designate_client.get_recordset(
                recordset.zone.id,
                recordset.id,
                headers=headers,
                name='/v2/zones/{id}/recordsets/{id} (DELETE status check)',
                catch_response=True)

            self._poll_until_404(
                api_call=api_call,
                interval=interval,
                success_function=del_resp.success,
                failure_function=del_resp.failure)

    def _poll_until_active_or_error(self, api_call, interval, status_function,
                                    success_function, failure_function,
                                    expected='ACTIVE'):
        # NOTE: this is assumed to be run in a separate greenlet. We use
        # `while True` here, and use gevent to manage a timeout or to kill
        # the greenlet externally.
        while True:
            resp = api_call()
            if resp.ok and status_function(resp) == expected:
                success_function()
                break
            elif resp.ok and status_function(resp) == 'ERROR':
                failure_function("Failed - saw ERROR status")
                break
            gevent.sleep(interval)

    def _poll_until_404(self, api_call, interval, success_function,
                        failure_function):
        # NOTE: this is assumed to be run in a separate greenlet. We use
        # `while True` here, and use gevent to manage a timeout or to kill
        # the greenlet externally.
        while True:
            with api_call() as resp:
                if resp.status_code == 404:
                    # ensure the 404 isn't marked as a failure in the report
                    resp.success()
                    # mark the original (delete) request as a success
                    success_function()
                    return
            gevent.sleep(interval)
