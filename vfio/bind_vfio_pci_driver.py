#!/usr/bin/python

__author__ = "Max Gurtovoy"
__version__ = '1.0'


import optparse
import sys
if sys.version_info[0] >= 3:
     unicode = str
import os
try:
    import commands
except ImportError:
    import subprocess as commands
import datetime
import time
import platform

KERNEL_MODULES = "/lib/modules/"
MODULES = "/sys/module/"
ALIAS_FILE = "modules.alias"
DEVICES = "/sys/devices/"
DRIVERS = "/sys/bus/pci/drivers/"
DRIVER_OVERRIDE_ALIAS_PREFIX = "vfio_pci:"
PCI_ALIAS_PREFIX = "pci:"

def print_and_log(line):
    line = ("%s: %s" % (datetime.datetime.now(), line))
    print(line)

def load(module, params=None):
    cmd = "modprobe " + module
    if params:
        cmd = " ".join([cmd, params])

    rc, out = commands.getstatusoutput(cmd)
    if rc:
        print_and_log(out)
    else:
        time.sleep(2)
    return rc

def write_helper(destfile, string):
    expected_rc = 0
    rc = destfile.write(string)
    if sys.version_info[0] >= 3:
        expected_rc = len(string)
    elif sys.version_info[0] == 2:
        expected_rc = None
    if rc != expected_rc:
        return 1
    return 0

def find_device_dirname(device):
    for root,d_names,f_names in os.walk(DEVICES):
        for f in f_names:
            if f == "driver_override":
                if device in os.path.join(root, f):
                    return os.path.dirname(os.path.join(root, f))

    return None

def find_orig_driver(dirname):
    for f in os.listdir(dirname):
        if f == "driver":
            return os.path.join(dirname, f)
    return None

def unbind_device(orig_driver, device):
    if not os.path.islink(orig_driver):
        return 1

    for f in os.listdir(orig_driver):
        if f == "unbind":
            with open(os.path.join(orig_driver, f), "w") as unbind:
                rc = write_helper(unbind, device)
                if rc:
                    return 1
                else:
                    return 0
    return 1

def is_device_bounded(driver, device):
    return os.path.exists(os.path.join(DRIVERS, driver, driver))

def bind_device_to_driver_override(driver, device, path):
    with open(os.path.join(path, "driver_override"), "w") as override:
        rc = write_helper(override, driver)
        if rc:
            return 1

    #wait for binding driver to device
    time.sleep(2)
    if is_device_bounded(driver, device):
        return 0

    with open(os.path.join(DRIVERS, driver, "bind"), "w") as bind:
        rc = write_helper(bind, device)
        if rc:
            return 1

    return 0

def is_driver_override_alias(alias):
    if alias.split()[1].startswith(DRIVER_OVERRIDE_ALIAS_PREFIX):
        return True
    return False

def split_alias(alias):
    if "driver_override" in alias:
        orig = alias.split(DRIVER_OVERRIDE_ALIAS_PREFIX)[1].split()[0]
    else:
        orig = alias.split(PCI_ALIAS_PREFIX)[1].split()[0]
    v = orig.split("d")[0].split("v")[-1]
    d = orig.split("sv")[0].split("d")[-1]
    sv = orig.split("sd")[0].split("sv")[-1]
    sd = orig.split("bc")[0].split("sd")[-1]
    bc = orig.split("sc")[0].split("bc")[-1]
    sc = orig.split("i")[0].split("sc")[-1]
    i = orig.split("i")[1]

    return v, d, sv, sd, bc, sc, i

def get_modalias(dirname):
    with open(os.path.join(dirname, "modalias"), "r") as f:
        return f.readlines()[0]

