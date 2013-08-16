# Storage Management Providers
#
# Copyright (c) 2013, Red Hat, Inc. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are
# those of the authors and should not be interpreted as representing official
# policies, either expressed or implied, of the FreeBSD Project.
#
# Authors: Jan Safranek <jsafrane@redhat.com>
#
"""
Basic device information.

Usage:
    %(cmd)s list [<devices>]...
    %(cmd)s show [<devices>]...
    %(cmd)s depends [ --deep ] [<devices>]...
    %(cmd)s provides [ --deep ] [<devices>]...
    %(cmd)s tree [<device>]

Commands:
    list        List short information about given device. If no devices
                are given, all devices are listed.

    show        Show detailed information about given devices. If no devices
                are provided, all of them are displayed.

    provides    Show devices, which are created from given devices
                (= show children of the devices).

                For example, if disk is provided, all partitions on it are
                returned. If 'deep' is used, all RAIDs, Volume Groups and
                Logical Volumes indirectly allocated from it are returned too.

    depends     Show devices, which are required by given devices to operate
                correctly (= show parents of the devices).

                For example, if a Logical Volume is provided, its Volume Group
                is returned. If 'deep' is used, also all Physical Volumes and
                disk are returned.

    tree        Show tree of devices, similar to lsblk.
                (Note that the output is really crude and needs to be worked
                on).

                If no device is provided, all devices are shown, starting
                with physical disks.

                If a device is provided, tree starts with the device
                and all dependent devices are shown.
"""

from lmi.scripts.common import command
from lmi.scripts.storage import show, fs
from lmi.scripts.storage.common import str2device, size2str, get_devices, \
        get_children, get_parents
from lmi.scripts.storage.lvm import get_vgs
from lmi.shell.LMIUtil import lmi_isinstance

def get_device_info(ns, device):
    return (device.DeviceID,
            device.Name,
            device.ElementName,
            size2str(device.NumberOfBlocks * device.BlockSize),
            fs.get_device_format_label(ns, device))

def get_pool_info(ns, pool):
    return (pool.InstanceID,
            pool.ElementName,
            size2str(pool.TotalManagedSpace),
            "volume group (LVM)")

def get_obj_info(ns, obj):
    if lmi_isinstance(obj, ns.CIM_StorageExtent):
        return get_device_info(ns, obj)
    else:
        return get_pool_info(ns, obj)

def get_obj_id(ns, obj):
    if lmi_isinstance(obj, ns.CIM_StorageExtent):
        return obj.DeviceID
    else:
        return obj.InstanceID

def list(ns, devices=None):
    devices = get_devices(ns, devices)
    for dev in devices:
        yield get_device_info(ns, dev)

def cmd_show(ns, devices=None):
    if not devices:
        devices = get_devices(ns)
    for dev in devices:
        show.device_show(ns, dev)
        print ""
    return 0

def cmd_tree(ns, device=None):
    # Note, this is high-speed version of the device tree.
    # Walking through associations using get_children() functions
    # was kind of slow, even for small number of devices (~5).

    # devices = dict id -> LMIInstance
    devices = {}
    # Load *all* CIM_StorageExtents to speed things up, calling get_children
    # iteratively is slow
    for dev in get_devices(ns):
        devices[get_obj_id(ns, dev)] = dev
    # Add *all* LMI_VGStoragePools
    for vg in get_vgs(ns):
        devices[get_obj_id(ns, vg)] = vg

    # deps = array of tuples (parent id, child id)
    # Load all dependencies, calling get_children iteratively is slow
    # Add CIM_BasedOn dependencies
    # (and omit LMI_LVBasedOn, we need LMI_LVAllocatedFromStoragePool instead)
    deps = [ (get_obj_id(ns, i.Antecedent), get_obj_id(ns, i.Dependent))
                    for i in ns.CIM_BasedOn.instances()
                        if not lmi_isinstance(i, ns.LMI_LVBasedOn)]

    # Add VG-LV dependencies from LMI_LVAllocatedFromStoragePool association
    deps += [ (get_obj_id(ns, i.Antecedent), get_obj_id(ns, i.Dependent))
                    for i in ns.LMI_LVAllocatedFromStoragePool.instances()]

    # Add PV-VG dependencies from LMI_VGAssociatedComponentExtent association
    deps += [ (get_obj_id(ns, i.PartComponent), get_obj_id(ns, i.GroupComponent))
                    for i in ns.LMI_VGAssociatedComponentExtent.instances()]

    # queue = array of tuples (id, level), queue of items to inspect and display
    queue = []
    if device:
        queue = [(get_obj_id(ns, device), 0), ]
    else:
        for (id, device) in devices.iteritems():
            if device.Primordial:
                queue.append((id, 0))
    shown = set()

    while queue:
        (id, level) = queue.pop()

        device = devices[id]
        info = get_obj_info(ns, device)
        if id in shown:
            info = ("*** " + info[0],)
        yield (level,) + info
        # don't show children of already displayed elements
        if id in shown:
            continue

        shown.add(id)
        children = [ dep[1] for dep in deps if dep[0] == id ]
        for child in reversed(children):
            queue.append((child, level + 1))



def cmd_depends(ns, devices=None, __deep=None):
    for device in devices:
        # TODO: do a better output
        print "%s:" % (device,)
        for parent in  get_parents(ns, device, __deep):
            yield get_obj_info(ns, parent)

def cmd_provides(ns, devices=None, __deep=None):
    for device in devices:
        # TODO: do a better output
        print "%s:" % (device,)
        for child in  get_children(ns, device, __deep):
            yield get_obj_info(ns, child)

class Lister(command.LmiLister):
    CALLABLE = 'lmi.scripts.storage.device_cmd:list'
    COLUMNS = ('DeviceID', "Name", "ElementName", "Size", "Format")

class Show(command.LmiCheckResult):
    CALLABLE = 'lmi.scripts.storage.device_cmd:cmd_show'
    EXPECT = 0

class Depends(command.LmiLister):
    CALLABLE = 'lmi.scripts.storage.device_cmd:cmd_depends'
    COLUMNS = ('DeviceID', "Name", "ElementName", "Size", "Format")

class Provides(command.LmiLister):
    CALLABLE = 'lmi.scripts.storage.device_cmd:cmd_provides'
    COLUMNS = ('DeviceID', "Name", "ElementName", "Size", "Format")

class Tree(command.LmiLister):
    CALLABLE = 'lmi.scripts.storage.device_cmd:cmd_tree'
    COLUMNS = ('Level', 'DeviceID', "Name", "ElementName", "Size", "Format")

Device = command.register_subcommands(
        'device', __doc__,
        { 'list'    : Lister,
          'show'    : Show,
          'tree'    : Tree,
          'provides': Provides,
          'depends' : Depends,
        },
    )
