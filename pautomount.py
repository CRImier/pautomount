#!/usr/bin/env python

logfile = "/var/log/pautomount.log" 

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

import logging 
level = logging.DEBUG #Log level
if "-e" in [element.strip(" ") for element in sys.argv]: #Option to output logs to console
    logging.basicConfig(level=level)
else:
    logging.basicConfig(filename=logfile,level=level)

scanner = None #Two global variables for singleton objects
mounter = None 


class Mounter():
    """

    """

    noexecute = False #Forbids executing things, logs command to be executed instead
    main_mount_dir = "/media/" #Main directory for relative mountpoints in config and generating mountpoints
    default_mount_option  = "rw" #Option that is used if drive hasn't got any special options
    threading = True #TODO

    def process_attached_partition(*args, **kwargs):

    def process_detached_partition(*args, **kwargs):

    def mount_rule_parser(self, partition, mount_rule):
        """Wrapper around mount(), enables 'mount list' function. Returns all the mountpoints of successful mount() calls. """
        if type(mount_rule) != list:
            mount_rule = [mount_rule] #We'll iterate anyway, so wrapping a single rule in a list
        else:
            logging.debug("Received mount list with "+len(mount_rule)+"elements")
        mountpoints = []
        for rule in mount_rule:
            result = mount(partition, rule)
            if result: 
                mountpoints.add(result)
        return mountpoints

    def mount(self, partition, mount_rule):
        """Mount function, wrapper around execute(). Reads the rule mount options and composes the command accordingly"""
        #1. Checking options
        if not mount_rule: #False disables mounting
            return None
        if type(mount_rule) != dict: #Must be 'mount':True
            mount_rule = {} 
        #Checking for defined mountpoint
        if "mountpoint" in mount_rule.keys():
            mountpoint = mount_rule["mountpoint"]
            mountpoint = return_absolute_mountpoint(mountpoint)
        else:
            mountpoint = self.generate_mountpoint(partition)
        #Checking for mount options
        if "options" in mount_rule.keys(): 
            options = mount_rule["options"]
        else:
            options = self.default_mount_option
        try: #If path is not there, we need to create it.
            self.ensure_path_exists(mountpoint)
        except:
            logging.warning("Directory creation failed, path: "+mountpoint)
            logging.warning("Mount aborted.")
        #2. Composing and executing command
        logging.info("Trying to mount partition "+partition["uuid"]+"  on path "+mountpoint)
        command = "mount "+partition["path"]+" "+mountpoint+" -o "+options #TODO: options might not be provided at all
        output = execute(command)
        #TODO: Add UUIDs because in case of parallel mounts all the output is getting mixed up
        if output[0] != 0:
            logging.warning("Mount failed. Exit status: "+str(output[0])) 
            logging.warning("Output: "+output[1])
            return None
        else:
            logging.info("Partition "+partition["uuid"]+" successfully mounted")
            return mountpoint

    def complies_to_rule(self, partition, rule):
        """Check if the partition parameters comply to the rule given"""
        #1. Partition and rule UUIDs match
        if "uuid" in rule.keys() and partition["uuid"] == rule["uuid"]:
            logging.debug("Partition complies to UUID rule")
            return True
        #2. Partition has a label
        elif "label" in partition.keys():
            #2.1 Rule has a label and it matches to the label of the partition
            if "label" in rule.keys() and partition["label"] == rule["label"]:
                logging.debug("Partition complies to label rule")
                return True
            #2.2 Rule has an option "label-regex" and the regex provided matches the label
            elif "label_regex" in rule.keys():
                pattern = re.compile(rule["label_regex"])
                if pattern.match(partition["label"]):
                    logging.debug("Partition complies to label_regex rule")
                    return True
        #None options worked, partition doesn't match to rule
        return False

    def script_rule_parses(self, script_path, part_info=None):
        """Wrapper around execute_custom_script(), enables 'script list' function."""
        if type(script_paths) != list:
            script_paths = list([script_paths])
        for script in script_paths:
            self.execute_custom_script(script, part_info=part_info)

    def execute_custom_script(self, command, part_info=None):
        """Function to execute arbitrary script - also gives arguments about partition if part_info is given"""
        #If part_info is not supplied, it just calls the given command without options
        #If part_info is supplied, it calls the given command with partition information as arguments 
        if part_info:
            #We have some arguments and options in partition information
            #Arguments are block device path and uuid
            #Options are mountpoint and label
            device = part_info["path"]
            uuid = part_info["uuid"]
            if "mountpoint" in part_info.keys(): #TODO: multiple mountpoints
                mountpoint = part_info["mountpoint"] #TODO: May contain traces of dangerous characters
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
        logging.info("Calling external script: "+command)
        output = execute(command)
        if output[0] != 0:
            logging.warning("Calling external script failed. Exit status: "+str(output[0]))
            logging.warning("Output: "+output[1])
        else:
            logging.info("Calling external script succeeded.")

    def return_absolute_mountpoint(self, path):
        """"This function adds main_mount_dir in case the supplied path is relative."""
        if not os.path.isabs(path): 
            path = os.path.join(self.main_mount_dir, path)
        return path

    def ensure_path_exists(self, path):
        if not os.path.isdir(path): 
            logging.info("Mountpoint does not exist. Quickly fixing this...")
            os.makedirs(path)
        return True

    def generate_mountpoint(self, part_info):
        """Generates a valid mountpoint path for automatic mount if not specified in config or it's default action"""
        def path_good_for_mounting(path):
            """A helper function to determine if directory would be suitable as a mountpoint"""
            #The directory we want to choose as mountpoint is suitable if:
            #1) It doesn't exist, or:
            #2) Nothing is mounted there and it's empty.
            if not path: return False 
            return not os.path.exists(path) or (not os.path.ismount(path) and not os.listdir(path))

        #Mountpoint can be generated from 1) label 2) UUID (in order of precedence)
        if "label" in part_info.keys():
            path_from_label = os.path.join(self.main_mount_dir, part_info['label'])
        else:
            path_from_label = None #Avoiding a branching bug 
        path_from_uuid = os.path.join(self.main_mount_dir, part_info['uuid'])

        if path_good_for_mounting(path_from_label):
            log("Choosing path from label")
            return path_from_label 
        elif path_good_for_mounting(path_from_uuid):
            log("Choosing path from UUID")
            return path_from_uuid
        #UUID collision possible with non-proper ejectcloned drives, making a counter that is appended to the mountpoint end
        else: #Iterating through all the folders
            logging.warning("Possible UUID collision found (most probably device wasn't unmounted before ejection)")
            counter = 1
            new_uuid_path = os.path.join(self.main_mount_dir, part_info['uuid']+"_(1)")
            while not path_good_for_mounting(new_uuid_path):
                counter += 1
                new_uuid_path = os.path.join(self.main_mount_dir, part_info['uuid']+"_("+str(counter)+")")
            return new_uuid_path

    def execute(self, *args):
        """Comfortable subprocess wrapper to call external programs
        Returns list [exit_status, stdout+stderr]"""
        #Currently hides all the exceptions from user. Don't know if that's a good thing, will rethink it later.
        logging.debug("Executing: "+str(args))
        if not self.noexecute: #Noexecute parameter turns off any system interaction, allowing testing on a non-root account
            try:
                output = subprocess.check_output(args, stderr=subprocess.STDOUT, shell=True)
                result = [0, output]
            except subprocess.CalledProcessError as e:
                result = [int(e.returncode), e.output]
            logging.debug("Exit code: "+str(result[0])+", output: "+result[1])
        else:
            logging.warning("'noexecute' turned on, not doing anything, attempted command:")
            logging.warning(str(args))
            result = [0, ""] #Returning some results so that a function that called execute() doesn't get embarassed
        return result


