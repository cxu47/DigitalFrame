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
### phase 1 - fast api local
- [x] created server and client structure  
- [x] created docker file  
- [x] created photo upload function
- [x] created temp download extension before completion 
- [x] created loop checking cache folder
- [x] created loop checking server to update cache folder in the background
 
### phase 2 - google drive cloud server 
- [x] download cred and tokens
- [x] check listing
- [] convert iphone image formats

### phase 3 - alibaba OSS cloud server
- [] check long term token and expiration date

# Current Features (important notes)
- No duplicate detection. New photo if dup name, will replace older photo
- currently no remove photo function on server -- only way to update cache from app is to download. Need to test on deleting photos if slideshow updates. currently only checks manually delete from cache folder, works fine.
