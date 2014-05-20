#!/usr/bin/env python
import time #For sleeping
import datetime #For logging timestamps
import os #For reading contents of directories, symlinks and similar
import json #For parsing the config file
import subprocess #For calling external programs, such as "mount"
import signal #For reloading daemon 
import re #For "label-regex" option handling
import sys #For stdout and stderr redirection

config_file = "/etc/pautomount.conf"
#Some globals
config = {}
previous_partitions = []
#These variables are those that affect the work of the daemon. They have default values now,
#but those are overridden by values in the config file.
main_mount_dir = "/media/" #Main directory for relative mountpoints in config and generating mountpoints
default_mount_option  = "rw" #Option that is used if drive hasn't got any special options
logfile = "/var/log/pautomount.log" 
debug = False #Makes output more verbose
super_debug = False #MORE VERBOSE!
interval = 3 #Interval between work cycles in seconds
noexecute = False #Forbids executing things, logs command to be executed instead

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
    #Everything else is already handled by all the other functions.
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

def scan_partitions():
    partitions = []
    labels = {}
    dbu_dir = "/dev/disk/by-uuid/"
    dbl_dir = "/dev/disk/by-label/"
    try:
        parts_by_label = os.listdir(dbl_dir)
    except OSError:
        parts_by_label = [] 
    parts_by_uuid = os.listdir(dbu_dir)
    for label in parts_by_label:
        #Getting the place where symlink points to - that's the needed "/dev/sd**"
        path = os.path.realpath(os.path.join(dbl_dir, label)) 
        labels[path] = label
        #Makes dict like {"/dev/sda1":"label1", "/dev/sdc1":"label2"}
    for uuid in parts_by_uuid:
        path = os.path.realpath(os.path.join(dbu_dir, uuid))
        details_dict = {"uuid":uuid, "path":path}
        if path in labels.keys():
            details_dict["label"] = labels[path]
        partitions.append(details_dict)
        #partitions is now something like 
        #[{"uuid":"5OUU1DMUCHUNIQUEW0W", "path":"/dev/sda1"}, {"label":"label1", "uuid":"MANYLETTER5SUCH1ONGWOW", "path":"/dev/sdc1"}]
    if debug:
        log("Partitions scanned. Current number of partitions: "+str(len(partitions)))
    return partitions

def log_to_stdout(message):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print timestamp+"    "+str(message) 
    
def compare(arr1, arr2):
    """Compares two arrays - arr1 and arr2. Returns tuple (items that lack from arr2, items that lack from arr1)"""
    attached, detached = [item for item in arr1 if item not in arr2], [item for item in arr2 if item not in arr1]
    #Dirty bugfix - my misunderstanding of Python mutable and immutable structures doesn't allow me to fix the actual problem.
    for apartition in attached[:]:
        for dpartition in detached[:]:
            if dpartition["uuid"] == apartition["uuid"]:
                attached.remove(apartition)
                detached.remove(dpartition)
    return attached, detached

def execute_background(argument):
    """This function is used for running external scripts and commands, making them as a background job."""
    #The problem is that we don't know how much time it will take for an external script to run. 
    #If we wait for the exit code and output as we do in execute(), daemon will freeze until the job is done.
    pass

def execute(*args):
    """Comfortable subprocess wrapper to call external programs"""
    if debug:
        log("Executing: "+str(args))
    if noexecute: 
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
        log("Partition complies to UUID rule")
        return True
    #Latter two only apply if partition has a label
    elif "label" in partition.keys():
    #Second is when there's some label in the rule and it matches to the label of the partition
        if "label" in rule.keys() and partition["label"] == rule["label"]:
            log("Partition complies to label rule")
            return True
        #Third is when the rule has option "label-regex" 
        #That means we take this regex, compile it and check
        elif "label_regex" in rule.keys():
            pattern = re.compile(rule["label_regex"])
            if pattern.match(partition["label"]):
                log("Partition complies to label_regex rule")
                return True
            else:
                return False
        else: #No more options to check
            return False
    else:
        return False
	
def mount(partition, rule):
    """Mount function, wrapper around execute()"""
    #rule["mount"] is true - we wouldn't have gotten here if it wasn't.
    #Now we need to see if the rule["mount"] is a dictionary or a list, or just a boolean True.
    #In the second case, there are many things for us to do. 
    #Have to somehow unify these three cases... Hmm.
    #TODO - finish this change and finally unify this. 
    if type(rule["mount"]) == dict:
        rule["mount"] = rule["mount"] #Nothing to be changed yet, but after I'll be wrapping everything in lists
    elif type(rule["mount"]) == bool:
        rule["mount"] = {"mount":True}
    # Lists as config options to mount are not supported yet but support is to be added.
    #This would require some refactoring, though. 
    #I guess I'll have to add another functiion caring for lists.
    """elif type(rule["mount"]) == list:
        for mount_rule in rule["mount"]:
            if type(mount_rule[""]) == bool:
               if type["rule"] - to be continued"""
    #Main task for now is parsing partition dictionary and guessing mount path and options
    if "mountpoint" not in rule["mount"].keys():
        mountpoint = generate_mountpoint(partition)
    else:
        mountpoint = rule["mount"]["mountpoint"]
        mountpoint = return_absolute_mountpoint(mountpoint)
    if "options" not in rule.keys() and rule["mount"]:
        options = default_mount_option
    else:     
        options = rule["options"]
    try:
        ensure_path_exists(mountpoint)
    except:
        log("Directory creation failed, path: "+mountpoint)
        raise Exception #Path creation failed - throw exception
    #Now kiss!^W^W^W^W execute!
    log("Trying to mount partition "+partition["path"]+" on path "+mountpoint)
    command = "mount "+partition["path"]+" "+mountpoint+" -o "+options
    output = execute(command)
    if output[0] != 0:
        log("Mount failed. Exit status: "+str(output[0]))
        log("Output: "+output[1])
        return None
    else:
        log("Partition successfully mounted")
        return mountpoint

