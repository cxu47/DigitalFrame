# DigitalFrame Goals
- Create a client linux application that does the following:
- connects to given server to read picture files;
- update local picture files to del / download new files;
- periodically check server for updates;
- show picture slides as a digital picture frame;
- runs on a rasberry pi / banana pi with a display

# Potential Upgrades
- regulate file name "no space etc."
- random shuffle function
- create option for encryptions
- add collage options
- security protocal
- overwride policies
- check stored pics at reboot
- diy server url
- diy pic elapse time

# Progress
- [x] created server and client structure  
- [x] created docker file  
- [x] created photo upload function  

# Current Features (important notes)
- No duplicate detection. New photo if dup name, will replace older photo