def is_alias_match(alias, dirname):
    v, d, sv, sd, bc, sc, i = split_alias(alias)

    modalias = get_modalias(dirname)
    real_v, real_d, real_sv, real_sd, real_bc, real_sc, real_i = split_alias(modalias)

    if not (v == "*" or real_v == v):
        return False

    if not (d == "*" or real_d == d):
        return False

    if not (sv == "*" or real_sv == sv):
        return False

    if not (sd == "*" or real_sd == sd):
        return False

    if not (bc == "*" or real_bc == sd):
        return False

    if not (sc == "*" or real_sc == sc):
        return False

    if not (i == "*" or real_i == i):
        return False

    return True

def find_driver_override_name(module_name):
    for root, directories, files in os.walk(os.path.join(MODULES, module_name, "drivers")):
        for directory in directories:
            if "pci:" in directory:
                return directory.split(":")[-1]
    return None

def match_score(alias, dirname):
    score = 0
    v, d, sv, sd, bc, sc, i = split_alias(alias)

    modalias = get_modalias(dirname)
    real_v, real_d, real_sv, real_sd, real_bc, real_sc, real_i = split_alias(modalias)

    if real_v != v and v == "*":
        score += 1

    if real_d != d and d == "*":
        score += 1

    if real_sv != sv and sv == "*":
        score += 1

    if real_sd != sd and sd == "*":
        score += 1

    if real_bc != sd and bc == "*":
        score += 1

    if real_sc != sc and sc == "*":
        score += 1

    if real_i != i and i == "*":
        score += 1

    return score

def find_driver_override(dirname):
    potential_modules = {}
    alias_f = os.path.join(KERNEL_MODULES, platform.release(), ALIAS_FILE)
    if alias_f:
        with open(alias_f, "r") as f:
            aliases = f.readlines()
            for alias in aliases:
                if is_driver_override_alias(alias) and is_alias_match(alias, dirname):
                    module_name = alias.split()[-1]
                    potential_modules[module_name] = match_score(alias, dirname)

    module = None
    min_value = -1
    for key, value in potential_modules.items():
        print_and_log("module %s with score %d" % (key, value))
        if min_value == -1 or min_value > value:
            min_value = value
            module = key

    print_and_log("chosen module is %s with score %d" % (module, min_value))
    return module

def main():

    parser = optparse.OptionParser()
    parser.add_option('-d', '--device',
                      help="Device to bind",
                      default=None,
                      dest="device")

    (opts, args) = parser.parse_args()

    rc = 0
    if args:
        print_and_log('error: invalid input,  check -h or --help')
        sys.exit(1)

    if not opts.device:
        print_and_log("Device is missing")
        sys.exit(1)

    dirname = find_device_dirname(opts.device)
    if not dirname:
        print_and_log("Can't find dirname for device %s" % opts.device)
        sys.exit(1)

    print_and_log("dirname for device %s is %s" % (opts.device, dirname))

    orig_driver = find_orig_driver(dirname)
    if orig_driver:
        print_and_log('orig driver is %s' % os.path.basename(os.readlink(orig_driver)))
        rc = unbind_device(orig_driver, opts.device)
        if rc:
            print_and_log('error: failed to unbind device %s from %s' % (opts.device, orig_driver))
            sys.exit(1)

    driver_override = find_driver_override(dirname)
    if not driver_override:
        print_and_log("Can't find driver to override for device %s" % opts.device)
        sys.exit(1)

    rc = load(driver_override)
    if rc:
        print_and_log("can't load driver %s" % driver_override)
        sys.exit(1)

    driver_override_name = find_driver_override_name(driver_override)
    if not driver_override_name:
        print_and_log("Can't find driver override name for %s" % driver_override)
        sys.exit(1)

    rc = bind_device_to_driver_override(driver_override_name, opts.device, dirname)
    if rc:
        print_and_log('error: failed to bind device %s to %s' % (opts.device, driver_override))
        sys.exit(1)

    print_and_log('Bind script finished with rc %s driver_override is %s' % (rc, driver_override_name))
    sys.exit(rc)


if __name__ == "__main__":
    main()
