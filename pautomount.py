#!/usr/bin/env python

import time #For sleeping
import datetime #For logging timestamps
import os #For reading contents of directories, symlinks and similar
import json #For parsing the config file
import subprocess #For calling external programs, such as "mount"
import signal #For reloading daemon
import re #For "label-regex" option handling
import sys #For stdout and stderr redirection
import threading #For parallel partition processing
from copy import deepcopy #For fixing a bug with copying
import shlex #For fstab/mtab/whatever parsing

import pyrtitions

__version__ = "1.0.0"

config_file = "/etc/pautomount.conf"
#Some globals
config = {}
previous_partitions = []
processed_partitions = []
#These variables are those that affect the work of the daemon. They have default values now,
#but those are overridden by values in the config file.
main_mount_dir = "/media/" #Main directory for relative mountpoints in config and generating mountpoints
default_mount_option  = "rw" #Option that is used if drive hasn't got any special options
logfile = "/var/log/pautomount.log"
debug = False #Makes output more verbose
super_debug = False #MORE VERBOSE!
interval = 3 #Interval between work cycles in seconds
noexecute = False #Forbids executing things, logs command to be executed instead
label_char_filter = True #Filters every disk label for every non-ascii character

def log(data):
    """Writes data into a logfile adding a timestamp """
    f = open(logfile, "a")
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    f.write(timestamp+"    "+str(data)+"\n")
    f.close()

def export_globals():
    log("Exporting globals from config file")
    for variable in config["globals"].keys():
        if debug:
            log("Exporting variable "+variable+" from config")
        globals()[variable] = config["globals"][variable]

def normalize_config(config):
    #finished
    """Check config file's structure and contents for everything that can make the daemon fail, spits out warnings about inconsistent entries and deletes them from the daemon's dictionary"""
    #Should there be some problems with the logfile, log to the /var/log/daemon.log
    #Well, an empty file with curly braces should do. But Python has its own way of handling a try to get a value from a dict by a non-existent key.
    #Precisely, it returns an exception, and to catch this, we need to wrap in try:except many blocks.
    #I think that the most efficient way is adding the basic keys (config, exceptions, rules and default section) if they don't exist in the actual dictionary.
    #Checking everything else is already handled by all the other functions.
    categories = {"globals":{}, "exceptions":[], "rules":[], "default":{}}
    for category in categories.keys():
        if category not in config.keys():
            config[category] = categories[category]
    #Now check if logfile exists. If it doesn't, we have to create it.
    try:
        logfile_var = config["globals"]["logfile"]
    except KeyError:
        logfile_var = "/var/log/pautomount.log"
    if not os.path.exists(logfile_var):
        try:
            os.touch(logfile_var)
        except:
            logger("Logfile creation in path "+logfile_var+" not permitted. Falling back to default.")
            logfile_var = "/var/log/daemon.log"
    config["globals"]["logfile"] = logfile_var
    #OK. We have a logfile that should work. I suppose we can just redirect stderr and let all
    #the uncaught exception output appear there.
    #Checks will be added to this function in case lack of check can mean something dreadful.
    return config

def log_to_stdout(message):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(timestamp+"    "+str(message))

def compare(arr1, arr2):
    """Compares two arrays - arr1 and arr2. Returns tuple (items that lack from arr2, items that lack from arr1)"""
    attached, detached = [item for item in arr1 if item not in arr2], [item for item in arr2 if item not in arr1]
    return attached, detached

def execute(*args):
    """Comfortable subprocess wrapper to call external programs"""
    if debug:
        log("Executing: "+str(args))
    if noexecute:
        log("'noexecute' turned on, not doing anything, arguments:")
        log(str(args))
        result = [0, ""] #Totally faking it
    else:
        try:
            output = subprocess.check_output(args, stderr=subprocess.STDOUT, shell=True)
            result = [0, output]
        except subprocess.CalledProcessError as e:
            result = [int(e.returncode), e.output]
        if debug:
            log("Exit code: "+str(result[0])+", output: "+result[1])
    return result

