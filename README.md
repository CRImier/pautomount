##pautomount
==========

###Linux automount daemon written in Python.

####What it does? 

Automatically performs an action when a storage device is attached to Linux PC running the daemon. 
Most common action is mounting this storage device, however, it can also call an external command or script.

####How to install?

Download all the files and run "setup.sh". Ideally, it should put all the files where they belong. Then, edit "/etc/pautomount.conf", changing "exceptions" as described below, then removing a "noexecute" option from the "globals" section.

Daemon is configured by changing entries in /etc/pautomount.conf file, a JSON file. It typically consists of four sections:

####1) "exceptions" section.
 There you'd certainly like to put UUIDs of the partitions that are mounted on boot with fstab. Otherwise, daemon will try to mount them on boot, too =)

Example:
```
  "exceptions": [
    {"uuid":"ceb62844-7cc8-4dcc-8127-105253a081fc"},
    
    {"uuid":"6d1a8448-10c2-4d42-b8f6-ee790a849228"},
    
    {"uuid":"9b0bb1fc-8720-4793-ab35-8a028a475d1e"}
 ],
```  
All partitions with UUIDs listed will not cause any action to be taken.

####2) "rules" section.
 Every entry there corresponds to a specific partition with a specific UUID ("uuid" key), but... You can also use labels ("label" key), potentially using one rule on a multiple partition with the same label. Additionally, you can use a regex which is checked using re.match ("label_regex" key)

Every entry, subsequently, can have one or more actions.

- "mount" action - causes partition to be mounted, and allows for some additional options controlling everything.

- "command" action - causes pautomount to call an external command. 

- "script" action - causes pautomount to call a custom script with arguments .

Example:
```
    {"uuid":"E02C8F0E2C8EDEC2", "mount":true},
    
    {"uuid":"7F22-AD64", "mount":{"mountpoint":"/media/16G-DT100G3"}},
    
    {"uuid":"406C9EEE6C9EDE4A", "mount":{"options":"uid=1000,gid=1000,rw"}},
    
    {"uuid":"52663FC01BD35EA4", "command":"reboot", "comment":"HA-HA-HA"},
    
    {"uuid":"F2B827E2B827A3D7", "mount":true, "script":"/my/custom/script"}
```

####3) "default" section. 
Is triggered where nothing else works. Usually consists of simple:
```
"mount":true 
```
Every drive not in "exceptions" or "rules" goes through this section. "uuid"/"label"/"label_regex" option in the "default" section is ignored, since it's not logical ;-) It can haz all the same action("mount"/"command"/"script") options as "rules", though.

####4) "globals" section. 
Every variable there is exported to the daemon's global namespace. Useful variables are:

- main_mount_dir - Main directory for mounting. Will be used only where directory for mounting is generated or directory path is relative. Has to be an absolute path. I recommend "/media", this is the default.

- default_mount_option - Default mounting options. I recommend "rw", even though I'm not sure - it might be a default in actual "mount" command for most filesystem types. You can also add something about "uid" and "gid" there, to allow ordinary user read-write access to the folders.

- logfile - Path to logfile. Has to be absolute, otherwise I do not respond for where your logs might land =)

- interval - Integer, which represents number of seconds between each pautomount cycle. If pautomount somehow happens to load the CPU - just lower that. Even though - this has hardly ever been a problem for me on my single-core 900MHz ;-)

Miscellaneous globals:

- debug - this option's name speaks for itself. Makes logging more verbose - and makes logs grow faster. You'll hardly need that.

- super_debug - this option makes logging even more verbose. You'll hardly need that, too.

- noexecute - option that disables calling external commands pautomount relies on for mounting and other stuff you tell it to do. It is enabled in config and has to be there until pautomount is configured properly, so that no unwanted mounts appear =)

- label_char_filter - turns on partition label filtering.

By default, if partition has label and its UUID is not in rule list, it's mounted by "/media/$LABEL" (or whatever your main_mount_dir is)
Partition labels, however, can contain any kind of Unicode symbols that are not necessarily correctly displayed by consoles
So - there's label filtering, which leaves only ASCII letters in label
By default it's set to True

----------------------------------------------------
More about actions:

"mount" action: uses "mount" external command. You currently can either set is as true (meaning that drive has to be mounted) or false (meaning that the drive shouldn't be mounted), or set it as a dictionary of additional options - in this case, "true" is assumed. 
You can also set mount as list - for example, 
    "mount":[{"mountpoint":"/media/ExternalDisk"}, {"mountpoint":"/media/SecondLocation"}]
Please keep in mind that multiple mounts of the same block device are not supported by, for example, NTFS drivers.

Additional options might be:

"options" - Options for "mount" command, used like "-o $OPTIONS". Hint - you can put spaces in it and imitate some more 
"mountpoint" - Fixed mountpoint for "mount" command. I like using this option - it's really convenient =)

I might add support of more options later if requested.


"command" action just runs a command as it is. For example, entry:

    "command":"rm -rf /" 

will run "rm -rf /"

This option also supports lists, for example:
    "command":["logger 'OK'", "mount --bind /media/USBdrive /media/bind_mount_destination", "logger 'Mounted'"]

"script" action - causes pautomount to call a custom script. Script is called like "/path/to/script DEVICE_PATH UUID MOUNTPOINT LABEL". If LABEL or MOUNTPOINT do not exist (partition not mounted or has no label), "None" is used instead. 
So, possible script calls are:

    /path/to/script /dev/sda1 U1U2-I3D4 /media/4GB-Flash Flashdrive

or

    /path/to/script /dev/sda1 U1U2-I3D4 None None

This also supports lists, just like two options above

Minimal system requirements:

Python 2.7 - will try to lower this requirement after a while

Non-standard modules used - none 

External commands required - "mount". 

....

4MB of RAM or higher

SVGA-compatible video card 

Windows 98 OSR2 or higher

Mouse, 101-key keyboard

AC97-compatible soundcard, speakers

... just kidding ;-)


Tips for debugging:

To read logs as they are created, use "tail -f /var/log/pautomount.log". Also, don't forget to set "debug" in /etc/pautomount.conf ! 

There's a Python thread created for each attached partition. This is to prevent pautomount freezes when there's a stubborn partition that doesn't want to be mounted automatically. But that means log messages are not necessarily in the correct order - series of log messages about different partitions can overlap and mix together.


Known bugs to be fixed and features that have to be added:

No automatic parsing of "/etc/fstab" to determine which drives should be listed as exceptions, user has to do it manually by now.

No support of "mount --bind", even though I'm not sure that's needed since it doesn't really fit in the design and can easily be added via "script" option.