class PollingScanner():

    #Storage objects
    previous_partitions = []
    processed_partitions = []

    #Configuration variables
    interval = 3 #Interval between work cycles in seconds
    label_char_filter = True #Filters every disk label for every non-ascii character
    by_uuid_dir = "/dev/disk/by-uuid/"
    by_label_dir = "/dev/disk/by-label/"


    def scan_partitions(self):
        partitions = []
        labels = {}

        #1. Getting available labels
        try:
            partitions_by_label = os.listdir(self.by_label_dir)
        except OSError: #Directory most probably empty
            partitions_by_label = [] #No labels available

        for label in parts_by_label:
            #Every entry in /dev/disk/by-label is a symlink pointing to a block device
            path = os.path.realpath(os.path.join(dbl_dir, label)) 
            label = self.label_filter(label) #Necessary because of Unicode symbols in labels and such
            if label: #Checking because there might be nothing left after label_filter =)
                labels[path] = label_filter(label)

        # Finished getting labels.
        #labels ~= {"/dev/sda1":"label1", "/dev/sdc1":"label2"}
        logging.debug(str(labels))

        #2. Getting UUIDs and corresponding block devices
        partitions_by_uuid = os.listdir(self.by_uuid_dir) #Directory seems to be never empty

        for uuid in parts_by_uuid:
            #Every entry in /dev/disk/by-uuid is a symlink pointing to a block device
            path = os.path.realpath(os.path.join(dbu_dir, uuid)) 
            details_dict = {"uuid":uuid, "path":path}
            if path in labels.keys():
                details_dict["label"] = labels[path]
            partitions.append(details_dict)

        #Finished getting partition list
        #partitions ~= [{"uuid":"5OUU1DMUCHUNIQUEW0W", "path":"/dev/sda1"}, {"label":"label1", "uuid":"MANYLETTER5SUCH1ONGWOW", "path":"/dev/sdc1"}]
        logging.debug("Partitions scanned. Current number of partitions: "+str(len(partitions)))
        logging.debug(partitions)

        return partitions

    def label_filter(self, label):
        arr_label = [char for char in label] #Most elegant way to turn a string into an list of chars... Or not?
        ascii_letters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ '
        dangerous_chars = ["&", ";", "|", "/", "$"]
        for char in dangerous_chars: #Filters characters possible in UUIDs (okay, maybe not of them) that can cause malfunction when called as an argument of an external script in shell mode
            while char in arr_label[:]:
                arr_label.remove(char)
        if self.label_char_filter: #Filters non-ASCII characters by default, can be changed in configuration
            for char in arr_label[:]:
                if char not in ascii_letters:
                    arr_label.remove(char)
        #Now need to check if label is good enough to be considered a proper disk label =)
        if not arr_label or len(label)/len(arr_label) <= 2: #Label after filtering is empty or more than half of label is lost after filtering
            label = None
        else:
            label = "".join(arr_label)
        return label

    def compare(self, arr1, arr2):
        """Compares two list - arr1 and arr2. Returns tuple ([items that lack from arr2], [items that lack from arr1])"""
        attached, detached = [item for item in arr1 if item not in arr2], [item for item in arr2 if item not in arr1]
        return attached, detached

    def add_processed_partition_entry(self, part_info, rule):
        """This function adds data to processed_partitions list, which is used to avoid mounting partitions more than one time.
        Can also be used when action is needed on drive eject"""
        part_info = deepcopy(part_info) #Avoiding a bug
        if "umount" in rule.keys(): #Saving 'umount' action contents in partition entry - maybe it'd be better to get it from config? TODO
            part_info["umount"] = rule["umount"]
        else:
            part_info["umount"] = None
        processed_partitions.append(part_info)    

    def remove_processed_partition_entry(self, part_info):
        """When partition gets ejected, we also need to remove any signs of its existence from processed_partitions"""
        global processed_partitions
        for entry in deepcopy(processed_partitions): #Avoiding a bug once again
            if entry["uuid"] == part_info["uuid"]: #Checking by uuid because it always works
                processed_partitions.remove["entry"]

    def mark_mounted_partitions(self):
        #Good source of information about mounted partitions is /etc/mtab
        mounted_partitions = []
        filename = "/etc/mtab" 

        f = open(filename, "r")
        lines = f.readlines()
        f.close()
        for line in lines:
            line = line.strip().strip("\n")
            if line:
                elements = shlex.split(line) #Smart line splitting - ignores spaces in quotes
                if len(elements) != 6: #Typical mtab line consists of 6 elements
                    break
                path = elements[0] 
                #/etc/mtab is full of entries that aren't mounted block devices we would be interested in.
                if path.startswith("/dev"): #This might also grab things like /dev/pts, but it should not be an issue. TODO why
                    #Close enough to be disk device. It's either /dev/sd** or a symlink to that. 
                    dev_path = os.path.realpath(path) #If it's a symlink, it will be resolved by realpath().
                    mounted_partitions.append(dev_path)
        #TODO - where is that dict?
        for entry in self.current_entries:
            if entry["path"] in mounted_partitions:
                entry["mounted"] = True
            else:
                entry["mounted"] = False

    def main_loop(): #TODO
        global previous_partitions
        current_partitions = scan_partitions()
        attached, detached = compare(current_partitions, previous_partitions)
        attached = deepcopy(attached) #Fixing a bug with compare() when modifying elements in attached() led to previous_partitions being modified
        detached = deepcopy(detached) #Ditto
        #We need to copy "current_partitions" into "previous_partitions" now
        #If current_partition is modified, it may lead to attempt to reattach partition in the next step
        previous_partitions = current_partitions
        if attached:
            logging.info("Found "+str(len(attached))+" attached partition(s)")
            logging.debug(str(attached))
        if detached:
            logging.info("Found "+str(len(detached))+" detached partition(s)")
            logging.debug(str(detached))
        #Start processing every attached drive
        attached = mark_mounted_partitions(attached) #Sets a flag on all the partitions that are already mounted
        for partition in attached: 
            if partition["mounted"]: #This is for ignoring partitions that have been mounted when daemon starts but aren't in processed_partition dictionary - such as root partition and other partitions in fstab
                logging.info("Partition already mounted, not doing anything")
                continue
            t = threading.Thread(target = process_attached_partition, args = tuple([partition])) #tuple([]) is a fix for a problem with *args that is totally ununderstandable for me and I don't even want to dig through this shit. It doesn't accept a tuple, but accepts tuple(list). So - this fix isn't dirty, just quick =)
            t.daemon = True
            t.start()
        for partition in detached:
            t = threading.Thread(target = process_detached_partition, args = tuple([partition])) #tuple([]) is a fix for a problem with *args that is totally ununderstandable for me and I don't even want to dig through this shit. It doesn't accept a tuple, but accepts tuple(list). So - this fix isn't dirty, just quick =)
            t.daemon = True
            t.start()
        logging.debug("Sleeping...")
        