def add_processed_partition_entry(part_info, rule):
    #This function adds data to processed_partitions dictionary
    #Useful mainly on ejects for getting knowledge which directory to `umount`
    global processed_partitions
    part_info = deepcopy(part_info) #Who knows, maybe this is exactly a place for a bug I've fought with before
    if "umount" in rule.keys(): #Saving umount action for later
        part_info["umount"] = rule["umount"]
    else:
        part_info["umount"] = None
    processed_partitions.append(part_info)

def remove_processed_partition_entry(part_info):
    #When partition gets ejected, we also need to remove any signs of its existence from processed_partitions
    global processed_partitions
    for entry in deepcopy(processed_partitions):
        if entry["uuid"] == part_info["uuid"]: #Checking by uuid because it's 100% working
            processed_partitions.remove(entry)

def filter_virtual_devices(current_entries):
    virtual_devices = pyrtitions.get_virtual_devices()
    return [entry for entry in current_entries if os.path.basename(entry["path"]) not in virtual_devices]

def mark_mounted_partitions(current_entries):
    mounted_partitions = pyrtitions.get_mounts()
    mounted_devices = list(mounted_partitions.keys())
    for entry in current_entries:
         if entry["path"] in mounted_devices:
             entry["mounted"] = True
         else:
             entry["mounted"] = False
    return current_entries

def read_config():
    try:
        log("Opening config file - "+config_file)
        f = open(config_file, 'r')
        d = json.load(f)
        f.close()
    except (IOError, ValueError) as e:
        #if the config file doesn't exist - there's no need in running this daemon.
        log("Exception while opening config file")
        log(str(e))
        sys.exit(1)
    return d

def complies_to_rule(partition, rule):
    """Check if the partition parameters comply to the rule given"""
    #This function exists because we can have many different conditions when partition parameters apply to the rule
    #First one is when UUIDs match
    if "uuid" in rule.keys() and partition["uuid"] == rule["uuid"]:
        if debug:
            log("Partition complies to UUID rule")
        return True
    #Latter two only apply if partition has a label
    elif "label" in partition.keys():
    #Second is when there's some label in the rule and it matches to the label of the partition
        if "label" in rule.keys() and partition["label"] == rule["label"]:
            if debug:
                log("Partition complies to label rule")
            return True
        #Third is when the rule has option "label-regex"
        #That means we take this regex, compile it and check
        elif "label_regex" in rule.keys():
            pattern = re.compile(rule["label_regex"])
            if pattern.match(partition["label"]):
                if debug:
                    log("Partition complies to label_regex rule")
                return True
            else:
                return False
        else: #No more options to check
            return False
    else:
        return False

def mount_wrapper(partition, mount_rule):
    """Wrapper around mount(), takes care of "mount lists" function"""
    #Could be possibly made as a decorator...
    if type(mount_rule) != list:
        mount_rule = [mount_rule]
    else:
        log("Received mount list with "+len(mount_rule)+"elements")
    mountpoint = None
    for rule in mount_rule:
        result = mount(partition, rule)
        if not mountpoint and result: #Mountpoint is not set, result of mount() is not negative
            #First mountpoint which is used is to be returned by mount_wrapper() as a mountpoint
            mountpoint = result
    return mountpoint

def mount(partition, mount_rule):
    """Mount function, wrapper around execute()"""
    if not mount_rule:
        return None #Don't need to react at all
    #log(mount_rule.keys())
    if type(mount_rule) != dict or "mountpoint" not in mount_rule.keys():
        mountpoint = pyrtitions.generate_mountpoint(partition)
    else:
        mountpoint = mount_rule["mountpoint"]
        mountpoint = return_absolute_mountpoint(mountpoint)
    if type(mount_rule) != dict or "options" not in mount_rule.keys():
        options = default_mount_option
    else:
        options = mount_rule["options"]
    try:
        ensure_path_exists(mountpoint)
    except:
        log("Directory creation failed, path: "+mountpoint)
        raise Exception #Path creation failed - throw exception...
        #TODO - change exception type
    #Now kiss!^W^W^W^W execute!
    log("Trying to mount partition "+partition["uuid"]+"  on path "+mountpoint)
    command = "mount "+partition["path"]+" "+mountpoint+" -o "+options
    output = execute(command)
    if output[0] != 0:
        log("Mount failed. Exit status: "+str(output[0]))
        log("Output: "+output[1])
        return None
    else:
        log("Partition "+partition["uuid"]+" successfully mounted")
        return mountpoint

