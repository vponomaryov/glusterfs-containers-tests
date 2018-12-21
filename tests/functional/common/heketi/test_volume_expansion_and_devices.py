from __future__ import division
import json
import math
import unittest

from glusto.core import Glusto as g
from glustolibs.gluster import volume_ops, rebalance_ops

from cnslibs.common.exceptions import ExecutionError
from cnslibs.common.heketi_libs import HeketiBaseClass
from cnslibs.common.openshift_ops import get_ocp_gluster_pod_names
from cnslibs.common import heketi_ops, podcmd


class TestVolumeExpansionAndDevicesTestCases(HeketiBaseClass):
    """
    Class for volume expansion and devices addition related test cases
    """

    @podcmd.GlustoPod()
    def get_num_of_bricks(self, volume_name):
        """
        Method to determine number of
        bricks at present in the volume
        """
        brick_info = []

        if self.deployment_type == "cns":

            gluster_pod = get_ocp_gluster_pod_names(
                self.heketi_client_node)[1]

            p = podcmd.Pod(self.heketi_client_node, gluster_pod)

            volume_info_before_expansion = volume_ops.get_volume_info(
                p, volume_name)

        elif self.deployment_type == "crs":
            volume_info_before_expansion = volume_ops.get_volume_info(
                self.heketi_client_node, volume_name)

        self.assertIsNotNone(
            volume_info_before_expansion,
            "Volume info is None")

        for brick_details in (volume_info_before_expansion
                              [volume_name]["bricks"]["brick"]):

            brick_info.append(brick_details["name"])

        num_of_bricks = len(brick_info)

        return num_of_bricks

    @podcmd.GlustoPod()
    def get_rebalance_status(self, volume_name):
        """
        Rebalance status after expansion
        """
        if self.deployment_type == "cns":
            gluster_pod = get_ocp_gluster_pod_names(
                self.heketi_client_node)[1]

            p = podcmd.Pod(self.heketi_client_node, gluster_pod)

            wait_reb = rebalance_ops.wait_for_rebalance_to_complete(
                p, volume_name)
            self.assertTrue(wait_reb, "Rebalance not complete")

            reb_status = rebalance_ops.get_rebalance_status(
                p, volume_name)

        elif self.deployment_type == "crs":
            wait_reb = rebalance_ops.wait_for_rebalance_to_complete(
                self.heketi_client_node, volume_name)
            self.assertTrue(wait_reb, "Rebalance not complete")

            reb_status = rebalance_ops.get_rebalance_status(
                self.heketi_client_node, volume_name)

        self.assertEqual(reb_status["aggregate"]["statusStr"],
                         "completed", "Rebalance not yet completed")

    @podcmd.GlustoPod()
    def get_brick_and_volume_status(self, volume_name):
        """
        Status of each brick in a volume
        for background validation
        """
        brick_info = []

        if self.deployment_type == "cns":
            gluster_pod = get_ocp_gluster_pod_names(
                self.heketi_client_node)[1]

            p = podcmd.Pod(self.heketi_client_node, gluster_pod)

            volume_info = volume_ops.get_volume_info(p, volume_name)
            volume_status = volume_ops.get_volume_status(p, volume_name)

        elif self.deployment_type == "crs":
            volume_info = volume_ops.get_volume_info(
                self.heketi_client_node, volume_name)
            volume_status = volume_ops.get_volume_status(
                self.heketi_client_node, volume_name)

        self.assertIsNotNone(volume_info, "Volume info is empty")
        self.assertIsNotNone(volume_status, "Volume status is empty")

        self.assertEqual(int(volume_info[volume_name]["status"]), 1,
                         "Volume not up")
        for brick_details in volume_info[volume_name]["bricks"]["brick"]:
            brick_info.append(brick_details["name"])

        if brick_info == []:
            raise ExecutionError("Brick details empty for %s" % volume_name)

        for brick in brick_info:
            brick_data = brick.strip().split(":")
            brick_ip = brick_data[0]
            brick_name = brick_data[1]
            self.assertEqual(int(volume_status[volume_name][brick_ip]
                             [brick_name]["status"]), 1,
                             "Brick %s not up" % brick_name)

    def enable_disable_devices(self, additional_devices_attached, enable=True):
        """
        Method to enable and disable devices
        """
        op = 'enable' if enable else 'disable'
        for node_id in additional_devices_attached.keys():
            node_info = heketi_ops.heketi_node_info(
                self.heketi_client_node, self.heketi_server_url,
                node_id, json=True)

            if not enable:
                self.assertNotEqual(node_info, False,
                                    "Node info for node %s failed" % node_id)

            for device in node_info["devices"]:
                if device["name"] == additional_devices_attached[node_id]:
                    out = getattr(heketi_ops, 'heketi_device_%s' % op)(
                        self.heketi_client_node,
                        self.heketi_server_url,
                        device["id"],
                        json=True)
                    if out is False:
                        g.log.info("Device %s could not be %sd"
                                   % (device["id"], op))
                    else:
                        g.log.info("Device %s %sd" % (device["id"], op))

    def enable_devices(self, additional_devices_attached):
        """
        Method to call enable_disable_devices to enable devices
        """
        return self.enable_disable_devices(additional_devices_attached, True)

    def disable_devices(self, additional_devices_attached):
        """
        Method to call enable_disable_devices to disable devices
        """
        return self.enable_disable_devices(additional_devices_attached, False)

    def get_devices_summary_free_space(self):
        """
        Calculates minimum free space per device and
        returns total free space across all devices
        """

        free_spaces = []

        heketi_node_id_list = heketi_ops.heketi_node_list(
            self.heketi_client_node, self.heketi_server_url)

        for node_id in heketi_node_id_list:
            node_info_dict = heketi_ops.heketi_node_info(
                self.heketi_client_node, self.heketi_server_url,
                node_id, json=True)
            total_free_space = 0
            for device in node_info_dict["devices"]:
                total_free_space += device["storage"]["free"]
            free_spaces.append(total_free_space)

        total_free_space = sum(free_spaces)/(1024 ** 2)
        total_free_space = int(math.floor(total_free_space))

        return total_free_space

    def detach_devices_attached(self, device_id_list):
        """
        All the devices attached are gracefully
        detached in this function
        """
        if not isinstance(device_id_list, (tuple, set, list)):
            device_id_list = [device_id_list]
        for device_id in device_id_list:
            device_disable = heketi_ops.heketi_device_disable(
                self.heketi_client_node, self.heketi_server_url, device_id)
            self.assertNotEqual(
                device_disable, False,
                "Device %s could not be disabled" % device_id)
            device_remove = heketi_ops.heketi_device_remove(
                self.heketi_client_node, self.heketi_server_url, device_id)
            self.assertNotEqual(
                device_remove, False,
                "Device %s could not be removed" % device_id)
            device_delete = heketi_ops.heketi_device_delete(
                self.heketi_client_node, self.heketi_server_url, device_id)
            self.assertNotEqual(
                device_delete, False,
                "Device %s could not be deleted" % device_id)

    @unittest.skip("Blocked by BZ-1629889")
    @podcmd.GlustoPod()
    def test_add_device_heketi_cli(self):
        """
        Method to test heketi device addition with background
        gluster validation
        """
        device_id_list = []
        hosts = []
        gluster_servers = []

        node_id_list = heketi_ops.heketi_node_list(
            self.heketi_client_node, self.heketi_server_url)

        creation_info = heketi_ops.heketi_volume_create(
            self.heketi_client_node, self.heketi_server_url, 100, json=True)

        self.assertNotEqual(creation_info, False,
                            "Volume creation failed")

        self.addCleanup(self.delete_volumes, creation_info["id"])

        ret, out, err = heketi_ops.heketi_volume_create(
            self.heketi_client_node, self.heketi_server_url, 620, json=True,
            raw_cli_output=True)

        self.assertEqual(ret, 255, "Volume creation did not fail ret- %s "
                         "out- %s err= %s" % (ret, out, err))
        g.log.info("Volume creation failed as expected, err- %s" % err)

        if ret == 0:
            out_json = json.loads(out)
            self.addCleanup(self.delete_volumes, out_json["id"])

        for node_id in node_id_list:
            device_present = False
            node_info = heketi_ops.heketi_node_info(
                self.heketi_client_node, self.heketi_server_url,
                node_id, json=True)

            self.assertNotEqual(
                node_info, False,
                "Heketi node info on node %s failed" % node_id)

            node_ip = node_info["hostnames"]["storage"][0]

            for gluster_server in g.config["gluster_servers"].keys():
                gluster_server_ip = (g.config["gluster_servers"]
                                     [gluster_server]["storage"])
                if gluster_server_ip == node_ip:
                    device_name = (g.config["gluster_servers"][gluster_server]
                                   ["additional_devices"][0])
                    break
            device_addition_info = heketi_ops.heketi_device_add(
                self.heketi_client_node, self.heketi_server_url,
                device_name, node_id, json=True)

            self.assertNotEqual(device_addition_info, False,
                                "Device %s addition failed" % device_name)

            node_info_after_addition = heketi_ops.heketi_node_info(
                self.heketi_client_node, self.heketi_server_url,
                node_id, json=True)
            for device in node_info_after_addition["devices"]:
                if device["name"] == device_name:
                    device_present = True
                    device_id_list.append(device["id"])

            self.assertEqual(device_present, True,
                             "device %s not present" % device["id"])

        self.addCleanup(self.detach_devices_attached, device_id_list)

        output_dict = heketi_ops.heketi_volume_create(
            self.heketi_client_node, self.heketi_server_url,
            620, json=True)

        self.assertNotEqual(output_dict, False, "Volume creation failed")
        self.addCleanup(self.delete_volumes, output_dict["id"])

        self.assertEqual(output_dict["durability"]["replicate"]["replica"], 3)
        self.assertEqual(output_dict["size"], 620)
        mount_node = (output_dict["mount"]["glusterfs"]
                      ["device"].strip().split(":")[0])

        hosts.append(mount_node)
        backup_volfile_server_list = (
            output_dict["mount"]["glusterfs"]["options"]
            ["backup-volfile-servers"].strip().split(","))

        for backup_volfile_server in backup_volfile_server_list:
                hosts.append(backup_volfile_server)
        for gluster_server in g.config["gluster_servers"].keys():
                gluster_servers.append(g.config["gluster_servers"]
                                       [gluster_server]["storage"])
        self.assertEqual(
            set(hosts), set(gluster_servers),
            "Hosts do not match gluster servers for %s" % output_dict["id"])

        volume_name = output_dict["name"]

        self.get_brick_and_volume_status(volume_name)

    def test_volume_expansion_expanded_volume(self):
        """
        To test volume expansion with brick and rebalance
        validation
        """
        creation_info = heketi_ops.heketi_volume_create(
            self.heketi_client_node, self.heketi_server_url, 10, json=True)

        self.assertNotEqual(creation_info, False, "Volume creation failed")

        volume_name = creation_info["name"]
        volume_id = creation_info["id"]

        free_space_after_creation = self.get_devices_summary_free_space()

        volume_info_before_expansion = heketi_ops.heketi_volume_info(
            self.heketi_client_node,
            self.heketi_server_url,
            volume_id, json=True)

        self.assertNotEqual(
            volume_info_before_expansion, False,
            "Heketi volume info for %s failed" % volume_id)

        heketi_vol_info_size_before_expansion = (
            volume_info_before_expansion["size"])

        num_of_bricks_before_expansion = self.get_num_of_bricks(volume_name)

        self.get_brick_and_volume_status(volume_name)

        expansion_info = heketi_ops.heketi_volume_expand(
            self.heketi_client_node,
            self.heketi_server_url,
            volume_id, 3)

        self.assertNotEqual(expansion_info, False,
                            "Volume %s expansion failed" % volume_id)

        free_space_after_expansion = self.get_devices_summary_free_space()

        self.assertTrue(
            free_space_after_creation > free_space_after_expansion,
            "Expansion of %s did not consume free space" % volume_id)

        num_of_bricks_after_expansion = self.get_num_of_bricks(volume_name)

        self.get_brick_and_volume_status(volume_name)
        self.get_rebalance_status(volume_name)

        volume_info_after_expansion = heketi_ops.heketi_volume_info(
            self.heketi_client_node,
            self.heketi_server_url,
            volume_id, json=True)

        self.assertNotEqual(
            volume_info_after_expansion, False,
            "Heketi volume info for %s command failed" % volume_id)

        heketi_vol_info_size_after_expansion = (
            volume_info_after_expansion["size"])

        difference_size_after_expansion = (
            heketi_vol_info_size_after_expansion -
            heketi_vol_info_size_before_expansion)

        self.assertTrue(
            difference_size_after_expansion > 0,
            "Volume expansion for %s did not consume free space" % volume_id)

        num_of_bricks_added_after_expansion = (num_of_bricks_after_expansion -
                                               num_of_bricks_before_expansion)

        self.assertEqual(
            num_of_bricks_added_after_expansion, 3,
            "Number of bricks added in %s after expansion is not 3"
            % volume_name)

        further_expansion_info = heketi_ops.heketi_volume_expand(
            self.heketi_client_node,
            self.heketi_server_url,
            volume_id, 3)

        self.assertNotEqual(further_expansion_info, False,
                            "Volume expansion failed for %s" % volume_id)

        free_space_after_further_expansion = (
            self.get_devices_summary_free_space())
        self.assertTrue(
            free_space_after_expansion > free_space_after_further_expansion,
            "Further expansion of %s did not consume free space" % volume_id)

        num_of_bricks_after_further_expansion = (
            self.get_num_of_bricks(volume_name))

        self.get_brick_and_volume_status(volume_name)

        self.get_rebalance_status(volume_name)

        volume_info_after_further_expansion = heketi_ops.heketi_volume_info(
            self.heketi_client_node,
            self.heketi_server_url,
            volume_id, json=True)

        self.assertNotEqual(
            volume_info_after_further_expansion, False,
            "Heketi volume info for %s failed" % volume_id)

        heketi_vol_info_size_after_further_expansion = (
            volume_info_after_further_expansion["size"])

        difference_size_after_further_expansion = (
            heketi_vol_info_size_after_further_expansion -
            heketi_vol_info_size_after_expansion)

        self.assertTrue(
            difference_size_after_further_expansion > 0,
            "Size of volume %s did not increase" % volume_id)

        num_of_bricks_added_after_further_expansion = (
            num_of_bricks_after_further_expansion -
            num_of_bricks_after_expansion)

        self.assertEqual(
            num_of_bricks_added_after_further_expansion, 3,
            "Number of bricks added is not 3 for %s" % volume_id)

        free_space_before_deletion = self.get_devices_summary_free_space()

        volume_delete = heketi_ops.heketi_volume_delete(
            self.heketi_client_node, self.heketi_server_url,
            volume_id, json=True)

        self.assertNotEqual(volume_delete, False, "Deletion of %s failed"
                            % volume_id)

        free_space_after_deletion = self.get_devices_summary_free_space()

        self.assertTrue(free_space_after_deletion > free_space_before_deletion,
                        "Free space not reclaimed after deletion of %s"
                        % volume_id)

    def test_volume_expansion_no_free_space(self):
        """Test case CNS-467: volume expansion when there is no free space."""

        vol_size, expand_size, additional_devices_attached = None, 10, {}
        h_node, h_server_url = self.heketi_client_node, self.heketi_server_url

        # Get nodes info
        heketi_node_id_list = heketi_ops.heketi_node_list(h_node, h_server_url)
        if len(heketi_node_id_list) < 3:
            self.skipTest("3 Heketi nodes are required.")

        # Disable 4th and other nodes
        for node_id in heketi_node_id_list[3:]:
            heketi_ops.heketi_node_disable(h_node, h_server_url, node_id)
            self.addCleanup(
                heketi_ops.heketi_node_enable, h_node, h_server_url, node_id)

        # Prepare first 3 nodes
        smallest_size = None
        for node_id in heketi_node_id_list[0:3]:
            node_info = heketi_ops.heketi_node_info(
                h_node, h_server_url, node_id, json=True)

            # Disable second and other devices
            devices = node_info["devices"]
            self.assertTrue(
                devices, "Node '%s' does not have devices." % node_id)
            if devices[0]["state"].strip().lower() != "online":
                self.skipTest("Test expects first device to be enabled.")
            if (smallest_size is None or
                    devices[0]["storage"]["free"] < smallest_size):
                smallest_size = devices[0]["storage"]["free"]
            for device in node_info["devices"][1:]:
                heketi_ops.heketi_device_disable(
                    h_node, h_server_url, device["id"])
                self.addCleanup(
                    heketi_ops.heketi_device_enable,
                    h_node, h_server_url, device["id"])

            # Gather info about additional devices
            for gluster_server in self.gluster_servers:
                gluster_server_data = self.gluster_servers_info[gluster_server]
                g_manage = gluster_server_data["manage"]
                g_storage = gluster_server_data["storage"]
                if not (g_manage in node_info["hostnames"]["manage"] or
                        g_storage in node_info["hostnames"]["storage"]):
                    continue

                heketi_ops.heketi_device_add(
                    h_node, h_server_url,
                    gluster_server_data["additional_devices"][0], node_id)
                additional_devices_attached.update(
                    {node_id: gluster_server_data["additional_devices"][0]})

        # Schedule cleanup of the added devices
        for node_id in additional_devices_attached.keys():
            node_info = heketi_ops.heketi_node_info(
                h_node, h_server_url, node_id, json=True)
            for device in node_info["devices"]:
                if device["name"] != additional_devices_attached[node_id]:
                    continue
                self.addCleanup(self.detach_devices_attached, device["id"])
                break
            else:
                self.fail("Could not find ID for added device on "
                          "'%s' node." % node_id)

        # Temporary disable new devices
        self.disable_devices(additional_devices_attached)

        # Create volume and save info about it
        vol_size = int(smallest_size / (1024**2)) - 1
        creation_info = heketi_ops.heketi_volume_create(
            h_node, h_server_url, vol_size, json=True)
        volume_name, volume_id = creation_info["name"], creation_info["id"]
        self.addCleanup(
            heketi_ops.heketi_volume_delete,
            h_node, h_server_url, volume_id, raise_on_error=False)

        volume_info_before_expansion = heketi_ops.heketi_volume_info(
            h_node, h_server_url, volume_id, json=True)
        num_of_bricks_before_expansion = self.get_num_of_bricks(volume_name)
        self.get_brick_and_volume_status(volume_name)
        free_space_before_expansion = self.get_devices_summary_free_space()

        # Try to expand volume with not enough device space
        self.assertRaises(
            ExecutionError, heketi_ops.heketi_volume_expand,
            h_node, h_server_url, volume_id, expand_size)

        # Enable new devices to be able to expand our volume
        self.enable_devices(additional_devices_attached)

        # Expand volume and validate results
        heketi_ops.heketi_volume_expand(
            h_node, h_server_url, volume_id, expand_size, json=True)
        free_space_after_expansion = self.get_devices_summary_free_space()
        self.assertGreater(
            free_space_before_expansion, free_space_after_expansion,
            "Free space not consumed after expansion of %s" % volume_id)
        num_of_bricks_after_expansion = self.get_num_of_bricks(volume_name)
        self.get_brick_and_volume_status(volume_name)
        volume_info_after_expansion = heketi_ops.heketi_volume_info(
            h_node, h_server_url, volume_id, json=True)
        self.assertGreater(
            volume_info_after_expansion["size"],
            volume_info_before_expansion["size"],
            "Size of %s not increased" % volume_id)
        self.assertGreater(
            num_of_bricks_after_expansion, num_of_bricks_before_expansion)
        self.assertEqual(
            num_of_bricks_after_expansion % num_of_bricks_before_expansion, 0)

        # Delete volume and validate release of the used space
        heketi_ops.heketi_volume_delete(h_node, h_server_url, volume_id)
        free_space_after_deletion = self.get_devices_summary_free_space()
        self.assertGreater(
            free_space_after_deletion, free_space_after_expansion,
            "Free space not reclaimed after deletion of volume %s" % volume_id)

    @podcmd.GlustoPod()
    def test_volume_expansion_rebalance_brick(self):
        """
        To test volume expansion with brick and rebalance
        validation
        """
        creation_info = heketi_ops.heketi_volume_create(
            self.heketi_client_node, self.heketi_server_url, 10, json=True)

        self.assertNotEqual(creation_info, False, "Volume creation failed")

        volume_name = creation_info["name"]
        volume_id = creation_info["id"]

        free_space_after_creation = self.get_devices_summary_free_space()

        volume_info_before_expansion = heketi_ops.heketi_volume_info(
            self.heketi_client_node,
            self.heketi_server_url,
            volume_id, json=True)

        self.assertNotEqual(volume_info_before_expansion, False,
                            "Volume info for %s failed" % volume_id)

        heketi_vol_info_size_before_expansion = (
            volume_info_before_expansion["size"])

        self.get_brick_and_volume_status(volume_name)
        num_of_bricks_before_expansion = self.get_num_of_bricks(volume_name)

        expansion_info = heketi_ops.heketi_volume_expand(
            self.heketi_client_node,
            self.heketi_server_url,
            volume_id, 5)

        self.assertNotEqual(expansion_info, False,
                            "Volume expansion of %s failed" % volume_id)

        free_space_after_expansion = self.get_devices_summary_free_space()
        self.assertTrue(
            free_space_after_creation > free_space_after_expansion,
            "Free space not consumed after expansion of %s" % volume_id)

        volume_info_after_expansion = heketi_ops.heketi_volume_info(
            self.heketi_client_node,
            self.heketi_server_url,
            volume_id, json=True)

        self.assertNotEqual(volume_info_after_expansion, False,
                            "Volume info failed for %s" % volume_id)

        heketi_vol_info_size_after_expansion = (
            volume_info_after_expansion["size"])

        difference_size = (heketi_vol_info_size_after_expansion -
                           heketi_vol_info_size_before_expansion)

        self.assertTrue(
            difference_size > 0,
            "Size not increased after expansion of %s" % volume_id)

        self.get_brick_and_volume_status(volume_name)
        num_of_bricks_after_expansion = self.get_num_of_bricks(volume_name)

        num_of_bricks_added = (num_of_bricks_after_expansion -
                               num_of_bricks_before_expansion)

        self.assertEqual(
            num_of_bricks_added, 3,
            "Number of bricks added is not 3 for %s" % volume_id)

        self.get_rebalance_status(volume_name)

        deletion_info = heketi_ops.heketi_volume_delete(
            self.heketi_client_node, self.heketi_server_url,
            volume_id, json=True)

        self.assertNotEqual(deletion_info, False,
                            "Deletion of volume %s failed" % volume_id)

        free_space_after_deletion = self.get_devices_summary_free_space()

        self.assertTrue(
            free_space_after_deletion > free_space_after_expansion,
            "Free space is not reclaimed after volume deletion of %s"
            % volume_id)