class ConfigManager():

    #Storage objects
    config = {}

    #Configuration variables
    config_file = "/etc/pautomount.conf"

    def export_globals(self, key):
        #TODO: exporting config entries to different modules
        logging.info("Exporting globals from config file")
        """for variable in config["globals"].keys():
            logging.debug("Exporting variable "+variable+" from config")
            globals()[variable] = config["globals"][variable]"""

    def normalize_config(self):
        """Check config file's structure and contents for everything that can make the daemon fail.
        In future, warns about inconsistent entries and deletes them from the daemon's dictionary"""
        #An empty file with curly braces should do. But Python gets angry when we use a non-existent key with the dict.
        #Precisely, it returns an exception, and to catch this, we need to wrap in try:except many blocks.
        #I think that the most efficient way is adding the basic keys (config, exceptions, rules and default section) if they don't exist in the actual dictionary. 
        #Checking everything has to be handled by all the other functions.
        categories = {"globals":{}, "exceptions":[], "rules":[], "default":{}}
        for category in categories.keys():  
            if category not in self.config.keys():
                self.config[category] = categories[category]
                logging.info("Config category "+category+"not found, assumed empty")
        #Checks have to be added to this function in case lack of check can mean something dreadful.

    def read_config(self):
        try:
            logging.info("Opening config file - "+self.config_file)
            f = open(self.config_file, 'r')
            self.config = json.load(f)
            f.close()
        except (IOError, ValueError) as e:
            #if the config file doesn't exist, there's no need in running this daemon
            logging.critical("Exception while opening config file")
            logging.critical(str(e))
            sys.exit(1)

    def load_config(self):
        self.config = read_config()
        self.normalize_config(config)
        #self.export_globals()
        logging.info("Config loaded and parsed successfully")

    def reload(self, signum, frame):
        #Is just a wrapper for load_config 
        #Just in case we will need more sophisticated signal processing 
        logging.warning("Reloading on external signal")
        self.load_config()

if __name__ == "__main__":
    config_manager = ConfigManager()
    signal.signal(signal.SIGHUP, config_manager.reload) #Makes daemon reloading possible
    config_manager.load_config()

    scanner = PollingScanner(scanner_config)
    scanner.load_config(config)    
    mounter = Mounter(mounter_config)
    #TODO: insert selections for different scanner types
    while True:
        scanner.main_loop() #Starts daemon
        time.sleep(interval)

#==============HERE BE DRAGONS===============


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
                 while exit_status == 0:
                     exit_status = execute("umount "+partition["mountpoint"]+"")[0]
         else:
             continue
    remove_processed_partition_entry(part_info)

def load_config()