def execute_script_wrapper(script_path, part_info=None):
    #script_path might as well be list, so we need to make a workaround here
    if type(script_path) != list:
        script_path = list([script_path])
    for script in script_path:
        execute_custom_script(script, part_info=part_info)

def execute_custom_script(script_path, part_info=None):
    """Function to execute arbitrary script - main function is to arrange arguments in a correct order"""
    #First of all, there are two ways to call this function.
    #If you don't supply part_info, it just calls some command without options
    #If you supply part_info, it calls that command giving info about partition as arguments
    #Second occasion is handy for custom scripts
    #Okay, we have some arguments and options
    #Arguments are partition's block device path and uuid
    #Options are... Mountpoint and label, for example.  Can't think of many now.
    if part_info:
        device = part_info["path"]
        uuid = part_info["uuid"]
        if "mountpoint" in part_info.keys():
            mountpoint = part_info["mountpoint"] #Might need to be escaped as may contain spaces and so on
        else:
            mountpoint = "None"
        uuid = part_info["uuid"]
        if "label" in part_info.keys():
            label = part_info["label"] #Might need to be escaped as well
        else:
            label = "None"
        #Script will be called like '/path/to/script /dev/sda1 U1U2-I3D4 /media/4GB-Flash Flashdrive'
        command = script_path+" "+device+" "+uuid+" "+mountpoint+" "+label
    else:
        command = script_path
    log("Calling external script: "+command)
    output = execute(command)
    if output[0] != 0:
        log("Calling external script failed. Exit status: "+str(output[0]))
        log("Output: "+output[1])
    else:
        log("Calling external script succeeded.")

def return_absolute_mountpoint(path):
    """We can specify both relative and absolute path in config file. This function adds main_mount_dir to all relative paths."""
    if os.path.isabs(path):
        path = path
    else:
        path = os.path.join(main_mount_dir, path)
    return path

def ensure_path_exists(path):
    if not os.path.isdir(path):
        log("Mountpoint does not seem to exist. Quickly fixing this...")
        os.makedirs(path)
    return True

def main_loop():
    global previous_partitions
    current_partitions = pyrtitions.get_uuids_and_labels()
    current_partitions = filter_virtual_devices(current_partitions)
    attached, detached = compare(current_partitions, previous_partitions)
    attached = deepcopy(attached) #Fixing a bug with compare() when modifying elements in attached() led to previous_partitions being modified
    detached = deepcopy(detached) #Preventing a bug in the future
    #We need to copy "current_partitions" into "previous_partitions" now
    #If current_partition is modified, it may lead to attempt to reattach partition in the next step
    previous_partitions = current_partitions
    if attached:
        log("Found "+str(len(attached))+" attached partition(s)")
        if debug:
            log(str(attached))
    if detached:
        log("Found "+str(len(detached))+" detached partition(s)")
        if debug:
            log(str(detached))
    #Start processing every attached drive
    attached = mark_mounted_partitions(attached)
    for partition in attached:
        if partition["mounted"]: #This is for ignoring partitions that have been mounted when daemon starts but aren't in processed_partition dictionary - such as root partition and other partitions in fstab
            log("Partition already mounted, not doing anything")
            continue
        t = threading.Thread(target = process_attached_partition, args = tuple([partition])) #tuple([]) is a fix for a problem with *args that is totally ununderstandable for me and I don't even want to dig through this shit. It doesn't accept a tuple, but accepts tuple(list). So - this fix isn't dirty, just quick =)
        t.daemon = True
        t.start()
    for partition in detached:
        t = threading.Thread(target = process_detached_partition, args = tuple([partition])) #tuple([]) is a fix for a problem with *args that is totally ununderstandable for me and I don't even want to dig through this shit. It doesn't accept a tuple, but accepts tuple(list). So - this fix isn't dirty, just quick =)
        t.daemon = True
        t.start()
        pass
    if super_debug:
        log(str(current_partitions))
    if debug:
        log("Sleeping...")
    pass