def execute_custom_script(script_path, part_info=None): #TODO
    """Function to execute arbitrary script - main function is to arrange arguments in a correct order"""
    #First of all, there are two ways to call this function.
    #If you don't supply part_info, it just calls some command without options
    #If you supply part_info, it calls that command giving info about partition as arguments 
    #Second occasion is handy for custom scripts
    #Okay, we have some arguments and options
    #Arguments are partition's block device path and uuid
    #Options are... Mountpoint and label, for example.  Can't think of many now. 
    
    #TODO: Find a way to run the said script in background.
    if part_info:
        device = part_info["path"]
        uuid = part_info["uuid"]
        if "mountpoint" in part_info.keys():
            mountpoint = part_info["mountpoint"]
        else:
            mountpoint = "None"
        uuid = part_info["uuid"]
        if "label" in part_info.keys():
            label = part_info["label"]
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

def generate_mountpoint(part_info):
    """Generates a valid mountpoint path for automatic mount if not specified in config or it's default action"""
    #We could use either label (easier and prettier)
    #Or UUID (not pretty yet always available)
    path_from_uuid = os.path.join(main_mount_dir, part_info['uuid'])
    #We can tell that the directory we want to choose as mountpoint is OK if:
    #1) It doesn't exist, or:
    #2) Nothing is mounted there and it's empty.
    if "label" in part_info.keys():
        path_from_label = os.path.join(main_mount_dir, part_info['label'])
        if not os.path.exists(path_from_label) or (not os.path.ismount(path_from_label) and not os.listdir(path_from_label)):
            log("Choosing path from label")
            return path_from_label 
    elif not os.path.exists(path_from_uuid) or (not os.path.ismount(path_from_uuid) and not os.listdir(path_from_uuid)):
        log("Choosing path from UUID")
        return path_from_uuid
    #But there could be another partition with the same UUID!
    #CAN'T HANDLE THAT
    #Seriously, is that even possible?
    #Okay, I've seen some flash drives that have really short UUIDs
    #So collision could be possible. Anyway, shit happens. Let's add a solution just in case: 
    else:
        counter = 1
        while os.path.exists(path_from_uuid+"_("+str(counter)+")"):
            counter += 1
        return path_from_uuid+"_("+str(counter)+")"

def main_loop():
    global previous_partitions
    current_partitions = scan_partitions()
    attached, unplugged = compare(current_partitions, previous_partitions)
    previous_partitions = current_partitions
    if attached:
        log("Found "+str(len(attached))+" attached partition(s)")
        if debug:
            log(str(attached))
    if unplugged:
        log("Found "+str(len(unplugged))+" detached partition(s)")
        if debug:
            log(str(unplugged))
    #We need to copy "current_partitions" into "previous_partitions" now
    #If current_partition is modified, it may lead to attempt to reattach partition in the next step
    #Start processing every attached drive
    for partition in attached:
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
                    log("Partition complies to exception rule.")
                break
        for rule in config["rules"]:
            if complies_to_rule(partition, rule) and action_taken == False:
                #That should be the time to do what it says to!
                mountpoint = None
                if "mount" in rule.keys() and rule["mount"]:
                    partition["mountpoint"] = mount(partition, rule)
                if "command" in rule.keys() and rule["command"]:
                    execute_custom_script(rule["command"])
                if "script" in rule.keys() and rule["script"]:
                    execute_custom_script(rule["script"], part_info=partition)
                action_taken = True
                if debug:
                    log("Partition complies to rule: "+str(exception))
                else:
                    log("Partition complies to rule.")
        if action_taken == False:
            #And now for the defaults
            log("No rule that suits this partition, taking actions set by default.")
            default = config["default"]
            if "mount" in default.keys() and default["mount"]:
                partition["mountpoint"] = mount(partition, default)
            if "command" in default.keys() and default["command"]:
                execute_custom_script(default["command"])
            if "script" in default.keys() and default["script"]:
                execute_custom_script(default["script"], part_info=partition)
        #That seems it, by this time action is already taken/exception is made.
    if super_debug:
        log(str(current_partitions))
    #Partition detach event handling not done yet, needs to be planned better
    if debug:
        log("Sleeping")
    pass

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

if __name__ == "__main__":
    signal.signal(signal.SIGHUP, reload) #Makes daemon reloading possible
    set_output() #Decides where to output logging messages 
    load_config() #Manages config - loads it, cleans it up and exports globals
    if super_debug:
        debug = True
    while True:
        main_loop() #Starts daemon
        time.sleep(interval)