def process_attached_partition(*args, **kwargs):
    partition = args[0]
    log("Processing attached drive with UUID "+partition["uuid"])
    action_taken = False
    for exception in config["exceptions"]:
        if complies_to_rule(partition, exception):
            #Well, we don't need to do anything
            #Other than
            action_taken = True
            if debug:
                log("Partition complies to exception rule: "+str(exception))
            else:
                log("Partition "+partition["uuid"]+" complies to exception rule.")
            break
    for rule in config["rules"]:
        if complies_to_rule(partition, rule) and action_taken == False:
            partition["mountpoint"] = None
            if "mount" in rule.keys() and rule["mount"]:
                partition["mountpoint"] = mount_wrapper(partition, rule["mount"])
            if "command" in rule.keys() and rule["command"]:
                execute_script_wrapper(rule["command"])
            if "script" in rule.keys() and rule["script"]:
                execute_script_wrapper(rule["script"], part_info=partition)
            add_processed_partition_entry(partition, rule)
            action_taken = True
            if debug:
                log("Partition complies to rule: "+str(rule))
            else:
                log("Partition "+partition["uuid"]+" complies to rule.")
    if action_taken == False:
        #And now for the defaults
        log("No rule that suits this partition, taking actions set by default.")
        default = config["default"]
        partition["mountpoint"] = None
        if "mount" in default.keys() and default["mount"]:
            partition["mountpoint"] = mount_wrapper(partition, default["mount"])
        if "command" in default.keys() and default["command"]:
            execute_script_wrapper(default["command"])
        if "script" in default.keys() and default["script"]:
            execute_script_wrapper(default["script"], part_info=partition)
        add_processed_partition_entry(partition, default)
    #That seems it, by this time action is already taken/exception is made.
    return #No need in return value.

def process_detached_partition(*args, **kwargs):
    part_info = args[0]
    log("Processing detached drive with UUID "+part_info["uuid"])
    for partition in processed_partitions:
         if partition["uuid"] == part_info["uuid"]:
             if "umount"in partition.keys() and partition["umount"]:
                 #The same command list support, just executing all the commands one by one
                 execute_script_wrapper(partition["umount"])
             if "mountpoint" in partition.keys() and partition["mountpoint"]:
                 #Unmounting the mountpoint where device was mounted - just in case
                 exit_status = 0
                 while exit_status != 0:
                     exit_status = execute("umount "+partition["mountpoint"]+"")[0]
         else:
             continue
    remove_processed_partition_entry(part_info)

def set_output():
    """This function looks for a certain command-line option presence and sets stdout and stderr accordingly."""
    global log
    option = "-e"
    if option in [element.strip(" ") for element in sys.argv]:
       #Flag for debugging to make pautomount output stderr to console
       log = log_to_stdout #Reassigns logging function
    else:
       f = open(logfile, "a")
       sys.stderr = f
       sys.stdout = f

def load_config():
    global config
    config = read_config()
    config = normalize_config(config)
    export_globals()
    log("Config loaded and parsed successfully")

def reload(signum, frame):
    #Is just a wrapper for load_config
    #Just in case we will need more sophisticated signal processing
    log("Reloading on external signal")
    load_config()

def main():
    signal.signal(signal.SIGHUP, reload) #Makes daemon reloading possible
    set_output() #Decides where to output logging messages
    load_config() #Manages config - loads it, cleans it up and exports globals
    if super_debug:
        debug = True
    while True:
        main_loop() #Starts daemon
        time.sleep(interval)

if __name__ == "__main__":
    main()
